def test_main_binds_to_localhost(monkeypatch):
    import pdfe.__main__ as entry

    calls = {}
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **kw: calls.update(kw))
    entry.main()
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8000
