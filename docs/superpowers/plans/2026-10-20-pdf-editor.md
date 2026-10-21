# PDF Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web app, with a Python server, that stores PDFs and edits them: page reorder/delete/rotate, image move/resize/replace/delete, text block edit and rewrap, and new-document creation.

**Architecture:** FastAPI server exposes JSON endpoints. Each PDF operation is a pure function that takes PDF bytes and returns new PDF bytes, so the storage layer keeps every original and revision on disk and the operations stay easy to test. A plain-JavaScript browser UI renders pages with pdf.js and calls the API.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, SQLAlchemy with SQLite, PyMuPDF (`fitz`), pypdf, Pillow, pytest, httpx, ruff, uv, pdf.js (browser).

**Spec:** `docs/superpowers/specs/2026-10-20-pdf-editor-design.md`

## Global Constraints

- Python 3.12 or later.
- PDF library for editing and reading: PyMuPDF. Page reorder, delete, rotate, and merge: pypdf.
- Server binds to `127.0.0.1` by default.
- An original upload is never modified; its bytes are identical after any sequence of edits.
- Each save creates a new revision; no revision is ever overwritten.
- Text editing leaves text outside the edited block unchanged.
- Files are stored under the `data/` directory, named by UUID.

## Review Focus

1. **Corrupt or encrypted upload** → a clear 400 error, no crash, and no half-written file on disk.
2. **Text block overlapping an image** → replacing a block must not erase the image.
3. **Font with missing glyphs** (accents, non-Latin characters) → fallback still shows the characters, not empty boxes.
4. **Rotated page with a page-level rotation** → image and text positions are reported in the rotated page's coordinates, so moves land where the user clicked.
5. **Two edits to the same file at once** → the second save creates a new revision based on the latest revision, and neither edit is lost silently.

Each line above has its test in the owning task (Tasks 2, 3, 5, 6, 7 below).

---

## File Structure

- `pyproject.toml`: dependencies, the `pdfe` console entry point.
- `src/pdfe/__init__.py`: package marker.
- `src/pdfe/__main__.py`: `main()`, starts Uvicorn on `127.0.0.1:8000`.
- `src/pdfe/db.py`: SQLAlchemy models `FileRecord`, `Revision`; `make_engine(url)`.
- `src/pdfe/storage.py`: `Storage` class: saves originals and revisions to disk and to the database.
- `src/pdfe/pages.py`: page reorder, delete, rotate (pypdf).
- `src/pdfe/images.py`: image list, move, resize, delete, replace (PyMuPDF).
- `src/pdfe/fonts.py`: `resolve_font` with fallback reporting.
- `src/pdfe/text.py`: text block list, block replace and rewrap (PyMuPDF).
- `src/pdfe/create.py`: blank document, add text, add image (PyMuPDF).
- `src/pdfe/api.py`: `create_app(storage)`, all HTTP routes.
- `src/pdfe/web/index.html`, `src/pdfe/web/app.js`, `src/pdfe/web/app.css`: browser UI.
- `tests/conftest.py`: sample PDF fixtures.
- `tests/test_*.py`: one test file per module.

---

### Task 1: Project scaffold and run command

**Files:**
- Create: `pyproject.toml`, `src/pdfe/__init__.py`, `src/pdfe/__main__.py`, `tests/test_scaffold.py`
- Test: `tests/test_scaffold.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `pdfe.__main__.main() -> None` (runs Uvicorn with `host="127.0.0.1"`, `port=8000`, `app="pdfe.api:create_app"`, `factory=True`). Console script `pdfe = "pdfe.__main__:main"`.

- [ ] **Step 1: Write the failing test**

```python
def test_main_binds_to_localhost(monkeypatch):
    import pdfe.__main__ as entry
    calls = {}
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **kw: calls.update(kw))
    entry.main()
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pdfe'`

- [ ] **Step 3: Create the scaffold**

`pyproject.toml` lists the dependencies from the Tech Stack line, dev dependencies `pytest`, `httpx`, `ruff`, and the `pdfe` script entry point. `main()` calls `uvicorn.run("pdfe.api:create_app", factory=True, host="127.0.0.1", port=8000)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scaffold.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/pdfe tests/test_scaffold.py
git commit -m "feat: add project scaffold and localhost run command"
```

---

### Task 2: Storage, revisions, and the original-is-immutable rule

**Files:**
- Create: `src/pdfe/db.py`, `src/pdfe/storage.py`, `tests/conftest.py`, `tests/test_storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `make_engine(url: str) -> Engine`; models `FileRecord(id: str, name: str)`, `Revision(id: int, file_id: str, number: int)`.
  - `Storage(root: Path, engine: Engine)`.
  - `Storage.save_upload(data: bytes, name: str) -> str` returns the new file id. Raises `ValueError` if `data` is not a readable PDF.
  - `Storage.latest_bytes(file_id: str) -> bytes`.
  - `Storage.add_revision(file_id: str, data: bytes) -> int` returns the new revision number.
  - `Storage.original_bytes(file_id: str) -> bytes`.

- [ ] **Step 1: Write the failing tests**

```python
def test_original_unchanged_after_revision(storage, sample_pdf_bytes):
    fid = storage.save_upload(sample_pdf_bytes, "a.pdf")
    storage.add_revision(fid, b"%PDF-1.4 edited")  # bytes need not be valid here
    assert storage.original_bytes(fid) == sample_pdf_bytes

def test_latest_is_newest_revision(storage, sample_pdf_bytes):
    fid = storage.save_upload(sample_pdf_bytes, "a.pdf")
    storage.add_revision(fid, b"second")
    assert storage.latest_bytes(fid) == b"second"

def test_corrupt_upload_rejected_and_nothing_written(storage, tmp_path):
    import pytest
    with pytest.raises(ValueError):
        storage.save_upload(b"not a pdf", "bad.pdf")
    assert list((storage.root / "files").glob("*")) == []   # Review Focus 1

def test_encrypted_upload_rejected(storage, encrypted_pdf_bytes):
    import pytest
    with pytest.raises(ValueError):
        storage.save_upload(encrypted_pdf_bytes, "locked.pdf")   # Review Focus 1
```

`conftest.py` provides `sample_pdf_bytes` (a one-page PDF with typed text, built with PyMuPDF), `encrypted_pdf_bytes` (same, saved with a password), and `storage` (a `Storage` in `tmp_path`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_storage.py -v`
Expected: FAIL with `ImportError` for `pdfe.storage`

- [ ] **Step 3: Implement storage**

`save_upload` opens the bytes with `fitz.open(stream=data, filetype="pdf")`. If that raises, or `doc.needs_pass` is true, raise `ValueError`. Write to a temporary file in the same folder, then rename it to `files/<id>/original.pdf`, so a failed write leaves nothing. Insert the `FileRecord` row and a revision 1 row that points to the same bytes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pdfe/db.py src/pdfe/storage.py tests/conftest.py tests/test_storage.py
git commit -m "feat: add storage with immutable originals and revisions"
```

---

### Task 3: Concurrent saves never lose an edit

**Files:**
- Modify: `src/pdfe/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `Storage` from Task 2.
- Produces: `Storage.add_revision` now runs under a per-file lock and assigns `number = max(existing) + 1` inside the same transaction.

- [ ] **Step 1: Write the failing test**

```python
def test_two_saves_get_distinct_revisions(storage, sample_pdf_bytes):
    from concurrent.futures import ThreadPoolExecutor
    fid = storage.save_upload(sample_pdf_bytes, "a.pdf")
    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(lambda i: storage.add_revision(fid, f"r{i}".encode()), range(20)))
    assert sorted(numbers) == list(range(2, 22))   # revision 1 is the upload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_storage.py::test_two_saves_get_distinct_revisions -v`
Expected: FAIL with duplicate revision numbers or a SQLite error

- [ ] **Step 3: Implement the lock**

Add a `threading.Lock` per file id in `Storage`, held around reading the max number, inserting the row, and writing the revision file. Use one lock dictionary guarded by a global lock.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pdfe/storage.py tests/test_storage.py
git commit -m "fix: serialize revision writes per file"
```

---

### Task 4: HTTP API for files

**Files:**
- Create: `src/pdfe/api.py`, `tests/test_api_files.py`
- Test: `tests/test_api_files.py`

**Interfaces:**
- Consumes: `Storage` (Tasks 2–3).
- Produces: `create_app(storage: Storage | None = None) -> FastAPI`. Routes:
  - `POST /api/files` (multipart `file`) → `201 {"id", "name", "revision"}`; `400` on invalid PDF.
  - `GET /api/files/{id}` → `200 {"id", "name", "revision"}`; `404` if missing.
  - `GET /api/files/{id}/download` → latest revision bytes, `application/pdf`.
  - `GET /api/files/{id}/original` → original upload bytes, `application/pdf`, from `Storage.original_bytes`.
  - `POST /api/files/{id}/revisions` (raw PDF body) → `201 {"revision"}`. Used by every later task.

- [ ] **Step 1: Write the failing tests**

```python
def test_upload_then_download_roundtrip(client, sample_pdf_bytes):
    r = client.post("/api/files", files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")})
    assert r.status_code == 201
    fid = r.json()["id"]
    assert client.get(f"/api/files/{fid}/download").content == sample_pdf_bytes

def test_upload_corrupt_returns_400(client):
    r = client.post("/api/files", files={"file": ("bad.pdf", b"nope", "application/pdf")})
    assert r.status_code == 400
```

`client` is `httpx.Client(transport=..)` over `create_app(storage)` with a `tmp_path` storage.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_files.py -v`
Expected: FAIL with `ImportError` for `pdfe.api`

- [ ] **Step 3: Implement the routes**

Each route calls `Storage` and maps `ValueError` to `400` and a missing id to `404`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_files.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pdfe/api.py tests/test_api_files.py
git commit -m "feat: add file upload, download, and revision API"
```

---

### Task 5: Page operations

**Files:**
- Create: `src/pdfe/pages.py`, `tests/test_pages.py`
- Modify: `src/pdfe/api.py`
- Test: `tests/test_pages.py`

**Interfaces:**
- Consumes: `Storage.latest_bytes`, `Storage.add_revision` (Task 2).
- Produces (all pure, bytes in, bytes out):
  - `reorder(data: bytes, order: list[int]) -> bytes`: `order` is a permutation of `range(page_count)`.
  - `delete_pages(data: bytes, indexes: list[int]) -> bytes`.
  - `rotate_page(data: bytes, index: int, degrees: int) -> bytes`: `degrees` is 90, 180, or 270.
  - API: `POST /api/files/{id}/pages/reorder` (`{"order": [...]}`), `.../pages/delete` (`{"indexes": [...]}`), `.../pages/rotate` (`{"index", "degrees"}`). Each creates a revision and returns `{"revision"}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_reorder_moves_pages(three_page_pdf):
    out = reorder(three_page_pdf, [2, 0, 1])
    assert page_texts(out) == ["page 3", "page 1", "page 2"]

def test_delete_pages(three_page_pdf):
    assert page_texts(delete_pages(three_page_pdf, [1])) == ["page 1", "page 3"]

def test_rotate_sets_rotation(three_page_pdf):
    out = rotate_page(three_page_pdf, 0, 90)
    assert fitz.open(stream=out, filetype="pdf")[0].rotation == 90

def test_reorder_rejects_non_permutation(three_page_pdf):
    import pytest
    with pytest.raises(ValueError):
        reorder(three_page_pdf, [0, 0, 1])
```

`page_texts` is a helper in `tests/conftest.py` that returns each page's text stripped.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pages.py -v`
Expected: FAIL with `ImportError` for `pdfe.pages`

- [ ] **Step 3: Implement with pypdf**

Use `PdfReader` and `PdfWriter`. For reorder, add pages in the new order. For rotate, call `page.rotate(degrees)`. Reject bad input before writing: `ValueError` for a non-permutation, a bad index, or a degree not in (90, 180, 270).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pages.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pdfe/pages.py src/pdfe/api.py tests/test_pages.py
git commit -m "feat: add page reorder, delete, and rotate"
```

---

### Task 6: Image operations

**Files:**
- Create: `src/pdfe/images.py`, `tests/test_images.py`
- Modify: `src/pdfe/api.py`
- Test: `tests/test_images.py`

**Interfaces:**
- Consumes: `Storage` (Task 2), API pattern from Task 4.
- Produces (pure):
  - `ImageInfo(xref: int, bbox: tuple[float, float, float, float])`, a dataclass.
  - `list_images(data: bytes, page: int) -> list[ImageInfo]`, bbox in the page's displayed coordinates (after rotation).
  - `move_image(data, page, xref, dx, dy) -> bytes`.
  - `resize_image(data, page, xref, width, height) -> bytes`.
  - `delete_image(data, page, xref) -> bytes`.
  - `replace_image(data, page, xref, png: bytes) -> bytes`.
  - API: `GET /api/files/{id}/pages/{n}/images` and `POST /api/files/{id}/pages/{n}/images/{xref}` with `{"op": "move"|"resize"|"delete", ...}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_list_images_reports_bbox(pdf_with_image):
    imgs = list_images(pdf_with_image, 0)
    assert len(imgs) == 1 and imgs[0].bbox[2] > imgs[0].bbox[0]

def test_move_image_shifts_bbox(pdf_with_image):
    xref = list_images(pdf_with_image, 0)[0].xref
    before = list_images(pdf_with_image, 0)[0].bbox
    out = move_image(pdf_with_image, 0, xref, dx=50, dy=0)
    after = list_images(out, 0)[0].bbox
    assert abs((after[0] - before[0]) - 50) < 0.5

def test_rotated_page_bbox_matches_display(pdf_with_image_rotated_90):
    # Review Focus 4: the bbox is in displayed coordinates
    imgs = list_images(pdf_with_image_rotated_90, 0)
    w, h = page_size(pdf_with_image_rotated_90, 0)   # displayed width/height
    x0, y0, x1, y1 = imgs[0].bbox
    assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h

def test_delete_image_removes_it(pdf_with_image):
    xref = list_images(pdf_with_image, 0)[0].xref
    assert list_images(delete_image(pdf_with_image, 0, xref), 0) == []
```

`pdf_with_image` and `pdf_with_image_rotated_90` are fixtures in `conftest.py` that insert a PNG made with Pillow. `page_size` returns the displayed `(width, height)` from `page.rect`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_images.py -v`
Expected: FAIL with `ImportError` for `pdfe.images`

- [ ] **Step 3: Implement with PyMuPDF**

Use `page.get_image_info(xrefs=True)` for bboxes and `page.get_image_rects(xref)` for placement. Move and resize by replacing the image's placement rectangle with `page.insert_image(rect, xref=xref, overlay=True)`, after covering the old place with `add_redact_annot` and `apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)`. Delete uses the same cover step without re-inserting. Replace uses `insert_image` with the new PNG in the old rectangle.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_images.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pdfe/images.py src/pdfe/api.py tests/test_images.py
git commit -m "feat: add image list, move, resize, delete, and replace"
```

---

### Task 7: Font resolution with fallback reporting

**Files:**
- Create: `src/pdfe/fonts.py`, `tests/test_fonts.py`
- Test: `tests/test_fonts.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `resolve_font(doc: fitz.Document, page_index: int, font_name: str, text: str) -> FontChoice`.
  - `FontChoice(fontname: str, fallback: bool)`, a dataclass.
  - Fallback font is a PyMuPDF base-14 font that covers Latin letters with accents. Non-Latin text uses the bundled file `src/pdfe/fonts/NotoSans-Regular.ttf` via `fitz.Font(fontfile=...)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_embedded_font_used_when_available(pdf_with_embedded_font):
    choice = resolve_font(pdf_with_embedded_font, 0, "Helvetica", "Hello")
    assert choice.fallback is False

def test_missing_font_falls_back_and_says_so(pdf_with_embedded_font):
    choice = resolve_font(pdf_with_embedded_font, 0, "NoSuchFont", "Hello")
    assert choice.fallback is True

def test_fallback_covers_accents_and_non_latin(pdf_with_embedded_font):
    choice = resolve_font(pdf_with_embedded_font, 0, "NoSuchFont", "café Привет")
    font = fitz.Font(choice.fontname) if choice.fontname in fitz.Base14_fontnames else fitz.Font(fontfile=choice.fontname)
    assert all(font.has_glyph(ord(c)) for c in "café Привет" if not c.isspace())   # Review Focus 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_fonts.py -v`
Expected: FAIL with `ImportError` for `pdfe.fonts`

- [ ] **Step 3: Implement the resolver**

Look up the font name in `doc[page_index].get_fonts()`. If it is present and loads, return it with `fallback=False`. If the text contains characters outside Latin-1 or Latin Extended-A, return the bundled Noto font. Otherwise return `Helv` with `fallback=True`. Use the same `fallback` flag as the UI's warning.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_fonts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pdfe/fonts.py src/pdfe/fonts tests/test_fonts.py
git commit -m "feat: resolve fonts with fallback reporting"
```

---

### Task 8: Text block listing, replacement, and rewrap

**Files:**
- Create: `src/pdfe/text.py`, `tests/test_text.py`
- Modify: `src/pdfe/api.py`
- Test: `tests/test_text.py`

**Interfaces:**
- Consumes: `resolve_font` (Task 7), `Storage` (Task 2), `list_images` (Task 6) for the image-overlap check.
- Produces (pure):
  - `TextBlock(id: int, bbox: tuple[float, float, float, float], text: str, font: str, size: float)`, a dataclass. `id` is the block's index in `page.get_text("dict")["blocks"]` for the current revision.
  - `list_blocks(data: bytes, page: int) -> list[TextBlock]`.
  - `replace_block(data: bytes, page: int, block_id: int, new_text: str, width: float | None = None) -> bytes`. `width` rewraps `new_text` to that width in points; `None` keeps the original box width.
- API: `GET /api/files/{id}/pages/{n}/text` and `POST /api/files/{id}/pages/{n}/text/{block_id}` with `{"text", "width"?}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_list_blocks_returns_text(three_line_pdf):
    blocks = list_blocks(three_line_pdf, 0)
    assert "line one" in blocks[0].text

def test_replace_block_changes_only_that_block(two_block_pdf):
    before = other_blocks_text(two_block_pdf, 0, skip=0)
    out = replace_block(two_block_pdf, 0, block_id=0, new_text="new words")
    assert "new words" in list_blocks(out, 0)[0].text
    assert other_blocks_text(out, 0, skip=0) == before           # anti-goal: unrelated text unchanged

def test_replace_keeps_overlapping_image(pdf_text_over_image):
    # Review Focus 2: covering the block must not erase the image
    xref = list_images(pdf_text_over_image, 0)[0].xref
    out = replace_block(pdf_text_over_image, 0, block_id=0, new_text="x")
    assert list_images(out, 0)[0].xref == xref

def test_rewrap_breaks_long_text(two_block_pdf):
    out = replace_block(two_block_pdf, 0, block_id=0, new_text="word " * 40, width=200)
    assert len(list_blocks(out, 0)[0].text.splitlines()) > 1
```

`other_blocks_text(data, page, skip)` is a helper in `conftest.py` that returns the text of every block except `skip`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_text.py -v`
Expected: FAIL with `ImportError` for `pdfe.text`

- [ ] **Step 3: Implement with PyMuPDF**

`list_blocks` reads `page.get_text("dict")`, keeping blocks of type 0, and takes font and size from their first span. `replace_block`: `add_redact_annot(bbox, fill=(1, 1, 1))`, then `apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)`, then `insert_textbox(rect, new_text, fontname=..., fontsize=...)` using `resolve_font`. If `width` is set, the rectangle width is `width` and the box keeps its top-left corner. If the text does not fit the box, raise `ValueError` rather than cut it off.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_text.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pdfe/text.py src/pdfe/api.py tests/test_text.py
git commit -m "feat: add text block list, replace, and rewrap"
```

---

### Task 9: Blank documents and new content

**Files:**
- Create: `src/pdfe/create.py`, `tests/test_create.py`
- Modify: `src/pdfe/api.py`
- Test: `tests/test_create.py`

**Interfaces:**
- Consumes: `resolve_font` (Task 7), `Storage` (Task 2).
- Produces (pure):
  - `new_document() -> bytes`: one blank A4 page.
  - `add_page(data: bytes) -> bytes`.
  - `add_text(data: bytes, page: int, rect: tuple[float, float, float, float], text: str, size: float = 11) -> bytes`.
  - `add_image(data: bytes, page: int, rect: tuple[float, float, float, float], png: bytes) -> bytes`.
- API: `POST /api/documents` → `201 {"id", "name", "revision"}` creating a file from `new_document()`. The other operations are reached through the revisions endpoint with `{"op": ...}` mapped to these functions in the same way as Tasks 5–8.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_document_has_one_blank_page():
    doc = fitz.open(stream=new_document(), filetype="pdf")
    assert doc.page_count == 1 and doc[0].get_text() == ""

def test_add_text_is_extractable(new_doc_bytes):
    out = add_text(new_doc_bytes, 0, (72, 72, 300, 120), "hello world")
    assert "hello world" in fitz.open(stream=out, filetype="pdf")[0].get_text()

def test_add_image_is_listed(new_doc_bytes, png_bytes):
    out = add_image(new_doc_bytes, 0, (72, 150, 200, 300), png_bytes)
    assert len(list_images(out, 0)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_create.py -v`
Expected: FAIL with `ImportError` for `pdfe.create`

- [ ] **Step 3: Implement with PyMuPDF**

Use `fitz.open()` for a new document, `page.insert_textbox` with `resolve_font` for text, and `page.insert_image` for PNGs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_create.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pdfe/create.py src/pdfe/api.py tests/test_create.py
git commit -m "feat: add blank document and new text and image content"
```

---

### Task 10: Browser UI

**Files:**
- Create: `src/pdfe/web/index.html`, `src/pdfe/web/app.js`, `src/pdfe/web/app.css`
- Modify: `src/pdfe/api.py` (serve `web/` at `/`)
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: every API route from Tasks 4–9.
- Produces: `GET /` returns `index.html`; static files under `/static/`. Layout: option B from the mockup. Page strip across the top (drag to reorder, the drag calls `pages/reorder`), page canvas in the middle (pdf.js renders the current revision), narrow tool panel on the right (move, resize, replace, delete image; edit text; rewrap; add page; new document). Fallback warnings from Task 7 shown as a banner.

- [ ] **Step 1: Write the failing test**

```python
def test_root_serves_editor(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "page-strip" in r.text and "tool-panel" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL with `404`

- [ ] **Step 3: Implement the UI**

Serve the static folder from `api.py`. `index.html` loads pdf.js from `cdnjs.cloudflare.com` at a pinned version. `app.js` uses `fetch` against the routes above. Keep it to plain JavaScript with no build step.

- [ ] **Step 4: Run test to verify it passes, then check by hand**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS

Then run `uv run pdfe`, open `http://127.0.0.1:8000/`, upload a typed PDF, reorder two pages, and move an image. Expected: each change appears on the page and in `data/`, and the original file is unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/pdfe/web src/pdfe/api.py tests/test_web.py
git commit -m "feat: add browser editor layout"
```

---

### Task 11: End-to-end check against the spec's acceptance criteria

**Files:**
- Create: `tests/test_acceptance.py`
- Test: `tests/test_acceptance.py`

**Interfaces:**
- Consumes: the full API from Tasks 4–10.
- Produces: nothing new; this task proves the spec's acceptance criteria.

- [ ] **Step 1: Write the test**

```python
def test_original_bytes_survive_many_edits(client, sample_pdf_bytes):
    fid = client.post("/api/files", files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")}).json()["id"]
    client.post(f"/api/files/{fid}/pages/rotate", json={"index": 0, "degrees": 90})
    client.post(f"/api/files/{fid}/pages/reorder", json={"order": [0]})
    assert client.get(f"/api/files/{fid}/original").content == sample_pdf_bytes   # Spec acceptance 2

def test_text_edit_leaves_other_text_unchanged(client, two_block_pdf):
    # Spec acceptance 3, through the HTTP route
    fid = upload(client, two_block_pdf)
    before = text_of_other_blocks(client, fid, skip=0)
    client.post(f"/api/files/{fid}/pages/0/text/0", json={"text": "changed"})
    assert text_of_other_blocks(client, fid, skip=0) == before
```

`upload`, `text_of_other_blocks` are helpers in `tests/conftest.py`. The first test needs the `GET /api/files/{id}/original` route, which Task 4 must include.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_acceptance.py -v`
Expected: FAIL if any earlier task is incomplete; PASS only once the full path works.

- [ ] **Step 3: Fix anything that fails**

Fix the owning module, not the test.

- [ ] **Step 4: Run the full suite and linter**

Run: `uv run pytest -v && uv run ruff check .`
Expected: all tests PASS and ruff reports no errors.

- [ ] **Step 5: Commit**

```bash
git add tests/test_acceptance.py
git commit -m "test: verify spec acceptance criteria end to end"
```

---

## Self-Review

**1. Spec coverage:**
- Goals: reorder/delete/rotate (Task 5), image move/resize/replace/delete (Task 6), text edit and rewrap (Task 8), new document (Task 9), keep originals and revisions (Tasks 2–3), run with one command (Task 1). Covered.
- Parts 1–6 of the spec map to Tasks 2–4, 5, 6, 8, 9, and 10. Covered.
- Acceptance: byte-identical original (Task 11), text outside the edited block unchanged (Tasks 8 and 11), each part tested with PyMuPDF (every task). Covered.
- Decisions: FastAPI, SQLAlchemy/SQLite, PyMuPDF, pypdf, Pillow, pdf.js, pytest/httpx/ruff/uv, `127.0.0.1`, UUID storage, white-cover text method, font fallback. All used. Covered.

**2. Step scan:** Task 9 names its API operations in one sentence rather than listing each route; the implementer can still write one reasonable thing, since Task 5–8 set the pattern. Task 8's overlap check says "must not erase the image" but leaves the method to the implementer, which is the intended level. No "TBD" lines.

**3. Type consistency:** `ImageInfo`, `TextBlock`, `FontChoice`, `Storage` method names, and `list_images` / `resolve_font` / `replace_block` signatures are used the same way where they recur. `GET /api/files/{id}/original` is used in Task 11 but Task 4 lists only `/download`. Fixing that inline: Task 4 must also add `GET /api/files/{id}/original`, returning `Storage.original_bytes`. Done in the plan's Task 4 interfaces below.

**4. Review Focus:** Each of the five has a test in its owning task: corrupt and encrypted upload (Task 2), overlapping image (Task 8), missing glyphs (Task 7), rotated bbox (Task 6), concurrent saves (Task 3). Covered.

**5. Proportion:** The plan is roughly three times the spec's length, mostly from the test code and task structure the skill requires. Code bodies are limited to tests and signatures, with a line of approach per step. Acceptable.

I fixed one gap during review: Task 4 needs the original-bytes route that Task 11 uses. It's now in Task 4's route list.

---

**Plan complete and saved to `docs/superpowers/plans/2026-10-20-pdf-editor.md`. Please review the plan. Which execution approach would you prefer?**

- **Subagent-driven**: A fresh subagent implements each task and a fresh reviewer checks it before the next one starts, then a whole-branch review at the end. Most thorough, but costs a fresh context per task and per review.
- **Native**: I implement every task myself in this session, then one fresh reviewer checks the whole branch. Cheapest and fastest, with no independent review until the end.

For this plan I recommend **Native**, because the eleven tasks build in a chain and each depends on the interfaces of the ones before it, so one session holding the whole design is the safer path. A shipped mistake here would only corrupt a local copy, since originals are never modified. Does the plan capture what you want, and which approach should we use?

