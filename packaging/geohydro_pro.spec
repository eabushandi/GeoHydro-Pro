# PyInstaller spec for the standalone GeoHydro Pro build (one-folder mode).
#
#   pyinstaller packaging/geohydro_pro.spec --noconfirm
#
# Output: dist/GeoHydroPro/ containing GeoHydroPro(.exe) and an _internal folder
# with Python, Qt, GDAL, PROJ and the sample data. One-folder mode starts faster
# than one-file mode and lets the installer and antivirus software see real files.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))
from geohydro import __version__  # noqa: E402

datas = [
    (str(ROOT / "samples" / "data"), "samples/data"),
    (str(ROOT / "samples" / "sample_project.ghproj"), "samples"),
    (str(ROOT / "samples" / "README.md"), "samples"),
    (str(ROOT / "docs"), "docs"),
]
# PROJ database (pyproj), GDAL/PROJ data shipped inside rasterio and pyogrio wheels
for pkg in ("pyproj", "rasterio", "pyogrio", "shapely", "matplotlib"):
    datas += collect_data_files(pkg)
binaries = []
for pkg in ("rasterio", "pyogrio", "shapely", "pyproj"):
    binaries += collect_dynamic_libs(pkg)
hiddenimports = (collect_submodules("rasterio") + collect_submodules("pyogrio")
                 + collect_submodules("geohydro")
                 # export backends are imported lazily by savefig()
                 + ["matplotlib.backends.backend_pdf", "matplotlib.backends.backend_svg",
                    "matplotlib.backends.backend_agg", "matplotlib.backends.backend_ps"])

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "pykrige", "IPython", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = ROOT / "packaging" / "geohydro.ico"
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="GeoHydroPro",
    console=False,               # windowed application
    icon=str(icon) if icon.exists() else None,
    version=str(ROOT / "packaging" / "version_info.txt") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GeoHydroPro")
