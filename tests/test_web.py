from fastapi.testclient import TestClient

from pdfe.api import create_app


def test_root_serves_editor(storage):
    r = TestClient(create_app(storage)).get("/")
    assert r.status_code == 200
    assert "page-strip" in r.text and "tool-panel" in r.text


def test_static_script_is_served(storage):
    r = TestClient(create_app(storage)).get("/static/app.js")
    assert r.status_code == 200


def test_font_check_reports_fallback(storage):
    client = TestClient(create_app(storage))
    r = client.get("/api/fonts/check", params={"font": "NoSuchFont", "text": "Hello"})
    assert r.json() == {"fontname": "helv", "fallback": True}


def test_pdfjs_is_served_locally(storage):
    client = TestClient(create_app(storage))
    assert client.get("/static/vendor/pdfjs/pdf.min.mjs").status_code == 200
    assert client.get("/static/vendor/pdfjs/pdf.worker.min.mjs").status_code == 200


def test_editor_has_no_external_script_dependencies(storage):
    from pathlib import Path

    web = Path(__file__).parent.parent / "src" / "pdfe" / "web"
    sources = [p.read_text() for p in web.glob("*.html")] + [p.read_text() for p in web.glob("*.js")]
    assert not any("http://" in s or "https://" in s for s in sources)
