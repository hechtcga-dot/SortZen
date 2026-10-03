"""Asking an AI service about labels: first a label list for users to edit, then labels for a sample of
files (SortZen labels the rest on the PC from them), and later only the files SortZen still can't settle.

Only what the privacy settings allow is sent: file names (long numbers removed), the folder each file
is in, and the beginning of a file when users chose that. Every reply's cost is counted.
"""
from __future__ import annotations

from .costs import cost, tokens
from .parsing import extract_json

LIST_NAMES = 200            # file names sent when asking for a label list
LIST_FOLDERS = 60
MAX_LABELS = 20
BATCH = 40
REPLY_TOKENS_LIST = 600
REPLY_TOKENS_PER_FILE = 20


def list_request(names: list[str], folders: list[str], labels: list[str]) -> str:
    lines = ["Suggest labels for one person's files: short words or phrases that describe what files are about "
             "or are for, such as Work, Taxes, School, Photo session, Receipts, House. A file can have several "
             f"labels. Suggest at most {MAX_LABELS}, the most useful first; prefer what the files are about over "
             "what type of file they are (never 'PDF' or 'Subtitles')."]
    if labels:
        lines.append("They already use these labels; keep them and add what is missing: " + ", ".join(labels))
    lines.append("\nTheir folders:")
    lines += [f"- {f}" for f in folders[:LIST_FOLDERS]]
    lines.append("\nSome of their file names:")
    lines += [f"- {n}" for n in names[:LIST_NAMES]]
    lines.append('\nReply with JSON only: {"labels": [{"name": "Taxes", "why": "a short reason"}]}')
    return "\n".join(lines)


def parse_list(text: str) -> list[tuple[str, str]]:
    try:
        data = extract_json(text)
    except ValueError:
        return []
    found, seen = [], set()
    for item in (data.get("labels") if isinstance(data, dict) else None) or []:
        name = " ".join(str(item.get("name") if isinstance(item, dict) else item or "").split())[:40]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            found.append((name, str(item.get("why") or "")[:160] if isinstance(item, dict) else ""))
    return found[:MAX_LABELS]


def label_request(labels: list[str], files: list[dict]) -> str:
    """``files``: {"name", "folder", "text"} as privacy settings allow."""
    lines = ["Give each file the labels that fit it, from this list only: " + ", ".join(labels) + ". A file can "
             "have several labels, or none if nothing fits. Say how sure you are of each (0-100).", "", "Files:"]
    for n, f in enumerate(files, start=1):
        line = f"{n}: {f['name']} (in {f['folder']})"
        if f.get("text"):
            line += f" | begins: {f['text']}"
        lines.append(line)
    lines.append('\nReply with JSON only: {"files": [{"n": 1, "labels": [{"label": "Taxes", "sure": 85}]}]}')
    return "\n".join(lines)


def parse_labels(text: str, labels: list[str], count: int) -> dict[int, list[tuple[str, int]]]:
    """Labels by file number (1-based), only from the list."""
    try:
        data = extract_json(text)
    except ValueError:
        return {}
    known = {x.lower(): x for x in labels}
    found = {}
    for item in (data.get("files") if isinstance(data, dict) else None) or []:
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= count:
            continue
        given = []
        for x in item.get("labels") or []:
            name = known.get(str(x.get("label") if isinstance(x, dict) else x).strip().lower())
            if name is None:
                continue
            try:
                sure = max(0, min(100, int(x.get("sure", 70) if isinstance(x, dict) else 70)))
            except (TypeError, ValueError):
                sure = 70
            given.append((name, sure))
        found[n] = given
    return found


def list_cost(service_key: str, names: list[str], folders: list[str], labels: list[str]) -> float:
    return cost(service_key, tokens(list_request(names, folders, labels)), REPLY_TOKENS_LIST)


def label_cost(service_key: str, labels: list[str], files: list[dict]) -> float:
    total = 0.0
    for start in range(0, len(files), BATCH):
        batch = files[start:start + BATCH]
        total += cost(service_key, tokens(label_request(labels, batch)), REPLY_TOKENS_PER_FILE * len(batch))
    return total
