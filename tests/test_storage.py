import pytest


def test_original_unchanged_after_revision(storage, sample_pdf_bytes):
    fid = storage.save_upload(sample_pdf_bytes, "a.pdf")
    storage.add_revision(fid, b"%PDF-1.4 edited")
    assert storage.original_bytes(fid) == sample_pdf_bytes


def test_latest_is_newest_revision(storage, sample_pdf_bytes):
    fid = storage.save_upload(sample_pdf_bytes, "a.pdf")
    storage.add_revision(fid, b"second")
    assert storage.latest_bytes(fid) == b"second"


def test_corrupt_upload_rejected_and_nothing_written(storage):
    with pytest.raises(ValueError):
        storage.save_upload(b"not a pdf", "bad.pdf")
    assert list((storage.root / "files").glob("*")) == []


def test_encrypted_upload_rejected(storage, encrypted_pdf_bytes):
    with pytest.raises(ValueError):
        storage.save_upload(encrypted_pdf_bytes, "locked.pdf")


def test_two_saves_get_distinct_revisions(storage, sample_pdf_bytes):
    from concurrent.futures import ThreadPoolExecutor

    fid = storage.save_upload(sample_pdf_bytes, "a.pdf")
    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(lambda i: storage.add_revision(fid, f"r{i}".encode()), range(20)))
    assert sorted(numbers) == list(range(2, 22))


def test_concurrent_edits_are_not_lost(storage, sample_pdf_bytes):
    # Review Focus 5: two edits that overlap must both survive
    import time
    from concurrent.futures import ThreadPoolExecutor

    fid = storage.save_upload(sample_pdf_bytes, "a.pdf")

    def append_marker(i):
        def operation(data):
            time.sleep(0.005)
            return data + f"|{i}".encode()

        storage.edit(fid, operation)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append_marker, range(20)))
    latest = storage.latest_bytes(fid)
    assert all(f"|{i}".encode() in latest for i in range(20))


def test_files_from_the_previous_layout_still_open(tmp_path, sample_pdf_bytes):
    # Existing files keep their history when the storage layout changes
    import sqlite3

    from pdfe.db import make_engine
    from pdfe.storage import Storage

    root = tmp_path / "data"
    folder = root / "files" / "abc"
    folder.mkdir(parents=True)
    (folder / "original.pdf").write_bytes(sample_pdf_bytes)
    (folder / "rev-1.pdf").write_bytes(sample_pdf_bytes)
    (folder / "rev-2.pdf").write_bytes(b"second revision bytes")
    db = root / "pdfe.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE files (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL)")
    conn.execute("CREATE TABLE revisions (id INTEGER PRIMARY KEY, file_id VARCHAR, number INTEGER NOT NULL)")
    conn.execute("INSERT INTO files VALUES ('abc', 'old.pdf')")
    conn.execute("INSERT INTO revisions (file_id, number) VALUES ('abc', 1), ('abc', 2)")
    conn.commit()
    conn.close()

    storage = Storage(root, make_engine(f"sqlite:///{db}"))
    assert storage.revision_numbers("abc") == [1, 2]
    assert storage.revision_bytes("abc", 2) == b"second revision bytes"
    assert storage.original_bytes("abc") == sample_pdf_bytes
