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
        if self.service.jobs.current:
            self.service.jobs.current.join(30)
        self.app.processEvents()
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
        self.assertTrue(ready.child(0).text(2).endswith("%"))
        first = ready.child(0)
        page.tree.setCurrentItem(first)
        self.assertIn("% sure", page.details.toPlainText())
        from sortzen.ui.plan_page import ROW
        row = first.data(0, ROW)
        target = str(root / "Sorted" / "Archives")
        self.window.correct([row], target)
        self.assertEqual(self.service.corrections(), {row.path: os.path.abspath(target)})
        self.assertEqual(self.window.plan.for_path(row.path).percent, 100)
        self.assertIn("changed 1 of", page.accuracy.text())
        self.window.undo()
        self.assertEqual(self.service.corrections(), {})

    def test_plan_search_group_by_destination_and_ticks(self):
        from PySide6.QtCore import Qt

        from sortzen.ui.sortable import natural

        root = shared_test_folders()
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        page = self.window.plan_page
        ticked = page.ticked_rows()
        self.assertTrue(ticked and all(r.moves for r in ticked))
        self.assertIn(f"Move {len(ticked):,} ticked", page.move_button.text())
        first = page.tree.topLevelItem(0).child(0)
        first.setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual(len(page.ticked_rows()), len(ticked) - 1)
        page.search.setText("Autumn_Ellery")
        visible = [item for _, item in page._rows_items() if not item.isHidden()]
        self.assertTrue(visible and all("Autumn_Ellery" in i.text(0) for i in visible))
        page.search.clear()
        page.group_by.setCurrentIndex(1)
        headings = [page.tree.topLevelItem(i).text(0) for i in range(page.tree.topLevelItemCount())]
        self.assertTrue(any(h.startswith("Sorted/Documents/Work/Payroll (") for h in headings))
        page.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        group = page.tree.topLevelItem(0)
        names = [group.child(i).text(0) for i in range(group.childCount())]
        self.assertEqual(names, sorted(names, key=natural))

    def test_move_ticked_then_undo(self):
        import shutil

        source = shared_test_folders()
        root = Path(self.dir.name) / "folders"
        for name in ("Downloads", "Sorted"):
            shutil.copytree(source / name, root / name)
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        ticked = self.window.plan_page.ticked_rows()[:5]
        before = sorted(str(p) for p in root.rglob("*"))
        self.window.move_rows(ticked, confirm=False)
        self.assertTrue(wait_until(self.app, lambda: getattr(self.window, "result_dialog", None) is not None))
        self.assertTrue(all(not os.path.exists(r.path) for r in ticked))
        self.assertIn("Moved 5 items", self.window.result_dialog.findChild(type(self.window.start_hint)).text())
        self.assertEqual(self.window.undo_action.text(), "Undo move")
        self.window.plan = None
        self.window.result_dialog.accept()                  # closing it makes the plan again
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        self.assertFalse({r.path for r in ticked} & {s.path for s in self.window.plan.files})
        from PySide6.QtWidgets import QMessageBox
        from unittest import mock
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.undo()
        self.assertTrue(wait_until(self.app, lambda: all(os.path.exists(r.path) for r in ticked)))
        self.assertTrue(wait_until(self.app, lambda: not self.service.jobs.busy))
        self.assertEqual(sorted(str(p) for p in root.rglob("*")), before)
        self.assertTrue(self.service.move_runs()[0]["undone"])

    def test_copies_tab_keep_instead_and_queue(self):
        import shutil

        from PySide6.QtCore import Qt

        root = Path(self.dir.name) / "folders"
        shutil.copytree(shared_test_folders() / "Downloads", root / "Downloads")
        self.service.add_source(str(root / "Downloads"))
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        tabs = [self.window.tabs.tabText(i) for i in range(self.window.tabs.count())]
        self.assertTrue(any(t.startswith("Copies (") for t in tabs))
        page = self.window.copies_page
        group = page.groups[0]
        extra = group.extras[0]
        page.keep_instead(extra)
        self.assertTrue(extra.keep)
        heading = page.tree.topLevelItem(0)
        child = next(heading.child(i) for i in range(heading.childCount())
                     if heading.child(i).checkState(0) == Qt.CheckState.Checked)
        child.setCheckState(0, Qt.CheckState.Unchecked)
        ticked = page.ticked()
        self.assertIn(f"Queue {len(ticked):,} ticked", page.queue_button.text())
        self.window.queue_copies(page.groups, confirm=False)
        self.assertTrue(wait_until(self.app, lambda: getattr(self.window, "result_dialog", None) is not None))
        self.assertTrue(all(not os.path.exists(c.path) for c in ticked))
        self.assertTrue(extra.path and os.path.exists(extra.path))
        self.assertEqual(self.window.undo_action.text(), "Undo queue copies")

    def test_ask_ai_dialog_and_job(self):
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        from sortzen.ui.ai_dialog import AskAIDialog
        from tests.test_ai import FakeProvider

        root = shared_test_folders()
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        dialog = AskAIDialog(self.window, self.service, self.window.plan)
        self.assertIn("Ask Gemini about", dialog.title.text())
        self.assertFalse(dialog.ask.isEnabled())                  # no key yet
        dialog.ai_box.key.setText("test-key")
        self.assertTrue(dialog.ask.isEnabled())
        dialog.privacy.buttons["beginning"].setChecked(True)
        self.assertIn("beginning of the file", dialog.cost.text())
        self.assertEqual(self.service.ai_value("ai_privacy"), "name")     # nothing saved before Ask
        dialog.accept()
        self.assertTrue(self.service.has_api_key("gemini"))
        self.assertEqual(self.service.ai_value("ai_privacy"), "beginning")
        first = self.window.plan
        with mock.patch.object(type(self.service), "provider", lambda s: FakeProvider()), \
                mock.patch.object(QMessageBox, "information") as told:
            self.window.ask_ai(confirm=False)
            self.assertTrue(wait_until(self.app, lambda: told.called))
            self.assertTrue(wait_until(self.app, lambda: self.window.plan is not first and not self.service.jobs.busy))
        self.assertIn("suggested a folder", told.call_args.args[2])

    def test_settings_window_profile_and_diagnostics(self):
        from sortzen.ui.settings_window import SettingsWindow

        root = shared_test_folders()
        window = SettingsWindow(self.window, self.service, "Privacy")
        self.assertEqual(window.tabs.tabText(window.tabs.currentIndex()), "Privacy")
        window.level.setValue(75)
        window.options["gentle"].setChecked(True)
        window.privacy_lists.words.setText("tax, payslip")
        window.accept()
        self.assertEqual(self.service.autonomy(), 75)
        self.assertTrue(self.service.option("gentle"))
        self.assertEqual(self.service.ai_value("ai_name_only_words"), ["tax", "payslip"])

        self.service.add_destination(str(root / "Sorted"))
        target = str(Path(self.dir.name) / "me.szprofile")
        self.service.save_profile(target)
        self.service.remove_folder(str(root / "Sorted"))
        self.service.set_autonomy(90)
        self.window.load_profile(target)
        self.assertEqual(self.service.destination_folders(), [str(root / "Sorted")])
        self.assertEqual(self.service.autonomy(), 75)
        self.assertEqual(self.window.undo_action.text(), "Undo load profile")
        self.window.undo()
        self.assertEqual(self.service.destination_folders(), [])

        self.window.copy_diagnostics()
        self.assertIn("SortZen", self.app.clipboard().text())

    def test_remove_data_for_uninstall(self):
        from unittest import mock

        from sortzen.ui.app import main

        storage = Path(self.dir.name) / "to remove"
        (storage / "runs").mkdir(parents=True)
        cleared = []
        with mock.patch.dict(os.environ, {"SORTZEN_DATA_DIR": str(storage)}), \
                mock.patch("sortzen.repositories.api_keys.ApiKeyStore.clear", lambda self, s: cleared.append(s)):
            self.assertEqual(main(["SortZen.exe", "--remove-data"]), 0)
        self.assertFalse(storage.exists())
        self.assertIn("gemini", cleared)

    def test_confirm_and_runs_windows(self):
        from sortzen.mover import RunResult
        from sortzen.services.moving import MovePreview
        from sortzen.ui.move_dialogs import ConfirmMoveDialog, MoveResultDialog, RunsDialog

        preview = MovePreview(files=3, folders=1, files_in_folders=12,
                              destinations=[("/x/Sorted/Work", 3, False), ("/x/Sorted/Trips", 1, True)],
                              renamed=["notes.txt"], emptied=["/x/Downloads/older"])
        dialog = ConfirmMoveDialog(self.window, preview, lambda p: p)
        self.assertEqual(dialog.move_button.text(), "Move 4")
        self.assertEqual(dialog.table.topLevelItem(0).text(1), "3")
        result = MoveResultDialog(self.window, RunResult("log", moved=2, failed=[("/x/a.docx", "It's open")]),
                                  lambda p: p)
        result.close()
        runs = RunsDialog(self.window, [{"log": "a", "kind": "move", "time": 2, "moved": 4, "undone": False},
                                        {"log": "b", "kind": "move", "time": 1, "moved": 2, "undone": True}])
        runs.table.setCurrentItem(runs.table.topLevelItem(1))
        self.assertFalse(runs.put_back.isEnabled())         # already put back
        runs.table.setCurrentItem(runs.table.topLevelItem(0))
        self.assertTrue(runs.put_back.isEnabled())
        runs.accept()
        self.assertEqual(runs.chosen, "a")
        dialog.close()

    def test_folders_tab_counts_drill_down_and_tick_boxes(self):
        from PySide6.QtCore import Qt

        root = shared_test_folders()
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.refresh_folders()
        page = self.window.folders_page
        self.assertTrue(wait_until(self.app, lambda: page.counts, 30))
        self.assertIn("files", page.summary.text())
        self.assertIn("Making a plan takes", page.estimate.text())
        downloads = page.tree.topLevelItem(0)
        downloads.setExpanded(True)
        self.app.processEvents()
        older = next(downloads.child(i) for i in range(downloads.childCount())
                     if downloads.child(i).text(0) == "older downloads")
        self.assertGreater(int(older.text(1).replace(",", "")), 50)
        older.setCheckState(0, Qt.CheckState.Unchecked)
        self.assertEqual(self.service.left_out(), [str(root / "Downloads" / "older downloads")])
        self.assertEqual(downloads.checkState(0), Qt.CheckState.PartiallyChecked)
        older.setExpanded(True)
        self.app.processEvents()
        self.assertEqual(older.child(0).checkState(0), Qt.CheckState.Unchecked)
        self.window.undo()
        self.assertEqual(self.service.left_out(), [])
        self.assertEqual(downloads.checkState(0), Qt.CheckState.Checked)

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
