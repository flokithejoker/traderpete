from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without overwriting the process environment."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True, slots=True)
class Settings:
    root_dir: Path
    db_path: Path
    reports_dir: Path
    model: str
    reasoning_effort: str
    max_narratives: int
    candidate_narratives: int
    currency: str
    openai_api_key: str | None = field(repr=False)
    coingecko_demo_api_key: str | None = field(repr=False)
    coingecko_pro_api_key: str | None = field(repr=False)

    @classmethod
    def from_env(cls, root_dir: Path | None = None) -> Settings:
        root = (root_dir or Path.cwd()).resolve()
        _load_dotenv(root / ".env")
        db_path = Path(os.getenv("TRADER_PETE_DB_PATH", root / "data/trader_pete.db"))
        reports_dir = Path(os.getenv("TRADER_PETE_REPORTS_DIR", root / "reports"))
        return cls(
            root_dir=root,
            db_path=db_path.resolve(),
            reports_dir=reports_dir.resolve(),
            model=os.getenv("TRADER_PETE_MODEL", "gpt-5.6-sol"),
            reasoning_effort=os.getenv("TRADER_PETE_REASONING_EFFORT", "medium"),
            max_narratives=int(os.getenv("TRADER_PETE_MAX_NARRATIVES", "3")),
            candidate_narratives=int(os.getenv("TRADER_PETE_CANDIDATE_NARRATIVES", "6")),
            currency=os.getenv("TRADER_PETE_CURRENCY", "usd").lower(),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            coingecko_demo_api_key=os.getenv("COINGECKO_DEMO_API_KEY") or None,
            coingecko_pro_api_key=os.getenv("COINGECKO_PRO_API_KEY") or None,
        )

    def safe_dict(self) -> dict[str, object]:
        """Return reproducibility settings with secrets reduced to presence flags."""
        return {
            "db_path": str(self.db_path),
            "reports_dir": str(self.reports_dir),
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "max_narratives": self.max_narratives,
            "candidate_narratives": self.candidate_narratives,
            "currency": self.currency,
            "has_openai_key": bool(self.openai_api_key),
            "has_coingecko_key": bool(self.coingecko_demo_api_key or self.coingecko_pro_api_key),
        }
