"""Build the share bundle and SHA256SUMS.txt in dist/share.

Windows: RoundtableSouls.zip (the exe and docs/How to use.txt), plus the exe itself and the setup when it was built.
Linux:   RoundtableSouls-linux-x86_64.tar.gz (the program, the guide and the licence files).

Settings and logs are never included. Run by scripts/build.py after PyInstaller; safe to run by hand.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE_NAME = "RoundtableSouls"
DIST = ROOT / "dist"
SHARE = DIST / "share"
STALE = ("launcher_settings.json",)


def write_checksums(files: list[Path]) -> Path:
    sums = SHARE / "SHA256SUMS.txt"
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in files if p.is_file()]
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return sums


def linux_bundle() -> int:
    src = DIST / EXE_NAME
    if not src.is_file():
        print(f"make_share: {src} not found (run scripts/build.py first)", file=sys.stderr)
        return 1
    SHARE.mkdir(parents=True, exist_ok=True)
    out = SHARE / f"{EXE_NAME}-linux-x86_64.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(src, arcname=EXE_NAME)
        for extra in (ROOT / "docs" / "How to use.txt", ROOT / "LICENSE", ROOT / "THIRD_PARTY_NOTICES.md"):
            if extra.is_file():
                tar.add(extra, arcname=extra.name)
    with tarfile.open(out, "r:gz") as tar:
        size = tar.getmember(EXE_NAME).size
    if size != src.stat().st_size:
        print("make_share: archive did not verify", file=sys.stderr)
        return 1
    sums = write_checksums([out])
    print(f"Shared: {out}; checksums in {sums.name}")
    return 0


def main() -> int:
    if sys.platform.startswith("linux"):
        return linux_bundle()
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
    sums = write_checksums([out, exe, SHARE / f"{EXE_NAME}-Setup.exe"])
    print(f"Shared: {out} ({', '.join(sizes)}); checksums in {sums.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
