"""Map document model: layers, map furniture and page layout (JSON-serialisable).

A map references grids and point datasets by id; the renderer resolves the
ids through a callable, so the same map can be drawn by the desktop
application or (later) the web backend.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass, field, fields

from ..errors import MapError
from .levels import LevelSpec

PAGE_SIZES_MM = {"A4": (210, 297), "A3": (297, 420), "Letter": (215.9, 279.4),
                 "Tabloid": (279.4, 431.8)}
POSITIONS = ["upper left", "upper right", "lower left", "lower right"]


def _new_id():
    return uuid.uuid4().hex


@dataclass
class Layer:
    type: str = "base"
    name: str = "Layer"
    visible: bool = True
    opacity: float = 1.0
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(getattr(self, k), LevelSpec):
                d[k] = getattr(self, k).to_dict()
        return d


@dataclass
class ContourLayer(Layer):
    type: str = "contour"
    grid_id: str = ""
    levels: LevelSpec = field(default_factory=LevelSpec)
    line_color: str = "#2b2b2b"
    line_width: float = 0.6
    major_every: int = 5  # every n-th level is a major (index) contour; 0 = none
    major_width: float = 1.2
    labels: bool = True  # labels on major contours
    label_decimals: int | None = None  # None = automatic from the interval
    label_size: float = 7.0
    color_by_level: bool = False
    palette: str = "viridis"
    reverse: bool = False


@dataclass
class FilledContourLayer(Layer):
    type: str = "filled_contour"
    grid_id: str = ""
    levels: LevelSpec = field(default_factory=LevelSpec)
    palette: str = "viridis"
    reverse: bool = False
    show_colorbar: bool = True


@dataclass
class ColourReliefLayer(Layer):
    type: str = "colour_relief"
    grid_id: str = ""
    palette: str = "terrain"
    reverse: bool = False
    z_min: float | None = None
    z_max: float | None = None
    smooth: bool = True  # bilinear display interpolation between nodes
    show_colorbar: bool = True


@dataclass
class PostLayer(Layer):
    type: str = "post"
    dataset_id: str = ""
    marker: str = "o"
    size: float = 12.0
    face_color: str = "#d62728"
    edge_color: str = "#ffffff"
    color_by_z: bool = False
    palette: str = "viridis"
    reverse: bool = False
    label_column: str | None = None  # None, "Z" or an attribute column
    label_size: float = 6.5
    label_decimals: int = 2


LAYER_TYPES = {cls.type: cls for cls in (ContourLayer, FilledContourLayer, ColourReliefLayer,
                                          PostLayer)}
LAYER_TITLES = {"contour": "Contours", "filled_contour": "Filled contours",
                "colour_relief": "Colour relief", "post": "Post (points)"}


def layer_from_dict(d: dict) -> Layer:
    d = dict(d)
    cls = LAYER_TYPES.get(d.get("type"))
    if cls is None:
        raise MapError(f"Unknown layer type '{d.get('type')}'.")
    known = {f.name for f in fields(cls)}
    d = {k: v for k, v in d.items() if k in known}
    if "levels" in d:
        d["levels"] = LevelSpec.from_dict(d["levels"])
    return cls(**d)


@dataclass
class ElementPos:
    """Position of a map element: a named corner or an explicit (x, y) in
    axes-fraction coordinates (0..1) of the map frame."""

    visible: bool = True
    position: str = "lower left"
    xy: tuple | None = None  # overrides position when set (dragged in the layout)

    def to_dict(self):
        d = asdict(self)
        d["xy"] = list(self.xy) if self.xy is not None else None
        return d


@dataclass
class MapDocument:
    name: str = "Map"
    title: str = ""
    subtitle: str = ""
    page: str = "A4"
    orientation: str = "landscape"
    margins_mm: float = 15.0
    crs: str | None = None
    xy_units: str = "m"
    extent: list | None = None  # [x_min, x_max, y_min, y_max]; None = from layers
    layers: list = field(default_factory=list)  # drawn bottom -> top
    colorbar: dict = field(default_factory=lambda: {"visible": True, "label": "",
                                                    "location": "right"})
    scale_bar: ElementPos = field(default_factory=lambda: ElementPos(True, "lower left"))
    north_arrow: ElementPos = field(default_factory=lambda: ElementPos(True, "upper right"))
    graticule: dict = field(default_factory=lambda: {"visible": True, "lines": True,
                                                     "line_alpha": 0.25})
    annotations: list = field(default_factory=list)  # {text, x, y, size, color}
    id: str = field(default_factory=_new_id)
    kind: str = "map"

    def __post_init__(self):
        if self.page not in PAGE_SIZES_MM:
            raise MapError(f"Unknown page size '{self.page}'.")
        if self.orientation not in ("landscape", "portrait"):
            raise MapError("Orientation must be 'landscape' or 'portrait'.")

    def page_size_inches(self) -> tuple[float, float]:
        w, h = PAGE_SIZES_MM[self.page]
        if self.orientation == "landscape":
            w, h = h, w
        return w / 25.4, h / 25.4

    def layer(self, layer_id: str) -> Layer:
        for lyr in self.layers:
            if lyr.id == layer_id:
                return lyr
        raise MapError(f"No layer with id {layer_id}.")

    def move_layer(self, layer_id: str, step: int) -> None:
        i = [lyr.id for lyr in self.layers].index(layer_id)
        j = min(max(i + step, 0), len(self.layers) - 1)
        self.layers.insert(j, self.layers.pop(i))

    def referenced_ids(self) -> set:
        out = set()
        for lyr in self.layers:
            for k in ("grid_id", "dataset_id"):
                if getattr(lyr, k, ""):
                    out.add(getattr(lyr, k))
        return out

    def to_dict(self) -> dict:
        d = {f.name: copy.deepcopy(getattr(self, f.name)) for f in fields(self)}
        d["layers"] = [lyr.to_dict() for lyr in self.layers]
        d["scale_bar"] = self.scale_bar.to_dict()
        d["north_arrow"] = self.north_arrow.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MapDocument":
        d = dict(d)
        known = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in known}
        d["layers"] = [layer_from_dict(x) for x in d.get("layers", [])]
        for k in ("scale_bar", "north_arrow"):
            if k in d and isinstance(d[k], dict):
                e = dict(d[k])
                if e.get("xy") is not None:
                    e["xy"] = tuple(e["xy"])
                d[k] = ElementPos(**e)
        return cls(**d)
