"""Profile mods as the Mods page sees them: enable / disable, install, options, remove, profiles, me3 facts."""

from __future__ import annotations

import re
import time
import tomllib
from pathlib import Path

from roundtable_souls.config.settings import load_settings, save_settings
from roundtable_souls.formats import me3_profile
from roundtable_souls.game.locate import Locations
from roundtable_souls.mods import install, models, profile_writer, remove
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods import profile_edit as mod_manage
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.platform import me3_info


def _plain_line(line: str) -> str:
    return re.sub(r"^[ \t]*#[ \t]?", "", line.rstrip("\r\n")).strip()


def read_profile_mods(profile):
    """Mods me3 will load, in file order.

    An entry loads unless it sets enabled = false. enabled defaults to true.
    Commented-out blocks are comments, not entries. Both me3 shapes are read:
    [[packages]] blocks, and the packages = [ { ... } ] form Revive's installer writes.
    """
    try:
        text = me3_profile.read_text(Path(profile))
        found = me3_profile.entries(text)
    except OSError, tomllib.TOMLDecodeError:
        return []
    out = []
    for e in found:
        ident = e["id"] or Path(e["path"]).name
        if e["enabled"] and ident:
            out.append(dict(index=e["index"], kind=e["kind"], id=ident, path=e["path"], name=ident))
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
    """Turn one package or native on or off. Commented-out keys in its block are uncommented when turned on. Returns
    whether it changed."""
    w = profile_writer.ProfileWriter(Path(profile))
    blocks = me3_profile.blocks(w.text)
    if index < 0 or index >= len(blocks):
        raise IndexError(index)
    i, j = blocks[index]["start"], blocks[index]["end"]
    lines = w.text.splitlines(keepends=True)
    new_block = _rewrite_block(lines[i:j], enabled)
    if new_block == lines[i:j]:
        return False
    w.replace_block(index, new_block)
    w.write(f"before turning a mod {'on' if enabled else 'off'}")
    return True


def me3_facts(setup, loc: Locations) -> dict:
    """Installed version, `me3 info` folders, and (cached daily) the latest release. Never raises. reload: True when
    me3 reported its folders (cached in settings): the caller reads the settings again, as the profile folder falls
    back to that cache."""
    me3 = setup.me3_path() if setup else loc.me3_exe()
    facts = {
        "path": str(me3) if me3 else "",
        "version": me3_info.me3_version(me3),
        "info": me3_info.me3_info(me3),
        "latest": None,
        "update": False,
        "reload": False,
    }
    s = load_settings()
    if facts["info"].get("profile_dir") or facts["info"].get("logs_dir"):
        cache = {k: facts["info"].get(k, "") for k in ("profile_dir", "logs_dir", "install_prefix")}
        if cache != s.me3_info_cache:
            save_settings(me3_info_cache=cache)
            s.me3_info_cache = cache
        facts["reload"] = True
    if s.check_me3_updates:
        cached = s.me3_latest
        when = float(s.me3_latest_checked or 0)
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
        return profile_tools.read_settings(me3_profile.read_text(Path(profile)))
    except OSError:
        return {}


def write_profile_setting(profile, key: str, value) -> bool:
    """Set (or None: remove) one top-level me3 setting in the profile text, keeping comments; one .bak. Returns whether it changed."""
    w = profile_writer.ProfileWriter(Path(profile))
    w.set_setting(key, value)
    if w.text == w.before:
        return False
    w.write(f"before changing {key}")
    return True


def save_profile_text(profile, text: str) -> None:
    """The profile's whole text as the player wrote it in the editor: one .bak and a history copy first, written
    as it is (no rule but the safety ones applies to the player's own text)."""
    w = profile_writer.ProfileWriter(Path(profile))
    w.replace_text(text)
    w.write("before saving the editor")


def scan_profile_conflicts(profile) -> dict:
    return profile_tools.scan_conflicts(Path(profile))


def profile_entries(profile) -> list:
    """Every package and native block, enabled or not, with options (mod_manage.entries)."""
    try:
        return mod_manage.entries(Path(profile))
    except Exception:
        return []


def plan_mod_install(profile, source, name=None, pkg_id=None, variant=None, *, loc: Locations) -> dict:
    plan = install.plan_install(Path(profile), Path(source), name, pkg_id, variant, loc=loc)
    models.ModPlan.model_validate(plan)
    return plan


def replan_mod_install(profile, plan, name=None, pkg_id=None, variant=None, *, loc: Locations) -> dict:
    """The same unpacked mod with another folder name, id or variant (nothing is unpacked again)."""
    new = install.replan(Path(profile), plan, name, pkg_id, variant, loc=loc)
    models.ModPlan.model_validate(new)
    return new


def install_mod(profile, plan, overwrite=False, rebuild=False, *, loc: Locations) -> dict:
    """Install (or update) as one recoverable operation (mods.operations); with rebuild, the merged mods are rebuilt
    inside it, so a failed rebuild leaves the previous installation as it was."""
    from roundtable_souls.mods import rebuild as merge

    def then():
        merge.rebuild(Path(profile), run_logging.log, loc=loc)

    out = install.install(Path(profile), plan, overwrite=overwrite, then=then if rebuild else None, loc=loc)
    run_logging.log(f"{'updated' if out['update'] else 'installed'} {plan['kind']} {plan['name']} -> {out['dest']}")
    for rel in out.get("kept") or []:
        run_logging.log(f"kept your changed {rel} (the new version's copy is beside it as .new)")
    return out


def recover_interrupted(profile, timeout: float = 30.0) -> list[str]:
    """Finish or undo an install, update or removal in this profile's folder that was interrupted (the window or
    the PC closed during it). Returns what was done; [] when there was nothing, or the folder is busy."""
    from roundtable_souls.merging.build import BuildError
    from roundtable_souls.mods import operations

    try:
        said = operations.recover(Path(profile), timeout)
    except (BuildError, OSError) as e:
        run_logging.log(f"warning: could not check for an interrupted install: {e}")
        return []
    for line in said:
        run_logging.log(f"mods: {line}")
    return said


def uninstall_mod(profile, index: int, delete_folder=True, *, loc: Locations) -> dict:
    out = remove.uninstall(Path(profile), index, delete_folder=delete_folder, loc=loc)
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


def set_mod_options(profile, index: int, opts: dict, *, loc: Locations):
    return mod_manage.set_options(Path(profile), index, opts, loc=loc)


def create_profile(name: str, copy_from=None, *, loc: Locations) -> Path:
    """A new profile for loc's game in me3's profile folder."""
    folder = loc.me3_profiles_dir()
    if not folder:
        raise RuntimeError("me3's profile folder is unknown on this PC (no LOCALAPPDATA).")
    return mod_manage.create_profile(folder, name, game=loc.game.key, copy_from=copy_from)


def delete_profile(path) -> Path:
    return mod_manage.delete_profile(Path(path))
