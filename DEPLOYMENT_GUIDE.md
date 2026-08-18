# Deployment Guide — Mavis Trading Bot

Three ways to deploy, pick one.

---

## Option 1 — Render (recommended, free tier works)

### One-time: Telegram
1. `@BotFather` → `/newbot` → copy the **token**.
2. Send `/start` to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` → copy your **chat id** from the JSON.

### One-time: Supabase (strongly recommended)
Render's free tier wipes `/tmp` on restart. Supabase keeps your state alive.

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
Then `/test` to confirm data feeds.

---

## Option 2 — Docker (any VPS: DigitalOcean, Hetzner, AWS Lightsail, etc.)

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

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Telegram bot doesn't respond | Wrong token / chat id | Re-check `.env` |
| Prices show ₹0 | yfinance blocked your IP | Wait — fallback should kick in. Check logs. |
| State resets on every restart | No Supabase configured | Add `SUPABASE_URL` + `SUPABASE_KEY` |
| Render app is "sleeping" | Free tier idle | Add cron-job.org ping every 10 min |
| News tab is empty | API down / date parse bug | Run `/refreshnews` in Telegram, check logs |
| `Daily Reset` errors in logs | (Fixed) | Redeploy — purges bad keys automatically |
