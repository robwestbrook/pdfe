from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from pdfe import pages
from pdfe.db import make_engine
from pdfe.images import delete_image, list_images, move_image, replace_image, resize_image
from pdfe.storage import Storage, check_pdf


class ReorderBody(BaseModel):
    order: list[int]


class DeleteBody(BaseModel):
    indexes: list[int]


class RotateBody(BaseModel):
    index: int
    degrees: int


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
            data = operation(storage.latest_bytes(file_id))
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"revision": storage.add_revision(file_id, data)}

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
        return Response(storage.latest_bytes(file_id), media_type="application/pdf")

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
            operation = lambda data: move_image(data, n, xref, body.dx, body.dy)  # noqa: E731
        elif body.op == "resize":
            if body.width is None or body.height is None:
                raise HTTPException(status_code=400, detail="resize needs width and height")
            operation = lambda data: resize_image(  # noqa: E731
                data, n, xref, body.width, body.height
            )
        else:
            operation = lambda data: delete_image(data, n, xref)  # noqa: E731
        return edit(file_id, operation)

    @app.post("/api/files/{file_id}/pages/{n}/images/{xref}/replace", status_code=201)
    async def image_replace(file_id: str, n: int, xref: int, file: UploadFile):
        png = await file.read()
        return edit(file_id, lambda data: replace_image(data, n, xref, png))

    return app
