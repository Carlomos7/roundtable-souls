"""What the window knows about a save: read-only info and plans, backups, and the named repairs behind each button."""

from __future__ import annotations

import datetime
import shutil
import time
from pathlib import Path

from roundtable_souls import models
from roundtable_souls.saves import analyze as save_analyze
from roundtable_souls.saves import fix as save_fix
from roundtable_souls.saves import layout as save_layout_check
from roundtable_souls.saves import loading as save_loading
from roundtable_souls.saves import regulation as repair_regulation
from roundtable_souls.saves import vanilla as save_vanilla
from roundtable_souls.system import common


def _save_info(path: Path) -> dict:
    """One save file: type, modified time, findings, and its active characters."""
    path = Path(path)
    info = dict(
        path=path,
        name=path.name,
        kind="Seamless Co-op" if path.suffix.lower() == ".co2" else "Standard",
        modified="?",
        characters=[],
        block="?",
        findings=[],
        error=None,
        needs_repair=False,
        convert_ok=False,
        checksum_fixes={"slots": [], "ud10": False},
        vanilla_plan=[],
        loading_plan=[],
    )
    try:
        info["modified"] = datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError as e:
        info["error"] = str(e)[:120]
        info["findings"] = [{"level": "error", "code": "read", "title": "Cannot read this save", "detail": str(e)}]
        return info
    try:
        data = path.read_bytes()
    except OSError as e:
        info["error"] = str(e)[:120]
        info["findings"] = [{"level": "error", "code": "read", "title": "Cannot read this save", "detail": str(e)}]
        return info

    if not repair_regulation.is_pc_save(data):
        info["error"] = "Not a PC Elden Ring save"
        info["findings"] = [
            {
                "level": "error",
                "code": "layout",
                "title": "Not a PC Elden Ring save",
                "detail": "Magic or size does not match.",
            }
        ]
        return info

    healthy, used, _hdr = repair_regulation.block_status(data)
    info["needs_repair"] = not healthy
    info["block"] = "needs repair" if not healthy else "OK"
    findings = []
    if healthy:
        findings.append(
            {
                "level": "ok",
                "code": "regulation",
                "title": "Regulation block OK",
                "detail": f"{used:#x} bytes of real regulation data.",
            }
        )
    else:
        findings.append(
            {
                "level": "warn",
                "code": "regulation",
                "title": "Regulation block needs repair",
                "detail": "me3 left garbage here. Repair puts the game's regulation.bin back. The game does not mind; save editors do.",
            }
        )

    try:
        r = save_layout_check.parse(str(path))
        findings.append(
            {
                "level": "ok",
                "code": "layout",
                "title": "Save layout OK",
                "detail": "Parses the way the Rust save editor expects.",
            }
        )
        bad = [str(i + 1) for i, ok in enumerate(r["slot_md5_ok"]) if not ok and r["ud10"]["active"][i]]
        if bad:
            findings.append(
                {
                    "level": "warn",
                    "code": "slot_checksum",
                    "title": "Character checksum mismatch",
                    "detail": f"Active slot(s) {', '.join(bad)}. The character still shows; some editors refuse to write that slot.",
                }
            )
        if not r["ud10_md5_ok"]:
            findings.append(
                {
                    "level": "warn",
                    "code": "ud10_checksum",
                    "title": "Profile summary checksum mismatch",
                    "detail": "The profile summary checksum does not match. Unusual; Fix checksums recomputes it.",
                }
            )
        for i, why in sorted((r.get("unreadable") or {}).items()):
            if not r["ud10"].get("active_raw", r["ud10"]["active"])[i]:
                continue
            if not (0 < why["ver"] <= 81):
                continue  # current layout that fails to parse = torn write (analyzer)
            name, level = r["ud10"]["profiles"][i] if i < len(r["ud10"]["profiles"]) else ("", 0)
            info["unreadable"] = info.get("unreadable", []) + [
                {"slot": i + 1, "name": name, "level": level, "ver": why["ver"], "error": why["error"]}
            ]
            findings.append(
                {
                    "level": "warn",
                    "code": "old_slot",
                    "title": f"Cannot read slot {i + 1}" + (f" ({name})" if name else ""),
                    "detail": (
                        f"Its layout is save version {why['ver']}, which this reader does not know (the other characters read fine). "
                        f"Load that character once in the game to bring it up to date, then Refresh. Nothing on this page touches it. "
                        f"Parser said: {why['error']}"
                    ),
                }
            )
        for i, s in enumerate(r["slots"]):
            if not r["ud10"]["active"][i]:
                continue
            p = s["pgd"]
            info["characters"].append(
                dict(
                    slot=i + 1,
                    name=p["name"],
                    level=p["level"],
                    body="Type B" if p.get("gender") == 1 else "Type A",
                    hp=p["max_health"],
                    runes=p["souls"],
                    ok=r["slot_md5_ok"][i],
                    where=place_name(s["map_id"]),
                    torrent=torrent_text(s.get("horse")),
                    stats=dict(
                        vig=p["vig"],
                        mind=p["mind"],
                        end=p["end"],
                        str=p["str"],
                        dex=p["dex"],
                        int=p["int"],
                        fai=p["fai"],
                        arc=p["arc"],
                    ),
                )
            )
        dlc = dlc_owned()
        info["tarnished_flag"] = save_analyze.tarnished_flag(r)
        info["dlc_owned"] = dlc
        findings.extend(save_analyze.analyze_parsed(r, dlc_owned=dlc, raw=data))
        # read-only plans: what each repair would do
        info["loading_plan"] = save_loading.plan_loading_fixes(r, dlc)
        info["checksum_fixes"] = save_fix.plan_checksum_fixes(r)
        info["vanilla_plan"] = save_vanilla.plan_restore(r)
    except save_layout_check.ParseError as e:
        findings.append({"level": "error", "code": "layout", "title": "Save layout failed", "detail": str(e)})
        info["error"] = str(e)[:120]
    except Exception as e:
        findings.append(
            {"level": "error", "code": "layout", "title": "Could not parse this save", "detail": str(e)[:200]}
        )
        info["error"] = str(e)[:120]
    info["findings"] = findings
    info["convert_ok"] = path.suffix.lower() == ".co2" and save_analyze.findings_are_clean(findings)
    return info


def save_info(path: Path) -> dict:
    """One save file: type, modified time, findings, and its active characters (shape: models.SaveInfo)."""
    info = _save_info(path)
    models.SaveInfo.model_validate(info)
    return info


AREA_NAMES = {
    10: "Stormveil Castle",
    11: "Leyndell",
    12: "Crumbling Farum Azula",
    13: "Ainsel River",
    14: "Academy of Raya Lucaria",
    15: "Miquella's Haligtree",
    16: "Volcano Manor",
    18: "Stranded Graveyard",
    19: "Erdtree",
    20: "Belurat",
    21: "Shadow Keep",
    22: "Specimen Storehouse",
    60: "The Lands Between",
    61: "Land of Shadow",
}


def place_name(map_id) -> str:
    """Readable place from the 4-byte map id (m<prefix>_<b2>_<b1>_<b0>)."""
    try:
        b = list(map_id)
    except TypeError:
        return "?"
    if len(b) != 4:
        return "?"
    if b[3] == 11 and b[2] == 10:
        return "Roundtable Hold"
    name = AREA_NAMES.get(b[3])
    if b[3] in (60, 61):
        return f"{name} (tile {b[2]}, {b[1]})"
    if 30 <= b[3] <= 59:
        return f"Dungeon m{b[3]}_{b[2]:02d}"
    return name or f"m{b[3]}_{b[2]:02d}_{b[1]:02d}_{b[0]:02d}"


def torrent_text(horse) -> str:
    if not horse:
        return "?"
    hp, state = horse
    return {1: "resting", 3: "dead", 13: "summoned"}.get(state, f"state {state}") + f", {hp:,} HP"


def character_detail(info: dict, slot_index: int) -> dict:
    """Everything the workshop's About card shows for one character (0-based slot)."""
    ch = next((c for c in info.get("characters") or [] if c["slot"] == slot_index + 1), None)
    if not ch:
        return {}
    mods = {}
    for p in info.get("vanilla_plan") or []:
        if p["slot"] != slot_index:
            continue
        for e in list(p.get("strip") or []) + list(p.get("blocked") or []):
            mods[e.get("source") or "Other mod"] = mods.get(e.get("source") or "Other mod", 0) + 1
    loading = [l for p in info.get("loading_plan") or [] if p["slot"] == slot_index for l in p["labels"]]
    return {**ch, "mods": mods, "loading": loading}


def save_findings(path: Path) -> list:
    """Read-only findings for one save. Never writes."""
    return save_info(path)["findings"]


def health_report(path: Path | None = None, info: dict | None = None) -> str:
    """Copyable plain-text health report for one save (or pass a save_info dict)."""
    if info is None:
        if path is None:
            raise ValueError("path or info required")
        info = save_info(path)
    return save_analyze.format_health_report(info)


def saves_needing_attention(infos: list | None = None) -> list:
    """Saves with repair needed or warn/error findings. Used for the Play pre-glance."""
    if infos is None:
        try:
            infos = [save_info(p) for p in common.save_files()]
        except Exception:
            return []
    out = []
    for s in infos:
        if s.get("needs_repair") or any(f.get("level") in ("warn", "error") for f in s.get("findings") or []):
            out.append(s)
    return out


BACKUP_FOLDERS = ("save-fix-backups", "regulation-fix-backups", "co2-to-sl2-backups", "sl2-to-co2-backups")
FOLDER_ACTIONS = {
    "save-fix-backups": "Save fix",
    "regulation-fix-backups": "Repair regulation block",
    "co2-to-sl2-backups": "Copy to standard save",
    "sl2-to-co2-backups": "Copy to co-op save",
}


def list_backups(save: Path | None = None) -> list:
    """Every backup next to the save(s), newest first: {path, save_name, when, action, changes, size, folder}."""
    paths = [Path(save)] if save else list(common.save_files())
    seen = set()
    out = []
    for p in paths:
        for folder in BACKUP_FOLDERS:
            d = p.parent / folder
            if not d.is_dir() or d in seen:
                continue
            seen.add(d)
            for f in d.iterdir():
                if f.suffix not in (".bak", ".src") or (save and not f.name.startswith(p.name + ".")):
                    continue
                m = save_fix.read_manifest(f) or {}
                try:
                    st = f.stat()
                except OSError:
                    continue
                when = m.get("when") or datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                action = m.get("action") or (
                    FOLDER_ACTIONS.get(folder, "Backup") + (" (source copy)" if f.suffix == ".src" else "")
                )
                out.append(
                    {
                        "path": f,
                        "save_name": f.name.split(".")[0] + "." + f.name.split(".")[1],
                        "when": when,
                        "action": action,
                        "changes": list(m.get("changes") or []),
                        "size": st.st_size,
                        "folder": folder,
                        "mtime": st.st_mtime,
                    }
                )
    out.sort(key=lambda b: b["mtime"], reverse=True)
    return out


def save_for_backup(bak: Path) -> Path:
    """The live save a backup belongs to: same folder as the backup folder's parent, first two name parts."""
    bak = Path(bak)
    parts = bak.name.split(".")
    return bak.parent.parent / (parts[0] + "." + parts[1])


def restore_backup(bak: Path, save: Path | None = None) -> Path | None:
    """Put a backup back over the live save. The current file is backed up first (so a restore can be undone).
    Returns the path of that safety copy."""
    bak = Path(bak)
    save = Path(save) if save else save_for_backup(bak)
    assert_writable(save)
    if not bak.is_file():
        raise RuntimeError(f"Backup not found: {bak}")
    data = bak.read_bytes()
    if not repair_regulation.is_pc_save(data):
        raise RuntimeError("That backup is not a PC Elden Ring save.")
    safety = None
    if save.exists():
        safety = save_fix.backup(save, {"action": "Before restoring a backup", "changes": [f"restored {bak.name}"]})
    tmp = save.with_name(save.name + ".roundtable.tmp")
    tmp.write_bytes(data)
    tmp.replace(save)
    common.log(f"restored {bak.name} over {save.name}" + (f" (safety copy: {safety.name})" if safety else ""))
    return safety


def delete_backup(bak: Path) -> None:
    bak = Path(bak)
    for p in (bak, Path(str(bak) + ".json")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def repair_save(path: Path) -> bool:
    """Repair one save's regulation block from the game's regulation.bin. Returns True if rewritten."""
    path = Path(path)
    assert_writable(path)
    source = common.regulation_bin()
    if not source:
        raise RuntimeError("Could not find the game's regulation.bin through Steam.")
    reg, header = repair_regulation.load_regulation(source)
    if not repair_regulation.plausible_regulation(reg):
        raise RuntimeError(f"{source}: regulation length does not look right.")
    return bool(repair_regulation.repair(path, reg, header))


def assert_writable(path: Path, settle_seconds: float = 4.0) -> None:
    """The lock every write goes through: the game must be closed, and the file must not have changed in the
    last few seconds (the game flushes saves for a moment after quitting)."""
    if common.game_running():
        raise RuntimeError("Elden Ring is running. Close it before changing saves.")
    path = Path(path)
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return
    if age < settle_seconds:
        time.sleep(settle_seconds - age)
        if common.game_running():
            raise RuntimeError("Elden Ring started while waiting. Close it before changing saves.")


def fix_checksums(path: Path) -> dict:
    """Recompute stale character / profile-summary checksums. Backs up first and verifies before replacing."""
    path = Path(path)
    assert_writable(path)
    return save_fix.repair_checksums(path, log=common.log)


def dlc_owned() -> bool | None:
    """Shadow of the Erdtree installed on this PC: DLC.bdt next to the game. None when the game folder is unknown
    (treated as installed)."""
    try:
        return save_loading.dlc_installed(common.game_dir())
    except Exception:
        return None


def fix_loading(path: Path, slots: list | None = None, selection: dict | None = None) -> dict:
    """Apply the loading-screen fixes (Torrent, position, DLC flags, weather). Backs up, re-signs, verifies."""
    path = Path(path)
    assert_writable(path)
    return save_loading.apply_loading_fixes(path, slots, dlc_owned=dlc_owned(), log=common.log, selection=selection)


def restore_vanilla(path: Path, slots: list | None = None, selection: dict | None = None) -> dict:
    """Take items the game does not define off the given (or every active) character and clear leftover rows.
    Backs up first, re-signs, verifies before replacing. Returns save_vanilla's result."""
    path = Path(path)
    assert_writable(path)
    return save_vanilla.apply_restore(path, slots, log=common.log, selection=selection)


remove_mod_items = restore_vanilla  # the button is called Remove mod items; the backend keeps its name


def restore_available(info: dict) -> bool:
    """True when Remove mod items would change something (items to take off or rows to clear)."""
    return save_vanilla.restore_needed(info.get("vanilla_plan") or [])


def repair_available(info: dict) -> bool:
    """True when Roundtable Souls itself can fix something in this save (block repair, mod items, checksums, loading).
    The Saves nav badge uses this."""
    cs = info.get("checksum_fixes") or {}
    return bool(
        info.get("needs_repair")
        or cs.get("slots")
        or cs.get("ud10")
        or restore_available(info)
        or info.get("loading_plan")
    )


def save_summary(info: dict) -> list:
    """Three calm status chips for a save card: (text, tone). Tones: success, warn, muted."""
    chips = []
    if info.get("error") and not info.get("characters"):
        return [("Could not read", "warn")]
    torn = any(f.get("code") == "layout" and f.get("level") == "error" for f in info.get("findings") or [])
    if torn:
        chips.append(("Damaged file", "warn"))
    elif info.get("loading_plan"):
        n = len(info["loading_plan"])
        chips.append((f"May not load ({n} character{'s' if n != 1 else ''})", "warn"))
    else:
        chips.append(("Loads fine", "success"))
    plan = info.get("vanilla_plan") or []
    holders = [p for p in plan if p.get("strip") or p.get("blocked")]
    if holders:
        chips.append((f"Mod items on {len(holders)} character{'s' if len(holders) != 1 else ''}", "muted"))
    else:
        chips.append(("Only game items", "success"))
    cs = info.get("checksum_fixes") or {}
    if info.get("needs_repair") or cs.get("slots") or cs.get("ud10"):
        chips.append(("Needs a repair for save editors", "muted"))
    else:
        chips.append(("Opens in save editors", "success"))
    return chips


def convert_co2_to_sl2(path: Path, dest: Path | None = None, *, force: bool = False) -> Path:
    """Copy a .co2 to .sl2 only when findings are clean (or force=True after an explicit confirm).

    Never overwrites a live ER0000.sl2 without a backup. Default dest is ER0000.sl2.next-to-co2
    with a timestamp if the standard name already exists — callers pass dest for the live file.
    """
    path = Path(path)
    if path.suffix.lower() != ".co2":
        raise RuntimeError("Only Seamless Co-op .co2 files can be converted this way.")
    if common.game_running():
        raise RuntimeError("Elden Ring is running. Close it before converting saves.")
    info = save_info(path)
    if not force and not save_analyze.findings_are_clean(info["findings"]):
        raise RuntimeError("Findings are not clean. Repair or clear warnings first, or use force after confirming.")
    dest = Path(dest) if dest else path.with_suffix(".sl2")
    folder = dest.parent / "co2-to-sl2-backups"
    folder.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if dest.exists():
        bak = folder / f"{dest.name}.{stamp}.bak"
        shutil.copy2(dest, bak)
    shutil.copy2(path, dest)
    # Keep a copy of the source too
    shutil.copy2(path, folder / f"{path.name}.{stamp}.src")
    return dest


def convert_sl2_to_co2(path: Path, dest: Path | None = None) -> Path:
    """Copy a standard .sl2 to the .co2 Seamless Co-op reads. Same bytes; the mod does not mind extra notes.

    Whatever ER0000.co2 already exists is backed up into sl2-to-co2-backups first, with a copy of the source.
    """
    path = Path(path)
    if path.suffix.lower() != ".sl2":
        raise RuntimeError("Only standard .sl2 files can be copied this way.")
    if common.game_running():
        raise RuntimeError("Elden Ring is running. Close it before converting saves.")
    dest = Path(dest) if dest else path.with_suffix(".co2")
    folder = dest.parent / "sl2-to-co2-backups"
    folder.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if dest.exists():
        shutil.copy2(dest, folder / f"{dest.name}.{stamp}.bak")
    shutil.copy2(path, dest)
    shutil.copy2(path, folder / f"{path.name}.{stamp}.src")
    return dest


def dead_shells_count() -> int:
    try:
        return len(common.dead_game_shells())
    except Exception:
        return 0


def backups_folder(path: Path):
    """The newest backups folder next to the save: save fixes or regulation repairs."""
    cands = [path.parent / save_fix.BACKUP_DIR, path.parent / repair_regulation.BACKUP_DIR]
    have = [c for c in cands if c.is_dir()]
    if not have:
        return cands[1]
    return max(have, key=lambda c: c.stat().st_mtime)
