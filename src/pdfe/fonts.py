from dataclasses import dataclass
from pathlib import Path

import pymupdf

BUNDLED_FONT = Path(__file__).parent / "fonts" / "NotoSans-Regular.ttf"
_BASE14 = {name.lower(): name for name in pymupdf.Base14_fontnames}
_LATIN1_LIMIT = 0xFF


@dataclass(frozen=True)
class FontChoice:
    fontname: str
    fontfile: str | None
    fallback: bool


def resolve_font(font_name: str, text: str) -> FontChoice:
    """Pick the font for new text, and say whether it differs from the named font.

    A named standard font is used when the text stays within Latin-1. Other text
    needs the bundled Noto Sans, which covers Latin Extended and Cyrillic.
    """
    named = _BASE14.get(font_name.lower())
    if named and all(ord(c) <= _LATIN1_LIMIT for c in text):
        return FontChoice(fontname=named, fontfile=None, fallback=False)
    if any(ord(c) > _LATIN1_LIMIT for c in text):
        return FontChoice(fontname="notos", fontfile=str(BUNDLED_FONT), fallback=True)
    return FontChoice(fontname="helv", fontfile=None, fallback=True)
