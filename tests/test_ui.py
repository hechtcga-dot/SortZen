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
try:
    from PySide6.QtWidgets import QPushButton
except ImportError:
    QPushButton = None
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
        self.assertTrue(any(t.startswith("Labels (") for t in tabs))
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
        with mock.patch.object(type(self.service), "check_ai", lambda *a, **k: None):
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

    def test_wrong_model_is_explained_and_nothing_closes(self):
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        from sortzen.ai.provider import AIProvider
        from sortzen.ai.sorter import AIRun
        from sortzen.ui.ai_dialog import AskAIDialog

        class NoSuchModel(AIProvider):
            def generate_json(self, model, contents):
                raise RuntimeError(f"404 NOT_FOUND. models/{model} is not found for API version v1beta")

            def list_models(self):
                return ["gemini-lite", "gemini-pro"]

        root = shared_test_folders()
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        dialog = AskAIDialog(self.window, self.service, self.window.plan)
        dialog.show()
        box = dialog.ai_box
        box.key.setText("test-key")
        with mock.patch("sortzen.services.app_service.make_provider", lambda *a: NoSuchModel()):
            box.fetch_models()
            self.assertEqual([box.model.itemData(i) for i in range(box.model.count())][-2:],
                             ["gemini-lite", "gemini-pro"])
            box.model.setEditText("gemini-prooo")
            self.assertIn("isn't in Gemini's list", box.note.text())
            with mock.patch.object(QMessageBox, "warning") as warned:
                dialog.accept()
        self.assertIn("can't find the model “gemini-prooo”", warned.call_args.args[2])
        self.assertTrue(dialog.isVisible())                          # stays open to fix the name
        self.assertFalse(self.service.has_api_key("gemini"))         # nothing saved
        box.model.setCurrentIndex(box.model.findData("gemini-lite"))
        self.assertEqual(box.model_name(), "gemini-lite")
        dialog.close()
        failed = AIRun(stopped="Gemini can't find the model “x”.", failed=True)
        with mock.patch.object(QMessageBox, "warning") as warned:
            self.window._asked(failed)
        self.assertIn("can't find the model", warned.call_args.args[2])

    def test_recent_folders_rules_and_renaming(self):
        import shutil
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        from sortzen.ui.dialogs import DestinationDialog
        from sortzen.ui.settings_window import SettingsWindow

        root = Path(self.dir.name) / "folders"
        for name in ("Downloads", "Sorted"):
            shutil.copytree(shared_test_folders() / name, root / name)
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        rows = [r for r in self.service.plan_rows(self.window.plan)["Review"] if not r.is_folder][:3]
        target = str(root / "Sorted" / "Archives")
        with mock.patch.object(type(self.window), "offer_rule"):
            self.window.correct(rows[:1], target)
            self.window.correct(rows[1:2], str(root / "Sorted" / "Music"))
        self.assertEqual(self.service.recent_destinations()[:2], [str(root / "Sorted" / "Music"), target])
        dialog = DestinationDialog(self.window, self.service.destination_choices(self.window.plan),
                                   self.service.display, recent=self.service.recent_destinations(), rename=lambda f: None)
        self.assertEqual(dialog.recent.count(), 2)
        dialog.recent.setCurrentRow(1)
        dialog.accept()
        self.assertEqual(dialog.chosen, target)

        # a rule is offered after two files with a word in common go to one folder
        from sortzen.engine.rules import Rule, RuleSuggestion
        suggestion = RuleSuggestion(Rule("invoice", target), 2, ["x"])
        with mock.patch.object(self.window, "make_plan") as replanned:
            self.window.offer_rule(suggestion, answer="make")
        replanned.assert_called_once()
        self.assertEqual(self.service.rules(), [Rule("invoice", target)])
        settings = SettingsWindow(self.window, self.service, "Rules")
        self.assertIn("Names with “invoice” go to", settings.rules.item(0).text())
        self.window.undo()
        self.assertEqual(self.service.rules(), [])
        settings.close()

        # renaming a folder that exists: on disk, with Undo
        with mock.patch.object(self.window, "make_plan"):
            new = self.window.rename_folder(str(root / "Sorted" / "Music"), "Songs", confirm=False)
        self.assertTrue(os.path.isdir(new))
        self.assertFalse(os.path.exists(root / "Sorted" / "Music"))
        self.assertEqual(self.service.recent_destinations()[0], new)
        self.window.undo()
        self.assertTrue(os.path.isdir(root / "Sorted" / "Music"))
        with mock.patch.object(QMessageBox, "warning") as warned:
            self.assertIsNone(self.window.rename_folder(str(root / "Sorted" / "Music"), "Bad/Name", confirm=False))
        self.assertIn("can't contain", warned.call_args.args[2])

    def test_to_place_labels_similar_files_and_groups(self):
        import shutil

        from sortzen.ui.to_place_page import GroupDialog

        root = Path(self.dir.name) / "folders"
        shutil.copytree(shared_test_folders() / "Downloads", root / "Downloads")
        shutil.copytree(shared_test_folders() / "Sorted", root / "Sorted")
        for n in (48213, 99120, 1203, 77):
            (root / "Downloads" / f"{n}.pdf").write_bytes(b"%PDF-1.4\n%" + str(n).encode())
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None))
        page = self.window.to_place_page
        heading = next(page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())
                       if page.tree.topLevelItem(i).text(0).startswith("4 PDFs whose names are only numbers"))
        heading.setSelected(True)
        numbers = page.selected_paths()
        self.assertEqual(len(numbers), 4)                                    # a whole group at once
        scans = str(root / "Sorted" / "Documents" / "Scans")
        self.window.new_label(numbers, "Scans")
        self.assertEqual(list(page.label_buttons), ["Scans"])
        self.assertEqual(self.service.labels_of(numbers[0]), ["Scans"])
        self.assertEqual(page.items[os.path.normcase(numbers[0])].text(1), "Scans")
        self.window.new_label([numbers[0]], "Work")
        self.window.edit_label("Work", "up")                                # Work now counts most
        self.assertEqual(self.service.labels(), ["Work", "Scans"])
        self.assertEqual(page.label_buttons["Work"].text(), "Work  1/4")   # one of the four selected has it
        page.label.emit(numbers, "Work", False)                              # taken away from whichever have it
        self.assertEqual(self.service.labels_of(numbers[0]), ["Scans"])
        self.window.undo()
        self.assertEqual(self.service.labels_of(numbers[0]), ["Scans", "Work"])
        from PySide6.QtWidgets import QMenu

        from sortzen.ui.to_place_page import label_menus

        menu = QMenu()
        label_menus(menu, self.service, numbers, lambda *a: None)
        take = next(a.menu() for a in menu.actions() if a.text() == "Take a label away")
        self.assertEqual([a.text() for a in take.actions()], ["Work  (1 of 4 have it)", "Scans"])
        page.toggle_label("Scans")                                           # all four have it: taken away
        self.assertEqual(self.service.labels_of(numbers[1]), [])
        self.window.undo()
        self.assertEqual(self.service.labels_of(numbers[1]), ["Scans"])
        self.assertEqual(self.service.labels_of(numbers[0]), ["Scans", "Work"])
        payroll = root / "Sorted" / "Documents" / "Work" / "Payroll"
        other = str(next(payroll.iterdir()))
        self.window.pair_files([numbers[2]], "similar", other)
        self.assertEqual(self.service.pairs_of(numbers[2]), [("similar", other)])
        self.assertIn("You said: similar to “", page.items[os.path.normcase(numbers[2])].text(3))
        self.window.undo()
        self.assertEqual(self.service.pairs_of(numbers[2]), [])
        group = next(g for g in page.groups if g.title == "4 PDFs whose names are only numbers")
        dialog = GroupDialog(page, self.service, self.window.plan, group, [], [])
        dialog.picker.box.setEditText("Sorted/Documents/Scans")              # a folder typed as shown
        self.assertEqual(dialog.picker.folder(), scans)
        dialog.close()
        first = self.window.plan
        page.place_group.emit(group, scans, True)
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not first and not self.service.jobs.busy))
        moved = self.window.plan.for_path(str(root / "Downloads" / "77.pdf"))
        self.assertEqual((moved.destination, moved.percent), (scans, 100))
        self.assertEqual(len(self.service.rules()), 1)
        if page.cards:                                              # questions take any folder too
            question = page.cards[0]
            question.picker.box.setEditText("Sorted/Projects/Typed")
            self.assertEqual(question.answer(), str(root / "Sorted" / "Projects" / "Typed"))

    def test_cataloguing_wizard_labels_rounds_and_ai(self):
        import json
        import shutil
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox

        from sortzen.ai.provider import AIProvider, AIResponse, TokenUsage
        from sortzen.ui.dialogs import LabelChoiceDialog

        root = Path(self.dir.name) / "folders"
        shutil.copytree(shared_test_folders() / "Downloads", root / "Downloads")
        shutil.copytree(shared_test_folders() / "Sorted", root / "Sorted")
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.refresh_folders()
        self.window.open_wizard()
        wizard = self.window.wizard_page
        self.assertIs(self.window.tabs.currentWidget(), wizard)
        self.assertEqual(wizard.stack.currentIndex(), 0)
        self.assertFalse(wizard.start_button.isEnabled())                   # no labels yet
        for name in ("Work", "School", "Resume"):
            self.window.new_label([], name)
        self.assertEqual(wizard.labels_shown(), ["Work", "School", "Resume"])
        self.window.reorder_labels(["Resume", "Work", "School"])
        self.assertEqual(self.service.labels()[0], "Resume")
        wizard.start_button.click()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None and not self.service.jobs.busy))
        self.assertTrue(wait_until(self.app, lambda: wizard.stack.currentIndex() == 1))
        page = self.window.to_place_page
        self.assertGreater(page.count(), 0)
        self.assertIn("need you", wizard.meter.text())
        resumes = next(page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())
                       if "resume" in page.tree.topLevelItem(i).text(0).lower())
        resumes.setSelected(True)
        paths = page.selected_paths()
        self.window.confirm_labels(paths)                                    # one answer for the whole group
        self.assertIn("Resume", self.service.labels_of(paths[0]))
        self.assertEqual(self.service.agreement()[1], len(paths))
        self.assertIn(str(len(paths)), wizard.banner_text.text())
        self.window.note_file(paths[0], "for the Staffing folder")
        self.assertEqual(self.service.file_note(paths[0]), "for the Staffing folder")
        first = self.window.plan
        wizard.again_button.click()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not first and not self.service.jobs.busy))
        self.assertEqual(self.service.learned_since_plan(), 0)
        staffing = self.window.plan.for_path(paths[0])
        self.assertTrue(staffing.destination.endswith("Staffing"))

        class Labeller(AIProvider):
            def generate_json(self, model, contents):
                if "Suggest labels" in contents[0]:
                    return AIResponse(json.dumps({"labels": [{"name": "Taxes"}, {"name": "Work"}]}), TokenUsage(9, 9, 18))
                n = sum(1 for line in contents[0].splitlines() if line[:1].isdigit())
                return AIResponse(json.dumps({"files": [{"n": i, "labels": [{"label": "Taxes", "sure": 80}]}
                                                        for i in range(1, n + 1)]}), TokenUsage(9, 9, 18))

        self.service.set_ai_value("ai_enabled", True)
        self.service.save_api_key("test-key")
        with mock.patch.object(self.service, "provider", return_value=Labeller()), \
                mock.patch.object(LabelChoiceDialog, "exec", return_value=1), \
                mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.ai_suggest_labels()
            self.assertTrue(wait_until(self.app, lambda: "Taxes" in self.service.labels()))
            self.assertEqual(self.service.labels().count("Work"), 1)            # labels already there are kept
            plan = self.window.plan
            self.window.ai_label_files("unsure")
            self.assertTrue(wait_until(self.app, lambda: self.window.plan is not plan and not self.service.jobs.busy))
        self.assertTrue(self.service.ai_labels())
        page.tree.clearSelection()
        rows = list(page.items.values())[:2]
        for row in rows:
            row.setSelected(True)
        doomed = page.selected_paths()
        self.assertEqual(len(doomed), 2)                                     # several files at once
        with mock.patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Yes):
            page.delete_button.click()
        self.assertTrue(wait_until(self.app, lambda: not any(os.path.exists(p) for p in doomed)
                                   and os.path.normcase(doomed[0]) not in page.items))
        self.assertTrue((root / "Downloads" / "To delete").is_dir())
        self.assertIsNone(self.window.plan.for_path(doomed[0]))               # gone from the plan and the list
        self.service.set_option("ask_before_delete", False)
        self.window.undo()
        self.assertTrue(wait_until(self.app, lambda: all(os.path.exists(p) for p in doomed)
                                   and not self.service.jobs.busy))
        if getattr(self.window, "result_dialog", None):
            self.window.result_dialog.close()
        self.window.finish_wizard()
        self.assertIs(self.window.tabs.currentWidget(), self.window.catalog_page)

    def test_cataloguing_tab_planned_files_dragged_notes_and_label_folders(self):
        import shutil

        from sortzen.ui.catalog_page import COMING, PATH

        root = Path(self.dir.name) / "folders"
        shutil.copytree(shared_test_folders() / "Downloads", root / "Downloads")
        shutil.copytree(shared_test_folders() / "Sorted", root / "Sorted")
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None and not self.service.jobs.busy))
        self.window.tabs.setCurrentWidget(self.window.catalog_page)
        page = self.window.catalog_page
        self.assertIn("coming from the plan", page.summary.text())
        staffing = str(root / "Sorted" / "Documents" / "Work" / "Staffing")
        payroll = str(root / "Sorted" / "Documents" / "Work" / "Payroll")
        page.select(staffing)
        coming = [page.files.topLevelItem(i) for i in range(page.files.topLevelItemCount())
                  if page.files.topLevelItem(i).data(0, COMING)]
        self.assertTrue(coming)
        coming[0].setSelected(True)
        self.assertTrue(page.note_box.isVisible())
        path = coming[0].data(0, PATH)
        self.assertTrue(page.file_why.text())
        page.note_edit.setPlainText("an old applicant, keep for HR")
        page.note_file.emit(path, page.note_edit.toPlainText())
        self.assertEqual(self.service.file_note(path), "an old applicant, keep for HR")
        before = self.service.agreement()[1]
        self.window.place_in_category([path], payroll)                       # the plan changes; nothing moves
        self.assertTrue(os.path.exists(path))
        self.assertEqual(self.window.plan.for_path(path).destination, payroll)
        self.assertEqual(self.service.corrections()[path], payroll)
        self.assertEqual(self.service.agreement()[1], before + 1)          # SortZen's guess was checked
        page.select(payroll)
        self.assertIn(path, [page.files.topLevelItem(i).data(0, PATH) for i in range(page.files.topLevelItemCount())])
        self.window.undo()
        self.assertNotIn(path, self.service.corrections())

    def test_double_click_opens_files_and_folders_everywhere(self):
        from unittest import mock

        from PySide6.QtGui import QDesktopServices

        root = shared_test_folders()
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.window.refresh_folders()
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.plan is not None and not self.service.jobs.busy))
        opened = []
        with mock.patch.object(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True):
            def double_click(view, item):
                view.itemDoubleClicked.emit(item, 0)
                return os.path.normcase(os.path.normpath(opened[-1])) if opened else None

            def first_with(view, role, wanted=lambda v: v):
                stack = [view.topLevelItem(i) for i in range(view.topLevelItemCount())]
                while stack:
                    item = stack.pop(0)
                    if wanted(item.data(0, role)):
                        return item
                    stack += [item.child(i) for i in range(item.childCount())]
                return None

            source = self.window.sources_item.child(0)                      # the folder tree on the left
            self.assertEqual(double_click(self.window.tree, source), os.path.normcase(str(root / "Downloads")))
            self.assertFalse(self.window.tree.expandsOnDoubleClick())

            from sortzen.ui import folders_page, plan_page

            self.window.folders_page.set_counts(self.service.count_folders())
            item = first_with(self.window.folders_page.tree, folders_page.PATH, bool)
            self.assertEqual(double_click(self.window.folders_page.tree, item),
                             os.path.normcase(item.data(0, folders_page.PATH)))

            item = first_with(self.window.plan_page.tree, plan_page.ROW, lambda r: r is not None and not r.is_folder)
            self.assertEqual(double_click(self.window.plan_page.tree, item),
                             os.path.normcase(item.data(0, plan_page.ROW).path))

            from sortzen.ui.catalog_page import PATH as CATALOG_PATH

            page = self.window.catalog_page
            self.window.tabs.setCurrentWidget(page)
            payroll = str(root / "Sorted" / "Documents" / "Work" / "Payroll")
            page.select(payroll)
            self.assertEqual(double_click(page.tree, page.tree.currentItem()), os.path.normcase(payroll))
            file_row = page.files.topLevelItem(0)
            self.assertEqual(double_click(page.files, file_row), os.path.normcase(file_row.data(0, CATALOG_PATH)))

            wizard = self.window.to_place_page
            row = next(iter(wizard.items.values()))
            from sortzen.ui.to_place_page import PATH as WIZARD_PATH

            self.assertEqual(double_click(wizard.tree, row), os.path.normcase(row.data(0, WIZARD_PATH)))

            count = len(opened)
            self.window.open_folder(str(root / "Sorted" / "Not made yet"))      # not there: says so, opens nothing
            self.assertEqual(len(opened), count)
            self.assertIn("isn't there yet", self.window.statusBar().currentMessage())

    def test_folder_notes_from_the_window(self):
        root = shared_test_folders()
        self.service.add_destination(str(root / "Sorted"))
        self.window.refresh_folders()
        payroll = str(root / "Sorted" / "Documents" / "Work" / "Payroll")
        self.window.note_folder(payroll, "pay stubs, T4s, timesheets")
        self.assertEqual(self.service.folder_note(payroll), "pay stubs, T4s, timesheets")
        self.assertEqual(self.window.undo_action.text(), "Undo folder note")
        from sortzen.ui.dialogs import DestinationDialog
        dialog = DestinationDialog(self.window, [payroll], self.service.display, note=self.service.folder_note)
        self.assertIn("pay stubs, T4s, timesheets", dialog.list.item(0).text())
        dialog.close()
        self.window.undo()
        self.assertEqual(self.service.folder_note(payroll), "")

    def test_catalog_tab_edit_feedback_and_suggestions(self):
        import shutil

        from sortzen.engine.catalog_review import CatalogSuggestion

        root = Path(self.dir.name) / "folders"
        shutil.copytree(shared_test_folders() / "Sorted", root / "Sorted")
        self.service.add_destination(str(root / "Sorted"))
        self.window.tabs.setCurrentWidget(self.window.catalog_page)
        page = self.window.catalog_page
        self.assertIn("folders", page.summary.text())
        payroll = str(root / "Sorted" / "Documents" / "Work" / "Payroll")
        page.select(payroll)
        self.assertEqual(page.title.text(), "Payroll")
        self.window.hide_category(payroll, True)
        self.assertEqual(self.service.catalog_hidden(), [payroll])
        self.window.undo()
        self.assertEqual(self.service.catalog_hidden(), [])
        self.window.category_feedback(payroll, "too_broad", "stubs and timesheets mixed")
        page.select(payroll)
        self.assertIn("Too broad: split it (stubs and timesheets mixed)", page.details.text())
        self.window.accept_suggestion(CatalogSuggestion("new", payroll, "Add Timesheets", name="Timesheets",
                                                        note="weekly hours"))
        made = Path(payroll) / "Timesheets"
        self.assertTrue(made.is_dir())
        self.assertEqual(self.service.folder_note(str(made)), "weekly hours")
        self.window.undo()
        self.assertFalse(made.exists())
        budget = str(root / "Sorted" / "Documents" / "Work" / "Budget")
        files = len(os.listdir(budget))
        self.assertTrue(wait_until(self.app, lambda: not self.service.jobs.busy))
        self.window.run_job("count", lambda emit, token: time.sleep(1) or [])   # a count still running
        self.window.merge_category(budget, payroll, move_files=True)
        self.assertTrue(wait_until(self.app, lambda: getattr(self.window, "result_dialog", None) is not None))
        self.assertEqual(os.listdir(budget), [])
        self.assertEqual(self.service.catalog_edits()["merged"], {budget: payroll})
        self.window.result_dialog.accept()
        self.assertTrue(wait_until(self.app, lambda: not self.service.jobs.busy))
        from unittest import mock

        from PySide6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.window.undo()                                       # the move: files go back
        self.assertTrue(wait_until(self.app, lambda: len(os.listdir(budget)) == files and not self.service.jobs.busy))

    def test_catalog_files_dragged_deleted_and_folders_added(self):
        import shutil
        from unittest import mock

        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QDropEvent
        from PySide6.QtWidgets import QMessageBox

        from sortzen.ui.catalog_page import PATH, paths_from

        root = Path(self.dir.name) / "folders"
        shutil.copytree(shared_test_folders() / "Sorted", root / "Sorted")
        self.service.add_destination(str(root / "Sorted"))
        self.window.tabs.setCurrentWidget(self.window.catalog_page)
        page = self.window.catalog_page
        budget = str(root / "Sorted" / "Documents" / "Work" / "Budget")
        payroll = str(root / "Sorted" / "Documents" / "Work" / "Payroll")
        page.select(budget)
        self.assertTrue(page.files_title.text().startswith("Files in Budget"))
        self.assertEqual(page.files.topLevelItemCount(), len(self.service.category_files(budget)))
        page.files.topLevelItem(0).setSelected(True)
        page.files.topLevelItem(1).setSelected(True)
        chosen = page.files.selected_paths()
        mime = page.files.mimeData(page.files.selectedItems())
        self.assertEqual(sorted(paths_from(mime)), sorted(chosen))
        roots = [page.tree.topLevelItem(i) for i in range(page.tree.topLevelItemCount())]
        self.assertEqual(paths_from(page.tree.mimeData(roots)), [])            # added folders aren't dragged
        target = next(i for i in page._items() if i.data(0, PATH) == payroll)
        page.tree.scrollToItem(target)
        self.app.processEvents()
        where = QPointF(page.tree.visualItemRect(target).center())
        self.assertTrue(wait_until(self.app, lambda: not self.service.jobs.busy))
        drop = QDropEvent(where, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            page.tree.dropEvent(drop)
            self.assertTrue(wait_until(self.app, lambda: all(os.path.exists(os.path.join(payroll, os.path.basename(p)))
                                                             for p in chosen) and not self.service.jobs.busy))
        moved = os.path.join(payroll, os.path.basename(chosen[0]))
        self.assertEqual(self.service.corrections()[moved], payroll)            # remembered and learned from
        self.assertTrue(wait_until(self.app, lambda: self.window.undo_action.text() == "Undo put into a category"))
        self.window.undo()
        self.assertTrue(wait_until(self.app, lambda: all(os.path.exists(p) for p in chosen) and not self.service.jobs.busy))
        self.assertEqual(self.service.corrections(), {})
        if getattr(self.window, "result_dialog", None):
            self.window.result_dialog.close()
        self.assertTrue(wait_until(self.app, lambda: not self.service.jobs.busy))

        self.window.delete_files([chosen[0]], confirm=False)
        self.assertTrue(wait_until(self.app, lambda: not os.path.exists(chosen[0]) and not self.service.jobs.busy))
        self.assertTrue(wait_until(self.app, lambda: self.window.undo_action.text() == "Undo delete"))
        self.window.undo()
        self.assertTrue(wait_until(self.app, lambda: os.path.exists(chosen[0]) and not self.service.jobs.busy))
        if getattr(self.window, "result_dialog", None):
            self.window.result_dialog.close()

        extra = Path(self.dir.name) / "Photos"
        (extra / "Session one").mkdir(parents=True)
        page.tree.dropped_outside.emit([str(extra)])
        self.assertIn(str(extra), self.service.destination_folders())
        self.assertIn(str(extra), [c.path for c in self.service.catalog()])
        self.assertIs(self.window.tabs.currentWidget(), page)
        page.show_files.setChecked(False)
        self.assertFalse(page.files_panel.isVisible())

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


    def test_review_folders_dragged_and_too_many_folders_put_together(self):
        from unittest import mock

        from sortzen.engine.planner import TIDY
        from sortzen.ui.dialogs import GroupFoldersDialog

        base = Path(self.dir.name)
        downloads, sorted_ = base / "Downloads", base / "Sorted"
        for name in ("Tide Log-windows", "Tide Log-windows (1)", "Tide Log-windows (2)", "old tools"):
            (downloads / name).mkdir(parents=True)
            (downloads / name / f"{name} readme.txt").write_text(f"notes {name}")
        (sorted_ / "Programs").mkdir(parents=True)
        (sorted_ / "Programs" / "Paint helper.txt").write_text("program")
        self.service.add_source(str(downloads), TIDY)
        self.service.add_destination(str(sorted_))
        self.window.flow = self.service.new_session("Old versions")
        self.window._after_plan = "review"
        self.window.make_plan()
        self.assertTrue(wait_until(self.app, lambda: self.window.tabs.currentWidget() is self.window.review_page
                                   and not self.service.jobs.busy))
        review = self.window.review_page
        versions = [str(downloads / n) for n in ("Tide Log-windows", "Tide Log-windows (1)", "Tide Log-windows (2)")]
        review.tree.clearSelection()
        review.items[os.path.normcase(str(downloads))].setSelected(True)       # one folder: its look-alike folders

        def put_together(dialog):
            self.assertEqual(sorted(dialog.chosen()), versions)
            self.assertEqual(dialog.name(), "Tide Log-windows (old versions)")
            return 1

        with mock.patch.object(GroupFoldersDialog, "exec", put_together):
            review.group_button.click()
        new = str(downloads / "Tide Log-windows (old versions)")
        moving = self.window.flow.moving_folders()
        self.assertEqual({moving[os.path.normcase(v)].destination for v in versions}, {new})
        self.assertEqual(review.items[os.path.normcase(new)].childCount(), 3)   # shown where they go
        review.dropped([str(downloads / "old tools")], str(sorted_ / "Programs"))
        self.assertEqual(moving and self.window.flow.moving_folders()[os.path.normcase(str(downloads / "old tools"))]
                         .destination, str(sorted_ / "Programs"))
        self.window.undo()
        self.assertNotIn(os.path.normcase(str(downloads / "old tools")), self.window.flow.moving_folders())

    def test_right_click_open_containing_folder_and_delete_everywhere(self):
        from unittest import mock

        from PySide6.QtWidgets import QMenu

        from sortzen.ui import opening

        file = Path(self.dir.name) / "Downloads" / "Lakeview lease.docx"
        file.parent.mkdir(parents=True)
        file.write_text("lease")
        menu = QMenu()
        opening.add_file_actions(menu, [str(file)])
        texts = [a.text() for a in menu.actions() if a.text()]
        self.assertEqual(texts[:2], ["Open", "Open containing folder"])
        self.assertTrue(texts[2].startswith("Delete"))
        with mock.patch.object(self.window, "delete_files") as delete:
            opening.set_handlers(self.window._report, delete)
            menu = QMenu()
            opening.add_file_actions(menu, [str(file)])
            next(a for a in menu.actions() if a.text().startswith("Delete")).trigger()
            delete.assert_called_once_with([str(file)])
        opening.set_handlers(self.window._report, self.window.delete_files)
        with mock.patch("sortzen.ui.opening.QDesktopServices.openUrl") as opened, \
                mock.patch("sortzen.ui.opening.sys.platform", "linux"):
            self.assertTrue(opening.show_in_folder(str(file)))
            self.assertTrue(opening.open_path(str(file)))
        self.assertEqual(opened.call_count, 2)
        self.assertIn("Opening", self.window.statusBar().currentMessage())
        self.assertFalse(opening.open_path(str(file) + ".gone"))

        facts = self.service.file_facts([str(file)])[str(file)]
        self.assertEqual((facts.kind, facts.size), ("Word", 5))
        self.assertGreater(facts.added, 0)

    def test_rules_change_in_a_dialog_from_suggestions_review_and_settings(self):
        import shutil
        from unittest import mock

        from sortzen.engine.rules import Rule
        from sortzen.services.app_service import LabelFolderSuggestion
        from sortzen.services.flow import Learned
        from sortzen.ui.dialogs import RuleDialog

        root = Path(self.dir.name) / "folders"
        shutil.copytree(shared_test_folders() / "Downloads", root / "Downloads")
        shutil.copytree(shared_test_folders() / "Sorted", root / "Sorted")
        self.service.add_source(str(root / "Downloads"))
        self.service.add_destination(str(root / "Sorted"))
        self.service.add_label("Programs")
        rule = Rule("", str(root / "Downloads" / "older downloads"), label="Programs")
        dialog = RuleDialog(self.window, self.service, rule)
        self.assertIn("Files labelled “Programs” go to Downloads/older downloads", dialog.preview.text())
        dialog.folder.box.setEditText("Downloads/Program projects/Tide Log")       # a folder still to be made
        self.assertIn("go to Downloads/Program projects/Tide Log", dialog.preview.text())
        dialog.accept()
        target = str(root / "Downloads" / "Program projects" / "Tide Log")
        self.assertEqual(dialog.chosen.destination, target)

        self.window.plan_button.click()                                    # the banner in Step 3
        wizard = self.window.wizard
        wizard.choose.refresh()
        wizard.next_button.click()
        self.assertTrue(wait_until(self.app, lambda: wizard.stack.currentWidget() is not wizard.choose
                                   and not self.service.jobs.busy))
        wizard.show_catalog()
        page = wizard.catalog
        page._show_learned(Learned(folder=LabelFolderSuggestion(rule, "Files labelled “Programs” go to …", "why", 20)))
        self.assertTrue(page.banner_change.isVisible())

        def chose(dialog_self):
            dialog_self.chosen = dialog.chosen
            return 1

        with mock.patch.object(RuleDialog, "exec", chose):
            page.banner_change.click()
        self.assertEqual([r.destination for r in self.service.rules()], [target])
        self.assertIn(rule.key, self.service.settings.get("declined_rules"))  # the suggestion isn't offered again
        self.assertFalse(page.banner.isVisible())
        self.window.undo()
        self.assertEqual(self.service.rules(), [])
        wizard.close()

        from sortzen.ui.settings_window import SettingsWindow

        self.service.add_rule(rule)
        settings = SettingsWindow(self.window, self.service, "Rules")
        settings.rules.setCurrentRow(0)
        with mock.patch.object(RuleDialog, "exec", chose):
            settings._change_rule()
        self.assertIn("Tide Log", settings.rules.item(0).text())
        settings.accept()
        self.assertEqual([r.destination for r in self.service.rules()], [target])

    def test_organizing_session_wizard_review_and_move(self):
        import shutil
        from unittest import mock

        from sortzen.ui.review_page import KIND

        root = Path(self.dir.name) / "folders"
        shutil.copytree(shared_test_folders() / "Downloads", root / "Downloads")
        shutil.copytree(shared_test_folders() / "Sorted", root / "Sorted")
        self.assertIn("No sessions yet", self.window.sessions_list.itemAt(0).widget().text())
        self.window.plan_button.click()                                     # Start the wizard
        wizard = self.window.wizard
        self.assertIs(wizard.stack.currentWidget(), wizard.choose)
        self.assertFalse(wizard.next_button.isEnabled())                    # a folder to sort first
        self.window.add_source(str(root / "Downloads"), mode="sort into other folders")
        self.window.add_destination(str(root / "Sorted"))
        wizard.choose.refresh()
        ideas = [b.text() for b in wizard.choose.findChildren(QPushButton, "smallChip")]
        self.assertIn("+ Work", ideas)
        next(b for b in wizard.choose.findChildren(QPushButton, "smallChip") if b.text() == "+ Screenshots").click()
        self.assertEqual(self.service.labels(), ["Screenshots"])
        wizard.choose.name.setText("Downloads clean-up")
        wizard.choose.level.setValue(95)
        wizard.next_button.click()
        self.assertTrue(wait_until(self.app, lambda: wizard.stack.currentWidget() is wizard.duplicates
                                   and not self.service.jobs.busy))
        self.assertEqual(self.service.autonomy(), 95)
        self.assertIn("Downloads clean-up", [s.name for s, _ in self.service.recent_sessions()])
        extras = wizard.flow.ticked_copies()
        self.assertTrue(wizard.next_button.text().startswith(f"Next: {extras} cop"))
        wizard.next_button.click()                                          # the extras go at once
        self.assertTrue(wait_until(self.app, lambda: wizard.stack.currentWidget() is wizard.catalog
                                   and not self.service.jobs.busy))
        self.assertEqual(wizard.flow.session.copies_queued, extras)
        page = wizard.catalog
        first = page.batch
        self.assertEqual(first.labels[0][0], "Screenshots")
        self.assertIn("Batch 1 of", wizard.steps.count.text())
        page._tick_all(False)
        self.assertFalse(wizard.next_button.isEnabled())                    # nothing ticked
        page._tick_all(True)
        wizard.next_button.click()                                          # Confirm and next batch
        self.assertEqual(self.service.labels_of(first.paths[0]), ["Screenshots"])
        self.assertIn("Batch 2 of", wizard.steps.count.text())
        wizard.back_button.click()                                          # Back shows it again
        self.assertEqual(page.batch.paths, first.paths)
        wizard.next_button.click()
        while page.batch is not None and page.batch.labels:
            wizard.next_button.click()
        if page.batch is not None:                                          # no guess: type a label
            self.assertFalse(wizard.next_button.isEnabled())
            page.typed.setText("Phone pictures")
            self.assertTrue(wizard.next_button.isEnabled())
            done = page.batch
            wizard.next_button.click()
            self.assertIn("Phone pictures", self.service.labels())
            self.assertEqual(self.service.labels_of(done.paths[0]), ["Phone pictures"])
        file = wizard.flow.session.file
        wizard.close()                                                      # stop, then carry on later
        self.assertTrue(wait_until(self.app, lambda: self.window.wizard is None))
        self.window.open_session(file)
        self.assertTrue(wait_until(self.app, lambda: self.window.wizard is not None and not self.service.jobs.busy
                                   and self.window.wizard.stack.currentWidget() is self.window.wizard.catalog))
        wizard = self.window.wizard
        while wizard.isVisible() and wizard.catalog.batch is not None:
            wizard.skip_button.click()
        self.assertTrue(wait_until(self.app, lambda: self.window.tabs.currentWidget() is self.window.review_page
                                   and not self.service.jobs.busy))
        self.assertEqual([self.window.tabs.tabText(i) for i in range(self.window.tabs.count())], ["Review"])
        self.window.show_tab(self.window.folders_page)                      # tabs open again from View
        self.assertEqual(self.window.tabs.count(), 2)
        self.window.show_tab(self.window.review_page)

        review = self.window.review_page
        flow = self.window.flow
        i = next(i for i, r in enumerate(flow.review) if not flow.is_reviewed(r) and r.batch.paths)
        review.show_batch(i)
        path = flow.review[i].batch.paths[0]
        self.assertIn("SELECTED FILE", review.details_caption.text())
        review.tree.clearSelection()
        review.items[os.path.normcase(os.path.abspath(str(root / "Sorted")))].setSelected(True)
        new = review.new_folder("Jordan")
        self.assertIn(os.path.normcase(new), review.items)
        self.assertEqual(review.items[os.path.normcase(new)].data(0, KIND), "folder")
        review.dropped([path], new)                                         # dragged in the tree
        self.assertEqual(flow.plan.for_path(path).destination, new)
        self.assertEqual(self.service.corrections()[path], new)
        self.window.undo()
        self.assertNotEqual(flow.plan.for_path(path).destination, new)
        self.assertTrue(wait_until(self.app, lambda: not self.service.jobs.busy))      # the folder count after Undo
        with mock.patch("sortzen.ui.move_dialogs.ConfirmMoveDialog.exec", return_value=1):
            while not self.service.jobs.busy and getattr(self.window, "result_dialog", None) is None:
                review.confirm_button.click()
        self.assertTrue(wait_until(self.app, lambda: not self.service.jobs.busy
                                   and getattr(self.window, "result_dialog", None) is not None))
        moved = flow.session.moved
        self.assertGreater(moved, 0)
        self.assertFalse(os.path.exists(path))                              # a confirmed file has moved
        self.window.result_dialog.close()
        self.assertTrue(wait_until(self.app, lambda: self.window.tabs.currentWidget() is self.window.start_page))
        self.assertEqual(self.service.recent_sessions()[0][1], f"Moved · {moved:,} files")


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
        from sortzen.ui.progress_window import TIP_SECONDS

        self.assertEqual(window.tip_timer.interval(), TIP_SECONDS * 1000)
        self.assertGreaterEqual(TIP_SECONDS, 15)
        shown = [window.tip.text()]
        for _ in range(5):
            window.next_button.click()
            shown.append(window.tip.text())
        self.assertEqual(len(set(shown)), 6)                # Next always shows something new
        self.assertTrue(all(t.startswith(("Tip: ", "Did you know? ")) for t in shown))
        self.assertTrue(any(t.startswith("Did you know? ") for t in shown))
        stopped = []
        window.stop.connect(lambda: stopped.append(True))
        window.stop_button.click()
        self.assertEqual(stopped, [True])
        self.assertFalse(window.stop_button.isEnabled())
        window.finish()
