from pathlib import Path

from trader_pete.config import Settings


def test_settings_defaults_are_safe(tmp_path: Path, monkeypatch) -> None:
    for key in (
        "OPENAI_API_KEY",
        "COINGECKO_DEMO_API_KEY",
        "COINGECKO_PRO_API_KEY",
        "TRADER_PETE_DB_PATH",
        "TRADER_PETE_REPORTS_DIR",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env(tmp_path)

    assert settings.model == "gpt-5.6-sol"
    assert settings.db_path == (tmp_path / "data/trader_pete.db").resolve()
    assert settings.safe_dict()["has_openai_key"] is False
    assert "openai_api_key" not in settings.safe_dict()
