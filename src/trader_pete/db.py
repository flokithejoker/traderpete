from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import median
from typing import Any

from trader_pete.config import StrategyPolicy
from trader_pete.models import (
    CategoryMarket,
    DailyLandscapeResearch,
    DailyNarrativeResearch,
    DynamicRadarSnapshot,
    LandscapeSnapshot,
    MarketAsset,
    ProtocolActivityMetric,
    ProtocolMetric,
    RunMode,
    RunStatus,
    SocialWindowMetrics,
    TrendingAsset,
)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    as_of TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('offline', 'live')),
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS provider_payloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id),
    provider TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    UNIQUE (run_id, provider, endpoint)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    run_id TEXT NOT NULL REFERENCES runs(id),
    asset_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    price_usd REAL,
    market_cap_usd REAL,
    volume_24h_usd REAL,
    change_24h_pct REAL,
    change_7d_pct REAL,
    change_30d_pct REAL,
    primary_sector TEXT,
    PRIMARY KEY (run_id, asset_id)
);

CREATE TABLE IF NOT EXISTS category_snapshots (
    run_id TEXT NOT NULL REFERENCES runs(id),
    category_id TEXT NOT NULL,
    name TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    market_cap_usd REAL,
    volume_24h_usd REAL,
    change_24h_pct REAL,
    top_asset_ids_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, category_id)
);

CREATE TABLE IF NOT EXISTS protocol_snapshots (
    run_id TEXT NOT NULL REFERENCES runs(id),
    protocol_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    observed_at TEXT NOT NULL,
    tvl_usd REAL,
    change_1d_pct REAL,
    change_7d_pct REAL,
    change_30d_pct REAL,
    chains_json TEXT NOT NULL,
    PRIMARY KEY (run_id, protocol_id)
);

CREATE TABLE IF NOT EXISTS protocol_activity_snapshots (
    run_id TEXT NOT NULL REFERENCES runs(id),
    protocol_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT,
    metric_type TEXT NOT NULL CHECK (metric_type IN ('fees', 'revenue', 'dex_volume')),
    observed_at TEXT NOT NULL,
    total_24h_usd REAL,
    total_7d_usd REAL,
    total_30d_usd REAL,
    growth_1d_pct REAL,
    growth_7d_pct REAL,
    growth_30d_pct REAL,
    PRIMARY KEY (run_id, protocol_id, metric_type)
);

CREATE TABLE IF NOT EXISTS trending_snapshots (
    run_id TEXT NOT NULL REFERENCES runs(id),
    asset_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    search_rank INTEGER NOT NULL,
    market_cap_rank INTEGER,
    PRIMARY KEY (run_id, asset_id)
);

CREATE TABLE IF NOT EXISTS narrative_assessments (
    run_id TEXT NOT NULL REFERENCES runs(id),
    narrative_id TEXT NOT NULL,
    name TEXT NOT NULL,
    summary TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    opportunity_score REAL NOT NULL,
    confidence_score REAL NOT NULL,
    is_shortlisted INTEGER NOT NULL DEFAULT 0,
    signals_json TEXT NOT NULL,
    protocol_ids_json TEXT NOT NULL DEFAULT '[]',
    metric_coverage_json TEXT NOT NULL DEFAULT '{}',
    thesis TEXT NOT NULL,
    counter_thesis TEXT NOT NULL,
    PRIMARY KEY (run_id, narrative_id)
);

CREATE TABLE IF NOT EXISTS narrative_memberships (
    run_id TEXT NOT NULL,
    narrative_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1,
    PRIMARY KEY (run_id, narrative_id, asset_id),
    FOREIGN KEY (run_id, narrative_id)
        REFERENCES narrative_assessments(run_id, narrative_id)
);

CREATE TABLE IF NOT EXISTS research_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    narrative_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    source_type TEXT NOT NULL,
    publisher TEXT NOT NULL DEFAULT '',
    root_url TEXT NOT NULL DEFAULT '',
    claim TEXT NOT NULL DEFAULT '',
    is_primary INTEGER NOT NULL DEFAULT 0,
    supports INTEGER NOT NULL,
    credibility REAL NOT NULL,
    FOREIGN KEY (run_id, narrative_id)
        REFERENCES narrative_assessments(run_id, narrative_id)
);

CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY REFERENCES runs(id),
    model TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    response_id TEXT,
    market_regime TEXT NOT NULL,
    market_summary TEXT NOT NULL DEFAULT '',
    data_gaps_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS landscape_narratives (
    run_id TEXT NOT NULL REFERENCES runs(id),
    narrative_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    kpi_profile TEXT NOT NULL,
    rank INTEGER NOT NULL,
    state TEXT NOT NULL,
    is_focus INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL,
    confidence REAL NOT NULL,
    metrics_json TEXT NOT NULL,
    update_json TEXT,
    PRIMARY KEY (run_id, narrative_id)
);

CREATE TABLE IF NOT EXISTS landscape_projects (
    run_id TEXT NOT NULL,
    narrative_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    eligible INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    selection_notes_json TEXT NOT NULL,
    review_json TEXT,
    PRIMARY KEY (run_id, narrative_id, project_id),
    FOREIGN KEY (run_id, narrative_id)
        REFERENCES landscape_narratives(run_id, narrative_id)
);

CREATE TABLE IF NOT EXISTS market_events (
    run_id TEXT NOT NULL REFERENCES runs(id),
    event_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    direction TEXT NOT NULL,
    horizon TEXT NOT NULL,
    narrative_ids_json TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    PRIMARY KEY (run_id, event_index)
);

CREATE TABLE IF NOT EXISTS dynamic_research_runs (
    run_id TEXT PRIMARY KEY REFERENCES runs(id),
    model TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    response_id TEXT,
    data_gaps_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dynamic_narratives (
    run_id TEXT NOT NULL REFERENCES runs(id),
    narrative_id TEXT NOT NULL,
    name TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    summary TEXT NOT NULL,
    parent_narrative_ids_json TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    state TEXT NOT NULL,
    score REAL NOT NULL,
    confidence REAL NOT NULL,
    persistence_days INTEGER NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    catalyst TEXT NOT NULL,
    counter_thesis TEXT NOT NULL,
    protocol_ids_json TEXT NOT NULL,
    discovery_lanes_json TEXT NOT NULL,
    rejection_reasons_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    PRIMARY KEY (run_id, narrative_id)
);

CREATE TABLE IF NOT EXISTS dynamic_narrative_memberships (
    run_id TEXT NOT NULL,
    narrative_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    review_json TEXT,
    PRIMARY KEY (run_id, narrative_id, asset_id),
    FOREIGN KEY (run_id, narrative_id)
        REFERENCES dynamic_narratives(run_id, narrative_id)
);

CREATE TABLE IF NOT EXISTS social_window_metrics (
    run_id TEXT NOT NULL REFERENCES runs(id),
    provider TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (run_id, provider, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS forecast_cohorts (
    run_id TEXT NOT NULL REFERENCES runs(id),
    narrative_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    eligible INTEGER NOT NULL,
    decision_state TEXT NOT NULL,
    asset_ids_json TEXT NOT NULL,
    entry_prices_json TEXT NOT NULL,
    btc_entry_price REAL,
    created_at TEXT NOT NULL,
    decision_date TEXT NOT NULL DEFAULT '',
    run_mode TEXT NOT NULL DEFAULT 'live',
    policy_hash TEXT NOT NULL DEFAULT '',
    is_canonical INTEGER NOT NULL DEFAULT 0,
    narrative_gate_passed INTEGER NOT NULL DEFAULT 0,
    paper_trade_eligible INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, narrative_id)
);

CREATE TABLE IF NOT EXISTS forecast_outcomes (
    cohort_run_id TEXT NOT NULL,
    narrative_id TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    observation_run_id TEXT NOT NULL REFERENCES runs(id),
    observed_at TEXT NOT NULL,
    median_return_pct REAL,
    btc_return_pct REAL,
    btc_excess_pct REAL,
    status TEXT NOT NULL DEFAULT 'priced',
    expected_asset_count INTEGER NOT NULL DEFAULT 0,
    priced_asset_count INTEGER NOT NULL DEFAULT 0,
    missing_asset_ids_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (cohort_run_id, narrative_id, horizon_days),
    FOREIGN KEY (cohort_run_id, narrative_id)
        REFERENCES forecast_cohorts(run_id, narrative_id)
);

CREATE TABLE IF NOT EXISTS paper_decisions (
    run_id TEXT PRIMARY KEY REFERENCES runs(id),
    policy_version TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    prospective_days INTEGER NOT NULL,
    qualified_narrative_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    readiness_state TEXT NOT NULL DEFAULT 'BLOCKED_INSUFFICIENT_HISTORY',
    policy_hash TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS dashboard_artifacts (
    run_id TEXT PRIMARY KEY REFERENCES runs(id),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    raw = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        additions = {
            "category_snapshots": {
                "top_asset_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            },
            "narrative_assessments": {
                "is_shortlisted": "INTEGER NOT NULL DEFAULT 0",
                "protocol_ids_json": "TEXT NOT NULL DEFAULT '[]'",
                "metric_coverage_json": "TEXT NOT NULL DEFAULT '{}'",
            },
            "research_sources": {
                "publisher": "TEXT NOT NULL DEFAULT ''",
                "root_url": "TEXT NOT NULL DEFAULT ''",
                "claim": "TEXT NOT NULL DEFAULT ''",
                "is_primary": "INTEGER NOT NULL DEFAULT 0",
            },
            "research_runs": {
                "market_summary": "TEXT NOT NULL DEFAULT ''",
            },
            "forecast_cohorts": {
                "decision_date": "TEXT NOT NULL DEFAULT ''",
                "run_mode": "TEXT NOT NULL DEFAULT 'live'",
                "policy_hash": "TEXT NOT NULL DEFAULT ''",
                "is_canonical": "INTEGER NOT NULL DEFAULT 0",
                "narrative_gate_passed": "INTEGER NOT NULL DEFAULT 0",
                "paper_trade_eligible": "INTEGER NOT NULL DEFAULT 0",
            },
            "forecast_outcomes": {
                "status": "TEXT NOT NULL DEFAULT 'priced'",
                "expected_asset_count": "INTEGER NOT NULL DEFAULT 0",
                "priced_asset_count": "INTEGER NOT NULL DEFAULT 0",
                "missing_asset_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            },
            "paper_decisions": {
                "readiness_state": ("TEXT NOT NULL DEFAULT 'BLOCKED_INSUFFICIENT_HISTORY'"),
                "policy_hash": "TEXT NOT NULL DEFAULT ''",
            },
        }
        for table, columns in additions.items():
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_forecast_cohort
            ON forecast_cohorts (
                strategy_version, run_mode, decision_date, narrative_id
            ) WHERE is_canonical = 1
            """
        )
        connection.execute("PRAGMA user_version = 5")

    def create_run(self, *, as_of: datetime, mode: RunMode, config: dict[str, object]) -> str:
        run_id = f"{as_of.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        config_json = canonical_json(config)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    id, as_of, mode, status, started_at, config_json, config_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    as_of.astimezone(UTC).isoformat(),
                    mode.value,
                    RunStatus.RUNNING.value,
                    datetime.now(UTC).isoformat(),
                    config_json,
                    content_hash(config_json),
                ),
            )
        return run_id

    def finish_run(self, run_id: str, status: RunStatus, error: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE runs SET status = ?, completed_at = ?, error = ? WHERE id = ?
                """,
                (status.value, datetime.now(UTC).isoformat(), error, run_id),
            )

    def store_payload(
        self,
        *,
        run_id: str,
        provider: str,
        endpoint: str,
        observed_at: datetime,
        payload: Any,
    ) -> int:
        payload_json = canonical_json(payload)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO provider_payloads (
                    run_id, provider, endpoint, fetched_at, observed_at,
                    payload_json, payload_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    provider,
                    endpoint,
                    datetime.now(UTC).isoformat(),
                    observed_at.astimezone(UTC).isoformat(),
                    payload_json,
                    content_hash(payload_json),
                ),
            )
            return int(cursor.lastrowid)

    def store_research(
        self,
        *,
        run_id: str,
        result: DailyNarrativeResearch,
        model: str,
        reasoning_effort: str,
        prompt_version: str,
        prompt: str,
        response_id: str | None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO research_runs (
                    run_id, model, reasoning_effort, prompt_version, prompt_hash,
                    response_id, market_regime, data_gaps_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    model,
                    reasoning_effort,
                    prompt_version,
                    content_hash(prompt),
                    response_id,
                    result.market_regime,
                    canonical_json(result.data_gaps),
                ),
            )
            for narrative in result.narratives:
                connection.execute(
                    """
                    INSERT INTO narrative_assessments (
                        run_id, narrative_id, name, summary, lifecycle,
                        opportunity_score, confidence_score, is_shortlisted, signals_json,
                        protocol_ids_json, metric_coverage_json, thesis, counter_thesis
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        narrative.narrative_id,
                        narrative.name,
                        narrative.summary,
                        narrative.lifecycle.value,
                        narrative.opportunity_score,
                        narrative.confidence_score,
                        int(narrative.is_shortlisted),
                        narrative.signals.model_dump_json(),
                        canonical_json(narrative.protocol_ids),
                        canonical_json(narrative.metric_coverage),
                        narrative.thesis,
                        narrative.counter_thesis,
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO narrative_memberships (
                        run_id, narrative_id, asset_id, confidence
                    ) VALUES (?, ?, ?, ?)
                    """,
                    [
                        (run_id, narrative.narrative_id, asset_id, 1.0)
                        for asset_id in narrative.constituent_ids
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO research_sources (
                        run_id, narrative_id, title, url, published_at,
                        source_type, publisher, root_url, claim, is_primary,
                        supports, credibility
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            narrative.narrative_id,
                            source.title,
                            str(source.url),
                            source.published_at.isoformat() if source.published_at else None,
                            source.source_type,
                            source.publisher,
                            source.root_url,
                            source.claim,
                            int(source.is_primary),
                            int(source.supports),
                            source.credibility,
                        )
                        for source in narrative.sources
                    ],
                )

    def store_landscape_research(
        self,
        *,
        run_id: str,
        landscape: LandscapeSnapshot,
        result: DailyLandscapeResearch,
        model: str,
        reasoning_effort: str,
        prompt_version: str,
        prompt: str,
        response_id: str | None,
    ) -> None:
        valid_narrative_ids = {item.narrative_id for item in landscape.narratives}
        updates = {
            item.narrative_id: item
            for item in result.narrative_updates
            if item.narrative_id in valid_narrative_ids
        }
        reviews = {(item.narrative_id, item.project_id): item for item in result.project_reviews}
        gaps = list(dict.fromkeys([*landscape.data_gaps, *result.data_gaps]))
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO research_runs (
                    run_id, model, reasoning_effort, prompt_version, prompt_hash,
                    response_id, market_regime, market_summary, data_gaps_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    model,
                    reasoning_effort,
                    prompt_version,
                    content_hash(prompt),
                    response_id,
                    landscape.market_regime,
                    result.market_summary,
                    canonical_json(gaps),
                ),
            )
            connection.executemany(
                """
                INSERT INTO landscape_narratives (
                    run_id, narrative_id, name, description, kpi_profile, rank,
                    state, is_focus, score, confidence, metrics_json, update_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item.narrative_id,
                        item.name,
                        item.description,
                        item.kpi_profile,
                        item.rank,
                        item.state.value,
                        int(item.is_focus),
                        item.score,
                        item.confidence,
                        canonical_json(item.metrics.model_dump(mode="json")),
                        canonical_json(updates[item.narrative_id].model_dump(mode="json"))
                        if item.narrative_id in updates
                        else None,
                    )
                    for item in landscape.narratives
                ],
            )
            connection.executemany(
                """
                INSERT INTO landscape_projects (
                    run_id, narrative_id, project_id, name, asset_id, rank,
                    score, eligible, metrics_json, selection_notes_json, review_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item.narrative_id,
                        item.project_id,
                        item.name,
                        item.asset_id,
                        item.rank,
                        item.score,
                        int(item.eligible),
                        canonical_json(item.metrics.model_dump(mode="json")),
                        canonical_json(item.selection_notes),
                        canonical_json(
                            reviews[(item.narrative_id, item.project_id)].model_dump(mode="json")
                        )
                        if (item.narrative_id, item.project_id) in reviews
                        else None,
                    )
                    for item in landscape.projects
                ],
            )
            connection.executemany(
                """
                INSERT INTO market_events (
                    run_id, event_index, title, why_it_matters, direction,
                    horizon, narrative_ids_json, sources_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        index,
                        item.title,
                        item.why_it_matters,
                        item.direction,
                        item.horizon,
                        canonical_json(item.narrative_ids),
                        canonical_json([source.model_dump(mode="json") for source in item.sources]),
                    )
                    for index, item in enumerate(result.key_events, 1)
                ],
            )

    def dynamic_history(self, prompt_version: str | None = None) -> list[dict[str, Any]]:
        """Return prior successful dynamic observations, newest first, for identity resolution."""
        with self.connect() as connection:
            where_version = " AND dr.prompt_version = ?" if prompt_version else ""
            parameters = (prompt_version,) if prompt_version else ()
            rows = connection.execute(
                f"""
                SELECT d.*, r.as_of AS observation_as_of, r.mode
                FROM dynamic_narratives d
                JOIN runs r ON r.id = d.run_id
                JOIN dynamic_research_runs dr ON dr.run_id = d.run_id
                WHERE r.status = 'succeeded'
                {where_version}
                ORDER BY r.started_at DESC
                """,
                parameters,
            ).fetchall()
            memberships = connection.execute(
                f"""
                SELECT m.run_id, m.narrative_id, m.asset_id
                FROM dynamic_narrative_memberships m
                JOIN runs r ON r.id = m.run_id
                JOIN dynamic_research_runs dr ON dr.run_id = m.run_id
                WHERE r.status = 'succeeded'
                {where_version}
                """,
                parameters,
            ).fetchall()
        members: dict[tuple[str, str], list[str]] = {}
        for row in memberships:
            members.setdefault((row["run_id"], row["narrative_id"]), []).append(row["asset_id"])
        result = []
        seen_daily: set[tuple[str, str, str]] = set()
        for raw in rows:
            row = dict(raw)
            daily_key = (
                row["mode"],
                row["observation_as_of"][:10],
                row["narrative_id"],
            )
            if daily_key in seen_daily:
                continue
            seen_daily.add(daily_key)
            row["aliases"] = json.loads(row["aliases_json"])
            row["constituent_ids"] = members.get((row["run_id"], row["narrative_id"]), [])
            row["parent_narrative_ids"] = json.loads(row["parent_narrative_ids_json"])
            row["protocol_ids"] = json.loads(row["protocol_ids_json"])
            row["discovery_lanes"] = json.loads(row["discovery_lanes_json"])
            row["rejection_reasons"] = json.loads(row["rejection_reasons_json"])
            row["metrics"] = json.loads(row["metrics_json"])
            row["sources"] = json.loads(row["sources_json"])
            row["as_of"] = row["last_seen_at"]
            result.append(row)
        return result

    def store_dynamic_research(
        self,
        *,
        run_id: str,
        radar: DynamicRadarSnapshot,
        result: DailyLandscapeResearch,
        social_metrics: list[SocialWindowMetrics],
        model: str,
        reasoning_effort: str,
        prompt_version: str,
        prompt: str,
        response_id: str | None,
        policy: StrategyPolicy,
        run_mode: RunMode,
    ) -> None:
        dynamic_ids = {item.narrative_id for item in radar.narratives}
        reviews = {
            (item.narrative_id, item.project_id): item
            for item in result.project_reviews
            if item.narrative_id in dynamic_ids
        }
        strategy_hash = content_hash(
            {"policy_hash": policy.policy_hash, "dynamic_prompt_version": prompt_version}
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO dynamic_research_runs (
                    run_id, model, reasoning_effort, prompt_version, prompt_hash,
                    response_id, data_gaps_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    model,
                    reasoning_effort,
                    prompt_version,
                    content_hash(prompt),
                    response_id,
                    canonical_json(radar.data_gaps),
                ),
            )
            connection.executemany(
                """
                INSERT INTO dynamic_narratives (
                    run_id, narrative_id, name, mechanism, summary,
                    parent_narrative_ids_json, aliases_json, state, score,
                    confidence, persistence_days, first_seen_at, last_seen_at,
                    catalyst, counter_thesis, protocol_ids_json,
                    discovery_lanes_json, rejection_reasons_json, metrics_json,
                    sources_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item.narrative_id,
                        item.name,
                        item.mechanism,
                        item.summary,
                        canonical_json(item.parent_narrative_ids),
                        canonical_json(item.aliases),
                        item.state.value,
                        item.score,
                        item.confidence,
                        item.persistence_days,
                        item.first_seen_at.astimezone(UTC).isoformat(),
                        item.last_seen_at.astimezone(UTC).isoformat(),
                        item.catalyst,
                        item.counter_thesis,
                        canonical_json(item.protocol_ids),
                        canonical_json(item.discovery_lanes),
                        canonical_json(item.rejection_reasons),
                        canonical_json(item.metrics.model_dump(mode="json")),
                        canonical_json([source.model_dump(mode="json") for source in item.sources]),
                    )
                    for item in radar.narratives
                ],
            )
            connection.executemany(
                """
                INSERT INTO dynamic_narrative_memberships (
                    run_id, narrative_id, asset_id, review_json
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item.narrative_id,
                        asset_id,
                        canonical_json(
                            reviews[(item.narrative_id, asset_id)].model_dump(mode="json")
                        )
                        if (item.narrative_id, asset_id) in reviews
                        else None,
                    )
                    for item in radar.narratives
                    for asset_id in item.constituent_ids
                ],
            )
            connection.executemany(
                """
                INSERT INTO social_window_metrics (
                    run_id, provider, target_type, target_id, metrics_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item.provider,
                        item.target_type,
                        item.target_id,
                        canonical_json(item.model_dump(mode="json")),
                    )
                    for item in social_metrics
                ],
            )
            prior_dates = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT DISTINCT decision_date
                    FROM forecast_cohorts
                    WHERE is_canonical = 1 AND run_mode = 'live' AND policy_hash = ?
                    """,
                    (strategy_hash,),
                )
            }
            if run_mode is RunMode.LIVE:
                prior_dates.add(radar.as_of.date().isoformat())
            history_days = 0
            cursor = radar.as_of.date()
            while cursor.isoformat() in prior_dates:
                history_days += 1
                cursor = date.fromordinal(cursor.toordinal() - 1)
            connection.executemany(
                """
                INSERT INTO forecast_cohorts (
                    run_id, narrative_id, strategy_version, eligible,
                    decision_state, asset_ids_json, entry_prices_json,
                    btc_entry_price, created_at, decision_date, run_mode,
                    policy_hash, is_canonical, narrative_gate_passed,
                    paper_trade_eligible
                ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0)
                """,
                [
                    (
                        run_id,
                        item.narrative_id,
                        policy.version,
                        (
                            "research_qualified_after_burn_in"
                            if history_days >= policy.minimum_prospective_days
                            and item.state.value in policy.dynamic_entry_states
                            else (
                                "insufficient_history"
                                if history_days < policy.minimum_prospective_days
                                else "research_only"
                            )
                        ),
                        canonical_json(item.constituent_ids),
                        canonical_json(
                            self._reference_prices(connection, run_id, item.constituent_ids)
                        ),
                        self._reference_prices(connection, run_id, ["bitcoin"]).get("bitcoin"),
                        radar.as_of.astimezone(UTC).isoformat(),
                        radar.as_of.date().isoformat(),
                        run_mode.value,
                        strategy_hash,
                        int(
                            history_days >= policy.minimum_prospective_days
                            and item.state.value in policy.dynamic_entry_states
                        ),
                    )
                    for item in radar.narratives
                ],
            )
            qualified = sum(
                item.state.value in policy.dynamic_entry_states for item in radar.narratives
            )
            if run_mode is not RunMode.LIVE:
                readiness = "BLOCKED_OFFLINE_OBSERVATION"
                reason = "Offline observations do not count toward the live prospective burn-in."
            elif history_days < policy.minimum_prospective_days:
                readiness = "BLOCKED_INSUFFICIENT_HISTORY"
                reason = (
                    f"Live canonical history is {history_days}/"
                    f"{policy.minimum_prospective_days} consecutive days."
                )
            elif qualified:
                readiness = "BLOCKED_INVESTABILITY_NOT_IMPLEMENTED"
                reason = (
                    "A narrative is research-qualified, but venue, cost, unlock, contract, "
                    "and security gates are not implemented."
                )
            else:
                readiness = "NO_RESEARCH_QUALIFIED_NARRATIVE"
                reason = "No dynamic narrative passed the research-promotion gate."
            connection.execute(
                """
                INSERT INTO paper_decisions (
                    run_id, policy_version, action, reason, prospective_days,
                    qualified_narrative_count, created_at, readiness_state,
                    policy_hash
                ) VALUES (?, ?, 'NO_ACTION', ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    policy.version,
                    reason,
                    history_days,
                    qualified,
                    datetime.now(UTC).isoformat(),
                    readiness,
                    strategy_hash,
                ),
            )

    @staticmethod
    def _reference_prices(
        connection: sqlite3.Connection,
        run_id: str,
        asset_ids: list[str],
    ) -> dict[str, float]:
        if not asset_ids:
            return {}
        placeholders = ",".join("?" for _ in asset_ids)
        rows = connection.execute(
            f"""
            SELECT asset_id, price_usd FROM market_snapshots
            WHERE run_id = ? AND asset_id IN ({placeholders}) AND price_usd IS NOT NULL
            """,
            (run_id, *asset_ids),
        ).fetchall()
        return {row["asset_id"]: float(row["price_usd"]) for row in rows}

    def finalize_canonical_cohorts(self, run_id: str) -> None:
        """Select at most one successful cohort per policy, mode, date, and narrative."""
        with self.connect() as connection:
            run = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None or run["status"] != RunStatus.SUCCEEDED.value:
                raise ValueError("Canonical cohorts require a succeeded run.")
            self._finalize_canonical_cohorts(connection, run_id)

    @staticmethod
    def _finalize_canonical_cohorts(
        connection: sqlite3.Connection,
        run_id: str,
    ) -> None:
        connection.execute(
            """
            UPDATE forecast_cohorts AS current
            SET is_canonical = 1
            WHERE current.run_id = ?
              AND NOT EXISTS (
                SELECT 1
                FROM forecast_cohorts prior
                JOIN runs prior_run ON prior_run.id = prior.run_id
                WHERE prior.is_canonical = 1
                  AND prior_run.status = 'succeeded'
                  AND prior.strategy_version = current.strategy_version
                  AND prior.run_mode = current.run_mode
                  AND prior.decision_date = current.decision_date
                  AND prior.narrative_id = current.narrative_id
              )
            """,
            (run_id,),
        )

    def record_forecast_outcomes(
        self,
        *,
        observation_run_id: str,
        observed_at: datetime,
        assets: list[MarketAsset],
    ) -> None:
        current_prices = {
            item.asset_id: float(item.price_usd) for item in assets if item.price_usd is not None
        }
        with self.connect() as connection:
            observation = connection.execute(
                "SELECT status FROM runs WHERE id = ?", (observation_run_id,)
            ).fetchone()
            if observation is None or observation["status"] != RunStatus.SUCCEEDED.value:
                raise ValueError("Forecast outcomes require a succeeded observation run.")
            cohorts = connection.execute(
                """
                SELECT c.*, r.as_of
                FROM forecast_cohorts c JOIN runs r ON r.id = c.run_id
                WHERE c.is_canonical = 1 AND r.status = 'succeeded'
                ORDER BY r.as_of
                """
            ).fetchall()
            for cohort in cohorts:
                created_at = datetime.fromisoformat(cohort["as_of"].replace("Z", "+00:00"))
                age_days = (observed_at - created_at).total_seconds() / 86_400
                reference_prices = json.loads(cohort["entry_prices_json"])
                expected_ids = json.loads(cohort["asset_ids_json"])
                for horizon in (7, 28):
                    if age_days < horizon:
                        continue
                    existing = connection.execute(
                        """
                        SELECT 1 FROM forecast_outcomes
                        WHERE cohort_run_id = ? AND narrative_id = ? AND horizon_days = ?
                        """,
                        (cohort["run_id"], cohort["narrative_id"], horizon),
                    ).fetchone()
                    if existing:
                        continue
                    missing_ids = [
                        asset_id
                        for asset_id in expected_ids
                        if asset_id not in current_prices or asset_id not in reference_prices
                    ]
                    if missing_ids and age_days <= horizon + 1.5:
                        continue
                    status = "priced"
                    if age_days > horizon + 1.5:
                        status = "missed_window"
                    elif missing_ids:
                        status = "incomplete_coverage"
                    returns = [
                        (current_prices[asset_id] / float(reference_prices[asset_id]) - 1) * 100
                        for asset_id in expected_ids
                        if asset_id in current_prices
                        and asset_id in reference_prices
                        and float(reference_prices[asset_id]) > 0
                    ]
                    full_coverage = len(returns) == len(expected_ids) and bool(expected_ids)
                    median_return = (
                        round(float(median(returns)), 2)
                        if status == "priced" and full_coverage
                        else None
                    )
                    btc_return = None
                    if (
                        status == "priced"
                        and cohort["btc_entry_price"]
                        and current_prices.get("bitcoin")
                    ):
                        btc_return = round(
                            (current_prices["bitcoin"] / float(cohort["btc_entry_price"]) - 1)
                            * 100,
                            2,
                        )
                    excess = (
                        round(median_return - btc_return, 2)
                        if median_return is not None and btc_return is not None
                        else None
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO forecast_outcomes (
                            cohort_run_id, narrative_id, horizon_days,
                            observation_run_id, observed_at, median_return_pct,
                            btc_return_pct, btc_excess_pct, status,
                            expected_asset_count, priced_asset_count,
                            missing_asset_ids_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cohort["run_id"],
                            cohort["narrative_id"],
                            horizon,
                            observation_run_id,
                            observed_at.astimezone(UTC).isoformat(),
                            median_return,
                            btc_return,
                            excess,
                            status,
                            len(expected_ids),
                            len(returns),
                            canonical_json(missing_ids),
                        ),
                    )
            self._finalize_canonical_cohorts(connection, observation_run_id)

    def store_market_assets(self, run_id: str, assets: list[MarketAsset]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO market_snapshots (
                    run_id, asset_id, symbol, name, observed_at, price_usd,
                    market_cap_usd, volume_24h_usd, change_24h_pct,
                    change_7d_pct, change_30d_pct, primary_sector
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        asset.asset_id,
                        asset.symbol,
                        asset.name,
                        asset.observed_at.astimezone(UTC).isoformat(),
                        asset.price_usd,
                        asset.market_cap_usd,
                        asset.volume_24h_usd,
                        asset.change_24h_pct,
                        asset.change_7d_pct,
                        asset.change_30d_pct,
                        asset.primary_sector,
                    )
                    for asset in assets
                ],
            )

    def store_categories(self, run_id: str, categories: list[CategoryMarket]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO category_snapshots (
                    run_id, category_id, name, observed_at, market_cap_usd,
                    volume_24h_usd, change_24h_pct, top_asset_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        category.category_id,
                        category.name,
                        category.observed_at.astimezone(UTC).isoformat(),
                        category.market_cap_usd,
                        category.volume_24h_usd,
                        category.change_24h_pct,
                        canonical_json(category.top_asset_ids),
                    )
                    for category in categories
                ],
            )

    def store_protocols(self, run_id: str, protocols: list[ProtocolMetric]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO protocol_snapshots (
                    run_id, protocol_id, name, category, observed_at, tvl_usd,
                    change_1d_pct, change_7d_pct, change_30d_pct, chains_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        protocol.protocol_id,
                        protocol.name,
                        protocol.category,
                        protocol.observed_at.astimezone(UTC).isoformat(),
                        protocol.tvl_usd,
                        protocol.change_1d_pct,
                        protocol.change_7d_pct,
                        protocol.change_30d_pct,
                        canonical_json(protocol.chains),
                    )
                    for protocol in protocols
                ],
            )

    def store_protocol_activity(self, run_id: str, metrics: list[ProtocolActivityMetric]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO protocol_activity_snapshots (
                    run_id, protocol_id, name, category, metric_type, observed_at,
                    total_24h_usd, total_7d_usd, total_30d_usd, growth_1d_pct,
                    growth_7d_pct, growth_30d_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        item.protocol_id,
                        item.name,
                        item.category,
                        item.metric_type.value,
                        item.observed_at.astimezone(UTC).isoformat(),
                        item.total_24h_usd,
                        item.total_7d_usd,
                        item.total_30d_usd,
                        item.growth_1d_pct,
                        item.growth_7d_pct,
                        item.growth_30d_pct,
                    )
                    for item in metrics
                ],
            )

    def store_trending_assets(self, run_id: str, assets: list[TrendingAsset]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO trending_snapshots (
                    run_id, asset_id, symbol, name, observed_at, search_rank, market_cap_rank
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        asset.asset_id,
                        asset.symbol,
                        asset.name,
                        asset.observed_at.astimezone(UTC).isoformat(),
                        asset.search_rank,
                        asset.market_cap_rank,
                    )
                    for asset in assets
                ],
            )

    def store_market_bundle(
        self,
        *,
        run_id: str,
        assets: list[MarketAsset],
        categories: list[CategoryMarket],
        protocols: list[ProtocolMetric],
        protocol_activity: list[ProtocolActivityMetric] | None = None,
        trending_assets: list[TrendingAsset] | None = None,
    ) -> None:
        self.store_market_assets(run_id, assets)
        self.store_categories(run_id, categories)
        self.store_protocols(run_id, protocols)
        self.store_protocol_activity(run_id, protocol_activity or [])
        self.store_trending_assets(run_id, trending_assets or [])

    def store_dashboard_artifact(self, run_id: str, path: Path, sha256: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO dashboard_artifacts (run_id, path, sha256, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, str(path), sha256, datetime.now(UTC).isoformat()),
            )

    def dashboard_data(self, run_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            run = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            research = connection.execute(
                "SELECT * FROM research_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None or research is None:
                raise KeyError(f"No complete research run found for {run_id}")
            assets = connection.execute(
                """
                SELECT * FROM market_snapshots WHERE run_id = ?
                ORDER BY market_cap_usd DESC
                """,
                (run_id,),
            ).fetchall()
            categories = connection.execute(
                """
                SELECT * FROM category_snapshots WHERE run_id = ?
                ORDER BY change_24h_pct DESC
                """,
                (run_id,),
            ).fetchall()
            protocols = connection.execute(
                """
                SELECT * FROM protocol_snapshots WHERE run_id = ?
                ORDER BY change_7d_pct DESC
                """,
                (run_id,),
            ).fetchall()
            narratives = connection.execute(
                """
                SELECT * FROM narrative_assessments WHERE run_id = ?
                ORDER BY opportunity_score DESC, confidence_score DESC
                """,
                (run_id,),
            ).fetchall()
            memberships = connection.execute(
                """
                SELECT nm.narrative_id, ms.*
                FROM narrative_memberships nm
                JOIN market_snapshots ms
                  ON ms.run_id = nm.run_id AND ms.asset_id = nm.asset_id
                WHERE nm.run_id = ?
                ORDER BY ms.market_cap_usd DESC
                """,
                (run_id,),
            ).fetchall()
            sources = connection.execute(
                """
                SELECT * FROM research_sources WHERE run_id = ? ORDER BY credibility DESC
                """,
                (run_id,),
            ).fetchall()
            trending = connection.execute(
                """
                SELECT * FROM trending_snapshots WHERE run_id = ? ORDER BY search_rank
                """,
                (run_id,),
            ).fetchall()
            run_history = connection.execute(
                """
                SELECT id, as_of, mode, status, started_at, completed_at, error
                FROM runs ORDER BY started_at DESC LIMIT 8
                """
            ).fetchall()

        return {
            "run": dict(run),
            "research": dict(research),
            "assets": [dict(row) for row in assets],
            "categories": [dict(row) for row in categories],
            "protocols": [dict(row) for row in protocols],
            "narratives": [dict(row) for row in narratives],
            "memberships": [dict(row) for row in memberships],
            "sources": [dict(row) for row in sources],
            "trending": [dict(row) for row in trending],
            "run_history": [dict(row) for row in run_history],
        }

    def landscape_dashboard_data(self, run_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            run = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            research = connection.execute(
                "SELECT * FROM research_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None or research is None:
                raise KeyError(f"No complete landscape run found for {run_id}")
            narratives = connection.execute(
                """
                SELECT * FROM landscape_narratives WHERE run_id = ? ORDER BY rank
                """,
                (run_id,),
            ).fetchall()
            projects = connection.execute(
                """
                SELECT * FROM landscape_projects
                WHERE run_id = ? ORDER BY narrative_id, rank
                """,
                (run_id,),
            ).fetchall()
            events = connection.execute(
                "SELECT * FROM market_events WHERE run_id = ? ORDER BY event_index",
                (run_id,),
            ).fetchall()
            assets = connection.execute(
                "SELECT * FROM market_snapshots WHERE run_id = ? ORDER BY market_cap_usd DESC",
                (run_id,),
            ).fetchall()
            trending = connection.execute(
                "SELECT * FROM trending_snapshots WHERE run_id = ? ORDER BY search_rank",
                (run_id,),
            ).fetchall()
            activity_count = connection.execute(
                "SELECT COUNT(*) FROM protocol_activity_snapshots WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            dynamic_narratives = connection.execute(
                "SELECT * FROM dynamic_narratives WHERE run_id = ? ORDER BY score DESC",
                (run_id,),
            ).fetchall()
            dynamic_research = connection.execute(
                "SELECT * FROM dynamic_research_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            dynamic_memberships = connection.execute(
                """
                SELECT m.narrative_id, m.asset_id, m.review_json,
                       s.name, s.symbol, s.price_usd, s.market_cap_usd,
                       s.volume_24h_usd, s.change_7d_pct, s.change_30d_pct
                FROM dynamic_narrative_memberships m
                LEFT JOIN market_snapshots s
                  ON s.run_id = m.run_id AND s.asset_id = m.asset_id
                WHERE m.run_id = ?
                ORDER BY m.narrative_id, s.market_cap_usd DESC
                """,
                (run_id,),
            ).fetchall()
            social = connection.execute(
                "SELECT * FROM social_window_metrics WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            paper_decision = connection.execute(
                "SELECT * FROM paper_decisions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            cohort_count = connection.execute(
                "SELECT COUNT(*) FROM forecast_cohorts WHERE is_canonical = 1",
            ).fetchone()[0]
            outcome_count = connection.execute(
                "SELECT COUNT(*) FROM forecast_outcomes WHERE status = 'priced'",
            ).fetchone()[0]
            run_history = connection.execute(
                """
                SELECT id, as_of, mode, status, started_at, completed_at, error
                FROM runs ORDER BY started_at DESC LIMIT 8
                """
            ).fetchall()
            previous = connection.execute(
                """
                SELECT r.id
                FROM runs r
                JOIN landscape_narratives n ON n.run_id = r.id
                WHERE substr(r.as_of, 1, 10) < substr(?, 1, 10)
                  AND r.status = 'succeeded' AND r.mode = ?
                GROUP BY r.id
                ORDER BY r.started_at DESC
                LIMIT 1
                """,
                (run["as_of"], run["mode"]),
            ).fetchone()
            previous_narratives = []
            previous_projects = []
            if previous:
                previous_narratives = connection.execute(
                    "SELECT narrative_id, score, state FROM landscape_narratives WHERE run_id = ?",
                    (previous["id"],),
                ).fetchall()
                previous_projects = connection.execute(
                    """
                    SELECT narrative_id, project_id, score
                    FROM landscape_projects WHERE run_id = ?
                    """,
                    (previous["id"],),
                ).fetchall()

        return {
            "run": dict(run),
            "research": dict(research),
            "narratives": [dict(row) for row in narratives],
            "projects": [dict(row) for row in projects],
            "events": [dict(row) for row in events],
            "assets": [dict(row) for row in assets],
            "trending": [dict(row) for row in trending],
            "protocol_activity_count": int(activity_count),
            "dynamic_narratives": [dict(row) for row in dynamic_narratives],
            "dynamic_research": dict(dynamic_research) if dynamic_research else None,
            "dynamic_memberships": [dict(row) for row in dynamic_memberships],
            "social_metrics": [dict(row) for row in social],
            "paper_decision": dict(paper_decision) if paper_decision else None,
            "forecast_cohort_count": int(cohort_count),
            "forecast_outcome_count": int(outcome_count),
            "run_history": [dict(row) for row in run_history],
            "previous_run_id": previous["id"] if previous else None,
            "previous_narratives": [dict(row) for row in previous_narratives],
            "previous_projects": [dict(row) for row in previous_projects],
        }
