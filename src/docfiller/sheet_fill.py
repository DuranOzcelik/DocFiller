"""Filling a spreadsheet from the program and handing back the same file.

Instead of opening a spreadsheet and hunting cell by cell for where each value
goes, the program finds the fillable fields itself; the user only types the
values, and gets back the SAME workbook with its structure untouched. The
filled copy can then be used as the data source of a job.

Two steps:

1. **Find the fields.** A field is a caption and the value cell that belongs to
   it — usually the next cell to the right, or the cell underneath in a table
   header. Unlike reading a data source, an EMPTY value cell counts too: blanks
   are exactly what is being filled. Merged cells are respected: a caption
   spread over several merged cells ends where its merge ends, and the program
   never writes into a caption.
2. **Write back.** Excel itself (COM) writes the values and saves a copy.
   Writing with a Python library could damage charts, shapes, macros and print
   settings it does not understand; with Excel's own engine only the target
   cells change and everything else stays byte-for-byte as it was. The source
   file is never modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import formatting, office, workbook

VALUE_SEARCH_WIDTH = 40


@dataclass
class Field:
    sheet: str
    sheet_index: int
    label: str
    row: int
    column: int
    value: Any = None

    @property
    def address(self) -> str:
        return f"{workbook.column_letter(self.column)}{self.row}"

    @property
    def key(self) -> str:
        return f"{self.sheet_index}!{self.address}"

    @property
    def text(self) -> str:
        return formatting.for_editing(self.value)


@dataclass
class _Sheet:
    name: str
    cells: dict[tuple[int, int], Any]
    merges: list[tuple[int, int, int, int]]  # (first row, first col, last row, last col)
    max_column: int

    def merge_of(self, row: int, column: int):
        for first_row, first_col, last_row, last_col in self.merges:
            if first_row <= row <= last_row and first_col <= column <= last_col:
                return first_row, first_col, last_row, last_col
        return None


def _read_sheets(path: Path) -> list[_Sheet]:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        import xlrd

        book = xlrd.open_workbook(str(path), formatting_info=True)
        sheets = []
        for sheet in book.sheets():
            cells = {}
            for r in range(min(sheet.nrows, workbook.MAX_ROWS)):
                for c, value in enumerate(sheet.row_values(r)[: workbook.MAX_COLUMNS]):
                    if value not in (None, "") and str(value).strip():
                        cells[(r + 1, c + 1)] = value
            merges = [(r1 + 1, c1 + 1, r2, c2) for r1, r2, c1, c2 in sheet.merged_cells]
            sheets.append(_Sheet(sheet.name, cells, merges, sheet.ncols))
        return sheets
    if suffix == ".csv":
        cells_list = workbook.read_cells(path)
        cells = {(c.row, c.column): c.value for c in cells_list}
        max_col = max((c.column for c in cells_list), default=0)
        return [_Sheet(path.stem, cells, [], max_col)]

    from openpyxl import load_workbook

    # Not read-only: merged ranges are only available in normal mode.
    book = load_workbook(str(path), data_only=True)
    try:
        sheets = []
        for sheet in book.worksheets:
            cells = {}
            for row in sheet.iter_rows(max_row=min(sheet.max_row, workbook.MAX_ROWS),
                                       max_col=min(sheet.max_column, workbook.MAX_COLUMNS)):
                for cell in row:
                    value = cell.value
                    if value is not None and str(value).strip():
                        cells[(cell.row, cell.column)] = value
            merges = [
                (m.min_row, m.min_col, m.max_row, m.max_col) for m in sheet.merged_cells.ranges
            ]
            sheets.append(_Sheet(sheet.title, cells, merges, sheet.max_column))
        return sheets
    finally:
        book.close()


def _anchor(sheet: _Sheet, row: int, column: int) -> tuple[int, int, int]:
    """(row, first column, last column) of the cell or merge at this position."""
    merge = sheet.merge_of(row, column)
    if merge is None:
        return row, column, column
    return merge[0], merge[1], merge[3]


def _value_cell(sheet: _Sheet, row: int, caption_last_col: int):
    """The value cell belonging to a caption whose merge ends at `caption_last_col`.

    Returns (column, value) — value None for an empty field — or None when
    there is no value cell. An adjacent cell is the value whatever it holds; a
    non-empty cell found only after a gap is treated as the NEXT caption, and the
    first empty cell before it becomes this caption's (empty) field.
    """
    column = caption_last_col + 1
    limit = min(caption_last_col + VALUE_SEARCH_WIDTH, max(sheet.max_column, caption_last_col + 1))
    first_empty = None
    adjacent = True
    while column <= limit:
        anchor_row, first_col, last_col = _anchor(sheet, row, column)
        value = sheet.cells.get((anchor_row, first_col))
        if value is None:
            if first_empty is None and anchor_row == row:
                first_empty = first_col
            adjacent = False
            column = last_col + 1
            continue
        if adjacent or not workbook.looks_like_label(value):
            return first_col, value
        break  # the next caption: this one's field is the gap before it
    if first_empty is not None:
        return first_empty, None
    return None


def extract_fields(path: str | Path) -> tuple[list[Field], list[str]]:
    """The fillable fields of a workbook and its sheet names.

    Excel is not started: the file is read once, directly.
    """
    path = Path(path)
    sheets = _read_sheets(path)
    result: list[Field] = []
    seen: set[str] = set()
    for index, sheet in enumerate(sheets):
        for (row, column) in sorted(sheet.cells):
            value = sheet.cells[(row, column)]
            if not workbook.looks_like_label(value):
                continue
            merge = sheet.merge_of(row, column)
            if merge is not None and (merge[0], merge[1]) != (row, column):
                continue
            last_col = merge[3] if merge else column
            found = _value_cell(sheet, row, last_col)
            if found is None:
                continue
            value_col, cell_value = found
            field = Field(
                sheet=sheet.name,
                sheet_index=index,
                label=str(value).strip(),
                row=row,
                column=value_col,
                value=cell_value,
            )
            if field.key in seen or (row, value_col) == (row, column):
                continue
            seen.add(field.key)
            result.append(field)
    return result, [s.name for s in sheets]


def as_cell_value(text: str):
    """What to write into a cell for typed text: numbers as numbers, so Excel
    does not store them as text and its formulas keep working."""
    if not text:
        return ""
    try:
        number = formatting.to_number(text)
    except formatting.NotANumber:
        return text
    return int(number) if number.is_integer() and abs(number) < 1e15 else number


def save_copy(source: str | Path, target: str | Path, values: dict[str, Any]) -> Path:
    """Have Excel write `values` and save the workbook as `target`.

    `values` maps a field key (``"<sheet index>!<address>"``) to the new value.
    Only those cells are touched; formatting, formulas, charts, print settings
    and macros are preserved by Excel itself. The source file is opened
    read-only and never changed.
    """
    source, target = Path(source).resolve(), Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    def body(excel):
        book = excel.Workbooks.Open(
            str(source),
            ReadOnly=True,
            UpdateLinks=0,
            IgnoreReadOnlyRecommended=True,
            Notify=False,
            Password="",
            WriteResPassword="",
        )
        try:
            for key, value in values.items():
                sheet_index, _, address = key.partition("!")
                try:
                    book.Worksheets(int(sheet_index) + 1).Range(address).Value = (
                        "" if value is None else value
                    )
                except Exception:  # noqa: BLE001 - one cell failing must not stop the rest
                    continue
            if target.exists():
                target.unlink()
            # No file format is given: Excel keeps the source file's own format.
            book.SaveCopyAs(str(target))
        finally:
            book.Close(False)

    try:
        office.EXCEL.run(body)
    except office.OfficeUnavailable as exc:
        raise RuntimeError("Microsoft Excel is required to fill a spreadsheet.") from exc
    if not target.exists():
        raise RuntimeError("The file could not be saved.")
    return target
