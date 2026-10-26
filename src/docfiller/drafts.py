"""Drafts — what was entered is not lost when switching away and back.

A user fills in fields, loads other files (or goes to another page), then
returns. Without drafts every edit would be gone, because the spreadsheet is
read again and its values take over.

The draft is tied to the **loaded files**:

* Its identity is the files' names, sizes and modification times. If a
  spreadsheet is changed and saved, the identity changes and the old draft is
  not applied — stale values are never laid over a newer file.
* Only what the USER added is stored — typed values, re-pointed fields, form
  answers, the chosen document set and documents, the output folder — never the
  values read from the file. A corrected spreadsheet therefore still supplies
  its fresh values.
* Drafts belong to the account and stay on disk: closing the program does not
  lose them.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from . import paths

FILE_NAME = "drafts.json"
MAX_DRAFTS = 40


def identity(files: list[str] | list[Path]) -> str:
    parts = []
    for item in sorted(str(f) for f in files):
        path = Path(item)
        try:
            stat = path.stat()
            parts.append(f"{path.name}|{stat.st_size}|{int(stat.st_mtime)}")
        except OSError:
            parts.append(path.name)
    return hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()[:32]


def _encode(value: Any) -> Any:
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and "__date__" in value:
        try:
            return date.fromisoformat(value["__date__"])
        except ValueError:
            return None
    return value


def capture(fresh, current, **extra) -> dict:
    """What the user added on top of the freshly read project."""
    mapping_changes = {}
    for name in set(fresh.mapping) | set(current.mapping):
        before = fresh.mapping.get(name)
        after = current.mapping.get(name)
        before_address = before.address if before else ""
        after_address = after.address if after else ""
        if before_address != after_address:
            mapping_changes[name] = after_address  # "" = deliberately unmapped
    fresh_typed = fresh.typed
    typed = {
        name: _encode(value)
        for name, value in current.typed.items()
        if fresh_typed.get(name, object()) != value
    }
    record = {
        "typed": typed,
        "mapping": mapping_changes,
        "form_choices": {k: dict(v) for k, v in current.form_choices.items() if v},
        "document_set": current.document_set,
        "custom_set_name": current.custom_set_name,
        "copy_source_spreadsheets": current.copy_source_spreadsheets,
        "copy_attachments": current.copy_attachments,
    }
    record.update(extra)
    return record


def has_content(record: dict) -> bool:
    return bool(record.get("typed") or record.get("mapping") or record.get("form_choices")
                or record.get("document_set") or record.get("selected"))


def apply(project, record: dict) -> int:
    """Lay a stored draft over a freshly read project; return how much was restored."""
    restored = 0
    by_address = {lv.address: lv for lv in project.labels}
    for name, address in (record.get("mapping") or {}).items():
        if address:
            source = by_address.get(address)
            if source is None:
                continue  # the cell no longer exists in this file
            project.mapping[name] = source
        else:
            project.mapping.pop(name, None)
        restored += 1
    for name, value in (record.get("typed") or {}).items():
        project.typed[name] = _decode(value)
        restored += 1
    choices = record.get("form_choices") or {}
    if isinstance(choices, dict):
        for template, values in choices.items():
            if isinstance(values, dict) and values:
                project.form_choices[template] = dict(values)
                restored += 1
    if record.get("document_set"):
        project.document_set = record["document_set"]
        project.custom_set_name = record.get("custom_set_name")
    project.copy_source_spreadsheets = bool(record.get("copy_source_spreadsheets"))
    project.copy_attachments = bool(record.get("copy_attachments"))
    return restored


# ------------------------------------------------------------------- storage


def _store() -> Path:
    return paths.data_file(FILE_NAME)


def _load() -> dict:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load(key: str) -> dict | None:
    return _load().get(key) if key else None


def save(key: str, record: dict) -> None:
    if not key:
        return
    data = _load()
    order = max((v.get("_order", 0) for v in data.values() if isinstance(v, dict)), default=0)
    record = dict(record)
    record["_order"] = order + 1
    data[key] = record
    if len(data) > MAX_DRAFTS:
        data = dict(sorted(data.items(), key=lambda p: p[1].get("_order", 0))[-MAX_DRAFTS:])
    try:
        paths.atomic_write(_store(), json.dumps(data, ensure_ascii=False, indent=1))
    except OSError:
        pass  # failing to keep a draft never stops the user


def clear() -> None:
    try:
        paths.atomic_write(_store(), "{}")
    except OSError:
        pass
