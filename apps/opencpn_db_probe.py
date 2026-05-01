#!/usr/bin/env python3
"""
OpenCPN DB probe utility for Raspberry Pi.

Examples:
  python apps/opencpn_db_probe.py --tables
  python apps/opencpn_db_probe.py --routes
  python apps/opencpn_db_probe.py --columns waypoint
  python apps/opencpn_db_probe.py --route "My Route Name"
  python apps/opencpn_db_probe.py --route "My Route Name" --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.opencpn_db import (  # noqa: E402
    OpenCPNDbError,
    list_routes,
    list_tables,
    route_with_waypoints,
    table_columns,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe OpenCPN navobj.db on Raspberry Pi")
    parser.add_argument("--tables", action="store_true", help="List all tables")
    parser.add_argument("--routes", action="store_true", help="List all routes")
    parser.add_argument("--columns", metavar="TABLE", help="List columns for a specific table")
    parser.add_argument("--route", metavar="ROUTE_NAME", help="Extract waypoints for a route name")
    parser.add_argument("--json", action="store_true", help="Print route extraction output as JSON")
    return parser


def print_tables() -> None:
    tables = list_tables()
    print(f"tables: {len(tables)}")
    for t in tables:
        print(f"- {t}")


def print_routes() -> None:
    routes = list_routes()
    print(f"routes: {len(routes)}")
    for r in routes:
        print(f"- {r.name} [{r.route_key_column}={r.route_key_value}] (table={r.table})")


def print_columns(table_name: str) -> None:
    cols = table_columns(table_name)
    if not cols:
        print(f"No columns found for table '{table_name}'.")
        return
    print(f"columns in {table_name}: {len(cols)}")
    for c in cols:
        print(f"- {c}")


def print_route(route_name: str, as_json: bool) -> None:
    payload = route_with_waypoints(route_name)
    if as_json:
        print(json.dumps(payload, indent=2))
        return

    print(f"route: {payload['route_name']}")
    print(f"waypoints: {payload['waypoint_count']}")
    for wp in payload["waypoints"]:
        seq = wp.get("sequence")
        name = wp.get("name") or "(unnamed)"
        lat = wp.get("lat")
        lon = wp.get("lon")
        print(f"- seq={seq} name={name} lat={lat} lon={lon}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not (args.tables or args.routes or args.columns or args.route):
        parser.print_help()
        return 0

    try:
        if args.tables:
            print_tables()
        if args.columns:
            print_columns(args.columns)
        if args.routes:
            print_routes()
        if args.route:
            print_route(args.route, args.json)
        return 0
    except OpenCPNDbError as exc:
        print(f"OpenCPN DB error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
