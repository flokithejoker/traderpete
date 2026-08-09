from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RunMode(StrEnum):
    OFFLINE = "offline"
    LIVE = "live"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class NarrativeLifecycle(StrEnum):
    DORMANT = "dormant"
    EMERGING = "emerging"
    ACCELERATING = "accelerating"
    CROWDED = "crowded"
    FADING = "fading"
    BROKEN = "broken"


class EvidenceSource(FrozenModel):
    title: str
    url: HttpUrl
    published_at: datetime | None = None
    source_type: str = "web"
    supports: bool = True
    credibility: float = Field(ge=0, le=1)


class NarrativeSignals(FrozenModel):
    attention_acceleration: float = Field(ge=0, le=100)
    novelty: float = Field(ge=0, le=100)
    catalyst_strength: float = Field(ge=0, le=100)
    market_confirmation: float = Field(ge=0, le=100)
    breadth: float = Field(ge=0, le=100)
    fundamental_confirmation: float = Field(ge=0, le=100)
    crowding_risk: float = Field(ge=0, le=100)


class NarrativeAssessment(FrozenModel):
    narrative_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    summary: str
    lifecycle: NarrativeLifecycle
    opportunity_score: float = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=100)
    signals: NarrativeSignals
    thesis: str
    counter_thesis: str
    constituent_ids: list[str] = Field(default_factory=list)
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


class CategoryMarket(FrozenModel):
    category_id: str
    name: str
    observed_at: datetime
    market_cap_usd: float | None = None
    volume_24h_usd: float | None = None
    change_24h_pct: float | None = None


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
    payloads: list[ProviderBatch]


def utc_now() -> datetime:
    return datetime.now(UTC)
