"""User-facing text (technical specification §8.6 D4): every string a page shows goes through tr(), so a translation
can be added later without a second pass over the code. Text lives in the presenters, which pass it to the views;
QML uses qsTr() only for strings born in the view.

tr() looks the text up in the installed translation (gettext; none is installed yet, so it returns the text as it
is). Placeholders are filled after the lookup: tr("Restore {name}").format(name=name), so the translated sentence
can move them."""

from __future__ import annotations

import gettext

DOMAIN = "roundtable_souls"

_translation: gettext.NullTranslations = gettext.NullTranslations()


def install(translation: gettext.NullTranslations | None) -> None:
    """Use this translation for tr() from now on (None goes back to the text as written)."""
    global _translation
    _translation = translation or gettext.NullTranslations()


def tr(text: str) -> str:
    """The text in the user's language."""
    return _translation.gettext(text)


def plural(one: str, many: str, n: int) -> str:
    """The singular or plural form for n, in the user's language: plural("{n} job", "{n} jobs", n).format(n=n)."""
    return _translation.ngettext(one, many, n)
