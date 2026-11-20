"""Phase 3 GUI tests: vector / raster import, GIS documents, grid math, terrain,
volumes, profiles, point density, GIS map layers and undo / redo.

They drive the real main window (offscreen) and the real engine with the
bundled GIS sample data (samples/data/gis).
"""

import numpy as np
import pytest

from geohydro.desktop.dialogs.gis_dialogs import Field, ParamDialog, ProfileDialog
from geohydro.desktop.documents.gis_documents import ImageDocument, VectorDocument
from geohydro.desktop.documents.map_document import MapView, apply_edit, layer_props, map_props
from geohydro.engine.capabilities import CAPABILITIES
from geohydro.engine.errors import MapError
from geohydro.engine.mapping.model import ImageLayer, VectorLayer
from geohydro.paths import GIS_SAMPLE_PROJECT
from geohydro.project import load_project, save_project


@pytest.fixture
def gis(samples):
    return samples / "gis"


@pytest.fixture
def dem(win, gis):
    g = win.import_raster(gis / "dem_50m_utm39n.tif", values={"kind": "grid"})
    assert g is not None
    return g


def test_phase3_capabilities_enabled(win):
    for key in ("data.import.vector", "data.import.raster", "grid.math", "map.vector",
                "map.density", "terrain.slope", "terrain.aspect", "terrain.hillshade",
                "terrain.curvature", "terrain.profile", "terrain.volume", "edit.undo"):
        assert CAPABILITIES[key].implemented
        assert "planned" not in win.actions[key].text().lower()
    assert win.actions["data.import.vector"].isEnabled()
    assert not win.actions["grid.math"].isEnabled()  # no grid yet
    assert not CAPABILITIES["3d.surface"].implemented  # still planned, now Phase 4
    assert not win.actions["3d.surface"].isEnabled()


def test_import_vector_all_sample_formats(win, gis):
    for f in ("site_boundary.geojson", "wadi_channels.shp", "land_use.gpkg", "boreholes.gpkg"):
        ds = win.import_vector(gis / f)
        assert ds is not None and ds.id in win.project.vectors
    assert len(win.project.vectors) == 4
    assert win.project.history[-1].action == "vector.import"
    w = win.mdi.activeSubWindow().widget()
    assert isinstance(w, VectorDocument) and w.model.rowCount() == 40
    assert "40" in w.info.toPlainText()
    kids = [it.text(0) for it in win.explorer.child_items("vectors")]
    assert any(k.startswith("boreholes") and "point" in k for k in kids)
    assert win.actions["vector_to_points"].isEnabled()


def test_import_vector_error_is_reported(win, tmp_path):
    bad = tmp_path / "bad.geojson"
    bad.write_text("not json")
    assert win.import_vector(bad) is None
    assert not win.project.vectors
    assert "cannot be read" in win.console.plain_text()


def test_import_raster_as_grid_and_image(win, gis, dem):
    assert dem.id in win.project.grids and dem.crs == "EPSG:32639"
    assert dem.geometry.nx > 50 and np.isfinite(dem.z).any()
    img = win.import_raster(gis / "basemap_rgb_wgs84.tif", values={"kind": "image"})
    assert img is not None and img.id in win.project.images
    assert isinstance(win.mdi.activeSubWindow().widget(), ImageDocument)
    assert win.actions["grid.math"].isEnabled()
    assert [it.text(0).split("  (")[0] for it in win.explorer.child_items("images")] == [img.name]


def test_import_raster_reprojected_to_project_crs(win, gis):
    win.project.default_crs = "EPSG:4326"
    g = win.import_raster(gis / "dem_50m_utm39n.tif",
                          values={"kind": "grid", "target_crs": "EPSG:4326"})
    assert g is not None and g.crs == "EPSG:4326" and g.xy_units == "deg"


def test_grid_math_commands(win, dem, gis):
    calc = win.grid_calculator({"expression": "A * 2 - 1", "A": dem.id, "name": "Doubled"})
    assert calc is not None and calc.name == "Doubled"
    np.testing.assert_allclose(calc.z, dem.z * 2 - 1, equal_nan=True)
    two = win.grid_calculator({"expression": "A - B", "A": calc.id, "B": dem.id})
    np.testing.assert_allclose(two.z, dem.z - 1, equal_nan=True, atol=1e-9)
    filt = win.grid_filter({"grid_id": dem.id, "kind": "median", "size": 5})
    assert filt.metadata["parameters"]["filter"] == "median"
    win.import_vector(gis / "land_use.gpkg")
    assert win.actions["grid_blank"].isEnabled()
    poly = next(iter(win.project.vectors))
    bl = win.grid_blank({"grid_id": dem.id, "vector_id": poly, "mode": "outside"})
    assert bl.n_blank >= dem.n_blank
    geo = dem.geometry
    cl = win.grid_clip({"grid_id": dem.id, "x0": geo.x_min, "x1": geo.x_min + 1000,
                        "y0": geo.y_min, "y1": geo.y_min + 1000})
    assert cl.geometry.nx <= 22
    assert win.grid_calculator({"expression": "A +", "A": dem.id}) is None
    assert "Grid calculator" in win.console.plain_text()


def test_terrain_volume_profile(win, dem, gis, tmp_path):
    for kind in ("slope", "aspect", "hillshade", "curvature"):
        g = win.terrain(kind, {"grid_id": dem.id})
        assert g is not None, kind
    hs = [g for g in win.project.grids.values() if g.metadata.get("method", "").endswith("hillshade")][0]
    assert 0 <= np.nanmin(hs.z) and np.nanmax(hs.z) <= 255
    lo = float(np.nanmin(dem.z))
    res = win.grid_volume({"upper": dem.id, "level": lo, "method": "simpson"})
    assert res["net_volume"] > 0 and res["fill_volume"] == pytest.approx(0, abs=1e-6)
    assert win.project.history[-1].action == "grid.volume"
    assert "Net volume" in win.console.plain_text()
    geo = dem.geometry
    prof = win.grid_profile({"grid_id": dem.id, "source": "__typed__",
                             "vertices": f"{geo.x_min} {geo.y_min}; {geo.x_max} {geo.y_max}"})
    assert prof is not None and prof["distance"][-1] > 0
    dlg = win._last_profile_dialog
    assert isinstance(dlg, ProfileDialog)
    out = dlg.export_csv(tmp_path / "p.csv")
    assert out and (tmp_path / "p.csv").read_text().startswith("distance,x,y,z")
    win.import_vector(gis / "wadi_channels.shp")
    line = next(iter(win.project.vectors))
    prof2 = win.grid_profile({"grid_id": dem.id, "source": line, "feature": 1})
    assert prof2 is not None and np.isfinite(prof2["z"]).sum() > 5


def test_point_density_and_vector_to_points(win, gis):
    win.import_vector(gis / "flood_reports.geojson")   # WGS 84 points: KDE must refuse
    vid = next(iter(win.project.vectors))
    assert win.point_density({"source": vid, "make_map": False}) is None
    assert "projected coordinates" in win.console.plain_text()
    bh = win.import_vector(gis / "boreholes.gpkg")
    g = win.point_density({"source": bh.id, "n_long": 60, "bandwidth": 800.0})
    assert g is not None and g.z_units.endswith("km²")
    assert g.metadata["parameters"]["bandwidth"] == 800.0
    m = next(m for m in win.project.maps.values() if m.layers[0].grid_id == g.id)
    assert m.layers[0].clear_below is not None
    assert isinstance(win.mdi.activeSubWindow().widget(), MapView)
    cnt = win.point_density({"source": bh.id, "method": "count", "make_map": False})
    assert cnt.z.sum() == pytest.approx(40)
    ds = win.vector_to_points(bh.id, {"z_field": "water_level_mAMSL"})
    assert ds is not None and ds.n_points == 40 and ds.has_z
    assert win.actions["grid_data"].isEnabled()
    wdens = win.point_density({"source": ds.id, "weight": "Z", "n_long": 40, "make_map": False})
    assert wdens.metadata["parameters"]["weighted"] is True


def test_gis_map_layers_and_properties(win, gis, dem):
    img = win.import_raster(gis / "basemap_rgb_wgs84.tif", values={"kind": "image"})
    lu = win.import_vector(gis / "land_use.gpkg")
    win.new_map("colour_relief", dem.id)
    mid = win.selected_item("map")
    lyr = win.add_gis_layer(mid, lu.id)
    assert isinstance(lyr, VectorLayer) and lyr.fill
    base = win.add_gis_layer(mid, img.id)
    doc = win.project.maps[mid]
    assert isinstance(doc.layers[0], ImageLayer) and doc.layers[0] is base  # bottom
    view = win.documents[mid].widget()
    assert view.layers.count() == len(doc.layers)
    # vector symbology through the Properties panel
    keys = {p.key for p in layer_props(lyr, win.project) if p.key}
    assert {"layer.symbology", "layer.field", "layer.label_field"} <= keys
    with pytest.raises(MapError, match="field"):
        apply_edit(doc, lyr.id, "layer.symbology", "categorized")
    win._map_prop_target = (mid, lyr.id)
    win._phase2_property_edited("layer.field", "class")
    win._phase2_property_edited("layer.symbology", "categorized")
    assert lyr.symbology == "categorized"
    # furniture
    for key, val in (("map.legend.visible", "Yes"), ("map.inset.visible", "Yes"),
                     ("map.graticule.geographic", "Yes"), ("map.graticule.interval_deg", "0.05")):
        win._map_prop_target = (mid, None)
        win._phase2_property_edited(key, val)
    assert doc.legend["visible"] and doc.inset["visible"] and doc.graticule["interval_deg"] == 0.05
    box = win.add_map_text(mid, "Synthetic data")
    assert any(p.key == f"map.text.{box['id']}.text" for p in map_props(doc))
    apply_edit(doc, None, f"map.text.{box['id']}.text", "")
    assert not doc.text_boxes
    view.refresh()
    assert "legend" in view.info.artists and "inset" in view.info.artists


def test_map_export_tiff(win, dem, tmp_path):
    win.new_map("colour_relief", dem.id)
    mid = win.selected_item("map")
    out = win.export_map(mid, tmp_path / "map.tif", dpi=120)
    assert out is not None and out.suffix == ".tif"
    assert win.project.outputs[-1]["format"].startswith("TIFF")


def test_logo_from_file(win, dem, tmp_path):
    from PIL import Image
    win.new_map("colour_relief", dem.id)
    mid = win.selected_item("map")
    p = tmp_path / "logo.png"
    Image.new("RGBA", (60, 30), (0, 128, 128, 255)).save(p)
    logo = win.set_map_logo(mid, p)
    assert logo["visible"] and logo["data"] and logo["name"] == "logo.png"
    view = win.documents[mid].widget()
    assert "logo" in view.info.artists


def test_undo_redo_round_trip(win, gis, dem, tmp_path):
    assert win.actions["edit.undo"].isEnabled()
    assert "Undo" in win.actions["edit.undo"].text()
    lu = win.import_vector(gis / "land_use.gpkg")
    s = win.terrain("slope", {"grid_id": dem.id})
    assert s.id in win.project.grids
    assert win.undo() == "Create grid"
    assert s.id not in win.project.grids and lu.id in win.project.vectors
    assert win.actions["edit.redo"].isEnabled()
    assert win.redo() == "Create grid"
    assert s.id in win.project.grids
    # undo a removal
    win.remove_vector(lu.id)
    assert lu.id not in win.project.vectors
    win.undo()
    assert lu.id in win.project.vectors
    # a map edit is undoable and open documents are rebuilt on the restored objects
    win.new_map("colour_relief", dem.id)
    mid = win.selected_item("map")
    win._map_prop_target = (mid, None)
    win._phase2_property_edited("map.title", "Changed title")
    assert win.project.maps[mid].title == "Changed title"
    win.undo()
    assert win.project.maps[mid].title != "Changed title"
    view = win.documents[mid].widget()
    assert view.doc is win.project.maps[mid]
    actions = [h.action for h in win.project.history]
    assert "edit.undo" in actions and "edit.redo" in actions  # history is append-only
    # an export changes nothing undoable
    n = len(win.undo_stack.labels())
    assert win.export_grid(dem.id, tmp_path / "probe.grd") is not None
    assert len(win.undo_stack.labels()) == n


def test_undo_resets_on_new_project(win, dem):
    assert win.undo_stack.can_undo
    win.new_project()
    assert not win.undo_stack.can_undo and not win.actions["edit.undo"].isEnabled()


def test_vector_properties_and_crs_assignment(win, gis):
    ds = win.import_vector(gis / "boreholes.gpkg")
    win._show_vector_properties(ds.id)
    assert "vector.crs" in win.properties.editors
    win._gis_property_edited("vector.name", "Wells")
    assert ds.name == "Wells"
    win._gis_property_edited("vector.crs", "EPSG:4326")
    assert ds.crs == "EPSG:4326" and ds.xy_units == "deg"
    assert win.project.history[-1].action == "vector.assign_crs"


def test_save_and_reload_gis_project(win, gis, dem, tmp_path):
    win.import_vector(gis / "wadi_channels.shp")
    win.import_raster(gis / "basemap_rgb_wgs84.tif", values={"kind": "image"})
    path = tmp_path / "gis.ghproj"
    save_project(win.project, path)
    p = load_project(path)
    assert len(p.vectors) == 1 and len(p.images) == 1 and dem.id in p.grids
    assert win.open_project(str(path))
    assert len(win.explorer.child_items("vectors")) == 1


def test_gis_demo_project_opens_and_renders(win):
    assert GIS_SAMPLE_PROJECT.exists()
    win.open_sample_project(GIS_SAMPLE_PROJECT)
    p = win.project
    assert p.path is None and len(p.maps) == 3 and p.vectors and p.images
    for mid in list(p.maps):
        view = win.open_map(mid)
        assert view.info is not None
        assert not [w for w in view.info.warnings if "missing" in w], view.info.warnings
    assert win.validate_project() == 0


def test_param_dialog_values(qtbot):
    dlg = ParamDialog("T", [Field("a", "A", "float", 1.5), Field("n", "N", "int", 3),
                            Field("c", "C", "choice", "y", [("x", "X"), ("y", "Y")]),
                            Field("b", "B", "bool", True), Field("t", "T", "text", "hi"),
                            Field("o", "Optional", "float", None, optional=True)])
    qtbot.addWidget(dlg)
    assert dlg.values() == {"a": 1.5, "n": 3, "c": "y", "b": True, "t": "hi", "o": None}
    dlg.set_value("c", "x")
    dlg.set_value("o", 2.5)
    dlg.set_value("n", 7)
    v = dlg.values()
    assert v["c"] == "x" and v["o"] == 2.5 and v["n"] == 7
    with pytest.raises(KeyError):
        dlg.set_value("c", "zz")
