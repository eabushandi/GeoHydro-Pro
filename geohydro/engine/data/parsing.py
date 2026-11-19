"""Low-level parsing helpers: numeric conversion and missing value tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_MISSING_TOKENS = ("", "NA", "N/A", "NaN", "nan", "NULL", "null", "None", "-", "*", "#N/A")
DEFAULT_NODATA_VALUES = (-9999.0, -99999.0, 1.70141e38)

_NUMBER_RE = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$")


def looks_numeric(text: str, decimal: str = ".") -> bool:
    t = str(text).strip()
    if not t:
        return False
    if decimal == ".":
        t2 = t
        if "," in t2:
            return False
    else:
        if "." in t and "," in t:
            return False
        t2 = t
    if _NUMBER_RE.match(t2):
        return True
    return t.lower() in ("inf", "-inf", "+inf", "nan")


@dataclass
class NumericParse:
    values: np.ndarray  # float64, NaN where missing/invalid
    missing: np.ndarray  # bool: blank or missing token
    invalid: np.ndarray  # bool: present but not a number (or infinite)
    nodata: np.ndarray  # bool: numeric but equal to a NoData sentinel


def parse_numeric(
    series: pd.Series,
    decimal: str = ".",
    missing_tokens=DEFAULT_MISSING_TOKENS,
    nodata_values=DEFAULT_NODATA_VALUES,
) -> NumericParse:
    """Convert a column of raw values to float with explicit diagnostics.

    The source values are not modified; masks explain every NaN produced.
    """
    raw = series.astype(object)
    as_text = raw.map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else str(v).strip())
    tokens = {str(t).strip() for t in missing_tokens}
    missing = as_text.isin(tokens).to_numpy()

    text = as_text
    if decimal == ",":
        text = text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    values = pd.to_numeric(text.where(~missing, None), errors="coerce").to_numpy(dtype=float, copy=True)
    infinite = np.isinf(values)
    values[infinite] = np.nan
    invalid = np.isnan(values) & ~missing

    nodata = np.zeros(len(values), dtype=bool)
    for nd in nodata_values or ():
        nd = float(nd)
        tol = abs(nd) * 1e-9
        nodata |= np.isclose(values, nd, rtol=0.0, atol=tol) & ~np.isnan(values)
    values = values.copy()
    values[nodata] = np.nan
    return NumericParse(values=values, missing=missing, invalid=invalid, nodata=nodata)


def column_numeric_fraction(series: pd.Series, decimal: str = ".") -> float:
    vals = [str(v).strip() for v in series if str(v).strip() != ""]
    if not vals:
        return 0.0
    return sum(looks_numeric(v, decimal) for v in vals) / len(vals)
