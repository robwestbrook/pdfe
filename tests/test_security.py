from fastapi.testclient import TestClient
from pdf_helpers import LocalClient

from pdfe.api import create_app


def test_other_hosts_are_refused(storage):
    # Problem 3: a page served for another name (DNS rebinding) cannot use the editor
    client = TestClient(create_app(storage), base_url="http://evil.example")
    assert client.get("/api/documents").status_code in (403, 405)
    assert client.get("/").status_code == 403


def test_writes_need_the_editor_header(storage):
    # Problem 3: a plain cross-site form cannot write, because it cannot send this header
    client = TestClient(create_app(storage), base_url="http://localhost")
    assert client.post("/api/documents").status_code == 403


def test_writes_from_another_origin_are_refused(storage):
    client = TestClient(create_app(storage), base_url="http://localhost")
    r = client.post("/api/documents", headers={"X-Pdfe": "1", "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_edits_need_the_revision_they_were_made_from(storage, sample_pdf_bytes):
    # Problem 2: an edit without a base revision is refused, not applied to whatever is current
    client = LocalClient(create_app(storage))
    fid = client.post("/api/files", files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")}).json()["id"]
    raw = TestClient(create_app(storage), base_url="http://localhost", headers={"X-Pdfe": "1"})
    assert raw.post(f"/api/files/{fid}/pages/rotate", json={"index": 0, "degrees": 90}).status_code == 428


def test_stale_edit_is_a_conflict(storage, sample_pdf_bytes):
    # Problem 2: a second tab working from an old revision is told the file has moved on
    client = LocalClient(create_app(storage))
    fid = client.post("/api/files", files={"file": ("a.pdf", sample_pdf_bytes, "application/pdf")}).json()["id"]
    client.post(f"/api/files/{fid}/pages/rotate", json={"index": 0, "degrees": 90})
    r = client.post(
        f"/api/files/{fid}/pages/rotate",
        json={"index": 0, "degrees": 90},
        headers={"X-Base-Revision": "1"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["latest"] == 2
