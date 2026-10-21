# PDF Editor

A web app for editing PDFs that were made from typed text, and for creating new ones.
It runs on your own computer: a Python server stores your files and does the PDF work,
and the editor runs in your browser.

## What it does

- Open a PDF, or start a new one.
- Reorder, delete, rotate, and add pages. Drag thumbnails to reorder.
- Edit a text block. Text that is too long grows downward into free space; text that
  still does not fit is refused with a message.
- Move, resize, replace, and delete images. The stacking order and the other content
  on the page are kept.
- Add text boxes and pictures (PNG, GIF, JPEG, and WordPerfect graphics).
- Undo, and browse the full history. Going back creates a new revision, so nothing is lost.
- Download the current revision under the file's own name.

Every save is a numbered revision. The original upload is never changed.

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) to install dependencies and run the app
- ImageMagick, only if you want to add WordPerfect graphics. Without it, those uploads
  are refused with a message; everything else works.

## Run it

```sh
uv sync
uv run pdfe
```

Then open <http://127.0.0.1:8000/>. The server only answers on this computer.

Files and history are kept in `data/`, which is git-ignored.

## Test it

```sh
uv run pytest -v
```

The browser test runs against a real server when a Chromium is available. Point
`PDFE_CHROME` at one to run it:

```sh
PDFE_CHROME=/path/to/chrome uv run pytest -v
```

Without it, that test is skipped.

Lint:

```sh
uv run ruff check .
```

## Limits

- Uploads are limited to 100 MB; pictures to 20 MB.
- Every revision is kept, so disk use grows with each edit. There is no pruning yet.
- Each edit rewrites the whole file, so very large documents will be slow.
- Only standard fonts are reused when editing text; other fonts are replaced, and the
  editor tells you when that happens.

## Project layout

- `src/pdfe/api.py`: the HTTP API (FastAPI)
- `src/pdfe/storage.py`: revisions, and the shared store they are kept in
- `src/pdfe/pages.py`, `images.py`, `text.py`, `create.py`: the PDF operations
- `src/pdfe/placements.py`: edits to where an image is drawn, in the page's content
- `src/pdfe/coords.py`: converts between displayed and PDF page coordinates
- `src/pdfe/web/`: the browser editor (plain JavaScript, with pdf.js vendored in `vendor/`)
- `tests/`: the test suite
- `docs/superpowers/`: the design spec and the implementation plan
- `CLAUDE.md`: working notes for contributors and for Claude Code

## API

The editor uses the API below. Writes need two headers:

- `X-Pdfe: 1`, which marks the request as coming from the editor.
- `X-Base-Revision: <n>`, the revision the edit was made from. A stale value gets
  `409 Conflict`, and a missing one gets `428`.

Positions are in the page as it is displayed, after rotation.

## License

No license has been chosen yet.
