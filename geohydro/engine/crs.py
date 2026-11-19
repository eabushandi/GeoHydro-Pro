"""Coordinate reference system handling (thin wrapper around PyProj).

Phase 1 *assigns* a CRS to imported coordinates (metadata). It never silently
reprojects data. Explicit transformations are available through
:func:`transform_points` and are always a user-initiated action.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import CRSError

try:  # pyproj is a hard dependency, but keep import errors readable
    from pyproj import CRS, Transformer
    from pyproj.exceptions import CRSError as _PyprojCRSError
except ImportError as exc:  # pragma: no cover
    raise ImportError("pyproj is required: pip install pyproj") from exc


# A short, curated list for quick selection. Any EPSG code / WKT / PROJ
# string accepted by PyProj can also be typed by the user.
COMMON_CRS: list[tuple[str, str]] = [
    ("EPSG:4326", "WGS 84 (geographic, degrees)"),
    ("EPSG:3857", "WGS 84 / Pseudo-Mercator"),
    ("EPSG:32637", "WGS 84 / UTM zone 37N"),
    ("EPSG:32638", "WGS 84 / UTM zone 38N"),
    ("EPSG:32639", "WGS 84 / UTM zone 39N"),
    ("EPSG:32640", "WGS 84 / UTM zone 40N"),
    ("EPSG:20439", "Ain el Abd / UTM zone 39N"),
    ("EPSG:32633", "WGS 84 / UTM zone 33N"),
    ("EPSG:27700", "OSGB36 / British National Grid"),
    ("EPSG:3035", "ETRS89 / LAEA Europe"),
]

UNDEFINED_CRS_LABEL = "Undefined (local / engineering coordinates)"


@dataclass(frozen=True)
class CRSInfo:
    user_input: str
    name: str
    authority: str | None  # e.g. "EPSG:32639"
    is_geographic: bool
    is_projected: bool
    axis_unit: str  # e.g. "metre", "degree"
    wkt: str

    @property
    def display(self) -> str:
        return f"{self.authority} - {self.name}" if self.authority else self.name

    @property
    def is_metric(self) -> bool:
        return self.axis_unit in ("metre", "meter", "m")


def resolve_crs(text: str | None) -> CRSInfo | None:
    """Parse a CRS definition. Returns ``None`` for an undefined CRS.

    Raises :class:`CRSError` if the text is not understood by PyProj.
    """
    if text is None:
        return None
    text = text.strip()
    if not text or text.lower().startswith("undefined") or text.lower() in ("none", "local"):
        return None
    # allow "32639" as a shorthand for EPSG:32639
    candidate = f"EPSG:{text}" if text.isdigit() else text
    # allow "EPSG:32639 - description" as produced by the UI combo box
    if " - " in candidate and candidate.upper().startswith("EPSG:"):
        candidate = candidate.split(" - ", 1)[0].strip()
    try:
        crs = CRS.from_user_input(candidate)
    except (_PyprojCRSError, ValueError, TypeError) as exc:
        raise CRSError(f"Unrecognised coordinate reference system: {text!r}") from exc

    auth = crs.to_authority()
    authority = f"{auth[0]}:{auth[1]}" if auth else None
    unit = "unknown"
    if crs.axis_info:
        unit = crs.axis_info[0].unit_name or "unknown"
    return CRSInfo(
        user_input=text,
        name=crs.name,
        authority=authority,
        is_geographic=crs.is_geographic,
        is_projected=crs.is_projected,
        axis_unit=unit,
        wkt=crs.to_wkt(pretty=True),
    )


def crs_storage_string(info: CRSInfo | None) -> str | None:
    """Canonical string to store in projects: authority code, else WKT."""
    if info is None:
        return None
    return info.authority or info.wkt


def transform_points(x, y, source: str, target: str):
    """Transform coordinates between two CRSs (always_xy axis order)."""
    src = resolve_crs(source)
    dst = resolve_crs(target)
    if src is None or dst is None:
        raise CRSError("Both source and target CRS must be defined to transform coordinates")
    tr = Transformer.from_crs(
        crs_storage_string(src), crs_storage_string(dst), always_xy=True
    )
    xo, yo = tr.transform(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    return np.asarray(xo), np.asarray(yo)
