"""Account selection / creation — completely offline.

Several people may use the same computer. On start the program asks who is
working; the chosen account's history, record library, field memory and drafts
are read from its own folder. Nothing goes on the network.

The password is optional and the window says so honestly: it does not encrypt
local files, it only stops someone else from working under your account.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QLabel,
)

from .. import accounts, settings
from ..i18n import tr
from . import branding, theme
from .widgets import heading


class SignInWindow(QDialog):
    """Choose an account or create a new one."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Account selection"))
        self.setWindowIcon(branding.icon())
        self.setModal(True)
        self.setStyleSheet(theme.STYLE)
        self.setMinimumWidth(520)
        self.chosen: accounts.Account | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("signInHeader")
        # The background is set right here: left to the general style sheet the
        # header stayed white and the white logo text on it looked faded.
        header.setAttribute(Qt.WA_StyledBackground, True)
        header.setStyleSheet(
            f"QFrame#signInHeader {{ background: {theme.COLOURS['sidebar_bg']};"
            f" border: none; border-bottom: 3px solid {theme.COLOURS['accent']}; }}"
        )
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 20, 24, 18)
        header_layout.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(branding.logo(320))
        # The label's own background must be TRANSPARENT: the general style
        # gives labels a light background, which made a white box on the dark
        # header (and the white logo text disappeared in it).
        logo.setStyleSheet("background: transparent;")
        header_layout.addWidget(logo)
        sub = heading(
            tr("Several people can work on this computer. Each account has its own history, "
               "record library and field memory. Nothing leaves the computer."),
            8.5, False,
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {theme.COLOURS['sidebar_text']}; background: transparent;")
        header_layout.addWidget(sub)
        outer.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 18)
        body_layout.setSpacing(12)
        outer.addWidget(body, 1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_choose())
        self.stack.addWidget(self._page_new())
        body_layout.addWidget(self.stack)

        self._fill_list()
        if accounts.setup_needed():
            self.stack.setCurrentIndex(1)

    # ================================================================ pages

    def _page_choose(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        column.addWidget(heading(tr("Choose your account"), 11, True))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setMinimumHeight(180)
        self.list.itemDoubleClicked.connect(lambda _=None: self._sign_in())
        self.list.currentItemChanged.connect(lambda *_: self._refresh_password())
        column.addWidget(self.list)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText(tr("This account has no password"))
        self.password.setEnabled(False)
        self.password.returnPressed.connect(self._sign_in)
        form = QFormLayout()
        form.addRow(tr("Password"), self.password)
        column.addLayout(form)

        self.remember = QCheckBox(tr("Remember me — do not ask again on this computer"))
        self.remember.setToolTip(tr(
            "Your password is NOT stored; only 'open this account without asking' is "
            "remembered. Leave it off if you share the computer."
        ))
        self.remember.setChecked(bool(settings.remembered_account()))
        column.addWidget(self.remember)

        buttons = QHBoxLayout()
        new = QPushButton(tr("New account"))
        new.setCursor(Qt.PointingHandCursor)
        new.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        remove = QPushButton(tr("Remove account"))
        remove.setCursor(Qt.PointingHandCursor)
        remove.clicked.connect(self._remove)
        enter = QPushButton(tr("Sign in"))
        enter.setObjectName("primary")
        enter.setCursor(Qt.PointingHandCursor)
        enter.setMinimumHeight(38)
        enter.clicked.connect(self._sign_in)
        buttons.addWidget(new)
        buttons.addWidget(remove)
        buttons.addStretch()
        buttons.addWidget(enter)
        column.addLayout(buttons)
        return page

    def _page_new(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        column.addWidget(heading(tr("Create a new account"), 11, True))
        note = heading(
            tr("The name is required; everything else is optional and can be changed later on "
               "the Library page. A password does not encrypt local files; it only stops someone "
               "else from working under your account."),
            8.5, False, theme.COLOURS["text_muted"],
        )
        note.setWordWrap(True)
        column.addWidget(note)
        form = QFormLayout()
        form.setSpacing(8)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText(tr("e.g. Alex Morgan"))
        self.new_role = QLineEdit()
        self.new_role.setPlaceholderText(tr("e.g. Project engineer"))
        self.new_password = QLineEdit()
        self.new_password.setEchoMode(QLineEdit.Password)
        self.new_password.setPlaceholderText(tr("(optional)"))
        form.addRow(tr("Account name"), self.new_name)
        form.addRow(tr("Role"), self.new_role)
        form.addRow(tr("Password"), self.new_password)
        column.addLayout(form)
        self.new_remember = QCheckBox(tr("Remember me — do not ask again on this computer"))
        self.new_remember.setToolTip(tr("The password is not stored; only that this account opens directly."))
        column.addWidget(self.new_remember)

        buttons = QHBoxLayout()
        back = QPushButton(tr("Back"))
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        back.setEnabled(not accounts.setup_needed())
        create = QPushButton(tr("Create the account and sign in"))
        create.setObjectName("primary")
        create.setCursor(Qt.PointingHandCursor)
        create.setMinimumHeight(38)
        create.clicked.connect(self._create)
        buttons.addWidget(back)
        buttons.addStretch()
        buttons.addWidget(create)
        column.addLayout(buttons)
        return page

    # ============================================================== actions

    def _fill_list(self):
        self.list.clear()
        for account in accounts.list_all():
            text = account.name
            if account.role:
                text += f"  ·  {account.role}"
            if account.last_sign_in:
                text += "   " + tr("(last sign-in: {date})").format(date=account.last_sign_in[:10])
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, account.id)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _selected(self) -> accounts.Account | None:
        item = self.list.currentItem()
        return accounts.find(item.data(Qt.UserRole)) if item else None

    def _refresh_password(self):
        account = self._selected()
        protected = bool(account and account.has_password)
        self.password.setEnabled(protected)
        self.password.setPlaceholderText(tr("Enter your password") if protected else tr("This account has no password"))
        self.password.clear()

    def _sign_in(self):
        account = self._selected()
        if account is None:
            QMessageBox.information(self, tr("Choose an account"), tr("Choose an account in the list."))
            return
        if not accounts.password_matches(account, self.password.text()):
            QMessageBox.warning(self, tr("Wrong password"), tr("The password is not correct."))
            return
        self.chosen = account
        settings.remember_account(account.id if self.remember.isChecked() else None)
        self.accept()

    def _create(self):
        name = self.new_name.text().strip()
        if not name:
            QMessageBox.warning(self, tr("Missing"), tr("The account name cannot be empty."))
            return
        account = accounts.create(name, self.new_password.text(), role=self.new_role.text().strip())
        self.chosen = account
        settings.remember_account(account.id if self.new_remember.isChecked() else None)
        self.accept()

    def _remove(self):
        account = self._selected()
        if account is None:
            return
        if QMessageBox.question(
            self, tr("Remove account"),
            tr("Remove the account '{name}' from the list?\n\nIts history and documents STAY ON DISK; it only leaves the list.").format(name=account.name),
        ) != QMessageBox.Yes:
            return
        accounts.remove(account.id)
        self._fill_list()
        if not accounts.list_all():
            self.stack.setCurrentIndex(1)


def open_session(parent=None) -> accounts.Account | None:
    """Open the remembered account directly, or ask.

    With "remember me" ticked, the password is NOT asked — the password does not
    protect local files anyway (see accounts.py); it only prevents working under
    another account by mistake. Signing out from the menu clears the memory.
    """
    remembered = accounts.find(settings.remembered_account())
    if remembered is not None:
        accounts.sign_in(remembered)
        return remembered
    window = SignInWindow(parent)
    if window.exec() != QDialog.Accepted or window.chosen is None:
        return None
    accounts.sign_in(window.chosen)
    return window.chosen
