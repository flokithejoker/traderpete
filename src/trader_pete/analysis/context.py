from __future__ import annotations

from statistics import median

from trader_pete.models import MarketDataBundle


def _number(value: float | None) -> float:
    return float(value or 0)


def _market_regime(bundle: MarketDataBundle) -> dict[str, object]:
    benchmark = next((asset for asset in bundle.assets if asset.asset_id == "bitcoin"), None)
    liquid_assets = [
        asset
        for asset in bundle.assets
        if asset.market_cap_usd and asset.market_cap_usd >= 100_000_000
    ]
    breadth_7d = (
        sum(_number(asset.change_7d_pct) > 0 for asset in liquid_assets) / len(liquid_assets) * 100
        if liquid_assets
        else 0
    )
    return {
        "btc_change_7d_pct": benchmark.change_7d_pct if benchmark else None,
        "btc_change_30d_pct": benchmark.change_30d_pct if benchmark else None,
        "eligible_asset_breadth_7d_pct": round(breadth_7d, 1),
        "median_asset_change_7d_pct": round(
            median(_number(asset.change_7d_pct) for asset in liquid_assets), 2
        )
        if liquid_assets
        else None,
    }


def build_research_context(
    bundle: MarketDataBundle,
    *,
    asset_limit: int = 40,
    category_limit: int = 30,
    protocol_limit: int = 40,
) -> dict[str, object]:
    """Compile a bounded context; raw provider payloads deliberately stay out."""
    assets = sorted(
        bundle.assets,
        key=lambda asset: (
            _number(asset.volume_24h_usd),
            _number(asset.market_cap_usd),
        ),
        reverse=True,
    )[:asset_limit]
    categories = sorted(
        bundle.categories,
        key=lambda category: abs(_number(category.change_24h_pct)),
        reverse=True,
    )[:category_limit]
    protocols = sorted(
        bundle.protocols,
        key=lambda protocol: (
            abs(_number(protocol.change_7d_pct)),
            _number(protocol.tvl_usd),
        ),
        reverse=True,
    )[:protocol_limit]

    return {
        "observed_at": bundle.observed_at.isoformat(),
        "market_regime_inputs": _market_regime(bundle),
        "assets": [asset.model_dump(mode="json") for asset in assets],
        "categories": [category.model_dump(mode="json") for category in categories],
        "protocols": [protocol.model_dump(mode="json") for protocol in protocols],
        "coverage": {
            "asset_count": len(bundle.assets),
            "category_count": len(bundle.categories),
            "protocol_count": len(bundle.protocols),
            "context_asset_count": len(assets),
            "context_category_count": len(categories),
            "context_protocol_count": len(protocols),
        },
    }
