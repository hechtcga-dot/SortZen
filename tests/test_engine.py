import os
import tempfile
import time
import unittest
from pathlib import Path

from sortzen.engine import Planner, Source
from sortzen.engine.features import clues_for, split_word, words
from sortzen.engine.planner import SORT_OUT, TIDY
from sortzen.scanning.records import FileRecord
from tests.engine_score import run_engine, score
from tests.fixtures import answer_key, shared_test_folders


def record(path, text="", kind="word", ext=".docx", details=None, size=100):
    return FileRecord(path=os.path.normpath(os.path.abspath(path)), root="", role="", name=os.path.basename(path), ext=ext, kind=kind,
                      size=size, modified_ns=0, fingerprint="x", details=details or {}, text=text)


class CluesTest(unittest.TestCase):
    def test_odd_capitals_and_run_together_words(self):
        self.assertEqual(split_word("GardenPlanner"), ["garden", "planner"])
        self.assertEqual(split_word("ElleryPRSD"), ["ellery", "prsd"])
        self.assertEqual(split_word("AUg"), ["aug"])
        self.assertEqual(split_word("pROGRAMMING"), ["programming"])
        self.assertEqual(words("2022-2023 Op Costs template (1)"), ["op", "cost", "template"])

    def test_typos_share_a_prefix(self):
        typo = clues_for(record("x/Aug 2023 TB backupo.pdf", kind="pdf", ext=".pdf"))
        right = clues_for(record("x/TB backup.pdf", kind="pdf", ext=".pdf"))
        self.assertIn("p:backu", typo.weights.keys() & right.weights.keys())

    def test_default_names(self):
        self.assertTrue(clues_for(record("x/New Microsoft Excel Worksheet.xlsx", kind="spreadsheet")).default_name)
        self.assertTrue(clues_for(record("x/Untitled document.gdoc")).default_name)
        self.assertFalse(clues_for(record("x/Budget 2024.xlsx", kind="spreadsheet")).default_name)


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.down = os.path.join(self.dir, "Downloads")
        self.docs = os.path.join(self.dir, "Documents")

    def plan(self, records, sources=None, destinations=None):
        sources = sources or [Source(self.down, SORT_OUT)]
        return Planner(records, sources, destinations if destinations is not None else [self.docs]).plan()

    def examples(self):
        return [record(f"{self.docs}/Payroll/T4 summary {y}.pdf", f"T4 summary {y} payroll remittance", "pdf", ".pdf")
                for y in (2021, 2022, 2023)] + \
               [record(f"{self.docs}/Recipes/{n}.docx", f"{n} recipe flour sugar oven") for n in
                ("Banana bread", "Pancakes", "Apple pie")]

    def test_file_goes_to_the_folder_it_resembles_with_reasons(self):
        plan = self.plan(self.examples() + [record(f"{self.down}/Lemon cake recipe.docx", "lemon cake flour sugar oven")])
        s = plan.files[0]
        self.assertEqual(s.destination, os.path.join(self.docs, "Recipes"))
        self.assertGreaterEqual(s.percent, 90)
        texts = [r.text for r in s.reasons]
        self.assertTrue(any(t.startswith("Like “") for t in texts))
        self.assertTrue(any("Word document, like 3 of 3" in t for t in texts))

    def test_year_clash_is_explained(self):
        examples = [record(f"{self.docs}/2022 Audit/2022 TB {n}.pdf", "trial balance audit", "pdf", ".pdf") for n in range(3)]
        plan = self.plan(examples + [record(f"{self.down}/2023 TB final.pdf", "trial balance audit", "pdf", ".pdf")])
        s = plan.files[0]
        self.assertIn("Folder is for 2022; this file is from 2023", [r.text for r in s.reasons])
        self.assertTrue(any(not r.supports for r in s.reasons))

    def test_only_the_type_matches(self):
        plan = self.plan(self.examples() + [record(f"{self.down}/zzqx.pdf", "", "pdf", ".pdf")])
        s = plan.files[0]
        self.assertLessEqual(s.percent, 50)

    def test_default_named_empty_file_is_review(self):
        plan = self.plan(self.examples() + [record(f"{self.down}/New Microsoft Word Document.docx")])
        s = plan.files[0]
        self.assertEqual((s.destination, s.action, s.note), (None, "review", "looks empty"))

    def test_google_links_stay_in_their_drive(self):
        drive = os.path.join(self.dir, "My Drive")
        recs = self.examples() + [record(f"{drive}/Banana bread notes.gdoc", "", "word", ".gdoc", {"google": "Google Docs"})]
        plan = self.plan(recs, [Source(drive, SORT_OUT)])
        self.assertIsNone(plan.files[0].destination)
        self.assertIn("only move within their own drive", plan.files[0].reasons[0].text)

    def test_tidy_lone_file_stays_and_misfit_moves_out(self):
        drive = os.path.join(self.dir, "My Drive")
        recs = [record(f"{drive}/Recipes/{n}.docx", f"{n} recipe flour sugar oven") for n in ("Bread", "Pie", "Scones")]
        recs.append(record(f"{drive}/Recipes/T4 summary 2024.pdf", "T4 summary payroll remittance", "pdf", ".pdf"))
        recs += [record(f"{drive}/Payroll/T4 summary {y}.pdf", f"T4 summary {y} payroll", "pdf", ".pdf") for y in (2022, 2023)]
        recs.append(record(f"{drive}/Garden/Seed list.txt", "kale carrots", "text", ".txt"))
        plan = self.plan(recs, [Source(drive, TIDY)], [])
        by_name = {os.path.basename(s.path): s for s in plan.files}
        self.assertEqual(by_name["Seed list.txt"].action, "stay")
        self.assertEqual(by_name["Bread.docx"].action, "stay")
        moved = by_name["T4 summary 2024.pdf"]
        self.assertEqual((moved.action, moved.destination), ("move", os.path.join(drive, "Payroll")))


class EngineScoreTest(unittest.TestCase):
    """The engine on the test folders, graded against the answer key."""

    @classmethod
    def setUpClass(cls):
        root, key = shared_test_folders(), answer_key()
        start = time.perf_counter()
        cls.result = score(run_engine(root, key), key, root)
        cls.seconds = time.perf_counter() - start

    def test_top_suggestions(self):
        self.assertGreaterEqual(self.result["top suggestion right"], 0.93)

    def test_ready_suggestions_are_right(self):
        self.assertGreaterEqual(self.result["ready and right"], 0.97)
        band = self.result["right, by percentage band"]["90%+"]
        self.assertGreaterEqual(band[1], 0.95)

    def test_most_files_placed_without_asking(self):
        self.assertGreaterEqual(self.result["share placed without asking"], 0.70)

    def test_unclear_files_wait_in_review(self):
        self.assertGreaterEqual(self.result["review-only files kept for review"], 0.95)

    def test_organised_folders(self):
        self.assertLessEqual(self.result["wrong moves out of organised folders"], 2)
        found, total = map(int, self.result["misplaced files found"].split(" of "))
        self.assertGreaterEqual(found, total - 1)

    def test_speed(self):
        self.assertLess(self.seconds, 20)
