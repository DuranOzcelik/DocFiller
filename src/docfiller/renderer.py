"""Filling templates.

Only placeholder text is replaced, and form controls receive their answers in
the same open document. Styles, tables, headers, footers, images and controls
are carried over untouched, so the output is structurally identical to the
template it came from.
"""
from __future__ import annotations

from pathlib import Path

from docxtpl import DocxTemplate

from . import form_controls
from .templates import Template


def fill(
    template: Template,
    project,
    output_folder: str | Path,
    documents: dict | None = None,
) -> Path:
    """Fill one template, write it as .docx and return the path written.

    `documents`, when given, receives the still-open document keyed by its
    path, so validation can scan it without reading the file back.
    """
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    document = DocxTemplate(str(template.path))
    context = project.context(list(template.placeholders))
    # Anything the template asks for that the context lacks becomes an empty
    # string: a missing value never stops production.
    for name in document.get_undeclared_template_variables():
        context.setdefault(name, "")
    document.render(context)

    # Form controls are filled in the SAME open document: only existing text
    # changes, and saving then re-opening would cost time for nothing.
    form_controls.apply(document.docx, template.path, template.name, project)

    target = output_folder / f"{template.title}.docx"
    document.save(str(target))
    if documents is not None:
        documents[str(target)] = document.docx
    return target


def fill_all(
    selected: list[Template], project, output_folder: str | Path, documents: dict | None = None
) -> tuple[list[Path], list[tuple[str, str]]]:
    """Fill every selected template. Returns (files written, [(template, reason)])."""
    written: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for template in selected:
        if not template.ok:
            skipped.append((template.name, f"the template cannot be read: {template.error}"))
            continue
        try:
            written.append(fill(template, project, output_folder, documents))
        except Exception as exc:  # noqa: BLE001 - one bad template must not stop the rest
            skipped.append((template.name, f"error: {exc}"))
    return written, skipped
