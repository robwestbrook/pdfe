import pymupdf
import pytest

from pdfe.db import make_engine
from pdfe.storage import Storage


def _make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    return _make_pdf("hello world")


@pytest.fixture
def encrypted_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    doc.close()
    return data


@pytest.fixture
def storage(tmp_path) -> Storage:
    root = tmp_path / "data"
    root.mkdir()
    return Storage(root, make_engine(f"sqlite:///{root / 'pdfe.db'}"))


@pytest.fixture
def three_page_pdf() -> bytes:
    doc = pymupdf.open()
    for i in range(1, 4):
        doc.new_page().insert_text((72, 72), f"page {i}")
    data = doc.tobytes()
    doc.close()
    return data



@pytest.fixture
def png_bytes() -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (40, 20), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _pdf_with_image(png: bytes, rotation: int = 0) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(72, 100, 172, 150), stream=png)
    page.set_rotation(rotation)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def pdf_with_image(png_bytes) -> bytes:
    return _pdf_with_image(png_bytes)


@pytest.fixture
def pdf_with_image_rotated_90(png_bytes) -> bytes:
    return _pdf_with_image(png_bytes, rotation=90)
