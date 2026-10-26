"""Widgets shared by the pages."""
from __future__ import annotations

import traceback

from PySide6.QtCore import QEvent, QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QCompleter,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QWidget,
)

from .. import diagnostics, memory
from ..i18n import tr
from . import theme


def heading(text: str, size: float = 10, bold: bool = True, colour: str | None = None) -> QLabel:
    label = QLabel(text)
    font = QFont()
    font.setPointSizeF(size)
    font.setBold(bold)
    label.setFont(font)
    if colour:
        label.setStyleSheet(f"color: {colour}; background: transparent;")
    return label


def hint(text: str) -> QLabel:
    label = heading(text, 8.5, False, theme.COLOURS["text_muted"])
    label.setWordWrap(True)
    return label


def file_filter() -> str:
    return (
        f"{tr('Supported files')} (*.xls *.xlsx *.xlsm *.csv *.pdf *.doc *.docx *.docm *.jpg *.jpeg *.png);;"
        f"{tr('Spreadsheets')} (*.xls *.xlsx *.xlsm *.csv);;"
        f"{tr('All files')} (*)"
    )


# ---------------------------------------------------------------- drop zone


class DropZone(QLabel):
    """Where files are dropped or picked (several files at once)."""

    files_chosen = Signal(list)

    TEMPLATE = (
        "QLabel {{ border: 2px dashed {border}; border-radius: 8px; padding: 22px;"
        " color: {text}; background: {background}; }}"
    )

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(104)
        self.setCursor(Qt.PointingHandCursor)
        self.setText(
            tr("Drag your project files here")
            + "\n"
            + tr("or click to choose  ·  several files at once is fine")
        )
        self._normal()

    def _normal(self):
        c = theme.COLOURS
        self.setStyleSheet(self.TEMPLATE.format(border=c["border_strong"], text=c["text_muted"], background=c["card_alt"]))

    def _highlighted(self):
        c = theme.COLOURS
        self.setStyleSheet(self.TEMPLATE.format(border=c["accent"], text=c["accent_dark"], background=c["accent_soft"]))

    def mousePressEvent(self, event):  # noqa: N802
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("Choose project files (several at once is fine)"), "", file_filter()
        )
        if files:
            self.files_chosen.emit(files)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            self._highlighted()
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):  # noqa: N802
        self._normal()

    def dropEvent(self, event):  # noqa: N802
        self._normal()
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if files:
            self.files_chosen.emit(files)


# ------------------------------------------------------------- memory input


class MemoryInput(QWidget):
    """A line edit with the field's earlier values.

    Behaves like an ordinary QLineEdit, plus:

    * earlier values of the same field are suggested while typing,
    * the arrow on the right lists every remembered value,
    * the value is remembered when editing finishes.

    An editable QComboBox was deliberately not used: Qt may "correct" the typed
    text to one of the list entries by itself, and changing what the user wrote
    is unacceptable here — whatever is typed is what goes into the document.
    """

    def __init__(self, field: str, placeholder: str = "", parent=None):
        super().__init__(parent)
        self.field = field
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.edit = QLineEdit()
        if placeholder:
            self.edit.setPlaceholderText(placeholder)
        layout.addWidget(self.edit, 1)

        self.arrow = QToolButton()
        self.arrow.setObjectName("memoryArrow")
        self.arrow.setText("▾")
        self.arrow.setCursor(Qt.PointingHandCursor)
        self.arrow.clicked.connect(self._open_list)
        layout.addWidget(self.arrow)

        self._popup: QListWidget | None = None
        self.refresh_memory()
        self.edit.editingFinished.connect(self.remember)

    # --- QLineEdit face
    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:  # noqa: N802
        self.edit.setText(text)

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802
        self.edit.setPlaceholderText(text)

    def setReadOnly(self, value: bool) -> None:  # noqa: N802
        self.edit.setReadOnly(value)
        self.arrow.setVisible(not value)

    def setProperty(self, name, value):  # noqa: N802
        if name == "missing":
            self.edit.setProperty(name, value)
            return True
        return super().setProperty(name, value)

    @property
    def editingFinished(self):  # noqa: N802
        return self.edit.editingFinished

    @property
    def textEdited(self):  # noqa: N802
        return self.edit.textEdited

    def clear(self) -> None:
        self.edit.clear()

    def blockSignals(self, value: bool) -> bool:  # noqa: N802
        self.edit.blockSignals(value)
        return super().blockSignals(value)

    # --- memory
    def refresh_memory(self) -> None:
        values = memory.values(self.field)
        self.arrow.setEnabled(bool(values))
        self.arrow.setToolTip(
            tr("Values you typed before ({count})").format(count=len(values))
            if values else tr("Nothing typed in this field yet")
        )
        completer = QCompleter(values, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.edit.setCompleter(completer)

    def remember(self) -> None:
        memory.remember(self.field, self.edit.text())
        self.refresh_memory()

    def _open_list(self) -> None:
        values = memory.values(self.field)
        if not values:
            return
        if self._popup is not None:
            self._popup.close()
        listing = QListWidget(self.window())
        listing.setWindowFlags(Qt.Popup)
        c = theme.COLOURS
        listing.setStyleSheet(
            f"QListWidget {{ background: {c['card']}; border: 1px solid {c['border_strong']};"
            f" border-radius: 6px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 6px 8px; border-radius: 4px; color: {c['text']}; }}"
            f"QListWidget::item:selected {{ background: {c['accent_soft']}; color: {c['accent_dark']}; }}"
        )
        for value in values:
            QListWidgetItem(value, listing)
        listing.itemClicked.connect(self._picked)
        listing.installEventFilter(self)
        corner = self.edit.mapToGlobal(self.edit.rect().bottomLeft())
        listing.setFixedWidth(max(self.edit.width(), 260))
        listing.setMaximumHeight(min(260, 34 * len(values) + 12))
        listing.move(corner)
        listing.show()
        self._popup = listing

    def _picked(self, item: QListWidgetItem) -> None:
        self.edit.setText(item.text())
        if self._popup is not None:
            self._popup.close()
            self._popup = None
        self.edit.setFocus()
        self.edit.editingFinished.emit()

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            if self._popup is not None:
                self._popup.close()
                self._popup = None
            return True
        return super().eventFilter(obj, event)


# --------------------------------------------------------------- wheel guard


class WheelGuard(QObject):
    """The mouse wheel never changes a dropdown or spin box by accident.

    Qt changes a combo box's selection when the pointer passes over it while
    scrolling; on a long form that silently rewrites answers. The event is not
    swallowed but forwarded to the nearest scroll area, so the page still
    scrolls normally over a control. A value changes only by choosing it.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._forwarding = False

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() != QEvent.Wheel or self._forwarding:
            return super().eventFilter(obj, event)
        if not isinstance(obj, (QComboBox, QAbstractSpinBox)):
            return super().eventFilter(obj, event)
        scroller = obj.parent()
        while scroller is not None and not isinstance(scroller, QAbstractScrollArea):
            scroller = scroller.parent()
        if scroller is not None:
            self._forwarding = True
            try:
                QApplication.sendEvent(scroller.viewport(), event)
            finally:
                self._forwarding = False
        return True


def install_wheel_guard(application) -> WheelGuard:
    guard = WheelGuard(application)
    application.installEventFilter(guard)
    return guard


# ------------------------------------------------------------ background work


class Worker(QThread):
    """Runs a long task without freezing the window; can be cancelled.

    `func` receives a callback reporting whether cancellation was requested. A
    conversion already inside one Word/Excel COM call cannot be interrupted, so
    the job stops at the next document.
    """

    done = Signal(object)

    def __init__(self, func):
        super().__init__()
        self._func = func
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def cancel_requested(self) -> bool:
        return self._cancel

    def run(self):
        try:
            result = self._func(self.cancel_requested)
        except Exception as exc:  # noqa: BLE001 - reported to the page, logged
            diagnostics.write(f"Error in background job:\n{traceback.format_exc()}")
            result = exc
        self.done.emit(result)


class JobManager:
    """Keeps running workers alive until they really finish.

    If the last Python reference to a running QThread disappears, Qt destroys
    the C++ object and punishes it by ENDING THE PROCESS ("QThread: Destroyed
    while thread is still running"). In a windowed build that looks like "the
    documents were produced and the program closed". Workers are therefore held
    here until finished and then released properly.
    """

    def __init__(self):
        self._workers: list[Worker] = []

    def start(self, worker: Worker, on_done) -> Worker:
        self._workers.append(worker)
        worker.done.connect(diagnostics.guard(on_done))
        worker.finished.connect(lambda: self._finished(worker))
        worker.start()
        return worker

    def _finished(self, worker: Worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def busy(self) -> bool:
        return any(w.isRunning() for w in self._workers)

    def wait_all(self, timeout_ms: int = 15000) -> None:
        """While closing: cancel and wait, rather than destroying them midway."""
        for worker in list(self._workers):
            if worker.isRunning():
                worker.request_cancel()
                worker.wait(timeout_ms)


def is_running(worker) -> bool:
    """Is this worker still running? A finished worker may already be deleted
    by Qt; touching it would raise, so that counts as "not running"."""
    if worker is None:
        return False
    try:
        return bool(worker.isRunning())
    except RuntimeError:
        return False


def duration_text(seconds: float) -> str:
    if seconds < 60:
        return tr("{seconds:.1f} seconds").format(seconds=seconds)
    minutes, rest = divmod(seconds, 60)
    return tr("{minutes} min {seconds:.0f} s").format(minutes=int(minutes), seconds=rest)
