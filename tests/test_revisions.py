from fastapi.testclient import TestClient

from pdfe.api import create_app


def upload(client, data: bytes) -> str:
    return client.post("/api/files", files={"file": ("a.pdf", data, "application/pdf")}).json()["id"]


def test_history_lists_every_revision(storage, sample_pdf_bytes):
    client = TestClient(create_app(storage))
    fid = upload(client, sample_pdf_bytes)
    client.post(f"/api/files/{fid}/pages/rotate", json={"index": 0, "degrees": 90})
    r = client.get(f"/api/files/{fid}/revisions").json()
    assert r == {"latest": 2, "revisions": [1, 2]}


def test_revert_makes_a_new_revision_with_old_bytes(storage, sample_pdf_bytes):
    # Fix 4: going back never deletes history
    client = TestClient(create_app(storage))
    fid = upload(client, sample_pdf_bytes)
    client.post(f"/api/files/{fid}/pages", json={})
    assert client.get(f"/api/files/{fid}/download").content != sample_pdf_bytes
    r = client.post(f"/api/files/{fid}/revert", json={"revision": 1})
    assert r.status_code == 201
    assert r.json()["revision"] == 3
    assert client.get(f"/api/files/{fid}/download").content == sample_pdf_bytes
    assert client.get(f"/api/files/{fid}/revisions").json()["revisions"] == [1, 2, 3]


def test_revert_unknown_revision_is_404(storage, sample_pdf_bytes):
    client = TestClient(create_app(storage))
    fid = upload(client, sample_pdf_bytes)
    assert client.post(f"/api/files/{fid}/revert", json={"revision": 99}).status_code == 404


def test_text_edit_reports_substitute_font(storage, two_block_pdf):
    # Fix 6: an edit that needs a substitute font says so in its response
    client = TestClient(create_app(storage))
    fid = upload(client, two_block_pdf)
    r = client.post(f"/api/files/{fid}/pages/0/text/0", json={"text": "café Привет"})
    assert r.status_code == 201
    assert r.json()["fallback"] is True
    r = client.post(f"/api/files/{fid}/pages/0/text/0", json={"text": "plain words"})
    assert r.json()["fallback"] is False




def test_download_reports_the_revision_it_returns(storage, sample_pdf_bytes):
    # Fix 7: the page and its revision number come from one response, so they never disagree
    client = TestClient(create_app(storage))
    fid = upload(client, sample_pdf_bytes)
    client.post(f"/api/files/{fid}/pages/rotate", json={"index": 0, "degrees": 90})
    r = client.get(f"/api/files/{fid}/download")
    assert r.headers["x-revision"] == "2"
