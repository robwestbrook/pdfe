import pymupdf

# PyMuPDF reports positions in the page's unrotated frame. The browser shows the
# page as it is displayed, so the API speaks displayed coordinates and converts at
# the boundary with these two helpers.


def to_displayed(page: pymupdf.Page, rect) -> pymupdf.Rect:
    out = pymupdf.Rect(rect) * page.rotation_matrix
    out.normalize()
    return out


def to_page(page: pymupdf.Page, rect) -> pymupdf.Rect:
    out = pymupdf.Rect(rect) * page.derotation_matrix
    out.normalize()
    return out
