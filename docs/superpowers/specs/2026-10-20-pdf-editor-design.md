# PDF Editor: Design

Status: draft, awaiting approval. Nothing is built yet.

## Intent and why

A personal web app for editing PDFs made from typed text. The owner has older PDFs that need changes: embedded images moved, line breaks fixed, pages reordered. The owner also wants to create new PDFs with the same tools. The app runs on a server the owner controls. The server stores files and does the PDF work. The browser displays pages and sends edits.

## Goals

- Open an existing PDF and reorder, delete, and rotate pages.
- Select, move, resize, replace, and delete embedded images.
- Select a block of text, edit it, and rewrap it to fix line breaks.
- Create a new PDF from blank pages, with text blocks and images.
- Keep every upload and every saved revision on the server, so any change can be undone.
- Run locally with one command.

## Non-goals (v1)

- OCR or editing of scanned PDFs.
- Forms, annotations, digital signatures, or encryption.
- Multiple users, accounts, login, or sharing.
- Real-time collaboration.
- Mobile layout.

## Anti-goals (a failure even if the code works)

- Losing or overwriting an original upload.
- Silently dropping text or images during an edit.
- An edit to one block changing the position of unrelated content on the page.

## Constraints

- Python 3.12 or later.
- PyMuPDF is the main PDF library. The owner knows its AGPL license and accepts it for now, since the app is not being distributed.
- The owner knows Python well and Go less well. Python is the implementation language.
- Input files contain real text. Scanned-document support is out of scope.

## Decisions

Decisions the owner made:

- Python, not Go.
- PyMuPDF for PDF work.
- The server stores files and does the processing.
- No open-source licensing requirement for now.

Decisions I made (my calls, which the owner can change):

- **Server:** FastAPI with Uvicorn.
- **Database:** SQLAlchemy with SQLite, for file records, page order, and revision history.
- **PDF libraries:** PyMuPDF for reading text and images, rendering previews, and writing content. pypdf for page reordering, splitting, and merging. Pillow for image uploads.
- **Browser:** plain JavaScript with pdf.js for rendering. Drag and drop for thumbnails and images.
- **Tooling:** pytest, httpx for API tests, ruff for lint and format, uv for dependencies in `pyproject.toml`.
- **Bind address:** `127.0.0.1` by default, so the server is not exposed to the network.
- **Storage:** files on local disk under a data directory, named by UUID. Originals are never modified. Each save creates a new revision.
- **Text editing method:** find the existing text block, cover it with a white rectangle, and write the replacement text with `insert_textbox` at the same position. Line-break fixes rewrap the block to a set width.
- **Fonts:** use the font named in the original PDF when PyMuPDF can load it. Otherwise fall back to a bundled base font, and show the owner which fallback was used.
- **Pictures:** PNG, GIF, and JPEG are embedded as they are. WordPerfect graphics are converted to PNG with Wand, which needs ImageMagick installed on the machine.
- **Text growth:** a rewritten block extends downward into free space, up to the next block below it or the bottom margin. Text that still does not fit is refused.
- **New text:** text may not overlap or come within 4 pt of existing text, so it is never read back as part of that block.
- **Undo and history:** every save is a revision. Undo and Restore create a new revision with an older revision's bytes, so no history is lost.

## Parts

1. **Storage and revisions:** upload, store, list, and download files, with revision history.
2. **Page operations:** reorder, delete, rotate, split, merge. Built on pypdf.
3. **Image operations:** list, move, resize, replace, delete. Built on PyMuPDF.
4. **Text operations:** list text blocks with positions, edit a block, rewrap a block. Built on PyMuPDF.
5. **New documents:** create a blank PDF, add pages, text blocks, and images.
6. **Browser UI:** page strip, page canvas, tool panel (layout option B from the mockup).

Text operations (part 4) come last, because they are the hardest part.

## Left to the builder

- Exact API routes and data formats.
- How to detect image and text block boundaries in the original PDF.
- How to fall back when a font cannot be loaded.
- Test PDFs: the builder should create small sample files with typed text and images.

## Acceptance

- Each part works on a sample PDF, with tests that check the output with PyMuPDF.
- An original upload is byte-identical after any sequence of edits.
- A text edit leaves text outside the edited block unchanged, verified by text extraction before and after.

## Security and consistency (added after review)

- The server answers only for localhost, refuses requests from other origins, and requires `X-Pdfe: 1` on writes.
- Every edit names the revision it was made from (`X-Base-Revision`). A stale edit is refused with 409, so two windows cannot overwrite each other.
- Uploads are limited to 100 MB, and pictures to 20 MB.

## Coordinates and images (added after review)

- The API uses displayed coordinates. PyMuPDF's unrotated frame is converted at the boundary.
- Moving, resizing, and deleting an image edit only that image's drawing command, so other content and the stacking order are unchanged. A replaced picture is drawn on top of the page.
- Text is drawn with the page's rotation, so it reads upright on screen.

