"""A registered QML page in a top-level window of its own (technical specification §8.6 step 9: S5 hosts the Activity
page this way, opened from the Widgets launcher; never embedded in a Widgets window). The QML shell replaces this in
S9 and hosts the same page, adapter and presenter unchanged.

One QQmlApplicationEngine per window, with ui/qml as its import path and the bundled fonts loaded once; every QML
warning the engine reports is kept in `warnings` (the self-test fails on any)."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine, QQmlError
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from roundtable_souls.platform import data_folder
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.pages.registry import QmlPage

UI = Path(__file__).resolve().parent
QML_DIR = UI / "qml"
FONTS_DIR = UI / "assets" / "fonts"
WINDOW_QML = QML_DIR / "PageWindow.qml"

_fonts_loaded: list[str] = []


def load_fonts() -> list[str]:
    """Register the bundled fonts with Qt (once); the families they add."""
    if not _fonts_loaded:
        for ttf in sorted(FONTS_DIR.glob("*.ttf")):
            font_id = QFontDatabase.addApplicationFont(str(ttf))
            _fonts_loaded.extend(QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else [])
    return sorted(set(_fonts_loaded))


def use_qml_cache_folder() -> Path | None:
    """Keep Qt's compiled-QML cache in this run's data folder (cache/qmlcache). Left alone, Qt names the folder after
    the program (%LOCALAPPDATA%/<name>/cache), which for the packaged build is the real data folder's name: a
    self-test or a test build in a temporary data folder would write beside the user's data. With no data folder set
    (a test without one), the disk cache is off for the run."""
    try:
        folder = data_folder.data_root() / "cache" / "qmlcache"
    except RuntimeError:
        os.environ["QML_DISABLE_DISK_CACHE"] = "1"
        return None
    os.environ["QML_DISK_CACHE_PATH"] = str(folder)
    return folder


def theme_mode(setting: str) -> str:
    """The window's theme from the launcher's theme setting (dark | light today; tarnished and system later)."""
    return setting if setting in ("dark", "light", "tarnished", "system") else "dark"


class PageWindow(QObject):
    """The window for one registered page. show() builds it the first time and brings it forward after that."""

    def __init__(self, entry: QmlPage, host, theme: str = "dark", parent: QObject | None = None):
        super().__init__(parent)
        self.entry = entry
        self.host = host
        self.theme = theme_mode(theme)
        self.notifier = Notifier(self)
        self.adapter = entry.make_adapter(host, self.notifier)
        if isinstance(self.adapter, QObject) and self.adapter.parent() is None:
            self.adapter.setParent(self)  # it lives as long as the window that binds to it
        self.engine: QQmlApplicationEngine | None = None
        self.warnings: list[str] = []

    @property
    def window(self) -> QQuickWindow | None:
        roots = self.engine.rootObjects() if self.engine is not None else []
        return roots[0] if roots and isinstance(roots[0], QQuickWindow) else None

    def build(self) -> bool:
        """Load the window's QML (hidden); False when it did not load."""
        if self.engine is not None:
            return self.window is not None
        use_qml_cache_folder()  # before the engine compiles anything
        QQuickStyle.setStyle("Basic")
        load_fonts()
        self.engine = QQmlApplicationEngine(self)
        self.engine.addImportPath(str(QML_DIR))
        self.engine.warnings.connect(self._warned)
        self.engine.setInitialProperties(
            {
                "adapter": self.adapter,
                "notifier": self.notifier,
                "pageUrl": QUrl.fromLocalFile(str(QML_DIR / self.entry.qml)),
                "themeMode": self.theme,
                "visible": False,
            }
        )
        self.engine.load(QUrl.fromLocalFile(str(WINDOW_QML)))
        return self.window is not None

    def _warned(self, errors: list[QQmlError]) -> None:
        self.warnings.extend(e.toString() for e in errors)

    def show(self) -> bool:
        win = self.window if self.build() else None
        if win is None:
            return False
        win.show()
        win.raise_()
        win.requestActivate()
        return True

    def set_theme(self, theme: str) -> None:
        self.theme = theme_mode(theme)
        if self.window is not None:
            self.window.setProperty("themeMode", self.theme)

    def page_item(self):
        """The page's root item once loaded (tests and the self-test)."""
        win = self.window
        return win.findChild(QObject, f"{self.entry.name}Page") if win is not None else None

    def close(self) -> None:
        win = self.window
        if win is not None:
            win.close()

    def dispose(self) -> None:
        """Close the window and free it: the QML first, then its engine (the adapter outlives both)."""
        win = self.window
        if win is not None:
            win.close()
            win.deleteLater()
        if self.engine is not None:
            self.engine.deleteLater()
            self.engine = None
