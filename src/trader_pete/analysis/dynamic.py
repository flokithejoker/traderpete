from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from statistics import median
from typing import Any

from trader_pete.analysis.economic import economic_underlying_key
from trader_pete.analysis.scoring import source_domain, source_origin
from trader_pete.models import (
    DailyDynamicNarrativeDraft,
    DynamicNarrativeMetrics,
    DynamicNarrativeSnapshot,
    DynamicNarrativeState,
    DynamicRadarSnapshot,
    EvidenceSource,
    MarketDataBundle,
    SocialCoverage,
    SocialWindowMetrics,
)


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", folded.lower()))


def _slug(value: str) -> str:
    slug = "_".join(_normalize(value).split())[:42].strip("_") or "dynamic_narrative"
    return slug


def _median(values: list[float]) -> float | None:
    return round(float(median(values)), 2) if values else None


def _supporting_roots(sources, as_of: datetime) -> tuple[set[str], set[str]]:
    supporting: set[str] = set()
    contradicting: set[str] = set()
    for source in sources:
        source_type = source.source_type.lower()
        if (
            not source.url.startswith(("https://", "http://"))
            or not source.claim.strip()
            or any(marker in source_type for marker in ("social", "aggregator", "promotional"))
            or source.published_at is None
        ):
            continue
        age_days = (as_of - source.published_at).total_seconds() / 86_400
        if age_days < -42 or age_days > 90:
            continue
        root = source_origin(source.root_url or source.url)
        if source.supports:
            supporting.add(root)
        else:
            contradicting.add(root)
    return supporting, contradicting


def _verified_event_count(candidate, as_of: datetime) -> int:
    """A narrative draft carries at most one explicit event; articles never become events."""
    if (
        not candidate.event_subject.strip()
        or not candidate.event_type.strip()
        or not candidate.event_at
    ):
        return 0
    age_days = (candidate.event_at - as_of).total_seconds() / 86_400
    if age_days < -3 or age_days > 42:
        return 0
    subject_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize(candidate.event_subject))
        if len(token) >= 3
    }
    if not subject_tokens:
        return 0
    event_type_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", _normalize(candidate.event_type))
        if len(token) >= 3
    }
    if not event_type_tokens or not (subject_tokens - event_type_tokens):
        return 0
    roots = set()
    for source in candidate.sources:
        if not source.supports or not source.claim or source.published_at is None:
            continue
        published_age = (as_of - source.published_at).total_seconds() / 86_400
        if published_age < -1 or published_age > 90:
            continue
        claim_tokens = set(re.findall(r"[a-z0-9]+", _normalize(source.claim)))
        subject_overlap = len(subject_tokens & claim_tokens)
        type_overlap = len(event_type_tokens & claim_tokens)
        if subject_overlap < min(2, len(subject_tokens)) or (
            event_type_tokens and type_overlap < 1
        ):
            continue
        roots.add(source_origin(source.root_url or source.url))
    return 1 if len(roots) >= 2 else 0


def _identity_match(
    candidate,
    history: list[dict[str, Any]],
    as_of: datetime,
) -> dict[str, Any] | None:
    candidate_aliases = {_normalize(candidate.name), *map(_normalize, candidate.aliases)}
    candidate_mechanism = _normalize(candidate.mechanism)
    candidate_members = set(candidate.constituent_ids)
    candidate_protocols = set(candidate.protocol_ids)
    candidate_parents = set(candidate.parent_narrative_ids)
    best: tuple[float, dict[str, Any]] | None = None
    latest_by_id: dict[str, dict[str, Any]] = {}
    for row in history:
        latest_by_id.setdefault(row["narrative_id"], row)
    for row in latest_by_id.values():
        last_seen = datetime.fromisoformat(
            str(row.get("last_seen_at", row["as_of"])).replace("Z", "+00:00")
        )
        if (as_of - last_seen).total_seconds() / 86_400 > 180:
            continue
        aliases = {
            _normalize(row["name"]),
            *(_normalize(value) for value in row.get("aliases", [])),
        }
        mechanism_similarity = SequenceMatcher(
            None, candidate_mechanism, _normalize(row["mechanism"])
        ).ratio()
        previous_members = set(row.get("constituent_ids", []))
        union = candidate_members | previous_members
        overlap = len(candidate_members & previous_members) / len(union) if union else 0.0
        previous_protocols = set(row.get("protocol_ids", []))
        protocol_union = candidate_protocols | previous_protocols
        protocol_overlap = (
            len(candidate_protocols & previous_protocols) / len(protocol_union)
            if protocol_union
            else 0.0
        )
        previous_parents = set(row.get("parent_narrative_ids", []))
        parent_union = candidate_parents | previous_parents
        parent_overlap = (
            len(candidate_parents & previous_parents) / len(parent_union) if parent_union else 0.0
        )
        exact_alias = bool(candidate_aliases & aliases)
        score = (
            0.45 * mechanism_similarity
            + 0.30 * overlap
            + 0.15 * protocol_overlap
            + 0.10 * parent_overlap
        )
        alias_guard = mechanism_similarity >= 0.6 or max(overlap, protocol_overlap) >= 0.3
        qualifies = (
            (exact_alias and alias_guard)
            or score >= 0.82
            or mechanism_similarity >= 0.88
            or (mechanism_similarity >= 0.68 and overlap >= 0.5)
        )
        if qualifies and (best is None or score > best[0]):
            best = (score, row)
    return best[1] if best else None


def _new_identity(candidate) -> str:
    fingerprint = "|".join(
        [_normalize(candidate.mechanism), *sorted(set(candidate.constituent_ids))]
    )
    suffix = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:6]
    return f"{_slug(candidate.name)}_{suffix}"


def _economic_confirmation(candidate, bundle: MarketDataBundle) -> tuple[float | None, int]:
    protocol_ids = set(candidate.protocol_ids)
    by_protocol: dict[str, list[float]] = {}
    for item in bundle.protocols:
        if item.protocol_id in protocol_ids and item.change_7d_pct is not None:
            by_protocol.setdefault(item.protocol_id, []).append(float(item.change_7d_pct))
    for item in bundle.protocol_activity:
        if item.protocol_id in protocol_ids and item.growth_7d_pct is not None:
            by_protocol.setdefault(item.protocol_id, []).append(float(item.growth_7d_pct))
    protocol_values = [float(median(values)) for values in by_protocol.values() if values]
    if not protocol_values:
        return None, 0
    return _clamp(50 + 1.5 * float(median(protocol_values))), len(protocol_values)


def _current_streak(as_of: date, prior_rows: list[dict[str, Any]]) -> int:
    dates = {
        datetime.fromisoformat(str(row["as_of"]).replace("Z", "+00:00")).date()
        for row in prior_rows
    }
    dates.add(as_of)
    streak = 1
    cursor = as_of
    while date.fromordinal(cursor.toordinal() - 1) in dates:
        cursor = date.fromordinal(cursor.toordinal() - 1)
        streak += 1
    return streak


def _social_for(
    narrative_id: str, metrics: list[SocialWindowMetrics]
) -> SocialWindowMetrics | None:
    return next(
        (
            item
            for item in metrics
            if item.target_type == "dynamic_narrative" and item.target_id == narrative_id
        ),
        None,
    )


def build_dynamic_radar(
    draft: DailyDynamicNarrativeDraft,
    *,
    bundle: MarketDataBundle,
    parent_ids: set[str],
    history: list[dict[str, Any]],
    social_metrics: list[SocialWindowMetrics] | None = None,
    limit: int = 12,
) -> DynamicRadarSnapshot:
    """Resolve open-ended research seeds into stable, deterministic narrative episodes."""
    assets = {item.asset_id: item for item in bundle.assets}
    bitcoin = assets.get("bitcoin")
    btc_7d = (
        float(bitcoin.change_7d_pct)
        if bitcoin is not None and bitcoin.change_7d_pct is not None
        else None
    )
    trending = {item.asset_id: item.search_rank for item in bundle.trending_assets}
    history_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in history:
        history_by_id.setdefault(row["narrative_id"], []).append(row)

    snapshots: list[DynamicNarrativeSnapshot] = []
    seen_ids: set[str] = set()
    for candidate in draft.candidates[:limit]:
        previous = _identity_match(candidate, history, draft.as_of)
        narrative_id = previous["narrative_id"] if previous else _new_identity(candidate)
        if narrative_id in seen_ids:
            continue
        seen_ids.add(narrative_id)

        valid_constituents = list(
            dict.fromkeys(value for value in candidate.constituent_ids if value in assets)
        )
        valid_constituents.sort(
            key=lambda value: (
                float(assets[value].change_7d_pct or -999) - float(btc_7d or 0),
                float(assets[value].volume_24h_usd or 0)
                / max(float(assets[value].market_cap_usd or 1), 1),
            ),
            reverse=True,
        )
        measured_tokens = [
            assets[value]
            for value in valid_constituents
            if assets[value].change_7d_pct is not None
            and assets[value].market_cap_usd
            and assets[value].market_cap_usd >= 5_000_000
            and assets[value].volume_24h_usd
            and assets[value].volume_24h_usd >= 250_000
        ]
        measured_by_underlying = {}
        for asset in measured_tokens:
            underlying = economic_underlying_key(
                asset_id=asset.asset_id, name=asset.name, symbol=asset.symbol
            )
            previous_asset = measured_by_underlying.get(underlying)
            if previous_asset is None or float(asset.volume_24h_usd or 0) > float(
                previous_asset.volume_24h_usd or 0
            ):
                measured_by_underlying[underlying] = asset
        measured = list(measured_by_underlying.values())
        returns_7d = [float(item.change_7d_pct) for item in measured]
        returns_30d = [float(item.change_30d_pct) for item in measured if item.change_30d_pct]
        median_7d = _median(returns_7d)
        median_30d = _median(returns_30d)
        btc_excess = (
            round(median_7d - btc_7d, 2) if median_7d is not None and btc_7d is not None else None
        )
        breadth = (
            round(sum(value > btc_7d for value in returns_7d) / len(returns_7d) * 100, 1)
            if returns_7d and btc_7d is not None
            else None
        )
        market_confirmation = (
            _clamp(50 + 1.8 * btc_excess + 0.25 * (breadth - 50))
            if btc_excess is not None and breadth is not None
            else 0.0
        )
        fundamental, protocol_metric_count = _economic_confirmation(candidate, bundle)
        trending_by_underlying = {}
        for value in valid_constituents:
            if value not in trending:
                continue
            asset = assets[value]
            underlying = economic_underlying_key(
                asset_id=asset.asset_id, name=asset.name, symbol=asset.symbol
            )
            trending_by_underlying[underlying] = min(
                trending[value], trending_by_underlying.get(underlying, trending[value])
            )
        trending_members = list(trending_by_underlying)
        search_attention = (
            _clamp(
                70 * len(trending_members) / max(len(set(measured_by_underlying)), 1)
                + sum(max(0, 10 - rank) for rank in trending_by_underlying.values())
            )
            if trending_members
            else 0.0
        )
        roots, contradictions = _supporting_roots(candidate.sources, draft.as_of)
        independent_events = _verified_event_count(candidate, draft.as_of)
        publishers = {
            source.publisher.strip().lower() or source_domain(source.url)
            for source in candidate.sources
        }
        evidence_quality = _clamp(22 * len(roots) + 7 * len(publishers) - 25 * len(contradictions))
        lanes: list[str] = []
        if (
            len(measured) >= 3
            and market_confirmation >= 55
            and breadth is not None
            and breadth >= 60
        ):
            lanes.append("market")
        if protocol_metric_count >= 2 and fundamental is not None and fundamental >= 55:
            lanes.append("fundamental")
        if len(trending_members) >= 2:
            lanes.append("search")
        if independent_events >= 1 and len(roots) >= 2:
            lanes.append("event")

        prior_rows = history_by_id.get(narrative_id, [])
        persistence_days = _current_streak(draft.as_of.date(), prior_rows)
        recent_rows = [
            row
            for row in prior_rows
            if (
                draft.as_of.date()
                - datetime.fromisoformat(str(row["as_of"]).replace("Z", "+00:00")).date()
            ).days
            < persistence_days
        ]
        first_seen_at = min(row["as_of"] for row in recent_rows) if recent_rows else draft.as_of
        if isinstance(first_seen_at, str):
            first_seen_at = datetime.fromisoformat(first_seen_at.replace("Z", "+00:00"))

        social = _social_for(narrative_id, social_metrics or [])
        social_sentiment = social.sentiment_score if social else None
        coordination_risk = social.coordination_risk if social else None
        overheat = _clamp(
            max(0.0, float(median_7d or 0) - 20) * 1.8 + max(0.0, float(median_30d or 0) - 60) * 0.7
        )

        components = [
            (evidence_quality, 0.20),
        ]
        if btc_excess is not None and breadth is not None:
            components.extend([(market_confirmation, 0.30), (breadth, 0.15)])
        if trending_members:
            components.append((search_attention, 0.10))
        if fundamental is not None:
            components.append((fundamental, 0.20))
        weight = sum(item[1] for item in components)
        score = _clamp(sum(value * item_weight for value, item_weight in components) / weight)
        score = _clamp(score - 0.15 * overheat)
        confidence = _clamp(
            len(measured) * 12
            + len(lanes) * 12
            + min(len(roots), 2) * 12
            + min(protocol_metric_count, 3) * 7
        )
        if not roots:
            confidence = min(confidence, 55.0)

        rejection_reasons: list[str] = []
        if len(measured) < 3:
            rejection_reasons.append("Fewer than three independent measured economic underlyings")
        if len(measured_tokens) > len(measured):
            rejection_reasons.append(
                f"{len(measured_tokens)} liquid tokens collapse to "
                f"{len(measured)} independent economic underlyings"
            )
        if len(lanes) < 2:
            rejection_reasons.append("Fewer than two independent discovery lanes")
        if not roots:
            rejection_reasons.append("No recent, supportive non-promotional evidence root")
        if contradictions:
            rejection_reasons.append("Contradictory evidence requires review")
        if not ({"market", "fundamental"} & set(lanes)):
            rejection_reasons.append("No market or fundamental confirmation lane")

        prior_scores = [float(row["score"]) for row in prior_rows[:2]]
        if not measured and not protocol_metric_count and not roots:
            state = DynamicNarrativeState.REJECTED
        elif overheat >= 75 and score >= 55:
            state = DynamicNarrativeState.CROWDED
        elif (
            persistence_days >= 3
            and btc_excess is not None
            and btc_excess < 0
            and breadth is not None
            and breadth < 40
        ):
            state = DynamicNarrativeState.FADING
        elif (
            persistence_days >= 2
            and score >= 70
            and confidence >= 65
            and len(measured) >= 3
            and breadth is not None
            and breadth >= 60
            and len(lanes) >= 2
            and roots
            and not contradictions
            and (not prior_scores or score >= prior_scores[0])
        ):
            state = DynamicNarrativeState.ACCELERATING
        elif (
            persistence_days >= 2
            and score >= 60
            and confidence >= 60
            and len(measured) >= 3
            and breadth is not None
            and breadth >= 60
            and len(lanes) >= 2
            and roots
            and not contradictions
        ):
            state = DynamicNarrativeState.EMERGING
        elif persistence_days >= 2:
            state = DynamicNarrativeState.OBSERVED
        else:
            state = DynamicNarrativeState.FIRST_SEEN

        aliases = list(dict.fromkeys([candidate.name, *candidate.aliases]))
        if previous:
            aliases = list(dict.fromkeys([*previous.get("aliases", []), *aliases]))
        snapshots.append(
            DynamicNarrativeSnapshot(
                narrative_id=narrative_id,
                name=previous["name"] if previous else candidate.name,
                mechanism=previous["mechanism"] if previous else candidate.mechanism,
                summary=candidate.summary,
                parent_narrative_ids=[
                    value
                    for value in dict.fromkeys(candidate.parent_narrative_ids)
                    if value in parent_ids
                ],
                aliases=aliases,
                state=state,
                score=score,
                confidence=confidence,
                persistence_days=persistence_days,
                first_seen_at=first_seen_at,
                last_seen_at=draft.as_of,
                catalyst=candidate.catalyst,
                counter_thesis=candidate.counter_thesis,
                constituent_ids=valid_constituents,
                protocol_ids=list(dict.fromkeys(candidate.protocol_ids)),
                discovery_lanes=lanes,
                rejection_reasons=rejection_reasons,
                metrics=DynamicNarrativeMetrics(
                    median_7d_pct=median_7d,
                    median_30d_pct=median_30d,
                    btc_excess_7d_pct=btc_excess,
                    breadth_vs_btc_pct=breadth,
                    market_confirmation=market_confirmation,
                    fundamental_confirmation=fundamental,
                    search_attention=search_attention,
                    social_sentiment=social_sentiment,
                    coordination_risk=coordination_risk,
                    evidence_quality=evidence_quality,
                    overheat_risk=overheat,
                    measured_asset_count=len(measured),
                    measured_underlying_count=len(measured),
                    protocol_metric_count=protocol_metric_count,
                    trending_asset_count=len(trending_members),
                    unique_evidence_roots=len(roots),
                    independent_event_count=independent_events,
                    lane_count=len(lanes),
                ),
                sources=candidate.sources,
            )
        )

    latest_by_id: dict[str, dict[str, Any]] = {}
    for row in history:
        latest_by_id.setdefault(row["narrative_id"], row)
    for narrative_id, row in latest_by_id.items():
        if narrative_id in seen_ids or len(snapshots) >= 20:
            continue
        last_seen = datetime.fromisoformat(str(row["last_seen_at"]).replace("Z", "+00:00"))
        missing_days = (draft.as_of.date() - last_seen.date()).days
        if missing_days < 0 or missing_days > 7:
            continue
        if missing_days == 0:
            state = DynamicNarrativeState(row["state"])
            decay = 0
        elif missing_days <= 2:
            state = DynamicNarrativeState.FADING
            decay = 8 * missing_days
        else:
            state = DynamicNarrativeState.DORMANT
            decay = 12 * missing_days
        snapshots.append(
            DynamicNarrativeSnapshot(
                narrative_id=narrative_id,
                name=row["name"],
                mechanism=row["mechanism"],
                summary=row["summary"],
                parent_narrative_ids=row.get("parent_narrative_ids", []),
                aliases=row.get("aliases", []),
                state=state,
                score=_clamp(float(row["score"]) - decay),
                confidence=_clamp(float(row["confidence"]) - decay),
                persistence_days=max(1, int(row["persistence_days"])),
                first_seen_at=datetime.fromisoformat(
                    str(row["first_seen_at"]).replace("Z", "+00:00")
                ),
                last_seen_at=last_seen,
                catalyst=row["catalyst"],
                counter_thesis=row["counter_thesis"],
                constituent_ids=row.get("constituent_ids", []),
                protocol_ids=row.get("protocol_ids", []),
                discovery_lanes=row.get("discovery_lanes", []),
                rejection_reasons=[
                    *row.get("rejection_reasons", []),
                    "Not redetected in today's bounded scout",
                ],
                metrics=DynamicNarrativeMetrics.model_validate(row["metrics"]),
                sources=[
                    EvidenceSource.model_validate(source) for source in row.get("sources", [])
                ],
            )
        )

    snapshots.sort(key=lambda item: (item.score, item.confidence), reverse=True)
    gaps = list(draft.data_gaps)
    if not snapshots:
        gaps.append("No dynamic narrative seed survived entity resolution for this run.")
    gaps.append(
        "Dynamic narratives require two distinct daily observations before promotion; "
        "same-day reruns do not add persistence."
    )
    if not any(
        item.coverage in {SocialCoverage.MEASURED, SocialCoverage.PARTIAL}
        for item in (social_metrics or [])
    ):
        gaps.append("Social stance is unmeasured; search attention is shown separately.")
    return DynamicRadarSnapshot(
        as_of=draft.as_of,
        narratives=snapshots,
        data_gaps=list(dict.fromkeys(gaps)),
    )
