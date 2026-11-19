"""Import quality control: missing values, invalid values, NoData sentinels,
duplicate coordinates and coordinate range checks.

Every excluded or modified row is counted and explained in a
:class:`QCReport`. With default settings nothing is changed except that rows
without usable X/Y/Z numbers are excluded (they cannot be used in any spatial
calculation). Duplicates are *reported* but kept unless the user selects a
policy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from ..errors import ColumnMappingError
from .parsing import DEFAULT_MISSING_TOKENS, DEFAULT_NODATA_VALUES, parse_numeric

DUPLICATE_POLICIES = {
    "keep_all": "Keep all (report only)",
    "keep_first": "Keep first occurrence",
    "mean": "Merge: keep first location, average Z",
}

RESERVED = ("X", "Y", "Z", "source_row")


@dataclass
class ImportSettings:
    x_column: str | None = None
    y_column: str | None = None
    z_column: str | None = None  # optional: XY-only point sets are allowed
    crs: str | None = None  # canonical storage string or None (undefined)
    crs_is_geographic: bool = False
    xy_units: str = "m"
    z_units: str = "m"
    missing_tokens: list[str] = field(default_factory=lambda: list(DEFAULT_MISSING_TOKENS))
    nodata_values: list[float] = field(default_factory=lambda: list(DEFAULT_NODATA_VALUES))
    exclude_invalid: bool = True  # rows with missing/invalid/NoData X, Y or Z
    exclude_out_of_range: bool = True  # geographic coordinates outside valid range
    duplicate_policy: str = "keep_all"
    duplicate_tolerance: float = 0.0  # in XY units; 0 = exact match

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ImportSettings":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class QCReport:
    source_rows: int = 0
    imported_rows: int = 0
    excluded_rows: int = 0
    missing: dict = field(default_factory=dict)  # column -> count
    invalid: dict = field(default_factory=dict)
    nodata: dict = field(default_factory=dict)
    out_of_range: int = 0
    duplicate_groups: int = 0
    duplicate_rows: int = 0  # rows belonging to a duplicate group (incl. first)
    duplicate_z_conflicts: int = 0  # groups whose Z values differ
    duplicates_removed: int = 0
    exclusions: dict = field(default_factory=dict)  # reason -> count
    warnings: list[str] = field(default_factory=list)
    preview_only: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "QCReport":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @property
    def ok(self) -> bool:
        return self.imported_rows > 0

    def summary_lines(self) -> list[str]:
        lines = [
            f"Source rows: {self.source_rows}",
            f"Rows imported: {self.imported_rows}",
            f"Rows excluded: {self.excluded_rows}",
        ]
        for label, d in (("Missing", self.missing), ("Non-numeric", self.invalid), ("NoData", self.nodata)):
            nz = {k: v for k, v in d.items() if v}
            if nz:
                lines.append(f"{label}: " + ", ".join(f"{k}={v}" for k, v in nz.items()))
        if self.out_of_range:
            lines.append(f"Coordinates out of geographic range: {self.out_of_range}")
        if self.duplicate_groups:
            lines.append(
                f"Duplicate locations: {self.duplicate_groups} group(s), {self.duplicate_rows} rows"
                f" ({self.duplicate_z_conflicts} with differing Z); removed {self.duplicates_removed}"
            )
        else:
            lines.append("Duplicate locations: none")
        for reason, n in self.exclusions.items():
            lines.append(f"Excluded - {reason}: {n}")
        lines.extend(f"Warning: {w}" for w in self.warnings)
        return lines


@dataclass
class QCResult:
    data: pd.DataFrame  # X, Y, Z(optional), source_row, attributes...
    report: QCReport
    row_status: pd.Series  # per source row: "ok" or exclusion reason


def _duplicate_groups(x: np.ndarray, y: np.ndarray, tol: float) -> np.ndarray:
    """Group label per point; points sharing a label are duplicates."""
    n = len(x)
    if n == 0:
        return np.zeros(0, dtype=int)
    if tol <= 0:
        key = pd.MultiIndex.from_arrays([x, y])
        return pd.factorize(key)[0]
    tree = cKDTree(np.column_stack([x, y]))
    pairs = tree.query_pairs(r=tol, output_type="ndarray")
    if len(pairs) == 0:
        return np.arange(n)
    m = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    _, labels = connected_components(m, directed=False)
    return labels


def _maybe_numeric(s: pd.Series) -> pd.Series:
    txt = s.astype(str).str.strip()
    nonblank = txt != ""
    conv = pd.to_numeric(txt.where(nonblank, None), errors="coerce")
    if nonblank.any() and conv[nonblank].notna().all():
        return conv.astype(float)
    return s.astype(str)


def run_qc(frame: pd.DataFrame, settings: ImportSettings, decimal: str = ".") -> QCResult:
    cols = [str(c) for c in frame.columns]
    for role, col in (("X", settings.x_column), ("Y", settings.y_column)):
        if not col:
            raise ColumnMappingError(f"No {role} column selected")
        if col not in cols:
            raise ColumnMappingError(f"{role} column {col!r} not found in data")
    if settings.z_column and settings.z_column not in cols:
        raise ColumnMappingError(f"Z column {settings.z_column!r} not found in data")
    chosen = [c for c in (settings.x_column, settings.y_column, settings.z_column) if c]
    if len(set(chosen)) != len(chosen):
        raise ColumnMappingError("X, Y and Z must be different columns")
    if settings.duplicate_policy not in DUPLICATE_POLICIES:
        raise ValueError(f"Unknown duplicate policy {settings.duplicate_policy!r}")

    n = len(frame)
    rep = QCReport(source_rows=n)
    status = np.array(["ok"] * n, dtype=object)

    parsed = {}
    for role, col in (("X", settings.x_column), ("Y", settings.y_column), ("Z", settings.z_column)):
        if not col:
            continue
        p = parse_numeric(frame[col], decimal, settings.missing_tokens, settings.nodata_values)
        parsed[role] = p
        rep.missing[col] = int(p.missing.sum())
        rep.invalid[col] = int(p.invalid.sum())
        rep.nodata[col] = int(p.nodata.sum())

    bad = np.zeros(n, dtype=bool)
    if settings.exclude_invalid:
        for role, p in parsed.items():
            col = {"X": settings.x_column, "Y": settings.y_column, "Z": settings.z_column}[role]
            for mask, reason in (
                (p.missing, f"missing {role} ({col})"),
                (p.invalid, f"non-numeric {role} ({col})"),
                (p.nodata, f"NoData {role} ({col})"),
            ):
                new = mask & ~bad
                if new.any():
                    rep.exclusions[reason] = int(new.sum())
                    status[new] = reason
                bad |= mask
    else:
        unusable = np.zeros(n, dtype=bool)
        for p in parsed.values():
            unusable |= np.isnan(p.values)
        if unusable.any():
            rep.warnings.append(
                f"{int(unusable.sum())} row(s) have missing/invalid coordinates or Z but were kept as NaN"
            )

    x = parsed["X"].values
    y = parsed["Y"].values
    if settings.crs_is_geographic:
        oor = (~np.isnan(x) & ((x < -180) | (x > 360))) | (~np.isnan(y) & ((y < -90) | (y > 90)))
        rep.out_of_range = int(oor.sum())
        if settings.exclude_out_of_range:
            new = oor & ~bad
            if new.any():
                rep.exclusions["outside geographic range"] = int(new.sum())
                status[new] = "outside geographic range"
            bad |= oor
    elif settings.crs is None:
        if np.nanmax(np.abs(np.concatenate([x[~np.isnan(x)], y[~np.isnan(y)], [0.0]]))) <= 180:
            rep.warnings.append("No CRS assigned; coordinates are within +/-180 and may be geographic degrees")

    keep = ~bad
    out = pd.DataFrame({"X": x[keep], "Y": y[keep]})
    if "Z" in parsed:
        out["Z"] = parsed["Z"].values[keep]
    out["source_row"] = np.arange(1, n + 1)[keep]
    for c in cols:
        if c in chosen:
            continue
        name = c if c not in RESERVED else f"attr_{c}"
        out[name] = _maybe_numeric(frame[c].iloc[np.flatnonzero(keep)].reset_index(drop=True))
    out = out.reset_index(drop=True)

    # duplicates (on rows with finite coordinates)
    fin = np.isfinite(out["X"].to_numpy()) & np.isfinite(out["Y"].to_numpy())
    idx = np.flatnonzero(fin)
    if len(idx):
        labels = _duplicate_groups(
            out["X"].to_numpy()[idx], out["Y"].to_numpy()[idx], float(settings.duplicate_tolerance)
        )
        sizes = np.bincount(labels)
        dup_lab = np.flatnonzero(sizes > 1)
        rep.duplicate_groups = int(len(dup_lab))
        rep.duplicate_rows = int(sizes[dup_lab].sum())
        if "Z" in out and len(dup_lab):
            zz = out["Z"].to_numpy()[idx]
            g = pd.Series(zz).groupby(labels)
            spread = (g.max() - g.min()).reindex(dup_lab)
            rep.duplicate_z_conflicts = int((spread > 0).sum())
        if len(dup_lab) and settings.duplicate_policy != "keep_all":
            first_mask = ~pd.Series(labels).duplicated().to_numpy()
            drop_local = idx[~first_mask]
            if settings.duplicate_policy == "mean" and "Z" in out:
                zz = out["Z"].to_numpy()[idx]
                means = pd.Series(zz).groupby(labels).transform("mean").to_numpy()
                out.loc[idx[first_mask], "Z"] = means[first_mask]
            rep.duplicates_removed = int(len(drop_local))
            status_rows = out.loc[drop_local, "source_row"].to_numpy() - 1
            status[status_rows] = "duplicate location"
            out = out.drop(index=drop_local).reset_index(drop=True)
        elif len(dup_lab):
            rep.warnings.append(
                "Duplicate locations kept; most gridding methods require unique locations"
            )

    rep.imported_rows = int(len(out))
    rep.excluded_rows = int(n - len(out))
    if rep.imported_rows == 0:
        rep.warnings.append("No valid rows remain after quality control")
    return QCResult(out, rep, pd.Series(status, name="status"))
