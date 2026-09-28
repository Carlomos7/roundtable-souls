"""Logging: one file per run under the launcher's logs folder, plus any sink the window attaches."""

from __future__ import annotations

import logging
import logging.config
from collections.abc import Callable
from pathlib import Path

LOGGER_NAME = "roundtable_souls"
_FILE_HANDLER: logging.Handler | None = None
_SINK_HANDLER: logging.Handler | None = None


def get_logger(module: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{module}" if module else LOGGER_NAME)


def _config(level: str) -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "line": {"format": "%(asctime)s  %(message)s", "datefmt": "%Y-%m-%d %H:%M:%S"},
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "line", "level": level},
        },
        "loggers": {LOGGER_NAME: {"level": level, "handlers": ["console"], "propagate": False}},
    }


def setup_logging(level: str = "INFO") -> logging.Logger:
    logging.config.dictConfig(_config(level))
    return get_logger()


def start_run_log(log_dir: Path, title: str, filename: str = "last_run.log") -> Path:
    """Truncate the run log and start it with a title line. Later lines append through the file handler."""
    global _FILE_HANDLER
    root = get_logger()
    if _FILE_HANDLER is not None:
        root.removeHandler(_FILE_HANDLER)
        _FILE_HANDLER.close()
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / filename
    _FILE_HANDLER = logging.FileHandler(path, mode="w", encoding="utf-8")
    _FILE_HANDLER.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
    root.addHandler(_FILE_HANDLER)
    root.info("=== %s ===", title)
    return path


class _SinkHandler(logging.Handler):
    def __init__(self, sink: Callable[[str], None]) -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sink(record.getMessage())
        except Exception:  # noqa: BLE001 - a broken sink must never stop a job
            pass


def attach_sink(sink: Callable[[str], None]) -> None:
    """Send every line to a callable as well (the window's log pane). Replaces any earlier sink."""
    global _SINK_HANDLER
    root = get_logger()
    if _SINK_HANDLER is not None:
        root.removeHandler(_SINK_HANDLER)
    _SINK_HANDLER = _SinkHandler(sink)
    root.addHandler(_SINK_HANDLER)
