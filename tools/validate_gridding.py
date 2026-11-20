"""Reproduce the gridding validation table in docs/GRIDDING.md.

    python tools/validate_gridding.py

Grids the synthetic terrain survey (samples/data) with every method and
compares the result with the analytic surface it was generated from, plus a
leave-one-out cross-validation of all 300 points.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geohydro.engine.gridding.crossval import leave_one_out  # noqa: E402
from geohydro.engine.gridding.grid import GridGeometry  # noqa: E402
from geohydro.engine.gridding.gridder import GriddingRequest, grid_data  # noqa: E402
from geohydro.engine.interpolation.variogram import (experimental_variogram,  # noqa: E402
                                                     fit_variogram)


def main():
    spec = importlib.util.spec_from_file_location("gen", ROOT / "samples" / "generate_samples.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    df = pd.read_csv(ROOT / "samples" / "data" / "terrain_survey_utm39n.csv")
    x, y, z = (df[c].to_numpy(float) for c in ("Easting_m", "Northing_m", "Elevation_m"))
    geom = GridGeometry.from_spacing(441000, 449000, 2886000, 2894000, 200)  # survey interior
    X, Y = geom.mesh()
    truth = gen.terrain_surface(X, Y)
    vm, _ = fit_variogram(experimental_variogram(x, y, z, n_lags=15, max_lag=5000), "gaussian")
    params = {"idw": {}, "nearest": {}, "tin": {}, "natural_neighbour": {}, "rbf": {},
              "min_curvature": {}, "ordinary_kriging": {"variogram": vm.to_dict()},
              "universal_kriging": {"variogram": vm.to_dict()}}
    print(f"Grid {geom.nx} x {geom.ny}, spacing {geom.dx:g} m; variogram: {vm.describe()}")
    print(f"{'method':<20}{'RMSE vs truth':>15}{'CV RMSE':>10}{'CV R2':>8}{'MSSE':>8}")
    for m, p in params.items():
        g = grid_data(x, y, z, GriddingRequest(m, p, geom)).grid
        rmse = float(np.sqrt(np.nanmean((g.z - truth) ** 2)))
        cv = leave_one_out(x, y, z, m, p, geometry=geom if m == "min_curvature" else None,
                           max_validation_points=1000).metrics
        msse = cv.get("mean_squared_standardised_error", float("nan"))
        print(f"{m:<20}{rmse:>15.3f}{cv['rmse']:>10.3f}{cv['r_squared']:>8.3f}{msse:>8.2f}")


if __name__ == "__main__":
    main()
