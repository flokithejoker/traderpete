from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from openai import OpenAI

from trader_pete.analysis.scoring import canonical_source_url, evidence_metrics
from trader_pete.config import Settings
from trader_pete.models import (
    DailyLandscapeResearch,
    DynamicRadarSnapshot,
    EvidenceStatus,
    LandscapeSnapshot,
    MarketDataBundle,
    MarketEvent,
    NarrativeUpdate,
    ProjectQualityAssessment,
    ProjectReview,
    ProjectVerdict,
    SocialWindowMetrics,
)

PROMPT_VERSION = "landscape-and-quality-v5"

SYSTEM_INSTRUCTIONS = """You are Trader Pete's bounded crypto market researcher.
The stable taxonomy, dynamic narrative radar, and deterministic rankings in the input are
authoritative. You may explain or challenge them, but you must never create, rename, merge, or
score a narrative. Use only supplied narrative IDs and project IDs. Do not produce price targets,
purchases, allocations, or trade recommendations.

Research at most five genuinely market-relevant root events from the last 72 hours or dated
catalysts inside the next 28 days. Map every event to the supplied stable narratives. Prefer
protocol or company announcements, filings, governance records, repositories, regulators,
onchain data, and reputable original reporting. Trace syndicated coverage to its root, keep
at most three independent roots per claim, and include contradictions. An aggregator or social
post can discover a lead but cannot verify one. Do not treat CoinGecko trending as sentiment.

For each stable focus narrative, state why the measured evidence matters now and the strongest
counterpoint. For project diligence, prioritize the two highest-ranked dynamic narratives with at
least three resolved projects, then the stable focus set. Review no more than two supplied projects
per stable focus or dynamic narrative.
A project review must separately cover identifiable team, independently confirmed backing,
shipped product, measured adoption/economics, engineering delivery, security/governance,
community evidence, token value capture, dated catalyst, and risks. Every non-unknown quality
dimension must cite URLs included in that review's source list. Mark evidence unavailable when it
cannot be verified. Do not call a project credible from branding, market capitalization, price
performance, follower counts, or anonymous enthusiasm. Strong VC backing is not automatically
bullish. Do not infer organic sentiment, individual bot status, or AI-authored news without an
auditable raw dataset.

The supplied input context is not a source. Never cite an input:// URL or restate the input as
external evidence; every returned source must be an HTTP(S) URL retrieved through web search.
Every source must include the atomic claim it supports, publisher, root URL, source type,
publication date when known, whether it is primary, whether it supports or contradicts the claim,
and a calibrated credibility value. Keep the market summary to three short sentences. Return the
structured object only."""


class ResearchConfigurationError(RuntimeError):
    pass


class ResponsesClient(Protocol):
    def parse(self, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class ResearchOutput:
    result: DailyLandscapeResearch
    prompt: str
    prompt_version: str
    response_id: str | None


class LandscapeResearcher:
    def __init__(self, settings: Settings, client: ResponsesClient | None = None):
        self.settings = settings
        self._client = client

    def research(
        self,
        bundle: MarketDataBundle,
        landscape: LandscapeSnapshot,
        radar: DynamicRadarSnapshot | None = None,
        social_metrics: list[SocialWindowMetrics] | None = None,
        *,
        offline: bool,
    ) -> ResearchOutput:
        prompt = _prompt(bundle, landscape, radar, social_metrics or [])
        if offline:
            result = _offline_result(landscape)
            response_id = None
        else:
            result, response_id, retrieved_urls = self._live_result(prompt)
            result = _validate_result(result, landscape, radar, retrieved_urls=retrieved_urls)
        return ResearchOutput(
            result=result,
            prompt=prompt,
            prompt_version=PROMPT_VERSION,
            response_id=response_id,
        )

    def _live_result(self, prompt: str) -> tuple[DailyLandscapeResearch, str | None, set[str]]:
        if not self.settings.openai_api_key and self._client is None:
            raise ResearchConfigurationError("Live research requires OPENAI_API_KEY.")
        client = self._client or OpenAI(api_key=self.settings.openai_api_key).responses
        response = client.parse(
            model=self.settings.model,
            reasoning={"effort": self.settings.reasoning_effort, "context": "current_turn"},
            tools=[{"type": "web_search", "search_context_size": "medium"}],
            include=["web_search_call.action.sources"],
            input=prompt,
            instructions=SYSTEM_INSTRUCTIONS,
            text_format=DailyLandscapeResearch,
            store=False,
            max_tool_calls=12,
            max_output_tokens=12_000,
            text={"verbosity": "low"},
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI returned no structured landscape research result.")
        return (
            response.output_parsed,
            getattr(response, "id", None),
            _web_source_urls(response),
        )


def _prompt(
    bundle: MarketDataBundle,
    landscape: LandscapeSnapshot,
    radar: DynamicRadarSnapshot | None,
    social_metrics: list[SocialWindowMetrics],
) -> str:
    focus_ids = {item.narrative_id for item in landscape.narratives if item.is_focus}
    context = {
        "as_of": landscape.as_of.isoformat(),
        "market_regime": landscape.market_regime,
        "stable_narratives": [
            {
                "id": item.narrative_id,
                "name": item.name,
                "description": item.description,
                "state": item.state.value,
                "is_focus": item.is_focus,
                "score": item.score,
                "confidence": item.confidence,
                "measured_metrics": item.metrics.model_dump(mode="json"),
            }
            for item in landscape.narratives
        ],
        "focus_projects": [
            {
                "narrative_id": item.narrative_id,
                "project_id": item.project_id,
                "name": item.name,
                "asset_id": item.asset_id,
                "rank": item.rank,
                "score": item.score,
                "eligible": item.eligible,
                "measured_metrics": item.metrics.model_dump(mode="json"),
                "selection_notes": item.selection_notes,
            }
            for item in landscape.projects
            if item.narrative_id in focus_ids and item.rank <= 3
        ],
        "dynamic_narratives": [
            {
                "id": item.narrative_id,
                "name": item.name,
                "mechanism": item.mechanism,
                "state": item.state.value,
                "score": item.score,
                "confidence": item.confidence,
                "persistence_days": item.persistence_days,
                "measured_metrics": item.metrics.model_dump(mode="json"),
                "catalyst": item.catalyst,
                "counter_thesis": item.counter_thesis,
                "project_ids": item.constituent_ids[:4],
            }
            for item in (radar.narratives if radar else [])
        ],
        "dynamic_projects": [
            {
                "narrative_id": narrative.narrative_id,
                "project_id": asset_id,
                "name": next(
                    (asset.name for asset in bundle.assets if asset.asset_id == asset_id), asset_id
                ),
                "asset_id": asset_id,
            }
            for narrative in (radar.narratives if radar else [])
            for asset_id in narrative.constituent_ids[:3]
        ],
        "social_measurements": [item.model_dump(mode="json") for item in social_metrics],
        "search_trending": [
            {
                "asset_id": item.asset_id,
                "name": item.name,
                "search_rank": item.search_rank,
                "market_cap_rank": item.market_cap_rank,
            }
            for item in bundle.trending_assets
        ],
        "known_measurement_limits": landscape.data_gaps,
    }
    return (
        "Research the morning context around this fixed quantitative landscape. "
        "Scores are supplied "
        "for explanation only and must not be edited or repeated as recommendations.\n\n"
        + json.dumps(context, sort_keys=True, separators=(",", ":"))
    )


def _offline_result(landscape: LandscapeSnapshot) -> DailyLandscapeResearch:
    focus = [item for item in landscape.narratives if item.is_focus]
    updates = [
        NarrativeUpdate(
            narrative_id=item.narrative_id,
            why_now=(
                f"Measured project breadth and growth place {item.name} in the daily focus set."
            ),
            counterpoint="Offline mode contains no current event or project-quality verification.",
            sources=[],
        )
        for item in focus
    ]
    return DailyLandscapeResearch(
        as_of=landscape.as_of,
        market_summary=(
            f"Offline fixture shows a {landscape.market_regime} quantitative regime. "
            "No live news, catalyst, team, or community research was performed."
        ),
        key_events=[],
        narrative_updates=updates,
        project_reviews=[],
        data_gaps=["Offline fixture: current events and project credibility were not researched."],
    )


def _validate_result(
    result: DailyLandscapeResearch,
    landscape: LandscapeSnapshot,
    radar: DynamicRadarSnapshot | None = None,
    retrieved_urls: set[str] | None = None,
) -> DailyLandscapeResearch:
    narrative_ids = {item.narrative_id for item in landscape.narratives}
    focus_ids = {item.narrative_id for item in landscape.narratives if item.is_focus}
    allowed_projects = {
        (item.narrative_id, item.project_id)
        for item in landscape.projects
        if item.narrative_id in focus_ids and item.rank <= 3
    }
    allowed_projects.update(
        (item.narrative_id, asset_id)
        for item in (radar.narratives if radar else [])
        for asset_id in item.constituent_ids[:3]
    )
    events: list[MarketEvent] = []
    for item in result.key_events[:5]:
        mapped = [value for value in dict.fromkeys(item.narrative_ids) if value in narrative_ids]
        sources = _dedupe_sources(item.sources, 3, retrieved_urls)
        evidence = evidence_metrics(sources, as_of=landscape.as_of)
        if not mapped or not evidence["verified"]:
            continue
        events.append(item.model_copy(update={"narrative_ids": mapped, "sources": sources}))
    updates: list[NarrativeUpdate] = []
    seen_updates: set[str] = set()
    for item in result.narrative_updates:
        if item.narrative_id not in focus_ids or item.narrative_id in seen_updates:
            continue
        seen_updates.add(item.narrative_id)
        sources = _dedupe_sources(item.sources, 4, retrieved_urls)
        if not evidence_metrics(sources, as_of=landscape.as_of)["verified"]:
            continue
        updates.append(item.model_copy(update={"sources": sources}))
    reviews: list[ProjectReview] = []
    seen_reviews: set[tuple[str, str]] = set()
    per_narrative: dict[str, int] = {}
    for item in result.project_reviews:
        key = (item.narrative_id, item.project_id)
        if key not in allowed_projects or key in seen_reviews:
            continue
        if per_narrative.get(item.narrative_id, 0) >= 2:
            continue
        sources = _dedupe_sources(item.sources, 5, retrieved_urls)
        verdict = item.verdict
        evidence = evidence_metrics(sources, as_of=landscape.as_of)
        quality = _validate_quality(item.quality, sources)
        if verdict is ProjectVerdict.CREDIBLE and not evidence["verified"]:
            verdict = ProjectVerdict.MIXED if sources else ProjectVerdict.INSUFFICIENT
        if (
            verdict is ProjectVerdict.CREDIBLE
            and quality
            and float(quality.seriousness_score or 0) < 65
        ):
            verdict = ProjectVerdict.MIXED
        reviews.append(
            item.model_copy(update={"sources": sources, "verdict": verdict, "quality": quality})
        )
        seen_reviews.add(key)
        per_narrative[item.narrative_id] = per_narrative.get(item.narrative_id, 0) + 1
    gaps = list(result.data_gaps)
    if len(updates) < len(focus_ids):
        gaps.append("Not every quantitative focus narrative received a verified research update.")
    if not events:
        gaps.append("No qualifying root event was verified for the morning brief.")
    return result.model_copy(
        update={
            "as_of": landscape.as_of,
            "key_events": events,
            "narrative_updates": updates,
            "project_reviews": reviews,
            "data_gaps": list(dict.fromkeys(gaps)),
        }
    )


def _validate_quality(
    quality: ProjectQualityAssessment | None,
    sources,
) -> ProjectQualityAssessment | None:
    if quality is None:
        return None
    allowed_urls = {canonical_source_url(source.url) for source in sources} | {
        canonical_source_url(source.root_url) for source in sources if source.root_url
    }
    status_points = {
        EvidenceStatus.STRONG: 100,
        EvidenceStatus.MIXED: 60,
        EvidenceStatus.WEAK: 25,
        EvidenceStatus.UNKNOWN: 0,
    }
    updates = {}
    known_scores = []
    for name in (
        "identity_and_team",
        "funding_and_backing",
        "product_delivery",
        "adoption_and_economics",
        "engineering_health",
        "security_and_governance",
        "community_quality",
        "token_value_capture",
    ):
        dimension = getattr(quality, name)
        evidence_urls = [
            value
            for value in dict.fromkeys(dimension.evidence_urls)
            if value.startswith(("https://", "http://"))
            and canonical_source_url(value) in allowed_urls
        ]
        status = dimension.status
        if status is not EvidenceStatus.UNKNOWN and not evidence_urls:
            status = EvidenceStatus.UNKNOWN
        validated = dimension.model_copy(update={"status": status, "evidence_urls": evidence_urls})
        updates[name] = validated
        if status is not EvidenceStatus.UNKNOWN:
            known_scores.append(status_points[status])
    coverage = round(len(known_scores) / 8 * 100, 1)
    updates["quality_coverage"] = coverage
    updates["seriousness_score"] = (
        round(sum(known_scores) / len(known_scores), 1) if len(known_scores) >= 4 else None
    )
    return quality.model_copy(update=updates)


def _dedupe_sources(sources, limit: int, retrieved_urls: set[str] | None = None):
    selected = {}
    for source in sources:
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
        source = source.model_copy(update={"root_url": root_url})
        root = canonical_source_url(source.root_url or source.url)
        selected.setdefault(root, source)
    return list(selected.values())[:limit]


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


NarrativeResearcher = LandscapeResearcher
