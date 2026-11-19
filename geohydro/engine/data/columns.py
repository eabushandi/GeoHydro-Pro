"""Heuristic X/Y/Z column suggestion. The user always confirms the choice."""

from __future__ import annotations

import re

import pandas as pd

from .parsing import column_numeric_fraction

_X = ("x", "easting", "east", "e", "lon", "long", "longitude", "xcoord", "x_coord", "utm_e", "utme")
_Y = ("y", "northing", "north", "n", "lat", "latitude", "ycoord", "y_coord", "utm_n", "utmn")
_Z = (
    "z", "elevation", "elev", "height", "altitude", "alt", "value", "depth", "head",
    "water_level", "waterlevel", "wl", "gwl", "level", "concentration", "conc", "tds", "zcoord",
    "z_coord", "bathymetry", "dem", "rl",
)


def _norm(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r"\(.*?\)|\[.*?\]", "", n)  # drop "(m)" "[m]"
    n = re.sub(r"[^a-z0-9]+", "_", n).strip("_")
    return n


def _match(name: str, candidates) -> float:
    """Return match quality: 3 exact, 2.5 multi-word prefix, 2 first token, 1 any token, 0 none."""
    n = _norm(name)
    if n in candidates:
        return 3
    if any("_" in c and n.startswith(c) for c in candidates):
        return 2.5
    tokens = n.split("_")
    if tokens and tokens[0] in candidates:
        return 2
    if any(t in candidates and len(t) > 1 for t in tokens):
        return 1
    return 0


def guess_xyz(frame: pd.DataFrame, decimal: str = ".") -> tuple[str | None, str | None, str | None]:
    cols = [str(c) for c in frame.columns]
    numeric = [c for c in cols if column_numeric_fraction(frame[c].head(200), decimal) >= 0.8]

    def pick(cands, exclude):
        best, best_q = None, 0
        for c in numeric:
            if c in exclude:
                continue
            q = _match(c, cands)
            if q > best_q:
                best, best_q = c, q
        return best

    x = pick(_X, set())
    y = pick(_Y, {x})
    z = pick(_Z, {x, y})
    remaining = [c for c in numeric if c not in {x, y, z}]
    if x is None and remaining:
        x = remaining.pop(0)
    if y is None and remaining:
        y = remaining.pop(0)
    if z is None and remaining:
        z = remaining.pop(0)
    return x, y, z
