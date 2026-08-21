import os
import json
import time
import threading
import gc
from datetime import datetime, timedelta, timezone
from io import BytesIO
import io
from typing import Dict, List, Optional, Tuple, Any
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

from db import DatabaseManager

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

# Support multiple chat IDs (comma-separated): personal + group(s)
CHAT_IDS = [cid.strip() for cid in CHAT_ID.split(",") if cid.strip()] if CHAT_ID else []
if not CHAT_IDS:
    raise ValueError("TELEGRAM_CHAT_ID not set!")
print(f"[INIT] Bot will send to {len(CHAT_IDS)} chat(s): {CHAT_IDS}")

NIFTY_STOCKS = [
    ("RELIANCE.NS", "Reliance"), ("HDFCBANK.NS", "HDFC Bank"),
    ("ICICIBANK.NS", "ICICI Bank"), ("INFY.NS", "Infosys"), ("TCS.NS", "TCS"),
    ("ITC.NS", "ITC"), ("SBIN.NS", "SBI"), ("BHARTIARTL.NS", "Bharti Airtel"),
    ("LT.NS", "L&T"), ("HINDUNILVR.NS", "HUL"), ("AXISBANK.NS", "Axis Bank"),
    ("KOTAKBANK.NS", "Kotak Bank"), ("BAJFINANCE.NS", "Bajaj Finance"),
    ("MARUTI.NS", "Maruti"), ("SUNPHARMA.NS", "Sun Pharma"),
]

SYMBOL_NAMES = {
    "BTC-USD": "Bitcoin (BTC)",
    "GC=F": "Gold (XAU/USD)",
    "SI=F": "Silver (XAG/USD)",
    "HG=F": "Copper",
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "USDCHF=X": "USD/CHF",
    "AUDUSD=X": "AUD/USD",
    "USDCAD=X": "USD/CAD",
    "NZDUSD=X": "NZD/USD",
    "^NSEI": "NIFTY 50",
    "^NSEBANK": "BANK NIFTY",
    **{sym: name for sym, name in NIFTY_STOCKS}
}

def display_name(symbol: str) -> str:
    """Returns a clean, readable name for any ticker."""
    if symbol in SYMBOL_NAMES:
        return SYMBOL_NAMES[symbol]
    clean = symbol.replace("=X", "").replace(".NS", "").replace("^", "")
    return clean

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set!")

ACCOUNT_LIMITS = {"macro": 20, "nifty": 5, "ny_session": 3, "sweep_4h": 3}
MAX_SIGNAL_AGE_HOURS = 6  # Strictly 6 hours maximum limit
MAX_MSG_SEND_COUNT = 2    # Maximum identical message repeats allowed

db = DatabaseManager()
accounts = {}
muted_assets = set()
_lock = threading.RLock()

_news_pause_enabled = True
_chart_lock = threading.RLock()
_price_cache = {}
EST = pytz.timezone("America/New_York")
IST = pytz.timezone("Asia/Kolkata")
_sweep_cooldown = {}
_ut_15m_cache = {}
NEWS_CACHE = {"data": [], "last_fetch": 0, "initialized": False}
NEWS_CACHE_FILE = "/tmp/workspace/news_upcoming_cache.json"
NEWS_CACHE_TTL_S = 1800

_yf_symbol_cache = {} 
_YF_SYMBOL_TTL = 30.0

_yf_session = requests.Session()
_yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

BR = "━━━━━━━━━━━━━━━━━━━━━━"
BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

def get_signal_age_str(ts_ms):
    if not ts_ms:
        return "Unknown", "⚠️ STALE"
    now_ms = int(time.time() * 1000)
    diff_ms = now_ms - ts_ms
    diff_min = int(diff_ms / 60000)
    diff_hr = int(diff_min / 60)
    if diff_min < 60:
        age_str = f"{diff_min} min ago"
        tag = "✅ FRESH" if diff_min <= 60 else "⚠️ STALE"
    else:
        age_str = f"{diff_hr} hr {diff_min % 60} min ago"
        tag = "✅ FRESH" if diff_hr < 2 else "⚠️ STALE"
    return age_str, tag

def is_signal_too_old(ts_ms, max_hours=MAX_SIGNAL_AGE_HOURS):
    if not ts_ms:
        return False
    age_hours = (time.time() * 1000 - ts_ms) / (3600 * 1000)
    return age_hours > max_hours

def check_and_increment_msg_count(key: str) -> bool:
    """Tracks message send count via SQLite/Supabase. Drops if sent >= MAX_MSG_SEND_COUNT."""
    return db.check_and_increment_signal(key, max_count=MAX_MSG_SEND_COUNT)

def msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, actual_sl, actual_tp, qty, risk_amt, account, signal_ts_ms, fvg_zone=None):
    is_bullish = "BULLISH" in sig_type
    dot = "🟢" if is_bullish else "🔴"
    dir_label = "LONG 📈" if is_bullish else "SHORT 📉"
    is_sweep = bool(strat and "Sweep" in strat)
    curr = _currency(symbol)
    name_str = display_name(symbol)
    
    age_str, tag = get_signal_age_str(signal_ts_ms)
    dt = datetime.fromtimestamp(signal_ts_ms / 1000, tz=IST)
    time_str = dt.strftime("%d-%b-%Y %H:%M IST")
    status_icon = "✅" if "FRESH" in tag else "⚠️"
    
    header_title = f"FVG Fill ({tf}) · {name_str}" if is_sweep and fvg_zone else (f"{strat} · {name_str}" if not is_sweep else f"4H Sweep · {name_str}")
    fvg_line = f"🎯 *FVG Zone ({tf}):* `{curr}{fvg_zone[0]:,.4f} — {curr}{fvg_zone[1]:,.4f}`\n" if fvg_zone and is_sweep else ""
    
    return (
        f"{dot} *{header_title}* · {status_icon}\n{BR}\n"
        f"🪙 *Asset:* `{name_str}` (`{symbol}`)\n"
        f"🌐 *Market:* {mtype}\n"
        f"📊 *Direction:* {dir_label}\n"
        f"⏱ *Timeframe:* {tf}\n{BR}\n"
        f"⏳ *Signal Status:* `{tag}` ({age_str})\n"
        f"⏰ *Candle Closed:* `{time_str}`\n{BR}\n"
        f"💼 *PAPER TRADE EXECUTED*\n{BR}\n"
        f"🏢 *Account:* `{account.upper()}`\n"
        f"📍 *Entry:* `{curr}{price:,.4f}`\n"
        f"🛑 *Stop Loss:* `{curr}{actual_sl:,.4f}`\n"
        f"🎯 *Take Profit:* `{curr}{actual_tp:,.4f}`\n"
        f"{fvg_line}"
        f"📦 *Quantity:* `{qty:.4f}`\n"
        f"💸 *Risk:* `₹{risk_amt:,.2f}`\n{BR}\n"
        f"ℹ️ _✅ FRESH = Closed ≤1h ago | ⚠️ STALE = Closed >1h ago_\n{BR2}"
    )

def msg_trade_closed(trade, live, pnl, bal, is_long, hit_tp):
    result = "🎉 WIN" if hit_tp else "💀 LOSS"
    dot = "🟢" if is_long else "🔴"
    money = "💰" if hit_tp else "💸"
    pnl_s = f"+₹{pnl:,.2f}" if hit_tp else f"-₹{abs(pnl):,.2f}"
    curr = _currency(trade['symbol'])
    name_str = display_name(trade['symbol'])
    return (
        f"{dot} *TRADE CLOSED — {result}*\n{BR}\n"
        f"🪙 `{name_str}` | {'LONG' if is_long else 'SHORT'}\n"
        f"🎯 *Strategy:* {trade.get('strat', 'N/A')}\n"
        f"🏢 *Account:* `{trade.get('account', 'MACRO').upper()}`\n{BR}\n"
        f"📍 *Entry:* `{curr}{trade['entry']:,.4f}`\n"
        f"{'📈' if hit_tp else '📉'} *Exit:* `{curr}{live:,.4f}`\n"
        f"🛑 *SL Hit:* `{curr}{trade['trail_sl']:,.4f}`\n"
        f"🎯 *TP Target:* `{curr}{trade['tp']:,.4f}`\n{BR}\n"
        f"{money} *P/L:* `{pnl_s}`\n"
        f"🏦 *Balance:* `₹{bal:,.2f}`\n{BR2}"
    )

def msg_midnight_reset(day_pnl, macro_bal, nifty_bal, ny_bal, sweep_bal):
    pnl_icon = "📈" if day_pnl >= 0 else "📉"
    pnl_sign = "+" if day_pnl >= 0 else ""
    return f"🌙 *MIDNIGHT RESET*\n{BR}\n{pnl_icon} *Yesterday P/L:* `{pnl_sign}₹{day_pnl:,.2f}`\n{BR}\n🏦 *Account Balances:*\n├ 🌐 *Macro:* `₹{macro_bal:,.2f}`\n├ 🇮🇳 *Nifty:* `₹{nifty_bal:,.2f}`\n├ 🇺🇸 *NY Session:* `₹{ny_bal:,.2f}`\n└ 🔵 *Sweep 4H:* `₹{sweep_bal:,.2f}`\n{BR}\n🔄 *Daily trade limits reset*\n🧹 *Signal cache cleaned*\n{BR2}"

def msg_weekly_digest(week_pnl, wins, losses, best_sym, best_pnl, worst_sym, worst_pnl, total_equity):
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100.0) if total_trades else 0.0
    pnl_icon = "📈" if week_pnl >= 0 else "📉"
    pnl_sign = "+" if week_pnl >= 0 else ""
    best_str = f"`{display_name(best_sym)}` (`{'+' if best_pnl >= 0 else ''}₹{best_pnl:,.2f}`)" if best_sym else "—"
    worst_str = f"`{display_name(worst_sym)}` (`{'+' if worst_pnl >= 0 else ''}₹{worst_pnl:,.2f}`)" if worst_sym else "—"
    return f"🗓️ *WEEKLY DIGEST*\n{BR}\n{pnl_icon} *Week P/L:* `{pnl_sign}₹{week_pnl:,.2f}`\n📊 *Trades:* `{total_trades}` · ✅ `{wins}W` · ❌ `{losses}L` · 🎯 `{win_rate:.1f}%`\n{BR}\n🏆 *Best Symbol:* {best_str}\n💔 *Worst Symbol:* {worst_str}\n{BR}\n🏦 *Total Equity:* `₹{total_equity:,.2f}`\n{BR2}"

def msg_guide():
    return (
        f"🤖 *MAVIS TRADING ENGINE — COMMAND CENTER*\n{BR}\n"
        f"📊 *OPERATIONAL COMMANDS:*\n"
        f"├ `/start` — Command guide & status\n"
        f"├ `/check` — Force immediate scan on all pairs\n"
        f"├ `/test` — Test data feeds & latency\n"
        f"├ `/summary` — Open trades & floating P/L\n"
        f"├ `/balance` — View virtual account equity\n"
        f"├ `/pending` — Show 4H sweeps waiting for FVG\n"
        f"├ `/stats` — Strategy win-rate & P/L report\n"
        f"├ `/risk` — Portfolio exposure & 1R metrics\n"
        f"├ `/weekly` — 7-day performance digest\n"
        f"├ `/newspause` — Toggle high-impact news pause\n"
        f"├ `/refreshnews` — Force refresh news calendar\n"
        f"└ `/backtest` — Run strategy backtester\n{BR2}"
    )

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
        if now - last < cooldown_s:
            return
        _error_alert_last_sent[context] = now
    try:
        send_to_personal_only(msg_error(context, error), parse_mode="Markdown")
    except Exception:
        pass

class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True

def run_web():
    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")
        _resp = dashboard_api.register_routes(path, start_response, environ)
        if _resp is not None:
            return _resp
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

def _currency(symbol):
    return "₹" if (symbol.endswith(".NS") or "NSE" in symbol) else "$"

def safe_send(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception:
        try:
            clean_text = text.replace("*", "").replace("`", "").replace("_", "")
            bot.send_message(chat_id, clean_text, parse_mode=None)
        except Exception:
            pass

def send_sweep_to_all(message: str, **kwargs):
    """Sends sweep signals to ALL registered chats including group IDs."""
    if not CHAT_IDS:
        return
    for cid in CHAT_IDS:
        try:
            safe_send(cid, message, **kwargs)
            print(f"[SWEEP→ALL] Sent to {cid}: {message[:60]}...")
        except Exception as e:
            print(f"[ERR] [SWEEP→ALL] Failed to send to chat {cid}: {e}")

def send_to_personal_only(message: str, **kwargs):
    """Sends non-sweep and system notifications only to personal chats."""
    if not CHAT_IDS:
        return
    for cid in CHAT_IDS:
        if not str(cid).startswith("-"):
            try:
                safe_send(cid, message, **kwargs)
                print(f"[PERSONAL] Sent to {cid}: {message[:60]}...")
            except Exception as e:
                print(f"[ERR] [PERSONAL] Failed to send to personal chat {cid}: {e}")

def init_accounts():
    global accounts
    defaults = {"macro": 100000.0, "nifty": 100000.0, "ny_session": 100000.0, "sweep_4h": 100000.0}
    today = datetime.now(IST).strftime("%Y-%m-%d")
    accounts = db.init_accounts(defaults, today)

def is_ny_session():
    h, m = datetime.now(IST).hour, datetime.now(IST).minute
    return (h == 20 and m >= 0) or h in (21, 22, 23, 0, 1) or (h == 2 and m <= 30)

def is_nifty_open():
    n = datetime.now(IST)
    return n.weekday() < 5 and 555 <= (n.hour * 60 + n.minute) <= 930

def is_market_open(symbol):
    n = datetime.now(IST)
    w, tm = n.weekday(), n.hour * 60 + n.minute
    if symbol in ("BTC-USD", "GC=F"):
        return True
    if symbol in ("EURUSD=X", "GBPUSD=X", "USDJPY=X"):
        if w == 5: return False
        if w == 6: return tm >= 150
        if w == 4: return tm <= 1410
        return True
    if symbol in ("^NSEI", "^NSEBANK") or symbol.endswith(".NS"):
        return w < 5 and 555 <= tm <= 930
    return False

def yf_download(symbol, period, interval):
    now = time.time()
    cache_key = f"{symbol}_{period}_{interval}"
    if cache_key in _yf_symbol_cache:
        cached_df, cached_ts = _yf_symbol_cache[cache_key]
        if now - cached_ts < _YF_SYMBOL_TTL:
            return cached_df.copy()
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True, threads=False, session=_yf_session)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        _yf_symbol_cache[cache_key] = (df, now)
        return df
    except Exception as e:
        print(f"[ERR] yf_download {symbol} {interval}: {e}")
        return None

def get_price(symbol):
    now = time.time()
    if symbol in _price_cache:
        p, ts = _price_cache[symbol]
        if now - ts < 60:
            return p
    if symbol == "BTC-USD":
        try:
            r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                p = float(r.json()["bitcoin"]["usd"])
                _price_cache[symbol] = (p, now)
                return p
        except Exception:
            pass
    if symbol == "GC=F":
        for gold_sym in ["GC=F", "GLD", "IAU"]:
            try:
                df = yf_download(gold_sym, "1d", "1m")
                if df is not None and not df.empty:
                    p = float(df["Close"].iloc[-1])
                    _price_cache[symbol] = (p, now)
                    return p
            except Exception:
                continue
    df = yf_download(symbol, "1d", "1m")
    if df is not None and not df.empty:
        p = float(df["Close"].iloc[-1])
        _price_cache[symbol] = (p, now)
        return p
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
        df["Open time"] = pd.to_datetime(df["Open time"], unit="ms")
        df.set_index("Open time", inplace=True)
        return df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    except Exception:
        return None

def notify_neutral_sweep(symbol: str, mtype: str, sweep_high: float, sweep_low: float, sweep_ts_ms: int):
    """Sends neutral 'sweep detected' alert. Drops if >6h old or already sent 2 times."""
    if is_signal_too_old(sweep_ts_ms):
        print(f"[STALE SKIP] Suppressing neutral sweep on {symbol} (> {MAX_SIGNAL_AGE_HOURS}h old)")
        return
        
    msg_key = f"neutral_sweep_{symbol}_{sweep_ts_ms}"
    if not check_and_increment_msg_count(msg_key):
        print(f"[REPEAT SKIP] Neutral sweep for {symbol} already sent {MAX_MSG_SEND_COUNT} times.")
        return

    dt = datetime.fromtimestamp(sweep_ts_ms / 1000, tz=IST)
    time_str = dt.strftime("%d-%b-%Y %H:%M IST")
    age_str, tag = get_signal_age_str(sweep_ts_ms)
    curr = _currency(symbol)
    name_str = display_name(symbol)
    status_icon = "✅" if "FRESH" in tag else "⚠️"
    
    msg = (
        f"⚡ *SWEEP DETECTED · {name_str}* · {status_icon}\n{BR}\n"
        f"🪙 *Asset:* `{name_str}` (`{symbol}`)\n"
        f"🌐 *Market:* {mtype}\n"
        f"📍 *High:* `{curr}{sweep_high:,.4f}`\n"
        f"📍 *Low:* `{curr}{sweep_low:,.4f}`\n{BR}\n"
        f"⏳ *Signal Status:* `{tag}` ({age_str})\n"
        f"⏰ *Sweep Time:* `{time_str}`\n"
        f"ℹ️ *Action:* Informational — No trade pending\n{BR}\n"
        f"ℹ️ _✅ FRESH = Closed ≤1h ago | ⚠️ STALE = Closed >1h ago_\n{BR2}"
    )
    send_sweep_to_all(msg, parse_mode="Markdown")

def check_sweep(ticker):
    """Differentiates directional vs neutral sweeps."""
    try:
        df = yf_download(ticker, "15d", "1h")
        if df is None or len(df) < 20:
            return None
        df = df.resample("4h").agg({
            "Open": "first", "High": "max", "Low": "min", "Close": "last"
        }).dropna().iloc[:-1]
        if len(df) < 4:
            return None
        c, m = df.iloc[-2], df.iloc[-3]
        ts = int(df.index[-2].timestamp() * 1000)

        # 1. Clear Directional Bullish Sweep: Swept low, closed inside
        if c["Low"] < m["Low"] and c["High"] <= m["High"] and c["Close"] > m["Low"]:
            return ("BULLISH", float(c["High"]), float(c["Low"]), ts, ts + 4 * 3600 * 1000)

        # 2. Clear Directional Bearish Sweep: Swept high, closed inside
        if c["High"] > m["High"] and c["Low"] >= m["Low"] and c["Close"] < m["High"]:
            return ("BEARISH", float(c["High"]), float(c["Low"]), ts, ts + 4 * 3600 * 1000)

        # 3. Neutral Sweep: Both sides swept
        if c["Low"] < m["Low"] and c["High"] > m["High"]:
            return ("NEUTRAL", float(c["High"]), float(c["Low"]), ts, ts + 4 * 3600 * 1000)

    except Exception:
        pass
    return None

def find_timeframe_fvg(df: pd.DataFrame, direction: str, sweep_open_ts_ms: int) -> Optional[Tuple[float, float]]:
    """Scans for an unmitigated 3-candle Fair Value Gap."""
    try:
        if df is None or len(df) < 3:
            return None
            
        sweep_open = pd.to_datetime(int(sweep_open_ts_ms), unit="ms")
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            sweep_open = sweep_open.tz_localize("UTC") if sweep_open.tz is None else sweep_open.tz_convert(idx.tz)
            
        df_post = df[idx >= sweep_open].reset_index(drop=True)
        if len(df_post) < 3:
            return None

        for i in range(2, len(df_post)):
            c_prev2 = df_post.iloc[i - 2]
            c_curr = df_post.iloc[i]
            
            if direction == "BULLISH" and float(c_curr["Low"]) > float(c_prev2["High"]):
                zl, zh = float(c_prev2["High"]), float(c_curr["Low"])
                if zh > zl and not ((df_post.iloc[i + 1:]["Low"].astype(float) < zl).any()):
                    return (zl, zh)
                    
            elif direction == "BEARISH" and float(c_curr["High"]) < float(c_prev2["Low"]):
                zl, zh = float(c_curr["High"]), float(c_prev2["Low"])
                if zh > zl and not ((df_post.iloc[i + 1:]["High"].astype(float) > zh).any()):
                    return (zl, zh)
    except Exception:
        pass
    return None

def resolve_hierarchical_fvg(symbol: str, direction: str, sweep_open_ts: int) -> Tuple[Optional[Tuple[float, float]], Optional[str]]:
    """Checks for 4-Hour FVG first; if none exists, falls back to 1-Hour FVG."""
    df_1h = yf_download(symbol, "15d", "1h")
    if df_1h is None or len(df_1h) < 10:
        return None, None
        
    df_4h = df_1h.resample("4h").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last"
    }).dropna()
    
    # Priority 1: Check 4-Hour FVG
    fvg_4h = find_timeframe_fvg(df_4h, direction, sweep_open_ts)
    if fvg_4h:
        return fvg_4h, "4H"
        
    # Priority 2: Fallback to 1-Hour FVG
    fvg_1h = find_timeframe_fvg(df_1h, direction, sweep_open_ts)
    if fvg_1h:
        return fvg_1h, "1H"
        
    return None, None

FVG_EXPIRY_HOURS = 24

def register_pending_sweep(symbol, mtype, sweep):
    global _sweep_cooldown
    direction, sweep_high, sweep_low, sweep_open_ts, sweep_close_ts = sweep
    
    if is_signal_too_old(sweep_close_ts):
        print(f"[STALE SKIP] Suppressing sweep setup on {symbol} (> {MAX_SIGNAL_AGE_HOURS}h old)")
        return
        
    msg_key = f"sweep_waiting_{symbol}_{sweep_close_ts}_{direction}"
    if not check_and_increment_msg_count(msg_key):
        print(f"[REPEAT SKIP] Sweep alert for {symbol} already sent {MAX_MSG_SEND_COUNT} times.")
        return

    target_account = "nifty" if ("^NSE" in symbol or symbol.endswith(".NS")) else "sweep_4h"
    cooldown_key = f"{symbol}_{direction}"
    now_ts = int(time.time() * 1000)
    if now_ts - _sweep_cooldown.get(cooldown_key, 0) < 4 * 3600 * 1000:
        return
    with _lock:
        pending_list = db.get_pending_sweeps()
        if any(p["symbol"] == symbol and p["direction"] == direction and p["sweep_close_ts"] == sweep_close_ts for p in pending_list):
            return
        if accounts[target_account]["daily_trades"] >= ACCOUNT_LIMITS.get(target_account, 3):
            return
        active_list = db.get_active_trades()
        if any(t["symbol"] == symbol and t["account"] == target_account for t in active_list):
            return
        if any(p["symbol"] == symbol and p["status"] in ("waiting_fvg", "waiting_fill") for p in pending_list):
            return
        _sweep_cooldown[cooldown_key] = now_ts
        
        sweep_record = {
            "symbol": symbol, "mtype": mtype, "direction": direction,
            "sweep_high": float(sweep_high), "sweep_low": float(sweep_low),
            "sweep_open_ts": int(sweep_open_ts), "sweep_close_ts": int(sweep_close_ts),
            "created_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
            "fvg_zone": None, "fvg_tf": None, "fvg_found_at": None, "status": "waiting_fvg",
            "target_account": target_account
        }
        db.add_pending_sweep(sweep_record)
    
    dt = datetime.fromtimestamp(sweep_close_ts / 1000, tz=IST)
    time_str = dt.strftime("%d-%b-%Y %H:%M IST")
    age_str, tag = get_signal_age_str(sweep_close_ts)
    name_str = display_name(symbol)
    
    dot = "🟢" if direction == "BULLISH" else "🔴"
    dir_label = "LONG 📈" if direction == "BULLISH" else "SHORT 📉"
    status_icon = "✅" if "FRESH" in tag else "⚠️"
    
    sweep_alert_msg = (
        f"{dot} *SWEEP DETECTED — {name_str} — WAITING FOR FVG* · {status_icon}\n{BR}\n"
        f"🪙 *Asset:* `{name_str}` (`{symbol}`)\n"
        f"📊 *Direction:* {dir_label}\n"
        f"🌐 *Market:* {mtype}\n{BR}\n"
        f"⏳ *Signal Status:* `{tag}` ({age_str})\n"
        f"⏰ *Sweep Time:* `{time_str}`\n{BR}\n"
        f"ℹ️ _✅ FRESH = Closed ≤1h ago | ⚠️ STALE = Closed >1h ago_\n{BR2}"
    )
    send_sweep_to_all(sweep_alert_msg, parse_mode="Markdown")

def manage_pending_sweeps():
    while True:
        try:
            with _lock:
                copy = db.get_pending_sweeps()
            for p in copy:
                sym = p["symbol"]
                sid = p["id"]
                live_df = yf_download(sym, "1d", "1m")
                if live_df is None or live_df.empty:
                    continue
                live = float(live_df["Close"].iloc[-1])
                age_hours = (time.time() * 1000 - p["sweep_close_ts"]) / (3600 * 1000)
                
                if age_hours > FVG_EXPIRY_HOURS and p["status"] != "entered":
                    db.update_pending_sweep_status(sid, "expired")
                    send_to_personal_only(f"⏰ *PENDING SWEEP EXPIRED*\n{BR}\n`{display_name(sym)}` {p['direction']}\n{BR2}", parse_mode="Markdown")
                    continue
                if p["direction"] == "BULLISH" and live <= p["sweep_low"]:
                    db.update_pending_sweep_status(sid, "invalidated")
                    continue
                if p["direction"] == "BEARISH" and live >= p["sweep_high"]:
                    db.update_pending_sweep_status(sid, "invalidated")
                    continue
                if p["fvg_zone"] is None:
                    fvg_zone, tf_label = resolve_hierarchical_fvg(sym, p["direction"], p["sweep_open_ts"])
                    if fvg_zone:
                        fvg_key = f"fvg_confirmed_{sym}_{p['sweep_close_ts']}_{tf_label}"
                        db.update_pending_sweep_status(sid, "waiting_fill", fvg_zone=[float(fvg_zone[0]), float(fvg_zone[1])], fvg_tf=tf_label)
                        
                        if check_and_increment_msg_count(fvg_key):
                            curr = _currency(sym)
                            name_str = display_name(sym)
                            fvg_notify_msg = (
                                f"🎯 *{tf_label} FVG CONFIRMED · {name_str}*\n{BR}\n"
                                f"🪙 *Asset:* `{name_str}` ({p['direction']})\n"
                                f"📊 *Timeframe:* `{tf_label}` Priority Gap\n"
                                f"📍 *Zone:* `{curr}{fvg_zone[0]:,.4f} — {curr}{fvg_zone[1]:,.4f}`\n"
                                f"⏳ *Status:* Waiting for price retest\n{BR2}"
                            )
                            send_sweep_to_all(fvg_notify_msg, parse_mode="Markdown")
                    continue
                zl, zh = p["fvg_zone"]
                if zl <= live <= zh:
                    fvg_entry = {"entry_price": live, "sl": p["sweep_low"] if p["direction"] == "BULLISH" else p["sweep_high"], "sweep_ts": p["sweep_close_ts"], "zone": p["fvg_zone"], "tf": p.get("fvg_tf", "1H")}
                    db.update_pending_sweep_status(sid, "entered")
                    execute(sym, p["mtype"], p.get("target_account", "sweep_4h"), "4H Sweep", p["direction"], live, fvg_entry["sl"], 0, p["sweep_close_ts"], fvg_entry=fvg_entry)
        except Exception as e:
            alert_error("Pending Sweeps Manager", e)
        time.sleep(90)

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_f, ema_s = series.ewm(span=fast, adjust=False).mean(), series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_f - ema_s
    return macd_line, macd_line.ewm(span=signal, adjust=False).mean()

def check_trendpulse(ticker, mtype):
    try:
        df_1h = yf_download(ticker, "10d", "1h")
        if df_1h is None and ticker == "BTC-USD":
            df_1h = fetch_binance_klines("BTCUSDT", "1h", 200)
        if df_1h is None or len(df_1h) < 50:
            return None
        df_4h = df_1h.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        if len(df_4h) < 15:
            return None
        df_4h["EMA50"], df_4h["ATR"] = df_4h["Close"].ewm(span=50, adjust=False).mean(), calc_atr(df_4h, 14)
        htf_close, htf_ema50, htf_atr = float(df_4h["Close"].iloc[-2]), float(df_4h["EMA50"].iloc[-2]), float(df_4h["ATR"].iloc[-2])
        atr_pct = (htf_atr / htf_close) * 100
        if atr_pct < 0.2:
            return None
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
    except Exception:
        pass
    return None

def get_trendpulse_exit(ticker, trade_type):
    try:
        df = yf_download(ticker, "2d", "1h")
        if df is None and ticker == "BTC-USD":
            df = fetch_binance_klines("BTCUSDT", "1h", 100)
        if df is None or len(df) < 30:
            return None
        macd_line, signal_line = calc_macd(df["Close"])
        macd_c, sig_c, macd_p, sig_p = float(macd_line.iloc[-2]), float(signal_line.iloc[-2]), float(macd_line.iloc[-3]), float(signal_line.iloc[-3])
        if trade_type == "LONG" and macd_p >= sig_p and macd_c < sig_c:
            return "EXIT"
        if trade_type == "SHORT" and macd_p <= sig_p and macd_c > sig_c:
            return "EXIT"
    except Exception:
        pass
    return None

def calc_sl_tp(sig, entry, atr):
    return (entry - atr * 1.5, entry + atr * 3.0) if "BULLISH" in sig else (entry + atr * 1.5, entry - atr * 3.0)

def calc_qty(account, entry, sl):
    with _lock:
        dist = abs(entry - sl)
        bal = accounts[account]["balance"] if account in accounts else 100000.0
        return 0.0 if dist == 0 else float((bal * 0.02) / dist)

def format_signal_time(ts_ms):
    try:
        return datetime.fromtimestamp(ts_ms / 1000, tz=IST).strftime("%d-%b-%Y %H:%M IST (+5:30)")
    except Exception:
        return "Unknown"

def _iso_to_ist_dt(date_str: str) -> Optional[datetime]:
    """Parses timestamps (US Eastern, ISO, or UTC) and converts them to IST."""
    if not date_str:
        return None
    try:
        if "T" in str(date_str):
            clean_str = str(date_str).split(".")[0].replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                dt = timezone.utc.localize(dt)
            return dt.astimezone(IST)

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%b %d, %Y %I:%M%p"):
            try:
                dt_naive = datetime.strptime(date_str.strip(), fmt)
                dt_est = EST.localize(dt_naive)
                return dt_est.astimezone(IST)
            except ValueError:
                continue
    except Exception:
        pass
    return None

def _save_news_cache(items):
    try:
        with open(NEWS_CACHE_FILE, "w") as f:
            json.dump({"ts": int(time.time()), "items": items}, f)
    except Exception as e:
        print(f"[NEWS] cache save error: {e}")

def _load_news_cache():
    try:
        if not os.path.exists(NEWS_CACHE_FILE):
            return None
        with open(NEWS_CACHE_FILE) as f:
            data = json.load(f)
        if int(time.time()) - int(data.get("ts", 0)) < NEWS_CACHE_TTL_S:
            return data.get("items", [])
    except Exception as e:
        print(f"[NEWS] cache load error: {e}")
    return None

def fetch_news() -> List[Dict[str, Any]]:
    """Multi-source economic news calendar aggregator with public endpoints and fallbacks."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.forexfactory.com/"
    }

    all_events: List[Dict[str, Any]] = []

    # Source 1: FairEconomy ForexFactory JSON Feed
    ff_urls = [
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json"
    ]
    for url in ff_urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200 and r.text.strip():
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        all_events.append({
                            "title": item.get("title", "Economic Event"),
                            "country": item.get("country", ""),
                            "currency": item.get("country", ""),
                            "date": item.get("date", ""),
                            "impact": item.get("impact", "Low"),
                            "forecast": item.get("forecast", ""),
                            "previous": item.get("previous", "")
                        })
        except Exception as e:
            print(f"[NEWS WARN] FairEconomy failed ({url}): {e}")

    # Source 2: CryptoCompare Public API (public-apis directory fallback)
    if len(all_events) == 0:
        try:
            print("[NEWS] Switching to public-apis CryptoCompare feed fallback...")
            r = requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN", headers=headers, timeout=10)
            if r.status_code == 200:
                news_items = r.json().get("Data", [])
                for n in news_items[:35]:
                    pub_ts = n.get("published_on", 0)
                    dt_ist = datetime.fromtimestamp(pub_ts, tz=timezone.utc).astimezone(IST)
                    all_events.append({
                        "title": n.get("title", "Market Update"),
                        "country": "GLOBAL",
                        "currency": "USD",
                        "date": dt_ist.isoformat(),
                        "impact": "Medium",
                        "forecast": "",
                        "previous": ""
                    })
        except Exception as e:
            print(f"[NEWS WARN] Public-apis CryptoCompare failed: {e}")

    if not all_events:
        print("[NEWS] ⚠️ All economic event endpoints returned empty.")
        return []

    now_ist = datetime.now(IST)
    upcoming = []

    for ev in all_events:
        try:
            raw_date = ev.get("date", "")
            if not raw_date:
                continue
            ev_dt = _iso_to_ist_dt(raw_date)
            if ev_dt and (ev_dt >= now_ist - timedelta(hours=2)):
                ev_copy = dict(ev)
                ev_copy["date"] = ev_dt.isoformat()
                upcoming.append(ev_copy)
        except Exception:
            continue

    upcoming.sort(key=lambda x: x.get("date", ""))
    print(f"[NEWS] ✅ Loaded {len(upcoming)} economic events.")
    return upcoming

def get_cached_news():
    cached = _load_news_cache()
    if cached is not None:
        return cached

    items = fetch_news()
    if items:
        _save_news_cache(items)
    return items

def is_news_pause_active():
    if not _news_pause_enabled:
        return False, ""
    try:
        now = datetime.now(IST)
        for ev in get_cached_news():
            if str(ev.get("impact", "")).upper() not in ("HIGH", "H", "RED"):
                continue
            ev_dt = _iso_to_ist_dt(ev.get("date", ""))
            if ev_dt and abs((ev_dt - now).total_seconds() / 60) <= 15:
                return True, f"High-impact news: {ev.get('title', 'Unknown')} at {ev_dt.strftime('%H:%M IST')}"
    except Exception:
        pass
    return False, ""

def force_close_trade(trade_id, reason="Dashboard"):
    global accounts
    active_trades = db.get_active_trades()
    trade_to_close = None
    for t in active_trades:
        if t.get("id") == trade_id:
            trade_to_close = t
            break
    if not trade_to_close:
        return False, f"Trade {trade_id} not found"
    
    p = get_price(trade_to_close.get("symbol", ""))
    if p is None:
        return False, "Could not fetch price"
    
    live, is_long = float(p), trade_to_close.get("type") == "LONG"
    entry, qty = trade_to_close.get("entry", 0), trade_to_close.get("qty", 0)
    pnl = (live - entry) * qty if is_long else (entry - live) * qty
    acc_name = trade_to_close.get("account", "macro")
    
    with _lock:
        db.update_account_balance(acc_name, pnl)
        if acc_name in accounts:
            accounts[acc_name]["balance"] += pnl
        
        trade_to_close.update({
            "exit_price": live,
            "pnl": float(pnl),
            "result": "FORCE_CLOSE",
            "exit_reason": reason,
            "close_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)"),
            "closed_at": datetime.now(IST).isoformat(),
            "trail_sl": trade_to_close.get("sl", live)
        })
        db.close_active_trade(trade_id, trade_to_close)
        bal = accounts.get(acc_name, {}).get("balance", 0)
    
    msg = msg_trade_closed(trade_to_close, live, pnl, bal, is_long, pnl > 0)
    if trade_to_close.get("strat") and "Sweep" in trade_to_close["strat"]:
        send_sweep_to_all(msg, parse_mode="Markdown")
    else:
        send_to_personal_only(msg, parse_mode="Markdown")
    return True, f"Closed {display_name(trade_to_close.get('symbol'))} at {live:.4f}"

def build_strategy_stats():
    hist = db.get_trade_history(limit=500)
    strategies = {}
    for t in hist:
        strat = t.get("strat", "Unknown")
        if strat not in strategies:
            strategies[strat] = {"wins": 0, "losses": 0, "pnl": 0.0, "trades": 0}
        strategies[strat]["trades"] += 1
        if t.get("result") == "WIN":
            strategies[strat]["wins"] += 1
        elif t.get("result") == "LOSS":
            strategies[strat]["losses"] += 1
        try:
            strategies[strat]["pnl"] += float(t.get("pnl", 0))
        except Exception:
            pass
    for d in strategies.values():
        total = d["wins"] + d["losses"]
        d["win_rate"] = round((d["wins"] / total * 100), 1) if total > 0 else 0
        d["avg_pnl"] = round((d["pnl"] / total), 2) if total > 0 else 0
    return strategies

def execute(symbol, mtype, account, strat, sig_type, price, a1, a2, a3=None, fvg_entry=None):
    paused, pause_reason = is_news_pause_active()
    if paused:
        print(f"[NEWS PAUSE] Skipping {symbol} {sig_type} — {pause_reason}")
        send_to_personal_only(f"⏸️ *NEWS PAUSE*\n{BR}\n`{display_name(symbol)}` {sig_type} skipped\n🛑 {pause_reason}\n{BR2}", parse_mode="Markdown")
        return

    tf_label = fvg_entry.get("tf", "1H") if fvg_entry else ("4H" if (strat and "Sweep" in strat) else "1H")

    if fvg_entry is not None:
        sl, ts = float(fvg_entry["sl"]), fvg_entry["sweep_ts"]
        risk = abs(price - sl)
        if risk <= 0:
            return
        tp = price + risk * 2.0 if "BULLISH" in sig_type else price - risk * 2.0
    elif strat and "Sweep" in strat:
        sl, tp, ts = float(a1), float(a2), a3
    else:
        atr, ts = float(a1), a2
        sl, tp = calc_sl_tp(sig_type, price, atr)

    if is_signal_too_old(ts):
        print(f"[STALE SKIP] Suppressing trade execution for {symbol} (> {MAX_SIGNAL_AGE_HOURS}h old)")
        return

    exec_key = f"exec_{symbol}_{ts}_{sig_type}_{account}"
    if not check_and_increment_msg_count(exec_key):
        print(f"[REPEAT SKIP] Trade execution for {symbol} already fired.")
        return

    with _lock:
        lim = ACCOUNT_LIMITS.get(account, 3)
        if accounts.get(account, {}).get("daily_trades", 0) >= lim:
            return
        active_list = db.get_active_trades()
        if any(t["symbol"] == symbol and t["account"] == account for t in active_list):
            return
        qty = calc_qty(account, price, sl)
        if qty <= 0:
            return
        
        trade = {
            "id": f"{symbol}_{int(time.time())}",
            "symbol": symbol, "market": mtype,
            "account": account, "strat": strat,
            "type": "LONG" if "BULLISH" in sig_type else "SHORT",
            "entry": float(price), "sl": float(sl), "tp": float(tp),
            "qty": float(qty), "trail_sl": float(sl), "ts_trigger": ts,
            "opened_at": datetime.now(IST).isoformat(),
            "time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)")
        }
        db.add_active_trade(trade)
        db.increment_daily_trades(account)
        if account in accounts:
            accounts[account]["daily_trades"] += 1
        
        sig_msg = msg_trade_signal(symbol, mtype, strat, sig_type, tf_label, price, sl, tp, qty, abs(price - sl) * qty, account, ts, fvg_entry.get("zone") if fvg_entry else None)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📈 Chart", callback_data=f"chart_{symbol}"), InlineKeyboardButton(f"🔇 Mute {display_name(symbol)}", callback_data=f"mute_{symbol}")]])
        
        if strat and "Sweep" in strat:
            send_sweep_to_all(sig_msg, parse_mode="Markdown", reply_markup=keyboard)
        else:
            send_to_personal_only(sig_msg, parse_mode="Markdown", reply_markup=keyboard)

def monitor():
    while True:
        active_trades = db.get_active_trades()
        if not active_trades:
            time.sleep(15)
            continue
        for t in active_trades:
            try:
                df = yf_download(t["symbol"], "1d", "1m")
                if df is None or df.empty:
                    continue
                live = float(df["Close"].iloc[-1])
                with _lock:
                    _price_cache[t["symbol"]] = (live, time.time())
                
                long, entry, tp, qty = t["type"] == "LONG", t["entry"], t["tp"], t["qty"]
                account, strat = t["account"], t.get("strat")
                
                pct = ((live - entry) / entry * 100) if long else ((entry - live) / entry * 100)
                
                trail_sl = t["trail_sl"]
                if pct >= 1.0:
                    trail_sl = max(trail_sl, entry) if long else min(trail_sl, entry)
                if pct >= 3.0:
                    trail_sl = max(trail_sl, entry + (live - entry) * 0.3) if long else min(trail_sl, entry - (entry - live) * 0.3)
                if pct >= 5.0:
                    trail_sl = max(trail_sl, entry + (live - entry) * 0.5) if long else min(trail_sl, entry - (entry - live) * 0.5)
                
                if trail_sl != t["trail_sl"]:
                    db.update_trade_trail_sl(t["id"], trail_sl)
                    t["trail_sl"] = trail_sl
                
                hit_tp = (long and live >= tp) or (not long and live <= tp)
                hit_sl = (long and live <= trail_sl) or (not long and live >= trail_sl)
                
                # TrendPulse MACD Exit
                if strat == "TrendPulse 1H" and not (hit_tp or hit_sl):
                    now = time.time()
                    if now - _ut_15m_cache.get(t["symbol"], (None, 0))[1] >= 120:
                        exit_sig = get_trendpulse_exit(t["symbol"], t["type"])
                        _ut_15m_cache[t["symbol"]] = (exit_sig, now)
                        if exit_sig == "EXIT":
                            pnl = (live - entry) * qty * (1 if long else -1)
                            with _lock:
                                db.update_account_balance(account, pnl)
                                if account in accounts:
                                    accounts[account]["balance"] += pnl
                                t.update({
                                    "exit_price": live, "pnl": float(pnl), "result": "MACD EXIT",
                                    "exit_reason": "MACD EXIT",
                                    "close_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)"),
                                    "closed_at": datetime.now(IST).isoformat()
                                })
                                db.close_active_trade(t["id"], t)
                                bal = accounts[account]["balance"]
                            
                            c_msg = msg_trade_closed(t, live, pnl, bal, long, pnl > 0)
                            if strat and "Sweep" in strat:
                                send_sweep_to_all(c_msg, parse_mode="Markdown")
                            else:
                                send_to_personal_only(c_msg, parse_mode="Markdown")
                            continue
                
                if not (hit_tp or hit_sl):
                    continue

                pnl = (tp - entry) * qty * (1 if long else -1) if hit_tp else (trail_sl - entry) * qty * (1 if long else -1)
                
                with _lock:
                    db.update_account_balance(account, pnl)
                    if account in accounts:
                        accounts[account]["balance"] += pnl
                    t.update({
                        "exit_price": live, "pnl": float(pnl), "result": "WIN" if hit_tp else "LOSS",
                        "exit_reason": "TP" if hit_tp else "SL",
                        "close_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)"),
                        "closed_at": datetime.now(IST).isoformat()
                    })
                    db.close_active_trade(t["id"], t)
                    bal = accounts[account]["balance"]
                
                c_msg = msg_trade_closed(t, live, pnl, bal, long, hit_tp)
                if strat and "Sweep" in strat:
                    send_sweep_to_all(c_msg, parse_mode="Markdown")
                else:
                    send_to_personal_only(c_msg, parse_mode="Markdown")
            except Exception as e:
                alert_error(f"Monitor: {t.get('symbol','?')}", e)
        time.sleep(20)

MONITORED = [("BTC-USD", "Crypto"), ("GC=F", "Gold"), ("EURUSD=X", "Forex"), ("GBPUSD=X", "Forex"), ("USDJPY=X", "Forex"), ("^NSEI", "NIFTY 50"), ("^NSEBANK", "BANK NIFTY")] + [(sym, "NSE") for sym, _ in NIFTY_STOCKS]

def scanner():
    while True:
        try:
            for symbol, mtype in MONITORED:
                with _lock:
                    if symbol in muted_assets or not is_market_open(symbol):
                        continue
                is_nse = "^NSE" in symbol or symbol.endswith(".NS")
                
                if not is_nse:
                    tp = check_trendpulse(symbol, mtype)
                    if tp:
                        execute(symbol, mtype, "ny_session" if is_ny_session() else "macro", "TrendPulse 1H", tp[0], tp[1], tp[2], tp[3])
                    
                    sweep = check_sweep(symbol)
                    if sweep:
                        direction = sweep[0]
                        if direction == "NEUTRAL":
                            notify_neutral_sweep(symbol, mtype, sweep[1], sweep[2], sweep[3])
                        else:
                            register_pending_sweep(symbol, mtype, sweep)

                elif is_nifty_open():
                    sweep = check_sweep(symbol)
                    if sweep:
                        direction = sweep[0]
                        if direction == "NEUTRAL":
                            notify_neutral_sweep(symbol, mtype, sweep[1], sweep[2], sweep[3])
                        else:
                            register_pending_sweep(symbol, mtype, sweep)

                time.sleep(2)
                gc.collect()
        except Exception as e:
            alert_error("Scanner", e)
            time.sleep(300)

def daily_reset():
    today = datetime.now(IST).strftime("%Y-%m-%d")
    last = today
    while True:
        try:
            today = datetime.now(IST).strftime("%Y-%m-%d")
            if last != today:
                with _lock:
                    init_accounts()
                    hist = db.get_trade_history(limit=100)
                    day_pnl = sum(float(t["pnl"]) for t in hist if t.get("close_time", "").startswith(last))
                    send_to_personal_only(msg_midnight_reset(day_pnl, accounts["macro"]["balance"], accounts["nifty"]["balance"], accounts["ny_session"]["balance"], accounts["sweep_4h"]["balance"]), parse_mode="Markdown")
                last = today
                gc.collect()
        except Exception as e:
            alert_error("Daily Reset", e)
        time.sleep(60)

def weekly_digest_loop():
    while True:
        try:
            now = datetime.now(IST)
            if now.weekday() == 6 and now.hour >= 21:
                week_label = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
                state_file = "/tmp/workspace/weekly_digest_state.json"
                state = {}
                if os.path.exists(state_file):
                    try:
                        with open(state_file) as f: state = json.load(f)
                    except: pass
                if state.get("last_sent_week") != week_label:
                    send_to_personal_only(build_weekly_digest_text(7), parse_mode="Markdown")
                    state["last_sent_week"] = week_label
                    with open(state_file, "w") as f: json.dump(state, f)
        except Exception as e:
            alert_error("Weekly Digest", e)
        time.sleep(600)

def build_weekly_digest_text(days=7):
    hist = db.get_trade_history(limit=500)
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d")
    week_trades = [t for t in hist if str(t.get("closed_at", ""))[:10] >= cutoff]
    week_pnl, wins, losses, per_symbol = 0.0, 0, 0, {}
    for t in week_trades:
        try:
            pnl = float(t.get("pnl", 0))
        except Exception:
            pnl = 0.0
        week_pnl += pnl
        if t.get("result") == "WIN": wins += 1
        elif t.get("result") == "LOSS": losses += 1
        per_symbol[t.get("symbol", "?")] = per_symbol.get(t.get("symbol", "?"), 0.0) + pnl
    best_sym, best_pnl = max(per_symbol.items(), key=lambda kv: kv[1]) if per_symbol else (None, 0)
    worst_sym, worst_pnl = min(per_symbol.items(), key=lambda kv: kv[1]) if per_symbol else (None, 0)
    total_equity = sum(float(accounts.get(a, {}).get("balance", 0)) for a in ["macro", "nifty", "ny_session", "sweep_4h"])
    return msg_weekly_digest(week_pnl, wins, losses, best_sym, best_pnl, worst_sym, worst_pnl, total_equity)

# =====================================================================
# RESTORED TELEGRAM COMMAND CENTER HANDLERS
# =====================================================================

@bot.message_handler(commands=["start", "menu"])
def cmd_start(m):
    safe_send(m.chat.id, msg_guide(), parse_mode="Markdown")

@bot.message_handler(commands=["check", "scan"])
def cmd_check(m):
    safe_send(m.chat.id, "🔍 *Running immediate market scan across all pairs...*", parse_mode="Markdown")
    def run_scan():
        found = 0
        for symbol, mtype in MONITORED:
            with _lock:
                if symbol in muted_assets or not is_market_open(symbol):
                    continue
            is_nse = "^NSE" in symbol or symbol.endswith(".NS")
            if not is_nse:
                tp = check_trendpulse(symbol, mtype)
                if tp:
                    found += 1
                    execute(symbol, mtype, "ny_session" if is_ny_session() else "macro", "TrendPulse 1H", tp[0], tp[1], tp[2], tp[3])
                sweep = check_sweep(symbol)
                if sweep:
                    direction = sweep[0]
                    if direction == "NEUTRAL":
                        notify_neutral_sweep(symbol, mtype, sweep[1], sweep[2], sweep[3])
                    else:
                        found += 1
                        register_pending_sweep(symbol, mtype, sweep)
            elif is_nifty_open():
                sweep = check_sweep(symbol)
                if sweep:
                    direction = sweep[0]
                    if direction == "NEUTRAL":
                        notify_neutral_sweep(symbol, mtype, sweep[1], sweep[2], sweep[3])
                    else:
                        found += 1
                        register_pending_sweep(symbol, mtype, sweep)
        safe_send(m.chat.id, f"✅ *Scan Complete.* Found `{found}` active setups/signals.", parse_mode="Markdown")
    threading.Thread(target=run_scan, daemon=True).start()

@bot.message_handler(commands=["test"])
def cmd_test(m):
    safe_send(m.chat.id, "🧪 *Testing live data feeds...*", parse_mode="Markdown")
    test_symbols = ["BTC-USD", "GC=F", "EURUSD=X", "^NSEI", "RELIANCE.NS"]
    results = []
    for s in test_symbols:
        start_t = time.time()
        p = get_price(s)
        lat = round((time.time() - start_t) * 1000)
        status = f"✅ `{display_name(s)}` (`{s}`): `{_currency(s)}{p:,.2f}` ({lat}ms)" if p else f"❌ `{display_name(s)}` (`{s}`): Failed"
        results.append(status)
    safe_send(m.chat.id, "📡 *Data Feed Status:*\n" + BR + "\n" + "\n".join(results) + "\n" + BR2, parse_mode="Markdown")

@bot.message_handler(commands=["summary"])
def cmd_summary(m):
    with _lock:
        open_count = len(db.get_active_trades())
        pending_count = len(db.get_pending_sweeps())
        total_pnl = sum(float(t.get("pnl", 0)) for t in db.get_active_trades())
    
    msg = (
        f"📊 *SYSTEM SUMMARY*\n{BR}\n"
        f"🔥 *Active Trades:* `{open_count}`\n"
        f"⏳ *Pending Sweeps:* `{pending_count}`\n"
        f"💰 *Floating P/L:* `{'₹' if total_pnl>=0 else '-₹'}{abs(total_pnl):,.2f}`\n"
        f"🌐 *NY Session:* `{'ACTIVE ✅' if is_ny_session() else 'INACTIVE 🛑'}`\n"
        f"🇮🇳 *NSE Session:* `{'OPEN ✅' if is_nifty_open() else 'CLOSED 🛑'}`\n"
        f"{BR2}"
    )
    safe_send(m.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=["balance", "accounts"])
def cmd_balance(m):
    lines = []
    total_eq = 0.0
    with _lock:
        for acc_name, data in accounts.items():
            bal = float(data.get("balance", 0))
            trades = data.get("daily_trades", 0)
            lim = ACCOUNT_LIMITS.get(acc_name, 3)
            total_eq += bal
            lines.append(f"├ 💼 *{acc_name.upper()}:* `₹{bal:,.2f}` (`{trades}/{lim}` trades)")
    
    msg = (
        f"🏦 *ACCOUNT BALANCES*\n{BR}\n"
        + "\n".join(lines) + "\n" +
        f"{BR}\n💰 *Total Virtual Equity:* `₹{total_eq:,.2f}`\n{BR2}"
    )
    safe_send(m.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=["pending"])
def cmd_pending(m):
    with _lock:
        pending_sweeps = db.get_pending_sweeps()
        if not pending_sweeps:
            safe_send(m.chat.id, "⏳ *No pending liquidity sweeps right now.*", parse_mode="Markdown")
            return
        items = []
        for p in pending_sweeps:
            age_str, tag = get_signal_age_str(p.get("sweep_close_ts", 0))
            tf_tag = f"({p.get('fvg_tf', '1H')})" if p.get("fvg_tf") else ""
            zone = f"`{p['fvg_zone'][0]:,.2f} - {p['fvg_zone'][1]:,.2f}` {tf_tag}" if p.get("fvg_zone") else "Waiting for FVG"
            items.append(f"• `{display_name(p['symbol'])}` ({p['direction']})\n  └ Status: `{p['status']}` | Zone: {zone} | [{tag}] `{age_str}`")
    
    safe_send(m.chat.id, "⏳ *PENDING 4H SWEEPS:*\n" + BR + "\n" + "\n\n".join(items) + "\n" + BR2, parse_mode="Markdown")

@bot.message_handler(commands=["risk"])
def cmd_risk(m):
    with _lock:
        total_risk = 0.0
        for t in db.get_active_trades():
            entry, sl, qty = float(t.get("entry", 0)), float(t.get("sl", 0)), float(t.get("qty", 0))
            total_risk += abs(entry - sl) * qty
    
    total_eq = sum(float(accounts[a].get("balance", 0)) for a in accounts if isinstance(accounts[a], dict))
    risk_pct = (total_risk / total_eq * 100) if total_eq > 0 else 0.0
    
    msg = (
        f"⚠️ *PORTFOLIO RISK & EXPOSURE*\n{BR}\n"
        f"💸 *Total Open Risk (1R):* `₹{total_risk:,.2f}`\n"
        f"📊 *Portfolio Risk Exposure:* `{risk_pct:.2f}%`\n"
        f"💼 *Total Capital:* `₹{total_eq:,.2f}`\n"
        f"{BR2}"
    )
    safe_send(m.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    strategies = build_strategy_stats()
    if not strategies:
        safe_send(m.chat.id, "📊 *No closed trade statistics recorded yet.*", parse_mode="Markdown")
        return
    
    lines = []
    for sname, sdata in strategies.items():
        wr = sdata.get("win_rate", 0)
        pnl = sdata.get("pnl", 0)
        trades = sdata.get("trades", 0)
        lines.append(f"🎯 *{sname}:*\n  ├ Trades: `{trades}` | WR: `{wr}%`\n  └ P/L: `{'+' if pnl>=0 else ''}₹{pnl:,.2f}`")
        
    safe_send(m.chat.id, "📈 *STRATEGY PERFORMANCE REPORT:*\n" + BR + "\n" + "\n".join(lines) + "\n" + BR2, parse_mode="Markdown")

@bot.message_handler(commands=["weekly"])
def cmd_weekly(m):
    digest_text = build_weekly_digest_text(7)
    safe_send(m.chat.id, digest_text, parse_mode="Markdown")

@bot.message_handler(commands=["backtest"])
def cmd_backtest(m):
    if not _backtest_available:
        safe_send(m.chat.id, "⚠️ Backtest engine not available.", parse_mode="Markdown")
        return
    parts = m.text.split()
    if len(parts) < 2:
        safe_send(m.chat.id, "📊 *Backtest Usage*\n`/backtest <symbol> [strategy] [days]`", parse_mode="Markdown")
        return
    symbol, strategy = parts[1].upper(), parts[2].lower() if len(parts) > 2 else "trendpulse"
    try:
        days = min(int(parts[3]) if len(parts) > 3 else 30, 365)
    except ValueError:
        safe_send(m.chat.id, "❌ Days must be a number.", parse_mode="Markdown")
        return
    if strategy not in ("trendpulse", "sweep"):
        safe_send(m.chat.id, "❌ Strategy must be trendpulse or sweep", parse_mode="Markdown")
        return
    safe_send(m.chat.id, f"📊 *Backtesting {strategy.upper()} on {display_name(symbol)}...*", parse_mode="Markdown")
    def run():
        try:
            engine = BacktestEngine()
            res = engine.backtest_trendpulse(symbol, days) if strategy == "trendpulse" else engine.backtest_sweep(symbol, days)
            if "error" in res:
                safe_send(m.chat.id, f"❌ {res['error']}", parse_mode="Markdown")
                return
            
            chart_path = "/tmp/workspace/backtest_chart.png"
            caption = (
                f"📊 *BACKTEST RESULTS*\n"
                f"🪙 *Symbol:* `{display_name(symbol)}` (`{symbol}`)\n"
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
        except Exception as e:
            safe_send(m.chat.id, f"❌ {str(e)[:200]}", parse_mode="Markdown")
    threading.Thread(target=run, daemon=True).start()

@bot.message_handler(commands=["newspause"])
def cmd_newspause(m):
    global _news_pause_enabled
    parts = m.text.split()
    if len(parts) > 1 and parts[1].lower() in ("off", "0"):
        _news_pause_enabled = False
        safe_send(m.chat.id, "⏸️ News Pause DISABLED", parse_mode="Markdown")
    elif len(parts) > 1 and parts[1].lower() in ("on", "1"):
        _news_pause_enabled = True
        safe_send(m.chat.id, "▶️ News Pause ENABLED", parse_mode="Markdown")
    else:
        safe_send(m.chat.id, f"News Pause: {'ON ✅' if _news_pause_enabled else 'OFF 🛑'}", parse_mode="Markdown")

@bot.message_handler(commands=["refreshnews"])
def cmd_refreshnews(m):
    global NEWS_CACHE
    NEWS_CACHE["last_fetch"] = 0
    try:
        if os.path.exists(NEWS_CACHE_FILE):
            os.remove(NEWS_CACHE_FILE)
    except Exception:
        pass
    raw = fetch_news()
    if raw:
        _save_news_cache(raw)
        preview = "\n".join([f"• `{ev.get('title', 'Unknown')}` ({ev.get('impact', 'Low')})" for ev in raw[:5]])
        safe_send(m.chat.id, f"📰 *News Refreshed*\n{BR}\nFound `{len(raw)}` upcoming events\n\n{preview}\n\n{'...' if len(raw) > 5 else ''}", parse_mode="Markdown")
    else:
        safe_send(m.chat.id, "⚠️ *News API Unavailable* — Could not fetch economic calendar. Retrying automatically in background.", parse_mode="Markdown")

def send_chart(symbol, chat_id):
    with _chart_lock:
        try:
            df = yf_download(symbol, "5d", "1h")
            if df is None or df.empty:
                safe_send(chat_id, f"⚠️ No chart data available for `{display_name(symbol)}`", parse_mode="Markdown")
                return
            close = df["Close"]
            if hasattr(close, "columns"):
                close = close.iloc[:, 0]
            close = close.dropna()
            if close.empty:
                safe_send(chat_id, f"⚠️ No chart data available for `{display_name(symbol)}`", parse_mode="Markdown")
                return
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(close.index, close.values, color="#7c6cff", linewidth=1.4)
            ax.set_title(f"{display_name(symbol)} — 5D / 1H", fontsize=12)
            ax.grid(alpha=0.2)
            ax.tick_params(labelsize=8)
            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=110)
            plt.close(fig)
            buf.seek(0)
            bot.send_photo(chat_id, buf, caption=f"📈 `{display_name(symbol)}` — last 5 days (1H)", parse_mode="Markdown")
        except Exception as e:
            print(f"[ERR] send_chart {symbol}: {e}")
            safe_send(chat_id, f"⚠️ Failed to generate chart for `{display_name(symbol)}`", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def on_callback(call):
    try:
        if call.data.startswith("mute_"):
            sym = call.data.split("_", 1)[1]
            with _lock:
                muted_assets.add(sym)
            bot.answer_callback_query(call.id, text=f"🔇 {display_name(sym)} muted")
        elif call.data.startswith("chart_"):
            bot.answer_callback_query(call.id, text="📈 Generating chart...")
            threading.Thread(target=send_chart, args=(call.data.split("_", 1)[1], call.message.chat.id), daemon=True).start()
        else:
            bot.answer_callback_query(call.id)
    except Exception:
        pass

def warm_news_cache():
    time.sleep(30)
    try:
        print("[NEWS] Running initial news cache warm-up...")
        get_cached_news()
    except Exception as e:
        print(f"[NEWS] Warm-up failed: {e}")

if __name__ == "__main__":
    print("[INIT] Starting bot...")
    init_accounts()
    
    start_time_str = datetime.now(IST).strftime("%d-%b-%Y %H:%M IST")
    start_msg = (
        f"✅ *BOT STARTED*\n"
        f"{BR}\n"
        f"🕒 *Started At:* `{start_time_str}`\n"
        f"⚠️ *FILTER ACTIVE:* Stale signals older than {MAX_SIGNAL_AGE_HOURS}h or sent >={MAX_MSG_SEND_COUNT}x are suppressed.\n"
        f"{BR2}"
    )
    send_to_personal_only(start_msg, parse_mode="Markdown")
    
    threading.Thread(target=run_web, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=scanner, daemon=True).start()
    threading.Thread(target=manage_pending_sweeps, daemon=True).start()
    threading.Thread(target=daily_reset, daemon=True).start()
    threading.Thread(target=weekly_digest_loop, daemon=True).start()
    threading.Thread(target=warm_news_cache, daemon=True).start()
    print(f"[INIT] Bot running with clean names, {MAX_SIGNAL_AGE_HOURS}h stale limit, and {MAX_MSG_SEND_COUNT}x repetition cap.")
    while True:
        time.sleep(3600)
