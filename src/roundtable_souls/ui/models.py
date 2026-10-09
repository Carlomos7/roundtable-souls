"""List models the QML pages bind to: rows of plain values (dicts, or dataclasses turned into dicts) exposed as a
QAbstractListModel, one role per key, so a Repeater or ListView reads `model.title` and updates when the rows do."""

from __future__ import annotations

import dataclasses
from typing import Any

from PySide6.QtCore import Property, QAbstractListModel, QByteArray, QModelIndex, QPersistentModelIndex, Qt, Signal


def plain(value: Any) -> Any:
    """A dataclass (or a list / tuple / dict of them) as plain dicts and lists, the shapes QML reads."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


class RowsModel(QAbstractListModel):
    """Rows with the keys given at construction; set_rows() replaces them all. `count` is bindable from QML."""

    countChanged = Signal()

    def __init__(self, keys: tuple[str, ...], parent=None):
        super().__init__(parent)
        self._keys = keys
        self._rows: list[dict] = []

    def set_rows(self, rows) -> None:
        self.beginResetModel()
        self._rows = [plain(r) for r in rows]
        self.endResetModel()
        self.countChanged.emit()

    def rows(self) -> list[dict]:
        return list(self._rows)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        key = self._role_key(role)
        return self._rows[index.row()].get(key) if key else None

    def roleNames(self) -> dict[int, QByteArray]:
        return {Qt.ItemDataRole.UserRole + 1 + i: QByteArray(k.encode()) for i, k in enumerate(self._keys)}

    def _role_key(self, role: int) -> str | None:
        i = role - Qt.ItemDataRole.UserRole - 1
        return self._keys[i] if 0 <= i < len(self._keys) else None

    def _count(self) -> int:
        return len(self._rows)

    count = Property(int, _count, notify=countChanged)
