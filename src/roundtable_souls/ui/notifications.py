"""The notification helpers every QML page uses (technical specification §8.10, "how the launcher talks"): the
status text (the one place launcher state shows), the page InfoBar (a lasting condition on this page), a toast (the
result of what the user just did; errors stay until closed) and the confirmation dialog (before a change). A page's
adapter calls them; the window (or, from S9, the shell) shows them with the QML components of the same names.

Plain Python callers: status(), info(), clear_info(), toast(), confirm(). QML reads statusText / infoText /
infoSeverity, listens to toastRequested and confirmRequested, and answers a confirmation with answer()."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot


class Notifier(QObject):
    statusChanged = Signal()
    infoChanged = Signal()
    toastRequested = Signal(str, bool)  # text, is an error
    # token, title, the changes (one per line), the safety line, the apply button's text, destructive
    confirmRequested = Signal(int, str, list, str, str, bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._status = ""
        self._info = ("", "info")
        self._waiting: dict[int, Callable[[bool], None]] = {}
        self._next = 0

    # ---- the status text
    def status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    statusText = Property(str, lambda self: self._status, notify=statusChanged)

    # ---- the InfoBar
    def info(self, text: str, severity: str = "info") -> None:
        """Show a lasting condition (severity info | success | warning | error) until clear_info()."""
        if (text, severity) != self._info:
            self._info = (text, severity)
            self.infoChanged.emit()

    @Slot()
    def clear_info(self) -> None:
        self.info("")

    infoText = Property(str, lambda self: self._info[0], notify=infoChanged)
    infoSeverity = Property(str, lambda self: self._info[1], notify=infoChanged)

    # ---- toasts
    def toast(self, text: str, error: bool = False) -> None:
        self.toastRequested.emit(text, error)

    # ---- the confirmation dialog
    def confirm(
        self,
        title: str,
        changes: list[str] | tuple[str, ...],
        safety: str,
        apply_text: str,
        on_answer: Callable[[bool], None],
        destructive: bool = False,
    ) -> int:
        """Ask before a change; on_answer(True) when the user applies it, (False) when they cancel."""
        self._next += 1
        self._waiting[self._next] = on_answer
        self.confirmRequested.emit(self._next, title, list(changes), safety, apply_text, destructive)
        return self._next

    @Slot(int, bool)
    def answer(self, token: int, ok: bool) -> None:
        call = self._waiting.pop(token, None)
        if call is not None:
            call(ok)

    def waiting(self) -> int:
        """How many confirmations are still unanswered."""
        return len(self._waiting)
