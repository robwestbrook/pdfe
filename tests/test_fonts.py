import pymupdf

from pdfe.fonts import resolve_font


def test_named_base14_font_used():
    choice = resolve_font("Helvetica", "Hello")
    assert choice.fallback is False
    assert choice.fontname == "Helvetica"


def test_unknown_font_falls_back_and_says_so():
    choice = resolve_font("NoSuchFont", "Hello")
    assert choice.fallback is True


def test_fallback_covers_accents_and_non_latin():
    # Review Focus 3: characters must render, not come out as empty boxes
    choice = resolve_font("NoSuchFont", "café Привет")
    font = pymupdf.Font(fontfile=choice.fontfile)
    assert all(font.has_glyph(ord(c)) for c in "café Привет" if not c.isspace())
