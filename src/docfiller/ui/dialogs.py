"""Dialogs.

Contents:
  * DimOverlay        — darkens the main window while a modal is open
  * BaseDialog        — the shared modal frame: header, body, footer
  * FieldsDialog      — the fields of ONE document, edited in one place
  * SourceContentDialog — what was read from a loaded file, before producing
  * PreviewDialog     — a produced PDF, shown inside the program

All share the theme's palette: neutral surfaces, one accent, clear borders and
a shadow. Modals are centred on the main window.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import fields, form_controls, formatting, memory, templates
from ..i18n import tr
from ..project import AUTOMATIC, DEFAULT, PROFILE, SOURCE, TYPED
from . import theme
from .widgets import MemoryInput, heading

AUTOMATIC_LABEL = "Automatic"
BLANK_LABEL = "Leave empty (write nothing)"


class CollapsibleLabel(QWidget):
    """Shows long question texts IN FULL, folded when very long.

    Some form questions run past 300 characters. Cutting them (…) would make the
    text on screen differ from the document, and the user can only tell which
    box they are answering from the full text. So the text is never cut: a long
    one shows its beginning, and "more" reveals the rest.
    """

    THRESHOLD = 200

    def __init__(self, text: str, size: float = 8.5, bold: bool = False, colour=None):
        super().__init__()
        self._full = text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._label = heading(text, size, bold, colour)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._label)
        self._button = None
        if len(text) > self.THRESHOLD:
            self._open = False
            self._label.setText(text[: self.THRESHOLD].rstrip() + "…")
            self._button = QPushButton(tr("more"))
            self._button.setObjectName("link")
            self._button.setCursor(Qt.PointingHandCursor)
            self._button.setFlat(True)
            self._button.clicked.connect(self._toggle)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(self._button)
            row.addStretch()
            layout.addLayout(row)

    def _toggle(self):
        self._open = not self._open
        self._label.setText(self._full if self._open else self._full[: self.THRESHOLD].rstrip() + "…")
        self._button.setText(tr("less") if self._open else tr("more"))


class DimOverlay(QWidget):
    """A translucent layer over the main window while a modal is open.

    Qt does not darken the background by itself; the layer makes it clear the
    modal is "on top" and keeps the content behind from distracting.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(18, 22, 27, 90);")
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Resize and obj is self.parent():
            self.setGeometry(obj.rect())
        return False

    def close_overlay(self) -> None:
        parent = self.parent()
        if parent is not None:
            parent.removeEventFilter(self)
        self.hide()
        self.deleteLater()


class BaseDialog(QDialog):
    """Shared modal frame: header strip, scrollable body, footer buttons."""

    def __init__(self, parent, title: str, subtitle: str = "", width: int = 640, height: int = 560):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setStyleSheet(theme.STYLE)
        # Resizable: long question texts and a 90-row form list are unreadable
        # in a small box, so the system title bar (maximise/restore/close) and
        # corner resizing are enabled.
        self.setWindowFlags(
            Qt.Window | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint
        )
        self.setSizeGripEnabled(True)
        self._fit_to_screen(width, height)

        self._overlay = DimOverlay(parent) if parent is not None else None
        if self._overlay is not None:
            self._overlay.show()

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 14, 20, 14)
        header_layout.setSpacing(2)
        header_layout.addWidget(heading(title, 12.5, True))
        self._subtitle = None
        if subtitle:
            sub = heading(subtitle, 8.5, False, theme.COLOURS["text_muted"])
            sub.setWordWrap(True)
            header_layout.addWidget(sub)
            self._subtitle = sub
        outer.addWidget(header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(20, 16, 20, 16)
        self.body.setSpacing(12)
        wrapper = QWidget()
        wrapper.setLayout(self.body)
        outer.addWidget(wrapper, 1)

        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(20, 12, 20, 12)
        self.footer.setSpacing(10)
        footer_frame = QFrame()
        footer_frame.setObjectName("dialogFooter")
        footer_frame.setLayout(self.footer)
        outer.addWidget(footer_frame)

    def _fit_to_screen(self, preferred_width: int, preferred_height: int) -> None:
        """Fit the dialog into the available screen area and centre it, so the
        footer buttons never end up under the taskbar on a laptop screen."""
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(preferred_width, preferred_height)
            return
        area = screen.availableGeometry()
        width, height = theme.window_size(
            area.width(), area.height(), preferred_width, preferred_height, 420, 320, margin=60
        )
        self.resize(width, height)
        centre = self.parent().geometry().center() if self.parent() else area.center()
        frame = self.frameGeometry()
        frame.moveCenter(centre)
        frame.moveLeft(max(area.left(), min(frame.left(), area.right() - width)))
        frame.moveTop(max(area.top(), min(frame.top(), area.bottom() - height)))
        self.move(frame.topLeft())

    def set_subtitle(self, text: str) -> None:
        if self._subtitle is not None:
            self._subtitle.setText(text)

    def done(self, result):  # noqa: N802
        if self._overlay is not None:
            self._overlay.close_overlay()
            self._overlay = None
        super().done(result)

    @staticmethod
    def section_title(text: str, kind: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(theme.badge(kind))
        label.setAlignment(Qt.AlignLeft)
        label.setMaximumWidth(360)
        return label


# ======================================================== fields of a document


def _origin_text(project, name: str) -> str:
    origin = project.origin(name)
    if origin == SOURCE:
        source = project.mapping[name]
        return tr("from the file: \"{label}\" [{address}]").format(label=source.label, address=source.address)
    if origin == TYPED:
        return tr("typed in")
    if origin == PROFILE:
        return tr("from your profile")
    if origin == DEFAULT:
        return tr("document set default")
    if origin == AUTOMATIC:
        return tr("filled automatically")
    return ""


class FieldsDialog(BaseDialog):
    """The fields of ONE document.

    Fields belong to the document: one document's gaps are never pooled with
    another's. Saving writes straight into the project; anything left empty
    stays empty in the document and never stops production.
    """

    def __init__(self, parent, template: templates.Template, project):
        gaps = len(fields.missing(template, project))
        super().__init__(
            parent,
            template.title,
            tr("The fields of this document. {count} are empty — what you leave empty stays empty in the document.").format(count=gaps),
            width=960,
            height=780,
        )
        self.template = template
        self.project = project
        self._rows: list[tuple[str, MemoryInput, QComboBox | None, str]] = []
        self._controls: list[tuple[form_controls.Control, QWidget]] = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)

        all_fields = fields.document_fields(template, project)
        empty = [f for f in all_fields if not f.filled and not f.automatic]
        filled = [f for f in all_fields if f.filled or f.automatic]
        if empty:
            layout.addWidget(self.section_title(tr("Empty fields ({count})").format(count=len(empty)), "warning"))
            for f in empty:
                layout.addWidget(self._field_row(f))
        if filled:
            layout.addWidget(self.section_title(tr("Filled fields ({count})").format(count=len(filled)), "success"))
            for f in filled:
                layout.addWidget(self._field_row(f))

        self._form_controls(layout)
        layout.addStretch()
        self.body.addWidget(scroll)

        self.footer.addStretch()
        cancel = QPushButton(tr("Cancel"))
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        save = QPushButton(tr("Save"))
        save.setObjectName("primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self._save)
        self.footer.addWidget(cancel)
        self.footer.addWidget(save)

    def _field_row(self, field: fields.Field) -> QWidget:
        wrapper = QWidget()
        column = QVBoxLayout(wrapper)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(heading(field.label, 9, True))
        if field.required:
            badge = QLabel(tr("required"))
            badge.setStyleSheet(theme.badge("error"))
            top.addWidget(badge)
        if field.automatic:
            badge = QLabel(tr("automatic"))
            badge.setStyleSheet(theme.badge("accent"))
            top.addWidget(badge)
        origin = _origin_text(self.project, field.name)
        if origin and not field.automatic:
            note = heading(origin, 8, False, theme.COLOURS["text_faint"])
            top.addWidget(note)
        top.addStretch()
        column.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(8)
        current = formatting.for_editing(field.value)
        box = MemoryInput(field.name)
        box.setText(current)
        if field.automatic:
            box.setReadOnly(True)
            box.setPlaceholderText(tr("filled automatically during production"))
        elif not field.filled:
            box.setPlaceholderText(tr("empty — you can type a value"))
            box.setProperty("missing", "true")
        row.addWidget(box, 3)

        chooser = None
        if self.project.labels and not field.automatic:
            # Re-point the field to a different caption from the file.
            chooser = QComboBox()
            chooser.addItem(tr("— keep —"), "__keep__")
            chooser.addItem(tr("— not from the file —"), "")
            for source in self.project.labels:
                chooser.addItem(f"{source.label}  [{source.address}]", source.address)
            theme.style_dropdown(chooser)
            chooser.setToolTip(tr("Take this field from a different caption in the file"))
            row.addWidget(chooser, 2)
        column.addLayout(row)

        if not field.automatic:
            self._rows.append((field.name, box, chooser, current))
        return wrapper

    # --------------------------------------------------- the form's own boxes

    def _form_controls(self, layout) -> None:
        """Dropdowns and text boxes that the form itself contains.

        They are not placeholders. Where the file supplies an answer it is used
        automatically; the user always has the last word — choose a value,
        leave it empty, or leave it to the automatic answer.
        """
        found = form_controls.controls(self.template.path)
        if not found:
            return
        chosen = form_controls.choices(self.project, self.template.name)
        layout.addWidget(self.section_title(tr("Form answers ({count})").format(count=len(found)), "accent"))
        note = heading(
            tr("The form's own boxes. Left on 'Automatic', the program writes the answer it "
               "finds in the file; when it finds none, the box keeps its form value."),
            8.5, False, theme.COLOURS["text_muted"],
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        last_section = None
        for control in found:
            if control.section and control.section != last_section:
                last_section = control.section
                title = QLabel(control.section)
                title.setWordWrap(True)
                title.setObjectName("sectionHeading")
                layout.addWidget(title)
            layout.addWidget(self._control_row(control, chosen.get(control.key)))

    def _control_row(self, control: form_controls.Control, choice) -> QWidget:
        wrapper = QWidget()
        column = QVBoxLayout(wrapper)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        label = CollapsibleLabel(control.label, 8.5)
        label.setToolTip(control.label)
        column.addWidget(label)

        automatic = form_controls.automatic_value(control, self.project)
        if control.kind == form_controls.LIST:
            box = QComboBox()
            box.addItem(
                f"{tr(AUTOMATIC_LABEL)} → {automatic}" if automatic else f"{tr(AUTOMATIC_LABEL)} ({tr('no answer found')})",
                form_controls.AUTOMATIC,
            )
            for option in control.options:
                box.addItem(option, option)
            box.addItem(tr(BLANK_LABEL), form_controls.BLANK)
            index = box.findData(choice) if choice else 0
            box.setCurrentIndex(index if index >= 0 else 0)
            theme.style_dropdown(box)
        else:
            box = QLineEdit("" if choice in (None, form_controls.AUTOMATIC) else str(choice))
            box.setPlaceholderText(
                tr("automatic: {value}").format(value=automatic) if automatic else tr("empty — you can type a value")
            )
        column.addWidget(box)
        self._controls.append((control, box))
        return wrapper

    # ------------------------------------------------------------------ save

    def _save(self):
        if self._controls:
            chosen = form_controls.choices(self.project, self.template.name)
            for control, box in self._controls:
                value = box.currentData() if isinstance(box, QComboBox) else box.text().strip()
                if not value or value == form_controls.AUTOMATIC:
                    chosen.pop(control.key, None)
                else:
                    chosen[control.key] = value
            form_controls.set_choices(self.project, self.template.name, chosen)

        by_address = {lv.address: lv for lv in self.project.labels}
        to_remember = {}
        for name, box, chooser, original in self._rows:
            if chooser is not None and chooser.currentData() != "__keep__":
                address = chooser.currentData()
                self.project.point_to(name, by_address.get(address) if address else None)
                continue
            text = box.text().strip()
            to_remember[name] = text
            if text == original.strip():
                continue  # untouched: the field keeps its value and its origin
            self.project.type_value(name, formatting.from_editing(text, self.project.value(name)) if text else "")
        memory.remember_many(to_remember)
        self.accept()


# ====================================================== what was read from a file


class SourceContentDialog(BaseDialog):
    """What the program read from a loaded file — checked BEFORE producing.

    Without opening the file, every caption found is listed with its value and
    the field it fills, along with values that could not be read as numbers. A
    wrong value is noticed before it reaches a document.
    """

    def __init__(self, parent, analysis, project=None):
        super().__init__(parent, analysis.name, str(analysis.path.parent), width=860, height=720)
        self.analysis = analysis

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)

        layout.addWidget(self._facts())
        if analysis.error:
            box = heading(analysis.error, 9)
            box.setWordWrap(True)
            box.setStyleSheet(theme.banner("warning"))
            layout.addWidget(box)

        feeds: dict[str, list[str]] = {}
        if project is not None:
            for name, source in project.mapping.items():
                feeds.setdefault(source.address, []).append(templates.label(name))

        if analysis.labels:
            layout.addWidget(self.section_title(tr("Values read ({count})").format(count=len(analysis.labels)), "success"))
            layout.addWidget(self._table(analysis.labels, feeds))
        if analysis.unreadable_numbers:
            layout.addWidget(self.section_title(
                tr("Not readable as numbers ({count})").format(count=len(analysis.unreadable_numbers)), "warning"
            ))
            for caption, raw in analysis.unreadable_numbers:
                line = heading(f"{caption}: {raw!r}", 8.5, False)
                line.setWordWrap(True)
                layout.addWidget(line)

        layout.addStretch()
        self.body.addWidget(scroll)

        self.footer.addStretch()
        open_button = QPushButton(tr("Open the file"))
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.clicked.connect(self._open_file)
        close = QPushButton(tr("Close"))
        close.setObjectName("primary")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        self.footer.addWidget(open_button)
        self.footer.addWidget(close)

    def _facts(self) -> QWidget:
        frame = QFrame()
        c = theme.COLOURS
        frame.setStyleSheet(
            f"QFrame {{ background: {c['card_alt']}; border: 1px solid {c['border']}; border-radius: 6px; }}"
        )
        column = QVBoxLayout(frame)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(3)
        a = self.analysis
        for label, value in (
            (tr("Summary"), a.summary()),
            (tr("Sheets"), ", ".join(a.sheets) or "—"),
            (tr("Filled cells"), str(a.filled_cells or "—")),
        ):
            line = heading(f"{label}: {value}", 8.5, False)
            line.setWordWrap(True)
            column.addWidget(line)
        return frame

    def _table(self, rows, feeds) -> QWidget:
        wrapper = QWidget()
        column = QVBoxLayout(wrapper)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        c = theme.COLOURS
        for source in rows:
            row = QFrame()
            row.setStyleSheet(
                f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 5px; }}"
            )
            line = QHBoxLayout(row)
            line.setContentsMargins(10, 5, 10, 5)
            line.setSpacing(10)
            caption = heading(f"{source.label}  [{source.address}]", 8.5, True)
            caption.setMinimumWidth(240)
            caption.setWordWrap(True)
            line.addWidget(caption)
            value = heading(formatting.for_document(source.value), 8.5, False)
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            line.addWidget(value, 1)
            used = feeds.get(source.address)
            if used:
                badge = QLabel("→ " + ", ".join(used))
                badge.setStyleSheet(theme.badge("accent"))
                badge.setWordWrap(True)
                line.addWidget(badge)
            column.addWidget(row)
        return wrapper

    def _open_file(self):
        if self.analysis.path.exists():
            os.startfile(str(self.analysis.path))  # noqa: S606 - the user's own file


# ==================================================================== preview


class PreviewDialog(BaseDialog):
    """A produced document, shown inside the program.

    PDFs are displayed with Qt's own PDF engine, so the user can check a
    document without going to the output folder. Without Qt's PDF component
    the window still opens and offers the system viewer — a missing preview
    never blocks the work.
    """

    def __init__(self, parent, file: str | Path, analysis=None, project=None):
        file = Path(file)
        super().__init__(
            parent,
            analysis.name if analysis is not None else file.name,
            str(analysis.path.parent) if analysis is not None else str(file.parent),
            width=980,
            height=820,
        )
        self.file = file
        self.analysis = analysis
        self.project = project
        self._document = None  # QPdfDocument; collected too early the view goes blank
        self._view = None

        self._content = self._build()
        self.body.addWidget(self._content)

        self.footer.addStretch()
        if analysis is not None:
            values = QPushButton(tr("Values read"))
            values.setCursor(Qt.PointingHandCursor)
            values.setToolTip(tr("Which value was read into which field"))
            values.clicked.connect(lambda: SourceContentDialog(self.parent(), self.analysis, self.project).exec())
            self.footer.addWidget(values)
        system = QPushButton(tr("Open in the system viewer"))
        system.setCursor(Qt.PointingHandCursor)
        system.clicked.connect(self._open_in_system)
        close = QPushButton(tr("Close"))
        close.setObjectName("primary")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        self.footer.addWidget(system)
        self.footer.addWidget(close)

    def _build(self) -> QWidget:
        if not self.file.exists():
            return self._message(tr("File not found."), "error")
        if self.file.suffix.lower() != ".pdf":
            return self._message(
                tr("This file is not a PDF (an editable .docx). The preview shows PDF output only; "
                   "use the button below to open it in Word."),
                "neutral",
            )
        try:
            from PySide6.QtPdf import QPdfDocument
            from PySide6.QtPdfWidgets import QPdfView
        except ImportError:
            return self._message(
                tr("The PDF preview component is not available in this installation. "
                   "You can open the file in the system viewer."),
                "warning",
            )
        self._document = QPdfDocument(self)
        if self._document.load(str(self.file)) != QPdfDocument.Error.None_:
            return self._message(tr("The PDF could not be opened (the file may be damaged)."), "error")
        view = QPdfView(self)
        self._view = view
        view.setDocument(self._document)
        view.setPageMode(QPdfView.PageMode.MultiPage)
        view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        c = theme.COLOURS
        view.setStyleSheet(f"background: {c['border']}; border: 1px solid {c['border_strong']}; border-radius: 6px;")
        return view

    def reload(self, new_file: str | Path | None = None) -> None:
        """Refresh in place — the window stays open and shows the new version.

        When a field changes, the preview is produced again into a NEW temporary
        folder and an open window is pointed at the new file. The scroll
        position is kept so the user does not lose their place.
        """
        if new_file is not None:
            self.file = Path(new_file)
            self.set_subtitle(str(self.file.parent))
        position = None
        if self._view is not None:
            try:
                position = self._view.verticalScrollBar().value()
            except RuntimeError:
                position = None
        old = self._content
        self._document = None
        self._view = None
        self._content = self._build()
        self.body.addWidget(self._content)
        if old is not None:
            self.body.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
        if position and self._view is not None:
            self._view.verticalScrollBar().setValue(position)

    @staticmethod
    def _message(text: str, kind: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(theme.banner(kind) + " padding: 40px;")
        return label

    def _open_in_system(self):
        if self.file.exists():
            os.startfile(str(self.file))  # noqa: S606 - the user's own output
