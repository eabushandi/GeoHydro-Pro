"""Installation self-test.

    geohydro-pro --selftest [--report FILE]
    GeoHydroPro.exe --selftest --report "%TEMP%\\geohydro_selftest.txt"

Checks, without user interaction, that a source install or the standalone
Windows build is complete: every scientific library imports, PROJ and GDAL
find their data files, the sample project opens and verifies, a grid can be
computed and mapped, raster and vector files can be written and read back,
and the main window can be created. The exit code is 0 when every check
passes. The report is written to ``--report`` (and to stdout when there is
one), because the windowed Windows executable has no console.
"""

from __future__ import annotations

import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path


def _checks(tmp: Path):
    """Yield (name, callable) pairs. Each callable returns a short detail string."""

    def libraries():
        import matplotlib
        import numpy
        import pandas
        import pyproj
        import PySide6
        import scipy
        out = [f"numpy {numpy.__version__}", f"pandas {pandas.__version__}",
               f"scipy {scipy.__version__}", f"matplotlib {matplotlib.__version__}",
               f"PySide6 {PySide6.__version__}", f"pyproj {pyproj.__version__} "
               f"(PROJ {pyproj.proj_version_str})"]
        try:
            import pyogrio
            import rasterio
            import shapely
            out += [f"rasterio {rasterio.__version__} (GDAL {rasterio.__gdal_version__})",
                    f"pyogrio {pyogrio.__version__}", f"shapely {shapely.__version__}"]
        except ImportError as exc:  # GIS stack is required from Phase 3
            raise RuntimeError(f"GIS libraries missing: {exc}") from exc
        return ", ".join(out)

    def proj_database():
        from pyproj import CRS, Transformer
        crs = CRS.from_epsg(32639)
        t = Transformer.from_crs(4326, 32639, always_xy=True)
        x, y = t.transform(51.0, 26.0)
        if abs(x - 500000.0) > 1e-3:
            raise RuntimeError(f"unexpected UTM easting {x}")
        return f"{crs.name}; 51°E 26°N -> E {x:.3f} N {y:.3f}"

    def sample_project():
        from geohydro.paths import SAMPLE_PROJECT
        from geohydro.project import load_project
        p = load_project(SAMPLE_PROJECT)
        return (f"{SAMPLE_PROJECT.name}: {len(p.datasets)} datasets, {len(p.grids)} grids, "
                f"{len(p.maps)} maps, checksums ok")

    def gridding_and_map():
        import numpy as np

        from geohydro.engine.gridding.grid import GridGeometry
        from geohydro.engine.gridding.gridder import GriddingRequest, grid_data
        from geohydro.engine.mapping.model import ContourLayer, FilledContourLayer, MapDocument
        from geohydro.engine.mapping.render import export_map
        rng = np.random.default_rng(1)
        x, y = rng.uniform(0, 1000, 200), rng.uniform(0, 1000, 200)
        z = np.sin(x / 200) + np.cos(y / 300)
        g = grid_data(x, y, z, GriddingRequest("idw", {}, GridGeometry(0, 1000, 0, 1000, 51, 51)),
                      crs="EPSG:32639").grid
        doc = MapDocument(crs="EPSG:32639", layers=[FilledContourLayer(grid_id=g.id),
                                                    ContourLayer(grid_id=g.id)])
        out = []
        for ext in ("png", "pdf", "svg"):
            path, _ = export_map(doc, {g.id: g}.get, tmp / f"selftest.{ext}", dpi=100)
            out.append(f"{ext} {path.stat().st_size // 1024} KB")
        return "IDW 51x51; export " + ", ".join(out)

    def raster_io():
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        path = tmp / "selftest.tif"
        data = np.arange(12, dtype="float32").reshape(3, 4)
        with rasterio.open(path, "w", driver="GTiff", width=4, height=3, count=1,
                           dtype="float32", crs="EPSG:32639",
                           transform=from_origin(500000, 2900000, 10, 10)) as dst:
            dst.write(data, 1)
        with rasterio.open(path) as src:
            back = src.read(1)
            epsg = src.crs.to_epsg()
        if not np.array_equal(back, data) or epsg != 32639:
            raise RuntimeError("GeoTIFF round trip failed")
        return "GeoTIFF write/read, CRS EPSG:32639"

    def vector_io():
        import numpy as np
        import pyogrio
        import shapely
        geoms = shapely.points(np.array([[0.0, 0.0], [1.0, 1.0]]))
        path = tmp / "selftest.gpkg"
        pyogrio.raw.write(path, geometry=shapely.to_wkb(geoms), field_data=[np.array([1, 2])],
                          fields=["id"], geometry_type="Point", crs="EPSG:4326",
                          driver="GPKG")
        meta, _, geom, fields = pyogrio.raw.read(path)
        if len(geom) != 2 or list(fields[0]) != [1, 2]:
            raise RuntimeError("GeoPackage round trip failed")
        drivers = pyogrio.list_drivers()
        need = ("ESRI Shapefile", "GeoJSON", "GPKG", "KML")
        missing = [d for d in need if d not in drivers]
        if missing:
            raise RuntimeError(f"GDAL vector drivers missing: {missing}")
        return "GeoPackage write/read; drivers " + ", ".join(need)

    def main_window():
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QSettings

        from geohydro.desktop.app import create_app
        from geohydro.desktop.main_window import MainWindow
        app = create_app(["selftest"])
        win = MainWindow(QSettings(str(tmp / "selftest.ini"), QSettings.Format.IniFormat))
        win.open_sample_project()
        n = len(win.project.maps)
        win.project.dirty = False
        win.close()
        app.processEvents()
        return f"main window created, sample project opened ({n} maps), platform {app.platformName()}"

    return [("Scientific libraries", libraries), ("PROJ database", proj_database),
            ("Sample project", sample_project), ("Gridding and map export", gridding_and_map),
            ("Raster I/O (GDAL)", raster_io), ("Vector I/O (GDAL)", vector_io),
            ("Main window", main_window)]


def run(report: str | None = None) -> int:
    from geohydro import APP_NAME, __version__
    from geohydro.paths import ROOT, is_frozen
    lines = [f"{APP_NAME} {__version__} self-test",
             f"Python {sys.version.split()[0]} on {platform.platform()}",
             f"Frozen build: {is_frozen()}; resources: {ROOT}", ""]
    failures = 0
    with tempfile.TemporaryDirectory() as td:
        for name, fn in _checks(Path(td)):
            t0 = time.perf_counter()
            try:
                detail = fn()
                lines.append(f"PASS  {name}: {detail} ({time.perf_counter() - t0:.2f} s)")
            except Exception as exc:  # report every failure, keep going
                failures += 1
                lines.append(f"FAIL  {name}: {exc}")
                lines.extend("      " + ln for ln in traceback.format_exc().splitlines())
    lines += ["", "RESULT: " + ("all checks passed" if not failures else f"{failures} check(s) failed")]
    text = "\n".join(lines) + "\n"
    if report:
        Path(report).write_text(text, encoding="utf-8")
    if sys.stdout is not None:
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
    return 1 if failures else 0
