"""Library page — details that recur in every job, kept in one place.

Four sections:
  1. **Account profile** — your own details that belong in documents (name,
     title, licence or registration number…). They fill the matching fields of
     every job automatically.
  2. **Record library** — named groups of values (a customer, a supplier, an
     issuing organisation). Picked from a list on the production pages.
  3. **Document sets** — which documents each kind of job needs, which of
     their fields are required, and standard values.
  4. **Field memory** — how many values each field remembers; clear on demand.

Nothing goes to the cloud; all of it lives in the signed-in account's folder.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import accounts, diagnostics, document_sets, drafts, library, memory, profiles, settings, templates
from ..i18n import tr
from . import theme
from .widgets import heading, hint


def _key_value_table(headers: tuple[str, str], minimum_height: int = 150) -> QTableWidget:
    table = QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(list(headers))
    table.verticalHeader().setVisible(False)
    table.setMinimumHeight(minimum_height)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
    return table


def _table_to_dict(table: QTableWidget) -> dict[str, str]:
    result = {}
    for row in range(table.rowCount()):
        key_item, value_item = table.item(row, 0), table.item(row, 1)
        key = key_item.text().strip() if key_item else ""
        if key:
            result[key] = value_item.text() if value_item else ""
    return result


def _dict_to_table(table: QTableWidget, values: dict[str, str], extra_rows: int = 1) -> None:
    table.setRowCount(len(values) + extra_rows)
    for row, (key, value) in enumerate(values.items()):
        table.setItem(row, 0, QTableWidgetItem(key))
        table.setItem(row, 1, QTableWidgetItem(value))
    for row in range(len(values), len(values) + extra_rows):
        table.setItem(row, 0, QTableWidgetItem(""))
        table.setItem(row, 1, QTableWidgetItem(""))


class LibraryPage(QWidget):
    RECORD_COLUMNS = ("Name", "Fields")

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._editing_record: str | None = None
        self._editing_set: str | None = None
        self._set_template_boxes: dict[str, QCheckBox] = {}
        self._build()
        self.refresh()

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
        layout.addWidget(self._section_profile())
        layout.addWidget(self._section_records())
        layout.addWidget(self._section_sets())
        layout.addWidget(self._section_memory())
        layout.addStretch()

    # ---------------------------------------------------------- 1 profile

    def _section_profile(self) -> QGroupBox:
        box = QGroupBox(tr("1  ·  ACCOUNT PROFILE"))
        column = QVBoxLayout(box)
        column.addWidget(hint(tr(
            "Details that are yours and stay the same in every job — your name, title, licence "
            "or registration number. Enter the field name exactly as it appears in the templates "
            "(for example engineer_name); every document with that field receives the value."
        )))
        form = QFormLayout()
        form.setSpacing(8)
        self.account_label = QLabel("—")
        self.role_input = QLineEdit()
        self.role_input.setPlaceholderText(tr("Shown under your name in the sidebar"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText(tr("leave empty to keep the current password"))
        form.addRow(tr("Account"), self.account_label)
        form.addRow(tr("Role"), self.role_input)
        form.addRow(tr("New password"), self.password_input)
        column.addLayout(form)
        self.profile_table = _key_value_table((tr("Field"), tr("Value")), 140)
        column.addWidget(self.profile_table)
        row = QHBoxLayout()
        add = QPushButton(tr("Add a field"))
        add.clicked.connect(lambda: self.profile_table.insertRow(self.profile_table.rowCount()))
        row.addWidget(add)
        save = QPushButton(tr("Save profile"))
        save.setObjectName("primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(diagnostics.guard(self._save_profile))
        row.addWidget(save)
        row.addStretch()
        column.addLayout(row)
        return box

    def _save_profile(self):
        account = accounts.active()
        if account is None:
            QMessageBox.information(self, tr("No account"), tr("Sign in with an account first."))
            return
        account.role = self.role_input.text().strip()
        account.profile_values = _table_to_dict(self.profile_table)
        accounts.update(account)
        if self.password_input.text():
            accounts.change_password(account, self.password_input.text())
            self.password_input.clear()
        QMessageBox.information(self, tr("Saved"), tr("The profile was saved for this account."))
        self.main_window.profile_changed()

    # ---------------------------------------------------------- 2 records

    def _section_records(self) -> QGroupBox:
        box = QGroupBox(tr("2  ·  RECORD LIBRARY"))
        column = QVBoxLayout(box)
        column.addWidget(hint(tr(
            "Enter once, pick in every job. The 'Saved record' lists on the production pages "
            "show these records."
        )))
        self.record_table = QTableWidget(0, len(self.RECORD_COLUMNS))
        self.record_table.setHorizontalHeaderLabels([tr(c) for c in self.RECORD_COLUMNS])
        self.record_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.record_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.record_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.record_table.setAlternatingRowColors(True)
        self.record_table.verticalHeader().setVisible(False)
        self.record_table.setMinimumHeight(170)
        header = self.record_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.record_table.itemSelectionChanged.connect(diagnostics.guard(self._record_selected))
        column.addWidget(self.record_table)
        self.record_count = heading("", 8.5, False, theme.COLOURS["text_muted"])
        column.addWidget(self.record_count)

        form = QFormLayout()
        form.setSpacing(8)
        self.record_name = QLineEdit()
        form.addRow(tr("Record name"), self.record_name)
        column.addLayout(form)
        self.record_values = _key_value_table((tr("Field"), tr("Value")), 150)
        column.addWidget(self.record_values)
        column.addWidget(hint(tr(
            "To add a new record, fill in the fields and press 'Save record' — add as many as you "
            "like. To change an existing one, select it in the table first."
        )))
        row = QHBoxLayout()
        row.setSpacing(8)
        new = QPushButton(tr("New / clear"))
        new.setCursor(Qt.PointingHandCursor)
        new.clicked.connect(diagnostics.guard(self._clear_record_form))
        add_field = QPushButton(tr("Add a field"))
        add_field.clicked.connect(lambda: self.record_values.insertRow(self.record_values.rowCount()))
        save = QPushButton(tr("Save record"))
        save.setObjectName("primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(diagnostics.guard(self._save_record))
        delete = QPushButton(tr("Delete selected"))
        delete.setCursor(Qt.PointingHandCursor)
        delete.clicked.connect(diagnostics.guard(self._delete_record))
        for button in (new, add_field, save, delete):
            row.addWidget(button)
        row.addStretch()
        column.addLayout(row)
        return box

    def _record_selected(self):
        row = self.record_table.currentRow()
        if row < 0 or self.record_table.item(row, 0) is None:
            return
        record = library.find(self.record_table.item(row, 0).text())
        if record is None:
            return
        self._editing_record = record.name
        self.record_name.setText(record.name)
        _dict_to_table(self.record_values, record.values)

    def _clear_record_form(self):
        self._editing_record = None
        self.record_name.clear()
        _dict_to_table(self.record_values, {}, extra_rows=4)
        self.record_table.clearSelection()

    def _save_record(self):
        """Add a new record or update the SELECTED one.

        After saving, the form is CLEARED and the selection removed, so several
        records can be added one after another. (Keeping the saved one marked
        as "being edited" made the next save overwrite it, leaving only one
        record in the library.)
        """
        name = self.record_name.text().strip()
        if not name:
            QMessageBox.warning(self, tr("Missing"), tr("The record name cannot be empty."))
            return
        row = self.record_table.currentRow()
        selected = self.record_table.item(row, 0).text() if row >= 0 and self.record_table.item(row, 0) else None
        renaming = (
            self._editing_record and selected and selected == self._editing_record
            and library.find(name) is None
        )
        if renaming:
            library.delete(self._editing_record)
        library.save(library.Record(name=name, values=_table_to_dict(self.record_values)))
        self._clear_record_form()
        self.refresh()
        self.main_window.records_changed()

    def _delete_record(self):
        row = self.record_table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr("Nothing selected"), tr("Select a record in the list."))
            return
        name = self.record_table.item(row, 0).text()
        if QMessageBox.question(self, tr("Delete record"), tr("Delete '{name}'?").format(name=name)) != QMessageBox.Yes:
            return
        library.delete(name)
        self._clear_record_form()
        self.refresh()
        self.main_window.records_changed()

    # ------------------------------------------------------------- 3 sets

    def _section_sets(self) -> QGroupBox:
        box = QGroupBox(tr("3  ·  DOCUMENT SETS"))
        column = QVBoxLayout(box)
        column.addWidget(hint(tr(
            "A document set describes one kind of job: which templates it needs (they come "
            "ticked and marked 'required'), which of their fields must not be empty, standard "
            "values, and words that, found in a source file, suggest this set."
        )))
        row = QHBoxLayout()
        self.set_list = QListWidget()
        self.set_list.setMaximumWidth(260)
        self.set_list.currentItemChanged.connect(diagnostics.guard(self._set_selected))
        row.addWidget(self.set_list)

        editor = QVBoxLayout()
        form = QFormLayout()
        form.setSpacing(8)
        self.set_name = QLineEdit()
        self.set_keywords = QLineEdit()
        self.set_keywords.setPlaceholderText(tr("comma separated, e.g. installation, inspection"))
        self.set_source_pdf = QCheckBox(tr("Also print the source spreadsheet to PDF"))
        self.set_source_pdf.setChecked(True)
        form.addRow(tr("Name"), self.set_name)
        form.addRow(tr("Keywords"), self.set_keywords)
        form.addRow("", self.set_source_pdf)
        editor.addLayout(form)

        editor.addWidget(heading(tr("Templates in this set"), 9, True))
        self.set_templates_area = QVBoxLayout()
        self.set_templates_area.setSpacing(2)
        editor.addLayout(self.set_templates_area)

        editor.addWidget(heading(tr("Required fields (template → field names, comma separated)"), 9, True))
        self.set_required = _key_value_table((tr("Template"), tr("Required fields")), 110)
        editor.addWidget(self.set_required)
        editor.addWidget(heading(tr("Standard values"), 9, True))
        self.set_defaults = _key_value_table((tr("Field"), tr("Value")), 110)
        editor.addWidget(self.set_defaults)

        buttons = QHBoxLayout()
        new = QPushButton(tr("New set"))
        new.clicked.connect(diagnostics.guard(self._new_set))
        add_default = QPushButton(tr("Add a value"))
        add_default.clicked.connect(lambda: self.set_defaults.insertRow(self.set_defaults.rowCount()))
        save = QPushButton(tr("Save set"))
        save.setObjectName("primary")
        save.clicked.connect(diagnostics.guard(self._save_set))
        delete = QPushButton(tr("Delete set"))
        delete.clicked.connect(diagnostics.guard(self._delete_set))
        for button in (new, add_default, save, delete):
            buttons.addWidget(button)
        buttons.addStretch()
        editor.addLayout(buttons)
        row.addLayout(editor, 1)
        column.addLayout(row)
        return box

    def _fill_set_templates(self, ticked: list[str]):
        while self.set_templates_area.count():
            item = self.set_templates_area.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._set_template_boxes = {}
        found = templates.discover(settings.template_folder())
        if not found:
            self.set_templates_area.addWidget(hint(tr("No template folder chosen — choose it on the Documents page.")))
            return
        names = {t.name for t in found}
        for template in found:
            box = QCheckBox(template.title)
            box.setChecked(template.name in ticked)
            self._set_template_boxes[template.name] = box
            self.set_templates_area.addWidget(box)
        for missing in [n for n in ticked if n not in names]:
            box = QCheckBox(tr("{name} (not in the template folder)").format(name=missing))
            box.setChecked(True)
            self._set_template_boxes[missing] = box
            self.set_templates_area.addWidget(box)

    def _set_selected(self, current, _previous=None):
        if current is None:
            return
        document_set = document_sets.get(current.data(Qt.UserRole))
        if document_set is None:
            return
        self._editing_set = document_set.id
        self.set_name.setText(document_set.name)
        self.set_keywords.setText(", ".join(document_set.keywords))
        self.set_source_pdf.setChecked(document_set.export_source_pdf)
        self._fill_set_templates(document_set.templates)
        _dict_to_table(self.set_required, {k: ", ".join(v) for k, v in document_set.required_fields.items()})
        _dict_to_table(self.set_defaults, document_set.defaults)

    def _new_set(self):
        self._editing_set = None
        self.set_list.clearSelection()
        self.set_name.clear()
        self.set_keywords.clear()
        self.set_source_pdf.setChecked(True)
        self._fill_set_templates([])
        _dict_to_table(self.set_required, {}, extra_rows=2)
        _dict_to_table(self.set_defaults, {}, extra_rows=2)

    def _save_set(self):
        name = self.set_name.text().strip()
        if not name:
            QMessageBox.warning(self, tr("Missing"), tr("Give the document set a name."))
            return
        required = {
            template: [f.strip() for f in names.split(",") if f.strip()]
            for template, names in _table_to_dict(self.set_required).items()
        }
        document_set = document_sets.DocumentSet(
            id=self._editing_set or "",
            name=name,
            templates=[n for n, box in self._set_template_boxes.items() if box.isChecked()],
            required_fields={k: v for k, v in required.items() if v},
            defaults=_table_to_dict(self.set_defaults),
            export_source_pdf=self.set_source_pdf.isChecked(),
            keywords=[k.strip() for k in self.set_keywords.text().split(",") if k.strip()],
        )
        saved = document_sets.save(document_set)
        self._editing_set = saved.id
        self.refresh(select_set=saved.id)
        self.main_window.sets_changed()

    def _delete_set(self):
        if not self._editing_set:
            return
        if QMessageBox.question(self, tr("Delete set"), tr("Delete the document set '{name}'?").format(name=self.set_name.text())) != QMessageBox.Yes:
            return
        document_sets.delete(self._editing_set)
        self._new_set()
        self.refresh()
        self.main_window.sets_changed()

    # ----------------------------------------------------------- 4 memory

    def _section_memory(self) -> QGroupBox:
        box = QGroupBox(tr("4  ·  FIELD MEMORY"))
        column = QVBoxLayout(box)
        column.addWidget(hint(tr(
            "Values you type into fields collect here; in the next job, pick them from the arrow "
            "next to the same field."
        )))
        self.memory_list = QListWidget()
        self.memory_list.setMaximumHeight(160)
        column.addWidget(self.memory_list)
        form = QFormLayout()
        self.excluded_input = QLineEdit()
        self.excluded_input.setPlaceholderText(tr("comma separated field names, e.g. serial_number"))
        self.excluded_input.setToolTip(tr(
            "Fields whose value belongs to one job only. They are never remembered, so last "
            "job's value cannot slip into this one."
        ))
        form.addRow(tr("Never remember"), self.excluded_input)
        column.addLayout(form)
        row = QHBoxLayout()
        save = QPushButton(tr("Save"))
        save.clicked.connect(diagnostics.guard(self._save_excluded))
        clear = QPushButton(tr("Clear memory"))
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(diagnostics.guard(self._clear_memory))
        mappings = QPushButton(tr("Forget remembered matchings"))
        mappings.clicked.connect(diagnostics.guard(self._clear_mappings))
        draft = QPushButton(tr("Forget drafts"))
        draft.clicked.connect(diagnostics.guard(self._clear_drafts))
        for button in (save, clear, mappings, draft):
            row.addWidget(button)
        row.addStretch()
        column.addLayout(row)
        return box

    def _save_excluded(self):
        memory.set_excluded([f for f in self.excluded_input.text().split(",")])
        self.refresh()

    def _clear_memory(self):
        if QMessageBox.question(
            self, tr("Clear memory"),
            tr("Delete every value you have typed into fields?\n(The record library and history are not affected.)"),
        ) != QMessageBox.Yes:
            return
        memory.clear()
        self.refresh()

    def _clear_mappings(self):
        if QMessageBox.question(self, tr("Forget matchings"), tr("Forget every remembered field matching?")) == QMessageBox.Yes:
            profiles.clear()

    def _clear_drafts(self):
        if QMessageBox.question(self, tr("Forget drafts"), tr("Forget what was entered for earlier files?")) == QMessageBox.Yes:
            drafts.clear()

    # ============================================================== refresh

    def refresh(self, select_set: str | None = None):
        account = accounts.active()
        self.account_label.setText(account.name if account else tr("(no account signed in)"))
        if account:
            self.role_input.setText(account.role)
            _dict_to_table(self.profile_table, account.profile_values)

        records = library.records()
        self.record_table.setRowCount(len(records))
        for row, record in enumerate(records):
            self.record_table.setItem(row, 0, QTableWidgetItem(record.name))
            self.record_table.setItem(row, 1, QTableWidgetItem(", ".join(f"{k}: {v}" for k, v in record.values.items())))
        self.record_count.setText(
            tr("{count} records saved").format(count=len(records)) if records else tr("No records yet")
        )
        if not self.record_name.text():
            _dict_to_table(self.record_values, {}, extra_rows=4)

        self.set_list.blockSignals(True)
        self.set_list.clear()
        for document_set in document_sets.all_sets():
            item = QListWidgetItem(document_set.name)
            item.setData(Qt.UserRole, document_set.id)
            self.set_list.addItem(item)
            if document_set.id == select_set:
                self.set_list.setCurrentItem(item)
        self.set_list.blockSignals(False)
        if self._editing_set is None:
            self._new_set()

        self.memory_list.clear()
        for field, count in memory.summary():
            QListWidgetItem(tr("{field}  ·  {count} value(s)").format(field=templates.label(field), count=count), self.memory_list)
        if self.memory_list.count() == 0:
            QListWidgetItem(tr("(no values remembered yet)"), self.memory_list)
        self.excluded_input.setText(", ".join(memory.excluded()))
