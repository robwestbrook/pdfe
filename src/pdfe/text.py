from dataclasses import dataclass

import pymupdf

from pdfe.fonts import resolve_font


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
        # The tight text bounds are shorter than one line of PyMuPDF's layout,
        # so the write area is at least two font sizes tall.
        rect = pymupdf.Rect(
            bbox.x0,
            bbox.y0,
            bbox.x0 + (width if width is not None else bbox.width),
            max(bbox.y1, bbox.y0 + 2 * info.size),
        )
        unused = pg.insert_textbox(
            rect,
            new_text,
            fontname=choice.fontname,
            fontfile=choice.fontfile,
            fontsize=info.size,
        )
        if unused < 0:
            raise ValueError("text does not fit the block; shorten it or widen the block")
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
