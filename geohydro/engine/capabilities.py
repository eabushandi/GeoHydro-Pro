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


def _impl(key, title, desc=""):
    return Capability(key, title, 1, "implemented", desc)


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
    _plan("data.import.raster", "Import Raster (GeoTIFF, ASC, DEM, IMG)", 3),
    _plan("data.import.vector", "Import Vector (SHP, GPKG, GeoJSON, DXF)", 2),
    _plan("data.import.netcdf", "Import NetCDF", 6),
    _plan("data.import.lidar", "Import Point Cloud (LAS, LAZ)", 3),
    _plan("grid.idw", "Inverse Distance Weighting", 2),
    _plan("grid.ok", "Ordinary Kriging", 2),
    _plan("grid.uk", "Universal Kriging", 2),
    _plan("grid.mincurv", "Minimum Curvature", 2),
    _plan("grid.natnb", "Natural Neighbour", 2),
    _plan("grid.nearest", "Nearest Neighbour", 2),
    _plan("grid.tin", "Linear Triangulation", 2),
    _plan("grid.rbf", "Radial Basis Functions", 2),
    _plan("grid.variogram", "Variogram Analysis", 2),
    _plan("grid.crossval", "Cross-Validation", 2),
    _plan("map.contour", "Contour Map", 2),
    _plan("map.filled", "Filled Contour Map", 2),
    _plan("map.relief", "Colour Relief Map", 2),
    _plan("map.post", "Post Map", 2),
    _plan("map.layout", "Map Layout Editor", 2),
    _plan("map.export", "Export Map (PNG, JPEG, SVG, PDF)", 2),
    _plan("3d.surface", "3D Surface", 3),
    _plan("3d.points", "3D Point Cloud View", 3),
    _plan("terrain.slope", "Slope", 3),
    _plan("terrain.aspect", "Aspect", 3),
    _plan("terrain.hillshade", "Hillshade", 3),
    _plan("terrain.curvature", "Curvature", 3),
    _plan("terrain.profile", "Profiles & Cross-Sections", 3),
    _plan("terrain.volume", "Cut & Fill Volume", 3),
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
    _plan("edit.undo", "Undo / Redo", 2),
    _plan("settings.language.ar", "Arabic Interface", 8),
]

CAPABILITIES: dict[str, Capability] = {c.key: c for c in _ALL}


def capability(key: str) -> Capability:
    return CAPABILITIES[key]


def is_implemented(key: str) -> bool:
    cap = CAPABILITIES.get(key)
    return bool(cap and cap.implemented)
