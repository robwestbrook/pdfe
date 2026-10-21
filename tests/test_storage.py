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
