
from pdf_helpers import page_size

from pdfe.images import (
    delete_image,
    list_images,
    move_image,
    replace_image,
    resize_image,
)


def test_list_images_reports_bbox(pdf_with_image):
    imgs = list_images(pdf_with_image, 0)
    assert len(imgs) == 1
    assert imgs[0].bbox[2] > imgs[0].bbox[0]


def test_move_image_shifts_bbox(pdf_with_image):
    before = list_images(pdf_with_image, 0)[0]
    out = move_image(pdf_with_image, 0, before.xref, dx=50, dy=0)
    after = list_images(out, 0)[0]
    assert abs((after.bbox[0] - before.bbox[0]) - 50) < 0.5


def test_rotated_page_bbox_matches_display(pdf_with_image_rotated_90):
    # Review Focus 4: bbox is in displayed (rotated) coordinates
    img = list_images(pdf_with_image_rotated_90, 0)[0]
    w, h = page_size(pdf_with_image_rotated_90, 0)
    x0, y0, x1, y1 = img.bbox
    assert 0 <= x0 < x1 <= w
    assert 0 <= y0 < y1 <= h


def test_delete_image_removes_it(pdf_with_image):
    xref = list_images(pdf_with_image, 0)[0].xref
    assert list_images(delete_image(pdf_with_image, 0, xref), 0) == []


def test_resize_image_sets_size(pdf_with_image):
    img = list_images(pdf_with_image, 0)[0]
    out = resize_image(pdf_with_image, 0, img.xref, width=200, height=80)
    after = list_images(out, 0)[0].bbox
    assert abs((after[2] - after[0]) - 200) < 0.5
    assert abs((after[3] - after[1]) - 80) < 0.5


def test_replace_image_keeps_place(pdf_with_image, png_bytes):
    img = list_images(pdf_with_image, 0)[0]
    out = replace_image(pdf_with_image, 0, img.xref, png_bytes)
    after = list_images(out, 0)
    assert len(after) == 1
    assert all(abs(a - b) < 0.5 for a, b in zip(after[0].bbox, img.bbox))


def test_image_routes_list_then_move(storage, pdf_with_image):
    from fastapi.testclient import TestClient

    from pdfe.api import create_app

    client = TestClient(create_app(storage))
    fid = client.post(
        "/api/files", files={"file": ("a.pdf", pdf_with_image, "application/pdf")}
    ).json()["id"]
    listed = client.get(f"/api/files/{fid}/pages/0/images").json()
    assert len(listed) == 1
    r = client.post(
        f"/api/files/{fid}/pages/0/images/{listed[0]['xref']}",
        json={"op": "move", "dx": 30, "dy": 0},
    )
    assert r.status_code == 201
    moved = client.get(f"/api/files/{fid}/pages/0/images").json()
    assert abs((moved[0]["bbox"][0] - listed[0]["bbox"][0]) - 30) < 0.5


def test_move_on_rotated_page_moves_along_displayed_x(pdf_with_image_rotated_90):
    # Review Focus 4: a move lands where the user asked, in displayed coordinates
    before = list_images(pdf_with_image_rotated_90, 0)[0]
    out = move_image(pdf_with_image_rotated_90, 0, before.xref, dx=40, dy=0)
    after = list_images(out, 0)[0]
    assert abs((after.bbox[0] - before.bbox[0]) - 40) < 0.5
    assert abs(after.bbox[1] - before.bbox[1]) < 0.5


def test_move_keeps_text_under_image(pdf_text_over_image):
    # Fix 1: moving an image must not delete text that sits under it
    from pdf_helpers import page_texts

    img = list_images(pdf_text_over_image, 0)[0]
    out = move_image(pdf_text_over_image, 0, img.xref, dx=200, dy=0)
    assert "over image" in page_texts(out)[0]


def test_resize_keeps_text_under_image(pdf_text_over_image):
    from pdf_helpers import page_texts

    img = list_images(pdf_text_over_image, 0)[0]
    out = resize_image(pdf_text_over_image, 0, img.xref, width=300, height=120)
    assert "over image" in page_texts(out)[0]


def test_move_keeps_an_overlapping_image(png_bytes):
    # Fix 1: an image that overlaps the one being moved must survive the move
    from io import BytesIO

    import pymupdf
    from PIL import Image

    blue = BytesIO()
    Image.new("RGB", (40, 20), (0, 0, 255)).save(blue, "PNG")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(72, 100, 172, 150), stream=png_bytes)
    page.insert_image(pymupdf.Rect(150, 120, 250, 170), stream=blue.getvalue())
    data = doc.tobytes()
    first = list_images(data, 0)[0]
    out = move_image(data, 0, first.xref, dx=0, dy=-60)
    assert len(list_images(out, 0)) == 2
