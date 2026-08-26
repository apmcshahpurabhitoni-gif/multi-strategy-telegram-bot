# Phase 6 — Backtest Reliability & Reporting Hardening

Phase 6 starts from the approved release baseline and does not change live trading strategy decisions.

## Scope

1. Keep the dashboard backtest response JSON-friendly.
2. Prevent the dashboard from receiving an array where it expects the trade count.
3. Preserve detailed backtest records separately as `trade_details`.
4. Keep NIFTY 50 / BANK NIFTY provider aliases intact.
5. Repair the Binance 1-hour fallback path when Yahoo Finance is unavailable.
6. Add regression tests for the response contract and symbol aliases.

## User-visible result

The Tools → Backtest result and Overview → Latest Backtest should show a numeric trade count rather than JavaScript rendering trade objects as `[object Object]`.

The detailed trade records remain available in the API response under `metrics.trade_details` for future reporting UI work.

## Safety boundary

This phase does **not** change:

- Sweep Engine V2 live signal rules.
- TrendPulse live signal rules.
- Risk calculations for live paper trades.
- Paper-trade execution.
- Telegram signal/reminder behavior.
- Persistence contracts for live trading.

The compatibility layer only normalizes the backtest reporting contract and data-provider fallback.

## Verification

Run:

```bash
python -m compileall main.py run_bot.py dashboard_api.py sweep_engine.py sweep_runtime.py backtest.py sitecustomize.py
python -m unittest discover -s tests -v
```

Then manually verify:

- `/ping`
- `/dashboard`
- `/api/dashboard`
- `/api/backtest?symbol=GC%3DF&strategy=sweep&days=30`
- Tools → Backtest shows a numeric Trades value.
- Overview → Latest Backtest shows a numeric Trades value.

## Acceptance criteria

- No `[object Object]` in the backtest summary.
- `metrics.trades` is an integer count.
- `metrics.trade_details` contains the detailed records when trades exist.
- Existing baseline UI rules remain unchanged.
- Existing Sweep Engine tests remain green.
