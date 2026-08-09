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
deterministic identity, score, breadth, persistence, and promotion gates
                                ↓
bounded event and structured project-diligence research
                                ↓
immutable SQLite ledger → one-page local dashboard → prospective 7/28-day outcomes
```

The model may explain evidence, identify a narrow mechanism, and assess supplied projects. It may
not assign scores, invent entities, create trades, choose allocations, or execute orders.

## Dynamic narrative policy

Every seed is visible, including weak ones. Its identity is reused by canonical alias, mechanism
similarity, or project-membership overlap; names remain stable while new phrases become aliases.
Same-day reruns never increase persistence. Persistence is a consecutive current-episode streak,
not a lifetime count; a gap resets promotion. Recently omitted identities remain visible as
`fading` and then `dormant` instead of silently disappearing.

Lifecycle v1:

- `first_seen`: one daily observation; never trade-eligible.
- `observed`: at least two distinct daily observations but promotion gates are incomplete.
- `emerging`: two days, score ≥60, confidence ≥60, at least three measured assets, ≥60% breadth
  versus BTC, at least two discovery lanes, and an auditable evidence root.
- `accelerating`: the stronger form of `emerging`, with score ≥70, confidence ≥65, and non-declining
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
- security/governance, community quality, and token value capture;
- explicit unknowns, red flags, catalyst, and counter-thesis.

Each non-unknown quality dimension must link to a retrieved source already present in the review.
Unknown dimensions remain missing rather than becoming zero; a seriousness score appears only when
at least half the dimensions are covered.

X support is optional and off by default because the API is pay-per-use. When explicitly enabled,
the provider uses an explicit, capped 24-hour recent-search sample and reports post count, unique authors,
duplicate/repost share, author concentration, domain diversity, burstiness, dictionary stance, and
**coordination risk**. The result is labelled partial/right-censored where applicable and never
claims to identify individual bots, measure the full population, or prove organic demand.

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
the current bounded daily collection; the used DefiLlama endpoints need no key.

```powershell
trader-pete doctor
trader-pete init-db
trader-pete run-daily --offline
trader-pete run-daily
```

- Offline mode is deterministic and performs no provider or OpenAI calls.
- Live mode performs two bounded, stateless OpenAI web-research passes: dynamic discovery, then
  market-event/project diligence.
- Each invocation exits, so Windows Task Scheduler can run it daily.
- Reports are written to `reports/YYYY-MM-DD/<run-id>.html`.

Optional X collection requires conscious spend approval:

```dotenv
X_BEARER_TOKEN=...
TRADER_PETE_X_ENABLED=true
TRADER_PETE_X_MAX_QUERIES=4
TRADER_PETE_X_POSTS_PER_QUERY=20
```

## Dashboard

The morning view shows, in process order:

1. BTC regime, market breadth, dynamic-radar count, social coverage, paper status, and data age.
2. Root events and dated catalysts.
3. Dynamic narrative radar with lifecycle, persistence, BTC excess, breadth, fundamentals, search,
   social coverage, evidence roots, rejection reasons, and resolved projects.
4. Stable market map for broad coverage.
5. Project explorer with measured growth and structured seriousness evidence.
6. Social diagnostics, prospective Phase 2 status, known limits, and run ledger.

CoinGecko trending is explicitly search popularity under the endpoint's
[24-hour trend definition](https://docs.coingecko.com/reference/trending-search). TVL is not treated
as net inflow because DefiLlama distinguishes those concepts in its
[data definitions](https://docs.llama.fi/analysts/data-definitions).

## Prospective Phase 2 start

Phase 2 currently observes; it does not propose or fill trades. One successful live run per
narrative and calendar day becomes the canonical observation; reruns remain diagnostic. Each cohort
freezes membership and signal-time reference prices—not executable fills. Later runs append 7-day
and 28-day hypothesis returns only inside a 36-hour tolerance and only with complete constituent
price coverage. Missing assets never disappear from the median. No historical web reconstruction
is used.

The loaded and content-hashed `paper-v1` policy in `config/strategy_policy.json` requires at least 30 consecutive live canonical daily
observations before eligibility, at most two positions, at most 60% deployed, at most 30% per
position, at most one new entry per rolling seven days, spot only, and human confirmation. Even
after 30 days, project-level venue liquidity, spread/slippage, unlock, contract, security, and value
capture gates must exist before an entry engine is enabled.

## Ledger and integrity

- Database: `data/trader_pete.db`
- Provider payloads, normalized snapshots, stable and dynamic observations, social aggregates,
  research prompts, cohorts, outcomes, and report hashes are stored separately.
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
