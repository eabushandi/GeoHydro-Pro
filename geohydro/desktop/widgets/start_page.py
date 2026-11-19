"""Start page shown in the workspace when no document is open."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from geohydro import APP_NAME, APP_TAGLINE, DEVELOPMENT_PHASE, __version__
from geohydro.engine.capabilities import CAPABILITIES

from .. import icons, theme


class StartPage(QWidget):
    newProject = Signal()
    openProject = Signal()
    importData = Signal()
    openSample = Signal()
    openRecent = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"StartPage{{background:{theme.WORK_BG};}}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 28, 36, 28)
        outer.setSpacing(18)

        hero = QFrame()
        hero.setStyleSheet(
            f"QFrame{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {theme.NAVY},stop:1 {theme.NAVY_3});"
            "border-radius:10px;} QLabel{background:transparent;}"
        )
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(24, 20, 24, 20)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(76))
        hl.addWidget(logo)
        tl = QVBoxLayout()
        t = QLabel(APP_NAME)
        t.setStyleSheet("color:white;font-size:22pt;font-weight:700;")
        s = QLabel(APP_TAGLINE)
        s.setStyleSheet(f"color:{theme.TURQUOISE};font-size:11pt;")
        v = QLabel(f"Version {__version__} · {DEVELOPMENT_PHASE}")
        v.setStyleSheet("color:#B8C7DA;font-size:9pt;")
        tl.addWidget(t)
        tl.addWidget(s)
        tl.addWidget(v)
        hl.addLayout(tl, 1)
        outer.addWidget(hero)

        row = QHBoxLayout()
        row.setSpacing(18)
        outer.addLayout(row, 1)

        # actions + recent
        left = self._card("Start")
        ll = left.layout()
        for text, ic, sig in (
            ("New Project", "new", self.newProject),
            ("Open Project…", "open", self.openProject),
            ("Import Data…", "import", self.importData),
            ("Open Sample Project", "folder", self.openSample),
        ):
            b = QPushButton(icons.icon(ic), "  " + text)
            b.setMinimumHeight(34)
            b.setStyleSheet("text-align:left;padding-left:12px;")
            b.clicked.connect(sig.emit)
            ll.addWidget(b)
        lab = QLabel("Recent projects")
        lab.setStyleSheet(f"color:{theme.MUTED};font-weight:600;margin-top:10px;")
        ll.addWidget(lab)
        self.recent = QListWidget()
        self.recent.itemActivated.connect(lambda it: self.openRecent.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.recent.itemDoubleClicked.connect(lambda it: self.openRecent.emit(it.data(Qt.ItemDataRole.UserRole)))
        ll.addWidget(self.recent, 1)
        row.addWidget(left, 1)

        # capability overview
        right = self._card("Capabilities in this release")
        rl = right.layout()
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        impl = [c for c in CAPABILITIES.values() if c.implemented]
        planned = {}
        for c in CAPABILITIES.values():
            if not c.implemented:
                planned.setdefault(c.phase, []).append(c.title)
        a = QLabel("<b>Available now</b><br>" + "<br>".join(f"✓ {c.title}" for c in impl))
        a.setStyleSheet(f"color:{theme.SUCCESS};")
        a.setAlignment(Qt.AlignmentFlag.AlignTop)
        grid.addWidget(a, 0, 0)
        ptxt = "<b>Planned (not yet available)</b><br>" + "<br>".join(
            f"<span style='color:{theme.NAVY_2}'>Phase {ph}:</span> " + ", ".join(sorted(t)[:3])
            + (f" and {len(t) - 3} more" if len(t) > 3 else "")
            for ph, t in sorted(planned.items())
        )
        p = QLabel(ptxt)
        p.setWordWrap(True)
        p.setAlignment(Qt.AlignmentFlag.AlignTop)
        p.setStyleSheet(f"color:{theme.MUTED};")
        grid.addWidget(p, 0, 1)
        grid.setColumnStretch(1, 1)
        rl.addLayout(grid)
        rl.addStretch(1)
        note = QLabel(
            "Calculations are not certified engineering results. Review data quality reports "
            "before using results in professional work."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{theme.MUTED};font-size:8.5pt;")
        rl.addWidget(note)
        row.addWidget(right, 2)

    def _card(self, title: str) -> QFrame:
        f = QFrame()
        f.setStyleSheet(
            f"QFrame{{background:{theme.PANEL_BG};border:1px solid {theme.BORDER};border-radius:8px;}}"
            "QLabel{border:none;background:transparent;}"
        )
        lay = QVBoxLayout(f)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        h = QLabel(title)
        h.setStyleSheet(f"color:{theme.NAVY};font-size:12pt;font-weight:700;")
        lay.addWidget(h)
        return f

    def set_recent(self, paths: list[str]) -> None:
        self.recent.clear()
        for p in paths:
            it = QListWidgetItem(icons.icon("folder"), f"{Path(p).stem}   —   {p}")
            it.setData(Qt.ItemDataRole.UserRole, p)
            self.recent.addItem(it)
        if not paths:
            it = QListWidgetItem("No recent projects")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(it)
