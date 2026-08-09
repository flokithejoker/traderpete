from __future__ import annotations

import argparse
import json
from pathlib import Path

from trader_pete.config import Settings
from trader_pete.db import Database
from trader_pete.models import RunMode
from trader_pete.pipeline import run_daily


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trader-pete",
        description="Narrative-first crypto market research.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="Create or update the local SQLite schema.")
    subparsers.add_parser("doctor", help="Show safe configuration and provider readiness.")
    daily = subparsers.add_parser("run-daily", help="Collect, research, store, and render.")
    daily.add_argument(
        "--offline",
        action="store_true",
        help="Use fixed fixtures and make no provider or OpenAI calls.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings.from_env(Path.cwd())

    if args.command == "init-db":
        Database(settings.db_path).initialize()
        print(f"Initialized {settings.db_path}")
        return 0

    if args.command == "doctor":
        print(json.dumps(settings.safe_dict(), indent=2))
        return 0

    if args.command == "run-daily":
        mode = RunMode.OFFLINE if args.offline else RunMode.LIVE
        result = run_daily(settings, mode)
        print(f"Run: {result.run_id}")
        print(f"Report: {result.report_path}")
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
