"""Generate the v0.3.0 user-acceptance test dataset and its reference results.

    QT_QPA_PLATFORM=offscreen python tools/uat_reference.py

Writes
  samples/data/uat/uat_plane_utm39n.xyz      the test dataset (seed 20261120)
  docs/uat/expected_values.json              values the tester compares against
  docs/uat/screenshots/*.png                 screenshots of the same steps

Everything runs through the real MainWindow and its commands; nothing is mocked.
The dataset samples an exact plane, so most results have an analytic answer:

  z = 100 + 0.05 (x - 400000) + 0.02 (y - 2800000)     [m, UTM zone 39N, EPSG:32639]
  extent 400000-402000 E, 2800000-2801500 N
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

X0, Y0, X1, Y1 = 400000.0, 2800000.0, 402000.0, 2801500.0
A, B, C = 100.0, 0.05, 0.02


def plane(x, y):
    return C0 + B * (np.asarray(x) - X0) + C * (np.asarray(y) - Y0)


C0 = A


def make_dataset(path: Path) -> np.ndarray:
    """300 random interior points, the four corners and boundary points every 250 m."""
    rng = np.random.default_rng(20261120)
    xs = rng.uniform(X0 + 25, X1 - 25, 300)
    ys = rng.uniform(Y0 + 25, Y1 - 25, 300)
    bx, by = [], []
    for x in np.arange(X0, X1 + 1, 250.0):
        bx += [x, x]
        by += [Y0, Y1]
    for y in np.arange(Y0 + 250, Y1, 250.0):
        bx += [X0, X1]
        by += [y, y]
    x = np.concatenate([np.round(xs, 2), bx])
    y = np.concatenate([np.round(ys, 2), by])
    z = np.round(plane(x, y), 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="\n") as f:
        for a, b, c in zip(x, y, z):
            f.write(f"{a:.2f} {b:.2f} {c:.4f}\n")
    return np.column_stack([x, y, z])


def pump(app, n=8):
    for _ in range(n):
        app.processEvents()


def main():
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from geohydro.desktop.app import create_app

    data_path = ROOT / "samples" / "data" / "uat" / "uat_plane_utm39n.xyz"
    pts = make_dataset(data_path)
    out = ROOT / "docs" / "uat" / "screenshots"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    exp: dict = {"dataset": {"file": "samples/data/uat/uat_plane_utm39n.xyz", "points": len(pts),
                             "z_min": float(pts[:, 2].min()), "z_max": float(pts[:, 2].max()),
                             "surface": "z = 100 + 0.05 (x - 400000) + 0.02 (y - 2800000)",
                             "crs": "EPSG:32639"}}

    app = create_app(["uat"])
    from geohydro.desktop.dialogs.grid_dialog import GridDataDialog
    from geohydro.desktop.dialogs.import_wizard import ImportWizard
    from geohydro.desktop.main_window import MainWindow
    from geohydro.engine.gridding.grid import GridGeometry  # noqa: F401

    tmp = Path(tempfile.mkdtemp())
    settings = QSettings(str(tmp / "s.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings)
    win.resize(1600, 960)
    win.show()
    pump(app)

    def shot(widget, name):
        pump(app, 12)
        widget.grab().save(str(out / name))
        print("saved", name)

    # ---------------------------------------------------------------- import
    dlg = ImportWizard(win, [data_path], default_crs="EPSG:32639")
    dlg.resize(1500, 900)
    dlg.show()
    pump(app, 20)
    shot(dlg, "uat_01_import_wizard.png")
    dlg._accept(all_files=True)
    win.run_import_jobs(dlg.jobs)
    while win.tasks.busy:
        pump(app)
    pump(app, 20)
    ds = list(win.project.datasets.values())[-1]
    q = ds.qc_report
    exp["import"] = {"name": ds.name, "n_points": ds.n_points, "crs": ds.crs,
                     "imported_rows": q.get("imported_rows"), "excluded_rows": q.get("excluded_rows"),
                     "duplicate_groups": q.get("duplicate_groups")}
    doc = win.open_dataset(ds.id)
    doc.tabs.setCurrentIndex(1)
    shot(win, "uat_02_point_preview.png")

    # ---------------------------------------------------------------- gridding
    def grid(method, name, params=None, shot_name=None):
        g = GridDataDialog(win.project, win, ds.id, method, runner=None)
        g.resize(1120, 860)
        g.show()
        pump(app, 10)
        g.xmin.setValue(X0)
        g.xmax.setValue(X1)
        g.ymin.setValue(Y0)
        g.ymax.setValue(Y1)
        g.dx.setValue(20.0)
        g.dy.setValue(20.0)
        for k, v in (params or {}).items():
            g.p[k].setValue(v)
        g.out_name.setText(name)
        pump(app, 5)
        exp.setdefault("grid_dialog_defaults", {})[method] = {
            "nodes_label": g.nodes_label.text()}
        if shot_name:
            shot(g, shot_name)
        req = g.request()
        g.close()
        res = win.run_gridding(ds.id, req, name, synchronous=True)
        gg = res.grid
        xx, yy = gg.geometry.mesh()
        err = gg.z - plane(xx, yy)
        return gg, {"nx": gg.geometry.nx, "ny": gg.geometry.ny, "blank": int(gg.n_blank),
                    "max_abs_error_vs_plane": float(np.nanmax(np.abs(err))),
                    "rmse_vs_plane": float(np.sqrt(np.nanmean(err ** 2))),
                    "z_min": float(np.nanmin(gg.z)), "z_max": float(np.nanmax(gg.z))}

    tin, exp_tin = grid("tin", "UAT plane – TIN", shot_name="uat_03_grid_dialog_tin.png")
    exp["grid_tin"] = exp_tin
    _, exp["grid_natnb"] = grid("natural_neighbour", "UAT plane – natural neighbour")
    _, exp["grid_mincurv"] = grid("min_curvature", "UAT plane – minimum curvature")
    _, exp["grid_idw"] = grid("idw", "UAT plane – IDW")
    gdoc = win.open_grid(tin.id)
    shot(win, "uat_04_grid_document.png")

    # ---------------------------------------------------------------- grid files
    files = {}
    for fmt_ext in ("grd", "asc", "tif"):
        p = tmp / f"uat_tin.{fmt_ext}"
        win.export_grid(tin.id, str(p))
        n_before = len(win.project.grids)
        win.open_grid_file(str(p))
        back = list(win.project.grids.values())[-1] if len(win.project.grids) > n_before else None
        if back is not None:
            files[fmt_ext] = {"max_abs_diff": float(np.nanmax(np.abs(back.z - tin.z))),
                              "nx": back.geometry.nx, "ny": back.geometry.ny, "crs": back.crs}
    exp["grid_files"] = files

    # ---------------------------------------------------------------- grid math
    calc = win.grid_calculator({"expression": "A - 150", "A": tin.id, "z_units": "m",
                                "name": "UAT A minus 150"})
    cg = list(win.project.grids.values())[-1]
    exp["calculator_A_minus_150"] = {"z_min": float(np.nanmin(cg.z)), "z_max": float(np.nanmax(cg.z))}
    win.grid_filter({"grid_id": tin.id, "kind": "mean", "size": 3, "passes": 1, "min_valid": 1})
    fg = list(win.project.grids.values())[-1]
    inner = (slice(1, -1), slice(1, -1))
    exp["filter_mean_3"] = {"name": fg.name,
                            "max_abs_change_interior": float(np.nanmax(np.abs(fg.z[inner] - tin.z[inner]))),
                            "max_abs_change_edges": float(np.nanmax(np.abs(fg.z - tin.z)))}

    terr = {}
    for kind, vals in (("slope", {"units": "degrees"}), ("aspect", {}),
                       ("hillshade", {"azimuth": 315.0, "altitude": 45.0, "z_factor": 1.0}),
                       ("curvature", {"kind": "total"})):
        v = {"grid_id": tin.id, **vals}
        win.terrain(kind, v)
        tg = list(win.project.grids.values())[-1]
        z = tg.z[inner]
        terr[kind] = {"name": tg.name, "min": float(np.nanmin(z)), "max": float(np.nanmax(z)),
                      "blank_nodes": int(np.isnan(tg.z).sum())}
    exp["terrain_interior"] = terr
    g_ = math.hypot(B, C)
    exp["terrain_analytic"] = {
        "slope_deg": math.degrees(math.atan(g_)),
        "slope_percent": 100 * g_,
        "aspect_deg": (math.degrees(math.atan2(-B, -C)) + 360) % 360,
    }
    win.terrain("slope", {"grid_id": tin.id, "units": "degrees"})
    slope_g = list(win.project.grids.values())[-1]

    vol = {}
    for method in ("trapezoidal", "simpson", "simpson38"):
        r = win.grid_volume({"upper": tin.id, "lower": "__level__", "level": 0.0, "method": method},
                            show=False)
        vol[method] = r if isinstance(r, dict) else getattr(r, "__dict__", str(r))
    r150 = win.grid_volume({"upper": tin.id, "lower": "__level__", "level": 150.0,
                            "method": "trapezoidal"}, show=False)
    exp["volume_level_0"] = vol
    exp["volume_level_150"] = r150 if isinstance(r150, dict) else getattr(r150, "__dict__", str(r150))
    exp["volume_analytic"] = {"level_0_m3": 165.0 * 2000 * 1500, "level_150_net_m3": 15.0 * 2000 * 1500}

    prof = win.grid_profile({"grid_id": tin.id, "source": "__typed__",
                             "vertices": "400000 2800750; 402000 2800750", "spacing": 100.0},
                            show=True)
    pd_ = win._last_profile_dialog
    pd_.resize(1000, 650)
    pd_.show()
    shot(pd_, "uat_05_profile.png")
    pd_.close()
    p = prof
    try:
        exp["profile"] = {"length": float(p["distance"][-1]), "z_start": float(p["z"][0]),
                          "z_end": float(p["z"][-1]), "samples": int(len(p["z"]))}
    except Exception as exc:  # report the structure if attributes differ
        exp["profile"] = {"repr": repr(p)[:300], "error": str(exc)}

    # ---------------------------------------------------------------- maps
    m = win.new_map("contour", tin.id)
    mdoc = list(win.project.maps.values())[-1]
    win.open_map(mdoc.id)
    shot(win, "uat_06_contour_map.png")
    exp["contour_map"] = {"name": mdoc.name,
                          "analytic_spacing_m_per_10m": 10.0 / g_}
    png = tmp / "uat_contours.png"
    win.export_map(mdoc.id, str(png), dpi=300)
    from PIL import Image
    with Image.open(png) as im:
        exp["contour_map"]["png_300dpi_pixels"] = list(im.size)
        exp["contour_map"]["png_dpi"] = [round(v) for v in im.info.get("dpi", (0, 0))]
    win.new_map("colour_relief", slope_g.id)
    rdoc = list(win.project.maps.values())[-1]
    win.open_map(rdoc.id)
    shot(win, "uat_07_slope_relief_map.png")

    # ---------------------------------------------------------------- undo
    n = len(win.project.maps)
    win.undo()
    pump(app, 10)
    exp["undo"] = {"maps_before": n, "maps_after_undo": len(win.project.maps)}
    win.redo()
    pump(app, 10)
    exp["undo"]["maps_after_redo"] = len(win.project.maps)

    # ---------------------------------------------------------------- save / reopen
    proj = tmp / "uat.ghproj"
    win.project.name = "UAT plane"
    win._save_to(str(proj))
    counts = (len(win.project.datasets), len(win.project.grids), len(win.project.maps))
    win.project.dirty = False
    win.open_project(str(proj))
    pump(app, 20)
    exp["save_reopen"] = {"before": counts, "after": (len(win.project.datasets), len(win.project.grids),
                                                      len(win.project.maps))}

    # ---------------------------------------------------------------- GIS demo
    gis(app, win, exp, shot, tmp)

    (ROOT / "docs" / "uat" / "expected_values.json").write_text(json.dumps(exp, indent=2, default=str))
    win.project.dirty = False
    win.close()
    QApplication.processEvents()


def gis(app, win, exp, shot, tmp):
    """Vector, raster, density and map-furniture checks with the shipped GIS sample data."""
    gdir = ROOT / "samples" / "data" / "gis"
    exp["gis_files"] = sorted(p.name for p in gdir.iterdir() if p.is_file())
    win.new_project()
    win.project.dirty = False
    pump(app)
    res = {}
    for f in sorted(gdir.iterdir()):
        if f.suffix.lower() in (".geojson", ".shp", ".gpkg"):
            n = len(win.project.vectors)
            win.import_vector(str(f))
            if len(win.project.vectors) > n:
                v = list(win.project.vectors.values())[-1]
                types = sorted({g.geom_type for g in v.geometry if g is not None})
                res[f.name] = {"name": v.name, "features": int(len(v.geometry)), "geometry": types,
                               "fields": list(v.attributes.columns), "crs": v.crs}
    exp["vector_import"] = res
    for f in sorted(gdir.iterdir()):
        if f.suffix.lower() in (".tif", ".tiff"):
            n_g, n_i = len(win.project.grids), len(win.project.images)
            win.import_raster(str(f), {})
            if len(win.project.grids) > n_g:
                g = list(win.project.grids.values())[-1]
                exp.setdefault("raster_import", {})[f.name] = {
                    "as": "grid", "nx": g.geometry.nx, "ny": g.geometry.ny, "dx": g.geometry.dx,
                    "crs": g.crs, "z_min": float(np.nanmin(g.z)), "z_max": float(np.nanmax(g.z)),
                    "blank": int(g.n_blank)}
            elif len(win.project.images) > n_i:
                im = list(win.project.images.values())[-1]
                exp.setdefault("raster_import", {})[f.name] = {"as": "image", "crs": im.crs,
                                                                "name": im.name}
    errors = []
    win._error = lambda title, exc, *a, **k: errors.append(f"{title}: {exc}")
    V = {v.name: v for v in win.project.vectors.values()}
    proc = {}
    n = len(win.project.vectors)
    win.vector_process(V["flood_reports"].id, {"op": "buffer", "distance": 100.0})
    proc["buffer_geographic"] = {"new_layers": len(win.project.vectors) - n, "error": errors[-1] if errors else None}
    win.vector_process(V["flood_reports"].id, {"op": "reproject", "crs": "EPSG:32639"})
    fr = list(win.project.vectors.values())[-1]
    proc["reproject_flood_reports"] = {"name": fr.name, "crs": fr.crs, "features": int(len(fr.geometry))}
    win.vector_process(V["wadi_channels"].id, {"op": "buffer", "distance": 50.0})
    wb = list(win.project.vectors.values())[-1]
    proc["buffer_wadi_50m"] = {"name": wb.name, "features": int(len(wb.geometry)),
                               "geometry": sorted({g.geom_type for g in wb.geometry if g is not None})}
    win.vector_process(V["land_use"].id, {"op": "measures"})
    lu = list(win.project.vectors.values())[-1]
    new_cols = [c for c in lu.attributes.columns if c not in V["land_use"].attributes.columns]
    proc["land_use_measures"] = {"name": lu.name, "new_fields": new_cols,
                                 "total_area": float(lu.attributes[new_cols[0]].sum()) if new_cols else None}
    win.vector_process(V["land_use"].id, {"op": "dissolve"})
    dz = list(win.project.vectors.values())[-1]
    proc["land_use_dissolve_all"] = {"name": dz.name, "features": int(len(dz.geometry))}
    exp["vector_processing"] = proc
    nd = len(win.project.datasets)
    win.vector_to_points(V["boreholes"].id, {})
    if len(win.project.datasets) > nd:
        d = list(win.project.datasets.values())[-1]
        exp["boreholes_to_points"] = {"name": d.name, "n_points": d.n_points, "z_label": d.z_label,
                                      "excluded": d.qc_report.get("excluded_rows") if d.qc_report else None}
    ng = len(win.project.grids)
    win.point_density({"source": V["flood_reports"].id, "make_map": False})
    exp["density_geographic"] = {"new_grids": len(win.project.grids) - ng, "error": errors[-1] if errors else None}
    win.point_density({"source": fr.id, "method": "kde", "kernel": "quartic", "rule": "scott",
                       "n_long": 150, "per_km2": True, "make_map": True, "name": "UAT flood density"})
    dg = list(win.project.grids.values())[-1]
    cell_km2 = dg.geometry.dx * dg.geometry.dy / 1e6
    exp["density_kde"] = {"name": dg.name, "nx": dg.geometry.nx, "ny": dg.geometry.ny,
                          "z_units": dg.z_units, "max": float(np.nanmax(dg.z)),
                          "integral_points": float(np.nansum(dg.z) * cell_km2),
                          "bandwidth": dg.metadata.get("bandwidth") or dg.metadata.get("parameters")}
    win.point_density({"source": fr.id, "method": "count", "n_long": 50, "per_km2": False,
                       "make_map": False, "name": "UAT flood counts"})
    cg = list(win.project.grids.values())[-1]
    exp["density_count"] = {"total": float(np.nansum(cg.z)), "nx": cg.geometry.nx, "ny": cg.geometry.ny}
    dem = next(g for g in win.project.grids.values() if g.name.startswith("dem_50m"))
    win.grid_blank({"grid_id": dem.id, "vector_id": V["site_boundary"].id, "mode": "outside"})
    bg = list(win.project.grids.values())[-1]
    exp["blank_dem_outside_boundary"] = {"name": bg.name, "blank": int(bg.n_blank), "valid": int(bg.n_valid)}
    exp["errors_shown"] = errors
    win.project.dirty = False

    # GIS demo project: its three maps
    src = tmp / "gis_demo.ghproj"
    shutil.copy(ROOT / "samples" / "gis_demo_project.ghproj", src)
    win.open_project(str(src))
    pump(app, 20)
    exp["gis_demo"] = {"maps": [m.name for m in win.project.maps.values()],
                       "grids": [g.name for g in win.project.grids.values()],
                       "vectors": [v.name for v in win.project.vectors.values()],
                       "datasets": [d.name for d in win.project.datasets.values()],
                       "images": [i.name for i in win.project.images.values()]}
    for i, m in enumerate(win.project.maps.values()):
        win.open_map(m.id)
        shot(win, f"uat_{8 + i:02d}_gis_demo_map_{i + 1}.png")
    win.project.dirty = False


if __name__ == "__main__":
    main()
