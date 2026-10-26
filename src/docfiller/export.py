"""Convert filled Word and Excel files to PDF through Office automation.

Office is used rather than a pure-Python renderer because the point of the
program is that the delivered PDF looks exactly like the template: tables, form
controls, headers and page breaks all survive untouched.

Hard-won details encoded here:

* Macro-enabled and form-protected documents can open an **invisible** modal
  dialog that blocks automation forever. Macros are force-disabled and alerts
  suppressed so this cannot happen.
* COM needs absolute paths. A relative path produces a misleading "directory is
  not valid" error because Office has a different working directory.
* One unreadable file must not discard a whole batch, so failures are collected
  per file and reported alongside the documents that did convert.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from . import office

WD_EXPORT_FORMAT_PDF = 17
XL_TYPE_PDF = 0

# Print the whole used range of a worksheet instead of its saved print area.
# Spreadsheets routinely carry a print area covering only part of the sheet, and
# exporting that silently drops the rest of the data from the PDF.
PRINT_ENTIRE_SHEET = True


class ConversionError(Exception):
    """No file could be converted."""


class PartialConversion(Exception):
    """Some files converted and others did not.

    ``produced`` holds the PDFs that were written, ``failures`` the
    ``(file name, reason)`` pairs for the rest, so the caller can deliver what
    worked and report precisely what did not.
    """

    def __init__(self, produced: list[Path], failures: list[tuple[str, str]]) -> None:
        super().__init__(describe_failures(failures))
        self.produced = produced
        self.failures = failures


def describe_failures(failures: Iterable[tuple[str, str]]) -> str:
    return "; ".join(f"{name}: {reason}" for name, reason in failures)


def _cancelled(callback: Callable[[], bool] | None) -> bool:
    return bool(callback and callback())


def _prepare_output(folder: str | Path) -> Path:
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _finish(produced: list[Path], failures: list[tuple[str, str]]) -> list[Path]:
    if failures and not produced:
        raise ConversionError(describe_failures(failures))
    if failures:
        raise PartialConversion(produced, failures)
    return produced


def word_to_pdf(
    files: list[Path], output_folder: str | Path, is_cancelled: Callable[[], bool] | None = None
) -> list[Path]:
    """Convert Word files to PDF and return the paths that were written.

    ``is_cancelled`` is consulted before each document. A conversion already in
    progress cannot be interrupted — it happens inside a single COM call — so
    cancelling takes effect at the next document.
    """
    if not files:
        return []
    if not office.com_available():
        raise ConversionError(
            "pywin32 is not installed. Run 'pip install pywin32' to enable PDF export."
        )

    output_folder = _prepare_output(output_folder)
    produced: list[Path] = []
    failures: list[tuple[str, str]] = []

    def body(word):
        for item in files:
            if _cancelled(is_cancelled):
                break
            source = Path(item).resolve()
            target = output_folder / (source.stem + ".pdf")
            document = None
            try:
                document = word.Documents.Open(
                    str(source),
                    ConfirmConversions=False,
                    ReadOnly=True,
                    AddToRecentFiles=False,
                    # A password-protected file would otherwise raise a dialog
                    # that blocks automation. Supplying empty passwords turns it
                    # into an ordinary, reportable error instead.
                    # (Word's Open has no 'Notify' parameter; passing one makes
                    # the whole call fail.)
                    PasswordDocument="",
                    WritePasswordDocument="",
                    # Read what is on disk even if a copy is open in the UI.
                    Revert=True,
                    Visible=False,
                )
                # ExportAsFixedFormat rather than SaveAs: SaveAs fails with
                # "command failed" on read-only documents.
                document.ExportAsFixedFormat(
                    OutputFileName=str(target), ExportFormat=WD_EXPORT_FORMAT_PDF
                )
                produced.append(target)
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
                failures.append((source.name, str(exc)))
            finally:
                if document is not None:
                    try:
                        document.Close(0)
                    except Exception:  # noqa: BLE001, S110
                        pass

    try:
        office.WORD.run(body)
    except office.OfficeUnavailable as exc:
        raise ConversionError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"Word conversion failed: {exc}") from exc

    return _finish(produced, failures)


def excel_to_pdf(
    files: list[Path], output_folder: str | Path, is_cancelled: Callable[[], bool] | None = None
) -> list[Path]:
    """Convert spreadsheets to PDF, letting Excel evaluate formulas itself."""
    if not files:
        return []
    if not office.com_available():
        raise ConversionError("pywin32 is not installed.")

    output_folder = _prepare_output(output_folder)
    produced: list[Path] = []
    failures: list[tuple[str, str]] = []

    def body(excel):
        for item in files:
            if _cancelled(is_cancelled):
                break
            source = Path(item).resolve()
            target = output_folder / (source.stem + ".pdf")
            workbook = None
            try:
                workbook = excel.Workbooks.Open(
                    str(source),
                    ReadOnly=True,
                    # Do not follow external links: the file may reference other
                    # workbooks or network locations, which is slow and unsafe.
                    UpdateLinks=0,
                    IgnoreReadOnlyRecommended=True,
                    Notify=False,
                    Password="",
                    WriteResPassword="",
                )
                if PRINT_ENTIRE_SHEET:
                    _print_whole_sheets(workbook)
                workbook.ExportAsFixedFormat(XL_TYPE_PDF, str(target))
                produced.append(target)
            except Exception as exc:  # noqa: BLE001
                failures.append((source.name, str(exc)))
            finally:
                if workbook is not None:
                    try:
                        workbook.Close(False)
                    except Exception:  # noqa: BLE001, S110
                        pass

    try:
        office.EXCEL.run(body)
    except office.OfficeUnavailable as exc:
        raise ConversionError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"Excel conversion failed: {exc}") from exc

    return _finish(produced, failures)


def _print_whole_sheets(workbook) -> None:
    """Clear each sheet's print area so the full used range reaches the PDF.

    Width is fitted to one page so wide tables are not cut off; height is left
    free. The workbook is open read-only, so nothing is written back to disk.
    """
    for sheet in workbook.Worksheets:
        try:
            sheet.PageSetup.PrintArea = ""
            sheet.PageSetup.Zoom = False
            sheet.PageSetup.FitToPagesWide = 1
            sheet.PageSetup.FitToPagesTall = False
        except Exception:  # noqa: BLE001, S110 - one stubborn sheet must not stop the rest
            pass


def office_installed() -> tuple[bool, str]:
    """Report whether Word is available, without paying to start it.

    Reading the registry is instantaneous; actually launching Word to find out
    costs several seconds and would be immediately repeated by the first export.
    """
    if not office.com_available():
        return False, "pywin32 is not installed"
    if __import__("os").name != "nt":
        return False, "Microsoft Office automation requires Windows"
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CurVer") as key:
            version = winreg.QueryValueEx(key, "")[0]
        return True, f"Microsoft Word ({version})"
    except OSError:
        return False, "Microsoft Word is not registered on this computer"
