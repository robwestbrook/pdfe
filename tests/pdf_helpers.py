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


def block_texts_without(data: bytes, index: int, marker: str) -> list[str]:
    """Text of every text block on the page that does not contain marker."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    blocks = [b for b in doc[index].get_text("dict")["blocks"] if b["type"] == 0]
    doc.close()
    texts = ["\n".join("".join(s["text"] for s in ln["spans"]) for ln in b["lines"]) for b in blocks]
    return [t for t in texts if marker not in t]


class LocalClient:
    """A test client that behaves like the browser: local host, the editor's header,
    and the current revision sent with every edit."""

    def __init__(self, app) -> None:
        from fastapi.testclient import TestClient

        self._client = TestClient(app, base_url="http://localhost", headers={"X-Pdfe": "1"})

    def post(self, path, headers=None, **kwargs):
        headers = dict(headers or {})
        if path.startswith("/api/files/") and "X-Base-Revision" not in headers:
            file_id = path.split("/")[3]
            latest = self._client.get(f"/api/files/{file_id}/revisions").json()["latest"]
            headers["X-Base-Revision"] = str(latest)
        return self._client.post(path, headers=headers, **kwargs)

    def __getattr__(self, name):
        return getattr(self._client, name)
