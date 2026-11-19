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
