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
        replace_block(two_block_pdf, 0, block_id=0, new_text="word " * 2000)


def test_text_routes_list_then_edit(storage, two_block_pdf):
    from pdf_helpers import LocalClient

    from pdfe.api import create_app

    client = LocalClient(create_app(storage))
    fid = client.post(
        "/api/files", files={"file": ("a.pdf", two_block_pdf, "application/pdf")}
    ).json()["id"]
    listed = client.get(f"/api/files/{fid}/pages/0/text").json()
    assert "word" in listed[0]["text"]
    r = client.post(f"/api/files/{fid}/pages/0/text/0", json={"text": "changed words"})
    assert r.status_code == 201
    texts = [b["text"] for b in client.get(f"/api/files/{fid}/pages/0/text").json()]
    assert any("changed words" in t for t in texts)


def test_block_grows_downward_into_free_space(two_block_pdf):
    # Fix 2: a longer paragraph extends down into free space, and nothing is cut off
    out = replace_block(two_block_pdf, 0, block_id=0, new_text="word " * 120, width=300)
    grown = next(b for b in list_blocks(out, 0) if "word" in b.text)
    before = next(b for b in list_blocks(two_block_pdf, 0) if "word" in b.text)
    assert grown.bbox[3] > before.bbox[3]
    assert grown.text.split().count("word") == 120  # nothing cut off
    assert other_text_unchanged(two_block_pdf, out)


def test_growth_stops_before_the_next_block(two_block_pdf):
    # Fix 2: a block may not grow into the footer below it
    with pytest.raises(ValueError):
        replace_block(two_block_pdf, 0, block_id=0, new_text="word " * 600, width=300)


def other_text_unchanged(before: bytes, after: bytes) -> bool:
    return block_texts_without(before, 0, marker="word") == block_texts_without(after, 0, marker="word")


def _pixel_at(data: bytes, rect, x: int, y: int) -> tuple[int, int, int]:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    pix = doc[0].get_pixmap(clip=pymupdf.Rect(rect), dpi=72)
    doc.close()
    return pix.pixel(x, y)[:3]


def test_replacing_text_keeps_the_background_it_sat_on():
    # Problem 1: the old text's box must not be painted white over a coloured background
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(60, 60, 400, 120), color=None, fill=(1, 1, 0))
    page.insert_text((80, 95), "on yellow", fontname="helv", fontsize=11)
    data = doc.tobytes()
    block = list_blocks(data, 0)[0]
    out = replace_block(data, 0, 0, "new")
    assert _pixel_at(out, block.bbox, 1, 1) == (255, 255, 0)


def test_replacing_text_keeps_the_image_under_it(png_bytes):
    # Problem 1: the image under the old text keeps its pixels
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(72, 100, 172, 150), stream=png_bytes)
    page.insert_text((80, 130), "over image", fontname="helv", fontsize=11)
    data = doc.tobytes()
    block = list_blocks(data, 0)[0]
    out = replace_block(data, 0, 0, "x")
    assert _pixel_at(out, block.bbox, 1, 1) == (200, 30, 30)


def test_text_boxes_are_listed_as_displayed_on_rotated_page():
    # Problem 4: on a rotated page, text boxes are reported where they show on screen
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "turned text", fontname="helv", fontsize=11)
    page.set_rotation(90)
    data = doc.tobytes()
    turned = pymupdf.open(stream=data, filetype="pdf")[0]
    expected = pymupdf.Rect(turned.search_for("turned text")[0]) * turned.rotation_matrix
    expected.normalize()
    shown = list_blocks(data, 0)[0].bbox
    assert all(abs(a - b) < 0.5 for a, b in zip(shown, expected))


def test_edited_text_keeps_its_direction_on_a_rotated_page():
    # Problem 4: rotated text keeps the direction it runs in when it is edited
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 400, 200), "word " * 30, fontname="helv", fontsize=11, rotate=90)
    data = doc.tobytes()
    before = list_blocks(data, 0)[0]
    out = replace_block(data, 0, 0, "ab")
    after = next(b for b in list_blocks(out, 0) if "ab" in b.text)
    assert after.rotate == before.rotate
