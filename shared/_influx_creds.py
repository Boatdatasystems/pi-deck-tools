"""Internal credential loader shared by influx_writer and influx_reader.

Both modules need identical credential-loading logic with the same
once-only warning behaviour.  This is the single source of truth for
that logic — neither consumer should duplicate it.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.config import INFLUXDB_CREDENTIALS_PATH
from shared.logger import get_logger

logger = get_logger(__name__)

_credentials_warning_logged = False


def load_credentials() -> dict | None:
    """Load url/token/org/bucket from INFLUXDB_CREDENTIALS_PATH.

    Returns the parsed JSON dict on success, or None if the file is
    absent or malformed.  Logs a WARNING only the first time (module-level
    flag) so a genuinely-absent credentials file doesn't spam the log —
    the feature is meant to stay silently inert until someone sets it up
    on the Pi.
    """
    global _credentials_warning_logged

    path = Path(INFLUXDB_CREDENTIALS_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            creds = json.load(f)
        for key in ("url", "token", "org", "bucket"):
            if key not in creds:
                raise KeyError(key)
        return creds
    except Exception as exc:
        if not _credentials_warning_logged:
            logger.warning(
                "InfluxDB credentials not available (%s); InfluxDB features "
                "will not be active until %s is set up",
                exc,
                path,
            )
            _credentials_warning_logged = True
        return None
