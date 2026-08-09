from __future__ import annotations

from trader_pete.analysis import load_narrative_registry, registry_asset_ids
from trader_pete.config import Settings
from trader_pete.models import MarketDataBundle, RunMode
from trader_pete.providers.coingecko import CoinGeckoClient
from trader_pete.providers.defillama import DefiLlamaClient
from trader_pete.providers.fixtures import load_fixture_bundle


def collect_market_data(settings: Settings, mode: RunMode) -> MarketDataBundle:
    if mode is RunMode.OFFLINE:
        return load_fixture_bundle()

    coin_gecko = CoinGeckoClient.from_settings(settings)
    defi_llama = DefiLlamaClient()
    definitions = load_narrative_registry(settings.root_dir / "config" / "narratives.json")
    assets, categories, trending_assets, cg_payloads, cg_observed_at = coin_gecko.collect(
        requested_asset_ids=registry_asset_ids(definitions)
    )
    protocols, activity, dl_payloads, dl_observed_at = defi_llama.collect()
    observed_at = min(cg_observed_at, dl_observed_at)
    return MarketDataBundle(
        observed_at=observed_at,
        assets=assets,
        categories=categories,
        protocols=protocols,
        protocol_activity=activity,
        trending_assets=trending_assets,
        payloads=[*cg_payloads, *dl_payloads],
    )
