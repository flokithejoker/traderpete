from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from trader_pete.analysis.dynamic import build_dynamic_radar
from trader_pete.analysis.landscape import load_narrative_registry
from trader_pete.config import Settings
from trader_pete.models import (
    DailyDynamicNarrativeDraft,
    DynamicNarrativeDraft,
    DynamicNarrativeState,
    EvidenceSource,
    RunMode,
    SocialCoverage,
    SocialWindowMetrics,
)
from trader_pete.providers import collect_market_data
from trader_pete.providers.social import SocialTarget, collect_social_metrics


def _draft(as_of: datetime) -> DailyDynamicNarrativeDraft:
    sources = [
        EvidenceSource(
            title="Protocol release",
            url="https://protocol.example/releases/1",
            root_url="https://protocol.example/releases/1",
            publisher="Protocol",
            claim="Three protocols shipped related fee-producing products.",
            source_type="official_announcement",
            published_at=as_of,
            credibility=0.8,
        ),
        EvidenceSource(
            title="Independent activity data",
            url="https://data.example/perps",
            root_url="https://data.example/perps",
            publisher="Data Lab",
            claim="Fees and volume accelerated across the cluster.",
            source_type="data",
            published_at=as_of,
            credibility=0.8,
        ),
    ]
    return DailyDynamicNarrativeDraft(
        as_of=as_of,
        candidates=[
            DynamicNarrativeDraft(
                name="Perpetual DEX cash flow",
                mechanism="On-chain perpetual trading creates fees for protocol token holders",
                summary="A narrow derivatives revenue cluster.",
                parent_narrative_ids=["onchain_trading"],
                constituent_ids=["hyperliquid", "pendle", "ethena"],
                protocol_ids=["hyperliquid", "pendle", "ethena"],
                discovery_lanes=["event", "market", "fundamental"],
                catalyst="Related product releases during the next four weeks.",
                counter_thesis="Recent returns may already price in activity growth.",
                aliases=["perp DEX revenue"],
                sources=sources,
            )
        ],
    )


def test_dynamic_identity_is_stable_and_same_day_does_not_add_persistence() -> None:
    settings = Settings.from_env(Path.cwd())
    bundle = collect_market_data(settings, RunMode.OFFLINE)
    parent_ids = {
        item.id for item in load_narrative_registry(settings.root_dir / "config/narratives.json")
    }
    first = build_dynamic_radar(
        _draft(bundle.observed_at),
        bundle=bundle,
        parent_ids=parent_ids,
        history=[],
    ).narratives[0]
    history = [
        {
            "narrative_id": first.narrative_id,
            "name": first.name,
            "mechanism": first.mechanism,
            "aliases": first.aliases,
            "constituent_ids": first.constituent_ids,
            "score": first.score,
            "as_of": first.last_seen_at.isoformat(),
        }
    ]
    same_day = build_dynamic_radar(
        _draft(bundle.observed_at),
        bundle=bundle,
        parent_ids=parent_ids,
        history=history,
    ).narratives[0]
    next_day = build_dynamic_radar(
        _draft(bundle.observed_at + timedelta(days=1)),
        bundle=bundle,
        parent_ids=parent_ids,
        history=history,
    ).narratives[0]

    assert first.state is DynamicNarrativeState.FIRST_SEEN
    assert same_day.narrative_id == first.narrative_id
    assert same_day.persistence_days == 1
    assert next_day.persistence_days == 2
    assert next_day.state in {
        DynamicNarrativeState.EMERGING,
        DynamicNarrativeState.ACCELERATING,
    }


def test_social_collection_is_explicitly_missing_without_opt_in(tmp_path: Path) -> None:
    base = Settings.from_env(tmp_path)
    settings = replace(base, x_enabled=False, x_bearer_token=None)
    metrics = collect_social_metrics(
        settings,
        [SocialTarget(target_type="project", target_id="hype", label="Hyperliquid")],
    )

    assert metrics[0].coverage is SocialCoverage.UNAVAILABLE
    assert metrics[0].sentiment_score is None
    assert "disabled" in metrics[0].limitation


def test_asserted_lanes_and_contradictions_cannot_confirm_a_narrative() -> None:
    settings = Settings.from_env(Path.cwd())
    bundle = collect_market_data(settings, RunMode.OFFLINE)
    parent_ids = {
        item.id for item in load_narrative_registry(settings.root_dir / "config/narratives.json")
    }
    candidate = DynamicNarrativeDraft(
        name="Unsupported theme",
        mechanism="One token allegedly creates a new market",
        summary="Adversarial model output.",
        constituent_ids=["hyperliquid"],
        discovery_lanes=["event", "market", "fundamental", "search", "social"],
        catalyst="Unverified",
        counter_thesis="The claim is contradicted.",
        sources=[
            EvidenceSource(
                title="Contradiction",
                url="https://reporter.example/contradiction",
                publisher="Reporter",
                claim="The claimed launch did not occur.",
                published_at=bundle.observed_at,
                supports=False,
                credibility=0.9,
            )
        ],
    )
    result = build_dynamic_radar(
        DailyDynamicNarrativeDraft(as_of=bundle.observed_at, candidates=[candidate]),
        bundle=bundle,
        parent_ids=parent_ids,
        history=[],
    ).narratives[0]

    assert result.metrics.lane_count == 0
    assert result.metrics.unique_evidence_roots == 0
    assert result.state is not DynamicNarrativeState.EMERGING
    assert any("Contradictory" in value for value in result.rejection_reasons)


def test_social_diagnostics_do_not_change_research_priority() -> None:
    settings = Settings.from_env(Path.cwd())
    bundle = collect_market_data(settings, RunMode.OFFLINE)
    parent_ids = {
        item.id for item in load_narrative_registry(settings.root_dir / "config/narratives.json")
    }
    without_social = build_dynamic_radar(
        _draft(bundle.observed_at),
        bundle=bundle,
        parent_ids=parent_ids,
        history=[],
    ).narratives[0]
    social = SocialWindowMetrics(
        provider="x",
        target_type="dynamic_narrative",
        target_id=without_social.narrative_id,
        coverage=SocialCoverage.PARTIAL,
        raw_posts=20,
        unique_authors=20,
        sentiment_score=100,
        coordination_risk=100,
    )
    with_social = build_dynamic_radar(
        _draft(bundle.observed_at),
        bundle=bundle,
        parent_ids=parent_ids,
        history=[],
        social_metrics=[social],
    ).narratives[0]

    assert with_social.score == without_social.score
    assert with_social.metrics.overheat_risk == without_social.metrics.overheat_risk
    assert with_social.metrics.social_sentiment == 100
