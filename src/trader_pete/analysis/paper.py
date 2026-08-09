from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean

from trader_pete.analysis.economic import economic_underlying_key, wrapper_issuer_key
from trader_pete.analysis.scoring import is_authoritative_url
from trader_pete.config import StrategyPolicy
from trader_pete.models import (
    DailyLandscapeResearch,
    DynamicRadarSnapshot,
    EvidenceStatus,
    GateResult,
    GateStatus,
    InvestabilityAssetData,
    InvestabilityDataBundle,
    InvestmentCaseStage,
    MarketDataBundle,
    PaperCandidateAssessment,
    PaperCandidateState,
    PaperEvaluation,
    ProjectReview,
    ProjectVerdict,
    TechnicalSnapshot,
    VenueQuoteSnapshot,
)

RESEARCH_GATES = {
    "narrative_state",
    "narrative_evidence",
    "project_diligence",
    "narrative_fit",
    "team_accountability",
    "product_delivery",
    "traction_quality",
    "token_value_case",
    "supply_case",
    "catalyst_window",
    "investment_case",
}
CASE_GATES = {
    "narrative_evidence",
    "project_diligence",
    "narrative_fit",
    "team_accountability",
    "product_delivery",
    "traction_quality",
    "token_value_case",
    "supply_case",
    "catalyst_window",
    "investment_case",
}
INVESTABILITY_GATES = {
    "asset_identity",
    "contract_security",
    "supply_transparency",
    "token_value_capture",
    "executable_liquidity",
}


def select_investability_assets(
    radar: DynamicRadarSnapshot,
    research: DailyLandscapeResearch,
    market: MarketDataBundle,
    policy: StrategyPolicy,
    *,
    required_asset_ids: list[str] | None = None,
) -> list[str]:
    """Select a bounded diligence set without applying a market-cap minimum."""
    reviews = {(item.narrative_id, item.project_id): item for item in research.project_reviews}
    market_by_id = {item.asset_id: item for item in market.assets}
    required = list(dict.fromkeys(required_asset_ids or []))
    required_set = set(required)
    state_rank = {
        "accelerating": 5,
        "emerging": 4,
        "observed": 3,
        "first_seen": 2,
        "crowded": 1,
    }
    verdict_rank = {
        ProjectVerdict.CREDIBLE: 4,
        ProjectVerdict.MIXED: 3,
        ProjectVerdict.SPECULATIVE: 2,
        ProjectVerdict.INSUFFICIENT: 1,
    }
    ranked_narratives = sorted(
        (
            item
            for item in radar.narratives
            if state_rank.get(item.state.value, 0) >= state_rank["first_seen"]
        ),
        key=lambda item: (state_rank.get(item.state.value, 0), item.score),
        reverse=True,
    )
    per_narrative: dict[str, list[tuple[tuple[float, ...], str, str, str]]] = {}
    for narrative in ranked_narratives:
        candidates: list[tuple[tuple[float, ...], str, str, str]] = []
        for asset_id in narrative.constituent_ids:
            review = reviews.get((narrative.narrative_id, asset_id))
            quality = review.quality if review else None
            asset = market_by_id.get(asset_id)
            if not asset:
                continue
            candidates.append(
                (
                    (
                        float(state_rank.get(narrative.state.value, 0)),
                        float(verdict_rank.get(review.verdict, 0) if review else 0),
                        float(quality.seriousness_score or 0) if quality else 0,
                        narrative.score,
                        float(asset.change_7d_pct or -10_000) if asset else -10_000,
                    ),
                    asset_id,
                    economic_underlying_key(
                        asset_id=asset.asset_id, name=asset.name, symbol=asset.symbol
                    ),
                    wrapper_issuer_key(asset_id=asset.asset_id, name=asset.name),
                )
            )
        per_narrative[narrative.narrative_id] = sorted(
            candidates, key=lambda value: value[0], reverse=True
        )

    selected: list[str] = []
    seen_underlyings = {
        economic_underlying_key(
            asset_id=asset_id,
            name=market_by_id[asset_id].name,
            symbol=market_by_id[asset_id].symbol,
        )
        for asset_id in required
        if asset_id in market_by_id
    }
    issuer_counts: dict[str, int] = defaultdict(int)
    narrative_counts: dict[str, int] = defaultdict(int)
    cursors: dict[str, int] = defaultdict(int)
    while len(selected) < policy.maximum_candidates_per_run:
        made_progress = False
        for narrative in ranked_narratives:
            narrative_id = narrative.narrative_id
            rows = per_narrative.get(narrative_id, [])
            while cursors[narrative_id] < len(rows):
                _, asset_id, underlying, issuer = rows[cursors[narrative_id]]
                cursors[narrative_id] += 1
                if (
                    asset_id in required_set
                    or asset_id in selected
                    or underlying in seen_underlyings
                    or issuer_counts[issuer] >= 2
                    or narrative_counts[narrative_id] >= 2
                ):
                    continue
                selected.append(asset_id)
                seen_underlyings.add(underlying)
                issuer_counts[issuer] += 1
                narrative_counts[narrative_id] += 1
                made_progress = True
                break
            if len(selected) >= policy.maximum_candidates_per_run:
                break
        if not made_progress:
            break
    # Quote refreshes for open positions/approved packets are operational and do not consume the
    # bounded new-discovery diligence budget.
    return [*required, *selected]


def evaluate_paper_candidates(
    radar: DynamicRadarSnapshot,
    research: DailyLandscapeResearch,
    investability: InvestabilityDataBundle,
    policy: StrategyPolicy,
    *,
    prospective_days: int,
) -> PaperEvaluation:
    data_by_asset = {item.asset_id: item for item in investability.assets}
    reviews = {(item.narrative_id, item.project_id): item for item in research.project_reviews}
    narrative_by_asset = {}
    for narrative in radar.narratives:
        for asset_id in narrative.constituent_ids:
            if asset_id in data_by_asset:
                review = reviews.get((narrative.narrative_id, asset_id))
                quality = review.quality if review else None
                rank = (
                    review is not None,
                    float(quality.quality_coverage if quality else 0),
                    float(quality.seriousness_score or 0) if quality else 0,
                    narrative.score,
                )
                previous = narrative_by_asset.get(asset_id)
                if previous is None or rank > previous[0]:
                    narrative_by_asset[asset_id] = (rank, narrative)

    candidates = []
    gaps = []
    for asset_id, data in data_by_asset.items():
        selected = narrative_by_asset.get(asset_id)
        if not selected:
            gaps.extend(data.data_gaps)
            continue
        narrative = selected[1]
        review = reviews.get((narrative.narrative_id, asset_id))
        assessment = _assess(
            narrative=narrative,
            data=data,
            review=review,
            policy=policy,
            prospective_days=prospective_days,
            as_of=investability.observed_at,
        )
        candidates.append(assessment)
        gaps.extend(data.data_gaps)
    candidates.sort(
        key=lambda value: (
            value.state is PaperCandidateState.PROPOSABLE,
            value.state is PaperCandidateState.INVESTABILITY_VERIFIED,
            value.state is PaperCandidateState.RESEARCH_QUALIFIED,
            value.research_priority,
        ),
        reverse=True,
    )
    return PaperEvaluation(
        as_of=investability.observed_at,
        policy_hash=policy.policy_hash,
        prospective_days=prospective_days,
        candidates=candidates,
        data_gaps=list(dict.fromkeys(gaps)),
    )


def _assess(
    *,
    narrative,
    data: InvestabilityAssetData,
    review: ProjectReview | None,
    policy: StrategyPolicy,
    prospective_days: int,
    as_of: datetime,
) -> PaperCandidateAssessment:
    gates: list[GateResult] = []
    gates.append(
        _gate(
            "burn_in",
            prospective_days >= policy.minimum_prospective_days,
            (
                f"{prospective_days}/{policy.minimum_prospective_days} canonical live days."
                if prospective_days < policy.minimum_prospective_days
                else f"Prospective burn-in reached {prospective_days} days."
            ),
            {"prospective_days": prospective_days},
        )
    )
    gates.append(
        _gate(
            "narrative_state",
            narrative.state.value in policy.dynamic_entry_states,
            f"State is {narrative.state.value}; allowed states are {policy.dynamic_entry_states}.",
            {"state": narrative.state.value, "persistence_days": narrative.persistence_days},
        )
    )
    evidence_ok = narrative.metrics.unique_evidence_roots >= 2 and narrative.metrics.lane_count >= 2
    gates.append(
        _gate(
            "narrative_evidence",
            evidence_ok,
            (
                f"{narrative.metrics.unique_evidence_roots} supportive roots and "
                f"{narrative.metrics.lane_count} confirmed lanes."
            ),
            {
                "supportive_roots": narrative.metrics.unique_evidence_roots,
                "confirmed_lanes": narrative.metrics.lane_count,
            },
        )
    )
    quality = review.quality if review else None
    diligence_known = bool(
        review
        and review.verdict in {ProjectVerdict.CREDIBLE, ProjectVerdict.MIXED}
        and quality
        and quality.quality_coverage >= policy.minimum_quality_coverage_pct
        and float(quality.seriousness_score or 0) >= policy.minimum_seriousness_score
    )
    diligence_status = (
        GateStatus.PASS
        if diligence_known
        else GateStatus.UNKNOWN
        if not review
        else GateStatus.FAIL
    )
    gates.append(
        GateResult(
            name="project_diligence",
            status=diligence_status,
            reason=(
                "No current structured project review."
                if not review
                else (
                    f"Verdict {review.verdict.value}; coverage "
                    f"{quality.quality_coverage if quality else 0}%; seriousness "
                    f"{quality.seriousness_score if quality else None}."
                )
            ),
            evidence={"verdict": review.verdict.value if review else "unreviewed"},
        )
    )
    gates.append(
        _quality_dimension_gate(
            "narrative_fit",
            quality.narrative_fit if quality else None,
            "No sourced mechanism binds this project and token to the narrative.",
        )
    )
    gates.append(
        _quality_dimension_gate(
            "team_accountability",
            quality.identity_and_team if quality else None,
            "No sourced team identity or accountability evidence was verified.",
        )
    )
    gates.append(
        _quality_dimension_gate(
            "product_delivery",
            quality.product_delivery if quality else None,
            "No sourced evidence of a shipped, usable product was verified.",
        )
    )
    gates.append(
        _quality_dimension_gate(
            "traction_quality",
            quality.adoption_and_economics if quality else None,
            "No sourced adoption or economic growth trend was verified.",
        )
    )
    gates.append(
        _quality_dimension_gate(
            "token_value_case",
            quality.token_value_capture if quality else None,
            "No sourced mechanism connects project economics to tokenholder value.",
            require_strong=True,
        )
    )
    gates.append(
        _quality_dimension_gate(
            "supply_case",
            quality.token_supply_and_unlocks if quality else None,
            "No sourced circulating-supply and near-term unlock assessment was verified.",
            require_strong=True,
        )
    )
    gates.append(_catalyst_gate(review, as_of))

    identity = data.identity
    is_token = bool(identity and (identity.asset_platform_id or identity.contract_candidates))
    identity_ok = bool(
        identity
        and identity.symbol
        and (not is_token or (identity.chain_id and identity.contract_address))
    )
    gates.append(
        GateResult(
            name="asset_identity",
            status=GateStatus.PASS if identity_ok else GateStatus.UNKNOWN,
            reason=(
                f"CoinGecko resolved {identity.chain_id}:{identity.contract_address}, but an "
                "official project/issuer source has not independently bound it."
                if identity_ok and is_token and not identity.official_contract_verified
                else f"Officially cross-checked {identity.chain_id}:{identity.contract_address}."
                if identity_ok and is_token
                else "Resolved as a native asset."
                if identity_ok
                else "Exact chain and contract identity are unresolved."
            ),
            evidence={
                "chain_id": identity.chain_id if identity else None,
                "contract_address": identity.contract_address if identity else None,
                "resolution_provider": identity.resolution_provider if identity else None,
                "official_contract_verified": (
                    identity.official_contract_verified if identity else False
                ),
                "contract_candidates": identity.contract_candidates if identity else {},
            },
        )
    )
    if is_token and identity and not identity.official_contract_verified:
        gates[-1] = gates[-1].model_copy(update={"status": GateStatus.UNKNOWN})

    security = data.security
    if not is_token:
        security_status = GateStatus.PASS
        security_reason = "Native asset; token-contract screening does not apply."
    elif not security or security.coverage.value == "unavailable":
        security_status = GateStatus.UNKNOWN
        security_reason = "No supported contract-security snapshot."
    else:
        critical = {
            "honeypot": security.is_honeypot,
            "cannot_buy": security.cannot_buy,
            "cannot_sell_all": security.cannot_sell_all,
            "blacklisted": security.is_blacklisted,
            "hidden_owner": security.hidden_owner,
            "can_take_back_ownership": security.can_take_back_ownership,
            "owner_change_balance": security.owner_change_balance,
        }
        unknown_critical = [name for name, value in critical.items() if value is None]
        failed = [name for name, value in critical.items() if value is True]
        source_unknown = security.source_verified is not True
        coverage_unknown = security.coverage.value != "measured"
        proxy_status_unknown = security.is_proxy is None
        proxy_unknown = (
            security.is_proxy is True and security.proxy_implementation_verified is not True
        )
        concentration_unknown = security.top10_holder_pct is None or security.top10_holder_pct >= 80
        if failed or security.is_open_source is False or security.source_verified is False:
            security_status = GateStatus.FAIL
        elif (
            unknown_critical
            or coverage_unknown
            or proxy_status_unknown
            or security.is_open_source is not True
            or source_unknown
            or proxy_unknown
            or concentration_unknown
        ):
            security_status = GateStatus.UNKNOWN
        else:
            security_status = GateStatus.PASS
        security_reason = (
            f"Critical flags: {', '.join(failed)}."
            if failed
            else f"Unknown checks: {', '.join(unknown_critical)}."
            if unknown_critical
            else (
                "All required source, proxy, admin, tax, and holder-concentration checks passed."
                if security_status is GateStatus.PASS
                else "Contract screening is incomplete: source/proxy/admin or concentration review."
            )
        )
    gates.append(
        GateResult(
            name="contract_security",
            status=security_status,
            reason=security_reason,
            evidence=security.model_dump(mode="json") if security else {},
        )
    )

    gates.append(_supply_gate(data, quality, policy, as_of))
    gates.append(_value_capture_gate(data, quality))
    quote, liquidity_gate = _liquidity_gate(data.quotes, policy, as_of)
    gates.append(liquidity_gate)
    technical, technical_gate = _technical_gate(data, policy, as_of)
    gates.append(technical_gate)

    case = _investment_case(narrative, review, gates)
    case_gate_status = (
        GateStatus.PASS
        if case[0] >= policy.minimum_investment_case_score
        and case[1] >= policy.minimum_investment_case_coverage_pct
        else GateStatus.UNKNOWN
        if case[1] < policy.minimum_investment_case_coverage_pct
        else GateStatus.FAIL
    )
    gates.append(
        GateResult(
            name="investment_case",
            status=case_gate_status,
            reason=(
                f"Case score {case[0]:.1f}/100 with {case[1]:.1f}% decision coverage; "
                f"requires {policy.minimum_investment_case_score:.0f} and "
                f"{policy.minimum_investment_case_coverage_pct:.0f}%."
            ),
            evidence={"score": case[0], "coverage_pct": case[1], "components": case[2]},
        )
    )
    case_ready = narrative.state.value in policy.investment_case_states and _all_pass(
        gates, CASE_GATES
    )
    paper_research_ready = case_ready and _all_pass(gates, RESEARCH_GATES)
    investability_ready = case_ready and _all_pass(gates, INVESTABILITY_GATES)
    technical_ready = technical_gate.status is GateStatus.PASS
    burn_in_ready = gates[0].status is GateStatus.PASS
    if paper_research_ready and investability_ready and technical_ready and burn_in_ready:
        state = PaperCandidateState.PROPOSABLE
    elif investability_ready:
        state = PaperCandidateState.INVESTABILITY_VERIFIED
    elif case_ready:
        state = PaperCandidateState.RESEARCH_QUALIFIED
    else:
        state = PaperCandidateState.RESEARCH_ONLY
    if state is PaperCandidateState.PROPOSABLE:
        case_stage = InvestmentCaseStage.PAPER_READY
    elif case_ready and investability_ready and technical_ready:
        case_stage = InvestmentCaseStage.SHADOW_READY
    elif case_ready:
        case_stage = InvestmentCaseStage.WORTHY_CASE
    elif (
        narrative.state.value == "first_seen"
        and _gate_status(gates, "narrative_evidence") is GateStatus.PASS
        and _gate_status(gates, "project_diligence") is GateStatus.PASS
        and _gate_status(gates, "narrative_fit") is GateStatus.PASS
        and _gate_status(gates, "product_delivery") is GateStatus.PASS
        and _gate_status(gates, "catalyst_window") is GateStatus.PASS
        and not any(
            gate.status is GateStatus.FAIL
            for gate in gates
            if gate.name in CASE_GATES and gate.name != "investment_case"
        )
        and case[0] >= policy.minimum_investment_case_score * 0.75
        and case[1] >= 50
    ):
        case_stage = InvestmentCaseStage.EARLY_LEAD
    else:
        case_stage = InvestmentCaseStage.DEVELOPING

    proposed_notional = None
    maximum_loss = None
    reasons = [gate.reason for gate in gates if gate.status is not GateStatus.PASS]
    if (
        state is PaperCandidateState.PROPOSABLE
        and technical
        and technical.stop_price
        and quote
        and quote.buy_vwap_price
        and quote.estimated_round_trip_cost_bps is not None
    ):
        decision_stop_distance = (
            (quote.buy_vwap_price - technical.stop_price) / quote.buy_vwap_price * 100
        )
        if decision_stop_distance <= 0:
            reasons = [*reasons, "The executable entry quote is already below the planned stop."]
            return PaperCandidateAssessment(
                narrative_id=narrative.narrative_id,
                narrative_name=narrative.name,
                asset_id=data.asset_id,
                asset_name=identity.name if identity else data.asset_id,
                state=PaperCandidateState.INVESTABILITY_VERIFIED if investability_ready else state,
                research_priority=narrative.score,
                case_stage=InvestmentCaseStage.SHADOW_READY,
                case_score=case[0],
                case_coverage_pct=case[1],
                case_summary=case[3],
                case_components=case[2],
                case_strengths=case[4],
                case_risks=case[5],
                invalidation=case[6],
                gates=gates,
                quote=quote,
                diagnostic_quotes=[item for item in data.quotes if not item.executable],
                technical=technical,
                reasons=reasons,
            )
        position_cap = policy.paper_initial_cash_usd * policy.maximum_position_nav_pct / 100
        risk_budget = policy.paper_initial_cash_usd * policy.maximum_initial_risk_nav_pct / 100
        stressed_loss_fraction = (
            decision_stop_distance / 100 + quote.estimated_round_trip_cost_bps / 10_000
        )
        proposed_notional = round(min(position_cap, risk_budget / stressed_loss_fraction), 2)
        maximum_loss = round(proposed_notional * stressed_loss_fraction, 2)
    return PaperCandidateAssessment(
        narrative_id=narrative.narrative_id,
        narrative_name=narrative.name,
        asset_id=data.asset_id,
        asset_name=identity.name if identity else data.asset_id,
        state=state,
        research_priority=narrative.score,
        case_stage=case_stage,
        case_score=case[0],
        case_coverage_pct=case[1],
        case_summary=case[3],
        case_components=case[2],
        case_strengths=case[4],
        case_risks=case[5],
        invalidation=case[6],
        gates=gates,
        quote=quote,
        diagnostic_quotes=[item for item in data.quotes if not item.executable],
        technical=technical,
        proposed_notional_usd=proposed_notional,
        maximum_initial_loss_usd=maximum_loss,
        reasons=reasons,
    )


def _quality_dimension_gate(
    name, dimension, unknown_reason: str, *, require_strong: bool = False
) -> GateResult:
    if not dimension or dimension.status is EvidenceStatus.UNKNOWN:
        return GateResult(
            name=name,
            status=GateStatus.UNKNOWN,
            reason=unknown_reason,
            evidence={"research_status": "unknown", "urls": []},
        )
    passing = (
        dimension.status is EvidenceStatus.STRONG
        if require_strong
        else dimension.status in {EvidenceStatus.STRONG, EvidenceStatus.MIXED}
    )
    status = GateStatus.PASS if passing else GateStatus.FAIL
    return GateResult(
        name=name,
        status=status,
        reason=dimension.reason,
        evidence={
            "research_status": dimension.status.value,
            "urls": dimension.evidence_urls,
        },
    )


def _catalyst_gate(review: ProjectReview | None, as_of: datetime) -> GateResult:
    if not review or not review.catalyst_at or not review.catalyst_evidence_urls:
        return GateResult(
            name="catalyst_window",
            status=GateStatus.UNKNOWN,
            reason="No sourced, dated project catalyst was verified inside the next 28 days.",
            evidence={},
        )
    catalyst_at = _as_utc(review.catalyst_at)
    decision_at = _as_utc(as_of)
    days_until = (catalyst_at - decision_at).total_seconds() / 86_400
    in_window = 0 <= days_until <= 28
    return GateResult(
        name="catalyst_window",
        status=GateStatus.PASS if in_window else GateStatus.FAIL,
        reason=(
            f"{review.catalyst} ({days_until:.1f} days from the decision)."
            if in_window
            else "The sourced project catalyst is outside the four-week decision horizon."
        ),
        evidence={
            "catalyst_at": catalyst_at.isoformat(),
            "days_until": round(days_until, 2),
            "urls": review.catalyst_evidence_urls,
        },
    )


def _investment_case(narrative, review, gates):
    gate_map = {item.name: item for item in gates}
    quality = review.quality if review else None

    def gate_component(names: tuple[str, ...]) -> tuple[float, float]:
        selected = [gate_map[name] for name in names if name in gate_map]
        known = [item for item in selected if item.status is not GateStatus.UNKNOWN]
        if not selected:
            return 0.0, 0.0
        value = sum(item.status is GateStatus.PASS for item in selected) / len(selected) * 100
        coverage = len(known) / len(selected) * 100
        return value, coverage

    seriousness = float(quality.seriousness_score or 0) if quality else 0.0
    quality_coverage = float(quality.quality_coverage) if quality else 0.0
    component_specs = {
        "narrative_priority": (20.0, float(narrative.score), 100.0),
        "narrative_evidence": (
            10.0,
            *gate_component(("narrative_evidence",)),
        ),
        "project_quality": (
            20.0,
            seriousness * quality_coverage / 100,
            quality_coverage,
        ),
        "narrative_fit": (15.0, *gate_component(("narrative_fit",))),
        "traction": (15.0, *gate_component(("traction_quality",))),
        "catalyst": (10.0, *gate_component(("catalyst_window",))),
        "token_economics": (5.0, *gate_component(("token_value_case", "supply_case"))),
        "entry_quality": (
            5.0,
            *gate_component(("executable_liquidity", "technical_entry")),
        ),
    }
    components = {
        name: {
            "weight": weight,
            "value": round(value, 1),
            "coverage_pct": round(coverage, 1),
        }
        for name, (weight, value, coverage) in component_specs.items()
    }
    score = round(sum(weight * value / 100 for weight, value, _ in component_specs.values()), 1)
    coverage = round(sum(weight * known / 100 for weight, _, known in component_specs.values()), 1)
    strengths = [f"Narrative research priority {narrative.score:.1f}/100."]
    for name in (
        "narrative_evidence",
        "narrative_fit",
        "team_accountability",
        "product_delivery",
        "traction_quality",
        "token_value_case",
        "supply_case",
        "catalyst_window",
    ):
        gate = gate_map.get(name)
        if gate and gate.status is GateStatus.PASS:
            strengths.append(gate.reason)
    risks = list(review.risks if review else [])
    if quality:
        risks.extend(quality.red_flags)
    for name in (
        "supply_transparency",
        "token_value_capture",
        "executable_liquidity",
        "technical_entry",
    ):
        gate = gate_map.get(name)
        if gate and gate.status is not GateStatus.PASS:
            risks.append(gate.reason)
    summary = (
        review.investment_thesis.strip()
        if review and review.investment_thesis.strip()
        else "No falsifiable four-week project thesis has been verified yet."
    )
    invalidation = (
        review.invalidation if review and review.invalidation else [narrative.counter_thesis]
    )
    return (
        score,
        coverage,
        components,
        summary,
        list(dict.fromkeys(strengths))[:5],
        list(dict.fromkeys(risks))[:5],
        list(dict.fromkeys(invalidation))[:3],
    )


def _supply_gate(data, quality, policy: StrategyPolicy, as_of: datetime) -> GateResult:
    identity = data.identity
    supply_dimension = quality.token_supply_and_unlocks if quality else None
    schedule = data.unlock_schedule
    unlock_pct = schedule.next_35d_unlock_pct_of_circulating if schedule else None
    unlock_amount = schedule.next_35d_unlock_amount if schedule else None
    largest_unlock_at = schedule.largest_unlock_at if schedule else None
    unlock_source = schedule.source_url if schedule else None
    recomputed_pct = (
        unlock_amount / identity.circulating_supply * 100
        if identity and identity.circulating_supply and unlock_amount is not None
        else None
    )
    consistency_tolerance = max(0.1, abs(float(unlock_pct or 0)) * 0.05)
    amount_consistent = bool(
        unlock_pct is not None
        and unlock_amount is not None
        and recomputed_pct is not None
        and abs(recomputed_pct - unlock_pct) <= consistency_tolerance
    )
    date_consistent = bool(
        unlock_amount == 0
        or (
            largest_unlock_at is not None
            and as_of < largest_unlock_at <= as_of + timedelta(days=35)
        )
    )
    zero_confirmed = bool(
        unlock_pct != 0 or (unlock_amount == 0 and schedule and schedule.explicit_zero_unlock)
    )
    unlock_known = bool(
        schedule
        and schedule.asset_id == data.asset_id
        and schedule.provider.lower() not in {"openai", "llm", "model"}
        and len(schedule.source_payload_hash) == 64
        and unlock_pct is not None
        and unlock_source
        and is_authoritative_url(unlock_source)
        and amount_consistent
        and date_consistent
        and zero_confirmed
    )
    circulating = identity.circulating_supply if identity else None
    denominator = (identity.max_supply or identity.total_supply) if identity else None
    float_pct = circulating / denominator * 100 if circulating and denominator else None
    fdv_ratio = (
        identity.fully_diluted_valuation_usd / identity.market_cap_usd
        if identity
        and identity.fully_diluted_valuation_usd
        and identity.market_cap_usd
        and identity.market_cap_usd > 0
        else None
    )
    known_threshold_failure = float_pct is not None and (
        float_pct < policy.minimum_float_pct
        or (fdv_ratio is not None and fdv_ratio > policy.maximum_fdv_to_market_cap)
    )
    if known_threshold_failure or (
        unlock_pct is not None and unlock_pct > policy.maximum_next_35d_unlock_pct_of_circulating
    ):
        status = GateStatus.FAIL
    elif not unlock_known or float_pct is None:
        status = GateStatus.UNKNOWN
    elif float_pct < policy.minimum_float_pct or (
        fdv_ratio is not None and fdv_ratio > policy.maximum_fdv_to_market_cap
    ):
        status = GateStatus.FAIL
    else:
        status = GateStatus.PASS
    float_text = f"{float_pct:.1f}%" if float_pct is not None else "unknown"
    fdv_text = f"{fdv_ratio:.2f}x" if fdv_ratio is not None else "unknown"
    unlock_text = (
        f"{unlock_pct:.2f}% of circulating" if unlock_known else "unavailable/unquantified"
    )
    return GateResult(
        name="supply_transparency",
        status=status,
        reason=(
            f"Float {float_text}; FDV/cap {fdv_text}; quantified next-35d unlock {unlock_text}."
        ),
        evidence={
            "float_pct": round(float_pct, 2) if float_pct is not None else None,
            "fdv_to_market_cap": round(fdv_ratio, 2) if fdv_ratio is not None else None,
            "next_35d_unlock_pct": unlock_pct,
            "next_35d_unlock_amount": unlock_amount,
            "recomputed_unlock_pct": (
                round(recomputed_pct, 4) if recomputed_pct is not None else None
            ),
            "largest_unlock_at": largest_unlock_at.isoformat() if largest_unlock_at else None,
            "schedule_source_primary": bool(unlock_source and is_authoritative_url(unlock_source)),
            "schedule_provider": schedule.provider if schedule else None,
            "source_payload_hash": schedule.source_payload_hash if schedule else None,
            "research_schedule_status": (
                supply_dimension.status.value if supply_dimension else "unknown"
            ),
            "unlock_schedule_source_url": unlock_source,
        },
    )


def _value_capture_gate(data: InvestabilityAssetData, quality) -> GateResult:
    dimension = quality.token_value_capture if quality else None
    attestation = data.value_capture
    verified = bool(
        attestation
        and dimension
        and dimension.status is EvidenceStatus.STRONG
        and attestation.asset_id == data.asset_id
        and attestation.provider.lower() not in {"openai", "llm", "model"}
        and attestation.mechanism.strip()
        and len(attestation.source_payload_hash) == 64
        and is_authoritative_url(attestation.source_url)
    )
    status = GateStatus.PASS if verified else GateStatus.UNKNOWN
    return GateResult(
        name="token_value_capture",
        status=status,
        reason=(
            attestation.mechanism
            if verified and attestation
            else "Model diligence is context only; no deterministic value-capture attestation."
        ),
        evidence={
            "research_status": dimension.status.value if dimension else "unknown",
            "urls": dimension.evidence_urls if dimension else [],
            "attestation_provider": attestation.provider if attestation else None,
            "attestation_source_url": attestation.source_url if attestation else None,
            "source_payload_hash": attestation.source_payload_hash if attestation else None,
        },
    )


def _liquidity_gate(
    quotes: list[VenueQuoteSnapshot], policy: StrategyPolicy, as_of: datetime
) -> tuple[VenueQuoteSnapshot | None, GateResult]:
    executable = [
        item
        for item in quotes
        if item.executable
        and item.pair_online
        and item.estimated_round_trip_cost_bps is not None
        and 0 <= (as_of - item.observed_at).total_seconds() <= policy.maximum_quote_age_seconds
    ]
    if not executable:
        return None, GateResult(
            name="executable_liquidity",
            status=GateStatus.UNKNOWN,
            reason=(
                "No fresh executable order-book quote; DEX analytics alone cannot authorize a buy."
            ),
            evidence={"observed_routes": len(quotes)},
        )
    quote = min(executable, key=lambda item: float(item.estimated_round_trip_cost_bps))
    required_depth = quote.intended_notional_usd * policy.minimum_depth_multiple
    checks = {
        "spread": _missing_high(quote.spread_bps) <= policy.maximum_spread_pct * 100,
        "buy_impact": _missing_high(quote.buy_impact_bps)
        <= policy.maximum_one_way_impact_pct * 100,
        "sell_impact": _missing_high(quote.sell_impact_bps)
        <= policy.maximum_one_way_impact_pct * 100,
        "round_trip": _missing_high(quote.estimated_round_trip_cost_bps)
        <= policy.maximum_round_trip_cost_pct * 100,
        "buy_depth": float(quote.buy_depth_1pct_usd or 0) >= required_depth,
        "sell_depth": float(quote.sell_depth_1pct_usd or 0) >= required_depth,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return quote, GateResult(
        name="executable_liquidity",
        status=GateStatus.FAIL if failed else GateStatus.PASS,
        reason=(
            f"{quote.venue} {quote.pair}: spread {float(quote.spread_bps or 0) / 100:.2f}%, "
            f"round trip {float(quote.estimated_round_trip_cost_bps or 0) / 100:.2f}%; "
            f"failed {', '.join(failed) if failed else 'none'}."
        ),
        evidence=quote.model_dump(mode="json"),
    )


def _technical_gate(
    data: InvestabilityAssetData, policy: StrategyPolicy, as_of: datetime
) -> tuple[TechnicalSnapshot | None, GateResult]:
    daily = _daily_candles(data, as_of)
    required_days = max(21, policy.minimum_project_market_age_days)
    if len(daily) < required_days:
        return None, GateResult(
            name="technical_entry",
            status=GateStatus.UNKNOWN,
            reason=(
                f"Only {len(daily)} closed UTC daily candles; {required_days} are required "
                "for indicator and minimum-market-age coverage."
            ),
            evidence={"daily_candles": len(daily)},
        )
    closes = [row[3] for row in daily]
    highs = [row[1] for row in daily]
    lows = [row[2] for row in daily]
    rsi = _rsi(closes, 14)
    atr = _atr(highs, lows, closes, 14)
    close = closes[-1]
    ma20 = mean(closes[-20:])
    atr_pct = atr / close * 100 if atr else None
    above_ma = (close / ma20 - 1) * 100
    stop_distance = min(20.0, max(8.0, float(atr_pct or 0) * 2))
    technical = TechnicalSnapshot(
        observed_at=as_of,
        daily_candles=len(daily),
        close=close,
        rsi_14=rsi,
        atr_14_pct=atr_pct,
        ma_20=ma20,
        price_above_ma20_pct=above_ma,
        stop_price=close * (1 - stop_distance / 100),
        stop_distance_pct=stop_distance,
    )
    if rsi is None or atr_pct is None:
        status = GateStatus.UNKNOWN
        failed = ["indicator_coverage"]
    else:
        checks = {
            "above_ma20": close >= ma20,
            "rsi_band": policy.minimum_rsi_14 <= rsi <= policy.maximum_rsi_14,
            "atr": atr_pct <= policy.maximum_atr_14_pct,
            "not_extended": above_ma <= policy.maximum_price_above_ma20_pct,
        }
        failed = [name for name, passed in checks.items() if not passed]
        status = GateStatus.FAIL if failed else GateStatus.PASS
    return technical, GateResult(
        name="technical_entry",
        status=status,
        reason=(
            f"RSI14 {rsi:.1f}, ATR14 {atr_pct:.1f}%, price vs MA20 {above_ma:+.1f}%; "
            f"failed {', '.join(failed) if failed else 'none'}."
            if rsi is not None and atr_pct is not None
            else "Technical indicators are incomplete."
        ),
        evidence=technical.model_dump(mode="json"),
    )


def _daily_candles(
    data: InvestabilityAssetData, as_of: datetime
) -> list[tuple[float, float, float, float]]:
    grouped: dict[str, list] = defaultdict(list)
    for candle in sorted(data.candles, key=lambda value: value.closed_at):
        grouped[candle.closed_at.astimezone(UTC).date().isoformat()].append(candle)
    result = []
    for day in sorted(grouped):
        if day >= as_of.astimezone(UTC).date().isoformat():
            continue
        rows = grouped[day]
        result.append(
            (
                rows[0].open,
                max(value.high for value in rows),
                min(value.low for value in rows),
                rows[-1].close,
            )
        )
    return result


def _rsi(closes: list[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    changes = [
        current - previous for previous, current in zip(closes[:-1], closes[1:], strict=True)
    ]
    sample = changes[-period:]
    gains = sum(max(0, value) for value in sample) / period
    losses = sum(max(0, -value) for value in sample) / period
    if losses == 0:
        return 100.0
    relative = gains / losses
    return 100 - 100 / (1 + relative)


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    true_ranges = [
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(1, len(closes))
    ]
    return mean(true_ranges[-period:])


def _gate(name: str, passed: bool, reason: str, evidence: dict[str, object]) -> GateResult:
    return GateResult(
        name=name,
        status=GateStatus.PASS if passed else GateStatus.FAIL,
        reason=reason,
        evidence=evidence,
    )


def _missing_high(value: float | None) -> float:
    return 100_000.0 if value is None else float(value)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _gate_status(gates: list[GateResult], name: str) -> GateStatus | None:
    return next((item.status for item in gates if item.name == name), None)


def _all_pass(gates: list[GateResult], names: set[str]) -> bool:
    selected = [item for item in gates if item.name in names]
    return len(selected) == len(names) and all(item.status is GateStatus.PASS for item in selected)
