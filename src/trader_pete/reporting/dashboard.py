from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from statistics import median
from typing import Any

from jinja2 import Environment, select_autoescape

from trader_pete.db import Database, content_hash


@dataclass(frozen=True, slots=True)
class DashboardArtifact:
    path: Path
    sha256: str


def _median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return round(median(values), 2) if values else None


def _sector_rows(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in assets:
        groups[asset.get("primary_sector") or "unclassified"].append(asset)
    rows = []
    for sector, members in groups.items():
        rows.append(
            {
                "name": _sector_label(sector),
                "asset_count": len(members),
                "market_cap_usd": sum(float(item.get("market_cap_usd") or 0) for item in members),
                "median_7d_pct": _median(members, "change_7d_pct"),
                "median_30d_pct": _median(members, "change_30d_pct"),
            }
        )
    return sorted(rows, key=lambda row: row["market_cap_usd"], reverse=True)


def _prepare(data: dict[str, Any]) -> dict[str, Any]:
    source_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in data["sources"]:
        source_map[source["narrative_id"]].append(source)
    member_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for membership in data["memberships"]:
        member_map[membership["narrative_id"]].append(membership)
    for narrative in data["narratives"]:
        narrative["signals"] = json.loads(narrative.pop("signals_json"))
        narrative["sources"] = source_map[narrative["narrative_id"]]
        narrative["members"] = member_map[narrative["narrative_id"]]

    observed_values = [row["observed_at"] for row in data["assets"] if row.get("observed_at")]
    observed_at = min(observed_values) if observed_values else data["run"]["as_of"]
    observed_datetime = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    age_hours = max(0, (datetime.now(UTC) - observed_datetime).total_seconds() / 3600)
    data["observed_at"] = observed_at
    data["age_hours"] = round(age_hours, 1)
    data["is_stale"] = age_hours > 36
    data["data_gaps"] = json.loads(data["research"]["data_gaps_json"])
    data["sectors"] = _sector_rows(data["assets"])
    data["selected_projects"] = list({row["asset_id"]: row for row in data["memberships"]}.values())
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
        environment.filters["sector"] = _sector_label
        html = environment.from_string(template_text).render(**data)
        report_date = data["run"]["as_of"][:10]
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        path = (self.reports_dir / f"{report_date}.html").resolve()
        path.write_text(html, encoding="utf-8")
        return DashboardArtifact(path=path, sha256=content_hash(html))


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


def _sector_label(value: str | None) -> str:
    if not value:
        return "Unclassified"
    labels = {"defi": "DeFi"}
    return labels.get(value, value.replace("_", " ").title())
