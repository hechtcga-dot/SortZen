"""The organizing-session wizard: a window with three steps, then the Review tab.

1 Choose: the session's name, the folders to sort and where files go, the options (SortZen only or
  an AI service with a spending cap, how sure SortZen must be, starting labels) and, under
  Advanced, profiles and privacy.
2 Duplicates: exact copies with the kept one highlighted and the extras ticked; Next moves the
  ticked extras into "To delete" at once. Skipped when there are no copies.
3 Catalog: one batch of related files per screen, surest first. Users confirm, change or add
  labels for the ticked files; SortZen learns after each batch and settles what it is now sure of.

Moving the files waits for the Review tab. The window runs nothing itself: the main window does
the reading, queuing and deleting in the background and calls back.
"""
from __future__ import annotations

import os
import time

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSpinBox, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..ai.services import SERVICES
from ..engine.duplicates import KEEP_RULES
from ..engine.planner import SORT_OUT, TIDY
from . import theme
from .catalog_page import paths_from
from .opening import open_on_double_click
from ..services.file_facts import day
from .sortable import human_size
from .to_place_page import FlowLayout

PATH = Qt.ItemDataRole.UserRole
COPY = Qt.ItemDataRole.UserRole + 1
STEPS = ("1 Choose", "2 Duplicates", "3 Catalog", "Review")
OPTION_TEXT = {"meaning": "Match by meaning (on this PC)", "read_scans": "Read scans and pictures of documents",
               "gentle": "Be gentle with my computer"}


def _label(text: str = "", name: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(text, objectName=name) if name else QLabel(text)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _link(text: str, slot) -> QPushButton:
    button = QPushButton(text, objectName="link")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(lambda *_: slot())          # never Qt's "checked" as the slot's first value
    return button


def _section(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="section")
    col = QVBoxLayout(frame)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(0)
    col.addWidget(QLabel(title.upper(), objectName="sectionHead"))
    body = QVBoxLayout()
    body.setContentsMargins(14, 10, 14, 12)
    body.setSpacing(8)
    col.addLayout(body)
    return frame, body


def label_menu_on(widget, name: str, window) -> None:
    """Right-clicking a label chip offers Rename, Delete and Manage labels."""
    widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    widget.customContextMenuRequested.connect(lambda pos: window.label_menu(name, widget, pos))


def describe_facts(f) -> str:
    """One or two lines that help recognise a file: type, size, dates, site, title, pages and its first words."""
    parts = [f.kind] if f.kind else []
    if f.size:
        parts.append(human_size(f.size))
    if f.added:
        parts.append(f"downloaded or added {day(f.added)}" + (f" from {f.site}" if f.site else ""))
    if f.modified and day(f.modified) != day(f.added):
        parts.append(f"last saved {day(f.modified)}")
    if f.title:
        parts.append(f"title “{f.title}”")
    parts += f.extra
    text = " · ".join(parts)
    if f.snippet:
        text += f"\n“{f.snippet}”"
    return text


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


class StepBar(QWidget):
    def __init__(self):
        super().__init__()
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(20, 10, 20, 6)
        self.row.setSpacing(8)
        self.steps = []
        for i, text in enumerate(STEPS):
            if i:
                self.row.addWidget(QLabel("›", objectName="stepOff"))
            label = QLabel(text, objectName="stepOff")
            self.steps.append(label)
            self.row.addWidget(label)
        self.row.addStretch(1)
        self.count = QLabel(objectName="batchCount")
        self.row.addWidget(self.count)

    def show_step(self, index: int, count: str = "") -> None:
        from PySide6.QtGui import QFontMetrics

        for i, label in enumerate(self.steps):
            label.setObjectName("stepOn" if i == index else "stepOff")
            label.style().unpolish(label)
            label.style().polish(label)
            bold = label.font()
            bold.setBold(True)                  # room for the bold text and the pill's padding, so it is never cut
            label.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(label.text()) + 24)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.updateGeometry()
        self.count.setText(count)


class FolderRows(QWidget):
    """The folders in a section, one row each, with a way to remove them (and, for sources, how they're sorted)."""
    removed = Signal(str)
    mode_changed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(4)

    def set_folders(self, folders: list[tuple[str, str | None]], empty: str) -> None:
        _clear(self.col)
        if not folders:
            self.col.addWidget(_label(empty, "hint"))
        for path, mode in folders:
            row = QHBoxLayout()
            name = _label(path, wrap=False)
            name.setToolTip(path)
            row.addWidget(name, 1)
            if mode is not None:
                how = QComboBox()
                how.addItem("Sort into other folders", SORT_OUT)
                how.addItem("Tidy in place", TIDY)
                how.setCurrentIndex(0 if mode == SORT_OUT else 1)
                how.setAccessibleName(f"How {os.path.basename(path)} is sorted")
                how.currentIndexChanged.connect(lambda _, p=path, box=how: self.mode_changed.emit(p, box.currentData()))
                row.addWidget(how)
            remove = QPushButton("Remove", objectName="link")
            remove.clicked.connect(lambda _=False, p=path: self.removed.emit(p))
            row.addWidget(remove)
            self.col.addLayout(row)


class ChoosePage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.service = wizard.service
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(20, 4, 20, 12)
        col.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Session name", objectName="fieldLabel"))
        self.name = QLineEdit(time.strftime("Organizing session, %b %Y"))
        self.name.setAccessibleName("Session name")
        name_row.addWidget(self.name, 1)
        col.addLayout(name_row)
        col.addWidget(_label("Saved as you go; reopen it from the start screen.", "hint"))

        frame, box = _section("Input: folders to sort")
        self.sources = FolderRows()
        self.sources.removed.connect(self._remove)
        self.sources.mode_changed.connect(self._set_mode)
        box.addWidget(self.sources)
        row = QHBoxLayout()
        row.addWidget(_label("Drop folders here from Explorer, or", "hint"), 1)
        add = QPushButton("Add a folder…")
        add.clicked.connect(lambda: self._add(self.wizard.window.add_source))
        row.addWidget(add)
        box.addLayout(row)
        col.addWidget(frame)

        frame, box = _section("Output: where files go")
        self.destinations = FolderRows()
        self.destinations.removed.connect(self._remove)
        box.addWidget(self.destinations)
        row = QHBoxLayout()
        row.addWidget(_label("SortZen learns from what is already in these folders.", "hint"), 1)
        self.windows = QPushButton("Use my Windows folders")
        self.windows.setToolTip("Adds Documents, Pictures, Music and Videos")
        self.windows.clicked.connect(lambda: self._add(self.wizard.window.add_windows_folders))
        row.addWidget(self.windows)
        add = QPushButton("Add a folder…")
        add.clicked.connect(lambda: self._add(self.wizard.window.add_destination))
        row.addWidget(add)
        box.addLayout(row)
        col.addWidget(frame)

        frame, box = _section("Options")
        who = QButtonGroup(self)
        self.local = QRadioButton("SortZen only (free, on this PC)")
        self.use_ai = QRadioButton("Use AI:")
        who.addButton(self.local)
        who.addButton(self.use_ai)
        box.addWidget(self.local)
        ai_row = QHBoxLayout()
        ai_row.addWidget(self.use_ai)
        self.ai_service = QComboBox()
        for key, info in SERVICES.items():
            self.ai_service.addItem(info.caption, key)
        self.ai_service.setAccessibleName("AI service")
        ai_row.addWidget(self.ai_service)
        ai_row.addWidget(QLabel("spend at most"))
        self.cap = QDoubleSpinBox(minimum=0.0, maximum=100.0, decimals=2, prefix="$", singleStep=0.05)
        self.cap.setAccessibleName("Spending cap")
        ai_row.addWidget(self.cap)
        ai_row.addWidget(QLabel("per 1,000 files"))
        ai_row.addStretch(1)
        box.addLayout(ai_row)
        self.ai_hint = _label("", "hint")
        box.addWidget(self.ai_hint)
        self.ai_labels = QCheckBox("Ask the AI to suggest starting labels from the file names")
        box.addWidget(self.ai_labels)
        for widget in (self.local, self.use_ai):
            widget.toggled.connect(self._ai_changed)
        self.ai_service.currentIndexChanged.connect(self._ai_changed)
        self.options = {}
        for name, text in OPTION_TEXT.items():
            check = QCheckBox(text, checked=self.service.option(name))
            self.options[name] = check
            box.addWidget(check)
        level = QHBoxLayout()
        level.addWidget(QLabel("Move without asking when at least"))
        self.level = QSpinBox(minimum=50, maximum=100, suffix="% sure")
        self.level.setAccessibleName("Sureness level")
        level.addWidget(self.level)
        level.addStretch(1)
        box.addLayout(level)
        box.addWidget(_label("In Review, batches this sure need no check. Nothing moves until you confirm at "
                             "the end.", "hint"))
        box.addWidget(QLabel("Labels to start with", objectName="fieldLabel"))
        self.chips = FlowLayout(spacing=6)
        holder = QWidget()
        holder.setLayout(self.chips)
        box.addWidget(holder)
        box.addWidget(_label("Click an idea to add it. Labels are like tags: a file can have several. You can add "
                             "more in Step 3.", "hint"))
        col.addWidget(frame)

        frame, box = _section("Advanced")
        row = QHBoxLayout()
        row.addWidget(QLabel("Profile"))
        load = QPushButton("Load a profile…")
        load.clicked.connect(lambda: self._add(self.wizard.window.load_profile))
        save = QPushButton("Save as a profile…")
        save.clicked.connect(self.wizard.window.save_profile)
        row.addWidget(load)
        row.addWidget(save)
        row.addSpacing(18)
        row.addWidget(QLabel("Privacy"))
        privacy = QPushButton("What the AI may see…")
        privacy.clicked.connect(lambda: self.wizard.window.show_settings("Privacy"))
        row.addWidget(privacy)
        row.addStretch(1)
        box.addLayout(row)
        box.addWidget(_label("A profile keeps folders, labels, rules and options.", "hint"))
        col.addWidget(frame)
        col.addStretch(1)

    def refresh(self) -> None:
        self.sources.set_folders([(f["path"], f["mode"]) for f in self.service.source_folders()],
                                 "No folder yet. Add one, such as Downloads.")
        self.destinations.set_folders([(d, None) for d in self.service.destination_folders()],
                                      "No folder yet. Add one, or tidy the folders to sort in place.")
        self.windows.setVisible(bool(self.service.suggested_destinations()))
        on = bool(self.service.ai_value("ai_enabled")) and self.service.ai_ready()
        self.use_ai.setChecked(on)
        self.local.setChecked(not on)
        self.ai_service.setCurrentIndex(max(0, self.ai_service.findData(self.service.ai_service())))
        self.cap.setValue(float(self.service.ai_value("ai_cap_per_1000")))
        self.level.setValue(self.service.autonomy())
        self._fill_chips()
        self._ai_changed()
        self.wizard.next_button.setEnabled(bool(self.service.source_folders()))

    def _fill_chips(self) -> None:
        _clear(self.chips)
        for name in self.service.labels():
            chip = QLabel(name, objectName="labelChip")
            chip.setToolTip("Right-click to rename or delete this label")
            label_menu_on(chip, name, self.wizard.window)
            self.chips.addWidget(chip)
        for idea in self.service.label_ideas():
            button = QPushButton(f"+ {idea}", objectName="smallChip")
            button.setToolTip("Add this label")
            button.clicked.connect(lambda _=False, n=idea: self._add_label(n))
            self.chips.addWidget(button)
        new = QPushButton("+ New label", objectName="newChip")
        new.clicked.connect(lambda: self._add_label(None))
        self.chips.addWidget(new)
        if self.service.labels():
            self.chips.addWidget(_link("Manage labels…", self.wizard.window.manage_labels))

    def _add_label(self, name: str | None) -> None:
        if name is None:
            name, ok = QInputDialog.getText(self, "New label", "Name of the label (for example Work, Taxes or "
                                            "Photo session):")
            if not ok or not name.strip():
                return
        try:
            self.service.add_label(name)
        except ValueError as exc:
            QMessageBox.information(self, "Labels", str(exc))
        self._fill_chips()

    def _ai_changed(self, *_) -> None:
        key = self.ai_service.currentData()
        ready = self.service.has_api_key(key)
        for widget in (self.ai_service, self.cap, self.ai_labels):
            widget.setEnabled(self.use_ai.isChecked())
        if self.use_ai.isChecked() and not ready:
            self.ai_hint.setText(f"{SERVICES[key].name} needs its key: Edit › Settings › AI. Until then SortZen "
                                 "works on this PC only.")
        elif self.use_ai.isChecked():
            self.ai_hint.setText("The AI labels a sample of the files first (you see the cost and confirm); "
                                 "SortZen labels the rest from them. It sees only what your privacy settings allow.")
        else:
            self.ai_hint.setText("Nothing leaves this PC.")

    def _add(self, action) -> None:
        action()
        self.refresh()

    def _remove(self, path: str) -> None:
        self.wizard.window.remove_folder(path)
        self.refresh()

    def _set_mode(self, path: str, mode: str) -> None:
        self.wizard.window.set_mode(path, mode)

    def save_options(self) -> None:
        for name, check in self.options.items():
            self.service.set_option(name, check.isChecked())
        self.service.set_autonomy(self.level.value())
        self.service.set_ai_value("ai_enabled", self.use_ai.isChecked())
        self.service.set_ai_service(self.ai_service.currentData())
        self.service.set_ai_value("ai_cap_per_1000", round(self.cap.value(), 2))

    def wants_ai(self) -> bool:
        return self.use_ai.isChecked() and self.service.ai_ready()


class DuplicatesPage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.groups = []
        self._filling = False
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 4, 20, 12)
        row.setSpacing(16)
        left = QFrame(objectName="section")
        lcol = QVBoxLayout(left)
        lcol.setContentsMargins(0, 0, 0, 0)
        lcol.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 12, 8)
        self.count = QLabel(objectName="cardTitle")
        head.addWidget(self.count, 1)
        head.addWidget(QLabel("Ticked: to delete · Highlighted: kept", objectName="hint"))
        lcol.addLayout(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Folder", "Saved"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 150)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemChanged.connect(self._ticked)
        open_on_double_click(self.tree, lambda item: item.data(0, PATH), wizard.window.open_folder)
        lcol.addWidget(self.tree, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 6, 12, 8)
        foot.addWidget(_link("Select all", lambda: self._tick_all(True)))
        foot.addWidget(_link("Select none", lambda: self._tick_all(False)))
        foot.addStretch(1)
        foot.addWidget(QLabel("Double-click a file to open it · right-click to keep it instead", objectName="hint"))
        lcol.addLayout(foot)
        row.addWidget(left, 135)

        right = QVBoxLayout()
        right.setSpacing(14)
        card = QFrame(objectName="card")
        ccol = QVBoxLayout(card)
        ccol.setContentsMargins(18, 16, 18, 16)
        self.title = _label("", "bigTitle")
        ccol.addWidget(self.title)
        self.text = _label()
        ccol.addWidget(self.text)
        ccol.addWidget(_label("Every copy is checked byte for byte first. You can change this later on the "
                              "Copies tab.", "hint"))
        right.addWidget(card)
        keep, kcol = _section("Which copy to keep")
        self.rules = QButtonGroup(self)
        for key, text in KEEP_RULES.items():
            button = QRadioButton(text)
            button.setProperty("rule", key)
            self.rules.addButton(button)
            kcol.addWidget(button)
        self.rules.buttonClicked.connect(lambda b: self._keep_by(b.property("rule")))
        kcol.addWidget(_label("Right-click a copy in the list to keep that one instead.", "hint"))
        right.addWidget(keep)
        right.addStretch(1)
        row.addLayout(right, 100)

    def set_copies(self, groups: list, rule: str) -> None:
        self.groups = groups
        for button in self.rules.buttons():
            button.setChecked(button.property("rule") == rule)
        self._fill()

    def _keep_by(self, rule: str) -> None:
        self.wizard.flow.keep_by(rule)
        self._fill()

    def _fill(self) -> None:
        self._filling = True
        self.tree.clear()
        files = sum(len(g.copies) for g in self.groups)
        self.count.setText(f"Files · {files:,} copies in {len(self.groups):,} groups")
        for g in sorted(self.groups, key=lambda g: g.name.lower()):
            head = QTreeWidgetItem(self.tree, [g.name, f"{len(g.copies)} copies", f"{human_size(g.size)} each"])
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = head.font(0)
            font.setBold(True)
            head.setFont(0, font)
            for c in sorted(g.copies, key=lambda c: (not c.keep, c.path.lower())):
                when = time.strftime("%b %d %Y", time.localtime(c.modified_ns / 1e9))
                item = QTreeWidgetItem(head, [("KEEP  " if c.keep else "") + c.name,
                                              self.wizard.service.display(os.path.dirname(c.path)), when])
                item.setData(0, PATH, c.path)
                item.setData(0, COPY, c)
                item.setToolTip(0, c.path)
                if c.keep:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                    for column in range(3):
                        item.setBackground(column, QColor(theme.ACCENT_TINT))
                else:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                                  Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Checked if c.ticked else Qt.CheckState.Unchecked)
                    if c.note:
                        item.setText(2, f"{when} · {c.note}")
            head.setExpanded(True)
        self._filling = False
        self._update()

    def _ticked(self, item, column) -> None:
        copy = item.data(0, COPY)
        if self._filling or copy is None or copy.keep:
            return
        copy.ticked = item.checkState(0) == Qt.CheckState.Checked
        self._update()

    def _tick_all(self, on: bool) -> None:
        for g in self.groups:
            for c in g.extras:
                c.ticked = on
        self._fill()

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        copy = item.data(0, COPY) if item else None
        if copy is None:
            return
        menu = QMenu(self)
        group = next(g for g in self.groups if copy in g.copies)
        if not copy.keep:
            menu.addAction("Keep this copy instead", lambda: (group.keep_instead(copy.path), self._fill()))
        from .opening import add_file_actions

        add_file_actions(menu, [copy.path], self.wizard.window.open_folder, delete=False)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _update(self) -> None:
        files = sum(len(g.copies) for g in self.groups)
        ticked = sum(1 for g in self.groups for c in g.extras if c.ticked)
        self.title.setText(f"I found {files:,} files that appear to be duplicates.")
        self.text.setText(f"Mark the {ticked:,} extra cop{'y' if ticked == 1 else 'ies'} for deletion? They move into "
                          "a “To delete” folder when you click Next, so the next steps aren't cluttered. Nothing is "
                          "deleted, and Undo puts them back.")
        self.wizard.next_button.setText(f"Next: {ticked:,} cop{'y' if ticked == 1 else 'ies'} to “To delete”"
                                        if ticked else "Next")


class CatalogPage(QWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.service = wizard.service
        self.batch = None
        self.chosen: list[str] = []
        self._filling = False
        col = QVBoxLayout(self)
        col.setContentsMargins(20, 0, 20, 12)
        col.setSpacing(10)
        self.progress = QProgressBar(textVisible=False)
        col.addWidget(self.progress)

        self.banner = QFrame(objectName="banner")
        brow = QHBoxLayout(self.banner)
        brow.setContentsMargins(12, 8, 12, 8)
        self.banner_text = _label()
        brow.addWidget(self.banner_text, 1)
        self.banner_yes = QPushButton()
        self.banner_change = QPushButton("Change it…")
        self.banner_change.setToolTip("Choose another folder (or label) before making the rule")
        self.banner_change.clicked.connect(self._change_rule)
        self.banner_no = QPushButton("Not now")
        brow.addWidget(self.banner_yes)
        brow.addWidget(self.banner_change)
        brow.addWidget(self.banner_no)
        self.banner_yes.clicked.connect(lambda: self._banner_answer(True))
        self.banner_no.clicked.connect(lambda: self._banner_answer(False))
        self.banner.hide()
        self.offer = None
        col.addWidget(self.banner)

        row = QHBoxLayout()
        row.setSpacing(16)
        left = QFrame(objectName="section")
        lcol = QVBoxLayout(left)
        lcol.setContentsMargins(0, 0, 0, 0)
        lcol.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 12, 8)
        self.files_title = QLabel(objectName="cardTitle")
        head.addWidget(self.files_title)
        self.why = QLabel(objectName="hint")
        self.why.setWordWrap(True)
        self.why.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.why, 1)
        lcol.addLayout(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Downloaded", "Size", "Folder", "From"])
        self.tree.headerItem().setToolTip(1, "When the file arrived on this PC: downloaded, copied or saved there")
        self.tree.headerItem().setToolTip(4, "The website it was downloaded from, when Windows noted it")
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        for column, width in enumerate((200, 90, 66, 130, 110)):
            self.tree.setColumnWidth(column, width)
        self.tree.itemChanged.connect(self._ticked)
        self.tree.currentItemChanged.connect(lambda item, _: self._show_facts(item))
        open_on_double_click(self.tree, lambda item: item.data(0, PATH), wizard.window.open_folder)
        lcol.addWidget(self.tree, 1)
        self.facts = QLabel(objectName="hint")
        self.facts.setWordWrap(True)
        self.facts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.facts.setContentsMargins(12, 6, 12, 0)
        lcol.addWidget(self.facts)
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 6, 12, 8)
        foot.addWidget(_link("Select all", lambda: self._tick_all(True)))
        foot.addWidget(_link("Select none", lambda: self._tick_all(False)))
        foot.addStretch(1)
        foot.addWidget(QLabel("Double-click a file to open it", objectName="hint"))
        lcol.addLayout(foot)
        row.addWidget(left, 140)

        self.panel = QFrame(objectName="card")
        self.pcol = QVBoxLayout(self.panel)
        self.pcol.setContentsMargins(18, 16, 18, 16)
        self.pcol.setSpacing(12)
        self.panel_title = _label("", "bigTitle")
        self.pcol.addWidget(self.panel_title)
        self.panel_text = _label("", "muted")
        self.pcol.addWidget(self.panel_text)
        self.typed = QLineEdit(placeholderText="Type a label, for example: Bank statements")
        self.typed.setAccessibleName("Type a label")
        self.typed.returnPressed.connect(self._typed_label)
        self.typed.textChanged.connect(lambda _: self._update())
        self.pcol.addWidget(self.typed)
        self.suggested = FlowLayout(spacing=10)
        holder = QWidget()
        holder.setLayout(self.suggested)
        self.pcol.addWidget(holder)
        self.others_text = _label("Click a label to take it off. Add another:", "hint")
        self.pcol.addWidget(self.others_text)
        self.others = FlowLayout(spacing=8)
        holder = QWidget()
        holder.setLayout(self.others)
        self.pcol.addWidget(holder)
        self.pcol.addStretch(1)
        links = QHBoxLayout()
        links.setSpacing(14)
        self.to_review = _link("Send to Review without labels", self._send_to_review)
        links.addWidget(self.to_review)
        self.together = _link("Keep their folder together", self._keep_together)
        links.addWidget(self.together)
        links.addWidget(_link("Write a note", self._note))
        links.addWidget(_link("These don't belong together", self._apart))
        links.addWidget(_link("Delete", self._delete))
        links.addStretch(1)
        self.pcol.addWidget(QFrame(objectName="rule"))
        self.pcol.addLayout(links)
        row.addWidget(self.panel, 100)
        col.addLayout(row, 1)

    # ---------------------------------------------------------------- showing a batch
    def show_batch(self) -> None:
        flow = self.wizard.flow
        self.batch = flow.current()
        if self.batch is None:
            if self.wizard.learning:            # the last answers may bring files back: wait for them
                self.tree.clear()
                self.files_title.setText("Files")
                self.why.setText("")
                self.panel_title.setText("SortZen is learning from your answers…")
                self.wizard.next_button.setEnabled(False)
                return
            self.wizard.catalog_done()
            return
        number, total = flow.batch_number()
        later = flow.is_later(self.batch)
        self.wizard.steps.show_step(2, f"Batch {number} of {total} · " + ("they came back" if later else
                                                                            "surest first"))
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(number - 1)
        self._filling = True
        self.tree.clear()
        facts = self.service.file_facts(self.batch.paths)
        for path in self.batch.paths:
            f = facts[path]
            item = QTreeWidgetItem(self.tree, [os.path.basename(path), day(f.added), human_size(f.size) if f.size else "",
                                               self.service.display(os.path.dirname(path)), f.site])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setData(0, PATH, path)
            item.setToolTip(0, f"{path}\n{describe_facts(f)}")
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._filling = False
        first = self.tree.topLevelItem(0)
        if first is not None:
            self.tree.setCurrentItem(first)
        self._show_facts(first)
        n = len(self.batch.paths)
        self.files_title.setText(f"Files · {n:,}")
        self.why.setText(self.batch.why)
        self.chosen = [label for label, _ in self.batch.labels]
        self.typed.clear()
        self.wizard.back_button.setEnabled(True)
        self._fill_labels()
        self._update()

    def refresh_counts(self) -> None:
        """The batch number, progress and footer after SortZen learned, without touching the list on screen."""
        flow = self.wizard.flow
        if self.batch is None:
            return
        number, total = flow.batch_number()
        self.wizard.steps.show_step(2, f"Batch {number} of {total} · " + ("they came back" if flow.is_later(self.batch)
                                                                            else "surest first"))
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(number - 1)
        self._update()

    def _show_facts(self, item) -> None:
        """What helps recognise the selected file, under the list."""
        path = item.data(0, PATH) if item is not None else None
        if not path:
            self.facts.setText("")
            return
        from html import escape

        self.facts.setText(f"<b>{escape(os.path.basename(path))}</b> · " + escape(describe_facts(
            self.service.file_facts([path])[path])).replace("\n", "<br>"))

    def _fill_labels(self) -> None:
        _clear(self.suggested)
        _clear(self.others)
        guessed = dict(self.batch.labels)
        no_guess = not guessed
        self.typed.setVisible(no_guess)
        self.to_review.setVisible(no_guess)
        self.together.setVisible(not no_guess)
        for label in [*[x for x, _ in self.batch.labels], *[x for x in self.chosen if x not in guessed]]:
            text = f"{label} · {guessed[label]}%" if label in guessed else label
            chip = QPushButton(text, objectName="chip", checkable=True, checked=label in self.chosen)
            chip.setToolTip(("Click to take this label off" if label in self.chosen else "Click to give this label")
                            + ". Right-click to rename or delete it.")
            if label in self.service.labels():
                label_menu_on(chip, label, self.wizard.window)
            chip.toggled.connect(lambda on, x=label: self._choose(x, on))
            self.suggested.addWidget(chip)
        for label in self.service.labels():
            if label in guessed or label in self.chosen:
                continue
            chip = QPushButton(label, objectName="smallChip")
            chip.setToolTip("Click to give this label. Right-click to rename or delete it.")
            chip.clicked.connect(lambda _=False, x=label: self._choose(x, True))
            label_menu_on(chip, label, self.wizard.window)
            self.others.addWidget(chip)
        new = QPushButton("+ New label", objectName="newChip")
        new.clicked.connect(self._new_label)
        self.others.addWidget(new)
        if self.service.labels():
            self.others.addWidget(_link("Manage labels…", self.wizard.window.manage_labels))
        self.others_text.setText("Or pick one:" if no_guess and not self.chosen else
                                 "Click a label to take it off. Add another:")

    def labels_changed(self, renamed: dict) -> None:
        """A label was renamed (old -> new) or deleted (old -> None): the batch on screen follows."""
        if self.batch is None:
            return
        chosen = []
        for label in self.chosen:
            label = renamed.get(label, label)
            if label and label not in chosen:
                chosen.append(label)
        self.chosen = chosen
        merged: dict[str, int] = {}
        for label, percent in self.batch.labels:
            label = renamed.get(label, label)
            if label:
                merged[label] = max(merged.get(label, 0), percent)
        self.batch.labels = sorted(merged.items(), key=lambda lp: -lp[1])
        self._fill_labels()
        self._update()

    def _choose(self, label: str, on: bool) -> None:
        if on and label not in self.chosen:
            self.chosen.append(label)
        elif not on and label in self.chosen:
            self.chosen.remove(label)
        self._fill_labels()
        self._update()

    def _new_label(self) -> None:
        name, ok = QInputDialog.getText(self, "New label", "Name of the label (for example Work, Taxes or "
                                        "Photo session):")
        name = " ".join(name.split())
        if ok and name:
            existing = next((x for x in self.service.labels() if x.lower() == name.lower()), name)
            self._choose(existing, True)

    def _typed_label(self) -> None:
        name = " ".join(self.typed.text().split())
        if name:
            existing = next((x for x in self.service.labels() if x.lower() == name.lower()), name)
            self.typed.clear()
            self._choose(existing, True)

    def ticked(self) -> list[str]:
        found = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                found.append(item.data(0, PATH))
        return found

    def _ticked(self, item, column) -> None:
        if not self._filling:
            self._update()

    def _tick_all(self, on: bool) -> None:
        self._filling = True
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self._filling = False
        self._update()

    def _update(self) -> None:
        if self.batch is None:
            return
        ticked = len(self.ticked())
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            off = item.checkState(0) != Qt.CheckState.Checked
            item.setText(3, self.service.display(os.path.dirname(item.data(0, PATH)))
                         + (" · unticked: comes back later" if off else ""))
        if self.batch.labels:
            self.panel_title.setText(f"Confirm labels for the {ticked:,} ticked file{'s' if ticked != 1 else ''}")
            self.panel_text.setText("")
            self.panel_text.hide()
        else:
            self.panel_title.setText("SortZen has no guess for these")
            self.panel_text.setText("Give them labels and SortZen learns what files like these are. Open one to have "
                                    "a look first.")
            self.panel_text.show()
        flow = self.wizard.flow
        left = flow.files_left()
        meter = flow.agreement_text()
        if flow.session.settled_batches:
            meter = f"Started with {flow.session.batches_at_start} batches: SortZen settled " \
                    f"{flow.session.settled_batches} of them by itself as it learned" + (f" · {meter}" if meter else "")
        self.wizard.footer_text.setText(f"{left:,} file{'s' if left != 1 else ''} left to look at"
                                        + (f" · {meter}" if meter else ""))
        typed = bool(self.typed.isVisible() and self.typed.text().strip())
        self.wizard.next_button.setEnabled(bool(ticked) and (bool(self.chosen) or typed))
        self.wizard.next_button.setText("Confirm and next batch")

    # ---------------------------------------------------------------- answers
    def confirm(self) -> None:
        if self.typed.isVisible() and self.typed.text().strip():
            self._typed_label()
        if not self.chosen or self.batch is None:
            return
        self.wizard.flow.confirm(self.batch, self.ticked(), list(self.chosen), learn=False)
        self.banner.hide()
        self.show_batch()                       # the next batch at once; SortZen learns in the background
        self.wizard.start_learning()
        self.wizard.changed()

    def _show_learned(self, learned) -> None:
        parts = []
        if learned.settled_batches:
            parts.append(f"{learned.settled_batches} more batch{'es' if learned.settled_batches != 1 else ''} "
                         f"({learned.settled_files:,} files) {'are' if learned.settled_batches != 1 else 'is'} now "
                         "settled and skipped.")
        self.offer = None
        if learned.merge:
            drop, keep = learned.merge
            parts.append(f"It also suggests merging the label “{drop}” into “{keep}”.")
            self.offer = ("merge", learned.merge)
            self.banner_yes.setText("Merge them")
        elif learned.folder is not None:
            parts.append(f"Suggestion: {learned.folder.title} ({learned.folder.why}).")
            self.offer = ("folder", learned.folder)
            self.banner_yes.setText("Make it a rule")
        if not parts:
            self.banner.hide()
            return
        self.banner_text.setText("<b>Learned from your last batch:</b> " + " ".join(parts))
        self.banner_yes.setVisible(self.offer is not None)
        self.banner_change.setVisible(self.offer is not None and self.offer[0] == "folder")
        self.banner_no.setText("Not now" if self.offer else "OK")
        self.banner.show()

    def _banner_answer(self, yes: bool) -> None:
        offer, self.offer = self.offer, None
        self.banner.hide()
        if offer is None:
            return
        kind, what = offer
        if kind == "merge":
            if yes:
                self.wizard.flow.merge_labels(*what)
                self.wizard.start_learning()
                self.wizard.window.statusBar().showMessage(f"“{what[0]}” merged into “{what[1]}”.", 6000)
            else:
                self.wizard.flow.decline_merge(*what)
        elif yes:
            before = self.service.add_rule(what.rule)
            self.wizard.window._push_undo("Make a rule", lambda: self.service.restore_rules(before))
            self.wizard.window.statusBar().showMessage(f"{what.title}: used when the plan is made for Review.", 6000)
        else:
            self.service.decline_rule(what.rule)
        self.show_batch()

    def _change_rule(self) -> None:
        """Make the suggested rule with another folder or label; the suggestion itself isn't offered again."""
        from .dialogs import RuleDialog

        if self.offer is None or self.offer[0] != "folder":
            return
        suggestion = self.offer[1]
        dialog = RuleDialog(self, self.service, suggestion.rule, self.wizard.flow.plan, "Change the rule, then make it")
        if not dialog.exec() or dialog.chosen is None:
            return
        self.offer = None
        self.banner.hide()
        before = self.service.settings_snapshot()
        self.service.change_rule(suggestion.rule, dialog.chosen)
        self.service.decline_rule(suggestion.rule)
        self.wizard.window._push_undo("Make a rule", lambda: self.service.restore_settings(before))
        self.wizard.window.statusBar().showMessage(
            f"{self.service.describe_rule(dialog.chosen)}: used when the plan is made for Review.", 6000)
        self.show_batch()

    def skip(self) -> None:
        if self.batch is not None:
            self.wizard.flow.skip(self.batch)
            self.banner.hide()
            self.wizard.changed()
            self.show_batch()

    def back(self) -> bool:
        if self.wizard.flow.back():
            self.banner.hide()
            self.wizard.changed()
            self.show_batch()
            return True
        return False

    def _send_to_review(self) -> None:
        ticked = self.ticked()
        if ticked:
            self.wizard.flow.send_to_review(self.batch, ticked)
            self.wizard.changed()
            self.show_batch()

    def _apart(self) -> None:
        ticked = self.ticked()
        if ticked:
            self.wizard.flow.keep_apart(self.batch, ticked)
            self.wizard.window.statusBar().showMessage(
                f"{len(ticked):,} file{'s' if len(ticked) != 1 else ''} come back later, one by one.", 6000)
            self.wizard.changed()
            self.show_batch()

    def _keep_together(self) -> None:
        ticked = self.ticked()
        if ticked:
            self.wizard.window.keep_together(os.path.dirname(ticked[0]))

    def _note(self) -> None:
        ticked = self.ticked()
        if not ticked:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Write a note", f"Anything special about {'these files' if len(ticked) > 1 else 'this file'}? For "
            "example: “for the 2023 audit” or “keep with Mum's documents”. Its words count for labels and folders; "
            "naming a folder sends it there.", self.service.file_note(ticked[0]))
        if ok:
            for path in ticked:
                self.service.set_file_note(path, text)
            self.wizard.window.statusBar().showMessage("Note saved.", 5000)

    def _delete(self) -> None:
        ticked = self.ticked()
        if ticked:
            self.wizard.window.delete_files(ticked)


class _Learner(QObject):
    done = Signal(object)


class SessionWizard(QDialog):
    """Steps 1 to 3 of an organizing session. ``flow`` is None until Step 1 is done."""
    step_done = Signal(str)                 # "choose", "duplicates", "catalog": the main window carries on

    def __init__(self, window, flow=None):
        super().__init__(window)
        self.window = window
        self.service = window.service
        self.flow = flow
        self.learning = False
        self._again = False
        self._hub = _Learner(self)
        self._hub.done.connect(self._learned)
        self.setWindowTitle("New organizing session" if flow is None else flow.session.name)
        self.resize(980, 760)
        self.setAcceptDrops(True)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.steps = StepBar()
        col.addWidget(self.steps)
        self.stack = QStackedWidget()
        self.choose = ChoosePage(self)
        self.duplicates = DuplicatesPage(self)
        self.catalog = CatalogPage(self)
        for page in (self.choose, self.duplicates, self.catalog):
            self.stack.addWidget(page)
        col.addWidget(self.stack, 1)
        footer = QFrame(objectName="footer")
        row = QHBoxLayout(footer)
        row.setContentsMargins(20, 12, 20, 12)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self._back)
        row.addWidget(self.back_button)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.footer_text = QLabel(objectName="hint")
        self.footer_text.setWordWrap(True)
        words.addWidget(self.footer_text)
        self.notice_label = QLabel(objectName="muted")
        self.notice_label.hide()
        words.addWidget(self.notice_label)
        row.addLayout(words, 1)
        self.skip_button = QPushButton()
        self.skip_button.clicked.connect(self._skip)
        row.addWidget(self.skip_button)
        self.next_button = QPushButton(objectName="primary")
        self.next_button.clicked.connect(self._next)
        self.next_button.setDefault(True)
        row.addWidget(self.next_button)
        col.addWidget(footer)
        self.show_choose()

    # ---------------------------------------------------------------- pages
    def show_choose(self) -> None:
        self.stack.setCurrentWidget(self.choose)
        self.steps.show_step(0)
        if self.flow is not None:
            self.choose.name.setText(self.flow.session.name)
        self.choose.refresh()
        self.back_button.hide()
        self.skip_button.setText("Cancel")
        self.next_button.setText("Next: find duplicates")
        self.footer_text.setText("Nothing is moved until you confirm at the end. SortZen reads only these folders.")

    def show_duplicates(self) -> None:
        copies = self.flow.copies()
        if not copies:
            self.flow.skip_duplicates()
            self.show_catalog()
            return
        self.stack.setCurrentWidget(self.duplicates)
        self.steps.show_step(1)
        self.flow.keep_by(self.flow.session.keep_rule)
        self.duplicates.set_copies(copies, self.flow.session.keep_rule)
        self.back_button.show()
        self.back_button.setEnabled(True)
        self.skip_button.setText("Skip: keep every copy")
        self.footer_text.setText("")
        self.next_button.setEnabled(True)

    def show_catalog(self) -> None:
        self.stack.setCurrentWidget(self.catalog)
        self.back_button.show()
        self.skip_button.setText("Skip for now")
        self.catalog.show_batch()

    def changed(self) -> None:
        """The start screen's list of sessions is brought up to date when the wizard closes."""

    # ---------------------------------------------------------------- learning in the background
    def start_learning(self) -> None:
        """SortZen learns from the answers so far without holding up the window; the result comes back to
        ``_learned``. Answers given meanwhile start another round when this one ends."""
        if self.learning:
            self._again = True
            return
        self.learning = True
        self._again = False
        flow, inputs, hub = self.flow, self.flow.learning_inputs(), self._hub

        def work():
            try:
                result = flow.learn(inputs)
            except Exception:                   # reported in the log; the batches stay as they are
                import logging

                logging.getLogger("sortzen").exception("Learning from the answers stopped")
                result = None
            try:
                hub.done.emit(result)
            except RuntimeError:                # the wizard has closed
                pass

        threading.Thread(target=work, daemon=True).start()

    def _learned(self, result) -> None:
        self.learning = False
        if result is not None and self.flow is not None:
            learned = self.flow.apply_learning(result, keep=self.catalog.batch)
            if learned is not None and self.stack.currentWidget() is self.catalog:
                self.catalog._show_learned(learned)
        if self._again:
            self.start_learning()
        if self.stack.currentWidget() is self.catalog:
            if self.catalog.batch is None:
                self.catalog.show_batch()
            else:
                self.catalog.refresh_counts()

    def labels_changed(self, renamed: dict) -> None:
        """Labels were renamed or deleted elsewhere: the step on screen shows them as they are now."""
        if self.stack.currentWidget() is self.choose:
            self.choose._fill_chips()
        elif self.stack.currentWidget() is self.catalog:
            self.catalog.labels_changed(renamed)
            if self.flow is not None and self.flow.batches:
                for b in self.flow.batches[1:]:             # the rest follow too, until SortZen learns again
                    b.labels = [(renamed.get(a, a), p) for a, p in b.labels if renamed.get(a, a)]
                self.start_learning()

    def notice(self, text: str) -> None:
        """A short message under the steps, such as “Opening …”; it goes after a few seconds."""
        from PySide6.QtCore import QTimer

        self.notice_label.setText(text)
        self.notice_label.show()
        QTimer.singleShot(5000, lambda: self.notice_label.text() == text and self.notice_label.hide())

    def catalog_done(self) -> None:
        self.flow.finish_catalog()
        self.step_done.emit("catalog")

    # ---------------------------------------------------------------- footer
    def _next(self) -> None:
        page = self.stack.currentWidget()
        if page is self.choose:
            if not self.service.source_folders():
                return
            self.choose.save_options()
            if self.flow is None:
                self.flow = self.service.new_session(self.choose.name.text())
            else:
                self.flow.rename(self.choose.name.text())
            self.setWindowTitle(self.flow.session.name)
            self.flow.use_folders()
            self.step_done.emit("choose")
        elif page is self.duplicates:
            if self.flow.ticked_copies():
                self.step_done.emit("duplicates")
            else:
                self.flow.skip_duplicates()
                self.show_catalog()
        else:
            self.catalog.confirm()

    def _skip(self) -> None:
        page = self.stack.currentWidget()
        if page is self.choose:
            self.reject()
        elif page is self.duplicates:
            self.flow.skip_duplicates()
            self.show_catalog()
        else:
            self.catalog.skip()

    def _back(self) -> None:
        page = self.stack.currentWidget()
        if page is self.catalog and self.catalog.back():
            return
        self.show_choose()

    # ---------------------------------------------------------------- folders dropped from Explorer
    def dragEnterEvent(self, event) -> None:
        if self.stack.currentWidget() is self.choose and any(os.path.isdir(p) for p in paths_from(event.mimeData())):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for path in paths_from(event.mimeData()):
            if os.path.isdir(path):
                self.window.add_source(path)
        self.choose.refresh()
