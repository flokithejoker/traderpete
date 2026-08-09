import hashlib
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
    assert "Narrative Board" in html
    assert "What matters today" in html
    assert "Morning brief" in html
    assert "Dynamic Narrative Radar" in html
    assert "Prospective Phase 2" in html
    assert "Project Explorer" in html
    assert "NO ACTION" in html
    assert "OPENAI_API_KEY" not in html
    assert "https://cdn" not in html
    assert result.run_id in str(result.report_path)
    assert result.report_path.parent.name.replace("-", "") == result.run_id[:8]

    with Database(settings.db_path).connect() as connection:
        run = connection.execute(
            "SELECT status FROM runs WHERE id = ?", (result.run_id,)
        ).fetchone()
        artifact = connection.execute(
            "SELECT sha256 FROM dashboard_artifacts WHERE run_id = ?", (result.run_id,)
        ).fetchone()
        narratives = connection.execute(
            "SELECT COUNT(*) FROM landscape_narratives WHERE run_id = ?", (result.run_id,)
        ).fetchone()[0]
        projects = connection.execute(
            "SELECT COUNT(*) FROM landscape_projects WHERE run_id = ?", (result.run_id,)
        ).fetchone()[0]
        dynamic_runs = connection.execute(
            "SELECT COUNT(*) FROM dynamic_research_runs WHERE run_id = ?", (result.run_id,)
        ).fetchone()[0]
        paper_decisions = connection.execute(
            "SELECT COUNT(*) FROM paper_decisions WHERE run_id = ?", (result.run_id,)
        ).fetchone()[0]

    assert run["status"] == "succeeded"
    assert artifact["sha256"] == hashlib.sha256(result.report_path.read_bytes()).hexdigest()
    assert narratives == 14
    assert projects >= 60
    assert dynamic_runs == 1
    assert paper_decisions == 1


def test_same_day_runs_create_distinct_immutable_reports(tmp_path: Path) -> None:
    base = Settings.from_env(Path.cwd())
    settings = replace(
        base,
        db_path=tmp_path / "data" / "test.db",
        reports_dir=tmp_path / "reports",
    )

    first = run_daily(settings, RunMode.OFFLINE)
    second = run_daily(settings, RunMode.OFFLINE)

    assert first.report_path != second.report_path
    assert first.report_path.exists()
    assert second.report_path.exists()
