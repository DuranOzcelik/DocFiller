"""Documents page — the main job.

load files -> confirm the document set -> choose documents -> complete what is
missing -> output folder -> preview -> produce -> result and preview.
"""
from __future__ import annotations

import copy
import os
import traceback
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
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import (
    accounts,
    diagnostics,
    document_sets,
    drafts,
    engine,
    fields,
    file_analysis,
    formatting,
    history,
    library,
    memory,
    paths,
    profiles,
    settings,
    templates,
)
from ..i18n import tr
from . import dialogs, theme
from .widgets import DropZone, JobManager, MemoryInput, Worker, duration_text, heading, hint, is_running

# After the user stops typing, an open preview refreshes itself after this
# pause: not on every keystroke, but soon enough to feel immediate.
LIVE_PREVIEW_DELAY_MS = 700

# Drafts are written after this much quiet (see drafts.py).
DRAFT_DELAY_MS = 400


class DocumentRow(QFrame):
    """One line of the "documents to produce" list.

    Next to the check box the number of the document's empty fields is shown as
    a badge, and "Edit fields" opens the window of THAT document only.
    """

    def __init__(self, template: templates.Template, required: bool, project_source, page):
        super().__init__()
        self.template = template
        self.required = required
        self._project_source = project_source
        self._page = page
        c = theme.COLOURS
        self.setStyleSheet(
            f"DocumentRow {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 6px; }}"
        )
        line = QHBoxLayout(self)
        line.setContentsMargins(10, 6, 10, 6)
        line.setSpacing(8)

        self.box = QCheckBox(template.title)
        self.box.setMinimumWidth(0)
        self.box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.box.setToolTip(template.name)
        self.box.setChecked(required and template.ok)
        if required:
            self.box.setStyleSheet(f"font-weight: 700; color: {c['text']};")
        if not template.ok:
            self.box.setEnabled(False)
        else:
            self.box.setCursor(Qt.PointingHandCursor)
        line.addWidget(self.box, 1)

        controls_found = 0
        if template.ok:
            from .. import form_controls

            controls_found = len(form_controls.controls(template.path))
        detail = tr("{count} fields").format(count=len(template.placeholders))
        if controls_found:
            detail += " · " + tr("{count} form boxes").format(count=controls_found)
        line.addWidget(heading(detail, 8.5, False, c["text_muted"]))

        if required:
            badge = QLabel(tr("required"))
            badge.setStyleSheet(theme.badge("accent"))
            line.addWidget(badge)

        self.missing_badge = QLabel("")
        line.addWidget(self.missing_badge)

        self.edit_button = QPushButton(tr("Edit fields"))
        self.edit_button.setObjectName("small")
        self.edit_button.setCursor(Qt.PointingHandCursor)
        self.edit_button.clicked.connect(diagnostics.guard(self._edit))
        line.addWidget(self.edit_button)

        if not template.ok:
            self.edit_button.setEnabled(False)
            problem = QLabel(tr("cannot be read"))
            problem.setStyleSheet(theme.badge("neutral"))
            problem.setToolTip(template.error)
            line.addWidget(problem)
        self.refresh_badge()

    @property
    def name(self) -> str:
        return self.template.name

    def selected(self) -> bool:
        return self.box.isChecked() and self.box.isEnabled()

    def refresh_badge(self):
        project = self._project_source()
        if project is None or not self.template.ok:
            self.missing_badge.setText("")
            self.missing_badge.setStyleSheet("")
            return
        gaps = fields.missing(self.template, project)
        required = sum(1 for f in gaps if f.required)
        if required:
            self.missing_badge.setText(tr("{count} required empty").format(count=required))
            self.missing_badge.setStyleSheet(theme.badge("error"))
        elif gaps:
            self.missing_badge.setText(tr("{count} empty").format(count=len(gaps)))
            self.missing_badge.setStyleSheet(theme.badge("warning"))
        else:
            self.missing_badge.setText(tr("complete"))
            self.missing_badge.setStyleSheet(theme.badge("success"))

    def _edit(self):
        project = self._project_source()
        if project is None:
            QMessageBox.information(
                self._page, tr("Load files first"), tr("Load the project files first to see the fields.")
            )
            return
        window = dialogs.FieldsDialog(self._page.window(), self.template, project)
        if window.exec():
            self._page.refresh_badges()
            self._page.common_from_project()
            # Fields or form answers may have changed: an open preview refreshes
            # without the user pressing the button again.
            self._page.request_live_preview()


class DocumentsPage(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.project = None
        self.fresh_project = None         # as read from the files, before any edit
        self.loaded_files: list[str] = []
        self.analyses: list[file_analysis.Analysis] = []
        self.output_folder: str | None = None
        self.templates = templates.discover(settings.template_folder())
        self.rows: list[DocumentRow] = []
        self.common_inputs: dict[str, MemoryInput] = {}
        self.preview = None
        self.last_result = None
        self._worker = None
        self.jobs = JobManager()
        self._draft_key = ""
        self._quiet_refresh = False
        self._refresh_pending = False
        # Open preview windows: file name -> dialog. Refreshed in place.
        self._open_previews: dict[str, dialogs.PreviewDialog] = {}

        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(LIVE_PREVIEW_DELAY_MS)
        self._live_timer.timeout.connect(diagnostics.guard(self._auto_refresh))
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(DRAFT_DELAY_MS)
        self._draft_timer.timeout.connect(diagnostics.guard(self._save_draft))

        self._build()
        self._fill_document_rows()

    # ================================================================= layout

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
        layout.addWidget(self._section_files())
        layout.addWidget(self._section_set())
        layout.addWidget(self._section_documents())
        layout.addWidget(self._section_common())
        layout.addWidget(self._section_output())
        layout.addWidget(self._section_result())
        layout.addStretch()

    def _section_files(self) -> QGroupBox:
        box = QGroupBox(tr("1  ·  PROJECT FILES"))
        column = QVBoxLayout(box)
        column.setSpacing(10)
        self.drop_zone = DropZone()
        self.drop_zone.files_chosen.connect(diagnostics.guard(self.load_files))
        column.addWidget(self.drop_zone)
        column.addWidget(hint(tr(
            "Load as many files as you like: each one is examined, values are read from the "
            "spreadsheets, and unrecognised files never stop the job. PDF, Word and image "
            "files are not filled; they can be copied to the output folder."
        )))

        self.analysis_area = QVBoxLayout()
        self.analysis_area.setSpacing(6)
        column.addLayout(self.analysis_area)

        c = theme.COLOURS
        self.info = QLabel(tr("No files loaded yet."))
        self.info.setWordWrap(True)
        self.info.setStyleSheet(
            f"background: {c['card_alt']}; border: 1px solid {c['border']};"
            f" border-radius: 8px; padding: 12px; color: {c['text_muted']};"
        )
        column.addWidget(self.info)

        row = QHBoxLayout()
        self.remember_button = QPushButton(tr("Remember how fields were matched"))
        self.remember_button.setObjectName("small")
        self.remember_button.setToolTip(tr(
            "Store which caption fills which field for these templates; the next spreadsheet "
            "is matched the same way."
        ))
        self.remember_button.setEnabled(False)
        self.remember_button.clicked.connect(diagnostics.guard(self.remember_matching))
        row.addWidget(self.remember_button)
        row.addStretch()
        self.clear_button = QPushButton(tr("Clear selection"))
        self.clear_button.setObjectName("small")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(diagnostics.guard(self.clear_selection))
        self.clear_button.setEnabled(False)
        row.addWidget(self.clear_button)
        column.addLayout(row)
        return box

    def _section_set(self) -> QGroupBox:
        box = QGroupBox(tr("2  ·  DOCUMENT SET"))
        column = QVBoxLayout(box)
        column.setSpacing(8)
        self.set_combo = QComboBox()
        theme.style_dropdown(self.set_combo)
        self.fill_set_combo()
        self.set_combo.currentIndexChanged.connect(diagnostics.guard(self._set_changed))
        column.addWidget(self.set_combo)

        # Jobs that fit no set use "Other"; the user names them.
        self.custom_set = QLineEdit()
        self.custom_set.setPlaceholderText(tr("Name this kind of job"))
        self.custom_set.hide()
        self.custom_set.editingFinished.connect(diagnostics.guard(self._custom_set_named))
        column.addWidget(self.custom_set)

        self.suggestion = QLabel("")
        self.suggestion.setWordWrap(True)
        self.suggestion.hide()
        column.addWidget(self.suggestion)
        return box

    def _section_documents(self) -> QGroupBox:
        box = QGroupBox(tr("3  ·  DOCUMENTS TO PRODUCE"))
        column = QVBoxLayout(box)
        column.setSpacing(8)

        folder_row = QHBoxLayout()
        self.template_folder_label = heading("", 9, False, theme.COLOURS["text_muted"])
        self.template_folder_label.setWordWrap(True)
        folder_row.addWidget(self.template_folder_label, 1)
        change = QPushButton(tr("Template folder…"))
        change.setObjectName("small")
        change.setCursor(Qt.PointingHandCursor)
        change.clicked.connect(diagnostics.guard(self.choose_template_folder))
        folder_row.addWidget(change)
        column.addLayout(folder_row)

        top = QHBoxLayout()
        top.addWidget(hint(tr(
            "The documents the set requires come ticked. Each document's empty fields are "
            "completed in its own window."
        )), 1)
        for text, state in ((tr("All"), True), (tr("None"), False)):
            button = QPushButton(text)
            button.setObjectName("small")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, s=state: self._tick_all(s))
            top.addWidget(button)
        column.addLayout(top)

        self.rows_area = QVBoxLayout()
        self.rows_area.setSpacing(5)
        column.addLayout(self.rows_area)

        self.empty_label = heading("", 9.5, False, theme.COLOURS["text_muted"])
        self.empty_label.setWordWrap(True)
        column.addWidget(self.empty_label)

        self.copy_sources_box = QCheckBox(tr("Also put the source spreadsheet itself in the output folder"))
        self.copy_sources_box.setToolTip(tr(
            "The spreadsheet is already printed to PDF. Tick this to also deliver the "
            "spreadsheet file itself next to the PDFs."
        ))
        self.copy_sources_box.stateChanged.connect(diagnostics.guard(self._options_changed))
        column.addWidget(self.copy_sources_box)

        self.copy_attachments_box = QCheckBox(tr("Copy the loaded ready documents (PDF, Word, images) to the output folder"))
        self.copy_attachments_box.setToolTip(tr(
            "Off by default: those files are already in your own folder, so a second copy "
            "is usually not wanted."
        ))
        self.copy_attachments_box.stateChanged.connect(diagnostics.guard(self._options_changed))
        column.addWidget(self.copy_attachments_box)
        return box

    def _section_common(self) -> QGroupBox:
        box = QGroupBox(tr("4  ·  COMMON DETAILS"))
        column = QVBoxLayout(box)
        column.addWidget(hint(tr(
            "Details that several selected documents share, entered once here. Fields that "
            "belong to one document only are in that document's own window."
        )))

        record_row = QHBoxLayout()
        record_row.setSpacing(6)
        record_row.addWidget(QLabel(tr("Saved record")))
        self.record_combo = QComboBox()
        self.record_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        theme.style_dropdown(self.record_combo)
        self.record_combo.currentIndexChanged.connect(diagnostics.guard(self._record_chosen))
        record_row.addWidget(self.record_combo, 1)
        self.record_save = QPushButton(tr("Save"))
        self.record_save.setToolTip(tr(
            "Store the details below as a record; in the next job, pick it from the list."
        ))
        self.record_save.clicked.connect(diagnostics.guard(self._save_record))
        record_row.addWidget(self.record_save)
        self.record_delete = QPushButton(tr("Delete"))
        self.record_delete.setToolTip(tr("Remove the selected record from the library."))
        self.record_delete.clicked.connect(diagnostics.guard(self._delete_record))
        record_row.addWidget(self.record_delete)
        column.addLayout(record_row)

        self.common_form = QFormLayout()
        self.common_form.setSpacing(8)
        self.common_form.setContentsMargins(0, 8, 0, 0)
        column.addLayout(self.common_form)
        self.common_empty = hint(tr("Select documents to see the details they share."))
        column.addWidget(self.common_empty)
        self.fill_record_combo()
        return box

    def _section_output(self) -> QGroupBox:
        box = QGroupBox(tr("5  ·  OUTPUT FOLDER AND PRODUCTION"))
        column = QVBoxLayout(box)
        column.setSpacing(10)

        row = QHBoxLayout()
        self.folder_label = QLabel(tr("No folder chosen."))
        self.folder_label.setWordWrap(True)
        self.folder_label.setStyleSheet(f"color: {theme.COLOURS['text_muted']};")
        button = QPushButton(tr("Choose folder…"))
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(diagnostics.guard(self.choose_output_folder))
        row.addWidget(self.folder_label, 1)
        row.addWidget(button)
        column.addLayout(row)

        # Completeness of the selected documents, shown before producing.
        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.hide()
        column.addWidget(self.summary_label)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.preview_button = QPushButton(tr("Create Preview"))
        self.preview_button.setCursor(Qt.PointingHandCursor)
        self.preview_button.setMinimumHeight(44)
        self.preview_button.setToolTip(tr(
            "Produces the documents temporarily and shows them as PDF. Nothing is written to "
            "the output folder; check them, correct what is needed, then produce."
        ))
        self.preview_button.clicked.connect(diagnostics.guard(self.create_preview))
        buttons.addWidget(self.preview_button, 1)
        self.produce_button = QPushButton(tr("Produce Documents"))
        self.produce_button.setObjectName("primary")
        self.produce_button.setCursor(Qt.PointingHandCursor)
        self.produce_button.clicked.connect(diagnostics.guard(self.produce))
        buttons.addWidget(self.produce_button, 1)
        column.addLayout(buttons)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet(f"color: {theme.COLOURS['accent']}; font-weight: 600;")
        self.status.hide()
        column.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        column.addWidget(self.progress)

        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(diagnostics.guard(self.cancel))
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)
        row.addStretch()
        column.addLayout(row)
        return box

    def _section_result(self) -> QGroupBox:
        box = QGroupBox(tr("6  ·  PREVIEW AND RESULT"))
        column = QVBoxLayout(box)
        column.setSpacing(10)
        # States clearly when documents have not been saved yet.
        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.hide()
        column.addWidget(self.banner)

        self.output_rows = QVBoxLayout()
        self.output_rows.setSpacing(5)
        column.addLayout(self.output_rows)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumHeight(150)
        self.result_text.setPlaceholderText(tr("A summary appears here after the documents are produced."))
        column.addWidget(self.result_text)

        self.open_folder_button = QPushButton(tr("Open output folder"))
        self.open_folder_button.setCursor(Qt.PointingHandCursor)
        self.open_folder_button.clicked.connect(diagnostics.guard(self.open_output_folder))
        self.open_folder_button.setEnabled(False)
        column.addWidget(self.open_folder_button)
        return box

    # ============================================================ templates

    def choose_template_folder(self):
        start = str(settings.template_folder() or "")
        folder = QFileDialog.getExistingDirectory(self, tr("Choose the folder of Word templates"), start)
        if not folder:
            return
        found = templates.discover(folder)
        if not found:
            QMessageBox.information(
                self, tr("No templates found"),
                tr("That folder contains no .docx files.\n\nPut your Word templates in a folder and choose it here."),
            )
            return
        settings.set_workspace(template_folder=folder)
        self.reload_templates()

    def reload_templates(self):
        self.templates = templates.discover(settings.template_folder())
        if self.loaded_files:
            # Fields depend on the templates' placeholders: match again.
            self.load_files([], keep=True)
        else:
            self._fill_document_rows()

    def _templates_by_name(self) -> dict[str, templates.Template]:
        return templates.by_name(self.templates)

    # ================================================================ files

    def load_files(self, paths_list: list[str], keep: bool = False):
        current = list(self.loaded_files)
        for item in paths_list:
            if item not in current:
                current.append(item)
        if not current:
            return

        account = accounts.active()
        try:
            resolution = engine.resolve(current, self.templates, account.profile_values if account else {})
        except Exception as exc:  # noqa: BLE001 - shown to the user
            QMessageBox.critical(self, tr("The files could not be read"), str(exc))
            return

        self._finish_pending_draft()
        self.project = resolution.project
        self.fresh_project = copy.deepcopy(resolution.project)
        self.loaded_files = current
        self.analyses = resolution.analyses
        self.clear_button.setEnabled(True)
        self.remember_button.setEnabled(bool(self.templates))

        # Worked with these exact files before? What was entered comes back.
        self._draft_key = drafts.identity(current)
        record = drafts.load(self._draft_key)
        restored = drafts.apply(self.project, record) if record else 0

        self._draw_analysis(resolution.analyses)
        self._write_info(resolution)
        if record and record.get("document_set"):
            self._apply_draft_choices(record)
        else:
            self._apply_suggestion(resolution.suggestion)
            self._fill_document_rows()
        self.common_from_project()
        self.refresh_badges()
        if restored:
            self.suggestion.show()
            self.suggestion.setText(tr(
                "What you entered with these files before has been restored "
                "(kept as long as the files do not change)."
            ))
            self.suggestion.setStyleSheet(f"color: {theme.COLOURS['success']};")

    def _draw_analysis(self, analyses):
        """One line per loaded file: what it is and what was read from it."""
        while self.analysis_area.count():
            item = self.analysis_area.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        c = theme.COLOURS
        for analysis in analyses:
            row = QFrame()
            row.setStyleSheet(
                f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 6px; }}"
            )
            line = QHBoxLayout(row)
            line.setContentsMargins(10, 6, 10, 6)
            line.setSpacing(8)
            if analysis.recognised:
                state, kind = tr("values read"), "success"
            elif analysis.role == file_analysis.COPY:
                state, kind = tr("ready document"), "accent"
            else:
                state, kind = tr("not used"), "warning"
            badge = QLabel(state)
            badge.setStyleSheet(theme.badge(kind))
            line.addWidget(badge)
            line.addWidget(heading(analysis.name, 9, True))
            summary = heading(analysis.summary(), 8.5, False, c["text_muted"])
            # A long summary must not widen the row: it shrinks and the full
            # text is in the tooltip.
            summary.setMinimumWidth(0)
            summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            summary.setTextFormat(Qt.PlainText)
            line.addWidget(summary, 1)
            details = analysis.details()
            if details:
                row.setToolTip(details)
                summary.setToolTip(details)
            if analysis.sheets:
                sheets = QLabel(tr("{count} sheets").format(count=len(analysis.sheets)))
                sheets.setStyleSheet(theme.badge("neutral"))
                sheets.setToolTip(", ".join(analysis.sheets))
                line.addWidget(sheets)
            view = QPushButton(tr("View content"))
            view.setObjectName("small")
            view.setCursor(Qt.PointingHandCursor)
            view.setToolTip(tr("Shows the file as it is, and which value was read into which field."))
            view.clicked.connect(diagnostics.guard(lambda _=False, a=analysis: self.view_source(a)))
            line.addWidget(view)
            self.analysis_area.addWidget(row)

    def view_source(self, analysis):
        show_source(self.main_window, analysis, self.project, self.jobs)

    def _write_info(self, resolution):
        project = resolution.project
        placeholders = templates.all_placeholders(self.templates)
        matched = sum(1 for name in placeholders if name in project.mapping)
        lines = [
            f"<b style='color:{theme.COLOURS['text']};'>"
            + tr("{values} values read from {files} file(s)").format(
                values=len(project.labels), files=len(project.source_files)
            )
            + "</b>",
            tr("{matched} of {total} template fields were matched to a caption.").format(
                matched=matched, total=len(placeholders)
            ),
        ]
        unreadable = resolution.unreadable_numbers
        if unreadable:
            examples = ", ".join(f"{label} = {raw!r}" for label, raw in unreadable[:3])
            lines.append(
                f"<span style='color:{theme.COLOURS['warning']};'>"
                + tr("{count} value(s) could not be read as numbers ({examples}) — correct them in the document's window if needed.").format(
                    count=len(unreadable), examples=examples
                )
                + "</span>"
            )
        if not self.templates:
            lines.append(
                f"<span style='color:{theme.COLOURS['warning']};'>"
                + tr("No template folder is chosen yet — choose one in section 3.")
                + "</span>"
            )
        self.info.setText("<br>".join(lines))

    def remember_matching(self):
        if self.project is None or not self.templates:
            return
        key = profiles.template_key([t.path for t in self.templates])
        profiles.save(key, profiles.from_project(self.project, templates.all_placeholders(self.templates)))
        self._banner(tr("The field matching was remembered for these templates."), "success")

    def clear_selection(self):
        self._finish_pending_draft()
        self._draft_key = ""
        self.project = None
        self.fresh_project = None
        self.loaded_files = []
        self.analyses = []
        self.info.setText(tr("No files loaded yet."))
        self.suggestion.hide()
        self.clear_button.setEnabled(False)
        self.remember_button.setEnabled(False)
        self._draw_analysis([])
        self.discard_preview()
        self.common_from_project()
        self.refresh_badges()

    def discard_preview(self):
        """Drop the current preview and delete its temporary files."""
        if self.preview is not None:
            self.preview.discard()
            self.preview = None
        self.banner.hide()

    # ========================================================= document set

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

    def _apply_suggestion(self, suggestion):
        self.suggestion.show()
        if suggestion:
            index = self.set_combo.findData(suggestion)
            if index >= 0:
                self.set_combo.blockSignals(True)
                self.set_combo.setCurrentIndex(index)
                self.set_combo.blockSignals(False)
                if self.project is not None:
                    self.project.document_set = suggestion
            self.suggestion.setText(
                tr("Suggested: <b>{name}</b> — please confirm; the program never decides on its own.").format(
                    name=self.set_combo.currentText()
                )
            )
            self.suggestion.setStyleSheet(f"color: {theme.COLOURS['success']};")
        else:
            self.suggestion.setText(tr("No document set could be suggested; please choose one."))
            self.suggestion.setStyleSheet(f"color: {theme.COLOURS['warning']};")

    def _set_changed(self):
        set_id = self.set_combo.currentData()
        other = set_id == document_sets.OTHER
        self.custom_set.setVisible(other)
        if not other:
            self.custom_set.clear()
        if self.project is not None:
            self.project.document_set = set_id
            if not other:
                self.project.custom_set_name = None
        self._fill_document_rows()
        self.common_from_project()

    def _custom_set_named(self):
        if self.project is None:
            return
        self.project.custom_set_name = self.custom_set.text().strip() or None
        self.request_live_preview()

    def _apply_draft_choices(self, record: dict):
        """Put the draft's set, documents and folder back on screen."""
        index = self.set_combo.findData(record.get("document_set"))
        if index >= 0:
            self.set_combo.blockSignals(True)
            self.set_combo.setCurrentIndex(index)
            self.set_combo.blockSignals(False)
        other = record.get("document_set") == document_sets.OTHER
        self.custom_set.setVisible(other)
        self.custom_set.setText(record.get("custom_set_name") or "")
        self._fill_document_rows()
        chosen = record.get("selected")
        if isinstance(chosen, list) and chosen:
            for row in self.rows:
                row.box.setChecked(row.name in chosen)
        folder = record.get("output_folder")
        if folder and Path(folder).is_dir():
            self._set_output_folder(folder)
        self.copy_sources_box.setChecked(bool(record.get("copy_source_spreadsheets")))
        self.copy_attachments_box.setChecked(bool(record.get("copy_attachments")))

    # ======================================================== document list

    def _fill_document_rows(self):
        # deleteLater() alone is not enough: a widget stays on screen until the
        # event loop gets to it and would overlap the new rows.
        for row in self.rows:
            self.rows_area.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self.rows = []

        folder = settings.template_folder()
        self.template_folder_label.setText(
            tr("Templates: {folder}").format(folder=folder) if folder else tr("No template folder chosen.")
        )
        if not self.templates:
            self.empty_label.setText(tr(
                "No templates yet. Choose the folder that holds your Word templates "
                "(documents containing placeholders such as {{ customer_name }})."
            ))
            self.empty_label.show()
            self._update_summary()
            return
        set_id = self.set_combo.currentData()
        required = set(document_sets.required_templates(set_id))
        self.empty_label.setVisible(not set_id)
        self.empty_label.setText(tr(
            "Choose a document set to tick its documents automatically, or tick them yourself."
        ))
        ordered = sorted(self.templates, key=lambda t: (t.name not in required, t.title.casefold()))
        for template in ordered:
            row = DocumentRow(template, template.name in required, lambda: self.project, self)
            row.box.stateChanged.connect(diagnostics.guard(self._selection_changed))
            self.rows_area.addWidget(row)
            self.rows.append(row)
        self._update_summary()

    def _selection_changed(self):
        self.common_from_project()
        self._update_summary()

    def _tick_all(self, state: bool):
        for row in self.rows:
            if row.box.isEnabled():
                row.box.setChecked(state)
        self._update_summary()

    def selected_templates(self) -> list[templates.Template]:
        return [row.template for row in self.rows if row.selected()]

    def refresh_badges(self):
        for row in self.rows:
            row.refresh_badge()
        self._update_summary()

    def _options_changed(self):
        if self.project is not None:
            self.project.copy_source_spreadsheets = self.copy_sources_box.isChecked()
            self.project.copy_attachments = self.copy_attachments_box.isChecked()
        self._update_summary()

    # ======================================================== common details

    def common_from_project(self):
        """Rebuild the common-details form for the selected documents."""
        while self.common_form.rowCount():
            self.common_form.removeRow(0)
        self.common_inputs = {}
        shared = fields.shared_placeholders(self.selected_templates())
        self.common_empty.setVisible(not shared)
        for name in shared:
            box = MemoryInput(name)
            if self.project is not None:
                box.setText(formatting.for_editing(self.project.value(name)))
            box.setPlaceholderText(tr("empty — what you leave empty stays empty in the documents"))
            box.editingFinished.connect(diagnostics.guard(self.common_to_project))
            self.common_inputs[name] = box
            self.common_form.addRow(templates.label(name), box)
        self._mark_automatic_common()

    def _mark_automatic_common(self):
        from ..project import AUTOMATIC_FIELDS

        for name, box in self.common_inputs.items():
            if name in AUTOMATIC_FIELDS:
                box.setReadOnly(True)
                box.setText("")
                box.setPlaceholderText(tr("filled automatically with today's date"))

    def common_to_project(self):
        """Write the common details into the project (so the badges are right)."""
        if self.project is None:
            return
        from ..project import AUTOMATIC_FIELDS

        remembered = {}
        for name, box in self.common_inputs.items():
            if name in AUTOMATIC_FIELDS:
                continue
            text = formatting.single_line(box.text())
            current = formatting.for_editing(self.project.value(name))
            remembered[name] = text
            if text == current:
                continue
            self.project.type_value(name, formatting.from_editing(text, self.project.value(name)) if text else "")
        memory.remember_many(remembered)
        self.refresh_badges()
        self.request_live_preview()

    def fill_record_combo(self, select: str | None = None):
        self.record_combo.blockSignals(True)
        self.record_combo.clear()
        self.record_combo.addItem(tr("— choose a saved record —"), None)
        for record in library.records():
            self.record_combo.addItem(record.name, record.name)
        if select:
            index = self.record_combo.findData(select)
            if index >= 0:
                self.record_combo.setCurrentIndex(index)
        self.record_combo.blockSignals(False)
        self.record_delete.setEnabled(self.record_combo.currentData() is not None)

    def _record_chosen(self):
        name = self.record_combo.currentData()
        self.record_delete.setEnabled(name is not None)
        record = library.find(name)
        if record is None:
            return
        for field, value in record.values.items():
            box = self.common_inputs.get(field)
            if box is not None:
                box.setText(value)
            elif self.project is not None and value:
                # A field the record knows but that is not "common" here: it is
                # still filled, in the documents that use it.
                self.project.type_value(field, value)
        self.common_to_project()

    def _save_record(self):
        values = {name: box.text().strip() for name, box in self.common_inputs.items() if box.text().strip()}
        if not values:
            QMessageBox.warning(self, tr("Nothing to save"), tr("Fill in some common details first."))
            return
        suggested = self.record_combo.currentData() or next(iter(values.values()))
        name, ok = QInputDialog.getText(self, tr("Save record"), tr("Name of the record:"), text=suggested)
        if not ok or not name.strip():
            return
        existing = library.find(name)
        merged = dict(existing.values) if existing else {}
        merged.update(values)
        record = library.save(library.Record(name=name, values=merged))
        self.fill_record_combo(select=record.name)
        self.main_window.records_changed()
        self._banner(tr("'{name}' was saved to the library; pick it from the list in the next job.").format(name=record.name), "success")

    def _delete_record(self):
        name = self.record_combo.currentData()
        if not name:
            return
        if QMessageBox.question(
            self, tr("Delete record"), tr("Remove '{name}' from the library?\n(The fields below are not cleared.)").format(name=name)
        ) != QMessageBox.Yes:
            return
        library.delete(name)
        self.fill_record_combo()
        self.main_window.records_changed()

    # ============================================================== summary

    def _update_summary(self):
        self._request_draft()
        selected = self.selected_templates()
        if self.project is None or not selected:
            self.summary_label.hide()
            return
        overview = fields.summary(selected, self.project)
        required = sum(o["required_missing"] for o in overview)
        empty = sum(o["missing"] for o in overview)
        if required:
            problems = [f"{o['title']} ({o['required_missing']})" for o in overview if o["required_missing"]]
            text = tr("<b>{count} documents selected.</b> {required} required field(s) are empty: {list}. The documents are still produced, with those fields blank.").format(
                count=len(selected), required=required, list=", ".join(problems)
            )
            kind = "warning"
        elif empty:
            text = tr("<b>{count} documents selected.</b> All required fields are filled; {empty} optional field(s) are empty.").format(
                count=len(selected), empty=empty
            )
            kind = "neutral"
        else:
            text = tr("<b>{count} documents selected.</b> All fields are filled.").format(count=len(selected))
            kind = "success"
        if self.preview is not None and self.preview.valid:
            if self.preview.is_stale(self.project, selected):
                text += "<br><span style='color:%s;'>%s</span>" % (
                    theme.COLOURS["warning"],
                    tr("The preview is out of date — data or the selection changed since. 'Produce Documents' will produce them again."),
                )
            else:
                text += "<br><span style='color:%s;'>%s</span>" % (
                    theme.COLOURS["success"],
                    tr("The preview is up to date — 'Produce Documents' will write it to the folder without producing again."),
                )
        self.request_live_preview(draft=False)
        self.summary_label.setText(text)
        self.summary_label.setStyleSheet(theme.banner(kind))
        self.summary_label.show()

    # ================================================================ drafts

    def _request_draft(self):
        if self._draft_key and self.project is not None:
            self._draft_timer.start()

    def _finish_pending_draft(self):
        if self._draft_timer.isActive():
            self._draft_timer.stop()
            self._save_draft()

    def _save_draft(self):
        """Keep what the user entered, tied to these files (see drafts.py)."""
        if not self._draft_key or self.project is None or self.fresh_project is None:
            return
        try:
            record = drafts.capture(
                self.fresh_project,
                self.project,
                selected=[row.name for row in self.rows if row.selected()],
                output_folder=self.output_folder,
                files=[Path(p).name for p in self.loaded_files],
            )
            drafts.save(self._draft_key, record)
        except Exception:  # noqa: BLE001 - a draft failing must never interrupt work
            diagnostics.write("Draft could not be saved:\n" + traceback.format_exc())

    # ============================================================ production

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, tr("Choose the output folder"), self.output_folder or settings.workspace()["last_output_folder"]
        )
        if not folder:
            return
        # Windows' 260-character path limit: a deep folder plus a long document
        # name makes Word report "directory is not valid". Said here, plainly,
        # not halfway through production.
        problem = paths.path_length_problem(folder)
        if problem:
            QMessageBox.warning(self, tr("Folder path is very long"), problem)
        problem = paths.writable_problem(folder)
        if problem:
            QMessageBox.critical(self, tr("Cannot write to the folder"), problem)
            return
        self._set_output_folder(folder)
        settings.set_workspace(last_output_folder=folder)
        self._request_draft()

    def _set_output_folder(self, folder: str):
        self.output_folder = folder
        self.folder_label.setText(folder)
        self.folder_label.setStyleSheet(f"color: {theme.COLOURS['text']}; font-weight: 600;")

    def _prepare(self, folder_needed: bool, quiet: bool = False) -> list[templates.Template] | None:
        """Check the preconditions and write the forms into the project.

        Returns the selected templates, or None. When `quiet` (a live preview
        refresh) no message box opens: the user must not be interrupted while
        typing; the refresh just waits.
        """

        def warn(title: str, text: str) -> None:
            if not quiet:
                QMessageBox.warning(self, title, text)

        if self.project is None:
            warn(tr("Missing"), tr("Load the project files first."))
            return None
        set_id = self.set_combo.currentData()
        if not set_id:
            warn(tr("Missing"), tr("Choose the document set."))
            return None
        if folder_needed and not self.output_folder:
            warn(tr("Missing"), tr("Choose the output folder."))
            return None
        selected = self.selected_templates()
        if not selected:
            warn(tr("Missing"), tr("Select at least one document (Documents to produce)."))
            return None
        self.project.document_set = set_id
        if set_id == document_sets.OTHER:
            name = self.custom_set.text().strip()
            if not name:
                warn(tr("Missing"), tr("Name this kind of job (\"Other\" was chosen)."))
                return None
            self.project.custom_set_name = name
        self.project.copy_source_spreadsheets = self.copy_sources_box.isChecked()
        self.project.copy_attachments = self.copy_attachments_box.isChecked()
        if not quiet:
            self.common_to_project()
            self._remember_set_defaults(set_id)
        return selected

    def _remember_set_defaults(self, set_id):
        """A value typed for a field the set keeps a default for becomes the
        set's new default, so the next job of this kind starts with it."""
        document_set = document_sets.get(set_id)
        if document_set is None or not document_set.defaults:
            return
        changed = False
        for name in document_set.defaults:
            value = self.project.typed.get(name)
            if value not in (None, "") and document_set.defaults[name] != str(value):
                document_set.defaults[name] = formatting.single_line(str(value))
                changed = True
        if changed:
            document_sets.save(document_set)

    def _busy(self, status: str, cancellable: bool = True, quiet: bool = False):
        self.preview_button.setEnabled(False)
        self.produce_button.setEnabled(False)
        self.status.setText(status)
        self.status.show()
        self.progress.show()
        self.cancel_button.setText(tr("Cancel"))
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(cancellable)
        if quiet:
            # A live refresh: the list and open preview windows stay in place;
            # only their contents are updated.
            return
        self.result_text.clear()
        self._clear_output_rows()

    def _idle(self):
        self.preview_button.setEnabled(True)
        self.produce_button.setEnabled(True)
        self.status.hide()
        self.progress.hide()
        self.cancel_button.hide()

    def busy(self) -> bool:
        if not is_running(self._worker):
            self._worker = None
            return False
        return True

    def cancel(self):
        """Stop the running job at the next document."""
        if not self.busy():
            return
        self._worker.request_cancel()
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText(tr("Cancelling…"))
        self.status.setText(tr(
            "Cancelling — the document being converted is finished first (Word's work cannot be interrupted)."
        ))

    # -------------------------------------------------------------- preview

    def create_preview(self, quiet: bool = False):
        """Produce temporarily and show as PDF; nothing goes to the output folder."""
        selected = self._prepare(folder_needed=False, quiet=quiet)
        if selected is None:
            return
        previous = self.preview
        project = self.project
        self._quiet_refresh = quiet

        def work(is_cancelled):
            return engine.build_preview(project, selected, is_cancelled=is_cancelled, previous=previous)

        if quiet:
            self._busy(tr("Updating the preview…"), quiet=True)
        else:
            self._busy(tr("{count} document(s) are being produced for the preview… (nothing is written to the output folder)").format(count=len(selected)))
        self._worker = self.jobs.start(Worker(work), self._preview_done)

    def request_live_preview(self, draft: bool = True) -> None:
        """A field changed: an existing preview refreshes itself.

        Only when a preview already exists — otherwise nothing is produced (the
        user has not asked for one). The change always goes into the draft.
        """
        if draft:
            self._request_draft()
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
        if selected is None:
            return
        if not self.preview.is_stale(self.project, selected):
            return
        self.create_preview(quiet=True)

    def _refresh_open_previews(self):
        """Point open preview windows at the newly produced files."""
        if not self._open_previews or self.preview is None:
            return
        for name, window in list(self._open_previews.items()):
            new_file = self.preview.folder / name
            try:
                if new_file.exists():
                    window.reload(new_file)
                else:
                    window.set_subtitle(tr("This document is no longer selected — the preview was not updated."))
            except RuntimeError:
                self._open_previews.pop(name, None)

    def _preview_done(self, preview):
        self._worker = None
        self._idle()
        if isinstance(preview, Exception):
            self.result_text.setPlainText(tr("ERROR: {error}").format(error=preview))
            return
        if self.preview is not None and self.preview is not preview:
            self.preview.discard()
        self.preview = preview
        result = preview.result
        self.last_result = result
        self._draw_output_rows(result)
        self.result_text.setPlainText(self._result_text(result))
        self._refresh_open_previews()
        if self._refresh_pending:
            self._refresh_pending = False
            self._live_timer.start()
        if result.cancelled:
            self._banner(tr("The preview was cancelled — below is what was produced before cancelling."), "warning")
        else:
            self._banner(
                tr("<b>PREVIEW — the documents have not been saved yet</b> ({time}). Check them with "
                   "<b>Preview</b> on each row. When you change a field the preview <b>updates itself</b>, "
                   "and open preview windows refresh in place. When everything is right, write them to "
                   "the folder with <b>Produce Documents</b>.").format(time=duration_text(result.seconds)),
                "accent",
            )
        self._update_summary()

    def _banner(self, text: str, kind: str):
        self.banner.setText(text)
        self.banner.setStyleSheet(theme.banner(kind))
        self.banner.show()

    # ------------------------------------------------------------- produce

    def produce(self):
        selected = self._prepare(folder_needed=True)
        if selected is None:
            return
        # A valid, up-to-date preview is NOT produced again: its files are
        # copied (Word and Excel are not even started).
        preview = self.preview
        if preview is not None and preview.valid and not preview.is_stale(self.project, selected):
            self._busy(tr("The documents you previewed are being written to the folder…"), cancellable=False)
            try:
                result = engine.place_preview(preview, self.output_folder)
            except Exception as exc:  # noqa: BLE001
                result = engine.JobResult(project=self.project, error=f"{exc}\n\n{traceback.format_exc()}")
            self._produced(result)
            return

        project, folder = self.project, self.output_folder

        def work(is_cancelled):
            return engine.produce(project, selected, folder, is_cancelled=is_cancelled, reuse=preview)

        self._busy(tr("{count} document(s) are being filled, checked and converted to PDF…").format(count=len(selected)))
        self._worker = self.jobs.start(Worker(work), self._produced)

    def _produced(self, result):
        self._worker = None
        self._idle()
        if isinstance(result, Exception):
            result = engine.JobResult(project=self.project, error=str(result))
        self.last_result = result
        self._draw_output_rows(result)
        self.result_text.setPlainText(self._result_text(result))
        self.open_folder_button.setEnabled(bool(self.output_folder))
        if result.cancelled:
            self._banner(tr("Production was cancelled — only the files written before cancelling are in the folder. Run it again for a complete result."), "warning")
        elif not result.error:
            self._banner(tr("The documents were written to the output folder <b>({time})</b>.").format(time=duration_text(result.seconds)), "success")
        # Only the record of the job is logged, never the documents.
        if not result.error and not result.cancelled:
            history.record(result, self.output_folder)
            self.main_window.history_changed()

    # ---------------------------------------------------------- output rows

    def _clear_output_rows(self):
        while self.output_rows.count():
            item = self.output_rows.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

    def _output_row(self, file: Path, kind: str, note: str = "") -> QFrame:
        c = theme.COLOURS
        row = QFrame()
        row.setStyleSheet(f"QFrame {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 6px; }}")
        line = QHBoxLayout(row)
        line.setContentsMargins(10, 6, 10, 6)
        line.setSpacing(8)
        badge = QLabel(kind)
        badge.setStyleSheet(theme.badge("success" if kind == "PDF" else "neutral"))
        line.addWidget(badge)
        line.addWidget(heading(file.name, 9, True), 1)
        if note:
            warning = QLabel(note)
            warning.setStyleSheet(theme.badge("warning"))
            line.addWidget(warning)
        preview = QPushButton(tr("Preview"))
        preview.setObjectName("small")
        preview.setCursor(Qt.PointingHandCursor)
        preview.clicked.connect(diagnostics.guard(lambda _=False, f=file: self.open_preview(f)))
        line.addWidget(preview)
        return row

    def _draw_output_rows(self, result):
        self._clear_output_rows()
        problems = {Path(c.document).stem for c in result.problems}
        for pdf in result.pdfs:
            self.output_rows.addWidget(self._output_row(pdf, "PDF"))
        for copied in result.copied_files:
            self.output_rows.addWidget(self._output_row(copied, tr("copy")))
        for docx in result.editable:
            self.output_rows.addWidget(
                self._output_row(docx, "Word", tr("validation warning") if docx.stem in problems else "")
            )

    def open_preview(self, file: Path):
        """Open a document in a MODELESS window.

        Modeless on purpose: with the window open the user can keep correcting
        fields and watch the change reach the document.
        """
        try:
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
        except Exception as exc:  # noqa: BLE001 - a preview failing never affects production
            diagnostics.write("Preview window could not be opened:\n" + traceback.format_exc())
            QMessageBox.warning(
                self, tr("Preview unavailable"),
                tr("{name} could not be previewed:\n\n{error}\n\nOpen it from the output folder instead.").format(name=file.name, error=exc),
            )

    @staticmethod
    def _result_text(result) -> str:
        lines = []
        if result.error:
            lines.append(tr("ERROR: {error}").format(error=result.error))
        if result.seconds:
            lines.append(tr("Time: {time}").format(time=duration_text(result.seconds)))
        if result.project is not None and result.project.reference():
            lines.append(tr("Reference: {value}").format(value=result.project.reference()))
        if result.checks:
            passed = [c for c in result.checks if c.passed]
            lines.append("\n" + tr("Validation: {passed}/{total} documents without problems").format(passed=len(passed), total=len(result.checks)))
            for check in result.problems:
                lines.append(f"   {Path(check.document).stem}: {check.message()}")
        if result.pdfs:
            lines.append("\n" + tr("PDFs produced ({count})").format(count=len(result.pdfs)))
            lines += [f"   {p.name}" for p in result.pdfs]
        if result.copied_files:
            lines.append("\n" + tr("Copied files ({count})").format(count=len(result.copied_files)))
            lines += [f"   {p.name}" for p in result.copied_files]
        if result.editable:
            lines.append("\n" + tr("Editable Word files in the '{folder}' folder ({count})").format(folder=engine.EDITABLE_FOLDER, count=len(result.editable)))
            lines += [f"   {p.name}" for p in result.editable]
        if result.notes:
            lines.append("")
            lines += [tr("NOTE  {text}").format(text=n) for n in result.notes]
        if result.skipped:
            lines.append("\n" + tr("Skipped"))
            lines += [f"   {name}: {reason}" for name, reason in result.skipped]
        if result.warnings:
            lines.append("\n" + tr("Warnings"))
            lines += [f"   {w}" for w in result.warnings]
        lines.append("\n" + tr("Please do the final check yourself."))
        return "\n".join(lines)

    def open_output_folder(self):
        if not self.output_folder:
            return
        try:
            os.startfile(self.output_folder)  # noqa: S606
        except OSError as exc:
            QMessageBox.warning(self, tr("The folder could not be opened"), f"{self.output_folder}\n\n{exc}")

    # -------------------------------------------------------------- state

    def state(self) -> dict:
        """What must survive rebuilding the window (theme or language change)."""
        self._finish_pending_draft()
        return {"files": list(self.loaded_files), "folder": self.output_folder}

    def restore(self, state: dict) -> None:
        if state.get("files"):
            try:
                self.load_files(state["files"])
            except Exception:  # noqa: BLE001, S110 - restoring is not critical
                pass
        if state.get("folder"):
            self._set_output_folder(state["folder"])

    def shut_down(self):
        self._finish_pending_draft()
        self.discard_preview()


def show_source(main_window, analysis, project, jobs: JobManager) -> None:
    """Convert a loaded file to PDF and show it as it is.

    Converting happens in the background (a fraction of a second when Office is
    already running, a few seconds the first time); the window does not freeze.
    A file opened a second time comes from the cache.
    """
    from PySide6.QtWidgets import QApplication

    waiting = QMessageBox(main_window)
    waiting.setWindowTitle(tr("Preparing"))
    waiting.setText(tr("'{name}' is being prepared for viewing…").format(name=analysis.name))
    waiting.setStandardButtons(QMessageBox.NoButton)
    waiting.show()
    QApplication.processEvents()

    if analysis.role == file_analysis.COPY and analysis.path.suffix.lower() not in (".pdf", ".doc", ".docx", ".docm"):
        waiting.close()
        os.startfile(str(analysis.path))  # noqa: S606 - an image: the system viewer shows it
        return

    def work(_is_cancelled):
        return engine.source_to_pdf(analysis.path)

    def finished(result):
        waiting.close()
        if isinstance(result, Exception):
            diagnostics.write(f"Source preview error: {result}")
            QMessageBox.warning(
                main_window, tr("Could not be shown"),
                tr("{name} could not be shown:\n\n{error}\n\nYou can still see the values that were read.").format(name=analysis.name, error=result),
            )
            dialogs.SourceContentDialog(main_window, analysis, project).exec()
            return
        dialogs.PreviewDialog(main_window, result, analysis=analysis if analysis.role == file_analysis.DATA else None, project=project).exec()

    jobs.start(Worker(work), finished)
