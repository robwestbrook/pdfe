"""Edits to where a page draws its images, made in the page's content stream.

Moving, resizing, or deleting an image changes only that image's drawing command.
Everything else on the page keeps its place in the stacking order.
"""

from dataclasses import dataclass
from io import BytesIO

import pikepdf
import pymupdf

Matrix = tuple[float, float, float, float, float, float]
_IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)


@dataclass(frozen=True)
class Site:
    index: int  # position of the image's Do instruction in the page's content
    xref: int
    name: pikepdf.Name  # the image's name in the page's resources
    ctm: Matrix  # transform in effect when the image is drawn


def image_sites(pdf: pikepdf.Pdf, page: pikepdf.Page) -> list[Site]:
    sites = []
    stack: list[Matrix] = []
    ctm = _IDENTITY
    for index, instruction in enumerate(pikepdf.parse_content_stream(page)):
        operator = str(instruction.operator)
        if operator == "q":
            stack.append(ctm)
        elif operator == "Q":
            ctm = stack.pop() if stack else _IDENTITY
        elif operator == "cm":
            ctm = _mul(tuple(float(v) for v in instruction.operands), ctm)
        elif operator == "Do":
            xobject = page.Resources.XObject[instruction.operands[0]]
            if xobject.get("/Subtype") == "/Image":
                sites.append(Site(index, xobject.objgen[0], instruction.operands[0], ctm))
    return sites


def rewrite_page(pdf: pikepdf.Pdf, page: pikepdf.Page, edits: dict[int, list]) -> None:
    """Replace instructions by index. An empty list deletes the instruction."""
    instructions = []
    for index, instruction in enumerate(pikepdf.parse_content_stream(page)):
        if index in edits:
            instructions.extend(edits[index])
        else:
            instructions.append(instruction)
    page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(instructions))


def draw_image(name: pikepdf.Name, cm: Matrix) -> list:
    """Instructions that draw the image name with cm applied first, inside their own q/Q."""
    return [
        pikepdf.ContentStreamInstruction([], pikepdf.Operator("q")),
        pikepdf.ContentStreamInstruction(list(cm), pikepdf.Operator("cm")),
        pikepdf.ContentStreamInstruction([name], pikepdf.Operator("Do")),
        pikepdf.ContentStreamInstruction([], pikepdf.Operator("Q")),
    ]


def shifted(ctm: Matrix, dx: float, dy: float) -> Matrix:
    """The transform of an image drawn at ctm, moved by dx, dy in page user space."""
    return _mul(ctm, (1, 0, 0, 1, dx, dy))


def transform_for(site: Site, target: Matrix) -> Matrix:
    """The cm operand that makes the image end up at target, given the transform it is drawn in."""
    return _mul(target, _invert(site.ctm))


def unit_square_rect(ctm: Matrix) -> pymupdf.Rect:
    a, b, c, d, e, f = ctm
    corners = [(e, f), (a + e, b + f), (c + e, d + f), (a + c + e, b + d + f)]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))


def upright(rect: pymupdf.Rect) -> Matrix:
    """Transform that draws the unit image square over rect (in PDF user space)."""
    return (rect.width, 0, 0, rect.height, rect.x0, rect.y0)


def load(data: bytes) -> pikepdf.Pdf:
    return pikepdf.open(BytesIO(data))


def save(pdf: pikepdf.Pdf) -> bytes:
    out = BytesIO()
    pdf.save(out)
    return out.getvalue()


def _mul(m: Matrix, n: Matrix) -> Matrix:
    """Apply m, then n (the PDF convention CTM' = M x CTM)."""
    return (
        m[0] * n[0] + m[1] * n[2],
        m[0] * n[1] + m[1] * n[3],
        m[2] * n[0] + m[3] * n[2],
        m[2] * n[1] + m[3] * n[3],
        m[4] * n[0] + m[5] * n[2] + n[4],
        m[4] * n[1] + m[5] * n[3] + n[5],
    )


def _invert(m: Matrix) -> Matrix:
    a, b, c, d, e, f = m
    det = a * d - b * c
    if det == 0:
        raise ValueError("image transform cannot be inverted")
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(e * ia + f * ic), -(e * ib + f * id_))
