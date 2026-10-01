"""Theme review screenshots: every page, the states that only show on interaction, and a board of controls, in light
and dark.

    uv run python scripts/verify/theme_shots.py                       # both themes
    uv run python scripts/verify/theme_shots.py --theme dark --out D:/rs-verify
    uv run python scripts/verify/theme_shots.py --compare BEFORE AFTER  # pixels that differ, per file

Safe by construction: it renders offscreen unless --onscreen is given; Play, offline Play, every job and the update
check are replaced by no-ops, and settings are never written. Nothing is launched.

Inputs and outputs follow the other checks here (see README.md): `--game` and `--out`, or `local.toml`. Shots go to
an output folder of their own, never inside this repository, the game, me3's profiles or a save folder. The launcher's
own data folder (settings, history, caches) is a fresh one inside that output folder; `--launcher-data DIR` copies an
existing one in instead (the original is only read).

The shots are private. The launcher still finds what is on the machine as it always does, so they show its me3
profiles, mod names and characters (only read, never changed). Keep them out of issues and commits; the folders here
ignore PNG files as a second guard.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

if "--onscreen" not in sys.argv and "--compare" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # nothing on the monitor, nothing to press by accident
    if sys.platform == "win32":  # the offscreen platform does not find the system fonts on its own: text draws as boxes
        os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QGridLayout, QVBoxLayout, QWidget  # noqa: E402


def settle(seconds=0.6):
    t0 = time.time()
    while time.time() - t0 < seconds:
        QApplication.processEvents()


def activate(win):
    """Keyboard focus only paints in the active window; a script launched from a terminal may not be allowed to
    take the foreground, so tell Qt directly as well."""
    win.raise_()
    win.activateWindow()
    try:
        QApplication.setActiveWindow(win)
    except AttributeError:
        pass
    settle(0.2)


def focus(widget):
    activate(widget.window())
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    settle(0.2)


LOG_LINES = (
    ("Starting...", "banner"),
    ("launching me3", None),
    ("debug detail", "debug"),
    ("warning: example warning line", None),
    ("error: example error line", None),
)


def fixed_log(pane):
    """The same lines at the same time in every run, so paired shots match."""
    import datetime

    pane.clear()
    for msg, kind in LOG_LINES:
        pane.add(msg, kind=kind)
    at = datetime.datetime(2026, 1, 1, 12, 0, 0)
    pane._rows = [(at if ts else None, level, part) for ts, level, part in pane._rows]
    pane._paint()


def pair(out: Path, names: list[str]):
    """pair-NAME.png: the light shot and the dark shot of the same state, side by side."""
    from PySide6.QtGui import QPainter

    made = []
    for name in names:
        a, b = QImage(str(out / f"light-{name}.png")), QImage(str(out / f"dark-{name}.png"))
        if a.isNull() or b.isNull():
            continue
        gap = 16
        img = QImage(a.width() + gap + b.width(), max(a.height(), b.height()), QImage.Format.Format_RGB32)
        img.fill(QColor("#808080"))
        p = QPainter(img)
        p.drawImage(0, 0, a)
        p.drawImage(a.width() + gap, 0, b)
        p.end()
        img.save(str(out / f"pair-{name}.png"))
        made.append(f"pair-{name}.png")
    return made


def apply_theme(w, dark):
    from qfluentwidgets import Theme, setTheme, setThemeColor

    from roundtable_souls.ui.theme import ACCENT, ACCENT_LIGHT

    setTheme(Theme.DARK if dark else Theme.LIGHT)
    setThemeColor(ACCENT if dark else ACCENT_LIGHT)
    w._restyle()
    settle(0.4)


def states_board(dark):
    """Buttons at rest, focused and disabled, pills, status text, a log with every level and a highlighted editor."""
    from qfluentwidgets import BodyLabel, CaptionLabel, StrongBodyLabel
    from qfluentwidgets import FluentIcon as FI

    from roundtable_souls.ui import theme as th
    from roundtable_souls.ui import widgets as wd
    from roundtable_souls.ui.editor import code_edit

    board = QWidget()
    board.setWindowTitle("states")
    board.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    board.setAutoFillBackground(True)
    pal = board.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(th.BG_DARK if dark else th.BG_LIGHT))
    board.setPalette(pal)
    lay = QVBoxLayout(board)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(14)
    grid = QGridLayout()
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(10)
    buttons = {}
    rows = [
        ("Primary", lambda: th.primary_btn("Save")),
        ("Page action", lambda: th.ghost_btn("Install mod", FI.DOWNLOAD, role="action")),
        ("Secondary", lambda: th.ghost_btn("Options", FI.SETTING)),
        ("Destructive", lambda: th.ghost_btn("Delete profile", FI.DELETE, role="danger")),
    ]
    for r, (label, make) in enumerate(rows):
        grid.addWidget(StrongBodyLabel(label), r, 0)
        for c, state in enumerate(("rest", "focus", "disabled")):
            b = make()
            if state == "disabled":
                b.setEnabled(False)
            buttons[(label, state)] = b
            grid.addWidget(b, r, c + 1)
    lay.addLayout(grid)
    pills = QWidget()
    pl = QGridLayout(pills)
    pl.setContentsMargins(0, 0, 0, 0)
    for i, (text, level) in enumerate(
        (("Done", "ok"), ("Done, with warnings", "warn"), ("Failed", "bad"), ("Running", "busy"), ("Stopped", "muted"))
    ):
        pl.addWidget(wd.StatusPill(text, level), 0, i)
    focus_pill = wd.StatusPill("Parameters OK", "ok")
    focus_pill.setClickable(True)
    pl.addWidget(focus_pill, 0, 5)
    lay.addWidget(pills)
    tones = QWidget()
    tl = QGridLayout(tones)
    tl.setContentsMargins(0, 0, 0, 0)
    for i, level in enumerate(("error", "warning", "warn", "success", "busy", "accent", "muted")):
        lab = CaptionLabel(f"{level}: text says it too")
        th.tone_label(lab, level)
        tl.addWidget(lab, i // 4, i % 4)
    lay.addWidget(tones)
    lay.addWidget(BodyLabel("Body text, and a hint below it."))
    lay.addWidget(th.hint("Descriptions and captions use the muted tone."))
    log = wd.LogPane()
    fixed_log(log)
    log.setFixedHeight(190)
    lay.addWidget(log)
    ed = code_edit("", lang="toml")
    ed.setPlainText(
        '# a comment\n[profile]\nname = "Snow Witch"\nlevel = 153\nenabled = true\n\n[[packages]]\npath = "mod"\n'
    )
    ed.setFixedHeight(190)
    lay.addWidget(ed)
    board.resize(900, 900)
    return board, buttons, focus_pill


def make_harmless():
    """No launch, no job, no settings write, no network: the window can only be looked at."""
    from roundtable_souls import settings
    from roundtable_souls.ui import window

    def nothing(*_a, **_k):
        return None

    window.Launcher.launch = nothing
    window.Launcher.launch_offline = nothing
    window.Launcher.start = nothing
    window.launcher_update = nothing
    window.me3_facts = lambda _setup: {"version": None, "info": {}, "latest": None}
    settings.save_settings = nothing
    if hasattr(window, "save_settings"):
        window.save_settings = nothing


def shoot(out: Path, which: str, size: tuple[int, int]):
    from qfluentwidgets import NavigationPushButton

    from roundtable_souls.ui import theme
    from roundtable_souls.ui.dialogs import ConfirmDialog
    from roundtable_souls.ui.window import Launcher

    if hasattr(theme, "use_theme_text"):  # older checkouts (a baseline run) predate it
        theme.use_theme_text()
    make_harmless()
    out.mkdir(parents=True, exist_ok=True)
    themes = {"light": [False], "dark": [True], "both": [False, True]}[which]
    w = Launcher()
    w.resize(*size)
    w.show()
    settle(2.5)
    for _ in range(40):  # the save loads in the background; both themes should show it
        if not w.hero.name.text().startswith("Reading"):
            break
        settle(0.5)
    settle(0.5)
    saved = []

    def grab(widget, name):
        path = out / f"{name}.png"
        widget.grab().save(str(path))
        saved.append(path.name)

    for dark in themes:
        tag = "dark" if dark else "light"
        apply_theme(w, dark)
        pages = [
            ("play", w.play_page),
            ("coop", w.coop_page),
            ("mods", w.mods_page),
            ("saves", w.saves_page),
            ("activity", w.activity_page),
            ("settings", w.tools_page),
        ]
        for name, pg in pages:
            w.switchTo(pg)
            settle()
            grab(w, f"{tag}-{name}")

        w.switchTo(w.play_page)
        settle()
        w.play_btn.setEnabled(False)
        w.game_btn.setEnabled(False)
        settle(0.3)
        grab(w, f"{tag}-play-disabled")
        w.play_btn.setEnabled(True)
        w.game_btn.setEnabled(True)

        focus(w.play_btn)
        grab(w, f"{tag}-play-focus")
        w.setFocus(Qt.FocusReason.OtherFocusReason)

        fixed_log(w.log_pane)
        w.log_exp.setExpand(True)
        settle(0.8)
        w.play_page.verticalScrollBar().setValue(w.play_page.verticalScrollBar().maximum())
        settle(0.3)
        grab(w, f"{tag}-play-log")
        w.log_exp.setExpand(False)
        w.play_page.verticalScrollBar().setValue(0)
        settle(0.5)

        w.switchTo(w.coop_page)
        settle()
        w.save_bar.set_state(True, "Not saved: session password")
        settle(0.3)
        grab(w, f"{tag}-coop-pending")
        w.save_bar.set_state(False, "Saved.")

        # sidebar: Mods hovered, Saves focused, Co-op selected
        w.switchTo(w.coop_page)
        settle()
        # The rows only paint hover while the pointer is over them; point the paint's cursor at Mods instead of
        # moving the real pointer.
        from qfluentwidgets.components.navigation import navigation_widget

        from roundtable_souls.ui import widgets

        rows = {r.text(): r for r in w.navigationInterface.findChildren(NavigationPushButton)}
        mods = rows.get("Mods")
        fakes = []
        if mods is not None:
            at = mods.mapToGlobal(mods.rect().center())
            fake = type("Pointer", (), {"pos": staticmethod(lambda at=at: at)})
            for mod in (widgets, navigation_widget):
                if hasattr(mod, "QCursor"):
                    fakes.append((mod, mod.QCursor))
                    mod.QCursor = fake  # pyright: ignore[reportAttributeAccessIssue]
            mods.isEnter = True
        if rows.get("Saves") is not None:
            focus(rows["Saves"])
        if mods is not None:
            mods.update()
        settle(0.3)
        grab(w, f"{tag}-sidebar-states")
        for mod, real in fakes:
            mod.QCursor = real
        if mods is not None:
            mods.isEnter = False
            mods.update()
        w.setFocus(Qt.FocusReason.OtherFocusReason)

        menu = w._game_menu_view
        menu.exec(w.game_btn.mapToGlobal(QPoint(0, w.game_btn.height() + 4)))
        settle(0.8)
        grab(menu, f"{tag}-game-menu")
        menu.close()
        settle(0.3)

        dlg = ConfirmDialog(
            "Delete this profile?",
            w,
            changes=["Moves myprofile.me3 into the launcher's deleted profiles", "Mod folders stay where they are"],
            safety="It can be put back from Settings.",
            warning="This changes files on disk.",
            apply_text="Delete",
            second_text="Keep a copy",
        )
        dlg.show()
        settle(0.8)
        focus(dlg.cancelButton)
        grab(dlg, f"{tag}-dialog")
        dlg.close()
        settle(0.3)

        try:
            board, buttons, focus_pill = states_board(dark)
        except TypeError as exc:  # an older checkout (a baseline run) without button roles
            print("states board skipped:", exc)
            continue
        board.show()
        settle(0.5)
        activate(board)
        board.setFocus(Qt.FocusReason.OtherFocusReason)  # nothing focused in the resting frame
        settle(0.2)
        grab(board, f"{tag}-states")
        for (label, state), b in buttons.items():
            if state == "focus":
                focus(b)
                grab(board, f"{tag}-states-focus-{label.lower().replace(' ', '-')}")
        focus(focus_pill)
        grab(board, f"{tag}-states-focus-pill")
        board.close()
        settle(0.2)

    if which == "both":
        names = sorted({n[len("light-") : -len(".png")] for n in saved if n.startswith("light-")})
        saved += pair(out, names)
    print("shots in", out)
    for name in saved:
        print(" ", name)


def compare(before: Path, after: Path):
    for a in sorted(after.glob("*.png")):
        b = before / a.name
        if not b.is_file():
            print(f"{a.name}: no baseline")
            continue
        ia, ib = QImage(str(a)), QImage(str(b))
        if ia.size() != ib.size():
            print(f"{a.name}: size {ib.width()}x{ib.height()} -> {ia.width()}x{ia.height()}")
            continue
        ia = ia.convertToFormat(QImage.Format.Format_RGB32)
        ib = ib.convertToFormat(QImage.Format.Format_RGB32)
        diff = sum(1 for y in range(ia.height()) for x in range(ia.width()) if ia.pixel(x, y) != ib.pixel(x, y))
        print(f"{a.name}: {diff} px differ" + ("" if diff else " (identical)"))


def find_game(given: Path | None) -> Path | None:
    """The game folder if one is given or configured (then it must be valid); otherwise None, and the launcher looks
    for the game the way it always does, or runs without one."""
    if given is not None or "game" in _common.settings():
        return _common.game_dir(given)
    return None


def prepare(args) -> tuple[Path, Path | None]:
    """The output folder and the game folder; the launcher's code is sandboxed into the output folder."""
    game = find_game(args.game)
    out = _common.output_dir(args.out, "theme-shots", game)
    if args.launcher_data is not None:
        source = Path(args.launcher_data)
        if not source.is_dir():
            sys.exit(f"no launcher data folder at {source}")
        shutil.copytree(source, out / "launcher-data", ignore=shutil.ignore_patterns("logs", "temp", "*.bak"))
    _common.sandbox_launcher(out, game)
    return out / "shots", game


def main():
    p = _common.parser(__doc__ or "")
    p.add_argument("--theme", choices=("light", "dark", "both"), default="both")
    p.add_argument("--size", default="1080x760", help="window size, WIDTHxHEIGHT")
    p.add_argument("--launcher-data", type=Path, help="a launcher data folder to copy into the sandbox (read only)")
    p.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    p.add_argument("--onscreen", action="store_true", help="show the window (default: render offscreen)")
    args = p.parse_args()
    _app = QApplication(sys.argv)
    if args.compare:
        compare(*args.compare)
        return
    shots, _game = prepare(args)
    size = tuple(int(n) for n in args.size.lower().split("x"))
    shoot(shots, args.theme, size)  # pyright: ignore[reportArgumentType]
    sys.stdout.flush()
    os._exit(0)  # the shots are written; skip Qt's teardown of the half-closed window and menus, which can crash


if __name__ == "__main__":
    main()
