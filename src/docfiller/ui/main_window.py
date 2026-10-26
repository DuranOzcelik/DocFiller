"""The main window: a sidebar of pages and a stack of pages.

Pages follow the flow of the work: prepare a spreadsheet, produce documents,
look things up. Documents opens first because it is used most.
"""
from __future__ import annotations

import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import accounts, diagnostics, i18n, office, settings
from ..i18n import tr
from . import branding, theme
from .documents_page import DocumentsPage
from .fill_sheet_page import FillSheetPage
from .history_page import HistoryPage
from .library_page import LibraryPage
from .quick_page import QuickPage
from .widgets import heading

APP_TITLE = "DocFiller"

# Stack order matches the menu: prepare -> produce -> records.
PAGE_FILL_SHEET = 0
PAGE_DOCUMENTS = 1
PAGE_QUICK = 2
PAGE_LIBRARY = 3
PAGE_HISTORY = 4

# Exit code that returns to account selection instead of quitting.
SIGN_OUT_CODE = 77


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        # When signing out, the Office sessions are kept (see closeEvent).
        self._signing_out = False
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(branding.icon())
        self._fit_to_screen()
        self.setStyleSheet(theme.STYLE)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.stack = QStackedWidget()
        self._create_pages()
        outer.addWidget(self._sidebar())
        outer.addWidget(self.stack, 1)

    def _create_pages(self):
        self.documents_page = DocumentsPage(self)
        # The quick page SHARES the job manager of the Documents page: one queue
        # whichever page starts the work.
        self.quick_page = QuickPage(self)
        self.fill_sheet_page = FillSheetPage(self)
        self.library_page = LibraryPage(self)
        self.history_page = HistoryPage(self)
        for page in (
            self.fill_sheet_page,
            self.documents_page,
            self.quick_page,
            self.library_page,
            self.history_page,
        ):
            self.stack.addWidget(page)
        self.stack.setCurrentIndex(PAGE_DOCUMENTS)

    def _fit_to_screen(self):
        """Open the window so it fits the user's screen.

        A fixed 1060x940 pushes the bottom of the window under the taskbar on
        common 1366x768 laptops and the production buttons become unreachable.
        The preferred size is limited to the AVAILABLE area and centred.
        """
        preferred_w, preferred_h = 1100, 940
        minimum_w, minimum_h = 900, 560
        self.setMinimumSize(minimum_w, minimum_h)
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(preferred_w, preferred_h)
            return
        area = screen.availableGeometry()
        width, height = theme.window_size(area.width(), area.height(), preferred_w, preferred_h, minimum_w, minimum_h)
        self.resize(width, height)
        self.move(area.x() + (area.width() - width) // 2, area.y() + max(0, (area.height() - height) // 2))

    # ================================================================ sidebar

    def _sidebar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("sidebar")
        frame.setFixedWidth(220)
        column = QVBoxLayout(frame)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        # Brand: one logo drawn at screen resolution — sharp at every DPI.
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 20, 16, 18)
        logo = QLabel()
        logo.setPixmap(branding.logo(186))
        logo.setFixedHeight(int(186 * 0.28))
        top_layout.addWidget(logo, 1)
        column.addWidget(top)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {theme.COLOURS['sidebar_active']}; border: none;")
        column.addWidget(divider)

        self.menu = QButtonGroup(self)
        self.menu.setExclusive(True)
        index = 0
        for group, items in (
            ("PREPARE", ("Fill a sheet",)),
            ("PRODUCE", ("Documents", "Quick document")),
            ("RECORDS", ("Library", "History")),
        ):
            title = QLabel(tr(group))
            title.setObjectName("sidebarGroup")
            column.addWidget(title)
            for text in items:
                button = QPushButton(tr(text))
                button.setObjectName("sidebarItem")
                button.setCheckable(True)
                button.setCursor(Qt.PointingHandCursor)
                button.clicked.connect(lambda _=False, i=index: self.go_to(i))
                self.menu.addButton(button, index)
                column.addWidget(button)
                index += 1
        self.menu.button(PAGE_DOCUMENTS).setChecked(True)
        column.addStretch()
        column.addWidget(self._account_card())

        note = heading(tr("Documents are filled without changing their layout.\nThe final check is yours."), 8, False)
        note.setObjectName("sidebarNote")
        note.setWordWrap(True)
        note.setContentsMargins(18, 16, 18, 16)
        column.addWidget(note)
        return frame

    def _account_card(self) -> QFrame:
        """Bottom of the sidebar: account, appearance, language, profile, sign out."""
        frame = QFrame()
        frame.setObjectName("accountCard")
        column = QVBoxLayout(frame)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(8)

        account = accounts.active()
        top = QHBoxLayout()
        top.setSpacing(8)
        badge = QLabel(accounts.initials(account.name if account else "?"))
        badge.setObjectName("accountBadge")
        badge.setFixedSize(32, 32)
        badge.setAlignment(Qt.AlignCenter)
        top.addWidget(badge)
        names = QVBoxLayout()
        names.setSpacing(0)
        name = QLabel(account.name if account else tr("(no account)"))
        name.setObjectName("accountName")
        names.addWidget(name)
        role = QLabel((account.role if account else "") or tr("local account"))
        role.setObjectName("accountRole")
        names.addWidget(role)
        top.addLayout(names, 1)
        column.addLayout(top)

        appearance = QLabel(tr("APPEARANCE"))
        appearance.setObjectName("sidebarGroup")
        appearance.setContentsMargins(0, 2, 0, 0)
        column.addWidget(appearance)

        self.accent_combo = QComboBox()
        self.accent_combo.setObjectName("sidebarSelect")
        self.accent_combo.setToolTip(tr("Changes the colour palette"))
        for key, label in theme.accents():
            self.accent_combo.addItem(tr(label), key)
        index = self.accent_combo.findData(theme.accent())
        if index >= 0:
            self.accent_combo.setCurrentIndex(index)
        theme.style_dropdown(self.accent_combo)
        self.accent_combo.currentIndexChanged.connect(diagnostics.guard(self.change_accent))
        column.addWidget(self.accent_combo)

        self.language_combo = QComboBox()
        self.language_combo.setObjectName("sidebarSelect")
        self.language_combo.setToolTip(tr("Language"))
        for code, label in i18n.available().items():
            self.language_combo.addItem(label, code)
        index = self.language_combo.findData(i18n.current())
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        theme.style_dropdown(self.language_combo)
        self.language_combo.currentIndexChanged.connect(diagnostics.guard(self.change_language))
        column.addWidget(self.language_combo)

        self.mode_button = QPushButton()
        self.mode_button.setObjectName("sidebarButton")
        self.mode_button.setCursor(Qt.PointingHandCursor)
        self.mode_button.setToolTip(tr("Switches between light and dark mode"))
        self.mode_button.clicked.connect(diagnostics.guard(self.toggle_mode))
        self.mode_button.setText(tr("Switch to light mode") if theme.mode() == "dark" else tr("Switch to dark mode"))
        column.addWidget(self.mode_button)

        row = QHBoxLayout()
        row.setSpacing(6)
        profile = QPushButton(tr("Profile"))
        profile.setObjectName("sidebarButton")
        profile.setCursor(Qt.PointingHandCursor)
        profile.clicked.connect(diagnostics.guard(lambda: self.go_to(PAGE_LIBRARY)))
        sign_out = QPushButton(tr("Sign out"))
        sign_out.setObjectName("sidebarButton")
        sign_out.setCursor(Qt.PointingHandCursor)
        sign_out.setToolTip(tr("Leaves the account and returns to account selection"))
        sign_out.clicked.connect(diagnostics.guard(self.sign_out))
        row.addWidget(profile)
        row.addWidget(sign_out)
        column.addLayout(row)
        return frame

    def go_to(self, index: int):
        button = self.menu.button(index)
        if button is not None:
            button.setChecked(True)
        self.stack.setCurrentIndex(index)
        if index == PAGE_LIBRARY:
            self.library_page.refresh()
        elif index == PAGE_HISTORY:
            self.history_page.refresh()

    # ============================================================ appearance

    def change_accent(self):
        key = self.accent_combo.currentData()
        if not key or key == theme.accent():
            return
        theme.set_theme(accent_name=key)
        settings.set_machine(accent=key)
        self.rebuild()

    def toggle_mode(self):
        new = "light" if theme.mode() == "dark" else "dark"
        theme.set_theme(mode_name=new)
        settings.set_machine(mode=new)
        self.rebuild()

    def change_language(self):
        code = self.language_combo.currentData()
        if not code or code == i18n.current():
            return
        i18n.set_language(code)
        settings.set_machine(language=code)
        self.rebuild()

    def rebuild(self):
        """Rebuild the interface after a theme or language change, KEEPING the
        user's work: loaded files, entered values, chosen folders, the page."""
        state = {
            "page": self.stack.currentIndex(),
            "documents": self.documents_page.state(),
            "quick": self.quick_page.state(),
            "sheet": self.fill_sheet_page.state(),
        }
        self.documents_page.discard_preview()
        self.quick_page.discard_preview()
        QApplication.instance().setStyleSheet(theme.STYLE)
        self.setStyleSheet(theme.STYLE)

        old_sidebar = self.layout().itemAt(0).widget()
        while self.stack.count():
            page = self.stack.widget(0)
            self.stack.removeWidget(page)
            page.setParent(None)
            page.deleteLater()
        self._create_pages()
        new_sidebar = self._sidebar()
        self.layout().replaceWidget(old_sidebar, new_sidebar)
        old_sidebar.setParent(None)
        old_sidebar.deleteLater()

        for page, key in ((self.documents_page, "documents"), (self.quick_page, "quick"), (self.fill_sheet_page, "sheet")):
            try:
                page.restore(state[key])
            except Exception:  # noqa: BLE001 - restoring is a convenience, never a failure
                diagnostics.write("Restoring the page failed:\n" + traceback.format_exc())
        self.go_to(state["page"])

    # ======================================================= cross-page events

    def use_in_documents(self, file):
        """Load a spreadsheet filled on the Fill a sheet page on Documents."""
        self.go_to(PAGE_DOCUMENTS)
        self.documents_page.clear_selection()
        self.documents_page.load_files([str(file)])

    def records_changed(self):
        for refresh in (self.documents_page.fill_record_combo, self.quick_page.fill_record_combo, self.library_page.refresh):
            try:
                refresh()
            except Exception:  # noqa: BLE001, S110 - a list refresh is not critical
                pass

    def sets_changed(self):
        for page in (self.documents_page, self.quick_page):
            try:
                page.fill_set_combo()
            except Exception:  # noqa: BLE001, S110
                pass
        self.documents_page._fill_document_rows()

    def templates_changed(self):
        self.quick_page.reload_templates()

    def profile_changed(self):
        account = accounts.active()
        if account is not None:
            if self.documents_page.project is not None:
                self.documents_page.project.profile = dict(account.profile_values)
                self.documents_page.refresh_badges()
            self.quick_page.project.profile = dict(account.profile_values)
        self.rebuild()

    def history_changed(self):
        self.history_page.refresh()

    # ================================================================ session

    def sign_out(self):
        """Leave the account: remembering is turned off and account selection opens."""
        if self.documents_page.jobs.busy():
            QMessageBox.information(self, tr("A job is running"), tr("You cannot sign out until production finishes."))
            return
        settings.remember_account(None)
        accounts.sign_out()
        self._signing_out = True
        self.close()
        QApplication.instance().exit(SIGN_OUT_CODE)

    def closeEvent(self, event):  # noqa: N802
        """Finish running jobs and leave no temporary files behind."""
        try:
            if self.documents_page.jobs.busy():
                answer = QMessageBox.question(
                    self, tr("Production is running"),
                    tr("Documents are still being produced. If you close the program the job stops halfway.\n\nClose anyway?"),
                )
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
                # Running threads must be stopped BEFORE they are destroyed,
                # otherwise Qt ends the process by force.
                self.documents_page.jobs.wait_all()
            # HIDE FIRST. The clean-up below (temporary files, closing Office)
            # keeps Qt's event loop busy for seconds; a window left on screen is
            # painted by Windows as a WHITE box marked "not responding".
            self.hide()
            QApplication.processEvents()
            self.documents_page.shut_down()
            self.quick_page.discard_preview()
        except Exception:  # noqa: BLE001 - closing must never get stuck on an error
            diagnostics.write("Error while closing:\n" + traceback.format_exc())
        # The shared Word/Excel sessions are closed so no invisible Office
        # process stays behind. NOT when signing out: the same process continues
        # with another account; idle sessions close themselves, and at exit
        # atexit closes Office anyway.
        if not self._signing_out:
            try:
                office.close_all()
            except Exception:  # noqa: BLE001, S110
                pass
        super().closeEvent(event)
