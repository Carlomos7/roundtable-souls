"""How save findings become the calm notes and item rows the Saves page shows."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, StrongBodyLabel

from roundtable_souls.ui.theme import hint, tone_label


def _slot_names(title: str) -> str:
    """Character names from 'slot N (Name)' in a finding title."""
    names = re.findall(r"slot\s+\d+\s+\(([^)]+)\)", title or "", flags=re.I)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names)


def save_check_notes(info: dict) -> list[dict]:
    """Calm, grouped notes for the Saves panel. Empty when nothing useful to say."""
    notes = []
    findings = [f for f in (info.get("findings") or []) if f.get("level") in ("warn", "error")]
    if info.get("needs_repair"):
        nr = any(f.get("code") == "checksum" for f in info.get("findings") or [])
        notes.append(
            {
                "kind": "action",
                "title": "Repair for save editors",
                "detail": (
                    "me3 can leave a section unsigned or the regulation payload unreadable. Repair re-signs every "
                    "section. If entry 12 is garbled, it is copied from a healthy .bak / .sl2 / .co2 next to this file "
                    "when one exists."
                    if nr
                    else "me3 left extra data at the end of the file. The game does not mind. Repair puts the real regulation.bin back so editors can open it."
                ),
            }
        )
    by = {}
    for f in findings:
        if f.get("code") == "regulation":
            continue  # covered above
        by.setdefault(f.get("code") or "other", []).append(f)

    if "layout" in by:
        torn = [f for f in by["layout"] if (f.get("title") or "").startswith("Torn write")]
        if torn:
            notes.append(
                {
                    "kind": "issue",
                    "title": "Damaged by a crash while saving",
                    "rows": [
                        (
                            _slot_names(f.get("title") or "") or "Character",
                            "bytes shifted inside the character",
                            f.get("detail") or "",
                        )
                        for f in torn
                    ],
                    "detail": "A damaged character cannot be repaired here. Restore a backup from before the crash; everything else on this page is read-only.",
                }
            )
        else:
            notes.append(
                {
                    "kind": "issue",
                    "title": "Could not read this save",
                    "detail": by["layout"][0].get("detail")
                    or "The file is not a PC Elden Ring save, or the layout does not parse.",
                }
            )
    if "old_slot" in by:
        notes.append(
            {
                "kind": "note",
                "title": "One character could not be read",
                "rows": [
                    (
                        _slot_names(f.get("title") or "") or (f.get("title") or "").replace("Cannot read ", ""),
                        "old save layout, left alone",
                        f.get("detail") or "",
                    )
                    for f in by["old_slot"]
                ],
                "detail": "Load that character in the game once so it is saved in the current layout, then Refresh here. The other characters are unaffected.",
            }
        )
    if "loading" in by:
        rows = []
        for f in by["loading"]:
            who = _slot_names(f.get("title") or "") or "Character"
            label = (f.get("title") or "Loading problem").split(" (")[0]
            rows.append((who, label, f.get("detail") or ""))
        notes.append(
            {
                "kind": "issue",
                "title": "May not load",
                "rows": rows,
                "detail": "These states hang the loading screen. Review & fix applies the same repair the save editors use, with a backup.",
            }
        )
    if "unknown_item" in by:
        rows = _mod_item_rows(info)
        if not rows:
            for f in by["unknown_item"]:
                rows.append(
                    (_slot_names(f.get("title") or "") or "Character", (f.get("detail") or "").split(". ")[0], "")
                )
        worn = any("worn" in text for _, text, _ in rows)
        notes.append(
            {
                "kind": "note",
                "title": "Mod items held",
                "rows": rows,
                "detail": "Fine for co-op. Review & fix can remove them for a standard save"
                + (". Worn pieces come off in-game first." if worn else "."),
            }
        )
    if "duplicate_inventory" in by:
        who = ", ".join(filter(None, (_slot_names(f["title"]) for f in by["duplicate_inventory"])))
        notes.append(
            {
                "kind": "note",
                "title": "Duplicate inventory entries",
                "detail": (("On " + who + ". ") if who else "")
                + "Some editors refuse to write that character. The game usually still loads.",
            }
        )
    for code in ("slot_checksum", "ud10_checksum"):
        if code not in by:
            continue
        notes.append(
            {
                "kind": "note",
                "title": "Checksum mismatch",
                "detail": (by[code][0].get("detail") or "Unusual, but characters still show.")
                + " Fix checksums recomputes it, with a backup.",
            }
        )
    for code, group in by.items():
        if code in (
            "layout",
            "loading",
            "old_slot",
            "unknown_item",
            "duplicate_inventory",
            "slot_checksum",
            "ud10_checksum",
            "regulation",
            "checksum",
            "read",
        ):
            continue
        for f in group:
            notes.append({"kind": "note", "title": f.get("title") or code, "detail": f.get("detail") or ""})
    return notes


def _mod_item_rows(info: dict) -> list:
    """(character, 'Seamless Co-op 12  ·  Not in the game 2 (1 worn)', tooltip with the item names) per character."""
    rows = []
    for p in info.get("vanilla_plan") or []:
        entries = list(p.get("strip") or []) + [b for b in (p.get("blocked") or []) if b.get("why") == "worn"]
        if not entries:
            continue
        by: dict[str, tuple[list[str], set[str]]] = {}
        for e in entries:
            names, worn = by.setdefault(e.get("source") or "Not in the game", ([], set()))
            if e["name"] not in names:
                names.append(e["name"])
            if e.get("why") == "worn":
                worn.add(e["name"])
        parts, tip = [], []
        for source, (names, worn) in by.items():
            parts.append(f"{source} {len(names)}" + (f" ({len(worn)} worn)" if worn else ""))
            tip.append(source + ":\n  " + "\n  ".join(n + ("  (worn)" if n in worn else "") for n in names))
        rows.append((p.get("name") or f"slot {p['slot'] + 1}", "  \u00b7  ".join(parts), "\n".join(tip)))
    return rows


def _save_note_widget(note: dict) -> QWidget:
    """Title, optional character rows (name | text, names in the tooltip), then one calm line."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lab = StrongBodyLabel(note["title"])
    lab.setWordWrap(True)
    if note.get("kind") == "issue":
        tone_label(lab, "error")
    lay.addWidget(lab)
    rows = note.get("rows") or []
    if rows:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        for r, (who, text, tip) in enumerate(rows):
            name = BodyLabel(who)
            name.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            body = BodyLabel(text)
            body.setWordWrap(True)
            if tip:
                name.setToolTip(tip)
                body.setToolTip(tip)
            grid.addWidget(name, r, 0, Qt.AlignTop)
            grid.addWidget(body, r, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
    if note.get("detail"):
        lay.addWidget(hint(note["detail"]))
    return w
