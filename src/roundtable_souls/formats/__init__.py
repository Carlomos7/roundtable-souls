"""Game and mod-loader file formats: what a file contains and how to read and write it, nothing else.

dcx (the compressed wrapper), bnd4 (archives), fmg (text tables), param (parameter tables), regulation (regulation.bin:
encrypted, compressed, a binder of tables), esd (talk scripts), tae (animation events) and me3_profile (the entries of a
me3 profile, read from its text). The caller passes native (Oodle) compression in (game.oodle makes the codecs); no
module here knows about game folders, settings or the window.
"""


class FormatError(ValueError):
    """The file is not in the expected format (or needs a decompressor that is not available here)."""


from roundtable_souls.formats import (  # noqa: E402  (after FormatError: they use it)
    bnd4,
    dcx,
    fmg,
    me3_profile,
    param,
    regulation,
    tae,
)

__all__ = ["FormatError", "bnd4", "dcx", "fmg", "me3_profile", "param", "regulation", "tae"]
