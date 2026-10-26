"""History page — jobs produced earlier.

Document CONTENTS are not kept; the list shows only the record of each job, and
the user is taken to the job's output folder.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import diagnostics, history
from ..i18n import tr
from . import theme
from .widgets import heading


class HistoryPage(QWidget):
    # (title, fixed width) — None fills the remaining space. Widths avoid a
    # horizontal scroll bar at the default window size; every column can still
    # be widened by hand.
    COLUMNS = (
        ("Date / time", 118),
        ("Document set", 160),
        ("Subject", 170),
        ("Reference", 130),
        ("Docs", 52),
        ("Output folder", None),
    )

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.entries: list[history.Entry] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(12)

        top = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(heading(tr("History"), 14))
        note = heading(
            tr("Jobs produced on this computer. The documents themselves are not stored in the "
               "program — only the folder they were saved in."),
            8.5, False, theme.COLOURS["text_muted"],
        )
        note.setWordWrap(True)
        titles.addWidget(note)
        top.addLayout(titles, 1)
        refresh = QPushButton(tr("Refresh"))
        refresh.setObjectName("small")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(diagnostics.guard(self.refresh))
        top.addWidget(refresh)
        clear = QPushButton(tr("Clear history"))
        clear.setObjectName("small")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(diagnostics.guard(self._clear))
        top.addWidget(clear)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(c[0]) for c in self.COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.itemDoubleClicked.connect(diagnostics.guard(lambda _: self._open_folder()))
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        for index, (_, width) in enumerate(self.COLUMNS):
            if width:
                header.setSectionResizeMode(index, QHeaderView.Interactive)
                self.table.setColumnWidth(index, width)
            else:
                header.setSectionResizeMode(index, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        self.empty_label = heading(
            tr("No entries yet. Jobs appear here once documents are produced."),
            9.5, False, theme.COLOURS["text_faint"],
        )
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        bottom = QHBoxLayout()
        self.count_label = heading("", 9, False, theme.COLOURS["text_muted"])
        bottom.addWidget(self.count_label)
        bottom.addStretch()
        self.open_button = QPushButton(tr("Open the job's folder"))
        self.open_button.setObjectName("primary")
        self.open_button.setCursor(Qt.PointingHandCursor)
        self.open_button.clicked.connect(diagnostics.guard(self._open_folder))
        bottom.addWidget(self.open_button)
        layout.addLayout(bottom)
        self.refresh()

    def refresh(self):
        self.entries = history.entries()
        # Filling while sorting is enabled scrambles rows; it is re-enabled after.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            cells = (
                entry.readable_time(),
                entry.document_set or "—",
                entry.subject or "—",
                entry.reference or "—",
                str(len(entry.documents)),
                entry.output_folder or "—",
            )
            # Details that do not fit go in the row's tooltip.
            details = "\n".join((
                tr("Source files: {files}").format(files=", ".join(entry.source_files) or "—"),
                tr("Produced: {files}").format(files=", ".join(entry.documents) or "—"),
                tr("Warnings: {count}").format(count=entry.warning_count),
            ))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(details)
                item.setData(Qt.UserRole, row)
                if column == 4:
                    item.setTextAlignment(Qt.AlignCenter)
                if not entry.folder_exists and column == len(cells) - 1:
                    item.setText(f"{text}   {tr('(folder not found)')}")
                    item.setForeground(QColor(theme.COLOURS["warning"]))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)

        present = bool(self.entries)
        self.table.setVisible(present)
        self.empty_label.setVisible(not present)
        self.open_button.setEnabled(present)
        self.count_label.setText(
            tr("{count} entries  ·  double-click a row to open its folder").format(count=len(self.entries))
            if present else ""
        )
        if present:
            self.table.selectRow(0)

    def _selected(self) -> history.Entry | None:
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, 0) is None:
            return None
        # The table may be sorted: the entry is found through its stored index.
        index = self.table.item(row, 0).data(Qt.UserRole)
        return self.entries[index] if index is not None and index < len(self.entries) else None

    def _open_folder(self):
        entry = self._selected()
        if entry is None:
            QMessageBox.information(self, tr("Nothing selected"), tr("Select an entry in the list."))
            return
        if not entry.folder_exists:
            QMessageBox.warning(
                self, tr("Folder not found"),
                tr("The job's folder no longer exists or was moved:\n{folder}").format(folder=entry.output_folder),
            )
            return
        os.startfile(entry.output_folder)  # noqa: S606

    def _clear(self):
        if not self.entries:
            return
        if QMessageBox.question(
            self, tr("Clear history"),
            tr("Delete every entry?\n\nThis only clears the list; your produced documents stay on disk."),
        ) == QMessageBox.Yes:
            history.clear()
            self.refresh()
