Reference outputs of GDAL `gdaldem` (version in GDAL_VERSION.txt) for the
synthetic DEM `dem.tif` (61 × 41 nodes, 50 m spacing, EPSG:32639):

    z = 200 + 60 sin(x/500) cos(y/400) + 0.02 x + 15 exp(-((x-1500)² + (y-900)²) / 2e5)

Commands:

    gdaldem slope dem.tif slope.tif
    gdaldem aspect dem.tif aspect.tif
    gdaldem hillshade dem.tif hillshade_315_45.tif -az 315 -alt 45
    gdaldem hillshade dem.tif hillshade_120_30_z2.tif -az 120 -alt 30 -z 2

Used by tests/test_gridmath.py to validate GeoHydro Pro's terrain derivatives.
