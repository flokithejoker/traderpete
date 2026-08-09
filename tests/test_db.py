from datetime import UTC, datetime
from pathlib import Path

import pytest

from trader_pete.db import Database
from trader_pete.models import RunMode, RunStatus


def test_run_lifecycle_is_persisted(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    run_id = database.create_run(
        as_of=datetime(2026, 8, 9, tzinfo=UTC),
        mode=RunMode.OFFLINE,
        config={"model": "test"},
    )
    database.finish_run(run_id, RunStatus.SUCCEEDED)

    with database.connect() as connection:
        row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

    assert row is not None
    assert row["status"] == "succeeded"
    assert row["config_hash"]


def test_terminal_run_status_cannot_be_rewritten(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    run_id = database.create_run(
        as_of=datetime(2026, 8, 9, tzinfo=UTC), mode=RunMode.LIVE, config={}
    )
    database.finish_run(run_id, RunStatus.SUCCEEDED)

    with pytest.raises(ValueError, match="terminal"):
        database.finish_run(run_id, RunStatus.FAILED, error="late renderer failure")

    with database.connect() as connection:
        status = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
    assert status == "succeeded"


def test_provider_payload_is_content_hashed(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    as_of = datetime(2026, 8, 9, tzinfo=UTC)
    run_id = database.create_run(as_of=as_of, mode=RunMode.OFFLINE, config={})

    database.store_payload(
        run_id=run_id,
        provider="fixture",
        endpoint="market",
        observed_at=as_of,
        payload={"value": 42},
    )

    with database.connect() as connection:
        row = connection.execute(
            "SELECT payload_hash FROM provider_payloads WHERE run_id = ?", (run_id,)
        ).fetchone()

    assert row is not None
    assert len(row["payload_hash"]) == 64


def test_initialize_migrates_existing_phase_one_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    with database.connect() as connection:
        connection.execute("CREATE TABLE category_snapshots (category_id TEXT)")
        connection.execute("CREATE TABLE narrative_assessments (narrative_id TEXT)")
        connection.execute("CREATE TABLE research_sources (title TEXT)")

    database.initialize()

    with database.connect() as connection:
        category_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(category_snapshots)")
        }
        narrative_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(narrative_assessments)")
        }
        source_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(research_sources)")
        }

    assert "top_asset_ids_json" in category_columns
    assert "metric_coverage_json" in narrative_columns
    assert {"publisher", "root_url", "claim", "is_primary"} <= source_columns


def test_initialize_replaces_legacy_canonical_index_with_exact_lineage(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()

    with database.connect() as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'uq_canonical_forecast_cohort'"
        ).fetchone()[0]

    assert "policy_hash" in sql
    assert "strategy_version" not in sql


def test_v10_migration_corrects_earlier_workflow_backfill(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.db")
    database.initialize()
    run_id = database.create_run(
        as_of=datetime(2026, 1, 1, tzinfo=UTC), mode=RunMode.LIVE, config={}
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE runs SET status = 'succeeded', workflow_complete = 1 WHERE id = ?",
            (run_id,),
        )
        connection.execute("PRAGMA user_version = 8")

    database.initialize()

    with database.connect() as connection:
        workflow_complete = connection.execute(
            "SELECT workflow_complete FROM runs WHERE id = ?", (run_id,)
        ).fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert workflow_complete == 0
    assert version == 10
