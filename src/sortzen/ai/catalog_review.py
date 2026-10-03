"""Asking an AI service to review the catalog: names, counts, notes, a few example names and users'
feedback are sent (never file contents); its suggestions come back for users to accept or turn down."""
from __future__ import annotations

import os

from ..engine.catalog_review import CatalogSuggestion
from ..engine.features import stem_of, words
from .costs import cost, tokens
from .parsing import extract_json
from .privacy import scrub_name

EXAMPLES = 4
MAX_CATEGORIES = 250
REPLY_TOKENS = 1500


def request(categories: list, display) -> str:
    lines = ["Review how one person's files are organised. Below is their catalog of categories (folders), "
             "with file counts, their own notes about what belongs in a category, example file names and their "
             "feedback. Suggest at most 12 improvements that would make it clearer and easier to file into: "
             "rename a category, merge one into another, split one into subcategories (give each subcategory "
             "a name and the words in file names that belong in it), or add a new subcategory with a short "
             "note. Follow their feedback. Prefer few, clear changes; don't suggest anything for categories "
             "marked 'looks right'.", "", "Catalog:"]
    for number, c in enumerate(categories[:MAX_CATEGORIES], start=1):
        parts = [f"{number}: {display(c.path)} ({c.files} files)"]
        if c.note:
            parts.append(f"note: {c.note}")
        if c.examples:
            parts.append("e.g. " + "; ".join(scrub_name(n) for n in c.examples[:EXAMPLES]))
        for f in c.feedback[-2:]:
            parts.append(f"feedback: {f['kind'].replace('_', ' ')}" + (f" - {f['text']}" if f.get("text") else ""))
        lines.append(" | ".join(parts))
    lines.append('\nReply with JSON only: {"suggestions": [{"kind": "rename|merge|split|new", "category": 3, '
                 '"into": 5, "name": "new name or new subcategory", "note": "for new", '
                 '"subcategories": [{"name": "Timesheets", "words": ["timesheet", "hours"]}], '
                 '"why": "a short reason"}]}')
    return "\n".join(lines)


def estimate(service_key: str, categories: list, display) -> float:
    return cost(service_key, tokens(request(categories, display)), REPLY_TOKENS)


def parse(text: str, categories: list, display, service_name: str) -> list[CatalogSuggestion]:
    try:
        data = extract_json(text)
    except ValueError:
        return []
    items = data.get("suggestions") if isinstance(data, dict) else None
    listed = categories[:MAX_CATEGORIES]

    def pick(value):
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None
        return listed[n - 1] if 1 <= n <= len(listed) else None

    found = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kind, c, why = str(item.get("kind") or ""), pick(item.get("category")), str(item.get("why") or "")[:200]
        name = str(item.get("name") or "").strip()[:80]
        if c is None:
            continue
        if kind == "rename" and name and name != c.name:
            found.append(CatalogSuggestion("rename", c.path, f"Rename “{c.name}” to “{name}”", why, name=name,
                                           source=service_name))
        elif kind == "merge" and (into := pick(item.get("into"))) is not None and into is not c:
            found.append(CatalogSuggestion("merge", c.path, f"Merge “{c.name}” ({c.files} files) into “{into.name}”",
                                           why, into=into.path, source=service_name))
        elif kind == "new" and name:
            found.append(CatalogSuggestion("new", c.path, f"Add “{name}” inside “{c.name}”", why, name=name,
                                           note=str(item.get("note") or "")[:200], source=service_name))
        elif kind == "split":
            parts = []
            left = set(c.direct)
            for sub in item.get("subcategories") or []:
                if not isinstance(sub, dict) or not str(sub.get("name") or "").strip():
                    continue
                wanted = {w for t in sub.get("words") or [] for w in words(str(t))}
                members = sorted(n for n in left if wanted & set(words(stem_of(n))))
                if members:
                    parts.append((str(sub["name"]).strip()[:60], members))
                    left -= set(members)
            if parts:
                listed_parts = ", ".join(f"{n} ({len(m)})" for n, m in parts)
                found.append(CatalogSuggestion("split", c.path, f"Split “{c.name}” into {listed_parts}", why,
                                               parts=parts, source=service_name))
    return found
