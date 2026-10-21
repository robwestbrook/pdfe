from collections.abc import Callable
from dataclasses import dataclass

import pymupdf

from pdfe.pictures import normalize_picture


@dataclass(frozen=True)
class ImageInfo:
    xref: int
    bbox: tuple[float, float, float, float]


def list_images(data: bytes, page: int) -> list[ImageInfo]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        infos = doc[page].get_image_info(xrefs=True)
        return [ImageInfo(xref=info["xref"], bbox=tuple(info["bbox"])) for info in infos]
    finally:
        doc.close()


def move_image(data: bytes, page: int, xref: int, dx: float, dy: float) -> bytes:
    return _rewrite(
        data,
        page,
        xref,
        lambda rect: rect + (dx, dy, dx, dy),
        lambda pg, rect: pg.insert_image(rect, xref=xref, overlay=True, keep_proportion=False),
    )


def resize_image(data: bytes, page: int, xref: int, width: float, height: float) -> bytes:
    return _rewrite(
        data,
        page,
        xref,
        lambda rect: pymupdf.Rect(rect.x0, rect.y0, rect.x0 + width, rect.y0 + height),
        lambda pg, rect: pg.insert_image(rect, xref=xref, overlay=True, keep_proportion=False),
    )


def delete_image(data: bytes, page: int, xref: int) -> bytes:
    return _rewrite(data, page, xref, lambda rect: rect, lambda pg, rect: None)


def replace_image(data: bytes, page: int, xref: int, picture: bytes) -> bytes:
    picture = normalize_picture(picture)
    return _rewrite(
        data,
        page,
        xref,
        lambda rect: rect,
        lambda pg, rect: pg.insert_image(rect, stream=picture, overlay=True, keep_proportion=False),
    )


def _rewrite(
    data: bytes,
    page: int,
    xref: int,
    new_rect: Callable[[pymupdf.Rect], pymupdf.Rect],
    place: Callable[[pymupdf.Page, pymupdf.Rect], None],
) -> bytes:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        pg = doc[page]
        rects = pg.get_image_rects(xref)
        if not rects:
            raise ValueError(f"image {xref} is not on page {page}")
        old = rects[0]
        neighbours = _other_placements(pg, xref, old)
        pg.add_redact_annot(old)
        pg.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_REMOVE,
            text=pymupdf.PDF_REDACT_TEXT_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
        )
        for other_xref, other_rect in neighbours:
            pg.insert_image(other_rect, xref=other_xref, keep_proportion=False)
        place(pg, new_rect(old))
        return doc.tobytes()
    finally:
        doc.close()


def _other_placements(pg: pymupdf.Page, xref: int, old: pymupdf.Rect) -> list[tuple[int, pymupdf.Rect]]:
    """Other image placements that overlap old, so the redaction can put them back."""
    found = []
    for info in pg.get_image_info(xrefs=True):
        rect = pymupdf.Rect(info["bbox"])
        if info["xref"] == xref and rect == old:
            continue
        if rect.intersects(old):
            found.append((info["xref"], rect))
    return found
