"""Data import dialog: select files, preview, map X/Y/Z, CRS, units and QC.

Each selected file keeps its own settings. Every change re-runs the same
engine functions used for the final import, so what the user sees in the
preview (QC counts, excluded rows, point locations) is what will be imported.
For large files the preview and QC summary cover the first rows only, which
is stated in the dialog.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from geohydro.engine.crs import COMMON_CRS, UNDEFINED_CRS_LABEL, resolve_crs
from geohydro.engine.data.formats import file_dialog_filter
from geohydro.engine.data.importer import apply_crs, preview, qc_preview
from geohydro.engine.data.parsing import DEFAULT_MISSING_TOKENS, DEFAULT_NODATA_VALUES
from geohydro.engine.data.qc import DUPLICATE_POLICIES, ImportSettings
from geohydro.engine.data.readers import DELIMITER_NAMES, RawTable, ReadOptions, raw_text_preview
from geohydro.engine.errors import CRSError, GeoHydroError
from geohydro.engine.units import LENGTH_UNITS, Z_UNITS

from .. import icons, theme
from ..widgets.pandas_model import DataFrameModel
from ..widgets.point_preview import PointPreview

PREVIEW_ROWS = 2000
NONE_Z = "(none - XY only)"


@dataclass
class FileState:
    path: Path
    options: ReadOptions = field(default_factory=ReadOptions)
    settings: ImportSettings = field(default_factory=ImportSettings)
    crs_text: str = UNDEFINED_CRS_LABEL
    crs_error: str | None = None
    name: str = ""
    table: RawTable | None = None
    error: str | None = None
    qc = None
    initialised: bool = False


@dataclass
class ImportJob:
    path: Path
    options: ReadOptions
    settings: ImportSettings
    name: str


class ImportWizard(QDialog):
    def __init__(self, parent=None, paths=(), default_crs: str | None = None, start_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Import Point Data")
        self.setWindowIcon(icons.icon("import"))
        self.resize(1320, 820)
        self.default_crs = default_crs
        self.start_dir = start_dir
        self.states: list[FileState] = []
        self.current: FileState | None = None
        self.jobs: list[ImportJob] = []
        self._loading = False

        self._reread_timer = QTimer(self, singleShot=True, interval=200)
        self._reread_timer.timeout.connect(self._reread)
        self._qc_timer = QTimer(self, singleShot=True, interval=150)
        self._qc_timer.timeout.connect(self._recompute_qc)

        root = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split, 1)

        # ---- left: files + settings ---------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 6, 0)
        fg = QGroupBox("1  Input files")
        fl = QVBoxLayout(fg)
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(110)
        self.file_list.currentRowChanged.connect(self._select_file)
        fl.addWidget(self.file_list)
        fb = QHBoxLayout()
        b_add = QPushButton(icons.icon("import"), "Add files…")
        b_add.clicked.connect(self._browse)
        b_rm = QPushButton("Remove")
        b_rm.clicked.connect(self._remove_current)
        fb.addWidget(b_add)
        fb.addWidget(b_rm)
        fb.addStretch(1)
        fl.addLayout(fb)
        ll.addWidget(fg)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        form_host = QWidget()
        fh = QVBoxLayout(form_host)
        fh.setContentsMargins(0, 0, 0, 0)

        rg = QGroupBox("2  Read options")
        rf = QFormLayout(rg)
        self.fmt_label = QLabel("—")
        rf.addRow("Format:", self.fmt_label)
        self.delim = QComboBox()
        self.delim.addItem("Auto-detect", None)
        for k, v in DELIMITER_NAMES.items():
            self.delim.addItem(v, k)
        self.delim_info = QLabel("")
        rf.addRow("Delimiter:", self._pair(self.delim, self.delim_info))
        self.header = QComboBox()
        self.header.addItem("Auto-detect", "auto")
        self.header.addItem("First row is header", "yes")
        self.header.addItem("No header row", "no")
        self.header_info = QLabel("")
        rf.addRow("Header:", self._pair(self.header, self.header_info))
        self.skip = QSpinBox()
        self.skip.setRange(0, 100000)
        rf.addRow("Skip leading rows:", self.skip)
        self.comment = QLineEdit("#")
        self.comment.setMaximumWidth(60)
        rf.addRow("Comment prefix:", self.comment)
        self.decimal = QComboBox()
        self.decimal.addItem("Auto-detect", None)
        self.decimal.addItem("Point  ( . )", ".")
        self.decimal.addItem("Comma  ( , )", ",")
        self.decimal_info = QLabel("")
        rf.addRow("Decimal separator:", self._pair(self.decimal, self.decimal_info))
        self.encoding = QComboBox()
        for e in ("Auto-detect", "utf-8", "utf-8-sig", "cp1252", "latin-1"):
            self.encoding.addItem(e, None if e.startswith("Auto") else e)
        self.encoding_info = QLabel("")
        rf.addRow("Encoding:", self._pair(self.encoding, self.encoding_info))
        self.sheet = QComboBox()
        rf.addRow("Worksheet:", self.sheet)
        fh.addWidget(rg)

        mg = QGroupBox("3  Columns, coordinate system and units")
        mf = QFormLayout(mg)
        self.name_edit = QLineEdit()
        mf.addRow("Dataset name:", self.name_edit)
        self.xcol, self.ycol, self.zcol = QComboBox(), QComboBox(), QComboBox()
        mf.addRow("X column (Easting / Lon):", self.xcol)
        mf.addRow("Y column (Northing / Lat):", self.ycol)
        mf.addRow("Z column (value):", self.zcol)
        self.crs = QComboBox()
        self.crs.setEditable(True)
        self.crs.addItem(UNDEFINED_CRS_LABEL)
        for code, name in COMMON_CRS:
            self.crs.addItem(f"{code} - {name}")
        self.crs.setToolTip("Choose from the list or type any EPSG code, WKT or PROJ string. "
                            "The CRS is assigned as metadata; coordinates are not transformed.")
        mf.addRow("Coordinate system:", self.crs)
        self.crs_info = QLabel("")
        self.crs_info.setWordWrap(True)
        mf.addRow("", self.crs_info)
        self.xyu = QComboBox()
        for k, (n, _f) in LENGTH_UNITS.items():
            self.xyu.addItem(f"{k} ({n})", k)
        self.xyu.addItem("deg (degree)", "deg")
        mf.addRow("XY units:", self.xyu)
        self.zu = QComboBox()
        for k in Z_UNITS:
            self.zu.addItem(k, k)
        mf.addRow("Z units:", self.zu)
        fh.addWidget(mg)

        qg = QGroupBox("4  Quality control")
        qf = QFormLayout(qg)
        self.missing = QLineEdit(", ".join(t for t in DEFAULT_MISSING_TOKENS if t))
        self.missing.setToolTip("Comma-separated text values treated as missing. Blank cells are always missing.")
        qf.addRow("Missing value tokens:", self.missing)
        self.nodata = QLineEdit(", ".join(f"{v:g}" for v in DEFAULT_NODATA_VALUES))
        self.nodata.setToolTip("Comma-separated numeric sentinel values treated as NoData.")
        qf.addRow("NoData values:", self.nodata)
        self.excl_invalid = QCheckBox("Exclude rows with missing, non-numeric or NoData X/Y/Z")
        self.excl_invalid.setChecked(True)
        qf.addRow(self.excl_invalid)
        self.excl_range = QCheckBox("Exclude geographic coordinates outside ±180° / ±90°")
        self.excl_range.setChecked(True)
        qf.addRow(self.excl_range)
        self.dup = QComboBox()
        for k, v in DUPLICATE_POLICIES.items():
            self.dup.addItem(v, k)
        qf.addRow("Duplicate locations:", self.dup)
        self.tol = QDoubleSpinBox()
        self.tol.setDecimals(6)
        self.tol.setRange(0, 1e9)
        self.tol.setToolTip("Points closer than this distance (XY units) are treated as duplicates. 0 = identical.")
        qf.addRow("Duplicate tolerance:", self.tol)
        fh.addWidget(qg)
        fh.addStretch(1)
        scroll.setWidget(form_host)
        ll.addWidget(scroll, 1)
        split.addWidget(left)

        # ---- right: previews ------------------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        self.banner = QLabel("Add one or more files to begin.")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(f"padding:6px 8px;background:#E9EEF4;border-radius:4px;color:{theme.NAVY};")
        rl.addWidget(self.banner)
        self.tabs = QTabWidget()
        self.table = QTableView()
        self.table.setAlternatingRowColors(True)
        self.model = DataFrameModel()
        self.table.setModel(self.model)
        self.table.verticalHeader().setDefaultSectionSize(21)
        self.tabs.addTab(self.table, "Parsed preview")
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.raw.setStyleSheet("font-family:'DejaVu Sans Mono',Consolas,monospace;font-size:9pt;")
        self.tabs.addTab(self.raw, "Raw source")
        self.points = PointPreview(toolbar=False)
        self.tabs.addTab(self.points, "Point locations")
        self.qc_view = QTextBrowser()
        self.tabs.addTab(self.qc_view, "QC summary")
        rl.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([470, 850])

        btns = QDialogButtonBox()
        self.b_import_one = QPushButton("Import selected file")
        self.b_import_all = QPushButton("Import all files")
        self.b_import_all.setObjectName("Primary")
        btns.addButton(self.b_import_one, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(self.b_import_all, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(QDialogButtonBox.StandardButton.Cancel)
        btns.rejected.connect(self.reject)
        self.b_import_one.clicked.connect(lambda: self._accept(all_files=False))
        self.b_import_all.clicked.connect(lambda: self._accept(all_files=True))
        root.addWidget(btns)

        # signals
        for w in (self.delim, self.header, self.decimal, self.encoding, self.sheet):
            w.currentIndexChanged.connect(self._read_opts_changed)
        self.skip.valueChanged.connect(self._read_opts_changed)
        self.comment.editingFinished.connect(self._read_opts_changed)
        for w in (self.xcol, self.ycol, self.zcol, self.xyu, self.zu, self.dup):
            w.currentIndexChanged.connect(self._settings_changed)
        for w in (self.excl_invalid, self.excl_range):
            w.toggled.connect(self._settings_changed)
        self.tol.valueChanged.connect(self._settings_changed)
        self.missing.editingFinished.connect(self._settings_changed)
        self.nodata.editingFinished.connect(self._settings_changed)
        self.crs.currentTextChanged.connect(self._crs_changed)
        self.name_edit.textEdited.connect(self._name_changed)

        self._update_buttons()
        self.add_files(paths)

    # ---------------------------------------------------------------- utils
    @staticmethod
    def _pair(w, info):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(w, 1)
        info.setStyleSheet(f"color:{theme.MUTED};font-size:8.5pt;")
        h.addWidget(info)
        return box

    def add_files(self, paths) -> None:
        known = {s.path for s in self.states}
        for p in paths:
            p = Path(p).resolve()
            if p in known:
                continue
            st = FileState(path=p, name=p.stem)
            if self.default_crs:
                st.crs_text = self.default_crs
            self.states.append(st)
            it = QListWidgetItem(icons.icon("table"), p.name)
            it.setToolTip(str(p))
            self.file_list.addItem(it)
        # initialise every new file with auto-detected settings so that
        # "Import all" is possible after reviewing each file
        first_new = None
        for row, st in enumerate(self.states):
            if not st.initialised:
                first_new = row if first_new is None else first_new
                self.file_list.setCurrentRow(row)
        if first_new is not None:
            self.file_list.setCurrentRow(first_new)
        self._update_buttons()

    def _browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select data files", self.start_dir, file_dialog_filter())
        self.add_files(paths)

    def _remove_current(self):
        row = self.file_list.currentRow()
        if row < 0:
            return
        self.states.pop(row)
        self.file_list.takeItem(row)
        if not self.states:
            self.current = None
            self._show_empty()
        self._update_buttons()

    def _show_empty(self):
        self.banner.setText("Add one or more files to begin.")
        self.model.set_frame(pd.DataFrame())
        self.raw.clear()
        self.qc_view.clear()
        self.points.show_message("No data")

    # --------------------------------------------------------- file switch
    def _select_file(self, row: int):
        if row < 0 or row >= len(self.states):
            return
        self.current = self.states[row]
        st = self.current
        self._loading = True
        try:
            o = st.options
            self.fmt_label.setText(st.path.suffix.lower().lstrip(".").upper() or "text")
            self._set_combo_data(self.delim, o.delimiter)
            self._set_combo_data(self.header, o.header)
            self.skip.setValue(o.skip_rows)
            self.comment.setText(o.comment or "")
            self._set_combo_data(self.decimal, o.decimal)
            self._set_combo_data(self.encoding, o.encoding)
            self.sheet.clear()
            if st.table is not None and st.table.sheets:
                self.sheet.addItems(st.table.sheets)
                self.sheet.setCurrentText(st.table.options.sheet or "")
            self.name_edit.setText(st.name)
            self.crs.setCurrentText(st.crs_text)
        finally:
            self._loading = False
        try:
            self.raw.setPlainText(raw_text_preview(st.path, 60))
        except Exception as exc:  # noqa: BLE001
            self.raw.setPlainText(f"(cannot show raw text: {exc})")
        self._reread()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value):
        i = combo.findData(value)
        combo.setCurrentIndex(i if i >= 0 else 0)

    # ------------------------------------------------------------ reading
    def _read_opts_changed(self, *_):
        if self._loading or not self.current:
            return
        self._reread_timer.start()

    def _collect_read_options(self) -> ReadOptions:
        st = self.current
        o = ReadOptions(
            delimiter=self.delim.currentData(),
            header=self.header.currentData(),
            skip_rows=self.skip.value(),
            comment=self.comment.text().strip() or None,
            decimal=self.decimal.currentData(),
            encoding=self.encoding.currentData(),
            sheet=self.sheet.currentText() or None if st.path.suffix.lower() in (".xlsx", ".xlsm") else None,
        )
        return o

    def _reread(self):
        st = self.current
        if st is None:
            return
        if st.initialised:
            opts = self._collect_read_options()
        else:
            opts = ReadOptions(comment=self.comment.text().strip() or "#")
        st.options = opts
        try:
            table, suggested = preview(st.path, opts, max_rows=PREVIEW_ROWS)
        except GeoHydroError as exc:
            st.table, st.error = None, str(exc)
            self._show_error(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - unexpected parser failures
            st.table, st.error = None, f"Unexpected error reading file: {exc}"
            self._show_error(st.error)
            return
        st.table, st.error = table, None
        r = table.options
        self._loading = True
        try:
            self.delim_info.setText(f"detected: {DELIMITER_NAMES.get(r.delimiter, '—')}" if r.delimiter else "")
            self.header_info.setText(f"→ {'header' if r.header == 'yes' else 'no header'}")
            self.decimal_info.setText(f"→ '{r.decimal}'")
            self.encoding_info.setText(f"→ {r.encoding}" if r.encoding else "")
            is_xlsx = table.source_format == "xlsx"
            self.sheet.setEnabled(is_xlsx)
            self.sheet.clear()
            if is_xlsx:
                self.sheet.addItems(table.sheets)
                self.sheet.setCurrentText(r.sheet or "")
            for w in (self.delim, self.decimal, self.encoding):
                w.setEnabled(not is_xlsx)
            cols = table.columns
            prev = st.settings
            keep = prev.x_column in cols and prev.y_column in cols and st.initialised
            for combo in (self.xcol, self.ycol):
                combo.clear()
                combo.addItems(cols)
            self.zcol.clear()
            self.zcol.addItem(NONE_Z)
            self.zcol.addItems(cols)
            src = prev if keep else suggested
            if not keep:
                st.settings = ImportSettings(
                    x_column=suggested.x_column, y_column=suggested.y_column, z_column=suggested.z_column)
            self.xcol.setCurrentText(src.x_column or "")
            self.ycol.setCurrentText(src.y_column or "")
            self.zcol.setCurrentText(src.z_column or NONE_Z)
            s = st.settings
            self._set_combo_data(self.xyu, s.xy_units)
            self._set_combo_data(self.zu, s.z_units)
            self._set_combo_data(self.dup, s.duplicate_policy)
            self.tol.setValue(s.duplicate_tolerance)
            self.excl_invalid.setChecked(s.exclude_invalid)
            self.excl_range.setChecked(s.exclude_out_of_range)
            st.initialised = True
        finally:
            self._loading = False
        self._crs_changed(self.crs.currentText(), recompute=False)
        self._recompute_qc()

    def _show_error(self, msg: str):
        self.banner.setText(f"<span style='color:{theme.ERROR}'><b>Cannot read file:</b> {msg}</span>")
        self.model.set_frame(pd.DataFrame())
        self.qc_view.setHtml(f"<p style='color:{theme.ERROR}'>{msg}</p>")
        self.points.show_message("No preview available")
        self._update_buttons()

    # ------------------------------------------------------------ settings
    def _settings_changed(self, *_):
        if self._loading or not self.current or self.current.table is None:
            return
        self._qc_timer.start()

    def _name_changed(self, text):
        if self.current:
            self.current.name = text.strip()
            self._update_buttons()

    def _crs_changed(self, text, recompute=True):
        st = self.current
        if st is None or self._loading:
            return
        st.crs_text = text
        try:
            info = resolve_crs(text)
            st.crs_error = None
            if info is None:
                self.crs_info.setText(f"<span style='color:{theme.WARNING}'>No CRS assigned. Coordinates will be "
                                      "treated as local engineering coordinates.</span>")
            else:
                kind = "geographic" if info.is_geographic else "projected" if info.is_projected else "other"
                self.crs_info.setText(f"<span style='color:{theme.SUCCESS}'>✓ {info.display}</span>"
                                      f"<br><span style='color:{theme.MUTED}'>{kind}, axis unit: {info.axis_unit}</span>")
                unit = "deg" if info.is_geographic else ("m" if info.is_metric else None)
                if unit:
                    self._loading = True
                    self._set_combo_data(self.xyu, unit)
                    self._loading = False
        except CRSError as exc:
            st.crs_error = str(exc)
            self.crs_info.setText(f"<span style='color:{theme.ERROR}'>✗ {exc}</span>")
        if recompute:
            self._qc_timer.start()
        self._update_buttons()

    def _collect_settings(self) -> ImportSettings:
        st = self.current
        z = self.zcol.currentText()
        s = ImportSettings(
            x_column=self.xcol.currentText() or None,
            y_column=self.ycol.currentText() or None,
            z_column=None if z == NONE_Z or not z else z,
            xy_units=self.xyu.currentData(),
            z_units=self.zu.currentData(),
            missing_tokens=[""] + [t.strip() for t in self.missing.text().split(",") if t.strip()],
            nodata_values=self._parse_nodata(),
            exclude_invalid=self.excl_invalid.isChecked(),
            exclude_out_of_range=self.excl_range.isChecked(),
            duplicate_policy=self.dup.currentData(),
            duplicate_tolerance=float(self.tol.value()),
        )
        if st.crs_error is None:
            apply_crs(s, st.crs_text)
            s.xy_units = self.xyu.currentData() if not s.crs_is_geographic else "deg"
        return s

    def _parse_nodata(self) -> list[float]:
        vals = []
        bad = []
        for t in self.nodata.text().split(","):
            t = t.strip()
            if not t:
                continue
            try:
                vals.append(float(t))
            except ValueError:
                bad.append(t)
        self.nodata.setStyleSheet(f"border-color:{theme.ERROR};" if bad else "")
        return vals

    def _recompute_qc(self):
        st = self.current
        if st is None or st.table is None:
            return
        st.settings = self._collect_settings()
        t = st.table
        try:
            res = qc_preview(t, st.settings)
        except GeoHydroError as exc:
            st.qc = None
            self.banner.setText(f"<span style='color:{theme.ERROR}'><b>Column mapping:</b> {exc}</span>")
            self.model.set_frame(t.frame)
            self.qc_view.setHtml(f"<p style='color:{theme.ERROR}'>{exc}</p>")
            self.points.show_message("Select valid X and Y columns")
            self._update_buttons()
            return
        st.qc = res
        rep = res.report
        status = res.row_status.to_numpy()
        self.model.set_frame(t.frame, highlight_columns=[c for c in (st.settings.x_column, st.settings.y_column,
                                                                      st.settings.z_column) if c],
                             row_status=status)
        self.table.resizeColumnsToContents()
        scope = (f"first {len(t.frame):,} of {t.total_data_rows:,} rows (preview)"
                 if t.truncated else f"all {t.total_data_rows:,} rows")
        colour = theme.SUCCESS if rep.imported_rows and not rep.excluded_rows else theme.WARNING
        if rep.imported_rows == 0:
            colour = theme.ERROR
        self.banner.setText(
            f"<b>{st.path.name}</b> · {len(t.columns)} columns · QC on {scope}: "
            f"<span style='color:{colour}'><b>{rep.imported_rows:,}</b> rows usable, "
            f"<b>{rep.excluded_rows:,}</b> excluded</span>"
            + (f" · {rep.duplicate_groups} duplicate location group(s)" if rep.duplicate_groups else "")
            + ("<br><span style='color:%s'>%s</span>" % (theme.WARNING, "; ".join(t.warnings)) if t.warnings else "")
        )
        lines = "".join(
            f"<li style='color:{theme.WARNING if l.startswith(('Warning', 'Excluded')) else theme.TEXT}'>{l}</li>"
            for l in rep.summary_lines()
        )
        reasons = {}
        for s_ in status:
            if s_ != "ok":
                reasons[s_] = reasons.get(s_, 0) + 1
        excluded_rows = [f"row {i + 1}: {s_}" for i, s_ in enumerate(status) if s_ != "ok"][:50]
        self.qc_view.setHtml(
            f"<h3 style='color:{theme.NAVY}'>Quality control summary</h3>"
            f"<p style='color:{theme.MUTED}'>Computed on {scope}.</p><ul>{lines}</ul>"
            + (f"<h4>Excluded rows (first 50)</h4><p style='font-family:monospace'>{'<br>'.join(excluded_rows)}</p>"
               if excluded_rows else "")
        )
        d = res.data
        if len(d):
            excl_mask = status != "ok"
            ex_xy = None
            if excl_mask.any():
                from geohydro.engine.data.parsing import parse_numeric
                px = parse_numeric(t.frame[st.settings.x_column], t.options.decimal or ".").values[excl_mask]
                py = parse_numeric(t.frame[st.settings.y_column], t.options.decimal or ".").values[excl_mask]
                okk = np.isfinite(px) & np.isfinite(py)
                ex_xy = (px[okk], py[okk])
            self.points.plot(d["X"], d["Y"], d["Z"] if "Z" in d else None, title=st.name or st.path.stem,
                             x_label=st.settings.x_column, y_label=st.settings.y_column,
                             z_label=f"{st.settings.z_column or ''} [{st.settings.z_units}]",
                             units=st.settings.xy_units, excluded_xy=ex_xy)
        else:
            self.points.show_message("No valid points after quality control")
        self._update_buttons()

    # ------------------------------------------------------------- accept
    def _state_ready(self, st: FileState) -> bool:
        return (st.table is not None and st.error is None and st.crs_error is None and st.qc is not None
                and st.qc.report.imported_rows > 0 and bool(st.name))

    def _update_buttons(self):
        cur_ok = self.current is not None and self._state_ready(self.current)
        self.b_import_one.setEnabled(cur_ok)
        all_ok = bool(self.states) and all(self._state_ready(s) for s in self.states)
        self.b_import_all.setEnabled(all_ok)
        self.b_import_all.setText(f"Import all files ({len(self.states)})" if self.states else "Import all files")
        bad = [s.path.name for s in self.states if not self._state_ready(s)]
        self.b_import_all.setToolTip("Not ready: " + ", ".join(bad) if bad else "")

    def _accept(self, all_files: bool):
        targets = self.states if all_files else [self.current]
        self.jobs = [ImportJob(s.path, s.options, s.settings, s.name or s.path.stem)
                     for s in targets if s is not None and self._state_ready(s)]
        if self.jobs:
            self.accept()
