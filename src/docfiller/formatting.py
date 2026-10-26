"""Value formatting in both directions.

**Reading.** A spreadsheet may hold a number as text — ``"3.365,00"``,
``"3,365.00"`` or ``"3365 mm"``. When a field is meant to be numeric, the text
is converted so that the document receives a properly formatted number rather
than whatever the cell happened to contain. When it cannot be converted the
value is left untouched and reported, never mangled.

**Writing.** A value placed into a document is rendered the way a person would
type it: whole numbers without a trailing ``.0``, decimals without rounding
away precision, dates as ``dd.mm.yyyy``.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

# Units that may trail a number in a cell. The unit is already printed in the
# document next to the field, so it is stripped when converting.
UNITS = (
    "mm", "cm", "m", "km", "kg", "g", "t", "ton", "kw", "hp", "ps", "cm3", "cm³",
    "l", "lt", "ml", "pcs", "pc", "%", "rpm", "km/h", "mph", "€", "$", "£",
)

_UNIT_PATTERN = re.compile(
    r"\s*(?:" + "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True)) + r")\.?$",
    re.IGNORECASE,
)
_NUMBER_BODY = re.compile(r"^[+-]?[\d.,']*\d[\d.,']*$")
_DOT_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})+$")
_COMMA_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+$")

DATE_FORMAT = "%d.%m.%Y"

# Kept in a decimal: enough for any measurement while dropping the binary noise
# of floating point (0.1 + 0.2 = 0.30000000000000004).
MAX_DECIMALS = 10

# Decimal separator used when writing numbers into documents. "," suits most
# of continental Europe; "." suits English-speaking countries. Configurable.
DECIMAL_SEPARATOR = ","


class NotANumber(ValueError):
    """The value could not be read as a number."""


def to_number(value: Any) -> float:
    """Read a number written in either common convention; raise NotANumber.

        "3365"      -> 3365.0
        "3.365"     -> 3365.0     (dot as thousands separator)
        "3.365,50"  -> 3365.5     (continental)
        "3,365.50"  -> 3365.5     (English)
        "3365,5"    -> 3365.5
        "3365 mm"   -> 3365.0     (unit removed)
        "1'234.5"   -> 1234.5     (Swiss)
    """
    if isinstance(value, bool):
        raise NotANumber("a yes/no value is not a number")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise NotANumber(f"unexpected type: {type(value).__name__}")

    text = value.strip().replace("\xa0", " ")
    if not text:
        raise NotANumber("empty text")
    text = _UNIT_PATTERN.sub("", text).strip().replace(" ", "").replace("'", "")
    if not _NUMBER_BODY.match(text):
        raise NotANumber(f"not readable as a number: {value!r}")

    if "," in text and "." in text:
        # Whichever separator comes last is the decimal one.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", "") if _COMMA_THOUSANDS.match(text) else text.replace(",", ".")
    elif _DOT_THOUSANDS.match(text):
        text = text.replace(".", "")

    try:
        return float(text)
    except ValueError as exc:
        raise NotANumber(f"not readable as a number: {value!r}") from exc


def looks_numeric(text: str) -> bool:
    try:
        to_number(text)
        return True
    except NotANumber:
        return False


def _decimal_text(value: float) -> str:
    text = f"{float(value):.{MAX_DECIMALS}f}"
    whole, _, fraction = text.partition(".")
    fraction = fraction.rstrip("0").ljust(2, "0")
    return f"{whole}.{fraction}"


def for_document(value: Any) -> str:
    """Render a value the way it should appear in a document."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (datetime, date)):
        return value.strftime(DATE_FORMAT)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return _decimal_text(value).replace(".", DECIMAL_SEPARATOR)
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def for_editing(value: Any) -> str:
    """Render a value for an input box (no locale tricks, nothing lost)."""
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime(DATE_FORMAT)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def from_editing(text: str, previous: Any) -> Any:
    """Turn what the user typed back into a value of the field's former type.

    If the field held a number, the text is converted so the document receives
    a formatted number rather than raw text. If conversion fails the text is
    kept as typed — nothing the user wrote is ever lost.
    """
    if not text:
        return None
    if isinstance(previous, (int, float)) and not isinstance(previous, bool):
        try:
            number = to_number(text)
        except NotANumber:
            return text
        return int(number) if isinstance(previous, int) else number
    return text


def single_line(text: str | None) -> str:
    """Collapse line breaks into single spaces; touch nothing else.

    A line break inside a justified paragraph makes Word stretch the words of
    that line across the whole width, so addresses and names are kept on one
    line.
    """
    if not text:
        return ""
    return re.sub(r"[ \t]*[\r\n]+[ \t]*", " ", str(text)).strip()
