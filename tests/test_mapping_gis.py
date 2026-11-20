"""Phase 3 map features: vector/image layers, symbology, legend, inset, graticule,
logo, text boxes, TIFF and font-embedded PDF export."""

import base64
import io

import numpy as np
import pandas as pd
import pytest
import shapely
from PIL import Image

from geohydro.engine.errors import MapError
from geohydro.engine.gridding.grid import Grid, GridGeometry
from geohydro.engine.mapping.gis_render import classify, dms, encode_logo, feature_colours
from geohydro.engine.mapping.model import (ColourReliefLayer, ImageLayer, MapDocument,
                                           VectorLayer, layer_from_dict)
from geohydro.engine.mapping.render import export_map, render_map
from geohydro.engine.raster import RasterImage
from geohydro.engine.vector import VectorDataset

UTM = "EPSG:32639"


@pytest.fixture
def items():
    polys = VectorDataset("zones", np.array([shapely.box(440000, 2885000, 445000, 2890000),
                                             shapely.box(445000, 2885000, 450000, 2890000).difference(
                                                 shapely.box(446000, 2886000, 447000, 2887000))],
                                            dtype=object),
                          pd.DataFrame({"cls": ["A", "B"], "v": [1.0, np.nan]}), crs=UTM)
    lines = VectorDataset("rivers", np.array([shapely.LineString([(440000, 2885000),
                                                                  (450000, 2890000)])],
                                             dtype=object), pd.DataFrame({"n": ["W"]}), crs=UTM)
    pts = VectorDataset("wells", shapely.points(np.array([[441000, 2886000], [449000, 2889000],
                                                         [445000, 2887500]])),
                        pd.DataFrame({"wl": [1.0, 2.0, 3.0], "id": ["a", "b", "c"]}), crs=UTM)
    img = RasterImage("base", np.full((20, 20, 4), 200, np.uint8), (50.38, 50.52, 26.07, 26.18),
                      crs="EPSG:4326")
    g = Grid(GridGeometry(440000, 450000, 2885000, 2890000, 11, 6), np.arange(66.0).reshape(6, 11),
             crs=UTM)
    d = {o.id: o for o in (polys, lines, pts, img, g)}
    return d, polys, lines, pts, img, g


def test_vector_and_image_layers_render(items):
    d, polys, lines, pts, img, g = items
    doc = MapDocument(crs=UTM, layers=[
        ImageLayer(image_id=img.id, name="Base"),
        VectorLayer(vector_id=polys.id, name="Zones", symbology="categorized", field="cls",
                    label_field="cls"),
        VectorLayer(vector_id=lines.id, name="Rivers", edge_color="#0000ff"),
        VectorLayer(vector_id=pts.id, name="Wells", symbology="graduated", field="wl", classes=3,
                    classification="equal_interval", label_field="id")],
        legend={"visible": True, "position": "lower right", "xy": None, "title": "L", "size": 8})
    fig, info = render_map(doc, d.get)
    assert any("reprojected" in w for w in info.warnings)        # WGS 84 image → UTM
    assert "legend" in info.artists
    labels = [t.get_text() for t in info.artists["legend"].get_texts()]
    assert "Zones" in labels and any("A" in x for x in labels) and "Rivers" in labels
    assert any("–" in x for x in labels)                         # graduated class ranges
    assert doc.referenced_ids() == {img.id, polys.id, lines.id, pts.id}


def test_symbology_colours_and_no_data(items):
    _, polys, _, pts, _, _ = items
    cols, leg = feature_colours(VectorLayer(symbology="categorized", field="cls",
                                            palette="tab10"), polys)
    assert [lbl for lbl, _ in leg] == ["A", "B"] and not np.allclose(cols[0], cols[1])
    cols, leg = feature_colours(VectorLayer(symbology="graduated", field="v", classes=2), polys)
    assert leg[-1][0] == "no data"
    with pytest.raises(MapError, match="not found"):
        feature_colours(VectorLayer(symbology="graduated", field="zz"), pts)


def test_classification():
    v = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 100.0])
    assert np.allclose(classify(v, 4, "equal_interval"), [0, 25, 50, 75, 100])
    q = classify(v, 2, "quantile")
    assert np.allclose(q, [0, 4.5, 100])
    assert classify(np.ones(5), 3, "quantile").size == 2
    with pytest.raises(MapError):
        classify(np.array([np.nan]), 3, "quantile")


def test_inset_text_and_logo(items, tmp_path):
    d, polys, lines, pts, img, g = items
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (40, 20), (255, 0, 0, 255)).save(logo)
    doc = MapDocument(crs=UTM, extent=[442000, 446000, 2886000, 2889000], layers=[
        VectorLayer(vector_id=polys.id), VectorLayer(vector_id=pts.id)],
        inset={"visible": True, "position": "lower left", "size": 0.3, "extent": None,
               "frame_color": "red"},
        text_boxes=[{"id": "t1", "text": "Data: synthetic", "x": 0.05, "y": 0.02, "frame": True}],
        logo={"visible": True, "data": encode_logo(logo), "name": "logo.png",
              "position": "upper left", "xy": None, "width_mm": 20})
    fig, info = render_map(doc, d.get)
    iax = info.artists["inset"]
    x0, x1 = iax.get_xlim()
    assert x0 < 442000 and x1 > 446000 and (x1 - x0) >= 3 * 4000 * 0.99
    assert info.artists["text:t1"].get_text() == "Data: synthetic"
    assert "logo" in info.artists
    bad = MapDocument(crs=UTM, layers=[VectorLayer(vector_id=pts.id)],
                      logo={"visible": True, "data": base64.b64encode(b"junk").decode()})
    _, info = render_map(bad, d.get)
    assert any("logo" in w for w in info.warnings)


def test_latlon_graticule_and_dms(items):
    d, *_ , g = items
    doc = MapDocument(crs=UTM, layers=[ColourReliefLayer(grid_id=g.id)],
                      graticule={"visible": True, "lines": False, "geographic": True,
                                 "interval_deg": 0.02})
    fig, info = render_map(doc, d.get)
    gr = info.artists["latlon_graticule"]
    assert gr["interval_deg"] == 0.02 and gr["lines"] >= 6
    texts = [t.get_text() for t in info.ax.texts]
    assert any(t.endswith("E") for t in texts) and any(t.endswith("N") for t in texts)
    assert dms(50.5, "lon", 1 / 60) == "50°30′E"
    assert dms(-26.25, "lat", 0.25) == "26°15′S"
    assert dms(26.0083333, "lat", 1 / 3600) == "26°00′30″N"


def test_clear_below_masks_values(items):
    d, *_, g = items
    doc = MapDocument(crs=UTM, layers=[ColourReliefLayer(grid_id=g.id, clear_below=10)])
    fig, info = render_map(doc, d.get)
    im = info.ax.images[0]
    assert np.ma.getmaskarray(im.get_array())[0, :10].all()


def test_tiff_and_pdf_export(items, tmp_path):
    d, polys, *_ = items
    doc = MapDocument(crs=UTM, title="Embedded fonts", layers=[VectorLayer(vector_id=polys.id)])
    out, _ = export_map(doc, d.get, tmp_path / "m.tif", dpi=150)
    with Image.open(out) as im:
        assert im.format == "TIFF" and im.info.get("compression") == "tiff_lzw"
        assert round(im.info["dpi"][0]) == 150
    pdf, _ = export_map(doc, d.get, tmp_path / "m.pdf")
    raw = pdf.read_bytes()
    assert b"/FontFile2" in raw          # TrueType (Type 42) fonts embedded, text editable
    assert b"/Subtype /Type3" not in raw


def test_v2_document_gets_phase3_defaults():
    old = MapDocument().to_dict()
    for k in ("legend", "logo", "inset", "text_boxes"):
        old.pop(k)
    old["graticule"] = {"visible": True, "lines": True, "line_alpha": 0.25}
    doc = MapDocument.from_dict(old)
    assert doc.legend["visible"] is False and doc.graticule["geographic"] is False
    lyr = layer_from_dict(VectorLayer(vector_id="x", symbology="graduated").to_dict())
    assert isinstance(lyr, VectorLayer) and lyr.symbology == "graduated"


def test_wrong_source_kind_is_reported(items):
    d, polys, *_ , g = items
    doc = MapDocument(crs=UTM, layers=[VectorLayer(vector_id=g.id, name="X"),
                                       ImageLayer(image_id=polys.id, name="Y")])
    _, info = render_map(doc, d.get)
    assert any("needs a vector layer" in w for w in info.warnings)
    assert any("needs a raster image" in w for w in info.warnings)
