from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import pymupdf
from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pdfe import pages
from pdfe.create import add_image, add_page, add_text, new_document
from pdfe.db import make_engine
from pdfe.fonts import resolve_font
from pdfe.images import (
    delete_image,
    list_images,
    move_image,
    move_image_to_page,
    replace_image,
    resize_image,
)
from pdfe.storage import RevisionConflict, Storage, check_pdf
from pdfe.text import list_blocks, replace_block

WEB_DIR = Path(__file__).parent / "web"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_PICTURE_BYTES = 20 * 1024 * 1024
THUMBNAIL_WIDTH = 140
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class ReorderBody(BaseModel):
    order: list[int]


class DeleteBody(BaseModel):
    indexes: list[int]


class RotateBody(BaseModel):
    index: int
    degrees: int


class TextBody(BaseModel):
    text: str
    width: float | None = None


class RevertBody(BaseModel):
    revision: int


class TextAddBody(BaseModel):
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float = 11


class MoveToPageBody(BaseModel):
    target: int
    x: float
    y: float


class ImageOpBody(BaseModel):
    op: Literal["move", "resize", "delete"]
    dx: float = 0
    dy: float = 0
    width: float | None = None
    height: float | None = None


def create_app(storage: Storage | None = None) -> FastAPI:
    if storage is None:
        root = Path("data")
        root.mkdir(exist_ok=True)
        storage = Storage(root, make_engine(f"sqlite:///{root / 'pdfe.db'}"))

    app = FastAPI()

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Only this computer may use the editor. A page on another site cannot send
        # the editor's header, so it cannot write even if it reaches the port.
        host = request.headers.get("host", "").rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS:
            return _refuse("this editor only answers on this computer")
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in LOCAL_HOSTS:
            return _refuse("requests from other sites are not allowed")
        if request.method not in SAFE_METHODS and request.headers.get("x-pdfe") != "1":
            return _refuse("this request did not come from the editor")
        return await call_next(request)

    def require(file_id: str):
        record = storage.get(file_id)
        if record is None:
            raise HTTPException(status_code=404, detail="no such file")
        return record

    def base_revision(x_base_revision: int | None = Header(default=None)) -> int:
        if x_base_revision is None:
            raise HTTPException(status_code=428, detail="send the revision you are editing in X-Base-Revision")
        return x_base_revision

    def edit(file_id: str, operation: Callable[[bytes], bytes], base: int) -> dict:
        require(file_id)
        try:
            return {"revision": storage.edit(file_id, operation, base=base)}
        except RevisionConflict as exc:
            raise _conflict(exc) from exc
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/fonts/check")
    def font_check(font: str, text: str):
        choice = resolve_font(font, text)
        return {"fontname": choice.fontname, "fallback": choice.fallback}

    @app.post("/api/documents", status_code=201)
    def create_document():
        file_id = storage.save_upload(new_document(), "Untitled.pdf")
        return {"id": file_id, "name": "Untitled.pdf", "revision": 1}

    @app.post("/api/files", status_code=201)
    async def upload(file: UploadFile):
        data = await _read_limited(file, MAX_UPLOAD_BYTES)
        name = file.filename or "untitled.pdf"
        try:
            file_id = storage.save_upload(data, name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": file_id, "name": name, "revision": 1}

    @app.get("/api/files/{file_id}")
    def info(file_id: str):
        record = require(file_id)
        return {"id": record.id, "name": record.name, "revision": storage.latest_number(file_id)}

    @app.get("/api/files/{file_id}/download")
    def download(file_id: str):
        record = require(file_id)
        number = storage.latest_number(file_id)
        return Response(
            storage.revision_bytes(file_id, number),
            media_type="application/pdf",
            headers={
                "X-Revision": str(number),
                "Content-Disposition": f'inline; filename="{_safe_name(record.name)}"',
            },
        )

    @app.get("/api/files/{file_id}/original")
    def original(file_id: str):
        require(file_id)
        return Response(storage.original_bytes(file_id), media_type="application/pdf")

    @app.get("/api/files/{file_id}/revisions")
    def revisions(file_id: str):
        require(file_id)
        return {"latest": storage.latest_number(file_id), "revisions": storage.revision_numbers(file_id)}

    @app.get("/api/files/{file_id}/revisions/{number}/pages/{n}/thumbnail")
    def thumbnail(file_id: str, number: int, n: int):
        require(file_id)
        try:
            data = storage.revision_bytes(file_id, number)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such revision") from exc
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            if not 0 <= n < doc.page_count:
                raise HTTPException(status_code=404, detail="no such page")
            page = doc[n]
            zoom = THUMBNAIL_WIDTH / page.rect.width
            png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
        finally:
            doc.close()
        # A revision never changes, so its thumbnails can be kept by the browser for good.
        return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.post("/api/files/{file_id}/revisions", status_code=201)
    async def add_raw_revision(file_id: str, request: Request, base: int = Depends(base_revision)):
        require(file_id)
        data = await request.body()
        try:
            check_pdf(data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return edit(file_id, lambda _: data, base)

    @app.post("/api/files/{file_id}/revert", status_code=201)
    def revert(file_id: str, body: RevertBody, base: int = Depends(base_revision)):
        require(file_id)
        try:
            data = storage.revision_bytes(file_id, body.revision)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such revision") from exc
        return edit(file_id, lambda _: data, base)

    @app.post("/api/files/{file_id}/pages", status_code=201)
    def add_blank_page(file_id: str, base: int = Depends(base_revision)):
        return edit(file_id, add_page, base)

    @app.post("/api/files/{file_id}/pages/reorder", status_code=201)
    def reorder_pages(file_id: str, body: ReorderBody, base: int = Depends(base_revision)):
        return edit(file_id, lambda data: pages.reorder(data, body.order), base)

    @app.post("/api/files/{file_id}/pages/delete", status_code=201)
    def delete_pages(file_id: str, body: DeleteBody, base: int = Depends(base_revision)):
        return edit(file_id, lambda data: pages.delete_pages(data, body.indexes), base)

    @app.post("/api/files/{file_id}/pages/rotate", status_code=201)
    def rotate_page(file_id: str, body: RotateBody, base: int = Depends(base_revision)):
        return edit(file_id, lambda data: pages.rotate_page(data, body.index, body.degrees), base)

    @app.get("/api/files/{file_id}/pages/{n}/images")
    def images(file_id: str, n: int):
        require(file_id)
        try:
            found = list_images(storage.latest_bytes(file_id), n)
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [{"xref": info.xref, "bbox": info.bbox} for info in found]

    @app.post("/api/files/{file_id}/pages/{n}/images/{xref}", status_code=201)
    def image_op(file_id: str, n: int, xref: int, body: ImageOpBody, base: int = Depends(base_revision)):
        if body.op == "move":
            operation = lambda data: move_image(data, n, xref, body.dx, body.dy)
        elif body.op == "resize":
            if body.width is None or body.height is None:
                raise HTTPException(status_code=400, detail="resize needs width and height")
            operation = lambda data: resize_image(data, n, xref, body.width, body.height)
        else:
            operation = lambda data: delete_image(data, n, xref)
        return edit(file_id, operation, base)

    @app.post("/api/files/{file_id}/pages/{n}/images/{xref}/to-page", status_code=201)
    def image_to_page(file_id: str, n: int, xref: int, body: MoveToPageBody, base: int = Depends(base_revision)):
        return edit(file_id, lambda data: move_image_to_page(data, n, xref, body.target, body.x, body.y), base)

    @app.post("/api/files/{file_id}/pages/{n}/images/{xref}/replace", status_code=201)
    async def image_replace(
        file_id: str, n: int, xref: int, file: UploadFile, base: int = Depends(base_revision)
    ):
        picture = await _read_limited(file, MAX_PICTURE_BYTES)
        return edit(file_id, lambda data: replace_image(data, n, xref, picture), base)

    @app.post("/api/files/{file_id}/pages/{n}/texts", status_code=201)
    def add_text_box(file_id: str, n: int, body: TextAddBody, base: int = Depends(base_revision)):
        rect = (body.x0, body.y0, body.x1, body.y1)
        fallback = resolve_font("Helvetica", body.text).fallback
        result = edit(file_id, lambda data: add_text(data, n, rect, body.text, body.size), base)
        return {**result, "fallback": fallback}

    @app.post("/api/files/{file_id}/pages/{n}/pictures", status_code=201)
    async def add_picture(
        file_id: str,
        n: int,
        file: UploadFile,
        x0: float = Form(),
        y0: float = Form(),
        x1: float = Form(),
        y1: float = Form(),
        base: int = Depends(base_revision),
    ):
        picture = await _read_limited(file, MAX_PICTURE_BYTES)
        rect = (x0, y0, x1, y1)
        return edit(file_id, lambda data: add_image(data, n, rect, picture), base)

    @app.get("/api/files/{file_id}/pages/{n}/text")
    def text(file_id: str, n: int):
        require(file_id)
        try:
            blocks = list_blocks(storage.latest_bytes(file_id), n)
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(block) for block in blocks]

    @app.post("/api/files/{file_id}/pages/{n}/text/{block_id}", status_code=201)
    def text_edit(file_id: str, n: int, block_id: int, body: TextBody, base: int = Depends(base_revision)):
        report = {}

        def operation(data: bytes) -> bytes:
            blocks = list_blocks(data, n)
            if not 0 <= block_id < len(blocks):
                raise ValueError(f"no text block {block_id} on page {n}")
            report["fallback"] = resolve_font(blocks[block_id].font, body.text).fallback
            return replace_block(data, n, block_id, body.text, body.width)

        result = edit(file_id, operation, base)
        return {**result, "fallback": report["fallback"]}

    return app


def _refuse(message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=403)


def _conflict(exc: RevisionConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": "the file changed in another window", "latest": exc.latest},
    )


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"file is larger than {limit // (1024 * 1024)} MB")
    return data


def _safe_name(name: str) -> str:
    return name.replace('"', "").replace("\r", "").replace("\n", "")
