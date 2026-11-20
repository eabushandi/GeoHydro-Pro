"""Project Explorer: tree of project items grouped by category."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem

from geohydro.project import Project

from .. import icons, theme

ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_ID = Qt.ItemDataRole.UserRole + 1

# category key -> (label, icon, planned phase or None)
CATEGORIES = [
    ("points", "Point Datasets", "points", None),
    ("grids", "Grids", "grid", None),
    ("rasters", "Raster Layers", "raster", 3),
    ("vectors", "Vector Layers", "vector", 3),
    ("maps", "Maps", "map", None),
    ("surfaces", "3D Surfaces", "surface3d", 3),
    ("results", "Analysis Results", "results", 3),
    ("reports", "Reports", "report", 6),
]


class ProjectExplorer(QTreeWidget):
    datasetActivated = Signal(str)  # dataset id (double click)
    itemActivated = Signal(str, str)  # kind ("dataset"|"grid"|"map"), id (double click)
    selectionChangedTo = Signal(str, str)  # kind ("project"|"dataset"|"grid"|"map"|"category"|""), id
    contextAction = Signal(str, str)  # action name, item id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setIndentation(16)
        self.setUniformRowHeights(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.itemDoubleClicked.connect(self._double)
        self.itemSelectionChanged.connect(self._sel)
        self.root: QTreeWidgetItem | None = None
        self.category_items: dict[str, QTreeWidgetItem] = {}

    def populate(self, project: Project | None) -> None:
        self.blockSignals(True)
        self.clear()
        self.category_items.clear()
        self.root = None
        if project is None:
            self.blockSignals(False)
            return
        self.root = QTreeWidgetItem([project.name + (" *" if project.dirty else "")])
        self.root.setIcon(0, icons.icon("folder"))
        f = QFont()
        f.setBold(True)
        self.root.setFont(0, f)
        self.root.setData(0, ROLE_KIND, "project")
        self.addTopLevelItem(self.root)

        inputs = QTreeWidgetItem(["Input Datasets"])
        inputs.setIcon(0, icons.icon("import"))
        inputs.setData(0, ROLE_KIND, "category")
        inputs.setData(0, ROLE_ID, "inputs")
        self.root.addChild(inputs)
        for key, label, icon_name, phase in CATEGORIES:
            parent = inputs if key == "points" else self.root
            text = label if phase is None else f"{label}  (planned, Phase {phase})"
            it = QTreeWidgetItem([text])
            it.setIcon(0, icons.icon(icon_name))
            it.setData(0, ROLE_KIND, "category")
            it.setData(0, ROLE_ID, key)
            if phase is not None:
                it.setForeground(0, Qt.GlobalColor.gray)
                it.setToolTip(0, f"{label} will be available in Phase {phase}.")
            parent.addChild(it)
            self.category_items[key] = it

        pts = self.category_items["points"]
        for ds in project.datasets.values():
            child = QTreeWidgetItem([f"{ds.name}  ({ds.n_points:,})"])
            child.setIcon(0, icons.icon("points"))
            child.setData(0, ROLE_KIND, "dataset")
            child.setData(0, ROLE_ID, ds.id)
            child.setToolTip(0, f"{ds.source.path}\nCRS: {ds.crs or 'undefined'}")
            pts.addChild(child)
        pts.setText(0, f"Point Datasets  ({len(project.datasets)})")
        grids = self.category_items["grids"]
        for g in project.grids.values():
            geo = g.geometry
            child = QTreeWidgetItem([f"{g.name}  ({geo.nx}×{geo.ny})"])
            child.setIcon(0, icons.icon("grid"))
            child.setData(0, ROLE_KIND, "grid")
            child.setData(0, ROLE_ID, g.id)
            child.setToolTip(0, f"{(g.metadata or {}).get('method_title', 'Grid')}\n"
                                f"spacing {geo.dx:g} × {geo.dy:g}\nCRS: {g.crs or 'undefined'}")
            grids.addChild(child)
        grids.setText(0, f"Grids  ({len(project.grids)})")
        maps = self.category_items["maps"]
        for m in project.maps.values():
            child = QTreeWidgetItem([m.name])
            child.setIcon(0, icons.icon("map"))
            child.setData(0, ROLE_KIND, "map")
            child.setData(0, ROLE_ID, m.id)
            child.setToolTip(0, f"{len(m.layers)} layer(s)")
            maps.addChild(child)
        maps.setText(0, f"Maps  ({len(project.maps)})")
        self.expandAll()
        self.blockSignals(False)

    def select_dataset(self, dataset_id: str) -> None:
        self.select_item("points", dataset_id)

    def select_item(self, category: str, item_id: str) -> None:
        cat = self.category_items.get(category)
        if not cat:
            return
        for i in range(cat.childCount()):
            if cat.child(i).data(0, ROLE_ID) == item_id:
                if self.currentItem() is not cat.child(i):
                    self.setCurrentItem(cat.child(i))
                return

    def child_items(self, category: str) -> list[QTreeWidgetItem]:
        cat = self.category_items.get(category)
        return [cat.child(i) for i in range(cat.childCount())] if cat else []

    def dataset_items(self) -> list[QTreeWidgetItem]:
        pts = self.category_items.get("points")
        return [pts.child(i) for i in range(pts.childCount())] if pts else []

    def _sel(self):
        it = self.currentItem()
        if it is None:
            self.selectionChangedTo.emit("", "")
            return
        self.selectionChangedTo.emit(it.data(0, ROLE_KIND) or "", it.data(0, ROLE_ID) or "")

    def _double(self, it, _col):
        kind = it.data(0, ROLE_KIND)
        if kind == "dataset":
            self.datasetActivated.emit(it.data(0, ROLE_ID))
        if kind in ("dataset", "grid", "map"):
            self.itemActivated.emit(kind, it.data(0, ROLE_ID))

    MENUS = {
        "dataset": (
            ("open", "Open", "table"),
            ("stats", "Statistics", "stats"),
            ("qc", "Quality Control Report", "qc"),
            ("grid", "Grid Data…", "grid"),
            ("post", "New Post Map", "points"),
            ("rename", "Rename…", None),
            ("export", "Export to CSV…", "export"),
            (None, None, None),
            ("remove", "Remove from Project…", "delete"),
        ),
        "grid": (
            ("grid.open", "Open", "grid"),
            ("grid.contour", "New Contour Map", "contour"),
            ("grid.filled", "New Filled Contour Map", "filled"),
            ("grid.relief", "New Colour Relief Map", "relief"),
            ("grid.rename", "Rename…", None),
            ("grid.export", "Export Grid File…", "export"),
            (None, None, None),
            ("grid.remove", "Remove from Project…", "delete"),
        ),
        "map": (
            ("map.open", "Open", "map"),
            ("map.export", "Export Map…", "export"),
            ("map.rename", "Rename…", None),
            (None, None, None),
            ("map.remove", "Remove from Project…", "delete"),
        ),
    }

    def _context_menu(self, pos):
        it = self.itemAt(pos)
        if it is None or it.data(0, ROLE_KIND) not in self.MENUS:
            return
        did = it.data(0, ROLE_ID)
        m = QMenu(self)
        for name, label, ic in self.MENUS[it.data(0, ROLE_KIND)]:
            if name is None:
                m.addSeparator()
                continue
            a = QAction(label, m)
            if ic:
                a.setIcon(icons.icon(ic))
            a.triggered.connect(lambda _=False, n=name: self.contextAction.emit(n, did))
            m.addAction(a)
        m.exec(self.viewport().mapToGlobal(pos))


_ = theme
