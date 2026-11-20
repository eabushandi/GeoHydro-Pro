"""Drive the real desktop application offscreen and save interface screenshots.

    QT_QPA_PLATFORM=offscreen python tools/make_screenshots.py [out_dir]

Uses the actual MainWindow, ImportWizard and sample data - nothing is mocked.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from geohydro.desktop.app import create_app  # noqa: E402


def pump(app, n=8):
    for _ in range(n):
        app.processEvents()


def main(out_dir: str | None = None):
    out = Path(out_dir or ROOT / "docs" / "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    app = create_app(["screens"])
    from geohydro.desktop.dialogs.import_wizard import ImportWizard
    from geohydro.desktop.main_window import MainWindow

    tmp = tempfile.mkdtemp()
    settings = QSettings(str(Path(tmp) / "s.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings)
    win.resize(1600, 960)
    win.show()
    pump(app)

    def shot(widget, name):
        pump(app)
        widget.grab().save(str(out / name))
        print("saved", out / name)

    shot(win, "01_start_page.png")

    data = ROOT / "samples" / "data"
    dlg = ImportWizard(win, [data / "field_readings_with_errors.csv"], default_crs="EPSG:32639")
    dlg.resize(1500, 900)
    dlg.show()
    pump(app, 20)
    shot(dlg, "02_import_wizard_qc.png")
    dlg.tabs.setCurrentIndex(2)
    shot(dlg, "03_import_wizard_points.png")
    dlg.tabs.setCurrentIndex(3)
    shot(dlg, "04_import_wizard_qc_summary.png")
    dlg.close()

    dlg = ImportWizard(win, [data / "groundwater_wells.xlsx", data / "bathymetry_nearshore.xyz"],
                       default_crs="EPSG:32639")
    dlg.resize(1500, 900)
    dlg.show()
    pump(app, 20)
    shot(dlg, "05_import_wizard_xlsx.png")
    dlg._accept(all_files=True)
    jobs = dlg.jobs
    win.run_import_jobs(jobs)
    while win.tasks.busy:
        pump(app)
    pump(app, 20)
    doc = win.open_dataset(list(win.project.datasets)[-1])
    doc.tabs.setCurrentIndex(1)
    pump(app, 20)
    shot(win, "06_bathymetry_preview.png")
    doc.tabs.setCurrentIndex(2)
    shot(win, "07_statistics.png")
    doc = win.open_dataset(list(win.project.datasets)[0])
    doc.tabs.setCurrentIndex(0)
    shot(win, "08_wells_table.png")
    doc.tabs.setCurrentIndex(3)
    shot(win, "09_quality_report.png")
    win.ribbon.setCurrentIndex(3)
    shot(win, "10_ribbon_mapping.png")
    win.ribbon.setCurrentIndex(0)

    proj_path = Path(tmp) / "demo.ghproj"
    win.project.name = "Demo Project"
    win._save_to(str(proj_path))
    pump(app)
    win.validate_project()
    shot(win, "11_saved_and_validated.png")
    win.project.dirty = False
    phase2(app, win, out, shot, tmp)
    win.project.dirty = False
    win.close()
    QApplication.processEvents()


def phase2(app, win, out, shot, tmp):
    """Gridding, variogram, grid document and map layout, using the sample project."""
    import shutil

    from geohydro.desktop.dialogs.grid_dialog import GridDataDialog
    from geohydro.desktop.dialogs.variogram_dialog import VariogramDialog

    src = Path(tmp) / "sample_project.ghproj"
    shutil.copy(ROOT / "samples" / "sample_project.ghproj", src)
    win.open_project(str(src))
    pump(app, 20)
    wells = win.project.dataset_by_name("Monitoring wells")
    terrain = win.project.dataset_by_name("Terrain survey")

    dlg = GridDataDialog(win.project, win, terrain.id, "idw", runner=None)
    dlg.resize(1120, 860)
    dlg.show()
    pump(app, 10)
    dlg.cv_max.setValue(300)
    dlg.cross_validate()
    pump(app, 10)
    shot(dlg, "12_grid_data_dialog.png")
    dlg.close()

    vg = VariogramDialog(wells, win)
    vg.resize(1100, 700)
    vg.model.setCurrentIndex(vg.model.findData("spherical"))
    vg.auto_fit()
    vg.show()
    pump(app, 10)
    shot(vg, "13_variogram.png")
    vg.close()

    head = next(g for g in win.project.grids.values() if "kriging" in g.name)
    doc = win.open_grid(head.id)
    win.explorer.select_item("grids", head.id)
    win._show_grid_properties(head.id)
    pump(app, 20)
    shot(win, "14_grid_document.png")
    doc.tabs.setCurrentIndex(2)
    shot(win, "15_grid_provenance.png")

    for name, file in (("Terrain relief map", "16_map_layout_relief.png"),
                       ("Groundwater head map", "17_map_layout_head.png")):
        m = next(m for m in win.project.maps.values() if m.name == name)
        view = win.open_map(m.id)
        pump(app, 10)
        if file.startswith("17"):
            view.select_layer(m.layers[1].id)
        pump(app, 20)
        shot(win, file)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
