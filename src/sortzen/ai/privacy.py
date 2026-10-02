"""What may leave the PC: scrubbing text, name-only folders and words, image previews."""
from __future__ import annotations

import io
import os
import re

NAME_ONLY, BEGINNING = "name", "beginning"
WORDS_SENT = 400                    # "the beginning of the file": this many words at most
DEFAULT_NAME_ONLY_WORDS = ["tax", "bank", "passport", "medical", "password"]

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_LONG_NUMBER = re.compile(r"(?<![\w])(\d[\d \-./]{5,}\d)(?![\w])")        # card, account, phone numbers
_NUMBER = re.compile(r"(?<![\w])\d{3,}(?![\w])")
_YEAR = re.compile(r"^(19|20)\d\d$")
_NAME_NUMBER = re.compile(r"\d{7,}")


def scrub(text: str) -> str:
    """Email addresses and numbers removed (years kept), so account and card numbers never leave the PC."""
    text = _EMAIL.sub("[email]", text)
    text = _LONG_NUMBER.sub("[number]", text)
    return _NUMBER.sub(lambda m: m.group(0) if _YEAR.match(m.group(0)) else "[number]", text)


def scrub_name(name: str) -> str:
    """File names keep their words; only very long numbers (accounts, cards, phones) are removed."""
    return _NAME_NUMBER.sub("#", _EMAIL.sub("[email]", name))


def beginning(text: str, words: int = WORDS_SENT) -> str:
    return scrub(" ".join(text.split()[:words]))


def name_only(path: str, folders: list[str], words: list[str]) -> bool:
    """True when only the name of this file may be sent: it is in a name-only folder or mentions a listed word."""
    key = os.path.normcase(os.path.abspath(path))
    for folder in folders:
        f = os.path.normcase(os.path.abspath(folder)).rstrip(os.sep)
        if key == f or key.startswith(f + os.sep):
            return True
    lowered = path.lower()
    return any(w.strip() and w.strip().lower() in lowered for w in words)


def image_preview(path: str, size: int = 256) -> bytes | None:
    """A small JPEG of a picture, or None when it can't be made."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((size, size))
            out = io.BytesIO()
            image.convert("RGB").save(out, "JPEG", quality=70)
            return out.getvalue()
    except Exception:           # damaged or unusual pictures are sorted by name instead
        return None
