"""GeoHydro Pro visual identity: dark navy chrome, light working areas,
turquoise/blue accents."""

NAVY = "#0B1F3A"
NAVY_2 = "#13325C"
NAVY_3 = "#1E4378"
TURQUOISE = "#14B8A6"
TURQUOISE_DARK = "#0E9384"
BLUE = "#2F6FED"
WORK_BG = "#EEF2F6"
PANEL_BG = "#FFFFFF"
BORDER = "#D3DBE5"
TEXT = "#1A2433"
MUTED = "#6A7686"
PLANNED = "#9AA5B4"
ERROR = "#C93C3C"
WARNING = "#B7791F"
SUCCESS = "#1F8A5B"

FONT_FAMILY = "Inter, Segoe UI, Noto Sans, DejaVu Sans, sans-serif"

STYLESHEET = f"""
* {{ font-family: {FONT_FAMILY}; font-size: 9.5pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {WORK_BG}; }}

QMenuBar {{ background: {NAVY}; color: white; padding: 2px 6px; border: none; }}
QMenuBar::item {{ background: transparent; color: #DCE6F2; padding: 5px 9px; border-radius: 3px; }}
QMenuBar::item:selected {{ background: {NAVY_3}; color: white; }}
QMenu {{ background: {PANEL_BG}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 26px 5px 26px; border-radius: 3px; }}
QMenu::item:selected {{ background: #E3F6F4; color: {NAVY}; }}
QMenu::item:disabled {{ color: {PLANNED}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QMenu::section {{ color: {MUTED}; padding: 4px 10px; font-weight: 600; }}

#Ribbon {{ background: {NAVY}; border: none; }}
#MenuHost {{ background: {NAVY}; }}
#Ribbon QTabBar::tab {{ background: transparent; color: #B8C7DA; padding: 6px 16px; margin-right: 2px;
    border-top-left-radius: 4px; border-top-right-radius: 4px; font-weight: 600; }}
#Ribbon QTabBar::tab:selected {{ background: #F7F9FB; color: {NAVY}; }}
#Ribbon QTabBar::tab:hover:!selected {{ background: {NAVY_2}; color: white; }}
#Ribbon QTabWidget::pane {{ border: none; background: #F7F9FB; border-bottom: 1px solid {BORDER}; }}
#RibbonPage {{ background: #F7F9FB; }}
#RibbonGroup {{ background: transparent; border-right: 1px solid {BORDER}; }}
#RibbonGroupTitle {{ color: {MUTED}; font-size: 8pt; }}
#RibbonGroupTitlePlanned {{ color: {PLANNED}; font-size: 8pt; font-style: italic; }}
#RibbonPage QToolButton {{ border: 1px solid transparent; border-radius: 4px; padding: 3px 4px;
    background: transparent; min-width: 52px; font-size: 8.5pt; }}
#RibbonPage QToolButton:hover {{ background: #E3F6F4; border-color: #A6E3DC; }}
#RibbonPage QToolButton:pressed {{ background: #C9EEE9; }}
#RibbonPage QToolButton:disabled {{ color: {PLANNED}; }}
#BrandLabel {{ color: white; font-weight: 700; font-size: 10.5pt; padding: 0 10px; }}
#BrandTag {{ color: {TURQUOISE}; font-size: 8pt; padding: 0 10px; }}

QDockWidget {{ color: white; font-weight: 600; }}
QDockWidget::title {{ background: {NAVY_2}; color: white; padding: 5px 8px; text-align: left; }}
QDockWidget > QWidget {{ background: {PANEL_BG}; }}

QTreeView, QTreeWidget, QTableView, QListWidget, QPlainTextEdit, QTextEdit {{
    background: {PANEL_BG}; border: 1px solid {BORDER}; selection-background-color: #CDEFEA;
    selection-color: {NAVY}; alternate-background-color: #F6F8FB; }}
QTreeView::item {{ padding: 3px 2px; }}
QHeaderView::section {{ background: #E9EEF4; color: {TEXT}; border: none; border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER}; padding: 4px 6px; font-weight: 600; }}

QMdiArea {{ background: {WORK_BG}; }}
QMdiArea QTabBar::tab {{ background: #DDE4EC; color: {TEXT}; padding: 6px 14px; margin-right: 1px;
    border-top-left-radius: 4px; border-top-right-radius: 4px; }}
QMdiArea QTabBar::tab:selected {{ background: {PANEL_BG}; color: {NAVY}; border-top: 2px solid {TURQUOISE}; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; background: {PANEL_BG}; }}
QTabBar::tab {{ background: #E4EAF1; padding: 5px 12px; border: 1px solid {BORDER}; border-bottom: none;
    border-top-left-radius: 3px; border-top-right-radius: 3px; margin-right: 1px; }}
QTabBar::tab:selected {{ background: {PANEL_BG}; color: {NAVY}; font-weight: 600; }}

QPushButton {{ background: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 14px; }}
QPushButton:hover {{ border-color: {TURQUOISE}; background: #F1FBFA; }}
QPushButton:disabled {{ color: {PLANNED}; }}
QPushButton#Primary {{ background: {TURQUOISE_DARK}; border-color: {TURQUOISE_DARK}; color: white; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {TURQUOISE}; }}
QPushButton#Primary:disabled {{ background: #9FD9D2; border-color: #9FD9D2; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {PANEL_BG}; border: 1px solid {BORDER};
    border-radius: 3px; padding: 3px 6px; min-height: 20px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {TURQUOISE}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 5px; margin-top: 12px; padding-top: 8px;
    background: {PANEL_BG}; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {NAVY_2}; }}

QStatusBar {{ background: {NAVY}; color: #DCE6F2; }}
QStatusBar QLabel {{ color: #DCE6F2; padding: 0 8px; border-left: 1px solid {NAVY_3}; }}
QStatusBar QProgressBar {{ background: {NAVY_2}; border: none; border-radius: 3px; max-height: 10px;
    min-width: 120px; }}
QStatusBar QProgressBar::chunk {{ background: {TURQUOISE}; border-radius: 3px; }}

QToolTip {{ background: {NAVY}; color: white; border: 1px solid {NAVY_3}; padding: 4px; }}
QSplitter::handle {{ background: {BORDER}; }}
"""
