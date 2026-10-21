from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import Response

from pdfe.db import make_engine
from pdfe.storage import Storage, check_pdf


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

    return app
