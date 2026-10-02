"""Turn a scanned file into weighted clues the engine can compare.

Clues come from the file name (split into words, with odd capitals and run-together words
handled), the readable contents, the file kind and a few details (camera, Google link,
scanned page). Words of five or more letters also give a short prefix clue, so small typos
("backupo", "Accoutns") still match.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from ..scanning.records import FileRecord

STOPWORDS = {
    "the", "and", "of", "for", "to", "in", "on", "with", "by", "at", "from", "is", "be", "this", "that", "it", "as",
    "or", "are", "was", "an", "you", "we", "our", "your", "my", "me", "his", "her", "their", "its", "has", "have",
    "will", "can", "all", "any", "not", "no", "yes", "if", "but", "so", "do", "re", "per", "via", "than", "then",
    "page", "pdf", "docx", "xlsx", "jpg", "png", "www", "http", "https", "com",
}
DEFAULT_NAME_WORDS = {
    "new", "microsoft", "excel", "word", "powerpoint", "worksheet", "document", "presentation", "spreadsheet",
    "untitled", "file", "download", "copy", "doc", "text", "image", "book", "blank",
}
DOCUMENT_KINDS = {"word", "pdf", "spreadsheet", "presentation", "text"}
NAME_WEIGHT = 1.0
PREFIX_WEIGHT = 0.5
CONTENT_WEIGHT = 0.45
KIND_WEIGHT = 1.0
EXT_WEIGHT = 0.5
DETAIL_WEIGHT = 1.0
MAX_CONTENT_WORDS = 40
YEAR = re.compile(r"^(19[89]\d|20[0-4]\d)$")


def split_word(word: str) -> list[str]:
    """Split run-together words ("GardenPlanner", "ElleryPRSD"); keep odd capitals whole ("AUg", "pROJECT")."""
    if word.islower() or word.isupper() or not re.search(r"[a-z][A-Z]", word):
        return [word.lower()]
    if word[0].islower() and word[1:].isupper():
        return [word.lower()]
    return [p.lower() for p in re.findall(r"[A-Z]{2,}(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[A-Z]+", word)]


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text: str) -> list[str]:
    """Lower-case words of two or more letters, without common filler words."""
    out = []
    for raw in re.findall(r"[A-Za-z]+", text or ""):
        for part in split_word(raw):
            part = _singular(part)
            if len(part) >= 2 and part not in STOPWORDS:
                out.append(part)
    return out


def years(text: str) -> set[str]:
    return {y for y in re.findall(r"\d+", text or "") if YEAR.match(y)}


def stem_of(name: str) -> str:
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return re.sub(r"\s*\(\d+\)$", "", stem)


@dataclass
class Clues:
    weights: dict[str, float]
    name_words: list[str]
    content_words: list[str]
    name_years: set[str]
    default_name: bool
    no_contents: bool
    vector: dict[str, float] = field(default_factory=dict)      # weights x rarity, unit length


def clues_for(record: FileRecord) -> Clues:
    stem = stem_of(record.name)
    name_words = words(stem)
    weights: dict[str, float] = {}

    def add(key: str, weight: float) -> None:
        weights[key] = max(weights.get(key, 0.0), weight)

    for w in name_words:
        add(f"w:{w}", NAME_WEIGHT)
        if len(w) >= 5:
            add(f"p:{w[:5]}", PREFIX_WEIGHT)
    details = record.details or {}
    extra = " ".join(str(details.get(k, "")) for k in ("title", "subject", "keywords", "author", "product", "company"))
    names_inside = " ".join(details.get("names", []) if isinstance(details.get("names"), list) else [])
    content = words(f"{record.text} {extra} {names_inside}")
    counted = Counter(content)
    top = [w for w, _ in sorted(counted.items(), key=lambda kv: (-kv[1], content.index(kv[0])))][:MAX_CONTENT_WORDS]
    for w in top:
        weight = CONTENT_WEIGHT * (1 + math.log(counted[w])) / (1 + math.log(max(counted.values())))
        add(f"w:{w}", weight)
        if len(w) >= 5:
            add(f"p:{w[:5]}", weight * 0.5)
    add(f"k:{record.kind}", KIND_WEIGHT)
    if record.ext:
        add(f"e:{record.ext}", EXT_WEIGHT)
    if details.get("camera"):
        add("x:camera", DETAIL_WEIGHT)
    if details.get("google"):
        add("x:google", DETAIL_WEIGHT * 0.5)
    if details.get("no_text"):
        add("x:scan", DETAIL_WEIGHT * 0.5)
    letters = [w for w in name_words if not w.isdigit()]
    default_name = not letters or all(w in DEFAULT_NAME_WORDS for w in letters)
    no_contents = record.size == 0 or (record.kind in DOCUMENT_KINDS and not record.text.strip()
                                        and not details.get("google"))
    return Clues(weights, name_words, top, years(stem), default_name, no_contents)


def rarity(all_clues: list[Clues]) -> dict[str, float]:
    df = Counter(key for c in all_clues for key in c.weights)
    n = len(all_clues)
    return {key: math.log((n + 1) / (count + 1)) + 1 for key, count in df.items()}


def finish_vectors(all_clues: list[Clues], idf: dict[str, float]) -> None:
    for c in all_clues:
        vector = {k: w * idf.get(k, 1.0) for k, w in c.weights.items()}
        norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
        c.vector = {k: v / norm for k, v in vector.items()}
