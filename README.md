# Trader Pete

Trader Pete is a stable-narrative crypto research system for four-week paper-trading ideas. It runs
once, preserves an immutable evidence ledger in SQLite, and renders one local morning dashboard. It
does **not** place trades.

## Current state

Phase 1 now runs end to end:

1. Track the same 14 broad narratives every day from a versioned registry.
2. Collect CoinGecko market/category data plus direct coverage of every registry and trending asset.
3. Collect DefiLlama TVL, fees, revenue, and DEX-volume snapshots on the free API surface.
4. Rank projects inside each narrative by BTC-relative momentum, acceleration, liquidity, activity
   growth, breadth, attention, and overheating risk.
5. Rank narrative states deterministically as `leading`, `building`, `active`, `cooling`, or
   `dormant`; at most three can become daily research focuses, and the maximum is not a quota.
6. Use bounded OpenAI web research only for root events, narrative context, and project credibility.
7. Store every input and output and render the self-contained morning report.

The daily model cannot create or rename narratives, change scores, add unknown projects, or recommend
a trade. Registry changes are deliberate code changes, not daily model output.

## Pipeline

```text
stable narrative registry
          +
CoinGecko market/search data + DefiLlama TVL/fees/revenue/DEX volume
          ↓
deterministic project metrics, quality gates, and rankings
          ↓
stable narrative states, breadth, confidence, and focus gates
          ↓
bounded OpenAI root-event and project-credibility research
          ↓
immutable SQLite ledger → one-page local morning dashboard
```

The separation is intentional:

- Python owns taxonomy, membership, calculations, data-quality gates, scores, and ranking.
- The model investigates causes, catalysts, teams, shipped products, counter-evidence, and source
  provenance.
- The dashboard keeps measurements, research judgments, and known unknowns visibly separate.

## Setup and use

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Add `OPENAI_API_KEY` and `COINGECKO_DEMO_API_KEY` to `.env`. The CoinGecko Demo plan is sufficient for
one daily run; DefiLlama needs no key for the endpoints currently used.

```powershell
trader-pete doctor
trader-pete init-db
trader-pete run-daily --offline
trader-pete run-daily
```

- Offline mode is deterministic and makes no network calls.
- Live mode collects providers and performs the bounded web-research pass.
- Each command runs once and exits, so Windows Task Scheduler can call it daily.
- Reports are written to `reports/YYYY-MM-DD/<run-id>.html`.

## What the dashboard answers

The first view is designed for a morning check:

- BTC regime, broad market breadth, focus count, metric coverage, and freshness.
- Up to five verified root events and which stable narratives they affect.
- All 14 narratives ranked with state, seven-day performance, BTC excess return, breadth,
  fundamental growth, attention, coverage, and prior-run delta.
- Projects inside the focus narratives with price acceleration, cap/turnover, TVL growth, fee and
  revenue growth, DEX-volume growth, overheating risk, and an evidence-backed quality review.

CoinGecko trending is explicitly search popularity, not sentiment; this follows the endpoint's own
[24-hour search-trend definition](https://docs.coingecko.com/reference/trending-search). TVL is not
treated as net inflow because DefiLlama distinguishes those concepts in its
[data definitions](https://docs.llama.fi/analysts/data-definitions).

## Score v3

Project score uses available components and reweights when a family is absent:

```text
38% BTC-relative momentum and weekly acceleration
34% base-size-adjusted growth in TVL, fees, revenue, and DEX volume
18% liquidity quality
10% measured search attention
minus 22% of the overheating-risk score
```

Narrative score aggregates the top eligible project signals, breadth versus Bitcoin, fundamental
growth, and measured attention. A high score cannot become `leading` or `building` without at least
three measured projects. Focus additionally requires score, confidence, state, and coverage gates.

Small-base growth is shrunk toward neutral instead of being treated like mature economic activity.
Market snapshots older than 48 hours are excluded. These are transparent hypotheses, not trained
forecasts; they require prospective 28-day validation before they should influence capital.

## Evidence and sentiment policy

- Root URLs are canonicalized so syndicated copies do not become fake corroboration.
- Primary records, filings, governance, repositories, onchain evidence, and original reporting are
  preferred.
- A project cannot remain `credible` without verified source coverage.
- Social enthusiasm, CoinGecko trends, and price performance cannot prove project seriousness.
- Organic X sentiment, bot coordination, and AI-authored-news detection remain explicitly unknown
  until an auditable raw social feed exists.
- DefiLlama's free surface supplies TVL, fees, revenue, and volume; deeper data such as active users
  requires another provider or paid access. See the official [API SDK](https://github.com/DefiLlama/api-sdk)
  and [plan comparison](https://docs.llama.fi/pro-api).

## Ledger and integrity

- Database: `data/trader_pete.db`
- Raw provider payloads, normalized snapshots, quantitative landscape, model research, and report
  artifacts are stored separately.
- Provider payloads and HTML artifacts have SHA-256 hashes.
- Same-day runs never overwrite earlier reports.
- Schema migrations are additive; historical runs are not rewritten.
- Previous-run deltas compare only runs in the same mode.
- Credentials, reports, databases, and provider payloads are ignored by Git.

## Next phase

1. Accumulate stable daily history and measure 1/7/14/28-day narrative and project outcomes against
   Bitcoin and simple baselines.
2. Add an immutable raw event/claim ledger with first-seen time, content hash, near-duplicate cluster,
   root provenance, and contradiction tracking.
3. Add token unlocks, value capture, venue/spread depth, holder concentration, and drawdown features.
4. Add reliable users/transactions/flows from suitable free or paid sources.
5. Add paper entries and exits behind an explicit human-confirmation boundary.

An xLSTM or other time-series model should wait until this prospective ledger is large enough to beat
simple momentum and breadth baselines out of sample.

## Development

```powershell
ruff check .
ruff format --check .
pytest
```

This is experimental research software, not financial advice. Crypto assets can lose most or all of
their value.
