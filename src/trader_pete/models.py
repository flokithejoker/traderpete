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


class EvidenceStatus(StrEnum):
    STRONG = "strong"
    MIXED = "mixed"
    WEAK = "weak"
    UNKNOWN = "unknown"


class DynamicNarrativeState(StrEnum):
    FIRST_SEEN = "first_seen"
    OBSERVED = "observed"
    EMERGING = "emerging"
    ACCELERATING = "accelerating"
    CROWDED = "crowded"
    FADING = "fading"
    DORMANT = "dormant"
    REJECTED = "rejected"


class SocialCoverage(StrEnum):
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"
    MEASURED = "measured"


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class PaperCandidateState(StrEnum):
    RESEARCH_ONLY = "research_only"
    RESEARCH_QUALIFIED = "research_qualified"
    INVESTABILITY_VERIFIED = "investability_verified"
    PROPOSABLE = "proposable"


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
        if not value.startswith(("https://", "http://", "input://trader-pete/")):
            raise ValueError("Source URL must use http or https.")
        return value

    @field_validator("root_url")
    @classmethod
    def validate_root_url(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://", "input://trader-pete/")):
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
    research_eligible: bool
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


class DynamicNarrativeDraft(FrozenModel):
    name: str
    mechanism: str
    summary: str
    parent_narrative_ids: list[str] = Field(default_factory=list)
    constituent_ids: list[str] = Field(default_factory=list)
    protocol_ids: list[str] = Field(default_factory=list)
    discovery_lanes: list[str] = Field(default_factory=list)
    catalyst: str
    event_subject: str = ""
    event_type: str = ""
    event_at: datetime | None = None
    counter_thesis: str
    aliases: list[str] = Field(default_factory=list)
    sources: list[EvidenceSource] = Field(default_factory=list)


class DailyDynamicNarrativeDraft(FrozenModel):
    as_of: datetime
    candidates: list[DynamicNarrativeDraft] = Field(default_factory=list, max_length=12)
    data_gaps: list[str] = Field(default_factory=list)


class DynamicNarrativeMetrics(FrozenModel):
    median_7d_pct: float | None = None
    median_30d_pct: float | None = None
    btc_excess_7d_pct: float | None = None
    breadth_vs_btc_pct: float | None = None
    market_confirmation: float = Field(ge=0, le=100)
    fundamental_confirmation: float | None = Field(default=None, ge=0, le=100)
    search_attention: float | None = Field(default=None, ge=0, le=100)
    social_sentiment: float | None = Field(default=None, ge=-100, le=100)
    coordination_risk: float | None = Field(default=None, ge=0, le=100)
    evidence_quality: float = Field(ge=0, le=100)
    overheat_risk: float = Field(ge=0, le=100)
    measured_asset_count: int = Field(ge=0)
    measured_underlying_count: int = Field(default=0, ge=0)
    protocol_metric_count: int = Field(ge=0)
    trending_asset_count: int = Field(ge=0)
    unique_evidence_roots: int = Field(ge=0)
    independent_event_count: int = Field(default=0, ge=0)
    lane_count: int = Field(ge=0)


class DynamicNarrativeSnapshot(FrozenModel):
    narrative_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    mechanism: str
    summary: str
    parent_narrative_ids: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    state: DynamicNarrativeState
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    persistence_days: int = Field(ge=1)
    first_seen_at: datetime
    last_seen_at: datetime
    catalyst: str
    counter_thesis: str
    constituent_ids: list[str] = Field(default_factory=list)
    protocol_ids: list[str] = Field(default_factory=list)
    discovery_lanes: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    metrics: DynamicNarrativeMetrics
    sources: list[EvidenceSource] = Field(default_factory=list)


class DynamicRadarSnapshot(FrozenModel):
    as_of: datetime
    narratives: list[DynamicNarrativeSnapshot] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


class SocialWindowMetrics(FrozenModel):
    provider: str
    target_type: str
    target_id: str
    coverage: SocialCoverage
    window_hours: int = Field(default=24, ge=1)
    observed_at: datetime | None = None
    window_start_at: datetime | None = None
    window_end_at: datetime | None = None
    right_censored: bool = False
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    raw_posts: int = Field(default=0, ge=0)
    unique_authors: int = Field(default=0, ge=0)
    original_posts: int = Field(default=0, ge=0)
    duplicate_share: float | None = Field(default=None, ge=0, le=100)
    repost_share: float | None = Field(default=None, ge=0, le=100)
    author_concentration: float | None = Field(default=None, ge=0, le=100)
    source_entropy: float | None = Field(default=None, ge=0, le=100)
    timing_burstiness: float | None = Field(default=None, ge=0, le=100)
    coordination_risk: float | None = Field(default=None, ge=0, le=100)
    positive_share: float | None = Field(default=None, ge=0, le=100)
    negative_share: float | None = Field(default=None, ge=0, le=100)
    sentiment_score: float | None = Field(default=None, ge=-100, le=100)
    limitation: str = ""


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
    event_subject: str = ""
    event_type: str = ""
    event_at: datetime | None = None
    narrative_ids: list[str]
    sources: list[EvidenceSource] = Field(default_factory=list, max_length=2)


class NarrativeUpdate(FrozenModel):
    narrative_id: str
    why_now: str
    counterpoint: str
    sources: list[EvidenceSource] = Field(default_factory=list, max_length=3)


class ProjectQualityDimension(FrozenModel):
    status: EvidenceStatus
    reason: str
    evidence_urls: list[str] = Field(default_factory=list, max_length=2)


class ProjectQualityAssessment(FrozenModel):
    identity_and_team: ProjectQualityDimension
    funding_and_backing: ProjectQualityDimension
    product_delivery: ProjectQualityDimension
    adoption_and_economics: ProjectQualityDimension
    engineering_health: ProjectQualityDimension
    security_and_governance: ProjectQualityDimension
    community_quality: ProjectQualityDimension
    token_value_capture: ProjectQualityDimension
    token_supply_and_unlocks: ProjectQualityDimension = Field(
        default_factory=lambda: ProjectQualityDimension(
            status=EvidenceStatus.UNKNOWN,
            reason="No verified supply or unlock evidence was supplied.",
        )
    )
    next_35d_unlock_pct_of_circulating: float | None = Field(default=None, ge=0)
    next_35d_unlock_amount: float | None = Field(default=None, ge=0)
    largest_unlock_at: datetime | None = None
    unlock_schedule_source_url: str | None = None
    seriousness_score: float | None = Field(default=None, ge=0, le=100)
    quality_coverage: float = Field(default=0, ge=0, le=100)
    unknowns: list[str] = Field(default_factory=list, max_length=3)
    red_flags: list[str] = Field(default_factory=list, max_length=3)


class ProjectReview(FrozenModel):
    narrative_id: str
    project_id: str
    verdict: ProjectVerdict
    mission: str
    team_and_backing: str
    product_traction: str
    community_quality: str
    catalyst: str
    risks: list[str] = Field(default_factory=list, max_length=2)
    sources: list[EvidenceSource] = Field(default_factory=list, max_length=2)
    quality: ProjectQualityAssessment | None = None


class DailyLandscapeResearch(FrozenModel):
    as_of: datetime
    market_summary: str
    key_events: list[MarketEvent] = Field(default_factory=list, max_length=2)
    narrative_updates: list[NarrativeUpdate] = Field(default_factory=list, max_length=3)
    project_reviews: list[ProjectReview] = Field(default_factory=list, max_length=1)
    data_gaps: list[str] = Field(default_factory=list, max_length=6)


class ProviderBatch(FrozenModel):
    provider: str
    endpoint: str
    observed_at: datetime
    payload: list[object] | dict[str, object]
    request_params_hash: str | None = None
    response_received_at: datetime | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    content_type: str | None = None
    request_manifest: list[dict[str, object]] = Field(default_factory=list)


class TokenIdentitySnapshot(FrozenModel):
    asset_id: str
    symbol: str
    name: str
    observed_at: datetime
    asset_platform_id: str | None = None
    chain_id: str | None = None
    contract_address: str | None = None
    contract_candidates: dict[str, str] = Field(default_factory=dict)
    resolution_provider: str = "coingecko"
    official_contract_verified: bool = False
    official_contract_source_url: str | None = None
    circulating_supply: float | None = Field(default=None, ge=0)
    total_supply: float | None = Field(default=None, ge=0)
    max_supply: float | None = Field(default=None, ge=0)
    market_cap_usd: float | None = Field(default=None, ge=0)
    fully_diluted_valuation_usd: float | None = Field(default=None, ge=0)


class OhlcCandle(FrozenModel):
    closed_at: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)


class TokenSecuritySnapshot(FrozenModel):
    asset_id: str
    provider: str
    observed_at: datetime
    chain_id: str | None = None
    contract_address: str | None = None
    coverage: SocialCoverage = SocialCoverage.UNAVAILABLE
    is_open_source: bool | None = None
    is_honeypot: bool | None = None
    cannot_buy: bool | None = None
    cannot_sell_all: bool | None = None
    is_blacklisted: bool | None = None
    hidden_owner: bool | None = None
    can_take_back_ownership: bool | None = None
    owner_change_balance: bool | None = None
    buy_tax_pct: float | None = Field(default=None, ge=0)
    sell_tax_pct: float | None = Field(default=None, ge=0)
    holder_count: int | None = Field(default=None, ge=0)
    top10_holder_pct: float | None = Field(default=None, ge=0, le=100)
    source_verified: bool | None = None
    contract_name: str | None = None
    is_proxy: bool | None = None
    proxy_implementation_address: str | None = None
    proxy_implementation_verified: bool | None = None
    limitations: list[str] = Field(default_factory=list)


class UnlockScheduleSnapshot(FrozenModel):
    asset_id: str
    provider: str
    observed_at: datetime
    source_url: str
    next_35d_unlock_pct_of_circulating: float = Field(ge=0)
    next_35d_unlock_amount: float = Field(ge=0)
    largest_unlock_at: datetime | None = None
    source_payload_hash: str = Field(min_length=64, max_length=64)
    explicit_zero_unlock: bool = False


class ValueCaptureSnapshot(FrozenModel):
    asset_id: str
    provider: str
    observed_at: datetime
    mechanism: str
    source_url: str
    source_payload_hash: str = Field(min_length=64, max_length=64)


class VenueQuoteSnapshot(FrozenModel):
    asset_id: str
    provider: str
    venue: str
    venue_type: str
    pair: str
    base_symbol: str
    quote_symbol: str
    observed_at: datetime
    chain_id: str | None = None
    contract_address: str | None = None
    pair_address: str | None = None
    pair_url: str | None = None
    executable: bool = False
    pair_online: bool | None = None
    best_bid: float | None = Field(default=None, gt=0)
    best_ask: float | None = Field(default=None, gt=0)
    mid_price: float | None = Field(default=None, gt=0)
    spread_bps: float | None = Field(default=None, ge=0)
    buy_vwap_price: float | None = Field(default=None, gt=0)
    sell_vwap_price: float | None = Field(default=None, gt=0)
    buy_impact_bps: float | None = Field(default=None, ge=0)
    sell_impact_bps: float | None = Field(default=None, ge=0)
    buy_depth_1pct_usd: float | None = Field(default=None, ge=0)
    sell_depth_1pct_usd: float | None = Field(default=None, ge=0)
    taker_fee_bps: float | None = Field(default=None, ge=0)
    estimated_round_trip_cost_bps: float | None = Field(default=None, ge=0)
    liquidity_usd: float | None = Field(default=None, ge=0)
    volume_24h_usd: float | None = Field(default=None, ge=0)
    pair_created_at: datetime | None = None
    intended_notional_usd: float = Field(gt=0)
    limitations: list[str] = Field(default_factory=list)


class InvestabilityAssetData(FrozenModel):
    asset_id: str
    identity: TokenIdentitySnapshot | None = None
    candles: list[OhlcCandle] = Field(default_factory=list)
    security: TokenSecuritySnapshot | None = None
    unlock_schedule: UnlockScheduleSnapshot | None = None
    value_capture: ValueCaptureSnapshot | None = None
    quotes: list[VenueQuoteSnapshot] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


class InvestabilityDataBundle(FrozenModel):
    observed_at: datetime
    assets: list[InvestabilityAssetData] = Field(default_factory=list)
    payloads: list[ProviderBatch] = Field(default_factory=list)


class GateResult(FrozenModel):
    name: str
    status: GateStatus
    reason: str
    evidence: dict[str, object] = Field(default_factory=dict)


class TechnicalSnapshot(FrozenModel):
    observed_at: datetime
    daily_candles: int = Field(ge=0)
    close: float | None = Field(default=None, gt=0)
    rsi_14: float | None = Field(default=None, ge=0, le=100)
    atr_14_pct: float | None = Field(default=None, ge=0)
    ma_20: float | None = Field(default=None, gt=0)
    price_above_ma20_pct: float | None = None
    stop_price: float | None = Field(default=None, gt=0)
    stop_distance_pct: float | None = Field(default=None, gt=0, lt=100)


class PaperCandidateAssessment(FrozenModel):
    narrative_id: str
    narrative_name: str
    asset_id: str
    asset_name: str
    state: PaperCandidateState
    research_priority: float = Field(ge=0, le=100)
    gates: list[GateResult]
    quote: VenueQuoteSnapshot | None = None
    diagnostic_quotes: list[VenueQuoteSnapshot] = Field(default_factory=list)
    technical: TechnicalSnapshot | None = None
    proposed_notional_usd: float | None = Field(default=None, gt=0)
    maximum_initial_loss_usd: float | None = Field(default=None, ge=0)
    reasons: list[str] = Field(default_factory=list)


class PaperEvaluation(FrozenModel):
    as_of: datetime
    policy_hash: str
    prospective_days: int = Field(ge=0)
    candidates: list[PaperCandidateAssessment] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)


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
