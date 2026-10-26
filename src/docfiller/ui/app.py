"""Application start-up."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from .. import diagnostics, engine, i18n, settings
from ..i18n import tr
from . import branding, theme
from .main_window import SIGN_OUT_CODE, MainWindow
from .sign_in import open_session
from .widgets import install_wheel_guard

APP_TITLE = "DocFiller"


def _error_window(summary: str, detail: str) -> None:
    """Show an unexpected error in plain words.

    The executable has no console; without this window the program would close
    SILENTLY and the user would never know what happened.
    """
    if QApplication.instance() is None:
        return
    box = QMessageBox()
    box.setIcon(QMessageBox.Critical)
    box.setWindowTitle(tr("Unexpected error"))
    box.setText(tr(
        "An unexpected error occurred.\n\nIf your work is intact you can carry on; if the "
        "problem repeats, send the details below and the log file."
    ))
    box.setInformativeText(f"{summary}\n\n{tr('Log')}: {diagnostics.log_path()}")
    box.setDetailedText(detail)
    box.exec()


def _startup_warnings(window, warnings: list[str]) -> None:
    if not warnings:
        return
    QMessageBox.warning(
        window, tr("Start-up check"),
        tr("The program has started, but these things look wrong:") + "\n\n" + "\n\n".join(f"• {w}" for w in warnings),
    )


def main() -> int:
    # Error capture is installed FIRST: every later error is logged and shown.
    diagnostics.install(_error_window)
    diagnostics.capture_qt_messages()
    # Previews left by a session that ended abruptly are removed.
    try:
        engine.discard_old_previews()
    except Exception as exc:  # noqa: BLE001 - clean-up never blocks the start
        diagnostics.write(f"Old previews could not be removed: {exc}")

    application = QApplication(sys.argv)
    application.setStyle("Fusion")
    application.setApplicationName(APP_TITLE)
    # Scrolling over a dropdown never changes its value.
    install_wheel_guard(application)
    # Remembered appearance and language are applied before the first window.
    i18n.set_language(settings.language())
    theme.set_theme(settings.mode(), settings.accent())
    application.setStyleSheet(theme.STYLE)
    application.setWindowIcon(branding.icon())

    # "Sign out" returns to account selection IN THE SAME PROCESS. The
    # QApplication is created ONCE: Qt refuses a second instance ("Please
    # destroy the QApplication singleton before creating a new QApplication
    # instance"), so the session loop runs inside the one application.
    while True:
        code = _run_session(application)
        if code != SIGN_OUT_CODE:
            return code


def _run_session(application) -> int:
    # Splash: no blank screen while heavy imports and account selection run.
    splash = QSplashScreen(branding.splash())
    splash.show()
    application.processEvents()
    splash.hide()

    if open_session() is None:
        return 0  # the user cancelled

    window = MainWindow()
    window.show()
    splash.finish(window)
    # Environment problems (unwritable folder, no templates, no Word) are
    # reported once, at start, not halfway through a job.
    _startup_warnings(window, diagnostics.startup_check())

    code = application.exec()
    # The old window is destroyed for certain: two main windows alive together
    # would share one job queue and one Office pool.
    window.deleteLater()
    application.processEvents()
    return code


if __name__ == "__main__":
    sys.exit(main())
