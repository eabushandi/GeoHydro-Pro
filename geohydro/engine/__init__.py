"""Shared scientific engine.

This package is UI-independent: it must not import PySide6/Qt. Desktop and
(planned) web front ends call the same functions so calculations are identical
on every platform.
"""

from .capabilities import CAPABILITIES, Capability, capability, is_implemented  # noqa: F401
from .errors import GeoHydroError  # noqa: F401
