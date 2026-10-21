import gzip
import hashlib
import os
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

import pymupdf
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from pdfe.db import FileRecord, Revision


class RevisionConflict(Exception):
    def __init__(self, latest: int) -> None:
        super().__init__(f"the file is at revision {latest}")
        self.latest = latest


class Storage:
    """Files as numbered revisions. Each distinct content is stored once, gzip-compressed,
    under its sha256, so a revision's bytes never change and reverting costs no space."""

    def __init__(self, root: Path, engine: Engine) -> None:
        self.root = root
        self.engine = engine
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._upgrade_previous_layout()

    def _upgrade_previous_layout(self) -> None:
        # Files saved before revisions were shared by content keep their bytes in files/<id>/.
        # Move each of their revisions into the shared store. The old files are left in place.
        with self.engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(revisions)")}
            if "digest" in columns:
                return
            conn.exec_driver_sql("ALTER TABLE revisions ADD COLUMN digest VARCHAR")
        with Session(self.engine) as session:
            for revision in session.scalars(select(Revision)).all():
                folder = self.root / "files" / revision.file_id
                legacy = folder / f"rev-{revision.number}.pdf"
                if revision.number == 1 and not legacy.exists():
                    legacy = folder / "original.pdf"
                revision.digest = self._store_blob(legacy.read_bytes())
            session.commit()

    def get(self, file_id: str) -> FileRecord | None:
        with Session(self.engine) as session:
            return session.get(FileRecord, file_id)

    def save_upload(self, data: bytes, name: str) -> str:
        check_pdf(data)
        file_id = uuid.uuid4().hex
        digest = self._store_blob(data)
        with Session(self.engine) as session:
            session.add(FileRecord(id=file_id, name=name))
            session.add(Revision(file_id=file_id, number=1, digest=digest))
            session.commit()
        return file_id

    def original_bytes(self, file_id: str) -> bytes:
        return self._blob(self._digest_of(file_id, 1))

    def latest_bytes(self, file_id: str) -> bytes:
        return self._blob(self._digest_of(file_id, self.latest_number(file_id)))

    def revision_bytes(self, file_id: str, number: int) -> bytes:
        return self._blob(self._digest_of(file_id, number))

    def revision_numbers(self, file_id: str) -> list[int]:
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    select(Revision.number).where(Revision.file_id == file_id).order_by(Revision.number)
                )
            )

    def latest_number(self, file_id: str) -> int:
        with Session(self.engine) as session:
            return session.scalar(
                select(func.max(Revision.number)).where(Revision.file_id == file_id)
            )

    def add_revision(self, file_id: str, data: bytes) -> int:
        with self._lock_for(file_id):
            return self._commit(file_id, data)

    def edit(
        self,
        file_id: str,
        operation: Callable[[bytes], bytes],
        base: int | None = None,
    ) -> int:
        """Apply operation to the latest revision and save the result as a new one.

        The read, the operation, and the save happen under one lock, so two overlapping
        edits cannot both start from the same base. If base is given and is not the
        latest revision, nothing changes and RevisionConflict is raised.
        """
        with self._lock_for(file_id):
            latest = self.latest_number(file_id)
            if base is not None and base != latest:
                raise RevisionConflict(latest)
            return self._commit(file_id, operation(self.latest_bytes(file_id)))

    def _commit(self, file_id: str, data: bytes) -> int:
        number = self.latest_number(file_id) + 1
        digest = self._store_blob(data)
        with Session(self.engine) as session:
            session.add(Revision(file_id=file_id, number=number, digest=digest))
            session.commit()
        return number

    def _digest_of(self, file_id: str, number: int) -> str:
        with Session(self.engine) as session:
            digest = session.scalar(
                select(Revision.digest).where(Revision.file_id == file_id, Revision.number == number)
            )
        if digest is None:
            raise KeyError(number)
        return digest

    def _blob_path(self, digest: str) -> Path:
        return self.root / "blobs" / f"{digest}.pdf.gz"

    def _store_blob(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        path = self._blob_path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(path, gzip.compress(data))
        return digest

    def _blob(self, digest: str) -> bytes:
        return gzip.decompress(self._blob_path(digest).read_bytes())

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
