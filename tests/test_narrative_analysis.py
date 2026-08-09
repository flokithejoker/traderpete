from pathlib import Path
from types import SimpleNamespace

from trader_pete.analysis import build_research_context, score_signals
from trader_pete.config import Settings
from trader_pete.models import (
    DailyResearchDraft,
    EvidenceSource,
    NarrativeResearchDraft,
    NarrativeSignals,
    RunMode,
)
from trader_pete.providers import collect_market_data
from trader_pete.research.narratives import NarrativeResearcher


def _signals(**overrides: float) -> NarrativeSignals:
    values = {
        "attention_acceleration": 70,
        "novelty": 60,
        "catalyst_strength": 65,
        "market_confirmation": 70,
        "breadth": 60,
        "fundamental_confirmation": 55,
        "crowding_risk": 30,
    }
    values.update(overrides)
    return NarrativeSignals(**values)


def test_signal_score_is_deterministic_and_penalizes_crowding() -> None:
    base = score_signals(_signals())
    crowded = score_signals(_signals(crowding_risk=90))

    assert base == 64.8
    assert crowded == 58.8


def test_evidence_source_rejects_non_http_urls() -> None:
    try:
        EvidenceSource(title="Unsafe", url="javascript:alert(1)", credibility=0.5)
    except ValueError as error:
        assert "http or https" in str(error)
    else:
        raise AssertionError("Unsafe source URL was accepted")


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

    assert len(output.result.narratives) == settings.max_narratives
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
