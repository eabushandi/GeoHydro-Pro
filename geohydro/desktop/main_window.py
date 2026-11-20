"""GeoHydro Pro main window."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMdiArea,
    QMdiSubWindow,
    QMessageBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from geohydro import APP_NAME, __version__
from geohydro.engine.capabilities import CAPABILITIES, capability
from geohydro.engine.crs import COMMON_CRS, UNDEFINED_CRS_LABEL, crs_storage_string, resolve_crs
from geohydro.engine.data.dataset import utc_now
from geohydro.engine.data.formats import file_dialog_filter
from geohydro.engine.data.importer import import_point_file
from geohydro.engine.data.qc import QCReport
from geohydro.engine.mapping.model import layer_source
from geohydro.engine.errors import (
    CRSError,
    GeoHydroError,
    ProjectConflictError,
    ProjectOverwriteError,
)
from geohydro.engine.units import LENGTH_UNITS, Z_UNITS
from geohydro.project import FILE_EXTENSION, FORMAT_VERSION, Project, load_project, save_project
from geohydro.project.storage import project_manifest, verify_project_file

from . import icons, theme
from .dialogs.import_wizard import ImportWizard
from .dialogs.misc import AboutDialog, CRSToolDialog, HistoryDialog
from .documents.gis_documents import ImageDocument, VectorDocument
from .documents.grid_document import GridDocument
from .documents.map_document import MapView
from .gis import GISMixin
from .gridmap import GridMapMixin
from .documents.dataset_document import DatasetDocument, fmt_num
from .widgets.output_console import OutputConsole
from .widgets.project_explorer import ProjectExplorer
from .widgets.properties_panel import Prop, PropertiesPanel
from .widgets.ribbon import Ribbon
from .widgets.start_page import StartPage
from .widgets.status_bar import GeoStatusBar
from .workers import TaskRunner

log = logging.getLogger("geohydro.desktop")

from geohydro.paths import DOCS_DIR, GIS_SAMPLE_PROJECT, SAMPLE_DATA_DIR, SAMPLE_PROJECT  # noqa: E402
PROJECT_FILTER = f"GeoHydro Pro project (*{FILE_EXTENSION})"
MAX_RECENT = 8

RIBBON_LABELS = {
    "new": "New", "open": "Open", "save": "Save", "import": "Import Data", "table": "Table",
    "preview": "Preview", "stats": "Statistics", "qc": "QC Report", "export_csv": "Export CSV",
    "remove": "Remove", "project_props": "Properties", "history": "History", "validate": "Validate",
    "crs_tool": "CRS Tool", "data.import.raster": "Raster", "data.import.vector": "Vector",
    "data.import.netcdf": "NetCDF", "data.import.lidar": "LAS/LAZ", "grid.idw": "IDW",
    "grid.ok": "Kriging", "grid.mincurv": "Min. Curvature", "grid.natnb": "Natural Nbr",
    "grid.tin": "Triangulation", "grid.rbf": "RBF", "grid.variogram": "Variogram",
    "grid.crossval": "Cross-Valid.", "map.contour": "Contour", "map.filled": "Filled",
    "map.relief": "Colour Relief", "map.post": "Post Map", "map.layout": "Layout",
    "map.export": "Export Map", "grid_data": "Grid Data", "grid_open": "Open Grid",
    "grid_export": "Export Grid", "grid.uk": "Universal Kriging", "3d.surface": "3D Surface", "3d.points": "3D Points",
    "terrain.slope": "Slope", "terrain.hillshade": "Hillshade", "terrain.profile": "Profile",
    "terrain.volume": "Volume", "hydro.fill": "Fill Sinks", "hydro.d8": "D8 Flow",
    "hydro.accum": "Accumulation", "hydro.streams": "Streams", "hydro.watershed": "Watershed",
    "coastal.transects": "Transects", "coastal.rates": "EPR · LRR · NSM", "coastal.profiles": "Beach Profiles",
    "flood.susceptibility": "Susceptibility", "flood.stormwater": "Stormwater",
    "gw.contours": "GW Levels", "gw.quality": "Water Quality", "reports.pdf": "PDF Report",
    "reports.xlsx": "Excel Report", "edit.undo": "Undo", "edit.redo": "Redo",
    "grid.math": "Calculator", "grid_filter": "Filter", "grid_blank": "Blank", "grid_clip": "Clip",
    "map.vector": "Vector / Image", "map.density": "Density", "terrain.aspect": "Aspect",
    "terrain.curvature": "Curvature", "vector_to_points": "To Points",
}


class MainWindow(GISMixin, GridMapMixin, QMainWindow):
    def __init__(self, settings: QSettings | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings or QSettings()
        self.project: Project = Project()
        self.actions: dict[str, QAction] = {}
        self.documents: dict[str, QMdiSubWindow] = {}
        self.tasks = TaskRunner(self)
        # dialogs can be replaced in tests
        self.confirm = self._confirm
        self.choose = self._choose

        self.setWindowIcon(icons.app_icon())
        self.resize(1480, 920)
        self.setDockNestingEnabled(True)

        self._build_central()
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_ribbon()
        self.status = GeoStatusBar(self)
        self.setStatusBar(self.status)
        self._wire_phase2()
        self._wire_gis()

        self._refresh_all()
        self._restore_state()
        self.console.info(f"{APP_NAME} {__version__} started. Project format v{FORMAT_VERSION}.")
        planned = sum(1 for c in CAPABILITIES.values() if not c.implemented)
        self.console.info(f"{planned} planned features are shown greyed out and labelled with their phase.")

    # ================================================================ build
    def _build_central(self):
        self.mdi = QMdiArea()
        self.mdi.setViewMode(QMdiArea.ViewMode.TabbedView)
        self.mdi.setTabsClosable(True)
        self.mdi.setTabsMovable(True)
        self.mdi.setDocumentMode(True)
        self.mdi.subWindowActivated.connect(self._on_subwindow)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.mdi, 1)
        self.setCentralWidget(host)

        self.start_page = StartPage()
        self.start_page.newProject.connect(self.new_project)
        self.start_page.openProject.connect(lambda: self.open_project())
        self.start_page.importData.connect(lambda: self.import_data())
        self.start_page.openSample.connect(self.open_sample_project)
        self.start_page.openRecent.connect(self.open_project)
        self._start_sub = None
        self.show_start_page()

    def _build_docks(self):
        self.explorer = ProjectExplorer()
        self.explorer.datasetActivated.connect(self.open_dataset)
        self.explorer.selectionChangedTo.connect(self._on_selection)
        self.explorer.contextAction.connect(self._explorer_action)
        self.dock_explorer = self._dock("Project Explorer", "explorer_dock", self.explorer,
                                        Qt.DockWidgetArea.LeftDockWidgetArea)
        self.properties = PropertiesPanel()
        self.properties.propertyEdited.connect(self._property_edited)
        self.dock_properties = self._dock("Properties", "properties_dock", self.properties,
                                          Qt.DockWidgetArea.RightDockWidgetArea)
        self.console = OutputConsole()
        self.dock_console = self._dock("Output Console", "console_dock", self.console,
                                       Qt.DockWidgetArea.BottomDockWidgetArea)
        self.resizeDocks([self.dock_explorer, self.dock_properties], [290, 330], Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_console], [190], Qt.Orientation.Vertical)

    def _dock(self, title, name, widget, area):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        d.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                      | QDockWidget.DockWidgetFeature.DockWidgetClosable
                      | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(area, d)
        return d

    def _act(self, key, text, slot=None, icon=None, shortcut=None, cap=None, tip=None, checkable=False):
        a = QAction(text, self)
        if icon:
            a.setIcon(icons.icon(icon))
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if checkable:
            a.setCheckable(True)
        if cap and not CAPABILITIES[cap].implemented:
            c = CAPABILITIES[cap]
            a.setText(c.label)
            a.setEnabled(False)
            a.setToolTip(f"{c.title} — planned for Phase {c.phase}. Not available in this release.")
            a.setStatusTip(a.toolTip())
            a.setProperty("planned", True)
            a.setProperty("phase", c.phase)
            a.setIconText(c.title)
        else:
            if tip:
                a.setToolTip(tip)
                a.setStatusTip(tip)
            if slot is not None:
                a.triggered.connect(slot)
            a.setProperty("planned", False)
        self.actions[key] = a
        return a

    def _plan(self, cap, icon=None):
        c = capability(cap)
        return self._act(cap, c.title, icon=icon, cap=cap)

    def _build_actions(self):
        A = self._act
        A("new", "New Project", self.new_project, "new", "Ctrl+N", tip="Create a new project")
        A("open", "Open Project…", lambda: self.open_project(), "open", "Ctrl+O", tip="Open a .ghproj project")
        A("open_sample", "Open Sample Project", self.open_sample_project, "folder")
        A("open_gis_sample", "Open GIS Demo Project", lambda: self.open_sample_project(GIS_SAMPLE_PROJECT),
          "folder", tip="Terrain, drainage, land use and flood-report density maps (synthetic data)")
        A("save", "Save Project", self.save_project, "save", "Ctrl+S", tip="Save the project")
        A("save_as", "Save Project As…", self.save_project_as, "save", "Ctrl+Shift+S")
        A("import", "Import Data…", lambda: self.import_data(), "import", "Ctrl+I",
          tip="Import CSV, XLSX, XYZ, TXT or DAT point data")
        A("export_csv", "Export Dataset to CSV…", self.export_dataset_csv, "export",
          tip="Export the selected dataset (as imported, after QC) to CSV")
        A("export_manifest", "Export Project Manifest (JSON)…", self.export_manifest, "export")
        A("exit", "Exit", self.close, None, "Ctrl+Q")
        A("copy", "Copy", self.copy_selection, None, "Ctrl+C", tip="Copy selected table cells")
        A("select_all", "Select All", self.select_all, None, "Ctrl+A")
        A("start_page", "Start Page", self.show_start_page, "info")
        A("tabbed", "Tabbed Documents", self._toggle_tabbed, checkable=True).setChecked(True)
        A("tile", "Tile Windows", lambda: (self._set_tabbed(False), self.mdi.tileSubWindows()))
        A("cascade", "Cascade Windows", lambda: (self._set_tabbed(False), self.mdi.cascadeSubWindows()))
        A("reset_layout", "Reset Layout", self.reset_layout)
        A("project_props", "Project Properties", self.show_project_properties, "properties")
        A("history", "Processing History…", self.show_history, "history")
        A("validate", "Validate Project", self.validate_project, "validate")
        A("stats", "Dataset Statistics", lambda: self._dataset_tab("Statistics"), "stats")
        A("qc", "Quality Control Report", lambda: self._dataset_tab("Quality Report"), "qc")
        A("table", "Data Table", lambda: self._dataset_tab("Table"), "table")
        A("preview", "Point Preview", lambda: self._dataset_tab("Point Preview"), "points")
        A("rename", "Rename Dataset…", self.rename_dataset)
        A("remove", "Remove Dataset…", self.remove_dataset, "delete")
        A("crs_tool", "CRS Inspector & Transform…", self.show_crs_tool, "crs")
        A("docs", "Documentation", self.open_docs, "info", "F1")
        A("checklist", "Feature Checklist", self.open_checklist, "validate")
        A("about", f"About {APP_NAME}", lambda: AboutDialog(self).exec(), "info")
        self.actions["export_csv"].setEnabled(False)
        self._phase2_actions()
        self._gis_actions()

        for key, ic in (
            ("edit.undo", None), ("data.import.raster", "raster"), ("data.import.vector", "vector"),
            ("data.import.netcdf", "grid"), ("data.import.lidar", "points"), ("grid.idw", "grid"),
            ("grid.ok", "kriging"), ("grid.uk", "kriging"), ("grid.mincurv", "grid"), ("grid.natnb", "grid"),
            ("grid.nearest", "grid"), ("grid.tin", "grid"), ("grid.rbf", "grid"),
            ("grid.variogram", "variogram"), ("grid.crossval", "validate"), ("map.contour", "contour"),
            ("map.filled", "filled"), ("map.relief", "relief"), ("map.post", "points"),
            ("map.layout", "layout"), ("map.export", "export"), ("3d.surface", "surface3d"),
            ("3d.points", "points"), ("terrain.slope", "slope"), ("terrain.aspect", "slope"),
            ("terrain.hillshade", "hillshade"), ("terrain.curvature", "contour"),
            ("terrain.profile", "profile"), ("terrain.volume", "volume"), ("hydro.fill", "drop"),
            ("hydro.d8", "flow"), ("hydro.accum", "flow"), ("hydro.streams", "flow"),
            ("hydro.watershed", "watershed"), ("coastal.transects", "transect"), ("coastal.rates", "wave"),
            ("coastal.profiles", "profile"), ("flood.susceptibility", "flood"),
            ("flood.stormwater", "drop"), ("gw.contours", "well"), ("gw.quality", "well"),
            ("reports.pdf", "pdf"), ("reports.xlsx", "report"), ("cloud.sync", "cloud"),
            ("account.license", "settings"), ("settings.language.ar", None),
            ("grid.math", "grid"), ("map.vector", "vector"), ("map.density", "points"),
        ):
            self._plan(key, ic)

    def _build_menus(self):
        from PySide6.QtWidgets import QMenuBar
        self.mb = mb = QMenuBar()
        a = self.actions

        def menu(title, items):
            m = mb.addMenu(title)
            for it in items:
                if it is None:
                    m.addSeparator()
                elif isinstance(it, str):
                    m.addAction(a[it])
                else:
                    m.addMenu(it)
            return m

        self.recent_menu = self._make_recent_menu()
        menu("&File", ["new", "open", "open_sample", "open_gis_sample", self.recent_menu, None, "save", "save_as", None,
                       "import", "data.import.vector", "data.import.raster", "grid_open", None, "export_csv", "grid_export", "map.export",
                       "export_manifest", None, "exit"])
        menu("&Edit", ["edit.undo", "edit.redo", None, "copy", "select_all"])
        view = menu("&View", [])
        for d in (self.dock_explorer, self.dock_properties, self.dock_console):
            view.addAction(d.toggleViewAction())
        self.ribbon_toggle = QAction("Ribbon", self, checkable=True, checked=True)
        self.ribbon_toggle.toggled.connect(lambda on: self.ribbon.setVisible(on))
        view.addAction(self.ribbon_toggle)
        view.addSeparator()
        for k in ("start_page", "tabbed", "tile", "cascade", None, "reset_layout"):
            view.addSeparator() if k is None else view.addAction(a[k])
        menu("&Project", ["project_props", "history", "validate", None, "cloud.sync"])
        menu("&Data", ["import", None, "table", "preview", "stats", "qc", None, "rename", "export_csv",
                       "remove", None, "data.import.vector", "data.import.raster", "vector_to_points",
                       "vector_export", "vector_rename", "vector_remove", "image_rename", "image_remove",
                       None, "data.import.netcdf", "data.import.lidar"])
        menu("&Grid", ["grid_data", None, "grid.idw", "grid.ok", "grid.uk", "grid.mincurv",
                       "grid.natnb", "grid.nearest", "grid.tin", "grid.rbf", None, "grid.variogram",
                       "grid.crossval", None, "grid_open", "grid_export", "grid_rename",
                       "grid_remove", None, "grid.math", "grid_filter", "grid_blank", "grid_clip"])
        menu("&Mapping", ["map.contour", "map.filled", "map.relief", "map.post", None, "map.layout",
                          "map.export", "map_rename", "map_remove", None, "map.vector",
                          "map.density"])
        menu("&Analysis", ["terrain.slope", "terrain.aspect", "terrain.hillshade", "terrain.curvature",
                           "terrain.profile", "terrain.volume"])
        menu("H&ydrology", ["hydro.fill", "hydro.d8", "hydro.accum", "hydro.streams", "hydro.watershed"])
        menu("&Coastal Engineering", ["coastal.transects", "coastal.rates", "coastal.profiles"])
        menu("&Flood Analysis", ["flood.susceptibility", "flood.stormwater"])
        menu("Ground&water", ["gw.contours", "gw.quality"])
        menu("&3D Visualization", ["3d.surface", "3d.points"])
        menu("&Reports", ["reports.pdf", "reports.xlsx"])
        menu("&Tools", ["crs_tool", None, "account.license"])
        settings = mb.addMenu("&Settings")
        units = settings.addMenu("Default Length Unit")
        self.unit_group = QActionGroup(self)
        for code, (name, _f) in LENGTH_UNITS.items():
            ua = QAction(f"{name} ({code})", self, checkable=True)
            ua.setData(code)
            ua.triggered.connect(lambda _=False, c=code: self._set_project_units(c))
            self.unit_group.addAction(ua)
            units.addAction(ua)
        lang = settings.addMenu("Language")
        en = QAction("English", self, checkable=True, checked=True)
        lang.addAction(en)
        lang.addAction(a["settings.language.ar"])
        menu("&Help", ["docs", "checklist", None, "about"])

    def _make_recent_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu("Recent Projects", self)
        m.aboutToShow.connect(self._fill_recent_menu)
        return m

    def _fill_recent_menu(self):
        self.recent_menu.clear()
        rec = self.recent_files()
        if not rec:
            x = self.recent_menu.addAction("(none)")
            x.setEnabled(False)
        for p in rec:
            act = self.recent_menu.addAction(p)
            act.triggered.connect(lambda _=False, p=p: self.open_project(p))

    def _build_ribbon(self):
        self.ribbon = Ribbon()
        a = self.actions
        brand = QWidget()
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(6, 0, 10, 0)
        logo = QLabel()
        logo.setPixmap(icons.logo_pixmap(20))
        name = QLabel(APP_NAME)
        name.setObjectName("BrandLabel")
        bl.addWidget(logo)
        bl.addWidget(name)
        self.mb.setCornerWidget(brand, Qt.Corner.TopRightCorner)

        def page(title, groups):
            p = self.ribbon.add_page(title)
            for gtitle, keys in groups:
                planned = all(a[k].property("planned") for k in keys)
                g = p.add_group(gtitle, planned)
                for k in keys:
                    if k in RIBBON_LABELS:  # toolbuttons show iconText(), menus show text()
                        a[k].setIconText(RIBBON_LABELS[k])
                    g.add_action(a[k])

        page("Home", [("Project", ["new", "open", "save"]), ("Data", ["import", "table", "stats", "qc"]),
                      ("Grid && Map", ["grid_data", "map.relief", "map.filled"]),
                      ("Edit", ["edit.undo", "edit.redo"]),
                      ("Inspect", ["project_props", "history", "validate"]), ("Tools", ["crs_tool"])])
        page("Data", [("Import", ["import", "data.import.vector", "data.import.raster"]), ("Dataset", ["table", "preview", "stats", "qc", "export_csv",
                                                           "remove"]),
                      ("GIS layers", ["vector_to_points", "vector_export"]),
                      ("Other formats", ["data.import.netcdf", "data.import.lidar"])])
        page("Grid", [("Grid", ["grid_data", "grid_open", "grid_export"]),
                      ("Methods", ["grid.idw", "grid.ok", "grid.mincurv", "grid.natnb", "grid.tin",
                                   "grid.rbf"]),
                      ("Geostatistics", ["grid.variogram", "grid.crossval"]),
                      ("Grid math", ["grid.math", "grid_filter", "grid_blank", "grid_clip"])])
        page("Map", [("Maps", ["map.contour", "map.filled", "map.relief", "map.post"]),
                     ("GIS", ["map.vector", "map.density"]),
                     ("Layout", ["map.layout", "map.export"])])
        page("3D && Terrain", [("3D", ["3d.surface", "3d.points"]),
                              ("Terrain", ["terrain.slope", "terrain.aspect", "terrain.hillshade",
                                           "terrain.curvature", "terrain.profile", "terrain.volume"])])
        page("Hydrology", [("Hydrology", ["hydro.fill", "hydro.d8", "hydro.accum", "hydro.streams",
                                          "hydro.watershed"])])
        page("Coastal", [("Shoreline analysis", ["coastal.transects", "coastal.rates", "coastal.profiles"])])
        page("Flood && Groundwater", [("Flood screening", ["flood.susceptibility", "flood.stormwater"]),
                                     ("Groundwater", ["gw.contours", "gw.quality"])])
        page("Reports", [("Reports", ["reports.pdf", "reports.xlsx"])])
        host = QWidget()
        host.setObjectName("MenuHost")
        host.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hl = QVBoxLayout(host)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hl.addWidget(self.mb)
        hl.addWidget(self.ribbon)
        self.setMenuWidget(host)

    # ============================================================ helpers
    def _confirm(self, title, text, buttons=None, default=None) -> bool:
        r = QMessageBox.question(self, title, text)
        return r == QMessageBox.StandardButton.Yes

    def _choose(self, title, text, options: list[str]) -> str | None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Warning)
        btns = {box.addButton(o, QMessageBox.ButtonRole.ActionRole): o for o in options}
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        return btns.get(box.clickedButton())

    def _error(self, title, exc):
        msg = str(exc)
        self.console.error(f"{title}: {msg}")
        if QApplication.platformName() != "offscreen":
            QMessageBox.critical(self, title, msg)

    def selected_dataset_id(self) -> str | None:
        sub = self.mdi.activeSubWindow()
        if sub and isinstance(sub.widget(), DatasetDocument):
            return sub.widget().dataset_id
        it = self.explorer.currentItem()
        if it is not None and it.data(0, Qt.ItemDataRole.UserRole) == "dataset":
            return it.data(0, Qt.ItemDataRole.UserRole + 1)
        return None

    # ===================================================== refresh / state
    def _refresh_all(self):
        p = self.project
        self.setWindowTitle(f"{p.name} [*] — {APP_NAME}")
        self.setWindowModified(p.dirty)
        self.explorer.populate(p)
        has_ds = bool(p.datasets)
        for k in ("export_csv", "stats", "qc", "table", "preview", "rename", "remove"):
            self.actions[k].setEnabled(has_ds)
        for ua in self.unit_group.actions() if hasattr(self, "unit_group") else []:
            ua.setChecked(ua.data() == p.units)
        if hasattr(self, "status"):
            self.status.set_crs(self._crs_short(p.default_crs))
        self.start_page.set_recent(self.recent_files())
        for k in ("grid_export", "grid_rename", "grid_remove", "map.contour", "map.filled",
                  "map.relief"):
            self.actions[k].setEnabled(bool(p.grids))
        for k in ("map_rename", "map_remove", "map.export"):
            self.actions[k].setEnabled(bool(p.maps))
        self.actions["map.post"].setEnabled(has_ds)
        self.actions["grid_data"].setEnabled(any(d.has_z for d in p.datasets.values()))
        for k in ("grid.math", "grid_filter", "grid_clip", "terrain.slope", "terrain.aspect",
                  "terrain.hillshade", "terrain.curvature", "terrain.profile", "terrain.volume"):
            self.actions[k].setEnabled(bool(p.grids))
        self.actions["grid_blank"].setEnabled(bool(p.grids) and any(
            v.family == "polygon" for v in p.vectors.values()))
        for k in ("vector_rename", "vector_remove", "vector_export"):
            self.actions[k].setEnabled(bool(p.vectors))
        self.actions["vector_to_points"].setEnabled(any(v.family == "point" for v in p.vectors.values()))
        for k in ("image_rename", "image_remove"):
            self.actions[k].setEnabled(bool(p.images))
        self.actions["map.vector"].setEnabled(bool(p.vectors or p.images))
        self.actions["map.density"].setEnabled(bool(p.datasets) or any(
            v.family == "point" for v in p.vectors.values()))
        sel = self.selected_dataset_id()
        gsel = self.selected_item("grid")
        msel = self.selected_item("map")
        vsel = self.selected_item("vector")
        isel = self.selected_item("image")
        if vsel and vsel in p.vectors:
            self.explorer.select_item("vectors", vsel)
            self._show_vector_properties(vsel)
        elif isel and isel in p.images:
            self.explorer.select_item("images", isel)
            self._show_image_properties(isel)
        elif gsel and gsel in p.grids:
            self.explorer.select_item("grids", gsel)
            self._show_grid_properties(gsel)
        elif msel and msel in p.maps:
            self.explorer.select_item("maps", msel)
            target = getattr(self, "_map_prop_target", (None, None))
            self._show_map_item_properties(msel, target[1] if target[0] == msel else "")
        elif sel and sel in p.datasets:
            self.explorer.select_dataset(sel)
            self._show_dataset_properties(sel)
        else:
            self.show_project_properties()

    def _mark_dirty(self):
        self.project.dirty = True
        self.setWindowModified(True)
        if self.explorer.root is not None:
            self.explorer.root.setText(0, self.project.name + " *")
        self._checkpoint()

    @staticmethod
    def _crs_short(crs):
        if not crs:
            return None
        try:
            info = resolve_crs(crs)
            return info.authority or info.name if info else None
        except CRSError:
            return crs

    def recent_files(self) -> list[str]:
        v = self.settings.value("recent_projects", [])
        if isinstance(v, str):
            v = [v]
        return [p for p in (v or []) if Path(p).exists()][:MAX_RECENT]

    def _add_recent(self, path):
        rec = [str(path)] + [p for p in self.recent_files() if p != str(path)]
        self.settings.setValue("recent_projects", rec[:MAX_RECENT])

    def _restore_state(self):
        geo = self.settings.value("window/geometry")
        st = self.settings.value("window/state")
        if geo is not None:
            self.restoreGeometry(geo)
        if st is not None:
            self.restoreState(st)
        self._default_state = self.saveState()

    def reset_layout(self):
        for d, area in ((self.dock_explorer, Qt.DockWidgetArea.LeftDockWidgetArea),
                        (self.dock_properties, Qt.DockWidgetArea.RightDockWidgetArea),
                        (self.dock_console, Qt.DockWidgetArea.BottomDockWidgetArea)):
            d.setFloating(False)
            self.addDockWidget(area, d)
            d.show()
        self.ribbon_toggle.setChecked(True)

    def _toggle_tabbed(self, on):
        self.mdi.setViewMode(QMdiArea.ViewMode.TabbedView if on else QMdiArea.ViewMode.SubWindowView)

    def _set_tabbed(self, on):
        self.actions["tabbed"].setChecked(on)
        self._toggle_tabbed(on)

    # ============================================================ project
    def maybe_save(self) -> bool:
        if not self.project.dirty:
            return True
        choice = self.choose("Unsaved changes", f"Save changes to '{self.project.name}'?",
                             ["Save", "Discard"])
        if choice == "Save":
            return self.save_project()
        return choice == "Discard"

    def set_project(self, project: Project):
        for sub in list(self.documents.values()):
            sub.close()
        self.documents.clear()
        self.project = project
        self._reset_undo()
        self._refresh_all()

    def new_project(self):
        if not self.maybe_save():
            return
        self.set_project(Project())
        self.console.info("New project created.")

    def open_project(self, path: str | None = None):
        if not self.maybe_save():
            return False
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open project", self._last_dir(), PROJECT_FILTER)
            if not path:
                return False
        try:
            proj = load_project(path)
        except GeoHydroError as exc:
            self._error("Cannot open project", exc)
            return False
        self.set_project(proj)
        self._add_recent(path)
        self.settings.setValue("last_dir", str(Path(path).parent))
        self.console.success(f"Opened {Path(path).name} (revision {proj.revision}, "
                             f"{len(proj.datasets)} datasets, {len(proj.grids)} grids, "
                             f"{len(proj.maps)} maps, {len(proj.vectors)} vector layers, "
                             f"{len(proj.images)} images).")
        if proj.dirty:
            self.console.warning("The project was created with an older file format and was upgraded in "
                                 "memory. The original file is unchanged until you save.")
        self._refresh_all()
        return True

    def open_sample_project(self, path=None):
        path = Path(path or SAMPLE_PROJECT)
        if not path.exists():
            self._error("Sample project", FileNotFoundError(str(path)))
            return
        # open a copy so the shipped sample is never overwritten
        if self.open_project(str(path)):
            self.project.path = None
            self.project.revision = 0
            self.project.uuid = uuid.uuid4().hex
            self.console.info("Sample project opened as an unsaved copy. Use Save As to keep it.")
            self._refresh_all()

    def _last_dir(self):
        return str(self.settings.value("last_dir", str(SAMPLE_DATA_DIR if SAMPLE_DATA_DIR.exists() else Path.home())))

    def save_project(self) -> bool:
        if not self.project.path:
            return self.save_project_as()
        return self._save_to(self.project.path)

    def save_project_as(self) -> bool:
        start = str(Path(self._last_dir()) / f"{self.project.name}{FILE_EXTENSION}")
        path, _ = QFileDialog.getSaveFileName(self, "Save project as", start, PROJECT_FILTER)
        if not path:
            return False
        # the native dialog has already asked about replacing an existing file
        return self._save_to(path, overwrite_confirmed=True)

    def _save_to(self, path, overwrite_confirmed=False) -> bool:
        overwrite, force = overwrite_confirmed, False
        for _ in range(3):
            try:
                saved = save_project(self.project, path, overwrite=overwrite, force=force)
                break
            except ProjectOverwriteError as exc:
                if not self.confirm("Replace file?", str(exc)):
                    self.console.warning("Save cancelled: target file not replaced.")
                    return False
                overwrite = True
            except ProjectConflictError as exc:
                choice = self.choose("Newer version on disk", str(exc), ["Overwrite newer file", "Save As…"])
                if choice == "Save As…":
                    return self.save_project_as()
                if choice != "Overwrite newer file":
                    self.console.warning("Save cancelled to protect newer data on disk.")
                    return False
                force = True
            except (GeoHydroError, OSError) as exc:
                self._error("Save failed", exc)
                return False
        else:  # pragma: no cover
            return False
        self._add_recent(saved)
        self.settings.setValue("last_dir", str(Path(saved).parent))
        self.console.success(f"Saved {saved.name} (revision {self.project.revision}).")
        self._refresh_all()
        return True

    def export_manifest(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export project manifest",
                                              str(Path(self._last_dir()) / f"{self.project.name}.json"),
                                              "JSON (*.json)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(project_manifest(self.project), fh, indent=2, ensure_ascii=False)
        self.console.success(f"Manifest written to {path}")

    def _set_project_units(self, code):
        self.project.set_metadata(units=code)
        self._mark_dirty()
        self.console.info(f"Project default length unit set to {code}.")
        self._refresh_all()

    # =============================================================== data
    def import_data(self, paths=None):
        dlg = ImportWizard(self, paths or [], default_crs=self.project.default_crs, start_dir=self._last_dir())
        if not paths:
            if not dlg.states:
                files, _ = QFileDialog.getOpenFileNames(self, "Select data files", self._last_dir(),
                                                        file_dialog_filter())
                if not files:
                    return
                dlg.add_files(files)
        if dlg.exec() != ImportWizard.DialogCode.Accepted:
            return
        self.run_import_jobs(dlg.jobs)

    def run_import_jobs(self, jobs):
        if not jobs:
            return
        self.settings.setValue("last_dir", str(Path(jobs[0].path).parent))
        self.status.busy(True, f"Importing {len(jobs)} file(s)…")

        def work():
            out = []
            for j in jobs:
                try:
                    out.append((j, import_point_file(j.path, j.options, j.settings, j.name), None))
                except Exception as exc:  # noqa: BLE001
                    out.append((j, None, exc))
            return out

        self.tasks.start(work, self._import_done, self._import_failed)

    def _import_done(self, results):
        self.status.busy(False, "Ready")
        last = None
        for job, ds, exc in results:
            if exc is not None:
                self._error(f"Import of {Path(job.path).name} failed", exc)
                continue
            self.project.add_dataset(ds)
            rep = QCReport.from_dict(ds.qc_report)
            self.console.success(f"Imported '{ds.name}': {rep.imported_rows:,} points "
                                 f"({rep.excluded_rows:,} excluded) from {Path(job.path).name}.")
            last = ds.id
        self._mark_dirty()
        self._refresh_all()
        if last:
            self.open_dataset(last)

    def _import_failed(self, exc, tb):
        self.status.busy(False, "Import failed")
        log.debug(tb)
        self._error("Import failed", exc)

    def open_dataset(self, dataset_id: str):
        ds = self.project.datasets.get(dataset_id)
        if ds is None:
            return None
        sub = self.documents.get(dataset_id)
        if sub is None:
            doc = DatasetDocument(ds)
            doc.preview.cursorMoved.connect(self.status.set_cursor)
            doc.preview.scaleChanged.connect(self.status.set_scale)
            sub = self.mdi.addSubWindow(doc)
            sub.setWindowIcon(icons.icon("points"))
            sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            sub.destroyed.connect(lambda _=None, d=dataset_id: self.documents.pop(d, None))
            self.documents[dataset_id] = sub
            sub.showMaximized()
        self.mdi.setActiveSubWindow(sub)
        sub.setWindowTitle(ds.name)
        return sub.widget()

    def _dataset_tab(self, tab: str):
        did = self.selected_dataset_id() or next(iter(self.project.datasets), None)
        if not did:
            return
        doc = self.open_dataset(did)
        for i in range(doc.tabs.count()):
            if doc.tabs.tabText(i) == tab:
                doc.tabs.setCurrentIndex(i)

    def rename_dataset(self, dataset_id=None):
        did = dataset_id or self.selected_dataset_id()
        if not did:
            return
        ds = self.project.datasets[did]
        name, ok = QInputDialog.getText(self, "Rename dataset", "New name:", text=ds.name)
        if ok:
            self._apply_dataset_name(did, name)

    def _apply_dataset_name(self, did, name) -> bool:
        try:
            self.project.rename_dataset(did, name)
        except ValueError as exc:
            self._error("Rename", exc)
            return False
        self._mark_dirty()
        doc = self.documents.get(did)
        if doc:
            doc.widget().refresh(self.project.datasets[did])
            doc.setWindowTitle(name)
        self._refresh_all()
        return True

    def remove_dataset(self, dataset_id=None):
        did = dataset_id or self.selected_dataset_id()
        if not did:
            return
        ds = self.project.datasets[did]
        if not self.confirm("Remove dataset",
                            f"Remove '{ds.name}' from the project?\n\nThe source file "
                            f"{ds.source.path} is not deleted."):
            return
        sub = self.documents.pop(did, None)
        if sub:
            sub.close()
        self.project.remove_dataset(did)
        self._mark_dirty()
        self.console.info(f"Removed dataset '{ds.name}' from the project.")
        self._refresh_all()

    def export_dataset_csv(self, dataset_id=None, path=None):
        did = dataset_id or self.selected_dataset_id()
        if not did:
            return None
        ds = self.project.datasets[did]
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export dataset", str(Path(self._last_dir()) /
                                                  f"{ds.name}.csv"), "CSV (*.csv)")
            if not path:
                return None
        if Path(path).resolve() == Path(ds.source.path).resolve():
            self._error("Export", ValueError("Refusing to overwrite the original source file."))
            return None
        ds.data.to_csv(path, index=False, float_format="%.17g")
        self.project.outputs.append({"path": str(path), "kind": "dataset_csv", "dataset_id": did,
                                     "created": utc_now()})
        self.project.log("dataset.export_csv", dataset_id=did, name=ds.name, path=str(path))
        self._mark_dirty()
        self.console.success(f"Exported '{ds.name}' ({ds.n_points:,} rows) to {path}")
        return path

    def _explorer_action(self, name, did):
        if self._gis_context(name, did) or self._phase2_context(name, did):
            return
        {"open": lambda: self.open_dataset(did),
         "stats": lambda: (self.open_dataset(did), self._dataset_tab("Statistics")),
         "qc": lambda: (self.open_dataset(did), self._dataset_tab("Quality Report")),
         "rename": lambda: self.rename_dataset(did),
         "export": lambda: self.export_dataset_csv(did),
         "remove": lambda: self.remove_dataset(did)}[name]()

    # ======================================================== properties
    def _on_selection(self, kind, ident):
        if kind == "dataset":
            self._show_dataset_properties(ident)
        elif kind == "grid":
            self._show_grid_properties(ident)
        elif kind == "map":
            self._show_map_item_properties(ident, "")
        elif kind == "vector":
            self._show_vector_properties(ident)
        elif kind == "image":
            self._show_image_properties(ident)
        elif kind == "project" or kind == "":
            self.show_project_properties()
        elif kind == "category":
            self.properties.show_properties(self.explorer.currentItem().text(0), [])

    def _on_subwindow(self, sub):
        w = sub.widget() if sub else None
        if isinstance(w, GridDocument):
            if w.grid_id in self.project.grids:
                self.explorer.select_item("grids", w.grid_id)
                self._show_grid_properties(w.grid_id)
                self.status.set_scale("—")
            return
        if isinstance(w, (VectorDocument, ImageDocument)):
            vid = w.item_id
            if vid in self.project.vectors:
                self.explorer.select_item("vectors", vid)
                self._show_vector_properties(vid)
            elif vid in self.project.images:
                self.explorer.select_item("images", vid)
                self._show_image_properties(vid)
            self.status.set_scale("—")
            return
        if isinstance(w, MapView):
            if w.map_id in self.project.maps:
                self.explorer.select_item("maps", w.map_id)
                self._show_map_item_properties(w.map_id, w.current_layer_id() or "")
                self.status.set_crs(self._crs_short(w.doc.crs))
                self.status.set_scale("page view")
            return
        if sub and isinstance(sub.widget(), DatasetDocument):
            did = sub.widget().dataset_id
            ds = self.project.datasets.get(did)
            if ds:
                self.explorer.select_dataset(did)
                self.status.set_crs(self._crs_short(ds.crs))
                self._show_dataset_properties(did)
                pv = sub.widget().preview
                sc = pv.screen_scale() if pv.isVisible() else None
                self.status.set_scale(f"1:{sc:,.0f} (screen)" if sc else "—")
        else:
            self.status.set_crs(self._crs_short(self.project.default_crs))
            self.status.set_scale("—")

    def _crs_choices(self):
        return [UNDEFINED_CRS_LABEL] + [f"{c} - {n}" for c, n in COMMON_CRS]

    def _crs_display(self, crs):
        if not crs:
            return UNDEFINED_CRS_LABEL
        try:
            info = resolve_crs(crs)
            return info.display if info else UNDEFINED_CRS_LABEL
        except CRSError:
            return crs

    def show_project_properties(self):
        p = self.project
        props = [
            Prop("Project", "Name", p.name, "text", "project.name"),
            Prop("Project", "Description", p.description, "text", "project.description"),
            Prop("Project", "Author", p.author, "text", "project.author"),
            Prop("Coordinate system", "Default CRS", self._crs_display(p.default_crs), self._crs_choices(),
                 "project.default_crs", "Used as the default CRS when importing data"),
            Prop("Units", "Default length unit", p.units, list(LENGTH_UNITS), "project.units"),
            Prop("File", "Location", p.path or "(not saved)"),
            Prop("File", "Format version", FORMAT_VERSION),
            Prop("File", "Revision", p.revision),
            Prop("File", "Project ID", p.uuid),
            Prop("File", "Created (UTC)", p.created),
            Prop("File", "Modified (UTC)", p.modified),
            Prop("Contents", "Point datasets", len(p.datasets)),
            Prop("Contents", "Grids", len(p.grids)),
            Prop("Contents", "Maps", len(p.maps)),
            Prop("Contents", "Vector layers", len(p.vectors)),
            Prop("Contents", "Raster images", len(p.images)),
            Prop("Contents", "History entries", len(p.history)),
            Prop("Contents", "Outputs", len(p.outputs)),
        ]
        self.properties.show_properties(f"Project — {p.name}", props)

    def _show_dataset_properties(self, did):
        ds = self.project.datasets.get(did)
        if ds is None:
            return
        rep = QCReport.from_dict(ds.qc_report)
        z = ds.z_statistics()
        s = ds.spatial_statistics()
        props = [
            Prop("Dataset", "Name", ds.name, "text", "ds.name"),
            Prop("Dataset", "Type", "Point dataset"),
            Prop("Dataset", "Points", f"{ds.n_points:,}"),
            Prop("Dataset", "Attributes", ", ".join(ds.attribute_columns) or "—"),
            Prop("Columns", "X", ds.x_label),
            Prop("Columns", "Y", ds.y_label),
            Prop("Columns", "Z", ds.z_label if ds.has_z else "—"),
            Prop("Coordinate system", "Assigned CRS", self._crs_display(ds.crs), self._crs_choices(), "ds.crs",
                 "Assigning a CRS changes metadata only; coordinates are not transformed."),
            Prop("Coordinate system", "XY units", ds.xy_units),
            Prop("Coordinate system", "Z units", ds.z_units, Z_UNITS, "ds.z_units"),
            Prop("Extent", "X min / max", f"{fmt_num(s.get('x_min'))}  /  {fmt_num(s.get('x_max'))}"),
            Prop("Extent", "Y min / max", f"{fmt_num(s.get('y_min'))}  /  {fmt_num(s.get('y_max'))}"),
            Prop("Extent", "Mean NN distance", fmt_num(s.get("nn_mean"))),
            Prop("Z statistics", "Min / Max", f"{fmt_num(z.get('minimum'))}  /  {fmt_num(z.get('maximum'))}"),
            Prop("Z statistics", "Mean", fmt_num(z.get("mean"))),
            Prop("Z statistics", "Std. dev. (n-1)", fmt_num(z.get("std"))),
            Prop("Quality control", "Source rows", f"{rep.source_rows:,}"),
            Prop("Quality control", "Imported", f"{rep.imported_rows:,}"),
            Prop("Quality control", "Excluded", f"{rep.excluded_rows:,}"),
            Prop("Quality control", "Duplicate groups", rep.duplicate_groups),
            Prop("Source", "File", ds.source.path),
            Prop("Source", "Format", ds.source.format.upper()),
            Prop("Source", "SHA-256", ds.source.sha256[:16] + "…"),
            Prop("Source", "Imported (UTC)", ds.created),
        ]
        self.properties.show_properties(f"Dataset — {ds.name}", props)
        self.status.set_crs(self._crs_short(ds.crs))

    def _property_edited(self, key, value):
        p = self.project
        if self._phase2_property_edited(key, value) or self._gis_property_edited(key, value):
            return
        try:
            if key.startswith("project."):
                field = key.split(".", 1)[1]
                if field == "name" and not value.strip():
                    raise ValueError("Project name cannot be empty")
                if field == "default_crs":
                    info = resolve_crs(value)
                    value = crs_storage_string(info)
                p.set_metadata(**{field: value.strip() if isinstance(value, str) else value})
                self.console.info(f"Project {field.replace('_', ' ')} updated.")
            elif key.startswith("ds."):
                did = self.selected_dataset_id()
                if not did:
                    return
                field = key.split(".", 1)[1]
                if field == "name":
                    if not self._apply_dataset_name(did, value):
                        self.properties.revert(key, p.datasets[did].name)
                    return
                if field == "crs":
                    info = resolve_crs(value)
                    p.assign_crs(did, crs_storage_string(info), bool(info and info.is_geographic))
                    self.console.info(f"CRS of '{p.datasets[did].name}' set to "
                                      f"{info.display if info else 'undefined'} (metadata only, no reprojection).")
                elif field == "z_units":
                    ds = p.datasets[did]
                    old = ds.z_units
                    ds.z_units = value
                    p.log("dataset.z_units", dataset_id=did, old=old, new=value,
                          note="unit label changed; values not converted")
                doc = self.documents.get(did)
                if doc:
                    doc.widget().refresh(p.datasets[did])
            self._mark_dirty()
            self._refresh_all()
        except (CRSError, ValueError, KeyError) as exc:
            self._error("Invalid value", exc)
            self._refresh_all()

    # ============================================================== misc
    def show_history(self):
        HistoryDialog(self.project, self).exec()

    def show_crs_tool(self):
        did = self.selected_dataset_id()
        crs = self.project.datasets[did].crs if did else self.project.default_crs
        CRSToolDialog(self, initial=crs or "EPSG:4326").exec()

    def validate_project(self):
        p = self.project
        self.console.info(f"Validating project '{p.name}'…")
        problems = 0
        for ds in p.datasets.values():
            n_bad = int((~(ds.data["X"].notna() & ds.data["Y"].notna())).sum())
            if n_bad:
                problems += 1
                self.console.warning(f"'{ds.name}': {n_bad} points without valid coordinates")
            if not ds.crs:
                self.console.warning(f"'{ds.name}': no coordinate reference system assigned")
            if not Path(ds.source.path).exists():
                self.console.warning(f"'{ds.name}': source file no longer found at {ds.source.path} "
                                     "(the imported copy in the project is unaffected)")
        for m in p.maps.values():
            missing = [lyr.name for lyr in m.layers if p.item(layer_source(lyr)) is None]
            if missing:
                problems += 1
                self.console.warning(f"Map '{m.name}': missing data source for layer(s) "
                                     + ", ".join(missing))
        for v in p.vectors.values():
            if not v.crs:
                self.console.warning(f"Vector layer '{v.name}': no coordinate reference system assigned")
        for g in p.grids.values():
            if not g.crs:
                self.console.warning(f"Grid '{g.name}': no coordinate reference system assigned")
        if p.path and not p.dirty:
            try:
                for line in verify_project_file(p.path):
                    self.console.success(line)
            except GeoHydroError as exc:
                problems += 1
                self.console.error(f"File verification failed: {exc}")
        else:
            self.console.info("File integrity verification runs on the saved file; save the project to include it.")
        (self.console.success if not problems else self.console.warning)(
            f"Validation finished: {problems} problem(s) found.")
        return problems

    def copy_selection(self):
        w = QApplication.focusWidget()
        if isinstance(w, QTableView) and w.selectionModel():
            idx = sorted(w.selectionModel().selectedIndexes(), key=lambda i: (i.row(), i.column()))
            if not idx:
                return
            rows = {}
            for i in idx:
                rows.setdefault(i.row(), []).append(str(i.data() or ""))
            QGuiApplication.clipboard().setText("\n".join("\t".join(v) for v in rows.values()))
            self.status.set_status(f"Copied {len(idx)} cells")

    def select_all(self):
        w = QApplication.focusWidget()
        if isinstance(w, QTableView):
            w.selectAll()

    def show_start_page(self):
        if self._start_sub is None:
            sub = self.mdi.addSubWindow(self.start_page)
            sub.setWindowTitle("Start Page")
            sub.setWindowIcon(icons.icon("info"))
            self._start_sub = sub  # reused: closing the tab only hides it
        self._start_sub.showMaximized()
        self.mdi.setActiveSubWindow(self._start_sub)

    def open_docs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DOCS_DIR)))

    def open_checklist(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(DOCS_DIR / "FEATURE_CHECKLIST.md")))

    def closeEvent(self, event):
        if not self.maybe_save():
            event.ignore()
            return
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.console.detach()
        event.accept()


_ = theme
