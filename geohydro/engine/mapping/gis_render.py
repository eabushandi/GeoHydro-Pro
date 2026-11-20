"""Phase 3 map drawing: vector layers, base-map images, legend, text boxes,
logo, inset (overview) map and a latitude/longitude graticule.

Classification for graduated symbols
------------------------------------
equal_interval  class breaks at min + k·(max − min)/n
quantile        class breaks at the k/n quantiles of the values (linear
                interpolation between order statistics, NumPy default);
                duplicate breaks are merged, so fewer classes may result.
Features whose field value is missing are drawn in grey and listed as
"no data" in the legend.
"""

from __future__ import annotations

import base64
import io
import math

import numpy as np
from matplotlib.collections import LineCollection, PathCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, PathPatch, Rectangle
from matplotlib.path import Path as MPath

from ..errors import MapError
from .levels import get_cmap

MAX_CATEGORIES = 40
MAX_LABELS = 3000
NO_DATA_COLOR = "#bdbdbd"
_LOC = {"upper right": 1, "upper left": 2, "lower left": 3, "lower right": 4, "center": 10}


# ------------------------------------------------------------------ geometry → paths
def _ring_codes(n):
    codes = np.full(n, MPath.LINETO, dtype=MPath.code_type)
    codes[0] = MPath.MOVETO
    codes[-1] = MPath.CLOSEPOLY
    return codes


def polygon_path(poly) -> MPath:
    """Matplotlib path of a (multi)polygon with holes (even-odd via ring order)."""
    import shapely
    verts, codes = [], []
    for p in shapely.get_parts(poly):
        rings = [p.exterior, *p.interiors]
        for r in rings:
            c = np.asarray(r.coords)[:, :2]
            if len(c) < 3:
                continue
            verts.append(c)
            codes.append(_ring_codes(len(c)))
    if not verts:
        return None
    return MPath(np.concatenate(verts), np.concatenate(codes))


def _split(geoms):
    """Indices of polygon, line and point features (exploding collections)."""
    import shapely
    t = shapely.get_type_id(geoms)
    return (np.flatnonzero(np.isin(t, (3, 6))), np.flatnonzero(np.isin(t, (1, 2, 5))),
            np.flatnonzero(np.isin(t, (0, 4))), np.flatnonzero(t == 7))


# ------------------------------------------------------------------ symbology
def classify(values: np.ndarray, n: int, method: str) -> np.ndarray:
    v = values[np.isfinite(values)]
    if v.size == 0:
        raise MapError("the field has no numeric values.")
    n = max(int(n), 1)
    if method == "equal_interval":
        lo, hi = float(v.min()), float(v.max())
        breaks = np.linspace(lo, hi, n + 1) if hi > lo else np.array([lo, lo])
    elif method == "quantile":
        breaks = np.unique(np.quantile(v, np.linspace(0, 1, n + 1)))
        if breaks.size == 1:
            breaks = np.array([breaks[0], breaks[0]])
    else:
        raise MapError(f"unknown classification '{method}'.")
    return breaks


def feature_colours(lyr, vds):
    """Per-feature RGBA colours and legend entries [(label, colour)]."""
    from matplotlib.colors import to_rgba
    n = vds.n_features
    if lyr.symbology == "single" or not lyr.field:
        return np.tile(to_rgba(lyr.face_color, lyr.opacity), (n, 1)), [(lyr.name,
                                                                        lyr.face_color)]
    if lyr.field not in vds.attributes:
        raise MapError(f"field '{lyr.field}' not found.")
    col = vds.attributes[lyr.field]
    cols = np.tile(to_rgba(NO_DATA_COLOR, lyr.opacity), (n, 1))
    legend = []
    if lyr.symbology == "categorized":
        cats = [c for c in dict.fromkeys(col.dropna().tolist())]
        if len(cats) > MAX_CATEGORIES:
            raise MapError(f"{len(cats)} categories exceed the limit of {MAX_CATEGORIES}; use "
                           "graduated symbols or another field.")
        try:
            cats = sorted(cats)
        except TypeError:
            pass
        cmap = get_cmap(lyr.palette, lyr.reverse)
        m = max(len(cats), 1)
        for k, c in enumerate(cats):
            rgba = cmap(k % cmap.N if cmap.N < 64 else (k + 0.5) / m)
            rgba = (*rgba[:3], lyr.opacity)
            cols[(col == c).to_numpy()] = rgba
            legend.append((str(c), rgba))
    elif lyr.symbology == "graduated":
        import pandas as pd
        vals = pd.to_numeric(col, errors="coerce").to_numpy(float)
        breaks = classify(vals, lyr.classes, lyr.classification)
        cmap = get_cmap(lyr.palette, lyr.reverse)
        k = max(breaks.size - 1, 1)
        idx = np.clip(np.searchsorted(breaks, vals, side="right") - 1, 0, k - 1)
        ok = np.isfinite(vals)
        for i in range(k):
            rgba = cmap((i + 0.5) / k)
            rgba = (*rgba[:3], lyr.opacity)
            cols[ok & (idx == i)] = rgba
            legend.append((f"{breaks[i]:.4g} – {breaks[min(i + 1, breaks.size - 1)]:.4g}", rgba))
    else:
        raise MapError(f"unknown symbology '{lyr.symbology}'.")
    if col.isna().any():
        legend.append(("no data", NO_DATA_COLOR))
    return cols, legend


def draw_vector(ax, lyr, vds, zorder, info):
    import shapely
    if vds.n_features == 0:
        raise MapError("the layer has no features.")
    cols, legend = feature_colours(lyr, vds)
    g = vds.geometry
    ok = ~shapely.is_missing(g) & ~shapely.is_empty(g)
    poly_i, line_i, pt_i, coll_i = _split(np.where(ok, g, None))
    if coll_i.size:
        info.warnings.append(f"Layer '{lyr.name}': {coll_i.size} geometry collection(s) "
                             "were not drawn.")
    families = []
    for i in poly_i:
        path = polygon_path(g[i])
        if path is None:
            continue
        fc = cols[i] if lyr.fill else "none"
        ax.add_patch(PathPatch(path, facecolor=fc, edgecolor=lyr.edge_color,
                               linewidth=lyr.line_width, alpha=None if lyr.fill else lyr.opacity,
                               zorder=zorder))
    if poly_i.size:
        families.append("polygon")
    if line_i.size:
        segs, lc = [], []
        for i in line_i:
            for part in shapely.get_parts(g[i]):
                segs.append(np.asarray(part.coords)[:, :2])
                lc.append(cols[i] if lyr.symbology != "single" else
                          _rgba(lyr.edge_color, lyr.opacity))
        ax.add_collection(LineCollection(segs, colors=lc, linewidths=lyr.line_width,
                                         zorder=zorder))
        families.append("line")
    if pt_i.size:
        parts, src = shapely.get_parts(g[pt_i], return_index=True)
        xy = shapely.get_coordinates(parts)
        ax.scatter(xy[:, 0], xy[:, 1], s=lyr.marker_size, marker=lyr.marker,
                   c=cols[pt_i[src]], edgecolors=lyr.edge_color, linewidths=0.6, zorder=zorder)
        families.append("point")
    if lyr.label_field:
        _labels(ax, lyr, vds, ok, zorder, info)
    info.legend_entries.extend(_legend_handles(lyr, legend, families))


def _rgba(c, a):
    from matplotlib.colors import to_rgba
    return to_rgba(c, a)


def _labels(ax, lyr, vds, ok, zorder, info):
    import shapely
    if lyr.label_field not in vds.attributes:
        info.warnings.append(f"Layer '{lyr.name}': label field '{lyr.label_field}' not found.")
        return
    idx = np.flatnonzero(ok)
    if idx.size > MAX_LABELS:
        info.warnings.append(f"Layer '{lyr.name}': {idx.size} labels exceed {MAX_LABELS}; "
                             "labels were not drawn.")
        return
    vals = vds.attributes[lyr.label_field].to_numpy()
    for i in idx:
        v = vals[i]
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            continue
        geom = vds.geometry[i]
        t = shapely.get_type_id(geom)
        if t in (3, 6):
            p = shapely.point_on_surface(geom)
        elif t in (1, 2, 5):
            p = shapely.line_interpolate_point(geom, 0.5, normalized=True)
        else:
            p = shapely.get_parts(geom)[0]
        text = f"{v:.4g}" if isinstance(v, (float, np.floating)) else str(v)
        ax.annotate(text, (p.x, p.y), xytext=(3, 3) if t in (0, 4) else (0, 0),
                    textcoords="offset points", fontsize=lyr.label_size, zorder=zorder + 0.5,
                    ha="left" if t in (0, 4) else "center", va="bottom" if t in (0, 4)
                    else "center", clip_on=True)


def _legend_handles(lyr, legend, families):
    if not lyr.show_in_legend:
        return []
    out = []
    for label, colour in legend:
        if "polygon" in families:
            h = Patch(facecolor=colour if lyr.fill else "none", edgecolor=lyr.edge_color,
                      linewidth=lyr.line_width)
        elif "line" in families:
            h = Line2D([], [], color=colour if lyr.symbology != "single" else lyr.edge_color,
                       linewidth=max(lyr.line_width, 1.0))
        else:
            h = Line2D([], [], linestyle="none", marker=lyr.marker, markersize=6,
                       markerfacecolor=colour, markeredgecolor=lyr.edge_color)
        title = label if lyr.symbology == "single" else f"{lyr.name}: {label}" \
            if len(legend) == 1 else label
        out.append((h, title, lyr.name if lyr.symbology != "single" else None))
    return out


def draw_image(ax, lyr, img, zorder):
    x0, x1, y0, y1 = img.extent
    ax.imshow(img.rgba, extent=[x0, x1, y0, y1], origin="upper", alpha=lyr.opacity,
              interpolation="nearest", zorder=zorder, aspect=ax.get_aspect())


# ------------------------------------------------------------------ legend
def draw_legend(ax, doc, info):
    lg = doc.legend or {}
    entries = info.legend_entries
    if not lg.get("visible") or not entries:
        return
    handles, labels = [], []
    current_group = None
    for h, label, group in entries:
        if group and group != current_group:
            handles.append(Rectangle((0, 0), 0, 0, alpha=0))
            labels.append(group)
            current_group = group
        elif not group:
            current_group = None
        handles.append(h)
        labels.append(("   " if group else "") + label)
    kw = dict(fontsize=lg.get("size", 8), title=lg.get("title") or None,
              title_fontsize=lg.get("size", 8) + 1, framealpha=0.9, fancybox=False,
              edgecolor="#888888")
    if lg.get("xy"):
        kw.update(loc="center", bbox_to_anchor=tuple(lg["xy"]), bbox_transform=ax.transAxes)
    else:
        kw["loc"] = _LOC.get(lg.get("position", "lower right"), 4)
    leg = ax.legend(handles, labels, **kw)
    leg.set_zorder(1000)
    info.artists["legend"] = leg


# ------------------------------------------------------------------ text, logo
def draw_text_boxes(fig, doc, info):
    for tb in doc.text_boxes or []:
        bbox = dict(boxstyle="square,pad=0.4", facecolor="white", edgecolor="#555555",
                    linewidth=0.6) if tb.get("frame") else None
        t = fig.text(float(tb.get("x", 0.5)), float(tb.get("y", 0.05)), tb.get("text", ""),
                     size=tb.get("size", 9), color=tb.get("color", "black"),
                     weight="bold" if tb.get("bold") else "normal",
                     ha=tb.get("ha", "left"), va="bottom", bbox=bbox, zorder=1000, wrap=True)
        info.artists[f"text:{tb.get('id', '')}"] = t


def decode_logo(data: str):
    import matplotlib.image as mpimg
    if not data:
        return None
    raw = base64.b64decode(data)
    return mpimg.imread(io.BytesIO(raw), format="png")


def encode_logo(path) -> str:
    """Read an image file (PNG/JPEG) and return it as base64 PNG for embedding in a map."""
    import matplotlib.image as mpimg
    from matplotlib import pyplot as _unused  # noqa: F401  (registers PIL readers)
    arr = mpimg.imread(str(path))
    buf = io.BytesIO()
    mpimg.imsave(buf, arr, format="png")
    if buf.tell() > 2_000_000:
        raise MapError("The logo image is larger than 2 MB; use a smaller image.")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def draw_logo(fig, ax, doc, info):
    from matplotlib.offsetbox import AnchoredOffsetbox, OffsetImage
    lg = doc.logo or {}
    if not lg.get("visible") or not lg.get("data"):
        return
    try:
        arr = decode_logo(lg["data"])
    except Exception as exc:  # damaged image data: report, keep drawing
        info.warnings.append(f"The logo could not be drawn: {exc}")
        return
    dpi = fig.dpi
    width_px = float(lg.get("width_mm", 25.0)) / 25.4 * dpi
    zoom = width_px / max(arr.shape[1], 1)
    oi = OffsetImage(arr, zoom=zoom)
    kw = dict(loc="center", bbox_to_anchor=tuple(lg["xy"]), bbox_transform=ax.transAxes) \
        if lg.get("xy") else dict(loc=_LOC.get(lg.get("position", "upper left"), 2))
    box = AnchoredOffsetbox(child=oi, pad=0.2, borderpad=0.6, frameon=False, **kw)
    box.set_zorder(1000)
    ax.add_artist(box)
    info.artists["logo"] = box


# ------------------------------------------------------------------ inset map
def draw_inset(fig, ax, doc, objs, main_ext, info, draw_fn):
    ins = doc.inset or {}
    if not ins.get("visible"):
        return
    size = float(ins.get("size", 0.28))
    pos = ins.get("position", "lower right")
    x = 0.02 if "left" in pos else 0.98 - size
    y = 0.02 if "lower" in pos else 0.98 - size
    iax = ax.inset_axes([x, y, size, size], zorder=900)
    iax.set_xticks([])
    iax.set_yticks([])
    for s in iax.spines.values():
        s.set_linewidth(0.8)
    exts = []
    drawn = 0
    for z, lyr in enumerate(doc.layers):
        if not lyr.visible or not getattr(lyr, "show_in_inset", False):
            continue
        obj = objs.get(lyr.id)
        if obj is None:
            continue
        import copy
        small = copy.copy(lyr)
        for attr in ("label_field", "label_column"):
            if hasattr(small, attr):
                setattr(small, attr, None)
        if hasattr(small, "labels"):
            small.labels = False
        if hasattr(small, "marker_size"):
            small.marker_size = min(small.marker_size, 6)
        try:
            draw_fn(iax, small, obj, z + 1)
            drawn += 1
        except MapError:
            continue
        e = getattr(obj, "extent", None)
        exts.append(e if isinstance(e, tuple) else obj.bounds() if hasattr(obj, "bounds")
                    else None)
    exts = [e for e in exts if e]
    if ins.get("extent"):
        x0, x1, y0, y1 = ins["extent"]
    elif exts:
        x0, x1 = min(e[0] for e in exts), max(e[1] for e in exts)
        y0, y1 = min(e[2] for e in exts), max(e[3] for e in exts)
        x0, x1, y0, y1 = _union_square(x0, x1, y0, y1, main_ext, pad=1.15,
                                       min_factor=3.0)
    else:
        x0, x1, y0, y1 = _union_square(*main_ext, main_ext, pad=1.5)
    iax.set_xlim(x0, x1)
    iax.set_ylim(y0, y1)
    iax.set_aspect(ax.get_aspect() if ax.get_aspect() != "auto" else "equal",
                   adjustable="datalim")
    mx0, mx1, my0, my1 = main_ext
    iax.add_patch(Rectangle((mx0, my0), mx1 - mx0, my1 - my0, fill=False,
                            edgecolor=ins.get("frame_color", "#d62728"), linewidth=1.2,
                            zorder=1000))
    iax.set_facecolor("white")
    if not drawn:
        info.warnings.append("Inset map: no layer is set to appear in the inset; only the map "
                             "frame is shown.")
    info.artists["inset"] = iax


def _union_square(x0, x1, y0, y1, main, pad=1.15, min_factor=1.0):
    """Extent covering both boxes, padded, and at least ``min_factor`` × the main
    extent so that the inset shows context around the map frame."""
    x0, x1 = min(x0, main[0]), max(x1, main[1])
    y0, y1 = min(y0, main[2]), max(y1, main[3])
    cx, cy = (main[0] + main[1]) / 2, (main[2] + main[3]) / 2
    w = max((x1 - x0) * pad, (main[1] - main[0]) * min_factor) / 2
    h = max((y1 - y0) * pad, (main[3] - main[2]) * min_factor) / 2
    w = max(w, abs(x1 - cx) * pad, abs(cx - x0) * pad)
    h = max(h, abs(y1 - cy) * pad, abs(cy - y0) * pad)
    return cx - w, cx + w, cy - h, cy + h


# ------------------------------------------------------------------ lat/lon graticule
_DEG_STEPS = (1 / 3600, 2 / 3600, 5 / 3600, 10 / 3600, 15 / 3600, 30 / 3600, 1 / 60, 2 / 60,
              5 / 60, 10 / 60, 15 / 60, 30 / 60, 1, 2, 5, 10, 15, 30)


def dms(v: float, axis: str, step: float) -> str:
    hemi = ("E" if v >= 0 else "W") if axis == "lon" else ("N" if v >= 0 else "S")
    a = abs(v) + 1e-9
    d = int(a)
    m = int((a - d) * 60)
    s = (a - d - m / 60) * 3600
    if step >= 1:
        return f"{d}°{hemi}"
    if step >= 1 / 60:
        return f"{d}°{m:02d}′{hemi}"
    return f"{d}°{m:02d}′{s:02.0f}″{hemi}"


def draw_latlon_graticule(ax, doc, ext, info, zorder):
    """Meridians and parallels on a projected map, labelled in degrees-minutes."""
    gr = doc.graticule or {}
    if not gr.get("geographic") or not doc.crs:
        return
    from pyproj import CRS, Transformer
    crs = CRS.from_user_input(doc.crs)
    if not crs.is_projected:
        return
    geo = crs.geodetic_crs
    to_geo = Transformer.from_crs(crs, geo, always_xy=True)
    to_prj = Transformer.from_crs(geo, crs, always_xy=True)
    x0, x1, y0, y1 = ext
    bx = np.concatenate([np.linspace(x0, x1, 50), np.full(50, x1), np.linspace(x1, x0, 50),
                         np.full(50, x0)])
    by = np.concatenate([np.full(50, y0), np.linspace(y0, y1, 50), np.full(50, y1),
                         np.linspace(y1, y0, 50)])
    lon, lat = to_geo.transform(bx, by)
    lon0, lon1, lat0, lat1 = np.nanmin(lon), np.nanmax(lon), np.nanmin(lat), np.nanmax(lat)
    step = gr.get("interval_deg")
    if not step:
        span = max(lon1 - lon0, lat1 - lat0)
        step = next((s for s in _DEG_STEPS if span / s <= 6), 30)
    style = dict(color="#1f4e79", linewidth=0.5, alpha=0.6, zorder=zorder)
    tstyle = dict(fontsize=6.5, color="#1f4e79", zorder=zorder + 1,
                  bbox=dict(boxstyle="square,pad=0.1", facecolor="white", edgecolor="none",
                            alpha=0.8))
    n = 0
    for lo in np.arange(math.ceil(lon0 / step) * step, lon1 + step * 1e-6, step):
        la = np.linspace(lat0, lat1, 200)
        px, py = to_prj.transform(np.full_like(la, lo), la)
        ax.plot(px, py, **style)
        k = int(np.nanargmin(np.abs(py - y0)))
        if x0 <= px[k] <= x1:
            ax.text(px[k], y0 + 0.01 * (y1 - y0), dms(lo, "lon", step), ha="center",
                    va="bottom", **tstyle)
        n += 1
    for la in np.arange(math.ceil(lat0 / step) * step, lat1 + step * 1e-6, step):
        lo = np.linspace(lon0, lon1, 200)
        px, py = to_prj.transform(lo, np.full_like(lo, la))
        ax.plot(px, py, **style)
        k = int(np.nanargmin(np.abs(px - x0)))
        if y0 <= py[k] <= y1:
            ax.text(x0 + 0.01 * (x1 - x0), py[k], dms(la, "lat", step), ha="left",
                    va="center", **tstyle)
        n += 1
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    info.artists["latlon_graticule"] = {"interval_deg": step, "lines": n}


_ = PathCollection
