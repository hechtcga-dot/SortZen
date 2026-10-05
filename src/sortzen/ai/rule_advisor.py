"""Asking an AI service which rules to make (or drop) from a summary of an organizing session: where users
sent files and folders, the folders they made, what they deleted, the labels each folder holds and the
rules they have. Only names are sent (long numbers removed, as the privacy settings allow), never contents.
"""
from __future__ import annotations

from .costs import cost, tokens
from .parsing import extract_json

MAX_CHOICES = 150           # users' choices listed
MAX_FOLDERS = 120
MAX_DELETED = 60
MAX_RULES = 12              # rules the AI may suggest
REPLY_TOKENS = 900
KINDS = ("pdf", "word", "spreadsheet", "presentation", "image", "video", "audio", "archive", "installer", "text",
         "email", "web page", "ebook", "form")


def request(summary: dict) -> str:
    lines = ["You help one person keep their files tidy with rules. A rule sends every file that meets all of its "
             "conditions to one folder. Conditions: a label the file has, text its name contains, a kind of file "
             f"({', '.join(KINDS)}) or an ending such as .msi. A rule whose name condition fits a folder's name also "
             "moves that whole folder. Optionally files go into a folder for each year or month inside it.",
             "From what they did in this session, suggest rules that would place similar files the same way next "
             f"time (at most {MAX_RULES}, the most useful first), only when the pattern is clear. Never a rule for "
             "a kind of file alone unless every such file went to one folder. Also point out existing rules that "
             "look wrong for what they did."]
    lines.append("\nWhere they sent files and folders (name -> folder):")
    lines += [f"- {name} -> {folder}" for name, folder in summary.get("choices", [])[:MAX_CHOICES]]
    if summary.get("new_folders"):
        lines.append("\nFolders they made:")
        lines += [f"- {f}" for f in summary["new_folders"][:MAX_FOLDERS]]
    if summary.get("deleted"):
        lines.append("\nFiles they deleted:")
        lines += [f"- {n}" for n in summary["deleted"][:MAX_DELETED]]
    if summary.get("labels"):
        lines.append("\nLabels most files in a folder have:")
        lines += [f"- {folder}: {', '.join(labels)}" for folder, labels in summary["labels"][:MAX_FOLDERS]]
    lines.append("\nTheir folders:")
    lines += [f"- {f}" for f in summary.get("folders", [])[:MAX_FOLDERS]]
    if summary.get("rules"):
        lines.append("\nTheir rules now (by number):")
        lines += [f"{i}. {text}" for i, text in enumerate(summary["rules"], start=1)]
    lines.append('\nReply with JSON only: {"rules": [{"name": "Tax slips", "label": "", "contains": "T4", '
                 '"kind": "pdf", "ending": "", "folder": "Sorted/Documents/Taxes", "by": "year or month or empty", '
                 '"why": "a short reason"}], "doubts": [{"rule": 2, "why": "a short reason"}]}. Use the folder '
                 "names exactly as listed (a new one inside a listed folder is fine), and labels only from the "
                 "labels listed.")
    return "\n".join(lines)


def parse(text: str) -> tuple[list[dict], list[tuple[int, str]]]:
    """The suggested rules (as dictionaries of conditions) and the existing rules the AI doubts (number, why)."""
    try:
        data = extract_json(text)
    except ValueError:
        return [], []
    if not isinstance(data, dict):
        return [], []
    rules = []
    for item in data.get("rules") or []:
        if not isinstance(item, dict):
            continue
        clean = {k: " ".join(str(item.get(k) or "").split())[:120] for k in
                 ("name", "label", "contains", "kind", "ending", "folder", "by", "why")}
        if clean["kind"] not in KINDS:
            clean["kind"] = ""
        if clean["by"] not in ("year", "month"):
            clean["by"] = ""
        if clean["folder"] and (clean["label"] or clean["contains"] or clean["kind"] or clean["ending"]):
            rules.append(clean)
    doubts = []
    for item in data.get("doubts") or []:
        try:
            doubts.append((int(item.get("rule")), str(item.get("why") or "")[:160]))
        except (TypeError, ValueError, AttributeError):
            continue
    return rules[:MAX_RULES], doubts


def estimate(service_key: str, summary: dict) -> float:
    return cost(service_key, tokens(request(summary)), REPLY_TOKENS)
