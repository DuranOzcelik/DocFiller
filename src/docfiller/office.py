"""Shared Microsoft Office sessions for COM automation.

Starting Word or Excel costs several seconds; converting a document once the
application is running costs a fraction of that. A program that opens and closes
Office for every job therefore spends most of its time waiting for a splash
screen.

This module keeps **one worker thread per Office application**. The thread owns
the COM objects, runs submitted callables against the live application and keeps
it open between jobs. After ``IDLE_SHUTDOWN_SECONDS`` without work the
application is closed so nothing lingers in memory.

A dedicated thread is required rather than a simple cached object: COM objects
belong to the apartment that created them and cannot be used from another
thread. Background jobs run on short-lived threads, so the only way to share one
session is to keep COM in its own thread and post work to it.

Word and Excel use separate pools and run independently.
"""
from __future__ import annotations

import atexit
import queue
import threading
import time
from typing import Any, Callable

# Close an idle Office application after this many seconds. Long enough to cover
# a user reviewing a preview before pressing Generate, short enough that the
# program never keeps Word resident for hours.
IDLE_SHUTDOWN_SECONDS = 180.0

# msoAutomationSecurityForceDisable — macros never run during automation.
AUTOMATION_SECURITY_FORCE_DISABLE = 3

# How long to wait for an application to shut down before giving up on it.
QUIT_TIMEOUT_SECONDS = 20


class OfficeUnavailable(RuntimeError):
    """pywin32 is missing, or the Office application could not be started."""


def com_available() -> bool:
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


class _Job:
    __slots__ = ("func", "result", "error", "done")

    def __init__(self, func: Callable[[Any], Any]) -> None:
        self.func = func
        self.result: Any = None
        self.error: BaseException | None = None
        self.done = threading.Event()


class OfficeSession:
    """A shared session of one Office application (Word or Excel)."""

    def __init__(self, prog_id: str, configure: Callable[[Any], None]) -> None:
        self.prog_id = prog_id
        self._configure = configure
        self._queue: queue.Queue[_Job | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._open = False

    # ------------------------------------------------------------- public API

    def run(self, func: Callable[[Any], Any]) -> Any:
        """Run ``func(application)`` on the session thread and return its result.

        Exceptions raised inside ``func`` propagate to the caller unchanged.
        """
        if not com_available():
            raise OfficeUnavailable(
                "pywin32 is not installed; it is required to drive Microsoft Office."
            )
        job = _Job(func)
        self._ensure_thread()
        self._queue.put(job)
        job.done.wait()
        if job.error is not None:
            raise job.error
        return job.result

    def is_open(self) -> bool:
        return self._open

    def close(self) -> None:
        """Shut the application down now; the worker thread ends with it."""
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._queue.put(None)
        thread.join(timeout=QUIT_TIMEOUT_SECONDS)
        with self._lock:
            if self._thread is thread:
                self._thread = None

    # ---------------------------------------------------------------- internal

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._loop, name=f"office-{self.prog_id}", daemon=True
            )
            self._thread.start()

    def _loop(self) -> None:
        import pythoncom

        pythoncom.CoInitialize()
        application = None
        try:
            while True:
                try:
                    job = self._queue.get(timeout=IDLE_SHUTDOWN_SECONDS)
                except queue.Empty:
                    break  # idle: release the application and end this thread
                if job is None:
                    break
                try:
                    if application is None:
                        application = self._start_application()
                        self._open = True
                    job.result = job.func(application)
                except BaseException as exc:  # noqa: BLE001 - forwarded to caller
                    job.error = exc
                    # The session itself may be gone (Office crashed or was
                    # killed). Drop it so the next job starts a fresh one.
                    if _session_is_broken(exc):
                        _quit(application)
                        application = None
                        self._open = False
                finally:
                    job.done.set()
                    self._queue.task_done()
        finally:
            _quit(application)
            self._open = False
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None
            pythoncom.CoUninitialize()

    def _start_application(self):
        import win32com.client

        # DispatchEx starts a private instance instead of attaching to a copy the
        # user already has open, so automation never disturbs their documents.
        application = win32com.client.DispatchEx(self.prog_id)
        self._configure(application)
        return application


def _session_is_broken(exc: BaseException) -> bool:
    """Does this error mean the session is unusable, or just this one document?

    Document-level problems (corrupt file, password protection) leave the
    application perfectly usable; a broken RPC channel does not.
    """
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("rpc", "call was rejected", "server is unavailable", "disconnected")
    )


def _quit(application) -> None:
    if application is None:
        return
    try:
        application.Quit()
    except Exception:  # noqa: BLE001, S110 - it may already be gone
        pass
    try:
        del application
        import gc

        gc.collect()
    except Exception:  # noqa: BLE001, S110
        pass


# --------------------------------------------------------------- configuration


def _configure_word(word) -> None:
    word.Visible = False
    word.DisplayAlerts = 0
    word.AutomationSecurity = AUTOMATION_SECURITY_FORCE_DISABLE
    for name, value in (
        ("EnableEvents", False),
        ("ScreenUpdating", False),
        ("DisplayRecentFiles", False),
    ):
        try:
            setattr(word, name, value)
        except Exception:  # noqa: BLE001, S110 - absent in some Office versions
            pass


def _configure_excel(excel) -> None:
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.AutomationSecurity = AUTOMATION_SECURITY_FORCE_DISABLE
    for name, value in (
        # Windows uses DDE to hand files to an already-running Excel. Leaving it
        # ignored is a persistent, user-visible setting: afterwards double-clicking
        # a workbook opens a blank Excel window. Always hand it back enabled.
        ("IgnoreRemoteRequests", False),
        ("AskToUpdateLinks", False),
        ("EnableEvents", False),
        ("ScreenUpdating", False),
    ):
        try:
            setattr(excel, name, value)
        except Exception:  # noqa: BLE001, S110
            pass


WORD = OfficeSession("Word.Application", _configure_word)
EXCEL = OfficeSession("Excel.Application", _configure_excel)


def warm_up() -> None:
    """Start the Office applications in the background without blocking.

    Called once a data source is loaded: the user almost always previews or
    generates next, so Office finishes starting while they review the mapping.
    Failures are ignored — Office may simply not be installed.
    """
    if not com_available():
        return
    for session in (WORD, EXCEL):
        if session.is_open():
            continue
        threading.Thread(
            target=_warm_up_quietly, args=(session,), name=f"warm-{session.prog_id}", daemon=True
        ).start()


def _warm_up_quietly(session: OfficeSession) -> None:
    try:
        session.run(lambda application: None)
    except Exception:  # noqa: BLE001, S110 - warming up never reports errors
        pass


def close_all() -> None:
    """Shut every Office session down, leaving no background process behind.

    Word and Excel are closed **concurrently**: closing them one after another
    adds their timeouts together, and on machines where Office shuts down slowly
    the program stayed alive noticeably longer than it needed to.
    """
    threads = [
        threading.Thread(target=session.close, name=f"close-{session.prog_id}", daemon=True)
        for session in (WORD, EXCEL)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=QUIT_TIMEOUT_SECONDS + 5)


# Worker threads are daemons, so they are not cleaned up on their own; without
# this hook an invisible WINWORD.EXE could outlive the program.
atexit.register(close_all)


def status() -> str:
    names = [name for name, session in (("Word", WORD), ("Excel", EXCEL)) if session.is_open()]
    return ", ".join(names) if names else "closed"
