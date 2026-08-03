"""
Dashboard API for the multi-strategy Telegram bot.
==================================================

Fixed: Now handles both 'main' and '__main__' module names.
Fixed: Handles boolean sent_signals values (old format) and dict values (new format).

Drop this file at the REPO ROOT (next to main.py).
"""

import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta
from urllib.parse import parse_qs

# Cache TTLs (seconds)
PRICE_TTL = 60
SNAPSHOT_TTL = 15
NEWS_TTL = 600

_snapshot_cache = {"data": None, "ts": 0}
_snapshot_lock = threading.RLock()

# Resolve the HTML path once, at import time.
_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML_PATH = os.path.join(_HERE, "dashboard", "index.html")


def _get_main_module():
    """Get the main module - handles both 'main' and '__main__' module names."""
    # Try '__main__' first (when running with `python main.py`)
    main = sys.modules.get("__main__")
    if main is not None:
        return main
    # Fallback to 'main' (for direct imports)
    return sys.modules.get("main")


# ----------------------------------------------------------------
# 1. Batch live prices
# ----------------------------------------------------------------
def _batch_live_prices(symbols):
    """Fetch live prices. Uses main.py _price_cache first, yf.download as fallback."""
    if not symbols:
        return {}

    main = _get_main_module()
    if main is None:
        return {}

    _price_cache = getattr(main, "_price_cache", None)
    _lock = getattr(main, "_lock", None)
    yf_lib = getattr(main, "yf", None)
    _yf_session = getattr(main, "_yf_session", None)

    out = {}
    need = []
    now = time.time()

    # STEP 1: Read from main.py's price cache (updated by monitor/scanner every 15s)
    if _price_cache is not None and _lock is not None:
        with _lock:
            for s in symbols:
                if s in _price_cache:
                    p, ts = _price_cache[s]
                    if now - ts < 120:  # 2 min tolerance
                        out[s] = p
                        continue
                need.append(s)
    else:
        need = list(symbols)

    if not need:
        return out

    # STEP 2: Fallback to yf.download for missing symbols (with rate limit protection)
    if not (yf_lib and _yf_session):
        return out

    try:
        # Wait a bit to avoid hammering Yahoo alongside scanner/monitor
        time.sleep(0.5)
        
        df = yf_lib.download(
            tickers=need,
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=True,
            threads=False,
            session=_yf_session,
        )
        if df is None or df.empty:
            return out

        if len(need) == 1:
            sym = need[0]
            try:
                # Handle both flat and MultiIndex columns
                close_vals = df["Close"]
                if hasattr(close_vals, 'iloc'):
                    p = float(close_vals.iloc[-1])
                else:
                    p = float(close_vals[-1])
                out[sym] = p
                if _price_cache is not None and _lock is not None:
                    with _lock:
                        _price_cache[sym] = (p, now)
            except Exception as e:
                print(f"[PRICE] Single ticker fallback failed for {sym}: {e}")
            return out

        if hasattr(df.columns, 'nlevels') and df.columns.nlevels > 1:
            for sym in need:
                try:
                    p = float(df[sym]["Close"].iloc[-1])
                    out[sym] = p
                    if _price_cache is not None and _lock is not None:
                        with _lock:
                            _price_cache[sym] = (p, now)
                except Exception:
                    continue
        else:
            for sym in need:
                try:
                    p = float(df["Close"].iloc[-1])
                    out[sym] = p
                    if _price_cache is not None and _lock is not None:
                        with _lock:
                            _price_cache[sym] = (p, now)
                except Exception:
                    continue
    except Exception as e:
        print(f"[ERR] _batch_live_prices: {e}")

    return out

# ----------------------------------------------------------------
# 2. Build the snapshot the dashboard renders
# ----------------------------------------------------------------
def _build_snapshot():
    main = _get_main_module()
    if main is None:
        return {"error": "main module not loaded"}

    accounts = getattr(main, "accounts", {})
    active_trades = getattr(main, "active_trades", [])
    _lock = getattr(main, "_lock", None)
    load_json = getattr(main, "load_json", None)
    ACCOUNT_LIMITS = getattr(main, "ACCOUNT_LIMITS", {})
    is_ny_session = getattr(main, "is_ny_session", None)
    FVG_EXPIRY_HOURS = getattr(main, "FVG_EXPIRY_HOURS", 24)
    HISTORY_FILE = getattr(main, "HISTORY_FILE", "trade_history.json")
    SENT_SIGNALS_FILE = getattr(main, "SENT_SIGNALS_FILE", "sent_signals.json")
    PENDING_SWEEPS_FILE = getattr(main, "PENDING_SWEEPS_FILE", "pending_sweeps.json")
    pending_sweeps = getattr(main, "pending_sweeps", [])
    get_cached_news = getattr(main, "get_cached_news", None)
    IST = getattr(main, "IST", None)

    if not all([_lock, load_json, IST]):
        return {"error": "missing bot globals"}

    try:
        now = datetime.now(IST)
    except Exception:
        now = datetime.now()

    today_str = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    history = load_json(HISTORY_FILE, []) if load_json else []
    # Read sent_signals from file, fallback to in-memory dict
    sent = load_json(SENT_SIGNALS_FILE, {}) if load_json else {}
    sent_memory = getattr(main, "sent_signals", {})
    if isinstance(sent_memory, dict) and len(sent_memory) > len(sent):
        print(f"[API] Using in-memory sent_signals ({len(sent_memory)}) vs file ({len(sent)})")
        sent = sent_memory
    
    pending = list(pending_sweeps) if pending_sweeps else (load_json(PENDING_SWEEPS_FILE, []) if load_json else [])

    # Per-account today/week P/L
    per_acc_today = {k: 0.0 for k in accounts}
    per_acc_week = {k: 0.0 for k in accounts}
    for t in history:
        acc = t.get("account")
        try:
            pnl = float(t.get("pnl", 0))
        except Exception:
            pnl = 0.0
        ts = str(t.get("closed_at", t.get("close_time", t.get("time", t.get("timestamp", "")))))
        date_part = ts[:10]
        if acc in per_acc_today:
            if date_part == today_str:
                per_acc_today[acc] += pnl
            if date_part >= week_start:
                per_acc_week[acc] += pnl

    # Accounts view
    accounts_view = {}
    for key, acc in (accounts or {}).items():
        if not isinstance(acc, dict):
            continue
        ny_active = False
        if key == "ny_session" and is_ny_session:
            try:
                ny_active = is_ny_session()
            except Exception:
                ny_active = False
        accounts_view[key] = {
            "name": key.replace("_", " ").title(),
            "balance": float(acc.get("balance", 0)),
            "daily_trades": int(acc.get("daily_trades", 0)),
            "daily_limit": int(ACCOUNT_LIMITS.get(key, 0)),
            "today_pnl": round(per_acc_today.get(key, 0.0), 2),
            "week_pnl": round(per_acc_week.get(key, 0.0), 2),
            "is_active": ny_active,
        }

    # Live trades
    symbols = list({t.get("symbol") for t in active_trades if t.get("symbol")})
    live = _batch_live_prices(symbols) if symbols else {}

    live_trades_view = []
    for t in active_trades:
        sym = t.get("symbol")
        entry = float(t.get("entry", 0))
        sl = float(t.get("sl", 0))
        tp = float(t.get("tp", 0))
        qty = float(t.get("qty", 0))
        direction = str(t.get("type", t.get("direction", "LONG"))).upper()
        is_long = "BULL" in direction or "LONG" in direction
        cur = live.get(sym, entry)
        pnl = (cur - entry) * qty * (1 if is_long else -1)
        if is_long and tp != entry:
            progress = max(0.0, min(100.0, (cur - entry) / (tp - entry) * 100.0))
        elif (not is_long) and entry != tp:
            progress = max(0.0, min(100.0, (entry - cur) / (entry - tp) * 100.0))
        else:
            progress = 0.0
        live_trades_view.append({
            "symbol": sym,
            "market": t.get("market", t.get("mtype", "—")),
            "account": t.get("account", ""),
            "direction": "LONG" if is_long else "SHORT",
            "entry": entry, "current": cur, "sl": sl, "tp": tp,
            "qty": qty, "pnl_inr": round(pnl, 2),
            "progress": round(progress, 1),
            "opened": t.get("opened_at", t.get("opened", "")),
        })

    # Today signals (last 24h from sent_signals)
    today_signals = []
    cutoff = time.time() * 1000 - 24 * 3600 * 1000
    print(f"[API] sent_signals count: {len(sent)}, memory: {len(sent_memory)}, cutoff: {cutoff}")
    for key, sig in (sent or {}).items():
        ts_ms = 0
        sym = ""
        sig_type = ""
        strat = ""
        status = "open"
        pnl = 0
        hint = ""
        time_str = ""

        if isinstance(sig, dict):
            # New format: {key: {ts_ms, symbol, ...}}
            ts_ms = sig.get("ts_ms", 0)
            sym = sig.get("symbol", "")
            sig_type = sig.get("sig_type", "")
            strat = sig.get("strat", "")
            status = sig.get("status", "open")
            pnl = sig.get("pnl", 0)
            hint = sig.get("hint", "")
            time_str = sig.get("time_str", "")
        else:
            # Old format: {key: True} — parse key like "BTC-USD_1234567890123_BULLISH_macro"
            parts = str(key).split("_")
            if len(parts) >= 3:
                sym = parts[0]
                try:
                    ts_ms = int(parts[1])
                except ValueError:
                    ts_ms = 0
                sig_type = parts[2]
                strat = parts[3] if len(parts) > 3 else ""
            time_str = datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M") if ts_ms else ""

        if ts_ms < cutoff:
            continue

        today_signals.append({
            "time": time_str[-5:] if len(time_str) >= 5 else time_str,
            "sym": sym,
            "dir": "LONG" if "BULL" in str(sig_type).upper() else "SHORT",
            "strategy": strat,
            "status": status,
            "pnl": pnl,
            "hint": hint,
        })
    today_signals.sort(key=lambda x: x.get("time", ""), reverse=True)

    # History (last 15)
    last_history = sorted(
        history,
        key=lambda x: str(x.get("closed_at", x.get("time", x.get("timestamp", "")))),
        reverse=True,
    )[:15]

    # Pending sweeps
    pending_view = []
    for p in pending or []:
        if p.get("status") in ("entered", "expired", "invalidated"):
            continue
        zone = p.get("fvg_zone")
        try:
            expires_h = max(
                0.0,
                (p["sweep_close_ts"] + FVG_EXPIRY_HOURS * 3600 * 1000 - time.time() * 1000) / 3600000.0,
            )
        except Exception:
            expires_h = 0.0
        pending_view.append({
            "sym": p.get("symbol", ""),
            "dir": p.get("direction", "BULLISH"),
            "status": "waiting-fill" if zone else "waiting-fvg",
            "zone": zone,
            "expires_h": round(expires_h, 1),
        })

    # News
    news = []
    if get_cached_news:
        try:
            raw = get_cached_news()[:120]
            news = []
            for ev in raw:
                ev_copy = dict(ev)
                ev_copy["impact"] = str(ev.get("impact", "")).upper()
                news.append(ev_copy)
        except Exception:
            news = []

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "accounts": accounts_view,
        "live_trades": live_trades_view,
        "today_signals": today_signals,
        "history": last_history,
        "pending": pending_view,
        "news_raw": news,
    }


def _get_snapshot_cached():
    now = time.time()
    with _snapshot_lock:
        if _snapshot_cache["data"] is not None and (now - _snapshot_cache["ts"]) < SNAPSHOT_TTL:
            return {
                "cached": True,
                "cache_age_s": int(now - _snapshot_cache["ts"]),
                **_snapshot_cache["data"],
            }
        snap = _build_snapshot()
        _snapshot_cache["data"] = snap
        _snapshot_cache["ts"] = now
        return {"cached": False, **snap}


# ----------------------------------------------------------------
# 3. Response helpers
# ----------------------------------------------------------------
def _json_response(start_response, payload, status="200 OK"):
    body = json.dumps(payload, default=str).encode("utf-8")
    start_response(status, [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ])
    return [body]


def _html_response(start_response, body, status="200 OK"):
    if isinstance(body, str):
        body = body.encode("utf-8")
    start_response(status, [
        ("Content-Type", "text/html; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ])
    return [body]


# ----------------------------------------------------------------
# 4. Route handlers
# ----------------------------------------------------------------
def _route_dashboard(start_response):
    try:
        payload = _get_snapshot_cached()
        return _json_response(start_response, payload)
    except Exception as e:
        return _json_response(start_response, {"error": str(e)}, status="500 Internal Server Error")


def _route_prices(start_response, query):
    params = parse_qs(query or "")
    syms = params.get("symbols", [""])[0].split(",")
    syms = [s.strip() for s in syms if s.strip()]
    prices = _batch_live_prices(syms)
    return _json_response(start_response, {"prices": prices, "ts": int(time.time())})


def _route_health(start_response):
    return _json_response(start_response, {"ok": True, "ts": int(time.time())})


def _route_dashboard_html(start_response):
    if not os.path.exists(_HTML_PATH):
        return _html_response(
            start_response,
            "<h1>Dashboard not found</h1><p>Expected at: " + _HTML_PATH + "</p>",
            status="404 Not Found",
        )
    try:
        with open(_HTML_PATH, "rb") as f:
            body = f.read()
        return _html_response(start_response, body)
    except Exception as e:
        return _html_response(start_response, f"<h1>Error</h1><pre>{e}</pre>", status="500 Internal Server Error")


# ----------------------------------------------------------------
# 5. Mount helper
# ----------------------------------------------------------------
def register_routes(path, start_response, environ):
    """
    Call this from inside your app() function.
    Returns the response iterable, or None to let the caller fall through.
    """
    method = environ.get("REQUEST_METHOD", "GET")
    qs = environ.get("QUERY_STRING", "")

    if path == "/dashboard" or path == "/dashboard/":
        return _route_dashboard_html(start_response)

    if path == "/api/dashboard":
        return _route_dashboard(start_response)

    if path.startswith("/api/prices"):
        return _route_prices(start_response, qs)

    if path == "/api/health":
        return _route_health(start_response)

    return None
