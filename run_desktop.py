"""Convenience launcher: python run_desktop.py [project.ghproj] [--sample]"""

import sys

from geohydro.desktop.app import main

if __name__ == "__main__":
    sys.exit(main())
