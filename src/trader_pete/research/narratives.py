from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, Protocol

from openai import OpenAI

from trader_pete.analysis import build_research_context, finalize_research
from trader_pete.config import Settings
from trader_pete.models import (
    DailyNarrativeResearch,
    DailyResearchDraft,
    MarketDataBundle,
    NarrativeResearchDraft,
    NarrativeSignals,
)

PROMPT_VERSION = "narrative-discovery-v2"

SYSTEM_INSTRUCTIONS = """You are Trader Pete's candidate narrative research component.
Discover a broad radar of crypto themes that could matter over the next 28 days. Do not simply
repeat the largest categories. Search independently through three lanes: (1) newly verified events
and scheduled catalysts, (2) related assets beginning to accelerate together, and (3) accelerating
protocol usage. A one- or two-project idea is a theme seed, not a proven narrative.

Treat attention as reflexive evidence, never as proof of future returns. CoinGecko trending is
search popularity, not organic sentiment. Do not claim to detect AI-written news or bots. Instead,
trace each claim to its earliest root source, collapse syndication to that root, identify the
publisher, and look for independent corroboration and contradictions. A social post or aggregator
may discover a lead but cannot verify one. Prefer protocol documentation, governance proposals,
regulatory filings, repository releases, on-chain records, verified company announcements, and
reputable original reporting.

Research concrete events from the last seven days plus dated catalysts in the next 28 days. Older
sources may provide context but are not new evidence. Each source must state the atomic claim it
supports, publisher, whether it is primary, and the root URL from which repetitions derive. Do not
invent dates, metrics, sources, projects, or token relationships.

Only attention_acceleration, novelty, catalyst_strength, and crowding_risk are research judgments.
Express each judgment on a 0-100 scale, never 0-1.
Set attention_authenticity, market_confirmation, price_acceleration, breadth,
fundamental_confirmation, evidence_quality, and concentration_risk to 0; deterministic code will
replace them from the supplied snapshot and source provenance. Confidence describes the research
packet's completeness, not return conviction. Use only supplied asset IDs and protocol IDs. Return
no price targets, purchases, or trade recommendations.

Return the requested structured object only."""


class ResearchConfigurationError(RuntimeError):
    pass


class ResponsesClient(Protocol):
    def parse(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class ResearchOutput:
    result: DailyNarrativeResearch
    prompt: str
    prompt_version: str
    response_id: str | None


def _prompt(context: dict[str, object], candidate_narratives: int) -> str:
    return (
        f"As of {context['observed_at']}, discover and assess no more than "
        f"{candidate_narratives} candidate narratives or theme seeds. Keep no more than four "
        "deduplicated root sources per candidate. The input below is a bounded, quality-screened "
        "market snapshot; it is not a list of conclusions.\n\n"
        + json.dumps(context, sort_keys=True, separators=(",", ":"))
    )


class NarrativeResearcher:
    def __init__(self, settings: Settings, client: ResponsesClient | None = None):
        self.settings = settings
        self._client = client

    def research(self, bundle: MarketDataBundle, *, offline: bool) -> ResearchOutput:
        context = build_research_context(bundle)
        prompt = _prompt(context, self.settings.candidate_narratives)
        if offline:
            draft = self._offline_draft(bundle)
            response_id = None
        else:
            draft, response_id = self._live_draft(prompt)

        result = finalize_research(
            draft,
            bundle=bundle,
            candidate_limit=self.settings.candidate_narratives,
            shortlist_size=self.settings.max_narratives,
        )
        return ResearchOutput(
            result=result,
            prompt=prompt,
            prompt_version=PROMPT_VERSION,
            response_id=response_id,
        )

    def _live_draft(self, prompt: str) -> tuple[DailyResearchDraft, str | None]:
        if not self.settings.openai_api_key and self._client is None:
            raise ResearchConfigurationError("Live research requires OPENAI_API_KEY.")
        client = self._client or OpenAI(api_key=self.settings.openai_api_key).responses
        response = client.parse(
            model=self.settings.model,
            reasoning={
                "effort": self.settings.reasoning_effort,
                "context": "current_turn",
            },
            tools=[{"type": "web_search", "search_context_size": "medium"}],
            include=["web_search_call.action.sources"],
            input=prompt,
            instructions=SYSTEM_INSTRUCTIONS,
            text_format=DailyResearchDraft,
            store=False,
            max_tool_calls=10,
            max_output_tokens=10_000,
            text={"verbosity": "low"},
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI returned no structured narrative research result.")
        return response.output_parsed, getattr(response, "id", None)

    def _offline_draft(self, bundle: MarketDataBundle) -> DailyResearchDraft:
        registry_path = Path(self.settings.root_dir, "config", "narratives.json")
        definitions = json.loads(registry_path.read_text(encoding="utf-8"))
        assets = {item.asset_id: item for item in bundle.assets}
        categories = {item.category_id: item for item in bundle.categories}
        benchmark = assets.get("bitcoin")
        btc_7d = float(benchmark.change_7d_pct or 0) if benchmark else 0
        btc_30d = float(benchmark.change_30d_pct or 0) if benchmark else 0
        drafts: list[NarrativeResearchDraft] = []

        for definition in definitions:
            members = [assets[item] for item in definition["asset_ids"] if item in assets]
            category_members = [
                categories[item] for item in definition["category_ids"] if item in categories
            ]
            rel_30d = [float(item.change_30d_pct or 0) - btc_30d for item in members]
            category_24h = [float(item.change_24h_pct or 0) for item in category_members]
            category_strength = _median(category_24h)
            signals = NarrativeSignals(
                attention_acceleration=50,
                novelty=45,
                catalyst_strength=40,
                market_confirmation=0,
                breadth=0,
                fundamental_confirmation=0,
                crowding_risk=_clamp(45 + max(0, _median(rel_30d)) + category_strength),
            )
            drafts.append(
                NarrativeResearchDraft(
                    narrative_id=definition["id"],
                    name=definition["name"],
                    summary="Offline quantitative seed; live event evidence was not researched.",
                    confidence_score=35,
                    signals=signals,
                    thesis="Relative market data warrants placing this theme on the radar.",
                    counter_thesis=(
                        "Fixture data cannot establish attention novelty, catalysts, or current "
                        "investability."
                    ),
                    constituent_ids=definition["asset_ids"],
                    protocol_ids=definition["protocol_ids"],
                    sources=[],
                )
            )

        regime = "risk-on" if btc_7d > 3 else "risk-off" if btc_7d < -3 else "mixed"
        return DailyResearchDraft(
            as_of=bundle.observed_at,
            market_regime=regime,
            narratives=drafts,
            data_gaps=[
                "Offline fixture: no web, attention, catalyst, or current-event evidence was used.",
                "Narrative scores are development fixtures, not current research.",
            ],
        )


def _median(values: list[float]) -> float:
    return float(median(values)) if values else 0


def _clamp(value: float) -> float:
    return round(max(0, min(100, value)), 1)
