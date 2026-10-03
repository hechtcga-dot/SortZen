"""The Plan tab: every file and folder in Ready, Review, Staying or "Sorted from the inside" (or grouped
by destination), with how each percentage was worked out, problems found before moving, search, sortable
columns and tick boxes for what to move."""
from __future__ import annotations

import html
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSpinBox,
    QSplitter, QTextBrowser, QTreeWidget, QVBoxLayout, QWidget,
)

from ..services.plan_view import GROUPS, READY, SORTED_INSIDE, STAYING, TO_REVIEW, PlanRow
from . import theme
from .sortable import SortItem, make_sortable, natural

GROUP_HINTS = {
    READY: "At or above your level: ticked, so they move when you confirm.",
    TO_REVIEW: "Below your level, or unclear: tick the ones that should move.",
    STAYING: "Already where they belong.",
    SORTED_INSIDE: "Messy folders whose files are sorted one by one; emptied folders are removed.",
}
ROW = Qt.ItemDataRole.UserRole
GROUP = Qt.ItemDataRole.UserRole + 2
NAME, TYPE, SURE, FROM, TO, NOTES = range(6)
BY_STATUS, BY_DESTINATION = "Ready and Review", "Destination folder"
NO_DESTINATION = "No destination yet"


class GroupItem(SortItem):
    """A group heading: groups keep their order whichever way the rows are sorted."""

    def __lt__(self, other) -> bool:
        mine, theirs = self.data(0, GROUP), other.data(0, GROUP)
        if mine is None or theirs is None:
            return super().__lt__(other)
        tree = self.treeWidget()
        descending = tree is not None and tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        return (mine > theirs) if descending else (mine < theirs)


class PlanPage(QWidget):
    change_destination = Signal(list)        # rows
    leave_in_place = Signal(list)
    forget_choice = Signal(list)
    open_folder = Signal(str)
    update_plan = Signal()
    export = Signal()
    move_ticked = Signal(list)               # rows to move
    ask_ai = Signal()
    move_to = Signal(list, str)              # rows, a recently chosen folder
    rename_folder = Signal(str)
    note_folder = Signal(str)

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.plan = None
        self.ticks: dict[str, bool] = {}             # rows ticked or unticked by hand
        self.ready_at_start: set[str] = set()
        self.changed_ready: set[str] = set()
        self._filling = False
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(8)

        top = QHBoxLayout()
        self.summary = QLabel(objectName="pageTitle")
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.summary, 1)
        refresh = QPushButton("Update plan")
        refresh.setToolTip("Read the folders again and use your answers and choices (F5)")
        refresh.clicked.connect(self.update_plan)
        top.addWidget(refresh)
        self.ai_button = QPushButton("Ask AI about unsure files…")
        self.ai_button.setToolTip("Shows what would be sent and what it may cost first. Answers are remembered.")
        self.ai_button.clicked.connect(self.ask_ai)
        top.addWidget(self.ai_button)
        export = QPushButton("Export to Excel…")
        export.clicked.connect(self.export)
        top.addWidget(export)
        self.move_button = QPushButton("Move ticked…", objectName="primary")
        self.move_button.setToolTip("Shows what will move, then moves it after you confirm. Undo puts it back.")
        self.move_button.clicked.connect(lambda: self.move_ticked.emit(self.ticked_rows()))
        top.addWidget(self.move_button)
        col.addLayout(top)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Move without asking when at least"))
        self.level = QSpinBox(minimum=50, maximum=100, suffix="% sure", value=service.autonomy())
        self.level.setToolTip("Suggestions at or above this go to Ready, ticked; the rest wait in Review.")
        controls.addWidget(self.level)
        self.ask_all = QCheckBox("Ask me about everything", checked=service.ask_everything())
        controls.addSpacing(8)
        controls.addWidget(self.ask_all)
        controls.addStretch(1)
        controls.addWidget(QLabel("Group by"))
        self.group_by = QComboBox()
        self.group_by.addItems([BY_STATUS, BY_DESTINATION])
        controls.addWidget(self.group_by)
        col.addLayout(controls)

        filters = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search names, folders and topics")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 2)
        self.source = QComboBox()
        self.source.setToolTip("Show files from one added folder only")
        filters.addWidget(self.source, 1)
        self.problems_only = QCheckBox("Only rows with problems")
        filters.addWidget(self.problems_only)
        col.addLayout(filters)
        self.accuracy = QLabel(objectName="hint")
        self.accuracy.setWordWrap(True)
        col.addWidget(self.accuracy)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Type", "Sure", "From", "To", "Notes"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._show_details)
        self.tree.itemChanged.connect(self._ticked)
        for column, width in ((NAME, 300), (TYPE, 80), (SURE, 56), (FROM, 180), (TO, 220), (NOTES, 160)):
            self.tree.setColumnWidth(column, width)
        make_sortable(self.tree, SURE, Qt.SortOrder.DescendingOrder)
        split.addWidget(self.tree)

        side = QFrame(objectName="card")
        side_col = QVBoxLayout(side)
        side_col.setContentsMargins(14, 12, 14, 12)
        side_col.addWidget(QLabel("How this was worked out", objectName="sectionCaps"))
        self.details = QTextBrowser()
        self.details.setOpenLinks(False)
        self.details.setFrameShape(QFrame.Shape.NoFrame)
        side_col.addWidget(self.details, 1)
        buttons = QHBoxLayout()
        self.change_button = QPushButton("Change destination…")
        self.change_button.clicked.connect(lambda: self.change_destination.emit(self.selected_files()))
        self.stay_button = QPushButton("Leave it where it is")
        self.stay_button.clicked.connect(lambda: self.leave_in_place.emit(self.selected_files()))
        buttons.addWidget(self.change_button)
        buttons.addWidget(self.stay_button)
        side_col.addLayout(buttons)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([900, 340])
        col.addWidget(split, 1)

        self.level.valueChanged.connect(self._level_changed)
        self.ask_all.toggled.connect(self._ask_all_changed)
        self.group_by.currentIndexChanged.connect(lambda _: self.refresh())
        self.search.textChanged.connect(lambda _: self._apply_filters())
        self.source.currentIndexChanged.connect(lambda _: self._apply_filters())
        self.problems_only.toggled.connect(lambda _: self._apply_filters())
        self._show_details()

    # ---------------------------------------------------------------- filling
    def set_plan(self, plan) -> None:
        self.plan = plan
        self.ticks.clear()
        groups = self.service.plan_rows(plan)
        self.ready_at_start = {os.path.normcase(r.path) for r in groups[READY]}
        self.changed_ready = set()
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem("All folders", "")
        for root in self.service.all_roots():
            self.source.addItem(f"From {os.path.basename(root) or root}", root)
        self.source.blockSignals(False)
        self.refresh()

    def note_corrections(self, paths) -> None:
        """Counts Ready suggestions users changed, for the accuracy line."""
        for p in paths:
            key = os.path.normcase(p)
            if key in self.ready_at_start:
                self.changed_ready.add(key)
        self._update_accuracy()

    def is_ticked(self, row: PlanRow, group: str) -> bool:
        key = os.path.normcase(row.path)
        if key in self.ticks:
            return self.ticks[key]
        return group == READY or (row.moves and row.percent == 100)

    def refresh(self) -> None:
        if self.plan is None:
            return
        groups = self.service.plan_rows(self.plan)
        self._filling = True
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        bold = QFont(self.tree.font())
        bold.setBold(True)
        by_destination = self.group_by.currentText() == BY_DESTINATION
        self.tree.setColumnHidden(TO, by_destination)          # the heading already says where they go
        if by_destination:
            self._fill_by_destination(groups, bold)
        else:
            self._fill_by_status(groups, bold)
        self.tree.setSortingEnabled(True)
        self._filling = False
        n = {name: len(rows) for name, rows in groups.items()}
        questions = sum(1 for q in self.plan.questions if q.answer is None)
        problems = sum(1 for g in (READY, TO_REVIEW) for r in groups[g] if r.problems)
        parts = [f"{n[READY]} ready", f"{n[TO_REVIEW]} to review", f"{n[STAYING]} staying"]
        if questions:
            parts.append(f"{questions} question{'s' if questions != 1 else ''}")
        if problems:
            parts.append(f"{problems} problem{'s' if problems != 1 else ''}")
        self.summary.setText(" · ".join(parts))
        self._apply_filters()
        self._update_ticked()
        self._update_accuracy()
        self._show_details()

    def _group(self, title: str, hint: str, order: int, colour: str, bold) -> GroupItem:
        top = GroupItem(self.tree, [f"{title}  ·  {hint}" if hint else title])
        top.setData(0, GROUP, order)
        top.setFont(0, bold)
        top.setForeground(0, QColor(colour))
        top.setFirstColumnSpanned(True)
        top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        return top

    def _fill_by_status(self, groups, bold) -> None:
        colours = {READY: theme.ACCENT, TO_REVIEW: theme.WARN_TEXT, STAYING: theme.MUTED, SORTED_INSIDE: theme.MUTED}
        for order, name in enumerate(GROUPS):
            rows = groups[name]
            if not rows and name == SORTED_INSIDE:
                continue
            top = self._group(f"{name} ({len(rows)})", GROUP_HINTS[name], order, colours[name], bold)
            for row in rows:
                self._row_item(top, row, name)
            top.setExpanded(name != STAYING)

    def _fill_by_destination(self, groups, bold) -> None:
        by_destination: dict[str, list[tuple[PlanRow, str]]] = {}
        for name in (READY, TO_REVIEW):
            for row in groups[name]:
                label = self.service.display(row.destination) if row.destination else NO_DESTINATION
                by_destination.setdefault(label, []).append((row, name))
        labels = sorted(by_destination, key=lambda l: (l == NO_DESTINATION, natural(l)))
        for order, label in enumerate(labels):
            rows = by_destination[label]
            top = self._group(f"{label} ({len(rows)})", "", order,
                              theme.WARN_TEXT if label == NO_DESTINATION else theme.ACCENT_DARK, bold)
            for row, name in rows:
                self._row_item(top, row, name)
            top.setExpanded(True)

    def _row_item(self, parent, row: PlanRow, group: str) -> SortItem:
        name = f"{row.name}  (folder, {row.files} files)" if row.is_folder else row.name
        to = self.service.display(row.destination) if row.destination else "—"
        if row.new_folder and row.destination:
            to += "  (new folder)"
        if row.action == "Sort inside":
            to = "its files are sorted one by one"
        sure = "" if row.action == "Sort inside" else f"{row.percent}%"
        notes = row.problems[0] if row.problems else ("Looks empty" if row.note else (row.topic and f"Topic: {row.topic}"))
        item = SortItem(parent, [name, row.kind, sure, self.service.display(row.current), to, notes or ""])
        item.setData(0, ROW, row)
        item.setData(0, GROUP, group)
        item.set_key(SURE, row.percent)
        item.setToolTip(NAME, row.path)
        item.setToolTip(TO, to)
        if row.problems:
            item.setToolTip(NOTES, "\n".join(row.problems))
            item.setForeground(NOTES, QColor(theme.WARN_TEXT))
        item.setTextAlignment(SURE, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if row.note:
            item.setForeground(NAME, QColor(theme.MUTED))
        if row.moves:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(NAME, Qt.CheckState.Checked if self.is_ticked(row, group) else Qt.CheckState.Unchecked)
        return item

    # ---------------------------------------------------------------- filters, ticks, accuracy
    def _rows_items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top, top.child(j)

    def _apply_filters(self) -> None:
        text = self.search.text().strip().lower()
        root = self.source.currentData() or ""
        only_problems = self.problems_only.isChecked()
        shown_per_group: dict[int, int] = {}
        for top, item in self._rows_items():
            row: PlanRow = item.data(0, ROW)
            visible = True
            if text:
                haystack = " ".join([row.name, self.service.display(row.current), self.service.display(row.destination),
                                     row.topic]).lower()
                visible = text in haystack
            if visible and root:
                visible = os.path.normcase(row.path).startswith(os.path.normcase(root.rstrip(os.sep) + os.sep))
            if visible and only_problems:
                visible = bool(row.problems)
            item.setHidden(not visible)
            shown_per_group[id(top)] = shown_per_group.get(id(top), 0) + visible
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top.setHidden(bool(text or root or only_problems) and not shown_per_group.get(id(top)))

    def _ticked(self, item, column: int) -> None:
        if self._filling or column != NAME or item.data(0, ROW) is None:
            return
        self.ticks[os.path.normcase(item.data(0, ROW).path)] = item.checkState(NAME) == Qt.CheckState.Checked
        self._update_ticked()

    def ticked_rows(self) -> list[PlanRow]:
        return [item.data(0, ROW) for _, item in self._rows_items()
                if item.data(0, ROW).moves and item.checkState(NAME) == Qt.CheckState.Checked]

    def set_ticks(self, rows, on: bool) -> None:
        for row in rows:
            if row.moves:
                self.ticks[os.path.normcase(row.path)] = on
        self.refresh()

    def _update_ticked(self) -> None:
        n = len(self.ticked_rows())
        self.move_button.setText(f"Move {n:,} ticked…" if n else "Move ticked…")
        self.move_button.setEnabled(bool(n))

    def _update_accuracy(self) -> None:
        ready = len(self.ready_at_start)
        if not ready:
            self.accuracy.setText("")
            return
        changed = len(self.changed_ready)
        right = round(100 * (ready - changed) / ready)
        self.accuracy.setText(f"So far you changed {changed} of {ready} Ready suggestions ({right}% right).")

    # ---------------------------------------------------------------- selection and details
    def selected_rows(self) -> list[PlanRow]:
        return [i.data(0, ROW) for i in self.tree.selectedItems() if i.data(0, ROW) is not None]

    def selected_files(self) -> list[PlanRow]:
        return [r for r in self.selected_rows() if not r.is_folder]

    def _show_details(self) -> None:
        rows = self.selected_rows()
        files = [r for r in rows if not r.is_folder]
        self.change_button.setEnabled(bool(files))
        self.stay_button.setEnabled(bool(files))
        if not rows:
            self.details.setHtml(f"<p style='color:{theme.MUTED}'>Select a file or folder to see why SortZen "
                                 f"suggests it.</p>")
            return
        if len(rows) > 1:
            self.details.setHtml(f"<p><b>{len(rows)} selected</b></p><p style='color:{theme.MUTED}'>Change their "
                                 f"destination together with the buttons below or by right-clicking.</p>")
            return
        self.details.setHtml(self._explain(rows[0]))

    def _explain(self, row: PlanRow) -> str:
        e = html.escape
        if row.action == "Sort inside":
            head = f"Sort “{e(row.name)}” from the inside"
        elif row.destination and row.action != "Stay":
            head = f"{row.percent}% sure → {e(self.service.display(row.destination))}"
        elif row.action == "Stay":
            head = "Stays where it is"
        else:
            head = "Waiting for you"
        parts = [f"<p style='font-size:11pt'><b>{head}</b></p>", f"<p style='color:{theme.MUTED}'>{e(row.path)}</p>"]
        if row.note:
            parts.append(f"<p style='color:{theme.WARN_TEXT}'>Looks empty</p>")
        if row.topic:
            parts.append(f"<p>Topic: <b>{e(row.topic)}</b></p>")
        parts.append("<table cellspacing='0' cellpadding='3'>")
        for reason in row.reasons:
            mark, colour = ("+", theme.ACCENT) if reason.supports else ("−", theme.WARN_TEXT)
            parts.append(f"<tr><td style='color:{colour};font-weight:600'>{mark}</td><td>{e(reason.text)}</td></tr>")
        parts.append("</table>")
        if row.problems:
            parts.append(f"<p style='color:{theme.WARN_TEXT}'><b>Before moving</b></p><ul>")
            parts += [f"<li style='color:{theme.WARN_TEXT}'>{e(p)}</li>" for p in row.problems]
            parts.append("</ul>")
        return "".join(parts)

    # ---------------------------------------------------------------- right-click
    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None or item.data(0, ROW) is None:
            return
        if not item.isSelected():
            self.tree.clearSelection()
            item.setSelected(True)
        rows, files = self.selected_rows(), self.selected_files()
        movable = [r for r in rows if r.moves]
        menu = QMenu(self)
        change = menu.addAction("Change destination…", lambda: self.change_destination.emit(files))
        recent = self.service.recent_destinations(self.plan)
        quick = menu.addMenu("Move to")
        for folder in recent:
            label = self.service.display(folder) + ("" if os.path.isdir(folder) else "  (new folder)")
            quick.addAction(label, lambda f=folder: self.move_to.emit(files, f))
        quick.setEnabled(bool(files and recent))
        if not recent:
            quick.setTitle("Move to (folders you choose appear here)")
        stay = menu.addAction("Leave it where it is", lambda: self.leave_in_place.emit(files))
        corrected = [r for r in files if os.path.normcase(r.path) in
                     {os.path.normcase(p) for p in self.service.corrections()}]
        forget = menu.addAction("Forget my choice", lambda: self.forget_choice.emit(corrected))
        change.setEnabled(bool(files))
        stay.setEnabled(bool(files))
        forget.setEnabled(bool(corrected))
        menu.addSeparator()
        tick = menu.addAction("Tick", lambda: self.set_ticks(movable, True))
        untick = menu.addAction("Untick", lambda: self.set_ticks(movable, False))
        tick.setEnabled(bool(movable))
        untick.setEnabled(bool(movable))
        menu.addSeparator()
        destination = rows[0].destination if rows[0].destination and rows[0].moves else None
        rename = menu.addAction("Rename its destination folder…",
                                lambda: self.rename_folder.emit(destination))
        rename.setEnabled(bool(destination))
        note = menu.addAction("Write a note about its destination folder…", lambda: self.note_folder.emit(destination))
        note.setEnabled(bool(destination))
        menu.addAction("Open the folder it is in", lambda: self.open_folder.emit(rows[0].current))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ---------------------------------------------------------------- level
    def sync_settings(self) -> None:
        """Show autonomy and "ask about everything" as saved (after Settings or a profile changed them)."""
        for widget in (self.level, self.ask_all):
            widget.blockSignals(True)
        self.level.setValue(self.service.autonomy())
        self.ask_all.setChecked(self.service.ask_everything())
        self.level.setEnabled(not self.service.ask_everything())
        for widget in (self.level, self.ask_all):
            widget.blockSignals(False)
        self.refresh()

    def _level_changed(self, value: int) -> None:
        self.service.set_autonomy(value)
        self.refresh()

    def _ask_all_changed(self, on: bool) -> None:
        self.service.set_ask_everything(on)
        self.level.setEnabled(not on)
        self.refresh()
