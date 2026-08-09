from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trader_pete.config import Settings, StrategyPolicy
from trader_pete.db import Database
from trader_pete.models import (
    ActivityMetricType,
    ProviderBatch,
    RunMode,
    SocialCoverage,
    TokenIdentitySnapshot,
)
from trader_pete.providers import collect_market_data
from trader_pete.providers.coingecko import CoinGeckoClient, ProviderConfigurationError
from trader_pete.providers.defillama import DefiLlamaClient
from trader_pete.providers.investability import InvestabilityCollector


def test_provider_payload_accepts_ohlc_array_rows() -> None:
    batch = ProviderBatch(
        provider="coingecko",
        endpoint="/coins/alpha/ohlc",
        observed_at=datetime(2026, 8, 9, tzinfo=UTC),
        payload=[[1_786_291_200_000, 100.0, 102.0, 99.0, 101.0]],
    )

    assert batch.payload[0][4] == 101.0


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


def test_provider_batches_keep_exact_endpoint_request_manifests() -> None:
    observed_at = datetime(2026, 8, 9, tzinfo=UTC)
    coin_gecko = CoinGeckoClient("demo", "https://api.coingecko.test", "x-demo")
    market_request = {
        "url": "https://api.coingecko.test/coins/markets",
        "params": {"page": 1},
        "received_at": observed_at.isoformat(),
        "status": 200,
        "content_type": "application/json",
    }
    coin_gecko._last_request_record = {
        **market_request,
        "url": "https://api.coingecko.test/search/trending",
    }
    market_batch = coin_gecko._batch(
        provider="coingecko",
        endpoint="/coins/markets",
        observed_at=observed_at,
        payload=[],
        request_manifest=[market_request],
    )

    llama = DefiLlamaClient()
    llama._last_request_record = {
        "url": "https://api.llama.fi/protocols",
        "params": {},
        "received_at": observed_at.isoformat(),
        "status": 200,
        "content_type": "application/json",
    }
    failed_batch = llama._batch(
        provider="defillama",
        endpoint="/overview/fees?dataType=dailyFees",
        observed_at=observed_at,
        payload={"protocols": [], "collection_error": "timeout"},
        request_manifest=[],
    )

    assert market_batch.request_manifest == [market_request]
    assert market_batch.request_manifest[0]["url"].endswith("/coins/markets")
    assert failed_batch.request_manifest == []
    assert failed_batch.http_status is None


def test_goplus_partial_response_and_proxy_status_are_preserved(
    tmp_path: Path, monkeypatch
) -> None:
    settings = replace(Settings.from_env(tmp_path), etherscan_api_key=None)
    policy = StrategyPolicy.load(Path.cwd() / "config" / "strategy_policy.json")
    collector = InvestabilityCollector(settings, policy)
    identity = TokenIdentitySnapshot(
        asset_id="alpha",
        symbol="ALPHA",
        name="Alpha",
        observed_at=datetime(2026, 8, 9, tzinfo=UTC),
        chain_id="ethereum",
        contract_address="0x0000000000000000000000000000000000000001",
        contract_candidates={"ethereum": "0x0000000000000000000000000000000000000001"},
    )

    def fake_get(self, url, params):
        return {
            "code": 2,
            "result": {
                identity.contract_address: {
                    "is_proxy": "1",
                    "is_open_source": "1",
                    "is_honeypot": "0",
                    "cannot_buy": "0",
                    "cannot_sell_all": "0",
                    "is_blacklisted": "0",
                    "hidden_owner": "0",
                    "can_take_back_ownership": "0",
                    "owner_change_balance": "0",
                }
            },
        }

    monkeypatch.setattr(InvestabilityCollector, "_get_json", fake_get)
    security, _ = collector._security(identity, identity.observed_at)

    assert security.coverage is SocialCoverage.PARTIAL
    assert security.is_proxy is True
    assert security.proxy_implementation_verified is None
