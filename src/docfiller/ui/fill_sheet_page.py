"""Fill a sheet page — fill a spreadsheet from the program.

Instead of opening the spreadsheet and hunting for each field cell by cell, the
fields the program finds are filled in a form, and the file comes back with
its structure EXACTLY preserved. The saved file can then be loaded as the data
source on the Documents page.

Fields are taken from the file itself (sheet_fill.extract_fields), grouped by
sheet, filtered with the search box, and every input remembers earlier values.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import diagnostics, engine, paths, sheet_fill
from ..i18n import tr
from . import dialogs, theme
from .widgets import MemoryInput, Worker, heading, hint


def _memory_key(label: str) -> str:
    """Field-memory key for a caption: lower case, letters and digits only."""
    return "sheet." + re.sub(r"[^0-9a-z]+", "_", label.casefold()).strip("_")[:60]


class FillSheetPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.source: Path | None = None
        self.fields: list[sheet_fill.Field] = []
        self._inputs: dict[str, MemoryInput] = {}
        self._rows: list[tuple[str, QWidget]] = []  # (searchable text, row)
        self._worker = None
        self._build()

    # ============================================================== layout

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.layout_ = QVBoxLayout(content)
        self.layout_.setContentsMargins(20, 16, 20, 20)
        self.layout_.setSpacing(14)
        self.layout_.addWidget(self._section_file())
        self.layout_.addWidget(self._section_fields())
        self.layout_.addWidget(self._section_save())
        self.layout_.addStretch()

    def _section_file(self) -> QGroupBox:
        box = QGroupBox(tr("1  ·  SPREADSHEET TO FILL"))
        column = QVBoxLayout(box)
        column.setSpacing(8)
        column.addWidget(hint(tr(
            "Choose your spreadsheet. The program finds the fillable fields itself; you only "
            "type the values. When you save, the file's structure, formatting, formulas and "
            "tables are kept EXACTLY as they were."
        )))
        row = QHBoxLayout()
        row.setSpacing(8)
        choose = QPushButton(tr("Choose spreadsheet…"))
        choose.setCursor(Qt.PointingHandCursor)
        choose.clicked.connect(diagnostics.guard(self.choose_file))
        row.addWidget(choose)
        self.file_label = heading(tr("No file chosen"), 9, False, theme.COLOURS["text_muted"])
        self.file_label.setWordWrap(True)
        row.addWidget(self.file_label, 1)
        column.addLayout(row)
        return box

    def _section_fields(self) -> QGroupBox:
        box = QGroupBox(tr("2  ·  FIELDS"))
        column = QVBoxLayout(box)
        column.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search fields… (for example: name, date, number)"))
        self.search.textChanged.connect(diagnostics.guard(self._filter))
        top.addWidget(self.search, 1)
        self.count_label = heading("", 8.5, False, theme.COLOURS["text_muted"])
        top.addWidget(self.count_label)
        column.addLayout(top)
        self.fields_area = QVBoxLayout()
        self.fields_area.setSpacing(4)
        column.addLayout(self.fields_area)
        self.empty_label = heading(tr("Choose a spreadsheet first."), 9, False, theme.COLOURS["text_muted"])
        column.addWidget(self.empty_label)
        return box

    def _section_save(self) -> QGroupBox:
        box = QGroupBox(tr("3  ·  SAVE"))
        column = QVBoxLayout(box)
        column.setSpacing(8)
        column.addWidget(hint(tr("Your source file is not changed; a filled COPY is created.")))
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.preview_button = QPushButton(tr("Preview (PDF)"))
        self.preview_button.setMinimumHeight(40)
        self.preview_button.setEnabled(False)
        self.preview_button.setCursor(Qt.PointingHandCursor)
        self.preview_button.setToolTip(tr("Shows the file as you filled it, as a PDF; nothing is saved anywhere."))
        self.preview_button.clicked.connect(diagnostics.guard(self.preview))
        buttons.addWidget(self.preview_button)
        self.save_button = QPushButton(tr("Save the filled spreadsheet"))
        self.save_button.setObjectName("primary")
        self.save_button.setMinimumHeight(40)
        self.save_button.setEnabled(False)
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.clicked.connect(diagnostics.guard(self.save))
        buttons.addWidget(self.save_button)
        self.use_button = QPushButton(tr("Save and use on the Documents page"))
        self.use_button.setEnabled(False)
        self.use_button.setMinimumHeight(40)
        self.use_button.setCursor(Qt.PointingHandCursor)
        self.use_button.clicked.connect(diagnostics.guard(lambda: self.save(use_in_documents=True)))
        buttons.addWidget(self.use_button)
        buttons.addStretch()
        column.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        column.addWidget(self.progress)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.hide()
        column.addWidget(self.result_label)
        return box

    # ================================================================ file

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Spreadsheet to fill"), "", f"{tr('Spreadsheets')} (*.xlsx *.xlsm *.xls)"
        )
        if path:
            self.load(path)

    def load(self, path: str | Path):
        path = Path(path)
        try:
            found, sheets = sheet_fill.extract_fields(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("The file could not be read"), str(exc))
            return
        self.source = path
        self.fields = found
        self.file_label.setText(
            tr("<b>{name}</b> · {sheets} sheet(s) · {fields} fillable field(s)").format(
                name=path.name, sheets=len(sheets), fields=len(found)
            )
        )
        self.file_label.setStyleSheet(f"color: {theme.COLOURS['text']};")
        self._draw_fields()
        self.save_button.setEnabled(bool(found))
        self.use_button.setEnabled(bool(found))
        self.preview_button.setEnabled(bool(found))

    # ============================================================== fields

    def _clear_fields(self):
        while self.fields_area.count():
            item = self.fields_area.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self._inputs.clear()
        self._rows.clear()

    def _draw_fields(self):
        self._clear_fields()
        last_sheet = None
        for field in self.fields:
            if field.sheet != last_sheet:
                last_sheet = field.sheet
                title = QLabel(tr("Sheet: {name}").format(name=field.sheet))
                title.setObjectName("sectionHeading")
                title.setWordWrap(True)
                self.fields_area.addWidget(title)
                self._rows.append(("", title))
            self.fields_area.addWidget(self._field_row(field))
        self.empty_label.setVisible(not self.fields)
        if not self.fields:
            self.empty_label.setText(tr(
                "No fillable field was found in this file. You can still load it on the "
                "Documents page and fill the documents by hand."
            ))
        self._update_count()

    def _field_row(self, field: sheet_fill.Field) -> QWidget:
        c = theme.COLOURS
        frame = QFrame()
        frame.setStyleSheet(f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 6px; }}")
        line = QHBoxLayout(frame)
        line.setContentsMargins(10, 6, 10, 6)
        line.setSpacing(10)
        label = heading(field.label, 9, False)
        label.setWordWrap(True)
        label.setMinimumWidth(280)
        label.setMaximumWidth(420)
        line.addWidget(label)
        address = QLabel(field.address)
        address.setStyleSheet(theme.badge("neutral"))
        address.setToolTip(tr("Cell {address} on sheet {sheet}").format(address=field.address, sheet=field.sheet))
        line.addWidget(address)
        box = MemoryInput(_memory_key(field.label))
        box.setText(field.text)
        box.setPlaceholderText(tr("empty — type to fill it"))
        line.addWidget(box, 1)
        self._inputs[field.key] = box
        self._rows.append((f"{field.label} {field.address} {field.sheet}".casefold(), frame))
        return frame

    def _filter(self, text: str):
        needle = (text or "").strip().casefold()
        visible = 0
        for searchable, row in self._rows:
            if not searchable:  # a sheet heading
                row.setVisible(not needle)
                continue
            match = not needle or needle in searchable
            row.setVisible(match)
            visible += 1 if match else 0
        self._update_count(visible if needle else None)

    def _update_count(self, visible: int | None = None):
        if not self.fields:
            self.count_label.setText("")
        elif visible is None:
            self.count_label.setText(tr("{count} fields").format(count=len(self.fields)))
        else:
            self.count_label.setText(tr("{visible} / {count} fields").format(visible=visible, count=len(self.fields)))

    # =============================================================== saving

    def _changes(self) -> dict:
        changes = {}
        for field in self.fields:
            box = self._inputs.get(field.key)
            if box is None:
                continue
            new = box.text().strip()
            if new != field.text.strip():
                changes[field.key] = sheet_fill.as_cell_value(new)
        return changes

    def save(self, use_in_documents: bool = False):
        if self.source is None:
            return
        changes = self._changes()
        if not changes:
            QMessageBox.information(self, tr("No changes"), tr("You have not changed any field."))
            return
        suggested = str(self.source.with_name(f"{self.source.stem} - filled{self.source.suffix}"))
        target, _ = QFileDialog.getSaveFileName(
            self, tr("Save the filled spreadsheet"), suggested, f"Excel (*{self.source.suffix})"
        )
        if not target:
            return
        problem = paths.path_length_problem(str(Path(target).parent))
        if problem:
            QMessageBox.warning(self, tr("Folder path is very long"), problem)
            return
        source = self.source
        self._busy(True)

        def work(_is_cancelled):
            return sheet_fill.save_copy(source, target, changes)

        def finished(result):
            self._busy(False)
            self._worker = None
            if isinstance(result, Exception):
                self._result(tr("It could not be saved: {error}").format(error=result), "error")
                return
            self._result(tr("{count} field(s) written → {file}").format(count=len(changes), file=result), "success")
            if use_in_documents:
                self.main_window.use_in_documents(result)

        self._worker = self.main_window.documents_page.jobs.start(Worker(work), finished)

    def preview(self):
        """Write the filled state to a temporary copy and show it as a PDF.

        Nothing is written to the output folder or to the source file; the
        temporary copy is cleared when the program starts next time.
        """
        if self.source is None:
            return
        source = self.source
        changes = self._changes()
        temporary = Path(tempfile.mkdtemp(prefix="sheet-preview-", dir=paths.preview_root())) / source.name
        self._busy(True)

        def work(_is_cancelled):
            if changes:
                sheet_fill.save_copy(source, temporary, changes)
                target = temporary
            else:
                target = source  # nothing changed: show the file itself
            return engine.source_to_pdf(target)

        def finished(result):
            self._busy(False)
            self._worker = None
            if isinstance(result, Exception):
                self._result(tr("The preview could not be made: {error}").format(error=result), "error")
                return
            self._result(tr(
                "Preview ready ({count} change(s)). If it is right, press 'Save the filled spreadsheet'."
            ).format(count=len(changes)), "success")
            dialogs.PreviewDialog(self.main_window, result).exec()

        self._worker = self.main_window.documents_page.jobs.start(Worker(work), finished)

    def _busy(self, running: bool):
        self.progress.setVisible(running)
        self.save_button.setEnabled(not running)
        self.use_button.setEnabled(not running)
        self.preview_button.setEnabled(not running)

    def _result(self, text: str, kind: str):
        self.result_label.setText(text)
        self.result_label.setStyleSheet(theme.banner(kind))
        self.result_label.show()

    # ---------------------------------------------------------------- state

    def state(self) -> dict:
        return {"source": str(self.source) if self.source else None,
                "values": {k: b.text() for k, b in self._inputs.items()}}

    def restore(self, state: dict) -> None:
        if state.get("source") and Path(state["source"]).exists():
            self.load(state["source"])
            for key, text in (state.get("values") or {}).items():
                box = self._inputs.get(key)
                if box is not None:
                    box.setText(text)

    def open_folder(self, path: Path):
        if path.parent.is_dir():
            os.startfile(str(path.parent))  # noqa: S606
