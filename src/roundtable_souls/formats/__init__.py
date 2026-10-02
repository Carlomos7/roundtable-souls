"""Binary game file formats: what a file contains and how to read and write it, nothing else.

dcx (the compressed wrapper), bnd4 (archives), fmg (text tables), param (parameter tables), regulation (regulation.bin:
encrypted, compressed, a binder of tables) and esd (talk scripts). The caller passes native (Oodle) compression
in (game.oodle makes the codecs); no module here knows about game folders, profiles or the window.
"""


class FormatError(ValueError):
    """The file is not in the expected format (or needs a decompressor that is not available here)."""


from roundtable_souls.formats import bnd4, dcx, fmg, param, regulation  # noqa: E402  (after FormatError: they use it)

__all__ = ["FormatError", "bnd4", "dcx", "fmg", "param", "regulation"]
