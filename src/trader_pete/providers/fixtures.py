from __future__ import annotations

import json
from importlib.resources import files

from trader_pete.models import (
    CategoryMarket,
    MarketAsset,
    MarketDataBundle,
    ProtocolActivityMetric,
    ProtocolMetric,
    ProviderBatch,
)


def _read_fixture(name: str) -> list[dict[str, object]]:
    path = files("trader_pete").joinpath("fixtures", name)
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture_bundle() -> MarketDataBundle:
    market_payload = _read_fixture("markets.json")
    category_payload = _read_fixture("categories.json")
    protocol_payload = _read_fixture("protocols.json")
    activity_payload = _read_fixture("protocol_activity.json")
    assets = [MarketAsset.model_validate(item) for item in market_payload]
    categories = [CategoryMarket.model_validate(item) for item in category_payload]
    protocols = [ProtocolMetric.model_validate(item) for item in protocol_payload]
    activity = [ProtocolActivityMetric.model_validate(item) for item in activity_payload]
    observed_at = min(
        *(asset.observed_at for asset in assets),
        *(category.observed_at for category in categories),
        *(protocol.observed_at for protocol in protocols),
        *(metric.observed_at for metric in activity),
    )
    return MarketDataBundle(
        observed_at=observed_at,
        assets=assets,
        categories=categories,
        protocols=protocols,
        protocol_activity=activity,
        trending_assets=[],
        payloads=[
            ProviderBatch(
                provider="fixture",
                endpoint="markets.json",
                observed_at=observed_at,
                payload=market_payload,
            ),
            ProviderBatch(
                provider="fixture",
                endpoint="categories.json",
                observed_at=observed_at,
                payload=category_payload,
            ),
            ProviderBatch(
                provider="fixture",
                endpoint="protocols.json",
                observed_at=observed_at,
                payload=protocol_payload,
            ),
            ProviderBatch(
                provider="fixture",
                endpoint="protocol_activity.json",
                observed_at=observed_at,
                payload=activity_payload,
            ),
        ],
    )
