"""Error capture, the log file and the environment report.

The executable is built without a console, so an uncaught exception would make
the program disappear silently, with nothing for the user to report and nothing
for anyone to diagnose. This module:

* catches every uncaught error, on the main thread and on worker threads,
* shows the user an understandable window,
* writes the details to a persistent log, and
* starts the log with an environment report (Windows version, Office, screen,
  folders) so "it does not work on my computer" can be solved remotely.
"""
from __future__ import annotations

import datetime
import os
import platform
import sys
import traceback

from . import paths

# The log restarts once it grows past this size.
MAX_LOG_BYTES = 512 * 1024

# Callback that shows an error window; installed by the UI. None until then,
# in which case errors only go to the log.
_window = None


def log_path():
    return paths.log_file()


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def write(text: str) -> None:
    """Append an entry to the log. Failing to log must never cause a new error."""
    try:
        target = log_path()
        if target.exists() and target.stat().st_size > MAX_LOG_BYTES:
            target.unlink()
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(f"\n{'=' * 70}\n{_now()}\n{'=' * 70}\n{text}\n")
    except Exception:  # noqa: BLE001, S110
        pass


def environment_report() -> str:
    """What is needed to diagnose a problem remotely. Contains no personal data."""
    lines = [
        f"Mode         : {'packaged executable' if paths.is_frozen() else 'source'}",
        f"Python       : {sys.version.split()[0]}",
        f"System       : {platform.platform()}",
        f"Architecture : {platform.machine()}",
        f"Resources    : {paths.resource_root()}",
        f"Data folder  : {_safe(paths.data_root)}",
        f"Temp folder  : {os.environ.get('TEMP', '(TEMP not set)')}",
    ]
    try:
        from . import export

        available, message = export.office_installed()
        lines.append(f"Microsoft Word: {'available' if available else 'MISSING'} — {message}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Microsoft Word: could not be checked ({exc})")
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            screen = app.primaryScreen()
            geometry = screen.availableGeometry()
            lines.append(
                f"Screen       : {geometry.width()}x{geometry.height()} "
                f"(scale {screen.devicePixelRatio():g})"
            )
    except Exception:  # noqa: BLE001, S110
        pass
    try:
        from . import settings, templates

        folder = settings.template_folder()
        if folder is None:
            lines.append("Templates    : no template folder chosen")
        else:
            lines.append(f"Templates    : {len(templates.discover(folder))} in {folder}")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Templates    : could not be read ({exc})")
    return "\n".join(lines)


def _safe(func) -> str:
    try:
        return str(func())
    except Exception as exc:  # noqa: BLE001
        return f"(unavailable: {exc})"


def startup_check() -> list[str]:
    """Check the environment at start-up; return warnings to show the user.

    Problems are reported once, up front, in plain words — not halfway through
    a job.
    """
    warnings: list[str] = []
    try:
        folder = paths.data_root()
        probe = folder / ".write-test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            f"The settings folder cannot be written to ({exc}). History and saved "
            "records may not be kept."
        )
    try:
        from . import settings, templates

        folder = settings.template_folder()
        if folder is not None and not templates.discover(folder):
            warnings.append(
                f"The template folder contains no Word templates: {folder}. "
                "Choose another folder on the Documents page."
            )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"The template folder could not be read: {exc}")
    try:
        from . import export

        available, message = export.office_installed()
        if not available:
            warnings.append(
                f"Microsoft Word was not found ({message}). Documents are produced "
                "as .docx but cannot be converted to PDF."
            )
    except Exception:  # noqa: BLE001, S110
        pass
    return warnings


# ------------------------------------------------------------- error capture


def _report(kind, value, tb, origin: str) -> None:
    detail = "".join(traceback.format_exception(kind, value, tb))
    write(f"[{origin}] Uncaught error\n\n{environment_report()}\n\n{detail}")
    if _window is not None:
        try:
            _window(f"{kind.__name__}: {value}", detail)
        except Exception:  # noqa: BLE001, S110 - never fail while reporting a failure
            pass


def capture_qt_messages() -> None:
    """Route Qt's own warnings into the log.

    Qt reports fatal C++-side conditions (for example "QThread: Destroyed while
    thread is still running") through its message channel, not as Python
    exceptions, and may then end the process. Without this, a windowed build
    looks as if it closed for no reason.
    """
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return
    important = {QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg, QtMsgType.QtWarningMsg}

    def handler(kind, _context, message):
        if kind in important:
            write(f"[Qt/{kind.name}] {message}")

    qInstallMessageHandler(handler)


def _positional_capacity(func) -> int | None:
    """How many positional arguments `func` accepts (None when unlimited)."""
    import inspect

    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return None
    count = 0
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            return None
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            count += 1
    return count


def guard(func):
    """Wrap a UI callback so that its failure can never close the program.

    An exception inside a Qt slot can terminate the process outright on some
    versions. A wrapped callback logs the failure, shows it, and the program
    keeps running.

    Qt trims surplus signal arguments to match a slot's signature (``clicked``
    sends a bool even to a slot that takes none). A ``*args`` wrapper defeats
    that, so the trimming is done here; without it buttons silently stop
    working.
    """
    import functools

    capacity = _positional_capacity(func)

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*(args if capacity is None else args[:capacity]), **kwargs)
        except Exception:  # noqa: BLE001 - the interface must never close on an error
            _report(*sys.exc_info(), f"interface: {getattr(func, '__name__', func)}")
            return None

    return wrapper


def install(window=None) -> None:
    """Start capturing uncaught errors (main thread and worker threads)."""
    global _window
    _window = window

    def main_hook(kind, value, tb):
        if issubclass(kind, KeyboardInterrupt):
            sys.__excepthook__(kind, value, tb)
            return
        _report(kind, value, tb, "main")

    sys.excepthook = main_hook

    import threading

    def thread_hook(arguments):
        _report(arguments.exc_type, arguments.exc_value, arguments.exc_traceback, "worker thread")

    threading.excepthook = thread_hook
    write("Application started\n\n" + environment_report())
