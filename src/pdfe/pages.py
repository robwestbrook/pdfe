from io import BytesIO

from pypdf import PdfReader, PdfWriter


def reorder(data: bytes, order: list[int]) -> bytes:
    reader = PdfReader(BytesIO(data))
    if sorted(order) != list(range(len(reader.pages))):
        raise ValueError("order must list every page index exactly once")
    writer = PdfWriter()
    for index in order:
        writer.add_page(reader.pages[index])
    return _write(writer)


def delete_pages(data: bytes, indexes: list[int]) -> bytes:
    reader = PdfReader(BytesIO(data))
    _check_indexes(indexes, len(reader.pages))
    if set(indexes) >= set(range(len(reader.pages))):
        raise ValueError("cannot delete every page")
    writer = PdfWriter()
    for index, page in enumerate(reader.pages):
        if index not in indexes:
            writer.add_page(page)
    return _write(writer)


def rotate_page(data: bytes, index: int, degrees: int) -> bytes:
    if degrees not in (90, 180, 270):
        raise ValueError("degrees must be 90, 180, or 270")
    reader = PdfReader(BytesIO(data))
    _check_indexes([index], len(reader.pages))
    writer = PdfWriter(clone_from=reader)
    writer.pages[index].rotate(degrees)
    return _write(writer)


def _check_indexes(indexes: list[int], count: int) -> None:
    if any(not 0 <= index < count for index in indexes):
        raise ValueError("page index out of range")


def _write(writer: PdfWriter) -> bytes:
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
