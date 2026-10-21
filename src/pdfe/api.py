from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
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
    replace_image,
    resize_image,
)
from pdfe.storage import Storage, check_pdf
from pdfe.text import list_blocks, replace_block

WEB_DIR = Path(__file__).parent / "web"


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

    def require(file_id: str):
        record = storage.get(file_id)
        if record is None:
            raise HTTPException(status_code=404, detail="no such file")
        return record

    def edit(file_id: str, operation: Callable[[bytes], bytes]) -> dict:
        require(file_id)
        try:
            return {"revision": storage.edit(file_id, operation)}
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/files", status_code=201)
    async def upload(file: UploadFile):
        data = await file.read()
        try:
            file_id = storage.save_upload(data, file.filename or "untitled.pdf")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": file_id, "name": file.filename, "revision": 1}

    @app.get("/api/files/{file_id}")
    def info(file_id: str):
        record = require(file_id)
        return {
            "id": record.id,
            "name": record.name,
            "revision": storage.latest_number(file_id),
        }

    @app.get("/api/files/{file_id}/download")
    def download(file_id: str):
        require(file_id)
        number = storage.latest_number(file_id)
        return Response(
            storage.revision_bytes(file_id, number),
            media_type="application/pdf",
            headers={"X-Revision": str(number)},
        )

    @app.get("/api/files/{file_id}/original")
    def original(file_id: str):
        require(file_id)
        return Response(storage.original_bytes(file_id), media_type="application/pdf")

    @app.post("/api/files/{file_id}/revisions", status_code=201)
    async def add_revision(file_id: str, request: Request):
        require(file_id)
        data = await request.body()
        try:
            check_pdf(data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"revision": storage.add_revision(file_id, data)}

    @app.post("/api/files/{file_id}/pages/reorder", status_code=201)
    def reorder_pages(file_id: str, body: ReorderBody):
        return edit(file_id, lambda data: pages.reorder(data, body.order))

    @app.post("/api/files/{file_id}/pages/delete", status_code=201)
    def delete_pages(file_id: str, body: DeleteBody):
        return edit(file_id, lambda data: pages.delete_pages(data, body.indexes))

    @app.post("/api/files/{file_id}/pages/rotate", status_code=201)
    def rotate_page(file_id: str, body: RotateBody):
        return edit(file_id, lambda data: pages.rotate_page(data, body.index, body.degrees))

    @app.get("/api/files/{file_id}/pages/{n}/images")
    def images(file_id: str, n: int):
        require(file_id)
        try:
            found = list_images(storage.latest_bytes(file_id), n)
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [{"xref": info.xref, "bbox": info.bbox} for info in found]

    @app.post("/api/files/{file_id}/pages/{n}/images/{xref}", status_code=201)
    def image_op(file_id: str, n: int, xref: int, body: ImageOpBody):
        if body.op == "move":
            operation = lambda data: move_image(data, n, xref, body.dx, body.dy)
        elif body.op == "resize":
            if body.width is None or body.height is None:
                raise HTTPException(status_code=400, detail="resize needs width and height")
            operation = lambda data: resize_image(
                data, n, xref, body.width, body.height
            )
        else:
            operation = lambda data: delete_image(data, n, xref)
        return edit(file_id, operation)

    @app.post("/api/files/{file_id}/pages/{n}/images/{xref}/replace", status_code=201)
    async def image_replace(file_id: str, n: int, xref: int, file: UploadFile):
        png = await file.read()
        return edit(file_id, lambda data: replace_image(data, n, xref, png))

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

    @app.post("/api/files/{file_id}/pages", status_code=201)
    def add_blank_page(file_id: str):
        return edit(file_id, add_page)

    @app.post("/api/files/{file_id}/pages/{n}/texts", status_code=201)
    def add_text_box(file_id: str, n: int, body: TextAddBody):
        rect = (body.x0, body.y0, body.x1, body.y1)
        fallback = resolve_font("Helvetica", body.text).fallback
        result = edit(file_id, lambda data: add_text(data, n, rect, body.text, body.size))
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
    ):
        png = await file.read()
        rect = (x0, y0, x1, y1)
        return edit(file_id, lambda data: add_image(data, n, rect, png))

    @app.get("/api/files/{file_id}/pages/{n}/text")
    def text(file_id: str, n: int):
        require(file_id)
        try:
            blocks = list_blocks(storage.latest_bytes(file_id), n)
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(block) for block in blocks]

    @app.post("/api/files/{file_id}/pages/{n}/text/{block_id}", status_code=201)
    def text_edit(file_id: str, n: int, block_id: int, body: TextBody):
        require(file_id)
        report = {}

        def operation(data: bytes) -> bytes:
            blocks = list_blocks(data, n)
            if not 0 <= block_id < len(blocks):
                raise ValueError(f"no text block {block_id} on page {n}")
            report["fallback"] = resolve_font(blocks[block_id].font, body.text).fallback
            return replace_block(data, n, block_id, body.text, body.width)

        try:
            revision = storage.edit(file_id, operation)
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"revision": revision, "fallback": report["fallback"]}

    @app.get("/api/files/{file_id}/revisions")
    def revisions(file_id: str):
        require(file_id)
        return {"latest": storage.latest_number(file_id), "revisions": storage.revision_numbers(file_id)}

    @app.post("/api/files/{file_id}/revert", status_code=201)
    def revert(file_id: str, body: RevertBody):
        require(file_id)
        try:
            data = storage.revision_bytes(file_id, body.revision)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such revision") from exc
        return {"revision": storage.add_revision(file_id, data)}

    return app
