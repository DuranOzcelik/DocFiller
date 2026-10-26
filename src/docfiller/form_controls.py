"""The template's own form controls — dropdown lists and text boxes.

Some templates are real Word forms: rows of questions answered with a dropdown
("Select / YES / NO / N/A") or a small text box, built with Word content
controls (``w:sdt``). They are not placeholders, so the placeholder renderer
never sees them. This module handles them:

1. **Lists** the controls of a template — question text, kind, options and the
   section heading above them — so the "Edit fields" window can show every one.
2. **Answers automatically** where the source supplies an answer: when a
   question matches a caption in the spreadsheet and the cell holds one of the
   dropdown's own options (or text, for a text box), that answer is used. A
   question with no clear answer is never guessed; it keeps its form value.
3. **Applies the user's choice.** The user always has the last word, and
   "leave it empty" is a valid answer too.

Format preservation: no element is ever added or removed. Only the text of an
existing ``w:t`` changes, and a dropdown can only receive one of its own options.
"""
from __future__ import annotations

import functools
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from docx import Document
from docx.oxml.ns import qn

from . import formatting, matching

LIST = "list"
TEXT = "text"

# "Leave this empty on purpose" — distinct from "automatic", which means the
# user has not chosen anything.
BLANK = "__BLANK__"
AUTOMATIC = "__AUTO__"

# A section heading: a row without controls that spans one cell, or text that
# starts with a numbering such as "4.11-".
_SECTION = re.compile(r"^\d+(\.\d+)*\s*[-.]")


@dataclass(frozen=True)
class Control:
    key: str         # stable identity (question text + position); choices are stored by it
    label: str       # the question as written in the document
    kind: str        # LIST | TEXT
    options: tuple[str, ...] = ()
    section: str = ""
    order: int = 0


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text).replace("ı", "i").replace("İ", "I"))
    plain = "".join(c for c in plain if not unicodedata.combining(c)).casefold()
    return re.sub(r"\s+", " ", plain).strip()


def _key(text: str, index: int, counter: dict[str, int]) -> str:
    """A stable identity from the question text.

    The same text gives the same key even if rows move or the template is
    edited, so the user's choices survive a new version of the form. Repeated
    texts (a "Brand" box in several sections) get an occurrence number.
    """
    digest = hashlib.sha1(_fold(text).encode("utf-8")).hexdigest()[:10]
    seen = counter.get(digest, 0)
    counter[digest] = seen + 1
    return f"{digest}-{index}-{seen}"


def _control_info(sdt) -> tuple[str, tuple[str, ...]]:
    properties = sdt.find(qn("w:sdtPr"))
    if properties is None:
        return TEXT, ()
    listing = properties.find(qn("w:dropDownList"))
    if listing is None:
        listing = properties.find(qn("w:comboBox"))
    if listing is None:
        return TEXT, ()
    options: list[str] = []
    for item in listing.iter(qn("w:listItem")):
        value = item.get(qn("w:displayText")) or item.get(qn("w:value"))
        if value and value not in options:
            options.append(value)
    return LIST, tuple(options)


def _text_without_controls(element) -> str:
    inside = set()
    for sdt in element.iter(qn("w:sdt")):
        content = sdt.find(qn("w:sdtContent"))
        if content is not None:
            inside.update(id(t) for t in content.iter(qn("w:t")))
    parts = [t.text or "" for t in element.iter(qn("w:t")) if id(t) not in inside]
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _is_heading(row, text: str) -> bool:
    if not text:
        return False
    return len(row.findall(qn("w:tc"))) == 1 or bool(_SECTION.match(text))


def _walk(document) -> Iterator[tuple[str, str, str, Any, str, tuple[str, ...]]]:
    """Every control of a document, in reading order.

    Yields (key, label, section, content element, kind, options). Discovery and
    application both go through this one walk, so a key computed while listing
    always finds the same control when the answer is written.
    """
    counter: dict[str, int] = {}
    section = ""
    body = document.element.body
    for block in body.iterchildren():
        if block.tag == qn("w:tbl"):
            for row in block.iter(qn("w:tr")):
                controls = [s for s in row.iter(qn("w:sdt")) if s.find(qn("w:sdtContent")) is not None]
                text = _text_without_controls(row)
                if not controls:
                    if _is_heading(row, text):
                        section = text
                    continue
                yield from _controls_of(controls, text or section, section, counter)
        elif block.tag in (qn("w:p"), qn("w:sdt")):
            controls = (
                [block] if block.tag == qn("w:sdt")
                else [s for s in block.iter(qn("w:sdt")) if s.find(qn("w:sdtContent")) is not None]
            )
            if not controls:
                continue
            text = _text_without_controls(block) if block.tag == qn("w:p") else ""
            yield from _controls_of(controls, text or section, section, counter)


def _controls_of(controls, label, section, counter):
    for index, sdt in enumerate(controls):
        content = sdt.find(qn("w:sdtContent"))
        if content is None:
            continue
        current = "".join(t.text or "" for t in content.iter(qn("w:t")))
        # A control holding a placeholder is filled by the renderer, not here.
        if "{{" in current or "{%" in current:
            continue
        kind, options = _control_info(sdt)
        label_text = label or "(untitled field)"
        yield _key(f"{section}|{label_text}", index, counter), label_text, section, content, kind, options


@functools.lru_cache(maxsize=128)
def _controls_cached(path_text: str, modified: float) -> tuple[Control, ...]:
    try:
        document = Document(path_text)
    except Exception:  # noqa: BLE001 - an unreadable template simply has no controls
        return ()
    return tuple(
        Control(key=key, label=label, kind=kind, options=options, section=section, order=order)
        for order, (key, label, section, _content, kind, options) in enumerate(_walk(document))
    )


def controls(template_path: str | Path) -> tuple[Control, ...]:
    path = Path(template_path)
    try:
        modified = path.stat().st_mtime
    except OSError:
        return ()
    return _controls_cached(str(path.resolve()), modified)


# ----------------------------------------------------------- automatic answers


def automatic_value(control: Control, project) -> Any:
    """The answer the source supplies for this question, or None.

    The question is compared with every caption read from the source files; the
    best match above the matching threshold is taken. For a dropdown its value
    must be one of the dropdown's own options, otherwise no answer is given.
    """
    best, best_score = None, 0.0
    for source in project.labels:
        score = matching.score(control.label, source.label)
        if score > best_score:
            best, best_score = source, score
    if best is None or best_score < matching.ACCEPT_THRESHOLD:
        return None
    if control.kind == TEXT:
        return formatting.for_document(best.value) or None
    wanted = _fold(formatting.for_document(best.value))
    for option in control.options:
        if _fold(option) == wanted:
            return option
    return None


def choices(project, template_name: str) -> dict[str, str]:
    return dict(project.form_choices.get(template_name, {}))


def set_choices(project, template_name: str, values: dict[str, str]) -> None:
    project.form_choices[template_name] = dict(values)


def effective_values(template_path: str | Path, template_name: str, project) -> dict[str, Any]:
    """What each control will receive: the user's choice, else the automatic one."""
    chosen = choices(project, template_name)
    result: dict[str, Any] = {}
    for control in controls(template_path):
        choice = chosen.get(control.key)
        if choice == BLANK:
            result[control.key] = ""
        elif choice not in (None, "", AUTOMATIC):
            result[control.key] = choice
        else:
            automatic = automatic_value(control, project)
            if automatic not in (None, ""):
                result[control.key] = automatic
    return result


def apply(document, template_path: str | Path, template_name: str, project) -> bool:
    """Write the answers into an open document; return whether anything changed."""
    values = effective_values(template_path, template_name, project)
    if not values:
        return False
    known = {c.key: c for c in controls(template_path)}
    changed = False
    for key, _label, _section, content, kind, options in _walk(document):
        if key not in values:
            continue
        text = "" if values[key] is None else str(values[key])
        control = known.get(key)
        if control is not None and kind == LIST and text and text not in options:
            continue
        if _write_text(content, text):
            changed = True
    return changed


def _write_text(content, value: str) -> bool:
    runs = list(content.iter(qn("w:t")))
    if not runs:
        return False
    if runs[0].text == value and all(not (t.text or "") for t in runs[1:]):
        return False
    runs[0].text = value
    for extra in runs[1:]:
        extra.text = ""
    return True


def summary(template_path: str | Path, template_name: str, project) -> tuple[int, int]:
    """(answered controls, total controls)."""
    total = len(controls(template_path))
    return len(effective_values(template_path, template_name, project)), total


def signature(template_path: str | Path, template_name: str, project) -> str:
    """A compact digest of the answers, so a changed answer marks the
    document's preview as out of date."""
    values = effective_values(template_path, template_name, project)
    return ";".join(f"{k}={values[k]}" for k in sorted(values))


def clear_cache() -> None:
    _controls_cached.cache_clear()
