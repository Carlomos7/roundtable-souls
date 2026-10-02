"""Sharing Seamless Co-op settings: the whole file as JSON (export, paste, import with a preview of what changes), and the small text helpers the settings editor uses for JSON comments and indentation."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from roundtable_souls.coop.ini import (
    LINE_RE,
    SECTION_RE,
    _read,
)

JSON_FORMAT = "seamless-coop-settings"


def read_all_settings(ini: Path) -> dict:
    """{section: {key: value}} for every `key = value` line (comments and blank lines skipped)."""
    out, section = {}, ""
    for raw in _read(ini).splitlines():
        line = raw.rstrip("\r")
        if not line.strip() or line.lstrip().startswith((";", "#")):
            continue
        m = SECTION_RE.match(line)
        if m:
            section = m.group(1)
            out.setdefault(section, {})
            continue
        m = LINE_RE.match(line)
        if m:
            out.setdefault(section, {})[m.group(1)] = m.group(2)
    return out


def export_settings(ini: Path, out: Path):
    doc = {
        "format": JSON_FORMAT,
        "version": 1,
        "exported": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": ini.name,
        "settings": read_all_settings(ini),
    }
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return sum(len(v) for v in doc["settings"].values())


def export_text(ini: Path) -> str:
    doc = {
        "format": JSON_FORMAT,
        "version": 1,
        "exported": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": ini.name,
        "settings": read_all_settings(ini),
    }
    return json.dumps(doc, indent=2)


COMMENT_PREFIX = {"toml": "#", "json": "//", "ini": ";", "text": "#"}


def strip_json_comments(text: str) -> str:
    """Drops whole lines that start with // (what Ctrl+/ writes in the share box); JSON itself has no comments."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))


def toggle_comment(lines: list, prefix: str) -> list:
    """Ctrl+/ on a block: if every non-blank line is already commented, uncomment; otherwise comment each non-blank
    line at the block's shallowest indent. Blank lines are left alone. One space follows the marker."""
    mark = prefix + " "
    content = [l for l in lines if l.strip()]
    if not content:
        return list(lines)
    if all(l.lstrip().startswith(prefix) for l in content):
        out = []
        for l in lines:
            if not l.strip():
                out.append(l)
                continue
            indent = len(l) - len(l.lstrip())
            rest = l[indent:]
            rest = rest[len(mark) :] if rest.startswith(mark) else rest[len(prefix) :]
            out.append(l[:indent] + rest)
        return out
    col = min(len(l) - len(l.lstrip()) for l in content)
    return [(l[:col] + mark + l[col:]) if l.strip() else l for l in lines]


def indent_lines(lines: list, outdent: bool = False, width: int = 2) -> list:
    """Tab / Shift+Tab on a selection: shift every non-blank line by `width` spaces (me3 profiles use two)."""
    if outdent:
        out = []
        for l in lines:
            n = 0
            while n < width and n < len(l) and l[n] == " ":
                n += 1
            if n == 0 and l.startswith("\t"):
                n = 1
            out.append(l[n:])
        return out
    return [(" " * width + l) if l.strip() else l for l in lines]


def parse_settings_json(text: str) -> dict:
    """{key: value} flattened from exported JSON text. Accepts the full export, or a bare {section: {key: value}}
    / {key: value} object someone typed by hand. Lines starting with // are ignored. Raises ValueError on anything else."""
    doc = json.loads(strip_json_comments(text))
    if not isinstance(doc, dict):
        raise ValueError("expected a JSON object")
    body = doc.get("settings") if doc.get("format") == JSON_FORMAT else doc
    if not isinstance(body, dict):
        raise ValueError("not a Seamless Co-op settings export")
    flat = {}
    for k, v in body.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                flat[str(k2)] = str(v2)
        elif k not in ("format", "version", "exported", "source"):
            flat[str(k)] = str(v)
    if not flat:
        raise ValueError("no settings in that text")
    return flat


def load_settings_json(path: Path) -> dict:
    return parse_settings_json(Path(path).read_text(encoding="utf-8"))


def plan_import(ini: Path, incoming: dict):
    """(changes {key: (old, new)}, unknown keys) against the current file; keys not in the file are never added."""
    current = {k: v for sec in read_all_settings(ini).values() for k, v in sec.items()}
    changes = {k: (current[k], v) for k, v in incoming.items() if k in current and current[k] != v}
    unknown = sorted(k for k in incoming if k not in current)
    return changes, unknown
