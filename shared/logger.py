"""Shared logging setup for pi-deck-tools.

All apps and shared modules call get_logger(__name__) to obtain a named
logger that writes to ~/pi-deck-tools.log and prints WARNING+ to stderr.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import LOG_PATH

_FORMATTER = logging.Formatter(
    fmt="%(asctime)s  %(name)-30s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _build_root_logger() -> logging.Logger:
    root = logging.getLogger("pi_deck_tools")
    if root.handlers:
        return root

    root.setLevel(logging.DEBUG)

    fh = RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(_FORMATTER)
    root.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.WARNING)
    sh.setFormatter(_FORMATTER)
    root.addHandler(sh)

    if not sys.stdout.isatty():
        # Running non-interactively (e.g. under systemd) — send everything
        # to stdout too, so it lands in journald rather than only the file.
        oh = logging.StreamHandler(sys.stdout)
        oh.setLevel(logging.DEBUG)
        oh.setFormatter(_FORMATTER)
        root.addHandler(oh)

    return root


_ROOT_LOGGER = _build_root_logger()


def get_logger(name: str) -> logging.Logger:
    """Return a named child logger under the pi_deck_tools root."""
    return _ROOT_LOGGER.getChild(name)
