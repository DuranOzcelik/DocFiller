"""Field memory — pick from what you typed before, in every field.

Every value written into a field is added to that field's own list; next time
the same field comes up:

* suggestions appear as soon as you start typing, and
* the arrow beside the box lists everything remembered for it.

Values belong to the signed-in account and never leave the computer. Nothing is
shortened or altered: what was typed is what is stored and what comes back.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import paths

FILE_NAME = "field_memory.json"

# Values kept per field, most recent first.
MAX_VALUES = 25

# Fields never remembered: their value belongs to one job only, and offering it
# again would make it too easy to put last job's value into this one. The user
# can add to this list from the Library page.
_excluded: set[str] = set()


def _store() -> Path:
    return paths.data_file(FILE_NAME)


def _load() -> dict[str, list[str]]:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    excluded = data.pop("__excluded__", [])
    if isinstance(excluded, list):
        _excluded.update(str(x) for x in excluded)
    return {
        str(k): [str(v) for v in values if str(v).strip()]
        for k, values in data.items()
        if isinstance(values, list)
    }


def _save(data: dict[str, list[str]]) -> None:
    payload = dict(data)
    payload["__excluded__"] = sorted(_excluded)
    try:
        paths.atomic_write(_store(), json.dumps(payload, ensure_ascii=False, indent=2))
    except OSError:
        pass  # failing to remember never stops the user


def values(field: str) -> list[str]:
    """Values typed into this field before, most recent first."""
    return _load().get(field, [])


def remember(field: str, value) -> None:
    remember_many({field: value})


def remember_many(entries: dict[str, object]) -> None:
    """Remember several fields in one write (called after a job)."""
    data = _load()
    changed = False
    for field, value in entries.items():
        if not field or field in _excluded:
            continue
        text = "" if value is None else str(value).strip()
        if len(text) < 2:
            continue
        kept = [v for v in data.get(field, []) if v != text]
        kept.insert(0, text)
        kept = kept[:MAX_VALUES]
        if data.get(field) != kept:
            data[field] = kept
            changed = True
    if changed:
        _save(data)


def forget(field: str, value: str | None = None) -> None:
    """Forget one value, or the whole field when `value` is None."""
    data = _load()
    if field not in data:
        return
    if value is None:
        del data[field]
    else:
        data[field] = [v for v in data[field] if v != value]
        if not data[field]:
            del data[field]
    _save(data)


def clear() -> None:
    _save({})


def summary() -> list[tuple[str, int]]:
    """(field, number of remembered values) for the Library page."""
    return sorted(((f, len(v)) for f, v in _load().items()), key=lambda pair: pair[0])


def excluded() -> list[str]:
    _load()
    return sorted(_excluded)


def set_excluded(fields: list[str]) -> None:
    data = _load()
    _excluded.clear()
    _excluded.update(f.strip() for f in fields if f.strip())
    for field in list(data):
        if field in _excluded:
            del data[field]
    _save(data)
