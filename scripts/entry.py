"""PyInstaller entry point: the same two lines as roundtable_souls/__main__.py, kept as a file outside the package.

PyInstaller is given a script file to freeze. Handing it the package's own __main__.py would freeze that file as the
program's __main__ module and collect the package around it as a side effect; a script outside the package imports
roundtable_souls like any caller, so the frozen program and `python -m roundtable_souls` start the same way. The
console script (pyproject.toml's [project.scripts]) does not exist inside a frozen exe, hence a file.
"""

import sys

from roundtable_souls.cli import main

sys.exit(main())
