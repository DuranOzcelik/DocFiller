"""Match template placeholders to spreadsheet labels automatically.

``{{ customer_name }}`` and a cell captioned "Customer Name:" clearly belong
together, and so do ``{{ issue_date }}`` and "Date of issue". Working that out
mechanically is what saves the user from mapping dozens of fields by hand.

Scoring is deliberately simple and explainable, because the user sees the result
and has to judge it: an exact match outranks a containment, which outranks
shared words, which outranks a fuzzy character similarity. Anything below
``ACCEPT_THRESHOLD`` is left unmatched rather than guessed at — a wrong value in
a delivered document is far more expensive than an empty field the user fills in
themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .workbook import LabelValue, normalise

# Minimum score for the program to propose a match on its own.
ACCEPT_THRESHOLD = 0.62

# Words that carry no distinguishing meaning in a caption.
STOP_WORDS = {"the", "of", "a", "an", "no", "nr", "num", "number", "name", "date", "value"}


@dataclass
class Match:
    """One placeholder and the source chosen for it."""

    placeholder: str
    source: LabelValue | None = None
    score: float = 0.0
    manual: bool = False
    literal: str | None = None

    @property
    def matched(self) -> bool:
        return self.source is not None or self.literal is not None

    @property
    def origin(self) -> str:
        if self.literal is not None:
            return "typed in"
        if self.source is None:
            return "not mapped"
        return "chosen" if self.manual else f"auto ({self.score:.0%})"


def humanise(placeholder: str) -> str:
    """``customer_name`` -> ``customer name``."""
    return normalise(placeholder.replace("_", " "))


def _tokens(text: str) -> set[str]:
    words = {word for word in text.split() if word}
    meaningful = words - STOP_WORDS
    # If a caption is made entirely of stop words, comparing nothing to nothing
    # would score a perfect match, so fall back to the full set.
    return meaningful or words


def score(placeholder: str, label: str) -> float:
    """How strongly does `label` look like the source for `placeholder`?

    Returns 0.0 (unrelated) to 1.0 (identical).
    """
    left = humanise(placeholder)
    right = normalise(label)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_tokens = _tokens(left)
    right_tokens = _tokens(right)

    # One caption fully contains the other: "date" inside "date of issue".
    containment = 0.0
    if left in right or right in left:
        shorter, longer = sorted((len(left), len(right)))
        containment = 0.70 + 0.25 * (shorter / longer)

    shared = left_tokens & right_tokens
    overlap = 0.0
    if shared:
        overlap = 0.55 + 0.40 * (len(shared) / len(left_tokens | right_tokens))

    fuzzy = SequenceMatcher(None, left, right).ratio() * 0.85

    return round(min(1.0, max(containment, overlap, fuzzy)), 4)


def best_match(placeholder: str, sources: list[LabelValue]) -> tuple[LabelValue | None, float]:
    """Pick the strongest source for one placeholder."""
    best: LabelValue | None = None
    best_score = 0.0
    for source in sources:
        value = score(placeholder, source.label)
        if value > best_score:
            best, best_score = source, value
    return best, best_score


def auto_map(placeholders: list[str], sources: list[LabelValue]) -> list[Match]:
    """Propose a source for each placeholder, in the order given.

    A source may legitimately feed several placeholders, so sources are not
    consumed: each placeholder independently takes the best candidate it finds.
    """
    matches: list[Match] = []
    for placeholder in placeholders:
        source, value = best_match(placeholder, sources)
        if source is None or value < ACCEPT_THRESHOLD:
            matches.append(Match(placeholder=placeholder))
        else:
            matches.append(Match(placeholder=placeholder, source=source, score=value))
    return matches


def apply_saved(
    matches: list[Match], saved: dict[str, str], sources: list[LabelValue]
) -> list[Match]:
    """Re-apply a stored mapping over freshly proposed matches.

    ``saved`` maps a placeholder to either a cell address or, when prefixed with
    ``=``, a literal the user typed. A stored address that no longer exists in
    the current file is dropped rather than silently mapping to nothing.
    """
    by_address = {source.address: source for source in sources}
    for match in matches:
        stored = saved.get(match.placeholder)
        if stored is None:
            continue
        if stored.startswith("="):
            match.literal = stored[1:]
            match.source = None
            match.manual = True
            continue
        source = by_address.get(stored)
        if source is not None:
            match.source = source
            match.score = 1.0
            match.manual = True
    return matches


def to_saved(matches: list[Match]) -> dict[str, str]:
    """Serialise matches into the compact form stored in a profile."""
    stored: dict[str, str] = {}
    for match in matches:
        if match.literal is not None:
            stored[match.placeholder] = "=" + match.literal
        elif match.source is not None:
            stored[match.placeholder] = match.source.address
    return stored


def context(matches: list[Match]) -> dict[str, str]:
    """Build the name/value mapping handed to the renderer.

    Unmatched placeholders are included as empty strings: a missing value must
    leave a blank in the document, never the literal text ``{{ name }}``.
    """
    from .workbook import format_value

    values: dict[str, str] = {}
    for match in matches:
        if match.literal is not None:
            values[match.placeholder] = match.literal
        elif match.source is not None:
            values[match.placeholder] = format_value(match.source.value)
        else:
            values[match.placeholder] = ""
    return values
