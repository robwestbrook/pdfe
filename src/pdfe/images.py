from dataclasses import dataclass
from typing import Self

import pymupdf

from pdfe import placements as pl
from pdfe.coords import to_displayed, to_page
from pdfe.pictures import normalize_picture


@dataclass(frozen=True)
class ImageInfo:
    key: str  # the object number as text, or "inline-N" for an inline image
    xref: int  # the object number, or 0 for an inline image
    bbox: tuple[float, float, float, float]  # displayed coordinates


def list_images(data: bytes, page: int) -> list[ImageInfo]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        pg = doc[page]
        listed = [(info["xref"], tuple(to_displayed(pg, info["bbox"]))) for info in pg.get_image_info(xrefs=True)]
    finally:
        doc.close()
    named = [ImageInfo(str(xref), xref, box) for xref, box in listed if xref]
    inline = _inline_images(data, page, [box for xref, box in listed if not xref])
    # Top-to-bottom, then left-to-right: a stable order that does not depend on how the file is stored.
    return sorted(named + inline, key=lambda image: (image.bbox[1], image.bbox[0], image.key))


def move_image(data: bytes, page: int, key: str, dx: float, dy: float) -> bytes:
    return _place(data, page, key, lambda box: box + (dx, dy, dx, dy), keep_shape=True)


def resize_image(data: bytes, page: int, key: str, width: float, height: float) -> bytes:
    return _place(
        data,
        page,
        key,
        lambda box: pymupdf.Rect(box.x0, box.y0, box.x0 + width, box.y0 + height),
        keep_shape=False,
    )


def move_image_to_page(data: bytes, page: int, key: str, target: int, x: float, y: float) -> bytes:
    """Move an image so its top-left corner is at (x, y) on the target page, in displayed coordinates.

    The image keeps its size. Moving within the same page is an ordinary move.
    """
    with _Scene(data, page, key) as scene:
        width, height = scene.box.width, scene.box.height
        if target == page:
            return _place(data, page, key, lambda box: pymupdf.Rect(x, y, x + width, y + height), keep_shape=True)
        doc = pymupdf.open(stream=data, filetype="pdf")
        try:
            if not 0 <= target < doc.page_count:
                raise ValueError(f"no page {target}")
            target_page = doc[target]
            destination = to_page(target_page, pymupdf.Rect(x, y, x + width, y + height))
            target_user = destination * ~target_page.transformation_matrix
        finally:
            doc.close()
        pl.add_image_to_page(scene.pdf, scene.pdf.pages[target], scene.site, pl.upright(target_user))
        pl.rewrite_page(scene.pdf, scene.pdf_page, {scene.site.index: []})
        return pl.save(scene.pdf)


def delete_image(data: bytes, page: int, key: str) -> bytes:
    with _Scene(data, page, key) as scene:
        pl.rewrite_page(scene.pdf, scene.pdf_page, {scene.site.index: []})
        return pl.save(scene.pdf)


def replace_image(data: bytes, page: int, key: str, picture: bytes) -> bytes:
    picture = normalize_picture(picture)
    with _Scene(data, page, key) as scene:
        box = scene.box
        pl.rewrite_page(scene.pdf, scene.pdf_page, {scene.site.index: []})
        edited = pl.save(scene.pdf)
    doc = pymupdf.open(stream=edited, filetype="pdf")
    try:
        pg = doc[page]
        # The new picture is drawn on top of the page's other content.
        pg.insert_image(to_page(pg, box), stream=picture, overlay=True, keep_proportion=False)
        return doc.tobytes()
    finally:
        doc.close()


def _place(data: bytes, page: int, key: str, change, keep_shape: bool) -> bytes:
    with _Scene(data, page, key) as scene:
        new_user = scene.to_user(change(scene.box))
        old_user = scene.user_box
        if keep_shape:
            # Move: shift the image within the page, keeping its own orientation.
            target = pl.shifted(scene.site.ctm, new_user.x0 - old_user.x0, new_user.y0 - old_user.y0)
        else:
            target = pl.upright(new_user)
        cm = pl.transform_for(scene.site, target)
        pl.rewrite_page(scene.pdf, scene.pdf_page, {scene.site.index: pl.draw_image(scene.site.payload, cm)})
        return pl.save(scene.pdf)


def _inline_images(data: bytes, page: int, boxes: list[tuple]) -> list[ImageInfo]:
    """Ids for the inline images that PyMuPDF lists, matched to the page's inline images by position."""
    if not boxes:
        return []
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        pg = doc[page]
        pdf = pl.load(data)
        found = [
            (site.ordinal, tuple(to_displayed(pg, pl.unit_square_rect(site.ctm) * pg.transformation_matrix)))
            for site in pl.image_sites(pdf, pdf.pages[page])
            if site.ordinal >= 0
        ]
    finally:
        doc.close()
    images = []
    for box in boxes:
        ordinal = next((n for n, found_box in found if _close(found_box, box)), None)
        key = f"inline-{ordinal}" if ordinal is not None else f"inline-unmatched-{len(images)}"
        images.append(ImageInfo(key, 0, box))
    return images


def _close(a, b) -> bool:
    return all(abs(x - y) < 0.5 for x, y in zip(a, b))


class _Scene:
    """One image's drawing on one page, seen both as PDF content and as PyMuPDF sees it.

    key is the image's id: its object number, or "inline-N" for an inline image.
    """

    def __init__(self, data: bytes, page: int, key: str) -> None:
        self._data = data
        self._page = page
        self._key = str(key)

    def __enter__(self) -> Self:
        self._doc = pymupdf.open(stream=self._data, filetype="pdf")
        self._pg = self._doc[self._page]
        self.pdf = pl.load(self._data)
        self.pdf_page = self.pdf.pages[self._page]
        sites = pl.image_sites(self.pdf, self.pdf_page)
        if self._key.startswith("inline-") and self._key[7:].isdigit():
            ordinal = int(self._key[7:])
            matches = [s for s in sites if s.ordinal == ordinal]
        elif self._key.isdigit():
            matches = [s for s in sites if s.xref == int(self._key) and s.ordinal < 0]
        else:
            matches = []
        if not matches:
            self._doc.close()
            raise ValueError(f"image {self._key} is not on page {self._page}")
        self.site = matches[0]
        self.user_box = pl.unit_square_rect(self.site.ctm)
        self.box = self.box_of(self.site)
        return self

    def __exit__(self, *exc) -> None:
        self._doc.close()

    def box_of(self, site) -> pymupdf.Rect:
        return to_displayed(self._pg, pl.unit_square_rect(site.ctm) * self._pg.transformation_matrix)

    def to_user(self, displayed) -> pymupdf.Rect:
        return to_page(self._pg, displayed) * ~self._pg.transformation_matrix
