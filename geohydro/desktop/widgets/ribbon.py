"""Ribbon toolbar: tabs of labelled command groups.

Buttons are bound to QActions owned by the main window, so the ribbon and
the menus always share enabled/disabled state. Groups made only of planned
capabilities get a 'planned' caption.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class RibbonGroup(QFrame):
    def __init__(self, title: str, planned: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonGroup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 2)
        outer.setSpacing(2)
        self._row = QHBoxLayout()
        self._row.setSpacing(2)
        outer.addLayout(self._row, 1)
        cap = QLabel(f"{title}  ·  planned" if planned else title)
        cap.setObjectName("RibbonGroupTitlePlanned" if planned else "RibbonGroupTitle")
        cap.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        outer.addWidget(cap)
        self.title = title
        self.planned = planned
        self.buttons: list[QToolButton] = []

    def add_action(self, action: QAction, short_text: str | None = None) -> QToolButton:
        btn = QToolButton(self)
        btn.setDefaultAction(action)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        btn.setIconSize(QSize(28, 28))
        btn.setAutoRaise(True)
        if short_text:
            btn.setText(short_text)
        fm = btn.fontMetrics()
        btn.setMinimumWidth(max(56, fm.horizontalAdvance(btn.text()) + 18))
        btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._row.addWidget(btn)
        self.buttons.append(btn)
        return btn


class RibbonPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(4, 2, 4, 2)
        self._lay.setSpacing(0)
        self._lay.addStretch(1)
        self.groups: list[RibbonGroup] = []

    def add_group(self, title: str, planned: bool = False) -> RibbonGroup:
        g = RibbonGroup(title, planned, self)
        self._lay.insertWidget(self._lay.count() - 1, g)
        self.groups.append(g)
        return g


class Ribbon(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Ribbon")
        self.setDocumentMode(True)
        self.setFixedHeight(118)
        self.setUsesScrollButtons(True)
        self.pages: dict[str, RibbonPage] = {}

    def add_page(self, title: str) -> RibbonPage:
        page = RibbonPage()
        self.addTab(page, title)
        self.pages[title] = page
        return page

    def all_buttons(self) -> list[QToolButton]:
        return [b for p in self.pages.values() for g in p.groups for b in g.buttons]
