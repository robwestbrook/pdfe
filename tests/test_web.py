from pdf_helpers import LocalClient

from pdfe.api import create_app


def test_root_serves_editor(storage):
    r = LocalClient(create_app(storage)).get("/")
    assert r.status_code == 200
    assert "page-strip" in r.text and "tool-panel" in r.text


def test_static_script_is_served(storage):
    r = LocalClient(create_app(storage)).get("/static/app.js")
    assert r.status_code == 200


def test_font_check_reports_fallback(storage):
    client = LocalClient(create_app(storage))
    r = client.get("/api/fonts/check", params={"font": "NoSuchFont", "text": "Hello"})
    assert r.json() == {"fontname": "helv", "fallback": True}


def test_pdfjs_is_served_locally(storage):
    client = LocalClient(create_app(storage))
    assert client.get("/static/vendor/pdfjs/pdf.min.mjs").status_code == 200
    assert client.get("/static/vendor/pdfjs/pdf.worker.min.mjs").status_code == 200


def test_editor_has_no_external_script_dependencies(storage):
    from pathlib import Path

    web = Path(__file__).parent.parent / "src" / "pdfe" / "web"
    sources = [p.read_text() for p in web.glob("*.html")] + [p.read_text() for p in web.glob("*.js")]
    assert not any("http://" in s or "https://" in s for s in sources)


def test_page_has_favicon_so_browsers_do_not_request_one(storage):
    r = LocalClient(create_app(storage)).get("/")
    assert 'rel="icon"' in r.text


def test_editor_offers_page_rotate_and_delete(storage):
    r = LocalClient(create_app(storage)).get("/")
    assert 'id="rotate-left"' in r.text
    assert 'id="rotate-right"' in r.text
    assert 'id="delete-page"' in r.text


def test_editor_has_undo_and_history(storage):
    # Fix 4: undo and history are in the UI
    r = LocalClient(create_app(storage)).get("/")
    assert 'id="undo"' in r.text
    assert 'id="history-list"' in r.text
