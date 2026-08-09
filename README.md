# Trader Pete

Trader Pete is a narrative-first crypto research system for four-week paper-trading ideas. It creates an immutable daily evidence snapshot, detects narratives, scores their lifecycle and investability, and renders a concise single-page report. It does **not** place trades.

## Phase 1 scope

1. Collect point-in-time market and protocol data.
2. Discover overlapping crypto narratives while retaining a stable sector taxonomy.
3. Score narrative opportunity and evidence confidence separately.
4. Save all inputs, model metadata, and outputs to SQLite.
5. Render a self-contained daily HTML dashboard.

The system defaults to `NO_ACTION` when inputs are missing or stale. Project selection, paper portfolio decisions, and human-confirmed execution belong to later phases.

## Architecture

```text
providers -> immutable snapshots -> deterministic features
          -> structured narrative research -> lifecycle scores
          -> SQLite ledger -> static HTML report
```

- **Sectors** are stable, single-primary classifications used for coverage and risk.
- **Narratives** are overlapping, time-bounded opportunity hypotheses.
- **SQLite** is the source of truth; prompts never receive the entire historical ledger.
- **OpenAI** performs evidence synthesis. Deterministic Python handles validation and scoring.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Add `OPENAI_API_KEY` and a CoinGecko Demo or Pro key to `.env`. Keys are read only from the environment and are never stored in the database or report.

## Commands

```powershell
trader-pete init-db
trader-pete run-daily --offline
trader-pete run-daily
```

`doctor` prints only non-secret configuration and credential presence. `run-daily` executes one bounded pipeline and exits; an OS scheduler can call it later without embedding scheduling concerns in the research code.

## Daily workflow

1. Create an auditable run record.
2. Collect CoinGecko market/category data and the top DefiLlama protocols by TVL.
3. Preserve raw responses and normalized point-in-time records.
4. Compile a bounded context containing at most 40 assets, 30 categories, and 40 protocols.
5. Research at most three narratives using the Responses API, web search, and structured output.
6. Recalculate lifecycle and opportunity scores deterministically.
7. Render the report from the stored ledger, then mark the run successful.

The initial opportunity score is a transparent hypothesis: attention acceleration 18%, novelty 13%, catalysts 17%, market confirmation 17%, breadth 13%, fundamentals 12%, and inverse crowding risk 10%. The weights must be evaluated prospectively before they influence capital decisions.

Offline mode uses versioned fixtures and makes no provider calls. It exists for development, CI, and reproducible dashboard smoke tests. Live mode requires the relevant API keys.

## Data and reports

- Local database: `data/trader_pete.db`
- Generated report: `reports/YYYY-MM-DD.html`
- Provider payloads and daily outputs are keyed to a run ID and content hash.
- Generated runtime data is ignored by Git.

CoinGecko's current API exposes category market data and category-filtered coin markets; DefiLlama fundamentals require interpretation because USD TVL can change with asset prices even without deposits or withdrawals. Phase 1 stores the raw inputs so later features can separate price effects from flows.

## Development

```powershell
ruff check .
ruff format --check .
pytest
```

This is experimental research software, not financial advice. Crypto assets can lose most or all of their value; Phase 1 is intentionally read-only.
