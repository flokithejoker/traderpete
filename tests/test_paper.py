import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trader_pete.analysis.paper import evaluate_paper_candidates
from trader_pete.config import StrategyPolicy
from trader_pete.db import Database
from trader_pete.models import (
    DailyLandscapeResearch,
    DynamicNarrativeMetrics,
    DynamicNarrativeSnapshot,
    DynamicNarrativeState,
    DynamicRadarSnapshot,
    EvidenceSource,
    EvidenceStatus,
    InvestabilityAssetData,
    InvestabilityDataBundle,
    OhlcCandle,
    ProjectQualityAssessment,
    ProjectQualityDimension,
    ProjectReview,
    ProjectVerdict,
    RunMode,
    RunStatus,
    SocialCoverage,
    TokenIdentitySnapshot,
    TokenSecuritySnapshot,
    UnlockScheduleSnapshot,
    ValueCaptureSnapshot,
    VenueQuoteSnapshot,
)


def _radar(as_of: datetime) -> DynamicRadarSnapshot:
    return DynamicRadarSnapshot(
        as_of=as_of,
        narratives=[
            DynamicNarrativeSnapshot(
                narrative_id="niche_growth",
                name="Niche growth",
                mechanism="Measured niche usage turns into token demand.",
                summary="Synthetic paper-gate fixture.",
                state=DynamicNarrativeState.EMERGING,
                score=75,
                confidence=80,
                persistence_days=3,
                first_seen_at=as_of - timedelta(days=2),
                last_seen_at=as_of,
                catalyst="A dated catalyst.",
                counter_thesis="Usage can fade.",
                constituent_ids=["alpha"],
                discovery_lanes=["market", "event"],
                metrics=DynamicNarrativeMetrics(
                    market_confirmation=75,
                    evidence_quality=80,
                    overheat_risk=20,
                    measured_asset_count=1,
                    protocol_metric_count=1,
                    trending_asset_count=0,
                    unique_evidence_roots=2,
                    lane_count=2,
                ),
            )
        ],
    )


def _research(as_of: datetime, *, with_review: bool = True) -> DailyLandscapeResearch:
    if not with_review:
        return DailyLandscapeResearch(as_of=as_of, market_summary="Test")
    source = EvidenceSource(
        title="Primary evidence",
        url="https://www.sec.gov/Archives/test-filing",
        publisher="SEC",
        source_type="filing",
        claim="Synthetic verified evidence.",
        credibility=1,
    )
    strong = ProjectQualityDimension(
        status=EvidenceStatus.STRONG,
        reason="Verified for the test.",
        evidence_urls=[source.url],
    )
    quality = ProjectQualityAssessment(
        identity_and_team=strong,
        funding_and_backing=strong,
        product_delivery=strong,
        adoption_and_economics=strong,
        engineering_health=strong,
        security_and_governance=strong,
        community_quality=strong,
        token_value_capture=strong,
        token_supply_and_unlocks=strong,
        next_35d_unlock_pct_of_circulating=1,
        next_35d_unlock_amount=0.8,
        largest_unlock_at=as_of + timedelta(days=20),
        unlock_schedule_source_url=source.url,
        seriousness_score=100,
        quality_coverage=100,
    )
    return DailyLandscapeResearch(
        as_of=as_of,
        market_summary="Test",
        project_reviews=[
            ProjectReview(
                narrative_id="niche_growth",
                project_id="alpha",
                verdict=ProjectVerdict.CREDIBLE,
                mission="Test",
                team_and_backing="Test",
                product_traction="Test",
                community_quality="Test",
                catalyst="Test",
                sources=[source],
                quality=quality,
            )
        ],
    )


def _investability(as_of: datetime) -> InvestabilityDataBundle:
    candles = []
    for index in range(30):
        close = 100 + index * 0.3 + (1 if index % 2 else -0.5)
        candles.append(
            OhlcCandle(
                closed_at=as_of - timedelta(days=29 - index),
                open=close - 0.2,
                high=close + 1,
                low=close - 1,
                close=close,
            )
        )
    identity = TokenIdentitySnapshot(
        asset_id="alpha",
        symbol="ALPHA",
        name="Alpha",
        observed_at=as_of,
        asset_platform_id="ethereum",
        chain_id="ethereum",
        contract_address="0x0000000000000000000000000000000000000001",
        contract_candidates={"ethereum": "0x0000000000000000000000000000000000000001"},
        official_contract_verified=True,
        official_contract_source_url="https://www.sec.gov/Archives/test-filing",
        circulating_supply=80,
        total_supply=100,
        market_cap_usd=80_000_000,
        fully_diluted_valuation_usd=100_000_000,
    )
    security = TokenSecuritySnapshot(
        asset_id="alpha",
        provider="goplus",
        observed_at=as_of,
        chain_id="ethereum",
        contract_address=identity.contract_address,
        coverage=SocialCoverage.MEASURED,
        is_open_source=True,
        is_honeypot=False,
        cannot_buy=False,
        cannot_sell_all=False,
        is_blacklisted=False,
        hidden_owner=False,
        can_take_back_ownership=False,
        owner_change_balance=False,
        top10_holder_pct=30,
        source_verified=True,
        is_proxy=False,
        proxy_implementation_verified=True,
    )
    quote = VenueQuoteSnapshot(
        asset_id="alpha",
        provider="kraken",
        venue="Kraken",
        venue_type="cex_spot",
        pair="ALPHA/USD",
        base_symbol="ALPHA",
        quote_symbol="USD",
        observed_at=as_of,
        chain_id="ethereum",
        contract_address=identity.contract_address,
        executable=True,
        pair_online=True,
        best_bid=108.9,
        best_ask=109.0,
        mid_price=108.95,
        spread_bps=49.9,
        buy_vwap_price=109.1,
        sell_vwap_price=108.8,
        buy_impact_bps=10,
        sell_impact_bps=10,
        buy_depth_1pct_usd=5_000,
        sell_depth_1pct_usd=5_000,
        taker_fee_bps=20,
        estimated_round_trip_cost_bps=109.8,
        intended_notional_usd=90,
    )
    unlock_schedule = UnlockScheduleSnapshot(
        asset_id="alpha",
        provider="sec-filing-adapter",
        observed_at=as_of,
        source_url="https://www.sec.gov/Archives/test-filing",
        next_35d_unlock_pct_of_circulating=1,
        next_35d_unlock_amount=0.8,
        largest_unlock_at=as_of + timedelta(days=20),
        source_payload_hash="a" * 64,
    )
    value_capture = ValueCaptureSnapshot(
        asset_id="alpha",
        provider="sec-filing-adapter",
        observed_at=as_of,
        mechanism="Verified protocol revenue is contractually distributed to the token.",
        source_url="https://www.sec.gov/Archives/test-filing",
        source_payload_hash="b" * 64,
    )
    return InvestabilityDataBundle(
        observed_at=as_of,
        assets=[
            InvestabilityAssetData(
                asset_id="alpha",
                identity=identity,
                candles=candles,
                security=security,
                unlock_schedule=unlock_schedule,
                value_capture=value_capture,
                quotes=[quote],
            )
        ],
    )


def test_unknown_project_evidence_blocks_proposal() -> None:
    as_of = datetime(2026, 8, 9, tzinfo=UTC)
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    result = evaluate_paper_candidates(
        _radar(as_of),
        _research(as_of, with_review=False),
        _investability(as_of),
        policy,
        prospective_days=30,
    )
    assert result.candidates[0].state.value == "research_only"
    assert (
        next(
            gate for gate in result.candidates[0].gates if gate.name == "project_diligence"
        ).status.value
        == "unknown"
    )


def test_mixed_value_capture_never_passes() -> None:
    as_of = datetime(2026, 8, 9, tzinfo=UTC)
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    research = _research(as_of)
    review = research.project_reviews[0]
    mixed = ProjectQualityDimension(
        status=EvidenceStatus.MIXED,
        reason="The token mechanism is disputed.",
        evidence_urls=[review.sources[0].url],
    )
    quality = review.quality.model_copy(update={"token_value_capture": mixed})
    research = research.model_copy(
        update={"project_reviews": [review.model_copy(update={"quality": quality})]}
    )

    result = evaluate_paper_candidates(
        _radar(as_of), research, _investability(as_of), policy, prospective_days=30
    )
    gate = next(item for item in result.candidates[0].gates if item.name == "token_value_capture")
    assert gate.status.value == "unknown"


def test_known_supply_failure_is_not_masked_by_unknown_unlock() -> None:
    as_of = datetime(2026, 8, 9, tzinfo=UTC)
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    research = _research(as_of)
    review = research.project_reviews[0]
    quality = review.quality.model_copy(
        update={
            "next_35d_unlock_pct_of_circulating": None,
            "unlock_schedule_source_url": None,
        }
    )
    research = research.model_copy(
        update={"project_reviews": [review.model_copy(update={"quality": quality})]}
    )
    investability = _investability(as_of)
    asset = investability.assets[0]
    identity = asset.identity.model_copy(
        update={
            "circulating_supply": 20,
            "total_supply": 100,
            "market_cap_usd": 20_000_000,
            "fully_diluted_valuation_usd": 100_000_000,
        }
    )
    investability = investability.model_copy(
        update={"assets": [asset.model_copy(update={"identity": identity})]}
    )

    result = evaluate_paper_candidates(
        _radar(as_of), research, investability, policy, prospective_days=30
    )
    gate = next(item for item in result.candidates[0].gates if item.name == "supply_transparency")
    assert gate.status.value == "fail"
    assert gate.evidence["float_pct"] == 20


def test_unlock_amount_must_reconcile_to_reported_percentage() -> None:
    as_of = datetime(2026, 8, 9, tzinfo=UTC)
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    research = _research(as_of)
    investability = _investability(as_of)
    asset = investability.assets[0]
    schedule = asset.unlock_schedule.model_copy(update={"next_35d_unlock_amount": 999_999_999})
    investability = investability.model_copy(
        update={"assets": [asset.model_copy(update={"unlock_schedule": schedule})]}
    )

    result = evaluate_paper_candidates(
        _radar(as_of), research, investability, policy, prospective_days=30
    )
    gate = next(item for item in result.candidates[0].gates if item.name == "supply_transparency")
    assert gate.status.value == "unknown"


def test_burn_in_is_a_proposal_gate_not_a_research_gate() -> None:
    as_of = datetime(2026, 8, 9, tzinfo=UTC)
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    result = evaluate_paper_candidates(
        _radar(as_of),
        _research(as_of),
        _investability(as_of),
        policy,
        prospective_days=29,
    )

    assert result.candidates[0].state.value == "investability_verified"
    assert result.candidates[0].proposed_notional_usd is None


@pytest.mark.parametrize(
    ("security_update", "expected_reason"),
    [
        ({"coverage": SocialCoverage.PARTIAL}, "incomplete"),
        ({"is_proxy": None}, "incomplete"),
        ({"top10_holder_pct": None}, "concentration"),
    ],
)
def test_partial_or_unknown_proxy_security_cannot_pass(
    security_update: dict, expected_reason: str
) -> None:
    as_of = datetime(2026, 8, 9, tzinfo=UTC)
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    investability = _investability(as_of)
    asset = investability.assets[0]
    security = asset.security.model_copy(update=security_update)
    investability = investability.model_copy(
        update={"assets": [asset.model_copy(update={"security": security})]}
    )

    result = evaluate_paper_candidates(
        _radar(as_of), _research(as_of), investability, policy, prospective_days=30
    )
    gate = next(item for item in result.candidates[0].gates if item.name == "contract_security")
    assert gate.status.value == "unknown"
    assert expected_reason in gate.reason.lower()


def test_stale_initial_quote_cannot_pass_liquidity() -> None:
    as_of = datetime(2026, 8, 9, tzinfo=UTC)
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    investability = _investability(as_of)
    asset = investability.assets[0]
    stale_quote = asset.quotes[0].model_copy(
        update={"observed_at": as_of - timedelta(seconds=policy.maximum_quote_age_seconds + 1)}
    )
    investability = investability.model_copy(
        update={"assets": [asset.model_copy(update={"quotes": [stale_quote]})]}
    )

    result = evaluate_paper_candidates(
        _radar(as_of), _research(as_of), investability, policy, prospective_days=30
    )
    gate = next(item for item in result.candidates[0].gates if item.name == "executable_liquidity")
    assert gate.status.value == "unknown"


def test_all_mandatory_gates_can_form_human_approval_packet(tmp_path: Path) -> None:
    as_of = datetime.now(UTC)
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    radar = _radar(as_of)
    research = _research(as_of)
    investability = _investability(as_of)
    evaluation = evaluate_paper_candidates(
        radar,
        research,
        investability,
        policy,
        prospective_days=30,
    )
    assert evaluation.candidates[0].state.value == "proposable"

    database = Database(tmp_path / "paper.db")
    database.initialize()
    run_id = database.create_run(as_of=as_of, mode=RunMode.LIVE, config={})
    database.store_dynamic_research(
        run_id=run_id,
        radar=radar,
        result=research,
        social_metrics=[],
        model="test",
        reasoning_effort="low",
        prompt_version="paper-test",
        prompt="test",
        response_id=None,
        policy=policy,
        run_mode=RunMode.LIVE,
    )
    database.store_paper_evidence(
        run_id=run_id,
        investability=investability,
        evaluation=evaluation,
        policy=policy,
    )
    database.finish_run(run_id, RunStatus.SUCCEEDED)
    canonical = database.finalize_canonical_run(run_id)
    proposal_id = database.finalize_paper_decision(
        run_id=run_id,
        evaluation=evaluation,
        policy=policy,
        is_canonical=canonical,
        run_mode=RunMode.LIVE,
    )

    assert proposal_id
    with pytest.raises(ValueError, match="exact active policy hash"):
        database.record_proposal_response(proposal_id, approve=True)
    with pytest.raises(ValueError, match="different strategy policy"):
        database.record_proposal_response(
            proposal_id, approve=True, expected_policy_hash="stale-policy"
        )
    database.record_proposal_response(
        proposal_id, approve=True, expected_policy_hash=policy.policy_hash
    )
    assert database.list_paper_proposals(active_only=True)[0]["status"] == "APPROVED"
    with pytest.raises(ValueError, match="already APPROVED"):
        database.record_proposal_response(
            proposal_id, approve=True, expected_policy_hash=policy.policy_hash
        )

    preapproval_quote_run = database.create_run(
        as_of=as_of, mode=RunMode.LIVE, config={"purpose": "preapproval-quote"}
    )
    database.store_venue_quotes(
        run_id=preapproval_quote_run,
        investability=investability,
    )
    database.finish_run(preapproval_quote_run, RunStatus.SUCCEEDED)
    assert not database.settle_approved_entries(
        quote_run_id=preapproval_quote_run,
        policy=policy,
        proposal_id=proposal_id,
    )

    time.sleep(0.01)
    postapproval = _investability(datetime.now(UTC))
    quote_run = database.create_run(
        as_of=datetime.now(UTC), mode=RunMode.LIVE, config={"purpose": "paper-quote"}
    )
    database.store_venue_quotes(run_id=quote_run, investability=postapproval)
    database.finish_run(quote_run, RunStatus.SUCCEEDED)
    time.sleep(0.01)
    later_quote_run = database.create_run(
        as_of=datetime.now(UTC), mode=RunMode.LIVE, config={"purpose": "later-paper-quote"}
    )
    database.store_venue_quotes(
        run_id=later_quote_run, investability=_investability(datetime.now(UTC))
    )
    database.finish_run(later_quote_run, RunStatus.SUCCEEDED)
    fills = database.settle_approved_entries(
        quote_run_id=later_quote_run,
        policy=policy,
        proposal_id=proposal_id,
    )
    assert len(fills) == 1
    with database.connect() as connection:
        fill_run_id = connection.execute(
            "SELECT fill_run_id FROM paper_fills WHERE id = ?", (fills[0],)
        ).fetchone()[0]
    assert fill_run_id == quote_run
    assert not database.list_paper_proposals(active_only=True)


def test_fill_rechecks_position_cap_and_actual_stop_risk(tmp_path: Path) -> None:
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    database = Database(tmp_path / "paper.db")
    database.initialize()
    now = datetime.now(UTC)
    base_proposal = {
        "policy_hash": policy.policy_hash,
        "contract_address": "0x1",
        "maximum_entry_price": 120,
        "stop_price": 80,
        "maximum_initial_loss_usd": 15,
    }
    quote = {
        "observed_at": now.isoformat(),
        "executable": True,
        "pair_online": True,
        "contract_address": "0x1",
        "buy_vwap_price": 100,
        "estimated_round_trip_cost_bps": 100,
        "buy_depth_1pct_usd": 100_000,
        "sell_depth_1pct_usd": 100_000,
    }
    with database.connect() as connection:
        cap_rejection = database._fill_rejection_reason(
            connection,
            {**base_proposal, "proposed_quantity": 0.91},
            quote,
            policy,
            now,
        )
        risk_rejection = database._fill_rejection_reason(
            connection,
            {**base_proposal, "proposed_quantity": 0.8, "stop_price": 70},
            quote,
            policy,
            now,
        )
        packet_rejection = database._fill_rejection_reason(
            connection,
            {
                **base_proposal,
                "proposed_quantity": 0.4,
                "stop_price": 90,
                "maximum_initial_loss_usd": 4,
            },
            quote,
            policy,
            now,
        )
    assert "position" in cap_rejection
    assert "maximum-loss" in risk_rejection
    assert "maximum-loss" in packet_rejection


def test_running_quote_run_cannot_settle_a_paper_fill(tmp_path: Path) -> None:
    policy = StrategyPolicy.load(Path.cwd() / "config/strategy_policy.json")
    database = Database(tmp_path / "paper.db")
    database.initialize()
    run_id = database.create_run(
        as_of=datetime.now(UTC), mode=RunMode.LIVE, config={"purpose": "paper-quote"}
    )

    with pytest.raises(ValueError, match="completed succeeded"):
        database.settle_approved_entries(quote_run_id=run_id, policy=policy)
