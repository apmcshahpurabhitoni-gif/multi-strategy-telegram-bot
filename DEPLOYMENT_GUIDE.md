# Mavis Trading Bot — Deployment Guide

This guide reflects the current startup architecture and the mobile-first dashboard.

> **Production startup command: `python run_bot.py`.** Do not use `python main.py` as the deployment command. `main.py` is the existing application module; `run_bot.py` is the production entry point that installs the current runtime and starts the normal services.

## 1. Render (recommended)

### Required secrets

Set the variables listed in `.env.example`, including:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `SUPABASE_URL` and `SUPABASE_KEY` if persistent external state is required
- `WEBHOOK_URL` when using the configured webhook flow

### Blueprint deployment

1. Push the repository to GitHub.
2. Render → **New +** → **Blueprint**.
3. Select the repository.
4. Render reads `render.yaml`.
5. Enter the secret environment variables.
6. Deploy.

The current `render.yaml` uses:

```text
Build: pip install --upgrade pip && pip install -r requirements.txt
Start: python run_bot.py
Health: /ping
Port: 8080
```

### Manual Render service

If creating a Web Service manually:

```text
Environment: Python 3
Build: pip install --upgrade pip && pip install -r requirements.txt
Start: python run_bot.py
Health check: /ping
```

Do **not** replace the start command with `python main.py`.

## 2. Docker

```bash
git clone https://github.com/<you>/multi-strategy-telegram-bot.git
cd multi-strategy-telegram-bot
cp .env.example .env
# fill .env
docker build -t mavis-trading-bot .
docker run -d --name mavis --restart unless-stopped --env-file .env -p 8080:8080 mavis-trading-bot
```

The Docker image already starts:

```text
python run_bot.py
```

## 3. Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill .env
python run_bot.py
```

Dashboard:

```text
http://localhost:8080/dashboard
```

Health check:

```text
http://localhost:8080/ping
```

## 4. Telegram setup

1. Create the bot through BotFather.
2. Put the token in `TELEGRAM_BOT_TOKEN`.
3. Put the target chat ID in `TELEGRAM_CHAT_ID`.
4. Deploy.
5. Confirm the bot startup message.
6. Use the dashboard to verify live state.

## 5. Persistence

Render's filesystem is not a durable database. If state must survive restarts, configure the repository's supported Supabase persistence variables.

The persistent state is used for information such as balances, trade history and cached bot data according to the current application implementation.

## 6. Dashboard

Open `/dashboard` after the service is healthy.

### Mobile layout

Mobile uses one fixed bottom navigation:

```text
🏠 Overview · 📊 Trades · ⚡ Signals · 🕘 History · 📰 News · ⚙️ Tools
```

The desktop top navigation is hidden on mobile, so the dashboard does not show two navigation systems at once.

### Overview

The first screen prioritizes:

- Balance
- Equity
- Today's P&L
- State
- Account
- Open trades
- Signals
- Last update

### History

Closed trades are compact and grouped by date. Raw ISO timestamps and microseconds are intentionally not shown. The page includes total P&L, today's P&L, and wins/losses.

### News

News is grouped by date first, with today's events first and upcoming dates after it. Events are sorted by time inside each date. HIGH/MEDIUM/LOW impact is shown as a color accent rather than being the primary grouping.

### Themes

The dashboard has four selectable themes:

1. Modern Light
2. Modern Dark
3. Neo-Brutalist Light
4. Neo-Brutalist Dark

Modern Light/Dark share the modern design system. Neo-Brutalist Light/Dark share the neo-brutalist system. Accent colors are independent and persisted in browser storage.

### Motion

The dashboard uses purposeful animations for panel changes, cards, live status, numeric updates, refresh feedback and theme transitions. Reduced-motion preferences are respected.

## 7. Data-source warning

The dashboard and bot use the configured market-data provider. Yahoo Finance can cache, delay or rate-limit requests. A failed backtest or stale price is not automatically a strategy failure.

For instruments where another feed is authoritative, compare the candle and price against that source before acting.

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| Service fails to start | Confirm the start command is `python run_bot.py`. |
| `/dashboard` is unavailable | Check `/ping`, Render logs and the dashboard API response. |
| Telegram is silent | Verify token/chat ID and inspect service logs. |
| State resets after restart | Configure the supported Supabase persistence variables. |
| Prices are stale/zero | Check provider availability, cache and rate limits. |
| News is empty | Refresh the news source, then refresh the dashboard. |
| Backtest is incomplete | Treat it as a possible market-data/provider issue and retry later. |
| Mobile page moves sideways | The current dashboard is designed to prevent horizontal overflow; inspect browser zoom and any custom changes before changing the trading code. |
| Theme resets | Check browser storage and use one of the four supported theme names. |

## 9. Updating

### Render

Push to the configured branch. Render will rebuild from `render.yaml` when auto-deploy is enabled.

### Docker

```bash
git pull
docker build -t mavis-trading-bot .
docker restart mavis
```

### Local

Stop the current process and restart:

```bash
python run_bot.py
```

## 10. Safety boundary

The dashboard redesign is presentation-only. Keep these responsibilities in the Python application:

- strategy decisions
- candle construction
- signal validation
- risk calculation
- paper-trade execution
- Telegram messaging
- persistence

Do not implement trading decisions in dashboard JavaScript.
