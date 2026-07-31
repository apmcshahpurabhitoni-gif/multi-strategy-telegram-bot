# Mavis Trade Command Center — Dashboard

A single-page dashboard for the Telegram trading bot. Everything you used to
check via `/stats`, `/balance`, `/summary`, `/news`, `/pending` — on one screen.

## Files in this folder

| File | What it is |
|---|---|
| `index.html` | The dashboard. Open it in a browser. Self-contained, no build step. |
| `api_integration.py` | Drop-in API endpoints (`/api/dashboard`, `/api/prices`) for the bot. |
| `README.md` | This file. |

---

## What's on the page (top to bottom)

1. **Topbar** — live status, IST clock, manual refresh
2. **5 KPI cards** — Total Equity · Today P/L · This Week · Open Trades · Win Rate
3. **4 account cards** — Macro · Nifty · NY Session · Sweep 4H
   - Balance, today's P/L, weekly P/L, daily-trade usage bar
4. **Live Open Trades** (left) — every active trade with LIVE P/L, SL, TP, progress bar
5. **Today's Signals** (right) — all signals fired today, color-coded WIN/LOSS/OPEN/PENDING
6. **Cumulative P/L** chart (left) — toggleable per-account
7. **Daily P/L** chart (right) — this week / last 30 days
8. **Last Closed Trades** (left) — 15 most recent, with WR summary
9. **Pending Setups** (right) — Sweeps waiting for FVG, with expiry countdowns
10. **Weekly Economic Calendar** — full week, color-coded by impact, ET + IST

---

## The rate-limit problem (and how this solves it)

Naive approach: poll yfinance per-symbol every few seconds → 429 in minutes.

This dashboard's solution: **batch + cache + single endpoint**.

```
Dashboard tab ──> GET /api/dashboard ──> server builds snapshot (15s cache)
                                            │
                                            └─> _batch_live_prices(symbols)
                                                    │
                                                    ├─> check _price_cache (60s TTL)
                                                    └─> ONE yf.download for all uncached
                                                            (single HTTP call to Yahoo)
```

**Numbers**: 5 active symbols, dashboard polls every 30s →
- 1 yfinance call per minute total
- works with 10 tabs open or 1, same backend load
- never modifies `_price_cache`, `_yf_session`, or any trading logic

---

## How to wire it into the bot

### Step 1 — Add the API code

Open `api_integration.py` and copy the **three function blocks** into your `bot.py`:

1. `_batch_live_prices(symbols)` — paste anywhere at module level
2. `_build_dashboard_snapshot()` — paste anywhere at module level
3. `_dashboard_route` + `_prices_route` — paste at module level

### Step 2 — Wire the routes into the WSGI app

In your existing `run_web()` function, inside `app(environ, start_response)`,
add the new branches **alongside** the existing `/ping` and `/webhook` handlers:

```python
from urllib.parse import parse_qs

# ... inside app() ...
if path.startswith("/api/dashboard"):
    return _dashboard_route(start_response)

if path.startswith("/api/prices"):
    params = parse_qs(environ.get("QUERY_STRING", ""))
    syms = params.get("symbols", [""])[0].split(",")
    syms = [s.strip() for s in syms if s.strip()]
    return _prices_route(start_response, syms)

if path == "/api/health":
    body = json.dumps({"ok": True, "ts": int(time.time())}).encode()
    start_response("200 OK", [("Content-Type", "application/json"),
                              ("Content-Length", str(len(body)))])
    return [body]
```

### Step 3 — Host the dashboard

Three options, easiest first:

**(a) Same origin, static file** — drop `index.html` into a `/workspace/dashboard/`
folder and have your WSGI serve it. Add one more branch:

```python
if path == "/" or path == "/dashboard":
    with open("/workspace/dashboard/index.html", "rb") as f:
        body = f.read()
    start_response("200 OK", [("Content-Type", "text/html"),
                              ("Content-Length", str(len(body)))])
    return [body]
```

**(b) Separate static host** — Render static site, Vercel, Netlify, GitHub Pages.
Just replace the `MOCK = { ... }` block in `index.html` with the real
`fetch("/api/dashboard")` code (snippet in `api_integration.py` Section 5).

**(c) Local only** — open `index.html` directly in a browser. The MOCK data
shows the full design.

### Step 4 — Swap the mock data for the real API

In `index.html`, find the `MOCK` object and replace the `<script>` block's
`renderAll()` call at the bottom with the real fetch:

```js
async function loadDashboard() {
  const res = await fetch("/api/dashboard", { cache: "no-store" });
  const data = await res.json();
  // Map API response → render functions
  MOCK.accounts = data.accounts;
  MOCK.live_trades = data.live_trades;
  MOCK.today_signals = data.today_signals;
  MOCK.history = data.history;
  MOCK.pending = data.pending;
  // news: API returns raw ff_calendar — group by date in renderNews()
  renderAll();
}
loadDashboard();
setInterval(loadDashboard, 30000);
```

---

## What this does NOT change

- `execute()` — trade execution untouched
- `check_ut()` / `check_sweep()` / `find_fvg()` — strategies untouched
- `manage_pending_sweeps()` — pending-sweep loop untouched
- `news_alert_loop()` / `signal_check_loop()` — background loops untouched
- All Telegram command handlers — untouched
- `_price_cache` — only read, never cleared or modified
- `_yf_session` — only reused, never re-created
- All JSON file formats — only read

The dashboard is **additive only**: 2 new endpoints + 1 new batch helper.

---

## Quick test

After wiring it in:

```bash
# Server health
curl https://your-app.onrender.com/api/health
# {"ok": true, "ts": 1753967...}

# Full snapshot
curl https://your-app.onrender.com/api/dashboard | python -m json.tool | head -40

# Just prices
curl 'https://your-app.onrender.com/api/prices?symbols=EURUSD=X,GC=F,BTC-USD'
# {"prices": {"EURUSD=X": 1.0876, "GC=F": 2372.1, "BTC-USD": 61890.0}, ...}
```

Then open `index.html` (or `https://your-app/dashboard`) and you should see
real data, not the MOCK.
