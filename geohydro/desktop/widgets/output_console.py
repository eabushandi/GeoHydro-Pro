"""Output console: processing messages, warnings, errors, validation results.

Engine modules log through Python ``logging`` (``geohydro.*`` loggers); a
handler forwards records to this widget through a Qt signal so logging from
worker threads is safe.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import theme

LEVEL_COLORS = {
    "DEBUG": theme.MUTED,
    "INFO": theme.TEXT,
    "SUCCESS": theme.SUCCESS,
    "WARNING": theme.WARNING,
    "ERROR": theme.ERROR,
    "CRITICAL": theme.ERROR,
}
LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "SUCCESS": 25, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class _Bridge(QObject):
    record = Signal(str, str, str)  # level, source, message


class ConsoleLogHandler(logging.Handler):
    def __init__(self, bridge: _Bridge):
        super().__init__(level=logging.INFO)
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            src = record.name.replace("geohydro.", "")
            self.bridge.record.emit(record.levelname, src, record.getMessage())
        except Exception:  # pragma: no cover - never let logging crash the app
            pass


class OutputConsole(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[tuple[str, str, str, str]] = []  # time, level, source, msg
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Show:"))
        self.level_box = QComboBox()
        self.level_box.addItems(["All messages", "Warnings and errors", "Errors only"])
        self.level_box.currentIndexChanged.connect(self._refilter)
        bar.addWidget(self.level_box)
        bar.addStretch(1)
        self.counts = QLabel("")
        self.counts.setStyleSheet(f"color:{theme.MUTED}")
        bar.addWidget(self.counts)
        b_save = QPushButton("Save log…")
        b_save.clicked.connect(self._save)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self.clear)
        bar.addWidget(b_save)
        bar.addWidget(b_clear)
        lay.addLayout(bar)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(20000)
        self.view.setStyleSheet("font-family: 'DejaVu Sans Mono', Consolas, monospace; font-size: 9pt;")
        lay.addWidget(self.view)

        self._bridge = _Bridge()
        self._bridge.record.connect(self.log)
        self.handler = ConsoleLogHandler(self._bridge)
        logging.getLogger("geohydro").addHandler(self.handler)
        logging.getLogger("geohydro").setLevel(logging.INFO)

    def detach(self) -> None:
        logging.getLogger("geohydro").removeHandler(self.handler)

    def _min_level(self) -> int:
        return {0: 0, 1: 30, 2: 40}[self.level_box.currentIndex()]

    def _fmt(self, t, level, src, msg) -> str:
        color = LEVEL_COLORS.get(level, theme.TEXT)
        lv = level if level != "CRITICAL" else "ERROR"
        return (
            f'<span style="color:{theme.MUTED}">{t}</span> '
            f'<span style="color:{color};font-weight:600">{lv:<7}</span> '
            f'<span style="color:{theme.NAVY_3}">[{html.escape(src)}]</span> '
            f'<span style="color:{color}">{html.escape(msg)}</span>'
        )

    def log(self, level: str, source: str, message: str) -> None:
        level = level.upper()
        t = datetime.now().strftime("%H:%M:%S")
        self.entries.append((t, level, source, message))
        if LEVEL_ORDER.get(level, 20) >= self._min_level():
            self.view.appendHtml(self._fmt(t, level, source, message))
        self._update_counts()

    def info(self, msg, source="app"):
        self.log("INFO", source, msg)

    def success(self, msg, source="app"):
        self.log("SUCCESS", source, msg)

    def warning(self, msg, source="app"):
        self.log("WARNING", source, msg)

    def error(self, msg, source="app"):
        self.log("ERROR", source, msg)

    def _update_counts(self):
        w = sum(1 for e in self.entries if e[1] == "WARNING")
        e = sum(1 for e in self.entries if e[1] in ("ERROR", "CRITICAL"))
        self.counts.setText(f"{len(self.entries)} messages · {w} warnings · {e} errors")

    def _refilter(self):
        self.view.clear()
        m = self._min_level()
        for t, lv, src, msg in self.entries:
            if LEVEL_ORDER.get(lv, 20) >= m:
                self.view.appendHtml(self._fmt(t, lv, src, msg))

    def clear(self):
        self.entries.clear()
        self.view.clear()
        self._update_counts()

    def plain_text(self) -> str:
        return "\n".join(f"{t} {lv:<7} [{src}] {msg}" for t, lv, src, msg in self.entries)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save console log", "geohydro_log.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.plain_text() + "\n")
