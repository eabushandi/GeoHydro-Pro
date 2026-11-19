"""Original line icons drawn as inline SVG (no third-party icon assets)."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

_S = 'fill="none" stroke="{c}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'

# 24x24 viewBox path bodies. "{a}" = accent colour.
_ICONS = {
    "new": '<path d="M6 3h8l4 4v14H6z" {s}/><path d="M14 3v4h4" {s}/><path d="M12 11v6M9 14h6" stroke="{a}" stroke-width="1.8" stroke-linecap="round"/>',
    "open": '<path d="M3 7h6l2 2h10v10H3z" {s}/><path d="M3 11h18" {s}/>',
    "save": '<path d="M4 4h13l3 3v13H4z" {s}/><path d="M8 4v5h8V4" {s}/><rect x="7" y="13" width="10" height="7" rx="1" stroke="{a}" stroke-width="1.6" fill="none"/>',
    "import": '<path d="M12 3v11" stroke="{a}" stroke-width="1.8" stroke-linecap="round"/><path d="M8 10l4 4 4-4" stroke="{a}" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 15v5h16v-5" {s}/>',
    "table": '<rect x="3" y="4" width="18" height="16" rx="1.5" {s}/><path d="M3 9h18M3 14h18M9 4v16M15 4v16" {s}/>',
    "points": '<rect x="3" y="3" width="18" height="18" rx="1.5" {s}/><circle cx="8" cy="9" r="1.6" fill="{a}"/><circle cx="15" cy="7" r="1.6" fill="{a}"/><circle cx="11" cy="14" r="1.6" fill="{a}"/><circle cx="17" cy="16" r="1.6" fill="{a}"/><circle cx="7" cy="17" r="1.6" fill="{a}"/>',
    "stats": '<path d="M4 20V4" {s}/><path d="M4 20h16" {s}/><rect x="7" y="12" width="3" height="6" fill="{a}"/><rect x="12" y="8" width="3" height="10" fill="{a}"/><rect x="17" y="5" width="3" height="13" fill="{a}"/>',
    "qc": '<path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z" {s}/><path d="M9 12l2 2 4-4" stroke="{a}" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "export": '<path d="M12 14V3" stroke="{a}" stroke-width="1.8" stroke-linecap="round"/><path d="M8 7l4-4 4 4" stroke="{a}" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 15v5h16v-5" {s}/>',
    "delete": '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13" {s}/>',
    "grid": '<path d="M4 4h16v16H4z" {s}/><path d="M4 9.3h16M4 14.6h16M9.3 4v16M14.6 4v16" stroke="{a}" stroke-width="1.2"/>',
    "kriging": '<path d="M3 19c3-9 6-12 9-12s6 3 9 12" {s}/><circle cx="6" cy="15" r="1.4" fill="{a}"/><circle cx="12" cy="7" r="1.4" fill="{a}"/><circle cx="17" cy="11" r="1.4" fill="{a}"/>',
    "variogram": '<path d="M4 20V4M4 20h16" {s}/><path d="M5 18c3-8 7-10 14-11" stroke="{a}" stroke-width="1.8" fill="none" stroke-linecap="round"/>',
    "contour": '<path d="M4 16c3-6 7-7 10-5s5 1 6-2" {s}/><path d="M4 20c4-5 8-5 11-3s4 1 5-1" {s}/><path d="M6 11c2-4 5-6 8-4" stroke="{a}" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
    "filled": '<path d="M3 21V9c4-4 7 2 10-1s5-4 8-2v15z" fill="{a}" opacity="0.35"/><path d="M3 21V14c4-3 7 1 10-1s5-3 8-1v9z" fill="{a}" opacity="0.7"/><rect x="3" y="3" width="18" height="18" {s}/>',
    "relief": '<path d="M3 18l5-7 4 4 3-5 6 8z" fill="{a}" opacity="0.5"/><path d="M3 18l5-7 4 4 3-5 6 8z" {s}/>',
    "layout": '<rect x="3" y="3" width="18" height="18" rx="1" {s}/><rect x="6" y="6" width="12" height="8" stroke="{a}" stroke-width="1.4" fill="none"/><path d="M6 17h7M16 17h2" {s}/>',
    "surface3d": '<path d="M3 15l9-5 9 5-9 5z" {s}/><path d="M3 15c3-6 5-9 9-9s6 3 9 9" stroke="{a}" stroke-width="1.6" fill="none"/>',
    "slope": '<path d="M3 20h18L3 6z" {s}/><path d="M8 20a5 5 0 00-2-4" stroke="{a}" stroke-width="1.6" fill="none"/>',
    "hillshade": '<circle cx="18" cy="6" r="2.5" stroke="{a}" stroke-width="1.6" fill="none"/><path d="M2 20l6-9 4 5 3-3 7 7z" {s}/>',
    "profile": '<path d="M3 17c3-1 4-6 7-6s3 4 6 3 3-5 5-6" {s}/><path d="M3 21h18" stroke="{a}" stroke-width="1.6"/>',
    "volume": '<path d="M4 8l8-4 8 4-8 4z" {s}/><path d="M4 8v8l8 4 8-4V8" {s}/><path d="M12 12v8" stroke="{a}" stroke-width="1.6"/>',
    "drop": '<path d="M12 3c4 5 6 8 6 11a6 6 0 01-12 0c0-3 2-6 6-11z" {s}/><path d="M9 15a3 3 0 003 3" stroke="{a}" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
    "flow": '<path d="M4 4l6 6M10 10l4 2M14 12l6 8" {s}/><path d="M18 20h2v-2" stroke="{a}" stroke-width="1.6" fill="none"/>',
    "watershed": '<path d="M3 12c2-6 5-8 9-8s7 2 9 8c-2 5-5 8-9 8s-7-3-9-8z" {s}/><path d="M12 5v15M12 12l-4-3M12 15l4-3" stroke="{a}" stroke-width="1.4" fill="none"/>',
    "wave": '<path d="M2 14c2.5 0 2.5-3 5-3s2.5 3 5 3 2.5-3 5-3 2.5 3 5 3" stroke="{a}" stroke-width="1.8" fill="none" stroke-linecap="round"/><path d="M2 19c2.5 0 2.5-3 5-3s2.5 3 5 3 2.5-3 5-3 2.5 3 5 3" {s}/><path d="M4 9l4-5 4 5" {s}/>',
    "transect": '<path d="M3 18c5-2 9-6 18-10" {s}/><path d="M6 10l3 9M11 7l3 9M16 5l3 9" stroke="{a}" stroke-width="1.4"/>',
    "flood": '<path d="M4 11l8-6 8 6v9H4z" {s}/><path d="M2 17c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2" stroke="{a}" stroke-width="1.8" fill="none"/>',
    "well": '<path d="M9 3h6v4H9z" {s}/><path d="M12 7v14" {s}/><path d="M4 15h16" stroke="{a}" stroke-width="1.6" stroke-dasharray="2 2"/>',
    "report": '<path d="M6 3h9l4 4v14H6z" {s}/><path d="M9 12h7M9 15h7M9 18h4" {s}/><path d="M9 7h3" stroke="{a}" stroke-width="1.6"/>',
    "pdf": '<path d="M6 3h9l4 4v14H6z" {s}/><text x="8" y="17" font-size="6" font-family="sans-serif" font-weight="700" fill="{a}">PDF</text>',
    "crs": '<circle cx="12" cy="12" r="8" {s}/><path d="M4 12h16M12 4c3 3 3 13 0 16M12 4c-3 3-3 13 0 16" {s}/><circle cx="12" cy="12" r="1.8" fill="{a}"/>',
    "history": '<path d="M4 12a8 8 0 108-8" {s}/><path d="M4 4v4h4" {s}/><path d="M12 8v4l3 2" stroke="{a}" stroke-width="1.8" fill="none" stroke-linecap="round"/>',
    "properties": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" {s}/><circle cx="16" cy="6" r="2" stroke="{a}" stroke-width="1.6" fill="none"/><circle cx="10" cy="12" r="2" stroke="{a}" stroke-width="1.6" fill="none"/><circle cx="18" cy="18" r="2" stroke="{a}" stroke-width="1.6" fill="none"/>',
    "console": '<rect x="3" y="4" width="18" height="16" rx="1.5" {s}/><path d="M7 9l3 3-3 3" stroke="{a}" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/><path d="M12 15h5" {s}/>',
    "explorer": '<path d="M4 4h6v4H4zM4 16h6v4H4zM14 10h6v4h-6z" {s}/><path d="M7 8v8M7 12h7" stroke="{a}" stroke-width="1.6"/>',
    "folder": '<path d="M3 7h6l2 2h10v10H3z" {s}/>',
    "raster": '<rect x="3" y="3" width="18" height="18" {s}/><rect x="3" y="3" width="6" height="6" fill="{a}" opacity=".7"/><rect x="9" y="9" width="6" height="6" fill="{a}" opacity=".45"/><rect x="15" y="15" width="6" height="6" fill="{a}" opacity=".25"/>',
    "vector": '<path d="M4 18l6-10 5 6 5-9" {s}/><circle cx="4" cy="18" r="1.6" fill="{a}"/><circle cx="10" cy="8" r="1.6" fill="{a}"/><circle cx="15" cy="14" r="1.6" fill="{a}"/><circle cx="20" cy="5" r="1.6" fill="{a}"/>',
    "map": '<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z" {s}/><path d="M9 4v14M15 6v14" stroke="{a}" stroke-width="1.4"/>',
    "results": '<path d="M4 20h16" {s}/><path d="M6 16l4-5 3 3 5-7" stroke="{a}" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "info": '<circle cx="12" cy="12" r="9" {s}/><path d="M12 11v6" stroke="{a}" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="7.5" r="1.1" fill="{a}"/>',
    "settings": '<circle cx="12" cy="12" r="3" stroke="{a}" stroke-width="1.6" fill="none"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" {s}/>',
    "cloud": '<path d="M7 18h10a4 4 0 000-8 6 6 0 00-11.5 1.5A3.3 3.3 0 007 18z" {s}/><path d="M12 11v5M10 14l2 2 2-2" stroke="{a}" stroke-width="1.6" fill="none"/>',
    "validate": '<circle cx="12" cy="12" r="9" {s}/><path d="M8 12l3 3 5-6" stroke="{a}" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
}

LOGO_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect x="2" y="2" width="60" height="60" rx="13" fill="{theme.NAVY}"/>
<path d="M10 44c8-3 12-13 22-13s14 8 22 6" fill="none" stroke="{theme.TURQUOISE}" stroke-width="3" stroke-linecap="round"/>
<path d="M10 52c9-3 14-9 22-9s13 5 22 4" fill="none" stroke="#5FA8FF" stroke-width="3" stroke-linecap="round"/>
<path d="M14 36c6-2 10-10 18-10s11 5 18 4" fill="none" stroke="#9FE7DE" stroke-width="2" stroke-linecap="round" opacity=".8"/>
<path d="M32 9c5 6 7.5 9.5 7.5 13a7.5 7.5 0 01-15 0c0-3.5 2.5-7 7.5-13z" fill="{theme.TURQUOISE}"/>
<path d="M29 23a3 3 0 003 3" stroke="white" stroke-width="1.6" fill="none" stroke-linecap="round"/>
</svg>"""


def _render(svg: str, size: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def _svg(name: str, color: str, accent: str) -> str:
    body = _ICONS[name].format(s=_S.format(c=color), a=accent, c=color)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    ic = QIcon()
    for size in (16, 24, 32, 48):
        ic.addPixmap(_render(_svg(name, theme.NAVY_2, theme.TURQUOISE_DARK), size), QIcon.Mode.Normal)
        ic.addPixmap(_render(_svg(name, "#AAB4C2", "#C3CBD6"), size), QIcon.Mode.Disabled)
    return ic


@lru_cache(maxsize=None)
def logo_pixmap(size: int = 64) -> QPixmap:
    return _render(LOGO_SVG, size)


@lru_cache(maxsize=None)
def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(_render(LOGO_SVG, s))
    return ic


def names() -> list[str]:
    return sorted(_ICONS)
