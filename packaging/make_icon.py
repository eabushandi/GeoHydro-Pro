"""Render the application logo (geohydro/desktop/icons.py) to packaging/geohydro.ico."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from geohydro.desktop.icons import LOGO_SVG, _render  # noqa: E402

images = []
for size in (256, 128, 64, 48, 32, 24, 16):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    _render(LOGO_SVG, size).toImage().save(buf, "PNG")
    out = ROOT / "packaging" / f"_icon_{size}.png"
    out.write_bytes(bytes(buf.data()))
    images.append(Image.open(out).convert("RGBA"))
target = ROOT / "packaging" / "geohydro.ico"
images[0].save(target, sizes=[im.size for im in images], append_images=images[1:])
for size in (256, 128, 64, 48, 32, 24, 16):
    (ROOT / "packaging" / f"_icon_{size}.png").unlink()
print("wrote", target)
