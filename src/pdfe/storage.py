import os
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

import pymupdf
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from pdfe.db import FileRecord, Revision


class Storage:
    def __init__(self, root: Path, engine: Engine) -> None:
        self.root = root
        self.engine = engine
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def get(self, file_id: str) -> FileRecord | None:
        with Session(self.engine) as session:
            return session.get(FileRecord, file_id)

    def save_upload(self, data: bytes, name: str) -> str:
        check_pdf(data)

        file_id = uuid.uuid4().hex
        folder = self.root / "files" / file_id
        folder.mkdir(parents=True)
        _write_atomic(folder / "original.pdf", data)
        _write_atomic(folder / "rev-1.pdf", data)

        with Session(self.engine) as session:
            session.add(FileRecord(id=file_id, name=name))
            session.add(Revision(file_id=file_id, number=1))
            session.commit()
        return file_id

    def original_bytes(self, file_id: str) -> bytes:
        return (self.root / "files" / file_id / "original.pdf").read_bytes()

    def latest_bytes(self, file_id: str) -> bytes:
        number = self.latest_number(file_id)
        return self._revision_path(file_id, number).read_bytes()

    def add_revision(self, file_id: str, data: bytes) -> int:
        with self._lock_for(file_id):
            return self._commit(file_id, data)

    def edit(self, file_id: str, operation: Callable[[bytes], bytes]) -> int:
        """Apply operation to the latest revision and save the result as a new one.

        The read, the operation, and the save happen under one lock, so two
        overlapping edits cannot both start from the same base revision.
        """
        with self._lock_for(file_id):
            return self._commit(file_id, operation(self.latest_bytes(file_id)))

    def _commit(self, file_id: str, data: bytes) -> int:
        with Session(self.engine) as session:
            latest = session.scalar(
                select(func.max(Revision.number)).where(Revision.file_id == file_id)
            )
            number = (latest or 0) + 1
            _write_atomic(self._revision_path(file_id, number), data)
            session.add(Revision(file_id=file_id, number=number))
            session.commit()
        return number

    def revision_numbers(self, file_id: str) -> list[int]:
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    select(Revision.number).where(Revision.file_id == file_id).order_by(Revision.number)
                )
            )

    def revision_bytes(self, file_id: str, number: int) -> bytes:
        path = self._revision_path(file_id, number)
        if not path.exists():
            raise KeyError(number)
        return path.read_bytes()

    def latest_number(self, file_id: str) -> int:
        with Session(self.engine) as session:
            return session.scalar(
                select(func.max(Revision.number)).where(Revision.file_id == file_id)
            )

    def _revision_path(self, file_id: str, number: int) -> Path:
        return self.root / "files" / file_id / f"rev-{number}.pdf"

    def _lock_for(self, file_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(file_id, threading.Lock())


def check_pdf(data: bytes) -> None:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("not a readable PDF") from exc
    try:
        if doc.needs_pass:
            raise ValueError("encrypted PDFs are not supported")
    finally:
        doc.close()


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
