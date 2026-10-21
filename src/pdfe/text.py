from dataclasses import dataclass

import pymupdf

from pdfe.fonts import FontChoice, resolve_font


@dataclass(frozen=True)
class TextBlock:
    id: int
    bbox: tuple[float, float, float, float]
    text: str
    font: str
    size: float


def list_blocks(data: bytes, page: int) -> list[TextBlock]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        return [_describe(i, raw) for i, raw in enumerate(_text_blocks(doc[page]))]
    finally:
        doc.close()


def replace_block(
    data: bytes, page: int, block_id: int, new_text: str, width: float | None = None
) -> bytes:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        pg = doc[page]
        raw = _text_blocks(pg)
        if not 0 <= block_id < len(raw):
            raise ValueError(f"no text block {block_id} on page {page}")
        info = _describe(block_id, raw[block_id])
        bbox = pymupdf.Rect(info.bbox)

        pg.add_redact_annot(bbox, fill=(1, 1, 1))
        pg.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        )

        choice = resolve_font(info.font, new_text)
        box_width = width if width is not None else bbox.width
        limit = _growth_limit(pg, bbox, box_width)
        height = _fit_height(new_text, choice, info.size, box_width, limit - bbox.y0)
        if height is None:
            raise ValueError("text does not fit, even below the block; shorten it or widen the block")
        rect = pymupdf.Rect(bbox.x0, bbox.y0, bbox.x0 + box_width, bbox.y0 + height)
        pg.insert_textbox(
            rect,
            new_text,
            fontname=choice.fontname,
            fontfile=choice.fontfile,
            fontsize=info.size,
        )
        return doc.tobytes()
    finally:
        doc.close()


def _text_blocks(pg: pymupdf.Page) -> list[dict]:
    return [b for b in pg.get_text("dict")["blocks"] if b["type"] == 0]


def _describe(block_id: int, raw: dict) -> TextBlock:
    first_span = raw["lines"][0]["spans"][0]
    text = "\n".join("".join(span["text"] for span in line["spans"]) for line in raw["lines"])
    return TextBlock(
        id=block_id,
        bbox=tuple(raw["bbox"]),
        text=text,
        font=first_span["font"],
        size=first_span["size"],
    )


_PAGE_MARGIN = 36


def _growth_limit(pg: pymupdf.Page, bbox: pymupdf.Rect, width: float) -> float:
    """The lowest y a block written at bbox may reach without running into content below it."""
    limit = pg.rect.y1 - _PAGE_MARGIN
    for block in pg.get_text("dict")["blocks"]:
        top = block["bbox"][1]
        overlaps = block["bbox"][0] < bbox.x0 + width and block["bbox"][2] > bbox.x0
        if overlaps and top > bbox.y0 + 1:
            limit = min(limit, top - 2)
    return limit


def _fit_height(
    text: str, choice: FontChoice, size: float, width: float, max_height: float
) -> float | None:
    """The smallest box height that holds text, or None if max_height is not enough.

    Each trial lays the text out on a scratch page, so the real page is untouched.
    Two font sizes is the least height PyMuPDF will lay out one line in.
    """
    def fits(height: float) -> bool:
        scratch = pymupdf.open()
        try:
            page = scratch.new_page(width=width + 100, height=height + 100)
            unused = page.insert_textbox(
                pymupdf.Rect(0, 0, width, height),
                text,
                fontname=choice.fontname,
                fontfile=choice.fontfile,
                fontsize=size,
            )
            return unused >= 0
        finally:
            scratch.close()

    low, high = 2 * size, max_height
    if high < low or not fits(high):
        return None
    while high - low > 0.5:
        middle = (low + high) / 2
        if fits(middle):
            high = middle
        else:
            low = middle
    return high
