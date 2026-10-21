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
