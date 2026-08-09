# Trader Pete

Trader Pete is a local, narrative-first crypto research system for four-week paper-trading
hypotheses. It runs once per invocation, preserves a point-in-time SQLite ledger, and renders one
self-contained morning dashboard. It does not place trades.

## How it works

Trader Pete deliberately keeps two narrative layers:

- **Stable market map:** 14 broad parent archetypes provide daily coverage and comparable history.
  They are not the boundary of discovery.
- **Dynamic radar:** bounded OpenAI web research proposes narrow mechanisms such as prediction
  markets, on-chain gambling, perp-DEX cash flow, or token launchpads. Python resolves aliases and
  membership, computes every score, logs rejected seeds, and controls promotion.

```text
CoinGecko top-1000-best-effort market/categories/search + DefiLlama TVL/fees/revenue/DEX volume
                                ↓
stable parent map + anomaly-rich discovery context
                                ↓
bounded dynamic seed extraction and web evidence
                                ↓
deterministic identity, independent-underlying breadth, persistence, and promotion gates
                                ↓
bounded event and structured project-diligence research
                                ↓
contract/supply/security + executable venue + technical entry gates
                                ↓
immutable ledger → one-page dashboard → paper proposal → human approval → simulated fill
```

The model may explain evidence, identify a narrow mechanism, and assess supplied projects. It may
not assign scores, invent entities, size positions, approve proposals, or execute orders. Python
owns every gate and paper-only decision.

## Dynamic narrative policy

Every seed is visible, including weak ones. Its identity is reused by canonical alias, mechanism
similarity, or project-membership overlap; names remain stable while new phrases become aliases.
Same-day reruns never increase persistence. Persistence is a consecutive current-episode streak,
not a lifetime count; a gap resets promotion. Recently omitted identities remain visible as
`fading` and then `dormant` instead of silently disappearing.

Lifecycle v1:

- `first_seen`: one daily observation; never trade-eligible.
- `observed`: at least two distinct daily observations but promotion gates are incomplete.
- `emerging`: two days, score ≥60, evidence coverage ≥60, at least three independent measured
  economic underlyings, ≥60% breadth
  versus BTC, at least two discovery lanes, and an auditable evidence root.
- `accelerating`: the stronger form of `emerging`, with score ≥70, evidence coverage ≥65, and non-declining
  score.
- `crowded`, `fading`, or `rejected`: deterministic risk or evidence vetoes.

Research-priority scores combine measured BTC-relative returns, breadth, protocol activity,
CoinGecko search attention, retrieved supportive evidence, and overheating risk. Only lanes
confirmed by Python can promote a seed; model-asserted lanes cannot. Missing social data is `N/A`,
not zero, and is not silently replaced by search popularity. Social diagnostics do not affect the
score. These rules need prospective testing and are not expected-return or trade-readiness
estimates.

## Project diligence and social evidence

Project research separates opportunity from seriousness and investability. Quality reviews cover:

- team identity and independently confirmed backing;
- shipped product, measured adoption/economics, and engineering delivery;
- security/governance, community quality, token value capture, and quantified 35-day unlocks;
- explicit unknowns, red flags, catalyst, and counter-thesis.

The live pass fully researches one top eligible project per day. This keeps the packet auditable,
prevents context dilution, and bounds daily model context and cost.

Each non-unknown quality dimension must link to a retrieved source already present in the review.
Unlock readiness additionally requires a dated schedule, amount, and percentage of circulating
supply; prose about tokenomics or FDV is not an unlock measurement.
Unknown dimensions remain missing rather than becoming zero; a seriousness score appears only when
at least half the dimensions are covered.

X support is intentionally unavailable in `paper-v2`. The prototype aggregation path stays
fail-closed until sanitized raw-post IDs/content hashes, query manifests, response metadata, and
retention compliance can be stored with every diagnostic. This prevents an unreproducible sentiment
number from influencing research.

Without X access the dashboard says `social sentiment unmeasured`. Free/open discovery sources can
be added later, but they must not be represented as equivalent to Crypto Twitter.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Add `OPENAI_API_KEY` and `COINGECKO_DEMO_API_KEY` to `.env`. The CoinGecko Demo key is sufficient for
the bounded daily collection. Kraken, DEX Screener, DefiLlama, and baseline GoPlus checks need no
key. Do not add an Etherscan key yet: the adapter is deliberately non-authorizing until proxy and
official-contract cross-checks are complete.

```powershell
trader-pete doctor
trader-pete init-db
trader-pete run-daily --offline
trader-pete run-daily
trader-pete paper-proposals
trader-pete approve <proposal-id>
trader-pete reject <proposal-id>
```

- Offline mode is deterministic and performs no provider or OpenAI calls.
- Live mode performs two bounded, stateless OpenAI web-research passes: configured-effort dynamic
  discovery, then low-reasoning evidence synthesis. Python performs all scoring and authorization.
- Each invocation exits, so Windows Task Scheduler can run it daily.
- Reports are written to `reports/YYYY-MM-DD/<run-id>.html`.
- `approve` binds one exact proposal, fetches the first post-approval quote, and may create a paper
  fill. It never uses exchange credentials or sends a live order.

No X key is needed in this phase. Search attention remains separate and cannot be relabelled as
social sentiment.

## Dashboard

The morning view shows, in process order:

1. BTC regime, market breadth, dynamic-radar count, social coverage, paper status, and data age.
2. Root events and dated catalysts.
3. Dynamic narrative radar with lifecycle, persistence, BTC excess, breadth, fundamentals, search,
   social coverage, evidence roots, rejection reasons, and resolved projects.
4. Stable market map for broad coverage.
5. Project explorer with measured growth and structured seriousness evidence.
6. Paper gate board: official identity binding, security, quantified supply/unlocks, value capture,
   technical entry, deterministic size, and first blocker.
7. Proposal/portfolio ledger, social diagnostics, known limits, and run ledger.

CoinGecko trending is explicitly search popularity under the endpoint's
[24-hour trend definition](https://docs.coingecko.com/reference/trending-search). TVL is not treated
as net inflow because DefiLlama distinguishes those concepts in its
[data definitions](https://docs.llama.fi/analysts/data-definitions).

## Paper-only Phase 2

Research qualification, investability, and buy eligibility are separate states. One successful
live run for the entire research-strategy lineage/date is canonical; that lineage includes the
paper policy, both prompt versions, and evaluator version. The distinct paper-policy hash binds
approvals and fills. Later reruns remain diagnostic and cannot add a new candidate. Research cohorts
freeze signal-time reference prices for 7/28-day hypothesis
measurement. Those outcomes never mix with approved, costed paper-portfolio performance.

The content-hashed `paper-v2` policy requires 30 consecutive canonical live days and every mandatory
gate to pass. `UNKNOWN` blocks a proposal. Current evidence adapters include exact CoinGecko
identity/supply, 30-day OHLC, CoinGecko-linked Kraken listing identity, Kraken L2 book walking,
contract-matched DEX Screener pools, GoPlus screening, and optional Etherscan source/proxy metadata.
CoinGecko resolution is labelled provider-resolved, not officially verified. Etherscan metadata is
screening evidence rather than a security audit or proof of issuer identity.
DEX Screener is diagnostic only because it does not provide an executable router quote or sell
simulation.

When all research, official identity, security, quantified 35-day unlock, strong value-capture,
executable-cost/depth, and
technical gates pass, Trader Pete may create at most one immutable proposal. The default synthetic
portfolio is $300: two positions maximum, 60% maximum deployment, 30% maximum position, 5% maximum
initial risk, and one filled entry per rolling seven days. Human approval expires after 12 hours
and binds the venue, pair, contract, size, stop, maximum loss, price tolerance, and packet hash.
The earliest persisted quote strictly after approval supplies the simulated fill; a bad first quote
requires a new proposal rather than letting the engine cherry-pick a better later price.

The portfolio is entry-only and unvalued in this increment: no position mark-to-market or automatic
exit exists yet. Automated paper exits and chain-specific DEX router/sell simulation are the next
execution-ledger increment. There is deliberately no live trading or exchange-secret support.

## Ledger and integrity

- Database: `data/trader_pete.db`
- Provider payloads, normalized snapshots, stable and dynamic observations, social aggregates,
  bounded prompts without configured secrets, normalized model outputs, retrieved-source manifests,
  outcomes, venue quotes, gate assessments, proposals,
  approval events, paper fills, cash movements, positions, and report hashes are stored separately.
- Sanitized request manifests, response timestamps, status codes, content types, and hashes make
  live provider acquisition replayable without storing credentials.
- `workflow_complete` means the canonical/noncanonical decision core is durably complete. Settlement,
  outcome maturation, and report rendering only consume completed runs and are separately retryable.
  A failure before core completion releases its canonical claim.
- Same-day reports never overwrite earlier reports; provider and HTML artifacts are SHA-256 hashed.
- Schema changes are additive and historical narrative membership is never rewritten.
- Credentials, databases, provider payloads, reports, and generated output are ignored by Git.

Phase 1 is operational but not statistically validated. A stable Phase 1 requires 30 consecutive
point-in-time days, seven unattended scheduled runs, source/data freshness checks, and prospective
comparison with BTC and simple momentum baselines.

## Development

```powershell
ruff check .
ruff format --check .
pytest
```

This is experimental research software, not financial advice. Crypto assets can lose most or all
of their value.
