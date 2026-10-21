import pymupdf

_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_GIF = (b"GIF87a", b"GIF89a")
_WPG = b"\xffWPC"


def normalize_picture(data: bytes) -> bytes:
    """Return picture bytes that PDF can embed: PNG, JPEG, and GIF as they are, WordPerfect as PNG."""
    if data.startswith((_PNG, _JPEG)) or data.startswith(_GIF):
        _check_decodes(data)
        return data
    if data.startswith(_WPG):
        return _wpg_to_png(data)
    raise ValueError("unsupported picture; use PNG, GIF, JPEG, or WordPerfect graphics")


def _check_decodes(data: bytes) -> None:
    try:
        pymupdf.Pixmap(data)
    except Exception as exc:
        raise ValueError("the picture could not be decoded") from exc


def _wpg_to_png(data: bytes) -> bytes:
    # Wand needs the ImageMagick library installed on the system, so it is imported only when needed.
    try:
        from wand.image import Image as WandImage
    except ImportError as exc:
        raise ValueError("WordPerfect pictures need ImageMagick installed on this machine") from exc
    try:
        with WandImage(blob=data) as image:
            image.format = "png"
            return image.make_blob()
    except Exception as exc:
        raise ValueError("the WordPerfect picture could not be read") from exc
