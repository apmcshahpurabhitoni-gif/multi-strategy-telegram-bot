# Deployment Guide — Mavis Trading Bot

Three ways to deploy, pick one. All three serve the same dashboard at `/dashboard`.

---

## Option 1 — Render (recommended, free tier works)

### One-time: Telegram
1. `@BotFather` → `/newbot` → copy the **token**.
2. Send `/start` to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` → copy your **chat id** from the JSON.

### One-time: Supabase (strongly recommended)
Render's free tier wipes `/tmp` on restart. Supabase keeps your state alive (account balances, trade history, news cache, etc).

1. [supabase.com](https://supabase.com) → free project.
2. SQL editor → run:
   ```sql
   create table if not exists bot_data (
     key text primary key,
     value jsonb,
     updated_at timestamptz default now()
   );
   alter table bot_data enable row level security;
   create policy "service role full access" on bot_data
     for all using (true) with check (true);
   ```
3. **Settings → API** → copy **Project URL** + **service_role** key.

### Deploy
**Via Blueprint (easiest):**
1. Push this repo to GitHub.
2. Render → **New +** → **Blueprint** → pick the repo.
3. Render reads `render.yaml` and pre-fills everything. You just enter the secret env vars in the dashboard.
4. Click **Apply**.

**Via Web Service (manual):**
1. Render → **New +** → **Web Service** → connect repo.
2. Settings:
   - Environment: **Python 3**
   - Build: `pip install --upgrade pip && pip install -r requirements.txt`
   - Start: `python main.py`
   - Health check path: `/ping`
3. Add env vars (see `.env.example`).
4. **Deploy**.

### Keep alive
Free tier sleeps after 15 min idle.
1. [cron-job.org](https://cron-job.org) → free account.
2. New cron: `GET https://<your-app>.onrender.com/ping`, every 10 min, 24/7.

### Verify
In Telegram within ~60 s:
```
✅ BOT STARTED
Started At: 18-Aug-2026 10:48 IST
⚠️ Any signal/sweep message older than this is STALE — do not act on it.
```
Then `/test` to confirm data feeds. Open `https://<your-app>.onrender.com/dashboard` to see the UI.

---

## Option 2 — Docker (any VPS: DigitalOcean, Hetzner, AWS Lightsail, Fly.io, etc.)

```bash
git clone https://github.com/<you>/multi-strategy-telegram-bot.git
cd multi-strategy-telegram-bot
cp .env.example .env   # fill in values
docker build -t mavis-trading-bot .
docker run -d --name mavis --restart unless-stopped --env-file .env -p 8080:8080 mavis-trading-bot
```

Reverse proxy with Caddy or nginx + Let's Encrypt for HTTPS (Telegram needs HTTPS webhook).

---

## Option 3 — Local (dev only)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in values
python main.py
```

Use a tunnel like `ngrok http 8080` and set `WEBHOOK_URL` to the HTTPS ngrok URL.

Open `http://localhost:8080/dashboard` for the UI.

---

## Dashboard tour

Once your bot is up, hit `/dashboard`. You should see:

- **🏠 Overview** — 4 account cards (Macro / Nifty / NY Session / Sweep 4H), Total Equity, Today/Week P/L (color-coded green/red), equity curve, risk strip
- **💼 Trades** — Live open trades with progress bars + close button; pending sweep setups
- **📡 Signals** — last 24h of signals with FRESH/STALE age tags
- **📜 History** — closed trades grouped by day with daily totals
- **📰 News** — economic calendar (HIGH events in red, MEDIUM in amber, etc.) with ET → IST times
- **🇮🇳 Nifty** — Nifty 50, Bank Nifty, and 15 NSE stocks with live prices
- **🧪 Backtest** — pick a symbol/strategy/duration, hit Run, get an equity curve + 12 metrics + trade list

### Theme cycle (top-right 🌑/☀️/🌙)

| Icon | Theme | Look |
|---|---|---|
| 🌑 | Normal | warm grey on off-white, black borders — calm terminal look |
| ☀️ | Light | white card on off-white bg, black borders, accent from 🎨 |
| 🌙 | Dark | dark grey on near-black, off-white borders — high contrast |

Click 🎨 to open the accent picker and pick any color (16 presets + custom hex). The accent drives the active tab color, the highlight bar on Nifty cards, the news-day pills, the success indicators — everything.

Choices are saved in `localStorage` (`mavis_theme`, `mavis_accent`) — they survive page refresh and redeploys.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Telegram bot doesn't respond | Wrong token / chat id | Re-check `.env` |
| Prices show ₹0 | yfinance blocked your IP | Wait — fallback should kick in. Check logs. |
| State resets on every restart | No Supabase configured | Add `SUPABASE_URL` + `SUPABASE_KEY` |
| Render app is "sleeping" | Free tier idle | Add cron-job.org ping every 10 min |
| News tab is empty | API down / cache empty | Run `/refreshnews` in Telegram, then reload the dashboard. The dashboard will re-render the news section. |
| Backtest returns "cannot access local variable 'sl'" | (Fixed in current `backtest.py`) | Pull the latest code — the SHORT branch of TrendPulse was assigning `sl` and `qty` in a single tuple line. |
| Bottom nav buttons are squashed on mobile | (Fixed in current `dashboard/index.html`) | Pull the latest code — the tab bar is now a CSS Grid with proper safe-area-inset. |
| Dashboard colors look "off" / too blue / too purple | (Fixed in current `dashboard/index.html`) | The three themes are now grey / white+custom / dark-grey+off-white. Use the 🎨 button to pick the exact accent. |
| Tab text unreadable on custom accent | Auto-contrast | The active tab's text color is computed from accent luminance — should always be readable. If you find a bad case, open a ticket. |

---

## Updating

```bash
git pull
# if you use Render Blueprint: just push, Render auto-rebuilds
# if you use Docker:    docker build -t mavis-trading-bot . && docker restart mavis
# if you use Local:     Ctrl-C, then python main.py again
```

Your theme + accent choices live in the browser's `localStorage` — they don't need to be re-picked after an update.
