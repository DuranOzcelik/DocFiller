"""Filesystem locations used by the application.

Two roots matter:

* the **resource root** — where bundled files live. From source this is the
  package directory; inside a PyInstaller one-file build the archive is
  unpacked to a temporary folder exposed as ``sys._MEIPASS``.
* the **data root** — a writable folder for settings, history and libraries.
  Never write next to the executable: a program installed under
  ``C:\\Program Files`` cannot write to its own directory.

The data root has two levels. The **shared** level belongs to the computer
(the account list, appearance, the error log). Once someone signs in, the
**active** level switches to that person's own folder, so history, libraries
and drafts are never mixed between people sharing one machine.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "DocFiller"


def is_frozen() -> bool:
    """True when running from a PyInstaller build."""
    return getattr(sys, "frozen", False)


def resource_root() -> Path:
    """Directory holding bundled, read-only resources."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent


def _is_writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _shared_candidates() -> list[Path]:
    override = os.environ.get("DOCFILLER_DATA_DIR")
    if override:
        return [Path(override)]
    candidates = []
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            candidates.append(Path(base) / APP_NAME)
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / APP_NAME)
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        candidates.append(Path(base) / APP_NAME.lower())
    # Last resort: a locked-down machine may refuse every profile folder.
    candidates.append(Path(tempfile.gettempdir()) / APP_NAME)
    return candidates


_shared_root: Path | None = None


def shared_data_root() -> Path:
    """Writable folder shared by every account on this machine (cached)."""
    global _shared_root
    if _shared_root is not None and not os.environ.get("DOCFILLER_DATA_DIR"):
        return _shared_root
    for candidate in _shared_candidates():
        if _is_writable(candidate):
            if not os.environ.get("DOCFILLER_DATA_DIR"):
                _shared_root = candidate
            return candidate
    raise OSError("No writable folder is available for application data.")


def accounts_root() -> Path:
    root = shared_data_root() / "accounts"
    root.mkdir(parents=True, exist_ok=True)
    return root


# The active data root: the shared folder until someone signs in, then that
# person's own folder (see accounts.sign_in).
_active_root: Path | None = None


def set_active_root(root: Path | None) -> None:
    global _active_root
    _active_root = root


def data_root() -> Path:
    root = _active_root if _active_root is not None else shared_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_file(name: str) -> Path:
    return data_root() / name


def log_file() -> Path:
    # Always shared: a failure before sign-in must still be recorded.
    return shared_data_root() / "errors.log"


def atomic_write(target: Path, text: str) -> None:
    """Write `text` so that a crash midway never leaves a half-written file.

    The content goes to a temporary file next to the target and is then
    swapped in with a single rename, which the file system performs atomically.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".tmp-", dir=str(target.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


# Windows refuses paths longer than 260 characters unless long-path support is
# enabled, and Office reports it as a confusing "directory is not valid". Room
# is reserved for the generated file names that get appended to the folder.
MAX_PATH_LENGTH = 259
FILE_NAME_ALLOWANCE = 110


def path_length_problem(folder: str | Path) -> str | None:
    """A readable explanation when `folder` is too deep to write into, else None."""
    length = len(str(Path(folder).resolve()))
    if length + FILE_NAME_ALLOWANCE <= MAX_PATH_LENGTH:
        return None
    return (
        f"The folder path is {length} characters long. Windows limits a full file "
        f"path to {MAX_PATH_LENGTH} characters, and document names are added to the "
        "folder path. Choose a folder closer to the top of the drive (for example "
        "on the Desktop) to avoid write failures."
    )


def writable_problem(folder: str | Path) -> str | None:
    """A readable explanation when `folder` cannot be written to, else None."""
    try:
        with tempfile.NamedTemporaryFile(prefix=".docfiller-write-", dir=str(folder)):
            pass
    except OSError as exc:
        return (
            f"You do not have permission to write to this folder, or it cannot be "
            f"used:\n\n{exc}\n\nChoose a different folder."
        )
    return None


def preview_root() -> Path:
    """Temporary folder for previews; cleared on every start."""
    root = Path(tempfile.gettempdir()) / f"{APP_NAME}-preview"
    root.mkdir(parents=True, exist_ok=True)
    return root
