"""Set the version in pyproject.toml and the package, ready to commit and tag.

uv run python scripts/bump_version.py 3.2.0-beta.1   a beta (Beta channel only; every version starts as betas)
uv run python scripts/bump_version.py 3.2.0          the stable release (both channels), from the last beta's commit
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = r"\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?"
FILES = {
    ROOT / "pyproject.toml": re.compile(rf'^version = "({VERSION})"$', re.M),
    ROOT / "src" / "roundtable_souls" / "__init__.py": re.compile(rf'^__version__ = "({VERSION})"$', re.M),
}


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(VERSION, sys.argv[1]):
        print(__doc__, file=sys.stderr)
        return 2
    new = sys.argv[1]
    for path, rx in FILES.items():
        text = path.read_text(encoding="utf-8")
        if not rx.search(text):
            print(f"no version line in {path}", file=sys.stderr)
            return 1
        path.write_text(
            rx.sub(lambda m: m.group(0).replace(m.group(1), new), text, count=1), encoding="utf-8", newline="\n"
        )
        print(f"{path.relative_to(ROOT)}: {new}")
    print(
        f'\nNext:\n  uv lock\n  git commit -am "Release {new}"\n  git tag -a v{new} -m "Roundtable Souls {new}"\n'
        "  git push && git push --tags\n\nThe Release workflow publishes a vX.Y.Z-beta.N tag to the Beta channel and a plain vX.Y.Z to both channels."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
