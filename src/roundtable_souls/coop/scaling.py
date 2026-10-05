"""Seamless Co-op's difficulty scaling: which keys a file has (six for Elden Ring, three for Nightreign), their labels and presets, and reading the values from an ini."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from roundtable_souls.coop.ini import (
    _key_re,
    _read,
    read_keys,
)

SCALING_KEYS = (
    "enemy_health_scaling",
    "enemy_damage_scaling",
    "enemy_posture_scaling",
    "boss_health_scaling",
    "boss_damage_scaling",
    "boss_posture_scaling",
)

SCALING_LABELS = ("Enemy HP", "Enemy damage", "Enemy posture", "Boss HP", "Boss damage", "Boss posture")

SCALING_PRESETS = {  # % per extra player (Seamless applies each value once per player beyond the host)
    "Seamless default": (35, 0, 15, 100, 0, 20),
    # Nightreign's own rule, from datamined values: enemy and boss HP scale linearly with the party (a Nightlord has
    # 3x its solo HP with three players, so +100 % per extra player, mobs the same), damage does NOT change with
    # player count, and poise goes from 80 solo to 130 with three (about +30 % per extra player).
    "Party of 3 (Nightreign rule)": (100, 0, 30, 100, 0, 30),
    # Larger parties: Seamless keeps adding the per-player value for every extra player, so with these numbers a full
    # party of 4 or 5 lands on the same total as Nightreign's trio (3x HP, ~1.6x poise) instead of 4x or 5x HP.
    "Party of 4": (67, 0, 20, 67, 0, 20),
    "Party of 5": (50, 0, 15, 50, 0, 15),
    "Party of 6": (40, 0, 12, 40, 0, 12),
}

CUSTOM = "Custom"


@dataclass(frozen=True)
class ScalingSpec:
    """The difficulty keys one Seamless Co-op flavour uses, their labels, and the presets offered for them."""

    keys: tuple[str, ...]
    labels: tuple[str, ...]
    presets: dict
    hint: str


ELDEN_RING_SCALING = ScalingSpec(
    SCALING_KEYS, SCALING_LABELS, SCALING_PRESETS, "Percent per extra player. Only the host's numbers count."
)

NIGHTREIGN_SCALING = ScalingSpec(
    ("health_scaling", "damage_scaling", "posture_scaling"),
    ("Enemy HP", "Enemy damage", "Enemy posture"),
    {},
    "Percent, as Seamless Co-op for Nightreign reads them. Only the host's numbers count.",
)

SCALING_SPECS = (ELDEN_RING_SCALING, NIGHTREIGN_SCALING)


def scaling_spec(ini: Path) -> ScalingSpec | None:
    """Which set of difficulty keys this ini has, or None when it has neither complete set."""
    text = _read(ini)
    for spec in SCALING_SPECS:
        if all(_key_re(k).search(text) for k in spec.keys):
            return spec
    return None


def read_scaling(ini: Path, spec: ScalingSpec | None = None):
    """The difficulty values in key order, or None when the ini has no complete set (or a value is not a number)."""
    spec = spec or scaling_spec(ini)
    if spec is None:
        return None
    vals = read_keys(ini, spec.keys)
    try:
        return tuple(int(vals[k]) for k in spec.keys)
    except KeyError, ValueError:
        return None


def preset_of(values, spec: ScalingSpec | None = None):
    presets = (spec or ELDEN_RING_SCALING).presets
    return next((n for n, v in presets.items() if tuple(v) == tuple(values)), CUSTOM)
