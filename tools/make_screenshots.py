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
    shot(win, "10_ribbon_planned_map.png")
    win.ribbon.setCurrentIndex(0)

    proj_path = Path(tmp) / "demo.ghproj"
    win.project.name = "Demo Project"
    win._save_to(str(proj_path))
    pump(app)
    win.validate_project()
    shot(win, "11_saved_and_validated.png")
    win.project.dirty = False
    win.close()
    QApplication.processEvents()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
