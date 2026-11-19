"""Properties panel: categorised property grid with inline editors.

Each property is (category, label, value, editor, key). ``editor`` is
``None`` for read-only values, ``"text"`` for a line edit, ``"multiline"``,
or a list of choices (editable combo box). Edits are committed through
``propertyEdited(key, value)``; the owner validates and calls
``refresh`` again (or ``revert`` on error).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme


@dataclass
class Prop:
    category: str
    label: str
    value: object
    editor: object = None  # None | "text" | list[str]
    key: str | None = None
    tooltip: str = ""


class PropertiesPanel(QWidget):
    propertyEdited = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QLabel("No selection")
        self.header.setStyleSheet(
            f"background:#E9EEF4;color:{theme.NAVY};font-weight:600;padding:6px 8px;"
            f"border-bottom:1px solid {theme.BORDER}"
        )
        lay.addWidget(self.header)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Property", "Value"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setStretchLastSection(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        lay.addWidget(self.tree)
        self.editors: dict[str, QWidget] = {}
        self._values: dict[str, str] = {}

    def show_properties(self, title: str, props: list[Prop]) -> None:
        self.header.setText(title)
        self.tree.clear()
        self.editors.clear()
        self._values.clear()
        cats: dict[str, QTreeWidgetItem] = {}
        bold = QFont()
        bold.setBold(True)
        for p in props:
            cat = cats.get(p.category)
            if cat is None:
                cat = QTreeWidgetItem([p.category, ""])
                cat.setFont(0, bold)
                cat.setFirstColumnSpanned(True)
                self.tree.addTopLevelItem(cat)
                cats[p.category] = cat
            it = QTreeWidgetItem([p.label, ""])
            if p.tooltip:
                it.setToolTip(0, p.tooltip)
                it.setToolTip(1, p.tooltip)
            cat.addChild(it)
            text = "" if p.value is None else str(p.value)
            if p.editor is None or p.key is None:
                it.setText(1, text)
                it.setToolTip(1, p.tooltip or text)
                it.setForeground(1, Qt.GlobalColor.darkGray)
                continue
            self._values[p.key] = text
            if isinstance(p.editor, list):
                ed = QComboBox()
                ed.setEditable(True)
                ed.addItems([str(c) for c in p.editor])
                ed.setCurrentText(text)
                ed.lineEdit().setCursorPosition(0)
                ed.setToolTip(p.tooltip or text)
                ed.lineEdit().editingFinished.connect(lambda k=p.key, e=ed: self._commit(k, e.currentText()))
                ed.activated.connect(lambda _i, k=p.key, e=ed: self._commit(k, e.currentText()))
            else:
                ed = QLineEdit(text)
                ed.setCursorPosition(0)
                ed.editingFinished.connect(lambda k=p.key, e=ed: self._commit(k, e.text()))
            ed.setFrame(False)
            self.tree.setItemWidget(it, 1, ed)
            self.editors[p.key] = ed
        self.tree.expandAll()

    def clear_selection(self) -> None:
        self.show_properties("No selection", [])

    def _commit(self, key: str, value: str) -> None:
        if self._values.get(key) == value:
            return
        self._values[key] = value
        self.propertyEdited.emit(key, value)

    def revert(self, key: str, value: str) -> None:
        ed = self.editors.get(key)
        self._values[key] = value
        if isinstance(ed, QComboBox):
            ed.setCurrentText(value)
        elif isinstance(ed, QLineEdit):
            ed.setText(value)

    def value_of(self, label: str) -> str | None:
        """Text of a read-only or editable property by label (used in tests)."""
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            for j in range(cat.childCount()):
                it = cat.child(j)
                if it.text(0) == label:
                    w = self.tree.itemWidget(it, 1)
                    if isinstance(w, QComboBox):
                        return w.currentText()
                    if isinstance(w, QLineEdit):
                        return w.text()
                    return it.text(1)
        return None
