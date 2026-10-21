import pytest

from pdf_helpers import block_texts_without
from pdfe.images import list_images
from pdfe.text import list_blocks, replace_block


def test_list_blocks_returns_text(three_line_pdf):
    blocks = list_blocks(three_line_pdf, 0)
    assert "line one" in blocks[0].text


def test_replace_block_changes_only_that_block(two_block_pdf):
    before = block_texts_without(two_block_pdf, 0, marker="word")
    out = replace_block(two_block_pdf, 0, block_id=0, new_text="new words")
    assert any("new words" in b.text for b in list_blocks(out, 0))
    assert block_texts_without(out, 0, marker="new words") == before  # anti-goal: unrelated text unchanged


def test_replace_keeps_overlapping_image(pdf_text_over_image):
    # Review Focus 2: covering the text must not erase the image under it
    xref = list_images(pdf_text_over_image, 0)[0].xref
    out = replace_block(pdf_text_over_image, 0, block_id=0, new_text="x")
    assert list_images(out, 0)[0].xref == xref


def test_rewrap_breaks_long_text(two_block_pdf):
    out = replace_block(two_block_pdf, 0, block_id=0, new_text="word " * 20, width=200)
    rewrapped = next(b for b in list_blocks(out, 0) if "word" in b.text)
    assert len(rewrapped.text.splitlines()) > 1


def test_text_that_does_not_fit_is_refused(two_block_pdf):
    with pytest.raises(ValueError):
        replace_block(two_block_pdf, 0, block_id=0, new_text="word " * 200)


def test_text_routes_list_then_edit(storage, two_block_pdf):
    from fastapi.testclient import TestClient

    from pdfe.api import create_app

    client = TestClient(create_app(storage))
    fid = client.post(
        "/api/files", files={"file": ("a.pdf", two_block_pdf, "application/pdf")}
    ).json()["id"]
    listed = client.get(f"/api/files/{fid}/pages/0/text").json()
    assert "word" in listed[0]["text"]
    r = client.post(f"/api/files/{fid}/pages/0/text/0", json={"text": "changed words"})
    assert r.status_code == 201
    texts = [b["text"] for b in client.get(f"/api/files/{fid}/pages/0/text").json()]
    assert any("changed words" in t for t in texts)
