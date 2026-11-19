"""Background task helper so long operations do not freeze the interface."""

from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object, str)  # exception, formatted traceback


class Task(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            self.signals.failed.emit(exc, traceback.format_exc())
        else:
            self.signals.done.emit(result)


class TaskRunner(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self._active: set[Task] = set()

    def start(self, fn, on_done, on_failed, *args, **kwargs) -> Task:
        t = Task(fn, *args, **kwargs)
        self._active.add(t)

        def _finish(cb, *a):
            self._active.discard(t)
            cb(*a)

        t.signals.done.connect(lambda r: _finish(on_done, r))
        t.signals.failed.connect(lambda e, tb: _finish(on_failed, e, tb))
        self.pool.start(t)
        return t

    @property
    def busy(self) -> bool:
        return bool(self._active)
