from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from openai import OpenAI

from trader_pete.analysis.scoring import (
    canonical_source_url,
    evidence_metrics,
    is_primary_source,
    source_origin,
)
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

PROMPT_VERSION = "landscape-and-quality-v9"
QUALITY_REASONING_EFFORT = "low"

SYSTEM_INSTRUCTIONS = """You are Trader Pete's bounded crypto market researcher.
The stable taxonomy, dynamic narrative radar, and deterministic rankings in the input are
authoritative. You may explain or challenge them, but you must never create, rename, merge, or
score a narrative. Use only supplied narrative IDs and project IDs. Do not produce price targets,
purchases, allocations, or trade recommendations.

Research at most two genuinely market-relevant root events from the last 72 hours or dated
catalysts inside the next 28 days. Map every event to the supplied stable narratives. Prefer
protocol or company announcements, filings, governance records, repositories, regulators,
onchain data, and reputable original reporting. Trace syndicated coverage to its root, keep
at most three independent roots per claim, and include contradictions. An aggregator or social
post can discover a lead but cannot verify one. Do not treat CoinGecko trending as sentiment.
Every event must include a normalized event subject, type, and timestamp. Multiple articles about
one subject/type/timestamp are independent evidence roots for one event, not separate events.

For each stable focus narrative, state why the measured evidence matters now and the strongest
counterpoint. Review exactly one project: take the first entry in project_research_shortlist. If
its evidence is unavailable, take the next entry; never substitute a project outside that
deterministic shortlist.
A project review must produce a falsifiable four-week investment case, not a company profile.
Separately cover project-to-narrative fit, identifiable team, independently confirmed backing,
shipped product, measured adoption/economics, engineering delivery, security/governance,
community evidence, and token value capture. Narrative fit must state the mechanism connecting
the measured narrative to demand for this exact token. Adoption must use a trend in fees, revenue,
users, volume, TVL, or another usage metric; current size alone is insufficient. Every non-unknown
quality dimension must cite URLs included in that review's source list. Separately verify
circulating and total supply plus material unlocks or emissions inside the next 35 days. Return the
unlock amount, percentage of circulating supply, largest dated cliff, and exact schedule URL.
Use 0% only when a retrieved official schedule establishes no unlock; do not infer a schedule
from fully diluted valuation. Mark evidence unavailable when it
cannot be verified. Do not call a project credible from branding, market capitalization, price
performance, follower counts, or anonymous enthusiasm. Strong VC backing is not automatically
bullish. Supply one specific catalyst timestamp inside the next 28 days and its source URLs only
when independently verified; otherwise leave catalyst_at and catalyst_evidence_urls empty. State
the causal investment thesis, two observable invalidation conditions, and the strongest downside
case. Do not infer organic sentiment, individual bot status, or AI-authored news without an
auditable raw dataset.

Be terse: keep every narrative explanation, quality reason, project field, risk, and source claim
under 25 words. Use at most five sources for the one reviewed project and two risks. The dashboard
needs decisions, not essay prose.

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
    retrieved_urls: tuple[str, ...]
    retrieval_manifest: tuple[dict[str, Any], ...]


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
            retrieved_urls: set[str] = set()
            retrieval_manifest: list[dict[str, Any]] = []
        else:
            result, response_id, retrieved_urls, retrieval_manifest = self._live_result(prompt)
            result = _validate_result(
                result,
                bundle,
                landscape,
                radar,
                retrieved_urls=retrieved_urls,
            )
        return ResearchOutput(
            result=result,
            prompt=prompt,
            prompt_version=PROMPT_VERSION,
            response_id=response_id,
            retrieved_urls=tuple(sorted(retrieved_urls)),
            retrieval_manifest=tuple(retrieval_manifest),
        )

    def _live_result(
        self, prompt: str
    ) -> tuple[DailyLandscapeResearch, str | None, set[str], list[dict[str, Any]]]:
        if not self.settings.openai_api_key and self._client is None:
            raise ResearchConfigurationError("Live research requires OPENAI_API_KEY.")
        client = self._client or OpenAI(api_key=self.settings.openai_api_key).responses
        response = client.parse(
            model=self.settings.model,
            reasoning={"effort": QUALITY_REASONING_EFFORT, "context": "current_turn"},
            tools=[{"type": "web_search", "search_context_size": "medium"}],
            include=["web_search_call.action.sources"],
            input=prompt,
            instructions=SYSTEM_INSTRUCTIONS,
            text_format=DailyLandscapeResearch,
            store=False,
            max_tool_calls=9,
            max_output_tokens=24_000,
            text={"verbosity": "low"},
        )
        if response.output_parsed is None:
            raise RuntimeError("OpenAI returned no structured landscape research result.")
        return (
            response.output_parsed,
            getattr(response, "id", None),
            _web_source_urls(response),
            _web_retrieval_manifest(response),
        )


def _project_research_shortlist(
    bundle: MarketDataBundle,
    landscape: LandscapeSnapshot,
    radar: DynamicRadarSnapshot | None,
) -> list[dict[str, object]]:
    assets = {item.asset_id: item for item in bundle.assets}
    state_rank = {
        "accelerating": 4,
        "emerging": 3,
        "observed": 2,
        "first_seen": 1,
    }
    dynamic_rows: list[tuple[tuple[float, ...], dict[str, object]]] = []
    for narrative in radar.narratives if radar else []:
        if (
            narrative.state.value not in state_rank
            or narrative.metrics.unique_evidence_roots < 2
            or narrative.metrics.lane_count < 2
        ):
            continue
        members = [assets[value] for value in narrative.constituent_ids if value in assets]
        if not members:
            continue
        project = max(
            members,
            key=lambda item: (
                item.volume_24h_usd is not None,
                (item.volume_24h_usd or 0) / max(item.market_cap_usd or 1, 1),
                item.change_7d_pct if item.change_7d_pct is not None else -10_000,
                item.market_cap_usd or 0,
            ),
        )
        rank = (
            float(state_rank[narrative.state.value]),
            narrative.score,
            float(narrative.metrics.fundamental_confirmation or 0),
            narrative.metrics.evidence_quality,
        )
        dynamic_rows.append(
            (
                rank,
                {
                    "narrative_id": narrative.narrative_id,
                    "narrative_name": narrative.name,
                    "project_id": project.asset_id,
                    "project_name": project.name,
                    "asset_id": project.asset_id,
                    "narrative_state": narrative.state.value,
                    "narrative_score": narrative.score,
                    "confirmed_lanes": narrative.metrics.lane_count,
                    "supportive_roots": narrative.metrics.unique_evidence_roots,
                    "selection_reason": (
                        "Highest-liquidity resolved member of the strongest narrative with at "
                        "least two Python-confirmed discovery lanes and two evidence roots."
                    ),
                },
            )
        )
    if dynamic_rows:
        return [
            item for _, item in sorted(dynamic_rows, key=lambda value: value[0], reverse=True)[:3]
        ]

    focus_ids = {item.narrative_id for item in landscape.narratives if item.is_focus}
    stable = sorted(
        (
            item
            for item in landscape.projects
            if item.narrative_id in focus_ids and item.research_eligible
        ),
        key=lambda item: (
            item.score,
            float(item.metrics.fundamental_growth_score or 0),
            float(item.metrics.liquidity_score or 0),
        ),
        reverse=True,
    )
    return [
        {
            "narrative_id": item.narrative_id,
            "narrative_name": next(
                (
                    narrative.name
                    for narrative in landscape.narratives
                    if narrative.narrative_id == item.narrative_id
                ),
                item.narrative_id,
            ),
            "project_id": item.project_id,
            "project_name": item.name,
            "asset_id": item.asset_id,
            "narrative_state": "stable_focus",
            "narrative_score": item.score,
            "confirmed_lanes": 0,
            "supportive_roots": 0,
            "selection_reason": (
                "Stable-focus fallback when no dynamic narrative passed lane gates."
            ),
        }
        for item in stable[:3]
    ]


def _prompt(
    bundle: MarketDataBundle,
    landscape: LandscapeSnapshot,
    radar: DynamicRadarSnapshot | None,
    social_metrics: list[SocialWindowMetrics],
) -> str:
    focus_ids = {item.narrative_id for item in landscape.narratives if item.is_focus}
    project_shortlist = _project_research_shortlist(bundle, landscape, radar)
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
                "research_eligible": item.research_eligible,
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
        "project_research_shortlist": project_shortlist,
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
    bundle: MarketDataBundle,
    landscape: LandscapeSnapshot,
    radar: DynamicRadarSnapshot | None = None,
    retrieved_urls: set[str] | None = None,
) -> DailyLandscapeResearch:
    narrative_ids = {item.narrative_id for item in landscape.narratives}
    focus_ids = {item.narrative_id for item in landscape.narratives if item.is_focus}
    allowed_projects = {
        (item["narrative_id"], item["project_id"])
        for item in _project_research_shortlist(bundle, landscape, radar)
    }
    events: list[MarketEvent] = []
    for item in result.key_events[:5]:
        mapped = [value for value in dict.fromkeys(item.narrative_ids) if value in narrative_ids]
        sources = _dedupe_sources(item.sources, 3, retrieved_urls)
        evidence = evidence_metrics(sources, as_of=landscape.as_of)
        event_age = (
            (item.event_at - landscape.as_of).total_seconds() / 86_400 if item.event_at else None
        )
        source_fresh = bool(sources) and all(
            source.published_at is not None
            and -1 <= (landscape.as_of - source.published_at).total_seconds() / 86_400 <= 3
            for source in sources
        )
        subject_tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", item.event_subject.lower())
            if len(token) >= 4
        }
        type_tokens = {
            token for token in re.findall(r"[a-z0-9]+", item.event_type.lower()) if len(token) >= 3
        }
        claims_linked = bool(subject_tokens) and all(
            len(subject_tokens & set(re.findall(r"[a-z0-9]+", source.claim.lower())))
            >= min(2, len(subject_tokens))
            and (
                not type_tokens or type_tokens & set(re.findall(r"[a-z0-9]+", source.claim.lower()))
            )
            for source in sources
        )
        event_window_ok = -3 <= event_age <= 28 if event_age is not None else source_fresh
        if event_age is not None and event_age <= 0:
            event_window_ok = event_window_ok and source_fresh
        if (
            not mapped
            or not evidence["verified"]
            or not item.event_subject.strip()
            or not item.event_type.strip()
            or not event_window_ok
            or not claims_linked
        ):
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
        if len(reviews) >= 1:
            break
        key = (item.narrative_id, item.project_id)
        if key not in allowed_projects or key in seen_reviews:
            continue
        if per_narrative.get(item.narrative_id, 0) >= 1:
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
        allowed_source_urls = {canonical_source_url(source.url) for source in sources} | {
            canonical_source_url(source.root_url) for source in sources if source.root_url
        }
        catalyst_urls = [
            value
            for value in dict.fromkeys(item.catalyst_evidence_urls)
            if value.startswith(("https://", "http://"))
            and canonical_source_url(value) in allowed_source_urls
        ][:2]
        catalyst_at = _as_utc(item.catalyst_at)
        decision_at = _as_utc(landscape.as_of)
        catalyst_in_window = bool(
            catalyst_at
            and decision_at
            and 0 <= (catalyst_at - decision_at).total_seconds() / 86_400 <= 28
            and catalyst_urls
        )
        reviews.append(
            item.model_copy(
                update={
                    "sources": sources,
                    "verdict": verdict,
                    "quality": quality,
                    "catalyst_at": catalyst_at if catalyst_in_window else None,
                    "catalyst_evidence_urls": catalyst_urls if catalyst_in_window else [],
                }
            )
        )
        seen_reviews.add(key)
        per_narrative[item.narrative_id] = per_narrative.get(item.narrative_id, 0) + 1
    gaps = list(result.data_gaps)
    if len(updates) < len(focus_ids):
        gaps.append("Not every quantitative focus narrative received a verified research update.")
    if not events:
        gaps.append("No qualifying root event was verified for the morning brief.")
    market_summary = (
        " ".join(f"{event.title}: {event.why_it_matters}" for event in events)
        if events
        else (
            "No qualifying root event survived retrieval and independence checks. Use the "
            "quantitative boards below; no news catalyst is asserted by this run."
        )
    )
    return result.model_copy(
        update={
            "as_of": landscape.as_of,
            "key_events": events,
            "narrative_updates": updates,
            "project_reviews": reviews,
            "market_summary": market_summary,
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
        "narrative_fit",
        "identity_and_team",
        "funding_and_backing",
        "product_delivery",
        "adoption_and_economics",
        "engineering_health",
        "security_and_governance",
        "community_quality",
        "token_value_capture",
        "token_supply_and_unlocks",
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
    coverage = round(len(known_scores) / 10 * 100, 1)
    updates["quality_coverage"] = coverage
    updates["seriousness_score"] = (
        round(sum(known_scores) / len(known_scores), 1) if len(known_scores) >= 4 else None
    )
    unlock_url = quality.unlock_schedule_source_url
    if not unlock_url or canonical_source_url(unlock_url) not in allowed_urls:
        updates.update(
            {
                "next_35d_unlock_pct_of_circulating": None,
                "next_35d_unlock_amount": None,
                "largest_unlock_at": None,
                "unlock_schedule_source_url": None,
            }
        )
    return quality.model_copy(update=updates)


def _dedupe_sources(sources, limit: int, retrieved_urls: set[str] | None = None):
    selected = {}
    for source in sources:
        cited = canonical_source_url(source.url)
        if retrieved_urls is not None and cited not in retrieved_urls:
            continue
        # Model-supplied syndication metadata is not an independence signal.
        source = source.model_copy(update={"root_url": ""})
        source = source.model_copy(update={"is_primary": is_primary_source(source)})
        root = source_origin(source.url)
        selected.setdefault(root, source)
    return list(selected.values())[:limit]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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


def _web_retrieval_manifest(response: Any) -> list[dict[str, Any]]:
    manifest = []
    for index, item in enumerate(getattr(response, "output", []) or []):
        if getattr(item, "type", "") != "web_search_call":
            continue
        action = getattr(item, "action", None)
        if hasattr(action, "model_dump"):
            action_data = action.model_dump(mode="json")
        else:
            action_data = {
                "type": getattr(action, "type", None),
                "query": getattr(action, "query", None),
                "sources": [
                    {
                        "url": getattr(source, "url", None),
                        "title": getattr(source, "title", None),
                    }
                    for source in getattr(action, "sources", []) or []
                ],
            }
        manifest.append({"call_index": index, "action": action_data})
    return manifest


NarrativeResearcher = LandscapeResearcher
