"""The project — every value that goes into one job's documents.

A value can come from several places. They are kept as separate layers rather
than merged into one dictionary, so the program always knows *why* a field
holds what it holds, can show that to the user, and can undo a change cleanly:

1. **typed** — what the user entered. Always wins. An empty string is a
   deliberate blank ("leave this empty"), not a missing value.
2. **source** — the spreadsheet cell matched to the placeholder.
3. **profile** — the signed-in person's own details (name, title, licence no.).
4. **default** — the document set's standard value for the field.
5. **automatic** — fields the program fills itself, such as today's date.

Anything still empty after that is left blank in the document. Nothing is ever
guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import document_sets, formatting
from .workbook import LabelValue

# Placeholders filled with today's date at production time. The user never has
# to type them and cannot be left with yesterday's date in a re-used draft.
AUTOMATIC_FIELDS = frozenset({"today", "current_date", "todays_date", "date_today"})

TYPED, SOURCE, PROFILE, DEFAULT, AUTOMATIC, EMPTY = (
    "typed", "source", "profile", "default", "automatic", "empty"
)


@dataclass
class Project:
    # --- values, by layer
    typed: dict[str, Any] = field(default_factory=dict)
    mapping: dict[str, LabelValue] = field(default_factory=dict)
    profile: dict[str, str] = field(default_factory=dict)

    # --- what was loaded
    source_files: list[str] = field(default_factory=list)     # spreadsheets read
    attachments: list[str] = field(default_factory=list)      # ready documents (PDF, Word, images)
    labels: list[LabelValue] = field(default_factory=list)    # every caption/value pair read

    # --- choices
    document_set: str | None = None
    custom_set_name: str | None = None      # when the set is "Other"
    form_choices: dict[str, dict[str, str]] = field(default_factory=dict)
    copy_source_spreadsheets: bool = False  # deliver the spreadsheet itself too
    copy_attachments: bool = False          # copy ready documents into the output

    # ------------------------------------------------------------ the layers

    def _default(self, name: str) -> Any:
        document_set = document_sets.get(self.document_set)
        return document_set.defaults.get(name) if document_set else None

    def origin(self, name: str) -> str:
        if name in AUTOMATIC_FIELDS:
            return AUTOMATIC
        if name in self.typed:
            return TYPED
        if name in self.mapping:
            return SOURCE
        if self.profile.get(name):
            return PROFILE
        if self._default(name):
            return DEFAULT
        return EMPTY

    def value(self, name: str) -> Any:
        """The value the document will receive for `name` (None when blank)."""
        if name in AUTOMATIC_FIELDS:
            return date.today()
        if name in self.typed:
            value = self.typed[name]
            return None if value in ("", None) else value
        if name in self.mapping:
            return self.mapping[name].value
        if self.profile.get(name):
            return self.profile[name]
        return self._default(name) or None

    def text(self, name: str) -> str:
        return formatting.for_document(self.value(name))

    def is_filled(self, name: str) -> bool:
        value = self.value(name)
        return not (value is None or (isinstance(value, str) and not value.strip()))

    # ---------------------------------------------------------------- edits

    def type_value(self, name: str, value: Any) -> None:
        self.typed[name] = value

    def clear_typed(self, name: str) -> None:
        self.typed.pop(name, None)

    def point_to(self, name: str, source: LabelValue | None) -> None:
        """Take `name` from another caption (None: from no caption)."""
        self.typed.pop(name, None)
        if source is None:
            self.mapping.pop(name, None)
        else:
            self.mapping[name] = source

    # -------------------------------------------------------------- context

    def context(self, placeholders: list[str]) -> dict[str, str]:
        """Name/value pairs for rendering. Missing values become empty strings —
        a blank must never come out as the literal text ``{{ name }}``."""
        return {name: self.text(name) for name in placeholders}

    # ------------------------------------------------------------- summary

    def set_display_name(self) -> str:
        if self.document_set == document_sets.OTHER:
            return self.custom_set_name or ""
        document_set = document_sets.get(self.document_set)
        return document_set.name if document_set else ""

    _REFERENCE = re.compile(r"(^|_)(no|number|nr|ref|reference|id|code|serial)($|_)")

    def reference(self) -> str:
        """An identifying value for the history list (order no., serial no. …)."""
        for name in list(self.typed) + list(self.mapping):
            if self._REFERENCE.search(name.lower()) and self.is_filled(name):
                return self.text(name)
        return ""

    def headline(self) -> str:
        """A short description for the history list: the first name-like value."""
        for name in list(self.typed) + list(self.mapping):
            if "name" in name.lower() and self.is_filled(name):
                return self.text(name)
        return ""

    def source_text(self) -> str:
        """All captions and values read, as one text (for set suggestions)."""
        return " ".join(f"{lv.label} {lv.value}" for lv in self.labels)
