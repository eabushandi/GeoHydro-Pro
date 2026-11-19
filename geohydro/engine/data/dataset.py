"""In-memory dataset model shared by desktop, storage and (planned) web."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from .statistics import describe, spatial_summary


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class SourceInfo:
    path: str  # absolute path at import time
    format: str
    sha256: str
    size_bytes: int
    modified: str  # file mtime (UTC ISO)
    read_options: dict = field(default_factory=dict)


@dataclass
class PointDataset:
    """A set of observation points with X, Y and optionally Z.

    ``data`` columns: ``X``, ``Y``, optional ``Z``, ``source_row`` (1-based
    data row in the source file) followed by any other source columns.
    """

    name: str
    data: pd.DataFrame
    source: SourceInfo
    import_settings: dict
    qc_report: dict
    crs: str | None = None
    xy_units: str = "m"
    z_units: str = "m"
    z_label: str = "Z"  # original name of the Z column
    x_label: str = "X"
    y_label: str = "Y"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    kind: str = "points"
    created: str = field(default_factory=utc_now)
    notes: str = ""

    @property
    def has_z(self) -> bool:
        return "Z" in self.data.columns

    @property
    def n_points(self) -> int:
        return int(len(self.data))

    @property
    def attribute_columns(self) -> list[str]:
        return [c for c in self.data.columns if c not in ("X", "Y", "Z", "source_row")]

    def z_statistics(self) -> dict:
        return describe(self.data["Z"]) if self.has_z else {"count": 0}

    def spatial_statistics(self) -> dict:
        return spatial_summary(self.data["X"], self.data["Y"])

    def extent(self) -> tuple[float, float, float, float] | None:
        s = self.spatial_statistics()
        if not s.get("count"):
            return None
        return s["x_min"], s["x_max"], s["y_min"], s["y_max"]
