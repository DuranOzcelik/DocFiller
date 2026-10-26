"""Remember the mapping a user confirmed, so they confirm it only once.

A profile is keyed by the **set of templates** in use, not by the data file: the
same templates are filled from a new spreadsheet every time, and that new file
is exactly when the saved mapping has to apply. Keys are addresses rather than
values, so a profile carries no data from the spreadsheet it was created with.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import paths

FILE_NAME = "mapping_profiles.json"

# Oldest profiles are dropped past this count; mappings are cheap but the file
# should not grow without bound.
MAX_PROFILES = 100


def template_key(template_paths: list[Path] | list[str]) -> str:
    """A stable identifier for one set of templates."""
    names = sorted(Path(item).name.lower() for item in template_paths)
    digest = hashlib.sha256("|".join(names).encode("utf-8")).hexdigest()
    return digest[:32]


def _store_path() -> Path:
    return paths.data_file(FILE_NAME)


def _load_all() -> dict:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_all(data: dict) -> None:
    try:
        _store_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except OSError:
        # Failing to remember a mapping must never stop the user from working.
        pass


def load(key: str) -> dict[str, str]:
    entry = _load_all().get(key)
    if not isinstance(entry, dict):
        return {}
    mapping = entry.get("mapping")
    return mapping if isinstance(mapping, dict) else {}


def save(key: str, mapping: dict[str, str], label: str = "") -> None:
    if not key:
        return
    data = _load_all()
    order = max((entry.get("order", 0) for entry in data.values() if isinstance(entry, dict)), default=0)
    data[key] = {"mapping": mapping, "label": label, "order": order + 1}
    if len(data) > MAX_PROFILES:
        kept = sorted(data.items(), key=lambda pair: pair[1].get("order", 0))[-MAX_PROFILES:]
        data = dict(kept)
    _save_all(data)


def forget(key: str) -> None:
    data = _load_all()
    if data.pop(key, None) is not None:
        _save_all(data)


def clear() -> None:
    _save_all({})


def from_project(project, placeholders: list[str]) -> dict[str, str]:
    """The current mapping of a project in stored form.

    A field taken from a cell is stored by its address; a typed value is stored
    with a leading ``=``. Values that came from nowhere are not stored.
    """
    stored: dict[str, str] = {}
    for name in placeholders:
        if name in project.typed and project.typed[name] not in (None, ""):
            stored[name] = "=" + str(project.typed[name])
        elif name in project.mapping:
            stored[name] = project.mapping[name].address
    return stored
