import os
import sys
import json
import time
import threading
from datetime import datetime
from urllib.parse import parse_qs

import pytz

SNAPSHOT_TTL = 10
_snapshot_cache = {"data": None, "ts": 0}
_snapshot_lock = threading.RLock()
_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML_PATH_PRIMARY = os.path.join(_HERE, "templates", "index.html")
_HTML_PATH_FALLBACK = os.path.join(_HERE, "dashboard", "index.html")


def _get_html_content():
    for path in (_HTML_PATH_PRIMARY, _HTML_PATH_FALLBACK):
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            body = f.read()

        # Keep the injected dashboard script ASCII-only and use a normal str
        # literal. A bytes literal cannot contain the em-dash/non-ASCII text
        # that the previous patch introduced, which crashed Render at import.
        override = r'''<script>
(function () {
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>\"']/g, function (c) {
      return {'&':'&amp;', '<':'&lt;', '>':'&gt;', '\"':'&quot;', "'":'&#39;'}[c];
    });
  }
  function direction(value) {
    var v = String(value || '').toUpperCase();
    if (v.indexOf('BUY') >= 0 || v.indexOf('BULL') >= 0 || v === 'LONG') return 'BUY';
    if (v.indexOf('SELL') >= 0 || v.indexOf('BEAR') >= 0 || v === 'SHORT') return 'SELL';
    return 'NEUTRAL';
  }
  function renderSignals(items) {
    var groups = {};
    (items || []).forEach(function (item) {
      var key = item.date || String(item.time || '').slice(0, 10) || 'OTHER';
      (groups[key] || (groups[key] = [])).push(item);
    });
    var keys = Object.keys(groups).sort().reverse();
    var html = keys.map(function (key) {
      var rows = groups[key].sort(function (a, b) {
        return Number(b.ts_ms || 0) - Number(a.ts_ms || 0);
      }).map(function (item) {
        var dir = direction(item.dir || item.direction);
        var cls = dir === 'BUY' ? 'p3-buy' : dir === 'SELL' ? 'p3-sell' : 'p3-neutral';
        return '<div class="p3-signal"><div class="p3-main">' +
          '<div><div class="p3-symbol">' + esc(item.sym || item.symbol || '-') + '</div>' +
          '<div class="p3-sub">' + esc(item.strategy || 'Sweep') + ' &middot; ' + esc(item.time || '') + '</div></div>' +
          '<div class="p3-side"><span class="p3-dir ' + cls + '">' + dir + '</span>' +
          '<span class="p3-pnl">' + esc(item.status || 'SIGNAL') + '</span></div>' +
          '</div></div>';
      }).join('');
      return '<div class="p3-date">' + esc(key === 'OTHER' ? 'OTHER' : key) + '</div>' + rows;
    }).join('');
    return html || '<div class="empty">No saved signals.</div>';
  }
  function loadSignals() {
    fetch('/api/dashboard', {cache: 'no-store'})
      .then(function (response) { return response.json(); })
      .then(function (data) {
        var list = document.getElementById('signalsList');
        var latest = document.getElementById('latest');
        var signals = data.signals || data.today_signals || [];
        if (list) list.innerHTML = renderSignals(signals);
        if (latest) {
          latest.innerHTML = signals.slice(0, 3).map(function (item) {
            var dir = direction(item.dir || item.direction);
            var cls = dir === 'BUY' ? 'p3-buy' : dir === 'SELL' ? 'p3-sell' : 'p3-neutral';
            return '<div class="p3-signal"><div class="p3-main"><div>' +
              '<div class="p3-symbol">' + esc(item.sym || item.symbol || '-') + '</div>' +
              '<div class="p3-sub">' + esc(item.strategy || 'Sweep') + ' &middot; ' + esc(item.time || '') + '</div>' +
              '</div><span class="p3-dir ' + cls + '">' + dir + '</span></div></div>';
          }).join('') || '<div class="empty">No signals yet.</div>';
        }
        var label = document.querySelector('#signals .muted');
        if (label) label.textContent = 'All saved signals';
      })
      .catch(function (error) { console.error('signal archive render', error); });
  }
  loadSignals();
  setInterval(loadSignals, 30000);
})();
</script>'''
        marker = b"</body>"
        if marker in body:
            body = body.replace(marker, override.encode("utf-8") + marker, 1)
        return body
    return b"<h1>Dashboard template index.html not found.</h1>"


def _get_main_module():
    return sys.modules.get("__main__") or sys.modules.get("main")


def _load_file(main, path, default):
    try:
        fn = getattr(main, "load_json", None)
        if fn:
            return fn(path, default) or default
    except Exception as exc:
        print("[DASHBOARD] load:", exc)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        print("[DASHBOARD] file load:", exc)
    return default


def _parse_ts(value, default=0):
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        v = float(value)
        return int(v if v > 10_000_000_000 else v * 1000)
    try:
        v = float(str(value).strip())
        return int(v if v > 10_000_000_000 else v * 1000)
    except Exception:
        pass
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return default


def _direction(value):
    value = str(value or "").upper()
    if "BULL" in value or value in ("BUY", "LONG"):
        return "BUY"
    if "BEAR" in value or value in ("SELL", "SHORT"):
        return "SELL"
    return "NEUTRAL"


def _batch_live_prices(symbols):
    if not symbols:
        return {}
    main = _get_main_module()
    out = {}
    if not main:
        return out
    cache = getattr(main, "_price_cache", {})
    lock = getattr(main, "_lock", None)
    get_price = getattr(main, "get_price", None)
    now = time.time()
    if lock:
        with lock:
            for symbol, value in cache.items():
                if symbol in symbols and isinstance(value, (list, tuple)) and len(value) >= 2 and now - value[1] < 120:
                    out[symbol] = value[0]
    need = [symbol for symbol in symbols if symbol not in out]
    if need:
        try:
            import yfinance as yf
            df = yf.download(
                tickers=','.join(need), period="1d", interval="1d",
                progress=False, threads=True, timeout=15
            )
            if df is not None and not df.empty:
                close = df["Close"]
                if len(need) == 1:
                    values = close.dropna()
                    if not values.empty:
                        out[need[0]] = float(values.iloc[-1])
                else:
                    for symbol in need:
                        try:
                            values = close[symbol].dropna()
                            if not values.empty:
                                out[symbol] = float(values.iloc[-1])
                        except Exception:
                            pass
        except Exception as exc:
            print("[DASHBOARD] price fetch:", exc)
    if get_price:
        for symbol in symbols:
            if symbol not in out:
                try:
                    value = get_price(symbol)
                    if value is not None:
                        out[symbol] = float(value)
                except Exception:
                    pass
    return out


def _build_equity_curve(history, starting=400000.0, days=60):
    daily = {}
    for trade in history:
        date = str(trade.get("closed_at", trade.get("close_time", trade.get("time", ""))))[:10]
        if not date:
            continue
        try:
            daily[date] = daily.get(date, 0) + float(trade.get("pnl", 0) or 0)
        except Exception:
            pass
    running = peak = starting
    ddmax = ddpct = 0
    points = []
    for date in sorted(daily):
        running += daily[date]
        peak = max(peak, running)
        drawdown = peak - running
        if drawdown > ddmax:
            ddmax = drawdown
            ddpct = drawdown / peak * 100 if peak else 0
        points.append({"date": date, "equity": round(running, 2)})
    points = points[-days:]
    return {
        "points": points,
        "current_equity": points[-1]["equity"] if points else starting,
        "max_drawdown_inr": round(ddmax, 2),
        "max_drawdown_pct": round(ddpct, 2),
    }


def _build_actual_signals(main, ist):
    """Permanent dashboard signal archive. Telegram reminder expiry is separate."""
    rows = _load_file(main, "/tmp/workspace/signal_history.json", [])
    if not isinstance(rows, list):
        rows = []

    # Compatibility fallback for signals already present in runtime state.
    if not rows:
        state = _load_file(main, "/tmp/workspace/sweep_runtime_state.json", {})
        if isinstance(state, dict):
            for key, record in state.items():
                if isinstance(record, dict) and record.get("initial"):
                    rows.append({
                        "id": key,
                        "symbol": str(key).split(":", 1)[0],
                        "direction": record.get("direction"),
                        "strategy": f"{record.get('timeframe', '4H')} Sweep",
                        "timeframe": record.get("timeframe", "4H"),
                        "candle_start": record.get("candle_start"),
                        "candle_end": record.get("candle_end"),
                        "reminder_sent": bool(record.get("reminder")),
                    })

    signals = []
    for record in rows:
        if not isinstance(record, dict):
            continue
        ts = _parse_ts(record.get("candle_end"), 0)
        symbol = str(record.get("symbol") or "").strip()
        if not symbol or not ts:
            continue
        try:
            dt = datetime.fromtimestamp(ts / 1000, tz=ist)
        except Exception:
            continue
        signals.append({
            "id": record.get("id", f"{symbol}:{ts}"),
            "time": dt.strftime("%d-%b %H:%M"),
            "sym": symbol,
            "dir": _direction(record.get("direction")),
            "strategy": record.get("strategy") or f"{record.get('timeframe', '4H')} Sweep",
            "status": "REMINDER SENT" if record.get("reminder_sent") else "SIGNAL",
            "pnl": 0,
            "hint": "Confirmed sweep signal",
            "ts_ms": ts,
            "reminder": bool(record.get("reminder_sent")),
            "date": dt.strftime("%Y-%m-%d"),
        })
    signals.sort(key=lambda item: item["ts_ms"], reverse=True)
    return signals


def _build_snapshot():
    main = _get_main_module()
    if not main:
        return {"error": "main module not loaded"}
    load_json = getattr(main, "load_json", None)
    lock = getattr(main, "_lock", None)
    if not load_json or not lock:
        return {"error": "missing bot globals"}

    ist = getattr(main, "IST", pytz.timezone("Asia/Kolkata"))
    now = datetime.now(ist)
    today = now.strftime("%Y-%m-%d")
    history = load_json(getattr(main, "HISTORY_FILE", "trade_history.json"), []) or []
    accounts = getattr(main, "accounts", {}) or {}
    active = getattr(main, "active_trades", []) or []
    limits = getattr(main, "ACCOUNT_LIMITS", {}) or {}

    per_today = {key: 0.0 for key in accounts}
    for trade in history:
        if str(trade.get("closed_at", trade.get("close_time", "")))[:10] == today:
            try:
                account = trade.get("account")
                per_today[account] = per_today.get(account, 0) + float(trade.get("pnl", 0) or 0)
            except Exception:
                pass

    accounts_view = {}
    for key, account in accounts.items():
        if isinstance(account, dict):
            accounts_view[key] = {
                "name": key.replace("_", " ").title(),
                "balance": float(account.get("balance", 0) or 0),
                "daily_trades": int(account.get("daily_trades", 0) or 0),
                "daily_limit": int(limits.get(key, 0) or 0),
                "today_pnl": round(per_today.get(key, 0), 2),
            }

    symbols = [trade.get("symbol") for trade in active if trade.get("symbol")]
    prices = _batch_live_prices(symbols)
    live = []
    for trade in active:
        symbol = trade.get("symbol")
        entry = float(trade.get("entry", 0) or 0)
        qty = float(trade.get("qty", 0) or 0)
        sl = float(trade.get("sl", trade.get("trail_sl", 0)) or 0)
        tp = float(trade.get("tp", 0) or 0)
        typ = str(trade.get("type", trade.get("direction", "LONG"))).upper()
        long = "LONG" in typ or "BULL" in typ or typ == "BUY"
        current = float(prices.get(symbol, entry) or entry)
        pnl = (current - entry) * qty * (1 if long else -1)
        live.append({
            "id": trade.get("id", ""),
            "symbol": symbol,
            "market": trade.get("market", trade.get("mtype", "")),
            "account": trade.get("account", ""),
            "direction": "LONG" if long else "SHORT",
            "entry": entry,
            "current": current,
            "sl": sl,
            "tp": tp,
            "qty": qty,
            "pnl_inr": round(pnl, 2),
            "opened": trade.get("opened_at", trade.get("opened", "")),
        })

    signals = _build_actual_signals(main, ist)

    news = []
    cached = getattr(main, "get_cached_news", None)
    fetch = getattr(main, "fetch_news", None)
    try:
        if cached:
            news = cached() or []
    except Exception as exc:
        print("[DASHBOARD] cached news:", exc)
    if not news and fetch:
        try:
            news = fetch() or []
        except Exception as exc:
            print("[DASHBOARD] fetch news:", exc)

    normalized_news = []
    for event in news[:120]:
        if isinstance(event, dict):
            item = dict(event)
            item["impact"] = str(item.get("impact") or item.get("importance") or "LOW").upper()
            normalized_news.append(item)

    history_sorted = sorted(
        history,
        key=lambda item: str(item.get("closed_at", item.get("close_time", ""))),
        reverse=True,
    )[:30]
    curve = _build_equity_curve(history)
    total = sum(float(item.get("pnl", 0) or 0) for item in history)

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "accounts": accounts_view,
        "live_trades": live,
        "today_signals": signals,
        "signals": signals,
        "history": history_sorted,
        "history_total": len(history),
        "pending": [],
        "news_raw": normalized_news,
        "news": normalized_news,
        "equity_curve": curve,
        "risk": {
            "max_drawdown_inr": curve["max_drawdown_inr"],
            "max_drawdown_pct": curve["max_drawdown_pct"],
        },
        "total_pnl": round(total, 2),
    }


def _get_snapshot_cached():
    now = time.time()
    with _snapshot_lock:
        if _snapshot_cache["data"] is not None and now - _snapshot_cache["ts"] < SNAPSHOT_TTL:
            return {
                "cached": True,
                "cache_age_s": int(now - _snapshot_cache["ts"]),
                **_snapshot_cache["data"],
            }
    snapshot = _build_snapshot()
    with _snapshot_lock:
        _snapshot_cache["data"], _snapshot_cache["ts"] = snapshot, now
    return {"cached": False, **snapshot}


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


def _route_backtest(start_response, environ):
    try:
        query = parse_qs(environ.get("QUERY_STRING", ""))
        symbol = (query.get("symbol", [""])[0] or "").strip().upper()
        strategy = (query.get("strategy", ["trendpulse"])[0] or "trendpulse").lower()
        days = max(7, min(int(query.get("days", ["30"])[0] or 30), 730))
        if not symbol:
            return _json_response(start_response, {"error": "symbol required"}, "400 Bad Request")
        from backtest import BacktestEngine
        engine = BacktestEngine()
        result = engine.backtest_sweep(symbol, days) if strategy == "sweep" else engine.backtest_trendpulse(symbol, days)
        if not isinstance(result, dict):
            result = {"error": "backtest failed"}
        if "error" not in result:
            result = {"metrics": result, "symbol": symbol, "strategy": strategy, "days": days}
        else:
            result.update({"symbol": symbol, "strategy": strategy, "days": days})
        return _json_response(start_response, result)
    except Exception as exc:
        return _json_response(start_response, {"error": str(exc)}, "500 Internal Server Error")


def _route_close_trade(start_response, environ):
    try:
        length = int(environ.get("CONTENT_LENGTH", 0) or 0)
        data = json.loads(environ["wsgi.input"].read(length).decode()) if length else {}
        trade_id = data.get("trade_id", "")
        main = _get_main_module()
        if not trade_id:
            return _json_response(start_response, {"success": False, "error": "trade_id required"}, "400 Bad Request")
        fn = getattr(main, "force_close_trade", None) if main else None
        ok, message = fn(trade_id, reason="Dashboard") if fn else (False, "Not found")
        return _json_response(start_response, {"success": ok, "message": message})
    except Exception as exc:
        return _json_response(start_response, {"success": False, "error": str(exc)}, "500 Internal Server Error")


def _route_refresh_news(start_response, environ):
    main = _get_main_module()
    try:
        items = main.fetch_news() if main and hasattr(main, "fetch_news") else []
        return _json_response(start_response, {"ok": True, "items": len(items or [])})
    except Exception as exc:
        return _json_response(start_response, {"ok": False, "error": str(exc)}, "500 Internal Server Error")


def register_routes(path, start_response, environ):
    method = environ.get("REQUEST_METHOD", "GET")
    if path in ("/dashboard", "/dashboard/"):
        return _html_response(start_response, _get_html_content())
    if path == "/api/dashboard":
        try:
            return _json_response(start_response, _get_snapshot_cached())
        except Exception as exc:
            return _json_response(start_response, {"error": str(exc)}, "500 Internal Server Error")
    if path.startswith("/api/backtest"):
        return _route_backtest(start_response, environ)
    if path.startswith("/api/prices"):
        symbols = parse_qs(environ.get("QUERY_STRING", "")).get("symbols", [""])[0].split(",")
        return _json_response(start_response, {"prices": _batch_live_prices([s for s in symbols if s]), "ts": int(time.time())})
    if path == "/api/health":
        return _json_response(start_response, {"ok": True, "ts": int(time.time())})
    if path == "/api/close-trade" and method == "POST":
        return _route_close_trade(start_response, environ)
    if path == "/api/refresh-news" and method == "POST":
        return _route_refresh_news(start_response, environ)
    return None
