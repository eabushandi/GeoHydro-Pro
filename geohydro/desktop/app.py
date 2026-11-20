"""Desktop application entry point.

    python -m geohydro.desktop [project.ghproj] [--sample | --gis-sample]
    python -m geohydro.desktop --selftest [--report FILE]
"""

from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from geohydro import APP_NAME, ORGANIZATION, __version__

from . import icons, theme
from .i18n import install_language


def create_app(argv=None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    QCoreApplication.setOrganizationName(ORGANIZATION)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(["Inter", "Segoe UI", "Noto Sans", "DejaVu Sans"])
    font.setPointSizeF(9.5)
    app.setFont(font)
    app.setStyleSheet(theme.STYLESHEET)
    app.setWindowIcon(icons.app_icon())
    install_language(app, "en")
    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="geohydro-pro", description=f"{APP_NAME} desktop")
    parser.add_argument("project", nargs="?", help="project file (.ghproj) to open")
    parser.add_argument("--sample", action="store_true", help="open the bundled sample project")
    parser.add_argument("--gis-sample", action="store_true",
                        help="open the bundled GIS demonstration project")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--selftest", action="store_true",
                        help="check the installation without user interaction and exit")
    parser.add_argument("--report", help="file for the --selftest report")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=logging.WARNING)
    if args.selftest:
        from geohydro.selftest import run
        return run(args.report)

    app = create_app([sys.argv[0]] + qt_args)
    from .main_window import MainWindow

    win = MainWindow(QSettings())
    win.show()
    if args.project:
        win.open_project(args.project)
    elif args.gis_sample:
        from geohydro.paths import GIS_SAMPLE_PROJECT
        win.open_sample_project(GIS_SAMPLE_PROJECT)
    elif args.sample:
        win.open_sample_project()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
