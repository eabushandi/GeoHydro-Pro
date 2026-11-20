"""Entry script for the frozen build (PyInstaller needs a file, not a module path)."""
import sys

from geohydro.desktop.app import main

if __name__ == "__main__":
    sys.exit(main())
