from __future__ import annotations

from contextlib import suppress

from trader_pete.config import Settings, StrategyPolicy
from trader_pete.db import Database
from trader_pete.models import RunMode, RunStatus, utc_now
from trader_pete.providers.investability import InvestabilityCollector


def refresh_and_fill_approved_proposal(
    settings: Settings,
    proposal_id: str,
    policy: StrategyPolicy | None = None,
) -> list[str]:
    """Collect a post-approval quote and simulate a fill; never send a live order."""
    database = Database(settings.db_path)
    proposal = database.proposal(proposal_id)
    policy = policy or StrategyPolicy.load(settings.root_dir / "config" / "strategy_policy.json")
    if proposal["policy_hash"] != policy.policy_hash:
        raise ValueError("The active policy no longer matches the approved proposal packet.")
    run_id = database.create_run(
        as_of=utc_now(),
        mode=RunMode.LIVE,
        config={**settings.safe_dict(), "purpose": "paper_quote_refresh"},
    )
    try:
        investability = InvestabilityCollector(settings, policy).collect([proposal["asset_id"]])
        for payload in investability.payloads:
            database.store_payload(
                run_id=run_id,
                provider=payload.provider,
                endpoint=payload.endpoint,
                observed_at=payload.observed_at,
                payload=payload.payload,
                request_params_hash=payload.request_params_hash,
                response_received_at=payload.response_received_at,
                http_status=payload.http_status,
                content_type=payload.content_type,
                request_manifest=payload.request_manifest,
            )
        database.store_venue_quotes(run_id=run_id, investability=investability)
        database.finish_run(run_id, RunStatus.SUCCEEDED)
        return database.settle_approved_entries(
            quote_run_id=run_id,
            policy=policy,
            proposal_id=proposal_id,
        )
    except Exception as error:
        with suppress(ValueError):
            database.finish_run(run_id, RunStatus.FAILED, error=str(error))
        raise
