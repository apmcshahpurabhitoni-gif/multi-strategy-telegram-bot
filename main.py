import os
import json
import time
import csv
import threading
import gc
from datetime import datetime, timedelta
from io import BytesIO
from collections import OrderedDict

import requests
import numpy as np
import pandas as pd
import yfinance as yf
import pytz
import telebot
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask, jsonify, send_file

# ============================================================
#  CONFIG
# ============================================================
TOKEN          = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID        = os.environ.get("TELEGRAM_CHAT_ID")
ATR_MULT_SL    = 1.5
ATR_MULT_TP    = 3.0
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set!")

DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)

ACCOUNTS_FILE      = os.path.join(DATA_DIR, "accounts.json")
ACTIVE_TRADES_FILE = os.path.join(DATA_DIR, "active_trades.json")
HISTORY_FILE       = os.path.join(DATA_DIR, "trade_history.json")
MUTE_FILE          = os.path.join(DATA_DIR, "muted_assets.json")
TRADE_LOG_CSV      = os.path.join(DATA_DIR, "trade_log.csv")
SENT_SIGNALS_FILE  = os.path.join(DATA_DIR, "sent_signals.json")

ACCOUNT_LIMITS = {
    "macro": 20, "nifty": 3, "ny_session": 3, "sweep_4h": 3,
}

MONITORED = [
    ("BTC-USD",  "Crypto"), ("GC=F", "Commodity"),
    ("^NSEI", "Index"), ("^NSEBANK", "Index"),
    ("EURUSD=X", "Forex"), ("GBPUSD=X", "Forex"), ("USDJPY=X", "Forex"),
]

MAX_HISTORY       = 200
MAX_SENT_SIGNALS  = 500
MAX_PRICE_CACHE   = 64

# ============================================================
#  GLOBALS & LOCKS
# ============================================================
accounts      = {}
active_trades = []
muted_assets  = set()
sent_signals  = {}

_lock        = threading.RLock()
_price_cache = OrderedDict()
_price_ttl   = 300
_last_scan_time = 0

_yf_lock               = threading.Lock()
_yf_last_call          = 0.0
_yf_min_gap            = 5.0
_yf_rate_limited_until = 0.0
_yf_backoff            = 60
_YF_BACKOFF_MAX        = 600

IST = pytz.timezone("Asia/Kolkata")

_YF_SESSION = requests.Session()
_YF_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
})

PORT = int(os.environ.get("PORT", 10000))

# ============================================================
#  HELPERS
# ============================================================
def is_market_open(symbol):
    now = datetime.now(IST)
    w, total_min = now.weekday(), now.hour * 60 + now.minute
    if symbol in ("BTC-USD", "GC=F"): return True
    if symbol in ("EURUSD=X", "GBPUSD=X", "USDJPY=X"): return w < 5
    if symbol in ("^NSEI", "^NSEBANK"): return w < 5 and 555 <= total_min <= 930
    return False

def is_ny_session():
    now = datetime.now(IST)
    w = now.weekday()
    total_min = now.hour * 60 + now.minute
    return w < 5 and (total_min >= 1200 or total_min <= 150)

def trim_dataframe(df):
    try: del df
    except Exception: pass

# ============================================================
#  MESSAGE TEMPLATES
# ============================================================
BR  = "━━━━━━━━━━━━━━━━━━━━━━"
BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
THIN = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

def progress_bar(current, total, width=10):
    if total <= 0: return "░" * width
    filled = max(0, min(width, int(round(width * current / total))))
    return "▓" * filled + "░" * (width - filled)

def pnl_emoji(pnl):
    if pnl > 0: return "🟢"
    if pnl < 0: return "🔴"
    return "⚪"

def pnl_str(pnl):
    if pnl >= 0: return f"+₹{pnl:,.2f}"
    return f"-₹{abs(pnl):,.2f}"

def pct_str(pct):
    return f"+{pct:.2f}%" if pct >= 0 else f"{pct:.2f}%"

def dir_emoji(t): return "📈" if t == "LONG" else "📉"
def dir_word(t): return "LONG  📈" if t == "LONG" else "SHORT 📉"
def now_short(): return datetime.now(IST).strftime("%H:%M:%S IST")

def fmt_rr(price, sl, tp):
    risk = abs(price - sl)
    reward = abs(tp - price)
    return f"1:{reward / risk:.2f}" if risk > 0 else "—"

def fmt_pct_dist(price, target, is_long):
    if price <= 0: return "—"
    dist = ((target - price) / price * 100) if is_long else ((price - target) / price * 100)
    return f"{dist:+.2f}%"

def build_trade_block(t, live):
    is_long, entry = t["type"] == "LONG", float(t["entry"])
    sl, tp, qty = float(t["trail_sl"]), float(t["tp"]), float(t["qty"])
    if live is None:
        return f"⏳ *`{t['symbol']}`*  ·  {dir_word(t['type'])}  ·  `{t['account'].upper()}`\n└─ Fetching Price..."
    live_f = float(live)
    pnl = (live_f - entry) * qty if is_long else (entry - live_f) * qty
    pnl_pct = ((live_f - entry) / entry * 100) if is_long else ((entry - live_f) / entry * 100)
    return (
        f"{pnl_emoji(pnl)} *`{t['symbol']}`*  ·  {dir_word(t['type'])}  ·  `{t['account'].upper()}`\n"
        f"┌─ 🎯 {t.get('strat', '—')}\n"
        f"│ 📊 Live: `${live_f:,.4f}` ({pct_str(pnl_pct)})\n"
        f"│ 🛡️ SL: `${sl:,.4f}` ({fmt_pct_dist(entry, sl, is_long)})  ·  🎯 TP: `${tp:,.4f}` ({fmt_pct_dist(entry, tp, is_long)})\n"
        f"│ 💹 U.PnL: `{pnl_str(pnl)}`\n└─"
    )

def msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, actual_sl, actual_tp, qty, risk_amt, account):
    is_long = "BULLISH" in sig_type
    arrow = "🟢🟢🟢" if is_long else "🔴🔴🔴"
    label = "🚀 STRONG BULLISH" if is_long else "💥 STRONG BEARISH"
    dir_ = "LONG 📈" if is_long else "SHORT 📉"
    rr = fmt_rr(price, actual_sl, actual_tp)
    sl_dist = abs(price - actual_sl) / price * 100
    tp_dist = abs(actual_tp - price) / price * 100
    sl_pct = fmt_pct_dist(price, actual_sl, is_long)
    tp_pct = fmt_pct_dist(price, actual_tp, is_long)
    return (
        f"{arrow}  *NEW SIGNAL — {label}*  {arrow}\n{BR2}\n"
        f"🪙 `{symbol}` · {mtype}\n📊 *{strat}*  ·  {dir_}  ·  ⏱ `{tf}`\n{BR}\n"
        f"💼 *PAPER TRADE EXECUTED*\n{BR}\n"
        f"🏢 *Account:*   `{account.upper()}`\n📍 *Entry:*     `${price:,.4f}`\n"
        f"🛑 *Stop Loss:* `${actual_sl:,.4f}`  {'🔻' if is_long else '🔺'} `{sl_pct}`\n"
        f"🎯 *Take Profit:* `${actual_tp:,.4f}`  🎯 `{tp_pct}`\n"
        f"📦 *Quantity:*  `{qty:.4f}`\n💸 *Risk:*      `₹{risk_amt:,.2f}`\n{BR}\n"
        f"📐 *R:R Ratio:* `{rr}`  ·  🛡️ *SL Dist:* `{sl_dist:.2f}%`  ·  🎯 *TP Dist:* `{tp_dist:.2f}%`\n{BR}\n"
        f"🕐 `{now_short()}`\n{BR2}"
    )

def msg_trade_closed(trade, live, pnl, bal, is_long, hit_tp):
    icon = "🟢" if hit_tp else "🔴"
    result = "🎉 WIN ✅" if hit_tp else "💀 LOSS ❌"
    entry, sl, tp = float(trade["entry"]), float(trade["trail_sl"]), float(trade["tp"])
    move_pct = abs(live - entry) / entry * 100 if entry else 0
    arrow = "📈" if ((live > entry) if is_long else (live < entry)) else "📉"
    duration = "—"
    if trade.get("open_time"):
        try:
            opened = datetime.strptime(trade["open_time"], "%Y-%m-%d %H:%M")
            secs = int((datetime.now(IST).replace(tzinfo=None) - opened).total_seconds())
            h, rem = divmod(secs, 3600)
            m, s = divmod(rem, 60)
            duration = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
        except Exception: pass
    return (
        f"{icon} *TRADE CLOSED*  {result}\n{BR2}\n"
        f"🪙 `{trade['symbol']}`  ·  {dir_word(trade['type'])}  ·  `{trade['account'].upper()}`\n"
        f"🎯 *Strategy:* {trade['strat']}\n{BR}\n"
        f"📍 *Entry:* `${entry:,.4f}`  ·  {arrow} *Exit:* `${live:,.4f}`\n"
        f"🛡️ *Trail SL:* `${sl:,.4f}`  ·  🎯 *TP Target:* `${tp:,.4f}`\n"
        f"📏 *Move:* `{move_pct:.2f}%`  ·  ⏱ *Duration:* `{duration}`\n{BR}\n"
        f"{icon} *P/L:* `{pnl_str(pnl)}`  ·  🏦 *Balance:* `₹{bal:,.2f}`\n{BR}\n"
        f"🕐 `{now_short()}`\n{BR2}"
    )

def msg_active_trades(trades_list, total_pnl):
    if not trades_list: return "📭 *NO ACTIVE TRADES*\n" + BR + "\nUse `/check` to scan for setups.\n" + BR2
    return (f"📊 *LIVE POSITIONS*  ·  {len(trades_list)} OPEN\n{BR2}\n" +
            "\n".join(trades_list) + f"\n{BR}\n{pnl_emoji(total_pnl)} *Total Unrealized:* `{pnl_str(total_pnl)}`\n{BR2}")

def msg_balance(macro_bal, nifty_bal, ny_bal, sweep_bal, macro_d, nifty_d, ny_d, sweep_d,
                macro_l, nifty_l, ny_l, sweep_l, ny_active, u_pnl):
    def line(emoji, name, bal, used, limit, upnl, status_icon="🟢", status_text="READY"):
        return (f"{emoji} *{name}*  {status_icon} `{status_text}`\n┌─\n"
                f"│ 💰 `₹{bal:,.2f}`  ·  📊 `{used}/{limit}` {progress_bar(used, limit)}\n"
                f"│ 💹 U.PnL: `{pnl_str(upnl)}` {pnl_emoji(upnl)}\n└─")
    total_upnl = u_pnl["macro"] + u_pnl["nifty"] + u_pnl["ny_session"] + u_pnl["sweep_4h"]
    return (
        f"💰 *ACCOUNT OVERVIEW*\n{BR2}\n"
        f"{line('🏢', 'MACRO', macro_bal, macro_d, macro_l, u_pnl['macro'])}\n\n"
        f"{line('🇮🇳', 'NIFTY', nifty_bal, nifty_d, nifty_l, u_pnl['nifty'])}\n\n"
        f"{line('🗽', 'NY SESSION', ny_bal, ny_d, ny_l, u_pnl['ny_session'], '🟢' if ny_active else '🔴', 'ACTIVE' if ny_active else 'CLOSED')}\n\n"
        f"{line('🌊', 'SWEEP 4H', sweep_bal, sweep_d, sweep_l, u_pnl['sweep_4h'])}\n{BR}\n"
        f"💼 *TOTAL EQUITY:* `₹{macro_bal + nifty_bal + ny_bal + sweep_bal:,.2f}`  ·  💹 *U.PnL:* `{pnl_str(total_upnl)}`\n{BR}\n"
        f"🕐 `{now_short()}`\n{BR2}"
    )

def msg_stats(mw, ml, mp, mwr, nw, nl, np_, nwr, nyw, nyl, nyp, nywr, sw, sl, sp, swr):
    def block(emoji, name, w, l, p, wr):
        return (f"{emoji} *{name}*\n┌─\n"
                f"│ 🏆 `{w}W`  💀 `{l}L`  📈 WR: `{wr:.1f}%`\n"
                f"│ 💰 Net P/L: `{pnl_str(p)}` {pnl_emoji(p)}\n└─")
    total_w, total_l = mw+nw+nyw+sw, ml+nl+nyl+sl
    total_p = mp+np_+nyp+sp
    total_wr = (total_w / (total_w + total_l) * 100) if (total_w + total_l) else 0
    return (
        f"📊 *PERFORMANCE REPORT*\n{BR2}\n"
        f"{block('🏢', 'MACRO', mw, ml, mp, mwr)}\n\n{block('🇮🇳', 'NIFTY', nw, nl, np_, nwr)}\n\n"
        f"{block('🗽', 'NY SESSION', nyw, nyl, nyp, nywr)}\n\n{block('🌊', 'SWEEP 4H', sw, sl, sp, swr)}\n{BR}\n"
        f"💼 *TOTAL:* 🏆 `{total_w}W` 💀 `{total_l}L`  ·  📈 WR: `{total_wr:.1f}%`  ·  💰 `{pnl_str(total_p)}`\n{BR2}"
    )

def msg_scanning():
    return f"🔍 *SCANNING MARKETS…*\n{BR}\n⏳ Analyzing assets…\n⏱ Please wait ~30 seconds…\n{BR2}"

def msg_scan_results(signals, neutral):
    header = f"🔥 *{len(signals)} SIGNALS FOUND*" if signals else "⏳ *NO ACTIVE SETUPS*"
    body = ""
    if signals: body = "🎯 *ACTIVE SETUPS*\n" + BR + "\n" + "\n".join(signals) + "\n"
    if neutral: body += f"⚪ *NEUTRAL ({len(neutral)})*\n" + "\n".join(neutral) + "\n"
    return f"{header}\n{BR}\n{body}{BR}\n🕐 `{now_short()}`\n{BR2}"

def msg_summary(lines):
    return f"📋 *LIVE MARKET SUMMARY*\n{BR2}\n" + "\n".join(lines) + f"\n{BR}\n🕐 `{now_short()}`\n{BR2}"

def msg_guide():
    return (
        f"🤖 *TRADING BOT — COMMAND CENTER*\n{BR2}\n"
        f"📘 *COMMANDS*\n{BR}\n┌─\n"
        f"│ `/check`        Scan markets now\n│ `/summary`      Live prices\n"
        f"│ `/active`       Open positions\n│ `/close SYM`    Close a trade\n"
        f"│ `/stats`        Performance\n│ `/balance`      Balances + U.PnL\n"
        f"│ `/clear`        Reset all\n│ `/indi1` `/indi2` Diagnostics\n└─\n{BR2}"
    )

def msg_error(context, error):
    return f"⚠️ *ERROR — {context}*\n{BR}\n❌ `{str(error)[:150]}`\n{BR2}"

def msg_cleared():
    return f"🗑️ *ACCOUNTS RESET*\n{BR2}\n✅ All balances → `₹1,00,000`\n✅ History & Trades Wiped\n{BR2}"

def msg_muted(sym):
    return f"🔇 *ASSET MUTED*\n{BR}\n🪙 `{sym}` will not trigger signals.\n{BR2}"

def msg_unmuted(sym):
    return f"🔊 *ASSET UNMUTED*\n{BR}\n🪙 `{sym}` is back in the scanner.\n{BR2}"

def msg_indi_diagnosing(n):
    return f"{'🔵' if n==1 else '🟣'} *DIAGNOSING STRATEGY {n}*\n{BR}\n⏳ Checking {len(MONITORED)} assets…\n{BR2}"

def msg_indi_no_signals(n):
    return f"{'🔵' if n==1 else '🟣'} *STRATEGY {n} — NO SIGNALS*\n{BR}\n⚪ No assets met conditions.\n{BR2}"

def msg_export_ready(count):
    return f"📥 *EXPORT READY*\n{BR}\n📝 `{count}` trades logged.\n{BR2}"

def msg_chart_failed():
    return f"❌ *CHART FAILED*\n{BR}\n⚠️ Could not fetch data.\n{BR2}"

# ============================================================
#  JSON / IO
# ============================================================
def load_json(filepath, default):
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: pass
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)
    except Exception: pass

def safe_send_message(chat_id, text, **kwargs):
    try: bot.send_message(chat_id, text, **kwargs)
    except Exception:
        try:
            clean = text.replace("*", "").replace("`", "'").replace("▓", "■").replace("░", "□")
            bot.send_message(chat_id, "⚠️ Formatting error:\n" + clean, parse_mode=None)
        except Exception: pass

def _log_trade_to_csv(trade_dict):
    try:
        file_exists = os.path.isfile(TRADE_LOG_CSV)
        with open(TRADE_LOG_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["close_time", "symbol", "account", "strategy", "type", "entry", "exit_price", "sl", "tp", "qty", "pnl", "result"])
            if not file_exists: writer.writeheader()
            writer.writerow({k: trade_dict.get(k, "") for k in writer.fieldnames})
    except Exception: pass

def init_accounts():
    global accounts
    defaults = {"macro": {"balance": 100000.0, "daily_trades": 0}, "nifty": {"balance": 100000.0, "daily_trades": 0},
                "ny_session": {"balance": 100000.0, "daily_trades": 0}, "sweep_4h": {"balance": 100000.0, "daily_trades": 0}}
    accounts = load_json(ACCOUNTS_FILE, defaults)
    for k in ["sweep_novol", "utbot_novol"]: accounts.pop(k, None)
    for k, v in defaults.items():
        if k not in accounts: accounts[k] = v
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if accounts.get("last_reset_date") != today:
        for k in defaults: accounts[k]["daily_trades"] = 0
        accounts["last_reset_date"] = today
        save_json(ACCOUNTS_FILE, accounts)

# ============================================================
#  YAHOO FINANCE THROTTLED DOWNLOAD (FIXED)
# ============================================================
def _throttled_yf_download(ticker, **kwargs):
    global _yf_last_call, _yf_rate_limited_until, _yf_backoff
    with _yf_lock:
        now = time.time()
        if now < _yf_rate_limited_until: return None
        elapsed = now - _yf_last_call
        if elapsed < _yf_min_gap: time.sleep(_yf_min_gap - elapsed)
    try:
        with _yf_lock: _yf_last_call = time.time()
        df = yf.download(ticker, **kwargs, session=_YF_SESSION)
        with _yf_lock: _yf_backoff = max(60, _yf_backoff // 2)
        if df is None or (hasattr(df, "empty") and df.empty): return None
        return df
    except Exception as e:
        if "rate" in str(e).lower() or "too many" in str(e).lower() or "429" in str(e):
            with _yf_lock:
                _yf_rate_limited_until = time.time() + _yf_backoff
                _yf_backoff = min(_yf_backoff * 2, _YF_BACKOFF_MAX)
                print(f"[YF BAN] {ticker} — backoff {_yf_backoff}s")
        raise

def get_price(symbol):
    now = time.time()
    if symbol in _price_cache:
        price, ts = _price_cache[symbol]
        if now - ts < _price_ttl:
            _price_cache.move_to_end(symbol)
            return price
    if now < _yf_rate_limited_until:
        return _price_cache[symbol][0] if symbol in _price_cache else None
    try:
        df = _throttled_yf_download(symbol, period="1d", interval="5m", progress=False, auto_adjust=True)
        if df is None or df.empty: return None
        df = normalise_cols(df)
        if "Close" not in df.columns or df["Close"].empty: return None
        price = float(df["Close"].iloc[-1])
        _price_cache[symbol] = (price, now)
        if len(_price_cache) > MAX_PRICE_CACHE: _price_cache.popitem(last=False)
        return price
    except Exception: return None

# ============================================================
#  INDICATORS & STRATEGIES
# ============================================================
def calculate_atr(df, period=10):
    tr = pd.concat([df["High"]-df["Low"], (df["High"]-df["Close"].shift(1)).abs(), (df["Low"]-df["Close"].shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def normalise_cols(df):
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    return df

def get_rsi(df, period=14):
    delta = df["Close"].diff()
    rs = delta.clip(lower=0).rolling(period).mean() / (-delta.clip(upper=0)).rolling(period).mean().replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def check_sweep_engulfing(ticker):
    try:
        df = _throttled_yf_download(ticker, period="10d", interval="1h", progress=False, auto_adjust=True)
        if df is None or df.empty or len(df) < 30: return None
        df = normalise_cols(df)
        is_nifty = "^NSEI" in ticker or "^NSEBANK" in ticker
        df_target = df if is_nifty else df.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
        if not is_nifty: trim_dataframe(df)
        if len(df_target) < 4: return None
        curr, mother = df_target.iloc[-2], df_target.iloc[-3]
        ts, price = int(df_target.index[-2].timestamp()*1000), float(curr["Close"])
        if curr["Low"]<mother["Low"] and curr["High"]>mother["High"] and curr["Close"]>mother["High"]:
            sl, risk = float(curr["Low"]), price-float(curr["Low"])
            if risk<=0: return None
            return ("BULLISH", price, sl, price+(risk*2.0), ts)
        if curr["High"]>mother["High"] and curr["Low"]<mother["Low"] and curr["Close"]<mother["Low"]:
            sl, risk = float(curr["High"]), float(curr["High"])-price
            if risk<=0: return None
            return ("BEARISH", price, sl, price-(risk*2.0), ts)
    except Exception as e: print(f"[ERR] Sweep {ticker}: {e}")
    return None

def check_ut_bot(ticker, kv=2):
    try:
        df_15 = _throttled_yf_download(ticker, period="3d", interval="15m", progress=False, auto_adjust=True)
        if df_15 is None or df_15.empty or len(df_15)<20: return None
        df_5 = _throttled_yf_download(ticker, period="1d", interval="5m", progress=False, auto_adjust=True)
        if df_5 is None or df_5.empty or len(df_5)<40: return None
        df_15, df_5 = normalise_cols(df_15), normalise_cols(df_5)
        df_15["xATR"], df_15["nLoss"] = calculate_atr(df_15, 10), kv*calculate_atr(df_15, 10)
        src, nLoss, ts_arr = df_15["Close"].values, df_15["nLoss"].values, np.zeros(len(df_15))
        for i in range(1, len(df_15)):
            p_ts, p_src = ts_arr[i-1], src[i-1]
            if src[i]>p_ts and p_src>p_ts: ts_arr[i]=max(p_ts, src[i]-nLoss[i])
            elif src[i]<p_ts and p_src<p_ts: ts_arr[i]=min(p_ts, src[i]+nLoss[i])
            elif src[i]>p_ts: ts_arr[i]=src[i]-nLoss[i]
            else: ts_arr[i]=src[i]+nLoss[i]
        i = len(df_15)-2
        is_buy, is_sell = (src[i]>ts_arr[i] and src[i-1]<=ts_arr[i-1]), (src[i]<ts_arr[i] and src[i-1]>=ts_arr[i-1])
        df_5["EMA50"], df_15["RSI"] = df_5["Close"].ewm(span=50, adjust=False).mean(), get_rsi(df_15)
        m5_close, m5_ema, rsi_15 = float(df_5["Close"].iloc[-2]), float(df_5["EMA50"].iloc[-2]), float(df_15["RSI"].iloc[-2])
        ts, atr_val = int(df_15.index[-2].timestamp()*1000), float(df_15["xATR"].iloc[i])
        if is_buy and m5_close>m5_ema and rsi_15>50: return ("BULLISH", m5_close, m5_close-(atr_val*ATR_MULT_SL), m5_close+(atr_val*ATR_MULT_TP), ts)
        if is_sell and m5_close<m5_ema and rsi_15<50: return ("BEARISH", m5_close, m5_close+(atr_val*ATR_MULT_SL), m5_close-(atr_val*ATR_MULT_TP), ts)
    except Exception as e: print(f"[ERR] UT Bot {ticker}: {e}")
    return None

def _finalize_trade_close(trade, live):
    is_long = trade["type"]=="LONG"
    pnl = ((live-trade["entry"])*trade["qty"]) if is_long else ((trade["entry"]-live)*trade["qty"])
    accounts[trade["account"]]["balance"] += pnl
    trade["exit_price"], trade["pnl"], trade["result"] = live, float(pnl), "WIN" if pnl>0 else "LOSS"
    trade["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    save_json(ACCOUNTS_FILE, accounts); save_json(ACTIVE_TRADES_FILE, active_trades)
    history = load_json(HISTORY_FILE, [])
    history.append(trade)
    if len(history)>MAX_HISTORY: history = history[-MAX_HISTORY:]
    save_json(HISTORY_FILE, history); _log_trade_to_csv(trade)
    safe_send_message(CHAT_ID, msg_trade_closed(trade, live, float(pnl), accounts[trade["account"]]["balance"], is_long, pnl>0), parse_mode="Markdown")
    return pnl

# ============================================================
#  SCANNER & MONITOR
# ============================================================
def scanner_loop():
    global _last_scan_time
    time.sleep(30) # Wait 30s on boot
    while True:
        now = time.time()
        if now - _last_scan_time < 300: time.sleep(15); continue
        if now < _yf_rate_limited_until: time.sleep(60); continue
        _last_scan_time = now
        for symbol, mtype in MONITORED:
            if not is_market_open(symbol): continue
            try:
                ut, sweep = check_ut_bot(symbol), check_sweep_engulfing(symbol)
                for strat_name, sig in [("UT Bot", ut), ("Sweep", sweep)]:
                    if not sig: continue
                    sig_type, price, sl, tp, ts = sig
                    key = f"{symbol}_{strat_name}_{ts}"
                    with _lock:
                        if key in sent_signals: continue
                        sent_signals[key] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
                        if len(sent_signals)>MAX_SENT_SIGNALS:
                            kept = list(sent_signals.items())[-(MAX_SENT_SIGNALS//2):]
                            sent_signals.clear(); sent_signals.update(kept)
                        save_json(SENT_SIGNALS_FILE, sent_signals)
                        if symbol in muted_assets: continue
                        account = "nifty" if "^NSE" in symbol else ("sweep_4h" if strat_name=="Sweep" else ("ny_session" if is_ny_session() else "macro"))
                        if accounts[account]["daily_trades"]>=ACCOUNT_LIMITS[account]: continue
                        risk_amt, risk = accounts[account]["balance"]*0.01, abs(price-sl)
                        if risk<=0: continue
                        qty = risk_amt/risk
                        trade = {"symbol":symbol,"account":account,"strat":strat_name,"type":"LONG" if "BULLISH" in sig_type else "SHORT","entry":price,"sl":sl,"tp":tp,"trail_sl":sl,"qty":qty,"open_time":datetime.now(IST).strftime("%Y-%m-%d %H:%M")}
                        active_trades.append(trade); accounts[account]["daily_trades"]+=1
                        save_json(ACCOUNTS_FILE, accounts); save_json(ACTIVE_TRADES_FILE, active_trades)
                    safe_send_message(CHAT_ID, msg_trade_signal(symbol, mtype, strat_name, sig_type, "15m" if strat_name=="UT Bot" else "4H", price, sl, tp, qty, risk_amt, account), parse_mode="Markdown")
                    print(f"[TRADE] {strat_name} {sig_type} {symbol}")
            except Exception as e: print(f"[ERR] Scanner {symbol}: {e}")
        gc.collect(); time.sleep(120)

def monitor_trades():
    while True:
        time.sleep(60)
        with _lock: trades = list(active_trades)
        if not trades: continue
        prices = {}
        for t in trades:
            if t["symbol"] not in prices:
                prices[t["symbol"]] = get_price(t["symbol"])
                time.sleep(2)
        for t in trades:
            live = prices.get(t["symbol"])
            if not live: continue
            is_long = t["type"]=="LONG"
            hit_tp = (is_long and live>=t["tp"]) or (not is_long and live<=t["tp"])
            hit_sl = (is_long and live<=t["trail_sl"]) or (not is_long and live>=t["trail_sl"])
            if hit_tp or hit_sl:
                with _lock:
                    if t in active_trades:
                        active_trades.remove(t)
                        _finalize_trade_close(t, live)
        gc.collect()

def daily_reset_loop():
    while True:
        now = datetime.now(IST)
        target = now.replace(hour=0, minute=5, second=0, microsecond=0)
        if now > target: target += timedelta(days=1)
        time.sleep((target - now).total_seconds())
        with _lock:
            for acc in accounts: accounts[acc]["daily_trades"] = 0
            accounts["last_reset_date"] = datetime.now(IST).strftime("%Y-%m-%d")
            save_json(ACCOUNTS_FILE, accounts)

# ============================================================
#  FLASK APP & TELEGRAM BOT
# ============================================================
flask_app = Flask(__name__)
@flask_app.route("/ping")
def ping(): return "pong"
@flask_app.route("/")
def home(): return "Trading Bot OK"
@flask_app.route("/api/balance")
def api_balance():
    with _lock: return jsonify({k: accounts.get(k, {"balance":100000,"daily_trades":0}) for k in ["macro","nifty","ny_session","sweep_4h"]})
@flask_app.route("/dashboard")
def dashboard(): return "<h1>Trading Bot Active</h1><p>Check Telegram for alerts.</p>"

bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")
def menu_markup():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("🔍 Check Markets", callback_data="cmd_check"))
    m.add(InlineKeyboardButton("📊 Asset Summary", callback_data="cmd_summary"))
    return m

@bot.message_handler(commands=["start", "help"])
def cmd_start(m): safe_send_message(m.chat.id, msg_guide(), parse_mode="Markdown", reply_markup=menu_markup())

@bot.message_handler(commands=["check"])
def cmd_check(m):
    chat_id = m.chat.id
    safe_send_message(chat_id, msg_scanning())
    def run_scan():
        try:
            signals, neutral = [], []
            for symbol, mtype in MONITORED:
                if not is_market_open(symbol): neutral.append(f"⚪ `{symbol}` — Closed"); continue
                ut, sweep = check_ut_bot(symbol), check_sweep_engulfing(symbol)
                if ut: signals.append(f"🟢 `{symbol}` ➔ 🟣 UT Bot *{ut[0]}* `${ut[1]:,.4f}`")
                if sweep: signals.append(f"🟢 `{symbol}` ➔ 🔵 Sweep *{sweep[0]}* `${sweep[1]:,.4f}`")
                if not ut and not sweep: neutral.append(f"⚪ `{symbol}` — No Setup")
                time.sleep(2)
            safe_send_message(chat_id, msg_scan_results(signals, neutral))
        except Exception as e: safe_send_message(chat_id, msg_error("Scan", str(e)))
        finally: gc.collect()
    threading.Thread(target=run_scan, daemon=True).start()

@bot.message_handler(commands=["summary"])
def cmd_summary(m):
    try:
        lines = []
        for symbol, mtype in MONITORED:
            price = get_price(symbol)
            lines.append(f"{'🔴' if symbol in muted_assets else '🟢'} `{symbol}` · {mtype} · `${price:,.4f}`" if price else f"{'🔴' if symbol in muted_assets else '🟢'} `{symbol}` · {mtype}")
            time.sleep(2)
        safe_send_message(m.chat.id, msg_summary(lines))
    except Exception as e: safe_send_message(m.chat.id, msg_error("Summary", str(e)))

@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    try:
        history = load_json(HISTORY_FILE, [])
        def stats(acc):
            ts = [x for x in history if x.get("account")==acc]
            w, l = sum(1 for x in ts if x.get("result")=="WIN"), sum(1 for x in ts if x.get("result")=="LOSS")
            p = sum(float(x.get("pnl",0)) for x in ts)
            return w, l, p, (w/(w+l)*100) if (w+l) else 0
        safe_send_message(m.chat.id, msg_stats(*stats("macro"), *stats("nifty"), *stats("ny_session"), *stats("sweep_4h")), reply_markup=menu_markup())
    except Exception as e: safe_send_message(m.chat.id, msg_error("Stats", str(e)))

@bot.message_handler(commands=["active"])
def cmd_active(m):
    try:
        with _lock: trades = list(active_trades)
        if not trades: safe_send_message(m.chat.id, msg_active_trades([], 0)); return
        trades_list, total_pnl, prices = [], 0.0, {}
        for t in trades:
            if t["symbol"] not in prices:
                prices[t["symbol"]] = get_price(t["symbol"])
                time.sleep(2)
            live = prices[t["symbol"]]
            if live:
                pnl = (live-t["entry"])*t["qty"] if t["type"]=="LONG" else (t["entry"]-live)*t["qty"]
                total_pnl += pnl
            trades_list.append(build_trade_block(t, live))
        safe_send_message(m.chat.id, msg_active_trades(trades_list, total_pnl))
    except Exception as e: safe_send_message(m.chat.id, msg_error("Active", str(e)))

@bot.message_handler(commands=["balance"])
def cmd_balance(m):
    try:
        with _lock:
            b = {k: accounts.get(k, {"balance":100000.0,"daily_trades":0}) for k in ["macro","nifty","ny_session","sweep_4h"]}
            trades = list(active_trades)
        u_pnl, prices = {"macro":0.0,"nifty":0.0,"ny_session":0.0,"sweep_4h":0.0}, {}
        for t in trades:
            if t["symbol"] not in prices:
                prices[t["symbol"]] = get_price(t["symbol"])
                time.sleep(2)
            live = prices[t["symbol"]]
            if live:
                u_pnl[t["account"]] += ((live-t["entry"])*t["qty"]) if t["type"]=="LONG" else ((t["entry"]-live)*t["qty"])
        safe_send_message(m.chat.id, msg_balance(b["macro"]["balance"],b["nifty"]["balance"],b["ny_session"]["balance"],b["sweep_4h"]["balance"],b["macro"]["daily_trades"],b["nifty"]["daily_trades"],b["ny_session"]["daily_trades"],b["sweep_4h"]["daily_trades"],ACCOUNT_LIMITS["macro"],ACCOUNT_LIMITS["nifty"],ACCOUNT_LIMITS["ny_session"],ACCOUNT_LIMITS["sweep_4h"],is_ny_session(),u_pnl), reply_markup=menu_markup())
    except Exception as e: safe_send_message(m.chat.id, msg_error("Balance", str(e)))

@bot.message_handler(commands=["clear"])
def cmd_clear(m):
    global active_trades, sent_signals
    try:
        with _lock:
            active_trades = []
            for acc in ACCOUNT_LIMITS: accounts[acc] = {"balance":100000.0,"daily_trades":0}
            save_json(ACCOUNTS_FILE, accounts); save_json(ACTIVE_TRADES_FILE, []); save_json(HISTORY_FILE, [])
            sent_signals = {}; save_json(SENT_SIGNALS_FILE, sent_signals)
        safe_send_message(m.chat.id, msg_cleared())
    except Exception as e: safe_send_message(m.chat.id, msg_error("Clear", str(e)))

@bot.message_handler(commands=["indi1", "indi2"])
def cmd_indi(m):
    chat_id, n = m.chat.id, 1 if "/indi1" in m.text else 2
    safe_send_message(chat_id, msg_indi_diagnosing(n))
    def run():
        try:
            results = []
            for symbol, _ in MONITORED:
                if not is_market_open(symbol): continue
                res = check_sweep_engulfing(symbol) if n==1 else check_ut_bot(symbol)
                if res: results.append(f"{'🟢' if 'BULLISH' in res[0] else '🔴'} `{symbol}` → {res[0]} @ {res[1]:.2f}")
                else: results.append(f"⚪ `{symbol}` → No Setup")
                time.sleep(2)
            if any("BULLISH" in r or "BEARISH" in r for r in results): safe_send_message(chat_id, "\n".join(results))
            else: safe_send_message(chat_id, msg_indi_no_signals(n))
        except Exception as e: safe_send_message(chat_id, msg_error(f"Indi{n}", str(e)))
    threading.Thread(target=run, daemon=True).start()

@bot.callback_query_handler(func=lambda c: True)
def handle_cb(c):
    try:
        if c.data == "cmd_check": cmd_check(c.message)
        elif c.data == "cmd_summary": cmd_summary(c.message)
        elif c.data.startswith("mute_"):
            sym = c.data.split("_",1)[1]
            with _lock: muted_assets.add(sym); save_json(MUTE_FILE, list(muted_assets))
            bot.edit_message_text(msg_muted(sym), c.message.chat.id, c.message.message_id, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔊 Unmute", callback_data=f"unmute_{sym}")))
        elif c.data.startswith("unmute_"):
            sym = c.data.split("_",1)[1]
            with _lock: muted_assets.discard(sym); save_json(MUTE_FILE, list(muted_assets))
            bot.edit_message_text(msg_unmuted(sym), c.message.chat.id, c.message.message_id, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔇 Mute", callback_data=f"mute_{sym}")))
    except Exception as e: print(f"[ERR] Callback: {e}")
    finally: bot.answer_callback_query(c.id)

# ============================================================
#  BOOT
# ============================================================
if __name__ == "__main__":
    if not CHAT_ID:
        print("FATAL: CHAT_ID not set!")
        exit(1)

    init_accounts()
    muted_assets.update(load_json(MUTE_FILE, []))
    active_trades = load_json(ACTIVE_TRADES_FILE, [])
    sent_signals = load_json(SENT_SIGNALS_FILE, {})

    print("=" * 50)
    print("  Trading Bot Starting...")
    print(f"  Macro:      Rs.{accounts['macro']['balance']:,.2f}")
    print(f"  Nifty:      Rs.{accounts['nifty']['balance']:,.2f}")
    print(f"  NY Session: Rs.{accounts['ny_session']['balance']:,.2f}")
    print(f"  Sweep 4H:   Rs.{accounts['sweep_4h']['balance']:,.2f}")
    print(f"  Web server: :{PORT}/ping")
    print("=" * 50)

    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=monitor_trades, daemon=True).start()
    threading.Thread(target=daily_reset_loop, daemon=True).start()
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False), daemon=True).start()

    print("[BOT] Connecting to Telegram...")
    while True:
        try: bot.polling(timeout=60, long_polling_timeout=10)
        except Exception as e:
            print(f"[ERR] Polling crashed: {e}")
            time.sleep(5)
