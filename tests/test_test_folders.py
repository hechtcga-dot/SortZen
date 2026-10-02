import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tests.fixtures.make_test_folders import PLAN, build


def _digest(folder: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            h.update(str(path.relative_to(folder)).encode())
            h.update(path.read_bytes())
    return h.hexdigest()


class TestFoldersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.root = build(Path(cls.dir.name) / "a")

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_downloads_and_answer_key_match(self):
        key = json.loads((self.root / "answer_key.json").read_text(encoding="utf-8"))
        names = sorted(p.name for p in (self.root / "Downloads").iterdir())
        self.assertEqual(sorted(key), names)
        self.assertEqual(len(names), sum(n for _, n, _ in PLAN.values()))
        self.assertEqual(len(names), 300)

    def test_every_destination_already_has_examples(self):
        for destination, _, already in PLAN.values():
            if destination:
                files = list((self.root / "Sorted" / destination).iterdir())
                self.assertEqual(len(files), already, destination)

    def test_same_seed_builds_identical_folders(self):
        again = build(Path(self.dir.name) / "b")
        self.assertEqual(_digest(self.root), _digest(again))
