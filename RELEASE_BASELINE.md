# Mavis Trading Bot — Approved UI Release Baseline

**Baseline code commit:** `42a109ebc3308f230b40b64a34e2055523a22afe`  
**Previous approved branch:** `baseline-approved-2026-08-26`  
**New release baseline branch:** `baseline-approved-2026-08-26-final`  
**Approved:** 2026-08-26

This is the release contract for the approved dashboard state. Future phases must preserve these decisions unless a later phase explicitly changes them.

## Non-negotiable rules

1. Mobile-first dashboard; do not squeeze a desktop dashboard into mobile.
2. Trading logic stays in Python. Browser JavaScript is presentation only.
3. Existing API contracts remain stable unless a backend requirement is documented.
4. No runtime HTML/JS injection to patch the dashboard after rendering.
5. No unrelated strategy changes in UI commits.
6. Each phase starts from the latest approved state, uses a dedicated branch, is tested, and is committed separately.
7. Preserve working approved components; no redesign for novelty.

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
- Events within each date are chronological.
- Impact is secondary to the date-first organization.
- Never reorganize the feed primarily by HIGH/MEDIUM/LOW impact.
- **HIGH = red accent.**
- **MEDIUM = orange accent.**
- **LOW = yellow accent.**
- The impact accent is applied to both the event card and its badge so impact is visible at a glance without needing to read the label.

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

## Release contents

The final approved release baseline includes the previously approved themes, mobile navigation, date-first news organization, and presentation-layer separation, plus the final Phase 5 polish:

- Human-readable date labels.
- `Today` for the current IST date.
- `Yesterday` for the previous date.
- Readable IST timestamps for signals and history.
- Red/orange/yellow news impact accents.
- Regression coverage for the date and impact presentation contract.

**No trading strategy, execution, risk, persistence, market-data, or Telegram behavior was changed by this release-baseline polish.**
