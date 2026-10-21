import pytest
from fastapi.testclient import TestClient

from pdfe.api import create_app


@pytest.fixture
def client(storage):
    return TestClient(create_app(storage))


def test_upload_then_download_roundtrip(client, sample_pdf_bytes):
    r = client.post("/api/files", files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")})
    assert r.status_code == 201
    fid = r.json()["id"]
    assert client.get(f"/api/files/{fid}/download").content == sample_pdf_bytes


def test_upload_corrupt_returns_400(client):
    r = client.post("/api/files", files={"file": ("bad.pdf", b"nope", "application/pdf")})
    assert r.status_code == 400


def test_unknown_file_returns_404(client):
    assert client.get("/api/files/does-not-exist").status_code == 404


def test_revision_post_updates_download_and_keeps_original(client, sample_pdf_bytes, storage):
    r = client.post("/api/files", files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")})
    fid = r.json()["id"]
    r = client.post(
        f"/api/files/{fid}/revisions",
        content=sample_pdf_bytes,
        headers={"content-type": "application/pdf"},
    )
    assert r.status_code == 201
    assert r.json()["revision"] == 2
    assert client.get(f"/api/files/{fid}/original").content == sample_pdf_bytes


def test_file_info_reports_latest_revision(client, sample_pdf_bytes):
    fid = client.post(
        "/api/files", files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")}
    ).json()["id"]
    info = client.get(f"/api/files/{fid}").json()
    assert info == {"id": fid, "name": "a.pdf", "revision": 1}
