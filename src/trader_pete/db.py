from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from trader_pete.config import StrategyPolicy
from trader_pete.models import (
    CategoryMarket,
    DailyDynamicNarrativeDraft,
    DailyLandscapeResearch,
    DailyNarrativeResearch,
    DynamicRadarSnapshot,
    InvestabilityDataBundle,
    LandscapeSnapshot,
    MarketAsset,
    PaperEvaluation,
    ProtocolActivityMetric,
    ProtocolMetric,
    RunMode,
    RunStatus,
    SocialWindowMetrics,
    TrendingAsset,
)

CANONICAL_LEASE_TTL = timedelta(hours=2)

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
    error TEXT,
    workflow_complete INTEGER NOT NULL DEFAULT 0
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
    request_params_hash TEXT,
    response_received_at TEXT,
    http_status INTEGER,
    content_type TEXT,
    request_manifest_json TEXT NOT NULL DEFAULT '[]',
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
    ,prompt_text TEXT NOT NULL DEFAULT ''
    ,normalized_output_json TEXT NOT NULL DEFAULT '{}'
    ,source_manifest_json TEXT NOT NULL DEFAULT '[]'
    ,packet_hash TEXT NOT NULL DEFAULT ''
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
    event_subject TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    event_at TEXT,
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
    data_gaps_json TEXT NOT NULL,
    prompt_text TEXT NOT NULL DEFAULT '',
    normalized_output_json TEXT NOT NULL DEFAULT '{}',
    source_manifest_json TEXT NOT NULL DEFAULT '[]',
    validated_draft_json TEXT NOT NULL DEFAULT '{}',
    packet_hash TEXT NOT NULL DEFAULT ''
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

CREATE TABLE IF NOT EXISTS canonical_runs (
    policy_hash TEXT NOT NULL,
    run_mode TEXT NOT NULL,
    decision_date TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES runs(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (policy_hash, run_mode, decision_date)
);

CREATE TABLE IF NOT EXISTS strategy_policy_versions (
    policy_hash TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_portfolios (
    id TEXT PRIMARY KEY,
    policy_hash TEXT NOT NULL REFERENCES strategy_policy_versions(policy_hash),
    initial_cash_usd REAL NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE (policy_hash)
);

CREATE TABLE IF NOT EXISTS portfolio_cash_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id TEXT NOT NULL REFERENCES paper_portfolios(id),
    event_type TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    reference_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (portfolio_id, reference_type, reference_id, event_type)
);

CREATE TABLE IF NOT EXISTS venue_quote_snapshots (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    asset_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    venue TEXT NOT NULL,
    pair TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    quote_json TEXT NOT NULL,
    quote_hash TEXT NOT NULL,
    UNIQUE (run_id, provider, asset_id, pair)
);

CREATE TABLE IF NOT EXISTS paper_candidate_assessments (
    run_id TEXT NOT NULL REFERENCES runs(id),
    narrative_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    state TEXT NOT NULL,
    research_priority REAL NOT NULL,
    assessment_json TEXT NOT NULL,
    assessment_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, narrative_id, asset_id)
);

CREATE TABLE IF NOT EXISTS trade_proposals (
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES paper_portfolios(id),
    source_run_id TEXT NOT NULL REFERENCES runs(id),
    narrative_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    intent TEXT NOT NULL CHECK (intent IN ('entry', 'exit')),
    venue_quote_id TEXT NOT NULL REFERENCES venue_quote_snapshots(id),
    venue TEXT NOT NULL,
    pair TEXT NOT NULL,
    chain_id TEXT,
    contract_address TEXT,
    proposed_notional_usd REAL NOT NULL,
    proposed_quantity REAL NOT NULL,
    decision_price REAL NOT NULL,
    maximum_entry_price REAL,
    stop_price REAL,
    maximum_initial_loss_usd REAL,
    policy_hash TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approval_deadline TEXT NOT NULL,
    planned_exit_at TEXT NOT NULL,
    UNIQUE (source_run_id, asset_id, intent)
);

CREATE TABLE IF NOT EXISTS proposal_events (
    proposal_id TEXT NOT NULL REFERENCES trade_proposals(id),
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    proposal_hash TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    quote_id TEXT REFERENCES venue_quote_snapshots(id),
    PRIMARY KEY (proposal_id, sequence)
);

CREATE TABLE IF NOT EXISTS paper_fills (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES trade_proposals(id),
    fill_run_id TEXT NOT NULL REFERENCES runs(id),
    quote_id TEXT NOT NULL REFERENCES venue_quote_snapshots(id),
    side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    execution_price REAL NOT NULL,
    gross_notional_usd REAL NOT NULL,
    fee_usd REAL NOT NULL,
    total_cost_bps REAL NOT NULL,
    executed_at TEXT NOT NULL,
    fill_model_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    id TEXT PRIMARY KEY,
    portfolio_id TEXT NOT NULL REFERENCES paper_portfolios(id),
    opening_fill_id TEXT NOT NULL UNIQUE REFERENCES paper_fills(id),
    narrative_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    quantity REAL NOT NULL,
    opened_at TEXT NOT NULL,
    planned_exit_at TEXT NOT NULL,
    initial_stop_price REAL NOT NULL
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
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        run_columns_before = {row["name"] for row in connection.execute("PRAGMA table_info(runs)")}
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
                "prompt_text": "TEXT NOT NULL DEFAULT ''",
                "normalized_output_json": "TEXT NOT NULL DEFAULT '{}'",
                "source_manifest_json": "TEXT NOT NULL DEFAULT '[]'",
                "packet_hash": "TEXT NOT NULL DEFAULT ''",
            },
            "dynamic_research_runs": {
                "prompt_text": "TEXT NOT NULL DEFAULT ''",
                "normalized_output_json": "TEXT NOT NULL DEFAULT '{}'",
                "source_manifest_json": "TEXT NOT NULL DEFAULT '[]'",
                "validated_draft_json": "TEXT NOT NULL DEFAULT '{}'",
                "packet_hash": "TEXT NOT NULL DEFAULT ''",
            },
            "provider_payloads": {
                "request_params_hash": "TEXT",
                "response_received_at": "TEXT",
                "http_status": "INTEGER",
                "content_type": "TEXT",
                "request_manifest_json": "TEXT NOT NULL DEFAULT '[]'",
            },
            "market_events": {
                "event_subject": "TEXT NOT NULL DEFAULT ''",
                "event_type": "TEXT NOT NULL DEFAULT ''",
                "event_at": "TEXT",
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
            "runs": {
                "workflow_complete": "INTEGER NOT NULL DEFAULT 0",
            },
        }
        for table, columns in additions.items():
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        connection.execute("DROP INDEX IF EXISTS uq_canonical_forecast_cohort")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_forecast_cohort
            ON forecast_cohorts (
                policy_hash, run_mode, decision_date, narrative_id
            ) WHERE is_canonical = 1
            """
        )
        if "workflow_complete" not in run_columns_before:
            connection.execute(
                """
                UPDATE runs SET workflow_complete = 1
                WHERE status = 'succeeded' AND (
                    (
                        EXISTS (SELECT 1 FROM paper_decisions d WHERE d.run_id = runs.id)
                        AND EXISTS (SELECT 1 FROM dashboard_artifacts a WHERE a.run_id = runs.id)
                    )
                    OR config_json LIKE '%paper_quote_refresh%'
                )
                """
            )
        if user_version < 9:
            connection.execute(
                """
                UPDATE runs SET workflow_complete = CASE
                    WHEN status = 'succeeded' AND (
                        EXISTS (SELECT 1 FROM paper_decisions d WHERE d.run_id = runs.id)
                        OR config_json LIKE '%paper_quote_refresh%'
                    ) THEN 1 ELSE 0 END
                """
            )
        if user_version < 10:
            connection.execute(
                """
                UPDATE market_events
                SET event_subject = COALESCE((
                        SELECT json_extract(
                            r.normalized_output_json,
                            '$.key_events[' || (market_events.event_index - 1) || '].event_subject'
                        ) FROM research_runs r WHERE r.run_id = market_events.run_id
                    ), ''),
                    event_type = COALESCE((
                        SELECT json_extract(
                            r.normalized_output_json,
                            '$.key_events[' || (market_events.event_index - 1) || '].event_type'
                        ) FROM research_runs r WHERE r.run_id = market_events.run_id
                    ), ''),
                    event_at = (
                        SELECT json_extract(
                            r.normalized_output_json,
                            '$.key_events[' || (market_events.event_index - 1) || '].event_at'
                        ) FROM research_runs r WHERE r.run_id = market_events.run_id
                    )
                """
            )
        connection.execute("PRAGMA user_version = 10")

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
            cursor = connection.execute(
                """
                UPDATE runs SET status = ?, completed_at = ?, error = ?, workflow_complete = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    status.value,
                    datetime.now(UTC).isoformat(),
                    error,
                    int(status is RunStatus.SUCCEEDED),
                    run_id,
                ),
            )
            if cursor.rowcount == 0:
                current = connection.execute(
                    "SELECT status FROM runs WHERE id = ?", (run_id,)
                ).fetchone()
                if current is None:
                    raise KeyError(f"Unknown run: {run_id}")
                if current["status"] != status.value:
                    raise ValueError(
                        f"Run {run_id} is terminal ({current['status']}); it cannot become "
                        f"{status.value}."
                    )
            if status is RunStatus.FAILED:
                self._invalidate_incomplete_run(connection, run_id, error or "Run failed.")

    def complete_daily_run(self, run_id: str) -> None:
        """Atomically terminalize a daily run only after its decision ledger exists."""
        with self.connect() as connection:
            run = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            decision = connection.execute(
                "SELECT 1 FROM paper_decisions WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None or run["status"] != RunStatus.RUNNING.value:
                raise ValueError("Daily completion requires a running run.")
            if decision is None:
                raise ValueError("Daily completion requires a persisted paper decision.")
            cohort = connection.execute(
                "SELECT policy_hash, run_mode, decision_date FROM forecast_cohorts "
                "WHERE run_id = ? LIMIT 1",
                (run_id,),
            ).fetchone()
            if cohort:
                selected = connection.execute(
                    """
                    SELECT selected.run_id, owner.status, owner.workflow_complete
                    FROM canonical_runs selected
                    JOIN runs owner ON owner.id = selected.run_id
                    WHERE policy_hash = ? AND run_mode = ? AND decision_date = ?
                    """,
                    (cohort["policy_hash"], cohort["run_mode"], cohort["decision_date"]),
                ).fetchone()
                if selected is None:
                    raise ValueError("Daily completion has no canonical run lease.")
                if selected["run_id"] != run_id and not (
                    selected["status"] == RunStatus.SUCCEEDED.value
                    and selected["workflow_complete"]
                ):
                    raise ValueError("Daily diagnostic completion is waiting on the canonical run.")
            connection.execute(
                """
                UPDATE runs SET status = 'succeeded', workflow_complete = 1,
                    completed_at = ?, error = NULL
                WHERE id = ? AND status = 'running'
                """,
                (datetime.now(UTC).isoformat(), run_id),
            )

    @classmethod
    def _invalidate_incomplete_run(
        cls, connection: sqlite3.Connection, run_id: str, reason: str
    ) -> None:
        connection.execute(
            "UPDATE forecast_cohorts SET is_canonical = 0 WHERE run_id = ?", (run_id,)
        )
        connection.execute("DELETE FROM canonical_runs WHERE run_id = ?", (run_id,))
        proposals = connection.execute(
            """
            SELECT p.* FROM trade_proposals p
            WHERE p.source_run_id = ?
              AND NOT EXISTS (SELECT 1 FROM paper_fills f WHERE f.proposal_id = p.id)
              AND (SELECT event_type FROM proposal_events e WHERE e.proposal_id = p.id
                   ORDER BY sequence DESC LIMIT 1) IN ('PROPOSED', 'APPROVED')
            """,
            (run_id,),
        ).fetchall()
        now = datetime.now(UTC)
        for proposal in proposals:
            cls._append_proposal_event(
                connection,
                proposal,
                "RUN_INVALIDATED",
                "paper-policy",
                reason,
                now,
            )

    def store_payload(
        self,
        *,
        run_id: str,
        provider: str,
        endpoint: str,
        observed_at: datetime,
        payload: Any,
        request_params_hash: str | None = None,
        response_received_at: datetime | None = None,
        http_status: int | None = None,
        content_type: str | None = None,
        request_manifest: list[dict[str, object]] | None = None,
    ) -> int:
        payload_json = canonical_json(payload)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO provider_payloads (
                    run_id, provider, endpoint, fetched_at, observed_at,
                    payload_json, payload_hash, request_params_hash,
                    response_received_at, http_status, content_type
                    ,request_manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    provider,
                    endpoint,
                    datetime.now(UTC).isoformat(),
                    observed_at.astimezone(UTC).isoformat(),
                    payload_json,
                    content_hash(payload_json),
                    request_params_hash,
                    response_received_at.astimezone(UTC).isoformat()
                    if response_received_at
                    else None,
                    http_status,
                    content_type,
                    canonical_json(request_manifest or []),
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
        retrieved_urls: tuple[str, ...] = (),
        source_manifest: tuple[dict[str, Any], ...] = (),
    ) -> None:
        valid_narrative_ids = {item.narrative_id for item in landscape.narratives}
        updates = {
            item.narrative_id: item
            for item in result.narrative_updates
            if item.narrative_id in valid_narrative_ids
        }
        reviews = {(item.narrative_id, item.project_id): item for item in result.project_reviews}
        gaps = list(dict.fromkeys([*landscape.data_gaps, *result.data_gaps]))
        normalized_output = canonical_json(result.model_dump(mode="json"))
        manifest_json = canonical_json(
            list(source_manifest)
            or sorted(
                set(retrieved_urls)
                or {source.url for event in result.key_events for source in event.sources}
                | {source.url for update in result.narrative_updates for source in update.sources}
                | {source.url for review in result.project_reviews for source in review.sources}
            )
        )
        packet_hash = content_hash(
            {"prompt": prompt, "normalized_output": normalized_output, "manifest": manifest_json}
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO research_runs (
                    run_id, model, reasoning_effort, prompt_version, prompt_hash,
                    response_id, market_regime, market_summary, data_gaps_json,
                    prompt_text, normalized_output_json, source_manifest_json, packet_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    prompt,
                    normalized_output,
                    manifest_json,
                    packet_hash,
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
                        int(item.research_eligible),
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
                    horizon, event_subject, event_type, event_at,
                    narrative_ids_json, sources_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        index,
                        item.title,
                        item.why_it_matters,
                        item.direction,
                        item.horizon,
                        item.event_subject,
                        item.event_type,
                        item.event_at.astimezone(UTC).isoformat() if item.event_at else None,
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
                WHERE r.status = 'succeeded' AND r.workflow_complete = 1
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
                WHERE r.status = 'succeeded' AND r.workflow_complete = 1
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
        quality_prompt_version: str = "unknown",
        retrieved_urls: tuple[str, ...] = (),
        source_manifest: tuple[dict[str, Any], ...] = (),
        dynamic_draft: DailyDynamicNarrativeDraft | None = None,
    ) -> None:
        dynamic_ids = {item.narrative_id for item in radar.narratives}
        reviews = {
            (item.narrative_id, item.project_id): item
            for item in result.project_reviews
            if item.narrative_id in dynamic_ids
        }
        # forecast_cohorts.policy_hash is the original database column name. It
        # stores the complete research-strategy lineage (policy + prompt/evaluator
        # versions), while paper_decisions.policy_hash stores the exact trading
        # policy hash used for approval and settlement.
        strategy_lineage_hash = content_hash(
            {
                "policy_hash": policy.policy_hash,
                "dynamic_prompt_version": prompt_version,
                "quality_prompt_version": quality_prompt_version,
                "paper_evaluation_version": "paper-gates-v2",
            }
        )
        normalized_output = canonical_json(radar.model_dump(mode="json"))
        manifest_json = canonical_json(
            list(source_manifest)
            or sorted(
                set(retrieved_urls)
                or {source.url for item in radar.narratives for source in item.sources}
            )
        )
        validated_draft = (
            canonical_json(dynamic_draft.model_dump(mode="json")) if dynamic_draft else "{}"
        )
        packet_hash = content_hash(
            {
                "prompt": prompt,
                "normalized_output": normalized_output,
                "manifest": manifest_json,
                "validated_draft": validated_draft,
            }
        )
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO dynamic_research_runs (
                    run_id, model, reasoning_effort, prompt_version, prompt_hash,
                    response_id, data_gaps_json, prompt_text,
                    normalized_output_json, source_manifest_json, validated_draft_json,
                    packet_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    model,
                    reasoning_effort,
                    prompt_version,
                    content_hash(prompt),
                    response_id,
                    canonical_json(radar.data_gaps),
                    prompt,
                    normalized_output,
                    manifest_json,
                    validated_draft,
                    packet_hash,
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
                    SELECT DISTINCT c.decision_date
                    FROM forecast_cohorts c JOIN runs r ON r.id = c.run_id
                    WHERE c.is_canonical = 1 AND c.run_mode = 'live'
                      AND c.policy_hash = ? AND r.status = 'succeeded'
                      AND r.workflow_complete = 1
                    """,
                    (strategy_lineage_hash,),
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
                        strategy_lineage_hash,
                        int(
                            history_days >= policy.minimum_prospective_days
                            and item.state.value in policy.dynamic_entry_states
                        ),
                    )
                    for item in radar.narratives
                ],
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
              AND EXISTS (
                SELECT 1 FROM canonical_runs selected
                WHERE selected.run_id = current.run_id
                  AND selected.policy_hash = current.policy_hash
                  AND selected.run_mode = current.run_mode
                  AND selected.decision_date = current.decision_date
              )
            """,
            (run_id,),
        )

    def prospective_days_for_run(self, run_id: str) -> int:
        """Count the current consecutive live episode under one exact strategy lineage."""
        with self.connect() as connection:
            cohort = connection.execute(
                """
                SELECT policy_hash, decision_date, run_mode
                FROM forecast_cohorts WHERE run_id = ? LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if cohort is None or cohort["run_mode"] != RunMode.LIVE.value:
                return 0
            dates = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT selected.decision_date FROM canonical_runs selected
                    JOIN runs r ON r.id = selected.run_id
                    WHERE selected.policy_hash = ? AND selected.run_mode = 'live'
                      AND r.status = 'succeeded' AND r.workflow_complete = 1
                    """,
                    (cohort["policy_hash"],),
                )
            }
            dates.add(cohort["decision_date"])
        cursor = date.fromisoformat(cohort["decision_date"])
        days = 0
        while cursor.isoformat() in dates:
            days += 1
            cursor = date.fromordinal(cursor.toordinal() - 1)
        return days

    def finalize_canonical_run(self, run_id: str) -> bool:
        """Lease one run per research-strategy lineage/date, never per narrative."""
        with self.connect() as connection:
            run = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            cohort = connection.execute(
                """
                SELECT policy_hash, run_mode, decision_date
                FROM forecast_cohorts WHERE run_id = ? LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if run is None or run["status"] not in {
                RunStatus.RUNNING.value,
                RunStatus.SUCCEEDED.value,
            }:
                raise ValueError("A canonical run must be running or succeeded.")
            if cohort is None:
                return False
            lease_cutoff = (datetime.now(UTC) - CANONICAL_LEASE_TTL).isoformat()
            invalid = connection.execute(
                """
                SELECT selected.run_id FROM canonical_runs selected
                JOIN runs r ON r.id = selected.run_id
                WHERE selected.policy_hash = ? AND selected.run_mode = ?
                  AND selected.decision_date = ?
                  AND (
                    r.status = 'failed'
                    OR (r.status = 'succeeded' AND r.workflow_complete = 0)
                    OR (
                        r.status = 'running' AND selected.run_id != ?
                        AND selected.created_at <= ?
                    )
                  )
                """,
                (
                    cohort["policy_hash"],
                    cohort["run_mode"],
                    cohort["decision_date"],
                    run_id,
                    lease_cutoff,
                ),
            ).fetchone()
            if invalid:
                stale = connection.execute(
                    "SELECT status FROM runs WHERE id = ?", (invalid["run_id"],)
                ).fetchone()
                if stale and stale["status"] == RunStatus.RUNNING.value:
                    connection.execute(
                        """
                        UPDATE runs SET status = 'failed', workflow_complete = 0,
                            completed_at = ?, error = ?
                        WHERE id = ? AND status = 'running'
                        """,
                        (
                            datetime.now(UTC).isoformat(),
                            f"Canonical lease superseded by {run_id}.",
                            invalid["run_id"],
                        ),
                    )
                self._invalidate_incomplete_run(
                    connection,
                    invalid["run_id"],
                    f"Canonical lease superseded by {run_id}.",
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO canonical_runs (
                    policy_hash, run_mode, decision_date, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cohort["policy_hash"],
                    cohort["run_mode"],
                    cohort["decision_date"],
                    run_id,
                    datetime.now(UTC).isoformat(),
                ),
            )
            selected = connection.execute(
                """
                SELECT run_id FROM canonical_runs
                WHERE policy_hash = ? AND run_mode = ? AND decision_date = ?
                """,
                (cohort["policy_hash"], cohort["run_mode"], cohort["decision_date"]),
            ).fetchone()
            is_canonical = bool(selected and selected["run_id"] == run_id)
            if is_canonical:
                self._finalize_canonical_cohorts(connection, run_id)
            return is_canonical

    def store_paper_evidence(
        self,
        *,
        run_id: str,
        investability: InvestabilityDataBundle,
        evaluation: PaperEvaluation,
        policy: StrategyPolicy,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        portfolio_id = f"paper-{policy.policy_hash[:16]}"
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO strategy_policy_versions (
                    policy_hash, version, policy_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (policy.policy_hash, policy.version, policy.policy_json, now),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO paper_portfolios (
                    id, policy_hash, initial_cash_usd, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (portfolio_id, policy.policy_hash, policy.paper_initial_cash_usd, now),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO portfolio_cash_ledger (
                    portfolio_id, event_type, amount_usd, reference_type,
                    reference_id, created_at
                ) VALUES (?, 'initial_funding', ?, 'policy', ?, ?)
                """,
                (portfolio_id, policy.paper_initial_cash_usd, policy.policy_hash, now),
            )
            for asset in investability.assets:
                for quote in asset.quotes:
                    quote_json = canonical_json(quote.model_dump(mode="json"))
                    quote_hash = content_hash(quote_json)
                    quote_id = f"quote-{quote_hash[:24]}"
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO venue_quote_snapshots (
                            id, run_id, asset_id, provider, venue, pair,
                            observed_at, quote_json, quote_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            quote_id,
                            run_id,
                            quote.asset_id,
                            quote.provider,
                            quote.venue,
                            quote.pair,
                            quote.observed_at.astimezone(UTC).isoformat(),
                            quote_json,
                            quote_hash,
                        ),
                    )
            for candidate in evaluation.candidates:
                assessment_json = canonical_json(candidate.model_dump(mode="json"))
                connection.execute(
                    """
                    INSERT INTO paper_candidate_assessments (
                        run_id, narrative_id, asset_id, state, research_priority,
                        assessment_json, assessment_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        candidate.narrative_id,
                        candidate.asset_id,
                        candidate.state.value,
                        candidate.research_priority,
                        assessment_json,
                        content_hash(assessment_json),
                        now,
                    ),
                )

    def store_venue_quotes(
        self,
        *,
        run_id: str,
        investability: InvestabilityDataBundle,
    ) -> None:
        with self.connect() as connection:
            for asset in investability.assets:
                for quote in asset.quotes:
                    quote_json = canonical_json(quote.model_dump(mode="json"))
                    quote_hash = content_hash(quote_json)
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO venue_quote_snapshots (
                            id, run_id, asset_id, provider, venue, pair,
                            observed_at, quote_json, quote_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"quote-{quote_hash[:24]}",
                            run_id,
                            quote.asset_id,
                            quote.provider,
                            quote.venue,
                            quote.pair,
                            quote.observed_at.astimezone(UTC).isoformat(),
                            quote_json,
                            quote_hash,
                        ),
                    )

    def proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM trade_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown paper proposal: {proposal_id}")
        return dict(row)

    def settle_approved_entries(
        self,
        *,
        quote_run_id: str,
        policy: StrategyPolicy,
        proposal_id: str | None = None,
    ) -> list[str]:
        """Use the first post-approval quote; never select a more favorable later quote."""
        filled: list[str] = []
        now = datetime.now(UTC)
        with self.connect() as connection:
            run = connection.execute(
                "SELECT status, workflow_complete FROM runs WHERE id = ?", (quote_run_id,)
            ).fetchone()
            if (
                run is None
                or run["status"] != RunStatus.SUCCEEDED.value
                or not run["workflow_complete"]
            ):
                raise ValueError("Paper fills require a completed succeeded quote run.")
            parameters: tuple[Any, ...] = (
                (policy.policy_hash, proposal_id) if proposal_id else (policy.policy_hash,)
            )
            where = "AND p.id = ?" if proposal_id else ""
            proposals = connection.execute(
                f"""
                SELECT p.*, approved.created_at AS approved_at,
                       approved.sequence AS approved_sequence
                FROM trade_proposals p
                JOIN proposal_events approved ON approved.proposal_id = p.id
                 AND approved.event_type = 'APPROVED'
                WHERE NOT EXISTS (
                    SELECT 1 FROM paper_fills f WHERE f.proposal_id = p.id
                )
                  AND p.policy_hash = ?
                  AND approved.sequence = (
                    SELECT MAX(sequence) FROM proposal_events WHERE proposal_id = p.id
                  )
                  {where}
                ORDER BY approved.created_at
                """,
                parameters,
            ).fetchall()
            for proposal in proposals:
                approved_at = datetime.fromisoformat(proposal["approved_at"])
                deadline = datetime.fromisoformat(proposal["approval_deadline"])
                quote_row = connection.execute(
                    """
                    SELECT q.* FROM venue_quote_snapshots q
                    JOIN runs r ON r.id = q.run_id
                    WHERE q.asset_id = ? AND q.venue = ? AND q.pair = ?
                      AND q.observed_at > ? AND q.observed_at <= ?
                      AND r.status = 'succeeded' AND r.workflow_complete = 1
                    ORDER BY q.observed_at ASC, q.id ASC LIMIT 1
                    """,
                    (
                        proposal["asset_id"],
                        proposal["venue"],
                        proposal["pair"],
                        approved_at.isoformat(),
                        deadline.isoformat(),
                    ),
                ).fetchone()
                if quote_row is None:
                    if now > deadline:
                        self._append_proposal_event(
                            connection,
                            proposal,
                            "EXPIRED",
                            "paper-policy",
                            "No post-approval quote arrived before expiry.",
                            now,
                        )
                    continue
                quote = json.loads(quote_row["quote_json"])
                rejection = self._fill_rejection_reason(connection, proposal, quote, policy, now)
                if rejection:
                    self._append_proposal_event(
                        connection,
                        proposal,
                        "REQUOTE_REQUIRED",
                        "paper-policy",
                        rejection,
                        now,
                        quote_row["id"],
                    )
                    continue
                price = float(quote["buy_vwap_price"])
                quantity = float(proposal["proposed_quantity"])
                gross = price * quantity
                fee = gross * float(quote["taker_fee_bps"] or 0) / 10_000
                fill_id = f"fill-{uuid.uuid4().hex[:16]}"
                connection.execute(
                    """
                    INSERT INTO paper_fills (
                        id, proposal_id, fill_run_id, quote_id, side, quantity,
                        execution_price, gross_notional_usd, fee_usd,
                        total_cost_bps, executed_at, fill_model_version
                    ) VALUES (?, ?, ?, ?, 'buy', ?, ?, ?, ?, ?, ?, 'book-walk-v1')
                    """,
                    (
                        fill_id,
                        proposal["id"],
                        quote_row["run_id"],
                        quote_row["id"],
                        quantity,
                        price,
                        gross,
                        fee,
                        float(quote["estimated_round_trip_cost_bps"]),
                        now.isoformat(),
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO portfolio_cash_ledger (
                        portfolio_id, event_type, amount_usd, reference_type,
                        reference_id, created_at
                    ) VALUES (?, ?, ?, 'fill', ?, ?)
                    """,
                    [
                        (
                            proposal["portfolio_id"],
                            "entry_principal",
                            -gross,
                            fill_id,
                            now.isoformat(),
                        ),
                        (
                            proposal["portfolio_id"],
                            "entry_fee",
                            -fee,
                            fill_id,
                            now.isoformat(),
                        ),
                    ],
                )
                position_id = f"position-{uuid.uuid4().hex[:16]}"
                connection.execute(
                    """
                    INSERT INTO paper_positions (
                        id, portfolio_id, opening_fill_id, narrative_id,
                        asset_id, quantity, opened_at, planned_exit_at,
                        initial_stop_price
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        position_id,
                        proposal["portfolio_id"],
                        fill_id,
                        proposal["narrative_id"],
                        proposal["asset_id"],
                        quantity,
                        now.isoformat(),
                        proposal["planned_exit_at"],
                        proposal["stop_price"],
                    ),
                )
                self._append_proposal_event(
                    connection,
                    proposal,
                    "FILLED",
                    "paper-policy",
                    "First qualifying post-approval quote filled the all-or-none paper order.",
                    now,
                    quote_row["id"],
                )
                filled.append(fill_id)
        return filled

    @staticmethod
    def _append_proposal_event(
        connection: sqlite3.Connection,
        proposal: sqlite3.Row,
        event_type: str,
        actor: str,
        reason: str,
        created_at: datetime,
        quote_id: str | None = None,
    ) -> None:
        sequence = connection.execute(
            "SELECT MAX(sequence) FROM proposal_events WHERE proposal_id = ?",
            (proposal["id"],),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO proposal_events (
                proposal_id, sequence, event_type, actor, proposal_hash,
                reason, created_at, quote_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal["id"],
                int(sequence) + 1,
                event_type,
                actor,
                proposal["proposal_hash"],
                reason,
                created_at.isoformat(),
                quote_id,
            ),
        )

    @staticmethod
    def _fill_rejection_reason(
        connection: sqlite3.Connection,
        proposal: sqlite3.Row,
        quote: dict[str, Any],
        policy: StrategyPolicy,
        now: datetime,
    ) -> str | None:
        if proposal["policy_hash"] != policy.policy_hash:
            return "The proposal policy no longer matches the active settlement policy."
        observed_at = datetime.fromisoformat(str(quote["observed_at"]))
        if (now - observed_at).total_seconds() > policy.maximum_quote_age_seconds:
            return "The first post-approval quote was stale."
        if not quote.get("executable") or not quote.get("pair_online"):
            return "The approved venue route was not executable and online."
        if proposal["contract_address"] != quote.get("contract_address"):
            return "The quote contract did not match the approved proposal."
        price = quote.get("buy_vwap_price")
        if not price or float(price) > float(proposal["maximum_entry_price"]):
            return "The first post-approval price exceeded the approved tolerance."
        costs = quote.get("estimated_round_trip_cost_bps")
        if costs is None or float(costs) > policy.maximum_round_trip_cost_pct * 100:
            return "Estimated round-trip costs exceeded policy."
        notional = float(proposal["proposed_quantity"]) * float(price)
        maximum_position = policy.paper_initial_cash_usd * policy.maximum_position_nav_pct / 100
        if notional > maximum_position + 0.005:
            return "The fill price would breach the per-position paper NAV cap."
        stop_price = float(proposal["stop_price"] or 0)
        if stop_price <= 0 or stop_price >= float(price):
            return "The approved absolute stop is invalid at the post-approval fill price."
        stop_loss = notional * (float(price) - stop_price) / float(price)
        stressed_initial_loss = stop_loss + notional * float(costs) / 10_000
        maximum_initial_loss = (
            policy.paper_initial_cash_usd * policy.maximum_initial_risk_nav_pct / 100
        )
        packet_maximum_loss = float(proposal["maximum_initial_loss_usd"] or 0)
        approved_loss_limit = min(maximum_initial_loss, packet_maximum_loss)
        if stressed_initial_loss > approved_loss_limit + 0.005:
            return (
                "The post-approval price and costs would breach the human-approved "
                "maximum-loss packet."
            )
        required_depth = notional / (policy.maximum_depth_utilization_pct / 100)
        if float(quote.get("buy_depth_1pct_usd") or 0) < required_depth:
            return "Approved size would use too much ask-side depth."
        if float(quote.get("sell_depth_1pct_usd") or 0) < required_depth:
            return "Approved size would use too much exit-side depth."
        cash = float(
            connection.execute(
                """
                SELECT COALESCE(SUM(amount_usd), 0) FROM portfolio_cash_ledger
                WHERE portfolio_id = ?
                """,
                (proposal["portfolio_id"],),
            ).fetchone()[0]
        )
        fee = notional * float(quote.get("taker_fee_bps") or 0) / 10_000
        if cash < notional + fee:
            return "Paper cash no longer covers the approved fill and fee."
        open_rows = connection.execute(
            "SELECT narrative_id, asset_id FROM paper_positions WHERE portfolio_id = ?",
            (proposal["portfolio_id"],),
        ).fetchall()
        if len(open_rows) >= policy.maximum_open_positions:
            return "The open-position limit changed before fill."
        if any(row["asset_id"] == proposal["asset_id"] for row in open_rows):
            return "The paper portfolio already owns this asset."
        if any(row["narrative_id"] == proposal["narrative_id"] for row in open_rows):
            return "The paper portfolio already has this narrative exposure."
        recent = connection.execute(
            """
            SELECT COUNT(*) FROM paper_fills f
            JOIN trade_proposals p ON p.id = f.proposal_id
            WHERE p.portfolio_id = ? AND f.side = 'buy' AND f.executed_at >= ?
            """,
            (proposal["portfolio_id"], (now - timedelta(days=7)).isoformat()),
        ).fetchone()[0]
        if recent >= policy.maximum_new_entries_per_rolling_7d:
            return "The rolling seven-day filled-entry cadence changed before fill."
        deployed = float(
            connection.execute(
                """
                SELECT COALESCE(SUM(f.gross_notional_usd), 0)
                FROM paper_positions pos JOIN paper_fills f ON f.id = pos.opening_fill_id
                WHERE pos.portfolio_id = ?
                """,
                (proposal["portfolio_id"],),
            ).fetchone()[0]
        )
        maximum_deployed = policy.paper_initial_cash_usd * policy.maximum_deployed_nav_pct / 100
        if deployed + notional > maximum_deployed:
            return "The maximum deployed paper NAV would be exceeded."
        return None

    def finalize_paper_decision(
        self,
        *,
        run_id: str,
        evaluation: PaperEvaluation,
        policy: StrategyPolicy,
        is_canonical: bool,
        run_mode: RunMode,
    ) -> str | None:
        """Persist one decision and, at most, one immutable entry proposal."""
        now = datetime.now(UTC)
        proposal_id = None
        decision_action = "NO_ACTION"
        portfolio_id = f"paper-{policy.policy_hash[:16]}"
        qualified = sum(item.state.value != "research_only" for item in evaluation.candidates)
        with self.connect() as connection:
            run = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None or run["status"] not in {
                RunStatus.RUNNING.value,
                RunStatus.SUCCEEDED.value,
            }:
                raise ValueError("Paper decisions require a running or succeeded evidence run.")
            proposable = [
                item for item in evaluation.candidates if item.state.value == "proposable"
            ]
            shadow_cases = [
                item for item in evaluation.candidates if item.case_stage.value == "shadow_ready"
            ]
            worthy_cases = [
                item
                for item in evaluation.candidates
                if item.case_stage.value in {"worthy_case", "shadow_ready", "paper_ready"}
            ]
            if run_mode is not RunMode.LIVE:
                readiness = "BLOCKED_OFFLINE_OBSERVATION"
                reason = "Offline evidence cannot originate a paper proposal."
            elif not is_canonical:
                readiness = "BLOCKED_NONCANONICAL_RERUN"
                reason = "Only the first complete scheduled run for the policy/date may propose."
            elif proposable:
                candidate = proposable[0]
                capacity_reason = self._paper_capacity_reason(connection, portfolio_id, policy, now)
                if capacity_reason:
                    readiness = "BLOCKED_PORTFOLIO_POLICY"
                    reason = capacity_reason
                elif (
                    not candidate.quote
                    or not candidate.technical
                    or not candidate.proposed_notional_usd
                ):
                    readiness = "BLOCKED_INCOMPLETE_PROPOSAL_PACKET"
                    reason = "A proposal packet is missing a quote, stop, or deterministic size."
                else:
                    quote_json = canonical_json(candidate.quote.model_dump(mode="json"))
                    quote_id = f"quote-{content_hash(quote_json)[:24]}"
                    price = float(candidate.quote.buy_vwap_price or 0)
                    notional = float(candidate.proposed_notional_usd)
                    quantity = notional / price
                    proposal_id = f"proposal-{uuid.uuid4().hex[:16]}"
                    deadline = now + timedelta(hours=policy.approval_ttl_hours)
                    planned_exit = now + timedelta(days=policy.paper_horizon_days)
                    packet = {
                        "candidate": candidate.model_dump(mode="json"),
                        "policy_hash": policy.policy_hash,
                        "source_run_id": run_id,
                        "approval_semantics": (
                            "Approval binds this exact packet and permits only a post-approval "
                            "paper quote; it is not a fill or live order."
                        ),
                    }
                    proposal_json = canonical_json(packet)
                    proposal_hash = content_hash(proposal_json)
                    connection.execute(
                        """
                        INSERT INTO trade_proposals (
                            id, portfolio_id, source_run_id, narrative_id, asset_id,
                            intent, venue_quote_id, venue, pair, chain_id,
                            contract_address, proposed_notional_usd, proposed_quantity,
                            decision_price, maximum_entry_price, stop_price,
                            maximum_initial_loss_usd, policy_hash, proposal_json,
                            proposal_hash, created_at, approval_deadline, planned_exit_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, 'entry', ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            proposal_id,
                            portfolio_id,
                            run_id,
                            candidate.narrative_id,
                            candidate.asset_id,
                            quote_id,
                            candidate.quote.venue,
                            candidate.quote.pair,
                            candidate.quote.chain_id,
                            candidate.quote.contract_address,
                            notional,
                            quantity,
                            price,
                            price * (1 + policy.maximum_approval_price_move_pct / 100),
                            candidate.technical.stop_price,
                            candidate.maximum_initial_loss_usd,
                            policy.policy_hash,
                            proposal_json,
                            proposal_hash,
                            now.isoformat(),
                            deadline.isoformat(),
                            planned_exit.isoformat(),
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO proposal_events (
                            proposal_id, sequence, event_type, actor, proposal_hash,
                            reason, created_at, quote_id
                        ) VALUES (?, 1, 'PROPOSED', 'system', ?, ?, ?, ?)
                        """,
                        (
                            proposal_id,
                            proposal_hash,
                            "All deterministic research, investability, technical, and "
                            "portfolio gates passed.",
                            now.isoformat(),
                            quote_id,
                        ),
                    )
                    readiness = "PROPOSAL_AWAITING_HUMAN"
                    decision_action = "PROPOSE_ENTRY"
                    reason = (
                        f"{candidate.asset_name} passed every {policy.version} gate; approval is "
                        "required."
                    )
            elif shadow_cases:
                candidate = shadow_cases[0]
                readiness = "SHADOW_CASE_READY"
                decision_action = "TRACK_SHADOW_CASE"
                reason = (
                    f"{candidate.asset_name} has a {candidate.case_score:.1f}/100 case and a "
                    "valid entry setup; it is being observed before paper eligibility."
                )
            elif worthy_cases:
                candidate = worthy_cases[0]
                readiness = "WORTHY_CASE_MONITORING"
                decision_action = "WATCH_CASE"
                reason = (
                    f"{candidate.asset_name} has a {candidate.case_score:.1f}/100 sourced case; "
                    "remaining investability or entry gates still block a proposal."
                )
            elif evaluation.prospective_days < policy.minimum_prospective_days:
                readiness = "BUILDING_EARLY_EVIDENCE"
                reason = (
                    f"Cases are visible now; paper eligibility needs "
                    f"{evaluation.prospective_days}/{policy.minimum_prospective_days} canonical "
                    "live days."
                )
            else:
                states = {item.state.value for item in evaluation.candidates}
                if "investability_verified" in states:
                    readiness = "WAITING_FOR_TECHNICAL_ENTRY"
                elif "research_qualified" in states:
                    readiness = "BLOCKED_INVESTABILITY"
                else:
                    readiness = "NO_WORTHY_INVESTMENT_CASE"
                reason = (
                    "; ".join(evaluation.candidates[0].reasons[:2])
                    if evaluation.candidates
                    else "No bounded project candidate was available for investability checks."
                )
            connection.execute(
                """
                INSERT INTO paper_decisions (
                    run_id, policy_version, action, reason, prospective_days,
                    qualified_narrative_count, created_at, readiness_state,
                    policy_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    policy.version,
                    decision_action,
                    reason,
                    evaluation.prospective_days,
                    qualified,
                    now.isoformat(),
                    readiness,
                    policy.policy_hash,
                ),
            )
        return proposal_id

    @staticmethod
    def _paper_capacity_reason(
        connection: sqlite3.Connection,
        portfolio_id: str,
        policy: StrategyPolicy,
        now: datetime,
    ) -> str | None:
        open_count = connection.execute(
            "SELECT COUNT(*) FROM paper_positions WHERE portfolio_id = ?",
            (portfolio_id,),
        ).fetchone()[0]
        if open_count >= policy.maximum_open_positions:
            return f"Portfolio already has {open_count} open positions."
        recent_entries = connection.execute(
            """
            SELECT COUNT(*) FROM paper_fills f
            JOIN trade_proposals p ON p.id = f.proposal_id
            WHERE p.portfolio_id = ? AND f.side = 'buy' AND f.executed_at >= ?
            """,
            (portfolio_id, (now - timedelta(days=7)).isoformat()),
        ).fetchone()[0]
        if recent_entries >= policy.maximum_new_entries_per_rolling_7d:
            return "The rolling seven-day filled-entry cadence is exhausted."
        active = connection.execute(
            """
            SELECT COUNT(*) FROM trade_proposals p
            WHERE p.portfolio_id = ?
              AND NOT EXISTS (SELECT 1 FROM paper_fills f WHERE f.proposal_id = p.id)
              AND (SELECT event_type FROM proposal_events e
                   WHERE e.proposal_id = p.id ORDER BY sequence DESC LIMIT 1)
                  IN ('PROPOSED', 'APPROVED')
            """,
            (portfolio_id,),
        ).fetchone()[0]
        if active:
            return "Another entry proposal is already awaiting a terminal outcome."
        cash = connection.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) FROM portfolio_cash_ledger WHERE portfolio_id = ?",
            (portfolio_id,),
        ).fetchone()[0]
        if cash <= 0:
            return "Paper portfolio has no available cash."
        return None

    def paper_assets_requiring_quotes(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT asset_id FROM paper_positions
                UNION
                SELECT p.asset_id FROM trade_proposals p
                JOIN runs r ON r.id = p.source_run_id
                WHERE r.status = 'succeeded' AND r.workflow_complete = 1
                  AND NOT EXISTS (SELECT 1 FROM paper_fills f WHERE f.proposal_id = p.id)
                  AND (SELECT event_type FROM proposal_events e
                       WHERE e.proposal_id = p.id ORDER BY sequence DESC LIMIT 1)
                      IN ('PROPOSED', 'APPROVED')
                """
            ).fetchall()
        return [row["asset_id"] for row in rows]

    def list_paper_proposals(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        where = (
            "WHERE latest.event_type IN ('PROPOSED', 'APPROVED') AND f.id IS NULL"
            if active_only
            else ""
        )
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT p.*, latest.event_type AS status, latest.created_at AS status_at,
                       f.id AS fill_id
                FROM trade_proposals p
                JOIN proposal_events latest ON latest.proposal_id = p.id
                 AND latest.sequence = (
                    SELECT MAX(sequence) FROM proposal_events WHERE proposal_id = p.id
                 )
                LEFT JOIN paper_fills f ON f.proposal_id = p.id
                {where}
                ORDER BY p.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def record_proposal_response(
        self,
        proposal_id: str,
        *,
        approve: bool,
        actor: str = "human",
        reason: str = "",
        expected_policy_hash: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with self.connect() as connection:
            proposal = connection.execute(
                """
                SELECT p.*, r.status AS run_status,
                       r.workflow_complete AS run_workflow_complete,
                       (SELECT event_type FROM proposal_events e
                        WHERE e.proposal_id = p.id ORDER BY sequence DESC LIMIT 1) AS status,
                       (SELECT MAX(sequence) FROM proposal_events e
                        WHERE e.proposal_id = p.id) AS sequence
                FROM trade_proposals p JOIN runs r ON r.id = p.source_run_id
                WHERE p.id = ?
                """,
                (proposal_id,),
            ).fetchone()
            if proposal is None:
                raise KeyError(f"Unknown paper proposal: {proposal_id}")
            if proposal["run_status"] != RunStatus.SUCCEEDED.value:
                raise ValueError("A failed evidence run cannot be approved.")
            if not proposal["run_workflow_complete"]:
                raise ValueError("An incomplete daily workflow cannot be approved.")
            if approve and not expected_policy_hash:
                raise ValueError("Approval requires the caller's exact active policy hash.")
            if approve and expected_policy_hash and proposal["policy_hash"] != expected_policy_hash:
                raise ValueError(
                    "The proposal was created under a different strategy policy and cannot be "
                    "approved."
                )
            if proposal["status"] != "PROPOSED":
                raise ValueError(f"Proposal is already {proposal['status']}.")
            event_type = "APPROVED" if approve else "REJECTED"
            if approve and now > datetime.fromisoformat(proposal["approval_deadline"]):
                event_type = "EXPIRED"
                reason = reason or "Approval arrived after the packet deadline."
            connection.execute(
                """
                INSERT INTO proposal_events (
                    proposal_id, sequence, event_type, actor, proposal_hash,
                    reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    int(proposal["sequence"]) + 1,
                    event_type,
                    actor,
                    proposal["proposal_hash"],
                    reason
                    or (
                        "Human approved the exact paper packet."
                        if approve
                        else "Human rejected the paper packet."
                    ),
                    now.isoformat(),
                ),
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
                "SELECT status, workflow_complete FROM runs WHERE id = ?", (observation_run_id,)
            ).fetchone()
            if (
                observation is None
                or observation["status"] != RunStatus.SUCCEEDED.value
                or not observation["workflow_complete"]
            ):
                raise ValueError("Forecast outcomes require a completed succeeded observation.")
            current_cohort = connection.execute(
                """
                SELECT policy_hash, run_mode, decision_date
                FROM forecast_cohorts WHERE run_id = ? LIMIT 1
                """,
                (observation_run_id,),
            ).fetchone()
            if current_cohort:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO canonical_runs (
                        policy_hash, run_mode, decision_date, run_id, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        current_cohort["policy_hash"],
                        current_cohort["run_mode"],
                        current_cohort["decision_date"],
                        observation_run_id,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                self._finalize_canonical_cohorts(connection, observation_run_id)
            cohorts = connection.execute(
                """
                SELECT c.*, r.as_of
                FROM forecast_cohorts c JOIN runs r ON r.id = c.run_id
                WHERE c.is_canonical = 1 AND r.status = 'succeeded'
                  AND r.workflow_complete = 1
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
            provider_fetch = connection.execute(
                """
                SELECT MAX(response_received_at) AS latest_response_at,
                       SUM(CASE WHEN response_received_at IS NOT NULL THEN 1 ELSE 0 END)
                           AS received_payloads
                FROM provider_payloads WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            paper_decision = connection.execute(
                "SELECT * FROM paper_decisions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            paper_policy = (
                connection.execute(
                    "SELECT policy_json FROM strategy_policy_versions WHERE policy_hash = ?",
                    (paper_decision["policy_hash"],),
                ).fetchone()
                if paper_decision
                else None
            )
            paper_candidates = connection.execute(
                """
                SELECT * FROM paper_candidate_assessments
                WHERE run_id = ? ORDER BY research_priority DESC
                """,
                (run_id,),
            ).fetchall()
            paper_proposals = connection.execute(
                """
                SELECT p.*, latest.event_type AS status, latest.created_at AS status_at
                FROM trade_proposals p
                JOIN proposal_events latest ON latest.proposal_id = p.id
                 AND latest.sequence = (
                    SELECT MAX(sequence) FROM proposal_events WHERE proposal_id = p.id
                 )
                WHERE p.source_run_id = ?
                   OR latest.event_type IN ('PROPOSED', 'APPROVED')
                ORDER BY p.created_at DESC LIMIT 6
                """,
                (run_id,),
            ).fetchall()
            lineage = connection.execute(
                "SELECT policy_hash FROM forecast_cohorts WHERE run_id = ? LIMIT 1",
                (run_id,),
            ).fetchone()
            cohort_count = connection.execute(
                """
                SELECT COUNT(*) FROM forecast_cohorts
                WHERE is_canonical = 1 AND policy_hash = ?
                  AND EXISTS (
                    SELECT 1 FROM runs r WHERE r.id = forecast_cohorts.run_id
                      AND r.status = 'succeeded' AND r.workflow_complete = 1
                  )
                """,
                (lineage["policy_hash"] if lineage else "",),
            ).fetchone()[0]
            outcome_count = connection.execute(
                """
                SELECT COUNT(*) FROM forecast_outcomes o
                JOIN forecast_cohorts c
                  ON c.run_id = o.cohort_run_id AND c.narrative_id = o.narrative_id
                WHERE o.status = 'priced' AND c.policy_hash = ?
                """,
                (lineage["policy_hash"] if lineage else "",),
            ).fetchone()[0]
            portfolio = None
            portfolio_cash = 0.0
            positions = []
            paper_fill_count = 0
            if paper_decision:
                portfolio = connection.execute(
                    "SELECT * FROM paper_portfolios WHERE policy_hash = ?",
                    (paper_decision["policy_hash"],),
                ).fetchone()
            if portfolio:
                portfolio_cash = float(
                    connection.execute(
                        """
                        SELECT COALESCE(SUM(amount_usd), 0)
                        FROM portfolio_cash_ledger WHERE portfolio_id = ?
                        """,
                        (portfolio["id"],),
                    ).fetchone()[0]
                )
                positions = connection.execute(
                    "SELECT * FROM paper_positions WHERE portfolio_id = ? ORDER BY opened_at",
                    (portfolio["id"],),
                ).fetchall()
                paper_fill_count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM paper_fills f
                        JOIN trade_proposals p ON p.id = f.proposal_id
                        WHERE p.portfolio_id = ?
                        """,
                        (portfolio["id"],),
                    ).fetchone()[0]
                )
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
                  AND r.status = 'succeeded' AND r.workflow_complete = 1 AND r.mode = ?
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
            "provider_fetch": dict(provider_fetch),
            "paper_decision": dict(paper_decision) if paper_decision else None,
            "paper_policy_json": paper_policy["policy_json"] if paper_policy else "{}",
            "paper_candidates": [dict(row) for row in paper_candidates],
            "paper_proposals": [dict(row) for row in paper_proposals],
            "paper_portfolio": dict(portfolio) if portfolio else None,
            "paper_cash_usd": portfolio_cash,
            "paper_positions": [dict(row) for row in positions],
            "paper_fill_count": paper_fill_count,
            "forecast_cohort_count": int(cohort_count),
            "forecast_outcome_count": int(outcome_count),
            "run_history": [dict(row) for row in run_history],
            "previous_run_id": previous["id"] if previous else None,
            "previous_narratives": [dict(row) for row in previous_narratives],
            "previous_projects": [dict(row) for row in previous_projects],
        }
