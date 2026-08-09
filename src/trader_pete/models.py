from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RunMode(StrEnum):
    OFFLINE = "offline"
    LIVE = "live"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class NarrativeState(StrEnum):
    LEADING = "leading"
    BUILDING = "building"
    ACTIVE = "active"
    COOLING = "cooling"
    DORMANT = "dormant"


class ActivityMetricType(StrEnum):
    FEES = "fees"
    REVENUE = "revenue"
    DEX_VOLUME = "dex_volume"


class ProjectVerdict(StrEnum):
    CREDIBLE = "credible"
    MIXED = "mixed"
    SPECULATIVE = "speculative"
    INSUFFICIENT = "insufficient"


class NarrativeLifecycle(StrEnum):
    SEED = "seed"
    NASCENT = "nascent"
    DORMANT = "dormant"
    EMERGING = "emerging"
    ACCELERATING = "accelerating"
    CROWDED = "crowded"
    FADING = "fading"
    BROKEN = "broken"


class EvidenceSource(FrozenModel):
    title: str
    url: str
    published_at: datetime | None = None
    source_type: str = "web"
    publisher: str = ""
    root_url: str = ""
    claim: str = ""
    is_primary: bool = False
    supports: bool = True
    credibility: float = Field(ge=0, le=1)

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("Source URL must use http or https.")
        return value

    @field_validator("root_url")
    @classmethod
    def validate_root_url(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("Root source URL must be empty or use http or https.")
        return value


class NarrativeSignals(FrozenModel):
    attention_acceleration: float = Field(ge=0, le=100)
    attention_authenticity: float = Field(default=0, ge=0, le=100)
    novelty: float = Field(ge=0, le=100)
    catalyst_strength: float = Field(ge=0, le=100)
    market_confirmation: float = Field(ge=0, le=100)
    price_acceleration: float = Field(default=0, ge=0, le=100)
    breadth: float = Field(ge=0, le=100)
    fundamental_confirmation: float = Field(ge=0, le=100)
    evidence_quality: float = Field(default=0, ge=0, le=100)
    crowding_risk: float = Field(ge=0, le=100)
    concentration_risk: float = Field(default=0, ge=0, le=100)


class NarrativeAssessment(FrozenModel):
    narrative_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    summary: str
    lifecycle: NarrativeLifecycle
    opportunity_score: float = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=100)
    is_shortlisted: bool = False
    signals: NarrativeSignals
    thesis: str
    counter_thesis: str
    constituent_ids: list[str] = Field(default_factory=list)
    protocol_ids: list[str] = Field(default_factory=list)
    metric_coverage: dict[str, int] = Field(default_factory=dict)
    sources: list[EvidenceSource] = Field(default_factory=list)


class NarrativeResearchDraft(FrozenModel):
    narrative_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    summary: str
    confidence_score: float = Field(ge=0, le=100)
    signals: NarrativeSignals
    thesis: str
    counter_thesis: str
    constituent_ids: list[str] = Field(default_factory=list)
    protocol_ids: list[str] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)


class DailyResearchDraft(FrozenModel):
    as_of: datetime
    market_regime: str
    narratives: list[NarrativeResearchDraft]
    data_gaps: list[str] = Field(default_factory=list)


class DailyNarrativeResearch(FrozenModel):
    as_of: datetime
    market_regime: str
    narratives: list[NarrativeAssessment]
    data_gaps: list[str] = Field(default_factory=list)


class MarketAsset(FrozenModel):
    asset_id: str
    symbol: str
    name: str
    observed_at: datetime
    price_usd: float | None = None
    market_cap_usd: float | None = None
    volume_24h_usd: float | None = None
    change_24h_pct: float | None = None
    change_7d_pct: float | None = None
    change_30d_pct: float | None = None
    primary_sector: str | None = None


class TrendingAsset(FrozenModel):
    asset_id: str
    symbol: str
    name: str
    observed_at: datetime
    search_rank: int = Field(ge=1)
    market_cap_rank: int | None = Field(default=None, ge=1)


class CategoryMarket(FrozenModel):
    category_id: str
    name: str
    observed_at: datetime
    market_cap_usd: float | None = None
    volume_24h_usd: float | None = None
    change_24h_pct: float | None = None
    top_asset_ids: list[str] = Field(default_factory=list)


class ProtocolMetric(FrozenModel):
    protocol_id: str
    name: str
    category: str | None = None
    observed_at: datetime
    tvl_usd: float | None = None
    change_1d_pct: float | None = None
    change_7d_pct: float | None = None
    change_30d_pct: float | None = None
    chains: list[str] = Field(default_factory=list)


class ProtocolActivityMetric(FrozenModel):
    protocol_id: str
    name: str
    category: str | None = None
    metric_type: ActivityMetricType
    observed_at: datetime
    total_24h_usd: float | None = None
    total_7d_usd: float | None = None
    total_30d_usd: float | None = None
    growth_1d_pct: float | None = None
    growth_7d_pct: float | None = None
    growth_30d_pct: float | None = None


class NarrativeProjectDefinition(FrozenModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    asset_id: str
    protocol_ids: list[str] = Field(default_factory=list)


class NarrativeDefinition(FrozenModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    description: str
    kpi_profile: str
    aliases: list[str] = Field(default_factory=list)
    category_ids: list[str] = Field(default_factory=list)
    projects: list[NarrativeProjectDefinition]


class ProjectMetrics(FrozenModel):
    market_data_age_hours: float | None = Field(default=None, ge=0)
    price_7d_pct: float | None = None
    price_30d_pct: float | None = None
    btc_excess_7d_pct: float | None = None
    price_acceleration: float | None = None
    market_cap_usd: float | None = None
    volume_24h_usd: float | None = None
    turnover_24h: float | None = None
    tvl_usd: float | None = None
    tvl_growth_7d_pct: float | None = None
    fees_7d_usd: float | None = None
    fees_growth_7d_pct: float | None = None
    revenue_7d_usd: float | None = None
    revenue_growth_7d_pct: float | None = None
    dex_volume_7d_usd: float | None = None
    dex_volume_growth_7d_pct: float | None = None
    fundamental_growth_score: float | None = Field(default=None, ge=0, le=100)
    liquidity_score: float | None = Field(default=None, ge=0, le=100)
    overheat_risk: float = Field(ge=0, le=100)
    is_trending: bool = False
    coverage: int = Field(ge=0)


class ProjectSnapshot(FrozenModel):
    narrative_id: str
    project_id: str
    name: str
    asset_id: str
    rank: int = Field(ge=1)
    score: float = Field(ge=0, le=100)
    eligible: bool
    metrics: ProjectMetrics
    selection_notes: list[str] = Field(default_factory=list)


class NarrativeMetrics(FrozenModel):
    median_7d_pct: float | None = None
    median_30d_pct: float | None = None
    btc_excess_7d_pct: float | None = None
    breadth_vs_btc_pct: float | None = None
    fundamental_growth_score: float | None = Field(default=None, ge=0, le=100)
    category_change_24h_pct: float | None = None
    attention_score: float = Field(ge=0, le=100)
    median_overheat_risk: float = Field(ge=0, le=100)
    project_count: int = Field(ge=0)
    measured_project_count: int = Field(ge=0)
    economic_metric_count: int = Field(ge=0)
    trending_project_count: int = Field(ge=0)


class StableNarrativeSnapshot(FrozenModel):
    narrative_id: str
    name: str
    description: str
    kpi_profile: str
    rank: int = Field(ge=1)
    state: NarrativeState
    is_focus: bool = False
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    metrics: NarrativeMetrics


class LandscapeSnapshot(FrozenModel):
    as_of: datetime
    market_regime: str
    narratives: list[StableNarrativeSnapshot]
    projects: list[ProjectSnapshot]
    data_gaps: list[str] = Field(default_factory=list)


class MarketEvent(FrozenModel):
    title: str
    why_it_matters: str
    direction: str
    horizon: str
    narrative_ids: list[str]
    sources: list[EvidenceSource] = Field(default_factory=list)


class NarrativeUpdate(FrozenModel):
    narrative_id: str
    why_now: str
    counterpoint: str
    sources: list[EvidenceSource] = Field(default_factory=list)


class ProjectReview(FrozenModel):
    narrative_id: str
    project_id: str
    verdict: ProjectVerdict
    mission: str
    team_and_backing: str
    product_traction: str
    community_quality: str
    catalyst: str
    risks: list[str] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)


class DailyLandscapeResearch(FrozenModel):
    as_of: datetime
    market_summary: str
    key_events: list[MarketEvent] = Field(default_factory=list, max_length=5)
    narrative_updates: list[NarrativeUpdate] = Field(default_factory=list)
    project_reviews: list[ProjectReview] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


class ProviderBatch(FrozenModel):
    provider: str
    endpoint: str
    observed_at: datetime
    payload: list[dict[str, object]] | dict[str, object]


class MarketDataBundle(FrozenModel):
    observed_at: datetime
    assets: list[MarketAsset]
    categories: list[CategoryMarket]
    protocols: list[ProtocolMetric]
    protocol_activity: list[ProtocolActivityMetric] = Field(default_factory=list)
    trending_assets: list[TrendingAsset] = Field(default_factory=list)
    payloads: list[ProviderBatch]


def utc_now() -> datetime:
    return datetime.now(UTC)
