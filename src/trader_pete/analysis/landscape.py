from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import median

from trader_pete.models import (
    ActivityMetricType,
    LandscapeSnapshot,
    MarketDataBundle,
    NarrativeDefinition,
    NarrativeMetrics,
    NarrativeState,
    ProjectMetrics,
    ProjectSnapshot,
    StableNarrativeSnapshot,
)


def load_narrative_registry(path: Path) -> list[NarrativeDefinition]:
    definitions = [
        NarrativeDefinition.model_validate(item)
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]
    narrative_ids = [item.id for item in definitions]
    if len(narrative_ids) != len(set(narrative_ids)):
        raise ValueError("Narrative registry contains duplicate narrative IDs.")
    for definition in definitions:
        project_ids = [item.id for item in definition.projects]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError(f"Narrative {definition.id} contains duplicate project IDs.")
    return definitions


def registry_asset_ids(definitions: list[NarrativeDefinition]) -> list[str]:
    return sorted({project.asset_id for item in definitions for project in item.projects})


def analyze_landscape(
    bundle: MarketDataBundle,
    definitions: list[NarrativeDefinition],
    *,
    max_focus: int,
) -> LandscapeSnapshot:
    assets = {item.asset_id: item for item in bundle.assets}
    categories = {item.category_id: item for item in bundle.categories}
    protocols = {_key(item.protocol_id): item for item in bundle.protocols}
    protocol_names = {_key(item.name): item for item in bundle.protocols}
    activity = {
        (_key(item.protocol_id), item.metric_type): item for item in bundle.protocol_activity
    }
    activity_names = {
        (_key(item.name), item.metric_type): item for item in bundle.protocol_activity
    }
    trending = {item.asset_id for item in bundle.trending_assets}
    bitcoin = assets.get("bitcoin")
    btc_7d = _number(bitcoin.change_7d_pct) if bitcoin else 0
    btc_30d = _number(bitcoin.change_30d_pct) if bitcoin else 0

    projects: list[ProjectSnapshot] = []
    narrative_rows: list[tuple[NarrativeDefinition, NarrativeMetrics, float, float]] = []
    for definition in definitions:
        project_rows: list[ProjectSnapshot] = []
        for project in definition.projects:
            asset = assets.get(project.asset_id)
            protocol_aliases = [_key(item) for item in project.protocol_ids]
            tvl_rows = [protocols[item] for item in protocol_aliases if item in protocols]
            if not tvl_rows and _key(project.name) in protocol_names:
                tvl_rows = [protocol_names[_key(project.name)]]
            tvl = max(tvl_rows, key=lambda item: float(item.tvl_usd or 0), default=None)

            activities = {}
            for metric_type in ActivityMetricType:
                matches = [
                    activity[(item, metric_type)]
                    for item in protocol_aliases
                    if (item, metric_type) in activity
                ]
                name_key = (_key(project.name), metric_type)
                if not matches and name_key in activity_names:
                    matches = [activity_names[name_key]]
                activities[metric_type] = max(
                    matches,
                    key=lambda item: float(item.total_7d_usd or 0),
                    default=None,
                )

            metrics = _project_metrics(
                asset=asset,
                tvl=tvl,
                activities=activities,
                as_of=bundle.observed_at,
                btc_7d=btc_7d,
                btc_30d=btc_30d,
                is_trending=project.asset_id in trending,
            )
            score, research_eligible, notes = _project_score(metrics)
            project_rows.append(
                ProjectSnapshot(
                    narrative_id=definition.id,
                    project_id=project.id,
                    name=project.name,
                    asset_id=project.asset_id,
                    rank=1,
                    score=score,
                    research_eligible=research_eligible,
                    metrics=metrics,
                    selection_notes=notes,
                )
            )

        project_rows.sort(key=lambda item: (item.research_eligible, item.score), reverse=True)
        project_rows = [
            item.model_copy(update={"rank": rank}) for rank, item in enumerate(project_rows, 1)
        ]
        projects.extend(project_rows)
        narrative_metrics = _narrative_metrics(
            definition=definition,
            projects=project_rows,
            categories=categories,
            btc_7d=btc_7d,
        )
        score = _narrative_score(project_rows, narrative_metrics)
        confidence = _narrative_confidence(narrative_metrics)
        narrative_rows.append((definition, narrative_metrics, score, confidence))

    narrative_rows.sort(key=lambda item: (item[2], item[3]), reverse=True)
    narratives: list[StableNarrativeSnapshot] = []
    focus_count = 0
    for rank, (definition, metrics, score, confidence) in enumerate(narrative_rows, 1):
        state = _narrative_state(score, metrics)
        focus = (
            focus_count < max_focus
            and score >= 50
            and confidence >= 50
            and metrics.measured_project_count >= 3
            and state in {NarrativeState.LEADING, NarrativeState.BUILDING, NarrativeState.ACTIVE}
        )
        focus_count += int(focus)
        narratives.append(
            StableNarrativeSnapshot(
                narrative_id=definition.id,
                name=definition.name,
                description=definition.description,
                kpi_profile=definition.kpi_profile,
                rank=rank,
                state=state,
                is_focus=focus,
                score=score,
                confidence=confidence,
                metrics=metrics,
            )
        )

    eligible_assets = [
        item
        for item in bundle.assets
        if item.market_cap_usd
        and item.market_cap_usd >= 100_000_000
        and item.change_7d_pct is not None
    ]
    breadth = (
        sum(float(item.change_7d_pct or 0) > 0 for item in eligible_assets) / len(eligible_assets)
        if eligible_assets
        else 0
    )
    regime = (
        "risk-on"
        if btc_7d > 3 and breadth >= 0.55
        else "risk-off"
        if btc_7d < -3 and breadth < 0.45
        else "mixed"
    )
    gaps = [
        (
            "CoinGecko trending measures search popularity, not sentiment or organic "
            "community quality."
        ),
        "TVL can move with token prices and is not treated as net capital inflow.",
        (
            "Active-user history is unavailable on the free DefiLlama surface; user-growth "
            "KPIs remain unmeasured."
        ),
        (
            "X bot coordination and organic sentiment are unknown without an auditable "
            "raw social-data feed."
        ),
        (
            "Narrative and project scores are transparent research heuristics, not a trained "
            "return forecast."
        ),
    ]
    if not bundle.protocol_activity:
        gaps.insert(
            0, "Protocol fees, revenue, and DEX-volume activity were unavailable for this run."
        )
    if not bundle.trending_assets:
        gaps.insert(0, "Search-attention data were unavailable for this run.")
    stale_projects = sum(
        item.metrics.market_data_age_hours is not None and item.metrics.market_data_age_hours > 48
        for item in projects
    )
    if stale_projects:
        gaps.insert(
            0,
            f"{stale_projects} registry project(s) had market snapshots older than 48 hours "
            "and were excluded from ranking inputs.",
        )
    return LandscapeSnapshot(
        as_of=bundle.observed_at,
        market_regime=regime,
        narratives=narratives,
        projects=projects,
        data_gaps=gaps,
    )


def _project_metrics(
    *, asset, tvl, activities, as_of, btc_7d: float, btc_30d: float, is_trending: bool
) -> ProjectMetrics:
    market_age = max(0, (as_of - asset.observed_at).total_seconds() / 3600) if asset else None
    current_asset = asset if market_age is not None and market_age <= 48 else None
    price_7d = (
        float(current_asset.change_7d_pct)
        if current_asset and current_asset.change_7d_pct is not None
        else None
    )
    price_30d = (
        float(current_asset.change_30d_pct)
        if current_asset and current_asset.change_30d_pct is not None
        else None
    )
    excess_7d = price_7d - btc_7d if price_7d is not None else None
    acceleration = (
        excess_7d - (price_30d - btc_30d) / 4
        if excess_7d is not None and price_30d is not None
        else None
    )
    market_cap = (
        float(current_asset.market_cap_usd)
        if current_asset and current_asset.market_cap_usd
        else None
    )
    volume = (
        float(current_asset.volume_24h_usd)
        if current_asset and current_asset.volume_24h_usd
        else None
    )
    turnover = volume / market_cap if market_cap and volume else None
    tvl_growth = _sane_growth(tvl.change_7d_pct) if tvl else None
    fees = activities[ActivityMetricType.FEES]
    revenue = activities[ActivityMetricType.REVENUE]
    dex_volume = activities[ActivityMetricType.DEX_VOLUME]
    growth_values = [
        (
            _reliable_growth(tvl_growth, float(tvl.tvl_usd or 0) if tvl else None, 1e6, 1e8),
            0.15,
        ),
        (_reliable_growth(_activity_growth(fees), _activity_total(fees), 1e4, 1e6), 0.30),
        (
            _reliable_growth(_activity_growth(revenue), _activity_total(revenue), 1e4, 1e6),
            0.30,
        ),
        (
            _reliable_growth(_activity_growth(dex_volume), _activity_total(dex_volume), 1e6, 1e8),
            0.25,
        ),
    ]
    available_growth = [(value, weight) for value, weight in growth_values if value is not None]
    fundamental = (
        _clamp(
            sum(value * weight for value, weight in available_growth)
            / sum(weight for _, weight in available_growth)
        )
        if available_growth
        else None
    )
    liquidity = _liquidity_score(market_cap, volume)
    overheat = _overheat_risk(price_7d, price_30d, turnover)
    coverage = sum(
        value is not None
        for value in (
            price_7d,
            price_30d,
            market_cap,
            volume,
            tvl_growth,
            _activity_growth(fees),
            _activity_growth(revenue),
            _activity_growth(dex_volume),
        )
    )
    return ProjectMetrics(
        market_data_age_hours=_round(market_age),
        price_7d_pct=_round(price_7d),
        price_30d_pct=_round(price_30d),
        btc_excess_7d_pct=_round(excess_7d),
        price_acceleration=_round(acceleration),
        market_cap_usd=market_cap,
        volume_24h_usd=volume,
        turnover_24h=_round(turnover, 4),
        tvl_usd=float(tvl.tvl_usd) if tvl and tvl.tvl_usd is not None else None,
        tvl_growth_7d_pct=_round(tvl_growth),
        fees_7d_usd=_activity_total(fees),
        fees_growth_7d_pct=_round(_activity_growth(fees)),
        revenue_7d_usd=_activity_total(revenue),
        revenue_growth_7d_pct=_round(_activity_growth(revenue)),
        dex_volume_7d_usd=_activity_total(dex_volume),
        dex_volume_growth_7d_pct=_round(_activity_growth(dex_volume)),
        fundamental_growth_score=fundamental,
        liquidity_score=liquidity,
        overheat_risk=overheat,
        is_trending=is_trending,
        coverage=coverage,
    )


def _project_score(metrics: ProjectMetrics) -> tuple[float, bool, list[str]]:
    market = None
    if metrics.btc_excess_7d_pct is not None:
        market = _clamp(
            50 + 2.2 * metrics.btc_excess_7d_pct + 1.2 * (metrics.price_acceleration or 0)
        )
    components = [
        (market, 0.38),
        (metrics.fundamental_growth_score, 0.34),
        (metrics.liquidity_score, 0.18),
        (90.0 if metrics.is_trending else 35.0, 0.10),
    ]
    available = [(value, weight) for value, weight in components if value is not None]
    raw = sum(value * weight for value, weight in available) / sum(
        weight for _, weight in available
    )
    score = _clamp(raw - 0.22 * metrics.overheat_risk)
    notes = []
    if metrics.btc_excess_7d_pct is not None and metrics.btc_excess_7d_pct > 0:
        notes.append("outperforming Bitcoin over 7 days")
    if metrics.fundamental_growth_score is not None and metrics.fundamental_growth_score >= 55:
        notes.append("economic or TVL activity is expanding")
    if metrics.is_trending:
        notes.append("appears in CoinGecko search trends")
    if metrics.overheat_risk >= 65:
        notes.append("momentum or turnover is already crowded")
    if metrics.market_data_age_hours is not None and metrics.market_data_age_hours > 48:
        notes.append("market snapshot is older than 48 hours")
    eligible = bool(
        metrics.market_cap_usd
        and metrics.market_cap_usd >= 5_000_000
        and metrics.volume_24h_usd
        and metrics.volume_24h_usd >= 250_000
        and metrics.price_7d_pct is not None
    )
    if not eligible:
        notes.append("fails minimum market-data or liquidity coverage")
    return score, eligible, notes


def _narrative_metrics(*, definition, projects, categories, btc_7d: float) -> NarrativeMetrics:
    measured = [item for item in projects if item.metrics.price_7d_pct is not None]
    eligible = [item for item in projects if item.research_eligible]
    prices_7d = [item.metrics.price_7d_pct for item in measured]
    prices_30d = [
        item.metrics.price_30d_pct for item in measured if item.metrics.price_30d_pct is not None
    ]
    excess = [
        item.metrics.btc_excess_7d_pct
        for item in measured
        if item.metrics.btc_excess_7d_pct is not None
    ]
    fundamentals = [
        item.metrics.fundamental_growth_score
        for item in projects
        if item.metrics.fundamental_growth_score is not None
    ]
    category_changes = [
        float(categories[item].change_24h_pct)
        for item in definition.category_ids
        if item in categories and categories[item].change_24h_pct is not None
    ]
    trending_count = sum(item.metrics.is_trending for item in projects)
    attention = _clamp(30 + trending_count * 16 + max(0, _median(category_changes) or 0) * 2)
    return NarrativeMetrics(
        median_7d_pct=_round(_median(prices_7d)),
        median_30d_pct=_round(_median(prices_30d)),
        btc_excess_7d_pct=_round(_median(excess)),
        breadth_vs_btc_pct=(
            round(sum(value > 0 for value in excess) / len(excess) * 100, 1) if excess else None
        ),
        fundamental_growth_score=_round(_median(fundamentals)),
        category_change_24h_pct=_round(_median(category_changes)),
        attention_score=attention,
        median_overheat_risk=_round(
            _median([item.metrics.overheat_risk for item in eligible]) or 0
        ),
        project_count=len(projects),
        measured_project_count=len(measured),
        economic_metric_count=len(fundamentals),
        trending_project_count=trending_count,
    )


def _narrative_score(projects: list[ProjectSnapshot], metrics: NarrativeMetrics) -> float:
    eligible_scores = [item.score for item in projects if item.research_eligible]
    project_signal = _median(sorted(eligible_scores, reverse=True)[:3])
    breadth = metrics.breadth_vs_btc_pct
    components = [
        (project_signal, 0.42),
        (breadth, 0.22),
        (metrics.fundamental_growth_score, 0.22),
        (metrics.attention_score, 0.14),
    ]
    available = [(value, weight) for value, weight in components if value is not None]
    if not available:
        return 0
    raw = sum(value * weight for value, weight in available) / sum(
        weight for _, weight in available
    )
    return _clamp(raw - 0.10 * metrics.median_overheat_risk)


def _narrative_confidence(metrics: NarrativeMetrics) -> float:
    market_coverage = min(1, metrics.measured_project_count / max(metrics.project_count, 1))
    economic_coverage = min(1, metrics.economic_metric_count / max(metrics.project_count, 1))
    breadth_bonus = 1 if metrics.measured_project_count >= 3 else 0
    return _clamp(25 + 35 * market_coverage + 25 * economic_coverage + 15 * breadth_bonus)


def _narrative_state(score: float, metrics: NarrativeMetrics) -> NarrativeState:
    if (
        score >= 65
        and metrics.measured_project_count >= 3
        and (metrics.breadth_vs_btc_pct or 0) >= 60
    ):
        return NarrativeState.LEADING
    if (
        score >= 55
        and metrics.measured_project_count >= 3
        and (metrics.breadth_vs_btc_pct or 0) >= 40
    ):
        return NarrativeState.BUILDING
    if score >= 43 and metrics.measured_project_count >= 1:
        return NarrativeState.ACTIVE
    if (metrics.median_7d_pct or 0) < 0 or score >= 30:
        return NarrativeState.COOLING
    return NarrativeState.DORMANT


def _activity_total(item) -> float | None:
    return float(item.total_7d_usd) if item and item.total_7d_usd is not None else None


def _activity_growth(item) -> float | None:
    return _sane_growth(item.growth_7d_pct) if item else None


def _sane_growth(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)) or abs(float(value)) > 1000:
        return None
    return float(value)


def _growth_score(value: float) -> float:
    return _clamp(50 + 1.7 * value)


def _reliable_growth(
    growth: float | None,
    total: float | None,
    floor: float,
    full_weight: float,
) -> float | None:
    if growth is None or total is None or total < floor:
        return None
    reliability = min(1, max(0, math.log10(total / floor) / math.log10(full_weight / floor)))
    raw = _growth_score(growth)
    return _clamp(50 + (raw - 50) * reliability)


def _liquidity_score(market_cap: float | None, volume: float | None) -> float | None:
    if not market_cap or not volume:
        return None
    volume_score = _clamp((math.log10(max(volume, 1)) - math.log10(250_000)) / 3 * 100)
    turnover = volume / market_cap
    turnover_score = _clamp(35 + min(turnover, 0.5) * 130)
    return _clamp(0.7 * volume_score + 0.3 * turnover_score)


def _overheat_risk(
    price_7d: float | None, price_30d: float | None, turnover: float | None
) -> float:
    risk = 15.0
    if price_7d is not None:
        risk += max(0, price_7d - 15) * 1.2
    if price_30d is not None:
        risk += max(0, price_30d - 50) * 0.35
    if turnover is not None:
        risk += max(0, turnover - 0.35) * 45
    return _clamp(risk)


def _median(values: list[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return float(median(clean)) if clean else None


def _number(value: float | None) -> float:
    return float(value or 0)


def _round(value: float | None, digits: int = 1) -> float | None:
    return round(value, digits) if value is not None else None


def _clamp(value: float) -> float:
    return round(max(0, min(100, value)), 1)


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())
