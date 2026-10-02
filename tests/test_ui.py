import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from sortzen.ui.app import create_app
    from sortzen.ui.main_window import MainWindow
except ImportError:  # PySide6 not installed
    create_app = None

from sortzen.config import AppPaths
from sortzen.engine.planner import TIDY
from sortzen.repositories.api_keys import ApiKeyStore
from sortzen.services import AppService
from sortzen.tasks import Status
from tests.fixtures import shared_test_folders
from tests.test_repositories import FakeKeyring


def wait_until(app, condition, seconds=60):
    deadline = time.time() + seconds
    while not condition() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return condition()


@unittest.skipIf(create_app is None, "PySide6 is not installed")
class MainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.service = AppService(AppPaths(Path(self.dir.name)), ApiKeyStore(FakeKeyring()))
        self.service.scanner.protected = []
        self.window = MainWindow(self.service)
        self.window.show()

    def tearDown(self):
        self.window.close()
        self.dir.cleanup()

    def test_window_opens_on_start_tab_with_folder_groups(self):
        self.assertEqual(self.window.tabs.tabText(0), "Start")
        groups = [self.window.tree.topLevelItem(i).text(0) for i in range(self.window.tree.topLevelItemCount())]
        self.assertEqual(groups, ["Source folders", "Destination folders"])
        self.assertFalse(self.window.plan_action.isEnabled())

    def test_folder_tree_can_be_hidden(self):
        self.window.tree_action.setChecked(False)
        self.assertFalse(self.window.splitter.widget(0).isVisible())
        self.window.tree_action.setChecked(True)
        self.assertTrue(self.window.splitter.widget(0).isVisible())

    def test_background_job_reports_to_status_bar(self):
        def work(emit, token):
            emit(Status("Scanning", "Downloads"))
            return 1

        job = self.window.run_job("scan", work)
        job.join(5)
        self.assertTrue(wait_until(self.app, lambda: self.window.statusBar().currentMessage() == "Ready", 5))

    def test_folders_added_removed_and_undone(self):
        root = shared_test_folders()
        self.window.add_source(str(root / "Downloads"), mode="sort into other folders")
        self.window.add_destination(str(root / "Sorted"))
        self.assertEqual(self.window.sources_item.child(0).text(0), "Downloads  ·  sort out")
        self.assertTrue(self.window.plan_action.isEnabled())
        self.window.remove_folder(str(root / "Sorted"))
        self.assertEqual(self.service.destination_folders(), [])
        self.window.undo()
        self.assertEqual(self.service.destination_folders(), [str(root / "Sorted")])

    def test_make_plan_explain_correct_and_undo(self):
        root = shared_test_folders()
        self.service.add_source(str(root / "Downloads"))
        self.service.add_source(str(root / "My Drive"), TIDY)
        self.service.add_destination(str(root / "Sorted"))
        self.window.refresh_folders()
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        tabs = [self.window.tabs.tabText(i) for i in range(self.window.tabs.count())]
        self.assertIn("Plan", tabs)
        self.assertTrue(any(t.startswith("Questions") for t in tabs))
        page = self.window.plan_page
        self.assertIn("ready", page.summary.text())
        ready = page.tree.topLevelItem(0)
        self.assertTrue(ready.text(0).startswith("Ready ("))
        self.assertTrue(ready.child(0).text(1).endswith("%"))
        first = ready.child(0)
        page.tree.setCurrentItem(first)
        self.assertIn("% sure", page.details.toPlainText())
        from sortzen.ui.plan_page import ROW
        row = first.data(0, ROW)
        target = str(root / "Sorted" / "Archives")
        self.window.correct([row], target)
        self.assertEqual(self.service.corrections(), {row.path: os.path.abspath(target)})
        self.assertEqual(self.window.plan.for_path(row.path).percent, 100)
        self.window.undo()
        self.assertEqual(self.service.corrections(), {})

    def test_autonomy_regroups_instantly(self):
        root = shared_test_folders()
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        page = self.window.plan_page
        def ready_count():
            return int(page.tree.topLevelItem(0).text(0).split("(")[1].split(")")[0])

        ready_before = ready_count()
        page.ask_all.setChecked(True)
        self.assertEqual(ready_count(), 0)
        page.ask_all.setChecked(False)
        page.level.setValue(50)
        self.assertGreater(ready_count(), ready_before)
        self.assertEqual(self.service.autonomy(), 50)


@unittest.skipIf(create_app is None, "PySide6 is not installed")
class ProgressWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def test_progress_times_tips_and_stop(self):
        from sortzen.ui.progress_window import ProgressWindow

        window = ProgressWindow(None, "Making the plan", estimate=200)
        window.set_step("Reading", "Downloads")
        window.set_progress(50, 100)
        window.set_progress(10, 100)                 # never goes backwards
        self.assertEqual(window.bar.value(), 500)
        self.assertTrue(window.times.text().startswith("50% done"))
        first = window.tip.text()
        window._next_tip()
        self.assertNotEqual(first, window.tip.text())
        stopped = []
        window.stop.connect(lambda: stopped.append(True))
        window.stop_button.click()
        self.assertEqual(stopped, [True])
        self.assertFalse(window.stop_button.isEnabled())
        window.finish()
