from __future__ import annotations

from datetime import datetime
from statistics import median
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from trader_pete.models import (
    DailyNarrativeResearch,
    DailyResearchDraft,
    EvidenceSource,
    MarketDataBundle,
    NarrativeAssessment,
    NarrativeLifecycle,
    NarrativeSignals,
)

TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}
AUTHORITATIVE_DOMAINS = {
    "github.com",
    "sec.gov",
    "cftc.gov",
    "europa.eu",
    "gov.uk",
    "snapshot.org",
}


def _clamp(value: float) -> float:
    return round(max(0, min(100, value)), 1)


def _normalize_score(value: float) -> float:
    """Accept model judgments expressed as either 0-1 or 0-100."""
    return _clamp(value * 100 if 0 <= value <= 1 else value)


def _median(values: list[float]) -> float:
    return float(median(values)) if values else 0


def canonical_source_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    port = f":{parts.port}" if parts.port else ""
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
        )
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host + port, path, query, ""))


def source_domain(url: str) -> str:
    return (urlsplit(url).hostname or "unknown").lower().removeprefix("www.")


def source_origin(url: str) -> str:
    """Conservatively group pages/subdomains owned by one registered domain."""
    host = source_domain(url)
    labels = [value for value in host.split(".") if value]
    if len(labels) <= 2:
        return host
    compound_suffixes = {"co.uk", "org.uk", "gov.uk", "com.au", "com.br", "co.jp"}
    suffix = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if suffix in compound_suffixes else suffix


def is_primary_source(source: EvidenceSource) -> bool:
    return is_authoritative_url(source.url)


def is_authoritative_url(url: str) -> bool:
    domain = source_domain(url)
    if domain.endswith(".example"):
        return False
    return domain in AUTHORITATIVE_DOMAINS or any(
        domain.endswith(f".{value}") for value in AUTHORITATIVE_DOMAINS
    )


def _source_prior(source: EvidenceSource) -> float:
    source_type = source.source_type.lower()
    if is_primary_source(source):
        return 85
    if any(marker in source_type for marker in ("original_reporting", "reputable_news")):
        return 70
    if "data" in source_type or "research" in source_type:
        return 65
    if "aggregator" in source_type or "social" in source_type:
        return 25
    return 45


def evidence_metrics(
    sources: list[EvidenceSource], *, as_of: datetime | None = None
) -> dict[str, float | int]:
    if not sources:
        return {
            "evidence_quality": 0.0,
            "attention_authenticity": 0.0,
            "unique_roots": 0,
            "unique_publishers": 0,
            "primary_sources": 0,
            "contradictions": 0,
            "duplicate_share": 0.0,
            "fresh_sources_7d": 0,
            "recent_sources_30d": 0,
            "verified": 0,
        }
    root_sources = [
        source
        for source in sources
        if not any(
            marker in source.source_type.lower()
            for marker in ("aggregator", "social", "promotional")
        )
    ]
    roots = {
        source_origin(source.root_url or source.url)
        for source in root_sources
        if source.root_url or source.url
    }
    publishers = roots
    primary_count = sum(is_primary_source(source) for source in sources)
    contradictions = sum(not source.supports for source in sources)
    recency_scores: list[float] = []
    fresh_sources = 0
    recent_sources = 0
    for source in sources:
        if source.published_at is None or as_of is None:
            recency_scores.append(20 if source.published_at is None else 50)
            continue
        age_days = (as_of - source.published_at).total_seconds() / 86_400
        if age_days < 0:
            recency_scores.append(0)
        elif age_days <= 7:
            fresh_sources += 1
            recent_sources += 1
            recency_scores.append(100)
        elif age_days <= 30:
            recent_sources += 1
            recency_scores.append(65)
        elif age_days <= 90:
            recency_scores.append(30)
        else:
            recency_scores.append(10)
    duplicate_share = 1 - len(roots) / len(sources)
    source_prior = sum(_source_prior(source) for source in sources) / len(sources)
    independent_score = min(100, len(roots) * 35 + len(publishers) * 10)
    provenance_score = 100 if primary_count else 55 if len(roots) >= 2 else 20
    verified = len(roots) >= 2 and len(publishers) >= 2 and contradictions == 0
    contradiction_penalty = min(25, contradictions * 8)
    quality = _clamp(
        0.35 * provenance_score
        + 0.25 * independent_score
        + 0.20 * source_prior
        + 0.20 * _median(recency_scores)
        - contradiction_penalty
    )
    weak_source_count = sum(
        any(marker in source.source_type.lower() for marker in ("social", "aggregator"))
        for source in sources
    )
    authenticity = _clamp(
        quality * (1 - 0.55 * weak_source_count / len(sources)) - duplicate_share * 30
    )
    return {
        "evidence_quality": quality,
        "attention_authenticity": authenticity,
        "unique_roots": len(roots),
        "unique_publishers": len(publishers),
        "primary_sources": primary_count,
        "contradictions": contradictions,
        "duplicate_share": round(duplicate_share * 100, 1),
        "fresh_sources_7d": fresh_sources,
        "recent_sources_30d": recent_sources,
        "verified": int(verified),
    }


def score_signals(signals: NarrativeSignals, *, coverage: dict[str, int] | None = None) -> float:
    """Versioned v2 score with visible evidence, crowding, and concentration penalties."""
    coverage = coverage or {"market_assets": 1, "protocols": 1, "sources": 1}
    components = [
        (0.12, signals.attention_acceleration, True),
        (0.08, signals.attention_authenticity, coverage.get("sources", 0) > 0),
        (0.11, signals.novelty, True),
        (0.14, signals.catalyst_strength, True),
        (0.14, signals.market_confirmation, coverage.get("market_assets", 0) > 0),
        (0.11, signals.price_acceleration, coverage.get("market_assets", 0) > 0),
        (0.10, signals.breadth, coverage.get("market_assets", 0) > 0),
        (0.10, signals.fundamental_confirmation, coverage.get("protocols", 0) > 0),
        (0.10, signals.evidence_quality, coverage.get("sources", 0) > 0),
    ]
    available = [(weight, value) for weight, value, present in components if present]
    weight_total = sum(weight for weight, _ in available) or 1
    base = sum(weight * value for weight, value in available) / weight_total
    penalties = 0.12 * signals.crowding_risk + 0.08 * signals.concentration_risk
    return _clamp(base - penalties)


def classify_lifecycle(
    signals: NarrativeSignals,
    *,
    opportunity_score: float,
    confidence_score: float,
    member_count: int,
    contradiction_count: int,
) -> NarrativeLifecycle:
    if contradiction_count >= 2 and signals.evidence_quality < 35:
        return NarrativeLifecycle.BROKEN
    if signals.attention_acceleration >= 70 and signals.crowding_risk >= 70:
        return NarrativeLifecycle.CROWDED
    if (
        opportunity_score >= 70
        and signals.price_acceleration >= 65
        and signals.breadth >= 60
        and signals.crowding_risk < 70
        and member_count >= 3
    ):
        return NarrativeLifecycle.ACCELERATING
    if (
        opportunity_score >= 60
        and confidence_score >= 60
        and member_count >= 3
        and (signals.market_confirmation >= 55 or signals.fundamental_confirmation >= 55)
    ):
        return NarrativeLifecycle.EMERGING
    if opportunity_score >= 45 and confidence_score >= 40:
        return NarrativeLifecycle.NASCENT
    if signals.attention_acceleration < 35 and signals.market_confirmation < 35:
        return NarrativeLifecycle.FADING
    return NarrativeLifecycle.SEED


def _quantitative_signals(
    candidate_signals: NarrativeSignals,
    *,
    constituent_ids: list[str],
    protocol_ids: list[str],
    bundle: MarketDataBundle,
    evidence: dict[str, float | int],
) -> tuple[NarrativeSignals, dict[str, int]]:
    assets = {asset.asset_id: asset for asset in bundle.assets}
    protocols = {protocol.protocol_id: protocol for protocol in bundle.protocols}
    benchmark = assets.get("bitcoin")
    btc_7d = float(benchmark.change_7d_pct or 0) if benchmark else 0
    btc_30d = float(benchmark.change_30d_pct or 0) if benchmark else 0
    members = [assets[item] for item in constituent_ids if item in assets]
    protocol_members = [
        protocols[item]
        for item in protocol_ids
        if item in protocols
        and protocols[item].change_7d_pct is not None
        and abs(float(protocols[item].change_7d_pct or 0)) <= 500
    ]
    relative_7d = [float(item.change_7d_pct or 0) - btc_7d for item in members]
    relative_30d = [float(item.change_30d_pct or 0) - btc_30d for item in members]
    acceleration = [
        weekly - monthly / 4 for weekly, monthly in zip(relative_7d, relative_30d, strict=True)
    ]
    market_confirmation = _clamp(50 + 2 * _median(relative_7d) + 0.4 * _median(relative_30d))
    price_acceleration = _clamp(50 + 3 * _median(acceleration))
    breadth = (
        round(sum(value > 0 for value in relative_7d) / len(relative_7d) * 100, 1)
        if relative_7d
        else 0
    )
    positive = [max(0, value) for value in relative_7d]
    if len(members) < 2:
        concentration = 100
    elif sum(positive) > 0:
        concentration = _clamp(max(positive) / sum(positive) * 100)
    else:
        concentration = _clamp(100 / len(members))
    protocol_7d = [float(item.change_7d_pct or 0) for item in protocol_members]
    fundamental = _clamp(50 + 1.5 * _median(protocol_7d)) if protocol_7d else 0
    signals = candidate_signals.model_copy(
        update={
            "attention_authenticity": float(evidence["attention_authenticity"]),
            "market_confirmation": market_confirmation if members else 0,
            "price_acceleration": price_acceleration if members else 0,
            "breadth": breadth,
            "fundamental_confirmation": fundamental,
            "evidence_quality": float(evidence["evidence_quality"]),
            "concentration_risk": concentration,
        }
    )
    coverage = {
        "market_assets": len(members),
        "protocols": len(protocol_members),
        "sources": int(evidence["unique_roots"]),
        "publishers": int(evidence["unique_publishers"]),
        "primary_sources": int(evidence["primary_sources"]),
        "contradictions": int(evidence["contradictions"]),
        "fresh_sources_7d": int(evidence["fresh_sources_7d"]),
        "recent_sources_30d": int(evidence["recent_sources_30d"]),
        "verified": int(evidence["verified"]),
    }
    return signals, coverage


def finalize_research(
    draft: DailyResearchDraft,
    *,
    bundle: MarketDataBundle,
    candidate_limit: int,
    shortlist_size: int,
) -> DailyNarrativeResearch:
    assessments: list[NarrativeAssessment] = []
    eligible_asset_ids = {asset.asset_id for asset in bundle.assets}
    eligible_protocol_ids = {protocol.protocol_id for protocol in bundle.protocols}
    seen_ids: set[str] = set()
    trending_ids = {item.asset_id for item in bundle.trending_assets}
    for candidate in draft.narratives:
        if candidate.narrative_id in seen_ids:
            continue
        seen_ids.add(candidate.narrative_id)
        constituents = list(dict.fromkeys(candidate.constituent_ids))
        valid_constituents = [item for item in constituents if item in eligible_asset_ids]
        protocols = list(dict.fromkeys(candidate.protocol_ids))
        valid_protocols = [item for item in protocols if item in eligible_protocol_ids]
        evidence = evidence_metrics(candidate.sources, as_of=draft.as_of)
        normalized_signals = candidate.signals.model_copy(
            update={
                "attention_acceleration": _normalize_score(
                    candidate.signals.attention_acceleration
                ),
                "novelty": _normalize_score(candidate.signals.novelty),
                "catalyst_strength": _normalize_score(candidate.signals.catalyst_strength),
                "crowding_risk": _normalize_score(candidate.signals.crowding_risk),
            }
        )
        if not trending_ids.intersection(valid_constituents):
            normalized_signals = normalized_signals.model_copy(
                update={
                    "attention_acceleration": min(normalized_signals.attention_acceleration, 55)
                }
            )
        if not evidence["recent_sources_30d"]:
            normalized_signals = normalized_signals.model_copy(
                update={"catalyst_strength": min(normalized_signals.catalyst_strength, 35)}
            )
        if not evidence["verified"]:
            normalized_signals = normalized_signals.model_copy(
                update={"catalyst_strength": min(normalized_signals.catalyst_strength, 25)}
            )
        signals, coverage = _quantitative_signals(
            normalized_signals,
            constituent_ids=valid_constituents,
            protocol_ids=valid_protocols,
            bundle=bundle,
            evidence=evidence,
        )
        opportunity = score_signals(signals, coverage=coverage)
        coverage_score = min(100, len(valid_constituents) * 25 + int(evidence["unique_roots"]) * 15)
        confidence = _clamp(
            0.35 * _normalize_score(candidate.confidence_score)
            + 0.45 * float(evidence["evidence_quality"])
            + 0.20 * coverage_score
        )
        if not evidence["verified"]:
            confidence = min(confidence, 55.0)
        assessments.append(
            NarrativeAssessment(
                narrative_id=candidate.narrative_id,
                name=candidate.name,
                summary=candidate.summary,
                lifecycle=classify_lifecycle(
                    signals,
                    opportunity_score=opportunity,
                    confidence_score=confidence,
                    member_count=len(valid_constituents),
                    contradiction_count=int(evidence["contradictions"]),
                ),
                opportunity_score=opportunity,
                confidence_score=confidence,
                signals=signals,
                thesis=candidate.thesis,
                counter_thesis=candidate.counter_thesis,
                constituent_ids=valid_constituents,
                protocol_ids=valid_protocols,
                metric_coverage=coverage,
                sources=candidate.sources,
            )
        )

    ranked = sorted(
        assessments,
        key=lambda item: (item.opportunity_score, item.confidence_score),
        reverse=True,
    )[:candidate_limit]
    shortlisted = 0
    gated: list[NarrativeAssessment] = []
    excluded_lifecycles = {
        NarrativeLifecycle.CROWDED,
        NarrativeLifecycle.FADING,
        NarrativeLifecycle.BROKEN,
    }
    for item in ranked:
        qualifies = (
            shortlisted < shortlist_size
            and item.metric_coverage.get("verified", 0) == 1
            and item.confidence_score >= 60
            and item.opportunity_score >= 45
            and item.lifecycle not in excluded_lifecycles
        )
        gated.append(item.model_copy(update={"is_shortlisted": qualifies}))
        shortlisted += int(qualifies)
    ranked = gated
    data_gaps = list(draft.data_gaps)
    if shortlisted < shortlist_size:
        data_gaps.append(
            f"Only {shortlisted} candidate(s) passed shortlist gates; the maximum is "
            f"{shortlist_size}, not a quota."
        )
    if any(item.metric_coverage["market_assets"] < 3 for item in ranked):
        data_gaps.append(
            "Candidates with fewer than three measured constituents are theme seeds, "
            "not narratives."
        )
    if not bundle.trending_assets:
        data_gaps.append("No measured search-trending snapshot was available for this run.")
    data_gaps.append(
        "Attention acceleration remains research-assessed until a 28-day deduplicated "
        "claim history exists."
    )
    data_gaps.append(
        "TVL growth is not treated as net inflow because price effects are not yet decomposed."
    )
    return DailyNarrativeResearch(
        as_of=draft.as_of,
        market_regime=draft.market_regime,
        narratives=ranked,
        data_gaps=list(dict.fromkeys(data_gaps)),
    )
