"""Grid mathematics: raster calculator, resampling, filters, terrain derivatives,
volumes and blanking.

Phase 3. Governing equations, assumptions and validation: docs/GRID_MATH.md.
Every function returns a new grid (inputs are never modified in place) with
its method, parameters and warnings recorded in ``metadata``.
"""

STATUS = "implemented"
PHASE = 3
