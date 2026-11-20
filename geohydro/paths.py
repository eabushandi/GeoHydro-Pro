"""Locations of bundled resources, for both a source checkout and a frozen build.

In a source checkout the samples and docs live next to the ``geohydro`` package.
In the standalone Windows build (PyInstaller, one-folder mode) they are copied
into the bundle directory, which PyInstaller exposes as ``sys._MEIPASS``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


ROOT = resource_root()
SAMPLES_DIR = ROOT / "samples"
SAMPLE_DATA_DIR = SAMPLES_DIR / "data"
SAMPLE_PROJECT = SAMPLES_DIR / "sample_project.ghproj"
DOCS_DIR = ROOT / "docs"
GIS_SAMPLE_PROJECT = SAMPLES_DIR / "gis_demo_project.ghproj"
