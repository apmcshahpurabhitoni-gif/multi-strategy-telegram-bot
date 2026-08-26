# Mavis Trading Bot — Approved UI Baseline

**Baseline:** `ae68ed0fb95269be2b42e0dc9f8c68a8b411cee7`  
**Backup branch:** `baseline-approved-2026-08-26`  
**Approved:** 2026-08-26

This document is the release contract for the dashboard baseline approved before Phase 5. Future work must preserve these decisions unless a later phase explicitly changes them.

## Non-negotiable product rules

1. The dashboard is mobile-first. It must not become a desktop dashboard squeezed into a phone.
2. Trading logic stays in Python. Do not move strategy decisions, risk calculations, execution, persistence, or Telegram behavior into browser JavaScript.
3. Existing API contracts remain stable unless a backend requirement is explicitly documented.
4. Do not use runtime HTML/JS injection to patch the dashboard after rendering.
5. Do not introduce unrelated strategy changes into UI commits.
6. Every meaningful phase starts from the latest approved state, uses a dedicated branch, is tested, and is committed separately.
7. Preserve working behavior. Do not redesign an already-approved component merely for visual novelty.

## Approved visual system

The dashboard supports exactly four theme combinations:

- Modern Light
- Modern Dark
- Neo-Brutalist Light
- Neo-Brutalist Dark

Modern themes use smooth, restrained motion and a professional presentation. Neo themes use stronger borders and physical/brutalist separation while keeping the same information architecture.

Dark mode must remain genuinely dark and readable, not a light theme with a dark background.

Theme and accent choices persist in browser storage.

## Mobile navigation

There is exactly one mobile navigation: the fixed bottom navigation.

Sections, in this order:

1. Overview
2. Trades
3. Signals
4. History
5. News
6. Tools

The active section is visually obvious. The navigation must respect mobile safe-area space and must not obscure important content.

Do not add a second mobile navigation or revert to a cramped desktop-style menu.

## Approved overview hierarchy

The first screen prioritizes:

1. Balance
2. Equity
3. Today's P&L
4. Bot state / risk state
5. Account overview
6. Open exposure
7. Latest signals
8. Performance / backtest information

The last-update time remains visible where appropriate.

## History rules

History is date-grouped and readable. Avoid raw ISO timestamps with microseconds in the primary UI.

The history header exposes meaningful P&L totals and win/loss information.

## News rules

**News is date-first.** This is an explicit approved requirement.

The hierarchy is:

```text
DATE
  TIME → EVENT → IMPACT
```

Rules:

- Today's events first.
- Upcoming dates follow.
- Events inside each date are chronological.
- Impact is a secondary visual/status treatment.
- Never reorganize the feed primarily by HIGH/MEDIUM/LOW impact.

## Motion rules

Motion is purposeful rather than decorative.

Allowed uses include panel transitions, active navigation, live status, number changes, refresh feedback, theme transitions, and button press/hover feedback.

Respect `prefers-reduced-motion`.

Do not repeatedly animate unchanged data, flash the whole page on polling, delay trading information, or introduce motion that causes layout overflow.

## Data and trading safety

The dashboard remains a presentation layer over the existing Python state/API.

Do not silently alter:

- Sweep Engine V2 decisions
- TrendPulse decisions
- risk calculations
- paper-trade execution
- Telegram messages
- persistence
- market-data access

A UI request that appears to require a strategy change must be separated into a documented backend task.

## Phase workflow

For each new phase:

1. Start from the latest approved baseline.
2. Create a dedicated branch.
3. Make only the changes belonging to that phase.
4. Add/update regression tests for the affected behavior.
5. Run Python compilation and the test suite.
6. Verify dashboard routes and critical UI contracts.
7. Review mobile overflow/navigation/theme behavior.
8. Commit the phase with a descriptive message.
9. Keep the approved baseline branch untouched.

## Phase 5 scope

Phase 5 begins as **production hardening and regression locking**. It must not redesign the approved UI.

The purpose is to make the approved state safer to continue developing from by documenting the contract and adding regression coverage for the most important dashboard invariants, especially date-first news organization, the four-theme system, single mobile navigation, reduced-motion support, and the separation between dashboard presentation and trading logic.
