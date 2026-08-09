# Trader Pete

Trader Pete is a narrative-first crypto research system for four-week paper-trading ideas. It runs a bounded daily workflow, preserves its evidence in SQLite, and renders one concise local HTML dashboard. It does **not** place trades.

## Current state

Phase 1 is operational:

1. Collect point-in-time CoinGecko market, category, and trending-search data.
2. Enrich trending coins outside the top-250 market-cap universe.
3. Collect the top DefiLlama protocols by TVL.
4. Build a quality-screened discovery universe from search trends, price acceleration, BTC-relative momentum, turnover, categories, and protocol growth.
5. Use OpenAI web research to discover up to six event-led, market-led, or fundamental-led candidates.
6. Deterministically normalize, verify, score, and retain all candidates while marking at most three as the shortlist.
7. Store the immutable run and render a self-contained report.

The dashboard is research-only and always displays `NO ACTION`. Project selection, paper positions, and human-confirmed execution belong to later phases.

## Architecture

```text
CoinGecko + DefiLlama
        ↓
immutable raw + normalized snapshots
        ↓
quality screens + diversified discovery features
        ↓
OpenAI candidate/event/source research
        ↓
deterministic evidence, market, breadth, and risk scoring
        ↓
SQLite ledger → one-page HTML dashboard
```

The model discovers claims, causal mechanisms, projects, catalysts, and counter-evidence. Python owns URL normalization, source-root deduplication, market and breadth calculations, evidence weighting, scale normalization, lifecycle gates, and ranking.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Add `OPENAI_API_KEY` and `COINGECKO_DEMO_API_KEY` to `.env`. The free CoinGecko Demo plan supports the endpoints used here; a paid plan is not required for one daily run. DefiLlama currently needs no key.

```powershell
trader-pete doctor
trader-pete init-db
trader-pete run-daily --offline
trader-pete run-daily
```

- `doctor` shows only non-secret settings and credential-presence flags.
- Offline mode uses fixed fixtures and makes no network calls.
- Live mode performs provider collection and OpenAI web research; the expanded research pass can take several minutes.
- Each command runs once and exits, so Windows Task Scheduler can invoke it later.

## What the dashboard means

The report separates three ideas that must not be conflated:

- **Discovery:** search popularity, new events, unusual price/turnover, and protocol growth find possible themes.
- **Confirmation:** constituent BTC-relative returns, acceleration, breadth, and mapped protocol metrics test whether a theme is moving broadly.
- **Trust and risk:** canonical source roots, publisher breadth, primary evidence, recency, contradictions, crowding, and constituent concentration control confidence.

CoinGecko trending is explicitly treated as search popularity, not organic sentiment. Syndicated links with the same root count once. Social or aggregator-only evidence cannot verify a candidate. Signals missing from the snapshot are shown as unavailable or reduce confidence; they are not silently replaced by invented precision.

One- or two-project themes remain `seed`/`nascent` candidates. A narrative needs at least three measured constituents and sufficient evidence/confirmation before it can become `emerging` or `accelerating`.

## Opportunity score v2

Available components are reweighted when a measured family is missing:

```text
12% attention acceleration (research-assessed; capped without trending confirmation)
 8% attention authenticity
11% novelty
14% catalyst strength (capped when evidence is stale or unverified)
14% BTC-relative market confirmation
11% weekly price acceleration
10% constituent breadth
10% protocol fundamental confirmation
10% evidence quality

minus 12% crowding-risk penalty
minus  8% constituent-concentration penalty
```

These weights are transparent hypotheses, not a trained prediction model. They must earn trust through prospective 28-day evaluation before influencing capital.

## Data integrity

- Database: `data/trader_pete.db`
- Report: `reports/YYYY-MM-DD/<run-id>.html`
- Every provider payload and artifact has a SHA-256 hash.
- Same-day runs never overwrite prior run artifacts.
- SQLite schema migrations are additive; historical snapshots are not rewritten.
- Failed runs remain visible in the run ledger.
- Credentials, databases, provider payloads, and reports are ignored by Git.

CoinGecko category changes are only discovery hints and are screened for missing, tiny, illiquid, and extreme rows. DefiLlama TVL changes are not treated as net flows because TVL also moves with underlying asset prices; [DefiLlama defines USD inflows separately](https://docs.llama.fi/analysts/data-definitions).

## Next phase

The next implementation phase should add:

1. An immutable raw-news/claim/event ledger with first-seen timestamps, content hashes, near-duplicate clustering, provenance roots, and contradiction tracking.
2. Daily narrative history with frozen point-in-time membership, 1/7/14/28-day capped basket returns, BTC excess return, breadth, drawdown, and constituent churn.
3. Fees, revenue, users, and flow-adjusted protocol features instead of TVL alone.
4. Project-level token value capture, liquidity, unlocks, venue availability, and downside analysis.
5. Paper entries and exits behind a human-confirmation boundary.

## Development

```powershell
ruff check .
ruff format --check .
pytest
```

This is experimental research software, not financial advice. Crypto assets can lose most or all of their value.
