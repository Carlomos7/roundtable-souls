"""PyInstaller entry point (the console script is not available inside a frozen exe)."""

import sys

from roundtable_souls import main

sys.exit(main())
