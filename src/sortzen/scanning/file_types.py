"""File kinds by extension, and the files the scanner never sorts."""
from __future__ import annotations

KINDS = {
    "word": {".docx", ".doc", ".odt", ".rtf", ".gdoc"},
    "pdf": {".pdf"},
    "spreadsheet": {".xlsx", ".xls", ".xlsm", ".ods", ".csv", ".gsheet"},
    "presentation": {".pptx", ".ppt", ".odp", ".gslides"},
    "form": {".gform"},
    "text": {".txt", ".md", ".log", ".json", ".xml", ".ini", ".cfg"},
    "image": {".jpg", ".jpeg", ".jfif", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif", ".svg"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".webm"},
    "audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"},
    "archive": {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"},
    "installer": {".exe", ".msi", ".msix", ".appx"},
    "ebook": {".epub", ".mobi"},
    "web page": {".html", ".htm", ".mhtml"},
    "email": {".eml", ".msg"},
    "shortcut": {".lnk", ".url"},
}
_BY_EXT = {ext: kind for kind, exts in KINDS.items() for ext in exts}

# Google Drive for desktop writes these small link files; the document itself stays online.
GOOGLE_LINKS = {".gdoc": "Google Docs", ".gsheet": "Google Sheets", ".gslides": "Google Slides",
                ".gform": "Google Forms"}

# Never sorted: Windows housekeeping files, Office lock files and downloads still in progress.
IGNORED_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}
IGNORED_PREFIXES = ("~$",)
TEMPORARY_EXTS = {".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload"}
SKIPPED_FOLDER_NAMES = {"$recycle.bin", "system volume information"}
QUEUE_FOLDER = "Queued for deletion"        # dated folders of copies waiting to be deleted; never read or sorted


def is_queue_folder(name: str) -> bool:
    return name.lower().startswith(QUEUE_FOLDER.lower())


def kind_of(ext: str) -> str:
    return _BY_EXT.get(ext.lower(), "other")


def skip_reason(name: str, ext: str) -> str:
    """Why a file is never sorted, or "" when it is sortable."""
    lower = name.lower()
    if lower in IGNORED_NAMES:
        return "system"
    if lower.startswith(IGNORED_PREFIXES) or ext.lower() in TEMPORARY_EXTS:
        return "temporary"
    return ""
