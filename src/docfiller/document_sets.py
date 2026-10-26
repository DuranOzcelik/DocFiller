"""Document sets — which documents a kind of job needs.

Most work comes in a few recurring kinds, and each kind always needs the same
documents. A document set captures that once:

* **templates** — the documents the job requires; they come pre-ticked and are
  marked "required" in the list (any other template can still be added),
* **required fields** — placeholders that must not be blank in a given
  document; a blank one is flagged before production and in the validation,
* **defaults** — values used when nothing else supplies one, such as a standard
  product description for that kind of job,
* **source PDF** — whether the source spreadsheet itself should also be printed
  to PDF alongside the documents,
* **keywords** — words that, found in a source file, suggest this set.

The program only ever **suggests** a set. The user always confirms it, and a
job that fits no set is done with "Other", for which the user types a name.

Sets belong to the signed-in account and are edited on the Library page.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths

FILE_NAME = "document_sets.json"

OTHER = "__other__"


@dataclass
class DocumentSet:
    id: str
    name: str
    templates: list[str] = field(default_factory=list)
    required_fields: dict[str, list[str]] = field(default_factory=dict)
    defaults: dict[str, str] = field(default_factory=dict)
    export_source_pdf: bool = True
    keywords: list[str] = field(default_factory=list)


def _slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name.replace("ı", "i").replace("İ", "I"))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]+", "-", plain).strip("-").lower() or "set"


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


def _from_dict(entry: dict) -> DocumentSet | None:
    if not entry.get("id") or not entry.get("name"):
        return None
    required = entry.get("required_fields") or {}
    defaults = entry.get("defaults") or {}
    return DocumentSet(
        id=str(entry["id"]),
        name=str(entry["name"]),
        templates=[str(t) for t in entry.get("templates") or []],
        required_fields={
            str(k): [str(x) for x in v] for k, v in required.items() if isinstance(v, list)
        } if isinstance(required, dict) else {},
        defaults={str(k): str(v) for k, v in defaults.items()} if isinstance(defaults, dict) else {},
        export_source_pdf=bool(entry.get("export_source_pdf", True)),
        keywords=[str(k) for k in entry.get("keywords") or [] if str(k).strip()],
    )


def all_sets() -> list[DocumentSet]:
    result = [s for s in (_from_dict(e) for e in _load()) if s is not None]
    result.sort(key=lambda s: s.name.casefold())
    return result


def get(set_id: str | None) -> DocumentSet | None:
    if not set_id or set_id == OTHER:
        return None
    return next((s for s in all_sets() if s.id == set_id), None)


def save(document_set: DocumentSet) -> DocumentSet:
    """Create or update a set. A new set gets an id derived from its name."""
    entries = _load()
    if not document_set.id:
        taken = {e.get("id") for e in entries}
        base = _slug(document_set.name)
        candidate, suffix = base, 2
        while candidate in taken or candidate == OTHER:
            candidate = f"{base}-{suffix}"
            suffix += 1
        document_set.id = candidate
    entries = [e for e in entries if e.get("id") != document_set.id]
    entries.append(asdict(document_set))
    _save(entries)
    return document_set


def delete(set_id: str) -> bool:
    entries = _load()
    kept = [e for e in entries if e.get("id") != set_id]
    if len(kept) == len(entries):
        return False
    _save(kept)
    return True


def required_templates(set_id: str | None) -> list[str]:
    document_set = get(set_id)
    return list(document_set.templates) if document_set else []


def export_source_pdf(set_id: str | None) -> bool:
    document_set = get(set_id)
    return document_set.export_source_pdf if document_set else True


# ---------------------------------------------------------------- suggestion


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text).replace("ı", "i").replace("İ", "I"))
    return "".join(c for c in plain if not unicodedata.combining(c)).casefold()


def suggest(source_text: str, placeholders_with_source: set[str], templates_by_name: dict) -> str | None:
    """Pick the set that best fits the loaded files, or None when nothing fits.

    Two signals count: a set's keywords appearing anywhere in the source files,
    and how many of the set's placeholders actually found a value in them. A
    suggestion is only made when the evidence is clear; the user confirms it
    either way.
    """
    haystack = _fold(source_text)
    best_id, best_score = None, 0.0
    for document_set in all_sets():
        keyword_hits = sum(1 for k in document_set.keywords if _fold(k) in haystack)
        names = {
            p
            for t in document_set.templates
            if t in templates_by_name
            for p in templates_by_name[t].placeholders
        }
        coverage = len(names & placeholders_with_source) / len(names) if names else 0.0
        score = keyword_hits * 1.0 + coverage
        if score > best_score:
            best_id, best_score = document_set.id, score
    return best_id if best_score >= 0.5 else None
