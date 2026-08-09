from __future__ import annotations

import argparse
import json
from pathlib import Path

from trader_pete.config import Settings, StrategyPolicy
from trader_pete.db import Database
from trader_pete.models import RunMode
from trader_pete.paper_service import refresh_and_fill_approved_proposal
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
    proposals = subparsers.add_parser(
        "paper-proposals", help="List immutable paper proposals and their current event state."
    )
    proposals.add_argument("--all", action="store_true", help="Include terminal proposals.")
    approve = subparsers.add_parser(
        "approve", help="Approve one exact paper proposal packet; this never places an order."
    )
    approve.add_argument("proposal_id")
    approve.add_argument("--reason", default="")
    reject = subparsers.add_parser("reject", help="Reject one paper proposal packet.")
    reject.add_argument("proposal_id")
    reject.add_argument("--reason", default="")
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

    if args.command == "paper-proposals":
        rows = Database(settings.db_path).list_paper_proposals(active_only=not args.all)
        print(
            json.dumps(
                [
                    {
                        "id": row["id"],
                        "asset_id": row["asset_id"],
                        "intent": row["intent"],
                        "status": row["status"],
                        "notional_usd": row["proposed_notional_usd"],
                        "maximum_initial_loss_usd": row["maximum_initial_loss_usd"],
                        "approval_deadline": row["approval_deadline"],
                    }
                    for row in rows
                ],
                indent=2,
            )
        )
        return 0

    if args.command in {"approve", "reject"}:
        policy = StrategyPolicy.load(settings.root_dir / "config" / "strategy_policy.json")
        Database(settings.db_path).record_proposal_response(
            args.proposal_id,
            approve=args.command == "approve",
            reason=args.reason,
            expected_policy_hash=policy.policy_hash if args.command == "approve" else None,
        )
        if args.command == "approve":
            fills = refresh_and_fill_approved_proposal(settings, args.proposal_id, policy)
            outcome = f"paper fill {fills[0]}" if fills else "no qualifying paper fill"
            print(f"Approved {args.proposal_id}: {outcome}. No live order was sent.")
        else:
            print(f"Rejected {args.proposal_id}; no live order was sent.")
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
