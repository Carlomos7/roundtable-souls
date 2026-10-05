"""Opening a folder, file or URL with the desktop's default handler."""

import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"


def open_path(target) -> None:
    """Open a folder, file or URL with the desktop's default handler."""
    target = str(target)
    if IS_WINDOWS:
        os.startfile(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
