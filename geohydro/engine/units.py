"""Measurement units. Metric (metre) is the default everywhere.

Conversion factors are exact by definition:
  * international foot = 0.3048 m (1959 agreement)
  * US survey foot     = 1200/3937 m
"""

from __future__ import annotations

import numpy as np

from .errors import UnitError

DEFAULT_LENGTH_UNIT = "m"

# unit code -> (display name, metres per unit)
LENGTH_UNITS: dict[str, tuple[str, float]] = {
    "m": ("metre", 1.0),
    "km": ("kilometre", 1000.0),
    "cm": ("centimetre", 0.01),
    "mm": ("millimetre", 0.001),
    "ft": ("foot (international)", 0.3048),
    "us-ft": ("US survey foot", 1200.0 / 3937.0),
}

ANGULAR_UNITS: dict[str, tuple[str, float]] = {
    "deg": ("degree", 1.0),
}

ALL_UNITS = {**LENGTH_UNITS, **ANGULAR_UNITS}

# Z values are not always lengths (concentrations, TDS, temperature ...).
# "other" means the quantity has no convertible unit in the engine.
Z_UNITS = list(LENGTH_UNITS) + ["mg/L", "ppm", "degC", "other"]


def unit_name(code: str) -> str:
    if code in ALL_UNITS:
        return ALL_UNITS[code][0]
    return code


def length_factor(code: str) -> float:
    try:
        return LENGTH_UNITS[code][1]
    except KeyError as exc:
        raise UnitError(f"'{code}' is not a length unit") from exc


def convert_length(values, from_unit: str, to_unit: str):
    """Convert length values between units. Accepts scalars or arrays."""
    if from_unit == to_unit:
        return values
    factor = length_factor(from_unit) / length_factor(to_unit)
    return np.asarray(values, dtype=float) * factor
