from __future__ import annotations

import hashlib
import json
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


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    x_bearer_token: str | None = field(repr=False)
    etherscan_api_key: str | None = field(repr=False)
    x_enabled: bool
    x_max_queries: int
    x_posts_per_query: int

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
            x_bearer_token=os.getenv("X_BEARER_TOKEN") or None,
            etherscan_api_key=os.getenv("ETHERSCAN_API_KEY") or None,
            x_enabled=_env_bool("TRADER_PETE_X_ENABLED"),
            x_max_queries=max(0, min(10, int(os.getenv("TRADER_PETE_X_MAX_QUERIES", "4")))),
            x_posts_per_query=max(
                10,
                min(100, int(os.getenv("TRADER_PETE_X_POSTS_PER_QUERY", "20"))),
            ),
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
            "x_enabled": self.x_enabled,
            "has_x_key": bool(self.x_bearer_token),
            "has_etherscan_key": bool(self.etherscan_api_key),
            "x_max_queries": self.x_max_queries,
            "x_posts_per_query": self.x_posts_per_query,
        }


@dataclass(frozen=True, slots=True)
class StrategyPolicy:
    version: str
    policy_hash: str
    policy_json: str
    minimum_prospective_days: int
    paper_initial_cash_usd: float
    maximum_open_positions: int
    maximum_deployed_nav_pct: float
    maximum_position_nav_pct: float
    maximum_initial_risk_nav_pct: float
    maximum_new_entries_per_rolling_7d: int
    spot_only: bool
    human_confirmation_required: bool
    automatic_order_execution: bool
    approval_ttl_hours: int
    maximum_quote_age_seconds: int
    maximum_approval_price_move_pct: float
    paper_horizon_days: int
    maximum_round_trip_cost_pct: float
    maximum_spread_pct: float
    maximum_one_way_impact_pct: float
    maximum_depth_utilization_pct: float
    minimum_depth_multiple: float
    minimum_quality_coverage_pct: float
    minimum_seriousness_score: float
    minimum_project_market_age_days: int
    minimum_float_pct: float
    maximum_fdv_to_market_cap: float
    maximum_next_35d_unlock_pct_of_circulating: float
    minimum_rsi_14: float
    maximum_rsi_14: float
    maximum_atr_14_pct: float
    maximum_price_above_ma20_pct: float
    maximum_candidates_per_run: int
    dynamic_entry_states: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> StrategyPolicy:
        raw = path.read_bytes()
        data = json.loads(raw)
        return cls(
            version=str(data["version"]),
            policy_hash=hashlib.sha256(raw).hexdigest(),
            policy_json=raw.decode("utf-8"),
            minimum_prospective_days=int(data["minimum_prospective_days"]),
            paper_initial_cash_usd=float(data["paper_initial_cash_usd"]),
            maximum_open_positions=int(data["maximum_open_positions"]),
            maximum_deployed_nav_pct=float(data["maximum_deployed_nav_pct"]),
            maximum_position_nav_pct=float(data["maximum_position_nav_pct"]),
            maximum_initial_risk_nav_pct=float(data["maximum_initial_risk_nav_pct"]),
            maximum_new_entries_per_rolling_7d=int(data["maximum_new_entries_per_rolling_7d"]),
            spot_only=bool(data["spot_only"]),
            human_confirmation_required=bool(data["human_confirmation_required"]),
            automatic_order_execution=bool(data["automatic_order_execution"]),
            approval_ttl_hours=int(data["approval_ttl_hours"]),
            maximum_quote_age_seconds=int(data["maximum_quote_age_seconds"]),
            maximum_approval_price_move_pct=float(data["maximum_approval_price_move_pct"]),
            paper_horizon_days=int(data["paper_horizon_days"]),
            maximum_round_trip_cost_pct=float(data["maximum_round_trip_cost_pct"]),
            maximum_spread_pct=float(data["maximum_spread_pct"]),
            maximum_one_way_impact_pct=float(data["maximum_one_way_impact_pct"]),
            maximum_depth_utilization_pct=float(data["maximum_depth_utilization_pct"]),
            minimum_depth_multiple=float(data["minimum_depth_multiple"]),
            minimum_quality_coverage_pct=float(data["minimum_quality_coverage_pct"]),
            minimum_seriousness_score=float(data["minimum_seriousness_score"]),
            minimum_project_market_age_days=int(data["minimum_project_market_age_days"]),
            minimum_float_pct=float(data["minimum_float_pct"]),
            maximum_fdv_to_market_cap=float(data["maximum_fdv_to_market_cap"]),
            maximum_next_35d_unlock_pct_of_circulating=float(
                data["maximum_next_35d_unlock_pct_of_circulating"]
            ),
            minimum_rsi_14=float(data["minimum_rsi_14"]),
            maximum_rsi_14=float(data["maximum_rsi_14"]),
            maximum_atr_14_pct=float(data["maximum_atr_14_pct"]),
            maximum_price_above_ma20_pct=float(data["maximum_price_above_ma20_pct"]),
            maximum_candidates_per_run=int(data["maximum_candidates_per_run"]),
            dynamic_entry_states=tuple(data["dynamic_entry_states"]),
        )
