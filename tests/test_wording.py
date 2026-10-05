"""Docs and code describe SortZen only: no other projects and no request notes."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yml", ".yaml", ".iss", ".spec", ".bat", ".svg"}
FORBIDDEN = [
    re.compile("auction" + "zen", re.I),
    re.compile("auction" + "craft", re.I),
    re.compile("catal" + "ogger", re.I),
    re.compile(r"\(\s*" + "own" + r"er\b", re.I),
    re.compile(r"\b" + "own" + r"er's\b", re.I),
]


class WordingTest(unittest.TestCase):
    def test_no_outside_references(self):
        problems = []
        for path in ROOT.rglob("*"):
            if ".git" in path.parts or path.suffix.lower() not in TEXT_SUFFIXES or "fonts" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in FORBIDDEN:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    problems.append(f"{path.relative_to(ROOT)}:{line}: {match.group(0)}")
        self.assertEqual(problems, [])
