# PDF Editor

A local web app for editing and creating PDFs. A Python FastAPI server stores files and does the PDF work. A plain-JavaScript browser UI displays pages and sends edits.

## Commands

- Install dependencies: `uv sync`
- Run the app: `uv run pdfe` (serves http://127.0.0.1:8000)
- Run tests: `uv run pytest -v`. The browser test runs when a Chromium is available: set `PDFE_CHROME` to its path, otherwise it is skipped.
- Lint: `uv run ruff check .`

## Constraints

- An original upload is never modified. Every save creates a new revision, and no revision is overwritten.
- The server binds to `127.0.0.1` by default.
- Text editing leaves text outside the edited block unchanged.
- PDF editing uses PyMuPDF (`fitz`). Page reorder, delete, rotate, and merge use pypdf.
- Uploaded files and the SQLite database live under `data/`, which is git-ignored.
- WordPerfect pictures need ImageMagick installed on the system (Wand loads its library). Without it, those uploads are refused with a message; the other formats do not need it.

## Where things live

- Design spec: `docs/superpowers/specs/2026-10-20-pdf-editor-design.md`
- Implementation plan: `docs/superpowers/plans/2026-10-20-pdf-editor.md`. Follow the plan's task order and interfaces.

## Working rules

- Write the failing test before the code, as each plan task describes.
- Commit at the end of each task, using the commit message from the plan. Commits in the plan are approved; other commits need a request.
- Keep the spec and the plan current if a decision changes.

## API rules for writes

- Every write needs `X-Pdfe: 1`. Requests from other sites, or with a Host other than localhost, are refused.
- Every edit needs `X-Base-Revision` set to the revision the edit was made from. A stale value gets 409, and a missing one gets 428.
- Coordinates in the API are displayed coordinates (the page as it is shown, after rotation). Internally PyMuPDF uses the unrotated frame; convert with `pdfe/coords.py`.
- Revisions are stored once per distinct content under `data/blobs/`, gzip-compressed. Older layouts are migrated on start.

