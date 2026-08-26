# Mavis Trading Bot — Best Approved UI Release Baseline

**Baseline application commit:** `4fea9845fecb7cc21b3c340a33b4df72cb6eb921`  
**Previous approved branch:** `baseline-approved-2026-08-26-final`  
**Release baseline branch:** `baseline-approved-2026-08-26-final`  
**Approved:** 2026-08-26

This is the current best approved dashboard state and is the release contract for future phases. Future work must start from this state and preserve these decisions unless a later phase explicitly changes them.

## Non-negotiable rules

1. Mobile-first dashboard; do not squeeze a desktop dashboard into mobile.
2. Trading logic stays in Python. Browser JavaScript is presentation only.
3. Existing API contracts remain stable unless a backend requirement is documented.
4. No runtime HTML/JS injection to patch the dashboard after rendering.
5. No unrelated strategy changes in UI commits.
6. Each phase starts from the latest approved state, uses a dedicated branch, is tested, and is committed separately.
7. Preserve working approved components; no redesign for novelty.
8. The approved baseline is the starting point for the next phase; do not regress previously approved behavior.

## Approved visual system

Exactly four theme combinations remain supported:

- Modern Light
- Modern Dark
- Neo-Brutalist Light
- Neo-Brutalist Dark

Theme and accent choices persist in browser storage. Dark mode remains genuinely dark and readable.

## Mobile navigation

Exactly one mobile navigation is used: the fixed bottom navigation.

1. Overview
2. Trades
3. Signals
4. History
5. News
6. Tools

It must not obscure important content or be replaced by a second mobile navigation.

## Date display rules

- The current date in **IST** is displayed as **Today**.
- The previous date may be displayed as **Yesterday**.
- Other dates use a readable form such as **28 Aug 2026**, not raw ISO dates.
- Signal and history timestamps use readable IST date/time formatting instead of raw ISO timestamps with microseconds.
- Date grouping remains chronological; display labels do not change ordering.
- News is ordered **Today first, future next, past last**.

## History rules

History stays date-grouped and readable. The history header keeps meaningful P&L totals and win/loss information.

## News rules

**News remains date-first.**

```text
DATE
  TIME → EVENT → IMPACT
```

- Today's events first.
- Upcoming dates follow.
- Past dates follow after upcoming dates.
- Events within each date are chronological.
- Impact is secondary to the date-first organization.
- Never reorganize the feed primarily by HIGH/MEDIUM/LOW impact.
- **HIGH = red accent.**
- **MEDIUM = orange accent.**
- **LOW = yellow accent.**
- The impact accent is applied to both the event card and its badge so impact is visible at a glance without needing to read the label.

## Backtest rules

The Backtest tool is a complete report, not an empty result shell.

- Symbol, strategy, and days controls remain available.
- Run produces the latest saved backtest result.
- Return, trade count, and win rate are displayed.
- Equity curve is displayed when equity-point data is available.
- Individual trade details are displayed when trade-detail data is available.
- Backtest results remain readable and mobile-safe.
- Backtest API wiring uses the existing presentation-layer contract and does not alter trading strategy logic.

## Motion rules

Motion is purposeful. `prefers-reduced-motion` remains supported. Do not repeatedly animate unchanged data, flash the whole page during polling, delay trading information, or introduce layout overflow.

## Data and trading safety

The dashboard remains a presentation layer over the existing Python state/API. Do not silently alter:

- Sweep Engine V2 decisions
- TrendPulse decisions
- risk calculations
- paper-trade execution
- Telegram messages
- persistence
- market-data access

## Current release contents

The best approved release includes all previously approved UI work plus the final Phase 7 corrections:

- Four approved theme combinations.
- Fixed mobile bottom navigation.
- Human-readable date labels.
- `Today` for the current IST date.
- `Yesterday` for the previous date.
- Readable IST timestamps for signals and history.
- News ordered Today first, future next, past last.
- Red/orange/yellow news impact accents on cards and badges.
- Complete backtest reporting with return, trade count, win rate, equity curve, and trade details.
- Dashboard smoke-test alignment for the approved UI/API markers.
- Mobile-safe presentation and existing API contracts preserved.

**No trading strategy, execution, risk, persistence, market-data, or Telegram behavior was changed by this release-baseline update.**

## Baseline status

**STATUS: BEST APPROVED / RELEASE BASELINE**

Future phases must branch from the current approved baseline rather than rewriting or regressing it.
