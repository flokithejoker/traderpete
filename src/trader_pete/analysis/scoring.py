from __future__ import annotations

from trader_pete.models import (
    DailyNarrativeResearch,
    DailyResearchDraft,
    NarrativeAssessment,
    NarrativeLifecycle,
    NarrativeSignals,
)


def _clamp(value: float) -> float:
    return round(max(0, min(100, value)), 1)


def score_signals(signals: NarrativeSignals) -> float:
    """Transparent v1 score. Weights are hypotheses to evaluate, not learned truth."""
    positive = (
        0.18 * signals.attention_acceleration
        + 0.13 * signals.novelty
        + 0.17 * signals.catalyst_strength
        + 0.17 * signals.market_confirmation
        + 0.13 * signals.breadth
        + 0.12 * signals.fundamental_confirmation
    )
    crowding_resilience = 0.10 * (100 - signals.crowding_risk)
    return _clamp(positive + crowding_resilience)


def classify_lifecycle(signals: NarrativeSignals) -> NarrativeLifecycle:
    if signals.market_confirmation < 20 and signals.catalyst_strength < 25:
        return NarrativeLifecycle.BROKEN
    if signals.attention_acceleration >= 75 and signals.crowding_risk >= 70:
        return NarrativeLifecycle.CROWDED
    if (
        signals.attention_acceleration >= 60
        and signals.market_confirmation >= 55
        and signals.breadth >= 50
    ):
        return NarrativeLifecycle.ACCELERATING
    if signals.novelty >= 60 and signals.attention_acceleration >= 50:
        return NarrativeLifecycle.EMERGING
    if signals.attention_acceleration < 40 and signals.market_confirmation < 40:
        return NarrativeLifecycle.FADING
    return NarrativeLifecycle.DORMANT


def finalize_research(
    draft: DailyResearchDraft,
    *,
    eligible_asset_ids: set[str],
    max_narratives: int,
) -> DailyNarrativeResearch:
    assessments: list[NarrativeAssessment] = []
    for candidate in draft.narratives:
        constituents = list(dict.fromkeys(candidate.constituent_ids))
        valid_constituents = [item for item in constituents if item in eligible_asset_ids]
        assessment = NarrativeAssessment(
            narrative_id=candidate.narrative_id,
            name=candidate.name,
            summary=candidate.summary,
            lifecycle=classify_lifecycle(candidate.signals),
            opportunity_score=score_signals(candidate.signals),
            confidence_score=candidate.confidence_score,
            signals=candidate.signals,
            thesis=candidate.thesis,
            counter_thesis=candidate.counter_thesis,
            constituent_ids=valid_constituents,
            sources=candidate.sources,
        )
        assessments.append(assessment)

    ranked = sorted(
        assessments,
        key=lambda item: (item.opportunity_score, item.confidence_score),
        reverse=True,
    )[:max_narratives]
    data_gaps = list(draft.data_gaps)
    if any(len(item.constituent_ids) == 0 for item in ranked):
        data_gaps.append(
            "At least one narrative has no eligible constituent in the market universe."
        )
    return DailyNarrativeResearch(
        as_of=draft.as_of,
        market_regime=draft.market_regime,
        narratives=ranked,
        data_gaps=list(dict.fromkeys(data_gaps)),
    )
