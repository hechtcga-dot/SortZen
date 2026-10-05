"""Read details and text from files, on the PC only.

``read_contents`` returns ``(details, text)``. Details are small facts (title, author,
camera, archive file names); text is the readable words, capped at ``MAX_TEXT_CHARS``.
Office files (.docx, .xlsx, .pptx) and OpenDocument files (.odt, .ods, .odp) are zip files
of XML, read with the standard library; older Office files (.doc, .xls, .ppt) and Outlook
emails (.msg) with olefile; .eml emails with the standard library. Damaged files raise an
exception, which the scanner records.
"""
from __future__ import annotations

import logging
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .file_types import GOOGLE_LINKS
from .ocr import read_text, wants_ocr

logging.getLogger("pypdf").setLevel(logging.ERROR)     # damaged PDFs are recorded, not printed

READER_VERSION = 2          # remembered files of the kinds below, read by an older version, are read again
REREAD_EXTS = {".doc", ".xls", ".ppt", ".msg", ".eml", ".rtf", ".odt", ".ods", ".odp", ".html", ".htm"}
MAX_TEXT_CHARS = 20_000
MAX_CONTENT_BYTES = 50 * 1024 * 1024     # bigger files are sorted by name and details only
MAX_PDF_PAGES = 2
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


def read_contents(path: Path, kind: str, ext: str, size: int, ocr=None) -> tuple[dict, str]:
    """Details and text. ``ocr`` (a text recognizer) reads scans and pictures of documents."""
    details, text = _read_contents(path, kind, ext.lower(), size)
    if ocr is not None and wants_ocr(ext.lower(), kind, size, details):
        details["ocr_tried"] = True
        try:
            found = read_text(ocr, path, ext.lower())
        except Exception as exc:          # an unusual picture: sorted by name and details
            details["ocr_error"] = f"{type(exc).__name__}: {exc}"[:200]
            found = ""
        if found.strip():
            details["ocr"] = True
            text = _cap(f"{text}\n{found}" if text else found)
    return details, text


def _read_contents(path: Path, kind: str, ext: str, size: int) -> tuple[dict, str]:
    if size > MAX_CONTENT_BYTES and kind not in ("image", "archive", "installer"):
        return {}, ""
    if ext in GOOGLE_LINKS:
        return {"google": GOOGLE_LINKS[ext]}, ""
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
    if ext in (".odt", ".ods", ".odp"):
        return _odf(path)
    if ext == ".rtf":
        return {}, _rtf(path)
    if ext in OLE_STREAMS:
        return _ole(path, OLE_STREAMS[ext])
    if ext == ".msg":
        return _msg(path)
    if ext == ".eml":
        return _eml(path)
    if kind == "web page" and ext != ".mhtml":
        return {}, _html(_text_file(path))
    if kind == "image":
        return _image(path), ""
    if ext == ".zip":
        return _zip(path), ""
    if ext == ".exe":
        return _exe(path), ""
    return {}, ""


def needs_reread(record, ocr: bool = False) -> bool:
    """A remembered file this version reads better than the version that read it, or a scan or picture
    of a document not yet read with text recognition (when ``ocr`` is available)."""
    if record.details.get("names_only") or record.cloud_only:
        return False
    if record.ext in REREAD_EXTS and record.details.get("reader", 1) < READER_VERSION:
        return True
    return ocr and not record.details.get("ocr_tried") and wants_ocr(record.ext, record.kind, record.size,
                                                                     record.details)


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


_ODF_META = {"title": "{http://purl.org/dc/elements/1.1/}title",
             "author": "{http://purl.org/dc/elements/1.1/}creator"}
OLE_STREAMS = {".doc": "WordDocument", ".xls": "Workbook", ".ppt": "PowerPoint Document"}
_UTF16_RUN = re.compile(rb"(?:[\x20-\x7e\xa0-\xff]\x00){4,}")
_BYTE_RUN = re.compile(rb"[\x20-\x7e\xa0-\xff]{4,}")


def _odf(path: Path) -> tuple[dict, str]:
    details = {}
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "meta.xml" in names:
            root = ElementTree.fromstring(archive.read("meta.xml"))
            for name, tag in _ODF_META.items():
                found = root.find(f".//{tag}")
                if found is not None and (found.text or "").strip():
                    details[name] = found.text.strip()
        text = " ".join(ElementTree.fromstring(archive.read("content.xml")).itertext()) \
            if "content.xml" in names else ""
    return details, _cap(text)


def _rtf(path: Path) -> str:
    """RTF without its formatting: control words, groups like fonts and pictures, and escapes removed."""
    with path.open("rb") as f:
        raw = f.read(MAX_TEXT_FILE_BYTES).decode("latin-1", "replace")
    raw = re.sub(r"\{\\\*[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", " ", raw)
    raw = re.sub(r"\{\\(?:fonttbl|colortbl|stylesheet|info|pict)[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", " ", raw)
    raw = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "replace"), raw)
    raw = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), raw)
    raw = re.sub(r"\\(?:par|line|tab)\b", " ", raw)
    raw = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", raw)
    return _cap(raw.replace("{", "").replace("}", "").replace("\\", ""))


def ole_strings(data: bytes) -> str:
    """Readable text in an older Office file's binary stream: runs of UTF-16 or single-byte letters."""
    wide = " ".join(m.group(0).decode("utf-16-le", "replace") for m in _UTF16_RUN.finditer(data))
    narrow = " ".join(m.group(0).decode("cp1252", "replace") for m in _BYTE_RUN.finditer(data))

    def letters(text: str) -> int:
        return sum(1 for c in text if c.isalpha())

    best = wide if letters(wide) >= letters(narrow) else narrow
    return " ".join(w for w in best.split() if sum(c.isalpha() for c in w) >= max(1, len(w) // 2))


def _ole(path: Path, stream: str) -> tuple[dict, str]:
    import olefile

    with olefile.OleFileIO(str(path)) as ole:
        details = {}
        meta = ole.get_metadata()
        for name, value in (("title", meta.title), ("author", meta.author), ("subject", meta.subject)):
            if value:
                value = value.decode("cp1252", "replace") if isinstance(value, bytes) else str(value)
                if value.strip():
                    details[name] = value.strip()
        text = ole_strings(ole.openstream(stream).read(4 * MAX_TEXT_FILE_BYTES)) if ole.exists(stream) else ""
    return details, _cap(text)


def _msg_text(ole, prop: str) -> str:
    for suffix, encoding in (("001F", "utf-16-le"), ("001E", "cp1252")):
        name = f"__substg1.0_{prop}{suffix}"
        if ole.exists(name):
            return ole.openstream(name).read(MAX_TEXT_FILE_BYTES).decode(encoding, "replace").rstrip("\x00").strip()
    return ""


def _msg(path: Path) -> tuple[dict, str]:
    """An Outlook email: subject, sender's name and the beginning of the message."""
    import olefile

    with olefile.OleFileIO(str(path)) as ole:
        subject, sender, body = _msg_text(ole, "0037"), _msg_text(ole, "0C1A"), _msg_text(ole, "1000")
    details = {k: v for k, v in (("title", subject), ("author", sender)) if v}
    return details, _cap(f"{subject}\n{body}")


def _eml(path: Path) -> tuple[dict, str]:
    from email import policy
    from email.parser import BytesParser
    from email.utils import parseaddr

    with path.open("rb") as f:
        message = BytesParser(policy=policy.default).parse(f)
    subject = str(message.get("subject") or "").strip()
    sender = parseaddr(str(message.get("from") or ""))[0].strip()
    part = message.get_body(preferencelist=("plain", "html"))
    body = ""
    if part is not None:
        body = part.get_content()
        if part.get_content_type() == "text/html":
            body = _html(body)
    details = {k: v for k, v in (("title", subject), ("author", sender)) if v}
    return details, _cap(f"{subject}\n{body}")


def _html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        text = text.replace(entity, char)
    return _cap(text)


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
