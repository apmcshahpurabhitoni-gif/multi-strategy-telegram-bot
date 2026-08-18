import os
import json
import time
import threading
import gc
from datetime import datetime, timedelta
from io import BytesIO
import io
from wsgiref.simple_server import make_server, WSGIServer
from socketserver import ThreadingMixIn

import requests
import dashboard_api
import numpy as np
import pandas as pd
import yfinance as yf
import pytz
import telebot
import matplotlib
import matplotlib.pyplot as plt
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.makedirs("/tmp/workspace", exist_ok=True)
matplotlib.use("Agg")
plt.style.use("dark_background")

# Backtest engine
try:
    from backtest import BacktestEngine
    _backtest_available = True
except Exception as _bt_err:
    print(f"[WARN] Backtest engine not available: {_bt_err}")
    _backtest_available = False

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

NIFTY_STOCKS = [
    ("RELIANCE.NS", "Reliance"), ("HDFCBANK.NS", "HDFC Bank"),
    ("ICICIBANK.NS", "ICICI Bank"), ("INFY.NS", "Infosys"), ("TCS.NS", "TCS"),
    ("ITC.NS", "ITC"), ("SBIN.NS", "SBI"), ("BHARTIARTL.NS","Bharti Airtel"),
    ("LT.NS", "L&T"), ("HINDUNILVR.NS","HUL"), ("AXISBANK.NS", "Axis Bank"),
    ("KOTAKBANK.NS", "Kotak Bank"), ("BAJFINANCE.NS","Bajaj Finance"),
    ("MARUTI.NS", "Maruti"), ("SUNPHARMA.NS", "Sun Pharma"),
]

if not TOKEN: raise ValueError("TELEGRAM_BOT_TOKEN not set!")
if not CHAT_ID: raise ValueError("TELEGRAM_CHAT_ID not set!")

ACCOUNTS_FILE = "/tmp/workspace/accounts.json"
RESET_STATE_FILE = "/tmp/workspace/reset_state.json"
ACTIVE_TRADES_FILE = "/tmp/workspace/active_trades.json"
HISTORY_FILE = "/tmp/workspace/trade_history.json"
MUTE_FILE = "/tmp/workspace/muted_assets.json"
SENT_SIGNALS_FILE = "/tmp/workspace/sent_signals.json"
PENDING_SWEEPS_FILE = "/tmp/workspace/pending_sweeps.json"
WEEKLY_DIGEST_FILE = "/tmp/workspace/weekly_digest_state.json"

ACCOUNT_LIMITS = {"macro": 20, "nifty": 5, "ny_session": 3, "sweep_4h": 3}

accounts = {}
active_trades = []
muted_assets = set()
sent_signals = {}
history = []
pending_sweeps = []
_lock = threading.RLock()

_news_pause_enabled = True
_chart_lock = threading.RLock()
_price_cache = {}
IST = pytz.timezone("Asia/Kolkata")
_sweep_cooldown = {}
_ut_15m_cache = {}
NEWS_CACHE = {"data": [], "last_fetch": 0}

_yf_symbol_cache = {} 
_YF_SYMBOL_TTL = 30.0

_yf_session = requests.Session()
_yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

BR = "━━━━━━━━━━━━━━━━━━━━━━"
BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

def get_signal_age_str(ts_ms):
    if not ts_ms: return "Unknown"
    now_ms = int(time.time() * 1000)
    diff_ms = now_ms - ts_ms
    diff_min = int(diff_ms / 60000)
    diff_hr = int(diff_min / 60)
    if diff_min < 60:
        age_str = f"{diff_min} min ago"
        tag = "✅ FRESH" if diff_min <= 60 else "⚠️ STALE"
    else:
        age_str = f"{diff_hr} hr {diff_min % 60} min ago"
        tag = "✅ FRESH" if diff_hr < 4 else "⚠️ STALE"
    return f"{age_str} {tag}"

def msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, actual_sl, actual_tp, qty, risk_amt, account, signal_ts_ms, fvg_zone=None):
    is_bullish = "BULLISH" in sig_type
    dot = "🟢" if is_bullish else "🔴"
    dir_label = "LONG 📈" if is_bullish else "SHORT 📉"
    header = f"{dot} *FVG Fill · {symbol}*" if "Sweep" in strat and fvg_zone else (f"{dot} *{strat} · {symbol}*" if "Sweep" not in strat else f"{dot} *4H Sweep · {symbol}*")
    curr = _currency(symbol)
    fvg_line = f"🎯 *FVG Zone:* `{curr}{fvg_zone[0]:,.4f} — {curr}{fvg_zone[1]:,.4f}`\n" if fvg_zone and "Sweep" in strat else ""
    
    dt = datetime.fromtimestamp(signal_ts_ms / 1000, tz=IST)
    time_str = dt.strftime("%d-%b-%Y %H:%M IST")
    age_str = get_signal_age_str(signal_ts_ms)
    
    return (
        f"{header}\n{BR}\n"
        f"🪙 *Asset:* `{symbol}`\n🌐 *Market:* {mtype}\n📊 *Direction:* {dir_label}\n⏱ *Timeframe:* {tf}\n{BR}\n"
        f"⏰ *Signal Candle Closed At:*\n🔔 `{time_str}`\n"
        f"⏳ *Signal Age:* `{age_str}`\n{BR}\n"
        f"💼 *PAPER TRADE EXECUTED*\n{BR}\n"
        f"🏢 *Account:* `{account.upper()}`\n📍 *Entry:* `{curr}{price:,.4f}`\n🛑 *Stop Loss:* `{curr}{actual_sl:,.4f}`\n🎯 *Take Profit:* `{curr}{actual_tp:,.4f}`\n"
        f"{fvg_line}📦 *Quantity:* `{qty:.4f}`\n💸 *Risk:* `₹{risk_amt:,.2f}`\n{BR2}"
    )

def msg_trade_closed(trade, live, pnl, bal, is_long, hit_tp):
    result = "🎉 WIN" if hit_tp else "💀 LOSS"
    dot = "🟢" if is_long else "🔴"
    money = "💰" if hit_tp else "💸"
    pnl_s = f"+₹{pnl:,.2f}" if hit_tp else f"-₹{abs(pnl):,.2f}"
    curr = _currency(trade['symbol'])
    return f"{dot} *TRADE CLOSED — {result}*\n{BR}\n`{trade['symbol']}` | {'LONG' if is_long else 'SHORT'}\n🎯 *Strategy:* {trade['strat']}\n🏢 *Account:* `{trade['account'].upper()}`\n{BR}\n📍 *Entry:* `{curr}{trade['entry']:,.4f}`\n{'📈' if hit_tp else '📉'} *Exit:* `{curr}{live:,.4f}`\n🛑 *SL Hit:* `{curr}{trade['trail_sl']:,.4f}`\n🎯 *TP Target:* `{curr}{trade['tp']:,.4f}`\n{BR}\n{money} *P/L:* `{pnl_s}`\n🏦 *Balance:* `₹{bal:,.2f}`\n{BR2}"

def msg_midnight_reset(day_pnl, macro_bal, nifty_bal, ny_bal, sweep_bal):
    pnl_icon = "📈" if day_pnl >= 0 else "📉"
    pnl_sign = "+" if day_pnl >= 0 else ""
    return f"🌙 *MIDNIGHT RESET*\n{BR}\n{pnl_icon} *Yesterday P/L:* `{pnl_sign}₹{day_pnl:,.2f}`\n{BR}\n🏦 *Account Balances:*\n├ 🌐 *Macro:* `₹{macro_bal:,.2f}`\n├ 🇮🇳 *Nifty:* `₹{nifty_bal:,.2f}`\n├ 🇺🇸 *NY Session:* `₹{ny_bal:,.2f}`\n└ 🔵 *Sweep 4H:* `₹{sweep_bal:,.2f}`\n{BR}\n🔄 *Daily trade limits reset*\n🧹 *Signal cache cleaned*\n{BR2}"

def msg_weekly_digest(week_pnl, wins, losses, best_sym, best_pnl, worst_sym, worst_pnl, total_equity):
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100.0) if total_trades else 0.0
    pnl_icon = "📈" if week_pnl >= 0 else "📉"
    pnl_sign = "+" if week_pnl >= 0 else ""
    best_str = f"`{best_sym}` (`{'+' if best_pnl >= 0 else ''}₹{best_pnl:,.2f}`)" if best_sym else "—"
    worst_str = f"`{worst_sym}` (`{'+' if worst_pnl >= 0 else ''}₹{worst_pnl:,.2f}`)" if worst_sym else "—"
    return f"🗓️ *WEEKLY DIGEST*\n{BR}\n{pnl_icon} *Week P/L:* `{pnl_sign}₹{week_pnl:,.2f}`\n📊 *Trades:* `{total_trades}` · ✅ `{wins}W` · ❌ `{losses}L` · 🎯 `{win_rate:.1f}%`\n{BR}\n🏆 *Best Symbol:* {best_str}\n💔 *Worst Symbol:* {worst_str}\n{BR}\n🏦 *Total Equity:* `₹{total_equity:,.2f}`\n{BR2}"

def msg_guide():
    return f"🤖 *TRADING BOT — COMMAND CENTER*\n{BR}\n📘 *COMMANDS:*\n├ `/start` — Show this guide\n├ `/backtest` — Backtest a strategy\n├ `/newspause` — Toggle news auto-pause\n├ `/pending` — Show sweep setups waiting for FVG\n└ `/stats` — Win rate & P/L report\n{BR2}"

def msg_error(context, error):
    return f"⚠️ *ERROR — {context}*\n{BR}\n❌ `{error}`\n{BR2}"

_error_alert_lock = threading.Lock()
_error_alert_last_sent = {}
ERROR_ALERT_COOLDOWN_S = 900

def alert_error(context, error, cooldown_s=ERROR_ALERT_COOLDOWN_S):
    print(f"[ERR] {context}: {error}")
    now = time.time()
    with _error_alert_lock:
        last = _error_alert_last_sent.get(context, 0)
        if now - last < cooldown_s: return
        _error_alert_last_sent[context] = now
    try: safe_send(CHAT_ID, msg_error(context, error), parse_mode="Markdown")
    except Exception: pass

class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True

def run_web():
    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")
        _resp = dashboard_api.register_routes(path, start_response, environ)
        if _resp is not None: return _resp
        if path == "/ping":
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"pong"]
        if path == "/webhook" and method == "POST":
            try:
                content_length = int(environ.get('CONTENT_LENGTH', 0))
                body = environ['wsgi.input'].read(content_length)
                update = telebot.types.Update.de_json(body.decode('utf-8'))
                bot.process_new_updates([update])
                start_response("200 OK", [("Content-Type", "text/plain")])
                return [b"OK"]
            except Exception as e:
                print(f"[ERR] Webhook processing: {e}")
                start_response("500 Internal Server Error", [("Content-Type", "text/plain")])
                return [b"Error"]
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"Trading Bot OK"]
    PORT = int(os.environ.get("PORT", 10000))
    srv = make_server("0.0.0.0", PORT, app, server_class=ThreadedWSGIServer)
    srv.serve_forever()

bot = telebot.TeleBot(TOKEN, parse_mode="Markdown", threaded=False)

def _currency(symbol): return "₹" if (symbol.endswith(".NS") or "NSE" in symbol) else "$"

def load_json(fp, default):
    key = os.path.basename(fp)
    sup_url, sup_key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if sup_url and sup_key:
        try:
            r = requests.get(f"{sup_url}/rest/v1/bot_data?id=eq.{key}", headers={"apikey": sup_key, "Authorization": f"Bearer {sup_key}"}, timeout=15)
            if r.status_code == 200 and r.json():
                rows = r.json()
                if rows:
                    try:
                        with open(fp, "w") as f: json.dump(rows[0]["data"], f, indent=4)
                    except: pass
                    return rows[0]["data"]
        except Exception as e: print(f"[ERR] Supabase load {key}: {e}")
    try:
        if os.path.exists(fp): return json.load(open(fp))
    except Exception: pass
    return default

def save_json(fp, data):
    key = os.path.basename(fp)
    try:
        with open(fp + ".tmp", "w") as f: json.dump(data, f, indent=4)
        os.replace(fp + ".tmp", fp)
    except Exception as e: print(f"[ERR] local save {fp}: {e}")
    sup_url, sup_key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if sup_url and sup_key:
        try:
            requests.post(f"{sup_url}/rest/v1/bot_data", headers={"apikey": sup_key, "Authorization": f"Bearer {sup_key}", "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}, json={"id": key, "data": data}, timeout=15)
        except Exception as e: print(f"[ERR] Supabase save {key}: {e}")

def safe_send(chat_id, text, **kwargs):
    try: bot.send_message(chat_id, text, **kwargs)
    except Exception:
        try: bot.send_message(chat_id, text.replace("*","").replace("`","").replace("_",""), parse_mode=None)
        except Exception: pass

def init_accounts():
    global accounts
    defaults = {"macro": {"balance": 100000.0, "daily_trades": 0}, "nifty": {"balance": 100000.0, "daily_trades": 0}, "ny_session": {"balance": 100000.0, "daily_trades": 0}, "sweep_4h": {"balance": 100000.0, "daily_trades": 0}}
    raw_accounts = load_json(ACCOUNTS_FILE, {})
    # FIX: Purge junk non-dict keys (like last_reset_date if it was accidentally stored here)
    accounts = {k: v for k, v in raw_accounts.items() if isinstance(v, dict)}
    for k, v in defaults.items():
        if k not in accounts: accounts[k] = v.copy()
    
    # FIX: Handle reset state in a separate file
    reset_state = load_json(RESET_STATE_FILE, {"last_reset_date": ""})
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if reset_state.get("last_reset_date") != today:
        for acc in accounts: 
            if isinstance(accounts[acc], dict):
                accounts[acc]["daily_trades"] = 0
        reset_state["last_reset_date"] = today
        save_json(RESET_STATE_FILE, reset_state)
        
    save_json(ACCOUNTS_FILE, accounts)

def is_ny_session():
    h, m = datetime.now(IST).hour, datetime.now(IST).minute
    return (h == 20 and m >= 0) or h in (21, 22, 23, 0, 1) or (h == 2 and m <= 30)

def is_nifty_open():
    n = datetime.now(IST)
    return n.weekday() < 5 and 555 <= (n.hour * 60 + n.minute) <= 930

def is_market_open(symbol):
    n = datetime.now(IST)
    w, tm = n.weekday(), n.hour * 60 + n.minute
    if symbol in ("BTC-USD", "GC=F"): return True
    if symbol in ("EURUSD=X", "GBPUSD=X", "USDJPY=X"):
        if w == 5: return False
        if w == 6: return tm >= 150
        if w == 4: return tm <= 1410
        return True
    if symbol in ("^NSEI", "^NSEBANK") or symbol.endswith(".NS"): return w < 5 and 555 <= tm <= 930
    return False

def yf_download(symbol, period, interval):
    now = time.time()
    cache_key = f"{symbol}_{period}_{interval}"
    if cache_key in _yf_symbol_cache:
        cached_df, cached_ts = _yf_symbol_cache[cache_key]
        if now - cached_ts < _YF_SYMBOL_TTL: return cached_df.copy()
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True, threads=False, session=_yf_session)
        if df is None or df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        _yf_symbol_cache[cache_key] = (df, now)
        return df
    except Exception as e: print(f"[ERR] yf_download {symbol} {interval}: {e}"); return None

def get_price(symbol):
    now = time.time()
    if symbol in _price_cache:
        p, ts = _price_cache[symbol]
        if now - ts < 60: return p
    if symbol == "BTC-USD":
        try:
            r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                p = float(r.json()["bitcoin"]["usd"])
                _price_cache[symbol] = (p, now); return p
        except Exception: pass
    if symbol == "GC=F":
        for gold_sym in ["GC=F", "GLD", "IAU"]:
            try:
                df = yf_download(gold_sym, "1d", "1m")
                if df is not None and not df.empty:
                    p = float(df["Close"].iloc[-1]); _price_cache[symbol] = (p, now); return p
            except Exception: continue
    df = yf_download(symbol, "1d", "1m")
    if df is not None and not df.empty:
        p = float(df["Close"].iloc[-1]); _price_cache[symbol] = (p, now); return p
    return None

def calc_atr(df, period=10):
    hl, hc, lc = df["High"] - df["Low"], np.abs(df["High"] - df["Close"].shift(1)), np.abs(df["Low"] - df["Close"].shift(1))
    return pd.concat([hl, hc, lc], axis=1).max(axis=1).ewm(alpha=1/period, adjust=False).mean()

def get_rsi(df, period=14):
    d = df["Close"].diff()
    g, l = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs = g / l.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)

def fetch_binance_klines(symbol="BTCUSDT", interval="1h", limit=200):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}", timeout=15)
        df = pd.DataFrame(r.json(), columns=["Open time", "Open", "High", "Low", "Close", "Volume", "Close time", "Quote asset volume", "Number of trades", "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore"])
        df["Open time"] = pd.to_datetime(df["Open time"], unit="ms"); df.set_index("Open time", inplace=True)
        return df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    except Exception: return None

def check_sweep(ticker):
    try:
        df = yf_download(ticker, "15d", "1h")
        if df is None or len(df) < 20: return None
        df = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna().iloc[:-1]
        if len(df) < 4: return None
        c, m = df.iloc[-2], df.iloc[-3]; ts = int(df.index[-2].timestamp() * 1000)
        if c["Low"] < m["Low"] and c["High"] > m["High"] and c["Close"] > m["High"]: return ("BULLISH", float(c["High"]), float(c["Low"]), ts, ts + 4 * 3600 * 1000)
        if c["High"] > m["High"] and c["Low"] < m["Low"] and c["Close"] < m["Low"]: return ("BEARISH", float(c["High"]), float(c["Low"]), ts, ts + 4 * 3600 * 1000)
    except Exception: pass
    return None

def find_fvg(df_1h, direction, sweep_open_ts_ms):
    try:
        if df_1h is None or len(df_1h) < 3: return None
        sweep_open = pd.to_datetime(int(sweep_open_ts_ms), unit="ms")
        idx = df_1h.index
        if getattr(idx, "tz", None) is not None: sweep_open = sweep_open.tz_localize("UTC") if sweep_open.tz is None else sweep_open.tz_convert(idx.tz)
        df = df_1h[idx >= sweep_open].reset_index(drop=True)
        if len(df) < 3: return None
        for i in range(2, len(df)):
            c_prev2, c_curr = df.iloc[i - 2], df.iloc[i]
            if direction == "BULLISH" and float(c_curr["Low"]) > float(c_prev2["High"]):
                zl, zh = float(c_prev2["High"]), float(c_curr["Low"])
                if zh > zl and not ((df.iloc[i + 1:]["Low"].astype(float) < zl).any()): return (zl, zh)
            elif direction == "BEARISH" and float(c_curr["High"]) < float(c_prev2["Low"]):
                zl, zh = float(c_curr["High"]), float(c_prev2["Low"])
                if zh > zl and not ((df.iloc[i + 1:]["High"].astype(float) > zh).any()): return (zl, zh)
    except Exception: pass
    return None

FVG_EXPIRY_HOURS = 24

def register_pending_sweep(symbol, mtype, sweep):
    global pending_sweeps, _sweep_cooldown
    direction, sweep_high, sweep_low, sweep_open_ts, sweep_close_ts = sweep
    target_account = "nifty" if ("^NSE" in symbol or symbol.endswith(".NS")) else "sweep_4h"
    cooldown_key = f"{symbol}_{direction}"
    now_ts = int(time.time() * 1000)
    if now_ts - _sweep_cooldown.get(cooldown_key, 0) < 4 * 3600 * 1000: return
    with _lock:
        if any(p["symbol"] == symbol and p["direction"] == direction and p["sweep_close_ts"] == sweep_close_ts for p in pending_sweeps): return
        if accounts[target_account]["daily_trades"] >= ACCOUNT_LIMITS.get(target_account, 3): return
        if any(t["symbol"] == symbol and t["account"] == target_account for t in active_trades): return
        if any(p["symbol"] == symbol and p["status"] in ("waiting_fvg", "waiting_fill") for p in pending_sweeps): return
        _sweep_cooldown[cooldown_key] = now_ts
        pending_sweeps.append({"symbol": symbol, "mtype": mtype, "direction": direction, "sweep_high": float(sweep_high), "sweep_low": float(sweep_low), "sweep_open_ts": int(sweep_open_ts), "sweep_close_ts": int(sweep_close_ts), "created_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"), "fvg_zone": None, "fvg_found_at": None, "status": "waiting_fvg", "target_account": target_account})
        save_json(PENDING_SWEEPS_FILE, pending_sweeps)
    
    dt = datetime.fromtimestamp(sweep_close_ts / 1000, tz=IST)
    time_str = dt.strftime("%d-%b-%Y %H:%M IST")
    age_str = get_signal_age_str(sweep_close_ts)
    
    safe_send(CHAT_ID, f"🟢 *SWEEP — WAITING FOR FVG*\n{BR}\n🪙 *Asset:* `{symbol}`\n📊 *Direction:* {'LONG 📈' if direction=='BULLISH' else 'SHORT 📉'}\n⏰ *Sweep Time:* `{time_str}`\n⏳ *Age:* `{age_str}`\n{BR2}", parse_mode="Markdown")

def manage_pending_sweeps():
    global pending_sweeps
    while True:
        try:
            with _lock: copy = list(pending_sweeps)
            to_remove = []
            for p in copy:
                sym = p["symbol"]
                live_df = yf_download(sym, "1d", "1m")
                if live_df is None or live_df.empty: continue
                live = float(live_df["Close"].iloc[-1])
                age_hours = (time.time() * 1000 - p["sweep_close_ts"]) / (3600 * 1000)
                
                if age_hours > FVG_EXPIRY_HOURS and p["status"] != "entered":
                    with _lock: p["status"] = "expired"
                    to_remove.append(p)
                    safe_send(CHAT_ID, f"⏰ *PENDING SWEEP EXPIRED*\n{BR}\n`{sym}` {p['direction']}\n{BR2}", parse_mode="Markdown")
                    continue
                if p["direction"] == "BULLISH" and live <= p["sweep_low"]:
                    with _lock: p["status"] = "invalidated"
                    to_remove.append(p)
                    continue
                if p["direction"] == "BEARISH" and live >= p["sweep_high"]:
                    with _lock: p["status"] = "invalidated"
                    to_remove.append(p)
                    continue
                if p["fvg_zone"] is None:
                    fvg = find_fvg(yf_download(sym, "5d", "1h"), p["direction"], p["sweep_open_ts"])
                    if fvg:
                        zl, zh = fvg
                        with _lock:
                            p["fvg_zone"] = [float(fvg[0]), float(fvg[1])]; p["fvg_found_at"] = int(time.time() * 1000); p["status"] = "waiting_fill"
                            save_json(PENDING_SWEEPS_FILE, pending_sweeps)
                    continue
                zl, zh = p["fvg_zone"]
                if zl <= live <= zh:
                    fvg_entry = {"entry_price": live, "sl": p["sweep_low"] if p["direction"] == "BULLISH" else p["sweep_high"], "sweep_ts": p["sweep_close_ts"], "zone": p["fvg_zone"]}
                    with _lock: p["status"] = "entered"
                    to_remove.append(p)
                    execute(sym, p["mtype"], p.get("target_account", "sweep_4h"), "4H Sweep", p["direction"], live, fvg_entry["sl"], 0, p["sweep_close_ts"], fvg_entry=fvg_entry)
            if to_remove:
                with _lock:
                    pending_sweeps = [pp for pp in pending_sweeps if pp not in to_remove]
                    save_json(PENDING_SWEEPS_FILE, pending_sweeps)
        except Exception as e: alert_error("Pending Sweeps Manager", e)
        time.sleep(90)

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_f, ema_s = series.ewm(span=fast, adjust=False).mean(), series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_f - ema_s
    return macd_line, macd_line.ewm(span=signal, adjust=False).mean()

def check_trendpulse(ticker, mtype):
    try:
        df_1h = yf_download(ticker, "10d", "1h")
        if df_1h is None and ticker == "BTC-USD": df_1h = fetch_binance_klines("BTCUSDT", "1h", 200)
        if df_1h is None or len(df_1h) < 50: return None
        df_4h = df_1h.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        if len(df_4h) < 15: return None
        df_4h["EMA50"], df_4h["ATR"] = df_4h["Close"].ewm(span=50, adjust=False).mean(), calc_atr(df_4h, 14)
        htf_close, htf_ema50, htf_atr = float(df_4h["Close"].iloc[-2]), float(df_4h["EMA50"].iloc[-2]), float(df_4h["ATR"].iloc[-2])
        atr_pct = (htf_atr / htf_close) * 100
        if atr_pct < 0.2: return None
        df_1h["EMA20"], df_1h["RSI"], df_1h["ATR"] = df_1h["Close"].ewm(span=20, adjust=False).mean(), get_rsi(df_1h, 14), calc_atr(df_1h, 14)
        macd_line, signal_line = calc_macd(df_1h["Close"])
        m1_close, m1_ema20, m1_rsi, m1_atr = float(df_1h["Close"].iloc[-2]), float(df_1h["EMA20"].iloc[-2]), float(df_1h["RSI"].iloc[-2]), float(df_1h["ATR"].iloc[-2])
        macd_c, macd_p, sig_c, sig_p = float(macd_line.iloc[-2]), float(macd_line.iloc[-3]), float(signal_line.iloc[-2]), float(signal_line.iloc[-3])
        ts = int(df_1h.index[-2].timestamp() * 1000)
        if htf_close > htf_ema50:
            if (macd_p <= sig_p) and (macd_c > sig_c) and m1_rsi > 50 and m1_rsi < 80 and m1_close > m1_ema20:
                return ("BULLISH", m1_close, m1_atr, ts)
        elif htf_close < htf_ema50:
            if (macd_p >= sig_p) and (macd_c < sig_c) and m1_rsi < 50 and m1_rsi > 20 and m1_close < m1_ema20:
                return ("BEARISH", m1_close, m1_atr, ts)
    except Exception: pass
    return None

def get_trendpulse_exit(ticker, trade_type):
    try:
        df = yf_download(ticker, "2d", "1h")
        if df is None and ticker == "BTC-USD": df = fetch_binance_klines("BTCUSDT", "1h", 100)
        if df is None or len(df) < 30: return None
        macd_line, signal_line = calc_macd(df["Close"])
        macd_c, sig_c, macd_p, sig_p = float(macd_line.iloc[-2]), float(signal_line.iloc[-2]), float(macd_line.iloc[-3]), float(signal_line.iloc[-3])
        if trade_type == "LONG" and macd_p >= sig_p and macd_c < sig_c: return "EXIT"
        if trade_type == "SHORT" and macd_p <= sig_p and macd_c > sig_c: return "EXIT"
    except Exception: pass
    return None

def calc_sl_tp(sig, entry, atr):
    return (entry - atr * 1.5, entry + atr * 3.0) if "BULLISH" in sig else (entry + atr * 1.5, entry - atr * 3.0)

def calc_qty(account, entry, sl):
    with _lock:
        dist = abs(entry - sl)
        return 0.0 if dist == 0 else float((accounts[account]["balance"] * 0.02) / dist)

def format_signal_time(ts_ms):
    try: return datetime.fromtimestamp(ts_ms / 1000, tz=IST).strftime("%d-%b-%Y %H:%M IST (+5:30)")
    except Exception: return "Unknown"

def _iso_to_ist_dt(iso_str):
    if not iso_str: return None
    try:
        dt = datetime.fromisoformat(str(iso_str).split(".")[0])
        return IST.localize(dt) if dt.tzinfo is None else dt.astimezone(IST)
    except Exception: pass
    return None

def get_cached_news():
    """Get cached news with forced refresh on empty."""
    global NEWS_CACHE
    now = time.time()
    last_fetch = NEWS_CACHE.get("last_fetch", 0)
    cached_data = NEWS_CACHE.get("data", [])
    
    # Refresh if: cache is old (10 min) OR cache is empty
    if now - last_fetch > 600 or not cached_data:
        try:
            fresh_data = fetch_news()
            NEWS_CACHE["data"] = fresh_data
            NEWS_CACHE["last_fetch"] = now
            print(f"[NEWS] Cache refreshed: {len(fresh_data)} upcoming events")
        except Exception as e:
            print(f"[ERR] News refresh failed: {e}")
    
    return NEWS_CACHE.get("data", [])

def is_news_pause_active():
    if not _news_pause_enabled: return False, ""
    try:
        now = datetime.now(IST)
        for ev in get_cached_news():
            if str(ev.get("impact", "")).upper() not in ("HIGH", "H", "RED"): continue
            ev_dt = _iso_to_ist_dt(ev.get("date", ""))
            if ev_dt and abs((ev_dt - now).total_seconds() / 60) <= 15:
                return True, f"High-impact news: {ev.get('title', 'Unknown')} at {ev_dt.strftime('%H:%M IST')}"
    except Exception: pass
    return False, ""

def force_close_trade(trade_id, reason="Dashboard"):
    global active_trades, history, accounts
    trade_to_close = None
    with _lock:
        for t in list(active_trades):
            if t.get("id") == trade_id: trade_to_close = t; break
    if not trade_to_close: return False, f"Trade {trade_id} not found"
    
    p = get_price(trade_to_close.get("symbol", ""))
    if p is None: return False, "Could not fetch price"
    
    live, is_long = float(p), trade_to_close.get("type") == "LONG"
    entry, qty = trade_to_close.get("entry", 0), trade_to_close.get("qty", 0)
    pnl = (live - entry) * qty if is_long else (entry - live) * qty
    
    with _lock:
        if trade_to_close not in active_trades: return False, "Trade already closed"
        acc_name = trade_to_close.get("account", "macro")
        if acc_name in accounts: accounts[acc_name]["balance"] += pnl
        trade_to_close.update({"exit_price": live, "pnl": float(pnl), "result": "FORCE_CLOSE", "close_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)"), "closed_at": datetime.now(IST).isoformat(), "force_close_reason": reason, "trail_sl": trade_to_close.get("sl", live)})
        active_trades.remove(trade_to_close); history.append(trade_to_close)
        save_json(ACCOUNTS_FILE, accounts); save_json(ACTIVE_TRADES_FILE, active_trades); save_json(HISTORY_FILE, history)
        bal = accounts.get(acc_name, {}).get("balance", 0)
    safe_send(CHAT_ID, msg_trade_closed(trade_to_close, live, pnl, bal, is_long, pnl > 0), parse_mode="Markdown")
    return True, f"Closed {trade_to_close.get('symbol')} at {live:.4f}"

def build_strategy_stats():
    hist = load_json(HISTORY_FILE, [])
    strategies = {}
    for t in hist:
        strat = t.get("strat", "Unknown")
        if strat not in strategies: strategies[strat] = {"wins": 0, "losses": 0, "pnl": 0.0, "trades": 0}
        strategies[strat]["trades"] += 1
        if t.get("result") == "WIN": strategies[strat]["wins"] += 1
        elif t.get("result") == "LOSS": strategies[strat]["losses"] += 1
        try: strategies[strat]["pnl"] += float(t.get("pnl", 0))
        except: pass
    for d in strategies.values():
        total = d["wins"] + d["losses"]
        d["win_rate"] = round((d["wins"] / total * 100), 1) if total > 0 else 0
        d["avg_pnl"] = round((d["pnl"] / total), 2) if total > 0 else 0
    return strategies

def execute(symbol, mtype, account, strat, sig_type, price, a1, a2, a3=None, fvg_entry=None):
    global active_trades
    paused, pause_reason = is_news_pause_active()
    if paused:
        print(f"[NEWS PAUSE] Skipping {symbol} {sig_type} — {pause_reason}")
        safe_send(CHAT_ID, f"⏸️ *NEWS PAUSE*\n{BR}\n`{symbol}` {sig_type} skipped\n🛑 {pause_reason}\n{BR2}", parse_mode="Markdown"); return

    if fvg_entry is not None:
        sl, ts = float(fvg_entry["sl"]), fvg_entry["sweep_ts"]
        risk = abs(price - sl)
        if risk <= 0: return
        tp = price + risk * 2.0 if "BULLISH" in sig_type else price - risk * 2.0
    elif "Sweep" in strat: sl, tp, ts = float(a1), float(a2), a3
    else: atr, ts = float(a1), a2; sl, tp = calc_sl_tp(sig_type, price, atr)
        
    with _lock:
        key = f"{symbol}_{ts}_{sig_type}_{account}_fvg_{price:.6f}" if fvg_entry else f"{symbol}_{ts}_{sig_type}_{account}"
        if key in sent_signals: return
        sent_signals[key] = {"ts_ms": int(time.time() * 1000), "symbol": symbol, "sig_type": sig_type, "strat": strat, "account": account, "status": "open", "pnl": 0, "hint": "", "time_str": datetime.now(IST).strftime("%H:%M")}
        save_json(SENT_SIGNALS_FILE, sent_signals)
        
        lim = ACCOUNT_LIMITS.get(account, 3)
        if accounts[account]["daily_trades"] >= lim: return
        if any(t["symbol"] == symbol and t["account"] == account for t in active_trades): return
        qty = calc_qty(account, price, sl)
        if qty <= 0: return
        
        trade = {"id": f"{symbol}_{int(time.time())}", "symbol": symbol, "market": mtype, "account": account, "strat": strat, "type": "LONG" if "BULLISH" in sig_type else "SHORT", "entry": float(price), "sl": float(sl), "tp": float(tp), "qty": float(qty), "trail_sl": float(sl), "ts_trigger": ts, "opened_at": datetime.now(IST).isoformat(), "time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)")}
        active_trades.append(trade); accounts[account]["daily_trades"] += 1
        save_json(ACCOUNTS_FILE, accounts); save_json(ACTIVE_TRADES_FILE, active_trades)
        safe_send(CHAT_ID, msg_trade_signal(symbol, mtype, strat, sig_type, "4H" if "Sweep" in strat else "1H", price, sl, tp, qty, abs(price - sl) * qty, account, ts, fvg_entry.get("zone") if fvg_entry else None), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📈 Chart", callback_data=f"chart_{symbol}"), InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}")]]))

def monitor():
    global active_trades
    while True:
        if not active_trades: time.sleep(15); continue
        to_close = []
        with _lock: copy = list(active_trades)
        for t in copy:
            try:
                df = yf_download(t["symbol"], "1d", "1m")
                if df is None or df.empty: continue
                live = float(df["Close"].iloc[-1])
                with _lock: _price_cache[t["symbol"]] = (live, time.time())
                
                with _lock:
                    long, entry, tp, qty = t["type"] == "LONG", t["entry"], t["tp"], t["qty"]
                    account, strat = t["account"], t["strat"]
                    
                    if long: pct = (live - entry) / entry * 100
                    else: pct = (entry - live) / entry * 100
                    
                    if pct >= 1.0: t["trail_sl"] = max(t["trail_sl"], entry) if long else min(t["trail_sl"], entry)
                    if pct >= 3.0: t["trail_sl"] = max(t["trail_sl"], entry + (live - entry) * 0.3) if long else min(t["trail_sl"], entry - (entry - live) * 0.3)
                    if pct >= 5.0: t["trail_sl"] = max(t["trail_sl"], entry + (live - entry) * 0.5) if long else min(t["trail_sl"], entry - (entry - live) * 0.5)
                    
                    trail_sl = t["trail_sl"]
                    hit_tp = (long and live >= tp) or (not long and live <= tp)
                    hit_sl = (long and live <= trail_sl) or (not long and live >= trail_sl)
                
                if strat == "TrendPulse 1H" and not (hit_tp or hit_sl):
                    now = time.time()
                    if now - _ut_15m_cache.get(t["symbol"], (None, 0))[1] >= 120:
                        exit_sig = get_trendpulse_exit(t["symbol"], t["type"])
                        _ut_15m_cache[t["symbol"]] = (exit_sig, now)
                        if exit_sig == "EXIT":
                            pnl = (live - entry) * qty * (1 if long else -1)
                            with _lock:
                                accounts[account]["balance"] += pnl; t.update({"exit_price": live, "pnl": float(pnl), "result": "MACD EXIT", "close_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)"), "closed_at": datetime.now(IST).isoformat()})
                                to_close.append(t); history.append(t)
                                save_json(ACCOUNTS_FILE, accounts); save_json(HISTORY_FILE, history)
                                bal = accounts[account]["balance"]
                            safe_send(CHAT_ID, msg_trade_closed(t, live, pnl, bal, long, pnl > 0), parse_mode="Markdown")
                            continue
                
                if not (hit_tp or hit_sl): continue

                if hit_tp: pnl = (tp - entry) * qty * (1 if long else -1)
                else: pnl = (trail_sl - entry) * qty * (1 if long else -1)
                
                with _lock:
                    accounts[account]["balance"] += pnl; t.update({"exit_price": live, "pnl": float(pnl), "result": "WIN" if hit_tp else "LOSS", "close_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)"), "closed_at": datetime.now(IST).isoformat()})
                    to_close.append(t); history.append(t)
                    save_json(ACCOUNTS_FILE, accounts); save_json(HISTORY_FILE, history)
                    bal = accounts[account]["balance"]
                safe_send(CHAT_ID, msg_trade_closed(t, live, pnl, bal, long, hit_tp), parse_mode="Markdown")
            except Exception as e: alert_error(f"Monitor: {t.get('symbol','?')}", e)
        if to_close:
            with _lock:
                for x in to_close:
                    if x in active_trades: active_trades.remove(x)
                save_json(ACTIVE_TRADES_FILE, active_trades)
        time.sleep(20)

MONITORED = [("BTC-USD", "Crypto"), ("GC=F", "Gold"), ("EURUSD=X", "Forex"), ("GBPUSD=X", "Forex"), ("USDJPY=X", "Forex"), ("^NSEI", "NIFTY 50"), ("^NSEBANK", "BANK NIFTY")] + [(sym, "NSE") for sym, _ in NIFTY_STOCKS]

def scanner():
    while True:
        try:
            for symbol, mtype in MONITORED:
                with _lock:
                    if symbol in muted_assets or not is_market_open(symbol): continue
                is_nse = "^NSE" in symbol or symbol.endswith(".NS")
                if not is_nse:
                    tp = check_trendpulse(symbol, mtype)
                    if tp: execute(symbol, mtype, "ny_session" if is_ny_session() else "macro", "TrendPulse 1H", tp[0], tp[1], tp[2], tp[3])
                    sweep = check_sweep(symbol)
                    if sweep: register_pending_sweep(symbol, mtype, sweep)
                elif is_nifty_open():
                    sweep = check_sweep(symbol)
                    if sweep: register_pending_sweep(symbol, mtype, sweep)
                time.sleep(2); gc.collect()
        except Exception as e: alert_error("Scanner", e); time.sleep(300)

def daily_reset():
    global sent_signals, history
    reset_state = load_json(RESET_STATE_FILE, {"last_reset_date": ""})
    last = reset_state.get("last_reset_date", "")
    while True:
        try:
            today = datetime.now(IST).strftime("%Y-%m-%d")
            if last != today:
                with _lock:
                    for acc in accounts: 
                        if isinstance(accounts[acc], dict):
                            accounts[acc]["daily_trades"] = 0
                    reset_state["last_reset_date"] = today
                    save_json(RESET_STATE_FILE, reset_state)
                    save_json(ACCOUNTS_FILE, accounts)
                    if len(sent_signals) > 500: sent_signals = {k: sent_signals[k] for k in list(sent_signals.keys())[-500:]}
                    save_json(SENT_SIGNALS_FILE, sent_signals)
                    history = load_json(HISTORY_FILE, [])
                    day_pnl = sum(float(t["pnl"]) for t in history if t.get("close_time", "").startswith(last))
                    safe_send(CHAT_ID, msg_midnight_reset(day_pnl, accounts["macro"]["balance"], accounts["nifty"]["balance"], accounts["ny_session"]["balance"], accounts["sweep_4h"]["balance"]), parse_mode="Markdown")
                    if len(history) > 500: history = history[-500:]
                    save_json(HISTORY_FILE, history)
                last = today; gc.collect()
        except Exception as e: alert_error("Daily Reset", e)
        time.sleep(60)

def weekly_digest_loop():
    while True:
        try:
            now = datetime.now(IST)
            if now.weekday() == 6 and now.hour >= 21:
                week_label = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
                state = load_json(WEEKLY_DIGEST_FILE, {"last_sent_week": None})
                if state.get("last_sent_week") != week_label:
                    safe_send(CHAT_ID, build_weekly_digest_text(7), parse_mode="Markdown")
                    state["last_sent_week"] = week_label; save_json(WEEKLY_DIGEST_FILE, state)
        except Exception as e: alert_error("Weekly Digest", e)
        time.sleep(600)

def build_weekly_digest_text(days=7):
    hist = load_json(HISTORY_FILE, [])
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d")
    week_trades = [t for t in hist if str(t.get("closed_at", ""))[:10] >= cutoff]
    week_pnl, wins, losses, per_symbol = 0.0, 0, 0, {}
    for t in week_trades:
        try: pnl = float(t.get("pnl", 0))
        except: pnl = 0.0
        week_pnl += pnl
        if t.get("result") == "WIN": wins += 1
        elif t.get("result") == "LOSS": losses += 1
        per_symbol[t.get("symbol", "?")] = per_symbol.get(t.get("symbol", "?"), 0.0) + pnl
    best_sym, best_pnl = max(per_symbol.items(), key=lambda kv: kv[1]) if per_symbol else (None, 0)
    worst_sym, worst_pnl = min(per_symbol.items(), key=lambda kv: kv[1]) if per_symbol else (None, 0)
    total_equity = sum(float(accounts.get(a, {}).get("balance", 0)) for a in ["macro", "nifty", "ny_session", "sweep_4h"])
    return msg_weekly_digest(week_pnl, wins, losses, best_sym, best_pnl, worst_sym, worst_pnl, total_equity)

def fetch_news():
    """Fetch economic calendar with reliable fallbacks."""
    sources = [
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    ]
    
    all_events = []
    for url in sources:
        try:
            print(f"[NEWS] Fetching from {url}...")
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=20)
            if r.status_code == 200 and r.text.strip():
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    all_events.extend(data)
                    print(f"[NEWS] Got {len(data)} events from {url}")
        except Exception as e:
            print(f"[NEWS] Failed {url}: {e}")
    
    if not all_events:
        print("[NEWS] ⚠️ All sources failed — no events available")
        return []
    
    # Filter to ONLY upcoming events (from now onwards)
    now = datetime.now(IST)
    upcoming = []
    for ev in all_events:
        try:
            ev_date_str = ev.get("date", "")
            if not ev_date_str: continue
            
            # Parse ISO date with timezone
            ev_dt = _iso_to_ist_dt(ev_date_str)
            if ev_dt and ev_dt >= now:
                upcoming.append(ev)
        except Exception as e:
            print(f"[NEWS] Failed to parse event: {e}")
            continue
    
    print(f"[NEWS] ✅ {len(upcoming)} upcoming events (filtered from {len(all_events)} total)")
    return upcoming

@bot.message_handler(commands=["start", "menu"])
def cmd_start(m): safe_send(m.chat.id, msg_guide(), parse_mode="Markdown")

@bot.message_handler(commands=["backtest"])
def cmd_backtest(m):
    if not _backtest_available: safe_send(m.chat.id, "⚠️ Backtest engine not available.", parse_mode="Markdown"); return
    parts = m.text.split()
    if len(parts) < 2: safe_send(m.chat.id, "📊 *Backtest Usage*\n`/backtest <symbol> [strategy] [days]`", parse_mode="Markdown"); return
    symbol, strategy = parts[1].upper(), parts[2].lower() if len(parts) > 2 else "trendpulse"
    try: days = min(int(parts[3]) if len(parts) > 3 else 30, 365)
    except ValueError: safe_send(m.chat.id, "❌ Days must be a number.", parse_mode="Markdown"); return
    if strategy not in ("trendpulse", "sweep"): safe_send(m.chat.id, "❌ Strategy must be trendpulse or sweep", parse_mode="Markdown"); return
    safe_send(m.chat.id, f"📊 *Backtesting {strategy.upper()} on {symbol}...*", parse_mode="Markdown")
    def run():
        try:
            engine = BacktestEngine()
            res = engine.backtest_trendpulse(symbol, days) if strategy == "trendpulse" else engine.backtest_sweep(symbol, days)
            if "error" in res: safe_send(m.chat.id, f"❌ {res['error']}", parse_mode="Markdown"); return
            
            chart_path = "/tmp/workspace/backtest_chart.png"
            caption = (
                f"📊 *BACKTEST RESULTS*\n"
                f"🪙 *Symbol:* `{symbol}`\n"
                f"📈 *Trades:* `{res['total_trades']}`\n"
                f"🎯 *Win Rate:* `{res['win_rate']:.1f}%`\n"
                f"💰 *P/L:* `₹{res['total_pnl']:,.2f}`\n"
                f"📉 *Max DD:* `{res['max_drawdown_pct']:.1f}%`"
            )
            if os.path.exists(chart_path):
                with open(chart_path, "rb") as f:
                    bot.send_photo(m.chat.id, f, caption=caption, parse_mode="Markdown")
            else:
                safe_send(m.chat.id, caption, parse_mode="Markdown")
        except Exception as e: safe_send(m.chat.id, f"❌ {str(e)[:200]}", parse_mode="Markdown")
    threading.Thread(target=run, daemon=True).start()

@bot.message_handler(commands=["newspause"])
def cmd_newspause(m):
    global _news_pause_enabled
    parts = m.text.split()
    if len(parts) > 1 and parts[1].lower() in ("off", "0"): _news_pause_enabled = False; safe_send(m.chat.id, "⏸️ News Pause DISABLED", parse_mode="Markdown")
    elif len(parts) > 1 and parts[1].lower() in ("on", "1"): _news_pause_enabled = True; safe_send(m.chat.id, "▶️ News Pause ENABLED", parse_mode="Markdown")
    else: safe_send(m.chat.id, f"News Pause: {'ON ✅' if _news_pause_enabled else 'OFF 🛑'}", parse_mode="Markdown")

def send_chart(symbol, chat_id):
    with _chart_lock:
        try:
            df = yf_download(symbol, "5d", "1h")
            if df is None or df.empty:
                safe_send(chat_id, f"⚠️ No chart data available for `{symbol}`", parse_mode="Markdown"); return
            close = df["Close"]
            if hasattr(close, "columns"): close = close.iloc[:, 0]
            close = close.dropna()
            if close.empty:
                safe_send(chat_id, f"⚠️ No chart data available for `{symbol}`", parse_mode="Markdown"); return
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(close.index, close.values, color="#7c6cff", linewidth=1.4)
            ax.set_title(f"{symbol} — 5D / 1H", fontsize=12)
            ax.grid(alpha=0.2)
            ax.tick_params(labelsize=8)
            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=110)
            plt.close(fig)
            buf.seek(0)
            bot.send_photo(chat_id, buf, caption=f"📈 `{symbol}` — last 5 days (1H)", parse_mode="Markdown")
        except Exception as e:
            print(f"[ERR] send_chart {symbol}: {e}")
            safe_send(chat_id, f"⚠️ Failed to generate chart for `{symbol}`", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def on_callback(call):
    try:
        if call.data.startswith("mute_"):
            with _lock: muted_assets.add(call.data.split("_", 1)[1])
            bot.answer_callback_query(call.id, text=f"🔇 {call.data.split('_', 1)[1]} muted")
        elif call.data.startswith("chart_"):
            bot.answer_callback_query(call.id, text="📈 Generating chart...")
            threading.Thread(target=send_chart, args=(call.data.split("_", 1)[1], call.message.chat.id), daemon=True).start()
        else:
            bot.answer_callback_query(call.id)
    except Exception: pass

if __name__ == "__main__":
    print("[INIT] Starting bot...")
    init_accounts()
    history = load_json(HISTORY_FILE, [])
    sent_signals = load_json(SENT_SIGNALS_FILE, {})
    muted_assets = set(load_json(MUTE_FILE, []))
    pending_sweeps = load_json(PENDING_SWEEPS_FILE, [])
    
    # FIX: Bot Started message with stale warning
    start_time_str = datetime.now(IST).strftime("%d-%b-%Y %H:%M IST")
    start_msg = (
        f"✅ *BOT STARTED*\n"
        f"{BR}\n"
        f"🕒 *Started At:* `{start_time_str}`\n"
        f"⚠️ *WARNING:* Any signal/sweep message older than this one is STALE — do not act on it.\n"
        f"{BR2}"
    )
    safe_send(CHAT_ID, start_msg, parse_mode="Markdown")
    
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()
    threading.Thread(target=manage_pending_sweeps, daemon=True).start()
    threading.Thread(target=daily_reset, daemon=True).start()
    threading.Thread(target=weekly_digest_loop, daemon=True).start()
    print("[INIT] Bot running with P0/P1 fixes applied.")
    while True: time.sleep(3600)
