import pymupdf


def page_texts(data: bytes) -> list[str]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    texts = [page.get_text().strip() for page in doc]
    doc.close()
    return texts
