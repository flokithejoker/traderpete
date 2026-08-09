from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from trader_pete.analysis import analyze_landscape, load_narrative_registry
from trader_pete.analysis.dynamic import build_dynamic_radar
from trader_pete.analysis.paper import evaluate_paper_candidates, select_investability_assets
from trader_pete.config import Settings, StrategyPolicy
from trader_pete.db import Database
from trader_pete.models import InvestabilityDataBundle, RunMode, RunStatus, utc_now
from trader_pete.providers import collect_market_data
from trader_pete.providers.investability import InvestabilityCollector
from trader_pete.providers.social import SocialTarget, collect_social_metrics
from trader_pete.reporting.dashboard import DashboardRenderer
from trader_pete.research.dynamic import DynamicNarrativeResearcher
from trader_pete.research.narratives import QUALITY_REASONING_EFFORT, LandscapeResearcher


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
                request_params_hash=payload.request_params_hash,
                response_received_at=payload.response_received_at,
                http_status=payload.http_status,
                content_type=payload.content_type,
                request_manifest=payload.request_manifest,
            )
        database.store_market_bundle(
            run_id=run_id,
            assets=bundle.assets,
            categories=bundle.categories,
            protocols=bundle.protocols,
            protocol_activity=bundle.protocol_activity,
            trending_assets=bundle.trending_assets,
        )
        definitions = load_narrative_registry(settings.root_dir / "config" / "narratives.json")
        policy = StrategyPolicy.load(settings.root_dir / "config" / "strategy_policy.json")
        landscape = analyze_landscape(
            bundle,
            definitions,
            max_focus=settings.max_narratives,
        )
        dynamic_output = DynamicNarrativeResearcher(settings).research(
            bundle,
            landscape,
            offline=mode is RunMode.OFFLINE,
        )
        history = database.dynamic_history(dynamic_output.prompt_version)
        preliminary_radar = build_dynamic_radar(
            dynamic_output.result,
            bundle=bundle,
            parent_ids={item.id for item in definitions},
            history=history,
            limit=settings.candidate_narratives,
        )
        asset_symbols = {item.asset_id: item.symbol for item in bundle.assets}
        social_targets = [
            SocialTarget(
                target_type="dynamic_narrative",
                target_id=item.narrative_id,
                label=item.name,
                query_terms=(item.name, *item.aliases[:2]),
            )
            for item in preliminary_radar.narratives
        ]
        social_targets.extend(
            SocialTarget(
                target_type="project",
                target_id=item.project_id,
                label=item.name,
                query_terms=tuple(
                    value
                    for value in (
                        item.name,
                        f"${asset_symbols[item.asset_id]}"
                        if item.asset_id in asset_symbols
                        else "",
                    )
                    if value
                ),
            )
            for item in landscape.projects
            if item.research_eligible
            and any(
                narrative.narrative_id == item.narrative_id and narrative.is_focus
                for narrative in landscape.narratives
            )
            and item.rank <= 2
        )
        social_metrics = collect_social_metrics(settings, social_targets)
        radar = build_dynamic_radar(
            dynamic_output.result,
            bundle=bundle,
            parent_ids={item.id for item in definitions},
            history=history,
            social_metrics=social_metrics,
            limit=settings.candidate_narratives,
        )
        output = LandscapeResearcher(settings).research(
            bundle,
            landscape,
            radar,
            social_metrics,
            offline=mode is RunMode.OFFLINE,
        )
        database.store_landscape_research(
            run_id=run_id,
            landscape=landscape,
            result=output.result,
            model=settings.model if mode is RunMode.LIVE else "offline-fixture",
            reasoning_effort=(QUALITY_REASONING_EFFORT if mode is RunMode.LIVE else "offline"),
            prompt_version=output.prompt_version,
            prompt=output.prompt,
            response_id=output.response_id,
            retrieved_urls=output.retrieved_urls,
            source_manifest=output.retrieval_manifest,
        )
        database.store_dynamic_research(
            run_id=run_id,
            radar=radar,
            result=output.result,
            social_metrics=social_metrics,
            model=settings.model if mode is RunMode.LIVE else "offline-fixture",
            reasoning_effort=settings.reasoning_effort,
            prompt_version=dynamic_output.prompt_version,
            prompt=dynamic_output.prompt,
            response_id=dynamic_output.response_id,
            policy=policy,
            run_mode=mode,
            quality_prompt_version=output.prompt_version,
            retrieved_urls=dynamic_output.retrieved_urls,
            source_manifest=dynamic_output.retrieval_manifest,
            dynamic_draft=dynamic_output.result,
        )
        required_assets = database.paper_assets_requiring_quotes()
        investability_asset_ids = select_investability_assets(
            radar,
            output.result,
            bundle,
            policy,
            required_asset_ids=required_assets,
        )
        if mode is RunMode.LIVE:
            investability = InvestabilityCollector(settings, policy).collect(
                investability_asset_ids
            )
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
        else:
            investability = InvestabilityDataBundle(observed_at=radar.as_of)
        prospective_days = database.prospective_days_for_run(run_id)
        paper_evaluation = evaluate_paper_candidates(
            radar,
            output.result,
            investability,
            policy,
            prospective_days=prospective_days,
        )
        database.store_paper_evidence(
            run_id=run_id,
            investability=investability,
            evaluation=paper_evaluation,
            policy=policy,
        )
        is_canonical = database.finalize_canonical_run(run_id)
        database.finalize_paper_decision(
            run_id=run_id,
            evaluation=paper_evaluation,
            policy=policy,
            is_canonical=is_canonical,
            run_mode=mode,
        )
        database.complete_daily_run(run_id)
        database.settle_approved_entries(quote_run_id=run_id, policy=policy)
        database.record_forecast_outcomes(
            observation_run_id=run_id,
            observed_at=bundle.observed_at,
            assets=bundle.assets,
        )
        renderer = DashboardRenderer(database=database, reports_dir=settings.reports_dir)
        artifact = renderer.render(run_id)
        database.store_dashboard_artifact(run_id, artifact.path, artifact.sha256)
        return DailyRunResult(run_id=run_id, report_path=artifact.path)
    except Exception as error:
        with suppress(ValueError):
            database.finish_run(run_id, RunStatus.FAILED, error=str(error))
        raise
