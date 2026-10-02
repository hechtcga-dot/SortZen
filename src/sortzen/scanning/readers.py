"""Read details and text from files, on the PC only.

``read_contents`` returns ``(details, text)``. Details are small facts (title, author,
camera, archive file names); text is the readable words, capped at ``MAX_TEXT_CHARS``.
Office files (.docx, .xlsx, .pptx) are zip files of XML and are read with the standard
library. Damaged files raise an exception, which the scanner records.
"""
from __future__ import annotations

import logging
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

logging.getLogger("pypdf").setLevel(logging.ERROR)     # damaged PDFs are recorded, not printed

MAX_TEXT_CHARS = 20_000
MAX_CONTENT_BYTES = 50 * 1024 * 1024     # bigger files are sorted by name and details only
MAX_PDF_PAGES = 10
MAX_TEXT_FILE_BYTES = 256 * 1024
MAX_ARCHIVE_NAMES = 50

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_CORE = {
    "title": "{http://purl.org/dc/elements/1.1/}title",
    "author": "{http://purl.org/dc/elements/1.1/}creator",
    "subject": "{http://purl.org/dc/elements/1.1/}subject",
    "keywords": "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}keywords",
}
_EXIF_MAKE, _EXIF_MODEL, _EXIF_DATETIME, _EXIF_IFD, _EXIF_TAKEN = 0x010F, 0x0110, 0x0132, 0x8769, 0x9003


def read_contents(path: Path, kind: str, ext: str, size: int) -> tuple[dict, str]:
    ext = ext.lower()
    if size > MAX_CONTENT_BYTES and kind not in ("image", "archive", "installer"):
        return {}, ""
    if ext == ".docx":
        return _docx(path)
    if ext == ".xlsx" or ext == ".xlsm":
        return _xlsx(path)
    if ext == ".pptx":
        return _pptx(path)
    if ext == ".pdf":
        return _pdf(path)
    if kind == "text" or ext == ".csv":
        return {}, _text_file(path)
    if kind == "image":
        return _image(path), ""
    if ext == ".zip":
        return _zip(path), ""
    if ext == ".exe":
        return _exe(path), ""
    return {}, ""


def _cap(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:MAX_TEXT_CHARS]


def _core_properties(archive: zipfile.ZipFile) -> dict:
    try:
        root = ElementTree.fromstring(archive.read("docProps/core.xml"))
    except KeyError:
        return {}
    details = {}
    for name, tag in _CORE.items():
        node = root.find(tag)
        if node is not None and (node.text or "").strip():
            details[name] = node.text.strip()
    return details


def _docx(path: Path) -> tuple[dict, str]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        paragraphs = ["".join(t.text or "" for t in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p")]
        return _core_properties(archive), _cap("\n".join(paragraphs))


def _xlsx(path: Path) -> tuple[dict, str]:
    with zipfile.ZipFile(path) as archive:
        words = []
        try:
            shared = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            words += ["".join(t.text or "" for t in si.iter(f"{_S}t")) for si in shared.iter(f"{_S}si")]
        except KeyError:
            pass
        sheets = sorted(n for n in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        for name in sheets[:5]:
            sheet = ElementTree.fromstring(archive.read(name))
            words += [t.text or "" for t in sheet.iter(f"{_S}t")]          # inline strings
        details = _core_properties(archive)
        details["sheets"] = len(sheets)
        return details, _cap("\n".join(w for w in words if w.strip()))


def _pptx(path: Path) -> tuple[dict, str]:
    with zipfile.ZipFile(path) as archive:
        slides = sorted((n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        lines = []
        for name in slides:
            root = ElementTree.fromstring(archive.read(name))
            lines += [t.text or "" for t in root.iter(f"{_A}t")]
        details = _core_properties(archive)
        details["slides"] = len(slides)
        return details, _cap("\n".join(lines))


def _pdf(path: Path) -> tuple[dict, str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        return {"encrypted": True}, ""
    details = {"pages": len(reader.pages)}
    meta = reader.metadata or {}
    for name, key in (("title", "/Title"), ("author", "/Author"), ("subject", "/Subject")):
        value = str(meta.get(key) or "").strip()
        if value:
            details[name] = value
    text = "\n".join((page.extract_text() or "") for page in reader.pages[:MAX_PDF_PAGES])
    if not text.strip():
        details["no_text"] = True                       # a scan: needs OCR to read
    return details, _cap(text)


def _text_file(path: Path) -> str:
    with path.open("rb") as f:
        raw = f.read(MAX_TEXT_FILE_BYTES)
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", "replace")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", "replace")
    return _cap(text)


def _image(path: Path) -> dict:
    from PIL import Image

    with Image.open(path) as image:
        details = {"width": image.width, "height": image.height}
        exif = image.getexif()
        make, model = str(exif.get(_EXIF_MAKE) or "").strip(), str(exif.get(_EXIF_MODEL) or "").strip()
        taken = str(exif.get_ifd(_EXIF_IFD).get(_EXIF_TAKEN) or exif.get(_EXIF_DATETIME) or "").strip()
    if make or model:
        details["camera"] = " ".join(p for p in (make, model) if p)
    if taken:
        details["taken"] = taken
    return details


def _zip(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
    return {"files": len(names), "names": names[:MAX_ARCHIVE_NAMES]}


def _exe(path: Path) -> dict:
    """Product and company from a program's version information (Windows only)."""
    if not sys.platform.startswith("win"):
        return {}
    import ctypes
    from ctypes import wintypes

    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return {}
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return {}
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(buffer, r"\VarFileInfo\Translation", ctypes.byref(pointer), ctypes.byref(length)) \
            or length.value < 4:
        return {}
    language, codepage = ctypes.cast(pointer, ctypes.POINTER(wintypes.WORD * 2)).contents
    details = {}
    for name, key in (("product", "ProductName"), ("company", "CompanyName"), ("description", "FileDescription")):
        query = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{key}"
        if version.VerQueryValueW(buffer, query, ctypes.byref(pointer), ctypes.byref(length)) and length.value:
            value = ctypes.wstring_at(pointer, length.value).rstrip("\x00").strip()
            if value:
                details[name] = value
    return details
