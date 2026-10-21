from pdf_helpers import LocalClient, block_texts_without

from pdfe.api import create_app


def upload(client, data: bytes) -> str:
    return client.post("/api/files", files={"file": ("a.pdf", data, "application/pdf")}).json()["id"]


def test_original_bytes_survive_many_edits(storage, sample_pdf_bytes):
    client = LocalClient(create_app(storage))
    fid = upload(client, sample_pdf_bytes)
    client.post(f"/api/files/{fid}/pages/rotate", json={"index": 0, "degrees": 90})
    client.post(f"/api/files/{fid}/pages/reorder", json={"order": [0]})
    client.post(f"/api/files/{fid}/pages/0/texts", json={"text": "more", "x0": 72, "y0": 200, "x1": 300, "y1": 240})
    assert client.get(f"/api/files/{fid}/original").content == sample_pdf_bytes  # spec acceptance 2


def test_text_edit_leaves_other_text_unchanged(storage, two_block_pdf):
    client = LocalClient(create_app(storage))
    fid = upload(client, two_block_pdf)
    before = block_texts_without(client.get(f"/api/files/{fid}/download").content, 0, marker="word")
    client.post(f"/api/files/{fid}/pages/0/text/0", json={"text": "changed"})
    after = block_texts_without(client.get(f"/api/files/{fid}/download").content, 0, marker="changed")
    assert after == before  # spec acceptance 3, through HTTP
