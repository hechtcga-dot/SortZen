"""The workspace window: folder tree on the left, tabs on the right."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QSplitter, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..config import APP_NAME, APP_TAGLINE, APP_VERSION
from ..services import AppService
from ..tasks import JobFailed, JobFinished, Log, Progress, Status
from . import theme
from .bridge import EventBridge
from .icons import app_icon

STEPS = (
    ("Add folders", "Choose the messy folders to sort and the folders files may go to. "
                    "SortZen reads nothing outside them."),
    ("Scan", "SortZen reads the files on this PC and learns from the folders you've already sorted."),
    ("Review", "Every file gets a suggested destination with a reason. Change any of them; "
               "files SortZen is unsure about wait in Needs you."),
    ("Move", "Nothing moves until you confirm. Every run can be undone."),
)


class MainWindow(QMainWindow):
    def __init__(self, service: AppService | None = None):
        super().__init__()
        self.service = service or AppService()
        self.bridge = EventBridge(self)
        self.bridge.event.connect(self._on_job_event)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1100, 720)

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
        self.tabs.addTab(self._start_page(), "Start")
        self.splitter.addWidget(self.tabs)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([260, 840])
        layout.addWidget(self.splitter, 1)
        self.setCentralWidget(body)

        self._menus()
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
        col = QVBoxLayout(panel)
        col.setContentsMargins(8, 10, 8, 10)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.sources_item = self._tree_group("Source folders", "Messy folders to sort")
        self.destinations_item = self._tree_group("Destination folders", "Where files may go")
        col.addWidget(self.tree, 1)
        footer = QLabel("SortZen only reads the folders listed here.", objectName="treeFooter")
        footer.setWordWrap(True)
        col.addWidget(footer)
        return panel

    def _tree_group(self, title: str, hint: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.tree, [title])
        item.setFont(0, self._bold(item.font(0)))
        item.setToolTip(0, hint)
        empty = QTreeWidgetItem(item, ["No folders added yet"])
        empty.setFlags(Qt.ItemFlag.NoItemFlags)
        empty.setForeground(0, QColor(theme.MUTED))
        item.setExpanded(True)
        return item

    @staticmethod
    def _bold(font):
        font.setBold(True)
        return font

    def _start_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(28, 24, 28, 24)
        col.setSpacing(14)
        title = QLabel("Sort a messy folder", objectName="pageTitle")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(title)
        intro = QLabel("SortZen moves files from folders like Downloads into the right place, "
                       "learns how you sort, and only asks an AI service about files it can't place by itself.",
                       objectName="muted")
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
        col.addStretch(1)
        return page

    def _menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        quit_action = QAction("E&xit", self, shortcut=QKeySequence.StandardKey.Quit, triggered=self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        self.tree_action = QAction("Show folder tree", self, checkable=True, checked=True)
        self.tree_action.toggled.connect(lambda on: self.splitter.widget(0).setVisible(on))
        view_menu.addAction(self.tree_action)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(QAction(f"About {APP_NAME}", self, triggered=self.show_about))

    def show_about(self) -> None:
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<b>{APP_NAME} {APP_VERSION}</b> (alpha)<br>{APP_TAGLINE}<br><br>"
                          "Sorts messy folders into the right place. Local first; AI is optional.")

    # ---------------------------------------------------------------- background jobs
    def run_job(self, name: str, work):
        """Start ``work(emit, token)`` in the background; its events update the status bar."""
        return self.service.run_job(name, work, self.bridge.post)

    def _on_job_event(self, event) -> None:
        if isinstance(event, Status):
            self.statusBar().showMessage(f"{event.primary} {event.detail}".strip())
        elif isinstance(event, Progress):
            self.statusBar().showMessage(f"{event.done} of {event.total}")
        elif isinstance(event, Log):
            self.statusBar().showMessage(event.message, 5000)
        elif isinstance(event, JobFinished):
            self.statusBar().showMessage("Ready")
        elif isinstance(event, JobFailed):
            self.statusBar().showMessage(f"Stopped: {event.message}")
