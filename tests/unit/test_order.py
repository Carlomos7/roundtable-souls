"""mods.order, the port of me3's sort_dependencies: me3's own tests, and me3's answers on generated profiles
(tests/unit/order_cases.json, made by running me3's code at the pinned commit)."""

import json
from pathlib import Path

import pytest

from roundtable_souls.mods import order

CASES = json.loads((Path(__file__).parent / "order_cases.json").read_text(encoding="utf-8"))


def items(packages: list[dict]) -> list[order.Item]:
    def deps(raw):
        return [order.Dependent(d["id"], d["optional"]) for d in raw]

    return [order.Item(p.get("id") or p["path"], deps(p["load_after"]), deps(p["load_before"])) for p in packages]


def answer(packages: list[dict]) -> dict:
    try:
        return {"order": [i.id for i in order.sort_dependencies(items(packages))]}
    except order.OrderError as e:
        return {"error": str(e)}


def pkg(ident, after=(), before=()):
    return {"id": ident, "path": ident, "load_after": [{"id": d, "optional": False} for d in after],
            "load_before": [{"id": d, "optional": False} for d in before]}  # fmt: skip


# me3's tests (crates/mod-protocol/src/dependency.rs at the pinned commit)
def test_detect_cycles():
    with pytest.raises(order.Cyclic):
        order.sort_dependencies(items([pkg("pkg1", ["pkg2"]), pkg("pkg2", ["pkg1"])]))


def test_loads_before_and_after():
    got = answer([pkg("pkg1", ["pkg2"]), pkg("pkg2"), pkg("pkg3", ["pkg2"], ["pkg1"])])["order"]
    assert got[:3] == ["pkg2", "pkg3", "pkg1"]


def test_loads_after():
    assert answer([pkg("pkg1", ["pkg2"]), pkg("pkg2"), pkg("pkg3")])["order"][:2] == ["pkg2", "pkg1"]


def test_smoke_test():
    assert answer([pkg("pkg1"), pkg("pkg2"), pkg("pkg3")])["order"] == ["pkg1", "pkg2", "pkg3"]


def test_preserves_iteration_order():
    got = answer([pkg("pkg1"), pkg("pkg2"), pkg("pkg3", [], ["pkg2"]), pkg("pkg4", [], ["pkg2"]), pkg("pkg5")])
    assert got["order"] == ["pkg1", "pkg3", "pkg4", "pkg2", "pkg5"]


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["name"])
def test_the_same_answer_as_me3(case):
    assert answer(case["items"]) == case["me3"]


def test_the_cases_cover_orders_and_refusals():
    kinds = {"order" if "order" in c["me3"] else "error" for c in CASES["cases"]}
    assert kinds == {"order", "error"} and len(CASES["cases"]) > 400


def test_a_missing_required_dependency_and_a_cycle_name_what_me3_names():
    with pytest.raises(order.MissingDependency, match="Required dependency is unavailable: gone"):
        order.sort_dependencies(items([pkg("a", ["gone"])]))
    with pytest.raises(order.Cyclic) as e:
        order.sort_dependencies(items([pkg("a", ["b"]), pkg("b", ["a"]), pkg("c")]))
    assert str(e.value) == 'Dependencies resulted in cycles, remaining dependencies: ["a", "b", "c"]'


@pytest.mark.parametrize(
    ("version", "known"),
    [("0.13.0", True), ("v0.11.0", True), ("0.12.1-beta", True), ("1.0", True), ("0.10.2", None), ("", None),
     ("nightly", None)],
)  # fmt: skip
def test_which_me3_versions_this_order_is_known_to_match(version, known):
    assert order.supported(version) is known
