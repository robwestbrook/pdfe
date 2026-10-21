import pymupdf
import pytest
from pdf_helpers import LocalClient, page_texts

from pdfe.api import create_app
from pdfe.pages import delete_pages, reorder, rotate_page


def test_reorder_moves_pages(three_page_pdf):
    out = reorder(three_page_pdf, [2, 0, 1])
    assert page_texts(out) == ["page 3", "page 1", "page 2"]


def test_delete_pages(three_page_pdf):
    assert page_texts(delete_pages(three_page_pdf, [1])) == ["page 1", "page 3"]


def test_rotate_sets_rotation(three_page_pdf):
    out = rotate_page(three_page_pdf, 0, 90)
    assert pymupdf.open(stream=out, filetype="pdf")[0].rotation == 90


def test_reorder_rejects_non_permutation(three_page_pdf):
    with pytest.raises(ValueError):
        reorder(three_page_pdf, [0, 0, 1])


def test_delete_rejects_every_page(three_page_pdf):
    with pytest.raises(ValueError):
        delete_pages(three_page_pdf, [0, 1, 2])


def test_reorder_route_creates_revision(storage, three_page_pdf):
    client = LocalClient(create_app(storage))
    fid = client.post(
        "/api/files", files={"file": ("a.pdf", three_page_pdf, "application/pdf")}
    ).json()["id"]
    r = client.post(f"/api/files/{fid}/pages/reorder", json={"order": [2, 0, 1]})
    assert r.status_code == 201
    assert page_texts(client.get(f"/api/files/{fid}/download").content) == [
        "page 3",
        "page 1",
        "page 2",
    ]
