from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from statistics import median
from typing import Any

from trader_pete.models import CategoryMarket, MarketAsset, MarketDataBundle, ProtocolMetric


def _number(value: float | None) -> float:
    return float(value or 0)


def _market_regime(bundle: MarketDataBundle) -> dict[str, object]:
    benchmark = next((asset for asset in bundle.assets if asset.asset_id == "bitcoin"), None)
    liquid_assets = [
        asset
        for asset in bundle.assets
        if asset.market_cap_usd
        and asset.market_cap_usd >= 100_000_000
        and asset.volume_24h_usd
        and asset.volume_24h_usd >= 1_000_000
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
        "median_asset_change_7d_pct": (
            round(median(_number(asset.change_7d_pct) for asset in liquid_assets), 2)
            if liquid_assets
            else None
        ),
        "eligible_asset_count": len(liquid_assets),
    }


def _robust_outliers(values: list[float], *, threshold: float = 8) -> set[float]:
    if len(values) < 5:
        return set()
    center = median(values)
    mad = median(abs(value - center) for value in values)
    if mad == 0:
        return {value for value in values if abs(value - center) > 25}
    scale = 1.4826 * mad
    return {value for value in values if abs(value - center) / scale > threshold}


def _merge_ranked[T](
    ranked_groups: list[tuple[str, list[T]]],
    *,
    identity: Callable[[T], str],
    limit: int,
) -> tuple[list[T], dict[str, list[str]]]:
    selected: dict[str, T] = {}
    reasons: dict[str, list[str]] = defaultdict(list)
    for reason, items in ranked_groups:
        for item in items:
            item_id = identity(item)
            reasons[item_id].append(reason)
            selected.setdefault(item_id, item)
    ordered = list(selected.values())[:limit]
    return ordered, {identity(item): reasons[identity(item)] for item in ordered}


def _asset_context(bundle: MarketDataBundle, limit: int) -> list[dict[str, Any]]:
    benchmark = next((asset for asset in bundle.assets if asset.asset_id == "bitcoin"), None)
    btc_7d = _number(benchmark.change_7d_pct) if benchmark else 0
    btc_30d = _number(benchmark.change_30d_pct) if benchmark else 0
    eligible = [
        asset
        for asset in bundle.assets
        if asset.market_cap_usd
        and asset.market_cap_usd >= 5_000_000
        and asset.volume_24h_usd
        and asset.volume_24h_usd >= 250_000
        and asset.change_7d_pct is not None
    ]

    def acceleration(asset: MarketAsset) -> float:
        relative_7d = _number(asset.change_7d_pct) - btc_7d
        relative_30d = _number(asset.change_30d_pct) - btc_30d
        return relative_7d - relative_30d / 4

    def turnover(asset: MarketAsset) -> float:
        return _number(asset.volume_24h_usd) / max(_number(asset.market_cap_usd), 1)

    trending_ids = {item.asset_id for item in bundle.trending_assets}
    selected, reasons = _merge_ranked(
        [
            (
                "search_trending",
                sorted(
                    [asset for asset in eligible if asset.asset_id in trending_ids],
                    key=lambda asset: next(
                        item.search_rank
                        for item in bundle.trending_assets
                        if item.asset_id == asset.asset_id
                    ),
                ),
            ),
            (
                "price_acceleration",
                sorted(eligible, key=acceleration, reverse=True)[:35],
            ),
            (
                "turnover_expansion_proxy",
                sorted(eligible, key=turnover, reverse=True)[:25],
            ),
            (
                "relative_momentum",
                sorted(
                    eligible,
                    key=lambda asset: _number(asset.change_7d_pct) - btc_7d,
                    reverse=True,
                )[:25],
            ),
            (
                "liquid_benchmark",
                sorted(eligible, key=lambda asset: _number(asset.market_cap_usd), reverse=True)[
                    :25
                ],
            ),
        ],
        identity=lambda asset: asset.asset_id,
        limit=limit,
    )

    rows: list[dict[str, Any]] = []
    for asset in selected:
        row = asset.model_dump(mode="json")
        row["relative_7d_vs_btc_pct"] = round(_number(asset.change_7d_pct) - btc_7d, 2)
        row["relative_30d_vs_btc_pct"] = round(_number(asset.change_30d_pct) - btc_30d, 2)
        row["weekly_price_acceleration_pct"] = round(acceleration(asset), 2)
        row["turnover_24h_pct"] = round(turnover(asset) * 100, 2)
        row["discovery_reasons"] = reasons[asset.asset_id]
        rows.append(row)
    return rows


def _category_context(
    categories: list[CategoryMarket], limit: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    changes = [item.change_24h_pct for item in categories if item.change_24h_pct is not None]
    outliers = _robust_outliers([float(value) for value in changes])
    usable = [
        item
        for item in categories
        if item.change_24h_pct is not None
        and item.change_24h_pct not in outliers
        and item.market_cap_usd
        and item.market_cap_usd >= 10_000_000
        and item.volume_24h_usd
        and item.volume_24h_usd >= 1_000_000
    ]
    ranked = sorted(usable, key=lambda item: _number(item.change_24h_pct), reverse=True)[:limit]
    return [item.model_dump(mode="json") for item in ranked], {
        "raw": len(categories),
        "usable": len(usable),
        "missing_change": sum(item.change_24h_pct is None for item in categories),
        "outliers_excluded": sum(item.change_24h_pct in outliers for item in categories),
        "illiquid_or_tiny_excluded": sum(
            not item.market_cap_usd
            or item.market_cap_usd < 10_000_000
            or not item.volume_24h_usd
            or item.volume_24h_usd < 1_000_000
            for item in categories
        ),
    }


def _protocol_context(
    protocols: list[ProtocolMetric], limit: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    changes = [item.change_7d_pct for item in protocols if item.change_7d_pct is not None]
    outliers = _robust_outliers([float(value) for value in changes])
    usable = [
        item
        for item in protocols
        if item.change_7d_pct is not None
        and item.change_7d_pct not in outliers
        and abs(item.change_7d_pct) <= 500
        and item.tvl_usd
        and item.tvl_usd >= 1_000_000
    ]
    ranked = sorted(
        usable,
        key=lambda item: (_number(item.change_7d_pct), _number(item.tvl_usd)),
        reverse=True,
    )[:limit]
    return [item.model_dump(mode="json") for item in ranked], {
        "raw": len(protocols),
        "usable": len(usable),
        "missing_7d_change": sum(item.change_7d_pct is None for item in protocols),
        "outliers_excluded": sum(
            item.change_7d_pct in outliers
            or (item.change_7d_pct is not None and abs(item.change_7d_pct) > 500)
            for item in protocols
        ),
    }


def build_research_context(
    bundle: MarketDataBundle,
    *,
    asset_limit: int = 100,
    category_limit: int = 35,
    protocol_limit: int = 50,
) -> dict[str, object]:
    """Compile diversified, quality-screened discovery inputs without raw payloads."""
    assets = _asset_context(bundle, asset_limit)
    categories, category_quality = _category_context(bundle.categories, category_limit)
    protocols, protocol_quality = _protocol_context(bundle.protocols, protocol_limit)
    trending = [item.model_dump(mode="json") for item in bundle.trending_assets]

    return {
        "observed_at": bundle.observed_at.isoformat(),
        "market_regime_inputs": _market_regime(bundle),
        "assets": assets,
        "categories": categories,
        "protocols": protocols,
        "trending_searches": trending,
        "coverage": {
            "asset_count": len(bundle.assets),
            "category_count": len(bundle.categories),
            "protocol_count": len(bundle.protocols),
            "trending_count": len(bundle.trending_assets),
            "context_asset_count": len(assets),
            "context_category_count": len(categories),
            "context_protocol_count": len(protocols),
        },
        "data_quality": {
            "categories": category_quality,
            "protocols": protocol_quality,
            "warnings": [
                "CoinGecko trending measures search popularity, not organic sentiment or returns.",
                "Category changes are discovery hints and may reflect membership changes.",
                "Protocol TVL changes are not net USD inflows and include asset-price effects.",
                "Attention history is unavailable until multiple daily snapshots accumulate.",
            ],
        },
        "feature_provenance": {
            "price_and_volume": "CoinGecko point-in-time market snapshot",
            "trending_searches": "CoinGecko search popularity over the last 24 hours",
            "protocol_growth": "DefiLlama TVL change; not flow-adjusted",
            "news_and_events": "OpenAI web search; source roots must be reported and verified",
        },
    }
