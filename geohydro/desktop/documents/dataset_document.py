"""Workspace document for a point dataset: table, preview, statistics, QC."""

from __future__ import annotations

import html
import math

from PySide6.QtWidgets import QTableView, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from geohydro.engine.crs import resolve_crs
from geohydro.engine.data.dataset import PointDataset
from geohydro.engine.data.qc import QCReport
from geohydro.engine.errors import CRSError

from .. import theme
from ..widgets.pandas_model import DataFrameModel
from ..widgets.point_preview import PointPreview

CSS = f"""
<style>
body {{ font-family: Inter, 'Segoe UI', sans-serif; color: {theme.TEXT}; font-size: 9.5pt; }}
h2 {{ color: {theme.NAVY}; font-size: 12pt; margin: 4px 0 6px 0; }}
h3 {{ color: {theme.NAVY_2}; font-size: 10pt; margin: 12px 0 4px 0; }}
table {{ border-collapse: collapse; }}
td, th {{ padding: 3px 12px 3px 6px; border-bottom: 1px solid {theme.BORDER}; }}
th {{ text-align: left; color: {theme.MUTED}; font-weight: 600; }}
td.num {{ text-align: right; font-family: 'DejaVu Sans Mono', Consolas, monospace; }}
.warn {{ color: {theme.WARNING}; }} .ok {{ color: {theme.SUCCESS}; }} .muted {{ color: {theme.MUTED}; }}
</style>
"""


def fmt_num(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if math.isnan(v):
            return "—"
        if v != 0 and (abs(v) >= 1e7 or abs(v) < 1e-3):
            return f"{v:.6g}"
        return f"{v:,.4f}".rstrip("0").rstrip(".")
    return f"{v:,}" if isinstance(v, int) else str(v)


def crs_label(crs: str | None) -> str:
    if not crs:
        return "CRS: undefined"
    try:
        info = resolve_crs(crs)
        return f"CRS: {info.display}" if info else "CRS: undefined"
    except CRSError:
        return f"CRS: {crs} (unrecognised)"


def statistics_html(ds: PointDataset) -> str:
    z = ds.z_statistics()
    s = ds.spatial_statistics()
    u, zu = ds.xy_units, ds.z_units
    rows_z = [
        ("Count", z.get("count")), ("Minimum", z.get("minimum")), ("Maximum", z.get("maximum")),
        ("Range", z.get("range")), ("Mean", z.get("mean")), ("Median", z.get("median")),
        ("1st quartile", z.get("q1")), ("3rd quartile", z.get("q3")),
        ("Standard deviation (n-1)", z.get("std")), ("Variance (n-1)", z.get("variance")),
        ("Coefficient of variation", z.get("coefficient_of_variation")),
        ("Skewness (adjusted)", z.get("skewness")),
    ]
    rows_s = [
        ("Points", s.get("count")), ("X min", s.get("x_min")), ("X max", s.get("x_max")),
        ("Y min", s.get("y_min")), ("Y max", s.get("y_max")), ("Extent width", s.get("width")),
        ("Extent height", s.get("height")), ("Mean nearest-neighbour distance", s.get("nn_mean")),
        ("Min nearest-neighbour distance", s.get("nn_min")),
        ("Max nearest-neighbour distance", s.get("nn_max")),
        ("Point density (per unit²)", s.get("density_per_unit_area")),
    ]

    def table(rows, unit):
        return "<table>" + "".join(
            f"<tr><th>{html.escape(k)}</th><td class='num'>{fmt_num(v)}</td><td class='muted'>{unit}</td></tr>"
            for k, v in rows
        ) + "</table>"

    zname = html.escape(ds.z_label)
    out = [CSS, f"<h2>{html.escape(ds.name)} — statistics</h2>",
           f"<p class='muted'>{html.escape(crs_label(ds.crs))} · XY units: {u} · Z units: {zu}</p>"]
    if ds.has_z:
        out += [f"<h3>Z values ({zname})</h3>", table(rows_z, zu)]
    out += ["<h3>Spatial distribution</h3>", table(rows_s, u)]
    if u == "deg":
        out.append("<p class='warn'>Coordinates are geographic (degrees): distances and densities are in "
                   "degrees and are not metric. Assign or transform to a projected CRS for metric analysis.</p>")
    out.append("<p class='muted'>Standard deviation and variance use the sample estimator (n-1). "
               "Skewness is the adjusted Fisher-Pearson coefficient.</p>")
    return "".join(out)


def qc_html(ds: PointDataset) -> str:
    rep = QCReport.from_dict(ds.qc_report)
    st = ds.import_settings
    src = ds.source
    out = [CSS, f"<h2>{html.escape(ds.name)} — data quality report</h2>"]
    out.append("<h3>Source</h3><table>")
    for k, v in (("File", src.path), ("Format", src.format.upper()), ("Size", f"{src.size_bytes:,} bytes"),
                 ("SHA-256", src.sha256), ("Modified", src.modified), ("Imported", ds.created)):
        out.append(f"<tr><th>{k}</th><td>{html.escape(str(v))}</td></tr>")
    ro = src.read_options
    delim = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe", "whitespace": "whitespace"}.get(
        ro.get("delimiter"), ro.get("delimiter") or "—")
    out.append(f"<tr><th>Read options</th><td>delimiter: {html.escape(str(delim))}, header: {ro.get('header')}, "
               f"decimal: '{ro.get('decimal')}', encoding: {ro.get('encoding') or '—'}, "
               f"sheet: {html.escape(str(ro.get('sheet') or '—'))}, skipped rows: {ro.get('skip_rows')}</td></tr>")
    out.append("</table>")
    out.append("<h3>Column mapping</h3><table>")
    for k in ("x_column", "y_column", "z_column"):
        out.append(f"<tr><th>{k[0].upper()}</th><td>{html.escape(str(st.get(k) or '—'))}</td></tr>")
    out.append(f"<tr><th>CRS</th><td>{html.escape(crs_label(ds.crs))}</td></tr>")
    out.append(f"<tr><th>Units</th><td>XY: {ds.xy_units}, Z: {ds.z_units}</td></tr>")
    out.append(f"<tr><th>Missing tokens</th><td>{html.escape(', '.join(repr(t) for t in st.get('missing_tokens', [])))}</td></tr>")
    out.append(f"<tr><th>NoData values</th><td>{html.escape(', '.join(str(v) for v in st.get('nodata_values', [])))}</td></tr>")
    out.append(f"<tr><th>Duplicate policy</th><td>{st.get('duplicate_policy')} (tolerance {st.get('duplicate_tolerance')})</td></tr>")
    out.append("</table><h3>Results</h3><ul>")
    for line in rep.summary_lines():
        cls = "warn" if line.startswith(("Warning", "Excluded")) else ""
        out.append(f"<li class='{cls}'>{html.escape(line)}</li>")
    out.append("</ul><p class='muted'>The source file was not modified. Excluded rows are listed by reason; "
               "the imported table keeps a <i>source_row</i> column linking each point to its source row.</p>")
    return "".join(out)


class DatasetDocument(QWidget):
    def __init__(self, ds: PointDataset, parent=None):
        super().__init__(parent)
        self.dataset_id = ds.id
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.model = DataFrameModel()
        self.table.setModel(self.model)
        self.table.verticalHeader().setDefaultSectionSize(22)
        self.tabs.addTab(self.table, "Table")

        self.preview = PointPreview()
        self.tabs.addTab(self.preview, "Point Preview")

        self.stats = QTextBrowser()
        self.tabs.addTab(self.stats, "Statistics")
        self.qc = QTextBrowser()
        self.tabs.addTab(self.qc, "Quality Report")
        self.refresh(ds)

    def refresh(self, ds: PointDataset) -> None:
        self.setWindowTitle(ds.name)
        self.model.set_frame(ds.data, highlight_columns=("X", "Y", "Z"))
        self.table.resizeColumnsToContents()
        self.preview.plot(
            ds.data["X"], ds.data["Y"], ds.data["Z"] if ds.has_z else None,
            title=f"{ds.name} — {ds.n_points:,} points", x_label=ds.x_label, y_label=ds.y_label,
            z_label=f"{ds.z_label} [{ds.z_units}]", units=ds.xy_units, crs_label=crs_label(ds.crs),
        )
        self.stats.setHtml(statistics_html(ds))
        self.qc.setHtml(qc_html(ds))
