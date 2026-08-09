from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from openai import OpenAI

from trader_pete.analysis.context import build_research_context
from trader_pete.analysis.scoring import canonical_source_url
from trader_pete.config import Settings
from trader_pete.models import (
    DailyDynamicNarrativeDraft,
    LandscapeSnapshot,
    MarketDataBundle,
)

PROMPT_VERSION = "dynamic-radar-v2"

SYSTEM_INSTRUCTIONS = """You are Trader Pete's bounded dynamic crypto-narrative scout.
Discover narrow, economically coherent, time-bounded narratives that may be emerging now.
The supplied stable narratives are parent archetypes only; do not merely repeat them. Good
examples of granularity include perpetual DEX cash flow, prediction markets/event contracts,
on-chain gambling, sports betting, token launchpads, app-specific chains, or restaking slashing
infrastructure. These examples are not a required list.

Return no more than the requested candidate limit. A candidate must explain one economic
mechanism, source of demand, and likely beneficiary set. Use only supplied asset IDs, protocol
IDs, and stable parent IDs. Never invent an entity or return a numeric score, price target,
allocation, or trade recommendation. Broad labels such as DeFi, AI, Layer 1, or gaming are not
dynamic candidates by themselves.

Search concrete developments from the last 72 hours and dated catalysts inside the next 42 days.
Use market anomalies, protocol fees/revenue/volume/TVL acceleration, independent project adoption,
and search interest as discovery lanes. CoinGecko trending is search attention, not sentiment.
Trace news to auditable roots; syndicated copies remain one evidence origin. Prefer primary
announcements, governance records, repositories, regulators, on-chain data, and original
reporting. Include contradictions and promotional-source limitations. Social chatter alone cannot
verify a narrative and must be labelled as a social discovery lane.

The supplied input context is not a source. Never cite an input:// URL or restate the input as
external evidence; every returned source must be an HTTP(S) URL retrieved through web search.

List aliases rather than creating separate candidates for synonymous phrases. Discovery lanes
must use only: event, market, fundamental, search, social. Return the structured object only."""


class ResponsesClient(Protocol):
    def parse(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class DynamicResearchOutput:
    result: DailyDynamicNarrativeDraft
    prompt: str
    prompt_version: str
    response_id: str | None


class DynamicNarrativeResearcher:
    def __init__(self, settings: Settings, client: ResponsesClient | None = None):
        self.settings = settings
        self._client = client

    def research(
        self,
        bundle: MarketDataBundle,
        landscape: LandscapeSnapshot,
        *,
        offline: bool,
    ) -> DynamicResearchOutput:
        prompt = _prompt(bundle, landscape, self.settings.candidate_narratives)
        if offline:
            result = DailyDynamicNarrativeDraft(
                as_of=bundle.observed_at,
                candidates=[],
                data_gaps=[
                    "Offline fixture: dynamic web discovery and evidence verification were not run."
                ],
            )
            response_id = None
        else:
            result, response_id, retrieved_urls = self._live_result(prompt)
            result = _validate_result(
                result,
                bundle,
                landscape,
                self.settings.candidate_narratives,
                retrieved_urls=retrieved_urls,
            )
        return DynamicResearchOutput(
            result=result,
            prompt=prompt,
            prompt_version=PROMPT_VERSION,
            response_id=response_id,
        )

    def _live_result(self, prompt: str) -> tuple[DailyDynamicNarrativeDraft, str | None, set[str]]:
        if not self.settings.openai_api_key and self._client is None:
            raise RuntimeError("Dynamic live research requires OPENAI_API_KEY.")
        client = self._client or OpenAI(api_key=self.settings.openai_api_key).responses
        response = client.parse(
            model=self.settings.model,
            reasoning={"effort": self.settings.reasoning_effort, "context": "current_turn"},
            tools=[{"type": "web_search", "search_context_size": "medium"}],
            include=["web_search_call.action.sources"],
            input=prompt,
            instructions=SYSTEM_INSTRUCTIONS,
            text_format=DailyDynamicNarrativeDraft,
            store=False,
            max_tool_calls=10,
            max_output_tokens=10_000,
            text={"verbosity": "low"},
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI returned no structured dynamic-narrative result.")
        return (
            response.output_parsed,
            getattr(response, "id", None),
            _web_source_urls(response),
        )


def _prompt(
    bundle: MarketDataBundle,
    landscape: LandscapeSnapshot,
    candidate_limit: int,
) -> str:
    context = build_research_context(bundle)
    context["candidate_limit"] = candidate_limit
    context["stable_parent_archetypes"] = [
        {
            "id": item.narrative_id,
            "name": item.name,
            "description": item.description,
        }
        for item in landscape.narratives
    ]
    return (
        "Find the strongest dynamic narrative seeds in this bounded, point-in-time context. "
        "Log weak but coherent seeds too; deterministic code will decide promotion.\n\n"
        + json.dumps(context, sort_keys=True, separators=(",", ":"))
    )


def _validate_result(
    result: DailyDynamicNarrativeDraft,
    bundle: MarketDataBundle,
    landscape: LandscapeSnapshot,
    limit: int,
    retrieved_urls: set[str] | None = None,
) -> DailyDynamicNarrativeDraft:
    asset_ids = {item.asset_id for item in bundle.assets}
    protocol_ids = {item.protocol_id for item in bundle.protocols} | {
        item.protocol_id for item in bundle.protocol_activity
    }
    parent_ids = {item.narrative_id for item in landscape.narratives}
    candidates = []
    seen: set[tuple[str, str]] = set()
    for item in result.candidates[:limit]:
        key = (item.name.strip().lower(), item.mechanism.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        sources = []
        for source in item.sources[:6]:
            cited = canonical_source_url(source.url)
            if retrieved_urls is not None and cited not in retrieved_urls:
                continue
            root_url = source.root_url
            if (
                root_url
                and retrieved_urls is not None
                and canonical_source_url(root_url) not in retrieved_urls
            ):
                root_url = ""
            sources.append(source.model_copy(update={"root_url": root_url}))
        candidates.append(
            item.model_copy(
                update={
                    "parent_narrative_ids": [
                        value
                        for value in dict.fromkeys(item.parent_narrative_ids)
                        if value in parent_ids
                    ],
                    "constituent_ids": [
                        value for value in dict.fromkeys(item.constituent_ids) if value in asset_ids
                    ],
                    "protocol_ids": [
                        value for value in dict.fromkeys(item.protocol_ids) if value in protocol_ids
                    ],
                    "discovery_lanes": list(dict.fromkeys(item.discovery_lanes)),
                    "sources": sources,
                }
            )
        )
    gaps = list(result.data_gaps)
    if len(candidates) < len(result.candidates):
        gaps.append("Invalid, duplicate, or out-of-context dynamic entities were removed.")
    return result.model_copy(
        update={
            "as_of": bundle.observed_at,
            "candidates": candidates,
            "data_gaps": list(dict.fromkeys(gaps)),
        }
    )


def _web_source_urls(response: Any) -> set[str]:
    urls: set[str] = set()
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "web_search_call":
            continue
        action = getattr(item, "action", None)
        for source in getattr(action, "sources", []) or []:
            url = getattr(source, "url", None)
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                urls.add(canonical_source_url(url))
    return urls
