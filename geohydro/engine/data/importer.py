"""High-level point import pipeline: read -> map columns -> QC -> dataset.

This is the function both the desktop wizard and the (planned) web upload
endpoint call, guaranteeing identical results on every platform.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..crs import crs_storage_string, resolve_crs
from .columns import guess_xyz
from .dataset import PointDataset, SourceInfo
from .qc import ImportSettings, QCResult, run_qc
from .readers import RawTable, ReadOptions, read_table

log = logging.getLogger("geohydro.engine.import")


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def suggest_settings(table: RawTable) -> ImportSettings:
    x, y, z = guess_xyz(table.frame, table.options.decimal or ".")
    return ImportSettings(x_column=x, y_column=y, z_column=z)


def apply_crs(settings: ImportSettings, crs_text: str | None) -> ImportSettings:
    """Validate a CRS string and store its canonical form in ``settings``."""
    info = resolve_crs(crs_text)
    settings.crs = crs_storage_string(info)
    settings.crs_is_geographic = bool(info and info.is_geographic)
    if info and info.is_geographic:
        settings.xy_units = "deg"
    elif settings.xy_units == "deg":
        settings.xy_units = "m"
    return settings


def preview(path: str | Path, options: ReadOptions | None = None, max_rows: int = 1000):
    """Read up to ``max_rows`` rows and return ``(table, suggested_settings)``."""
    opts = ReadOptions(**(options.to_dict() if options else {}))
    opts.max_rows = max_rows
    table = read_table(path, opts)
    return table, suggest_settings(table)


def qc_preview(table: RawTable, settings: ImportSettings) -> QCResult:
    res = run_qc(table.frame, settings, table.options.decimal or ".")
    res.report.preview_only = table.truncated
    return res


def import_point_file(
    path: str | Path,
    options: ReadOptions | None = None,
    settings: ImportSettings | None = None,
    name: str | None = None,
) -> PointDataset:
    path = Path(path).resolve()
    opts = ReadOptions(**(options.to_dict() if options else {}))
    opts.max_rows = None
    log.info("Reading %s", path.name)
    table = read_table(path, opts)
    if settings is None:
        settings = suggest_settings(table)
    res = run_qc(table.frame, settings, table.options.decimal or ".")
    for w in table.warnings:
        res.report.warnings.insert(0, w)
    st = path.stat()
    source = SourceInfo(
        path=str(path),
        format=table.source_format,
        sha256=file_sha256(path),
        size_bytes=st.st_size,
        modified=datetime.fromtimestamp(st.st_mtime, timezone.utc).replace(microsecond=0).isoformat(),
        read_options=table.options.to_dict(),
    )
    ds = PointDataset(
        name=name or path.stem,
        data=res.data,
        source=source,
        import_settings=settings.to_dict(),
        qc_report=res.report.to_dict(),
        crs=settings.crs,
        xy_units=settings.xy_units,
        z_units=settings.z_units,
        x_label=settings.x_column or "X",
        y_label=settings.y_column or "Y",
        z_label=settings.z_column or "Z",
    )
    log.info(
        "Imported %s: %d of %d rows (%d excluded)",
        ds.name, res.report.imported_rows, res.report.source_rows, res.report.excluded_rows,
    )
    for w in res.report.warnings:
        log.warning("%s: %s", ds.name, w)
    return ds
