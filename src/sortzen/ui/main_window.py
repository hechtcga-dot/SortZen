"""The workspace window: folder tree on the left; Start, Folders, To place, Plan and Copies tabs on the right."""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QInputDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSplitter, QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..config import APP_NAME, APP_TAGLINE, APP_VERSION
from ..engine.planner import SORT_OUT, TIDY
from ..services import AppService
from ..services.app_service import FolderError
from ..tasks import Estimate, JobFailed, JobFinished, Log, Progress, Status
from . import theme
from .bridge import EventBridge
from .ai_dialog import AskAIDialog
from .catalog_page import CatalogPage
from .copies_page import CopiesPage
from .dialogs import MODE_TEXT, DestinationDialog, MissingFoldersDialog, ModeDialog
from .folders_page import FoldersPage
from .icons import app_icon
from .move_dialogs import ConfirmMoveDialog, MoveResultDialog, RunsDialog
from .plan_page import PlanPage
from .progress_window import ProgressWindow
from .settings_window import SettingsWindow
from .sortable import human_size
from .to_place_page import ToPlacePage

STEPS = (
    ("Add folders", "Choose the messy folders to sort and the folders files may go to. "
                    "SortZen reads nothing outside them."),
    ("Make a plan", "SortZen reads the files on this PC, learns from the folders you've already sorted, and asks "
                    "about anything it can't settle."),
    ("Check the plan", "Every file and folder gets a destination and a percentage showing how sure "
                       "SortZen is, with the reasons. Anything below your chosen level waits in Review."),
    ("Move", "Tick what should move and confirm. Every move is written down, so Edit › Undo puts everything "
             "back."),
)
FOLDER = Qt.ItemDataRole.UserRole
log = logging.getLogger("sortzen")


class MainWindow(QMainWindow):
    def __init__(self, service: AppService | None = None):
        super().__init__()
        self.service = service or AppService()
        self.bridge = EventBridge(self)
        self.bridge.event.connect(self._on_job_event)
        self.plan = None
        self.progress: ProgressWindow | None = None
        self.undo_stack: list[tuple[str, object]] = []
        self._plan_waiting = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1200, 760)

        body = QWidget(objectName="ground")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        self.splitter.addWidget(self._tree_panel())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.start_page = self._start_page()
        self.tabs.addTab(self.start_page, "Start")
        self.folders_page = FoldersPage(self.service)
        self.folders_page.add_source.connect(self.add_source)
        self.folders_page.add_destination.connect(self.add_destination)
        self.folders_page.add_windows.connect(self.add_windows_folders)
        self.folders_page.recount.connect(self.count_folders)
        self.folders_page.leave_out.connect(self.leave_out)
        self.folders_page.remove_folder.connect(self.remove_folder)
        self.folders_page.set_mode.connect(self.set_mode)
        self.folders_page.open_folder.connect(self.open_folder)
        self.folders_page.note_folder.connect(self.note_folder)
        self.tabs.addTab(self.folders_page, "Folders")
        self.catalog_page = CatalogPage(self.service)
        for signal, slot in ((self.catalog_page.rename, self.rename_category),
                             (self.catalog_page.add_subcategory, self.add_subcategory),
                             (self.catalog_page.note, self.note_category),
                             (self.catalog_page.add_folder, self.add_category_folder),
                             (self.catalog_page.merge, self.merge_category),
                             (self.catalog_page.hide, self.hide_category),
                             (self.catalog_page.feedback, self.category_feedback),
                             (self.catalog_page.accept, self.accept_suggestion),
                             (self.catalog_page.decline, self.decline_suggestion),
                             (self.catalog_page.ask_ai, self.ask_ai_about_catalog)):
            signal.connect(slot)
        self.tabs.addTab(self.catalog_page, "Catalog")
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget() is self.catalog_page
                                         and self.catalog_page.refresh())
        self.to_place_page = ToPlacePage(self.service)
        self.to_place_page.save.connect(self.save_answers)
        self.to_place_page.place_group.connect(self.place_group)
        self.plan_page = PlanPage(self.service)
        self.plan_page.change_destination.connect(self.change_destination)
        self.plan_page.leave_in_place.connect(self.leave_in_place)
        self.plan_page.forget_choice.connect(self.forget_choice)
        self.plan_page.open_folder.connect(self.open_folder)
        self.plan_page.update_plan.connect(self.make_plan)
        self.plan_page.export.connect(self.export_plan)
        self.plan_page.move_ticked.connect(self.move_rows)
        self.plan_page.ask_ai.connect(self.ask_ai)
        self.plan_page.move_to.connect(self.correct)
        self.plan_page.rename_folder.connect(self.rename_folder)
        self.plan_page.note_folder.connect(self.note_folder)
        self.copies_page = CopiesPage(self.service)
        self.copies_page.queue.connect(self.queue_copies)
        self.copies_page.open_folder.connect(self.open_folder)
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 920])
        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(body)

        self._actions()
        self.refresh_folders()
        self.statusBar().showMessage("Ready")

    # ---------------------------------------------------------------- layout
    def _header(self) -> QFrame:
        header = QFrame(objectName="header")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 8, 14, 8)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(26, 26))
        row.addWidget(icon)
        row.addWidget(QLabel(APP_NAME, objectName="appName"))
        row.addWidget(QLabel(f"{APP_VERSION} alpha", objectName="versionPill"))
        row.addStretch(1)
        return header

    def _tree_panel(self) -> QFrame:
        panel = QFrame(objectName="tree")
        panel.setMinimumWidth(230)
        col = QVBoxLayout(panel)
        col.setContentsMargins(8, 10, 8, 10)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.sources_item = self._tree_group("Source folders", "Messy folders to sort")
        self.destinations_item = self._tree_group("Destination folders", "Where files may go")
        col.addWidget(self.tree, 1)
        footer = QLabel("SortZen only reads the folders listed here. Right-click to add, change or remove.",
                        objectName="treeFooter")
        footer.setWordWrap(True)
        col.addWidget(footer)
        return panel

    def _tree_group(self, title: str, hint: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.tree, [title])
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setToolTip(0, hint)
        item.setExpanded(True)
        return item

    def _start_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(28, 24, 28, 24)
        col.setSpacing(14)
        title = QLabel("Sort a messy folder", objectName="pageTitle")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(title)
        intro = QLabel("SortZen moves files from folders like Downloads into the right place, learns how you sort, "
                       "and only asks an AI service about files it can't place by itself.", objectName="muted")
        intro.setWordWrap(True)
        intro.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(intro)
        card = QFrame(objectName="card")
        steps = QVBoxLayout(card)
        steps.setContentsMargins(18, 16, 18, 16)
        steps.setSpacing(12)
        for number, (name, text) in enumerate(STEPS, start=1):
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(QLabel(str(number), objectName="stepNumber"), 0, Qt.AlignmentFlag.AlignTop)
            words = QVBoxLayout()
            words.setSpacing(2)
            words.addWidget(QLabel(name, objectName="cardTitle"))
            detail = QLabel(text, objectName="hint")
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            words.addWidget(detail)
            row.addLayout(words, 1)
            steps.addLayout(row)
        col.addWidget(card)
        buttons = QHBoxLayout()
        add_source = QPushButton("Add a folder to sort…")
        add_source.clicked.connect(self.add_source)
        add_destination = QPushButton("Add a destination folder…")
        add_destination.clicked.connect(self.add_destination)
        self.windows_button = QPushButton("Use my Windows folders")
        self.windows_button.setToolTip("Adds Documents, Pictures, Music and Videos as destination folders")
        self.windows_button.clicked.connect(self.add_windows_folders)
        self.plan_button = QPushButton("Make a plan", objectName="primary")
        self.plan_button.clicked.connect(self.make_plan)
        for b in (add_source, add_destination, self.windows_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.plan_button)
        col.addLayout(buttons)
        self.start_hint = QLabel(objectName="hint")
        self.start_hint.setWordWrap(True)
        col.addWidget(self.start_hint)
        col.addStretch(1)
        return page

    def _actions(self) -> None:
        def action(text, slot, shortcut=None, tip=""):
            a = QAction(text, self, triggered=slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setToolTip(tip)
                a.setStatusTip(tip)
            return a

        self.add_source_action = action("Add folder to sort…", self.add_source, "Ctrl+O",
                                        "Add a messy folder, like Downloads")
        self.add_destination_action = action("Add destination folder…", self.add_destination, "Ctrl+D",
                                             "Add a folder files may go to, like Documents")
        self.plan_action = action("Make a plan", self.make_plan, "F5", "Read the folders and plan where everything goes")
        self.export_action = action("Export plan to Excel…", self.export_plan, "Ctrl+E",
                                    "Save the plan as an Excel workbook")
        self.undo_action = action("Undo", self.undo, QKeySequence.StandardKey.Undo, "Undo the last change")
        self.runs_action = action("Undo a move…", self.show_runs, tip="Put back the files from an earlier move")
        self.settings_action = action("Settings…", self.show_settings, "Ctrl+,",
                                      "Autonomy, AI service, privacy and advanced options")
        self.export_action.setEnabled(False)
        self.undo_action.setEnabled(False)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        for a in (self.add_source_action, self.add_destination_action, self.plan_action, self.export_action,
                  self.undo_action):
            toolbar.addAction(a)
        self.addToolBar(toolbar)

        file_menu = self.menuBar().addMenu("&File")
        for a in (self.add_source_action, self.add_destination_action):
            file_menu.addAction(a)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(action("Save profile…", self.save_profile,
                                   tip="Save your folders, choices, answers and settings to a file"))
        file_menu.addAction(action("Load profile…", self.load_profile,
                                   tip="Use the folders, choices, answers and settings saved in a profile"))
        file_menu.addSeparator()
        file_menu.addAction(QAction("E&xit", self, shortcut=QKeySequence.StandardKey.Quit, triggered=self.close))
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.runs_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.settings_action)
        plan_menu = self.menuBar().addMenu("&Plan")
        plan_menu.addAction(self.plan_action)
        self.ai_action = action("Ask AI about unsure files…", self.ask_ai,
                                tip="Ask an AI service about the files SortZen couldn't place by itself")
        self.ai_action.setEnabled(False)
        plan_menu.addAction(self.ai_action)
        self.copies_action = action("Copies…", lambda: self.tabs.setCurrentWidget(self.copies_page),
                                    tip="Exact copies found while making the plan")
        self.copies_action.setEnabled(False)
        plan_menu.addAction(self.copies_action)
        plan_menu.addAction(action("Catalog", lambda: self.tabs.setCurrentWidget(self.catalog_page),
                                   tip="Your categories: see, edit and comment on them"))
        view_menu = self.menuBar().addMenu("&View")
        self.tree_action = QAction("Show folder tree", self, checkable=True, checked=True)
        self.tree_action.toggled.connect(lambda on: self.splitter.widget(0).setVisible(on))
        view_menu.addAction(self.tree_action)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(action("Open the activity log", self.open_log, tip="What SortZen did, and any problems"))
        help_menu.addAction(action("Copy diagnostic info", self.copy_diagnostics,
                                   tip="Copy details for reporting a problem (no file or folder names)"))
        help_menu.addSeparator()
        help_menu.addAction(QAction(f"About {APP_NAME}", self, triggered=self.show_about))

    def show_about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME} {APP_VERSION}</b> (alpha)<br>{APP_TAGLINE}<br><br>"
                          "Sorts messy folders into the right place. Local first; AI is optional. "
                          "Nothing moves until you confirm, and every move can be undone.")

    # ---------------------------------------------------------------- the catalog
    def _catalog_change(self, text: str, change, undo_extra=None) -> None:
        """Make a catalog change that Undo puts back (settings, and anything ``undo_extra`` undoes)."""
        before = self.service.settings_snapshot()
        try:
            result = change()
        except ValueError as exc:
            QMessageBox.warning(self, "Catalog", str(exc))
            return
        def undo():
            self.service.restore_settings(before)
            if undo_extra:
                undo_extra(result)
        self._push_undo(text, undo)
        self.catalog_page.refresh()
        self.statusBar().showMessage(f"{text}. Update the plan to use it.", 6000)

    def _category(self, path: str):
        return next((c for c in self.service.catalog() if c.path == path), None)

    def rename_category(self, path: str, name: str | None = None, folder_too: bool | None = None) -> None:
        c = self._category(path)
        if c is None:
            return
        if name is None:
            name, ok = QInputDialog.getText(self, "Rename category", f"New name for “{c.name}”:", text=c.name)
            if not ok or not name.strip():
                return
        if folder_too is None:
            folder_too = QMessageBox.question(
                self, "Rename category", f"Rename the folder on disk to “{name.strip()}” too?\n\nYes renames the "
                "folder (Undo puts the old name back). No changes only the name shown in the catalog.") \
                == QMessageBox.StandardButton.Yes
        if folder_too:
            if self.rename_folder(path, name, confirm=False):
                self.catalog_page.refresh()
            return
        self._catalog_change("Rename category", lambda: self.service.rename_category(path, name))

    def add_subcategory(self, path: str, name: str | None = None, note: str | None = None) -> None:
        if name is None:
            name, ok = QInputDialog.getText(self, "Add a subcategory", "Name of the new subcategory:")
            if not ok or not name.strip():
                return
            note, _ = QInputDialog.getText(self, "Add a subcategory",
                                           f"What belongs in “{name.strip()}”? (optional, e.g. pay stubs, T4s)")
        self._catalog_change("Add a subcategory", lambda: self.service.add_subcategory(path, name, note or ""),
                             self.service.remove_empty_subcategory)

    def note_category(self, path: str) -> None:
        self.note_folder(path)
        self.catalog_page.refresh()

    def add_category_folder(self, path: str, other: str | None = None) -> None:
        if other is None:
            other = QFileDialog.getExistingDirectory(self, "Another folder for this category")
            if not other:
                return
        self._catalog_change("Add a folder to a category", lambda: self.service.add_category_folder(path, other))

    def hide_category(self, path: str, hidden: bool) -> None:
        self._catalog_change("Don't put files here" if hidden else "Put files here again",
                             lambda: self.service.set_category_hidden(path, hidden))

    def category_feedback(self, path: str, kind: str, text: str | None = None) -> None:
        if text is None and kind in ("comment", "wrong_name", "too_broad", "too_narrow"):
            prompt = {"comment": "What should change about this category?",
                      "wrong_name": "What would be a better name? (optional)",
                      "too_broad": "What is mixed together in it? (optional)",
                      "too_narrow": "Where do its files belong? (optional)"}[kind]
            text, ok = QInputDialog.getText(self, "Feedback", prompt)
            if not ok or (kind == "comment" and not text.strip()):
                return
        self._catalog_change("Feedback", lambda: self.service.category_feedback(path, kind, text or ""))
        if kind == "wrong_name" and text and text.strip():
            self.rename_category(path, text.strip())

    def merge_category(self, path: str, into: str | None = None, move_files: bool | None = None) -> None:
        categories = [c for c in self.service.catalog() if c.path != path and not c.merged_into]
        if into is None:
            labels = [self.service.display(c.path) for c in categories]
            chosen, ok = QInputDialog.getItem(self, "Merge into", "Files for this category go to:", labels, 0, False)
            if not ok:
                return
            into = categories[labels.index(chosen)].path
        requests = self.service.merge_files(path, into)
        if move_files is None and requests:
            move_files = QMessageBox.question(
                self, "Merge category", f"Also move the {len(requests):,} files and folders in it into "
                f"{self.service.display(into)} now?\n\nNo merges future files only. Every move can be undone.") \
                == QMessageBox.StandardButton.Yes
        self._catalog_change("Merge category", lambda: self.service.merge_category(path, into))
        if move_files and requests:
            self._reorganize(requests)

    def _reorganize(self, requests) -> None:
        if not self._free_for_job():
            return
        self.progress = ProgressWindow(self, "Reorganizing the catalog", estimate=max(2.0, len(requests) / 50))
        self.progress.stop.connect(self.service.stop_job)
        self.progress.show()
        self.run_job("catalog-move", lambda emit, token: self.service.reorganize(requests, emit, token))

    def accept_suggestion(self, s, confirm: bool = True) -> None:
        if s.kind == "rename":
            self.rename_category(s.category, s.name, folder_too=False)
        elif s.kind == "merge":
            self.merge_category(s.category, s.into, None if confirm else True)
        elif s.kind == "new":
            self.add_subcategory(s.category, s.name, s.note)
        elif s.kind == "empty":
            self.hide_category(s.category, True)
        elif s.kind == "split":
            requests = self.service.split_requests(s)
            if confirm and QMessageBox.question(
                    self, "Split category", f"Make {len(s.parts)} subfolders in “{os.path.basename(s.category)}” "
                    f"({', '.join(n for n, _ in s.parts)}) and move {len(requests):,} files into them?\n\n"
                    "Every move can be undone.") != QMessageBox.StandardButton.Yes:
                return
            self._reorganize(requests)
        self.service.decline_suggestion(s)          # done: not suggested again
        self.catalog_page.refresh()

    def decline_suggestion(self, s) -> None:
        self.service.decline_suggestion(s)
        self.catalog_page.refresh()

    def ask_ai_about_catalog(self, confirm: bool = True) -> None:
        if not self._free_for_job():
            return
        if not self.service.ai_ready():
            QMessageBox.information(self, APP_NAME, "Choose an AI service and its key first (Edit › Settings › AI).")
            return
        estimate = self.service.catalog_ai_estimate()
        money = "free: it runs on this PC" if estimate["local"] else f"about ${estimate['cost']:.4f}"
        if confirm and QMessageBox.question(
                self, "Ask AI to review the catalog",
                f"Send {estimate['service']} the names of your {estimate['categories']:,} categories, their file "
                f"counts and notes, a few example file names (long numbers removed) and your feedback? No file "
                f"contents are sent.\n\nCost: {money}.") != QMessageBox.StandardButton.Yes:
            return
        self.progress = ProgressWindow(self, "Asking the AI service about the catalog")
        self.progress.show()
        self.run_job("catalog-ai", lambda emit, token: self.service.ask_ai_about_catalog(emit, token))

    # ---------------------------------------------------------------- settings, profiles, help
    def show_settings(self, tab: str = "General") -> None:
        before = self.service.settings_snapshot()
        if SettingsWindow(self, self.service, tab).exec():
            self._push_undo("Settings", lambda: self.service.restore_settings(before))
            self._settings_changed()

    def _settings_changed(self) -> None:
        if self.plan is not None:
            self.plan_page.sync_settings()

    def save_profile(self) -> None:
        target, _ = QFileDialog.getSaveFileName(self, "Save a profile", "SortZen profile.szprofile",
                                                "SortZen profile (*.szprofile)")
        if not target:
            return
        keys = False
        if any(self.service.has_api_key(k) for k in ("gemini", "claude", "openai", "openrouter")):
            keys = QMessageBox.question(
                self, "Save a profile", "Include your saved API keys?\n\nAnyone with the file could use them and "
                "spend on your account. Choose No to enter them again after loading.",
                defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        try:
            self.service.save_profile(target, keys)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"The profile couldn't be saved: {exc}")
            return
        self.statusBar().showMessage(f"Profile saved to {target}", 6000)

    def load_profile(self, path: str | None = None, moved=None, dropped=None) -> None:
        if self._moving():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Load a profile", "", "SortZen profile (*.szprofile)")
            if not path:
                return
        try:
            loaded = self.service.read_profile(path)
        except ValueError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        missing = self.service.missing_folders(loaded)
        if missing and moved is None:
            dialog = MissingFoldersDialog(self, missing)
            if not dialog.exec():
                return
            moved, dropped = dialog.moved, dialog.dropped
        before = self.service.load_profile(loaded, moved or {}, dropped or [])
        self._push_undo("Load profile", lambda: self.service.restore_settings(before))
        self._forget_plan()
        self.refresh_folders()
        self.statusBar().showMessage("Profile loaded. Make a plan to use it.", 8000)

    def _forget_plan(self) -> None:
        """The plan belongs to the folders it was made for; drop it when they change wholesale."""
        self.plan = None
        for page in (self.plan_page, self.to_place_page, self.copies_page):
            if self.tabs.indexOf(page) >= 0:
                self.tabs.removeTab(self.tabs.indexOf(page))
        self.export_action.setEnabled(False)
        self.ai_action.setEnabled(False)
        self.copies_action.setEnabled(False)

    def open_log(self) -> None:
        path = self.service.log_path()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.exists() else path.parent)))

    def copy_diagnostics(self) -> None:
        QApplication.clipboard().setText(self.service.diagnostics())
        self.statusBar().showMessage("Diagnostic info copied. It has no file or folder names in it.", 6000)

    # ---------------------------------------------------------------- folders
    def count_folders(self) -> None:
        """Count files in the background (nothing is opened) for the Folders tab."""
        if self.service.jobs.busy or not self.service.all_roots():
            if not self.service.all_roots():
                self.folders_page.set_counts([])
            return
        self.folders_page.show_counting()
        self.run_job("count", lambda emit, token: self.service.count_folders())

    def leave_out(self, paths: list, out: bool) -> None:
        previous = self.service.set_left_out(paths, out)
        self._push_undo("Leave out" if out else "Include again", lambda: self.service.restore_left_out(previous))
        self.folders_page.refresh_ticks()
        word = "Left out" if out else "Included again"
        self.statusBar().showMessage(f"{word}: {len(paths)} item{'s' if len(paths) != 1 else ''}. "
                                     "Update the plan to see the effect.", 6000)

    def refresh_folders(self) -> None:
        for group in (self.sources_item, self.destinations_item):
            group.takeChildren()
        muted = QColor(theme.MUTED)
        for f in self.service.source_folders():
            mode = "tidy" if f["mode"] == TIDY else "sort out"
            item = QTreeWidgetItem(self.sources_item, [f"{os.path.basename(f['path']) or f['path']}  ·  {mode}"])
            item.setToolTip(0, f"{f['path']}\n{MODE_TEXT[f['mode']][1]}")
            item.setData(0, FOLDER, ("source", f["path"]))
        for d in self.service.destination_folders():
            item = QTreeWidgetItem(self.destinations_item, [os.path.basename(d) or d])
            item.setToolTip(0, d)
            item.setData(0, FOLDER, ("destination", d))
        for group, empty in ((self.sources_item, "No folders added yet"), (self.destinations_item, "No folders added yet")):
            if not group.childCount():
                hint = QTreeWidgetItem(group, [empty])
                hint.setFlags(Qt.ItemFlag.NoItemFlags)
                hint.setForeground(0, muted)
        self.count_folders()
        has_sources = bool(self.service.source_folders())
        suggested = self.service.suggested_destinations()
        self.windows_button.setVisible(bool(suggested))
        self.plan_button.setEnabled(has_sources)
        self.plan_action.setEnabled(has_sources)
        if not has_sources:
            self.start_hint.setText("Start by adding a folder to sort, such as Downloads.")
        elif not self.service.destination_folders():
            self.start_hint.setText("Add destination folders too, or tidy a folder in place. "
                                    "“Use my Windows folders” adds Documents, Pictures, Music and Videos.")
        else:
            self.start_hint.setText("Ready to make a plan. Making one moves nothing: you see the plan first.")

    def _tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        data = item.data(0, FOLDER) if item else None
        if data:
            kind, path = data
            if kind == "source":
                current = next((f["mode"] for f in self.service.source_folders() if f["path"] == path), SORT_OUT)
                for mode, (title, _) in MODE_TEXT.items():
                    a = menu.addAction(title, lambda m=mode: self.set_mode(path, m))
                    a.setCheckable(True)
                    a.setChecked(mode == current)
                menu.addSeparator()
            menu.addAction("Open in Explorer", lambda: self.open_folder(path))
            menu.addAction("Remove from SortZen", lambda: self.remove_folder(path))
        else:
            menu.addAction(self.add_source_action)
            menu.addAction(self.add_destination_action)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def add_source(self, folder: str | None = None, mode: str | None = None) -> None:
        folder = folder or QFileDialog.getExistingDirectory(self, "Choose a folder to sort")
        if not folder:
            return
        if mode is None:
            guess = SORT_OUT if "download" in os.path.basename(folder).lower() else TIDY
            dialog = ModeDialog(self, folder, guess)
            if not dialog.exec():
                return
            mode = dialog.mode()
        self._try(lambda: self.service.add_source(folder, mode), f"Remove {os.path.basename(folder)}",
                  lambda path: self.service.remove_folder(path))

    def add_destination(self, folder: str | None = None) -> None:
        folder = folder or QFileDialog.getExistingDirectory(self, "Choose a destination folder")
        if folder:
            self._try(lambda: self.service.add_destination(folder), f"Remove {os.path.basename(folder)}",
                      lambda path: self.service.remove_folder(path))

    def add_windows_folders(self) -> None:
        added = []
        for folder in self.service.suggested_destinations():
            added.append(self.service.add_destination(folder))
        if added:
            self._push_undo("Add Windows folders", lambda: [self.service.remove_folder(p) for p in added])
        self.refresh_folders()

    def _try(self, work, undo_text, undo) -> None:
        try:
            path = work()
        except FolderError as exc:
            QMessageBox.information(self, APP_NAME, str(exc))
            return
        self._push_undo(undo_text, lambda: undo(path))
        self.refresh_folders()
        self.tabs.setCurrentWidget(self.folders_page)

    def set_mode(self, path: str, mode: str) -> None:
        before = next((f["mode"] for f in self.service.source_folders() if f["path"] == path), mode)
        self.service.set_source_mode(path, mode)
        self._push_undo("Change how a folder is sorted", lambda: self.service.set_source_mode(path, before))
        self.refresh_folders()

    def remove_folder(self, path: str) -> None:
        source = next((f for f in self.service.source_folders() if f["path"] == path), None)
        self.service.remove_folder(path)
        if source:
            self._push_undo("Remove folder", lambda: self.service.add_source(path, source["mode"]))
        else:
            self._push_undo("Remove folder", lambda: self.service.add_destination(path))
        self.refresh_folders()

    def open_folder(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ---------------------------------------------------------------- the plan
    def make_plan(self) -> None:
        if self.service.jobs.busy:
            if self.service.jobs.current.name == "count":     # plan as soon as the count is done
                self._plan_waiting = True
                self.statusBar().showMessage("Counting files first…")
            return
        if not self.service.source_folders():
            QMessageBox.information(self, APP_NAME, "Add a folder to sort first.")
            return
        self.progress = ProgressWindow(self, "Making the plan")
        self.progress.stop.connect(self.service.stop_job)
        self.progress.show()
        self.run_job("plan", self.service.make_plan)

    def show_plan(self, plan) -> None:
        self.plan = plan
        self.export_action.setEnabled(True)
        self.plan_page.set_plan(plan)
        if self.tabs.indexOf(self.plan_page) < 0:
            self.tabs.addTab(self.plan_page, "Plan")
        groups = self.service.file_groups(plan)
        self.to_place_page.set_contents(plan, groups, plan.questions, self.service.destination_choices(plan),
                                         self.service.recent_destinations(plan))
        waiting = self.to_place_page.count()
        if (groups or plan.questions) and self.tabs.indexOf(self.to_place_page) < 0:
            self.tabs.insertTab(self.tabs.indexOf(self.plan_page), self.to_place_page, "To place")
        elif not (groups or plan.questions) and self.tabs.indexOf(self.to_place_page) >= 0:
            self.tabs.removeTab(self.tabs.indexOf(self.to_place_page))
        if self.tabs.indexOf(self.to_place_page) >= 0:
            self.tabs.setTabText(self.tabs.indexOf(self.to_place_page),
                                 f"To place ({waiting:,})" if waiting else "To place")
        open_questions = waiting
        if plan.copies:
            if self.tabs.indexOf(self.copies_page) < 0:
                self.tabs.insertTab(self.tabs.indexOf(self.plan_page) + 1, self.copies_page, "Copies")
            self.tabs.setTabText(self.tabs.indexOf(self.copies_page), f"Copies ({len(plan.copies):,})")
        elif self.tabs.indexOf(self.copies_page) >= 0:
            self.tabs.removeTab(self.tabs.indexOf(self.copies_page))
        self.copies_page.set_copies(plan.copies)
        self.copies_action.setEnabled(bool(plan.copies))
        self.ai_action.setEnabled(True)
        self.tabs.setCurrentWidget(self.to_place_page if open_questions else self.plan_page)

    def place_group(self, group, folder: str, make_rule: bool) -> None:
        """Send a whole group of unsure files to one folder (and files like them later, with a rule)."""
        before = self.service.place_group(group, folder, make_rule)
        self.plan_page.note_corrections(group.paths)
        self._push_undo("Place a group", lambda: self.service.undo_place_group(before))
        self.statusBar().showMessage(f"{len(group.paths):,} files go to {self.service.display(folder)}"
                                     + (", and a rule places files like them from now on." if make_rule else "."),
                                     8000)
        self.make_plan()

    def save_answers(self, answers: dict) -> None:
        before = {k: self.service.answers().get(k) for k in answers}
        self.service.save_answers(answers)
        self._push_undo("Answers", lambda: self.service.save_answers(before))
        self.make_plan()

    def export_plan(self) -> None:
        if self.plan is None:
            return
        target, _ = QFileDialog.getSaveFileName(self, "Export the plan", "SortZen plan.xlsx", "Excel workbook (*.xlsx)")
        if target:
            try:
                self.service.export_plan(self.plan, target)
            except OSError as exc:
                QMessageBox.warning(self, APP_NAME, f"The plan couldn't be saved: {exc}")
                return
            self.statusBar().showMessage(f"Plan saved to {target}", 6000)

    # ---------------------------------------------------------------- corrections
    def change_destination(self, rows) -> None:
        if not rows:
            return
        dialog = DestinationDialog(self, self.service.destination_choices(self.plan), self.service.display,
                                   recent=self.service.recent_destinations(self.plan), rename=self.rename_folder,
                                   note=self.service.folder_note)
        if dialog.exec() and dialog.chosen:
            self.correct(rows, dialog.chosen)

    def leave_in_place(self, rows) -> None:
        for row in rows:
            self.correct([row], row.current, suggest=False)

    def forget_choice(self, rows) -> None:
        if rows:
            previous = self.service.correct([r.path for r in rows], None)
            self._push_undo("Forget choice", lambda: self.service.restore_corrections(previous))
            self.statusBar().showMessage("Choice forgotten. Update the plan to see SortZen's own suggestion.", 6000)

    def correct(self, rows, destination: str, suggest: bool = True) -> None:
        from ..engine.plan import Reason

        if suggest:
            self.service.note_destination(destination)
        previous = self.service.correct([r.path for r in rows], destination)
        changed = {os.path.normcase(r.path) for r in rows}
        for s in self.plan.files if self.plan else []:
            if os.path.normcase(s.path) in changed:
                s.destination, s.percent, s.new_folder = destination, 100, not os.path.isdir(destination)
                s.reasons = [Reason(True, "You chose this folder")]
        self._push_undo("Change destination", lambda: self.service.restore_corrections(previous))
        self.plan_page.note_corrections([r.path for r in rows])
        self.plan_page.refresh()
        self.statusBar().showMessage("Remembered. Update the plan to let SortZen learn from it for similar files.",
                                     6000)
        if suggest and self.plan is not None:
            suggestion = self.service.suggest_rule(self.plan, destination)
            if suggestion:
                self.offer_rule(suggestion)

    def offer_rule(self, suggestion, answer=None) -> None:
        """Offer to make a rule from a pattern in the destinations chosen; ``answer`` skips the question."""
        n = len(suggestion.matches)
        text = (f"{self.service.describe_rule(suggestion.rule)}?\n\nYou sent {suggestion.examples} files with this "
                f"in their name there. {n:,} more file{'s' if n != 1 else ''} in this plan match"
                f"{'es' if n == 1 else ''}. A rule places them, and similar files in future plans, at 100%. "
                "Nothing moves until you confirm. Rules are listed in Edit › Settings › Rules.")
        if answer is None:
            box = QMessageBox(QMessageBox.Icon.Question, "Make this a rule?", text, parent=self)
            make = box.addButton("Make a rule and update the plan", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
            never = box.addButton("Don't suggest this again", QMessageBox.ButtonRole.DestructiveRole)
            box.exec()
            answer = "make" if box.clickedButton() is make else "never" if box.clickedButton() is never else "no"
        if answer == "never":
            self.service.decline_rule(suggestion.rule)
        elif answer == "make":
            before = self.service.add_rule(suggestion.rule)
            self._push_undo("Make a rule", lambda: self.service.restore_rules(before))
            self.make_plan()

    def note_folder(self, folder: str, text: str | None = None) -> None:
        """Write what belongs in a folder; SortZen and the AI use the words like the folder's name."""
        if not folder:
            return
        if text is None:
            text, ok = QInputDialog.getMultiLineText(
                self, "Note about a folder",
                f"What belongs in “{os.path.basename(folder)}”? For example: pay stubs, T4s, timesheets.\n"
                "SortZen uses these words like the folder's name, and sends them to the AI with the folder list.",
                self.service.folder_note(folder))
            if not ok:
                return
        before = self.service.set_folder_note(folder, text)
        self._push_undo("Folder note", lambda: self.service.restore_folder_notes(before))
        self.folders_page.set_counts(self.folders_page.counts)
        self.statusBar().showMessage("Note saved. Update the plan to use it.", 6000)

    def rename_folder(self, folder: str, new_name: str | None = None, confirm: bool = True) -> str | None:
        """Give a folder a new name: in the plan if it is still to be made, on disk (with Undo) if it exists."""
        if not folder or self._moving():
            return None
        old_name = os.path.basename(folder)
        if new_name is None:
            new_name, ok = QInputDialog.getText(self, "Rename folder", f"New name for “{old_name}”:", text=old_name)
            if not ok:
                return None
        exists = os.path.isdir(folder)
        if exists and confirm and QMessageBox.question(
                self, "Rename folder", f"Rename the folder “{old_name}” to “{new_name.strip()}” now?\n\nThe files in "
                "it stay as they are, and Edit › Undo puts the old name back.") != QMessageBox.StandardButton.Yes:
            return None
        try:
            run = self.service.rename_folder(self.plan, folder, new_name)
        except ValueError as exc:
            QMessageBox.warning(self, "Rename folder", str(exc))
            return None
        new_path = os.path.join(os.path.dirname(os.path.abspath(folder)), new_name.strip().rstrip(". "))
        if run is not None:
            self._push_undo("Rename folder", lambda: self.service.undo_move(run.log))
            self.refresh_folders()
            self.make_plan()
        else:
            self._push_undo("Rename folder", lambda: self.service.rename_folder(self.plan, new_path, old_name))
            self.plan_page.refresh()
        self.statusBar().showMessage(f"Renamed “{old_name}” to “{os.path.basename(new_path)}”.", 6000)
        return new_path

    # ---------------------------------------------------------------- moving
    def move_rows(self, rows, confirm: bool = True) -> None:
        """Show what will move; after confirmation move it in the background."""
        if not rows or self.plan is None or not self._free_for_job():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            preview = self.service.move_preview(self.plan, rows)
        finally:
            QApplication.restoreOverrideCursor()
        if not preview.items:
            return
        if confirm and not ConfirmMoveDialog(self, preview, self.service.display).exec():
            return
        plan = self.plan
        self.progress = ProgressWindow(self, "Moving files", estimate=max(2.0, preview.items / 50))
        self.progress.stop.connect(self.service.stop_job)
        self.progress.show()
        self.run_job("move", lambda emit, token: self.service.move(plan, rows, emit, token))

    def queue_copies(self, groups, confirm: bool = True) -> None:
        """Move the ticked extra copies into "Queued for deletion" folders after confirmation."""
        ticked = [(g, c) for g in groups for c in g.extras if c.ticked]
        if not ticked or not self._free_for_job():
            return
        size = human_size(sum(g.size for g, _ in ticked))
        if confirm and QMessageBox.question(
                self, "Queue copies for deletion?",
                f"Move {len(ticked):,} extra cop{'y' if len(ticked) == 1 else 'ies'} ({size}) into folders named "
                "“Queued for deletion” with today's date, inside the folders they are in now?\n\n"
                "Each one is checked byte for byte against the copy kept just before it moves. Nothing is "
                "deleted: delete those folders yourself when you're sure. Edit › Undo puts the copies back.") \
                != QMessageBox.StandardButton.Yes:
            return
        self.progress = ProgressWindow(self, "Queuing copies for deletion", estimate=max(2.0, len(ticked) / 30))
        self.progress.stop.connect(self.service.stop_job)
        self.progress.show()
        self.run_job("queue", lambda emit, token: self.service.queue_copies(groups, emit, token))

    def ask_ai(self, confirm: bool = True) -> None:
        """Ask the AI service about unsure files after showing what is sent and what it may cost."""
        if self.plan is None or not self._free_for_job():
            return
        if confirm and not AskAIDialog(self, self.service, self.plan).exec():
            return
        plan = self.plan
        self.progress = ProgressWindow(self, "Asking the AI service")
        self.progress.stop.connect(self.service.stop_job)
        self.progress.show()
        self.run_job("ai", lambda emit, token: self.service.ask_ai(plan, emit, token))

    def _asked(self, run) -> None:
        if run.failed and not (run.asked or run.second_pass):
            QMessageBox.warning(self, "The AI service couldn't answer",
                                f"{run.stopped}\n\nNothing in the plan changed.")
            return
        if not run.asked:
            self.statusBar().showMessage("There was nothing new to ask about.", 6000)
            return
        text = (f"The AI service suggested a folder for {run.answered:,} of {run.asked:,} files"
                + (f" ({run.second_pass:,} asked again with the beginning of the file)" if run.second_pass else "")
                + f". Cost: about ${run.spent:.4f}.")
        if run.stopped:
            text += f"\n\nIt stopped early: {run.stopped}. The answers so far are kept."
        QMessageBox.information(self, APP_NAME, text + "\n\nThe plan is made again with the answers.")
        self.make_plan()

    def show_runs(self) -> None:
        dialog = RunsDialog(self, self.service.move_runs())
        if dialog.exec() and dialog.chosen:
            self.undo_run(dialog.chosen, confirm=False)

    def undo_run(self, log: str, confirm: bool = True) -> None:
        """Put everything from one move back where it was, in the background."""
        if not self._free_for_job():
            return
        run = next((r for r in self.service.move_runs() if r["log"] == log), None)
        if run is None or run["undone"]:
            self.statusBar().showMessage("That move has already been put back.", 6000)
            return
        if confirm and QMessageBox.question(
                self, APP_NAME, f"Put back the {run['moved']:,} items from this move?") != QMessageBox.StandardButton.Yes:
            return
        self.progress = ProgressWindow(self, "Putting files back", estimate=max(2.0, run["moved"] / 50))
        self.progress.stop_button.setEnabled(False)
        self.progress.show()
        self.run_job("undo-move", lambda emit, token: self.service.undo_move(log, emit, token))

    def _moved(self, result, undoing: bool, queued: bool = False) -> None:
        if not undoing and result.moved:
            self._push_undo("Queue copies" if queued else "Move", lambda: self.undo_run(result.log))
        self.result_dialog = MoveResultDialog(self, result, self.service.display, undoing, queued)
        self.result_dialog.finished.connect(lambda _: self._after_move(result))
        self.result_dialog.open()

    def _after_move(self, result) -> None:
        if self.result_dialog.undo_requested:
            if self.undo_stack and self.undo_stack[-1][0] in ("Move", "Queue copies"):
                self.undo_stack.pop()
                self._sync_undo_action()
            self.undo_run(result.log, confirm=False)
            return
        self.refresh_folders()
        if self.service.source_folders():
            self.make_plan()            # the plan is made again from where everything is now

    # ---------------------------------------------------------------- undo
    def _push_undo(self, text: str, undo) -> None:
        self.undo_stack.append((text, undo))
        self.undo_action.setEnabled(True)
        self.undo_action.setText(f"Undo {text.lower()}")

    def undo(self) -> None:
        if not self.undo_stack:
            return
        if self._moving():
            return
        text, undo = self.undo_stack.pop()
        undo()
        self._sync_undo_action()
        if self._moving():                  # a move is being put back; its own window reports
            return
        self.refresh_folders()
        self.folders_page.refresh_ticks()
        self._settings_changed()
        self.statusBar().showMessage(f"Undone: {text}. Update the plan to see the effect.", 6000)

    def _moving(self) -> bool:
        return self.service.jobs.busy and self.service.jobs.current.name in ("move", "undo-move", "queue",
                                                                              "catalog-move")

    def _sync_undo_action(self) -> None:
        self.undo_action.setEnabled(bool(self.undo_stack))
        self.undo_action.setText(f"Undo {self.undo_stack[-1][0].lower()}" if self.undo_stack else "Undo")

    # ---------------------------------------------------------------- background jobs
    def _free_for_job(self) -> bool:
        """True when nothing runs in the background; a file count is let finish first."""
        if self.service.jobs.busy and self.service.jobs.current.name == "count":
            self.service.jobs.current.join(30)          # counting is quick; let it finish
        if self.service.jobs.busy:
            QMessageBox.information(self, APP_NAME, "SortZen is still working. Try again when it has finished.")
            return False
        return True

    def run_job(self, name: str, work):
        """Start ``work(emit, token)`` in the background; its events update the status bar."""
        return self.service.run_job(name, work, self.bridge.post)

    def _on_job_event(self, event) -> None:
        if isinstance(event, Status):
            self.statusBar().showMessage(f"{event.primary} {event.detail}".strip())
            if self.progress:
                self.progress.set_step(event.primary, event.detail)
        elif isinstance(event, Progress):
            if self.progress:
                self.progress.set_progress(event.done, event.total)
        elif isinstance(event, Estimate):
            if self.progress:
                self.progress.estimate = event.seconds
        elif isinstance(event, Log):
            self.statusBar().showMessage(event.message, 5000)
        elif isinstance(event, (JobFinished, JobFailed)):
            job = self.service.jobs.current
            if job and job.name == event.name:
                job.join(5)                          # the job reports just before its thread ends
            self._job_ended(event)

    def _job_ended(self, event) -> None:
        job = self.service.jobs.current
        if isinstance(event, JobFailed):
            log.error("%s stopped: %s\n%s", event.name, event.message, job.traceback if job else "")
        else:
            log.info("%s finished", event.name)
        if isinstance(event, JobFinished):
            if event.name != "count":                # a count has no window; a later job's stays open
                self._close_progress()
                self.statusBar().showMessage("Ready")
            if event.name == "count":
                self.folders_page.set_counts(event.result or [])
                if self._plan_waiting:
                    self._plan_waiting = False
                    self.make_plan()
            if event.name == "ai":
                self._asked(event.result)
            if event.name == "catalog-ai":
                self.statusBar().showMessage(f"{len(event.result):,} suggestions from the AI service.", 6000)
                self.tabs.setCurrentWidget(self.catalog_page)
                self.catalog_page.refresh()
            if event.name == "catalog-move":
                self._moved(event.result, False)
                self.catalog_page.refresh()
            if event.name in ("move", "undo-move", "queue"):
                self._moved(event.result, event.name == "undo-move", event.name == "queue")
            if event.name == "plan":
                if event.result is None:
                    self.statusBar().showMessage("Stopped. Nothing was changed.", 6000)
                else:
                    self.show_plan(event.result)
        elif isinstance(event, JobFailed):
            if event.name != "count":
                self._close_progress()
            if event.name == "count" and self._plan_waiting:
                self._plan_waiting = False
                self.make_plan()
            self.statusBar().showMessage(f"Stopped: {event.message}")
            if event.name == "plan":
                QMessageBox.warning(self, APP_NAME, f"The plan couldn't be made: {event.message}")
            if event.name in ("ai", "catalog-ai"):
                QMessageBox.warning(self, APP_NAME, f"The AI service couldn't be asked: {event.message}")
            if event.name in ("move", "undo-move", "queue", "catalog-move"):
                QMessageBox.warning(self, APP_NAME, f"Moving stopped: {event.message}\n\nEverything moved so far "
                                    "is written down; Edit › Undo a move puts it back.")

    def _close_progress(self) -> None:
        if self.progress:
            self.progress.finish()
            self.progress = None
