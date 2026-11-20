"""Write packaging/version_info.txt (Windows file properties) from geohydro.__version__."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from geohydro import APP_NAME, __version__  # noqa: E402

parts = [int(p) for p in __version__.split(".")[:3]] + [0]
t = tuple(parts[:4])
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{APP_NAME}'),
      StringStruct('FileDescription', '{APP_NAME} - scientific mapping and hydrology'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'GeoHydroPro'),
      StringStruct('LegalCopyright', 'Proprietary. All rights reserved.'),
      StringStruct('OriginalFilename', 'GeoHydroPro.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
(ROOT / "packaging" / "version_info.txt").write_text(text, encoding="utf-8")
print("wrote packaging/version_info.txt for", __version__)
