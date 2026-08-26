# Phase 9 Scope Lock

**Phase:** 9 — Operational Trading Intelligence & Dashboard Reliability  
**Status:** Scope locked; implementation not started.

## Required outcomes

1. Operational health visibility.
2. Signal lifecycle visibility using only real persisted/server state.
3. Server-side trade-quality metrics with explicit insufficient-data handling.
4. Stronger dashboard/API regression tests.
5. Four-theme and mobile-safe dashboard integration.

## Hard exclusions

- No live trading.
- No broker execution.
- No strategy optimization.
- No Sweep Engine V2 rule or timing changes.
- No TrendPulse decision changes.
- No risk-model changes.
- No Telegram semantic changes.
- No persistence replacement.
- No frontend-framework replacement.

Implementation must begin from the exact current `main`, follow `DEVELOPMENT.md`, use a dedicated branch, preserve existing endpoints and Phase 8B behavior, and complete compile/tests/smoke/diff/CI/runtime verification before acceptance.
