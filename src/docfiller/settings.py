"""Remembered preferences, in two scopes.

**Machine** settings — appearance (mode, accent colour, language) and which
account opens automatically — belong to the computer, not to one person, and
are available before anyone signs in: the sign-in window itself must already be
themed and translated.

Security note on "remember me": the password is **never** stored. Only "this
account opens without asking" is remembered — consistent with the fact that an
account password protects against using someone else's account by mistake, not
against reading local files (see accounts.py). The interface says so plainly.

**Workspace** settings — the template folder, last folders used, choices on the
quick-document page — belong to the signed-in person and live in their folder.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import paths

MACHINE_FILE = "settings.json"
WORKSPACE_FILE = "workspace.json"

MACHINE_DEFAULTS: dict[str, Any] = {
    "mode": "light",          # light | dark
    "accent": "teal",         # see ui.theme.ACCENTS
    "language": "en",         # see i18n.LANGUAGES
    "remembered_account": "",  # account id opened without asking; "" = ask
}

WORKSPACE_DEFAULTS: dict[str, Any] = {
    "template_folder": "",
    "last_source_folder": "",
    "last_output_folder": "",
    "quick_templates": [],   # template file names ticked on the quick page
    "decimal_separator": ",",
}


def _read(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    values = dict(defaults)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return values
    if isinstance(stored, dict):
        # Only known keys are honoured: an old or hand-edited file cannot
        # inject unexpected settings.
        values.update({key: stored[key] for key in defaults if key in stored})
    return values


def _write(path: Path, values: dict[str, Any]) -> None:
    try:
        paths.atomic_write(path, json.dumps(values, ensure_ascii=False, indent=2))
    except OSError:
        pass  # the program keeps working with defaults if settings cannot be saved


# ------------------------------------------------------------------- machine


def machine() -> dict[str, Any]:
    return _read(paths.shared_data_root() / MACHINE_FILE, MACHINE_DEFAULTS)


def set_machine(**changes: Any) -> dict[str, Any]:
    values = machine()
    values.update({k: v for k, v in changes.items() if k in MACHINE_DEFAULTS})
    _write(paths.shared_data_root() / MACHINE_FILE, values)
    return values


def mode() -> str:
    value = machine()["mode"]
    return value if value in ("light", "dark") else "light"


def accent() -> str:
    return str(machine()["accent"] or "teal")


def language() -> str:
    return str(machine()["language"] or "en")


def remembered_account() -> str:
    return str(machine()["remembered_account"] or "")


def remember_account(account_id: str | None) -> None:
    """Choose the account that opens without asking (None/'' turns it off)."""
    set_machine(remembered_account=account_id or "")


# ----------------------------------------------------------------- workspace


def workspace() -> dict[str, Any]:
    return _read(paths.data_file(WORKSPACE_FILE), WORKSPACE_DEFAULTS)


def set_workspace(**changes: Any) -> dict[str, Any]:
    values = workspace()
    values.update({k: v for k, v in changes.items() if k in WORKSPACE_DEFAULTS})
    _write(paths.data_file(WORKSPACE_FILE), values)
    return values


def template_folder() -> Path | None:
    folder = workspace()["template_folder"]
    return Path(folder) if folder and Path(folder).is_dir() else None
