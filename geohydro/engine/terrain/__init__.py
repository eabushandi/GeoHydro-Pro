"""Terrain analysis: slope, aspect, hillshade, curvature, profiles, volumes.

STATUS: implemented in Phase 3. The calculations live in
:mod:`geohydro.engine.gridmath` (terrain derivatives in ``gridmath.terrain``,
volumes in ``gridmath.volume``); this package re-exports them under the
terrain name. Equations, assumptions and validation: docs/GRID_MATH.md.
"""

STATUS = "implemented"
PHASE = 3

from geohydro.engine.gridmath.terrain import aspect, curvature, hillshade, profile, slope  # noqa: E402,F401
from geohydro.engine.gridmath.volume import volume, volume_report  # noqa: E402,F401
