from dataclasses import dataclass
from typing import Self

import pymupdf

from pdfe import placements as pl
from pdfe.coords import to_displayed, to_page
from pdfe.pictures import normalize_picture


@dataclass(frozen=True)
class ImageInfo:
    xref: int
    bbox: tuple[float, float, float, float]  # displayed coordinates


def list_images(data: bytes, page: int) -> list[ImageInfo]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        pg = doc[page]
        found = [
            ImageInfo(info["xref"], tuple(to_displayed(pg, info["bbox"])))
            for info in pg.get_image_info(xrefs=True)
        ]
    finally:
        doc.close()
    # Top-to-bottom, then left-to-right: a stable order that does not depend on how the file is stored.
    return sorted(found, key=lambda image: (image.bbox[1], image.bbox[0], image.xref))


def move_image(data: bytes, page: int, xref: int, dx: float, dy: float) -> bytes:
    return _place(data, page, xref, lambda box: box + (dx, dy, dx, dy), keep_shape=True)


def resize_image(data: bytes, page: int, xref: int, width: float, height: float) -> bytes:
    return _place(
        data,
        page,
        xref,
        lambda box: pymupdf.Rect(box.x0, box.y0, box.x0 + width, box.y0 + height),
        keep_shape=False,
    )


def delete_image(data: bytes, page: int, xref: int) -> bytes:
    with _Scene(data, page, xref) as scene:
        pl.rewrite_page(scene.pdf, scene.pdf_page, {scene.site.index: []})
        return pl.save(scene.pdf)


def replace_image(data: bytes, page: int, xref: int, picture: bytes) -> bytes:
    picture = normalize_picture(picture)
    with _Scene(data, page, xref) as scene:
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


def _place(data: bytes, page: int, xref: int, change, keep_shape: bool) -> bytes:
    with _Scene(data, page, xref) as scene:
        new_user = scene.to_user(change(scene.box))
        old_user = scene.user_box
        if keep_shape:
            # Move: shift the image within the page, keeping its own orientation.
            target = pl.shifted(scene.site.ctm, new_user.x0 - old_user.x0, new_user.y0 - old_user.y0)
        else:
            target = pl.upright(new_user)
        cm = pl.transform_for(scene.site, target)
        pl.rewrite_page(scene.pdf, scene.pdf_page, {scene.site.index: pl.draw_image(scene.site.name, cm)})
        return pl.save(scene.pdf)


class _Scene:
    """One image's drawing on one page, seen both as PDF content and as PyMuPDF sees it."""

    def __init__(self, data: bytes, page: int, xref: int) -> None:
        self._data = data
        self._page = page
        self._xref = xref

    def __enter__(self) -> Self:
        self._doc = pymupdf.open(stream=self._data, filetype="pdf")
        self._pg = self._doc[self._page]
        self.pdf = pl.load(self._data)
        self.pdf_page = self.pdf.pages[self._page]
        sites = [s for s in pl.image_sites(self.pdf, self.pdf_page) if s.xref == self._xref]
        if not sites:
            self._doc.close()
            raise ValueError(f"image {self._xref} is not on page {self._page}")
        self.site = sites[0]
        self.user_box = pl.unit_square_rect(self.site.ctm)
        self.box = to_displayed(self._pg, self.user_box * self._pg.transformation_matrix)
        return self

    def __exit__(self, *exc) -> None:
        self._doc.close()

    def to_user(self, displayed) -> pymupdf.Rect:
        return to_page(self._pg, displayed) * ~self._pg.transformation_matrix
