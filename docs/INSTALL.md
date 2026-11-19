# Installation

## Supported platforms

| Platform | Status |
|---|---|
| Windows 10 / 11 (64-bit) | **Target platform. Not yet verified on real Windows hardware.** A GitHub Actions workflow (`.github/workflows/tests.yml`) runs the full suite on `windows-latest`, but it has not been run because no repository is connected yet. |
| Linux (Ubuntu 24.04, x86-64) | Verified: development environment, tests and offscreen screenshots. |
| macOS | Expected to work (all dependencies publish macOS wheels); not tested. |

Packaged installers (PyInstaller, Start-menu entry, desktop shortcut, code signing) are
planned for Phase 8. Phase 1 runs from source.

## Requirements

* Python 3.11, 3.12 or 3.13 (64-bit). Developed and tested on **Python 3.13.18**.
* No GDAL is required in Phase 1 (raster/vector formats arrive in later phases; on Windows
  they will be provided through wheels that bundle GDAL, such as rasterio/pyogrio).

### Dependency versions

| Package | Constraint | Verified version |
|---|---|---|
| PySide6 (Qt) | >=6.8, <6.11 | 6.8.1 (Qt 6.8 LTS) |
| numpy | >=1.26, <3 | 2.5.5 |
| pandas | >=2.1, <4 | 3.1.1 |
| scipy | >=1.11, <2 | 1.18.1 |
| openpyxl | >=3.1, <4 | 3.1.5 |
| pyproj | >=3.6, <4 | 3.8.0 (PROJ 9.8.1) |
| matplotlib | >=3.8, <4 | 3.11.2 |
| pytest / pytest-qt (dev) | >=8 / >=4.4 | 9.2.0 / 4.5.0 |

Only the verified versions have actually been tested together; the lower bounds are the
oldest versions whose APIs the code uses and should be confirmed in CI.

## Install from source

Windows (PowerShell):

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
geohydro-pro --sample
```

Linux / macOS:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
pip install -e .
geohydro-pro --sample
```

Linux needs the usual Qt system libraries (Ubuntu: `libegl1 libgl1 libxkbcommon0
libfontconfig1 libdbus-1-3`).

Other ways to start: `python -m geohydro.desktop [project.ghproj]` or `python run_desktop.py`.

## Running the tests

```bash
python -m pytest            # all 88 tests
python -m pytest tests/test_gui.py   # GUI tests only (offscreen)
```

GUI tests set `QT_QPA_PLATFORM=offscreen` automatically, so no display is needed.

Screenshots of the real application can be regenerated with
`python tools/make_screenshots.py` (writes to `docs/screenshots/`).

## Hardware (provisional)

These are provisional recommendations, **not measured requirements**; they will be
replaced by benchmark results in Phase 8.

* Minimum: 64-bit dual-core CPU, 4 GB RAM, 1366×768 display, 500 MB disk.
* Recommended: quad-core CPU, 16 GB RAM, 1920×1080 display, GPU with OpenGL 3.3+
  (needed for the planned 3D module).

## Licensing note for distribution

PySide6/Qt is used under the LGPLv3. Commercial distribution is permitted provided the
LGPL obligations are met (dynamic linking, allowing library replacement, licence notices).
This must be reviewed when the Windows installer is built (Phase 8).
