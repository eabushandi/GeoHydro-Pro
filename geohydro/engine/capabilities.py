"""Single source of truth for which features exist and which are planned.

The desktop UI reads this registry to decide whether a menu entry or ribbon
button is active. A feature must only be marked ``implemented`` once it has
code and automated tests. Everything else is shown to users as *planned*.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    key: str
    title: str
    phase: int
    status: str  # "implemented" | "planned"
    description: str = ""

    @property
    def implemented(self) -> bool:
        return self.status == "implemented"

    @property
    def label(self) -> str:
        if self.implemented:
            return self.title
        return f"{self.title} (planned, Phase {self.phase})"


def _impl(key, title, desc="", phase=1):
    return Capability(key, title, phase, "implemented", desc)


def _plan(key, title, phase, desc=""):
    return Capability(key, title, phase, "planned", desc)


_ALL = [
    # ---- Phase 1: implemented -------------------------------------------
    _impl("project.new", "New Project"),
    _impl("project.open", "Open Project"),
    _impl("project.save", "Save Project"),
    _impl("project.history", "Processing History"),
    _impl("project.validate", "Validate Project Integrity"),
    _impl("data.import.csv", "Import CSV"),
    _impl("data.import.xlsx", "Import XLSX"),
    _impl("data.import.xyz", "Import XYZ / TXT / DAT"),
    _impl("data.preview", "Data Preview"),
    _impl("data.qc", "Data Quality Control"),
    _impl("data.statistics", "Dataset Statistics"),
    _impl("data.export.csv", "Export Dataset to CSV"),
    _impl("tools.crs", "CRS Inspector & Coordinate Transform"),
    # ---- Later phases: planned ------------------------------------------
    _plan("data.import.netcdf", "Import NetCDF", 6),
    _plan("data.import.lidar", "Import Point Cloud (LAS, LAZ)", 4),
    # ---- Phase 2: implemented -------------------------------------------
    _impl("grid.idw", "Inverse Distance Weighting", phase=2),
    _impl("grid.ok", "Ordinary Kriging", phase=2),
    _impl("grid.uk", "Universal Kriging", phase=2),
    _impl("grid.mincurv", "Minimum Curvature", phase=2),
    _impl("grid.natnb", "Natural Neighbour", phase=2),
    _impl("grid.nearest", "Nearest Neighbour", phase=2),
    _impl("grid.tin", "Linear Triangulation", phase=2),
    _impl("grid.rbf", "Radial Basis Functions", phase=2),
    _impl("grid.variogram", "Variogram Analysis", phase=2),
    _impl("grid.crossval", "Cross-Validation", phase=2),
    _impl("grid.files", "Open / Export Grid Files (Surfer GRD, ESRI ASC, XYZ)", phase=2),
    _impl("grid.statistics", "Grid Statistics & Residuals", phase=2),
    _impl("map.contour", "Contour Map", phase=2),
    _impl("map.filled", "Filled Contour Map", phase=2),
    _impl("map.relief", "Colour Relief Map", phase=2),
    _impl("map.post", "Post Map", phase=2),
    _impl("map.layout", "Map Layout Editor", phase=2),
    _impl("map.export", "Export Map (PNG, JPEG, SVG, PDF)", phase=2),
    # ---- Phase 3: implemented -------------------------------------------
    _impl("data.import.vector", "Import Vector (SHP, GPKG, GeoJSON, KML, FlatGeobuf, DXF)", phase=3),
    _impl("data.import.raster", "Import Raster (GeoTIFF and other GDAL formats)", phase=3),
    _impl("grid.math", "Grid Mathematics (calculator, filters, blanking, clipping)", phase=3),
    _impl("map.vector", "Vector & Base Map Layers", phase=3),
    _impl("map.density", "Point Density (kernel density, counts)", phase=3),
    _impl("terrain.slope", "Slope", phase=3),
    _impl("terrain.aspect", "Aspect", phase=3),
    _impl("terrain.hillshade", "Hillshade", phase=3),
    _impl("terrain.curvature", "Curvature", phase=3),
    _impl("terrain.profile", "Profiles", phase=3),
    _impl("terrain.volume", "Cut & Fill Volume", phase=3),
    _impl("edit.undo", "Undo / Redo", phase=3),
    # ---- Later phases: planned ------------------------------------------
    _plan("3d.surface", "3D Surface", 4),
    _plan("3d.points", "3D Point Cloud View", 4),
    _plan("hydro.fill", "Depression Filling", 4),
    _plan("hydro.d8", "D8 Flow Direction", 4),
    _plan("hydro.accum", "Flow Accumulation", 4),
    _plan("hydro.streams", "Stream Network Extraction", 4),
    _plan("hydro.watershed", "Watershed Delineation", 4),
    _plan("coastal.transects", "Baseline & Transects", 5),
    _plan("coastal.rates", "Shoreline Change (EPR, LRR, NSM, SCE)", 5),
    _plan("coastal.profiles", "Beach Profiles & Volumes", 5),
    _plan("flood.susceptibility", "Flood Susceptibility (screening)", 6),
    _plan("flood.stormwater", "Stormwater Catchment Analysis", 6),
    _plan("gw.contours", "Groundwater Contours", 6),
    _plan("gw.quality", "Water Quality Surfaces", 6),
    _plan("reports.pdf", "PDF Report", 6),
    _plan("reports.xlsx", "Excel Report", 6),
    _plan("cloud.sync", "Cloud Synchronisation", 7),
    _plan("account.license", "Licence & Subscription", 7),
    _plan("settings.language.ar", "Arabic Interface", 8),
]

CAPABILITIES: dict[str, Capability] = {c.key: c for c in _ALL}


def capability(key: str) -> Capability:
    return CAPABILITIES[key]


def is_implemented(key: str) -> bool:
    cap = CAPABILITIES.get(key)
    return bool(cap and cap.implemented)
