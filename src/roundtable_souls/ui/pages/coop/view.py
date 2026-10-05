"""Co-op: Seamless Co-op's password, scaling and settings, sharing them, and the save bar.

Part of the window: ui/shell.Launcher inherits CoopView, so its methods share the window's state (self). Moved
from ui/window.py as it was; the page's presenter (plain Python, no Qt) comes in the page-by-page work."""

# The window's state is spread over the shell and the page views, which pyright cannot follow across mixins.
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    LineEdit,
    PasswordLineEdit,
    SpinBox,
    SwitchButton,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.services.coop import (
    CUSTOM,
    SAVE_KINDS,
    SCALING_KEYS,
    SCALING_LABELS,
    SCALING_PRESETS,
    VOLUME_STOPS,
    choice_label,
    export_text,
    label_of,
    parse_settings_json,
    plan_import,
    read_settings_meta,
    setting_face,
    write_keys,
    write_password,
)
from roundtable_souls.services.play import (
    has_password,
    preset_of,
    read_password,
    read_scaling,
    scaling_spec,
)
from roundtable_souls.ui.dialogs.common import (
    confirm,
)
from roundtable_souls.ui.theme import (
    ACCENT,
    ACCENT_LIGHT,
    HINT,
    HINT_ON_LIGHT,
    hint,
)
from roundtable_souls.ui.widgets.cards import ExpandGroupSettingCard, SettingRow, card, count_label
from roundtable_souls.ui.widgets.layout import page, titled
from roundtable_souls.ui.widgets.panels import ActionBar, EditorPanel


class CoopView:
    """The coop page's widgets and handlers (a mixin of ui/shell.Launcher)."""

    def _layout_scaling(self, cols):
        if cols == getattr(self, "_scal_cols", None):
            return
        self._scal_cols = cols
        for i, (lab, sp) in enumerate(zip(self.scal_labs, self.spins)):
            self.scal_grid.addWidget(lab, (i // cols) * 2, i % cols)
            self.scal_grid.addWidget(sp, (i // cols) * 2 + 1, i % cols)
        for c in range(3):
            self.scal_grid.setColumnStretch(c, 1 if c < cols else 0)

    # ---------------------------------------------------------------- Co-op page
    def _build_coop(self):
        root = QWidget()
        root.setObjectName("coopPage")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.coop_head = QWidget()
        hl = QVBoxLayout(self.coop_head)
        hl.setContentsMargins(40, 28, 40, 8)
        hl.setSpacing(0)
        titled(hl, "Co-op", FI.PEOPLE, "Seamless Co-op: difficulty, options, and the password where the mod has one.")
        outer.addWidget(self.coop_head)
        self.coop_scroll, lay = page("coopScroll")
        lay.setContentsMargins(40, 12, 40, 16)
        outer.addWidget(self.coop_scroll, 1)
        off, offl = card("No co-op in this setup", FI.PEOPLE)
        offl.addWidget(
            hint(
                "This setup does not load Seamless Co-op, so there is no password or difficulty to set. Pick a setup that includes it on the Play page."
            )
        )
        lay.addWidget(off)
        self.coop_off = off
        off.hide()
        self.coop_form = []
        c, cl = card("Session password", FI.CERTIFICATE)
        self.pw_card = c
        row = QHBoxLayout()
        self.pw = PasswordLineEdit()
        self.pw.setMinimumWidth(120)
        self.pw.setPlaceholderText("Friends type this to join")
        self.pw.textChanged.connect(self._on_pw_edit)
        row.addWidget(self.pw, 1)
        cl.addLayout(row)
        self.pw_hint = hint()
        cl.addWidget(self.pw_hint)
        lay.addWidget(c)
        self.coop_form.append(c)
        c, cl = card("Difficulty", FI.SPEED_HIGH)
        self.scal_about = hint("Percent per extra player. Only the host's numbers count.")
        cl.addWidget(self.scal_about)
        self.scaling = None  # the ScalingSpec of the loaded ini: which keys, labels and presets
        preset_row = QWidget()
        row = QHBoxLayout(preset_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.preset = ComboBox()
        self.preset.addItems(list(SCALING_PRESETS) + [CUSTOM])
        self.preset.setMinimumWidth(160)
        self.preset.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.preset.currentTextChanged.connect(self._on_preset)
        row.addWidget(BodyLabel("Preset"))
        row.addWidget(self.preset, 1)
        cl.addWidget(preset_row)
        self.preset_row = preset_row
        self.scal_grid = QGridLayout()
        self.scal_grid.setHorizontalSpacing(12)
        self.scal_grid.setVerticalSpacing(6)
        self.spins = []
        self.scal_labs = []
        for _i, label in enumerate(SCALING_LABELS):
            lab = CaptionLabel(label)
            self.scal_labs.append(lab)
            sp = SpinBox()
            sp.setRange(0, 500)
            sp.setSingleStep(5)
            sp.setMinimumWidth(72)
            sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            sp.valueChanged.connect(self._on_scaling_edit)
            self.spins.append(sp)
        self._scal_cols = None
        self._layout_scaling(3)
        cl.addLayout(self.scal_grid)
        self.scal_hint = hint()
        cl.addWidget(self.scal_hint)
        lay.addWidget(c)
        self.coop_form.append(c)
        self.other_host = QWidget()
        self.all_box = QVBoxLayout(self.other_host)
        self.all_box.setContentsMargins(0, 0, 0, 0)
        self.all_box.setSpacing(10)
        lay.addWidget(self.other_host)
        self.coop_form.append(self.other_host)
        self.all_dirty = {}
        self.all_file = {}
        share = ExpandGroupSettingCard(FI.SHARE, "Share with a friend", "Copy yours, or paste a friend's and apply.")
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 12, 16, 14)
        self.share_panel = EditorPanel(
            "Paste a friend's settings, or copy yours.",
            "Apply",
            self.share_apply,
            tools=(
                ("Copy", FI.COPY, self.share_copy, "Copy the text to send it to a friend."),
                ("Paste", FI.PASTE, self.share_paste, "Replace the text with what is on the clipboard."),
                ("Open file...", FI.FOLDER, self.share_load, "Load settings someone saved to a file."),
                ("Save as...", FI.DOWNLOAD, self.share_save, "Save the text to a file."),
            ),
            on_discard=self.share_fill,
            lang="json",
            wrap=True,
            min_height=190,
            clean_note="Your current settings.",
            dirty_note="Different from your settings. Apply writes the differences, after a confirm.",
            primary_tip="Write the settings in the text to your co-op ini (you see every change first).",
        )
        self.share = self.share_panel.edit
        bl.addWidget(self.share_panel)
        share.addGroupWidget(body)
        lay.addWidget(share)
        self.coop_form.append(share)
        lay.addStretch(1)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(40, 8, 40, 20)
        self.save_bar = ActionBar(
            "Save",
            lambda: self._announce_saved(self.save_seamless(), "next"),
            (
                "Discard",
                FI.CANCEL,
                self._discard_coop,
                "Put the password, difficulty and other options back to what the file says.",
            ),
            note="Saved.",
        )
        self.save_bar.primary.setToolTip("Write the password, difficulty and any other options you changed. Ctrl+S.")
        self.all_note, self.all_save, self.all_discard = (
            self.save_bar.note,
            self.save_bar.primary,
            self.save_bar.secondary,
        )
        wl.addWidget(self.save_bar)
        outer.addWidget(wrap)
        self.coop_bar = wrap
        self.coop_page = root

    # ---------------------------------------------------------------- co-op
    def _load_coop(self):
        ini = self.ini
        on = ini is not None
        self._coop_ready = True  # the co-op form now reflects self.ini, so pending-change detection is valid
        self.coop_off.setVisible(not on)
        for w in self.coop_form:
            w.setVisible(on)
        self.coop_bar.setVisible(on)
        for w in (self.pw, self.preset, self.share):
            w.setEnabled(on)
        if not on:
            self.pw.blockSignals(True)
            self.pw.setText("")
            self.pw.blockSignals(False)
            self.pw_file = None
            self.scaling_file = None
            self.scal_hint.setText("")
            self.share.setPlainText("")
            for sp in self.spins:
                sp.setEnabled(False)
            self._refresh_coop_actions()
            return
        self.pw_card.setVisible(has_password(ini))  # Nightreign's Seamless Co-op has no password
        self.pw_file = read_password(ini)
        self.pw.blockSignals(True)
        self.pw.setText(self.pw_file or "")
        self.pw.blockSignals(False)
        self._on_pw_edit()
        self.scaling = scaling_spec(ini)
        self.scaling_file = read_scaling(ini, self.scaling) if self.scaling else None
        self._show_scaling(self.scaling)
        if self.scaling_file is None:
            self.preset.setEnabled(False)
            for sp in self.spins:
                sp.setEnabled(False)
            self.scal_hint.setText(f"No difficulty values in {ini.name}.")
        else:
            name = preset_of(self.scaling_file, self.scaling)
            self.preset.blockSignals(True)
            self.preset.setCurrentText(name)
            self.preset.blockSignals(False)
            self._set_spins(self.scaling_file, name == CUSTOM)
            self._on_scaling_edit()
        self.share_fill()
        self._fill_all_settings()

    def _fill_all_settings(self):
        """Rebuild the section expanders from the file. Sections the quick cards already cover are skipped."""
        while self.all_box.count():
            it = self.all_box.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.all_dirty = {}
        self.all_file = {}
        self._all_dirty_changed()
        if self.ini is None:
            return
        for sec in read_settings_meta(self.ini):
            items = [i for i in sec["items"] if sec["section"].upper() not in ("PASSWORD", "SCALING")]
            if not items:
                continue
            icon = {"GAMEPLAY": FI.GAME, "SAVE": FI.SAVE, "LANGUAGE": FI.LANGUAGE}.get(
                sec["section"].upper(), FI.SETTING
            )
            sub = {
                "GAMEPLAY": "What the session feels like",
                "SAVE": "Which file Seamless writes",
                "LANGUAGE": "Locale override",
            }.get(sec["section"].upper(), count_label(len(items), "setting"))
            exp = ExpandGroupSettingCard(icon, sec["title"], sub)
            for it in items:
                self.all_file[it["key"]] = it["value"]
                exp.addGroupWidget(self._setting_row(it))
            self.all_box.addWidget(exp)
        self.other_host.setVisible(self.ini is not None and self.all_box.count() > 0)

    def _setting_row(self, it):
        """One form row. The control shows familiar words; the ini value is written behind the scenes."""
        key, kind, val = it["key"], it["kind"], it["value"].strip()
        title, blurb, help_text = setting_face(key, it["desc"])

        def mark(new):
            self._mark_dirty(key, str(new))

        if key == "default_boot_master_volume":
            w = ComboBox()
            labels = [lab for _, lab in VOLUME_STOPS]
            nums = [n for n, _ in VOLUME_STOPS]
            w.addItems(labels)
            w.setMinimumWidth(140)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            n = int(val) if val.lstrip("-").isdigit() else 5
            nearest = min(nums, key=lambda x: abs(x - n))
            w.setCurrentIndex(nums.index(nearest))
            w.currentIndexChanged.connect(lambda i, ns=nums: mark(ns[i]))
        elif key == "save_file_extension" and val in {k for k, _ in SAVE_KINDS}:
            w = ComboBox()
            kinds = [k for k, _ in SAVE_KINDS]
            w.addItems([lab for _, lab in SAVE_KINDS])
            w.setMinimumWidth(140)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            w.setCurrentIndex(kinds.index(val))
            w.currentIndexChanged.connect(lambda i, ks=kinds: mark(ks[i]))
        elif kind == "bool":
            w = SwitchButton()
            w.setOnText("On")
            w.setOffText("Off")
            w.setChecked(val == "1")
            w.checkedChanged.connect(lambda on: mark(1 if on else 0))
        elif kind == "choice":
            w = ComboBox()
            labels = [choice_label(key, n, lab) for n, lab in it["extra"]]
            w.addItems(labels)
            w.setMinimumWidth(200)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            nums = [n for n, _ in it["extra"]]
            w.setCurrentIndex(nums.index(int(val)) if val.lstrip("-").isdigit() and int(val) in nums else 0)
            w.setToolTip(w.currentText())
            w.currentIndexChanged.connect(lambda i, box=w, ns=nums: (box.setToolTip(box.itemText(i)), mark(ns[i])))
        elif kind == "int":
            w = SpinBox()
            lo, hi = it["extra"]
            w.setRange(lo, hi)
            w.setValue(int(val) if val.lstrip("-").isdigit() else lo)
            w.setMinimumWidth(96)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            w.valueChanged.connect(mark)
        else:
            w = LineEdit()
            w.setText(val)
            w.setMinimumWidth(140)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            w.setPlaceholderText("Game default" if key == "mod_language_override" else "")
            w.textChanged.connect(lambda t: mark(t.strip()))
        return SettingRow(title, blurb, w, help_text)

    def _mark_dirty(self, key, new):
        if new == self.all_file.get(key):
            self.all_dirty.pop(key, None)
        else:
            self.all_dirty[key] = new
        self._all_dirty_changed()

    def _all_dirty_changed(self):
        self._refresh_coop_actions()
        self._update_plan()

    def _on_pw_edit(self, *_):
        if self.ini is None:
            return
        changed = self.pw.text().strip() != (self.pw_file or "")
        self.pw_hint.setText("Not saved yet." if changed else "Friends type this to join.")
        self.pw_hint.setTextColor(ACCENT_LIGHT if changed else HINT_ON_LIGHT, ACCENT if changed else HINT)
        self._refresh_coop_actions()
        self._update_plan()

    def _show_scaling(self, spec):
        """Labels, visible fields and presets for this ini's set of difficulty keys (six for Elden Ring, three for
        Nightreign)."""
        n = len(spec.keys) if spec else len(self.spins)
        labels = spec.labels if spec else SCALING_LABELS
        for i, (lab, sp) in enumerate(zip(self.scal_labs, self.spins, strict=True)):
            lab.setVisible(i < n)
            sp.setVisible(i < n)
            if i < n:
                lab.setText(labels[i])
        presets = list(spec.presets) if spec else []
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItems(presets + [CUSTOM])
        self.preset.blockSignals(False)
        self.preset.setEnabled(bool(presets))
        self.preset_row.setVisible(bool(presets))
        if spec:
            self.scal_about.setText(spec.hint)

    def _scaling_values(self):
        n = len(self.scaling.keys) if self.scaling else len(self.spins)
        return tuple(sp.value() for sp in self.spins[:n])

    def _set_spins(self, values, enabled):
        for sp, v in zip(self.spins, values):
            sp.blockSignals(True)
            sp.setValue(int(v))
            sp.blockSignals(False)
            sp.setEnabled(enabled)

    def _on_preset(self, name):
        if self.scaling_file is None:
            return
        presets = self.scaling.presets if self.scaling else SCALING_PRESETS
        if name in presets:
            self._set_spins(presets[name], False)
        else:
            self._set_spins(self._scaling_values() or self.scaling_file, True)
        self._on_scaling_edit()

    def _on_scaling_edit(self, *_):
        if self.scaling_file is None:
            return
        changed = self._scaling_values() != self.scaling_file
        self.scal_hint.setText("Not saved yet." if changed else "")
        self.scal_hint.setTextColor(ACCENT_LIGHT if changed else HINT_ON_LIGHT, ACCENT if changed else HINT)
        self._refresh_coop_actions()
        self._update_plan()

    def _coop_pending(self):
        if self.ini is None or not hasattr(self, "pw") or not getattr(self, "_coop_ready", False):
            return False
        pw = self.pw.text().strip() != (self.pw_file or "")
        scal = self.scaling_file is not None and self._scaling_values() != self.scaling_file
        return pw or scal or bool(getattr(self, "all_dirty", None))

    def _pending_labels(self):
        if self.ini is None:
            return []
        labels = []
        if self.pw.text().strip() != (self.pw_file or ""):
            labels.append("Password")
        if self.scaling_file is not None and self._scaling_values() != self.scaling_file:
            labels.append("Difficulty")
        labels.extend(label_of(k) for k in getattr(self, "all_dirty", {}))
        return labels

    def _refresh_coop_actions(self):
        if not hasattr(self, "all_save"):
            return
        labels = self._pending_labels()
        pending = bool(labels)
        shown = ", ".join(labels[:4]) + (" ..." if len(labels) > 4 else "")
        self.save_bar.set_state(pending, ("Not saved: " + shown) if pending else "Saved.")

    def _discard_coop(self):
        self._load_coop()
        self._toast("Changes discarded", "Co-op settings are back to what is in the file.", info=True)

    def save_seamless(self):
        """Write password, scaling, and any other edited co-op settings. Returns what was written, or None if the write failed."""
        if self.ini is None:
            return []
        new = self.pw.text().strip()
        if self.pw.text().strip() != (self.pw_file or "") and not new:
            self._toast("Password needed", "The Seamless Co-op password cannot be empty.", error=True)
            return None
        wrote = []
        if new != (self.pw_file or ""):
            try:
                write_password(self.ini, new)
                self.pw_file = new
                self._on_pw_edit()
                self._log(f"password changed in {self.ini}")
            except Exception as e:
                self._toast("Could not write the password", str(e), error=True)
                return None
            wrote.append("Password")
        if self.scaling_file is not None and self._scaling_values() != self.scaling_file:
            vals = self._scaling_values()
            keys = self.scaling.keys if self.scaling else SCALING_KEYS
            labels = self.scaling.labels if self.scaling else SCALING_LABELS
            missing = write_keys(self.ini, dict(zip(keys, vals, strict=True)))
            if missing:
                self._toast("Missing keys", f"Not in {self.ini.name}: " + ", ".join(missing), error=True)
                return None
            self.scaling_file = vals
            self._on_scaling_edit()
            self._log("scaling changed to " + ", ".join(f"{l} {v}%" for l, v in zip(labels, vals, strict=True)))
            wrote.append("Difficulty")
        if self.all_dirty:
            labels = [label_of(k) for k in self.all_dirty]
            missing = write_keys(self.ini, dict(self.all_dirty))
            if missing:
                self._toast("Missing keys", f"Not in {self.ini.name}: " + ", ".join(missing), error=True)
                return None
            self._log("settings changed: " + ", ".join(f"{k}={v}" for k, v in self.all_dirty.items()))
            wrote.extend(labels)
            self._fill_all_settings()
        self.share_fill()
        self._refresh_coop_actions()
        return wrote

    def _announce_saved(self, wrote, when):
        """Toast after a co-op save. when is 'next' (saved for the following launch) or 'play' (this launch uses them)."""
        if wrote is None:
            return False
        if not wrote:
            return True
        shown = wrote[:3]
        if len(wrote) == 1:
            what = wrote[0]
        elif len(wrote) == 2:
            what = f"{wrote[0]} and {wrote[1]}"
        elif len(wrote) == 3:
            what = f"{wrote[0]}, {wrote[1]}, and {wrote[2]}"
        else:
            what = f"{shown[0]}, {shown[1]}, and {len(wrote) - 2} more"
        if when == "play":
            self._toast("Settings applied", f"{what}. This session will use them.")
        else:
            self._toast("Settings saved", f"{what}. They apply the next time you start the game.")
        return True

    def share_fill(self):
        if self.ini:
            self.share_panel.set_baseline(export_text(self.ini), f"Your settings, from {self.ini.name}", str(self.ini))

    def share_copy(self):
        QApplication.clipboard().setText(self.share.toPlainText())
        self._toast("Copied", "Settings are on the clipboard.")

    def share_paste(self):
        t = QApplication.clipboard().text()
        if not t.strip():
            self._toast("Clipboard is empty", "Copy settings from your friend first.", info=True)
            return
        self.share_panel.set_text(t)
        self._toast("Pasted", "Apply writes the settings that differ from yours, after a confirm.", info=True)

    def share_apply(self):
        if self.ini is None:
            return
        try:
            incoming = parse_settings_json(self.share.toPlainText())
        except Exception as e:
            self._toast("Not settings text", f"The text could not be read as co-op settings: {e}", error=True)
            return
        changes, unknown = plan_import(self.ini, incoming)
        if not changes:
            self._toast(
                "Nothing to change",
                "It matches your current settings." + (f" Ignored: {', '.join(unknown)}" if unknown else ""),
                info=True,
            )
            return
        if not confirm(
            self,
            f"Apply {len(changes)} setting{'s' if len(changes) != 1 else ''} from the pasted text",
            changes=[f"{k}:  {o}  \u2192  {n}" for k, (o, n) in changes.items()],
            detail=(f"Ignored (not in your file): {', '.join(unknown)}" if unknown else ""),
            safety="They apply the next time the game starts. The ini keeps a .bak of the previous version.",
            apply_text="Apply",
        ):
            return
        try:
            write_keys(self.ini, {k: n for k, (o, n) in changes.items()})
        except Exception as e:
            self._toast("Could not write", str(e), error=True)
            return
        self._log("applied " + ", ".join(f"{k}={n}" for k, (o, n) in changes.items()))
        self._load_coop()
        self._toast(
            "Settings applied",
            f"{len(changes)} setting"
            + ("s" if len(changes) != 1 else "")
            + ". They apply the next time you start the game.",
        )

    def share_save(self):
        p, _ = QFileDialog.getSaveFileName(
            self, "Save settings as", "seamless-coop-settings.json", "Settings export (*.json)"
        )
        if p:
            Path(p).write_text(self.share.toPlainText(), encoding="utf-8")
            self._toast("File saved", Path(p).name)

    def share_load(self):
        p, _ = QFileDialog.getOpenFileName(self, "Load settings file", "", "Settings export (*.json)")
        if p:
            self.share_panel.set_text(Path(p).read_text(encoding="utf-8"))
            self._toast(
                f"Opened {Path(p).name}",
                "Apply writes the settings that differ from yours, after a confirm.",
                info=True,
            )
