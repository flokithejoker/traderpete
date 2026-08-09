from pathlib import Path
from types import SimpleNamespace

from trader_pete.analysis import (
    analyze_landscape,
    build_research_context,
    load_narrative_registry,
    score_signals,
)
from trader_pete.analysis.scoring import evidence_metrics
from trader_pete.config import Settings
from trader_pete.models import (
    DailyLandscapeResearch,
    DynamicNarrativeMetrics,
    DynamicNarrativeSnapshot,
    DynamicNarrativeState,
    DynamicRadarSnapshot,
    EvidenceSource,
    MarketEvent,
    NarrativeSignals,
    RunMode,
)
from trader_pete.providers import collect_market_data
from trader_pete.research.narratives import NarrativeResearcher, _project_research_shortlist


def _signals(**overrides: float) -> NarrativeSignals:
    values = {
        "attention_acceleration": 70,
        "attention_authenticity": 65,
        "novelty": 60,
        "catalyst_strength": 65,
        "market_confirmation": 70,
        "price_acceleration": 65,
        "breadth": 60,
        "fundamental_confirmation": 55,
        "evidence_quality": 70,
        "crowding_risk": 30,
        "concentration_risk": 40,
    }
    values.update(overrides)
    return NarrativeSignals(**values)


def test_signal_score_is_deterministic_and_penalizes_crowding() -> None:
    base = score_signals(_signals())
    crowded = score_signals(_signals(crowding_risk=90))

    assert base == 58.0
    assert crowded == 50.8


def test_evidence_source_rejects_non_http_urls() -> None:
    try:
        EvidenceSource(title="Unsafe", url="javascript:alert(1)", credibility=0.5)
    except ValueError as error:
        assert "http or https" in str(error)
    else:
        raise AssertionError("Unsafe source URL was accepted")


def test_evidence_quality_counts_root_sources_not_syndicated_urls() -> None:
    sources = [
        EvidenceSource(
            title="Original announcement",
            url="https://project.example/news?id=1&utm_source=x",
            root_url="https://project.example/news?id=1",
            publisher="Project",
            source_type="official_announcement",
            is_primary=True,
            credibility=0.9,
        ),
        EvidenceSource(
            title="Syndicated copy",
            url="https://aggregator.example/copy",
            root_url="https://project.example/news?id=1&utm_campaign=copy",
            publisher="Aggregator",
            source_type="aggregator",
            credibility=0.4,
        ),
    ]

    metrics = evidence_metrics(sources)

    assert metrics["unique_roots"] == 1
    assert metrics["primary_sources"] == 0
    assert metrics["duplicate_share"] == 50
    assert metrics["attention_authenticity"] < metrics["evidence_quality"]


def test_same_domain_pages_cannot_fake_independent_publishers() -> None:
    sources = [
        EvidenceSource(
            title="First page",
            url="https://desk.example/one",
            publisher="Outlet A",
            claim="A protocol filed for an IPO.",
            source_type="original_reporting",
            credibility=0.8,
        ),
        EvidenceSource(
            title="Second page",
            url="https://desk.example/two",
            publisher="Outlet B",
            claim="The same protocol filed for an IPO.",
            source_type="original_reporting",
            credibility=0.8,
        ),
    ]

    metrics = evidence_metrics(sources)

    assert metrics["unique_roots"] == 1
    assert metrics["unique_publishers"] == 1
    assert metrics["verified"] == 0


def test_context_is_bounded_and_excludes_raw_payloads(tmp_path: Path) -> None:
    bundle = collect_market_data(Settings.from_env(tmp_path), RunMode.OFFLINE)
    context = build_research_context(bundle, asset_limit=3, category_limit=2, protocol_limit=2)

    assert len(context["assets"]) == 3
    assert len(context["categories"]) == 2
    assert len(context["protocols"]) == 2
    assert "payloads" not in context


def _landscape(settings: Settings):
    bundle = collect_market_data(settings, RunMode.OFFLINE)
    definitions = load_narrative_registry(settings.root_dir / "config" / "narratives.json")
    return bundle, analyze_landscape(bundle, definitions, max_focus=settings.max_narratives)


def test_stable_landscape_tracks_every_registry_narrative() -> None:
    settings = Settings.from_env(Path.cwd())
    bundle, landscape = _landscape(settings)
    definitions = load_narrative_registry(settings.root_dir / "config" / "narratives.json")

    assert {item.narrative_id for item in landscape.narratives} == {item.id for item in definitions}
    assert len(landscape.narratives) == 14
    assert len(landscape.projects) == sum(len(item.projects) for item in definitions)
    hyperliquid = next(item for item in landscape.projects if item.project_id == "hyperliquid")
    assert hyperliquid.metrics.fees_growth_7d_pct == 28
    assert hyperliquid.metrics.revenue_growth_7d_pct == 30
    assert hyperliquid.metrics.dex_volume_growth_7d_pct == 24
    assert bundle.protocol_activity
    assert all(item.state.value not in {"leading", "building"} for item in landscape.narratives)


def test_stale_project_market_data_is_excluded_from_ranking() -> None:
    settings = Settings.from_env(Path.cwd())
    bundle = collect_market_data(settings, RunMode.OFFLINE)
    assets = [
        item.model_copy(update={"observed_at": bundle.observed_at.replace(year=2024)})
        if item.asset_id == "solana"
        else item
        for item in bundle.assets
    ]
    stale_bundle = bundle.model_copy(update={"assets": assets})
    definitions = load_narrative_registry(settings.root_dir / "config" / "narratives.json")
    landscape = analyze_landscape(stale_bundle, definitions, max_focus=settings.max_narratives)
    solana = next(
        item
        for item in landscape.projects
        if item.narrative_id == "high_throughput_l1s" and item.project_id == "solana"
    )

    assert solana.metrics.market_data_age_hours > 48
    assert solana.metrics.price_7d_pct is None
    assert not solana.research_eligible


def test_project_research_shortlist_requires_confirmed_discovery_lanes() -> None:
    settings = Settings.from_env(Path.cwd())
    bundle, landscape = _landscape(settings)

    def candidate(narrative_id: str, asset_id: str, score: float, lanes: int):
        return DynamicNarrativeSnapshot(
            narrative_id=narrative_id,
            name=narrative_id,
            mechanism="A measured mechanism.",
            summary="Test candidate.",
            state=DynamicNarrativeState.FIRST_SEEN,
            score=score,
            confidence=80,
            persistence_days=1,
            first_seen_at=bundle.observed_at,
            last_seen_at=bundle.observed_at,
            catalyst="Test catalyst.",
            counter_thesis="Test counter-thesis.",
            constituent_ids=[asset_id],
            metrics=DynamicNarrativeMetrics(
                market_confirmation=80,
                evidence_quality=80,
                overheat_risk=20,
                measured_asset_count=1,
                protocol_metric_count=1,
                trending_asset_count=0,
                unique_evidence_roots=2,
                lane_count=lanes,
            ),
        )

    radar = DynamicRadarSnapshot(
        as_of=bundle.observed_at,
        narratives=[
            candidate("unsupported_hype", "bitcoin", 99, 0),
            candidate("confirmed_niche", "hyperliquid", 75, 2),
        ],
    )

    shortlist = _project_research_shortlist(bundle, landscape, radar)

    assert shortlist[0]["project_id"] == "hyperliquid"
    assert all(item["project_id"] != "bitcoin" for item in shortlist)


def test_offline_research_is_explicit_about_missing_live_evidence() -> None:
    settings = Settings.from_env(Path.cwd())
    bundle, landscape = _landscape(settings)
    output = NarrativeResearcher(settings).research(bundle, landscape, offline=True)

    assert output.response_id is None
    assert "Offline fixture" in output.result.data_gaps[0]
    assert not output.result.key_events
    assert "No live news" in output.result.market_summary


class FakeResponses:
    def __init__(self, draft: DailyLandscapeResearch):
        self.draft = draft
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            output_parsed=self.draft,
            id="resp_test",
            output=[
                SimpleNamespace(
                    type="web_search_call",
                    action=SimpleNamespace(
                        sources=[
                            SimpleNamespace(url="https://one.example/report"),
                            SimpleNamespace(url="https://two.example/report"),
                        ]
                    ),
                )
            ],
        )


def test_live_research_is_stateless_structured_and_web_enabled(tmp_path: Path, monkeypatch) -> None:
    settings = Settings.from_env(Path.cwd())
    bundle, landscape = _landscape(settings)
    valid_id = landscape.narratives[0].narrative_id
    draft = DailyLandscapeResearch(
        as_of=bundle.observed_at,
        market_summary="Test morning context.",
        key_events=[
            MarketEvent(
                title="Test event",
                why_it_matters="Tests stable mapping.",
                direction="mixed",
                horizon="7d",
                event_subject="Test event",
                event_type="market_event",
                event_at=bundle.observed_at,
                narrative_ids=[valid_id, "invented_narrative"],
                sources=[
                    EvidenceSource(
                        title="First report",
                        url="https://one.example/report",
                        publisher="One",
                        claim="The test market event occurred.",
                        published_at=bundle.observed_at,
                        credibility=0.7,
                    ),
                    EvidenceSource(
                        title="Second report",
                        url="https://two.example/report",
                        publisher="Two",
                        claim="The test market event occurred.",
                        published_at=bundle.observed_at,
                        credibility=0.7,
                    ),
                ],
            )
        ],
    )
    client = FakeResponses(draft)
    output = NarrativeResearcher(settings, client=client).research(bundle, landscape, offline=False)

    assert output.response_id == "resp_test"
    assert client.kwargs["store"] is False
    assert client.kwargs["reasoning"]["context"] == "current_turn"
    assert client.kwargs["text_format"] is DailyLandscapeResearch
    assert client.kwargs["tools"][0]["type"] == "web_search"
    assert client.kwargs["text"] == {"verbosity": "low"}
    assert "verbosity" not in client.kwargs
    assert output.result.key_events[0].narrative_ids == [valid_id]
