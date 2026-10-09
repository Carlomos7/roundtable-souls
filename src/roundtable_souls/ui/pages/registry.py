"""The QML pages, registered once: each entry names its QML file and how its adapter is made. A window (the S5 page
window today, the QML shell from S9) and the self-test build every page from this list, so a page added here is
covered by both without editing either."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from roundtable_souls.ui.notifications import Notifier


@dataclass(frozen=True)
class QmlPage:
    name: str
    qml: str  # relative to ui/qml
    make_adapter: Callable[[Any, Notifier], Any]  # (host, notifier) -> the page's adapter


def _activity(host, notifier: Notifier):
    from roundtable_souls.ui.pages.activity.adapter import ActivityAdapter

    return ActivityAdapter(host, notifier)


QML_PAGES: tuple[QmlPage, ...] = (QmlPage("activity", "Pages/ActivityPage.qml", _activity),)


def page(name: str) -> QmlPage:
    return next(p for p in QML_PAGES if p.name == name)
