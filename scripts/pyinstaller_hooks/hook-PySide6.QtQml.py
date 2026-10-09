"""PyInstaller hook for PySide6.QtQml, in place of PyInstaller's own (scripts/build.py passes this folder with
--additional-hooks-dir, which takes precedence). PyInstaller's hook collects every QML module Qt ships, Qt WebEngine,
Qt 3D and Qt Quick 3D included: about 290 MB the launcher never loads. This one collects the QML modules the
launcher imports (src/roundtable_souls/data/self-test.json's qml_modules, what pyside6-qmlimportscanner finds in
ui/qml) and the modules those depend on, read from their qmldir files (import and depends lines) and from the imports
in their own .qml files. `--self-test` on the build proves the set is complete: a missing module fails it."""

import json
import re
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

ROOT = Path(__file__).resolve().parents[2]
WANTED = json.loads((ROOT / "src" / "roundtable_souls" / "data" / "self-test.json").read_text(encoding="utf-8"))[
    "qml_modules"
]
_QMLDIR_DEP = re.compile(r"^\s*(?:import|depends)\s+([A-Za-z_][\w.]*)", re.MULTILINE)
_QML_IMPORT = re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)", re.MULTILINE)

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

qml_root = Path(pyside6_library_info.location["QmlImportsPath"]).resolve()
qml_dest = Path(pyside6_library_info.qt_rel_dir) / "qml"


def module_dir(name: str) -> Path:
    return qml_root.joinpath(*name.split("."))


def closure(names) -> list[str]:
    """The modules named and every Qt module they need, as far as Qt ships them (our own modules are data files)."""
    seen: set[str] = set()
    todo = list(names)
    while todo:
        name = todo.pop()
        folder = module_dir(name)
        if name in seen or not (folder / "qmldir").is_file():
            continue
        seen.add(name)
        todo += _QMLDIR_DEP.findall((folder / "qmldir").read_text(encoding="utf-8"))
        for qml in folder.glob("*.qml"):
            todo += _QML_IMPORT.findall(qml.read_text(encoding="utf-8", errors="replace"))
    return sorted(seen)


def dest_of(src: Path) -> str:
    """Where a collected file goes (its folder), or a collected folder (itself), under the bundle's qml folder."""
    src = Path(src)
    return str(qml_dest / (src.relative_to(qml_root) if src.is_dir() else src.parent.relative_to(qml_root)))


for name in closure(WANTED):
    plugin_binaries, plugin_datas = pyside6_library_info._process_qml_plugin(module_dir(name) / "qmldir")
    binaries += [(str(src), dest_of(src)) for src in plugin_binaries]
    datas += [(str(src), dest_of(src)) for src in plugin_datas]
