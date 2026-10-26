"""Job log — what was produced, when, and where it went.

Only the **record** of a job is kept, never the documents: no content is held
in memory or in the log. Each entry says when the job ran, for which document
set, from which source files, which documents were produced and in which folder
they were saved. Opening an entry takes the user to that folder.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths

FILE_NAME = "history.json"

# The log keeps the most recent entries only.
MAX_ENTRIES = 500

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass
class Entry:
    timestamp: str
    document_set: str | None = None
    subject: str | None = None          # a short description, e.g. the first key value
    reference: str | None = None        # an identifying value if one exists
    output_folder: str | None = None
    source_files: list[str] = field(default_factory=list)   # file NAMES only
    documents: list[str] = field(default_factory=list)      # file NAMES only
    warning_count: int = 0

    @property
    def folder_exists(self) -> bool:
        return bool(self.output_folder) and Path(self.output_folder).is_dir()

    def readable_time(self) -> str:
        try:
            return datetime.strptime(self.timestamp, TIME_FORMAT).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return self.timestamp


def _store() -> Path:
    return paths.data_file(FILE_NAME)


def entries() -> list[Entry]:
    """Most recent first. An unreadable log reads as empty, never as an error."""
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    result = []
    for raw in data if isinstance(data, list) else []:
        if not isinstance(raw, dict) or not raw.get("timestamp"):
            continue
        known = {k: raw.get(k) for k in Entry.__dataclass_fields__ if k in raw}
        known["source_files"] = [str(x) for x in known.get("source_files") or []]
        known["documents"] = [str(x) for x in known.get("documents") or []]
        known["warning_count"] = int(known.get("warning_count") or 0)
        try:
            result.append(Entry(**known))
        except TypeError:
            continue
    return result


def _write(items: list[Entry]) -> None:
    try:
        paths.atomic_write(
            _store(), json.dumps([asdict(e) for e in items[:MAX_ENTRIES]], ensure_ascii=False, indent=2)
        )
    except OSError:
        pass  # a job never fails because its log entry could not be written


def record(result, output_folder: str | Path) -> Entry | None:
    """Add an entry for a finished job (an engine.JobResult)."""
    project = getattr(result, "project", None)
    if project is None:
        return None
    entry = Entry(
        timestamp=datetime.now().strftime(TIME_FORMAT),
        document_set=project.set_display_name() or None,
        subject=project.headline() or None,
        reference=project.reference() or None,
        output_folder=str(Path(output_folder).resolve()),
        source_files=[Path(p).name for p in project.source_files],
        documents=[p.name for p in result.pdfs] + [p.name for p in result.copied_files],
        warning_count=len(result.warnings),
    )
    _write([entry] + entries())
    return entry


def clear() -> None:
    _write([])
