from pathlib import Path
from types import SimpleNamespace

from trader_pete.analysis import build_research_context, score_signals
from trader_pete.analysis.scoring import evidence_metrics
from trader_pete.config import Settings
from trader_pete.models import (
    DailyResearchDraft,
    EvidenceSource,
    NarrativeResearchDraft,
    NarrativeSignals,
    RunMode,
    TrendingAsset,
)
from trader_pete.providers import collect_market_data
from trader_pete.research.narratives import NarrativeResearcher


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
    assert metrics["primary_sources"] == 1
    assert metrics["duplicate_share"] == 50
    assert metrics["attention_authenticity"] < metrics["evidence_quality"]


def test_context_is_bounded_and_excludes_raw_payloads(tmp_path: Path) -> None:
    bundle = collect_market_data(Settings.from_env(tmp_path), RunMode.OFFLINE)
    context = build_research_context(bundle, asset_limit=3, category_limit=2, protocol_limit=2)

    assert len(context["assets"]) == 3
    assert len(context["categories"]) == 2
    assert len(context["protocols"]) == 2
    assert "payloads" not in context


def test_offline_research_is_ranked_and_explicitly_limited(tmp_path: Path) -> None:
    settings = Settings.from_env(Path.cwd())
    bundle = collect_market_data(settings, RunMode.OFFLINE)
    output = NarrativeResearcher(settings).research(bundle, offline=True)

    assert len(output.result.narratives) <= settings.candidate_narratives
    assert sum(item.is_shortlisted for item in output.result.narratives) == 0
    assert output.response_id is None
    assert "Offline fixture" in output.result.data_gaps[0]
    assert output.result.narratives == sorted(
        output.result.narratives,
        key=lambda item: (item.opportunity_score, item.confidence_score),
        reverse=True,
    )


class FakeResponses:
    def __init__(self, draft: DailyResearchDraft):
        self.draft = draft
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.draft, id="resp_test")


def test_live_research_is_stateless_structured_and_web_enabled(tmp_path: Path, monkeypatch) -> None:
    settings = Settings.from_env(Path.cwd())
    bundle = collect_market_data(settings, RunMode.OFFLINE)
    draft = DailyResearchDraft(
        as_of=bundle.observed_at,
        market_regime="mixed",
        narratives=[
            NarrativeResearchDraft(
                narrative_id="test_narrative",
                name="Test Narrative",
                summary="Test",
                confidence_score=70,
                signals=_signals(),
                thesis="Test thesis",
                counter_thesis="Test counter-thesis",
                constituent_ids=["bitcoin", "unknown-asset"],
                sources=[],
            )
        ],
    )
    client = FakeResponses(draft)
    output = NarrativeResearcher(settings, client=client).research(bundle, offline=False)

    assert output.response_id == "resp_test"
    assert client.kwargs["store"] is False
    assert client.kwargs["reasoning"]["context"] == "current_turn"
    assert client.kwargs["text_format"] is DailyResearchDraft
    assert client.kwargs["tools"][0]["type"] == "web_search"
    assert client.kwargs["text"] == {"verbosity": "low"}
    assert "verbosity" not in client.kwargs
    assert output.result.narratives[0].constituent_ids == ["bitcoin"]


def test_live_research_normalizes_zero_to_one_judgment_scale() -> None:
    settings = Settings.from_env(Path.cwd())
    fixture = collect_market_data(settings, RunMode.OFFLINE)
    bundle = fixture.model_copy(
        update={
            "trending_assets": [
                TrendingAsset(
                    asset_id="bitcoin",
                    symbol="BTC",
                    name="Bitcoin",
                    observed_at=fixture.observed_at,
                    search_rank=1,
                    market_cap_rank=1,
                )
            ]
        }
    )
    draft = DailyResearchDraft(
        as_of=bundle.observed_at,
        market_regime="mixed",
        narratives=[
            NarrativeResearchDraft(
                narrative_id="scaled_candidate",
                name="Scaled Candidate",
                summary="Test",
                confidence_score=0.8,
                signals=NarrativeSignals(
                    attention_acceleration=0.72,
                    novelty=0.65,
                    catalyst_strength=0.7,
                    market_confirmation=0,
                    breadth=0,
                    fundamental_confirmation=0,
                    crowding_risk=0.2,
                ),
                thesis="Test thesis",
                counter_thesis="Test counter-thesis",
                constituent_ids=["bitcoin", "ethereum", "solana"],
                sources=[
                    EvidenceSource(
                        title="Primary",
                        url="https://project.example/update",
                        published_at=bundle.observed_at,
                        source_type="official_announcement",
                        publisher="Project",
                        root_url="https://project.example/update",
                        is_primary=True,
                        credibility=0.8,
                    )
                ],
            )
        ],
    )

    output = NarrativeResearcher(settings, client=FakeResponses(draft)).research(
        bundle, offline=False
    )
    signals = output.result.narratives[0].signals

    assert signals.attention_acceleration == 72
    assert signals.novelty == 65
    assert signals.catalyst_strength == 70
    assert signals.crowding_risk == 20
