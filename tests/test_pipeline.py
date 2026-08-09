from dataclasses import replace
from pathlib import Path

from trader_pete.config import Settings
from trader_pete.db import Database
from trader_pete.models import RunMode
from trader_pete.pipeline import run_daily


def test_offline_pipeline_writes_ledger_and_self_contained_report(tmp_path: Path) -> None:
    base = Settings.from_env(Path.cwd())
    settings = replace(
        base,
        db_path=tmp_path / "data" / "test.db",
        reports_dir=tmp_path / "reports",
    )

    result = run_daily(settings, RunMode.OFFLINE)

    assert result.report_path.exists()
    html = result.report_path.read_text(encoding="utf-8")
    assert "Narrative Radar" in html
    assert "Project Explorer" in html
    assert "NO ACTION" in html
    assert "OPENAI_API_KEY" not in html
    assert "https://cdn" not in html

    with Database(settings.db_path).connect() as connection:
        run = connection.execute(
            "SELECT status FROM runs WHERE id = ?", (result.run_id,)
        ).fetchone()
        artifact = connection.execute(
            "SELECT sha256 FROM dashboard_artifacts WHERE run_id = ?", (result.run_id,)
        ).fetchone()

    assert run["status"] == "succeeded"
    assert len(artifact["sha256"]) == 64
