# Mavis Trading Bot

Mavis is a multi-strategy **paper-trading** Telegram bot with Sweep Engine V2, TrendPulse, persistent state, a dashboard, news calendar and backtesting tools.

> **Paper trading only.** Market data and backtests are not guaranteed execution feeds. Verify important signals against the authoritative market source.

## Features

- Telegram signal and paper-trade notifications
- Deterministic Sweep Engine V2
- TrendPulse strategy
- Persistent balances, trades and history
- Dashboard at `/dashboard`
- Mobile-first responsive UI
- Four dashboard themes: **Modern Light, Modern Dark, Neo-Brutalist Light, Neo-Brutalist Dark**
- Accent colors saved in browser storage
- Live trades, signals, history, news and backtests
- Render, Docker and local deployment

## Sweep Engine V2

A sweep exists only when the completed current candle breaks both sides of the previous candle:

```text
Current High > Previous High
AND
Current Low  < Previous Low
```

The completed candle Close then classifies the signal:

```text
Close > Previous High                    -> BUY
Previous Low <= Close <= Previous High  -> NEUTRAL SWEEP
Close < Previous Low                     -> SELL
```

If both sides are not broken: **NO SIGNAL**. Touch/equality does not count. Signals are evaluated only after the candle is closed.

Paper-trade rules:

- BUY/SELL open a paper trade.
- Entry = market price when the closed-candle signal is detected.
- BUY SL = sweeping candle Low.
- SELL SL = sweeping candle High.
- TP = 1:2 risk/reward.
- NEUTRAL never opens a trade.

A qualifying sweep can generate an initial Telegram message and one one-hour reminder.

## Dashboard

The dashboard is a **mobile-first application**, not a desktop layout squeezed onto a phone.

### Navigation

Desktop shows one top navigation. Mobile shows one bottom navigation. There is no duplicated navigation on mobile.

- 🏠 Overview
- 📊 Trades
- ⚡ Signals
- 🕘 History
- 📰 News
- ⚙️ Tools

### Overview order

The first screen prioritizes:

1. Balance
2. Equity
3. Today's P&L
4. Bot state
5. Account
6. Open trades
7. Signals

Last-update time remains visible.

### Trades

Open trades use compact cards on mobile: symbol, direction, entry, current, P&L, SL, TP, progress and close action. No wide horizontal trade table is used on mobile.

### History

History uses short readable records rather than raw ISO timestamps/microseconds. Each date group shows the day's trades, and the page also shows total P&L, today's P&L, and wins/losses.

### News

News is **date-first**, then chronological by time. Impact is a visual accent rather than the primary grouping:

- 🔴 HIGH
- 🟠 MEDIUM
- 🟢 LOW / other

Today's events are shown first, followed by upcoming dates.

### Four themes

| Design system | Light | Dark |
|---|---|---|
| Modern | Modern Light | Modern Dark |
| Neo-Brutalist | Neo-Brutalist Light | Neo-Brutalist Dark |

Each light/dark pair keeps the same layout and design language. Theme and accent selections persist in `localStorage`.

### Motion

Motion is purposeful and consistent with each style: smooth panel/card transitions, subtle live pulse, animated number changes, refresh feedback, news/trade entrance motion and neo-brutalist press behavior. `prefers-reduced-motion` is respected.

## Architecture

```text
main.py             existing bot, Telegram integration, accounts and state
sweep_engine.py     canonical Sweep Engine V2
sweep_runtime.py    sweep integration with scanning/Telegram/paper trades
run_bot.py          production startup entry point
backtest.py         backtesting engine
dashboard_api.py    dashboard HTTP/API and snapshot builder
dashboard/index.html self-contained dashboard UI
db.py               persistence helpers
render.yaml         Render deployment
Dockerfile          Docker deployment
Procfile            process startup declaration
```

The dashboard is a presentation layer. It consumes the existing API/state and does **not** move trading decisions or execution logic into JavaScript.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run_bot.py
```

Open `http://localhost:8080/dashboard`.

**Use `python run_bot.py` as the normal startup command.** `main.py` remains part of the application but is not the recommended deployment entry point.

## Deployment

- Render: `render.yaml` + `DEPLOYMENT_GUIDE.md`
- Docker: `Dockerfile` + `DEPLOYMENT_GUIDE.md`
- Local: `python run_bot.py`

## Verification checklist

Strategy:

- [ ] Current candle is closed.
- [ ] Current High > previous High.
- [ ] Current Low < previous Low.
- [ ] Close determines BUY / NEUTRAL / SELL.
- [ ] Candle times match the configured schedule.
- [ ] OHLC and prices match the authoritative reference when required.
- [ ] Data-source warnings are reviewed.

Dashboard:

- [ ] No horizontal overflow on mobile.
- [ ] Only one mobile navigation is visible.
- [ ] All six sections have icons.
- [ ] Overview shows balance/equity/today P&L/state/account/last update first.
- [ ] History uses short times and P&L totals.
- [ ] News is date-first and chronological.
- [ ] All four themes persist after reload.
- [ ] Animations remain smooth and respect reduced motion.
- [ ] Trading endpoints and strategy logic are unchanged.

## Legacy note

Older versions contained `4H Sweep + FVG`. FVG confirmation is **not part of Sweep Engine V2**. Sweep V2 acts immediately after a qualifying closed candle: both-side break, Close classification, then BUY/SELL paper execution or NEUTRAL information only.
