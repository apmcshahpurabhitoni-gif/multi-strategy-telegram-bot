# Phase 9 Scope Lock

Phase 9 is **Operational Trading Intelligence & Dashboard Reliability**.

It is read-only/additive and must not change trading strategy, risk, execution, Telegram behavior, or paper-trading rules.

Scope:
1. Operational health visibility.
2. Signal lifecycle visibility based only on real persisted/server state.
3. Server-side trade-quality metrics with safe insufficient-data handling.
4. Stronger dashboard/API regression tests.
5. Four-theme and mobile-safe dashboard integration.

Non-goals: live trading, broker execution, strategy optimization, Sweep Engine rule/timing changes, TrendPulse changes, risk changes, Telegram semantic changes, persistence replacement, or frontend-framework replacement.

Implementation starts only after current-main inspection and must follow DEVELOPMENT.md release/testing rules.
