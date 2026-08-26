# Phase 9 — Operational Trading Intelligence & Dashboard Reliability

**Status:** PLAN / NOT IMPLEMENTED  
**Base:** `main` at `356eb9c2bcb5f21150bd3fc44df37f714ce877de`  
**Branch:** `phase-9-operational-intelligence`  
**Prerequisite:** Phase 8B accepted as working  

---

## 1. Purpose

Phase 9 is the next controlled improvement after Phase 8B. Its purpose is to turn the existing signal/trade intelligence into a more useful **operational monitoring layer** without changing the trading strategy, execution, risk model, Telegram behavior, or paper-trading rules.

The phase is intentionally **read-only and additive** wherever possible.

The main goal is:

> Make it easier to understand what the bot is doing, what happened to signals/trades, and whether the system is healthy — without changing how trades are generated or executed.

---

## 2. Hard constraints

These rules are mandatory.

### Trading engine protection

Do **not** change:

- Sweep Engine V2 decision rules
- Nifty / Bank Nifty sweep timing rules
- TrendPulse decision rules
- entry conditions
- exit conditions
- stop-loss calculation
- target calculation
- risk sizing
- paper-trade execution behavior
- market-data selection
- Telegram signal/trade behavior

If any requested Phase 9 feature appears to require a trading-engine change, stop and document it separately rather than silently modifying strategy logic.

### Dashboard architecture

- Trading/business logic stays in Python.
- Browser JavaScript only renders server-provided results and handles UI interaction.
- No runtime HTML/JS injection.
- No duplicate dashboard implementation.
- Preserve the existing `/api/dashboard` contract and add fields only when required.
- Preserve all existing endpoints and actions.
- No unrelated refactors.

These rules follow the repository development contract. fileciteturn58file0

---

## 3. Phase 9 scope

Phase 9 has four workstreams.

### 3.1 System Health panel

Add a compact operational-health section using existing application state where possible.

It should expose, when available:

- bot/application state
- data freshness / last update
- dashboard snapshot age
- active/open trade count
- today's signal count
- today's completed trade count
- last successful news refresh state
- backtest availability/status
- persistence/data availability indicators

The panel must clearly distinguish **healthy**, **stale**, **unavailable**, and **error** states rather than silently displaying misleading zeros.

No new trading decisions may be made from this panel.

### 3.2 Signal lifecycle visibility

Extend the Phase 8B intelligence presentation so a user can understand the lifecycle of a signal:

```text
Detected → Recorded → Trade/No Trade → Outcome
```

Where the underlying data supports it, show:

- strategy
- symbol
- direction
- signal time
- signal explanation
- whether a trade was opened
- trade reference when available
- final outcome when available

Do not invent lifecycle events that are absent from persisted data.

### 3.3 Trade-quality monitoring

Build on the Phase 8B trade intelligence to surface operational metrics such as:

- wins
- losses
- win rate
- total P&L
- expectancy
- profit factor
- average win
- average loss
- average R
- maximum observed losing streak when reliably derivable

Metrics must be calculated server-side from the existing history/persistence layer.

The UI should make clear when a metric has insufficient data.

### 3.4 Dashboard reliability and test coverage

Strengthen automated protection around the dashboard and Phase 8/9 intelligence.

Add tests for:

- stable `/api/dashboard` response shape
- Phase 8B intelligence payload preservation
- Phase 9 health payload
- missing/empty history
- stale/unavailable data
- malformed optional records
- signal lifecycle records
- trade metric calculations
- zero-trade / zero-win / zero-loss edge cases
- dashboard JavaScript syntax

The test suite must protect existing behavior rather than merely testing the new happy path.

---

## 4. Proposed API shape

Do not replace existing snapshot fields.

Prefer an additive structure similar to:

```json
{
  "intelligence": {
    "signals": [],
    "trades": [],
    "strategies": []
  },
  "operational_health": {
    "status": "healthy|stale|unavailable|error",
    "generated_at": "...",
    "data_age_seconds": 0,
    "open_trades": 0,
    "today_signals": 0,
    "today_completed_trades": 0,
    "news": {},
    "backtest": {}
  }
}
```

This is a **target contract**, not permission to fabricate fields. During implementation, inspect the existing API and persistence structures first and use the smallest safe schema that satisfies the feature.

---

## 5. UI requirements

### Overview

The Overview should retain its current hierarchy:

1. Balance
2. Equity
3. Today's P&L
4. State
5. Account
6. Open trades
7. Signals
8. Last update

The new health information must not push the account summary below secondary information without a concrete design reason. fileciteturn58file0

### Signals

Add lifecycle/intelligence information without turning the Signals page into a dense desktop table.

Mobile cards should remain scannable.

### Trades

Retain the existing execution-focused trade presentation and add intelligence as secondary information.

### History

Do not replace the compact History hierarchy. Phase 9 should complement it with intelligence rather than duplicate the complete history table.

### Themes

All Phase 9 components must work in exactly these four themes:

- modern-light
- modern-dark
- neo-light
- neo-dark

Do not create separate layouts for each theme. fileciteturn58file0

### Mobile

Verify at minimum:

- 320px
- 360px
- 375px
- 390px
- 412px
- 430px

Requirements remain:

- no intentional horizontal overflow
- no clipped controls
- no duplicate navigation
- no important information hidden off-screen
- safe-area support
- sufficiently large touch targets

fileciteturn58file0

---

## 6. Data correctness rules

### Never infer unavailable facts

If a signal has no linked trade, display **No Trade / Not recorded**, not a guessed outcome.

If a metric cannot be calculated safely, display **Insufficient data**.

If market/news data is stale or unavailable, expose that state.

### No silent zeros

These are different states:

- actual zero
- unavailable
- not applicable
- not enough data
- error

The API and UI must preserve that distinction where practical.

### Time handling

Use the repository's existing timezone/date conventions. Do not introduce a second timezone implementation.

---

## 7. Files likely to be affected

These are candidates only and must be confirmed after inspecting `main`:

- `dashboard_api.py`
- `phase8_intelligence.py`
- `phase8_dashboard.py`
- canonical dashboard HTML/JS
- `tests/test_phase8b_dashboard.py`
- new Phase 9 test module(s)
- documentation

Potentially protected files include:

- `sweep_engine.py`
- `sweep_runtime.py`
- `main.py`
- risk/execution modules
- Telegram modules

A protected trading file must not be changed merely for convenience.

---

## 8. Implementation sequence

### Step 1 — Reinspect current `main`

Before coding:

- inspect current files
- inspect Phase 8B implementation
- inspect current dashboard API
- inspect current persistence/history structures
- inspect current tests
- identify actual canonical dashboard file

Do not assume the old Phase 8B file list is still exact.

### Step 2 — Create branch

Create:

```text
phase-9-operational-intelligence
```

from the exact current `main` commit.

### Step 3 — Implement server-side model

Build the smallest read-only/additive server-side model required for:

- operational health
- signal lifecycle
- trade-quality metrics

### Step 4 — Integrate API

Expose the new information without breaking existing dashboard fields.

### Step 5 — Integrate canonical UI

Modify only the canonical dashboard implementation.

No duplicate templates.

### Step 6 — Tests

Add/update tests for both normal and degraded/empty-data cases.

### Step 7 — Full verification

Run the repository-required checks:

```bash
python -m compileall main.py run_bot.py dashboard_api.py sweep_engine.py sweep_runtime.py backtest.py
python -m unittest discover -s tests -v
```

Also validate dashboard JavaScript using the repository's Node guidance. fileciteturn58file0

### Step 8 — Manual smoke verification

Verify:

- `/ping`
- `/dashboard`
- `/api/dashboard`
- `/api/dashboard?force=1`
- `/api/backtest?...`
- paper close-trade action
- news refresh
- Phase 9 health states
- Phase 8B intelligence still visible

### Step 9 — Diff review

Before merge:

- inspect every changed file
- confirm no strategy logic changed
- confirm no Telegram behavior changed
- confirm no endpoint was accidentally removed
- confirm no runtime injection was introduced
- confirm no unrelated formatting/refactor noise

### Step 10 — PR

Create a dedicated Phase 9 PR against the approved `main` baseline.

### Step 11 — CI

Ensure the repository's verification workflow runs against the Phase 9 branch/PR.

Do not declare success merely because a workflow file exists; verify the actual run/result when GitHub reports it.

### Step 12 — Merge/deployment

Only after the code and tests are clean:

- merge once
- do not make repeated speculative pushes
- verify deployment/runtime if the connected tooling exposes it
- otherwise clearly report what could and could not be verified

---

## 9. Acceptance criteria

Phase 9 is accepted only when all applicable items below are true:

- [ ] Phase 8B behavior remains intact.
- [ ] Existing trading strategy behavior is unchanged.
- [ ] Existing risk/execution behavior is unchanged.
- [ ] Existing Telegram behavior is unchanged.
- [ ] Existing dashboard endpoints remain functional.
- [ ] Operational health is visible and correctly distinguishes healthy/stale/unavailable/error states.
- [ ] Signal lifecycle is visible only where supported by actual data.
- [ ] Trade-quality metrics are calculated server-side.
- [ ] Insufficient-data states are handled safely.
- [ ] Four themes work.
- [ ] Mobile widths remain usable.
- [ ] No horizontal overflow is introduced.
- [ ] Python compilation passes.
- [ ] Full unit-test suite passes.
- [ ] Dashboard JavaScript syntax passes.
- [ ] Manual smoke checks pass.
- [ ] Full diff reviewed.
- [ ] CI result is verified if CI runs.
- [ ] Deployment/runtime status is verified when tooling permits.
- [ ] Documentation reflects the final implementation.

---

## 10. Explicit non-goals

Phase 9 does **not** include:

- live trading
- broker order execution
- changing risk percentages
- changing Sweep Engine rules
- changing Sweep Engine candle timing
- changing TrendPulse rules
- changing Telegram alert semantics
- replacing the persistence layer
- replacing the dashboard framework
- introducing a new frontend framework
- speculative strategy optimization
- automatic strategy parameter tuning

These can be considered as separate future phases.

---

## 11. Rollback rule

If Phase 9 causes any regression in:

- signal generation
- trade execution
- persistence
- Telegram
- dashboard loading
- existing API responses

then Phase 9 must not be accepted.

The implementation should be reverted or corrected before any production acceptance.

---

## 12. Final phase definition

**Phase 9 = Operational Trading Intelligence & Dashboard Reliability.**

It builds on Phase 8B without changing the trading engine. It makes the bot easier to monitor and the dashboard more trustworthy by exposing operational health, signal lifecycle, and trade-quality information from the existing server-side state, with stronger tests and explicit degraded-data handling.

This document is the authoritative Phase 9 plan until a later approved revision replaces it.
