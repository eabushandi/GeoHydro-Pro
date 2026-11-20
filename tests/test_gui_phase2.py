"""Phase 2 GUI tests: gridding, grid documents, grid files, map layouts and export.

They drive the real main window and dialogs (offscreen) and the real engine.
"""

import numpy as np
import pytest
from PySide6.QtCore import QSettings

from geohydro.desktop.dialogs.grid_dialog import GridDataDialog
from geohydro.desktop.dialogs.variogram_dialog import VariogramDialog
from geohydro.desktop.documents.grid_document import GridDocument
from geohydro.desktop.documents.map_document import MapView
from geohydro.desktop.main_window import MainWindow
from geohydro.engine.gridding.grid import GridGeometry
from geohydro.engine.gridding.gridder import GriddingRequest
from geohydro.engine.gridding.io import read_grid

from test_gui import import_files


@pytest.fixture
def terrain(win, qtbot, samples):
    import_files(win, qtbot, [samples / "terrain_survey_utm39n.csv"])
    return next(iter(win.project.datasets.values()))


def names(w, category):
    """Explorer child names without the size suffix shown after two spaces."""
    return [it.text(0).split("  (")[0] for it in w.explorer.child_items(category)]


def small_request(ds, method="idw", params=None, n=41):
    g = GridGeometry.from_points(ds.data["X"], ds.data["Y"], n_long=n)
    return GriddingRequest(method, params or {}, g)


@pytest.fixture
def gridded(win, terrain):
    res = win.run_gridding(terrain.id, small_request(terrain), "Terrain IDW", synchronous=True)
    assert res is not None
    return win.project.grids[res.grid.id]


def test_run_gridding_adds_grid_and_opens_document(win, terrain, gridded):
    g = gridded
    assert g.metadata["method"] == "idw" and g.metadata["source"]["dataset_id"] == terrain.id
    assert g.crs == terrain.crs and g.z_units == terrain.z_units
    assert win.project.dirty and win.project.history[-1].action == "grid.create"
    w = win.mdi.activeSubWindow().widget()
    assert isinstance(w, GridDocument) and w.grid_id == g.id
    assert w.stats.rowCount() > 8
    assert "Inverse Distance" in w.prov.toPlainText()
    assert "not certified" in w.prov.toPlainText()
    assert names(win, "grids") == ["Terrain IDW"]
    assert win.actions["grid_export"].isEnabled()
    # grid properties and status bar
    win._show_grid_properties(g.id)
    assert "Terrain IDW" in win.properties.header.text()
    assert "grid.name" in win.properties.editors
    win._phase2_property_edited("grid.name", "Terrain surface")
    assert g.name == "Terrain surface"


def test_gridding_failure_is_reported_not_raised(win, terrain):
    req = small_request(terrain, "ordinary_kriging", {})  # no variogram
    assert win.run_gridding(terrain.id, req, "bad", synchronous=True) is None
    assert not win.project.grids
    assert "Kriging needs a variogram" in win.console.plain_text()


def test_grid_data_dialog_request_and_cross_validation(win, qtbot, terrain):
    dlg = GridDataDialog(win.project, win, terrain.id, "idw", runner=None)
    qtbot.addWidget(dlg)
    assert dlg.dataset.id == terrain.id and dlg.method == "idw"
    g = dlg.geometry()
    assert g.n_nodes > 100
    req = dlg.request()
    assert req.params["power"] == 2.0 and req.params["search"]["max_points"] == 64
    dlg.cv_max.setValue(60)
    dlg.cross_validate()
    assert dlg.cv_result is not None and dlg.cv_result.n_validated == 60
    assert "RMSE" in dlg.cv_text.toPlainText()
    # Kriging without a variogram is refused with a message, not an exception
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("ordinary_kriging"))
    dlg._accept()
    assert "variogram" in dlg.error.text().lower() and dlg.result() == 0
    # Minimum curvature node limit is enforced in the dialog
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("min_curvature"))
    dlg.dx.setValue(1.0)
    dlg.dy.setValue(1.0)
    dlg._accept()
    assert "nodes" in dlg.error.text()


def test_variogram_dialog_fit_feeds_kriging(win, qtbot, terrain):
    dlg = VariogramDialog(terrain, win)
    qtbot.addWidget(dlg)
    assert dlg.ev is not None and len(dlg.ev.lags) > 3
    dlg.model.setCurrentIndex(dlg.model.findData("spherical"))
    dlg.auto_fit()
    m = dlg.current_model()
    assert m.model == "spherical" and m.sill > 0 and m.range > 0
    gd = GridDataDialog(win.project, win, terrain.id, "ordinary_kriging", runner=None)
    qtbot.addWidget(gd)
    gd.set_variogram(m)
    req = gd.request()
    req = GriddingRequest(req.method, req.params, small_request(terrain, n=25).geometry,
                          variance_grid=True)
    res = win.run_gridding(terrain.id, req, "Terrain OK", synchronous=True)
    assert res is not None and res.variance is not None
    names = {g.name for g in win.project.grids.values()}
    assert "Terrain OK" in names and len(names) == 2  # estimate plus variance grid


@pytest.mark.parametrize("kind", ["contour", "filled_contour", "colour_relief", "post"])
def test_new_map_of_each_type(win, gridded, kind):
    doc = win.new_map(kind)
    assert doc is not None and doc.id in win.project.maps
    view = win.mdi.activeSubWindow().widget()
    assert isinstance(view, MapView) and view.map_id == doc.id
    assert view.info is not None and view.info.warnings == []
    assert view.layers.count() == len(doc.layers)
    assert names(win, "maps") == [doc.name]


def test_new_map_without_source_reports_error(win):
    assert win.new_map("contour") is None
    assert "Create a grid first" in win.console.plain_text()


def test_map_view_editing(win, gridded):
    doc = win.new_map("colour_relief")
    view = win.mdi.activeSubWindow().widget()
    # map-level property through the properties panel route
    win._show_map_item_properties(doc.id)
    win._phase2_property_edited("map.title", "Site terrain")
    assert doc.title == "Site terrain" and view.info.artists["title"].get_text() == "Site terrain"
    win._phase2_property_edited("map.page", "A3")
    assert doc.page == "A3"
    # layer property: contour interval
    contour = next(lyr for lyr in doc.layers if lyr.type == "contour")
    win._show_map_item_properties(doc.id, contour.id)
    win._phase2_property_edited("layer.levels.interval", "2.5")
    assert contour.levels.mode == "interval" and contour.levels.interval == 2.5
    # invalid input is rejected and reported, the document is unchanged
    win._phase2_property_edited("layer.levels.interval", "-1")
    assert contour.levels.interval == 2.5
    assert "Invalid value" in win.console.plain_text()
    win._phase2_property_edited("layer.opacity", "abc")
    assert contour.opacity == 1.0
    # visibility toggle and layer order through the list
    view.select_layer(contour.id)
    top = view.layers.currentItem()
    from PySide6.QtCore import Qt
    top.setCheckState(Qt.CheckState.Unchecked)
    assert contour.visible is False
    before = [lyr.id for lyr in doc.layers]
    view._move(-1)
    assert [lyr.id for lyr in doc.layers] != before
    # add a post layer of the source points
    lyr = win.add_map_layer(doc.id, "post", next(iter(win.project.datasets)))
    assert doc.layers[-1] is lyr and view.current_layer_id() == lyr.id


def test_drag_scale_bar_stores_position(win, gridded):
    doc = win.new_map("contour")
    view = win.mdi.activeSubWindow().widget()
    view.canvas.draw()
    box = view.info.artists["scale_bar"]
    renderer = view.canvas.get_renderer()
    bb = box.get_window_extent(renderer)
    target = view.info.ax.transAxes.transform((0.6, 0.5))
    # A real mouse drag through matplotlib's event system: press on the box,
    # move, release (this is what the user does on the page view)
    from matplotlib.backend_bases import MouseButton, MouseEvent
    c = ((bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2)
    for name, (px, py) in (("button_press_event", c),
                           ("motion_notify_event", ((c[0] + target[0]) / 2, (c[1] + target[1]) / 2)),
                           ("motion_notify_event", target),
                           ("button_release_event", target)):
        MouseEvent(name, view.canvas, px, py, button=MouseButton.LEFT)._process()
    x, y = doc.scale_bar.xy
    assert abs(x - 0.6) < 0.03 and abs(y - 0.5) < 0.03
    assert win.project.dirty
    # The stored position is used on the next render and survives serialisation
    from geohydro.engine.mapping.model import MapDocument
    assert MapDocument.from_dict(doc.to_dict()).scale_bar.xy == doc.scale_bar.xy


def test_export_map_all_formats(win, gridded, tmp_path):
    doc = win.new_map("filled_contour")
    for ext, magic in (("png", b"\x89PNG"), ("jpg", b"\xff\xd8"), ("svg", b"<?xml"),
                       ("pdf", b"%PDF")):
        out = win.export_map(doc.id, str(tmp_path / f"map.{ext}"), dpi=72)
        assert out is not None and out.read_bytes().startswith(magic)
    assert win.export_map(doc.id, str(tmp_path / "map.png"), dpi=72) is None  # no overwrite
    assert "already exists" in win.console.plain_text()
    assert sum(o["kind"] == "map" for o in win.project.outputs) == 4


def test_export_and_reopen_grid_file(win, gridded, tmp_path):
    out = win.export_grid(gridded.id, str(tmp_path / "g.grd"), "surfer7_binary")
    assert out is not None
    back = read_grid(out)
    np.testing.assert_array_equal(back.z, gridded.z)
    g2 = win.open_grid_file(str(out))
    assert g2 is not None and g2.crs == win.project.default_crs
    assert "grid files carry no CRS" in g2.metadata["warnings"][0]
    assert len(win.project.grids) == 2
    assert win.open_grid_file(str(tmp_path / "missing.grd")) is None
    assert "Cannot read grid" in win.console.plain_text()


def test_remove_grid_used_by_map_then_validate(win, gridded):
    doc = win.new_map("contour")
    win.remove_grid(gridded.id)
    assert gridded.id not in win.project.grids
    assert win.validate_project() >= 1
    assert f"Map '{doc.name}': missing data source" in win.console.plain_text()
    view = win.documents[doc.id].widget()
    assert any("missing" in w for w in view.info.warnings)


def test_rename_and_remove_map(win, gridded):
    doc = win.new_map("contour")
    win.rename_map(doc.id, "Final contour map")
    assert doc.name == "Final contour map"
    assert win.documents[doc.id].windowTitle() == "Final contour map"
    win.remove_map(doc.id)
    assert doc.id not in win.project.maps and doc.id not in win.documents


def test_save_and_reopen_project_with_grids_and_maps(win, qtbot, gridded, tmp_path):
    doc = win.new_map("colour_relief")
    path = tmp_path / "p2.ghproj"
    assert win._save_to(str(path))
    assert win.validate_project() == 0
    w2 = MainWindow(QSettings(str(tmp_path / "s2.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(w2)
    assert w2.open_project(str(path))
    g2 = w2.project.grids[gridded.id]
    np.testing.assert_array_equal(g2.z, gridded.z)
    assert w2.project.maps[doc.id].to_dict() == doc.to_dict()
    assert names(w2, "maps") == [doc.name]
    w2._activate_item("map", doc.id)
    assert isinstance(w2.mdi.activeSubWindow().widget(), MapView)
    w2.project.dirty = False
    w2.close()
