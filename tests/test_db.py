from datetime import UTC, datetime
from pathlib import Path

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
