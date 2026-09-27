"""Build the share bundle: dist/share/RoundtableSouls.zip holding the exe and docs/How to use.txt.

Settings and logs are never included. Run by scripts/build.py after PyInstaller; safe to run by hand.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE_NAME = "RoundtableSouls"
DIST = ROOT / "dist"
SHARE = DIST / "share"
STALE = ("launcher_settings.json",)


def main() -> int:
    src = DIST / f"{EXE_NAME}.exe"
    if not src.is_file():
        print(f"make_share: {src} not found (run scripts/build.py first)", file=sys.stderr)
        return 1
    SHARE.mkdir(parents=True, exist_ok=True)
    for name in STALE:
        (SHARE / name).unlink(missing_ok=True)
    logs = SHARE / "logs"
    if logs.is_dir():
        for f in logs.iterdir():
            f.unlink()
        logs.rmdir()
    exe = SHARE / src.name
    shutil.copyfile(src, exe)
    docs = ROOT / "docs" / "How to use.txt"
    out = SHARE / f"{EXE_NAME}.zip"
    tmp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(exe, exe.name)
        if docs.is_file():
            z.write(docs, docs.name)
    tmp.replace(out)
    with zipfile.ZipFile(out) as z:
        sizes = {i.filename: i.file_size for i in z.infolist()}
    if sizes.get(exe.name) != exe.stat().st_size:
        print("make_share: zip did not verify", file=sys.stderr)
        return 1
    print(f"Shared: {out} ({', '.join(sizes)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
