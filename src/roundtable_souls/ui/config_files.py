"""Edit a DLL mod's own settings files from its row on the Mods page: the files found beside it, and any the user
attached to it (a mod that reads a differently named file, like SkeletonMan's skeleton_mods.txt)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout
from qfluentwidgets import ComboBox, SubtitleLabel
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.mods import configs
from roundtable_souls.ui.dialogs import Dialog, ask_unsaved
from roundtable_souls.ui.theme import ghost_btn, hint
from roundtable_souls.ui.widgets.panels import EditorPanel


class ConfigFilesDialog(Dialog):
    """files: configs.files_for() rows. tie(path) / untie(path) store the choice and return the new rows."""

    def __init__(self, parent, dll: Path, files: list[dict], tie, untie, toast):
        super().__init__(parent)
        self.dll, self.files, self._tie, self._untie, self._toast = Path(dll), list(files), tie, untie, toast
        self._loaded = None  # {path, encoding, crlf} of the file in the editor
        self.widget.setMinimumWidth(min(820, max(560, parent.width() - 140)))
        self.viewLayout.setSpacing(8)
        self.viewLayout.addWidget(SubtitleLabel(f"Settings for {self.dll.name}"))
        self.about = hint("")
        self.about.setWordWrap(True)
        self.viewLayout.addWidget(self.about)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.pick = ComboBox()
        self.pick.currentIndexChanged.connect(self._on_pick)
        row.addWidget(self.pick, 1)
        self.tie_btn = ghost_btn("Attach a file...", FI.LINK)
        self.tie_btn.setToolTip("Point at a settings file this mod reads that is not found automatically.")
        self.tie_btn.clicked.connect(self._on_tie)
        row.addWidget(self.tie_btn)
        self.untie_btn = ghost_btn("Detach", FI.CANCEL)
        self.untie_btn.setToolTip("Forget this file for this mod. The file itself stays.")
        self.untie_btn.clicked.connect(self._on_untie)
        row.addWidget(self.untie_btn)
        self.viewLayout.addLayout(row)
        self.panel = EditorPanel(
            "The mod's settings.",
            "Save",
            self._save,
            on_discard=self._reload,
            min_height=320,
            clean_note="Matches the file. The mod reads it at the next launch.",
            primary_tip="Write the file; one .bak of the previous version is kept.",
        )
        self.panel.bar.secondary.setToolTip("Read the file again and drop the edits.")
        self.viewLayout.addWidget(self.panel)
        self.hideYesButton()
        self.cancelButton.setText("Close")
        self._fill(0)

    # -------------------------------------------------------------- choosing a file
    def _label(self, f: dict) -> str:
        how = "attached" if f["how"] == "tied" else "beside it"
        return f"{f['path'].name}  ·  {how}" + ("" if f["exists"] else "  ·  missing")

    def _fill(self, index: int):
        self.pick.blockSignals(True)
        self.pick.clear()
        for f in self.files:
            self.pick.addItem(self._label(f))
        self.pick.blockSignals(False)
        has = bool(self.files)
        self.pick.setVisible(has)
        self.panel.setVisible(has)
        self.about.setText(
            "Found beside the DLL, or attached to it by you. Edits apply the next time the game starts."
            if has
            else "No settings file found beside this DLL. If the mod reads one (its readme names it), attach it here."
        )
        if has:
            self.pick.setCurrentIndex(min(index, len(self.files) - 1))
            self._load(self.files[self.pick.currentIndex()])
        self._refresh_buttons()

    def _refresh_buttons(self):
        cur = self._current()
        self.untie_btn.setVisible(bool(cur and cur["how"] == "tied"))

    def _current(self):
        i = self.pick.currentIndex()
        return self.files[i] if self.files and 0 <= i < len(self.files) else None

    def _settle(self, action: str) -> bool:
        """Unsaved edits: Save / Discard / Cancel before moving on. True when it is fine to go on."""
        if not self.panel.dirty or self._loaded is None:
            return True
        choice = ask_unsaved(self, [self._loaded["path"].name], action)
        if choice is None:
            return False
        return self._save() if choice == "save" else True

    def _on_pick(self, index: int):
        f = self._current()
        if f is None or (self._loaded and f["path"] == self._loaded["path"]):
            return
        if not self._settle("switching files"):
            back = next((i for i, x in enumerate(self.files) if self._loaded and x["path"] == self._loaded["path"]), 0)
            self.pick.blockSignals(True)
            self.pick.setCurrentIndex(back)
            self.pick.blockSignals(False)
            return
        self._load(f)
        self._refresh_buttons()

    # -------------------------------------------------------------- the file itself
    def _load(self, f: dict):
        p = f["path"]
        self.panel.edit.setReadOnly(False)
        try:
            got = configs.read(p)
        except FileNotFoundError:
            self._loaded = None
            self.panel.set_baseline("", f"{p.name} is missing. Detach it, or put the file back.", str(p))
            self.panel.edit.setReadOnly(True)
            self.panel.bar.setEnabled(False)
            return
        except (configs.ConfigError, OSError) as e:
            self._loaded = None
            self.panel.set_baseline("", str(e), str(p))
            self.panel.edit.setReadOnly(True)
            self.panel.bar.setEnabled(False)
            return
        self._loaded = {"path": p, "encoding": got["encoding"], "crlf": got["crlf"]}
        self.panel.bar.setEnabled(True)
        self._set_lang(configs.lang_for(p))
        self.panel.set_baseline(got["text"], str(p), str(p))

    def _set_lang(self, lang: str):
        hl = getattr(self.panel.edit, "_hl", None)
        if hl is not None and hl.kind != lang:
            hl.kind = lang
            hl.restyle()
        self.panel.edit.lang = lang  # Ctrl+/ uses the file's own comment mark

    def _reload(self):
        f = self._current()
        if f:
            self._load(f)

    def _save(self) -> bool:
        if self._loaded is None:
            return False
        try:
            configs.write(self._loaded["path"], self.panel.text(), self._loaded["encoding"], self._loaded["crlf"])
        except (configs.ConfigError, OSError) as e:
            self._toast("Could not save", str(e), error=True)
            return False
        self.panel.mark_clean()
        self._toast("Saved", f"{self._loaded['path'].name}. The mod reads it at the next launch.")
        return True

    # -------------------------------------------------------------- ties
    def _on_tie(self):
        if not self._settle("attaching a file"):
            return
        start = str(self.dll.parent)
        p, _ = QFileDialog.getOpenFileName(
            self,
            f"A settings file {self.dll.name} reads",
            start,
            "Settings (*.ini *.txt *.toml *.json *.cfg *.conf *.yaml *.yml *.xml);;All files (*)",
        )
        if not p:
            return
        try:
            configs.read(Path(p))
        except (configs.ConfigError, OSError) as e:
            self._toast("Not a settings file", str(e), error=True)
            return
        self.files = self._tie(Path(p))
        self._loaded = None
        self._fill(
            next((i for i, f in enumerate(self.files) if configs.key_for(f["path"]) == configs.key_for(Path(p))), 0)
        )

    def _on_untie(self):
        f = self._current()
        if not f or f["how"] != "tied" or not self._settle("detaching it"):
            return
        self.files = self._untie(f["path"])
        self._loaded = None
        self._fill(0)

    def reject(self):
        if self._settle("closing"):
            super().reject()
