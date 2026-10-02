"""Profile mods as the Mods page sees them: enable / disable, install, options, remove, profiles, me3 facts."""

from __future__ import annotations

import re
import time
from pathlib import Path

from roundtable_souls import models
from roundtable_souls.config.settings import load_settings, save_settings
from roundtable_souls.coop import _profile_rows, _read
from roundtable_souls.files import atomic_write
from roundtable_souls.mods import manage as mod_manage
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.platform import me3_info
from roundtable_souls.platform import paths as common
from roundtable_souls.platform.paths import apply_overrides

_BLOCK_HEADER = re.compile(r"^[ \t]*\[\[(packages|natives)\]\][ \t]*$", re.I)
_TOML_BODY = re.compile(r"^(?:\[\[|#?\s*[A-Za-z0-9_]+\s*=|\{|\}|\])")


def _plain_line(line: str) -> str:
    return re.sub(r"^[ \t]*#[ \t]?", "", line.rstrip("\r\n")).strip()


def _profile_blocks(text: str):
    """(start, end, kind) for each real [[packages]] / [[natives]] block, in file order. Commented lines are comments, not mods."""
    lines = text.splitlines(keepends=True)
    starts = [
        (i, "package" if m.group(1).lower() == "packages" else "native")
        for i, line in enumerate(lines)
        if (m := _BLOCK_HEADER.match(line.rstrip("\r\n")))
    ]
    blocks = []
    for n, (i, kind) in enumerate(starts):
        j = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        blocks.append((i, j, kind, lines))
    return blocks


def _toml_lines(lines) -> str:
    """Real keys only. A line whose first character is # is a comment, whatever it says."""
    kept = []
    for ln in lines:
        body = ln.rstrip("\r\n").strip()
        if body and not body.startswith("#"):
            kept.append(body)
    return "\n".join(kept)


def _mods_from_blocks(text: str):
    out = []
    for index, (i, j, kind, lines) in enumerate(_profile_blocks(text)):
        body = _toml_lines(lines[i:j])
        en_m = re.search(r"(?m)^enabled\s*=\s*(true|false)\b", body, re.I)
        if en_m and en_m.group(1).lower() == "false":
            continue
        id_m = re.search(r"(?m)^id\s*=\s*['\"]([^'\"]+)['\"]", body)
        path_m = re.search(r"(?m)^path\s*=\s*['\"]([^'\"]+)['\"]", body)
        path = path_m.group(1) if path_m else ""
        if not id_m and not path:
            continue
        ident = id_m.group(1) if id_m else Path(path).name
        out.append(dict(index=index, kind=kind, id=ident, path=path, name=ident))
    return out


def read_profile_mods(profile):
    """Mods me3 will load, in file order.

    An entry loads unless it sets enabled = false. enabled defaults to true.
    Commented-out blocks are comments, not entries. Both me3 shapes are read:
    [[packages]] blocks, and the packages = [ { ... } ] form Revive's installer writes.
    """
    try:
        text = _read(Path(profile))
    except OSError:
        return []
    if _profile_blocks(text):
        return _mods_from_blocks(text)
    rows = _profile_rows(text)
    if rows is None:
        return []
    out = []
    for index, (kind, row) in enumerate(rows):
        if row.get("enabled", True) is False:
            continue
        path = str(row.get("path") or "")
        ident = str(row.get("id") or (Path(path).name if path else ""))
        if not ident and not path:
            continue
        out.append(dict(index=index, kind=kind, id=ident, path=path, name=ident))
    return out


def _rewrite_block(block_lines, enabled: bool):
    lines = []
    for line in block_lines:
        nl = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
        body = line[: -len(nl)] if nl else line
        if enabled:
            m = re.match(r"^([ \t]*)#[ \t]?(.*)$", body)
            inner = m.group(2).strip() if m else ""
            if m and (inner.startswith("[[") or re.match(r"^[A-Za-z0-9_]+\s*=", inner) or inner[:1] in "{]}"):
                body = m.group(1) + m.group(2)
        lines.append(body + nl)
    val = "true" if enabled else "false"
    for i, line in enumerate(lines):
        if re.search(r"enabled\s*=", _plain_line(line), re.I):
            lines[i] = re.sub(r"(enabled\s*=\s*)(true|false)", r"\g<1>" + val, line, count=1, flags=re.I)
            return lines
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    lines.insert(1, f"enabled = {val}{nl}")
    return lines


def set_profile_mod_enabled(profile, index: int, enabled: bool) -> bool:
    """Turn one package or native on or off. Commented-out blocks are uncommented when turned on. Returns whether it changed."""
    path = Path(profile)
    text = _read(path)
    blocks = _profile_blocks(text)
    if index < 0 or index >= len(blocks):
        raise IndexError(index)
    i, j, _kind, lines = blocks[index]
    new_block = _rewrite_block(lines[i:j], enabled)
    if new_block == lines[i:j]:
        return False
    lines[i:j] = new_block
    from roundtable_souls.mods import history

    history.snapshot(path, f"before turning a mod {'on' if enabled else 'off'}")
    atomic_write(path, "".join(lines), backup=True)
    return True


def me3_facts(setup) -> dict:
    """Installed version, `me3 info` folders, and (cached daily) the latest release. Never raises."""
    me3 = setup.me3_path() if setup else common.me3_exe()
    facts = {
        "path": str(me3) if me3 else "",
        "version": me3_info.me3_version(me3),
        "info": me3_info.me3_info(me3),
        "latest": None,
        "update": False,
    }
    s = load_settings()
    if facts["info"].get("profile_dir") or facts["info"].get("logs_dir"):
        cache = {k: facts["info"].get(k, "") for k in ("profile_dir", "logs_dir", "install_prefix")}
        if cache != s.get("me3_info_cache"):
            save_settings(me3_info_cache=cache)
            s["me3_info_cache"] = cache
        apply_overrides(s)
    if bool(s.get("check_me3_updates", True)):
        cached = s.get("me3_latest")
        when = float(s.get("me3_latest_checked") or 0)
        if not cached or time.time() - when > 86400:
            rel = me3_info.latest_release()
            if rel:
                cached = rel
                save_settings(me3_latest=rel, me3_latest_checked=time.time())
        if isinstance(cached, dict):
            facts["latest"] = cached
            facts["update"] = me3_info.update_available(facts["version"], cached.get("version"))
    return facts


def read_profile_settings(profile) -> dict:
    try:
        return profile_tools.read_settings(_read(Path(profile)))
    except OSError:
        return {}


def write_profile_setting(profile, key: str, value) -> bool:
    """Set (or None: remove) one top-level me3 setting in the profile text, keeping comments; one .bak. Returns whether it changed."""
    path = Path(profile)
    text = _read(path)
    new = profile_tools.set_setting(text, key, value)
    if new == text:
        return False
    from roundtable_souls.mods import history

    history.snapshot(path, f"before changing {key}")
    atomic_write(path, new, backup=True)
    return True


def scan_profile_conflicts(profile) -> dict:
    return profile_tools.scan_conflicts(Path(profile))


def profile_entries(profile) -> list:
    """Every package and native block, enabled or not, with options (mod_manage.entries)."""
    try:
        return mod_manage.entries(Path(profile))
    except Exception:
        return []


def plan_mod_install(profile, source, name=None, pkg_id=None, variant=None) -> dict:
    plan = mod_manage.plan_install(Path(profile), Path(source), name, pkg_id, variant)
    models.ModPlan.model_validate(plan)
    return plan


def replan_mod_install(profile, plan, name=None, pkg_id=None, variant=None) -> dict:
    """The same unpacked mod with another folder name, id or variant (nothing is unpacked again)."""
    new = mod_manage.replan(Path(profile), plan, name, pkg_id, variant)
    models.ModPlan.model_validate(new)
    return new


def install_mod(profile, plan, overwrite=False) -> dict:
    out = mod_manage.install(Path(profile), plan, overwrite=overwrite)
    run_logging.log(f"installed {plan['kind']} {plan['name']} -> {out['dest']}")
    return out


def uninstall_mod(profile, index: int, delete_folder=True) -> dict:
    out = mod_manage.uninstall(Path(profile), index, delete_folder=delete_folder)
    run_logging.log(
        f"removed {out['kind']} {out['path']}"
        + (
            ""
            if not out["removed_folder"]
            else f" and moved its folder {out['folder']} to the Recycle Bin"
            if out.get("trash") and out["trash"].get("kind") != "gone"
            else f" and deleted its folder {out['folder']}"
        )
    )
    return out


def set_mod_options(profile, index: int, opts: dict):
    return mod_manage.set_options(Path(profile), index, opts)


def create_profile(name: str, copy_from=None) -> Path:
    folder = common.me3_profiles_dir()
    if not folder:
        raise RuntimeError("me3's profile folder is unknown on this PC (no LOCALAPPDATA).")
    return mod_manage.create_profile(folder, name, game=common.GAME.key, copy_from=copy_from)


def delete_profile(path) -> Path:
    return mod_manage.delete_profile(Path(path))
