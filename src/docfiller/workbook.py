"""Read a spreadsheet and recover the label/value pairs a human sees in it.

Addressing cells directly (``Sheet1!B4``) only works for one exact file. Real
source files drift: a row is inserted, a block moves to another sheet, someone
saves the ``.xls`` as ``.xlsx``. A fixed address then points at the wrong cell
and the wrong value is written into the document without anything looking wrong.

So values are located **by their label**. Every populated cell is scanned; when
a cell holds text that reads like a caption ("Customer Name", "Date:") the value
is taken from the nearest populated cell to its right, or directly below when
the row continues no further. That survives inserted rows, shifted columns and
re-saved formats, and it is what lets the program map an unfamiliar workbook
automatically.

No value is ever computed or invented. Whatever the spreadsheet holds is what
reaches the document.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# A sheet is scanned up to this size. Generous for real forms while keeping a
# pathological sheet (millions of empty cells) from stalling the program.
MAX_ROWS = 2000
MAX_COLUMNS = 120

# How far to the right of a label its value may sit.
VALUE_SEARCH_WIDTH = 40

# Labels longer than this are prose, not captions.
MAX_LABEL_LENGTH = 80

SPREADSHEET_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".csv")


@dataclass(frozen=True)
class Cell:
    sheet_index: int
    sheet_name: str
    row: int
    column: int
    value: Any

    @property
    def address(self) -> str:
        return f"{self.sheet_name}!{column_letter(self.column)}{self.row}"


@dataclass(frozen=True)
class LabelValue:
    """A caption found in the sheet and the value that belongs to it."""

    label: str
    value: Any
    address: str
    sheet_name: str
    row: int
    column: int

    @property
    def display(self) -> str:
        return f"{self.label} — {format_value(self.value)}  [{self.address}]"


def column_letter(index: int) -> str:
    """1 -> A, 27 -> AA."""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def format_value(value: Any) -> str:
    """Render a cell value the way it should appear in a document.

    Spreadsheets store every number as a float; writing "2026.0" where the sheet
    shows "2026" would be wrong, so whole numbers lose the decimal part. Genuine
    decimals keep their precision and are never rounded.
    """
    from datetime import date, datetime

    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (datetime, date)):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        text = f"{value:.10f}".rstrip("0")
        return text.rstrip(".") if text.endswith(".") else text
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


# --------------------------------------------------------------------- reading


def read_cells(path: str | Path) -> list[Cell]:
    """Read every populated cell of a workbook, whatever its format."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv(path)
    if suffix == ".xls":
        return _read_xls(path)
    return _read_xlsx(path)


def _collect(sheets: Iterable[tuple[str, Iterable[Iterable[Any]]]]) -> list[Cell]:
    cells: list[Cell] = []
    for sheet_index, (sheet_name, rows) in enumerate(sheets):
        for row_number, row in enumerate(rows, start=1):
            if row_number > MAX_ROWS:
                break
            for column_number, value in enumerate(row, start=1):
                if column_number > MAX_COLUMNS:
                    break
                if value is None or (isinstance(value, str) and not value.strip()):
                    continue
                cells.append(Cell(sheet_index, sheet_name, row_number, column_number, value))
    return cells


def _read_xlsx(path: Path) -> list[Cell]:
    from openpyxl import load_workbook

    # data_only=True returns the cached result of each formula rather than the
    # formula text, which is what a reader of the sheet actually sees.
    book = load_workbook(str(path), data_only=True, read_only=True)
    try:
        return _collect((sheet.title, sheet.iter_rows(values_only=True)) for sheet in book.worksheets)
    finally:
        book.close()


def _read_xls(path: Path) -> list[Cell]:
    import xlrd

    book = xlrd.open_workbook(str(path))
    sheets = []
    for sheet in book.sheets():
        rows = [sheet.row_values(index) for index in range(sheet.nrows)]
        sheets.append((sheet.name, rows))
    return _collect(sheets)


def _read_csv(path: Path) -> list[Cell]:
    # Spreadsheet exports are frequently UTF-8 with a byte-order mark; utf-8-sig
    # reads both that and plain UTF-8 correctly.
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            dialect: Any = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        rows = [row for row in csv.reader(handle, dialect)]
    return _collect([(path.stem, rows)])


# -------------------------------------------------------------------- labelling

_PUNCTUATION = re.compile(r"[\s:：*.\-_/\\()\[\]]+")


# A few letters do not decompose into "base + accent" under NFKD and so have to
# be folded explicitly. The Turkish dotless i is the common one; the dotted
# capital I is handled by the decomposition below but is listed for symmetry.
_EXPLICIT_FOLDS = {
    "\u0131": "i",  # i without a dot
    "\u0130": "i",  # I with a dot above
    "\u00df": "ss",  # sharp s
    "\u00f8": "o",  # o with stroke
    "\u0111": "d",  # d with stroke
    "\u0142": "l",  # l with stroke
}


def normalise(text: str) -> str:
    """Fold a caption to a comparable key: no accents, no punctuation, no case.

    Captions are written by people, so "Numero", "NUMERO" and "Numéro  :" all
    have to compare equal. Accented letters are decomposed
    and their marks dropped, which works for every Latin-script language rather
    than a hand-written list for one of them.

    ``str.lower()`` alone is not enough: applied to a dotted capital I it leaves
    a combining dot behind, so two strings that look identical on screen stop
    comparing equal.
    """
    folded = "".join(_EXPLICIT_FOLDS.get(character, character) for character in text)
    decomposed = unicodedata.normalize("NFKD", folded)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return _PUNCTUATION.sub(" ", without_marks.lower()).strip()


def looks_like_label(value: Any) -> bool:
    """Is this cell a caption rather than a piece of data?"""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > MAX_LABEL_LENGTH:
        return False
    # A caption contains letters; a bare number or code is data.
    return any(character.isalpha() for character in text)


# A row holding at least this many captions side by side is a table header, not
# a caption followed by its value.
HEADER_RUN = 3


def _row_runs(row: dict[int, Cell]) -> dict[int, int]:
    """For each caption in the row, how many captions sit directly beside it.

    Adjacency is measured in real column numbers, not in list position: two
    caption/value pairs separated by an empty column are two short runs, not one
    long one, and must not be read as a table header.
    """
    columns = sorted(row)
    runs: dict[int, int] = {}
    index = 0
    while index < len(columns):
        if not looks_like_label(row[columns[index]].value):
            index += 1
            continue
        end = index
        while (
            end + 1 < len(columns)
            and columns[end + 1] == columns[end] + 1
            and looks_like_label(row[columns[end + 1]].value)
        ):
            end += 1
        length = end - index + 1
        for position in range(index, end + 1):
            runs[columns[position]] = length
        index = end + 1
    return runs


def label_values(cells: list[Cell]) -> list[LabelValue]:
    """Pair every caption in the sheet with the value that belongs to it.

    Two layouts cover virtually every real form:

    * ``Caption | value`` across a row — by far the most common.
    * a header row of captions with the values underneath, as in an exported
      table.

    They are told apart by how many captions sit *directly* beside one another:
    three or more adjacent captions read as a header, so the value is taken from
    the row below; anything shorter reads as a form row and the value is taken
    from the right. Each case falls back to the other, so an unusual sheet still
    yields a pair instead of nothing.

    A value is never rejected for looking like text. A company name is
    indistinguishable from a caption, and discarding it would silently blank
    every non-numeric field.
    """
    by_position: dict[tuple[int, int], dict[int, Cell]] = {}
    for cell in cells:
        by_position.setdefault((cell.sheet_index, cell.row), {})[cell.column] = cell

    runs_by_row = {key: _row_runs(row) for key, row in by_position.items()}

    results: list[LabelValue] = []
    seen: set[tuple[str, str]] = set()
    for cell in cells:
        if not looks_like_label(cell.value):
            continue
        key = (cell.sheet_index, cell.row)
        row = by_position.get(key, {})
        looks_like_header = runs_by_row.get(key, {}).get(cell.column, 1) >= HEADER_RUN

        below = _value_below(by_position, cell)
        right = _value_to_the_right(row, cell.column)
        value_cell = (below or right) if looks_like_header else (right or below)
        if value_cell is None:
            continue

        label = str(cell.value).strip()
        # The same caption can legitimately appear on several sheets; the same
        # caption at the same address is one we have already taken.
        identity = (normalise(label), value_cell.address)
        if identity in seen:
            continue
        seen.add(identity)
        results.append(
            LabelValue(
                label=label,
                value=value_cell.value,
                address=value_cell.address,
                sheet_name=cell.sheet_name,
                row=cell.row,
                column=cell.column,
            )
        )
    return results


def _value_to_the_right(row: dict[int, Cell], column: int) -> Cell | None:
    """First populated cell to the right of a caption."""
    for offset in range(1, VALUE_SEARCH_WIDTH + 1):
        cell = row.get(column + offset)
        if cell is not None:
            return cell
    return None


def _value_below(
    by_position: dict[tuple[int, int], dict[int, Cell]], label_cell: Cell
) -> Cell | None:
    """Populated cell directly under a caption, if there is one."""
    row = by_position.get((label_cell.sheet_index, label_cell.row + 1), {})
    return row.get(label_cell.column)


def read_source(path: str | Path) -> list[LabelValue]:
    """Convenience: read a file and return its label/value pairs."""
    return label_values(read_cells(path))
