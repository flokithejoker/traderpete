from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trader_pete.config import StrategyPolicy
from trader_pete.db import Database
from trader_pete.models import (
    DailyLandscapeResearch,
    DynamicNarrativeMetrics,
    DynamicNarrativeSnapshot,
    DynamicNarrativeState,
    DynamicRadarSnapshot,
    MarketAsset,
    RunMode,
    RunStatus,
)


def _assets(as_of: datetime, *, missing: set[str] | None = None) -> list[MarketAsset]:
    missing = missing or set()
    rows = [
        ("bitcoin", "BTC", 100_000.0),
        ("alpha", "ALPHA", 10.0),
        ("beta", "BETA", 20.0),
        ("gamma", "GAMMA", 30.0),
    ]
    return [
        MarketAsset(
            asset_id=asset_id,
            symbol=symbol,
            name=asset_id.title(),
            observed_at=as_of,
            price_usd=price,
            market_cap_usd=100_000_000,
            volume_24h_usd=10_000_000,
            change_7d_pct=10,
        )
        for asset_id, symbol, price in rows
        if asset_id not in missing
    ]


def _radar(as_of: datetime) -> DynamicRadarSnapshot:
    metrics = DynamicNarrativeMetrics(
        median_7d_pct=10,
        median_30d_pct=20,
        btc_excess_7d_pct=5,
        breadth_vs_btc_pct=100,
        market_confirmation=70,
        fundamental_confirmation=65,
        search_attention=20,
        evidence_quality=60,
        overheat_risk=10,
        measured_asset_count=3,
        protocol_metric_count=2,
        trending_asset_count=0,
        unique_evidence_roots=2,
        lane_count=3,
    )
    return DynamicRadarSnapshot(
        as_of=as_of,
        narratives=[
            DynamicNarrativeSnapshot(
                narrative_id="test_narrative",
                name="Test narrative",
                mechanism="A test mechanism",
                summary="Point-in-time test cohort.",
                state=DynamicNarrativeState.EMERGING,
                score=70,
                confidence=70,
                persistence_days=2,
                first_seen_at=as_of - timedelta(days=1),
                last_seen_at=as_of,
                catalyst="Test catalyst",
                counter_thesis="Test counter-thesis",
                constituent_ids=["alpha", "beta", "gamma"],
                discovery_lanes=["event", "market", "fundamental"],
                metrics=metrics,
            )
        ],
    )


def _store_run(
    database: Database,
    *,
    as_of: datetime,
    policy: StrategyPolicy,
    status: RunStatus = RunStatus.SUCCEEDED,
) -> tuple[str, list[MarketAsset]]:
    run_id = database.create_run(as_of=as_of, mode=RunMode.LIVE, config={})
    assets = _assets(as_of)
    database.store_market_assets(run_id, assets)
    database.store_dynamic_research(
        run_id=run_id,
        radar=_radar(as_of),
        result=DailyLandscapeResearch(as_of=as_of, market_summary="Test"),
        social_metrics=[],
        model="test",
        reasoning_effort="low",
        prompt_version="test",
        prompt="test",
        response_id=None,
        policy=policy,
        run_mode=RunMode.LIVE,
    )
    database.finish_run(run_id, status)
    return run_id, assets


def test_same_day_reruns_create_one_canonical_cohort(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    as_of = datetime(2026, 1, 1, 8, tzinfo=UTC)
    first, assets = _store_run(database, as_of=as_of, policy=policy)
    database.record_forecast_outcomes(observation_run_id=first, observed_at=as_of, assets=assets)
    second, second_assets = _store_run(database, as_of=as_of + timedelta(hours=2), policy=policy)
    database.record_forecast_outcomes(
        observation_run_id=second,
        observed_at=as_of + timedelta(hours=2),
        assets=second_assets,
    )

    with database.connect() as connection:
        canonical = connection.execute(
            "SELECT COUNT(*) FROM forecast_cohorts WHERE is_canonical = 1"
        ).fetchone()[0]
        raw = connection.execute("SELECT COUNT(*) FROM forecast_cohorts").fetchone()[0]

    assert raw == 2
    assert canonical == 1


def test_failed_observation_cannot_mature_outcome(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    origin, assets = _store_run(database, as_of=start, policy=policy)
    database.record_forecast_outcomes(observation_run_id=origin, observed_at=start, assets=assets)
    failed, failed_assets = _store_run(
        database,
        as_of=start + timedelta(days=7),
        policy=policy,
        status=RunStatus.FAILED,
    )

    with pytest.raises(ValueError, match="succeeded"):
        database.record_forecast_outcomes(
            observation_run_id=failed,
            observed_at=start + timedelta(days=7),
            assets=failed_assets,
        )

    valid, valid_assets = _store_run(database, as_of=start + timedelta(days=8), policy=policy)
    database.record_forecast_outcomes(
        observation_run_id=valid,
        observed_at=start + timedelta(days=8),
        assets=valid_assets,
    )
    with database.connect() as connection:
        outcomes = connection.execute(
            "SELECT observation_run_id FROM forecast_outcomes WHERE cohort_run_id = ?",
            (origin,),
        ).fetchall()

    assert [row["observation_run_id"] for row in outcomes] == [valid]


def test_missing_constituent_never_publishes_aggregate_return(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    start = datetime(2026, 1, 1, 8, tzinfo=UTC)
    origin, assets = _store_run(database, as_of=start, policy=policy)
    database.record_forecast_outcomes(observation_run_id=origin, observed_at=start, assets=assets)
    observation_time = start + timedelta(days=8, hours=13)
    observation, _ = _store_run(database, as_of=observation_time, policy=policy)
    incomplete_assets = _assets(observation_time, missing={"gamma"})
    database.record_forecast_outcomes(
        observation_run_id=observation,
        observed_at=observation_time,
        assets=incomplete_assets,
    )

    with database.connect() as connection:
        outcome = connection.execute(
            """
            SELECT status, median_return_pct, missing_asset_ids_json
            FROM forecast_outcomes
            WHERE cohort_run_id = ? AND horizon_days = 7
            """,
            (origin,),
        ).fetchone()

    assert outcome["status"] == "missed_window"
    assert outcome["median_return_pct"] is None
    assert "gamma" in outcome["missing_asset_ids_json"]
