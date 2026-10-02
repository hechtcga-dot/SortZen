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
from sortzen.repositories.api_keys import ApiKeyStore
from sortzen.services import AppService
from sortzen.tasks import Status
from tests.test_repositories import FakeKeyring


@unittest.skipIf(create_app is None, "PySide6 is not installed")
class MainWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app([])

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.window = MainWindow(AppService(AppPaths(Path(self.dir.name)), ApiKeyStore(FakeKeyring())))
        self.window.show()

    def tearDown(self):
        self.window.close()
        self.dir.cleanup()

    def test_window_opens_on_start_tab_with_folder_groups(self):
        self.assertEqual(self.window.tabs.tabText(0), "Start")
        groups = [self.window.tree.topLevelItem(i).text(0) for i in range(self.window.tree.topLevelItemCount())]
        self.assertEqual(groups, ["Source folders", "Destination folders"])

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
        deadline = time.time() + 5
        while self.window.statusBar().currentMessage() != "Ready" and time.time() < deadline:
            self.app.processEvents()
        self.assertEqual(self.window.statusBar().currentMessage(), "Ready")
