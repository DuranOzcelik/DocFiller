"""The record library — enter details once, pick them in every job.

A record is a named group of values that appear together in documents again
and again: a customer, a supplier, an issuing organisation, a site. It stores
values by **placeholder name**, so choosing a record fills exactly the
placeholders it knows about and leaves everything else alone.

What a record contains is never altered: no abbreviation, no change of case, no
reformatting. Only line breaks are turned into spaces, because a line break
inside a justified paragraph makes Word stretch that line across the page.
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import formatting, paths

FILE_NAME = "record_library.json"


@dataclass
class Record:
    name: str
    values: dict[str, str] = field(default_factory=dict)


def _key(name: str | None) -> str:
    """Comparison form of a record name.

    ``str.lower()`` is not enough: on a dotted capital I it leaves a combining
    dot behind, so two names that look identical would not match. Marks are
    decomposed and dropped first, whatever the user typed or pasted.
    """
    text = formatting.single_line(name).replace("ı", "i").replace("İ", "I")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().strip()


def _store() -> Path:
    return paths.data_file(FILE_NAME)


def _load() -> list[dict]:
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def _save(entries: list[dict]) -> None:
    paths.atomic_write(_store(), json.dumps(entries, ensure_ascii=False, indent=2))


def records() -> list[Record]:
    result = []
    for entry in _load():
        name = formatting.single_line(entry.get("name"))
        if not name:
            continue
        values = entry.get("values")
        values = values if isinstance(values, dict) else {}
        result.append(Record(name=name, values={str(k): str(v) for k, v in values.items()}))
    result.sort(key=lambda r: r.name.casefold())
    return result


def find(name: str | None) -> Record | None:
    if not name:
        return None
    wanted = _key(name)
    return next((r for r in records() if _key(r.name) == wanted), None)


def save(record: Record) -> Record:
    """Add a record, or update the one with the same name."""
    record = Record(
        name=formatting.single_line(record.name),
        values={k: formatting.single_line(v) for k, v in record.values.items() if k.strip()},
    )
    if not record.name:
        return record
    entries = _load()
    for entry in entries:
        if _key(entry.get("name")) == _key(record.name):
            entry.update({"name": record.name, "values": record.values})
            break
    else:
        entries.append({"name": record.name, "values": record.values})
    _save(entries)
    return record


def delete(name: str) -> bool:
    entries = _load()
    kept = [e for e in entries if _key(e.get("name")) != _key(name)]
    if len(kept) == len(entries):
        return False
    _save(kept)
    return True


def find_by_value(values: dict[str, str]) -> Record | None:
    """A saved record whose values agree with these (used to recognise one
    already in the library when a spreadsheet supplies the same details)."""
    candidates = {k: _key(v) for k, v in values.items() if v}
    if not candidates:
        return None
    for record in records():
        shared = [k for k in record.values if k in candidates and record.values[k]]
        if shared and all(_key(record.values[k]) == candidates[k] for k in shared):
            return record
    return None
