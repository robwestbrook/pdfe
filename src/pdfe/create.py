import pymupdf

from pdfe.fonts import resolve_font

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
        unused = doc[page].insert_textbox(
            pymupdf.Rect(rect),
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
    png: bytes,
) -> bytes:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        doc[page].insert_image(pymupdf.Rect(rect), stream=png, keep_proportion=False)
        return doc.tobytes()
    finally:
        doc.close()
