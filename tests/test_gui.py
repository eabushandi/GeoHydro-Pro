"""GUI tests (pytest-qt, offscreen). They drive the real widgets and engine."""

import pandas as pd
import pytest
from PySide6.QtCore import QSettings

from geohydro.desktop.app import create_app
from geohydro.desktop.dialogs.import_wizard import ImportWizard
from geohydro.desktop.documents.dataset_document import DatasetDocument
from geohydro.desktop.main_window import MainWindow
from geohydro.engine.capabilities import CAPABILITIES
from geohydro.project import load_project, save_project

EXPECTED_MENUS = ["File", "Edit", "View", "Project", "Data", "Grid", "Mapping", "Analysis", "Hydrology",
                  "Coastal Engineering", "Flood Analysis", "Groundwater", "3D Visualization", "Reports",
                  "Tools", "Settings", "Help"]


@pytest.fixture(scope="session")
def app():
    return create_app(["test"])


@pytest.fixture
def win(app, qtbot, tmp_path):
    w = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(w)
    w.confirm = lambda *a, **k: True
    w.choose = lambda *a, **k: "Discard"
    w.show()
    yield w
    w.project.dirty = False
    w.close()


def import_files(win, qtbot, paths, crs="EPSG:32639", configure=None):
    dlg = ImportWizard(win, paths, default_crs=crs)
    qtbot.addWidget(dlg)
    if configure:
        configure(dlg)
    dlg._accept(all_files=True)
    assert dlg.jobs, "wizard produced no jobs"
    n = len(win.project.datasets)
    win.run_import_jobs(dlg.jobs)
    qtbot.waitUntil(lambda: len(win.project.datasets) == n + len(dlg.jobs), timeout=10000)
    return dlg


def test_main_window_structure(win):
    titles = [a.text().replace("&", "") for a in win.mb.actions()]
    assert titles == EXPECTED_MENUS
    for dock in (win.dock_explorer, win.dock_properties, win.dock_console):
        assert dock.isVisible()
    assert [win.ribbon.tabText(i).replace("&&", "&") for i in range(win.ribbon.count())][:3] == ["Home", "Data", "Grid"]
    assert "GeoHydro Pro" in win.windowTitle()
    status_texts = [w.text() for w in (win.status.coords, win.status.crs, win.status.scale, win.status.grid,
                                       win.status.elev, win.status.status)]
    assert status_texts[0].startswith("X:") and status_texts[1].startswith("CRS:")


def test_planned_features_are_disabled_and_labelled(win):
    for key, cap in CAPABILITIES.items():
        act = win.actions.get(key)
        if act is None:
            continue
        if cap.implemented:
            continue
        assert not act.isEnabled(), key
        assert "planned" in act.text().lower(), key
        assert f"Phase {cap.phase}" in act.toolTip()
    planned_buttons = [b for b in win.ribbon.all_buttons() if b.defaultAction().property("planned")]
    assert planned_buttons and all(not b.isEnabled() for b in planned_buttons)
    for key in ("new", "open", "save", "import", "crs_tool", "validate"):
        assert win.actions[key].isEnabled()


def test_explorer_categories(win):
    labels = [win.explorer.category_items[k].text(0) for k in win.explorer.category_items]
    assert labels[0].startswith("Point Datasets")
    assert any("Grid Files" in t and "planned" in t for t in labels)
    assert any("Reports" in t for t in labels)


def test_import_wizard_preview_and_qc(app, qtbot, samples):
    dlg = ImportWizard(None, [samples / "field_readings_with_errors.csv"], default_crs="EPSG:32639")
    qtbot.addWidget(dlg)
    st = dlg.current
    assert st.table is not None and st.table.options.delimiter == ";"
    assert (dlg.xcol.currentText(), dlg.ycol.currentText(), dlg.zcol.currentText()) == ("East", "North", "Level")
    assert "35" in dlg.banner.text() and "5" in dlg.banner.text()
    assert dlg.model.rowCount() == 40 and dlg.model.columnCount() == 4
    assert dlg.b_import_one.isEnabled()
    # invalid CRS blocks import
    dlg.crs.setCurrentText("EPSG:123456789")
    assert st.crs_error and not dlg.b_import_one.isEnabled()
    dlg.crs.setCurrentText("EPSG:32639")
    assert st.crs_error is None
    # change duplicate policy -> QC recomputed with the engine
    dlg.dup.setCurrentIndex(dlg.dup.findData("keep_first"))
    dlg._recompute_qc()
    assert st.qc.report.imported_rows == 33
    # switching off exclusion keeps all rows
    dlg.excl_invalid.setChecked(False)
    dlg._recompute_qc()
    assert st.qc.report.excluded_rows == 2  # only the two removed duplicates


def test_import_wizard_read_option_override(app, qtbot, samples):
    dlg = ImportWizard(None, [samples / "contaminant_survey.txt"])
    qtbot.addWidget(dlg)
    assert dlg.current.table.options.delimiter == "whitespace"
    dlg.header.setCurrentIndex(dlg.header.findData("no"))
    dlg._reread()
    assert dlg.current.table.columns[0] == "Column_1"
    assert dlg.current.qc.report.excluded_rows == 1  # header row is now non-numeric data


def test_import_wizard_unreadable_file(app, qtbot, tmp_path):
    bad = tmp_path / "empty.csv"
    bad.write_text("# nothing\n")
    dlg = ImportWizard(None, [bad])
    qtbot.addWidget(dlg)
    assert dlg.current.error and not dlg.b_import_all.isEnabled()
    assert "Cannot read" in dlg.banner.text()


def test_import_multiple_files_into_project(win, qtbot, samples):
    import_files(win, qtbot, [samples / "groundwater_wells.xlsx", samples / "bathymetry_nearshore.xyz"])
    names = sorted(d.name for d in win.project.datasets.values())
    assert names == ["bathymetry_nearshore", "groundwater_wells"]
    assert win.project.dirty and win.isWindowModified()
    assert len(win.explorer.dataset_items()) == 2
    doc = win.mdi.activeSubWindow().widget()
    assert isinstance(doc, DatasetDocument)
    assert [doc.tabs.tabText(i) for i in range(doc.tabs.count())] == [
        "Table", "Point Preview", "Statistics", "Quality Report"]
    assert doc.model.rowCount() == 2000
    assert "Standard deviation" in doc.stats.toPlainText()
    assert "Source rows: 2000" in doc.qc.toPlainText()
    assert win.status.crs.text() == "CRS: EPSG:32639"


def test_preview_cursor_updates_status_bar(win, qtbot, samples):
    import_files(win, qtbot, [samples / "contaminant_survey.txt"])
    doc = win.mdi.activeSubWindow().widget()
    ds = next(iter(win.project.datasets.values()))
    x, y, z = ds.data[["X", "Y", "Z"]].iloc[0]
    doc.preview.cursorMoved.emit(x, y, z)
    assert win.status.coords.text().startswith("X: ")
    assert f"{z:,.3f}" in win.status.elev.text()


def test_properties_edit_rename_and_crs(win, qtbot, samples):
    import_files(win, qtbot, [samples / "contaminant_survey.txt"])
    did = next(iter(win.project.datasets))
    win.explorer.select_dataset(did)
    win._property_edited("ds.name", "Benzene plume")
    assert win.project.datasets[did].name == "Benzene plume"
    assert win.explorer.dataset_items()[0].text(0).startswith("Benzene plume")
    win._property_edited("ds.crs", "EPSG:4326")
    assert win.project.datasets[did].crs == "EPSG:4326"
    win._property_edited("ds.crs", "definitely not a crs")
    assert win.project.datasets[did].crs == "EPSG:4326"  # unchanged
    assert "Invalid value" in win.console.plain_text()
    win._property_edited("project.name", "Site A")
    assert win.project.name == "Site A" and "Site A" in win.windowTitle()
    actions = [h.action for h in win.project.history]
    assert "dataset.rename" in actions and "dataset.assign_crs" in actions


def test_save_open_roundtrip_through_ui(win, qtbot, samples, tmp_path, app):
    import_files(win, qtbot, [samples / "terrain_survey_utm39n.csv"])
    path = tmp_path / "ui.ghproj"
    assert win._save_to(str(path))
    assert not win.project.dirty and path.exists()
    assert win.validate_project() == 0
    assert "checksum ok" in win.console.plain_text()

    w2 = MainWindow(QSettings(str(tmp_path / "s2.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(w2)
    assert w2.open_project(str(path))
    assert [d.name for d in w2.project.datasets.values()] == ["terrain_survey_utm39n"]
    pd.testing.assert_frame_equal(next(iter(w2.project.datasets.values())).data,
                                  next(iter(win.project.datasets.values())).data)
    w2.project.dirty = False
    w2.close()


def test_conflict_is_not_silently_overwritten(win, qtbot, samples, tmp_path):
    path = tmp_path / "c.ghproj"
    import_files(win, qtbot, [samples / "contaminant_survey.txt"])
    win._save_to(str(path))
    other = load_project(path)
    other.name = "Newer"
    save_project(other)
    win.project.name = "Older"
    win.choose = lambda *a, **k: None  # user cancels
    assert not win._save_to(str(path))
    assert load_project(path).name == "Newer"
    win.choose = lambda *a, **k: "Overwrite newer file"
    assert win._save_to(str(path))
    assert load_project(path).name == "Older"


def test_unsaved_changes_prompt(win, qtbot, samples):
    import_files(win, qtbot, [samples / "contaminant_survey.txt"])
    asked = []
    win.choose = lambda *a, **k: (asked.append(a), None)[1]  # cancel
    win.new_project()
    assert asked and len(win.project.datasets) == 1  # cancelled: project kept
    win.choose = lambda *a, **k: "Discard"
    win.new_project()
    assert len(win.project.datasets) == 0


def test_export_csv_and_source_protection(win, qtbot, samples, tmp_path):
    import_files(win, qtbot, [samples / "contaminant_survey.txt"])
    did = next(iter(win.project.datasets))
    out = win.export_dataset_csv(did, str(tmp_path / "out.csv"))
    df = pd.read_csv(out)
    assert len(df) == 80 and list(df.columns[:3]) == ["X", "Y", "Z"]
    assert win.project.outputs[-1]["path"] == str(tmp_path / "out.csv")
    assert win.export_dataset_csv(did, str(samples / "contaminant_survey.txt")) is None


def test_remove_dataset(win, qtbot, samples):
    import_files(win, qtbot, [samples / "contaminant_survey.txt"])
    did = next(iter(win.project.datasets))
    win.remove_dataset(did)
    assert not win.project.datasets and (samples / "contaminant_survey.txt").exists()


def test_sample_project_opens_as_copy(win):
    win.open_sample_project()
    assert len(win.project.datasets) == 2
    assert win.project.path is None  # Save goes to Save As: the shipped sample is never overwritten


def test_console_filter(win):
    win.console.clear()
    win.console.info("a")
    win.console.warning("b")
    win.console.error("c")
    win.console.level_box.setCurrentIndex(2)
    assert win.console.view.toPlainText().count("\n") == 0 and "c" in win.console.view.toPlainText()
    assert "3 messages" in win.console.counts.text()
