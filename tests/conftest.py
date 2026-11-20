import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

SAMPLES = ROOT / "samples" / "data"


@pytest.fixture
def samples():
    return SAMPLES


@pytest.fixture
def write(tmp_path):
    """Write a text file into tmp_path and return its path."""

    def _w(name, text, encoding="utf-8"):
        p = tmp_path / name
        p.write_bytes(text.encode(encoding))
        return p

    return _w


# ---- shared GUI fixtures (pytest-qt, offscreen) ------------------------------
@pytest.fixture(scope="session")
def app():
    from geohydro.desktop.app import create_app
    return create_app(["test"])


@pytest.fixture
def win(app, qtbot, tmp_path):
    from PySide6.QtCore import QSettings

    from geohydro.desktop.main_window import MainWindow
    w = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(w)
    w.confirm = lambda *a, **k: True
    w.choose = lambda *a, **k: "Discard"
    w.show()
    yield w
    w.project.dirty = False
    w.close()
