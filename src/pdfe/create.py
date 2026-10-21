import pymupdf

from pdfe.fonts import resolve_font
from pdfe.pictures import normalize_picture

PAGE_SIZE = pymupdf.paper_rect("a4")


def new_document() -> bytes:
    doc = pymupdf.open()
    try:
        doc.new_page(width=PAGE_SIZE.width, height=PAGE_SIZE.height)
        return doc.tobytes()
    finally:
        doc.close()


def add_page(data: bytes) -> bytes:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        doc.new_page(width=PAGE_SIZE.width, height=PAGE_SIZE.height)
        return doc.tobytes()
    finally:
        doc.close()


def add_text(
    data: bytes,
    page: int,
    rect: tuple[float, float, float, float],
    text: str,
    size: float = 11,
) -> bytes:
    choice = resolve_font("Helvetica", text)
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        target = pymupdf.Rect(rect)
        if _text_overlaps(doc[page], target):
            raise ValueError("that area already has text; choose a clear spot for the new text")
        unused = doc[page].insert_textbox(
            target,
            text,
            fontname=choice.fontname,
            fontfile=choice.fontfile,
            fontsize=size,
        )
        if unused < 0:
            raise ValueError("text does not fit the box; make the box larger")
        return doc.tobytes()
    finally:
        doc.close()


def add_image(
    data: bytes,
    page: int,
    rect: tuple[float, float, float, float],
    picture: bytes,
) -> bytes:
    picture = normalize_picture(picture)
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        doc[page].insert_image(pymupdf.Rect(rect), stream=picture, keep_proportion=False)
        return doc.tobytes()
    finally:
        doc.close()


_CLEARANCE = 4  # points; text closer than this to existing text is read back as part of it


def _text_overlaps(page: pymupdf.Page, rect: pymupdf.Rect) -> bool:
    # New text placed over or against existing text would be grouped with it when the page is read back.
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        clear_area = pymupdf.Rect(block["bbox"]) + (-_CLEARANCE, -_CLEARANCE, _CLEARANCE, _CLEARANCE)
        if clear_area.intersects(rect):
            return True
    return False
