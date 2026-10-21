import pymupdf


def page_texts(data: bytes) -> list[str]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    texts = [page.get_text().strip() for page in doc]
    doc.close()
    return texts


def page_size(data: bytes, index: int) -> tuple[float, float]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    rect = doc[index].rect
    doc.close()
    return rect.width, rect.height
