# Phase 8B — Dashboard Intelligence UI Contract

Phase 8B is an additive, read-only presentation layer built on the approved Phase 8A intelligence payload.

## Current implementation

- `phase8_dashboard.py` converts Phase 8A records into presentation-safe view models.
- `signal_view()` exposes only recorded signal metadata and an explicit explanation/hint.
- `trade_view()` exposes entry/exit/stop, outcome, P&L, R-multiple, direction and strategy when recorded.
- `strategy_cards()` exposes compact strategy statistics without inventing unavailable values.
- `build_dashboard_intelligence()` produces a versioned `8B` payload.
- `tests/test_phase8b_dashboard.py` covers normal, missing-metric and empty-data cases.

## UI contract

The approved dashboard should consume the 8B payload in three areas:

1. **Signals** — show symbol, BUY/SELL, strategy, timestamp, saved status and the recorded hint. Do not invent a reason for a signal.
2. **Trades** — show symbol, direction, strategy, entry, exit, stop availability, outcome, P&L and R-multiple when available.
3. **Overview / strategy cards** — show trades, wins, losses, win rate, P&L, expectancy and profit factor. `null` means unavailable and must remain visibly unavailable.

## Non-negotiable rules

- Do not alter the approved theme, navigation, dates, News or Backtest UI.
- Do not alter Sweep Engine, TrendPulse, risk, execution, paper-trade or Telegram behavior.
- Do not infer trading reasons that are absent from recorded data.
- Do not use runtime HTML/JavaScript injection or patch the template on every request.
- The canonical `templates/index.html` remains the source of truth for UI.
- The release baseline remains immutable; all Phase 8 work is additive and reversible.

## Integration gate

Before exposing 8B in production, the canonical template must be edited in source to consume the new payload, followed by Python compilation, unit tests, dashboard smoke testing and visual verification. No Render deploy should be triggered merely to test an unfinished intermediate patch.
