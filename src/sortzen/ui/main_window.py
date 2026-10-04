"""The workspace window: folder tree on the left; tabs on the right (Start, Review, Folders, Labels, Cataloguing,
Plan, Copies), each closed and opened again from the View menu. Organizing sessions run in the wizard window
and end in the Review tab."""
from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QInputDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSplitter, QTabWidget, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
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
from .opening import open_on_double_click
from .plan_page import PlanPage
from .progress_window import ProgressWindow
from .review_page import ReviewPage
from .session_wizard import SessionWizard
from .settings_window import SettingsWindow
from .sortable import human_size
from .wizard_page import WizardPage

FOLDER = Qt.ItemDataRole.UserRole
log = logging.getLogger("sortzen")


def _when(stamp: float) -> str:
    """When a session was last used: "today", "yesterday", "3 days ago" or "Sep 22"."""
    import time

    days = int((time.time() - stamp) // 86400)
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago" if days < 7 else time.strftime("%b %d", time.localtime(stamp))


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
        self._after_plan: str | None = None         # what the wizard does once the plan is made
        self._wizard_open = False
        self.wizard: SessionWizard | None = None      # the organizing-session wizard, while it is open
        self.flow = None                            # the organizing session in the Review tab
        self._session_ai: list[str] = []            # AI steps still to run before Step 2
        self._session_reading = False               # the wizard waits for the plan (and the AI steps)
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
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(lambda i: self.tabs.removeTab(i))
        self.start_page = self._start_page()
        self.tabs.addTab(self.start_page, "Start")
        self.review_page = ReviewPage(self)
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
                             (self.catalog_page.ask_ai, self.ask_ai_about_catalog),
                             (self.catalog_page.place, self.place_in_category),
                             (self.catalog_page.move_files, self.move_files_to),
                             (self.catalog_page.delete_files, self.delete_files),
                             (self.catalog_page.add_to_catalog, self.add_to_catalog),
                             (self.catalog_page.open_path, self.open_folder),
                             (self.catalog_page.label, self.label_files),
                             (self.catalog_page.right_folder, self.right_folder),
                             (self.catalog_page.note_file, self.note_file)):
            signal.connect(slot)
        self.tabs.addTab(self.catalog_page, "Cataloguing")
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget() is self.catalog_page
                                         and self.catalog_page.refresh())
        self.wizard_page = WizardPage(self.service)
        for signal, slot in ((self.wizard_page.start, self.start_cataloguing),
                             (self.wizard_page.suggest_labels, self.ai_suggest_labels),
                             (self.wizard_page.add_label, lambda: self.new_label([])),
                             (self.wizard_page.edit_label, self.edit_label),
                             (self.wizard_page.reorder, self.reorder_labels),
                             (self.wizard_page.again, self.catalog_again),
                             (self.wizard_page.ask_ai_rest, lambda: self.ai_label_files("unsure")),
                             (self.wizard_page.finish, self.finish_wizard)):
            signal.connect(slot)
        self.tabs.insertTab(self.tabs.indexOf(self.catalog_page), self.wizard_page, "Labels")
        self.to_place_page = self.wizard_page.check
        self.to_place_page.refresh_button.hide()
        self.to_place_page.confirm.connect(self.confirm_labels)
        self.to_place_page.note_file.connect(self.note_file)
        self.to_place_page.keep_together.connect(self.keep_together)
        self.to_place_page.delete_files.connect(self.delete_files)
        self.to_place_page.save.connect(self.save_answers)
        self.to_place_page.place_group.connect(self.place_group)
        self.to_place_page.label.connect(self.label_files)
        self.to_place_page.new_label.connect(self.new_label)
        self.to_place_page.edit_label.connect(self.edit_label)
        self.to_place_page.pair.connect(self.pair_files)
        self.to_place_page.forget_pairs.connect(self.forget_pairs)
        self.to_place_page.put_in_folder.connect(self.put_in_folder)
        self.to_place_page.update_plan.connect(self.make_plan)
        self.to_place_page.open_path.connect(self.open_folder)
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

        self.pages = [(self.start_page, "Start"), (self.review_page, "Review"), (self.folders_page, "Folders"),
                      (self.wizard_page, "Labels"), (self.catalog_page, "Cataloguing"), (self.plan_page, "Plan"),
                      (self.copies_page, "Copies")]
        self._actions()
        self._tab_corner()
        if not self.service.settings.get("show_start", True):
            self.tabs.removeTab(self.tabs.indexOf(self.start_page))
            self.tabs.setCurrentWidget(self.folders_page)
        self.refresh_folders()
        self.refresh_sessions()
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
        open_on_double_click(self.tree, self._tree_path, self.open_folder)
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
        col.setSpacing(16)
        title = QLabel("Sort a messy folder", objectName="bigTitle")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(16)
        card = QFrame(objectName="recommended")
        wizard = QVBoxLayout(card)
        wizard.setContentsMargins(22, 18, 22, 18)
        wizard.setSpacing(10)
        wizard.addWidget(QLabel("RECOMMENDED", objectName="recommendedTag"))
        wizard.addWidget(QLabel("Start a new organizing session", objectName="cardTitle"))
        text = QLabel("A short wizard: choose your folders, clear out duplicates, then label your files batch by "
                      "batch. SortZen learns as you go, so each batch asks less. You check everything in Review "
                      "before anything moves.")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        wizard.addWidget(text)
        wizard.addWidget(QLabel("1 Choose  ›  2 Duplicates  ›  3 Catalog  ›  Review", objectName="hint"))
        self.plan_button = QPushButton("Start the wizard", objectName="primary")
        self.plan_button.clicked.connect(self.new_session)
        wizard.addWidget(self.plan_button, 0, Qt.AlignmentFlag.AlignLeft)
        wizard.addStretch(1)
        row.addWidget(card, 3)
        sessions = QFrame(objectName="card")
        scol = QVBoxLayout(sessions)
        scol.setContentsMargins(20, 16, 20, 16)
        scol.setSpacing(8)
        scol.addWidget(QLabel("Carry on a session", objectName="cardTitle"))
        self.sessions_list = QVBoxLayout()
        self.sessions_list.setSpacing(6)
        scol.addLayout(self.sessions_list)
        scol.addStretch(1)
        row.addWidget(sessions, 2)
        col.addLayout(row)
        links = QHBoxLayout()
        links.addWidget(QLabel("Prefer the tabs?", objectName="muted"))
        for text, slot in (("Open the Folders tab", lambda: self.show_tab(self.folders_page)),
                           ("Open a saved profile…", self.load_profile)):
            link = QPushButton(text, objectName="link")
            link.clicked.connect(slot)
            links.addWidget(link)
        links.addStretch(1)
        col.addLayout(links)
        self.start_hint = QLabel("Every tab stays in the View menu and under “+ Open a tab”, for anyone who prefers "
                                 "working without the wizard.", objectName="hint")
        self.start_hint.setWordWrap(True)
        col.addWidget(self.start_hint)
        self.show_start = QCheckBox("Show this screen when SortZen opens",
                                    checked=bool(self.service.settings.get("show_start", True)))
        self.show_start.toggled.connect(lambda on: self.service.settings.set("show_start", on))
        col.addWidget(self.show_start)
        col.addStretch(1)
        return page

    def refresh_sessions(self) -> None:
        """The start screen's list of saved sessions, the latest used first."""
        from .session_wizard import _clear

        _clear(self.sessions_list)
        found = self.service.recent_sessions()
        if not found:
            empty = QLabel("No sessions yet. A session is saved as you go, so you can stop and carry on later.",
                           objectName="hint")
            empty.setWordWrap(True)
            self.sessions_list.addWidget(empty)
        for session, where in found:
            line = QHBoxLayout()
            words = QVBoxLayout()
            words.setSpacing(0)
            name = QLabel(session.name)
            name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            words.addWidget(name)
            words.addWidget(QLabel(f"{where} · {_when(session.updated)}", objectName="hint"))
            line.addLayout(words, 1)
            open_button = QPushButton("Open")
            open_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            open_button.customContextMenuRequested.connect(
                lambda _, f=session.file, b=open_button: self._session_menu(f, b))
            open_button.clicked.connect(lambda _=False, f=session.file: self.open_session(f))
            line.addWidget(open_button)
            self.sessions_list.addLayout(line)

    def _session_menu(self, file: str, button) -> None:
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.open_session(file))
        menu.addAction("Forget this session", lambda: self.forget_session(file))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def forget_session(self, file: str) -> None:
        """Forget a saved session (its files stay as they are; moves can still be undone)."""
        self.service.sessions.delete(file)
        self.refresh_sessions()

    def _tab_corner(self) -> None:
        self.open_tab_button = QToolButton(objectName="openTab")
        self.open_tab_button.setText("+ Open a tab ▾")
        self.open_tab_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.open_tab_button.setMenu(self.tabs_menu)
        self.tabs.setCornerWidget(self.open_tab_button, Qt.Corner.TopRightCorner)

    def _fill_tabs_menu(self) -> None:
        self.tabs_menu.clear()
        for page, title in self.pages:
            needs_plan = page in (self.plan_page, self.copies_page)
            needs_session = page is self.review_page
            a = self.tabs_menu.addAction(title, lambda p=page: self.show_tab(p))
            a.setCheckable(True)
            a.setChecked(self.tabs.indexOf(page) >= 0)
            a.setEnabled(not (needs_plan and self.plan is None) and not (needs_session and self.flow is None))

    def show_tab(self, page) -> None:
        """Open a tab (in its usual place) and show it."""
        if self.tabs.indexOf(page) < 0:
            order = [p for p, _ in self.pages]
            title = dict((p, t) for p, t in self.pages)[page]
            at = sum(1 for p in order[:order.index(page)] if self.tabs.indexOf(p) >= 0)
            self.tabs.insertTab(at, page, title)
            if page is self.wizard_page:
                self._count_to_place()
            if page is self.copies_page and self.plan is not None:
                self.tabs.setTabText(self.tabs.indexOf(page), f"Copies ({len(self.plan.copies):,})")
        self.tabs.setCurrentWidget(page)

    def only_tab(self, page) -> None:
        """Show one tab and close the others (they open again from View or “+ Open a tab”)."""
        self.show_tab(page)
        for i in reversed(range(self.tabs.count())):
            if self.tabs.widget(i) is not page:
                self.tabs.removeTab(i)

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
        self.session_action = action("New organizing session…", self.new_session, "Ctrl+N",
                                     "The wizard: choose folders, clear duplicates, label files batch by batch")
        self.wizard_action = action("Labels", self.open_wizard, "Ctrl+L",
                                    "Your labels, and the files SortZen isn't sure about")
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
        for a in (self.session_action, self.add_source_action, self.add_destination_action, self.plan_action,
                  self.export_action, self.undo_action):
            toolbar.addAction(a)
        self.addToolBar(toolbar)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.session_action)
        file_menu.addSeparator()
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
        plan_menu.addAction(self.wizard_action)
        plan_menu.addAction(self.plan_action)
        self.ai_action = action("Ask AI about unsure files…", self.ask_ai,
                                tip="Ask an AI service about the files SortZen couldn't place by itself")
        self.ai_action.setEnabled(False)
        plan_menu.addAction(self.ai_action)
        self.copies_action = action("Copies…", lambda: self.show_tab(self.copies_page),
                                    tip="Exact copies found while making the plan")
        self.copies_action.setEnabled(False)
        plan_menu.addAction(self.copies_action)
        plan_menu.addAction(action("Catalog", lambda: self.show_tab(self.catalog_page),
                                   tip="Your categories: see, edit and comment on them"))
        view_menu = self.menuBar().addMenu("&View")
        self.tabs_menu = QMenu("Tabs", self)
        self.tabs_menu.aboutToShow.connect(self._fill_tabs_menu)
        self._fill_tabs_menu()
        view_menu.addMenu(self.tabs_menu)
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

    # ---------------------------------------------------------------- putting files into categories
    def place_in_category(self, paths: list, folder: str, confirm: bool = True) -> None:
        """Files the plan sends somewhere: the plan changes (nothing moves) and SortZen learns. Files and
        folders already in place move into the category after confirmation; SortZen remembers the choice."""
        planned = {os.path.normcase(s.path): s for s in self.plan.files} if self.plan is not None else {}
        rows = [planned[os.path.normcase(p)] for p in paths if os.path.normcase(p) in planned
                and os.path.normcase(planned[os.path.normcase(p)].destination or "") != os.path.normcase(folder)]
        if rows:
            self.correct(rows, folder)
            self.catalog_page.set_plan(self.plan)
            self.catalog_page.refresh()
        paths = [p for p in paths if os.path.normcase(p) not in planned]
        if not paths:
            return
        requests = self.service.drop_requests(paths, folder)
        name = os.path.basename(folder) or folder
        if not requests:
            self.statusBar().showMessage(f"Already in “{name}”. Nothing to move.", 6000)
            return
        if not self._free_for_job():
            return
        files = sum(1 for r in requests if not os.path.isdir(r.path))
        what = ", ".join(part for part in (
            f"{files:,} file{'s' if files != 1 else ''}" if files else "",
            f"{len(requests) - files:,} folder{'s' if len(requests) - files != 1 else ''}"
            if len(requests) > files else "") if part)
        examples = ", ".join(os.path.basename(r.path) for r in requests[:3]) + (", …" if len(requests) > 3 else "")
        if confirm and QMessageBox.question(
                self, "Put into a category", f"Move {what} into “{self.service.display(folder)}”?\n\n{examples}\n\n"
                "SortZen remembers that they belong there and learns from them for future plans. "
                "Edit › Undo puts them back.") != QMessageBox.StandardButton.Yes:
            return
        self._placing = folder
        if len(requests) > 20:
            self.progress = ProgressWindow(self, "Moving into the category", estimate=max(2.0, len(requests) / 50))
            self.progress.stop.connect(self.service.stop_job)
            self.progress.show()
        self.run_job("place", lambda emit, token: self.service.place(requests, emit, token))

    def move_files_to(self, paths: list, folder: str | None = None) -> None:
        """Put files into a category chosen from the list (recently used folders first)."""
        if folder is None:
            categories = [c for c in self.service.catalog() if not c.merged_into]
            recent = [os.path.normcase(f) for f in self.service.recent_destinations()]
            categories.sort(key=lambda c: recent.index(os.path.normcase(c.path)) if os.path.normcase(c.path) in recent
                            else len(recent))
            labels = [self.service.display(c.path) for c in categories]
            if not labels:
                return
            chosen, ok = QInputDialog.getItem(self, "Move to a category", f"Put {len(paths):,} file"
                                              f"{'s' if len(paths) != 1 else ''} into:", labels, 0, False)
            if not ok:
                return
            folder = categories[labels.index(chosen)].path
        self.place_in_category(paths, folder, confirm=False)

    def delete_files(self, paths: list, confirm: bool = True) -> None:
        """Move files into "To delete" folders after confirmation; Undo puts them back."""
        requests = self.service.delete_requests(paths)
        if not requests or not self._free_for_job():
            return
        n = len(requests)
        if confirm and self.service.option("ask_before_delete"):
            from PySide6.QtWidgets import QCheckBox

            box = QMessageBox(QMessageBox.Icon.Question, "Delete files",
                              f"Delete {n:,} file{'s' if n != 1 else ''}?\n\nThey move into a folder named “To "
                              "delete”, inside the folder you added. Delete that folder yourself when you're sure. "
                              "Edit › Undo puts them back.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                              self)
            never = QCheckBox("Don't ask again (change it in Edit › Settings › General)")
            box.setCheckBox(never)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
            if never.isChecked():
                self.service.set_option("ask_before_delete", False)
        self.run_job("delete", lambda emit, token: self.service.delete(requests, emit, token))

    def add_to_catalog(self, folders: list) -> None:
        """Add folders to the catalog (as destination folders); an empty list asks which."""
        if not folders:
            folder = QFileDialog.getExistingDirectory(self, "Add a folder to the catalog")
            folders = [folder] if folder else []
        for folder in folders:
            self._try(lambda f=folder: self.service.add_destination(f), f"Add {os.path.basename(folder)} to the catalog",
                      lambda path: self.service.remove_folder(path), show_folders=False)
        self.catalog_page.refresh()

    def _placed(self, name: str, result) -> None:
        if result.moved:
            text = "Put into a category" if name == "place" else "Delete"
            self._push_undo(text, lambda: self.undo_run(result.log, confirm=False))
        if result.failed:
            QMessageBox.warning(self, APP_NAME, f"{len(result.failed):,} couldn't be moved:\n\n" + "\n".join(
                f"{os.path.basename(p)}: {why}" for p, why in result.failed[:8]))
        if name == "delete":
            self._drop_from_plan([old for old, _ in result.moves])
            if self.wizard is not None and self.wizard.flow is not None:
                self.wizard.flow.drop([old for old, _ in result.moves])
                self.wizard.catalog.show_batch()
            self.statusBar().showMessage(f"{result.moved:,} moved to “To delete”. Edit › Undo puts them back.", 8000)
            return
        self.catalog_page.refresh()
        folder = getattr(self, "_placing", "")
        self.statusBar().showMessage(f"{result.moved:,} moved into “{os.path.basename(folder)}”. SortZen learns from "
                                     "them: update the plan to use it. Edit › Undo puts them back.", 8000)
        if result.moved and self.plan is not None and folder:
            suggestion = self.service.suggest_rule(self.plan, folder)
            if suggestion:
                self.offer_rule(suggestion)

    def _drop_from_plan(self, paths: list) -> None:
        """Files that left (to the To delete folder) leave the plan and the lists on screen too."""
        if self.plan is not None and paths:
            gone = {os.path.normcase(p) for p in paths}
            self.plan.files = [s for s in self.plan.files if os.path.normcase(s.path) not in gone]
            self.plan_page.set_plan(self.plan)
            self.catalog_page.set_plan(self.plan)
            self.to_place_page.set_contents(self.plan, self.service.question_groups(self.plan), self.plan.questions,
                                             self.to_place_page.folders, self.to_place_page.recent)
            self._count_to_place()
        self.catalog_page.refresh()

    def _reorganize(self, requests) -> None:
        if not self._free_for_job():
            return
        self.progress = ProgressWindow(self, "Reorganizing the catalog", estimate=max(2.0, len(requests) / 50))
        self.progress.stop.connect(self.service.stop_job)
        self.progress.show()
        self.run_job("catalog-move", lambda emit, token: self.service.reorganize(requests, emit, token))

    def right_folder(self, paths: list) -> None:
        """Users agree with the folders the plan chose for these files: SortZen learns from them."""
        if self.plan is None:
            return
        keys = {os.path.normcase(p) for p in paths}
        by_folder: dict[str, list] = {}
        for s in self.plan.files:
            if os.path.normcase(s.path) in keys and s.destination:
                by_folder.setdefault(s.destination, []).append(s)
        for folder, rows in by_folder.items():
            self.correct(rows, folder, suggest=False)
        self.catalog_page.refresh()

    def accept_suggestion(self, s, confirm: bool = True) -> None:
        if hasattr(s, "rule"):                      # a folder for a label: a rule, then the plan again
            before = self.service.add_rule(s.rule)
            self._push_undo("Make a rule", lambda: self.service.restore_rules(before))
            self.statusBar().showMessage(f"{s.title}. Cataloguing again…", 6000)
            self._keep_tab = self.tabs.currentWidget()
            self.make_plan()
            return
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
        if hasattr(s, "rule"):
            self.service.decline_rule(s.rule)
            self.catalog_page.refresh()
            return
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
        self.plan_action.setEnabled(bool(self.service.source_folders()))

    def _tree_path(self, item):
        data = item.data(0, FOLDER) if item else None
        return data[1] if data else None

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

    def _try(self, work, undo_text, undo, show_folders: bool = True) -> None:
        show_folders = show_folders and self.wizard is None
        try:
            path = work()
        except FolderError as exc:
            QMessageBox.information(self, APP_NAME, str(exc))
            return
        self._push_undo(undo_text, lambda: undo(path))
        self.refresh_folders()
        if show_folders:
            self.show_tab(self.folders_page)

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
        """Open a file with its program, or a folder in Explorer."""
        from .opening import open_path

        if not open_path(path):
            self.statusBar().showMessage(f"“{os.path.basename(path) or path}” isn't there"
                                         + (" yet: SortZen makes it when files move into it." if not
                                            os.path.splitext(path)[1] else "."), 6000)

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
        self.catalog_page.set_plan(plan)
        if self.tabs.indexOf(self.plan_page) < 0:
            self.tabs.addTab(self.plan_page, "Plan")
        groups = self.service.question_groups(plan)
        self.to_place_page.set_contents(plan, groups, plan.questions, self.service.destination_choices(plan),
                                         self.service.recent_destinations(plan))
        open_questions = self._count_to_place()
        if plan.copies:
            if self.tabs.indexOf(self.copies_page) < 0:
                self.tabs.insertTab(self.tabs.indexOf(self.plan_page) + 1, self.copies_page, "Copies")
            self.tabs.setTabText(self.tabs.indexOf(self.copies_page), f"Copies ({len(plan.copies):,})")
        elif self.tabs.indexOf(self.copies_page) >= 0:
            self.tabs.removeTab(self.tabs.indexOf(self.copies_page))
        self.copies_page.set_copies(plan.copies)
        self.copies_action.setEnabled(bool(plan.copies))
        self.ai_action.setEnabled(True)
        after, self._after_plan = self._after_plan, None
        if after == "session" and self.wizard is not None:
            self.wizard.flow.set_plan(plan)
            self._session_continue()
            return
        if after == "review" and self.flow is not None:
            self.flow.set_plan(plan)
            self.review_page.set_flow(self.flow)
            self.only_tab(self.review_page)
            self.refresh_sessions()
            return
        if after == "ai-sample":
            self.ai_label_files("sample", then_plan=True)
        elif after == "suggest":
            self.ai_suggest_labels()
        keep, self._keep_tab = getattr(self, "_keep_tab", None), None
        if keep is not None:
            self.show_tab(keep)
        elif self._wizard_open:
            self.wizard_page.show_step(1)
            self.show_tab(self.wizard_page)
        else:
            self.show_tab(self.wizard_page if open_questions else self.plan_page)
            if open_questions:
                self.wizard_page.show_step(1)

    def _count_to_place(self) -> int:
        waiting = self.to_place_page.count()
        self.tabs.setTabText(self.tabs.indexOf(self.wizard_page),
                             f"Labels ({waiting:,})" if waiting else "Labels")
        self.wizard_page.refresh()
        return waiting

    # ---------------------------------------------------------------- organizing sessions
    def new_session(self) -> None:
        """Open the wizard on Step 1 for a new organizing session."""
        if self.wizard is not None:
            self.wizard.raise_()
            self.wizard.activateWindow()
            return
        if not self._free_for_job():
            return
        self._open_wizard(None)

    def _open_wizard(self, flow) -> SessionWizard:
        self.wizard = SessionWizard(self, flow)
        self.wizard.step_done.connect(self._session_step)
        self.wizard.finished.connect(self._wizard_closed)
        self.wizard.show()
        return self.wizard

    def _wizard_closed(self, *_) -> None:
        wizard, self.wizard = self.wizard, None
        self._session_ai = []
        self._session_reading = False
        if wizard is not None:
            wizard.deleteLater()
        self.refresh_sessions()

    def open_session(self, file: str) -> None:
        """Carry on a saved session where it was left."""
        from ..repositories.sessions import CATALOG, CHOOSE, DUPLICATES, MOVED

        if not self._free_for_job():
            return
        flow = self.service.open_session(file)
        if flow is None:
            QMessageBox.information(self, APP_NAME, "That session can't be read any more.")
            self.refresh_sessions()
            return
        if flow.session.stage == MOVED:
            QMessageBox.information(self, APP_NAME, f"“{flow.session.name}” is finished: {flow.session.moved:,} files "
                                    "were moved. Edit › Undo a move puts them back.")
            return
        if self.wizard is not None:
            self.wizard.close()
        missing = flow.restore_folders()
        self.refresh_folders()
        if missing:
            QMessageBox.information(self, APP_NAME, "These folders of the session can't be found, so they are left "
                                    "out:\n\n" + "\n".join(missing))
        if flow.session.stage == CHOOSE:
            self._open_wizard(flow)
        elif flow.session.stage in (DUPLICATES, CATALOG):
            self._open_wizard(flow)
            self._session_read()
        else:
            self.flow = flow
            self._after_plan = "review"
            self.make_plan()

    def _session_step(self, step: str) -> None:
        if step == "choose":
            self._session_ai = []
            if self.wizard.choose.wants_ai():
                self._session_ai = (["suggest"] if self.wizard.choose.ai_labels.isChecked() else []) + ["sample"]
            self._session_read()
        elif step == "duplicates":
            self._session_queue()
        elif step == "catalog":
            self.flow = self.wizard.flow
            self.wizard.close()
            self._after_plan = "review"
            self.make_plan()

    def _session_read(self) -> None:
        """Read the session's folders and make the plan; the wizard carries on when it is made."""
        self._session_reading = True
        self._after_plan = "session"
        self.make_plan()

    def _session_continue(self) -> None:
        """After reading: the AI steps chosen in Step 1, then Step 2 (or 3)."""
        from ..repositories.sessions import CATALOG, DUPLICATES

        if self.wizard is None:
            return
        while self._session_ai:
            step = self._session_ai.pop(0)
            if step == "suggest" and self.ai_suggest_labels():
                return
            if step == "sample" and self.ai_label_files("sample"):
                return
        self._session_reading = False
        flow = self.wizard.flow
        if flow.session.stage == CATALOG:
            self.service.guess_labels()
            self.wizard.show_catalog()
        else:
            flow.session.stage = DUPLICATES
            flow.save()
            self.wizard.show_duplicates()
        self.refresh_sessions()

    def _session_queue(self) -> None:
        """Step 2: the ticked extra copies move into "To delete" at once (checked byte for byte first)."""
        groups = self.wizard.flow.copies()
        ticked = self.wizard.flow.ticked_copies()
        if not ticked or not self._free_for_job():
            return
        self.progress = ProgressWindow(self, "Moving copies to “To delete”", estimate=max(2.0, ticked / 30))
        self.progress.stop.connect(self.service.stop_job)
        self.progress.show()
        self.run_job("session-queue", lambda emit, token: self.service.queue_copies(groups, emit, token))

    def _session_queued(self, result) -> None:
        if result.moved:
            self._push_undo("Queue copies", lambda: self.undo_run(result.log))
        if result.failed:
            QMessageBox.information(self, APP_NAME, f"{len(result.failed):,} copies stayed where they were:\n\n"
                                    + "\n".join(f"{os.path.basename(p)}: {why}" for p, why in result.failed[:8]))
        if self.wizard is not None:
            self.wizard.flow.copies_queued(result)
            self.service.guess_labels()
            self.wizard.show_catalog()
        self.statusBar().showMessage(f"{result.moved:,} copies moved to “To delete”. Edit › Undo puts them back.", 8000)

    def session_move(self, flow) -> None:
        """After the last Review batch: what will move, then the move itself."""
        rows = flow.move_rows()
        if not rows:
            QMessageBox.information(self, APP_NAME, "Nothing to move: confirm a batch first, or the plan leaves "
                                    "every file where it is.")
            return
        if not self._free_for_job():
            return
        preview = self.service.move_preview(flow.plan, rows)
        reviewed = sum(1 for r in flow.review if flow.is_reviewed(r))
        heading = (f"All {len(flow.review)} batches reviewed. " if reviewed == len(flow.review) else
                   f"{reviewed} of {len(flow.review)} batches confirmed; the rest stay where they are. ")
        notes = [f"The {flow.session.copies_queued:,} copies from Step 2 are already in “To delete”."] \
            if flow.session.copies_queued else []
        dialog = ConfirmMoveDialog(self, preview, self.service.display, heading, notes, "Back to Review")
        if not dialog.exec():
            return
        plan = flow.plan
        self.progress = ProgressWindow(self, "Moving files", estimate=max(2.0, preview.items / 50))
        self.progress.stop.connect(self.service.stop_job)
        self.progress.show()
        self.run_job("session-move", lambda emit, token: self.service.move(plan, rows, emit, token))

    # ---------------------------------------------------------------- the Labels tab
    def open_wizard(self) -> None:
        """The Labels tab, on the labels step."""
        if not self.service.source_folders():
            QMessageBox.information(self, APP_NAME, "Add a folder to sort first.")
            return
        self.wizard_page.show_step(0)
        self.show_tab(self.wizard_page)

    def start_cataloguing(self, mode: str) -> None:
        """Label the files (on the PC, or the AI for a sample first) and catalog them."""
        self._wizard_open = True
        self._after_plan = "ai-sample" if mode == "ai" else None
        if mode == "ai" and not self.service.ai_ready():
            QMessageBox.information(self, APP_NAME, "Choose an AI service and its key first (Edit › Settings › AI). "
                                    "SortZen labels the files on this PC for now.")
            self._after_plan = None
        self.make_plan()

    def catalog_again(self) -> None:
        self._wizard_open = True
        self.make_plan()

    def finish_wizard(self) -> None:
        self._wizard_open = False
        self.show_tab(self.catalog_page)
        self.catalog_page.refresh()

    def reorder_labels(self, names: list) -> None:
        self._label_change("Change label order", lambda: self.service.set_label_order(names))
        self.to_place_page._fill_labels()

    def confirm_labels(self, paths: list) -> None:
        if paths and self._label_change("Looks right", lambda: self.service.confirm_labels(paths)):
            self.statusBar().showMessage(f"Thanks: SortZen learns from {len(paths):,} file"
                                         f"{'s' if len(paths) != 1 else ''}.", 5000)

    def note_file(self, path: str, text: str | None = None) -> None:
        """A note about one file: why it goes somewhere special. Its words count for labels and folders."""
        if text is None:
            text, ok = QInputDialog.getMultiLineText(
                self, "Note about a file", f"Anything special about “{os.path.basename(path)}”? For example: "
                "“this one is for the 2023 audit” or “keep with Mum's documents”. Naming a folder sends it there.",
                self.service.file_note(path))
            if not ok:
                return
        if self._label_change("Note about a file", lambda: self.service.set_file_note(path, text)):
            self.statusBar().showMessage("Note saved. Catalog again to use it.", 5000)

    def keep_together(self, folder: str) -> None:
        if self._label_change("Keep a folder together", lambda: self.service.keep_folder_together(folder)):
            self.statusBar().showMessage(f"“{os.path.basename(folder)}” moves as it is. Catalog again to use it.", 6000)

    def _ai_ok(self, what: str, estimate: dict) -> bool:
        money = "free: it runs on this PC" if estimate["local"] else f"about ${estimate['cost']:.4f}"
        sending = ("file names (long numbers removed), the folder each file is in, and the beginning of files"
                   if self.service.ai_value("ai_privacy") == "beginning" else
                   "file names (long numbers removed) and the folder each file is in")
        return QMessageBox.question(
            self, "Ask the AI", f"Ask {estimate['service']} {what}? {money}.\n\nSent: {sending}, as your privacy "
            "settings allow (Edit › Settings › Privacy). Spending stops at your cap."
        ) == QMessageBox.StandardButton.Yes

    def ai_suggest_labels(self, confirm: bool = True) -> bool:
        if not self.service.ai_ready():
            QMessageBox.information(self, APP_NAME, "Choose an AI service and its key first (Edit › Settings › AI).")
            return False
        if self.plan is None:                       # the files are read first
            self._after_plan = "suggest"
            self.make_plan()
            return False
        if not self._free_for_job():
            return False
        estimate = self.service.ai_label_estimate("list")
        if confirm and not self._ai_ok(f"to suggest labels from {estimate['files']:,} file names", estimate):
            return False
        self.progress = ProgressWindow(self, "Asking the AI for labels")
        self.progress.show()
        self.run_job("ai-list", lambda emit, token: self.service.ai_suggest_labels(emit, token))
        return True

    def _pick_labels(self, found: list, chosen: list | None = None) -> None:
        if chosen is None:
            from .dialogs import LabelChoiceDialog

            dialog = LabelChoiceDialog(self, found, self.service.labels())
            if not dialog.exec():
                return
            chosen = dialog.chosen()
        new = [n for n in chosen if n.lower() not in {x.lower() for x in self.service.labels()}]
        if new:
            self._label_change("Labels from the AI", lambda: [self.service.add_label(n) for n in new])
            self.to_place_page._fill_labels()
        self.wizard_page.refresh()

    def ai_label_files(self, which: str, then_plan: bool = False, confirm: bool = True) -> bool:
        """The AI labels a sample of files (or the files SortZen is still unsure of); SortZen learns the rest."""
        if not self.service.ai_ready() or not self._free_for_job():
            return False
        estimate = self.service.ai_label_estimate(which, self.plan)
        if not estimate["files"]:
            self.statusBar().showMessage("Nothing to ask the AI about.", 5000)
            return False
        what = (f"to label a sample of {estimate['files']:,} files (SortZen labels the rest from them)"
                if which == "sample" else f"to label the {estimate['files']:,} files SortZen is still unsure of")
        if confirm and not self._ai_ok(what, estimate):
            return False
        plan = self.plan
        self._wizard_open = self.wizard is None
        self.progress = ProgressWindow(self, "Asking the AI for labels", estimate=max(4.0, estimate["files"] / 20))
        self.progress.stop.connect(self.service.stop_job)
        self.progress.show()
        self.run_job("ai-labels", lambda emit, token: self.service.ai_label_files(which, plan, emit, token))
        return True

    # ---------------------------------------------------------------- labels and similar files
    def _label_change(self, text: str, change) -> bool:
        """Make a change to labels or similar files that Undo puts back; the plan shows it at once."""
        before = self.service.settings_snapshot()
        try:
            change()
        except ValueError as exc:
            QMessageBox.information(self, "Labels", str(exc))
            return False

        def undo():
            self.service.restore_settings(before)
            self._show_labels()
        self._push_undo(text, undo)
        self._show_labels()
        return True

    def _show_labels(self) -> None:
        self.to_place_page.refresh_rows()
        self._count_to_place()
        if self.tabs.currentWidget() is self.catalog_page:
            self.catalog_page._show()

    def label_files(self, paths: list, name: str, on: bool) -> None:
        if paths and self._label_change(f"Label {name}" if on else f"Take away {name}",
                                        lambda: self.service.set_labels(paths, name, on)):
            n = len(paths)
            self.statusBar().showMessage(
                f"{n:,} file{'s' if n != 1 else ''} {'labelled' if on else 'no longer labelled'} “{name}”. "
                "Update the plan to let SortZen learn from it.", 6000)

    def new_label(self, paths: list | None = None, name: str | None = None) -> None:
        """Make a label (it goes last: the least important); then give it to the selected files."""
        if name is None:
            name, ok = QInputDialog.getText(self, "New label", "Name of the label (for example Work, Taxes or "
                                            "Photo session):")
            if not ok or not name.strip():
                return
        if self._label_change(f"New label {name.strip()}", lambda: self.service.add_label(name)):
            self.to_place_page._fill_labels()
            if paths:
                self.label_files(paths, " ".join(name.split()), True)

    def edit_label(self, name: str, action: str, value: str | None = None) -> None:
        if action == "rename":
            if value is None:
                value, ok = QInputDialog.getText(self, "Rename label", f"New name for “{name}”:", text=name)
                if not ok or not value.strip():
                    return
            self._label_change(f"Rename label {name}", lambda: self.service.rename_label(name, value))
        elif action in ("up", "down"):
            order = self.service.labels()
            i = order.index(name)
            j = max(0, i - 1) if action == "up" else min(len(order) - 1, i + 1)
            order[i], order[j] = order[j], order[i]
            self._label_change("Change label order", lambda: self.service.set_label_order(order))
        elif action == "remove":
            self._label_change(f"Remove label {name}", lambda: self.service.remove_label(name))
        self.to_place_page._fill_labels()
        self.to_place_page.refresh_rows()

    def pair_files(self, paths: list, kind: str, other: str | None = None) -> None:
        """Say files are similar to, or different from, another file. It changes percentages, never moves."""
        if not paths:
            return
        if other is None:
            from .to_place_page import FilePickerDialog

            word = "similar to" if kind == "similar" else "different from"
            dialog = FilePickerDialog(self, self.service.known_files(), self.service.display,
                                      f"Which file is it {word}?",
                                      f"Pick the file {'these are' if len(paths) > 1 else 'this is'} {word}. SortZen "
                                      f"becomes {'surer of' if kind == 'similar' else 'less sure of'} that file's "
                                      "folder; nothing moves.")
            if not dialog.exec() or not dialog.chosen:
                return
            other = dialog.chosen
        if self._label_change("Similar files" if kind == "similar" else "Different files",
                              lambda: self.service.pair_files(paths, other, kind, self.plan)):
            self.plan_page.refresh()
            self.to_place_page.refresh_rows()
            self.statusBar().showMessage("Remembered. SortZen uses it in every plan; nothing moved.", 6000)

    def forget_pairs(self, paths: list) -> None:
        self._label_change("Forget similar files", lambda: self.service.forget_pairs(paths))
        self.statusBar().showMessage("Forgotten. Update the plan to see SortZen's own suggestion.", 6000)

    def put_in_folder(self, paths: list) -> None:
        if self.plan is not None:
            keys = {os.path.normcase(p) for p in paths}
            self.change_destination([s for s in self.plan.files if os.path.normcase(s.path) in keys])
            self.to_place_page.refresh_rows()

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
        paths = self.service.with_companions(self.plan, [r.path for r in rows])
        changed = {os.path.normcase(p) for p in paths}
        guessed = {s.path: s.destination for s in (self.plan.files if self.plan else [])
                   if os.path.normcase(s.path) in changed}
        previous = self.service.correct(paths, destination, guessed)
        for s in self.plan.files if self.plan else []:
            if os.path.normcase(s.path) in changed:
                s.destination, s.percent, s.new_folder = destination, 100, not os.path.isdir(destination)
                s.reasons = [Reason(True, "You chose this folder")]
        self._push_undo("Change destination", lambda: self.service.restore_corrections(previous))
        self.plan_page.note_corrections(paths)
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
        sent = (f"You put {suggestion.examples} files with this label there" if suggestion.rule.label else
                f"You sent {suggestion.examples} files with this in their name there")
        text = (f"{self.service.describe_rule(suggestion.rule)}?\n\n{sent}. "
                f"{n:,} more file{'s' if n != 1 else ''} in this plan match"
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
        """Move the ticked extra copies into "To delete" folders after confirmation."""
        ticked = [(g, c) for g in groups for c in g.extras if c.ticked]
        if not ticked or not self._free_for_job():
            return
        size = human_size(sum(g.size for g, _ in ticked))
        if confirm and QMessageBox.question(
                self, "Queue copies for deletion?",
                f"Move {len(ticked):,} extra cop{'y' if len(ticked) == 1 else 'ies'} ({size}) into folders named "
                "“To delete”, inside the folders you added?\n\n"
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
        if self.flow is not None and self.flow.session.stage == "moved":
            self.flow = None                    # the session is done: back to the start screen
            self.review_page.flow = None
            self.tabs.removeTab(self.tabs.indexOf(self.review_page))
            self.show_tab(self.start_page)
            return
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
        return self.service.jobs.busy and self.service.jobs.current.name in (
            "move", "undo-move", "queue", "catalog-move", "place", "delete", "session-queue", "session-move")

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
            if event.name == "ai-list":
                self._pick_labels(event.result or [])
                if self._session_reading:
                    self._session_continue()
            if event.name == "ai-labels":
                self.statusBar().showMessage(f"The AI labelled {event.result or 0:,} files. Cataloguing them…", 6000)
                if self._session_reading:
                    self._after_plan = "session"
                self.make_plan()
            if event.name == "session-queue":
                self._session_queued(event.result)
            if event.name == "session-move":
                self.flow.moved(event.result)
                self.refresh_sessions()
                self._moved(event.result, False)
            if event.name == "catalog-ai":
                self.statusBar().showMessage(f"{len(event.result):,} suggestions from the AI service.", 6000)
                self.show_tab(self.catalog_page)
                self.catalog_page.refresh()
            if event.name == "catalog-move":
                self._moved(event.result, False)
                self.catalog_page.refresh()
            if event.name in ("place", "delete"):
                self._placed(event.name, event.result)
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
            if event.name in ("ai", "catalog-ai", "ai-list", "ai-labels"):
                QMessageBox.warning(self, APP_NAME, f"The AI service couldn't be asked: {event.message}")
                if event.name in ("ai-list", "ai-labels") and self._session_reading:
                    self._session_continue()
            if event.name in ("move", "undo-move", "queue", "catalog-move", "place", "delete", "session-queue",
                              "session-move"):
                QMessageBox.warning(self, APP_NAME, f"Moving stopped: {event.message}\n\nEverything moved so far "
                                    "is written down; Edit › Undo a move puts it back.")

    def _close_progress(self) -> None:
        if self.progress:
            self.progress.finish()
            self.progress = None
