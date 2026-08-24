import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta
from urllib.parse import parse_qs
import pytz

PRICE_TTL = 60
SNAPSHOT_TTL = 15
NEWS_TTL = 600

_snapshot_cache = {"data": None, "ts": 0}
_snapshot_lock = threading.RLock()

_HERE = os.path.dirname(os.path.abspath(__file__))
# Check templates or dashboard subfolder for index.html
_HTML_PATH_PRIMARY = os.path.join(_HERE, "templates", "index.html")
_HTML_PATH_FALLBACK = os.path.join(_HERE, "dashboard", "index.html")

def _get_html_content() -> bytes:
    if os.path.exists(_HTML_PATH_PRIMARY):
        with open(_HTML_PATH_PRIMARY, "rb") as f:
            return f.read()
    if os.path.exists(_HTML_PATH_FALLBACK):
        with open(_HTML_PATH_FALLBACK, "rb") as f:
            return f.read()
    return b"<h1>Dashboard template index.html not found.</h1>"

def _get_main_module():
    main = sys.modules.get("__main__")
    if main is not None: return main
    return sys.modules.get("main")

def _batch_live_prices(symbols):
    if not symbols: return {}
    main = _get_main_module()
    if main is None: return {}
    _price_cache = getattr(main, "_price_cache", None)
    _lock = getattr(main, "_lock", None)
    get_price_fn = getattr(main, "get_price", None)
    now = time.time()
    out = {}
    if _price_cache is not None and _lock is not None:
        with _lock:
            for s in symbols:
                if s in _price_cache:
                    p, ts = _price_cache[s]
                    if now - ts < 120: out[s] = p
    need = [s for s in symbols if s not in out]
    indices = [s for s in need if s.startswith("^")]
    regular = [s for s in need if not s.startswith("^")]
    if regular:
        try:
            import yfinance as yf
            df = yf.download(tickers=",".join(regular), period="1d", interval="1d", progress=False, threads=True, timeout=15)
            if df is not None and not df.empty:
                if len(regular) == 1:
                    close = df["Close"].dropna()
                    if not close.empty: out[regular[0]] = float(close.iloc[-1])
                else:
                    for s in regular:
                        try:
                            if s in df["Close"].columns:
                                val = df["Close"][s].dropna()
                                if not val.empty: out[s] = float(val.iloc[-1])
                        except Exception: pass
        except Exception as e: print(f"[PRICE] batch yf.download failed: {e}")
    for s in indices:
        if get_price_fn:
            try:
                p = get_price_fn(s)
                if p: out[s] = float(p)
            except Exception: pass
        time.sleep(0.2)
    still_need = [s for s in symbols if s not in out]
    if get_price_fn and still_need:
        for s in still_need:
            try:
                p = get_price_fn(s)
                if p: out[s] = float(p)
            except Exception: pass
            time.sleep(0.2)
    return out

DEFAULT_STARTING_EQUITY = 400000.0

def _build_equity_curve(history, starting_equity=DEFAULT_STARTING_EQUITY, days=60):
    if not history: return {"points": [], "current_equity": starting_equity, "max_drawdown_inr": 0.0, "max_drawdown_pct": 0.0}
    def _closed_key(t): return str(t.get("closed_at", t.get("close_time", t.get("time", t.get("timestamp", "")))))
    daily_pnl = {}
    for t in history:
        date_part = _closed_key(t)[:10]
        if not date_part: continue
        try: pnl = float(t.get("pnl", 0))
        except Exception: pnl = 0.0
        daily_pnl[date_part] = daily_pnl.get(date_part, 0.0) + pnl
    running, peak, max_dd_inr, max_dd_pct, points = starting_equity, starting_equity, 0.0, 0.0, []
    for date in sorted(daily_pnl.keys()):
        running += daily_pnl[date]
        peak = max(peak, running)
        dd = peak - running
        dd_pct = (dd / peak * 100.0) if peak > 0 else 0.0
        if dd > max_dd_inr: max_dd_inr, max_dd_pct = dd, dd_pct
        points.append({"date": date, "equity": round(running, 2)})
    points = points[-days:]
    return {"points": points, "current_equity": points[-1]["equity"] if points else starting_equity, "max_drawdown_inr": round(max_dd_inr, 2), "max_drawdown_pct": round(max_dd_pct, 2)}

def _build_risk(live_trades_view, equity_curve):
    total_exposure, total_risk_inr, trades_risk = 0.0, 0.0, []
    for t in live_trades_view:
        entry = float(t.get("entry", 0) or 0)
        sl = float(t.get("sl", 0) or 0)
        cur = float(t.get("current", 0) or entry)
        qty = float(t.get("qty", 0) or 0)
        is_long = t.get("direction") == "LONG"
        exposure = abs(entry * qty); total_exposure += exposure
        risk_per_unit = abs(entry - sl) if sl else 0.0
        initial_risk = risk_per_unit * qty; total_risk_inr += initial_risk
        r_multiple = round(((cur - entry) if is_long else (entry - cur)) / risk_per_unit, 2) if risk_per_unit > 0 else 0.0
        trades_risk.append({"symbol": t.get("symbol"), "account": t.get("account"), "direction": t.get("direction"), "r_multiple": r_multiple, "risk_inr": round(initial_risk, 2)})
    return {"total_exposure_inr": round(total_exposure, 2), "total_risk_inr": round(total_risk_inr, 2), "open_trades_risk": trades_risk, "max_drawdown_inr": equity_curve.get("max_drawdown_inr", 0.0), "max_drawdown_pct": equity_curve.get("max_drawdown_pct", 0.0)}

def _build_snapshot():
    main = _get_main_module()
    if main is None: return {"error": "main module not loaded"}
    accounts, active_trades, _lock = getattr(main, "accounts", {}), getattr(main, "active_trades", []), getattr(main, "_lock", None)
    load_json = getattr(main, "load_json", None)
    ACCOUNT_LIMITS, is_ny_session = getattr(main, "ACCOUNT_LIMITS", {}), getattr(main, "is_ny_session", None)
    HISTORY_FILE = getattr(main, "HISTORY_FILE", "trade_history.json")
    SENT_SIGNALS_FILE = getattr(main, "SENT_SIGNALS_FILE", "sent_signals.json")
    get_cached_news = getattr(main, "get_cached_news", None)
    IST_tz = getattr(main, "IST", pytz.timezone("Asia/Kolkata"))
    if not all([_lock, load_json, IST_tz]): return {"error": "missing bot globals"}
    try: now = datetime.now(IST_tz)
    except Exception: now = datetime.now()
    today_str, week_start = now.strftime("%Y-%m-%d"), (now - timedelta(days=7)).strftime("%Y-%m-%d")
    history = load_json(HISTORY_FILE, []) if load_json else []
    sent = load_json(SENT_SIGNALS_FILE, {}) if load_json else {}
    sent_memory = getattr(main, "sent_signals", {})
    if isinstance(sent_memory, dict) and len(sent_memory) > len(sent): sent = sent_memory
    per_acc_today, per_acc_week = {k: 0.0 for k in accounts}, {k: 0.0 for k in accounts}
    for t in history:
        acc = t.get("account")
        try: pnl = float(t.get("pnl", 0))
        except Exception: pnl = 0.0
        ts = str(t.get("closed_at", t.get("close_time", "")))[:10]
        if acc in per_acc_today:
            if ts == today_str: per_acc_today[acc] += pnl
            if ts >= week_start: per_acc_week[acc] += pnl
    accounts_view = {}
    for key, acc in (accounts or {}).items():
        if not isinstance(acc, dict): continue
        ny_active = False
        if key == "ny_session" and is_ny_session:
            try: ny_active = is_ny_session()
            except Exception: pass
        accounts_view[key] = {"name": key.replace("_", " ").title(), "balance": float(acc.get("balance", 0)), "daily_trades": int(acc.get("daily_trades", 0)), "daily_limit": int(ACCOUNT_LIMITS.get(key, 0)), "today_pnl": round(per_acc_today.get(key, 0.0), 2), "week_pnl": round(per_acc_week.get(key, 0.0), 2), "is_active": ny_active}
    
    symbols = list({t.get("symbol") for t in active_trades if t.get("symbol")})
    live = _batch_live_prices(symbols) if symbols else {}
    live_trades_view = []
    for t in active_trades:
        sym = t.get("symbol")
        entry, sl, tp, qty = float(t.get("entry", 0)), float(t.get("sl", 0)), float(t.get("tp", 0)), float(t.get("qty", 0))
        direction = str(t.get("type", t.get("direction", "LONG"))).upper()
        is_long = "BULL" in direction or "LONG" in direction
        cur = live.get(sym, entry)
        pnl = (cur - entry) * qty * (1 if is_long else -1)
        if is_long and tp != entry: progress = max(0.0, min(100.0, (cur - entry) / (tp - entry) * 100.0))
        elif (not is_long) and entry != tp: progress = max(0.0, min(100.0, (entry - cur) / (entry - tp) * 100.0))
        else: progress = 0.0
        
        live_trades_view.append({
            "id": t.get("id", ""),
            "symbol": sym, "market": t.get("market", t.get("mtype", "—")),
            "account": t.get("account", ""), "direction": "LONG" if is_long else "SHORT",
            "entry": entry, "current": cur, "sl": sl, "tp": tp,
            "qty": qty, "pnl_inr": round(pnl, 2), "progress": round(progress, 1),
            "opened": t.get("opened_at", t.get("opened", "")),
        })

    today_signals, cutoff = [], time.time() * 1000 - 24 * 3600 * 1000
    for key, sig in (sent or {}).items():
        ts_ms, sym, sig_type, strat, status, pnl, hint, time_str = 0, "", "", "", "open", 0, "", ""
        if isinstance(sig, dict): 
            ts_ms = sig.get("ts_ms", 0)
            sym = sig.get("symbol", "")
            sig_type = sig.get("sig_type", "")
            strat = sig.get("strat", "")
            status = sig.get("status", "open")
            pnl = sig.get("pnl", 0)
            hint = sig.get("hint", "")
            if ts_ms:
                try:
                    dt = datetime.fromtimestamp(ts_ms / 1000, tz=IST_tz)
                    time_str = dt.strftime("%d-%b %H:%M")
                except:
                    time_str = sig.get("time_str", "")
            else:
                time_str = sig.get("time_str", "")
        else:
            parts = str(key).split("_")
            if len(parts) >= 3: 
                sym, ts_ms, sig_type, strat = parts[0], int(parts[1]) if parts[1].isdigit() else 0, parts[2], parts[3] if len(parts) > 3 else ""
                if ts_ms:
                    try:
                        dt = datetime.fromtimestamp(ts_ms / 1000, tz=IST_tz)
                        time_str = dt.strftime("%d-%b %H:%M")
                    except:
                        time_str = ""
        
        if ts_ms < cutoff: continue
        
        age_ms = time.time() * 1000 - ts_ms
        age_hr = age_ms / 3600000
        if age_hr < 1:
            tag = "🔥 FRESH"
        elif age_hr > 4:
            tag = "⚠️ STALE"
        else:
            tag = ""
            
        today_signals.append({
            "time": time_str, 
            "sym": sym, 
            "dir": "LONG" if "BULL" in str(sig_type).upper() else "SHORT", 
            "strategy": strat, 
            "status": status, 
            "pnl": pnl, 
            "hint": hint,
            "tag": tag,
            "ts_ms": ts_ms
        })
    today_signals.sort(key=lambda x: x.get("ts_ms", 0), reverse=True)

    last_history = sorted(history, key=lambda x: str(x.get("closed_at", "")), reverse=True)[:15]
    pending_view = []  # FVG wait removed — sweeps execute immediately, nothing stays pending

    news = []
    if get_cached_news:
        try:
            raw_news = get_cached_news()
            if raw_news:
                news = [dict(ev, impact=str(ev.get("impact", "")).upper()) for ev in raw_news[:120]]
                print(f"[DASHBOARD] Loaded {len(news)} news items")
            else:
                print("[DASHBOARD] No news available from cache")
        except Exception as e:
            print(f"[DASHBOARD] Failed to load news: {e}")

    strategy_stats = {}
    for t in history:
        strat = t.get("strat", "Unknown")
        if strat not in strategy_stats: strategy_stats[strat] = {"wins": 0, "losses": 0, "pnl": 0.0, "trades": 0}
        strategy_stats[strat]["trades"] += 1
        if t.get("result") == "WIN": strategy_stats[strat]["wins"] += 1
        elif t.get("result") == "LOSS": strategy_stats[strat]["losses"] += 1
        try: strategy_stats[strat]["pnl"] += float(t.get("pnl", 0))
        except: pass
    for data in strategy_stats.values():
        total = data["wins"] + data["losses"]
        data["win_rate"] = round((data["wins"] / total * 100), 1) if total > 0 else 0
        data["avg_pnl"] = round((data["pnl"] / total), 2) if total > 0 else 0

    return {"generated_at": now.strftime("%Y-%m-%d %H:%M:%S IST"), "accounts": accounts_view, "live_trades": live_trades_view, "today_signals": today_signals, "history": last_history, "history_total": len(history), "pending": pending_view, "news_raw": news, "equity_curve": _build_equity_curve(history), "risk": _build_risk(live_trades_view, _build_equity_curve(history)), "strategy_stats": strategy_stats}

def _get_snapshot_cached():
    now = time.time()
    with _snapshot_lock:
        if _snapshot_cache["data"] is not None and (now - _snapshot_cache["ts"]) < SNAPSHOT_TTL: return {"cached": True, "cache_age_s": int(now - _snapshot_cache["ts"]), **_snapshot_cache["data"]}
    snap = _build_snapshot(); _snapshot_cache["data"], _snapshot_cache["ts"] = snap, now
    return {"cached": False, **snap}

def _json_response(start_response, payload, status="200 OK"):
    body = json.dumps(payload, default=str).encode("utf-8")
    start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
    return [body]

def _html_response(start_response, body, status="200 OK"):
    if isinstance(body, str): body = body.encode("utf-8")
    start_response(status, [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
    return [body]

def _route_dashboard(start_response):
    try: return _json_response(start_response, _get_snapshot_cached())
    except Exception as e: return _json_response(start_response, {"error": str(e)}, status="500 Internal Server Error")

def _route_close_trade(start_response, environ):
    try:
        content_length = int(environ.get('CONTENT_LENGTH', 0))
        if content_length > 0:
            data = json.loads(environ['wsgi.input'].read(content_length).decode('utf-8'))
            trade_id = data.get("trade_id", "")
        else: trade_id = ""
        if not trade_id: return _json_response(start_response, {"success": False, "error": "trade_id required"}, status="400 Bad Request")
        main = _get_main_module()
        if not main: return _json_response(start_response, {"success": False, "error": "main module not loaded"}, status="500 Internal Server Error")
        success, message = getattr(main, "force_close_trade", lambda *a, **k: (False, "Not found"))(trade_id, reason="Dashboard")
        return _json_response(start_response, {"success": success, "message": message})
    except Exception as e: return _json_response(start_response, {"success": False, "error": str(e)}, status="500 Internal Server Error")

def _route_backtest(start_response, environ):
    try:
        q = parse_qs(environ.get("QUERY_STRING", ""))
        symbol = (q.get("symbol", [""])[0] or "").strip().upper()
        strategy = (q.get("strategy", ["trendpulse"])[0] or "trendpulse").lower()
        try: days = int(q.get("days", ["30"])[0] or 30)
        except Exception: days = 30
        days = max(7, min(days, 730))
        if not symbol: return _json_response(start_response, {"error": "symbol required"}, status="400 Bad Request")
        try:
            from backtest import BacktestEngine
        except Exception as e:
            return _json_response(start_response, {"error": f"backtest module unavailable: {e}"}, status="500 Internal Server Error")
        eng = BacktestEngine()
        if strategy == "sweep": res = eng.backtest_sweep(symbol, days)
        else: res = eng.backtest_trendpulse(symbol, days)
        if not isinstance(res, dict): res = {"error": "backtest failed"}
        if "error" not in res:
            res = {"metrics": res, "symbol": symbol, "strategy": strategy, "days": days}
        else:
            res["symbol"], res["strategy"], res["days"] = symbol, strategy, days
        return _json_response(start_response, res)
    except Exception as e:
        return _json_response(start_response, {"error": str(e)}, status="500 Internal Server Error")

def _route_refresh_news(start_response, environ):
    try:
        for cache_file in ("/tmp/workspace/news_cache.json", "/tmp/workspace/news_upcoming_cache.json"):
            try:
                if os.path.exists(cache_file): os.remove(cache_file)
            except Exception as e:
                print(f"[NEWS] Could not remove {cache_file}: {e}")
        main = _get_main_module()
        if main is not None and hasattr(main, "news_cache"):
            try: main.news_cache = None
            except Exception: pass
        items = []
        if main is not None and hasattr(main, "fetch_news"):
            try: items = main.fetch_news() or []
            except Exception as e: print(f"[NEWS] Force-refresh fetch failed: {e}")
        try:
            now_ms = int(time.time() * 1000)
            IST_tz = getattr(main, "IST", None)
            norm = []
            for ev in (items or []):
                d = ev.get("date", "")
                if not d: continue
                ts_ms = 0
                try:
                    if IST_tz is not None:
                        from datetime import datetime
                        dt = datetime.fromisoformat(str(d).split(".")[0])
                        if dt.tzinfo is None and IST_tz is not None: dt = IST_tz.localize(dt)
                        ts_ms = int(dt.timestamp() * 1000)
                except Exception: pass
                if ts_ms and ts_ms + 30 * 60 * 1000 < now_ms: continue
                ev2 = dict(ev)
                ev2["impact"] = (ev.get("impact") or "Low")
                norm.append(ev2)
            norm.sort(key=lambda x: x.get("date", ""))
            with open("/tmp/workspace/news_upcoming_cache.json", "w") as f:
                json.dump({"ts": int(time.time()), "items": norm}, f)
            items = norm
        except Exception as e:
            print(f"[NEWS] Could not persist upcoming cache: {e}")
        return _json_response(start_response, {"ok": True, "items": len(items)})
    except Exception as e:
        return _json_response(start_response, {"ok": False, "error": str(e)}, status="500 Internal Server Error")

def register_routes(path, start_response, environ):
    method = environ.get("REQUEST_METHOD", "GET")
    if path in ("/dashboard", "/dashboard/"): return _html_response(start_response, _get_html_content())
    if path == "/api/dashboard": return _route_dashboard(start_response)
    if path.startswith("/api/backtest"): return _route_backtest(start_response, environ)
    if path.startswith("/api/prices"): return _json_response(start_response, {"prices": _batch_live_prices(parse_qs(environ.get("QUERY_STRING", "")).get("symbols", [""])[0].split(",")), "ts": int(time.time())})
    if path == "/api/health": return _json_response(start_response, {"ok": True, "ts": int(time.time())})
    if path == "/api/close-trade" and method == "POST": return _route_close_trade(start_response, environ)
    if path == "/api/refresh-news" and method == "POST": return _route_refresh_news(start_response, environ)
    return None
