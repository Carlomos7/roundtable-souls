"""Files shipped inside the package: item lists and the window's icon and logos."""

from importlib.resources import files
from pathlib import Path

PACKAGE_DIR = Path(str(files("roundtable_souls")))
DATA_DIR = PACKAGE_DIR / "data"
ASSETS_DIR = PACKAGE_DIR / "assets"
