from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from trader_pete.config import Settings
from trader_pete.models import SocialCoverage, SocialWindowMetrics

POSITIVE_WORDS = {
    "adoption",
    "bullish",
    "growth",
    "launch",
    "mainnet",
    "revenue",
    "shipping",
    "upgrade",
}
NEGATIVE_WORDS = {
    "bearish",
    "delay",
    "exploit",
    "hack",
    "rug",
    "scam",
    "unlock",
    "vulnerability",
}


@dataclass(frozen=True, slots=True)
class SocialTarget:
    target_type: str
    target_id: str
    label: str
    query_terms: tuple[str, ...] = ()


def _unavailable(target: SocialTarget, limitation: str) -> SocialWindowMetrics:
    return SocialWindowMetrics(
        provider="x",
        target_type=target.target_type,
        target_id=target.target_id,
        coverage=SocialCoverage.UNAVAILABLE,
        limitation=limitation,
    )


def collect_social_metrics(
    settings: Settings,
    targets: list[SocialTarget],
) -> list[SocialWindowMetrics]:
    """Collect a budget-capped X sample or return explicit missing-data rows."""
    selected = targets[: max(0, settings.x_max_queries)]
    if not settings.x_enabled:
        return [
            _unavailable(
                target,
                "X collection is disabled; set TRADER_PETE_X_ENABLED=true only after "
                "approving API spend.",
            )
            for target in selected
        ]
    if not settings.x_bearer_token:
        return [
            _unavailable(target, "X_BEARER_TOKEN is missing; social sentiment was not estimated.")
            for target in selected
        ]

    metrics: list[SocialWindowMetrics] = []
    observed_at = datetime.now(UTC)
    window_start = observed_at - timedelta(hours=24)
    headers = {"Authorization": f"Bearer {settings.x_bearer_token}"}
    with httpx.Client(base_url="https://api.x.com", timeout=30, headers=headers) as client:
        for index, target in enumerate(selected):
            terms = target.query_terms or (target.label,)
            quoted = [f'"{value}"' if " " in value else value for value in terms if value]
            query = f"({' OR '.join(quoted)}) lang:en"
            try:
                response = client.get(
                    "/2/tweets/search/recent",
                    params={
                        "query": query,
                        "max_results": max(10, min(100, settings.x_posts_per_query)),
                        "tweet.fields": (
                            "author_id,created_at,entities,lang,public_metrics,referenced_tweets"
                        ),
                        "sort_order": "recency",
                        "start_time": window_start.isoformat().replace("+00:00", "Z"),
                        "end_time": observed_at.isoformat().replace("+00:00", "Z"),
                    },
                )
                response.raise_for_status()
                metrics.append(
                    _aggregate_x(
                        target,
                        response.json().get("data") or [],
                        observed_at=observed_at,
                        window_start=window_start,
                        result_cap=max(10, min(100, settings.x_posts_per_query)),
                    )
                )
            except httpx.HTTPStatusError as error:
                metrics.append(_unavailable(target, f"X request failed: {type(error).__name__}."))
                if error.response.status_code in {401, 402, 403, 429}:
                    metrics.extend(
                        _unavailable(
                            remaining,
                            f"X collection stopped after HTTP {error.response.status_code}.",
                        )
                        for remaining in selected[index + 1 :]
                    )
                    break
            except (httpx.HTTPError, ValueError) as error:
                metrics.append(_unavailable(target, f"X request failed: {type(error).__name__}."))
    return metrics


def _normalize_text(value: str) -> str:
    value = re.sub(r"https?://\S+", " ", value.lower())
    value = re.sub(r"[$#@][a-z0-9_]+", " ", value)
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _percent(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _aggregate_x(
    target: SocialTarget,
    posts: list[dict],
    *,
    observed_at: datetime,
    window_start: datetime,
    result_cap: int,
) -> SocialWindowMetrics:
    if not posts:
        return SocialWindowMetrics(
            provider="x",
            target_type=target.target_type,
            target_id=target.target_id,
            coverage=SocialCoverage.PARTIAL,
            observed_at=observed_at,
            window_start_at=window_start,
            window_end_at=observed_at,
            limitation="The bounded recent-search query returned no posts.",
        )
    authors = Counter(str(item.get("author_id") or "unknown") for item in posts)
    normalized_hashes = []
    for item in posts:
        normalized = _normalize_text(str(item.get("text") or ""))
        fingerprint = normalized or f"empty:{item.get('id', len(normalized_hashes))}"
        normalized_hashes.append(hashlib.sha256(fingerprint.encode()).hexdigest())
    duplicate_share = (len(posts) - len(set(normalized_hashes))) / len(posts) * 100
    referenced = [item.get("referenced_tweets") or [] for item in posts]
    reposts = sum(
        any(reference.get("type") == "retweeted" for reference in references)
        for references in referenced
    )
    author_hhi = sum((count / len(posts)) ** 2 for count in authors.values()) * 100
    domains: list[str] = []
    hours: Counter[str] = Counter()
    positives = 0
    negatives = 0
    for item in posts:
        entities = item.get("entities") or {}
        for url in entities.get("urls") or []:
            host = urlsplit(url.get("expanded_url") or url.get("url") or "").hostname
            if host:
                domains.append(host.lower().removeprefix("www."))
        created_at = str(item.get("created_at") or "")
        try:
            bucket = datetime.fromisoformat(created_at.replace("Z", "+00:00")).strftime(
                "%Y-%m-%dT%H"
            )
            hours[bucket] += 1
        except ValueError:
            pass
        words = set(re.findall(r"[a-z]+", str(item.get("text") or "").lower()))
        positives += bool(words & POSITIVE_WORDS)
        negatives += bool(words & NEGATIVE_WORDS)
    unique_domains = len(set(domains))
    if domains and unique_domains > 1:
        probabilities = [count / len(domains) for count in Counter(domains).values()]
        entropy = -sum(value * math.log(value) for value in probabilities)
        source_entropy = _percent(entropy / math.log(unique_domains) * 100)
    else:
        source_entropy = None
    url_concentration = max(Counter(domains).values()) / len(domains) * 100 if domains else 0.0
    if len(hours) >= 2 and len(posts) >= 10:
        mean_bucket = len(posts) / len(hours)
        timing_burstiness = _percent((max(hours.values()) / max(mean_bucket, 1) - 1) * 35)
    else:
        timing_burstiness = None
    coordination_risk = (
        _percent(
            0.35 * duplicate_share
            + 0.25 * author_hhi
            + 0.20 * url_concentration
            + 0.20 * float(timing_burstiness or 0)
        )
        if len(posts) >= 10 and len(authors) >= 5
        else None
    )
    positive_share = positives / len(posts) * 100
    negative_share = negatives / len(posts) * 100
    sentiment_score = round((positive_share - negative_share), 1) if len(posts) >= 5 else None
    return SocialWindowMetrics(
        provider="x",
        target_type=target.target_type,
        target_id=target.target_id,
        coverage=SocialCoverage.PARTIAL,
        observed_at=observed_at,
        window_start_at=window_start,
        window_end_at=observed_at,
        right_censored=len(posts) >= result_cap,
        estimated_cost_usd=round(len(posts) * 0.005, 4),
        raw_posts=len(posts),
        unique_authors=len(authors),
        original_posts=len(posts) - reposts,
        duplicate_share=_percent(duplicate_share),
        repost_share=_percent(reposts / len(posts) * 100),
        author_concentration=_percent(author_hhi),
        source_entropy=source_entropy,
        timing_burstiness=timing_burstiness,
        coordination_risk=coordination_risk,
        positive_share=_percent(positive_share),
        negative_share=_percent(negative_share),
        sentiment_score=sentiment_score,
        limitation=(
            "Lexicon stance from a budget-capped recent-search sample; not population "
            "sentiment or bot detection."
        ),
    )
