# Repository Guidelines

## Project Structure & Module Organization
Core library code lives in `src/trading_strategy/`. Use `core/` for reusable signal, risk, exit, and state logic; use `live/` for Hyperliquid runtime code such as CLI flow, order handling, exchange sync, and persistence. App-style entrypoints live in `apps/`, especially `apps/runners/live_runner.py` and `apps/runners/paper_runner.py`. Backtest scripts live in `backtest/`. Tests are currently concentrated in `tests/test_live.py`. Runtime data and historical fixtures live under `data/`; treat live state files there as generated artifacts, not hand-edited source.

## Build, Test, and Development Commands
Create an environment and install dependencies with `pip install -r requirements.txt`.

- `python -m unittest tests.test_live` runs the current regression suite.
- `python -m compileall src tests` catches syntax and import-level issues quickly.
- `python apps/runners/paper_runner.py` starts paper trading.
- `python apps/runners/live_runner.py --live` runs one live cycle.
- `python apps/runners/live_runner.py --live --loop` runs the live loop.
- `python backtest/backtest_runner.py --coins BTC,ETH --strategy trend --max-days 240` runs a representative backtest.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, `snake_case` for functions and variables, `UPPER_SNAKE_CASE` for module constants, and short, focused helper functions. Keep modules narrow in responsibility; live-trading exchange calls belong in `live/`, not `core/`. Match the repository preference for plain standard-library testing and minimal abstraction. There is no dedicated formatter config in the repo, so keep edits consistent with surrounding code.

## Testing Guidelines
Add or update `unittest` coverage for behavior changes, especially in `tests/test_live.py` when touching live execution, reconciliation, TP/SL protection, or order normalization. Name new tests `test_<behavior>`. Prefer mocks over network calls and verify emitted summaries or state mutations, not just happy-path returns.

## Commit & Pull Request Guidelines
Recent commits use short imperative subjects such as `Refactor live runtime into package` and `Fix live position adoption and TP/SL protection`. Keep commit titles concise, capitalized, and action-oriented. PRs should describe the trading workflow affected, list validation steps you ran, and call out any `.env`, exchange, or state-file impacts. Include sample commands or logs when changing live-run behavior.

## Security & Configuration Tips
Copy `.env-template` to `.env` and keep secrets out of commits. Never hardcode API credentials or commit generated files such as live logs, debug logs, or local state snapshots from `data/`.
