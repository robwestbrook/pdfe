"""End-to-end checks in a real browser. They run when a Chromium is available:
set PDFE_CHROME to its path, or install one with `playwright install chromium`."""

import os
import socket
import threading
import time

import pymupdf
import pytest
import uvicorn

from pdfe.api import create_app


@pytest.fixture
def server(storage):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(create_app(storage), host="127.0.0.1", port=port, log_level="warning")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    for _ in range(100):
        if running.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch(executable_path=os.environ.get("PDFE_CHROME") or None)
        except sync_api.Error as exc:  # no browser installed on this machine
            pytest.skip(f"no Chromium available: {exc.__class__.__name__}")
        yield launched
        launched.close()


def _sample_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "first page text")
    doc.new_page().insert_text((72, 72), "second page text")
    data = doc.tobytes()
    doc.close()
    return data


def test_editor_upload_edit_and_undo(server, browser, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(_sample_pdf())
    page = browser.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server + "/")
    page.set_input_files("#open-file", str(pdf_path))
    page.wait_for_function("document.querySelectorAll('#page-strip .thumb').length === 2")
    page.wait_for_function("document.querySelector('#revision').textContent === 'revision 1'")

    page.locator("#rotate-right").click()
    page.wait_for_function("document.querySelector('#revision').textContent === 'revision 2'")
    assert page.locator("#page-strip .thumb img").count() == 2

    page.locator("#undo").click()
    page.wait_for_function("document.querySelector('#revision').textContent === 'revision 3'")
    assert page.locator("#undo").is_disabled() is False
    assert errors == []
