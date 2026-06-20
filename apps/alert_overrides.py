#!/usr/bin/env python3
"""Per-check alert overrides — apps/alert_overrides.py

Lets mcdash edit mcd's alerting behaviour (enabled/severity/
alert_interval_seconds/sound_file, per check name) without restarting
mcd. mcd reads MCD_ALERT_OVERRIDES_PATH fresh on every fast-loop sweep
(cheap — small file, simple parse), so edits take effect within
MCD_ALERT_INTERVAL_SECONDS.

Only checks with an explicit override appear in the file — everything
else keeps its hardcoded default from the check module that produced it.
Check modules remain the source of DEFAULT values; this module applies
overrides centrally in apps/mcd.py, not inside each check module.

File format:
    {
      "<check_name>": {
        "enabled": true/false,                   # omit to use default (true)
        "severity": "critical"/"non-critical",   # omit to use default
        "alert_interval_seconds": <int>,          # omit to use default
        "sound_file": "<filename>.wav"            # omit to use default
      },
      ...
    }
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from apps.checks import CheckResult
from shared.config import MCD_ALERT_OVERRIDES_PATH
from shared.logger import get_logger

logger = get_logger("alert_overrides")

_OVERRIDE_FIELDS = ("enabled", "severity", "alert_interval_seconds")


def load_overrides() -> dict:
    """Read MCD_ALERT_OVERRIDES_PATH as JSON and return its contents.

    Returns {} if the file doesn't exist. A malformed override file must
    never crash mcd — same lesson as the Obsidian-write crash incident —
    so a JSONDecodeError is logged as a warning and also yields {}.
    """
    path = Path(MCD_ALERT_OVERRIDES_PATH)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        logger.warning("Alert overrides file at %s is invalid JSON: %s; ignoring", path, exc)
        return {}


def apply_overrides(results: list[CheckResult], overrides: dict) -> list[CheckResult]:
    """Return a new list of CheckResults with per-check overrides applied.

    For each result, looks up overrides.get(result.name); where present,
    enabled/severity/alert_interval_seconds are updated from the override
    (only the keys actually present in the override dict — anything not
    specified keeps the check module's existing value). sound_file is not
    applied here; it's read separately where play_critical_alert is
    called, since it's not a CheckResult field.
    """
    updated: list[CheckResult] = []
    for r in results:
        override = overrides.get(r.name)
        if not override:
            updated.append(r)
            continue

        changes = {k: v for k, v in override.items() if k in _OVERRIDE_FIELDS}
        updated.append(replace(r, **changes) if changes else r)
    return updated


def save_overrides(overrides: dict) -> None:
    """Write overrides to MCD_ALERT_OVERRIDES_PATH as JSON, atomically.

    Called by mcdash when the user changes a setting. Atomic write (temp
    file + os.replace), same pattern as apps/mcd.py: write_status_json().
    """
    path = Path(MCD_ALERT_OVERRIDES_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2)
    os.replace(tmp_path, path)
