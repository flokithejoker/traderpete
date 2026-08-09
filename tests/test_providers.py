from datetime import UTC, datetime
from pathlib import Path

import pytest

from trader_pete.config import Settings
from trader_pete.db import Database
from trader_pete.models import ActivityMetricType, RunMode
from trader_pete.providers import collect_market_data
from trader_pete.providers.coingecko import CoinGeckoClient, ProviderConfigurationError
from trader_pete.providers.defillama import DefiLlamaClient


def test_fixture_bundle_is_point_in_time_and_complete(tmp_path: Path, monkeypatch) -> None:
    settings = Settings.from_env(tmp_path)
    bundle = collect_market_data(settings, RunMode.OFFLINE)

    assert len(bundle.assets) >= 10
    assert len(bundle.categories) >= 5
    assert len(bundle.protocols) >= 5
    assert {batch.provider for batch in bundle.payloads} == {"fixture"}
    assert all(asset.observed_at == bundle.observed_at for asset in bundle.assets)
    assert len(bundle.assets) == len({item.asset_id for item in bundle.assets})


def test_market_bundle_persists_without_rewriting_provider_payload(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    settings = Settings.from_env(tmp_path)
    bundle = collect_market_data(settings, RunMode.OFFLINE)
    run_id = database.create_run(
        as_of=datetime(2025, 1, 15, tzinfo=UTC), mode=RunMode.OFFLINE, config={}
    )
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
        protocol_activity=bundle.protocol_activity,
    )

    with database.connect() as connection:
        asset_count = connection.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
        payload_count = connection.execute("SELECT COUNT(*) FROM provider_payloads").fetchone()[0]
        activity_count = connection.execute(
            "SELECT COUNT(*) FROM protocol_activity_snapshots"
        ).fetchone()[0]

    assert asset_count == len(bundle.assets)
    assert payload_count == 4
    assert activity_count == len(bundle.protocol_activity)


def test_live_coingecko_requires_a_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("COINGECKO_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("COINGECKO_PRO_API_KEY", raising=False)
    settings = Settings.from_env(tmp_path)

    with pytest.raises(ProviderConfigurationError):
        CoinGeckoClient.from_settings(settings)


def test_trending_coin_parser_preserves_search_and_market_rank() -> None:
    observed_at = datetime(2026, 8, 9, tzinfo=UTC)

    item = CoinGeckoClient._parse_trending(
        {"id": "new-token", "symbol": "new", "name": "New Token", "market_cap_rank": 412},
        observed_at,
        3,
    )

    assert item.asset_id == "new-token"
    assert item.search_rank == 3
    assert item.market_cap_rank == 412


def test_defillama_activity_parser_uses_week_over_week_growth() -> None:
    observed_at = datetime(2026, 8, 9, tzinfo=UTC)
    metric = DefiLlamaClient._parse_activity(
        {
            "slug": "sample",
            "displayName": "Sample",
            "total7d": 1_000_000,
            "change_7d": 99,
            "change_7dover7d": 0,
        },
        ActivityMetricType.FEES,
        observed_at,
    )

    assert metric.growth_7d_pct == 0
