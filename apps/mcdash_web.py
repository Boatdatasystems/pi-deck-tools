#!/usr/bin/env python3
# pi-deck-tools: headless
"""Mission Control Web Dashboard — mcdash_web.py

Read-only Flask web view of mcd's current status, reachable from any
device on the boat's hotspot network.  Serves a single HTML page at /
that reads MCD_STATUS_JSON_PATH fresh on every request — no caching,
no background polling, no WebSocket.

Access from any hotspot device at http://10.42.0.1:8765/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, render_template_string

from shared.config import MCD_STATUS_JSON_PATH
from shared.logger import get_logger

logger = get_logger("mcdash_web")

# Port 8765 — chosen to avoid clashes with known Pi services:
#   3000  SignalK  |  3001  Grafana  |  8000  pypilot_web  |  8086  InfluxDB
# Change here and in deploy/mcdash-web.service if something else claims 8765.
PORT = 8765

STATUS_PATH = Path(MCD_STATUS_JSON_PATH)

_TEMPLATE = """\
{% autoescape true %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mission Control — Conachair</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, sans-serif;
      background: #0f1729;
      color: #d8dff0;
      min-height: 100vh;
    }

    header {
      background: #1a2744;
      padding: 0.9rem 1.5rem;
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
      border-bottom: 2px solid #253558;
    }

    h1 {
      font-size: 1.15rem;
      font-weight: 700;
      color: #fff;
      letter-spacing: 0.02em;
    }

    .badge {
      display: inline-block;
      padding: 0.25em 0.7em;
      border-radius: 3px;
      font-size: 0.85rem;
      font-weight: 600;
      white-space: nowrap;
    }
    .badge.ok            { background: #1a6b3a; color: #7efaad; }
    .badge.fail-critical { background: #6b1a1a; color: #fa7e7e; }
    .badge.fail-minor    { background: #5a3a10; color: #f5c87e; }

    .age {
      font-size: 0.78rem;
      color: #6a7a9a;
      white-space: nowrap;
    }

    .refresh {
      margin-left: auto;
      display: inline-block;
      padding: 0.3em 0.9em;
      background: #253558;
      color: #a0b4d8;
      text-decoration: none;
      border-radius: 4px;
      font-size: 0.82rem;
      border: 1px solid #304268;
    }
    .refresh:hover { background: #2e4170; color: #d0e0f8; }

    main { padding: 1.25rem 1.5rem; max-width: 960px; }

    section { margin-bottom: 2rem; }

    h2 {
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #6a7a9a;
      padding-bottom: 0.4rem;
      margin-bottom: 0.5rem;
      border-bottom: 1px solid #253558;
    }

    table { width: 100%; border-collapse: collapse; }

    th {
      text-align: left;
      font-size: 0.7rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #4a5a7a;
      padding: 0.3rem 0.5rem;
    }

    td {
      padding: 0.45rem 0.5rem;
      vertical-align: top;
      border-top: 1px solid #1e2d48;
    }

    tr.fail td { background: rgba(180, 40, 40, 0.07); }

    .dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .dot.ok   { background: #2ecc71; box-shadow: 0 0 4px #2ecc7166; }
    .dot.fail { background: #e74c3c; box-shadow: 0 0 4px #e74c3c88; }

    .col-status { width: 2rem; text-align: center; }
    .col-name   { font-family: 'SFMono-Regular', Consolas, monospace;
                  font-size: 0.87rem; white-space: nowrap; color: #c8d4ec; }
    .col-detail { font-size: 0.83rem; color: #8898b8; }

    /* ── Responsive: narrow phone ── */
    @media (max-width: 600px) {
      header { padding: 0.75rem 1rem; gap: 0.5rem; }
      main   { padding: 0.75rem 1rem; }

      /* Transform table rows into stacked cards */
      table, thead, tbody, tr, th, td { display: block; }
      thead { display: none; }
      tr    { padding: 0.35rem 0; }
      tr + tr { border-top: 1px solid #1e2d48; }
      tr.fail { background: rgba(180, 40, 40, 0.07); padding: 0.35rem 0.4rem; border-radius: 3px; }

      td { padding: 0.1rem 0; border: none; }

      /* Status dot and name on the same line */
      .col-status { display: inline-block; width: auto;
                    padding-right: 0.35rem; vertical-align: middle; }
      .col-name   { display: inline-block; width: auto; vertical-align: middle; }

      /* Detail on its own line, indented */
      .col-detail { display: block; padding-left: 1.4rem;
                    font-size: 0.8rem; color: #6a7a9a; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Mission Control</h1>
    <span class="badge {{ status_class }}">{{ overall_status }}</span>
    <span class="age">updated {{ age_str }}</span>
    <a class="refresh" href="/">Refresh</a>
  </header>

  <main>
    {% if critical_checks %}
    <section>
      <h2>Critical</h2>
      <table>
        <thead>
          <tr>
            <th class="col-status"></th>
            <th class="col-name">Check</th>
            <th class="col-detail">Detail</th>
          </tr>
        </thead>
        <tbody>
          {% for check in critical_checks %}
          <tr class="{{ 'ok' if check.ok else 'fail' }}">
            <td class="col-status">
              <span class="dot {{ 'ok' if check.ok else 'fail' }}"></span>
            </td>
            <td class="col-name">{{ check.name }}</td>
            <td class="col-detail">{{ check.detail }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </section>
    {% endif %}

    {% if noncritical_checks %}
    <section>
      <h2>Non-Critical</h2>
      <table>
        <thead>
          <tr>
            <th class="col-status"></th>
            <th class="col-name">Check</th>
            <th class="col-detail">Detail</th>
          </tr>
        </thead>
        <tbody>
          {% for check in noncritical_checks %}
          <tr class="{{ 'ok' if check.ok else 'fail' }}">
            <td class="col-status">
              <span class="dot {{ 'ok' if check.ok else 'fail' }}"></span>
            </td>
            <td class="col-name">{{ check.name }}</td>
            <td class="col-detail">{{ check.detail }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </section>
    {% endif %}
  </main>
</body>
</html>
{% endautoescape %}
"""

_UNAVAILABLE_TEMPLATE = """\
{% autoescape true %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mission Control — Unavailable</title>
  <style>
    body { font-family: -apple-system, sans-serif; background: #0f1729;
           color: #d8dff0; padding: 2rem; }
    h1   { color: #e74c3c; margin-bottom: 1rem; }
    p    { margin-bottom: 0.75rem; color: #8898b8; }
    a    { color: #5d9cf5; }
  </style>
</head>
<body>
  <h1>Mission Control</h1>
  <p>{{ message }}</p>
  <p><a href="/">Try again</a></p>
</body>
</html>
{% endautoescape %}
"""

app = Flask(__name__)


def _age_string(updated_at_str: str) -> str:
    """Return a human-readable age like '12s ago' or '2m 7s ago'."""
    try:
        dt = datetime.fromisoformat(updated_at_str)
        secs = int((datetime.now(timezone.utc) - dt).total_seconds())
        if secs < 0:
            return "just now"
        if secs < 60:
            return f"{secs}s ago"
        return f"{secs // 60}m {secs % 60}s ago"
    except (ValueError, TypeError):
        return "unknown"


@app.route("/")
def index() -> tuple[str, int] | str:
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("mcd status file not found at %s", STATUS_PATH)
        return (
            render_template_string(
                _UNAVAILABLE_TEMPLATE,
                message="Mission Control data not available — is mcd.service running?",
            ),
            503,
        )
    except json.JSONDecodeError as exc:
        logger.error("mcd status file at %s is invalid JSON: %s", STATUS_PATH, exc)
        return (
            render_template_string(
                _UNAVAILABLE_TEMPLATE,
                message="Status file is corrupt (invalid JSON). Check mcd.service logs.",
            ),
            503,
        )

    summary = data.get("summary", {})
    checks = data.get("checks", [])
    updated_at = data.get("updated_at", "")

    critical_fail_count = summary.get("critical_fail_count", 0)
    fail_count = summary.get("fail_count", 0)

    if critical_fail_count:
        noun = "failure" if critical_fail_count == 1 else "failures"
        overall_status = f"{critical_fail_count} critical {noun}"
        status_class = "fail-critical"
    elif fail_count:
        noun = "issue" if fail_count == 1 else "issues"
        overall_status = f"{fail_count} non-critical {noun}"
        status_class = "fail-minor"
    else:
        overall_status = "All nominal"
        status_class = "ok"

    critical_checks = [c for c in checks if c.get("severity") == "critical"]
    noncritical_checks = [c for c in checks if c.get("severity") != "critical"]

    return render_template_string(
        _TEMPLATE,
        overall_status=overall_status,
        status_class=status_class,
        age_str=_age_string(updated_at),
        critical_checks=critical_checks,
        noncritical_checks=noncritical_checks,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
