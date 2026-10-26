"""Per-document fields — which fields a document has and which are missing.

Each document's fields come from its own template, so the fields of one
document are never pooled with another's: the "Edit fields" window of each
document shows exactly what that document needs.

This module answers two questions:

1. "Which fields of this document are empty?" — for the badge next to each
   document and the completeness summary shown before production.
2. "Which empty fields are *required*?" — required fields are defined per
   document in the document set. A blank required field never stops
   production (a document can always be completed by hand later); it is
   flagged so the user decides knowingly.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import document_sets, templates
from .project import AUTOMATIC, EMPTY, Project


@dataclass
class Field:
    name: str
    label: str
    value: object
    filled: bool
    required: bool
    automatic: bool
    origin: str


def _required(project: Project, template_name: str) -> set[str]:
    document_set = document_sets.get(project.document_set)
    if document_set is None:
        return set()
    return set(document_set.required_fields.get(template_name, []))


def document_fields(template: templates.Template, project: Project) -> list[Field]:
    """Every field of one document with its current value. Empty and required
    fields come first, so what needs attention is at the top."""
    required = _required(project, template.name)
    result = []
    for name in template.placeholders:
        origin = project.origin(name)
        result.append(
            Field(
                name=name,
                label=templates.label(name),
                value=project.value(name),
                filled=project.is_filled(name),
                required=name in required,
                automatic=origin == AUTOMATIC,
                origin=origin,
            )
        )
    result.sort(key=lambda f: (f.filled, not f.required, f.label.casefold()))
    return result


def missing(template: templates.Template, project: Project) -> list[Field]:
    """Fields of this document that are empty (automatic ones never are)."""
    return [f for f in document_fields(template, project) if not f.filled and not f.automatic]


def summary(selected: list[templates.Template], project: Project) -> list[dict]:
    """Completeness of each selected document, shown before production."""
    result = []
    for template in selected:
        gaps = missing(template, project)
        result.append(
            {
                "name": template.name,
                "title": template.title,
                "missing": len(gaps),
                "required_missing": sum(1 for f in gaps if f.required),
            }
        )
    return result


def shared_placeholders(selected: list[templates.Template]) -> list[str]:
    """Placeholders that appear in more than one selected document.

    These are the details "common to all documents" — shown once on the main
    page instead of being typed into every document's window separately. With a
    single document selected, all of its placeholders count as common.
    """
    if len(selected) == 1:
        return list(selected[0].placeholders)
    counts: dict[str, int] = {}
    for template in selected:
        for name in template.placeholders:
            counts[name] = counts.get(name, 0) + 1
    return [name for name, count in counts.items() if count > 1]


__all__ = ["Field", "document_fields", "missing", "summary", "shared_placeholders", "EMPTY"]
