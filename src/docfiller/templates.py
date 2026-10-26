"""Word templates and the placeholders they expect.

A template is an ordinary ``.docx`` file whose variable parts are written as
placeholders::

    Customer: {{ customer_name }}        Date: {{ today }}

Which fields a document needs is read from the template itself
(``get_undeclared_template_variables``), never from a hand-kept list, so adding
a placeholder to a template needs no change anywhere else.

Nothing else about the file matters. Styles, tables, headers, footers and form
controls are left exactly as the author made them: only placeholder text is
replaced, so a generated document is indistinguishable from one typed by hand
into the same template.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path

from docxtpl import DocxTemplate

SUFFIXES = (".docx",)

# A placeholder split across several runs by Word's editing is invisible to the
# Jinja parser but still renders; this pattern recovers it from the plain text.
_PLACEHOLDER = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


@dataclass
class Template:
    path: Path
    placeholders: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def name(self) -> str:
        """Identifier used throughout the program: the file name."""
        return self.path.name

    @property
    def title(self) -> str:
        """What the user sees: the file name without its extension."""
        return self.path.stem

    @property
    def ok(self) -> bool:
        return not self.error


@functools.lru_cache(maxsize=256)
def _read_cached(path_text: str, modified: float, size: int) -> tuple[tuple[str, ...], str]:
    path = Path(path_text)
    try:
        document = DocxTemplate(str(path))
        names = set(document.get_undeclared_template_variables())
        try:
            docx = document.get_docx()
            texts = [p.text for p in docx.paragraphs]
            for table in docx.tables:
                for row in table.rows:
                    for cell in row.cells:
                        texts.extend(p.text for p in cell.paragraphs)
            for text in texts:
                names.update(_PLACEHOLDER.findall(text or ""))
        except Exception:  # noqa: BLE001, S110 - best-effort enrichment only
            pass
        return tuple(sorted(names)), ""
    except Exception as exc:  # noqa: BLE001 - a broken file is reported, not fatal
        return (), str(exc)


def read(path: str | Path) -> Template:
    """Inspect one template. Never raises for a file that cannot be parsed.

    Results are cached by path, modification time and size, so the same
    template is parsed once per change, however often it is asked about.
    """
    path = Path(path)
    try:
        stat = path.stat()
    except OSError as exc:
        return Template(path=path, error=str(exc))
    names, error = _read_cached(str(path.resolve()), stat.st_mtime, stat.st_size)
    return Template(path=path, placeholders=list(names), error=error)


def discover(folder: str | Path | None) -> list[Template]:
    """Every template in `folder`, sorted by name. Word lock files are skipped."""
    if folder is None:
        return []
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = [
        item for item in sorted(folder.iterdir(), key=lambda p: p.name.casefold())
        if item.suffix.lower() in SUFFIXES and not item.name.startswith("~$")
    ]
    return [read(item) for item in files]


def by_name(templates: list[Template]) -> dict[str, Template]:
    return {t.name: t for t in templates}


def all_placeholders(templates: list[Template]) -> list[str]:
    """Every distinct placeholder across `templates`, in stable order."""
    seen: dict[str, None] = {}
    for template in templates:
        for name in template.placeholders:
            seen.setdefault(name, None)
    return list(seen)


def label(placeholder: str) -> str:
    """A readable label for a placeholder: ``customer_name`` -> ``Customer name``."""
    text = placeholder.replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else placeholder


def clear_cache() -> None:
    _read_cached.cache_clear()
