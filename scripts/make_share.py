"""Turn vpk's output (dist/vpk) into the release files (dist/share), under the names releases keep using.

Windows: RoundtableSouls-Setup.exe     the Velopack setup (the name versions up to 3.13.2 update from)
         RoundtableSouls-win-Portable.zip
         <packId>-<version>-full.nupkg (+ -delta.nupkg when vpk had the previous release to diff against)
         releases.win.json            this release's feed (signed by the release workflow)
Linux:   RoundtableSouls-linux-x86_64.AppImage, <packId>-<version>-linux-full.nupkg (+ delta), releases.linux.json

The feed lists this version's packages, plus the full package the delta was made against (a file of an earlier
release; listed so the launcher knows which version the delta needs). SHA256SUMS.txt covers the files here; the
release workflow writes the final one over both systems' files.

uv run python scripts/make_share.py --pack-id <id> --version <version>     (scripts/build.py runs it)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VPK_OUT = DIST / "vpk"
SHARE = DIST / "share"
WINDOWS = sys.platform == "win32"
CHANNEL = "win" if WINDOWS else "linux"


def arg(name: str) -> str:
    argv = sys.argv[1:]
    if name not in argv:
        raise SystemExit(f"make_share: {name} is required")
    return argv[argv.index(name) + 1]


def version_key(v: str) -> tuple:
    sys.path.insert(0, str(ROOT / "src"))
    from roundtable_souls.updates import version_key as key

    return key(v)


def release_feed(doc: dict, version: str) -> dict:
    """This version's entries, plus the newest earlier full package when there is a delta (its base)."""
    mine = [a for a in doc["Assets"] if version_key(a["Version"]) == version_key(version)]
    if not any(a["Type"] == "Full" for a in mine):
        raise SystemExit(f"make_share: vpk's feed has no full package of {version}")
    if any(a["Type"] == "Delta" for a in mine):
        older = [a for a in doc["Assets"] if a["Type"] == "Full" and version_key(a["Version"]) < version_key(version)]
        if older:
            mine.append(max(older, key=lambda a: version_key(a["Version"])))
    return {"Assets": mine}


def write_checksums(files: list[Path]) -> Path:
    sums = SHARE / "SHA256SUMS.txt"
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in sorted(files) if p.is_file()]
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return sums


def main() -> int:
    pack_id, version = arg("--pack-id"), arg("--version")
    feed_name = f"releases.{CHANNEL}.json"
    doc = json.loads((VPK_OUT / feed_name).read_text(encoding="utf-8-sig"))
    feed = release_feed(doc, version)
    shutil.rmtree(SHARE, ignore_errors=True)
    SHARE.mkdir(parents=True)
    out: list[Path] = []
    for a in feed["Assets"]:
        if version_key(a["Version"]) == version_key(version):
            src = VPK_OUT / a["FileName"]
            if src.stat().st_size != a["Size"]:
                raise SystemExit(f"make_share: {src.name} does not match vpk's feed")
            out.append(Path(shutil.copy2(src, SHARE / a["FileName"])))
    renames = (
        {f"{pack_id}-win-Setup.exe": "RoundtableSouls-Setup.exe", f"{pack_id}-win-Portable.zip": "RoundtableSouls-win-Portable.zip"}
        if WINDOWS
        else {f"{pack_id}.AppImage": "RoundtableSouls-linux-x86_64.AppImage"}
    )  # fmt: skip
    for src_name, dst_name in renames.items():
        out.append(Path(shutil.copy2(VPK_OUT / src_name, SHARE / dst_name)))
    (SHARE / feed_name).write_text(json.dumps(feed, indent=1), encoding="utf-8", newline="\n")
    out.append(SHARE / feed_name)
    sums = write_checksums(out)
    for p in sorted(out):
        print(f"  {p.name:55} {p.stat().st_size / 1e6:9.2f} MB")
    print(f"Shared: {SHARE}; checksums in {sums.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
