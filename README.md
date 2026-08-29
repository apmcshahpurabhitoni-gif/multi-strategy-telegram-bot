# Mavis Trading Bot — Master Project README / Handoff

> **Purpose of this file:** This is the continuity document for future development chats. Read this file before changing the repository. It records the current architecture, locked trading rules, dashboard rules, known failures, lessons learned, phase history, verification requirements, and the next work plan.

## 0. Project identity

Mavis is a multi-strategy **paper-trading** Telegram bot. It contains:

- Sweep Engine V2 / V2.3
- TrendPulse
- Telegram alerts and paper-trade notifications
- persistent balances, trades and history
- dashboard and dashboard API
- economic/news calendar
- backtesting tools
- Render/Docker/local deployment support

**This is paper trading. It is not a broker execution system.** Market-data feeds and backtests are not guaranteed to match an authoritative trading venue. Important signals must be verified against the intended reference source.

---

# 1. MOST IMPORTANT RULES — READ FIRST

These rules are higher priority than convenience, UI requests, or a quick fix.

### Trading engine protection

Never change working trading logic to solve a dashboard/display problem.

Do not silently change:

- Sweep Engine V2 decision rules
- Sweep Engine candle timing
- NIFTY / BANK NIFTY timing
- TrendPulse decision rules
- entry conditions
- exit conditions
- stop-loss calculation
- target calculation
- risk sizing
- paper-trade execution
- market-data selection
- Telegram signal/reminder semantics
- persistence contracts

If a requested feature appears to require one of these changes, stop and document the conflict before coding.

### Dashboard protection

The dashboard is a presentation/monitoring layer over Python state and API data.

Business logic remains server-side:

- candle construction
- sweep detection
- TrendPulse decisions
- risk calculations
- paper execution
- Telegram messaging
- persistence
- market-data access
- intelligence calculations

Browser JavaScript should render server-provided results and manage UI interaction. Do not move trading decisions into JavaScript.

### Never use runtime source rewriting

Do not solve integration by reading `main.py` as text, injecting strings, compiling the modified text, and executing it. This previously created an unsafe/fragile bootstrap path.

The canonical production path is an explicit Python entry point:

```text
run_bot.py
  -> import main
  -> import sweep_runtime
  -> install canonical runtime into main
  -> main.main()
```

### Never create duplicate implementations

There must be one canonical dashboard implementation and one canonical Sweep V2 runtime path. Do not create another template, another scanner, or another hidden frontend copy merely to make one test pass.

---

# 2. CANONICAL SWEEP ENGINE V2 RULE

A sweep is valid only on a **completed/closed strategy candle**.

The current candle must break **both** sides of the previous candle:

```text
Current High > Previous High
AND
Current Low  < Previous Low
```

Strict inequality matters.

```text
Current High == Previous High  -> NOT a sweep
Current Low  == Previous Low   -> NOT a sweep
```

A one-sided break is **NOT** a sweep.

If either side is missing:

```text
NO SIGNAL
```

Only after both sides are swept does the current candle close classify direction:

```text
Close > Previous High
    -> BULLISH / BUY

Previous Low <= Close <= Previous High
    -> NEUTRAL SWEEP

Close < Previous Low
    -> BEARISH / SELL
```

### Meaning

- **BUY:** both sides swept and the closed candle closed above the previous high.
- **SELL:** both sides swept and the closed candle closed below the previous low.
- **NEUTRAL:** both sides swept but close remained inside the previous range.
- **NO SIGNAL:** both sides were not swept.

NEUTRAL is informational only. It must not open a paper trade.

### Legacy rule that is no longer valid

Older code used `4H Sweep + FVG`. **FVG confirmation is not part of canonical Sweep V2.** Do not reintroduce an FVG wait/fill step unless a new, explicitly approved strategy phase changes the contract.

---

# 3. CANONICAL CANDLE SCHEDULES

Candle boundaries are part of the strategy contract. Do not let provider timestamp conventions silently change them.

## NIFTY 50 and BANK NIFTY

Symbols:

```text
^NSEI
^NSEBANK
```

Use **1-hour strategy candles only** at these exact starts (IST):

```text
09:15
10:15
11:15
12:15
13:15
14:15
```

The candle closes one hour after its start:

```text
09:15 -> 10:15
10:15 -> 11:15
11:15 -> 12:15
12:15 -> 13:15
13:15 -> 14:15
14:15 -> 15:15
```

There must be **no 15:15 -> 16:15 strategy candle**.

A signal based on the 10:15 candle must not be evaluated before 11:15.

This exact schedule exists because generic pandas resampling/provider timestamps previously risked drifting the exchange-session boundaries.

## NSE stocks

For `.NS` symbols, current engine builds session-only 4H bars rather than fabricating overnight data:

```text
09:15 -> 13:15
13:15 -> 15:15
```

The second segment is only accepted when sufficient session data exists, including the final session period.

## Gold / FX

Current canonical provider schedule uses 4H boundaries:

```text
02:30
06:30
10:30
14:30
18:30
22:30 IST
```

These are treated as the expected OANDA/TradingView-style reference boundaries for the runtime.

## BTC

Current engine uses 4H boundaries:

```text
01:30
05:30
09:30
13:30
17:30
21:30 IST
```

The engine uses explicit schedule-aware construction rather than assuming every provider's 4H candle is identical.

---

# 4. CLOSED-CANDLE REQUIREMENT

The engine must never use an unfinished strategy candle.

A strategy candle is eligible only when its scheduled end is `<= now`.

This protects against:

- intrabar false sweeps
- changing highs/lows before close
- signals appearing early
- inconsistent signal times
- stale/incorrect Telegram alerts

A closed-candle signal is then subject to the one-hour freshness rule described below.

---

# 5. ONE-HOUR FRESHNESS RULE

There was a major historical inconsistency where old messaging referred to a **six-hour** stale rule while the approved Sweep V2 behavior was a **one-hour** freshness window.

The canonical user-facing rule is:

```text
0–60 minutes after candle close -> FRESH
>60 minutes after candle close   -> STALE
```

A stale sweep must not create a new paper trade.

The runtime also rejects a detected sweep if:

```text
age_ms > 3600 * 1000
```

The user-facing message should show one coherent age representation. Do not display `4 hr` in one place while another part says the same signal is fresh for 1 hour.

### Startup baseline protection

When the runtime first starts, it records the latest known candle close as a baseline and does not immediately replay it as a new signal. A newer qualifying closed candle is required.

This prevents restart/redeploy from duplicating an old signal.

---

# 6. PAPER-TRADE RULES

For a qualifying directional sweep:

### BUY

```text
Entry = market price when signal is detected
SL    = sweeping/current candle Low
TP    = 1:2 risk/reward
```

### SELL

```text
Entry = market price when signal is detected
SL    = sweeping/current candle High
TP    = 1:2 risk/reward
```

### NEUTRAL

```text
No paper trade
Informational Telegram message only
```

If a directional sweep is detected but no live market price is available, do not fabricate an entry. The runtime must leave the trade un-opened and report the data problem.

---

# 7. TELEGRAM MESSAGE CONTRACT

The Telegram message must be compact, readable, and internally consistent.

Canonical header concept:

```text
🟢SWEEP V2 · Gold ·  ✅
```

or equivalent direction/status formatting for SELL/NEUTRAL.

Required information for a directional signal includes:

- signal direction
- timeframe
- candle close time
- signal age
- sweep high
- sweep low
- action
- entry
- SL
- TP
- account
- quantity
- risk, when available
- data-source warning

For a NEUTRAL signal:

- show NEUTRAL
- show informational/no-paper-trade action
- do not invent entry/SL/TP/trade fields

### Reminder rule

A qualifying signal can produce:

1. initial Telegram alert
2. one reminder after one hour, if the initial alert was recorded and the reminder has not already been sent

The signal archive is persistent. Reminder delivery state is runtime state.

Do not send unlimited reminders.

---

# 8. PRICE/DISPLAY RULES

Backend/provider symbols and user-facing names are different concerns.

Known dashboard display mappings include:

```text
GC=F       -> Gold
XAUUSD     -> Gold
XAU/USD    -> Gold
BTC-USD    -> Bitcoin
^NSEI      -> NIFTY 50
^NSEBANK   -> BANK NIFTY
```

Unknown symbols must not be arbitrarily renamed.

Price formatting is display-only. It must never alter execution values.

Current display precision in Sweep runtime is instrument-aware:

```text
BTC       -> 2 decimals
USDJPY    -> 3 decimals
other FX  -> 5 decimals
Gold/Silver/Copper -> 2 decimals
NSE       -> 2 decimals
```

Do not solve visual readability by changing the actual price used for trading.

---

# 9. DATA-SOURCE WARNING RULE

The bot may use provider data that differs from the user's reference platform.

For known Yahoo-backed symbols, the message should warn:

```text
⚠️ DATA SOURCE: Yahoo Finance. Verify against TradingView before relying on the signal.
```

For other configured providers, state that the configured market-data provider is being used and advise verification when prices differ.

Never pretend provider OHLC is identical to TradingView/OANDA when it has not been verified.

---

# 10. SIGNAL HISTORY / PERSISTENCE

Confirmed sweep signals are stored with information including:

```text
id
symbol
market
direction
strategy
timeframe
candle_start
candle_end
created_at
reminder_sent
```

The signal ID is derived from symbol + candle close timestamp:

```text
<symbol>:<close_timestamp_ms>
```

This prevents the same candle from being stored repeatedly.

The archive is intended to survive redeploys through the existing persistence path. When `main.load_json/save_json` is available, the runtime routes signal-history persistence through it; local JSON is the fallback.

Do not silently delete historical signal records merely because the one-hour Telegram freshness window has expired. **Freshness controls new action; it does not erase history.**

---

# 11. DASHBOARD PRODUCT RULES

The dashboard is mobile-first.

## Navigation

Desktop: one top navigation.

Mobile: one bottom navigation.

Sections:

```text
🏠 Overview
📊 Trades
⚡ Signals
🕘 History
📰 News
⚙️ Tools
```

Never render both mobile and desktop navigation in a way that duplicates the UI on mobile.

## Overview hierarchy

First screen priority:

1. Balance
2. Equity
3. Today's P&L
4. Bot state
5. Account
6. Open trades
7. Signals
8. Last update

Do not bury the core account state under secondary analytics.

## Open trades

Mobile cards should prominently show:

```text
SYMBOL
BUY / SELL
Entry · Current · P&L
SL · TP
Progress
Close
```

Do not force a wide desktop table onto a phone.

## History

Use short readable dates/times, not raw ISO timestamps with microseconds.

History should make these easy to find:

- total P&L
- today's P&L
- wins/losses
- date groups
- trade direction
- strategy
- outcome

## News

Primary hierarchy is **date first, chronological second**:

```text
DATE
  TIME -> EVENT -> IMPACT
```

Do not group the entire feed by HIGH/MEDIUM/LOW impact.

Impact is visual emphasis:

```text
HIGH   -> red accent
MEDIUM -> amber accent
LOW    -> green/other accent
```

Today's events appear first, then upcoming dates.

---

# 12. FOUR-THEME DESIGN SYSTEM

Exactly four themes are supported:

```text
modern-light
modern-dark
neo-light
neo-dark
```

Modern Light/Dark share one layout and component system.

Neo Light/Dark share one layout and component system.

Do not build four unrelated pages.

Theme and accent choices persist in browser `localStorage`.

Motion should be purposeful:

- modern = smooth, restrained, professional
- neo = snappy, physical, expressive

Respect `prefers-reduced-motion`.

---

# 13. MOBILE ACCEPTANCE SIZES

At minimum test:

```text
320px
360px
375px
390px
412px
430px
```

Required:

- no intentional horizontal page overflow
- no clipped controls
- no duplicate navigation
- no important content hidden off-screen
- safe-area support for bottom navigation
- usable touch targets
- readable trade cards
- readable signal cards
- readable news cards

---

# 14. ARCHITECTURE / FILE RESPONSIBILITIES

```text
main.py
  Existing application, Telegram integration, accounts, scanner loop,
  persistence/state, paper execution and other bot behavior.

sweep_engine.py
  Canonical closed-candle Sweep V2 detection and instrument-specific
  candle construction.

sweep_runtime.py
  Runtime integration of Sweep V2 with main.py: signal handling,
  freshness, persistence, Telegram message rendering, paper-trade handoff,
  reminders and startup protection.

run_bot.py
  Production entry point. Explicitly imports main + sweep_runtime,
  installs runtime, then calls main.main().

phase8_intelligence.py
  Read-only intelligence derived from existing history/signals.

phase8_dashboard.py
  Read-only presentation models for Phase 8B.

dashboard_api.py
  Dashboard snapshot/API layer. Must remain a presentation/data adapter,
  not a second trading engine.

 dashboard/index.html
  Canonical dashboard frontend.

backtest.py
  Backtesting engine.

backtest_compat.py
  Compatibility normalization for backtest reporting contract.

db.py
  Persistence helpers.

render.yaml
  Render configuration. Current startup command is `python run_bot.py`.

Procfile
  `web: python run_bot.py`.

Dockerfile
  Container deployment configuration.

tests/
  Regression and behavior protection.
```

---

# 15. PHASE HISTORY / EVOLUTION

The exact names of every early phase are not reliably reconstructable from the current repository alone, so do **not invent historical phase names**. The following milestones are explicitly supported by repository history and documentation.

## Phase 4 — Runtime bridge

A Phase 4 runtime bridge was introduced to safely integrate the canonical runtime with the existing application.

Lesson:

- integration should be explicit and testable
- avoid hidden startup magic
- keep the legacy application intact while introducing a controlled runtime layer

## Phase 6 — Backtest reliability & reporting hardening

Goals included:

- keep backtest responses JSON-friendly
- ensure `metrics.trades` is a numeric count
- preserve detailed records separately as `metrics.trade_details`
- preserve NIFTY/BANK NIFTY aliases
- repair Binance 1H fallback when Yahoo was unavailable
- add regression tests

Historical failure:

```text
JavaScript received trade objects where it expected a trade count.
```

The visible symptom was effectively:

```text
[object Object]
```

Lesson:

> API contracts must distinguish summary numbers from detailed arrays.

## Sweep Engine V2 implementation

The canonical engine was implemented around:

- deterministic closed-candle logic
- both-side sweep requirement
- market-specific schedules
- audited Telegram alerts
- reminder behavior
- exact paper-trade SL/TP
- data warnings
- tests
- deployment launcher

This replaced the ambiguous legacy behavior with a deterministic contract.

## Phase 8A — Read-only intelligence

`phase8_intelligence.py` derives:

- signal/trade views
- outcome
- P&L
- R multiple
- strategy attribution
- win/loss/flat counts
- win rate
- average trade
- average win/loss
- profit factor
- expectancy

It must remain read-only and must not change trading decisions.

## Phase 8B — Dashboard intelligence presentation

`phase8_dashboard.py` converts Phase 8A data into compact dashboard view models.

The Phase 8B contract is:

```text
version = 8B
read_only = true
summary
signals[]
trades[]
strategies[]
```

It must not invent missing metrics. Existing tests explicitly protect this behavior.

## Phase 9 — Operational Trading Intelligence & Dashboard Reliability

The repository's formal Phase 9 plan defines this as the next controlled improvement after Phase 8B.

Required workstreams:

1. System health
2. Signal lifecycle visibility
3. Trade-quality monitoring
4. Dashboard/API reliability and test coverage

Hard exclusions:

- no live trading
- no broker execution
- no strategy optimization
- no Sweep V2 rule/timing changes
- no TrendPulse rule changes
- no risk-model changes
- no Telegram semantic changes
- no persistence replacement
- no frontend-framework replacement

Important status distinction:

- The formal Phase 9 planning documents on `main` originally state that Phase 9 implementation had not started.
- The later working branch contains Phase 8B dashboard intelligence plus subsequent canonical runtime/dashboard reliability work.
- Therefore **do not call Phase 9 fully accepted until the final implementation and acceptance checklist are actually verified.**

---

# 16. KNOWN ERRORS / INCIDENTS / WHAT WE LEARNED

This section exists so future chats do not repeat the same mistakes.

## Error 1 — Six-hour stale wording vs one-hour Sweep V2 rule

### Symptom

Telegram/startup/dashboard messaging could describe a stale limit of several hours while the approved Sweep V2 contract was one hour.

### Root cause

Legacy global stale-message wording survived after the strategy-specific freshness contract changed.

### Fix direction

Use one canonical one-hour freshness calculation and expose the same state everywhere.

### Lesson

Never maintain separate freshness rules for engine, Telegram, and dashboard.

---

## Error 2 — NIFTY message showed a high break but low was not swept

Observed regression example:

```text
Previous High = 24133.60
Previous Low  = 24090.85
Current High  = 24167.85
Current Low   = 24107.10
```

High was above previous high, but current low was **not** below previous low.

Therefore:

```text
NO SWEEP
```

The old behavior could incorrectly produce a signal from a one-sided break.

### Lesson

Always test both strict inequalities independently. A high sweep alone is never enough.

A regression test was added for this exact scenario.

---

## Error 3 — NIFTY candle boundaries drifted / generic resampling risk

### Symptom

The user required exactly:

```text
09:15, 10:15, 11:15, 12:15, 13:15, 14:15
```

Generic provider/resampling behavior could create incorrect session bins or imply a 15:15 candle.

### Fix

The engine now constructs exact NSE session-hour boundaries explicitly.

### Lesson

Exchange session boundaries are strategy rules, not formatting details. Never let generic resampling define them implicitly.

---

## Error 4 — Incomplete candle used for signal

### Symptom

A candle could be evaluated before its scheduled close.

### Fix

`build_closed_candles()` only returns bars whose scheduled end is `<= now`.

### Lesson

A sweep must be based on immutable closed OHLC, not live intrabar OHLC.

---

## Error 5 — Provider names exposed in dashboard

### Symptom

Users saw implementation/provider symbols such as:

```text
GC=F
BTC-USD
^NSEI
^NSEBANK
```

instead of readable names.

### Fix

Dashboard display mapping was added without changing backend symbols.

### Lesson

Separate internal identifiers from user-facing labels.

---

## Error 6 — Prices looked excessively long / hard to scan

### Symptom

Raw floating-point/provider precision made prices visually noisy.

### Fix

Dashboard display rounding and instrument-specific Telegram precision were introduced.

### Critical warning

Display formatting must not modify execution values.

### Lesson

Normalize presentation, not the trading model.

---

## Error 7 — BUY/SELL/action information was too small or hard to find

### Symptom

Even when the signal was present, the important action was not visually prominent enough.

### Lesson

A trading dashboard should optimize for immediate recognition:

```text
BUY / SELL
Entry
SL
TP
P&L
```

must be easier to find than secondary metadata.

This is a UI problem. Do not change strategy logic to solve it.

---

## Error 8 — Legacy FVG behavior confused the canonical strategy

### Symptom

Older documentation/code described:

```text
4H Sweep + FVG
```

while the approved Sweep V2 contract was immediate closed-candle classification and paper execution.

### Lesson

Old strategy documentation is not authoritative when it conflicts with the canonical V2 engine/tests. Update documentation rather than reintroducing obsolete behavior.

---

## Error 9 — Runtime source injection in `run_bot.py`

### Symptom / risk

The startup wrapper previously:

- read `main.py` as text
- injected a bootstrap string
- replaced the `__main__` marker
- compiled the modified source
- executed it

This was fragile and made startup behavior depend on source text matching.

### Fix

The working branch changed this to:

```python
import main as _main
import sweep_runtime as _sweep_runtime

if __name__ == "__main__":
    _sweep_runtime.install(_main)
    _main.main()
```

### Lesson

Use normal imports and explicit function calls. Never patch production source code at runtime.

---

## Error 10 — Tests themselves were coupled to the old bootstrap

### Symptom

A bootstrap test expected source injection rather than the desired explicit runtime integration.

### Fix

The test was rewritten to assert:

- explicit `main` import
- explicit `sweep_runtime` import
- runtime installation
- `main.main()` call
- absence of `source.replace()` / `exec(code)` / source compilation

### Lesson

Tests should lock the intended architecture, not preserve an obsolete implementation merely because it was once used.

---

## Error 11 — Weak timezone stub in a dashboard test

### Symptom

A dashboard signal fallback test passed a fake timezone object instead of a real timezone implementation.

### Fix

The test now uses:

```python
pytz.timezone("Asia/Kolkata")
```

### Lesson

Tests for time conversion should use the real timezone behavior, especially in a project where candle boundaries and display times are critical.

---

## Error 12 — Dashboard/API data could silently look like valid zeroes

### Lesson

These states are different:

```text
0
unavailable
not applicable
insufficient data
error
stale
```

Do not convert all missing information to `0`, empty strings, or fake success states.

This is especially important for Phase 9 operational health.

---

## Error 13 — Dashboard changes risked touching trading code

### Lesson

If a visual problem can be fixed in:

```text
HTML/CSS/JS rendering
or
server-side dashboard serialization
```

do that instead of modifying:

```text
sweep_engine.py
sweep_runtime.py
risk code
execution code
Telegram strategy logic
```

The dashboard must remain a consumer of the trading system, not a second copy of it.

---

# 17. PHASE 8B / INTELLIGENCE RULES

Phase 8A/8B is read-only.

It may calculate and display:

- wins
- losses
- flat trades
- win rate
- total P&L
- average trade
- average win/loss
- expectancy
- profit factor
- R multiple
- strategy attribution
- signal explanations
- trade outcomes

It must not:

- create trades
- close trades
- change SL/TP
- alter risk
- send a trading signal
- alter Sweep detection

If data is missing, the intelligence layer must not invent it.

For example:

```text
No linked trade
```

must not become a guessed loss/win.

---

# 18. PHASE 9 CURRENT PLAN

Phase 9 is intended to improve operational visibility without changing strategy behavior.

## Workstream A — System health

Expose, where actual data exists:

- bot/application state
- data freshness
- dashboard snapshot age
- open trades
- today's signals
- today's completed trades
- news refresh status
- backtest availability
- persistence/data availability

States should distinguish:

```text
healthy
stale
unavailable
error
```

## Workstream B — Signal lifecycle

Target lifecycle:

```text
Detected -> Recorded -> Trade/No Trade -> Outcome
```

Only show steps supported by actual persisted/server state.

## Workstream C — Trade-quality monitoring

Server-side metrics may include:

- wins
- losses
- win rate
- total P&L
- expectancy
- profit factor
- average win
- average loss
- average R
- maximum observed losing streak, if safely derivable

## Workstream D — Reliability/testing

Add regression protection for:

- dashboard response shape
- Phase 8B preservation
- health states
- empty history
- malformed records
- stale data
- lifecycle data
- metric edge cases
- dashboard JS syntax

---

# 19. PHASE 9 IMPLEMENTATION ORDER

When continuing this project, follow this order.

### Step 1 — Reinspect current state

Read:

```text
README.md
DEVELOPMENT.md
PHASE9_PLAN.md
PHASE9_SCOPE_LOCK.md
PHASE9_ACCEPTANCE.md
PHASE6_BACKTEST_HARDENING.md
sweep_engine.py
sweep_runtime.py
main.py
 dashboard_api.py
phase8_intelligence.py
phase8_dashboard.py
canonical dashboard HTML/JS
tests/
```

Do not assume an old plan exactly matches the current branch.

### Step 2 — Identify the true baseline

Record:

```text
current main SHA
current working branch SHA
open PRs
CI status
deployment state
```

Never accidentally branch from an old baseline.

### Step 3 — Make one focused change

Prefer small commits:

```text
server model
API integration
UI integration
tests
```

Do not mix unrelated refactors.

### Step 4 — Test immediately

Run targeted tests after each meaningful change.

### Step 5 — Run full verification

Required Python checks:

```bash
python -m compileall main.py run_bot.py dashboard_api.py sweep_engine.py sweep_runtime.py backtest.py
python -m unittest discover -s tests -v
```

If the repository's current CI uses pytest, also run:

```bash
python -m pytest -q
```

Dashboard JavaScript syntax must also be checked using the repository's Node guidance.

### Step 6 — Manual smoke checks

Verify:

```text
/ping
/dashboard
/api/dashboard
/api/dashboard?force=1
/api/backtest?... 
POST /api/close-trade
POST /api/refresh-news
```

Also verify:

- signal cards
- trade cards
- history
- news ordering
- all four themes
- mobile widths
- Phase 8B intelligence
- no duplicate navigation

### Step 7 — Inspect the full diff

Before merge ask:

```text
Did strategy logic change?
Did candle timing change?
Did risk change?
Did Telegram semantics change?
Did persistence change?
Did an endpoint disappear?
Did we create duplicate frontend code?
Did runtime source injection return?
Did we add unrelated formatting/refactors?
```

If yes, stop and correct it unless explicitly approved.

### Step 8 — CI is evidence, not decoration

Do not say "tests pass" because a workflow file exists.

Check the actual GitHub Actions run and conclusion.

For the current canonical runtime branch, the verified runs included successful:

- Phase 8B Tests
- Dashboard Smoke Test
- Sweep Engine Tests

Those results were obtained for commit `5f0dce30e550f7c036467b7a5a6f58f87c4dfe69` on the working branch.

Future commits require fresh verification.

### Step 9 — Merge only after acceptance

Do not merge speculative fixes.

Do not repeatedly push unverified changes to production.

Keep rollback straightforward.

---

# 20. CURRENT WORKING BRANCH / PR STATE

At the latest recorded handoff:

```text
Repository: apmcshahpurabhitoni-gif/multi-strategy-telegram-bot
Base:       main
audit/work: canonical-sync-2026-08-28
PR:         #45
PR title:   refactor: use explicit canonical bot entrypoint
PR state:   draft/open at the time of this handoff
Head SHA:   5f0dce30e550f7c036467b7a5a6f58f87c4dfe69
Base SHA:   d53ac689f6ca9a8e0d023b567bb44a0773571da3
```

The branch contains the explicit `run_bot.py` bootstrap and aligned regression tests.

The latest recorded CI for that head completed successfully for:

```text
Phase 8B Tests
Dashboard Smoke Test
Sweep Engine Tests
```

Do not assume the PR is merged or deployed just because CI passed.

---

# 21. DEPLOYMENT CONTRACT

Current Render configuration uses:

```text
build: pip install --upgrade pip && pip install -r requirements.txt
start: python run_bot.py
health: /ping
port: 8080
```

The Procfile also uses:

```text
web: python run_bot.py
```

Local startup:

```bash
python run_bot.py
```

Dashboard:

```text
http://localhost:8080/dashboard
```

Do not change the startup path casually. If `run_bot.py` changes, verify the whole startup chain.

---

# 22. ENVIRONMENT / DEPENDENCY NOTES

Current core requirements include:

```text
pyTelegramBotAPI
pandas
numpy
yfinance
requests
matplotlib
python-dotenv
```

Runtime also uses timezone/persistence/dashboard components already present in the repository.

Secrets must remain environment variables. Never commit Telegram tokens, database keys, or other credentials.

---

# 23. ACCEPTANCE CHECKLIST — TRADING

Before accepting any Sweep-related change:

- [ ] Candle is closed.
- [ ] Correct instrument schedule is used.
- [ ] Current High > previous High.
- [ ] Current Low < previous Low.
- [ ] Equality does not count.
- [ ] One-sided break does not count.
- [ ] Close classifies BUY/NEUTRAL/SELL correctly.
- [ ] NEUTRAL does not open a paper trade.
- [ ] BUY SL is sweep low.
- [ ] SELL SL is sweep high.
- [ ] TP is 1:2 risk/reward.
- [ ] Entry is actual available market price at detection.
- [ ] Missing price never becomes a fabricated entry.
- [ ] Signal is no older than one hour for new action.
- [ ] Restart does not replay the startup baseline.
- [ ] Reminder occurs once only.
- [ ] Data-source warning is present when required.
- [ ] Provider symbols are not exposed unnecessarily in user-facing UI.

---

# 24. ACCEPTANCE CHECKLIST — NIFTY/BANK NIFTY

- [ ] Only 1H sweep candles are used.
- [ ] Starts are exactly 09:15, 10:15, 11:15, 12:15, 13:15, 14:15 IST.
- [ ] 15:15 -> 16:15 is not created.
- [ ] 10:15 candle is not evaluated before 11:15.
- [ ] Session boundaries do not drift.
- [ ] One-sided high break is rejected.
- [ ] Both-side break with close inside range is NEUTRAL.
- [ ] Both-side break with close above previous high is BUY.
- [ ] Both-side break with close below previous low is SELL.

---

# 25. ACCEPTANCE CHECKLIST — DASHBOARD

- [ ] Mobile-first.
- [ ] 320–430px verified.
- [ ] No horizontal overflow.
- [ ] No duplicate navigation.
- [ ] Six sections visible with icons.
- [ ] Overview order is preserved.
- [ ] BUY/SELL are visually prominent.
- [ ] Prices are readable and not excessively precise.
- [ ] Backend values are unchanged by display formatting.
- [ ] History uses readable times.
- [ ] News is date-first and chronological.
- [ ] Four themes work.
- [ ] Theme persistence works.
- [ ] Reduced motion is respected.
- [ ] Dashboard remains a presentation layer.
- [ ] Trading logic was not moved into JavaScript.
- [ ] Phase 8B data remains visible.
- [ ] Missing data is not silently shown as a fake zero.

---

# 26. ACCEPTANCE CHECKLIST — API / BACKEND

- [ ] Existing `/api/dashboard` fields remain compatible.
- [ ] `/api/dashboard?force=1` works.
- [ ] `/api/backtest` works.
- [ ] `metrics.trades` is a numeric count.
- [ ] Detailed backtest trades remain under `metrics.trade_details` where supported.
- [ ] Intelligence remains read-only.
- [ ] Server-side metrics are derived from real history.
- [ ] Signal lifecycle does not invent missing events.
- [ ] Health states distinguish healthy/stale/unavailable/error.
- [ ] Malformed optional records do not crash the dashboard.

---

# 27. WHAT NOT TO DO IN A NEW CHAT

Do **not** start by immediately editing code.

First say/read:

```text
We are continuing the Mavis Trading Bot project.
Read the repository README/master handoff first.
Preserve all locked Sweep V2 rules and NIFTY/BANK NIFTY 1H timing.
Inspect current main and working branch before changing anything.
Do not use runtime source rewriting.
Do not change strategy/risk/Telegram behavior for dashboard fixes.
```

Then inspect the current repository state.

If the user reports a UI inconsistency such as:

```text
4 hr vs 1 hr
stale vs fresh
prices too long
BUY/SELL too small
wrong NIFTY candle
provider symbol visible
```

treat it first as a **contract consistency / presentation problem**. Trace the source of truth before changing code.

If the problem is genuinely in the strategy engine, use a minimal regression test first.

---

# 28. NEXT PHASE ROADMAP

## Phase 9A — Operational Health

First priority after canonical runtime stabilization:

- health status
- data age
- snapshot age
- persistence availability
- news state
- backtest state
- signal/trade counts

No trading changes.

## Phase 9B — Signal Lifecycle

Connect persisted signal records to actual trade records where a reliable identifier exists.

Display:

```text
Detected
Recorded
Trade / No Trade
Outcome
```

Only when supported by real data.

## Phase 9C — Trade Quality

Expose server-side:

- win rate
- expectancy
- profit factor
- average win/loss
- average R
- losing streak where reliably derivable

Handle insufficient data explicitly.

## Phase 9D — Reliability Hardening

Add tests for:

- empty state
- stale state
- malformed state
- zero trades
- zero wins
- zero losses
- missing news
- missing backtest
- dashboard JS syntax
- API shape compatibility

## Phase 10 — Future / separate approval

Potential future work may include strategy research or optimization, but it must be a separately approved phase. It must not be smuggled into Phase 9 through dashboard or monitoring work.

Live trading/broker execution is outside the current project contract.

---

# 29. FINAL GOLDEN RULE

**Preserve correctness first, consistency second, presentation third, and convenience last.**

The bot should always have one source of truth for:

```text
Candle construction
        ↓
Sweep detection
        ↓
Direction
        ↓
Freshness
        ↓
Paper-trade decision
        ↓
Telegram message
        ↓
Dashboard representation
```

The dashboard may improve how the information is presented, but it must not invent or reinterpret the trading decision.

When a bug appears, trace this chain from the bottom up and fix the actual source of the inconsistency.

**This README is the continuity handoff. Update it whenever a new phase, regression, architectural decision, or important production lesson is established.**
