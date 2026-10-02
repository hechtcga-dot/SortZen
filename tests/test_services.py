import os
import tempfile
import unittest
from pathlib import Path

from sortzen.ai.web_providers import OllamaProvider
from sortzen.config import AppPaths
from sortzen.services import AppService
from tests.test_repositories import FakeKeyring
from sortzen.repositories.api_keys import ApiKeyStore


class AppServiceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.dir.name))
        self.service = AppService(self.paths, ApiKeyStore(FakeKeyring()))

    def tearDown(self):
        self.dir.cleanup()

    def test_gemini_is_the_default(self):
        self.assertEqual(self.service.ai_service(), "gemini")

    def test_choose_service(self):
        self.service.set_ai_service("claude")
        self.assertEqual(AppService(self.paths, self.service.keys).ai_service(), "claude")
        with self.assertRaises(ValueError):
            self.service.set_ai_service("nonsense")

    def test_unknown_saved_service_falls_back_to_default(self):
        self.service.settings.set("ai_service", "gone")
        self.assertEqual(self.service.ai_service(), "gemini")

    def test_model_override_and_reset(self):
        default = self.service.model()
        self.service.set_model("custom-model")
        self.assertEqual(self.service.model(), "custom-model")
        self.service.set_model("")
        self.assertEqual(self.service.model(), default)

    def test_keys_never_written_to_settings(self):
        self.service.save_api_key("secret-key-value")
        self.service.set_model("custom-model")
        self.assertTrue(self.service.has_api_key())
        self.assertNotIn("secret-key-value", self.paths.settings_path.read_text(encoding="utf-8"))

    def test_ollama_needs_no_key(self):
        self.service.set_ai_service("ollama")
        self.assertTrue(self.service.has_api_key())
        self.assertIsInstance(self.service.provider(), OllamaProvider)

    def test_missing_key_is_a_plain_error(self):
        self.service.set_ai_service("claude")
        with self.assertRaises(ValueError):
            self.service.provider()


class FoldersTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.service = AppService(AppPaths(root / "data"), ApiKeyStore(FakeKeyring()))
        self.service.scanner.protected = []
        self.downloads, self.documents = root / "Downloads", root / "Documents"
        self.downloads.mkdir()
        self.documents.mkdir()

    def tearDown(self):
        self.dir.cleanup()

    def test_add_change_and_remove(self):
        from sortzen.engine.planner import TIDY
        from sortzen.services.app_service import FolderError

        self.service.add_source(str(self.downloads))
        self.service.add_destination(str(self.documents))
        with self.assertRaises(FolderError):
            self.service.add_destination(str(self.documents))
        with self.assertRaises(FolderError):
            self.service.add_source(str(self.downloads / "missing"))
        self.service.set_source_mode(str(self.downloads), TIDY)
        again = AppService(self.service.paths, self.service.keys)
        self.assertEqual(again.source_folders(), [{"path": str(self.downloads), "mode": TIDY}])
        self.assertEqual(again.destination_folders(), [str(self.documents)])
        again.remove_folder(str(self.downloads))
        self.assertEqual(again.source_folders(), [])

    def test_protected_folders_refused(self):
        from sortzen.repositories.file_index import path_key
        from sortzen.services.app_service import FolderError

        self.service.scanner.protected = [path_key(self.documents)]
        with self.assertRaises(FolderError):
            self.service.add_destination(str(self.documents))

    def test_options(self):
        self.assertFalse(self.service.option("gentle"))
        self.assertTrue(self.service.option("stop_reading_learned"))
        self.service.set_option("gentle", True)
        self.assertTrue(AppService(self.service.paths, self.service.keys).option("gentle"))
        with self.assertRaises(KeyError):
            self.service.set_option("nonsense", True)

    def test_autonomy_answers_corrections(self):
        self.assertEqual(self.service.autonomy(), 90)
        self.service.set_autonomy(120)
        self.assertEqual(self.service.autonomy(), 100)
        self.service.save_answers({"topic:x": 1})
        self.service.save_answers({"topic:y": 0, "topic:x": None})
        self.assertEqual(self.service.answers(), {"topic:y": 0})
        previous = self.service.correct(["a.pdf"], str(self.documents))
        self.assertEqual(self.service.corrections(), {"a.pdf": str(self.documents)})
        self.service.restore_corrections(previous)
        self.assertEqual(self.service.corrections(), {})

    def test_outermost_destination_only(self):
        from sortzen.services.app_service import _outermost
        a, b, c = self.documents, self.documents / "Word", Path(self.dir.name) / "Documents2"
        self.assertEqual(_outermost([b, a, c]), [a, c])


class MakePlanTest(unittest.TestCase):
    """The whole path on the test folders: add folders, plan, group, export."""

    @classmethod
    def setUpClass(cls):
        from tests.fixtures import shared_test_folders
        from sortzen.engine.planner import TIDY

        cls.dir = tempfile.TemporaryDirectory()
        root = shared_test_folders()
        cls.service = AppService(AppPaths(Path(cls.dir.name) / "data"), ApiKeyStore(FakeKeyring()))
        cls.service.scanner.protected = []
        cls.service.add_source(str(root / "Downloads"))
        cls.service.add_source(str(root / "My Drive"), TIDY)
        cls.service.add_destination(str(root / "Sorted"))
        cls.plan = cls.service.make_plan()

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_plan_groups(self):
        groups = self.service.plan_rows(self.plan)
        self.assertGreater(len(groups["Ready"]), 150)
        self.assertGreater(len(groups["Review"]), 20)
        self.assertTrue(any(r.is_folder and r.action == "Keep together" for r in groups["Ready"] + groups["Review"]))
        self.assertTrue(any(r.name == "older downloads" for r in groups["Sorted from the inside"]))
        self.service.set_ask_everything(True)
        try:
            self.assertEqual(self.service.plan_rows(self.plan)["Ready"], [])
        finally:
            self.service.set_ask_everything(False)

    def test_display_paths(self):
        row = self.service.plan_rows(self.plan)["Ready"][0]
        self.assertFalse(os.path.isabs(self.service.display(row.current)))

    def test_export(self):
        from openpyxl import load_workbook

        target = os.path.join(self.dir.name, "plan.xlsx")
        self.service.export_plan(self.plan, target)
        book = load_workbook(target)
        self.assertEqual(book["Plan"]["A1"].value, "Group")
        self.assertGreater(book["Plan"].max_row, 300)
        self.assertGreaterEqual(book["Questions"].max_row, 2)

    def test_destination_choices(self):
        choices = self.service.destination_choices(self.plan)
        self.assertTrue(any(c.endswith(os.path.join("Work", "Payroll")) for c in choices))

    def test_needs_a_folder_to_sort(self):
        from sortzen.services.app_service import FolderError

        empty = AppService(AppPaths(Path(self.dir.name) / "empty"), ApiKeyStore(FakeKeyring()))
        with self.assertRaises(FolderError):
            empty.make_plan()
