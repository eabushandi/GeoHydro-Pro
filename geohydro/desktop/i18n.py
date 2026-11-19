"""Internationalisation hooks.

Phase 1 ships English only. User-visible strings are kept in the desktop
layer (never in the engine) so they can be extracted with ``pyside6-lupdate``
into ``geohydro/desktop/resources/i18n/geohydro_<lang>.ts``. Right-to-left
languages (Arabic) switch the whole interface layout direction.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLocale, Qt, QTranslator
from PySide6.QtWidgets import QApplication

I18N_DIR = Path(__file__).parent / "resources" / "i18n"
AVAILABLE_LANGUAGES = {"en": "English"}
PLANNED_LANGUAGES = {"ar": "العربية (Arabic)"}
RTL_LANGUAGES = {"ar", "he", "fa", "ur"}


def install_language(app: QApplication, code: str = "en") -> bool:
    """Install a translation if available. Returns True if one was loaded."""
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft if code in RTL_LANGUAGES
                           else Qt.LayoutDirection.LeftToRight)
    if code == "en":
        return False
    tr = QTranslator(app)
    if tr.load(QLocale(code), "geohydro", "_", str(I18N_DIR)):
        app.installTranslator(tr)
        return True
    return False
