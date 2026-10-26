# DocFiller

**Fill Word templates from any spreadsheet and export them as PDF — without
touching the template's layout.**

Give DocFiller a folder of `.docx` templates and the spreadsheet for a job. It
finds the placeholders in the templates, finds the matching values in the sheet
*by their captions*, shows you what it matched, lets you correct anything, and
writes finished Word and PDF documents.

![Windows](https://img.shields.io/badge/platform-Windows-0078D6)
![Python](https://img.shields.io/badge/python-3.12-3776AB)
![Qt](https://img.shields.io/badge/UI-PySide6-41CD52)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Why

A lot of office work is copying the same values out of a spreadsheet into the
same handful of documents, then printing each one to PDF. It is slow, and one
mistyped figure is easy to miss.

Automating it with fixed cell addresses breaks quietly: someone inserts a row
and `Sheet1!B4` now points at the wrong number. Nothing looks broken — the
document just contains the wrong value.

DocFiller reads a spreadsheet the way a person does: it looks for the caption
and takes the value next to it. Rows can move, sheets can be reordered, `.xls`
can become `.xlsx`, and the match still holds.

## Highlights

- **Caption-based reading.** Caption/value pairs in rows, header rows with values
  underneath, merged cells — `.xlsx`, `.xlsm`, `.xls` and `.csv`.
- **Automatic matching, manual control.** `{{ customer_name }}` is matched to
  "Customer Name" automatically. Any match can be pointed at another caption or
  overridden by typing, and the correction can be remembered for next time.
- **Layout is never changed.** Only placeholder text is replaced; styles,
  tables, headers, footers and form controls are kept exactly as they were.
- **Live PDF preview.** See every document before anything is saved. Change a
  field and only the affected documents are rebuilt; producing then reuses the
  preview instead of starting over.
- **Document sets.** Describe a kind of job once — its templates, required
  fields, standard values and keywords — and DocFiller suggests it when a
  matching spreadsheet is loaded. You always confirm.
- **Word form controls.** Dropdowns and text boxes inside forms are answered from
  the spreadsheet, using only the dropdown's own options.
- **Nothing is guessed.** A field with no value is left blank and reported. A
  wrong value in a delivered document costs far more than an empty one.
- **Fully offline.** No network access, no telemetry. Everything stays on the
  machine.

## Pages

| Page | What it is for |
|---|---|
| **Fill a sheet** | Open a spreadsheet, fill its empty fields in a form and save a copy. Excel writes only the changed cells, so formulas and formatting survive. Send it straight to *Documents*. |
| **Documents** | The main job: load any number of files, pick a document set, tick the documents, review each one's fields, preview and produce. |
| **Quick document** | One-off documents with or without a source file: tick templates, type values, produce. |
| **Library** | Profile values, saved records (e.g. a customer, applied to many fields at once), document sets, field memory. |
| **History** | Every job — when, from which files, which documents, where they went. Double-click to open the folder. |

And around them:

- **Accounts** — several people can share one computer, each with their own
  history, library and remembered matchings. Passwords are optional and stored
  only as salted hashes.
- **Appearance** — light and dark mode, four colour palettes.
- **Languages** — English and Turkish, switchable at any time without losing
  your work. A new language is one dictionary in `i18n.py`.
- **Drafts** — what you entered for a spreadsheet comes back when you reload the
  same file.
- **Field memory** — values you typed before are offered again in the same field.

## How to use it

1. **Write a template.** Any `.docx`; put a placeholder wherever a value belongs:

   ```
   Customer: {{ customer_name }}        Date: {{ issue_date }}
   ```

2. **Prepare the data.** Any spreadsheet with captions next to values:

   ```
   Customer Name | Northwind Trading Ltd.     ← caption and value side by side
   Order Number  | ORD-2026-0184

   Customer Name | Order Number | Delivery    ← or a header row
   Acme Ltd      | A-77         | Ex Works    ← with values underneath
   ```

3. **Run DocFiller**, choose the template folder, drop in the spreadsheet,
   check the fields, preview, and press **Produce Documents**.

Output layout:

```
<output folder>/
  order_confirmation.pdf
  order_data.pdf            ← the source sheet, if the document set asks for it
  Word/
    order_confirmation.docx ← editable copy
```

Want to try it straight away? Generate an invented example pair:

```bash
python examples/make_examples.py
```

and point the program at `examples/generated/`.

## Installation

### Run from source

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py
```

### Build a single executable

```bash
pyinstaller docfiller.spec --noconfirm
```

The result is `dist/DocFiller.exe`; the target machine needs no Python.

### Requirements

| Feature | Needs |
|---|---|
| Filling templates | Python 3.12+, any platform |
| PDF export and preview, *Fill a sheet* | Windows with Microsoft Word / Excel |

PDF conversion drives Office through COM, because that is the only way to
guarantee the PDF looks exactly like the document. Word and Excel are started
once, reused between jobs and closed when idle, so no background Office process
is left behind.

## Where data is kept

| What | Where |
|---|---|
| Accounts, appearance, error log | `%APPDATA%\DocFiller\` |
| History, library, document sets, matchings, drafts | `%APPDATA%\DocFiller\accounts\<account>\` |
| Produced documents | the output folder you choose |

Remembered matchings store captions and cell addresses, never cell contents.

## Tests

```bash
python -m unittest discover -s tests -v
```

The suite builds its own example files and redirects all data to a temporary
folder, so it needs no Office and never touches your real settings.

## Project layout

```
src/docfiller/
  workbook.py        read spreadsheets, recover caption/value pairs
  templates.py       find placeholders in each .docx
  matching.py        match placeholders to captions and score the match
  file_analysis.py   decide what each loaded file is
  project.py         one job's values: typed > source > profile > set default
  fields.py          each document's fields and which are empty
  form_controls.py   answer Word form controls from the source
  renderer.py        fill templates
  validation.py      check filled documents for leftovers
  engine.py          resolve, preview and produce a job
  export.py          PDF conversion through Office
  office.py          shared, reusable Word/Excel sessions
  sheet_fill.py      write values back into a spreadsheet
  document_sets.py   user-defined kinds of job
  accounts.py        offline accounts
  settings.py        appearance and per-account workspace
  profiles.py        remembered matchings per template set
  drafts.py          per-file memory of edits
  library.py         saved records
  memory.py          remembered field values
  history.py         job log
  diagnostics.py     error log and start-up checks
  i18n.py            interface languages
  ui/                sign-in window, main window and its five pages
tests/               unit and end-to-end tests
examples/            generator for an invented sample template and spreadsheet
```

## License

MIT — see [LICENSE](LICENSE).
