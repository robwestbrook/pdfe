import pymupdf
import pytest
from fastapi.testclient import TestClient
from pdf_helpers import page_texts

from pdfe.api import create_app
from pdfe.create import add_image, add_text, new_document
from pdfe.images import list_images


@pytest.fixture
def blank_pdf() -> bytes:
    return new_document()


def test_new_document_has_one_blank_page():
    doc = pymupdf.open(stream=new_document(), filetype="pdf")
    assert doc.page_count == 1
    assert doc[0].get_text() == ""


def test_add_text_is_extractable(blank_pdf):
    out = add_text(blank_pdf, 0, (72, 72, 300, 120), "hello world")
    assert "hello world" in page_texts(out)[0]


def test_add_image_is_listed(blank_pdf, png_bytes):
    out = add_image(blank_pdf, 0, (72, 150, 200, 300), png_bytes)
    assert len(list_images(out, 0)) == 1


def test_create_document_route_then_add_text(storage):
    client = TestClient(create_app(storage))
    r = client.post("/api/documents")
    assert r.status_code == 201
    fid = r.json()["id"]
    r = client.post(
        f"/api/files/{fid}/pages/0/texts",
        json={"text": "hello route", "x0": 72, "y0": 72, "x1": 300, "y1": 120},
    )
    assert r.status_code == 201
    assert "hello route" in page_texts(client.get(f"/api/files/{fid}/download").content)[0]


def test_picture_route_places_image(storage, png_bytes):
    client = TestClient(create_app(storage))
    fid = client.post("/api/documents").json()["id"]
    r = client.post(
        f"/api/files/{fid}/pages/0/pictures",
        files={"file": ("p.png", png_bytes, "image/png")},
        data={"x0": "72", "y0": "150", "x1": "200", "y1": "300"},
    )
    assert r.status_code == 201
    assert len(list_images(client.get(f"/api/files/{fid}/download").content, 0)) == 1


def test_add_text_over_existing_text_is_refused(storage, two_block_pdf):
    # Fix 3: new text may not sit on top of existing text, where it would merge with it
    with pytest.raises(ValueError):
        add_text(two_block_pdf, 0, (72, 72, 300, 120), "overlapping note")


def test_add_text_clear_of_existing_text(two_block_pdf):
    out = add_text(two_block_pdf, 0, (72, 300, 300, 330), "separate note")
    assert "separate note" in page_texts(out)[0]


def _image_bytes(fmt: str) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (40, 20), (30, 160, 60)).save(buf, fmt)
    return buf.getvalue()


@pytest.mark.parametrize("fmt", ["GIF", "JPEG", "PNG"])
def test_pictures_accept_common_formats(blank_pdf, fmt):
    # Fix 5: PNG, GIF, and JPEG pictures are accepted
    out = add_image(blank_pdf, 0, (72, 150, 200, 300), _image_bytes(fmt))
    assert len(list_images(out, 0)) == 1


def test_pictures_accept_wordperfect(blank_pdf):
    # Fix 5: WordPerfect graphics are converted to PNG first
    from wand.color import Color
    from wand.image import Image as WandImage

    with WandImage(width=40, height=20, background=Color("red")) as img:
        img.format = "wpg"
        wpg = img.make_blob()
    out = add_image(blank_pdf, 0, (72, 150, 200, 300), wpg)
    assert len(list_images(out, 0)) == 1


def test_unknown_picture_format_is_refused(blank_pdf):
    with pytest.raises(ValueError):
        add_image(blank_pdf, 0, (72, 150, 200, 300), b"just some text")


def test_add_text_touching_existing_text_is_refused(two_block_pdf):
    # Fix 3: text placed right against existing text would join that block when read back
    from pdfe.text import list_blocks

    bottom = list_blocks(two_block_pdf, 0)[0].bbox[3]
    with pytest.raises(ValueError):
        add_text(two_block_pdf, 0, (72, bottom + 1, 300, bottom + 20), "touching note")
