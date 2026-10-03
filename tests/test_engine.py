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


def _parse(fraction: str) -> tuple[int, int]:
    got, total = fraction.split(" of ")
    return int(got), int(total)


class OverviewScoreTest(unittest.TestCase):
    """Subfolders, topics and questions on the test folders, graded against the answer key."""

    @classmethod
    def setUpClass(cls):
        cls.root, cls.key = shared_test_folders(), answer_key()
        cls.plan = run_engine(cls.root)
        cls.result = score(cls.plan, cls.key, cls.root)

    def test_subfolders(self):
        right, total = _parse(self.result["folders decided right"])
        self.assertGreaterEqual(right, total - 2)
        right, total = _parse(self.result["kept-together folders placed right"])
        self.assertGreaterEqual(right, total - 1)

    def test_topics_and_questions(self):
        right, total = _parse(self.result["topics together or asked about"])
        self.assertEqual(right, total)
        self.assertLessEqual(self.result["questions"], 10)
        garden = next(q for q in self.plan.questions if "Garden Planner" in q.text)
        self.assertIn("3 places", garden.text)
        self.assertEqual(garden.choices[-1].label, "Leave them where they are")

    def test_answers_are_applied(self):
        garden = next(q for q in self.plan.questions if "Garden Planner" in q.text)
        folder_q = next(q for q in self.plan.questions if q.key.startswith("folder:"))
        sort_choice = next(i for i, c in enumerate(folder_q.choices) if c.outcome == "sort inside")
        answered = run_engine(self.root, answers={garden.key: 0, folder_q.key: sort_choice})
        home = garden.choices[0].destination
        members = {os.path.normcase(m) for m in garden.about}
        for s in answered.files:
            if os.path.normcase(s.path) in members:
                self.assertEqual((s.destination, s.percent), (home, 100))
        for f in answered.folders:
            if os.path.normcase(f.path) in members and os.path.normcase(f.path) != os.path.normcase(home):
                self.assertEqual((f.outcome, f.destination), ("keep together", home))
        self.assertEqual(answered.folder(folder_q.about[0]).outcome, "sort inside")
        self.assertNotIn(garden.key, [q.key for q in answered.questions if q.answer is None])


class CorrectionsTest(unittest.TestCase):
    def test_a_correction_is_kept_and_teaches_similar_files(self):
        base = tempfile.mkdtemp()
        down, docs = os.path.join(base, "Downloads"), os.path.join(base, "Documents")
        recs = [record(f"{docs}/Recipes/{n}.docx", f"{n} recipe flour sugar oven") for n in ("Bread", "Pie", "Scones")]
        recs += [record(f"{docs}/Garden/{n}.docx", f"{n} seeds soil watering") for n in ("Kale", "Beans", "Peas")]
        first = record(f"{down}/Tomato chutney.docx", "tomato chutney jars vinegar")
        second = record(f"{down}/Tomato salsa.docx", "tomato salsa jars vinegar")
        corrections = {first.path: os.path.join(docs, "Recipes")}
        plan = Planner(recs + [first, second], [Source(down, SORT_OUT)], [docs], corrections=corrections).plan()
        corrected, similar = plan.for_path(first.path), plan.for_path(second.path)
        self.assertEqual((corrected.destination, corrected.percent), (os.path.join(docs, "Recipes"), 100))
        self.assertEqual(similar.destination, os.path.join(docs, "Recipes"))
        self.assertTrue(any("Tomato chutney.docx" in r.text for r in similar.reasons))


class SpeedTest(unittest.TestCase):
    """Planning grows roughly in step with the number of files, not with its square."""

    def test_four_thousand_files(self):
        from sortzen.repositories.file_index import FileIndex
        from sortzen.scanning.scanner import Scanner
        from tests.fixtures.make_test_folders import build

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            records, sources, destinations = [], [], []
            scanner = Scanner(FileIndex(root / "i.db"), protected=[])
            for seed in range(10):
                build(root / f"set{seed}", seed=seed)
                records += scanner.scan(root / f"set{seed}" / "Downloads", "source", recursive=True).files
                records += scanner.scan(root / f"set{seed}" / "Sorted", "destination", recursive=True).files
                sources.append(Source(str(root / f"set{seed}" / "Downloads"), SORT_OUT))
                destinations.append(str(root / f"set{seed}" / "Sorted"))
            start = time.perf_counter()
            plan = Planner(records, sources, destinations).plan()
            seconds = time.perf_counter() - start
        self.assertGreater(len(records), 4000)
        self.assertGreater(len(plan.files), 2500)
        self.assertLess(seconds, 30)


class LeftOutTest(unittest.TestCase):
    def test_left_out_files_stay_and_still_teach(self):
        base = tempfile.mkdtemp()
        down, docs = os.path.join(base, "Downloads"), os.path.join(base, "Documents")
        audit = os.path.join(docs, "2022 Audit")
        recs = [record(f"{audit}/2022 TB {n}.pdf", "trial balance audit year-end", "pdf", ".pdf") for n in range(3)]
        recs += [record(f"{docs}/Recipes/{n}.docx", f"{n} recipe flour sugar oven") for n in ("Bread", "Pie", "Scones")]
        project = os.path.join(down, "Project Wren")
        recs += [record(f"{project}/Wren notes {n}.docx", "Project Wren roof plans") for n in range(3)]
        tb = record(f"{down}/TB final.pdf", "trial balance audit year-end", "pdf", ".pdf")
        cake = record(f"{down}/Cake recipe.docx", "cake recipe flour sugar oven")
        plan = Planner(recs + [tb, cake], [Source(down, SORT_OUT)], [docs], left_out=[audit, project]).plan()
        self.assertIsNone(plan.for_path(project + os.sep + "Wren notes 0.docx"))
        self.assertIsNone(plan.folder(project))
        held = plan.for_path(tb.path)
        self.assertIsNone(held.destination)
        self.assertIn("which is left out", held.reasons[0].text)
        self.assertEqual(plan.for_path(cake.path).destination, os.path.join(docs, "Recipes"))


class CopiesEngineTest(unittest.TestCase):
    def test_copy_marks_and_keep_instead(self):
        from sortzen.engine.duplicates import Copy, CopyGroup, has_copy_mark

        self.assertTrue(has_copy_mark("report (2).pdf"))
        self.assertTrue(has_copy_mark("report - Copy.pdf"))
        self.assertTrue(has_copy_mark("Copy of report.pdf"))
        self.assertFalse(has_copy_mark("Report 2024.pdf"))
        group = CopyGroup("f", 10, [Copy("/a/x.pdf", "/a", 1, keep=True), Copy("/a/y.pdf", "/a", 2, ticked=True),
                                    Copy("/a/p/z.pdf", "/a", 3, note="Inside a folder that is kept together")])
        group.keep_instead("/a/y.pdf")
        self.assertEqual(group.kept.path, "/a/y.pdf")
        self.assertEqual([(c.path, c.ticked) for c in group.extras], [("/a/x.pdf", True), ("/a/p/z.pdf", False)])


class RulesTest(unittest.TestCase):
    def test_rules_place_matching_files_except_users_own_choices(self):
        from sortzen.engine.plan import Plan, Reason, Suggestion
        from sortzen.engine.rules import Rule, apply_rules

        plan = Plan(files=[Suggestion("/d/Northgate invoices 2024.pdf", "/d", "/s/Bills", 70),
                           Suggestion("/d/invoice 7.docx", "/d", None, 0),
                           Suggestion("/d/invoice 9.pdf", "/d", "/s/Mine", 100, [Reason(True, "You chose this folder")]),
                           Suggestion("/s/Old/invoice 3.pdf", "/s/Old", "/s/Old", 80),
                           Suggestion("/d/holiday.jpg", "/d", "/s/Photos", 95)])
        rules = [Rule("invoice", "/s/Invoices"), Rule("invoice", "/s/Invoices/PDF", ".pdf")]
        placed = apply_rules(plan, rules, lambda f: True, lambda p: p.startswith("/d/"))
        a, b, c, d, e = plan.files
        self.assertEqual(placed, 2)
        self.assertEqual((a.destination, a.percent, a.runner_up), ("/s/Invoices/PDF", 100, ("/s/Bills", 70)))
        self.assertIn("Your rule: Names with “invoice” (PDF files)", a.reasons[0].text)
        self.assertEqual(b.destination, "/s/Invoices")
        self.assertEqual(c.destination, "/s/Mine")                  # the user's own choice wins
        self.assertEqual(d.destination, "/s/Old")                   # only folders being sorted
        self.assertEqual(e.destination, "/s/Photos")

    def test_suggest_only_useful_and_harmless_rules(self):
        from sortzen.engine.rules import Rule, suggest_rule

        examples = ["Northgate invoice 12.pdf", "Prairie Invoice 3.pdf"]
        others = [("/d/Clearwater invoice 9.pdf", "/s/Bills", 60), ("/d/invoice scan.jpg", None, 0),
                  ("/d/Northgate letter.pdf", "/s/Letters", 95)]
        found = suggest_rule(examples, "/s/Invoices", others, [], set())
        self.assertEqual(found.rule, Rule("invoice", "/s/Invoices"))
        self.assertEqual((found.examples, len(found.matches)), (2, 2))
        self.assertIsNone(suggest_rule(examples[:1], "/s/Invoices", others, [], set()))      # one file only
        self.assertIsNone(suggest_rule(examples, "/s/Invoices", others, [], {found.rule.key,
                                                                            Rule("invoice", "/s/Invoices", ".pdf").key}))
        sure = [("/d/Clearwater invoice 9.pdf", "/s/Bills", 95)]       # would overrule a sure suggestion
        self.assertIsNone(suggest_rule(examples, "/s/Invoices", sure, [], set()))
        narrower = suggest_rule(examples, "/s/Invoices", others + [("/d/invoice photo.jpg", "/s/Photos", 97)], [],
                                set())
        self.assertEqual(narrower.rule, Rule("invoice", "/s/Invoices", ".pdf"))      # avoids the sure picture


class ProgramsAndFamiliesTest(unittest.TestCase):
    """Versions and copies of one thing go into one folder; programs are never picked apart."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        from sortzen.config import AppPaths
        from sortzen.engine.planner import TIDY
        from sortzen.repositories.api_keys import ApiKeyStore
        from sortzen.services import AppService
        from tests.test_repositories import FakeKeyring

        self.dir = tempfile.TemporaryDirectory()
        base = Path(self.dir.name)
        self.root = base / "Older stuff"
        files = {}
        for version in ("TideLog", "TideLog-1.7.3", "TideLog-release-1.3"):
            files[f"{version}/requirements.txt"] = "pyside6"
            for part in ("services", "label", "school", "main"):
                files[f"{version}/src/tidelog/{part}.py"] = f"def {part}(): pass"
                files[f"{version}/tests/test_{part}.py"] = f"def test_{part}(): pass"
        for copy in ("TideLog-windows", "TideLog-windows (1)", "TideLog-windows (4)"):
            files[f"{copy}/TideLog-Setup-1.5.exe"] = "MZ installer"
            files[f"{copy}/README.txt"] = "TideLog readme"
        files["TideLog-windows.zip"] = "PK"
        for copy in ("Hanlon", "Hanlon (1)"):
            files[f"{copy}/Hanlon site plan.pdf"] = "site plan for the hanlon renovation"
            files[f"{copy}/Hanlon quote.docx"] = "quote for the hanlon renovation"
        files["Recipes/Lemon tart.txt"] = "lemon tart recipe"
        files["Recipes/Apple pie.txt"] = "apple pie recipe"
        files["School label service notes.txt"] = "notes about the school label service"
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")
        self.service = AppService(AppPaths(base / "data"), ApiKeyStore(FakeKeyring()))
        self.service.scanner.protected = []
        self.service.add_source(str(self.root), TIDY)
        self.plan = self.service.make_plan()

    def tearDown(self):
        self.dir.cleanup()

    def folder(self, name):
        return next(f for f in self.plan.folders if os.path.basename(f.path) == name)

    def test_versions_and_copies_gathered_into_one_new_folder(self):
        from sortzen.engine.overview import family_base
        from sortzen.engine.plan import KEEP_TOGETHER

        self.assertEqual(family_base("TideLog-windows (4)"), "TideLog")
        self.assertEqual(family_base("TideLog-release-1.3"), "TideLog")
        self.assertEqual(family_base("TideLog-Setup-1.5.exe", is_file=True), "TideLog")
        program = str(self.root / "TideLog Program")
        for name in ("TideLog", "TideLog-1.7.3", "TideLog-release-1.3", "TideLog-windows", "TideLog-windows (1)",
                     "TideLog-windows (4)"):
            f = self.folder(name)
            self.assertEqual((f.outcome, f.destination, f.percent), (KEEP_TOGETHER, program, 90))
        self.assertIn("versions or copies of “TideLog”", self.folder("TideLog").reasons[0].text)
        zipped = self.plan.for_path(str(self.root / "TideLog-windows.zip"))
        self.assertEqual(zipped.destination, program)
        copies = str(self.root / "Hanlon (all copies)")
        self.assertEqual({self.folder("Hanlon").destination, self.folder("Hanlon (1)").destination}, {copies})
        self.assertIn(program, self.plan.new_folders)
        self.assertNotEqual(self.folder("Recipes").outcome, KEEP_TOGETHER)

    def test_nothing_inside_a_program_is_sorted_or_asked_about(self):
        inside = [s.path for s in self.plan.files if "src" in s.path.split(os.sep) or "tests" in s.path.split(os.sep)]
        self.assertEqual(inside, [])
        self.assertFalse(any("tidelog" in m.lower() and os.sep + "src" + os.sep in m
                             for t in self.plan.topics for m in t.members))
        self.assertFalse(any(os.sep + "tests" in a for q in self.plan.questions for a in q.about))


class GroupsTest(unittest.TestCase):
    def test_groups_by_name_shape_then_shared_word(self):
        from sortzen.engine.groups import find_groups
        from sortzen.engine.plan import Suggestion

        unsure = [Suggestion(f"/d/{n}.pdf", "/d", None, 0) for n in (48213, 99120, 1203, 77)]
        unsure += [Suggestion(f"/d/IMG_{n}.jpg", "/d", "/s/Photos", 60) for n in (2041, 2042, 2050)]
        unsure += [Suggestion(f"/d/Northgate {w}.docx", "/d", None, 0) for w in ("letter", "memo", "notes")]
        unsure += [Suggestion("/d/odd one.txt", "/d", None, 0), Suggestion("/d/55.docx", "/d", None, 0)]
        groups = find_groups(unsure)
        self.assertEqual([g.title for g in groups], ["4 PDFs whose names are only numbers",
                                                     "3 pictures named like “IMG_2041.jpg”",
                                                     "3 files with “northgate” in the name"])
        self.assertEqual(groups[1].suggestion, "/s/Photos")
        self.assertIsNone(groups[0].suggestion)
        rule = groups[0].rule("/s/Scans")
        self.assertTrue(rule.matches("31337.pdf"))
        self.assertFalse(rule.matches("31337.docx"))
        self.assertFalse(rule.matches("Scan 31337.pdf"))
        self.assertIn("Names that are only numbers (PDF files) go to /s/Scans", rule.describe())
        self.assertTrue(groups[2].rule("/s/Work").matches("Northgate invoice.pdf"))

    def test_a_typed_folder_answers_a_question(self):
        from sortzen.engine.overview import apply_answers
        from sortzen.engine.plan import Choice, Plan, Question, Suggestion

        plan = Plan(files=[Suggestion("/d/a.pdf", "/d", "/d", 70)],
                    questions=[Question("topic:/d:a", "Where?", [Choice("Together in d", "/d"),
                                                                 Choice("Leave them where they are", None)],
                                        ["/d/a.pdf"])])

        class P:
            answers = {"topic:/d:a": "/s/Typed"}

            @staticmethod
            def label(folder):
                return os.path.basename(folder)

        apply_answers(P, plan)
        self.assertEqual(plan.questions[0].choices[1].label, "Together in Typed")
        self.assertEqual(plan.questions[0].answer, 1)
        self.assertEqual((plan.files[0].destination, plan.files[0].percent), ("/s/Typed", 100))


class FolderNotesTest(unittest.TestCase):
    def test_a_folders_note_counts_like_its_name(self):
        import tempfile
        from pathlib import Path

        from sortzen.config import AppPaths
        from sortzen.repositories.api_keys import ApiKeyStore
        from sortzen.services import AppService
        from tests.test_repositories import FakeKeyring

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            files = {"Downloads/Q3 timesheet.txt": "hours for the quarter",
                     "Sorted/Payroll/March pay register.txt": "pay register for march",
                     "Sorted/Payroll/April pay register.txt": "pay register for april"}
            for n, dish in enumerate(("lemon tart", "apple pie", "plum cake", "pear crumble", "fig jam", "lime curd",
                                      "rice pudding", "bread loaf", "cherry pie", "peach cobbler")):
                files[f"Sorted/Recipes/{dish}.txt"] = f"{dish} recipe with sugar"
            for rel, text in files.items():
                (base / rel).parent.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text(text, encoding="utf-8")
            service = AppService(AppPaths(base / "data"), ApiKeyStore(FakeKeyring()))
            service.scanner.protected = []
            service.add_source(str(base / "Downloads"))
            service.add_destination(str(base / "Sorted"))
            sheet = str(base / "Downloads" / "Q3 timesheet.txt")
            before = service.make_plan().for_path(sheet)
            self.assertNotEqual(before.destination, str(base / "Sorted" / "Payroll"))
            service.set_folder_note(str(base / "Sorted" / "Payroll"), "pay stubs, T4s, timesheets")
            after = service.make_plan().for_path(sheet)
            self.assertEqual(after.destination, str(base / "Sorted" / "Payroll"))
            self.assertTrue(any("Your note on “Payroll” mentions “timesheet”" in r.text for r in after.reasons))


class MeaningTest(unittest.TestCase):
    def test_meaning_raises_agreeing_and_suggests_for_homeless_files(self):
        import numpy as np

        from sortzen.engine.meaning import ALONE_MAX, apply_meaning
        from sortzen.engine.plan import Plan, Reason, Suggestion

        folders = ["/s/Payroll", "/s/Recipes"]
        matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        plan = Plan(files=[Suggestion("/d/q3 hours.txt", "/d", "/s/Payroll", 60),
                           Suggestion("/d/stub.txt", "/d", None, 0),
                           Suggestion("/d/odd.txt", "/d", None, 0),
                           Suggestion("/d/mine.txt", "/d", "/s/Recipes", 100, [Reason(True, "You chose this folder")])])
        vectors = {"/d/q3 hours.txt": np.array([0.9, 0.1], dtype=np.float32),
                   "/d/stub.txt": np.array([0.95, 0.05], dtype=np.float32),
                   "/d/odd.txt": np.array([0.5, 0.5], dtype=np.float32),       # no folder clearly closer
                   "/d/mine.txt": np.array([1.0, 0.0], dtype=np.float32)}
        changed = apply_meaning(np, plan, vectors, folders, matrix, lambda p: p)
        agreeing, homeless, unclear, mine = plan.files
        self.assertEqual(changed, 2)
        self.assertEqual(agreeing.percent, 72)                             # 60 + 40 * 0.3
        self.assertIn("By meaning", agreeing.reasons[0].text)
        self.assertEqual((homeless.destination, homeless.percent), ("/s/Payroll", ALONE_MAX))
        self.assertIsNone(unclear.destination)
        self.assertEqual(mine.destination, "/s/Recipes")


class CatalogReviewTest(unittest.TestCase):
    def test_split_merge_and_empty_suggestions(self):
        from sortzen.engine.catalog_review import review
        from sortzen.services.catalog import Category

        payroll = Category("/s/Work/Payroll", "Payroll", "/s/Work", ["/s/Work/Payroll"],
                           direct=[f"Timesheet week {i}.xlsx" for i in range(14)]
                           + [f"Pay stub {i}.pdf" for i in range(12)] + [f"Note {i}.txt" for i in range(6)])
        payroll.files = len(payroll.direct)
        invoices = Category("/s/Work/Invoices", "Invoices", "/s/Work", [], files=40)
        invoice = Category("/s/Work/Invoice", "Invoice", "/s/Work", [], files=3)
        empty = Category("/s/Work/Later", "Later", "/s/Work", [])
        right = Category("/s/Work/Ledgers", "Ledger", "/s/Work", [], files=2,
                         feedback=[{"kind": "right", "text": ""}])
        found = review([payroll, invoices, invoice, empty, right])
        kinds = {(s.kind, s.category) for s in found}
        self.assertIn(("merge", "/s/Work/Invoice"), kinds)
        self.assertIn(("empty", "/s/Work/Later"), kinds)
        self.assertNotIn("/s/Work/Ledgers", {s.category for s in found})
        split = next(s for s in found if s.kind == "split")
        self.assertEqual([(n, len(m)) for n, m in split.parts], [("Timesheet", 14), ("Stub", 12), ("Note", 6)])
        merge = next(s for s in found if s.kind == "merge")
        self.assertEqual(merge.into, "/s/Work/Invoices")
        self.assertEqual(review([invoices, invoice], {merge.key}), [])

    def test_feedback_drives_suggestions(self):
        from sortzen.engine.catalog_review import review
        from sortzen.services.catalog import Category

        small = Category("/s/Home/Bills", "Bills", "/s/Home", [], direct=[f"Hydro bill {i}.pdf" for i in range(5)]
                         + [f"Phone bill {i}.pdf" for i in range(4)], feedback=[{"kind": "too_broad", "text": ""}])
        small.files = 9
        narrow = Category("/s/Home/Gas", "Gas", "/s/Home", [], direct=["Gas bill 1.pdf"], files=1,
                          feedback=[{"kind": "too_narrow", "text": ""}])
        found = review([small, narrow])
        self.assertEqual(found[0].kind, "split")                    # asked-for suggestions come first
        self.assertEqual([n for n, _ in found[0].parts], ["Hydro", "Phone"])
        merge = next(s for s in found if s.kind == "merge")
        self.assertEqual(merge.into, "/s/Home/Bills")               # shares "bill" with Bills


class PairsTest(unittest.TestCase):
    def plan(self, *suggestions):
        from sortzen.engine.plan import Plan, Suggestion

        return Plan(files=[Suggestion(p, "/in", d, pc, runner_up=r) for p, d, pc, r in suggestions])

    def test_similar_raises_leans_or_doubts(self):
        from sortzen.engine.pairs import SIMILAR_ALONE, apply_pairs

        plan = self.plan(("/in/a.pdf", "/s/Tax", 70, None), ("/in/b.pdf", None, 0, None),
                         ("/in/c.pdf", "/s/Work", 90, None), ("/in/d.pdf", "/s/Work", 100, None))
        home = {"/s/Tax/t4.pdf": "/s/Tax"}.get
        n = apply_pairs(plan, [("/in/a.pdf", "/s/Tax/t4.pdf"), ("/in/b.pdf", "/s/Tax/t4.pdf"),
                               ("/in/c.pdf", "/s/Tax/t4.pdf"), ("/in/d.pdf", "/s/Tax/t4.pdf")], [], home, str)
        a, b, c, d = plan.files
        self.assertEqual(n, 3)                                              # a folder users chose stays
        self.assertEqual((a.destination, a.percent), ("/s/Tax", 85))
        self.assertIn("You said it's like “t4.pdf”", a.reasons[0].text)
        self.assertEqual((b.destination, b.percent), ("/s/Tax", SIMILAR_ALONE))   # leans, still waits for users
        self.assertEqual((c.destination, c.percent, c.runner_up), ("/s/Work", 72, ("/s/Tax", SIMILAR_ALONE)))
        self.assertEqual((d.destination, d.percent), ("/s/Work", 100))

    def test_different_lowers_or_switches_to_the_runner_up(self):
        from sortzen.engine.pairs import DIFFERENT_MAX, apply_pairs

        plan = self.plan(("/in/a.pdf", "/s/Tax", 90, None), ("/in/b.pdf", "/s/Tax", 80, ("/s/Work", 50)),
                         ("/in/c.pdf", "/s/Work", 80, None))
        home = {"/s/Tax/t4.pdf": "/s/Tax"}.get
        pairs = [(p, "/s/Tax/t4.pdf") for p in ("/in/a.pdf", "/in/b.pdf", "/in/c.pdf")]
        self.assertEqual(apply_pairs(plan, [], pairs, home, str), 2)
        a, b, c = plan.files
        self.assertEqual((a.destination, a.percent), ("/s/Tax", DIFFERENT_MAX))
        self.assertFalse(a.reasons[0].supports)
        self.assertEqual((b.destination, b.percent, b.runner_up), ("/s/Work", 50, ("/s/Tax", DIFFERENT_MAX)))
        self.assertEqual((c.destination, c.percent), ("/s/Work", 80))       # already elsewhere: unchanged
