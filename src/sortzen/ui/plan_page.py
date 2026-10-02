"""The Plan tab: every file and folder in Ready, Review, Staying or "Sorted from the inside",
with how each percentage was worked out. Nothing moves in this version."""
from __future__ import annotations

import html
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSpinBox, QSplitter,
    QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..services.plan_view import GROUPS, READY, SORTED_INSIDE, STAYING, TO_REVIEW, PlanRow
from . import theme

GROUP_HINTS = {
    READY: "At or above your level: SortZen would move these without asking.",
    TO_REVIEW: "Below your level, or unclear: these wait for you.",
    STAYING: "Already where they belong.",
    SORTED_INSIDE: "Messy folders whose files are sorted one by one; emptied folders would be removed.",
}
ROW = Qt.ItemDataRole.UserRole


class PlanPage(QWidget):
    change_destination = Signal(list)        # rows
    leave_in_place = Signal(list)
    forget_choice = Signal(list)
    open_folder = Signal(str)
    update_plan = Signal()
    export = Signal()

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.plan = None
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
        export = QPushButton("Export to Excel…")
        export.clicked.connect(self.export)
        top.addWidget(export)
        col.addLayout(top)
        level_row = QHBoxLayout()
        level_row.addWidget(QLabel("Move without asking when at least"))
        self.level = QSpinBox(minimum=50, maximum=100, suffix="% sure", value=service.autonomy())
        self.level.setToolTip("Suggestions at or above this go to Ready; the rest wait in Review.")
        level_row.addWidget(self.level)
        self.ask_all = QCheckBox("Ask me about everything", checked=service.ask_everything())
        level_row.addSpacing(12)
        level_row.addWidget(self.ask_all)
        level_row.addStretch(1)
        col.addLayout(level_row)
        self.note = QLabel("Plan only: nothing is moved in this version. Change any destination and SortZen learns "
                           "from it.", objectName="hint")
        self.note.setWordWrap(True)
        col.addWidget(self.note)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Sure", "From", "To"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._show_details)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 56)
        self.tree.setColumnWidth(2, 200)
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
        split.setSizes([900, 360])
        col.addWidget(split, 1)

        self.level.valueChanged.connect(self._level_changed)
        self.ask_all.toggled.connect(self._ask_all_changed)
        self._show_details()

    # ---------------------------------------------------------------- filling
    def set_plan(self, plan) -> None:
        self.plan = plan
        self.refresh()

    def refresh(self) -> None:
        if self.plan is None:
            return
        groups = self.service.plan_rows(self.plan)
        expanded = {self.tree.topLevelItem(i).text(0).split(" (")[0]: self.tree.topLevelItem(i).isExpanded()
                    for i in range(self.tree.topLevelItemCount())}
        self.tree.clear()
        bold = QFont(self.tree.font())
        bold.setBold(True)
        colours = {READY: theme.ACCENT, TO_REVIEW: theme.WARN_TEXT, STAYING: theme.MUTED, SORTED_INSIDE: theme.MUTED}
        for name in GROUPS:
            rows = groups[name]
            if not rows and name == SORTED_INSIDE:
                continue
            top = QTreeWidgetItem(self.tree, [f"{name} ({len(rows)})  ·  {GROUP_HINTS[name]}"])
            top.setFont(0, bold)
            top.setForeground(0, QColor(colours[name]))
            top.setFirstColumnSpanned(True)
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for row in rows:
                self._row_item(top, row)
            top.setExpanded(expanded.get(name, name != STAYING))
        n = {name: len(rows) for name, rows in groups.items()}
        questions = sum(1 for q in self.plan.questions if q.answer is None)
        parts = [f"{n[READY]} ready", f"{n[TO_REVIEW]} to review", f"{n[STAYING]} staying"]
        if questions:
            parts.append(f"{questions} question{'s' if questions != 1 else ''}")
        self.summary.setText(" · ".join(parts))
        self._show_details()

    def _row_item(self, parent, row: PlanRow) -> QTreeWidgetItem:
        name = f"{row.name}  (folder, {row.files} files)" if row.is_folder else row.name
        to = self.service.display(row.destination) if row.destination else "—"
        if row.new_folder and row.destination:
            to += "  (new folder)"
        if row.action == "Sort inside":
            to = "its files are sorted one by one"
        sure = "" if row.action in ("Sort inside",) else f"{row.percent}%"
        item = QTreeWidgetItem(parent, [name, sure, self.service.display(row.current), to])
        item.setData(0, ROW, row)
        item.setToolTip(0, row.path)
        item.setToolTip(3, to)
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if row.note:
            item.setForeground(0, QColor(theme.MUTED))
        return item

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
        menu = QMenu(self)
        change = menu.addAction("Change destination…", lambda: self.change_destination.emit(files))
        stay = menu.addAction("Leave it where it is", lambda: self.leave_in_place.emit(files))
        corrected = [r for r in files if os.path.normcase(r.path) in
                     {os.path.normcase(p) for p in self.service.corrections()}]
        forget = menu.addAction("Forget my choice", lambda: self.forget_choice.emit(corrected))
        change.setEnabled(bool(files))
        stay.setEnabled(bool(files))
        forget.setEnabled(bool(corrected))
        menu.addSeparator()
        menu.addAction("Open the folder it is in", lambda: self.open_folder.emit(rows[0].current))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ---------------------------------------------------------------- level
    def _level_changed(self, value: int) -> None:
        self.service.set_autonomy(value)
        self.refresh()

    def _ask_all_changed(self, on: bool) -> None:
        self.service.set_ask_everything(on)
        self.level.setEnabled(not on)
        self.refresh()
