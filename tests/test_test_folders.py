import hashlib
import re
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import answer_key, shared_test_folders
from tests.fixtures.make_test_folders import build

SOURCES = ("Downloads", "My Drive")


def _digest(folder: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            h.update(path.relative_to(folder).as_posix().encode())
            h.update(path.read_bytes())
    return h.hexdigest()


class TestFoldersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = shared_test_folders()
        cls.key = answer_key()

    def held_folders(self):
        return [f for f, outcome in self.key["folders"].items() if outcome != "sort inside"]

    def test_every_file_to_sort_is_in_the_answer_key(self):
        held = self.held_folders()
        expected = set()
        for source in SOURCES:
            for path in (self.root / source).rglob("*"):
                rel = path.relative_to(self.root).as_posix()
                if path.is_file() and not any(rel.startswith(f + "/") for f in held):
                    expected.add(rel)
        self.assertEqual(set(self.key["files"]), expected)
        self.assertGreater(len(expected), 300)

    def test_destinations_exist(self):
        for rel, dest in self.key["files"].items():
            if dest:
                self.assertTrue((self.root / dest).is_dir(), f"{rel} -> {dest}")
        for folder, outcome in self.key["folders"].items():
            self.assertTrue((self.root / folder).is_dir(), folder)
            if outcome.startswith("keep together: "):
                self.assertTrue((self.root / outcome.split(": ", 1)[1]).is_dir(), outcome)
            else:
                self.assertIn(outcome, ("sort inside", "stays", "review"))

    def test_real_world_mess_is_represented(self):
        names = [Path(rel).name for rel in self.key["files"]]
        google = [n for n in names if Path(n).suffix in (".gdoc", ".gsheet", ".gform")]
        copies = [n for n in names if re.search(r" \(\d+\)\.", n)]
        review = [rel for rel, dest in self.key["files"].items() if dest is None]
        self.assertGreaterEqual(len(google), 15)
        self.assertGreaterEqual(len(copies), 5)
        self.assertTrue(any("backupo" in n or "Accoutns" in n for n in names))       # typos
        self.assertTrue(any(n.startswith("scan_") for n in names))                    # scanner output
        self.assertTrue(5 <= 100 * len(review) / len(names) <= 20)
        outcomes = set(o.split(":")[0] for o in self.key["folders"].values())
        self.assertEqual(outcomes, {"keep together", "sort inside", "stays", "review"})

    def test_own_resume_and_applicant_resumes_differ(self):
        files = self.key["files"]
        self.assertEqual(files["Downloads/Jordan Sample Resume 2025.docx"], "Sorted/Documents/Personal/Career")
        self.assertEqual(files["Downloads/2023 Autumn_Ellery_Resume.pdf"], "Sorted/Documents/Work/Staffing")

    def test_same_seed_builds_identical_folders(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_digest(self.root), _digest(build(Path(d))))
