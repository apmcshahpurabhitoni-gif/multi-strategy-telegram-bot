# Mavis Trading Bot — Development Guide

This document is the working contract for safely changing Mavis without breaking the existing trading engine.

## 1. Core rule

**Do not rewrite working trading logic to solve a dashboard problem.**

The dashboard is a presentation layer over the existing Python state/API.

Keep these responsibilities in Python:

- candle construction
- Sweep Engine V2 decisions
- TrendPulse decisions
- risk calculations
- paper-trade execution
- Telegram messaging
- persistence
- market-data access

The browser should render and interact with those results.

## 2. Application structure

```text
main.py              existing bot/application module
sweep_engine.py      canonical Sweep Engine V2
sweep_runtime.py     runtime integration for sweep scanning/execution
run_bot.py           production startup wrapper
backtest.py          backtest engine
dashboard_api.py     dashboard snapshot + HTTP/API layer
dashboard/index.html self-contained dashboard
 db.py               persistence helpers
tests/               automated tests
render.yaml          Render startup configuration
Dockerfile           container startup configuration
Procfile             process startup declaration
```

## 3. Startup contract

The normal command is:

```bash
python run_bot.py
```

`run_bot.py` is the production entry point. `main.py` remains part of the application and should not be replaced merely because the deployment command changed.

Render, Docker and the Procfile should all point to `run_bot.py`.

## 4. Dashboard contract

The dashboard consumes:

```text
GET  /api/dashboard
GET  /api/dashboard?force=1
POST /api/close-trade
POST /api/refresh-news
GET  /api/backtest?... 
```

Do not change these endpoints just to restyle the dashboard unless there is a concrete API requirement.

The dashboard snapshot currently supplies the main UI with data such as:

- `accounts`
- `live_trades`
- `today_signals`
- `history`
- `news_raw`
- `strategy_stats`
- `equity_curve`
- `risk`
- `generated_at`

If a UI field is missing, prefer adding a small server-side field to the snapshot rather than duplicating business logic in JavaScript.

## 5. Four-theme design system

Supported themes are exactly:

```text
modern-light
modern-dark
neo-light
neo-dark
```

### Modern

Modern Light and Modern Dark share the same component/layout system. Only the visual material, contrast and palette change.

The motion language is:

- smooth
- fluid
- restrained
- professional

### Neo-Brutalist

Neo Light and Neo Dark share the same component/layout system. The visual language uses stronger borders, hard shadows, bolder separation and more physical interactions.

The motion language is:

- snappy
- physical
- expressive
- short

Do not turn the four themes into four unrelated layouts.

## 6. Mobile-first rules

Test the dashboard at least at:

- 320px
- 360px
- 375px
- 390px
- 412px
- 430px

Requirements:

- no intentional horizontal page overflow
- no horizontally scrolling trading tables
- no duplicated navigation
- no clipped controls
- no important information hidden off-screen
- safe-area support for the bottom navigation
- touch targets large enough for mobile use

Desktop can use wider layouts, but mobile must not be a compressed desktop table.

## 7. Navigation

Desktop uses one top navigation.

Mobile uses one bottom navigation.

Sections:

```text
🏠 Overview
📊 Trades
⚡ Signals
🕘 History
📰 News
⚙️ Tools
```

Every section must have an icon and the active state must be visually obvious.

## 8. Overview hierarchy

The first dashboard screen should immediately expose:

1. Balance
2. Equity
3. Today's P&L
4. State
5. Account
6. Open trades
7. Signals
8. Last update

Do not move secondary metrics such as open exposure ahead of the account summary unless there is a specific product decision to do so.

## 9. Trade UI rules

Mobile trade cards should show only useful execution information:

```text
SYMBOL
BUY / SELL
Entry · Current · P&L
SL · TP
Progress
Close
```

Avoid raw implementation timestamps and unnecessary columns.

## 10. History UI rules

History should be compact.

Use:

```text
25 Aug 2026 · 2 items
SELL · 4H Sweep · LOSS · -₹1,843
BUY · TrendPulse · LOSS · -₹1,512
```

Do not expose:

```text
2026-08-25T08:27:35.879406+05:30
```

The History header should show total P&L, today's P&L, and wins/losses.

## 11. News UI rules

The primary hierarchy is:

```text
DATE
  TIME → EVENT → IMPACT
```

Not:

```text
HIGH IMPACT
MEDIUM IMPACT
LOW IMPACT
```

Today's events come first. Upcoming dates follow. Events inside each date are chronological.

Impact is a visual accent:

- HIGH = red accent
- MEDIUM = amber accent
- LOW/other = green accent

Do not reorganize the feed by impact.

## 12. Animation rules

Animations should explain state changes, not decorate every pixel.

Use animation for:

- panel transitions
- new/changed cards
- active navigation
- live status
- numeric changes
- refresh feedback
- theme transitions
- button press/hover

Do not:

- flash the whole page every poll
- animate unchanged data repeatedly
- delay important trading information
- animate layout in a way that causes horizontal overflow
- block button actions with long transitions

Prefer `opacity` and `transform` for performance.

Respect:

```css
@media (prefers-reduced-motion: reduce) { ... }
```

## 13. Polling

The dashboard polls every 30 seconds while visible and fetches immediately when the tab becomes visible again.

Do not create multiple polling timers.

Do not allow overlapping dashboard requests.

Abort in-flight requests during page unload.

## 14. State reconciliation

When improving the UI, preserve:

- current selected tab
- theme choice
- accent choice
- open/collapsed date sections where practical
- current bot state

Browser preferences should remain in `localStorage`.

## 15. Data freshness

Yahoo Finance or another free provider can be delayed, cached or rate-limited.

Never hide this limitation from the user.

A failed backtest is not automatically a bad strategy result; it may be incomplete market data.

## 16. Testing before committing

At minimum:

```bash
python -m compileall main.py run_bot.py dashboard_api.py sweep_engine.py sweep_runtime.py backtest.py
python -m unittest discover -s tests -v
```

For the dashboard, also check JavaScript syntax with a local Node installation:

```bash
node --check dashboard/index.html
```

If `node --check` is not suitable for the HTML file, extract the inline script and run `node --check` on that script.

Then manually verify:

- `/ping`
- `/dashboard`
- `/api/dashboard`
- `/api/dashboard?force=1`
- `/api/backtest?...`
- close-trade action with paper data
- news refresh

## 17. Git workflow

For risky UI changes, create a branch first:

```bash
git checkout -b ui/<short-name>
```

Keep dashboard changes separate from strategy changes when possible.

Recommended commit grouping:

```text
UI: mobile-first dashboard
UI: four-theme system
UI: history and news hierarchy
Docs: update deployment and development guides
```

Do not mix an unrelated strategy rewrite into a dashboard commit.

## 18. Safe-change principle

Before changing a Python trading file, identify whether the requested behavior actually requires a backend change.

If the problem is purely:

- spacing
- mobile layout
- colors
- icons
- animations
- card hierarchy
- date formatting
- dashboard navigation

then keep the trading engine untouched.

## 19. Release checklist

Before merging/deploying a dashboard change:

- [ ] Existing Sweep Engine tests pass.
- [ ] Python modules compile.
- [ ] Dashboard JavaScript syntax is valid.
- [ ] `/ping` works.
- [ ] `/dashboard` loads.
- [ ] Dashboard API still returns a valid snapshot.
- [ ] Mobile widths have no horizontal overflow.
- [ ] Desktop has one top navigation.
- [ ] Mobile has one bottom navigation.
- [ ] All six icons are visible.
- [ ] All four themes work.
- [ ] Theme persists after reload.
- [ ] Accent persists after reload.
- [ ] History is compact and includes P&L totals.
- [ ] News is date-first and chronological.
- [ ] Refresh/close-trade/backtest actions still use existing endpoints.
- [ ] Animations do not interfere with data or interaction.
- [ ] No trading strategy logic was moved into the browser.

## 20. Do not break the bot

The most important development rule is simple:

> **Improve the interface without silently changing the trading engine.**

If a requested UI improvement appears to require changing strategy behavior, stop and document the backend requirement separately before modifying the strategy code.
