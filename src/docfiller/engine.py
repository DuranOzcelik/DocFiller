"""The whole job, from loaded files to delivered PDFs.

This is the single entry point the interface calls, so every step can be
tested without a window.

Flow:
  read the files -> match placeholders -> fill templates -> validate ->
  convert to PDF -> PDFs in the output folder, editable .docx files in its
  "Word" subfolder.

A **preview** runs the same flow into a temporary folder. When the user then
confirms, nothing is produced again: the previewed files are copied into the
output folder. And when a preview is refreshed after one field changed, only
the documents whose data actually changed are converted again; the rest are
taken from the previous preview.
"""
from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import (
    document_sets,
    export,
    file_analysis,
    form_controls,
    matching,
    office,
    paths,
    profiles,
    renderer,
    templates,
    validation,
)
from .project import Project

EDITABLE_FOLDER = "Word"


class NoDataSource(Exception):
    """None of the loaded files could be read as a data source."""


@dataclass
class JobResult:
    project: Project | None = None
    pdfs: list[Path] = field(default_factory=list)
    editable: list[Path] = field(default_factory=list)      # filled .docx files
    copied_files: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    checks: list[validation.Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str | None = None
    cancelled: bool = False
    seconds: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.error is None and not self.cancelled and bool(self.pdfs or self.editable)

    @property
    def problems(self) -> list[validation.Check]:
        return [c for c in self.checks if not c.passed]


# =================================================================== reading


@dataclass
class Resolution:
    """The loaded files, analysed and turned into a project."""

    project: Project
    suggestion: str | None
    analyses: list[file_analysis.Analysis] = field(default_factory=list)

    @property
    def unreadable_numbers(self) -> list[tuple[str, str]]:
        return [u for a in self.analyses for u in a.unreadable_numbers]


def resolve(
    file_paths: list[str | Path],
    available_templates: list[templates.Template],
    profile_values: dict[str, str] | None = None,
) -> Resolution:
    """Analyse the loaded files, match every placeholder, suggest a document set.

    No fixed assumption is made about the files: how many there are, which can
    be read and which are only carried along is decided from their content.
    """
    if not file_paths:
        raise NoDataSource("No file was chosen.")
    analyses = file_analysis.analyse_all(file_paths)
    readable = [a for a in analyses if a.recognised]
    if not readable:
        problems = [f"'{a.name}': {a.summary()}" for a in analyses if a.role != file_analysis.COPY]
        raise NoDataSource(
            "No spreadsheet with readable values was found.\n\n" + "\n\n".join(problems)
        )

    labels = [lv for a in readable for lv in a.labels]
    placeholders = templates.all_placeholders(available_templates)
    matches = matching.auto_map(placeholders, labels)
    stored = profiles.load(profiles.template_key([t.path for t in available_templates]))
    if stored:
        matching.apply_saved(matches, stored, labels)

    project = Project(
        mapping={m.placeholder: m.source for m in matches if m.source is not None},
        typed={m.placeholder: m.literal for m in matches if m.literal is not None},
        profile=dict(profile_values or {}),
        source_files=[str(a.path.resolve()) for a in readable],
        attachments=[str(a.path.resolve()) for a in analyses if a.role == file_analysis.COPY],
        labels=labels,
    )
    suggestion = document_sets.suggest(
        project.source_text(), set(project.mapping), templates.by_name(available_templates)
    )
    # The user almost always previews or produces next: start Office now so the
    # first preview does not pay its start-up time.
    office.warm_up()
    return Resolution(project=project, suggestion=suggestion, analyses=analyses)


# ================================================================ production


def produce(
    project: Project,
    selected: list[templates.Template],
    output_folder: str | Path,
    make_pdf: bool = True,
    is_cancelled=None,
    reuse: "Preview | None" = None,
) -> JobResult:
    """Produce the documents and measure the total time taken."""
    started = time.perf_counter()
    result = _produce(project, selected, output_folder, make_pdf, is_cancelled, reuse)
    result.seconds = time.perf_counter() - started
    return result


def _cancelled(callback) -> bool:
    return bool(callback and callback())


def _produce(project, selected, output_folder, make_pdf, is_cancelled, reuse) -> JobResult:
    result = JobResult(project=project)
    output_folder = Path(output_folder).resolve()
    editable_folder = output_folder / EDITABLE_FOLDER

    if not selected:
        result.error = "No document was selected."
        return result

    # 1) Fill the templates. The open documents are kept so validation can scan
    #    them without reading the files back.
    open_documents: dict = {}
    try:
        written, skipped = renderer.fill_all(selected, project, editable_folder, open_documents)
    except Exception as exc:  # noqa: BLE001
        result.error = f"Filling the templates failed: {exc}"
        return result
    result.skipped.extend(skipped)
    result.editable.extend(written)

    if _cancelled(is_cancelled):
        result.cancelled = True
        return result

    # 2) Validate BEFORE converting. A document with a problem is still produced
    #    (so it can be fixed by hand) but it is not presented as a success.
    by_title = {t.title: t for t in selected}
    for path in written:
        template = by_title.get(path.stem)
        if template is not None:
            result.checks.append(
                validation.check(template, path, project, document=open_documents.get(str(path)))
            )
    open_documents.clear()
    for check in result.problems:
        result.warnings.append(f"'{Path(check.document).stem}' did not pass validation — {check.message()}")

    # 3) Copying needs no Office, so it happens before PDF conversion: even
    #    without Word these files reach the folder.
    _copy_attachments(project, output_folder, result)
    _copy_source_spreadsheets(project, output_folder, result)

    if not make_pdf:
        return result
    if _cancelled(is_cancelled):
        result.cancelled = True
        return result

    available, message = export.office_installed()
    if not available:
        result.warnings.append(
            f"PDFs could not be produced ({message}). The filled .docx files are ready "
            f"in the '{EDITABLE_FOLDER}' folder."
        )
        return result

    # 3a) Do not convert again what has not changed. Converting one document
    #     costs seconds; after one field changes, only that document's data is
    #     different, so the others' PDFs are taken from the previous preview.
    unchanged = reuse.unchanged_documents(project, selected) if reuse is not None else set()
    to_convert, ready = _split_reusable(written, reuse, output_folder, unchanged)
    result.pdfs.extend(ready)
    if ready:
        result.notes.append(
            f"{len(ready)} document(s) were unchanged and were not converted again "
            "(taken from the previous preview)."
        )

    # Word and Excel conversions run IN PARALLEL: they are separate Office
    # processes, and running them one after the other only adds up the time.
    source_job = _start_source_pdfs(project, output_folder, is_cancelled, reuse, result)

    try:
        pdfs = export.word_to_pdf(to_convert, output_folder, is_cancelled=is_cancelled)
    except export.PartialConversion as exc:
        pdfs = exc.produced
        for name, reason in exc.failures:
            result.warnings.append(f"'{name}' could not be converted to PDF: {reason}")
    except export.ConversionError as exc:
        result.warnings.append(f"PDF conversion failed: {exc}")
        pdfs = []
    result.pdfs.extend(pdfs)

    _collect_source_pdfs(source_job, result)

    if _cancelled(is_cancelled):
        result.cancelled = True
    return result


def _split_reusable(written, previous, output_folder, unchanged):
    """Split documents into "convert again" and "take from the previous preview".

    A document is reused only if its data is unchanged AND its previous PDF is
    still there. In any doubt it is converted again — losing a few seconds is
    better than delivering a stale document.
    """
    if previous is None:
        return list(written), []
    convert, ready = [], []
    for docx_path in written:
        old_pdf = previous.document_pdf(docx_path.stem) if docx_path.stem in unchanged else None
        if old_pdf is None or not old_pdf.exists():
            convert.append(docx_path)
            continue
        target = output_folder / f"{docx_path.stem}.pdf"
        try:
            output_folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_pdf, target)
            ready.append(target)
        except OSError:
            convert.append(docx_path)
    return convert, ready


# ------------------------------------------------------------- source files


def _source_spreadsheets(project: Project) -> list[Path]:
    return [Path(p) for p in project.source_files if Path(p).exists()]


def _start_source_pdfs(project, output_folder, is_cancelled, reuse, result):
    """Print the source spreadsheets to PDF in the background, alongside Word.

    A spreadsheet often already *is* one of the deliverables — a calculation or
    a schedule laid out in its print area. Letting Excel print it keeps its
    layout exactly and lets Excel compute its own formulas. A source file that
    has not changed since the previous preview is copied from it instead.
    """
    sources = _source_spreadsheets(project)
    if not sources or not document_sets.export_source_pdf(project.document_set):
        return None
    if reuse is not None:
        current = source_signatures(project)
        remaining = []
        for source in sources:
            old = reuse.source_pdf(source) if reuse.source_signatures.get(str(source)) == current.get(str(source)) else None
            if old is None:
                remaining.append(source)
                continue
            try:
                output_folder.mkdir(parents=True, exist_ok=True)
                target = output_folder / old.name
                shutil.copy2(old, target)
                result.pdfs.append(target)
            except OSError:
                remaining.append(source)
        sources = remaining
    if not sources:
        return None
    pool = ThreadPoolExecutor(max_workers=1)
    job = pool.submit(export.excel_to_pdf, sources, output_folder, is_cancelled)
    pool.shutdown(wait=False)
    return job


def _collect_source_pdfs(job, result: JobResult) -> None:
    if job is None:
        return
    try:
        pdfs = job.result()
    except export.PartialConversion as exc:
        pdfs = exc.produced
        for name, reason in exc.failures:
            result.warnings.append(f"'{name}' could not be converted to PDF: {reason}")
    except Exception as exc:  # noqa: BLE001 - becomes a warning, never stops the job
        result.warnings.append(f"The source spreadsheet could not be converted to PDF: {exc}")
        return
    result.pdfs.extend(pdfs)


def _copy_attachments(project: Project, output_folder: Path, result: JobResult) -> None:
    """Ready documents that were loaded are NOT copied unless asked for.

    A document loaded only so its details could be looked at already sits in
    the user's own folder; creating a second copy in the output would be noise.
    """
    if not project.copy_attachments:
        return
    for item in project.attachments:
        source = Path(item)
        if not source.exists():
            result.warnings.append(f"File to copy was not found: {source.name}")
            continue
        try:
            output_folder.mkdir(parents=True, exist_ok=True)
            target = output_folder / source.name
            shutil.copy2(source, target)
            result.copied_files.append(target)
        except OSError as exc:
            result.warnings.append(f"'{source.name}' could not be copied: {exc}")


def _copy_source_spreadsheets(project: Project, output_folder: Path, result: JobResult) -> None:
    """Deliver the source spreadsheet itself next to the PDFs, when asked for."""
    if not project.copy_source_spreadsheets:
        return
    for source in _source_spreadsheets(project):
        try:
            output_folder.mkdir(parents=True, exist_ok=True)
            target = output_folder / source.name
            if target.resolve() == source.resolve():
                continue
            shutil.copy2(source, target)
            result.copied_files.append(target)
        except OSError as exc:
            result.warnings.append(f"'{source.name}' could not be copied: {exc}")


# =================================================================== preview


@dataclass
class Preview:
    """Documents produced into a temporary folder, not yet delivered.

    Confirming a preview does NOT produce again — the files are copied into the
    output folder, which turns the confirmation step from seconds into an
    instant.
    """

    folder: Path
    result: JobResult
    signature: str
    document_signatures: dict[str, str] = field(default_factory=dict)
    source_signatures: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return self.folder.is_dir() and not self.result.cancelled

    def document_pdf(self, title: str) -> Path | None:
        candidate = self.folder / f"{title}.pdf"
        return candidate if candidate.exists() else None

    def source_pdf(self, source: Path) -> Path | None:
        candidate = self.folder / f"{Path(source).stem}.pdf"
        return candidate if candidate.exists() else None

    def unchanged_documents(self, project: Project, selected: list[templates.Template]) -> set[str]:
        """Titles of documents whose data has not changed since this preview."""
        current = document_signatures(project, selected)
        return {title for title, digest in current.items() if self.document_signatures.get(title) == digest}

    def is_stale(self, project: Project, selected: list[templates.Template]) -> bool:
        """True when data or the selection changed after the preview was made.

        A stale preview is never delivered as it is — the user must not receive
        something different from what they saw.
        """
        return self.signature != overall_signature(project, selected)

    def discard(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)


def document_signatures(project: Project, selected: list[templates.Template]) -> dict[str, str]:
    """A fingerprint per document, built ONLY from that document's own data.

    Changing a field of one document leaves the others' fingerprints alone, so
    only that document is converted again.
    """
    result = {}
    for template in selected:
        parts = [f"{name}={project.text(name)}" for name in sorted(template.placeholders)]
        parts.append("CONTROLS=" + form_controls.signature(template.path, template.name, project))
        try:
            parts.append(f"FILE={template.path.stat().st_mtime_ns}")
        except OSError:
            pass
        result[template.title] = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return result


def source_signatures(project: Project) -> dict[str, str]:
    """A fingerprint per source file (modification time and size)."""
    result = {}
    for source in _source_spreadsheets(project):
        try:
            stat = source.stat()
            result[str(source)] = f"{stat.st_mtime_ns}:{stat.st_size}"
        except OSError:
            result[str(source)] = "unreadable"
    return result


def overall_signature(project: Project, selected: list[templates.Template]) -> str:
    parts = [f"{k}={v}" for k, v in sorted(document_signatures(project, selected).items())]
    parts.append("SELECTED=" + ",".join(sorted(t.name for t in selected)))
    parts.append("ATTACHMENTS=" + ",".join(sorted(project.attachments)))
    parts.append(f"COPY_ATTACHMENTS={project.copy_attachments}")
    parts.append(f"COPY_SOURCES={project.copy_source_spreadsheets}")
    parts.append(f"SET={project.document_set}")
    parts.append("SOURCES=" + ",".join(f"{k}:{v}" for k, v in sorted(source_signatures(project).items())))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def build_preview(
    project: Project,
    selected: list[templates.Template],
    is_cancelled=None,
    previous: Preview | None = None,
) -> Preview:
    """Produce into a temporary folder (the output folder is not touched).

    The layout is exactly that of a real run, so a confirmed preview is copied
    across as it is.
    """
    folder = Path(tempfile.mkdtemp(prefix="preview-", dir=paths.preview_root()))
    result = produce(
        project,
        selected,
        folder,
        make_pdf=True,
        is_cancelled=is_cancelled,
        reuse=previous if (previous and previous.valid) else None,
    )
    return Preview(
        folder=folder,
        result=result,
        signature=overall_signature(project, selected),
        document_signatures=document_signatures(project, selected),
        source_signatures=source_signatures(project),
    )


def place_preview(preview: Preview, output_folder: str | Path) -> JobResult:
    """Deliver a confirmed preview WITHOUT producing again."""
    started = time.perf_counter()
    output_folder = Path(output_folder).resolve()
    output_folder.mkdir(parents=True, exist_ok=True)
    shutil.copytree(preview.folder, output_folder, dirs_exist_ok=True)

    old = preview.result
    new = JobResult(
        project=old.project,
        skipped=list(old.skipped),
        checks=list(old.checks),
        warnings=list(old.warnings),
        notes=list(old.notes),
        error=old.error,
    )
    new.pdfs = [_relocate(p, preview.folder, output_folder) for p in old.pdfs]
    new.editable = [_relocate(p, preview.folder, output_folder) for p in old.editable]
    new.copied_files = [_relocate(p, preview.folder, output_folder) for p in old.copied_files]
    new.seconds = time.perf_counter() - started
    return new


def _relocate(path: Path, old_root: Path, new_root: Path) -> Path:
    try:
        return new_root / Path(path).relative_to(old_root)
    except ValueError:
        return Path(path)


SOURCE_VIEW_FOLDER = "source-view"


def source_to_pdf(path: str | Path) -> Path:
    """Convert a loaded file to PDF so it can be looked at exactly as it is.

    The spreadsheet or document is printed by its own application, so what the
    user sees is what the file really looks like. PDFs are returned unchanged.
    The result is cached by path, modification time and size: opening the same
    file again does not start Office at all.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix.lower() == ".pdf":
        return path
    stat = path.stat()
    digest = hashlib.sha1(f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}".encode()).hexdigest()[:16]
    root = paths.preview_root() / SOURCE_VIEW_FOLDER
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{digest}.pdf"
    if target.exists():
        return target
    working = root / digest
    working.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix in (".xls", ".xlsx", ".xlsm", ".csv"):
        produced = export.excel_to_pdf([path], working)
    elif suffix in (".doc", ".docx", ".docm"):
        produced = export.word_to_pdf([path], working)
    else:
        raise ValueError(f"'{suffix}' files cannot be previewed.")
    if not produced:
        raise RuntimeError("The file could not be converted to PDF.")
    shutil.move(str(produced[0]), str(target))
    shutil.rmtree(working, ignore_errors=True)
    return target


def discard_old_previews() -> None:
    """Remove previews left behind by an earlier session that ended abruptly."""
    shutil.rmtree(paths.preview_root(), ignore_errors=True)
