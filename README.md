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

Offline mode uses versioned fixtures and makes no provider calls. It exists for development, CI, and reproducible dashboard smoke tests. Live mode requires the relevant API keys.

## Data and reports

- Local database: `data/trader_pete.db`
- Generated report: `reports/YYYY-MM-DD.html`
- Provider payloads and daily outputs are keyed to a run ID and content hash.
- Generated runtime data is ignored by Git.

## Development

```powershell
ruff check .
ruff format --check .
pytest
```

This is experimental research software, not financial advice. Crypto assets can lose most or all of their value; Phase 1 is intentionally read-only.

