"""Click-to-sort columns for every list: names in natural order, numbers and sizes as numbers."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

SORT_ROLE = Qt.ItemDataRole.UserRole + 50


def natural(text: str) -> tuple:
    """"file 2" before "file 10", ignoring capitals."""
    return tuple(int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text or ""))


class SortItem(QTreeWidgetItem):
    """A row that sorts by a per-column key (set with set_key), or by its text in natural order."""

    def set_key(self, column: int, key) -> None:
        self.setData(column, SORT_ROLE, key)

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree else 0
        mine, theirs = self.data(column, SORT_ROLE), other.data(column, SORT_ROLE)
        if mine is None or theirs is None or type(mine) is not type(theirs):
            return natural(self.text(column)) < natural(other.text(column))
        return mine < theirs


def make_sortable(tree: QTreeWidget, column: int = 0, order=Qt.SortOrder.AscendingOrder) -> None:
    """Clicking a column heading sorts by it; clicking again reverses."""
    tree.setSortingEnabled(True)
    tree.header().setSortIndicatorShown(True)
    tree.header().setSectionsClickable(True)
    tree.sortByColumn(column, order)


def human_size(size: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.0f} {unit}" if unit == "bytes" else f"{size:,.1f} {unit}"
        size /= 1024
    return ""
