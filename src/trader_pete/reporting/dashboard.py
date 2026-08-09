from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from statistics import median
from typing import Any

from jinja2 import Environment, select_autoescape

from trader_pete.analysis.scoring import canonical_source_url, is_primary_source, source_domain
from trader_pete.db import Database
from trader_pete.models import EvidenceSource


@dataclass(frozen=True, slots=True)
class DashboardArtifact:
    path: Path
    sha256: str


def _median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return round(median(values), 2) if values else None


def _source_summary(sources: list[dict[str, Any]], as_of: datetime) -> dict[str, Any]:
    roots = {canonical_source_url(source.get("root_url") or source["url"]) for source in sources}
    publishers = {
        (source.get("publisher") or source_domain(source["url"])).strip().lower()
        for source in sources
    }
    fresh = 0
    for source in sources:
        if source.get("published_at"):
            published = datetime.fromisoformat(source["published_at"].replace("Z", "+00:00"))
            if 0 <= (as_of - published).total_seconds() <= 7 * 86_400:
                fresh += 1
    return {
        "raw_count": len(sources),
        "root_count": len(roots),
        "publisher_count": len(publishers),
        "primary_count": sum(bool(source.get("trusted_primary")) for source in sources),
        "contradiction_count": sum(not bool(source["supports"]) for source in sources),
        "fresh_count": fresh,
        "duplicate_count": max(0, len(sources) - len(roots)),
    }


def _prepare(data: dict[str, Any]) -> dict[str, Any]:
    source_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in data["sources"]:
        source["trusted_primary"] = is_primary_source(
            EvidenceSource(
                title=source["title"],
                url=source["url"],
                published_at=source["published_at"],
                source_type=source["source_type"],
                publisher=source["publisher"],
                root_url=source["root_url"],
                claim=source["claim"],
                is_primary=bool(source["is_primary"]),
                supports=bool(source["supports"]),
                credibility=source["credibility"],
            )
        )
        source_map[source["narrative_id"]].append(source)
    member_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for membership in data["memberships"]:
        member_map[membership["narrative_id"]].append(membership)

    as_of = datetime.fromisoformat(data["run"]["as_of"].replace("Z", "+00:00"))
    benchmark = next((row for row in data["assets"] if row["asset_id"] == "bitcoin"), None)
    btc_7d = float(benchmark.get("change_7d_pct") or 0) if benchmark else 0
    for narrative in data["narratives"]:
        narrative["signals"] = json.loads(narrative.pop("signals_json"))
        narrative["metric_coverage"] = json.loads(narrative.pop("metric_coverage_json"))
        narrative["protocol_ids"] = json.loads(narrative.pop("protocol_ids_json"))
        narrative["sources"] = source_map[narrative["narrative_id"]]
        narrative["source_summary"] = _source_summary(narrative["sources"], as_of)
        narrative["members"] = member_map[narrative["narrative_id"]]
        narrative["median_7d_pct"] = _median(narrative["members"], "change_7d_pct")
        narrative["median_30d_pct"] = _median(narrative["members"], "change_30d_pct")
        narrative["btc_excess_7d_pct"] = (
            round(narrative["median_7d_pct"] - btc_7d, 2)
            if narrative["median_7d_pct"] is not None
            else None
        )

    all_observed = [
        row["observed_at"]
        for key in ("assets", "categories", "protocols", "trending")
        for row in data[key]
        if row.get("observed_at")
    ]
    observed_at = min(all_observed) if all_observed else data["run"]["as_of"]
    observed_datetime = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    age_hours = max(0, (datetime.now(UTC) - observed_datetime).total_seconds() / 3600)
    data["observed_at"] = observed_at
    data["age_hours"] = round(age_hours, 1)
    data["is_stale"] = age_hours > 36

    clean_categories = [
        row
        for row in data["categories"]
        if row.get("market_cap_usd")
        and row["market_cap_usd"] >= 10_000_000
        and row.get("volume_24h_usd")
        and row["volume_24h_usd"] >= 1_000_000
        and row.get("change_24h_pct") is not None
        and abs(row["change_24h_pct"]) <= 50
    ]
    data["category_pulse"] = clean_categories[:12]
    data["category_quality"] = {
        "raw": len(data["categories"]),
        "clean": len(clean_categories),
    }
    clean_protocols = [
        row
        for row in data["protocols"]
        if row.get("tvl_usd")
        and row["tvl_usd"] >= 1_000_000
        and row.get("change_7d_pct") is not None
        and abs(row["change_7d_pct"]) <= 500
    ]
    data["protocol_growth"] = clean_protocols[:10]

    data["shortlist"] = [item for item in data["narratives"] if item["is_shortlisted"]]
    data["watchlist"] = [item for item in data["narratives"] if not item["is_shortlisted"]]
    data["selected_projects"] = [
        {
            **member,
            "narrative_name": narrative["name"],
            "narrative_id": narrative["narrative_id"],
            "is_shortlisted": narrative["is_shortlisted"],
            "btc_excess_7d_pct": (
                round(float(member["change_7d_pct"] or 0) - btc_7d, 2)
                if member.get("change_7d_pct") is not None
                else None
            ),
        }
        for narrative in data["narratives"]
        for member in narrative["members"]
    ]

    assets_by_id = {row["asset_id"]: row for row in data["assets"]}
    for item in data["trending"]:
        item["market"] = assets_by_id.get(item["asset_id"])

    source_trust = [item["signals"].get("evidence_quality", 0) for item in data["narratives"]]
    asset_completeness = (
        sum(
            row.get("market_cap_usd") is not None
            and row.get("volume_24h_usd") is not None
            and row.get("change_7d_pct") is not None
            for row in data["assets"]
        )
        / len(data["assets"])
        * 100
        if data["assets"]
        else 0
    )
    category_clean_share = (
        len(clean_categories) / len(data["categories"]) * 100 if data["categories"] else 0
    )
    evidence_trust = median(source_trust) if source_trust else 0
    data["data_trust_score"] = round(
        0.45 * asset_completeness + 0.20 * category_clean_share + 0.35 * evidence_trust,
        1,
    )
    data["data_gaps"] = json.loads(data["research"]["data_gaps_json"])
    if len(clean_categories) < len(data["categories"]):
        data["data_gaps"].append(
            f"Category Pulse excludes {len(data['categories']) - len(clean_categories)} rows "
            "with missing, tiny, illiquid, or extreme inputs."
        )
    return data


class DashboardRenderer:
    def __init__(self, *, database: Database, reports_dir: Path):
        self.database = database
        self.reports_dir = reports_dir

    def render(self, run_id: str) -> DashboardArtifact:
        data = _prepare(self.database.dashboard_data(run_id))
        template_text = (
            files("trader_pete").joinpath("templates", "dashboard.html").read_text(encoding="utf-8")
        )
        environment = Environment(
            autoescape=select_autoescape(default_for_string=True),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        environment.filters["money"] = _money
        environment.filters["pct"] = _percent
        environment.filters["date"] = _date
        html = environment.from_string(template_text).render(**data)
        report_date = data["run"]["as_of"][:10]
        path = (self.reports_dir / report_date / f"{run_id}.html").resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = html.encode("utf-8")
        path.write_bytes(encoded)
        return DashboardArtifact(path=path, sha256=hashlib.sha256(encoded).hexdigest())


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    absolute = abs(value)
    if absolute >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:,.2f}"


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:+.1f}%"


def _date(value: str | None) -> str:
    return value[:10] if value else "undated"
