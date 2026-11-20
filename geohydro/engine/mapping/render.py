"""Render a :class:`MapDocument` with Matplotlib (no Qt dependency) and export it.

The renderer draws on a plain ``matplotlib.figure.Figure``; the desktop wraps
the same figure in a Qt canvas and a future web backend can render it to PNG
or SVG on a server.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.offsetbox import (AnchoredOffsetbox, AuxTransformBox, DrawingArea, TextArea,
                                  VPacker)
from matplotlib.patches import Polygon

from ..errors import MapError
from .levels import get_cmap
from .model import (ColourReliefLayer, ContourLayer, FilledContourLayer, MapDocument,
                    PostLayer)

EXPORT_FORMATS = {"png": "PNG image", "jpg": "JPEG image", "jpeg": "JPEG image",
                  "svg": "SVG vector graphic", "pdf": "PDF document"}
MAX_POST_LABELS = 3000

_LOC = {"upper right": 1, "upper left": 2, "lower left": 3, "lower right": 4, "center": 10}


@dataclass
class RenderInfo:
    extent: tuple | None = None
    warnings: list = field(default_factory=list)
    artists: dict = field(default_factory=dict)  # name -> artist (for layout editing)
    ax: object = None
    north_convergence: float | None = None  # degrees clockwise from grid north
    scale_text: str = ""


# ------------------------------------------------------------------ helpers
def _crs_info(doc: MapDocument):
    if not doc.crs:
        return None
    try:
        from ..crs import resolve_crs
        return resolve_crs(doc.crs)
    except Exception:  # invalid CRS is reported, map still draws
        return None


def _layer_extent(obj):
    if obj is None:
        return None
    if getattr(obj, "kind", "") == "grid":
        g = obj.geometry
        return g.x_min, g.x_max, g.y_min, g.y_max
    if hasattr(obj, "extent"):
        return obj.extent()
    return None


def _union(exts):
    exts = [e for e in exts if e]
    if not exts:
        return None
    return (min(e[0] for e in exts), max(e[1] for e in exts),
            min(e[2] for e in exts), max(e[3] for e in exts))


def _fmt_level(v, decimals):
    if decimals is None:
        return f"{v:g}"
    return f"{v:.{decimals}f}"


def _auto_decimals(levels):
    if len(levels) < 2:
        return None
    step = float(np.min(np.diff(levels)))
    if step <= 0:
        return None
    return max(0, -int(math.floor(math.log10(step) + 1e-9)))


def true_north_bearing(crs_text: str, x: float, y: float) -> float | None:
    """Bearing of true north from grid north at (x, y), degrees clockwise.

    Computed numerically from the CRS by projecting a small northward step
    along the meridian, so it does not depend on sign conventions.
    Returns None for undefined or geographic CRSs (where it is 0 by definition).
    """
    from pyproj import CRS, Transformer
    crs = CRS.from_user_input(crs_text)
    if not crs.is_projected:
        return None
    to_geo = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    to_prj = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    lon, lat = to_geo.transform(x, y)
    if not (np.isfinite(lon) and np.isfinite(lat)):
        return None
    d = 1e-4 if abs(lat) < 89.9 else -1e-4
    x1, y1 = to_prj.transform(lon, lat + d)
    return math.degrees(math.atan2(x1 - x, y1 - y)) * (1 if d > 0 else -1)


def _nice_length(target: float) -> float:
    if target <= 0:
        return 1.0
    e = math.floor(math.log10(target))
    best = 10**e
    for m in (1, 2, 2.5, 5):
        if m * 10**e <= target:
            best = m * 10**e
    return best


def _anchor_kwargs(pos, ax):
    if pos.xy is not None:
        return dict(loc="center", bbox_to_anchor=tuple(pos.xy), bbox_transform=ax.transAxes)
    return dict(loc=_LOC.get(pos.position, 3))


def _scale_bar(ax, doc, ext, crs, info):
    x0, x1, y0, y1 = ext
    width = x1 - x0
    lat_c = None
    if crs is not None and crs.is_geographic:
        from pyproj import Geod
        lat_c = (y0 + y1) / 2
        lon_c = (x0 + x1) / 2
        _, _, m_per_deg = Geod(ellps="WGS84").inv(lon_c - 0.5, lat_c, lon_c + 0.5, lat_c)
        metres_per_unit = m_per_deg
        unit = "m"
    else:
        unit = (crs.axis_unit if crs is not None else doc.xy_units) or "map units"
        metres_per_unit = 1.0 if unit in ("metre", "meter", "m") else None
        if unit in ("metre", "meter"):
            unit = "m"
    if metres_per_unit is not None:
        target_m = 0.25 * width * metres_per_unit
        use_km = target_m >= 2000
        nice = _nice_length(target_m / (1000 if use_km else 1))
        length_units = nice * (1000 if use_km else 1) / metres_per_unit
        label = f"{nice:g} {'km' if use_km else 'm'}"
        if lat_c is not None:
            label += f" (at {lat_c:.2f}°)"
    else:
        nice = _nice_length(0.25 * width)
        length_units = nice
        label = f"{nice:g} {unit}"
    info.scale_text = label
    # Bar drawn in data units (so it scales with the map), label below.
    seg = length_units / 2
    bar = AuxTransformBox(ax.transData)
    bar.add_artist(Line2D([0, length_units], [0, 0], color="black", linewidth=3,
                          solid_capstyle="butt"))
    bar.add_artist(Line2D([0, seg], [0, 0], color="white", linewidth=1.6,
                          solid_capstyle="butt"))
    for xv in (0, seg, length_units):
        bar.add_artist(Line2D([xv, xv], [0, 0], color="black", marker="|", markersize=7))
    txt = TextArea(label, textprops=dict(size=8))
    pack = VPacker(children=[bar, txt], align="center", pad=0, sep=4)
    box = AnchoredOffsetbox(child=pack, pad=0.4, borderpad=0.8, frameon=True,
                            **_anchor_kwargs(doc.scale_bar, ax))
    box.patch.set_alpha(0.8)
    box.patch.set_edgecolor("none")
    ax.add_artist(box)
    info.artists["scale_bar"] = box


def _north_arrow(ax, doc, ext, crs, info):
    angle = 0.0
    label = "N"
    if crs is not None and crs.is_projected and doc.crs:
        try:
            b = true_north_bearing(doc.crs, (ext[0] + ext[1]) / 2, (ext[2] + ext[3]) / 2)
            if b is not None:
                angle = b
                info.north_convergence = b
        except Exception:
            info.warnings.append("True north could not be computed; grid north is shown.")
    elif crs is None:
        label = "N (grid)"
    da = DrawingArea(26, 34, 0, 0)
    a = math.radians(-angle)  # clockwise bearing -> counter-clockwise rotation
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    centre = np.array([13.0, 16.0])

    def _r(pts):
        return (np.asarray(pts, float) - centre) @ rot.T + centre

    da.add_artist(Polygon(_r([[13, 31], [5, 2], [13, 9]]), closed=True, facecolor="black",
                          edgecolor="black", linewidth=0.8))
    da.add_artist(Polygon(_r([[13, 31], [21, 2], [13, 9]]), closed=True, facecolor="white",
                          edgecolor="black", linewidth=0.8))
    txt = TextArea(label, textprops=dict(size=9, weight="bold"))
    pack = VPacker(children=[txt, da], align="center", pad=0, sep=1)
    box = AnchoredOffsetbox(child=pack, pad=0.3, borderpad=0.8, frameon=False,
                            **_anchor_kwargs(doc.north_arrow, ax))
    ax.add_artist(box)
    info.artists["north_arrow"] = box


# ------------------------------------------------------------------ main
def render_map(doc: MapDocument, resolve, fig: Figure | None = None,
               fit_figure: bool = False) -> tuple[Figure, RenderInfo]:
    """Draw ``doc``. ``resolve(id)`` returns a Grid / PointDataset or None.

    The figure is sized to the document's page, unless ``fit_figure`` is
    True, in which case the layout uses the existing figure size (used for
    on-screen previews that fill a window).
    """
    info = RenderInfo()
    w_in, h_in = doc.page_size_inches()
    if fig is None:
        fig = Figure(figsize=(w_in, h_in))
    else:
        fig.clear()
        if fit_figure:
            w_in, h_in = (float(v) for v in fig.get_size_inches())
        else:
            fig.set_size_inches(w_in, h_in, forward=False)
    fig.patch.set_facecolor("white")
    crs = _crs_info(doc)
    if doc.crs and crs is None:
        info.warnings.append(f"CRS '{doc.crs}' could not be resolved.")

    objs = {}
    for lyr in doc.layers:
        ref = getattr(lyr, "grid_id", "") or getattr(lyr, "dataset_id", "")
        obj = resolve(ref) if ref else None
        if obj is None:
            info.warnings.append(f"Layer '{lyr.name}': its data source is missing.")
        objs[lyr.id] = obj
    ext = tuple(doc.extent) if doc.extent else _union(
        [_layer_extent(objs[lyr.id]) for lyr in doc.layers if lyr.visible])
    info.extent = ext

    m = doc.margins_mm / 25.4
    top = m + (0.45 if doc.title else 0) + (0.3 if doc.subtitle else 0)
    show_cb = bool(doc.colorbar.get("visible", True))
    cb_w = 1.0 if show_cb else 0.0
    left, bottom = m + 0.55, m + 0.45  # room for tick labels
    ax_w = max(w_in - left - m - cb_w, 1.0)
    ax_h = max(h_in - bottom - top, 1.0)
    ax = fig.add_axes([left / w_in, bottom / h_in, ax_w / w_in, ax_h / h_in])
    info.ax = ax
    if ext is None:
        _titles(fig, doc, ax, info)
        ax.text(0.5, 0.5, "Empty map: add a layer", ha="center", va="center",
                transform=ax.transAxes, color="#888888")
        ax.set_xticks([])
        ax.set_yticks([])
        return fig, info

    x0, x1, y0, y1 = ext
    if crs is not None and crs.is_geographic:
        ax.set_aspect(1 / max(math.cos(math.radians((y0 + y1) / 2)), 1e-6))
    else:
        ax.set_aspect("equal")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.apply_aspect()  # the frame shrinks to the map's aspect; furniture follows it

    colour_mappable = None
    colour_label = ""
    for z, lyr in enumerate(doc.layers):
        if not lyr.visible:
            continue
        obj = objs[lyr.id]
        if obj is None:
            continue
        try:
            mp = _draw_layer(ax, lyr, obj, z + 1, info)
        except MapError as exc:
            info.warnings.append(f"Layer '{lyr.name}': {exc}")
            continue
        if mp is not None:
            colour_mappable = mp
            zl = getattr(obj, "z_label", "Z") or "Z"
            zu = getattr(obj, "z_units", "")
            colour_label = f"{zl} ({zu})" if zu else zl

    gr = doc.graticule or {}
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.tick_params(labelsize=7)
    if gr.get("visible", True):
        if gr.get("lines", True):
            ax.grid(True, linewidth=0.4, alpha=gr.get("line_alpha", 0.25), color="black",
                    zorder=len(doc.layers) + 2)
        if crs is not None and crs.is_geographic:
            from matplotlib.ticker import FuncFormatter
            ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.4g}°"))
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.4g}°"))
        for lab in ax.get_yticklabels():
            lab.set_rotation(90)
            lab.set_va("center")
    else:
        ax.set_xticks([])
        ax.set_yticks([])

    _titles(fig, doc, ax, info)
    if show_cb and colour_mappable is not None:
        pos = ax.get_position()
        cax = fig.add_axes([pos.x1 + 0.25 / w_in, pos.y0 + 0.1 * pos.height,
                            0.18 / w_in, 0.8 * pos.height])
        cb = fig.colorbar(colour_mappable, cax=cax)
        cb.set_label(doc.colorbar.get("label") or colour_label, size=8)
        cb.ax.tick_params(labelsize=7)
        info.artists["colorbar"] = cb

    if doc.scale_bar.visible:
        _scale_bar(ax, doc, ext, crs, info)
    if doc.north_arrow.visible:
        _north_arrow(ax, doc, ext, crs, info)
    for a in doc.annotations or []:
        ax.annotate(a.get("text", ""), (a.get("x"), a.get("y")), xycoords="data",
                    fontsize=a.get("size", 9), color=a.get("color", "black"),
                    zorder=len(doc.layers) + 5)
    return fig, info


def _titles(fig, doc, ax, info):
    pos = ax.get_position()
    h_in = fig.get_size_inches()[1]
    y = pos.y1 + 0.2 / h_in
    if doc.subtitle:
        info.artists["subtitle"] = fig.text(0.5 * (pos.x0 + pos.x1), y, doc.subtitle,
                                            ha="center", va="bottom", size=10, color="#444444")
        y += 0.3 / h_in
    if doc.title:
        info.artists["title"] = fig.text(0.5 * (pos.x0 + pos.x1), y, doc.title, ha="center",
                                         va="bottom", size=15, weight="bold")


def _draw_layer(ax, lyr, obj, zorder, info):
    kind = getattr(obj, "kind", "")
    if isinstance(lyr, (ContourLayer, FilledContourLayer, ColourReliefLayer)):
        if kind != "grid":
            raise MapError("this layer type needs a grid.")
        g = obj.geometry
        z = np.ma.masked_invalid(obj.z)
        if z.count() == 0:
            raise MapError("the grid has no valid values.")
        zmin, zmax = float(z.min()), float(z.max())
        xs, ys = g.x_nodes(), g.y_nodes()
        if isinstance(lyr, ColourReliefLayer):
            vmin = lyr.z_min if lyr.z_min is not None else zmin
            vmax = lyr.z_max if lyr.z_max is not None else zmax
            if vmax <= vmin:
                vmax = vmin + 1e-12
            im = ax.imshow(z, origin="lower", cmap=get_cmap(lyr.palette, lyr.reverse),
                           vmin=vmin, vmax=vmax, alpha=lyr.opacity,
                           interpolation="bilinear" if lyr.smooth else "nearest",
                           extent=[g.x_min - g.dx / 2, g.x_max + g.dx / 2,
                                   g.y_min - g.dy / 2, g.y_max + g.dy / 2],
                           zorder=zorder, aspect=ax.get_aspect())
            return im if lyr.show_colorbar else None
        levels = lyr.levels.levels(zmin, zmax)
        if isinstance(lyr, FilledContourLayer):
            if levels.size < 2:
                raise MapError("filled contours need at least two levels.")
            extend = ("both" if zmin < levels[0] and zmax > levels[-1] else
                      "min" if zmin < levels[0] else "max" if zmax > levels[-1] else "neither")
            cs = ax.contourf(xs, ys, z, levels=levels, cmap=get_cmap(lyr.palette, lyr.reverse),
                             alpha=lyr.opacity, extend=extend, zorder=zorder)
            return cs if lyr.show_colorbar else None
        # line contours
        inside = levels[(levels >= zmin) & (levels <= zmax)]
        if inside.size == 0:
            info.warnings.append(f"Layer '{lyr.name}': no contour level within the grid range.")
            return None
        major = np.zeros(levels.size, bool)
        if lyr.major_every and lyr.major_every > 0:
            step = float(np.median(np.diff(levels))) if levels.size > 1 else 1.0
            major = np.isclose(np.mod(np.round(levels / step), lyr.major_every), 0)
        widths = np.where(major, lyr.major_width, lyr.line_width)
        kw = dict(levels=levels, linewidths=widths, alpha=lyr.opacity, zorder=zorder)
        if lyr.color_by_level:
            kw["cmap"] = get_cmap(lyr.palette, lyr.reverse)
        else:
            kw["colors"] = lyr.line_color
        cs = ax.contour(xs, ys, z, **kw)
        if lyr.labels:
            lab_levels = levels[major] if major.any() else levels
            lab_levels = [v for v in lab_levels if zmin <= v <= zmax]
            if lab_levels:
                dec = lyr.label_decimals if lyr.label_decimals is not None else \
                    _auto_decimals(levels)
                ax.clabel(cs, levels=lab_levels, fontsize=lyr.label_size, inline=True,
                          fmt=lambda v: _fmt_level(v, dec))
        return None
    if isinstance(lyr, PostLayer):
        if not hasattr(obj, "data"):
            raise MapError("a post layer needs a point dataset.")
        d = obj.data
        x, y = d["X"].to_numpy(float), d["Y"].to_numpy(float)
        kw = dict(s=lyr.size, marker=lyr.marker, edgecolors=lyr.edge_color, linewidths=0.6,
                  alpha=lyr.opacity, zorder=zorder)
        mp = None
        if lyr.color_by_z and "Z" in d:
            sc = ax.scatter(x, y, c=d["Z"].to_numpy(float), cmap=get_cmap(lyr.palette,
                                                                          lyr.reverse), **kw)
            mp = sc
        else:
            ax.scatter(x, y, c=lyr.face_color, **kw)
        col = lyr.label_column
        if col:
            if col not in d:
                info.warnings.append(f"Layer '{lyr.name}': label column '{col}' not found.")
            else:
                vals = d[col].to_numpy()
                n = len(vals)
                if n > MAX_POST_LABELS:
                    info.warnings.append(
                        f"Layer '{lyr.name}': {n} labels exceed {MAX_POST_LABELS}; labels "
                        "were not drawn.")
                else:
                    for xi, yi, v in zip(x, y, vals):
                        if isinstance(v, (float, np.floating)):
                            if not np.isfinite(v):
                                continue
                            v = f"{v:.{lyr.label_decimals}f}"
                        ax.annotate(str(v), (xi, yi), xytext=(3, 3), textcoords="offset points",
                                    fontsize=lyr.label_size, zorder=zorder, clip_on=True)
        return mp
    raise MapError(f"unsupported layer type {lyr.type}.")


def export_map(doc: MapDocument, resolve, path, dpi: int = 300, overwrite: bool = False
               ) -> tuple[Path, RenderInfo]:
    path = Path(path)
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in EXPORT_FORMATS:
        raise MapError(f"Unsupported export format '.{fmt}' (use PNG, JPEG, SVG or PDF).")
    if not (50 <= int(dpi) <= 1200):
        raise MapError("Resolution must be between 50 and 1200 dpi.")
    if path.exists() and not overwrite:
        raise MapError(f"{path} already exists.")
    fig, info = render_map(doc, resolve)
    tmp = path.with_name(f".{path.stem}.tmp{path.suffix}")
    try:
        kw = {"format": "jpeg" if fmt in ("jpg", "jpeg") else fmt, "dpi": int(dpi),
              "facecolor": "white"}
        if fmt in ("jpg", "jpeg"):
            kw["pil_kwargs"] = {"quality": 92}
        fig.savefig(tmp, **kw)
        os.replace(tmp, path)
    except OSError as exc:
        raise MapError(f"Could not write {path}: {exc}") from exc
    finally:
        if tmp.exists():
            tmp.unlink()
    return path, info
