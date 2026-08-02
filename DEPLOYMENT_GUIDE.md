# 🚀 Deployment Guide - Dashboard Fix

## The Problem
Your dashboard was showing all zeros because the API endpoint `/api/dashboard` was returning an error:
```
{"cached": false, "error": "main module not loaded"}
```

**Root Cause:** The `dashboard_api.py` file was checking `sys.modules.get("main")` but Python stores the main module as `__main__` when running with `python main.py`.

---

## Quick Fix (3 Options)

### Option 1: Replace the file on GitHub (Recommended)

1. **Go to your GitHub repo:** https://github.com/apmcshahpurabhitoni-gif/multi-strategy-telegram-bot

2. **Click on `dashboard_api.py` → Edit (pencil icon)**

3. **Replace the entire file** with the fixed version I've provided

4. **Commit changes** with message: "Fix: handle __main__ module name for API"

5. **Render will auto-deploy** within ~30 seconds

### Option 2: Manual Replace via Git

```bash
# Clone the repo
git clone https://github.com/apmcshahpurabhitoni-gif/multi-strategy-telegram-bot.git
cd multi-strategy-telegram-bot

# Replace dashboard_api.py with the fixed version

# Commit and push
git add dashboard_api.py
git commit -m "Fix: handle __main__ module name for API"
git push origin main
```

### Option 3: Direct Edit on Render

1. Log into Render Dashboard
2. Go to your service → Shell
3. Run: `nano dashboard_api.py`
4. Find and replace the `_get_main_module()` function (or the problematic line)
5. Save and restart the service

---

## Verify the Fix

After deploying, test the API:

```bash
curl https://multi-strategy-telegram-bot-1.onrender.com/api/dashboard
```

**Before (Broken):**
```json
{"cached": false, "error": "main module not loaded"}
```

**After (Fixed):**
```json
{
  "generated_at": "2026-08-02 10:30:00 IST",
  "accounts": {
    "macro": {"balance": 112450.30, ...},
    ...
  },
  "live_trades": [...],
  ...
}
```

Then open your dashboard: https://multi-strategy-telegram-bot-1.onrender.com/dashboard

---

## Files That Are Useless (Safe to Delete)

These files serve no purpose and bloat your repo:

### Completely Dead Code
```
src/                          ← Dead React app, never deployed
├── App.tsx
├── components/
├── src/data/initialData.ts
├── src/types.ts
├── src/utils/formatters.ts
├── src/index.css
├── src/main.tsx

server.ts                     ← Dev server for dead React app
vite.config.ts                ← Vite config for dead React app
package.json                  ← Node deps for dead React app (you have bun.lock too)
tsconfig.json                 ← TS config for dead React app
index.html                    ← Root placeholder HTML, not your dashboard
```

### How to Remove Them

```bash
git rm -r src/
git rm server.ts vite.config.ts package.json tsconfig.json index.html
git commit -m "Remove dead React app files"
git push origin main
```

### Keep These Files
```
✅ dashboard_api.py          ← Fixed, serves your dashboard API
✅ dashboard/index.html      ← Your actual dashboard
✅ main.py                   ← Main trading bot
✅ Dockerfile                ← Render deployment
✅ requirements.txt         ← Python dependencies
✅ render.yaml               ← Render config
✅ .env.example              ← Environment template
✅ .gitignore
✅ README.md
✅ metadata.json (if you use it)
✅ bun.lock (if you use Bun)
✅ runtime.txt
```

---

## Dashboard Behavior Explained

| State | Dashboard Shows | Status Pill |
|-------|----------------|-------------|
| API Working | Real data from your bot | 🟢 LIVE |
| API Down | MOCK demo data (₹1,12,450 etc) | 🟡 DEMO |
| Both Fail | Error message + retry button | 🔴 ERROR |

The MOCK fallback is intentional - it lets you see the dashboard layout even when the trading bot has no real data yet.

---

## Troubleshooting

### "main module not loaded" persists
- Make sure you're running the latest `dashboard_api.py`
- Check Render logs: Dashboard → Logs
- Restart the service manually

### Dashboard still empty
- Check browser console (F12 → Console) for JavaScript errors
- Verify `/api/dashboard` returns valid JSON (not an error)
- Clear browser cache

### Server is sleeping (Render Free Tier)
- Visit https://multi-strategy-telegram-bot-1.onrender.com/ping
- Wait 30 seconds for the server to wake up
- The dashboard will auto-refresh when server wakes

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                      Your Browser                          │
│                                                             │
│   GET /dashboard → Returns dashboard/index.html            │
│   GET /api/dashboard → Returns JSON snapshot               │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Render Server                             │
│                                                             │
│   main.py (Telegram Bot + Scanner + Monitor)               │
│       │                                                     │
│       ├── Imports dashboard_api.py                          │
│       └── run_web() → WSGI Server on PORT 10000            │
│                                                             │
│   dashboard_api.py                                          │
│       ├── register_routes() → Routes API requests          │
│       ├── _build_snapshot() → Reads bot's state            │
│       └── Returns JSON with accounts, trades, etc.         │
└─────────────────────────────────────────────────────────────┘
```

╔══════════════════════════════════════════════════════════════════════════════╗
║                    COMPLETE FIX — ALL IN ONE GO                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

You have 4 problems. Here are ALL the fixes:

┌──────────────────────────────────────────────────────────────────────────────┐
│ PROBLEM 1: Dashboard blank (--:--:--, all zeros)                             │
│ PROBLEM 2: Live trade not showing (BTC-USD exists in API)                     │
│ PROBLEM 3: News not showing (100+ events in API)                              │
│ PROBLEM 4: Today's signals empty                                              │
│ PROBLEM 5: Clock shows 24h instead of 12h AM/PM                              │
└──────────────────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════════
STEP 1: REPLACE dashboard/index.html
═══════════════════════════════════════════════════════════════════════════════

Download this file:
📎 dashboard_complete_fix.html

Copy its contents and PASTE OVER your entire dashboard/index.html file.
Do NOT make partial edits. Replace the WHOLE file.

What this fixes:
  ✅ 12-hour clock with AM/PM (01:30:45 PM instead of 13:30:45)
  ✅ Clock shows immediately (no more --:--:--)
  ✅ API timeout 30s instead of 12s (Render cold-start needs time)
  ✅ renderAll() never bails — always renders even if API fails
  ✅ Console logging so you can debug in browser
  ✅ Global error handlers catch JS crashes
  ✅ News parses ISO datetime correctly

═══════════════════════════════════════════════════════════════════════════════
STEP 2: REPLACE dashboard_api.py
═══════════════════════════════════════════════════════════════════════════════

Download this file:
📎 dashboard_api_fixed.py

Copy its contents and PASTE OVER your entire dashboard_api.py file.

What this fixes:
  ✅ today_signals now works with boolean sent_signals (old format)
  ✅ Parses signal keys like "BTC-USD_1234567890123_BULLISH_macro"
  ✅ Extracts symbol, timestamp, direction, account from key
  ✅ Shows signals that triggered your trades

═══════════════════════════════════════════════════════════════════════════════
STEP 3: COMMIT & PUSH
═══════════════════════════════════════════════════════════════════════════════

git add dashboard/index.html dashboard_api.py
git commit -m "Fix dashboard: 12h clock, render fallback, signal parsing, 30s timeout"
git push origin main

═══════════════════════════════════════════════════════════════════════════════
STEP 4: WAIT & VERIFY
═══════════════════════════════════════════════════════════════════════════════

1. Go to Render dashboard → your service → wait for "Deploy in progress..." to finish
2. Open: https://multi-strategy-telegram-bot-1.onrender.com/dashboard
3. Hard refresh: Ctrl+Shift+R (or Cmd+Shift+R on Mac)
4. Open DevTools (F12) → Console

You should see:
  [Dashboard] Starting bootstrap...
  [Dashboard] API loaded, keys: ["accounts", "live_trades", "today_signals", ...]

Then on the page you should see:
  ✅ Clock: "01:25:45 PM IST · Updated just now · 02/08"
  ✅ Total Equity: ₹4,00,000.00
  ✅ Live Open Trades: 1 (BTC-USD LONG)
  ✅ Today's Signals: your signal(s)
  ✅ Weekly Economic Calendar: all 100+ events

═══════════════════════════════════════════════════════════════════════════════
WHY THESE FIXES WERE NEEDED
═══════════════════════════════════════════════════════════════════════════════

1. BLANK DASHBOARD
   renderAll() had: if (!state.snapshot) return;
   When API was slow, snapshot was null → renderAll bailed → nothing rendered
   Fix: Remove guard, use MOCK fallback if API fails

2. --:--:-- CLOCK
   updateClock() only ran via setInterval(1000) — 1 second delay
   renderAll() bailed before setting state.lastFullUpdate
   Fix: Call updateClock() immediately before setInterval

3. LIVE TRADE HIDDEN
   Same as #1 — renderAll() bailed before renderLiveTrades()
   Fix: Same as #1

4. TODAY'S SIGNALS EMPTY
   sent_signals.json stores: {"BTC-USD_1234567890123_BULLISH_macro": true}
   dashboard_api.py expected: {"key": {"ts_ms": 123, "symbol": "BTC"...}}
   isinstance(sig, dict) was always False → all signals skipped
   Fix: Parse the key string when value is boolean

5. NEWS HIDDEN
   Same as #1 — renderAll() bailed before renderNews()
   Fix: Same as #1

6. 24-HOUR CLOCK
   You wanted AM/PM format
   Fix: Add h%12 logic with AM/PM suffix
