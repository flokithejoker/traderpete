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

PROMPT_VERSION = "narrative-discovery-v1"

SYSTEM_INSTRUCTIONS = """You are Trader Pete's narrative research component.
Identify at most the requested number of crypto narratives that could matter over the next
28 days.

Treat attention as reflexive evidence, never as proof of future returns. Prefer new acceleration
over absolute popularity. Confirm narratives using multiple independent dimensions: a credible
catalyst, market breadth and relative strength, protocol adoption, and investable constituents.
Penalize already-crowded, repetitive, promotional, or circular evidence.

Research the last seven days and upcoming 28 days with web search. Prefer primary sources,
official protocol material, filings, governance proposals, and reputable data providers. Use news
only for genuinely new events. Give both supporting and contradicting evidence. Do not invent
dates, metrics, sources, projects, or token relationships.

Signal values are 0-100 assessments. Market confirmation, breadth, and fundamentals must respect
the supplied point-in-time data. Attention acceleration, novelty, catalysts, and crowding require
web evidence. Confidence measures source quality, independence, recency, and completeness—not
conviction. Only use supplied asset IDs for constituent_ids. Do not make trade recommendations or
price targets.

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


def _prompt(context: dict[str, object], max_narratives: int) -> str:
    return (
        f"As of {context['observed_at']}, discover and assess no more than "
        f"{max_narratives} narratives. The input below is a bounded normalized market snapshot; "
        "it is not a list of conclusions.\n\n"
        + json.dumps(context, sort_keys=True, separators=(",", ":"))
    )


class NarrativeResearcher:
    def __init__(self, settings: Settings, client: ResponsesClient | None = None):
        self.settings = settings
        self._client = client

    def research(self, bundle: MarketDataBundle, *, offline: bool) -> ResearchOutput:
        context = build_research_context(bundle)
        prompt = _prompt(context, self.settings.max_narratives)
        if offline:
            draft = self._offline_draft(bundle)
            response_id = None
        else:
            draft, response_id = self._live_draft(prompt)

        result = finalize_research(
            draft,
            eligible_asset_ids={asset.asset_id for asset in bundle.assets},
            max_narratives=self.settings.max_narratives,
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
            max_tool_calls=8,
            max_output_tokens=8_000,
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
        protocols = {item.protocol_id: item for item in bundle.protocols}
        benchmark = assets.get("bitcoin")
        btc_7d = float(benchmark.change_7d_pct or 0) if benchmark else 0
        btc_30d = float(benchmark.change_30d_pct or 0) if benchmark else 0
        drafts: list[NarrativeResearchDraft] = []

        for definition in definitions:
            members = [assets[item] for item in definition["asset_ids"] if item in assets]
            category_members = [
                categories[item] for item in definition["category_ids"] if item in categories
            ]
            protocol_members = [
                protocols[item] for item in definition["protocol_ids"] if item in protocols
            ]
            rel_7d = [float(item.change_7d_pct or 0) - btc_7d for item in members]
            rel_30d = [float(item.change_30d_pct or 0) - btc_30d for item in members]
            category_24h = [float(item.change_24h_pct or 0) for item in category_members]
            protocol_7d = [float(item.change_7d_pct or 0) for item in protocol_members]
            protocol_30d = [float(item.change_30d_pct or 0) for item in protocol_members]

            market_confirmation = _clamp(50 + 1.6 * _median(rel_7d) + 0.7 * _median(rel_30d))
            breadth = (
                round(sum(item > 0 for item in rel_7d) / len(rel_7d) * 100, 1) if rel_7d else 0
            )
            fundamental_confirmation = _clamp(
                45 + 1.3 * _median(protocol_7d) + 0.4 * _median(protocol_30d)
            )
            category_strength = _median(category_24h)
            signals = NarrativeSignals(
                attention_acceleration=50,
                novelty=45,
                catalyst_strength=40,
                market_confirmation=market_confirmation,
                breadth=breadth,
                fundamental_confirmation=fundamental_confirmation,
                crowding_risk=_clamp(45 + max(0, _median(rel_30d)) + category_strength),
            )
            drafts.append(
                NarrativeResearchDraft(
                    narrative_id=definition["id"],
                    name=definition["name"],
                    summary=(
                        "Offline quantitative seed; live narrative evidence has not been "
                        "researched."
                    ),
                    confidence_score=40,
                    signals=signals,
                    thesis=(
                        "Relative market and protocol metrics warrant placing this narrative "
                        "on the radar."
                    ),
                    counter_thesis=(
                        "Fixture data cannot establish attention novelty, catalysts, or live "
                        "investability."
                    ),
                    constituent_ids=definition["asset_ids"],
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
                (
                    "Narrative scores are development fixtures and must not be treated as "
                    "current research."
                ),
            ],
        )


def _median(values: list[float]) -> float:
    return float(median(values)) if values else 0


def _clamp(value: float) -> float:
    return round(max(0, min(100, value)), 1)
