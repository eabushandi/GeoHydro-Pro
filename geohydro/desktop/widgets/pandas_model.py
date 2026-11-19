"""Read-only Qt table model over a pandas DataFrame (lazy, large-table safe)."""

from __future__ import annotations

import math

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor


class DataFrameModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, highlight_columns=(), row_status=None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()
        self._highlight = set(highlight_columns)
        self._status = row_status  # optional sequence: "ok" or reason per row

    def set_frame(self, df: pd.DataFrame, highlight_columns=(), row_status=None):
        self.beginResetModel()
        self._df = df
        self._highlight = set(highlight_columns)
        self._status = row_status
        self.endResetModel()

    def frame(self) -> pd.DataFrame:
        return self._df

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            v = self._df.iat[r, c]
            if role == Qt.ItemDataRole.ToolTipRole and self._status is not None:
                st = self._status[r]
                if st != "ok":
                    return f"Excluded: {st}"
            if isinstance(v, float):
                if math.isnan(v):
                    return ""
                return f"{v:.10g}"
            return "" if v is None else str(v)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            v = self._df.iat[r, c]
            if isinstance(v, (int, float)):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.BackgroundRole:
            if self._status is not None and self._status[r] != "ok":
                return QBrush(QColor("#FBE3E3"))
            if self._df.columns[c] in self._highlight:
                return QBrush(QColor("#E6F7F5"))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)
