# Trader Pete repository guidance

- Use Python 3.12 and keep the architecture dependency-light.
- Treat SQLite snapshots as immutable point-in-time evidence. Add new rows; do not rewrite history.
- Keep collection, scoring, model judgment, and presentation separated.
- Never add order execution or live trading without an explicit user request and a human approval boundary.
- Never commit credentials, generated databases, raw provider payloads, or generated reports.
- Update `README.md` whenever commands, configuration, providers, or the daily workflow change.
- Before committing, run `ruff check .`, `ruff format --check .`, and `pytest`.

