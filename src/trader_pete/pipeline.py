from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trader_pete.config import Settings
from trader_pete.db import Database
from trader_pete.models import RunMode, RunStatus, utc_now
from trader_pete.providers import collect_market_data
from trader_pete.reporting.dashboard import DashboardRenderer
from trader_pete.research.narratives import NarrativeResearcher


@dataclass(frozen=True, slots=True)
class DailyRunResult:
    run_id: str
    report_path: Path


def run_daily(settings: Settings, mode: RunMode) -> DailyRunResult:
    database = Database(settings.db_path)
    database.initialize()
    run_id = database.create_run(as_of=utc_now(), mode=mode, config=settings.safe_dict())
    try:
        bundle = collect_market_data(settings, mode)
        for payload in bundle.payloads:
            database.store_payload(
                run_id=run_id,
                provider=payload.provider,
                endpoint=payload.endpoint,
                observed_at=payload.observed_at,
                payload=payload.payload,
            )
        database.store_market_bundle(
            run_id=run_id,
            assets=bundle.assets,
            categories=bundle.categories,
            protocols=bundle.protocols,
            trending_assets=bundle.trending_assets,
        )
        output = NarrativeResearcher(settings).research(
            bundle,
            offline=mode is RunMode.OFFLINE,
        )
        database.store_research(
            run_id=run_id,
            result=output.result,
            model=settings.model if mode is RunMode.LIVE else "offline-fixture",
            reasoning_effort=settings.reasoning_effort,
            prompt_version=output.prompt_version,
            prompt=output.prompt,
            response_id=output.response_id,
        )
        database.finish_run(run_id, RunStatus.SUCCEEDED)
        renderer = DashboardRenderer(database=database, reports_dir=settings.reports_dir)
        artifact = renderer.render(run_id)
        database.store_dashboard_artifact(run_id, artifact.path, artifact.sha256)
        return DailyRunResult(run_id=run_id, report_path=artifact.path)
    except Exception as error:
        database.finish_run(run_id, RunStatus.FAILED, error=str(error))
        raise
