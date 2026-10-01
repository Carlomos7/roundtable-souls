"""What a merge reports: the result, which parts each mod changed, and where changes met."""

from __future__ import annotations

from dataclasses import dataclass, field

REMOVED = object()  # a part a mod's copy leaves out


@dataclass
class Result:
    data: bytes
    changed: dict[str, list[str]] = field(default_factory=dict)  # inner path -> the mods that changed it
    clashes: dict[str, list[str]] = field(default_factory=dict)  # inner path -> mods whose changes met; the last won
    merged: bool = True  # False: the file could not be merged and the last mod's copy is used whole

    def summary(self) -> str:
        n = len(self.changed)
        text = f"{n} part{'s' if n != 1 else ''} changed"
        if self.clashes:
            text += f", {len(self.clashes)} changed by more than one mod (the later one's used)"
        return text
