from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trader_pete.models import DailyNarrativeResearch, RunMode, RunStatus

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

CREATE TABLE IF NOT EXISTS narrative_assessments (
    run_id TEXT NOT NULL REFERENCES runs(id),
    narrative_id TEXT NOT NULL,
    name TEXT NOT NULL,
    summary TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    opportunity_score REAL NOT NULL,
    confidence_score REAL NOT NULL,
    signals_json TEXT NOT NULL,
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
    data_gaps_json TEXT NOT NULL
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
                        opportunity_score, confidence_score, signals_json,
                        thesis, counter_thesis
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        narrative.narrative_id,
                        narrative.name,
                        narrative.summary,
                        narrative.lifecycle.value,
                        narrative.opportunity_score,
                        narrative.confidence_score,
                        narrative.signals.model_dump_json(),
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
                        source_type, supports, credibility
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            run_id,
                            narrative.narrative_id,
                            source.title,
                            str(source.url),
                            source.published_at.isoformat() if source.published_at else None,
                            source.source_type,
                            int(source.supports),
                            source.credibility,
                        )
                        for source in narrative.sources
                    ],
                )
