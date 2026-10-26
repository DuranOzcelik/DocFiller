"""Quick document page — a few documents, filled by hand.

Why a separate page: many jobs need just one or two short documents. A source
file CAN be loaded — then its values fill the fields — but it is not required:
every field can be typed, and every value from a file can be changed.

Preview, cancel, production and the output layout use the SAME engine as the
Documents page; only the way details are entered is simpler.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import (
    accounts,
    diagnostics,
    document_sets,
    engine,
    fields,
    formatting,
    history,
    library,
    memory,
    paths,
    settings,
    templates,
)
from ..i18n import tr
from ..project import AUTOMATIC_FIELDS, Project
from . import dialogs, theme
from .documents_page import show_source
from .widgets import MemoryInput, Worker, duration_text, heading, hint, is_running


def _empty_project() -> Project:
    account = accounts.active()
    return Project(profile=dict(account.profile_values) if account else {})


class QuickPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.project = _empty_project()
        self.loaded_files: list[str] = []
        self.analyses = []
        self.output_folder: str | None = None
        self.preview = None
        self._worker = None
        self.jobs = main_window.documents_page.jobs if hasattr(main_window, "documents_page") else None
        self.templates = templates.discover(settings.template_folder())
        self.boxes: dict[str, QCheckBox] = {}
        self.inputs: dict[str, MemoryInput] = {}
        self._open_previews: dict[str, dialogs.PreviewDialog] = {}
        self._refresh_pending = False
        self._quiet = False
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(700)
        self._live_timer.timeout.connect(diagnostics.guard(self._auto_refresh))

        self._build()
        self._fill_documents()
        self._rebuild_fields()

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
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(self._section_source())
        layout.addWidget(self._section_documents())
        layout.addWidget(self._section_fields())
        layout.addWidget(self._section_output())
        layout.addWidget(self._section_result())
        layout.addStretch()

    def _section_source(self) -> QGroupBox:
        box = QGroupBox(tr("1  ·  SOURCE (OPTIONAL)"))
        column = QVBoxLayout(box)
        column.setSpacing(8)
        column.addWidget(hint(tr(
            "Load a file and the fields fill themselves. You can also fill them without one — "
            "every field below can be typed."
        )))
        row = QHBoxLayout()
        row.setSpacing(8)
        choose = QPushButton(tr("Choose file…"))
        choose.clicked.connect(diagnostics.guard(self.choose_source))
        self.content_button = QPushButton(tr("View content"))
        self.content_button.setEnabled(False)
        self.content_button.setToolTip(tr("Shows which value was read into which field."))
        self.content_button.clicked.connect(diagnostics.guard(self._view_source))
        self.drop_button = QPushButton(tr("Drop the source"))
        self.drop_button.setEnabled(False)
        self.drop_button.clicked.connect(diagnostics.guard(self.drop_source))
        row.addWidget(choose)
        row.addWidget(self.content_button)
        row.addWidget(self.drop_button)
        row.addStretch()
        column.addLayout(row)
        self.source_info = heading(tr("No source loaded — the fields start empty."), 9, False)
        self.source_info.setWordWrap(True)
        column.addWidget(self.source_info)
        return box

    def _section_documents(self) -> QGroupBox:
        box = QGroupBox(tr("2  ·  DOCUMENTS TO PRODUCE"))
        column = QVBoxLayout(box)
        column.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(tr("Document set")))
        self.set_combo = QComboBox()
        theme.style_dropdown(self.set_combo)
        self.fill_set_combo()
        self.set_combo.currentIndexChanged.connect(diagnostics.guard(self._set_changed))
        row.addWidget(self.set_combo, 1)
        column.addLayout(row)
        self.custom_set = QLineEdit()
        self.custom_set.setPlaceholderText(tr("Name this kind of job"))
        self.custom_set.hide()
        self.custom_set.editingFinished.connect(diagnostics.guard(self._custom_named))
        column.addWidget(self.custom_set)
        column.addWidget(hint(tr("The document set supplies its standard values; you type the rest.")))

        self.documents_area = QVBoxLayout()
        self.documents_area.setSpacing(4)
        column.addLayout(self.documents_area)

        self.copy_sources_box = QCheckBox(tr("Also put the source spreadsheet itself in the output folder"))
        self.copy_sources_box.setToolTip(tr("Only applies when a source file is loaded."))
        column.addWidget(self.copy_sources_box)
        return box

    def _section_fields(self) -> QGroupBox:
        box = QGroupBox(tr("3  ·  FIELDS"))
        column = QVBoxLayout(box)
        column.addWidget(hint(tr(
            "The fields of the ticked documents. Values from a file can be changed too; what "
            "you type is exactly what goes into the document."
        )))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel(tr("Saved record")))
        self.record_combo = QComboBox()
        theme.style_dropdown(self.record_combo)
        self.record_combo.currentIndexChanged.connect(diagnostics.guard(self._record_chosen))
        row.addWidget(self.record_combo, 1)
        column.addLayout(row)
        self.form = QFormLayout()
        self.form.setSpacing(8)
        self.form.setContentsMargins(0, 8, 0, 0)
        column.addLayout(self.form)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        column.addWidget(self.summary_label)
        self.fill_record_combo()
        return box

    def _section_output(self) -> QGroupBox:
        box = QGroupBox(tr("4  ·  OUTPUT FOLDER AND PRODUCTION"))
        column = QVBoxLayout(box)
        column.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(8)
        choose = QPushButton(tr("Choose folder…"))
        choose.clicked.connect(diagnostics.guard(self.choose_output_folder))
        row.addWidget(choose)
        self.folder_label = heading(tr("No folder chosen."), 9, False, theme.COLOURS["text_muted"])
        row.addWidget(self.folder_label, 1)
        column.addLayout(row)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.preview_button = QPushButton(tr("Preview (PDF)"))
        self.preview_button.clicked.connect(diagnostics.guard(self.create_preview))
        self.produce_button = QPushButton(tr("Produce Documents"))
        self.produce_button.setObjectName("primary")
        self.produce_button.clicked.connect(diagnostics.guard(self.produce))
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(diagnostics.guard(self.cancel))
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.produce_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        column.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        column.addWidget(self.progress)
        return box

    def _section_result(self) -> QGroupBox:
        box = QGroupBox(tr("5  ·  PREVIEW AND RESULT"))
        column = QVBoxLayout(box)
        self.output_rows = QVBoxLayout()
        self.output_rows.setSpacing(5)
        column.addLayout(self.output_rows)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumHeight(120)
        self.result_text.setPlainText(tr("No documents produced yet."))
        column.addWidget(self.result_text)
        row = QHBoxLayout()
        self.open_folder_button = QPushButton(tr("Open output folder"))
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(diagnostics.guard(self.open_output_folder))
        row.addWidget(self.open_folder_button)
        row.addStretch()
        column.addLayout(row)
        return box

    # ========================================================= sets / docs

    def fill_set_combo(self):
        current = self.set_combo.currentData() if self.set_combo.count() else None
        self.set_combo.blockSignals(True)
        self.set_combo.clear()
        self.set_combo.addItem(tr("— choose —"), None)
        for document_set in document_sets.all_sets():
            self.set_combo.addItem(document_set.name, document_set.id)
        self.set_combo.addItem(tr("Other (I will name it)"), document_sets.OTHER)
        index = self.set_combo.findData(current)
        self.set_combo.setCurrentIndex(index if index >= 0 else 0)
        self.set_combo.blockSignals(False)

    def reload_templates(self):
        self.templates = templates.discover(settings.template_folder())
        self._fill_documents()
        self._rebuild_fields()

    def _fill_documents(self):
        while self.documents_area.count():
            item = self.documents_area.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                _clear_layout(item.layout())
        self.boxes = {}
        remembered = set(settings.workspace()["quick_templates"])
        if not self.templates:
            self.documents_area.addWidget(hint(tr("No template folder chosen — choose it on the Documents page.")))
            return
        for template in self.templates:
            row = QHBoxLayout()
            row.setSpacing(8)
            box = QCheckBox(template.title)
            box.setEnabled(template.ok)
            box.setChecked(template.name in remembered)
            box.stateChanged.connect(diagnostics.guard(self._documents_changed))
            self.boxes[template.name] = box
            row.addWidget(box, 1)
            edit = QPushButton(tr("Edit fields"))
            edit.setCursor(Qt.PointingHandCursor)
            edit.setEnabled(template.ok)
            edit.clicked.connect(diagnostics.guard(lambda _=False, t=template: self._edit_document(t)))
            row.addWidget(edit)
            holder = QWidget()
            holder.setLayout(row)
            self.documents_area.addWidget(holder)

    def selected_templates(self) -> list[templates.Template]:
        return [t for t in self.templates if self.boxes.get(t.name) and self.boxes[t.name].isChecked()]

    def _documents_changed(self):
        settings.set_workspace(quick_templates=[t.name for t in self.selected_templates()])
        self._rebuild_fields()

    def _set_changed(self):
        set_id = self.set_combo.currentData()
        other = set_id == document_sets.OTHER
        self.custom_set.setVisible(other)
        if not other:
            self.custom_set.clear()
            self.project.custom_set_name = None
        self.project.document_set = set_id
        required = set(document_sets.required_templates(set_id))
        if required:
            for name, box in self.boxes.items():
                box.blockSignals(True)
                box.setChecked(name in required)
                box.blockSignals(False)
            settings.set_workspace(quick_templates=[t.name for t in self.selected_templates()])
        self._rebuild_fields()

    def _custom_named(self):
        self.project.custom_set_name = self.custom_set.text().strip() or None
        self.request_live_preview()

    # ================================================================ fields

    def _rebuild_fields(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.inputs = {}
        for name in templates.all_placeholders(self.selected_templates()):
            box = MemoryInput(name)
            if name in AUTOMATIC_FIELDS:
                box.setReadOnly(True)
                box.setPlaceholderText(tr("filled automatically with today's date"))
            else:
                box.setText(formatting.for_editing(self.project.value(name)))
                box.setPlaceholderText(tr("if left empty it stays empty in the document"))
                box.editingFinished.connect(diagnostics.guard(self.form_to_project))
            self.inputs[name] = box
            self.form.addRow(templates.label(name), box)
        self._update_summary()

    def _project_to_form(self):
        for name, box in self.inputs.items():
            if name in AUTOMATIC_FIELDS:
                continue
            box.blockSignals(True)
            box.setText(formatting.for_editing(self.project.value(name)))
            box.blockSignals(False)
        self._update_summary()

    def _form_to_project_quietly(self):
        """Write the form into the project WITHOUT asking for a live refresh
        (that would loop)."""
        for name, box in self.inputs.items():
            if name in AUTOMATIC_FIELDS:
                continue
            text = formatting.single_line(box.text())
            if text == formatting.for_editing(self.project.value(name)).strip():
                continue
            self.project.type_value(name, formatting.from_editing(text, self.project.value(name)) if text else "")

    def form_to_project(self):
        self._form_to_project_quietly()
        self._update_summary()
        self.request_live_preview()

    def fill_record_combo(self):
        self.record_combo.blockSignals(True)
        self.record_combo.clear()
        self.record_combo.addItem(tr("— choose a saved record —"), None)
        for record in library.records():
            self.record_combo.addItem(record.name, record.name)
        self.record_combo.blockSignals(False)

    def _record_chosen(self):
        record = library.find(self.record_combo.currentData())
        if record is None:
            return
        for name, value in record.values.items():
            if value:
                self.project.type_value(name, value)
        self._project_to_form()
        self.request_live_preview()

    def _edit_document(self, template: templates.Template):
        self.form_to_project()
        window = dialogs.FieldsDialog(self.main_window, template, self.project)
        window.exec()
        self._project_to_form()
        self.request_live_preview()

    def _update_summary(self):
        selected = self.selected_templates()
        if not selected:
            self.summary_label.setText(tr("No document selected."))
            self.summary_label.setStyleSheet(f"color: {theme.COLOURS['warning']};")
            self.summary_label.show()
            return
        overview = fields.summary(selected, self.project)
        required = sum(o["required_missing"] for o in overview)
        if required:
            problems = ", ".join(f"{o['title']} ({o['required_missing']})" for o in overview if o["required_missing"])
            self.summary_label.setText(tr(
                "<b>{count} documents selected.</b> {required} required field(s) are empty: {list}. "
                "The documents are still produced, with those fields blank."
            ).format(count=len(selected), required=required, list=problems))
            self.summary_label.setStyleSheet(f"color: {theme.COLOURS['warning']};")
        else:
            self.summary_label.setText(tr("<b>{count} documents selected.</b> All required fields are filled.").format(count=len(selected)))
            self.summary_label.setStyleSheet(f"color: {theme.COLOURS['success']};")
        self.summary_label.show()
        self.request_live_preview()

    # ================================================================ source

    def choose_source(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("Choose a source file"), "",
            f"{tr('Spreadsheets')} (*.xlsx *.xlsm *.xls *.csv);;{tr('All files')} (*)",
        )
        if files:
            self.load_files(files)

    def load_files(self, files: list[str]):
        account = accounts.active()
        try:
            resolution = engine.resolve(list(files), self.templates, account.profile_values if account else {})
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("The file could not be read"), str(exc))
            return
        previous_typed = dict(self.project.typed)
        self.project = resolution.project
        # What was already typed on this page is kept over the file's values.
        self.project.typed.update(previous_typed)
        self.loaded_files = list(files)
        self.analyses = list(resolution.analyses)
        self.drop_button.setEnabled(True)
        self.content_button.setEnabled(bool(self.analyses))
        self.source_info.setText(
            tr("<b>{values}</b> values read from {files}.").format(
                values=len(self.project.labels), files=", ".join(Path(f).name for f in files)
            )
        )
        if resolution.suggestion:
            index = self.set_combo.findData(resolution.suggestion)
            if index >= 0:
                self.set_combo.setCurrentIndex(index)
        self.project.document_set = self.set_combo.currentData()
        self._project_to_form()

    def _view_source(self):
        for analysis in self.analyses:
            show_source(self.main_window, analysis, self.project, self.jobs)

    def drop_source(self):
        self.project = _empty_project()
        self.project.document_set = self.set_combo.currentData()
        self.loaded_files = []
        self.analyses = []
        self.content_button.setEnabled(False)
        self.drop_button.setEnabled(False)
        self.source_info.setText(tr("No source loaded — the fields start empty."))
        self.discard_preview()
        self._project_to_form()

    # ============================================================ production

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("Choose the output folder"))
        if not folder:
            return
        problem = paths.path_length_problem(folder)
        if problem:
            QMessageBox.warning(self, tr("Folder path is very long"), problem)
            return
        problem = paths.writable_problem(folder)
        if problem:
            QMessageBox.critical(self, tr("Cannot write to the folder"), problem)
            return
        self.output_folder = folder
        self.folder_label.setText(folder)
        self.folder_label.setStyleSheet(f"color: {theme.COLOURS['text']};")

    def _prepare(self, folder_needed: bool, quiet: bool = False):
        def warn(text: str) -> None:
            if not quiet:
                QMessageBox.warning(self, tr("Missing"), text)

        self._form_to_project_quietly()
        set_id = self.set_combo.currentData()
        if not set_id:
            warn(tr("Choose the document set."))
            return None
        self.project.document_set = set_id
        if set_id == document_sets.OTHER:
            name = self.custom_set.text().strip()
            if not name:
                warn(tr("Name this kind of job (\"Other\" was chosen)."))
                return None
            self.project.custom_set_name = name
        self.project.copy_source_spreadsheets = self.copy_sources_box.isChecked()
        selected = self.selected_templates()
        if not selected:
            warn(tr("Select at least one document."))
            return None
        if not quiet:
            memory.remember_many({name: box.text() for name, box in self.inputs.items()})
        if folder_needed and not self.output_folder:
            warn(tr("Choose the output folder."))
            return None
        return selected

    def _busy(self, running: bool, text: str = ""):
        self.progress.setVisible(running)
        self.preview_button.setEnabled(not running)
        self.produce_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        if text:
            self.result_text.setPlainText(text)

    def busy(self) -> bool:
        if not is_running(self._worker):
            self._worker = None
            return False
        return True

    def cancel(self):
        if self.busy():
            self._worker.request_cancel()
            self.result_text.setPlainText(tr("Cancelling — the step in progress is finished first…"))

    def create_preview(self, quiet: bool = False):
        selected = self._prepare(folder_needed=False, quiet=quiet)
        if selected is None:
            return
        project, previous = self.project, self.preview
        self._quiet = quiet
        self._busy(True, "" if quiet else tr("Preparing the preview…"))

        def work(is_cancelled):
            return engine.build_preview(project, selected, is_cancelled=is_cancelled, previous=previous)

        self._worker = self.jobs.start(Worker(work), self._preview_done)

    def request_live_preview(self) -> None:
        """A field changed: an existing preview refreshes itself."""
        if self.preview is None or not self.preview.valid:
            return
        self._live_timer.start()

    def _auto_refresh(self):
        if self.preview is None or not self.preview.valid:
            return
        if self.busy():
            self._refresh_pending = True
            return
        selected = self._prepare(folder_needed=False, quiet=True)
        if selected is None or not self.preview.is_stale(self.project, selected):
            return
        self.create_preview(quiet=True)

    def _refresh_open_previews(self):
        if not self._open_previews or self.preview is None:
            return
        for name, window in list(self._open_previews.items()):
            new_file = self.preview.folder / name
            try:
                if new_file.exists():
                    window.reload(new_file)
            except RuntimeError:
                self._open_previews.pop(name, None)

    def _preview_done(self, preview):
        self._busy(False)
        self._worker = None
        if isinstance(preview, Exception):
            self.result_text.setPlainText(tr("The preview failed: {error}").format(error=preview))
            return
        if self.preview is not None and self.preview is not preview:
            self.preview.discard()
        self.preview = preview
        result = preview.result
        if result.cancelled:
            self.result_text.setPlainText(tr("The preview was cancelled."))
            return
        self._draw_output_rows(result)
        if not result.pdfs:
            self.result_text.setPlainText(tr("No preview PDF could be produced:") + "\n" + "\n".join(result.warnings))
            return
        self.result_text.setPlainText(tr(
            "Preview ready ({time}). When you change a field the preview updates itself; when "
            "everything is right, press 'Produce Documents'."
        ).format(time=duration_text(result.seconds)))
        self._refresh_open_previews()
        if self._refresh_pending:
            self._refresh_pending = False
            self._live_timer.start()
        if not self._quiet:
            self.open_preview(result.pdfs[0])

    def _draw_output_rows(self, result):
        """One row per produced document, each opening it — so all of them can
        be checked one by one, not just the first."""
        _clear_layout(self.output_rows)
        c = theme.COLOURS
        for file in list(result.pdfs) + [d for d in result.editable if d.suffix.lower() == ".docx"]:
            row = QFrame()
            row.setStyleSheet(f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 6px; }}")
            line = QHBoxLayout(row)
            line.setContentsMargins(10, 6, 10, 6)
            line.setSpacing(8)
            kind = "PDF" if file.suffix.lower() == ".pdf" else "DOCX"
            badge = QLabel(kind)
            badge.setStyleSheet(theme.badge("success" if kind == "PDF" else "neutral"))
            line.addWidget(badge)
            line.addWidget(heading(file.name, 9, True), 1)
            button = QPushButton(tr("Preview"))
            button.setObjectName("small")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(diagnostics.guard(lambda _=False, f=file: self.open_preview(f)))
            line.addWidget(button)
            self.output_rows.addWidget(row)

    def open_preview(self, file) -> None:
        """Modeless: the form can be edited while the window is open and the
        change is seen live."""
        file = Path(file)
        existing = self._open_previews.get(file.name)
        if existing is not None:
            try:
                existing.reload(file)
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                self._open_previews.pop(file.name, None)
        window = dialogs.PreviewDialog(self.main_window, file)
        window.setModal(False)
        self._open_previews[file.name] = window
        window.finished.connect(lambda _=0, n=file.name: self._open_previews.pop(n, None))
        window.show()

    def produce(self):
        selected = self._prepare(folder_needed=True)
        if selected is None:
            return
        project, folder, preview = self.project, self.output_folder, self.preview
        self._busy(True, tr("Producing the documents…"))

        def work(is_cancelled):
            if preview is not None and preview.valid and not preview.is_stale(project, selected):
                return engine.place_preview(preview, folder)
            return engine.produce(project, selected, folder, is_cancelled=is_cancelled, reuse=preview)

        self._worker = self.jobs.start(Worker(work), self._produced)

    def _produced(self, result):
        self._busy(False)
        self._worker = None
        if isinstance(result, Exception):
            self.result_text.setPlainText(tr("Production failed: {error}").format(error=result))
            self.open_folder_button.setEnabled(bool(self.output_folder and Path(self.output_folder).is_dir()))
            return
        self.discard_preview()
        files = [Path(p) for p in list(result.pdfs) + list(result.editable) + list(result.copied_files)]
        present = [f for f in files if f.is_file()]
        missing = [f for f in files if not f.is_file()]
        if not result.error and not result.cancelled and not files:
            result.error = tr("Production finished but no document was found to save.")
        if not result.error and not result.cancelled and missing:
            result.error = tr("Some produced files were not found in the output folder: ") + ", ".join(f.name for f in missing)

        lines = []
        if result.error:
            lines.append(tr("SAVE/PRODUCTION ERROR: {error}").format(error=result.error))
        elif result.cancelled:
            lines.append(tr("The job was cancelled."))
        else:
            lines.append(tr("Documents produced and saved: {pdfs} PDF, {words} Word file(s) — {time}.").format(
                pdfs=len(result.pdfs), words=len(result.editable), time=duration_text(result.seconds)
            ))
        if self.output_folder:
            lines.append(tr("Output folder: {folder}").format(folder=Path(self.output_folder).resolve()))
        if present:
            lines.append(tr("Saved files:"))
            root = Path(self.output_folder).resolve() if self.output_folder else None
            for file in present:
                try:
                    name = file.resolve().relative_to(root).as_posix() if root else file.name
                except ValueError:
                    name = str(file)
                lines.append(f"  • {name}")
        if missing:
            lines.append(tr("Files that could not be saved:"))
            lines.extend(f"  • {f}" for f in missing)
        lines.extend(tr("Warning: {text}").format(text=w) for w in result.warnings)
        self.result_text.setPlainText("\n".join(lines))
        self._draw_output_rows(result)
        self.open_folder_button.setEnabled(bool(self.output_folder and Path(self.output_folder).is_dir()))
        if not result.error and not result.cancelled:
            history.record(result, self.output_folder)
            self.main_window.history_changed()

    def discard_preview(self):
        if self.preview is not None:
            self.preview.discard()
            self.preview = None

    def open_output_folder(self):
        if self.output_folder and Path(self.output_folder).is_dir():
            try:
                os.startfile(self.output_folder)  # noqa: S606
            except OSError as exc:
                QMessageBox.warning(self, tr("The folder could not be opened"), f"{self.output_folder}\n\n{exc}")

    # ---------------------------------------------------------------- state

    def state(self) -> dict:
        self._form_to_project_quietly()
        return {"project": copy.deepcopy(self.project), "files": list(self.loaded_files),
                "set": self.set_combo.currentData(), "folder": self.output_folder}

    def restore(self, state: dict) -> None:
        index = self.set_combo.findData(state.get("set"))
        if index >= 0:
            self.set_combo.setCurrentIndex(index)
        if state.get("project") is not None:
            self.project = state["project"]
            self.loaded_files = state.get("files") or []
            if self.loaded_files:
                self.drop_button.setEnabled(True)
                self.source_info.setText(", ".join(Path(f).name for f in self.loaded_files))
        if state.get("folder"):
            self.output_folder = state["folder"]
            self.folder_label.setText(self.output_folder)
        self._project_to_form()


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())
