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

from trader_pete.models import (
    CategoryMarket,
    DailyNarrativeResearch,
    MarketAsset,
    ProtocolMetric,
    RunMode,
    RunStatus,
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
        }
        for table, columns in additions.items():
            existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        connection.execute("PRAGMA user_version = 2")

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
        trending_assets: list[TrendingAsset] | None = None,
    ) -> None:
        self.store_market_assets(run_id, assets)
        self.store_categories(run_id, categories)
        self.store_protocols(run_id, protocols)
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
