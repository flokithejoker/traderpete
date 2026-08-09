from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape

from trader_pete.db import Database


@dataclass(frozen=True, slots=True)
class DashboardArtifact:
    path: Path
    sha256: str


def _prepare(data: dict[str, Any]) -> dict[str, Any]:
    previous_narratives = {item["narrative_id"]: item for item in data.pop("previous_narratives")}
    previous_projects = {
        (item["narrative_id"], item["project_id"]): item for item in data.pop("previous_projects")
    }
    projects_by_narrative: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in data["projects"]:
        item["research_eligible"] = bool(item.pop("eligible"))
        item["metrics"] = json.loads(item.pop("metrics_json"))
        item["selection_notes"] = json.loads(item.pop("selection_notes_json"))
        review_json = item.pop("review_json")
        item["review"] = json.loads(review_json) if review_json else None
        prior = previous_projects.get((item["narrative_id"], item["project_id"]))
        item["score_delta"] = round(item["score"] - prior["score"], 1) if prior else None
        projects_by_narrative[item["narrative_id"]].append(item)

    narrative_names = {item["narrative_id"]: item["name"] for item in data["narratives"]}
    for item in data["narratives"]:
        item["metrics"] = json.loads(item.pop("metrics_json"))
        update_json = item.pop("update_json")
        item["update"] = json.loads(update_json) if update_json else None
        item["projects"] = projects_by_narrative[item["narrative_id"]]
        item["top_projects"] = [
            project for project in item["projects"] if project["research_eligible"]
        ][:3]
        prior = previous_narratives.get(item["narrative_id"])
        item["score_delta"] = round(item["score"] - prior["score"], 1) if prior else None
        item["previous_state"] = prior["state"] if prior else None

    for item in data["events"]:
        item["narrative_ids"] = json.loads(item.pop("narrative_ids_json"))
        item["narrative_names"] = [
            narrative_names[value] for value in item["narrative_ids"] if value in narrative_names
        ]
        item["sources"] = json.loads(item.pop("sources_json"))

    dynamic_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in data["dynamic_memberships"]:
        review_json = item.pop("review_json")
        item["review"] = json.loads(review_json) if review_json else None
        dynamic_members[item["narrative_id"]].append(item)
    for item in data["dynamic_narratives"]:
        for field in (
            "parent_narrative_ids_json",
            "aliases_json",
            "protocol_ids_json",
            "discovery_lanes_json",
            "rejection_reasons_json",
            "metrics_json",
            "sources_json",
        ):
            item[field.removesuffix("_json")] = json.loads(item.pop(field))
        item["members"] = dynamic_members[item["narrative_id"]]
        item["parent_names"] = [
            narrative_names[value]
            for value in item["parent_narrative_ids"]
            if value in narrative_names
        ]

    social = [json.loads(item["metrics_json"]) for item in data["social_metrics"]]
    data["social_metrics"] = social
    measured_social = [item for item in social if item["coverage"] == "measured"]
    partial_social = [item for item in social if item["coverage"] == "partial"]
    data["social_status"] = (
        "measured" if measured_social else "partial" if partial_social else "unavailable"
    )
    data["social_measured_count"] = len(measured_social)
    data["promoted_dynamic_count"] = sum(
        item["state"] in {"emerging", "accelerating"} for item in data["dynamic_narratives"]
    )

    for item in data["paper_candidates"]:
        assessment = json.loads(item.pop("assessment_json"))
        item.update(assessment)
        item["gate_map"] = {gate["name"]: gate for gate in item["gates"]}
        item["blockers"] = [gate for gate in item["gates"] if gate["status"] != "pass"]
        research_gates = [
            item["gate_map"][name]
            for name in ("narrative_state", "narrative_evidence", "project_diligence")
        ]
        item["research_status"] = (
            "fail"
            if any(gate["status"] == "fail" for gate in research_gates)
            else "unknown"
            if any(gate["status"] == "unknown" for gate in research_gates)
            else "pass"
        )
    for item in data["paper_proposals"]:
        item["packet"] = json.loads(item.pop("proposal_json"))
    data["paper_proposable_count"] = sum(
        item["state"] == "proposable" for item in data["paper_candidates"]
    )

    assets = {item["asset_id"]: item for item in data["assets"]}
    bitcoin = assets.get("bitcoin") or {}
    liquid_assets = [
        item
        for item in data["assets"]
        if item.get("market_cap_usd")
        and item["market_cap_usd"] >= 100_000_000
        and item.get("change_7d_pct") is not None
    ]
    breadth = (
        sum(float(item["change_7d_pct"]) > 0 for item in liquid_assets) / len(liquid_assets) * 100
        if liquid_assets
        else 0
    )
    is_live = data["run"]["mode"] == "live"
    provider_fetch = data.get("provider_fetch") or {}
    observed_at = provider_fetch.get("latest_response_at") if is_live else None
    observed_at = observed_at or data["run"]["as_of"]
    observed_datetime = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    age_hours = max(0, (datetime.now(UTC) - observed_datetime).total_seconds() / 3600)
    total_projects = sum(item["metrics"]["project_count"] for item in data["narratives"])
    measured_projects = sum(
        item["metrics"]["measured_project_count"] for item in data["narratives"]
    )

    data["focus_narratives"] = [item for item in data["narratives"] if item["is_focus"]]
    focus_ids = {item["narrative_id"] for item in data["focus_narratives"]}
    focus_projects = [
        item
        for item in data["projects"]
        if item["narrative_id"] in focus_ids and item["research_eligible"]
    ]
    fallback_projects = [item for item in data["projects"] if item["research_eligible"]]
    data["project_candidates"] = sorted(
        focus_projects or fallback_projects,
        key=lambda item: item["score"],
        reverse=True,
    )[:18]
    data["narrative_names"] = narrative_names
    data["btc_7d"] = bitcoin.get("change_7d_pct")
    data["btc_30d"] = bitcoin.get("change_30d_pct")
    data["market_breadth"] = round(breadth, 1)
    data["coverage_pct"] = (
        round(measured_projects / total_projects * 100, 1) if total_projects else 0
    )
    data["observed_at"] = observed_at
    data["is_live"] = is_live
    data["has_provider_fetch"] = bool(is_live and provider_fetch.get("received_payloads"))
    data["age_hours"] = round(age_hours, 1)
    data["is_stale"] = age_hours > 36
    data["data_gaps"] = json.loads(data["research"]["data_gaps_json"])
    if data.get("dynamic_research"):
        data["data_gaps"] = list(
            dict.fromkeys(
                [
                    *data["data_gaps"],
                    *json.loads(data["dynamic_research"]["data_gaps_json"]),
                ]
            )
        )
    return data


class DashboardRenderer:
    def __init__(self, *, database: Database, reports_dir: Path):
        self.database = database
        self.reports_dir = reports_dir

    def render(self, run_id: str) -> DashboardArtifact:
        data = _prepare(self.database.landscape_dashboard_data(run_id))
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
        environment.filters["ratio"] = _ratio
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


def _ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}x"


def _date(value: str | None) -> str:
    return value[:10] if value else "undated"
