"""Reading text in scans and pictures of documents with the text recognition built into Windows.

Everything happens on the PC: a scanned PDF's first page is drawn as a picture (pypdfium2) and
read by Windows (Windows.Media.Ocr, in Windows 10 and 11). Camera photos are not read. When
Windows text recognition isn't available, files are sorted by name and details as before.
"""
from __future__ import annotations

import io
import logging
import sys
import threading
from pathlib import Path

log = logging.getLogger("sortzen")

OCR_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
MIN_IMAGE_BYTES = 10 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_SIDE = 2500                 # pixels; bigger pictures are shrunk first
PDF_SCALE = 2.0                 # a scanned page drawn at 144 dots per inch


def wants_ocr(ext: str, kind: str, size: int, details: dict) -> bool:
    """A scanned PDF (no text), or a picture that isn't a camera photo, such as a screenshot or a scan."""
    if ext == ".pdf":
        return bool(details.get("no_text")) and not details.get("encrypted")
    return (kind == "image" and ext in OCR_IMAGE_EXTS and MIN_IMAGE_BYTES <= size <= MAX_IMAGE_BYTES
            and "camera" not in details)


def picture_of(path: Path, ext: str) -> bytes:
    """The file as a PNG picture: a PDF's first page, or the picture itself, shrunk to MAX_SIDE."""
    from PIL import Image

    if ext == ".pdf":
        import pypdfium2

        document = pypdfium2.PdfDocument(str(path))
        try:
            image = document[0].render(scale=PDF_SCALE).to_pil()
        finally:
            document.close()
    else:
        with Image.open(path) as original:
            image = original.convert("RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.convert("RGB").save(out, "PNG")
    return out.getvalue()


class WindowsRecognizer:
    """Windows text recognition in the languages of the Windows user."""

    def __init__(self):
        from winrt.windows.media.ocr import OcrEngine

        self.engine = OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:
            raise RuntimeError("Windows has no text recognition language installed")
        self.lock = threading.Lock()

    def read(self, png: bytes) -> str:
        import asyncio

        with self.lock:
            return asyncio.run(self._read(png))

    async def _read(self, png: bytes) -> str:
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapDecoder, BitmapPixelFormat
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(png)
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_alpha_mode_async(BitmapPixelFormat.BGRA8,
                                                                    BitmapAlphaMode.PREMULTIPLIED) \
            if hasattr(decoder, "get_software_bitmap_alpha_mode_async") \
            else await decoder.get_software_bitmap_async(BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
        result = await self.engine.recognize_async(bitmap)
        return result.text or ""


_recognizer = None
_why_not = ""


def recognizer():
    """Windows text recognition, made once; None (with why_unavailable()) when it can't be used."""
    global _recognizer, _why_not
    if _recognizer is None and not _why_not:
        if not sys.platform.startswith("win"):
            _why_not = "Text recognition needs Windows 10 or 11"
        else:
            try:
                _recognizer = WindowsRecognizer()
            except Exception as exc:      # missing Windows parts or languages: sort by name instead
                _why_not = f"Windows text recognition isn't available ({exc})"
                log.warning(_why_not)
    return _recognizer


def why_unavailable() -> str:
    recognizer()
    return _why_not


def read_text(recognizer_, path: Path, ext: str) -> str:
    """The text Windows reads in a scan or picture ("" when there is none)."""
    return recognizer_.read(picture_of(path, ext))
