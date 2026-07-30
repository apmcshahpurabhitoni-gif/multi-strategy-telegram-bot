import os
import json
import time
import csv
import threading
import gc
import io
from datetime import datetime, timedelta
from io import BytesIO
from collections import OrderedDict, deque

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

# --- Render free tier friendly paths ---
DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)

ACCOUNTS_FILE      = os.path.join(DATA_DIR, "accounts.json")
ACTIVE_TRADES_FILE = os.path.join(DATA_DIR, "active_trades.json")
HISTORY_FILE       = os.path.join(DATA_DIR, "trade_history.json")
MUTE_FILE          = os.path.join(DATA_DIR, "muted_assets.json")
TRADE_LOG_CSV      = os.path.join(DATA_DIR, "trade_log.csv")
SENT_SIGNALS_FILE  = os.path.join(DATA_DIR, "sent_signals.json")

ACCOUNT_LIMITS = {
    "macro":      20,
    "nifty":      3,
    "ny_session": 3,
    "sweep_4h":   3,
}

MONITORED = [
    ("BTC-USD",  "Crypto"),
    ("GC=F",     "Commodity"),
    ("^NSEI",    "Index"),
    ("^NSEBANK", "Index"),
    ("EURUSD=X", "Forex"),
    ("GBPUSD=X", "Forex"),
    ("USDJPY=X", "Forex"),
]

# --- Memory caps for 512MB Render free tier ---
MAX_HISTORY       = 200
MAX_SENT_SIGNALS  = 500
MAX_PRICE_CACHE   = 64
HISTORY_JSON_CAP  = 200  # keep file lean

# ============================================================
#  GLOBALS & LOCKS
# ============================================================
accounts      = {}
active_trades = []
muted_assets  = set()
sent_signals  = {}  # bounded dict

_lock        = threading.RLock()
_price_cache = OrderedDict()  # LRU
_price_ttl   = 300
_last_scan_time = 0

# --- YF global rate limiter (Render shares IPs, YF is aggressive) ---
_yf_lock               = threading.Lock()
_yf_last_call          = 0.0
_yf_min_gap            = 8.0          # 8s between any yf calls
_yf_rate_limited_until = 0.0
_yf_backoff            = 300          # start at 5 min, not 60s
_YF_BACKOFF_MAX        = 1800         # cap at 30 min
# Per-ticker cooldown so we don't hammer the same symbol
_yf_symbol_cooldown: dict = {}
# Sliding window: max 6 calls per 60s
_yf_call_times: list = []

IST = pytz.timezone("Asia/Kolkata")

# Shared Yahoo session
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
    if symbol in ("BTC-USD", "GC=F"):
        return True
    if symbol in ("EURUSD=X", "GBPUSD=X", "USDJPY=X"):
        return w < 5
    if symbol in ("^NSEI", "^NSEBANK"):
        return w < 5 and 555 <= total_min <= 930
    return False

def is_ny_session():
    now = datetime.now(IST)
    w = now.weekday()
    total_min = now.hour * 60 + now.minute
    return w < 5 and (total_min >= 1200 or total_min <= 150)

def trim_dataframe(df):
    """Drop dataframe immediately + collect — used aggressively to keep RAM low."""
    try:
        del df
    except Exception:
        pass

# ============================================================
#  MESSAGE TEMPLATES (v2 — colorful + informative)
# ============================================================
BR  = "━━━━━━━━━━━━━━━━━━━━━━"
BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
THIN = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

def progress_bar(current, total, width=10):
    if total <= 0:
        return "░" * width
    filled = max(0, min(width, int(round(width * current / total))))
    return "▓" * filled + "░" * (width - filled)

def pnl_emoji(pnl):
    if pnl > 0:    return "🟢"
    if pnl < 0:    return "🔴"
    return "⚪"

def pnl_str(pnl):
    if pnl >= 0:   return f"+₹{pnl:,.2f}"
    return f"-₹{abs(pnl):,.2f}"

def pct_str(pct):
    if pct >= 0:   return f"+{pct:.2f}%"
    return f"{pct:.2f}%"

def dir_emoji(t):  return "📈" if t == "LONG" else "📉"
def dir_word(t):  return "LONG  📈" if t == "LONG" else "SHORT 📉"

def now_short():
    return datetime.now(IST).strftime("%H:%M:%S IST")

def fmt_rr(price, sl, tp):
    risk = abs(price - sl)
    reward = abs(tp - price)
    if risk <= 0:
        return "—"
    return f"1:{reward / risk:.2f}"

def fmt_pct_dist(price, target, is_long):
    if price <= 0:
        return "—"
    if is_long:
        dist = (target - price) / price * 100
    else:
        dist = (price - target) / price * 100
    return f"{dist:+.2f}%"

def build_trade_block(t, live):
    is_long   = t["type"] == "LONG"
    entry     = float(t["entry"])
    sl        = float(t["trail_sl"])
    tp        = float(t["tp"])
    qty       = float(t["qty"])
    symbol    = t["symbol"]
    account   = t["account"]
    strat     = t.get("strat", "—")

    if live is None:
        pnl_s  = "⏳ Fetching…"
        pct_s  = "—"
        p_icon = "⏳"
        live_s = "—"
    else:
        live_f = float(live)
        pnl    = (live_f - entry) * qty if is_long else (entry - live_f) * qty
        pnl_pct = ((live_f - entry) / entry * 100) if is_long else ((entry - live_f) / entry * 100)
        pnl_s  = pnl_str(pnl)
        pct_s  = pct_str(pnl_pct)
        p_icon = pnl_emoji(pnl)
        live_s = f"${live_f:,.4f}"

    sl_pct = fmt_pct_dist(entry, sl, is_long)
    tp_pct = fmt_pct_dist(entry, tp, is_long)

    return (
        f"{p_icon} *`{symbol}`*  ·  {dir_word(t['type'])}  ·  `{account.upper()}`\n"
        f"┌─ 🎯 {strat}\n"
        f"│ 📍 Entry:    `${entry:,.4f}`\n"
        f"│ 📊 Live:     `{live_s}`  ({pct_s})\n"
        f"│ 🛡️ Trail SL: `${sl:,.4f}`  ({sl_pct})\n"
        f"│ 🎯 Take TP:  `${tp:,.4f}`  ({tp_pct})\n"
        f"│ 📦 Qty:      `{qty:.4f}`\n"
        f"│ 💹 U.PnL:    `{pnl_s}`\n"
        f"└─"
    )

# ---------- TRADE SIGNAL ----------
def msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, actual_sl, actual_tp, qty, risk_amt, account):
    is_long  = "BULLISH" in sig_type
    arrow    = "🟢🟢🟢" if is_long else "🔴🔴🔴"
    label    = "🚀 STRONG BULLISH" if is_long else "💥 STRONG BEARISH"
    dir_     = "LONG 📈" if is_long else "SHORT 📉"
    rr       = fmt_rr(price, actual_sl, actual_tp)
    sl_dist  = abs(price - actual_sl) / price * 100
    tp_dist  = abs(actual_tp - price) / price * 100
    sl_pct   = fmt_pct_dist(price, actual_sl, is_long)
    tp_pct   = fmt_pct_dist(price, actual_tp, is_long)
    sl_arrow = "🔻" if is_long else "🔺"
    tp_arrow = "🎯"
    # R:R checkmark — guard against "—" so split() doesn't crash
    rr_check = "✅"
    try:
        if rr != "—" and float(rr.split(":")[1]) < 2:
            rr_check = "⚠️"
    except Exception:
        rr_check = "⚠️"

    return (
        f"{arrow}  *NEW SIGNAL — {label}*  {arrow}\n"
        f"{BR2}\n"
        f"🪙 `{symbol}` · {mtype}\n"
        f"📊 *{strat}*  ·  {dir_}  ·  ⏱ `{tf}`\n"
        f"{BR}\n"
        f"💼 *PAPER TRADE EXECUTED*\n"
        f"{BR}\n"
        f"🏢 *Account:*   `{account.upper()}`\n"
        f"📍 *Entry:*     `${price:,.4f}`\n"
        f"🛑 *Stop Loss:* `${actual_sl:,.4f}`  {sl_arrow} `{sl_pct}`\n"
        f"🎯 *Take Profit:* `${actual_tp:,.4f}`  {tp_arrow} `{tp_pct}`\n"
        f"📦 *Quantity:*  `{qty:.4f}`\n"
        f"💸 *Risk:*      `₹{risk_amt:,.2f}`  (2% of account)\n"
        f"{BR}\n"
        f"📐 *R:R Ratio:* `{rr}`  {rr_check}\n"
        f"🛡️ *Stop Dist:* `{sl_dist:.2f}%`  ·  🎯 *TP Dist:* `{tp_dist:.2f}%`\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

# ---------- TRADE CLOSED ----------
def msg_trade_closed(trade, live, pnl, bal, is_long, hit_tp):
    result   = "🎉 *WIN* ✅" if hit_tp else "💀 *LOSS* ❌"
    icon     = "🟢" if hit_tp else "🔴"
    entry    = float(trade["entry"])
    sl       = float(trade["trail_sl"])
    tp       = float(trade["tp"])
    notional = entry * float(trade["qty"])
    pnl_pct  = (pnl / notional * 100) if notional else 0
    move_pct = abs(live - entry) / entry * 100 if entry else 0
    arrow    = "📈" if ((live > entry) if is_long else (live < entry)) else "📉"
    duration = ""
    if trade.get("open_time"):
        try:
            opened  = datetime.strptime(trade["open_time"], "%Y-%m-%d %H:%M")
            closed  = datetime.now(IST).replace(tzinfo=None)
            delta   = closed - opened
            secs    = int(delta.total_seconds())
            h, rem  = divmod(secs, 3600)
            m, s    = divmod(rem, 60)
            duration = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
        except Exception:
            duration = "—"

    return (
        f"{icon} *TRADE CLOSED*  {result}\n"
        f"{BR2}\n"
        f"🪙 `{trade['symbol']}`  ·  {dir_word(trade['type'])}  ·  `{trade['account'].upper()}`\n"
        f"🎯 *Strategy:* {trade['strat']}\n"
        f"{BR}\n"
        f"📊 *TRADE SUMMARY*\n"
        f"{BR}\n"
        f"📍 *Entry:*     `${entry:,.4f}`\n"
        f"{arrow} *Exit:*      `${live:,.4f}`\n"
        f"🛡️ *Trail SL:*  `${sl:,.4f}`\n"
        f"🎯 *TP Target:* `${tp:,.4f}`\n"
        f"📏 *Price Move:* `{move_pct:.2f}%`\n"
        f"⏱ *Duration:*   `{duration}`\n"
        f"{BR}\n"
        f"{icon} *P/L:*     `{pnl_str(pnl)}`  ({pnl_pct:+.2f}%)  {icon}\n"
        f"🏦 *Balance:* `₹{bal:,.2f}`\n"
        f"{BR}\n"
        f"🕐 Closed at `{now_short()}`\n"
        f"{BR2}"
    )

# ---------- ACTIVE TRADES ----------
def msg_active_trades(trades_list, total_pnl):
    if not trades_list:
        return msg_no_active_trades()
    n = len(trades_list)
    pnl_icon = pnl_emoji(total_pnl)
    return (
        f"📊 *LIVE POSITIONS*  ·  {n} OPEN\n"
        f"{BR2}\n"
        + "\n".join(trades_list)
        + f"\n{BR}\n"
        f"{pnl_icon} *Total Unrealized:* `{pnl_str(total_pnl)}`\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

# ---------- BALANCE ----------
def msg_balance(macro_bal, nifty_bal, ny_bal, sweep_bal, macro_d, nifty_d, ny_d, sweep_d,
                macro_l, nifty_l, ny_l, sweep_l, ny_active, u_pnl):
    def line(emoji, name, bal, used, limit, upnl, status_icon="🟢", status_text="READY"):
        bar    = progress_bar(used, limit)
        pct    = (used / limit * 100) if limit else 0
        upnl_s = pnl_str(upnl)
        return (
            f"{emoji} *{name}*  {status_icon} `{status_text}`\n"
            f"┌─\n"
            f"│ 💰 Balance:  `₹{bal:,.2f}`\n"
            f"│ 📊 Trades:   `{used}/{limit}`  {bar}  `{pct:.0f}%`\n"
            f"│ 💹 U.PnL:    `{upnl_s}`  {pnl_emoji(upnl)}\n"
            f"└─"
        )

    total_bal  = macro_bal + nifty_bal + ny_bal + sweep_bal
    total_upnl = u_pnl["macro"] + u_pnl["nifty"] + u_pnl["ny_session"] + u_pnl["sweep_4h"]
    ny_icon = "🟢" if ny_active else "🔴"
    ny_text = "ACTIVE" if ny_active else "CLOSED"

    return (
        f"💰 *ACCOUNT OVERVIEW*\n"
        f"{BR2}\n"
        f"{line('🏢', 'MACRO ACCOUNT',      macro_bal, macro_d, macro_l, u_pnl['macro'])}\n"
        f"\n"
        f"{line('🇮🇳', 'NIFTY ACCOUNT',     nifty_bal, nifty_d, nifty_l, u_pnl['nifty'])}\n"
        f"\n"
        f"{line('🗽', 'NY SESSION ACCOUNT', ny_bal,    ny_d,    ny_l,    u_pnl['ny_session'], ny_icon, ny_text)}\n"
        f"\n"
        f"{line('🌊', 'SWEEP 4H ACCOUNT',   sweep_bal, sweep_d, sweep_l, u_pnl['sweep_4h'])}\n"
        f"{BR}\n"
        f"💼 *TOTAL EQUITY:*   `₹{total_bal:,.2f}`\n"
        f"💹 *TOTAL U.PnL:*    `{pnl_str(total_upnl)}`  {pnl_emoji(total_upnl)}\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

# ---------- STATS ----------
def msg_stats(mw, ml, mp, mwr, nw, nl, np_, nwr, nyw, nyl, nyp, nywr, sw, sl, sp, swr):
    def acc_block(emoji, name, w, l, p, wr):
        total = w + l
        wr_emoji = "🟢" if wr >= 60 else ("🟡" if wr >= 40 else "🔴")
        return (
            f"{emoji} *{name}*\n"
            f"┌─\n"
            f"│ 🏆 Wins:  `{w}`    💀 Losses: `{l}`    📊 Total: `{total}`\n"
            f"│ 📈 Win Rate:    `{wr:.1f}%`  {wr_emoji}\n"
            f"│ 💰 Net P/L:     `{pnl_str(p)}`  {pnl_emoji(p)}\n"
            f"└─"
        )

    total_w  = mw + nw + nyw + sw
    total_l  = ml + nl + nyl + sl
    total_p  = mp + np_ + nyp + sp
    total_wr = (total_w / (total_w + total_l) * 100) if (total_w + total_l) else 0

    return (
        f"📊 *PERFORMANCE REPORT*\n"
        f"{BR2}\n"
        f"{acc_block('🏢', 'MACRO ACCOUNT',      mw, ml, mp,  mwr)}\n"
        f"\n"
        f"{acc_block('🇮🇳', 'NIFTY ACCOUNT',     nw, nl, np_, nwr)}\n"
        f"\n"
        f"{acc_block('🗽', 'NY SESSION ACCOUNT', nyw, nyl, nyp, nywr)}\n"
        f"\n"
        f"{acc_block('🌊', 'SWEEP 4H ACCOUNT',   sw, sl, sp,  swr)}\n"
        f"{BR}\n"
        f"💼 *AGGREGATE STATS*\n"
        f"┌─\n"
        f"│ 🏆 Total Wins:   `{total_w}`\n"
        f"│ 💀 Total Losses: `{total_l}`\n"
        f"│ 📈 Overall WR:   `{total_wr:.1f}%`  {pnl_emoji(total_wr - 50)}\n"
        f"│ 💰 Net P/L:      `{pnl_str(total_p)}`  {pnl_emoji(total_p)}\n"
        f"└─\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

# ---------- SCAN ----------
def msg_scanning():
    return (
        f"🔍 *SCANNING MARKETS…*\n"
        f"{BR}\n"
        f"⏳ Analyzing all assets across strategies…\n\n"
        f"🔵 Sweep + Reverse (4H / 1H)\n"
        f"🟣 UT Bot Signals (15m)\n\n"
        f"⏱ Please wait ~15 seconds…\n"
        f"{BR}\n"
        f"💡 Tip: I'll ping you when signals are found.\n"
        f"{BR2}"
    )

def msg_scan_results(signals, neutral):
    n_sig = len(signals)
    n_neu = len(neutral)
    header_emoji = "🔥" if n_sig else "⏳"
    header_text  = f"*{n_sig} SIGNAL{'S' if n_sig != 1 else ''} FOUND*" if n_sig else "*NO ACTIVE SETUPS*"

    body = ""
    if signals:
        body = "🎯 *ACTIVE SETUPS*\n" + BR + "\n" + "\n".join(signals) + "\n"
    if neutral:
        if body:
            body += "\n"
        body += f"⚪ *NEUTRAL ({n_neu})*\n" + THIN + "\n" + "\n".join(neutral) + "\n"

    return (
        f"{header_emoji} *MARKET SCAN COMPLETE*\n"
        f"{BR2}\n"
        f"{header_text}\n"
        f"{BR}\n"
        f"{body}"
        f"{BR}\n"
        f"📊 *Summary:* `{n_sig} setup{'s' if n_sig != 1 else ''}` / `{n_neu} neutral`\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

# ---------- SUMMARY ----------
def msg_summary(lines):
    n = len(lines)
    return (
        f"📋 *LIVE MARKET SUMMARY*\n"
        f"{BR2}\n"
        f"🪙 *{n} ASSET{'S' if n != 1 else ''} TRACKED*\n"
        f"{BR}\n"
        + "\n".join(lines) + "\n"
        + f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

# ---------- GUIDE ----------
def msg_guide():
    return (
        f"🤖 *TRADING BOT — COMMAND CENTER*\n"
        f"{BR2}\n"
        f"📘 *AVAILABLE COMMANDS*\n"
        f"{BR}\n"
        f"🎯 *TRADING & SCANNING*\n"
        f"┌─\n"
        f"│ `/check`        — Scan all markets now\n"
        f"│ `/summary`      — Live prices & status\n"
        f"│ `/active`       — View open positions\n"
        f"│ `/close SYMBOL` — Manually close a trade\n"
        f"└─\n"
        f"{BR}\n"
        f"📊 *ANALYTICS*\n"
        f"┌─\n"
        f"│ `/stats`        — Performance report\n"
        f"│ `/balance`      — Account balances + U.PnL\n"
        f"│ `/export`       — Download CSV log\n"
        f"└─\n"
        f"{BR}\n"
        f"🔧 *TOOLS*\n"
        f"┌─\n"
        f"│ `/indi1`        — Diagnose Sweep strategy\n"
        f"│ `/indi2`        — Diagnose UT Bot strategy\n"
        f"│ `/clear`        — Reset all accounts\n"
        f"└─\n"
        f"{BR}\n"
        f"⚡ *ACTIVE STRATEGIES*\n"
        f"┌─\n"
        f"│ 🔵 *Sweep + Engulfing*  (4H timeframe)\n"
        f"│ 🟣 *UT Bot Alerts*      (15m + 5m EMA)\n"
        f"└─\n"
        f"{BR}\n"
        f"📊 *MONITORED MARKETS*\n"
        f"┌─\n"
        f"│ 🪙 Crypto      — BTC-USD\n"
        f"│ 🟡 Commodity   — GC=F (Gold)\n"
        f"│ 💱 Forex       — EUR · GBP · JPY\n"
        f"│ 📈 Index       — NIFTY 50 · BANK NIFTY\n"
        f"└─\n"
        f"{BR}\n"
        f"💡 *Tip:* Use the buttons below for quick access.\n"
        f"{BR2}"
    )

# ---------- ERROR ----------
def msg_error(context, error):
    err_s = str(error)
    if len(err_s) > 200:
        err_s = err_s[:197] + "…"
    # Escape backticks so they don't break Markdown
    err_s = err_s.replace("`", "'")
    return (
        f"⚠️ *ERROR OCCURRED*\n"
        f"{BR2}\n"
        f"❌ *Context:*  `{context}`\n"
        f"🔍 *Details:*  `{err_s}`\n"
        f"{BR}\n"
        f"💡 *Suggestions:*\n"
        f"┌─\n"
        f"│ • Check your internet connection\n"
        f"│ • Try the command again in a moment\n"
        f"│ • Use `/clear` to reset if persistent\n"
        f"│ • Contact support if issue continues\n"
        f"└─\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

# ---------- MISC ----------
def msg_cleared():
    return (
        f"🗑️ *ACCOUNTS RESET*\n"
        f"{BR2}\n"
        f"✅ All balances       → `₹1,00,000`\n"
        f"✅ All active trades  → *Closed*\n"
        f"✅ All trade history  → *Wiped*\n"
        f"✅ Daily trade counts → *Reset*\n"
        f"✅ Signal cache       → *Cleared*\n"
        f"{BR}\n"
        f"🆕 *Fresh start — good luck!* 🍀\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

def msg_no_active_trades():
    return (
        f"📭 *NO ACTIVE TRADES*\n"
        f"{BR}\n"
        f"No positions currently open across any account.\n\n"
        f"💡 *What to do next:*\n"
        f"┌─\n"
        f"│ • `/check`  — Scan for new setups\n"
        f"│ • `/stats`  — Review past performance\n"
        f"│ • `/balance`— Check account status\n"
        f"└─\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

def msg_muted(sym):
    return (
        f"🔇 *ASSET MUTED*\n"
        f"{BR}\n"
        f"🪙 `{sym}`\n\n"
        f"✅ This asset will *NOT* trigger new signals\n"
        f"⏸️ Existing trades will still be monitored\n\n"
        f"💡 Use the button below to unmute\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

def msg_unmuted(sym):
    return (
        f"🔊 *ASSET UNMUTED*\n"
        f"{BR}\n"
        f"🪙 `{sym}`\n\n"
        f"✅ This asset is *back in the scanner*\n"
        f"🎯 Signals will be detected again\n\n"
        f"💡 Use the button below to mute\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

def msg_indi_diagnosing(n):
    name  = "Sweep + Engulfing (4H)" if n == 1 else "UT Bot (15m + 5m EMA)"
    color = "🔵" if n == 1 else "🟣"
    return (
        f"{color} *DIAGNOSING STRATEGY {n}*\n"
        f"{BR2}\n"
        f"📋 *Strategy:* {name}\n\n"
        f"⏳ Running deep analysis on all assets…\n"
        f"⏱ Please wait ~20 seconds…\n\n"
        f"💡 I'll send results when ready.\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

def msg_indi_no_signals(n):
    color = "🔵" if n == 1 else "🟣"
    name  = "Sweep + Engulfing" if n == 1 else "UT Bot"
    return (
        f"😴 *STRATEGY {n} — NO SIGNALS*\n"
        f"{BR2}\n"
        f"📋 *Strategy:* {name}\n\n"
        f"⚪ No assets met conditions.\n\n"
        f"💡 *Possible reasons:*\n"
        f"┌─\n"
        f"│ • Market is ranging or low-volume\n"
        f"│ • Waiting for clearer setup\n"
        f"│ • Try again in next session\n"
        f"└─\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

def msg_export_ready(count):
    return (
        f"📥 *EXPORT READY*\n"
        f"{BR}\n"
        f"📊 Trade Log CSV\n"
        f"📝 Records: `{count}` trade{'s' if count != 1 else ''}\n"
        f"💾 Format:  CSV (Excel-compatible)\n\n"
        f"💡 File attached below ⬇️\n"
        f"{BR}\n"
        f"🕐 `{now_short()}`\n"
        f"{BR2}"
    )

def msg_chart_failed():
    return (
        f"❌ *CHART GENERATION FAILED*\n"
        f"{BR2}\n"
        f"⚠️ Could not fetch or render chart data.\n\n"
        f"💡 *Possible reasons:*\n"
        f"┌─\n"
        f"│ • Insufficient data at this timeframe\n"
        f"│ • Yahoo Finance rate limit\n"
        f"│ • Network connectivity issue\n"
        f"└─\n"
        f"{BR}\n"
        f"💡 Try again in a minute or pick a different timeframe.\n"
        f"{BR2}"
    )

# ============================================================
#  JSON / IO
# ============================================================
def load_json(filepath, default):
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print("[ERR] load_json(" + filepath + "): " + str(e))
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print("[ERR] save_json(" + filepath + "): " + str(e))

def safe_send_message(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        print("[ERR] Failed to send message: " + str(e))
        # Fallback: strip markdown chars and retry
        try:
            clean = (text.replace("*", "")
                        .replace("`", "'")
                        .replace("▓", "■")
                        .replace("░", "□"))
            bot.send_message(chat_id, "⚠️ Message formatting error, raw output:\n" + clean, parse_mode=None)
        except Exception as fallback_e:
            print("[ERR] Fallback message also failed: " + str(fallback_e))

def _log_trade_to_csv(trade_dict):
    """Append one closed-trade row to CSV. Centralized to remove duplication."""
    try:
        file_exists = os.path.isfile(TRADE_LOG_CSV)
        with open(TRADE_LOG_CSV, "a", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["close_time", "symbol", "account", "strategy", "type",
                          "entry", "exit_price", "sl", "tp", "qty", "pnl", "result"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({k: trade_dict.get(k, "") for k in fieldnames})
    except Exception as e:
        print("[ERR] Log trade: " + str(e))

def init_accounts():
    global accounts
    defaults = {
        "macro":      {"balance": 100000.0, "daily_trades": 0},
        "nifty":      {"balance": 100000.0, "daily_trades": 0},
        "ny_session": {"balance": 100000.0, "daily_trades": 0},
        "sweep_4h":   {"balance": 100000.0, "daily_trades": 0},
    }
    accounts = load_json(ACCOUNTS_FILE, defaults)
    for key in ["sweep_novol", "utbot_novol"]:
        accounts.pop(key, None)
    for key, val in defaults.items():
        if key not in accounts:
            accounts[key] = val
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if accounts.get("last_reset_date") != today:
        for key in defaults:
            accounts[key]["daily_trades"] = 0
        accounts["last_reset_date"] = today
        save_json(ACCOUNTS_FILE, accounts)

# ============================================================
#  YAHOO FINANCE THROTTLED DOWNLOAD (hardened)
# ============================================================
def _throttled_yf_download(ticker, **kwargs):
    """
    Global yf.download wrapper with:
      - global minimum gap between any calls
      - per-ticker cooldown
      - circuit breaker on rate-limit response
      - exponential backoff up to cap
    Returns None if blocked by circuit breaker (caller must handle).
    """
    global _yf_last_call, _yf_rate_limited_until, _yf_backoff, _yf_symbol_cooldown
    with _yf_lock:
        now = time.time()

        # Circuit breaker — short-circuit on recent rate-limit
        if now < _yf_rate_limited_until:
            return None

        # Per-ticker cooldown (e.g. 20s)
        cd = _yf_symbol_cooldown.get(ticker, 0)
        if now < cd:
            return None

        # Enforce minimum gap between ANY yf calls
        elapsed = now - _yf_last_call
        if elapsed < _yf_min_gap:
            time.sleep(_yf_min_gap - elapsed)
            now = time.time()

    try:
        with _yf_lock:
            _yf_last_call = time.time()
            # Sliding window enforcement
            _yf_call_times.append(_yf_last_call)
            cutoff = _yf_last_call - 60
            while _yf_call_times and _yf_call_times[0] < cutoff:
                _yf_call_times.pop(0)
            # If we've made > 6 calls in the last 60s, wait
            if len(_yf_call_times) > 6:
                wait = 60 - (_yf_last_call - _yf_call_times[0]) + 0.5
                if wait > 0:
                    time.sleep(wait)
        df = yf.download(ticker, **kwargs, session=_YF_SESSION)
        # Empty result on a normally-working ticker = soft rate limit
        if df is None or (hasattr(df, "empty") and df.empty):
            with _yf_lock:
                _yf_rate_limited_until = time.time() + _yf_backoff
                _yf_backoff = min(_yf_backoff * 2, _YF_BACKOFF_MAX)
                _yf_symbol_cooldown[ticker] = _yf_rate_limited_until
                print(f"[YF EMPTY] {ticker} — backoff {_yf_backoff}s (treat as rate-limit)")
            return None
        # On success, set short per-ticker cooldown so we don't re-hit it
        with _yf_lock:
            _yf_symbol_cooldown[ticker] = time.time() + 20
            # Successful call → reduce backoff gradually
            _yf_backoff = max(60, _yf_backoff // 2)
        return df
    except Exception as e:
        err_str = str(e).lower()
        if ("rate" in err_str or "too many" in err_str or "429" in err_str):
            with _yf_lock:
                _yf_rate_limited_until = time.time() + _yf_backoff
                _yf_backoff = min(_yf_backoff * 2, _YF_BACKOFF_MAX)
                # Also freeze this ticker for the same backoff window
                _yf_symbol_cooldown[ticker] = _yf_rate_limited_until
                print(f"[YF BAN] {ticker} — backoff {_yf_backoff}s")
        raise

def get_price(symbol):
    """
    Lightweight price fetch — uses 1m interval over 1 day.
    Caches for _price_ttl seconds. Returns None on any failure.
    """
    now = time.time()
    if symbol in _price_cache:
        price, ts = _price_cache[symbol]
        if now - ts < _price_ttl:
            # move to end (LRU)
            _price_cache.move_to_end(symbol)
            return price
    # If rate-limited globally, return stale cached value rather than None
    if now < _yf_rate_limited_until:
        if symbol in _price_cache:
            print(f"[YF CACHE] {symbol} — using stale cache (rate-limited)")
            return _price_cache[symbol][0]
        return None

    try:
        df = _throttled_yf_download(
            symbol, period="1d", interval="5m",
            progress=False, auto_adjust=True
        )
        if df is None or df.empty:
            return None
        df = normalise_cols(df)
        if "Close" not in df.columns or df["Close"].empty:
            trim_dataframe(df)
            return None
        price = float(df["Close"].iloc[-1])
        _price_cache[symbol] = (price, now)
        # Bound the cache size
        if len(_price_cache) > MAX_PRICE_CACHE:
            _price_cache.popitem(last=False)
        trim_dataframe(df)
        return price
    except Exception as e:
        print(f"[ERR] get_price {symbol}: {e}")
        return None

# ============================================================
#  INDICATORS
# ============================================================
def calculate_atr(df, period=10):
    high_low = df["High"] - df["Low"]
    high_cp  = (df["High"] - df["Close"].shift(1)).abs()
    low_cp   = (df["Low"]  - df["Close"].shift(1)).abs()
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def normalise_cols(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def get_rsi(df, period=14):
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

# ============================================================
#  STRATEGY 1 — SWEEP + ENGULFING
# ============================================================
def check_sweep_engulfing(ticker):
    try:
        df = _throttled_yf_download(
            ticker, period="10d", interval="1h",
            progress=False, auto_adjust=True
        )
        if df is None or df.empty or len(df) < 30:
            trim_dataframe(df) if df is not None else None
            return None
        df = normalise_cols(df)

        is_nifty = "^NSEI" in ticker or "^NSEBANK" in ticker
        if is_nifty:
            df_target = df
        else:
            df_target = (
                df.resample("4h")
                  .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
                  .dropna()
            )
            trim_dataframe(df)

        if len(df_target) < 4:
            trim_dataframe(df_target)
            return None

        curr   = df_target.iloc[-2]
        mother = df_target.iloc[-3]
        ts = int(df_target.index[-2].timestamp() * 1000)
        price = float(curr["Close"])

        if curr["Low"] < mother["Low"] and curr["High"] > mother["High"] and curr["Close"] > mother["High"]:
            sl = float(curr["Low"])
            risk = price - sl
            if risk <= 0:
                trim_dataframe(df_target)
                return None
            tp = price + (risk * 2.0)
            trim_dataframe(df_target)
            return ("BULLISH", price, sl, tp, ts)

        if curr["High"] > mother["High"] and curr["Low"] < mother["Low"] and curr["Close"] < mother["Low"]:
            sl = float(curr["High"])
            risk = sl - price
            if risk <= 0:
                trim_dataframe(df_target)
                return None
            tp = price - (risk * 2.0)
            trim_dataframe(df_target)
            return ("BEARISH", price, sl, tp, ts)

        trim_dataframe(df_target)
    except Exception as e:
        print("[ERR] Sweep " + ticker + ": " + str(e))
    return None

# ============================================================
#  STRATEGY 2 — UT BOT
# ============================================================
def check_ut_bot(ticker, kv=2):
    try:
        df_15 = _throttled_yf_download(
            ticker, period="3d", interval="15m",
            progress=False, auto_adjust=True
        )
        if df_15 is None or df_15.empty or len(df_15) < 20:
            trim_dataframe(df_15) if df_15 is not None else None
            return None
        df_15 = normalise_cols(df_15)

        df_5 = _throttled_yf_download(
            ticker, period="1d", interval="5m",
            progress=False, auto_adjust=True
        )
        if df_5 is None or df_5.empty or len(df_5) < 40:
            trim_dataframe(df_15); trim_dataframe(df_5) if df_5 is not None else None
            return None
        df_5 = normalise_cols(df_5)

        df_15["xATR"]  = calculate_atr(df_15, 10)
        df_15["nLoss"] = kv * df_15["xATR"]

        src    = df_15["Close"].values
        nLoss  = df_15["nLoss"].values
        ts_arr = np.zeros(len(df_15))
        pos    = np.zeros(len(df_15))

        for i in range(1, len(df_15)):
            prev_ts, prev_src = ts_arr[i - 1], src[i - 1]
            if   src[i] > prev_ts and prev_src > prev_ts:
                ts_arr[i] = max(prev_ts, src[i] - nLoss[i])
            elif src[i] < prev_ts and prev_src < prev_ts:
                ts_arr[i] = min(prev_ts, src[i] + nLoss[i])
            elif src[i] > prev_ts:
                ts_arr[i] = src[i] - nLoss[i]
            else:
                ts_arr[i] = src[i] + nLoss[i]

            if   prev_src < prev_ts and src[i] > ts_arr[i]:
                pos[i] = 1
            elif prev_src > prev_ts and src[i] < ts_arr[i]:
                pos[i] = -1
            else:
                pos[i] = pos[i - 1]

        i = len(df_15) - 2
        is_buy  = (src[i] > ts_arr[i]) and (src[i - 1] <= ts_arr[i - 1])
        is_sell = (src[i] < ts_arr[i]) and (src[i - 1] >= ts_arr[i - 1])

        df_5["EMA50"]  = df_5["Close"].ewm(span=50, adjust=False).mean()
        df_15["RSI"]   = get_rsi(df_15)

        m5_close = float(df_5["Close"].iloc[-2])
        m5_ema   = float(df_5["EMA50"].iloc[-2])
        rsi_15   = float(df_15["RSI"].iloc[-2])
        ts       = int(df_15.index[-2].timestamp() * 1000)
        atr_val  = float(df_15["xATR"].iloc[i])

        if is_buy and m5_close > m5_ema and rsi_15 > 50:
            sl = m5_close - (atr_val * ATR_MULT_SL)
            tp = m5_close + (atr_val * ATR_MULT_TP)
            trim_dataframe(df_15); trim_dataframe(df_5)
            return ("BULLISH", m5_close, sl, tp, ts)

        if is_sell and m5_close < m5_ema and rsi_15 < 50:
            sl = m5_close + (atr_val * ATR_MULT_SL)
            tp = m5_close - (atr_val * ATR_MULT_TP)
            trim_dataframe(df_15); trim_dataframe(df_5)
            return ("BEARISH", m5_close, sl, tp, ts)

        trim_dataframe(df_15); trim_dataframe(df_5)
        return None
    except Exception as e:
        print("[ERR] UT Bot " + ticker + ": " + str(e))
        return None

# ============================================================
#  SHARED TRADE-CLOSE HELPER (eliminates 3x duplication)
# ============================================================
def _finalize_trade_close(trade_to_close, live):
    """
    Centralized close: updates account, removes from active, appends to history,
    writes CSV, sends Telegram message. Caller must hold _lock around the
    initial `if trade_to_close in active_trades: ... remove` and pass it in.
    """
    account_name = trade_to_close["account"]
    is_long      = trade_to_close["type"] == "LONG"
    pnl          = ((live - trade_to_close["entry"]) * trade_to_close["qty"]
                   if is_long else
                   (trade_to_close["entry"] - live) * trade_to_close["qty"])

    accounts[account_name]["balance"] += pnl
    trade_to_close["exit_price"] = live
    trade_to_close["pnl"]        = float(pnl)
    trade_to_close["result"]     = "WIN" if pnl > 0 else "LOSS"
    trade_to_close["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    bal = accounts[account_name]["balance"]

    save_json(ACCOUNTS_FILE, accounts)
    save_json(ACTIVE_TRADES_FILE, active_trades)

    history = load_json(HISTORY_FILE, [])
    history.append(trade_to_close)
    if len(history) > MAX_HISTORY:
        history = history[-HISTORY_JSON_CAP:]
    save_json(HISTORY_FILE, history)

    _log_trade_to_csv(trade_to_close)
    msg = msg_trade_closed(trade_to_close, live, float(pnl), bal, is_long, pnl > 0)
    safe_send_message(CHAT_ID, msg, parse_mode="Markdown")
    return pnl, bal

# ============================================================
#  SCANNER & MONITOR
# ============================================================
def scanner_loop():
    global _last_scan_time, _yf_rate_limited_until, _yf_backoff
    # Wait 90s after boot so we don't slam YF on cold start
    print("[SCAN] Waiting 90s before first scan to let the bot settle...")
    time.sleep(90)
    while True:
        now = time.time()
        if now - _last_scan_time < 300:
            time.sleep(15)
            continue
        if now < _yf_rate_limited_until:
            wait = int(_yf_rate_limited_until - now) + 5
            print(f"[SCAN SKIP] YF rate-limited, next attempt in {wait}s")
            time.sleep(min(wait, 120))
            continue
        _last_scan_time = now
        # Reset backoff on successful scan start
        with _yf_lock:
            _yf_backoff = 300  # start conservative

        for symbol, mtype in MONITORED:
            if not is_market_open(symbol):
                continue
            try:
                time.sleep(8)
                ut = check_ut_bot(symbol)
                time.sleep(3)
                sweep = check_sweep_engulfing(symbol)

                signals_found = []
                if ut:     signals_found.append(("UT Bot", ut))
                if sweep:  signals_found.append(("Sweep", sweep))

                for strat_name, sig in signals_found:
                    sig_type, price, sl, tp, ts = sig
                    key = f"{symbol}_{strat_name}_{ts}"

                    with _lock:
                        if key in sent_signals:
                            continue
                        sent_signals[key] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
                        # Bound the cache
                        if len(sent_signals) > MAX_SENT_SIGNALS:
                            # drop oldest by re-inserting newest half
                            kept = list(sent_signals.items())[-MAX_SENT_SIGNALS // 2:]
                            sent_signals.clear()
                            sent_signals.update(kept)
                        save_json(SENT_SIGNALS_FILE, sent_signals)

                        if symbol in muted_assets:
                            continue

                        account = "macro"
                        if "^NSE" in symbol:
                            account = "nifty"
                        elif strat_name == "UT Bot":
                            account = "ny_session"
                        elif strat_name == "Sweep":
                            account = "sweep_4h"

                        if accounts[account]["daily_trades"] >= ACCOUNT_LIMITS[account]:
                            continue

                        risk_amt = accounts[account]["balance"] * 0.01
                        risk = abs(price - sl)
                        if risk <= 0:
                            continue
                        qty = risk_amt / risk

                        trade = {
                            "symbol":   symbol,
                            "account":  account,
                            "strat":    strat_name,
                            "type":     "LONG" if "BULLISH" in sig_type else "SHORT",
                            "entry":    price,
                            "sl":       sl,
                            "tp":       tp,
                            "trail_sl": sl,
                            "qty":      qty,
                            "open_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M"),
                        }
                        active_trades.append(trade)
                        accounts[account]["daily_trades"] += 1
                        save_json(ACCOUNTS_FILE, accounts)
                        save_json(ACTIVE_TRADES_FILE, active_trades)

                        tf = "15m" if strat_name == "UT Bot" else "4H"
                        msg = msg_trade_signal(
                            symbol, mtype, strat_name, sig_type, tf,
                            price, sl, tp, qty, risk_amt, account
                        )
                        safe_send_message(CHAT_ID, msg, parse_mode="Markdown")
            except Exception as e:
                print(f"[ERR] Scanner {symbol}: {e}")

        # Aggressive RAM cleanup between cycles
        gc.collect()
        time.sleep(120)

def monitor_trades():
    while True:
        time.sleep(60)
        with _lock:
            trades = list(active_trades)
        if not trades:
            continue
        prices = {}
        for t in trades:
            sym = t["symbol"]
            if sym not in prices:
                prices[sym] = get_price(sym)
                time.sleep(2)
            live = prices[sym]
            if not live:
                continue
            is_long = t["type"] == "LONG"
            pnl = ((live - t["entry"]) * t["qty"]
                   if is_long else
                   (t["entry"] - live) * t["qty"])

            hit_sl = hit_tp = False
            if is_long:
                if   live <= t["trail_sl"]: hit_sl = True
                elif live >= t["tp"]:       hit_tp = True
            else:
                if   live >= t["trail_sl"]: hit_sl = True
                elif live <= t["tp"]:       hit_tp = True

            if hit_sl or hit_tp:
                with _lock:
                    if t not in active_trades:
                        continue
                    active_trades.remove(t)
                    _finalize_trade_close(t, live)
                # Drop references so the loop can move on without holding the dict
                del t
        # cleanup
        del trades
        gc.collect()

def daily_reset_loop():
    while True:
        now = datetime.now(IST)
        target = now.replace(hour=0, minute=5, second=0, microsecond=0)
        if now > target:
            target += timedelta(days=1)
        time.sleep((target - now).total_seconds())
        with _lock:
            for acc in accounts:
                accounts[acc]["daily_trades"] = 0
            accounts["last_reset_date"] = datetime.now(IST).strftime("%Y-%m-%d")
            save_json(ACCOUNTS_FILE, accounts)
            print("[RESET] Daily trade counters reset")

# ============================================================
#  FLASK APP
# ============================================================
flask_app = Flask(__name__)

@flask_app.route("/ping")
def ping():
    return "pong"

@flask_app.route("/")
def home():
    return "Trading Bot OK"

@flask_app.route("/api/balance")
def api_balance():
    with _lock:
        return jsonify({
            "macro":      accounts.get("macro",      {"balance": 100000, "daily_trades": 0}),
            "nifty":      accounts.get("nifty",      {"balance": 100000, "daily_trades": 0}),
            "ny_session": accounts.get("ny_session", {"balance": 100000, "daily_trades": 0}),
            "sweep_4h":   accounts.get("sweep_4h",   {"balance": 100000, "daily_trades": 0}),
        })

@flask_app.route("/api/active")
def api_active():
    with _lock:
        return jsonify({"trades": list(active_trades), "count": len(active_trades)})

@flask_app.route("/api/history")
def api_history():
    hist = load_json(HISTORY_FILE, [])
    return jsonify({"trades": hist[-50:]})

@flask_app.route("/api/summary")
def api_summary():
    hist = load_json(HISTORY_FILE, [])
    total_wins = sum(1 for t in hist if t.get("result") == "WIN")
    total_loss = sum(1 for t in hist if t.get("result") == "LOSS")
    total_pnl  = sum(float(t.get("pnl", 0)) for t in hist)
    return jsonify({
        "total_trades": len(hist),
        "wins":         total_wins,
        "losses":       total_loss,
        "win_rate":     (total_wins / (total_wins + total_loss) * 100) if (total_wins + total_loss) > 0 else 0,
        "total_pnl":    total_pnl,
        "active_count": len(active_trades),
    })

@flask_app.route("/api/export")
def api_export():
    if not os.path.exists(TRADE_LOG_CSV) or os.path.getsize(TRADE_LOG_CSV) == 0:
        return "No trade log available yet.", 404
    return send_file(TRADE_LOG_CSV, as_attachment=True, download_name="trade_log.csv")

@flask_app.route("/api/clear", methods=["POST"])
def api_clear():
    global active_trades, sent_signals
    with _lock:
        active_trades = []
        for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
            accounts[acc] = {"balance": 100000.0, "daily_trades": 0}
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, [])
        save_json(HISTORY_FILE, [])
        sent_signals = {}
        save_json(SENT_SIGNALS_FILE, sent_signals)
    return jsonify({"success": True})

@flask_app.route("/api/close/<symbol>", methods=["POST"])
def api_close_symbol(symbol):
    target_symbol = symbol.upper()
    with _lock:
        trade_to_close = next((t for t in active_trades if t["symbol"].upper() == target_symbol), None)
        if not trade_to_close:
            return jsonify({"success": False, "error": "No active trade found"}), 404

    live = get_price(target_symbol)
    if not live:
        return jsonify({"success": False, "error": "Price fetch failed"}), 500

    with _lock:
        if trade_to_close not in active_trades:
            return jsonify({"success": False, "error": "Trade already closed"}), 409
        active_trades.remove(trade_to_close)
        pnl, bal = _finalize_trade_close(trade_to_close, live)
    return jsonify({"success": True, "pnl": float(pnl), "balance": bal,
                    "result": trade_to_close["result"]})

@flask_app.route("/dashboard")
def dashboard():
    return DASHBOARD_HTML

# ============================================================
#  TELEGRAM BOT
# ============================================================
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")

def menu_markup():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("🔍 Check Markets", callback_data="cmd_check"))
    m.add(InlineKeyboardButton("📊 Asset Summary", callback_data="cmd_summary"))
    return m

@bot.message_handler(commands=["start", "help"])
def cmd_start(m):
    safe_send_message(m.chat.id, msg_guide(), parse_mode="Markdown", reply_markup=menu_markup())

@bot.message_handler(commands=["check"])
def cmd_check(m):
    chat_id = m.chat.id
    safe_send_message(chat_id, msg_scanning(), parse_mode="Markdown")

    def run_scan():
        try:
            signals, neutral = [], []
            for symbol, mtype in MONITORED:
                if not is_market_open(symbol):
                    neutral.append(f"⚪ `{symbol}` — Market Closed")
                    time.sleep(2)
                    continue
                ut = check_ut_bot(symbol)
                time.sleep(2)
                sweep = check_sweep_engulfing(symbol)
                if ut:
                    signals.append(f"🟢 `{symbol}` ➔ 🟣 UT Bot *{ut[0]}* `${ut[1]:,.4f}`")
                if sweep:
                    signals.append(f"🟢 `{symbol}` ➔ 🔵 Sweep *{sweep[0]}* `${sweep[1]:,.4f}`")
                if not ut and not sweep:
                    neutral.append(f"⚪ `{symbol}` — No Setup")
                time.sleep(2)
            safe_send_message(chat_id, msg_scan_results(signals, neutral), parse_mode="Markdown")
        except Exception as e:
            safe_send_message(chat_id, msg_error("Market Scan", str(e)), parse_mode="Markdown")
        finally:
            gc.collect()

    threading.Thread(target=run_scan, daemon=True).start()

@bot.message_handler(commands=["summary"])
def cmd_summary(m):
    try:
        lines = []
        for symbol, mtype in MONITORED:
            is_muted = symbol in muted_assets
            status = "🔇 Muted" if is_muted else "🟢 Active"
            price = get_price(symbol)
            icon = "🔴" if is_muted else "🟢"
            if price:
                lines.append(f"{icon} `{symbol}` · {mtype} · `${price:,.4f}` · {status}")
            else:
                lines.append(f"{icon} `{symbol}` · {mtype} · {status}")
            time.sleep(2)
        safe_send_message(m.chat.id, msg_summary(lines), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Asset Summary", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    try:
        history = load_json(HISTORY_FILE, [])
        def stats(acc):
            ts = [x for x in history if x["account"] == acc]
            w  = [x for x in ts if x["result"] == "WIN"]
            l  = [x for x in ts if x["result"] == "LOSS"]
            p  = sum(float(x["pnl"]) for x in ts)
            wr = len(w) / (len(w) + len(l)) * 100 if (w or l) else 0
            return len(w), len(l), p, wr
        mw, ml, mp, mwr     = stats("macro")
        nw, nl, np_, nwr    = stats("nifty")
        nyw, nyl, nyp, nywr = stats("ny_session")
        sw, sl, sp, swr     = stats("sweep_4h")
        safe_send_message(
            m.chat.id,
            msg_stats(mw, ml, mp, mwr, nw, nl, np_, nwr, nyw, nyl, nyp, nywr, sw, sl, sp, swr),
            parse_mode="Markdown", reply_markup=menu_markup()
        )
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Performance Stats", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["active"])
def cmd_active(m):
    try:
        with _lock:
            trades = list(active_trades)
        if not trades:
            safe_send_message(m.chat.id, msg_no_active_trades(), parse_mode="Markdown")
            return
        trades_list = []
        total_pnl = 0.0
        prices = {}
        for t in trades:
            symbol = t["symbol"]
            if symbol not in prices:
                prices[symbol] = get_price(symbol)
                time.sleep(2)
            trades_list.append(build_trade_block(t, prices[symbol]))
            live = prices[symbol]
            is_long = t["type"] == "LONG"
            if live:
                pnl = ((live - t["entry"]) * t["qty"]
                       if is_long else
                       (t["entry"] - live) * t["qty"])
                total_pnl += pnl
        safe_send_message(m.chat.id, msg_active_trades(trades_list, total_pnl), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Active Trades", str(e)), parse_mode="Markdown")
    finally:
        gc.collect()

@bot.message_handler(commands=["close"])
def cmd_close(m):
    try:
        parts = m.text.split()
        if len(parts) < 2:
            safe_send_message(
                m.chat.id,
                msg_error("Manual Close", "Provide a symbol. Example: /close BTC-USD"),
                parse_mode="Markdown"
            )
            return
        target_symbol = parts[1].upper()
        with _lock:
            trade_to_close = next((t for t in active_trades if t["symbol"].upper() == target_symbol), None)
        if not trade_to_close:
            safe_send_message(
                m.chat.id,
                msg_error("Manual Close", f"No active trade found for {target_symbol}"),
                parse_mode="Markdown"
            )
            return
        live = get_price(target_symbol)
        if not live:
            safe_send_message(
                m.chat.id,
                msg_error("Manual Close", f"Could not fetch current price for {target_symbol}"),
                parse_mode="Markdown"
            )
            return
        with _lock:
            if trade_to_close not in active_trades:
                return
            active_trades.remove(trade_to_close)
            pnl, bal = _finalize_trade_close(trade_to_close, live)
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Manual Close", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["export"])
def cmd_export(m):
    try:
        if not os.path.exists(TRADE_LOG_CSV) or os.path.getsize(TRADE_LOG_CSV) == 0:
            safe_send_message(
                m.chat.id, msg_error("Export", "No trade log available yet."), parse_mode="Markdown"
            )
            return
        with open(TRADE_LOG_CSV, "r", encoding="utf-8") as f:
            count = max(0, sum(1 for _ in f) - 1)
        with open(TRADE_LOG_CSV, "rb") as doc:
            bot.send_document(m.chat.id, doc, caption=msg_export_ready(count), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Export", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["balance"])
def cmd_balance(m):
    try:
        with _lock:
            macro_bal  = accounts["macro"]["balance"]
            nifty_bal  = accounts["nifty"]["balance"]
            ny_bal     = accounts["ny_session"]["balance"]
            sweep_bal  = accounts.get("sweep_4h", {"balance": 100000.0})["balance"]
            macro_d    = accounts["macro"]["daily_trades"]
            nifty_d    = accounts["nifty"]["daily_trades"]
            ny_d       = accounts["ny_session"]["daily_trades"]
            sweep_d    = accounts.get("sweep_4h", {"daily_trades": 0})["daily_trades"]
            ny_active  = is_ny_session()
            trades     = list(active_trades)
        prices = {}
        u_pnl = {"macro": 0.0, "nifty": 0.0, "ny_session": 0.0, "sweep_4h": 0.0}
        for t in trades:
            sym = t["symbol"]
            if sym not in prices:
                prices[sym] = get_price(sym)
                time.sleep(2)
            live = prices[sym]
            if not live:
                continue
            if t["type"] == "LONG":
                u_pnl[t["account"]] += (live - t["entry"]) * t["qty"]
            else:
                u_pnl[t["account"]] += (t["entry"] - live) * t["qty"]
        safe_send_message(
            m.chat.id,
            msg_balance(macro_bal, nifty_bal, ny_bal, sweep_bal, macro_d, nifty_d, ny_d, sweep_d,
                        ACCOUNT_LIMITS["macro"], ACCOUNT_LIMITS["nifty"],
                        ACCOUNT_LIMITS["ny_session"], ACCOUNT_LIMITS["sweep_4h"],
                        ny_active, u_pnl),
            parse_mode="Markdown", reply_markup=menu_markup()
        )
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Balance Query", str(e)), parse_mode="Markdown")
    finally:
        gc.collect()

@bot.message_handler(commands=["clear"])
def cmd_clear(m):
    global active_trades, sent_signals
    try:
        with _lock:
            active_trades = []
            for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
                accounts[acc] = {"balance": 100000.0, "daily_trades": 0}
            save_json(ACCOUNTS_FILE, accounts)
            save_json(ACTIVE_TRADES_FILE, [])
            save_json(HISTORY_FILE, [])
            sent_signals = {}
            save_json(SENT_SIGNALS_FILE, sent_signals)
        safe_send_message(m.chat.id, msg_cleared(), parse_mode="Markdown")
    except Exception as e:
        safe_send_message(m.chat.id, msg_error("Account Clear", str(e)), parse_mode="Markdown")

@bot.message_handler(commands=["indi1"])
def cmd_indi1(m):
    chat_id = m.chat.id
    safe_send_message(chat_id, msg_indi_diagnosing(1), parse_mode="Markdown")

    def run_diag():
        try:
            results = []
            for symbol, mtype in MONITORED:
                if not is_market_open(symbol):
                    continue
                res = check_sweep_engulfing(symbol)
                if res:
                    sig, price = res[0], res[1]
                    icon = "🟢" if "BULLISH" in sig else "🔴"
                    results.append(f"{icon} `{symbol}` → {sig} @ {price:.2f}")
                else:
                    results.append(f"⚪ `{symbol}` → No Setup")
                time.sleep(3)
            has_signals = any("BULLISH" in r or "BEARISH" in r for r in results)
            if has_signals:
                full_text = "\n".join(results)
                for i in range(0, len(full_text), 4000):
                    safe_send_message(chat_id, full_text[i:i+4000], parse_mode="Markdown")
            else:
                safe_send_message(chat_id, msg_indi_no_signals(1), parse_mode="Markdown")
        except Exception as e:
            safe_send_message(chat_id, msg_error("Strategy 1 Diagnosis", str(e)), parse_mode="Markdown")
        finally:
            gc.collect()

    threading.Thread(target=run_diag, daemon=True).start()

@bot.message_handler(commands=["indi2"])
def cmd_indi2(m):
    chat_id = m.chat.id
    safe_send_message(chat_id, msg_indi_diagnosing(2), parse_mode="Markdown")

    def run_diag():
        try:
            results = []
            for symbol, mtype in MONITORED:
                if not is_market_open(symbol):
                    continue
                res = check_ut_bot(symbol)
                if res:
                    sig, price = res[0], res[1]
                    icon = "🟢" if "BULLISH" in sig else "🔴"
                    results.append(f"{icon} `{symbol}` → {sig} @ {price:.2f}")
                else:
                    results.append(f"⚪ `{symbol}` → No Setup")
                time.sleep(3)
            has_signals = any("BULLISH" in r or "BEARISH" in r for r in results)
            if has_signals:
                full_text = "\n".join(results)
                for i in range(0, len(full_text), 4000):
                    safe_send_message(chat_id, full_text[i:i+4000], parse_mode="Markdown")
            else:
                safe_send_message(chat_id, msg_indi_no_signals(2), parse_mode="Markdown")
        except Exception as e:
            safe_send_message(chat_id, msg_error("Strategy 2 Diagnosis", str(e)), parse_mode="Markdown")
        finally:
            gc.collect()

    threading.Thread(target=run_diag, daemon=True).start()

@bot.message_handler(func=lambda m: True)
def cmd_fallback(m):
    if m.text.startswith("/"):
        return
    safe_send_message(m.chat.id, msg_guide(), parse_mode="Markdown", reply_markup=menu_markup())

# ============================================================
#  CALLBACK HANDLERS
# ============================================================
@bot.callback_query_handler(func=lambda c: True)
def handle_cb(c):
    try:
        if c.data == "cmd_check":
            cmd_check(c.message)
        elif c.data == "cmd_summary":
            cmd_summary(c.message)
        elif c.data.startswith("chart_"):
            sym = c.data.split("_", 1)[1]
            bot.answer_callback_query(c.id, text="Generating chart...")
            buf = generate_chart(sym)
            if buf:
                bot.send_photo(c.message.chat.id, buf, caption=f"📈 `{sym}` | 1H Chart", parse_mode="Markdown")
            else:
                safe_send_message(c.message.chat.id, msg_chart_failed(), parse_mode="Markdown")
        elif c.data.startswith("mute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.add(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(
                InlineKeyboardButton(f"🔊 Unmute {sym}", callback_data=f"unmute_{sym}"))
            bot.edit_message_text(
                msg_muted(sym), c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=m)
        elif c.data.startswith("unmute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.discard(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(
                InlineKeyboardButton(f"🔇 Mute {sym}", callback_data=f"mute_{sym}"))
            bot.edit_message_text(
                msg_unmuted(sym), c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=m)
    except Exception as e:
        print("[ERR] Callback: " + str(e))
        try:
            bot.answer_callback_query(c.id)
        except Exception:
            pass

# ============================================================
#  CHART GENERATION
# ============================================================
def generate_chart(symbol, tf="1h"):
    try:
        df = _throttled_yf_download(symbol, period="3d", interval=tf,
                                    progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        df = normalise_cols(df)

        fig, ax = plt.subplots(figsize=(8, 4), facecolor="#0d1117", dpi=70)
        ax.set_facecolor("#0d1117")

        x = np.arange(len(df))
        close = df["Close"].to_numpy()
        open_ = df["Open"].to_numpy()
        high  = df["High"].to_numpy()
        low   = df["Low"].to_numpy()
        colors = np.where(close >= open_, "#00ff88", "#ff4444")

        ax.vlines(x, low, high, color=colors, linewidth=1)
        body_h = np.abs(close - open_) + 1e-8
        body_b = np.minimum(open_, close)
        ax.bar(x, body_h, bottom=body_b, width=0.6, color=colors, linewidth=0)

        ax.set_title(f"{symbol} | {tf.upper()}", color="white", fontsize=11, fontweight="bold")
        ax.tick_params(colors="gray", labelsize=6)
        for spine in ax.spines.values():
            spine.set_color("#30363d")
        ax.grid(True, color="#21262d", linestyle="--", linewidth=0.5)
        plt.tight_layout()

        buf = BytesIO()
        plt.savefig(buf, format="png", facecolor="#0d1117", optimize=True)
        buf.seek(0)
        plt.close(fig)
        trim_dataframe(df)
        return buf
    except Exception as e:
        print(f"[ERR] Chart {symbol}: {e}")
        try: plt.close()
        except Exception: pass
        return None

# ============================================================
#  DASHBOARD HTML
# ============================================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Trading Bot Dashboard</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Oxygen,Ubuntu,Cantarell,sans-serif;background:#0d1117;color:#c9d1d9;padding:20px;max-width:900px;margin:0 auto}
  h1{color:#58a6ff;margin-bottom:8px;font-size:24px}
  .subtitle{color:#8b949e;font-size:12px;margin-bottom:20px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
  .card h3{font-size:14px;color:#8b949e;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.5px}
  .value{font-size:22px;font-weight:700;color:#e6edf3}
  .value.positive{color:#3fb950}.value.negative{color:#f85149}.value.neutral{color:#8b949e}
  .btn{background:#238636;color:#fff;border:none;padding:8px 14px;border-radius:6px;cursor:pointer;font-size:13px;margin-right:6px;margin-top:6px}
  .btn:hover{background:#2ea043}.btn.secondary{background:#21262d;border:1px solid #30363d;color:#c9d1d9}
  .btn.secondary:hover{background:#30363d}
  .section{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
  .section h2{font-size:16px;margin-bottom:12px;color:#e6edf3}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;color:#8b949e;padding:8px;border-bottom:1px solid #30363d;font-weight:600}
  td{padding:8px;border-bottom:1px solid #21262d}
  .badge{font-size:11px;padding:2px 8px;border-radius:12px;background:#30363d;color:#c9d1d9}
  .badge.long{background:#23863633;color:#3fb950}.badge.short{background:#f8514933;color:#f85149}
  .empty{text-align:center;padding:24px;color:#8b949e}
  .toast{position:fixed;bottom:20px;right:20px;background:#238636;color:#fff;padding:10px 16px;border-radius:6px;font-size:13px;opacity:0;transition:opacity .3s}
  .toast.show{opacity:1}.toast.error{background:#f85149}
</style>
</head>
<body>
<h1>⚡ Trading Bot Dashboard</h1>
<div class="subtitle">Status: <span id="connStatus" class="value neutral">Loading...</span> | Auto-refresh: 15s</div>

<div class="grid">
  <div class="card"><h3>Macro Balance</h3><div class="value" id="balMacro">--</div></div>
  <div class="card"><h3>Nifty Balance</h3><div class="value" id="balNifty">--</div></div>
  <div class="card"><h3>NY Session</h3><div class="value" id="balNY">--</div></div>
  <div class="card"><h3>Sweep 4H</h3><div class="value" id="balSweep">--</div></div>
</div>

<div class="section">
  <h2>📋 Open Positions (<span id="activeCount">0</span>)</h2>
  <div id="activeContainer"><div class="empty">Loading...</div></div>
</div>

<div class="section">
  <h2>📈 Recent History</h2>
  <div id="historyContainer"><div class="empty">Loading...</div></div>
</div>

<div class="section">
  <h2>🔔 Actions</h2>
  <button class="btn" onclick="loadAll()">🔄 Refresh</button>
  <button class="btn secondary" onclick="exportCSV()">📥 Export CSV</button>
  <button class="btn secondary" onclick="clearAll()">🗑 Reset All</button>
</div>

<div id="toast" class="toast"></div>

<script>
async function fetchJSON(url, opts={}) {
  try {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
    return await r.json();
  } catch (e) {
    console.error('API Error:', e);
    showToast('API Error: ' + e.message, true);
    return null;
  }
}

function showToast(msg, isErr) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast' + (isErr ? ' error' : '') + ' show';
  setTimeout(() => t.className = 'toast' + (isErr ? ' error' : ''), 2500);
}

async function loadBalances() {
  const d = await fetchJSON('/api/balance');
  if (!d) return;
  document.getElementById('balMacro').textContent = '₹' + (d.macro?.balance || 0).toLocaleString('en-IN', {maximumFractionDigits:2});
  document.getElementById('balNifty').textContent = '₹' + (d.nifty?.balance || 0).toLocaleString('en-IN', {maximumFractionDigits:2});
  document.getElementById('balNY').textContent = '₹' + (d.ny_session?.balance || 0).toLocaleString('en-IN', {maximumFractionDigits:2});
  document.getElementById('balSweep').textContent = '₹' + (d.sweep_4h?.balance || 0).toLocaleString('en-IN', {maximumFractionDigits:2});
}

async function loadActive() {
  const d = await fetchJSON('/api/active');
  if (!d) return;
  const el = document.getElementById('activeContainer');
  document.getElementById('activeCount').textContent = d.count || 0;
  if (!d.trades || d.trades.length === 0) {
    el.innerHTML = '<div class="empty">No open positions</div>';
    return;
  }
  let html = '<table><tr><th>Symbol</th><th>Account</th><th>Type</th><th>Entry</th><th>SL</th><th>TP</th><th>Qty</th></tr>';
  for (const t of d.trades) {
    const badge = t.type === 'LONG' ? 'long' : 'short';
    html += `<tr>
      <td><b>${t.symbol}</b></td>
      <td>${t.account}</td>
      <td><span class="badge ${badge}">${t.type}</span></td>
      <td>₹${t.entry?.toLocaleString?.() || t.entry}</td>
      <td>₹${t.sl?.toLocaleString?.() || t.sl}</td>
      <td>₹${t.tp?.toLocaleString?.() || t.tp}</td>
      <td>${t.qty}</td>
    </tr>`;
  }
  html += '</table>';
  el.innerHTML = html;
}

async function loadHistory() {
  const d = await fetchJSON('/api/history');
  if (!d) return;
  const el = document.getElementById('historyContainer');
  if (!d.trades || d.trades.length === 0) {
    el.innerHTML = '<div class="empty">No history yet</div>';
    return;
  }
  let html = '<table><tr><th>Time</th><th>Symbol</th><th>Account</th><th>Type</th><th>PnL</th><th>Result</th></tr>';
  for (const t of (d.trades || []).slice().reverse()) {
    const pnlClass = t.pnl > 0 ? 'positive' : (t.pnl < 0 ? 'negative' : 'neutral');
    html += `<tr>
      <td>${t.close_time || '-'}</td>
      <td>${t.symbol}</td>
      <td>${t.account}</td>
      <td>${t.type}</td>
      <td class="${pnlClass}">₹${Number(t.pnl).toLocaleString('en-IN', {maximumFractionDigits:2})}</td>
      <td><span class="badge ${t.result==='WIN'?'long':'short'}">${t.result}</span></td>
    </tr>`;
  }
  html += '</table>';
  el.innerHTML = html;
}

function exportCSV() {
  window.location.href = '/api/export';
}

async function clearAll() {
  if (!confirm('Reset ALL accounts to ₹1,00,000? This wipes history and active trades.')) return;
  showToast('Resetting...');
  const r = await fetchJSON('/api/clear', {method:'POST'});
  if (r && r.success) {
    showToast('All accounts reset');
    loadAll();
  } else {
    showToast('Reset failed', true);
  }
}

async function loadAll() {
  await Promise.all([loadBalances(), loadActive(), loadHistory()]);
  document.getElementById('connStatus').textContent = 'Live';
  document.getElementById('connStatus').className = 'value positive';
}

loadAll();
setInterval(loadAll, 15000);
</script>
</body>
</html>"""

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
    sent_signals  = load_json(SENT_SIGNALS_FILE, {})

    # Single webhook cleanup (was duplicated: remove_webhook + delete_webhook)
    try:
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(1)
    except Exception as e:
        print(f"[WARN] Webhook cleanup: {e}")

    print("=" * 50)
    print("  Trading Bot Starting...")
    print("  Macro:      ₹" + f"{accounts['macro']['balance']:,.2f}")
    print("  Nifty:      ₹" + f"{accounts['nifty']['balance']:,.2f}")
    print("  NY Session: ₹" + f"{accounts['ny_session']['balance']:,.2f}")
    print("  Dashboard:  /dashboard")
    print("  Web server: :" + str(PORT))
    print("=" * 50)

    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=monitor_trades, daemon=True).start()
    threading.Thread(target=daily_reset_loop, daemon=True).start()

    def run_flask():
        flask_app.run(host="0.0.0.0", port=PORT, threaded=True)

    threading.Thread(target=run_flask, daemon=True).start()

    print("[BOT] Connecting to Telegram...")
    backoff = 5
    while True:
        try:
            bot.polling(skip_pending=True, timeout=60, long_polling_timeout=10)
            backoff = 5
        except Exception as e:
            print("[ERR] Polling crashed: " + str(e))
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)
