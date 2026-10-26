"""What each loaded file is, and what was read from it.

The program never assumes "these three files will come". Any number and kind
of files may be loaded; each one is opened and reported on:

* **role** — a data source (a spreadsheet), a ready document that is only
  carried along (PDF, Word, image), or not supported,
* **sheets** and **filled cells** — the file's real structure,
* **captions read** — how many caption/value pairs were found,
* **unreadable values** — numbers stored as text that could not be read.

Nothing here ever raises. A damaged or unexpected file does not stop the job;
it is reported, and the user completes what is missing by hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import formatting, workbook

COPY_SUFFIXES = {".pdf", ".doc", ".docx", ".docm", ".jpg", ".jpeg", ".png"}
SPREADSHEET_SUFFIXES = set(workbook.SPREADSHEET_SUFFIXES)

DATA = "data"
COPY = "copy"
UNSUPPORTED = "unsupported"


@dataclass
class Analysis:
    path: Path
    role: str
    sheets: list[str] = field(default_factory=list)
    filled_cells: int = 0
    labels: list[workbook.LabelValue] = field(default_factory=list)
    unreadable_numbers: list[tuple[str, str]] = field(default_factory=list)  # (caption, raw)
    error: str | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def recognised(self) -> bool:
        return self.role == DATA and not self.error and bool(self.labels)

    def summary(self) -> str:
        """One line for the file row. The full text goes in details()."""
        if self.error:
            return self.error.strip().splitlines()[0]
        if self.role == COPY:
            return "ready document — not filled (copying it to the output is optional)"
        if self.role == UNSUPPORTED:
            return f"unsupported file type ({self.path.suffix or 'no extension'})"
        parts = [f"{len(self.labels)} captioned values read"]
        if self.unreadable_numbers:
            parts.append(f"{len(self.unreadable_numbers)} number(s) could not be read")
        return " · ".join(parts)

    def details(self) -> str:
        parts = []
        if self.error:
            parts.append(self.error.strip())
        if self.sheets:
            parts.append("Sheets: " + ", ".join(self.sheets))
        if self.filled_cells:
            parts.append(f"Filled cells scanned: {self.filled_cells}")
        if self.unreadable_numbers:
            parts.append(
                "Not readable as numbers: "
                + ", ".join(f"{label}={raw!r}" for label, raw in self.unreadable_numbers[:8])
            )
        return "\n\n".join(parts)


def _looks_like_number_with_text(value) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return bool(stripped) and stripped[0].isdigit() and not formatting.looks_numeric(stripped)


def analyse(path: str | Path) -> Analysis:
    """Analyse one file. NEVER raises."""
    path = Path(path)
    suffix = path.suffix.lower()
    if not path.exists():
        return Analysis(path=path, role=UNSUPPORTED, error="file not found")
    if suffix in COPY_SUFFIXES:
        return Analysis(path=path, role=COPY)
    if suffix not in SPREADSHEET_SUFFIXES:
        return Analysis(path=path, role=UNSUPPORTED)

    result = Analysis(path=path, role=DATA)
    try:
        cells = workbook.read_cells(path)
    except Exception as exc:  # noqa: BLE001 - a damaged file is reported, not fatal
        result.error = f"could not be opened: {exc}"
        return result
    result.filled_cells = len(cells)
    result.sheets = list(dict.fromkeys(c.sheet_name for c in cells))
    try:
        result.labels = workbook.label_values(cells)
    except Exception as exc:  # noqa: BLE001
        result.error = f"could not be read: {exc}"
        return result
    if not result.labels:
        result.error = "no captioned values were found in this file"
    result.unreadable_numbers = [
        (lv.label, lv.value) for lv in result.labels if _looks_like_number_with_text(lv.value)
    ]
    return result


def analyse_all(paths: list[str | Path]) -> list[Analysis]:
    return [analyse(p) for p in paths]
