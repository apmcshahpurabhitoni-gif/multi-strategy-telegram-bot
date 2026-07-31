import os
import json
import time
import threading
import gc
from datetime import datetime
from io import BytesIO
from wsgiref.simple_server import make_server

import requests
import numpy as np
import pandas as pd
import yfinance as yf
import pytz
import telebot
import matplotlib
import matplotlib.pyplot as plt
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

matplotlib.use("Agg")
plt.style.use("dark_background")

# ============================================================
# CONFIG
# ============================================================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set!")
if not CHAT_ID:
    raise ValueError("TELEGRAM_CHAT_ID not set!")

# Files
ACCOUNTS_FILE = "/workspace/accounts.json"
ACTIVE_TRADES_FILE = "/workspace/active_trades.json"
HISTORY_FILE = "/workspace/trade_history.json"
MUTE_FILE = "/workspace/muted_assets.json"
SENT_SIGNALS_FILE = "/workspace/sent_signals.json"

ACCOUNT_LIMITS = {
    "macro": 20,
    "nifty": 3,
    "ny_session": 3,
    "sweep_4h": 3,
}

accounts = {}
active_trades = []
muted_assets = set()
sent_signals = {}
_lock = threading.RLock()
_chart_lock = threading.RLock()
_price_cache = {}
IST = pytz.timezone("Asia/Kolkata")

# Yahoo Finance session with headers to avoid cloud blocking
_yf_session = requests.Session()
_yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

BR = "━━━━━━━━━━━━━━━━━━━━━━"
BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ============================================================
# MESSAGES
# ============================================================
def msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, actual_sl, actual_tp, qty, risk_amt, account, signal_time_str):
    arrow = "🟢🟢🟢" if "BULLISH" in sig_type else "🔴🔴🔴"
    label = "🚀 STRONG BULLISH" if "BULLISH" in sig_type else "💥 STRONG BEARISH"
    dir_ = "LONG 📈" if "BULLISH" in sig_type else "SHORT 📉"
    return (
        f"⚡ *ALERT — HIGH CONFLUENCE SIGNAL*\n"
        f"{BR}\n"
        f"{arrow} *{label}*\n"
        f"{BR}\n"
        f"🪙 *Asset:* `{symbol}`\n"
        f"🌐 *Market:* {mtype}\n"
        f"🎯 *Strategy:* {strat}\n"
        f"📊 *Direction:* {dir_}\n"
        f"⏱ *Timeframe:* {tf}\n"
        f"{BR}\n"
        f"⏰ *SIGNAL GENERATED AT:*\n"
        f"🔔 `{signal_time_str}`\n"
        f"{BR}\n"
        f"💼 *PAPER TRADE EXECUTED*\n"
        f"{BR}\n"
        f"🏢 *Account:* `{account.upper()}`\n"
        f"📍 *Entry:* `${price:,.4f}`\n"
        f"🛑 *Stop Loss:* `${actual_sl:,.4f}`\n"
        f"🎯 *Take Profit:* `${actual_tp:,.4f}`\n"
        f"📦 *Quantity:* `{qty:.4f}`\n"
        f"💸 *Risk:* `₹{risk_amt:,.2f}`\n"
        f"{BR2}"
    )

def msg_trade_closed(trade, live, pnl, bal, is_long, hit_tp):
    result = "🎉 WIN" if hit_tp else "💀 LOSS"
    icon = "✅" if hit_tp else "❌"
    arrow = "📈" if hit_tp else "📉"
    money = "💰" if hit_tp else "💸"
    dir_ = "LONG 🟢" if is_long else "SHORT 🔴"
    pnl_s = f"+₹{pnl:,.2f}" if hit_tp else f"-₹{abs(pnl):,.2f}"
    return (
        f"{icon} *TRADE CLOSED — {result}*\n"
        f"{BR}\n"
        f"{'🟢' if is_long else '🔴'} *{trade['symbol']}* | {dir_}\n"
        f"🎯 *Strategy:* {trade['strat']}\n"
        f"🏢 *Account:* `{trade['account'].upper()}`\n"
        f"{BR}\n"
        f"📍 *Entry:* `${trade['entry']:,.4f}`\n"
        f"{arrow} *Exit:* `${live:,.4f}`\n"
        f"🛑 *SL Hit:* `${trade['trail_sl']:,.4f}`\n"
        f"🎯 *TP Target:* `${trade['tp']:,.4f}`\n"
        f"{BR}\n"
        f"{money} *P/L:* `{pnl_s}`\n"
        f"🏦 *Balance:* `₹{bal:,.2f}`\n"
        f"{BR2}"
    )

def msg_midnight_reset(day_pnl, macro_bal, nifty_bal, ny_bal, sweep_bal):
    pnl_icon = "📈" if day_pnl >= 0 else "📉"
    pnl_sign = "+" if day_pnl >= 0 else ""
    return (
        f"🌙 *MIDNIGHT RESET*\n"
        f"{BR}\n"
        f"{pnl_icon} *Yesterday P/L:* `{pnl_sign}₹{day_pnl:,.2f}`\n"
        f"{BR}\n"
        f"🏦 *Account Balances:*\n"
        f"├ 🌐 *Macro:* `₹{macro_bal:,.2f}`\n"
        f"├ 🇮🇳 *Nifty:* `₹{nifty_bal:,.2f}`\n"
        f"├ 🇺🇸 *NY Session:* `₹{ny_bal:,.2f}`\n"
        f"└ 🔵 *Sweep 4H:* `₹{sweep_bal:,.2f}`\n"
        f"{BR}\n"
        f"🔄 *Daily trade limits reset*\n"
        f"🧹 *Signal cache cleaned*\n"
        f"{BR2}"
    )

def msg_guide():
    return (
        f"🤖 *TRADING BOT — COMMAND CENTER*\n"
        f"{BR}\n"
        f"📘 *COMMANDS:*\n"
        f"├ `/start` — Show this guide\n"
        f"├ `/test` — Test data fetch (debug)\n"
        f"├ `/check` — Scan all assets now\n"
        f"├ `/summary` — Live prices & status\n"
        f"├ `/stats` — Win rate & P/L report\n"
        f"├ `/balance` — Virtual account balances\n"
        f"├ `/clear` — Reset all to ₹1,00,000\n"
        f"├ `/indi1` — Diagnose Strategy 1 (Sweep)\n"
        f"└ `/indi2` — Diagnose Strategy 2 (UT Bot)\n"
        f"{BR2}"
    )

def msg_error(context, error):
    return f"⚠️ *ERROR — {context}*\n{BR}\n❌ `{error}`\n{BR2}"

# ============================================================
# WEB SERVER
# ============================================================
def run_web():
    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [b"Trading Bot OK"]
    PORT = int(os.environ.get("PORT", 10000))
    make_server("0.0.0.0", PORT, app).serve_forever()

threading.Thread(target=run_web, daemon=True).start()

# ============================================================
# BOT — threaded=False to prevent 409 Conflict on Render
# ============================================================
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown", threaded=False)

def load_json(fp, default):
    try:
        if os.path.exists(fp):
            with open(fp) as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(fp, data):
    try:
        with open(fp, "w") as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass

def safe_send(chat_id, text, **kwargs):
    try:
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        print(f"[ERR] send failed: {e}")
        try:
            bot.send_message(chat_id, text.replace("*","").replace("`","").replace("_",""), parse_mode=None)
        except Exception as e2:
            print(f"[ERR] fallback failed: {e2}")

def init_accounts():
    global accounts
    defaults = {
        "macro": {"balance": 100000.0, "daily_trades": 0},
        "nifty": {"balance": 100000.0, "daily_trades": 0},
        "ny_session": {"balance": 100000.0, "daily_trades": 0},
        "sweep_4h": {"balance": 100000.0, "daily_trades": 0},
    }
    accounts = load_json(ACCOUNTS_FILE, defaults)
    for k, v in defaults.items():
        if k not in accounts:
            accounts[k] = v
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if accounts.get("last_reset_date") != today:
        for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
            accounts[acc]["daily_trades"] = 0
        accounts["last_reset_date"] = today
        save_json(ACCOUNTS_FILE, accounts)

def is_ny_session():
    h = datetime.now(IST).hour
    m = datetime.now(IST).minute
    return h >= 18 or (h == 1 and m <= 30) or h == 0

def is_nifty_open():
    n = datetime.now(IST)
    if n.weekday() >= 5:
        return False
    return 555 <= (n.hour * 60 + n.minute) <= 930

def is_market_open(symbol):
    n = datetime.now(IST)
    w, tm = n.weekday(), n.hour * 60 + n.minute
    if symbol in ("BTC-USD", "GC=F"):
        return True
    if symbol in ("EURUSD=X", "GBPUSD=X", "USDJPY=X"):
        return w < 5
    if symbol in ("^NSEI", "^NSEBANK"):
        return w < 5 and 555 <= tm <= 930
    return False

# ============================================================
# YFINANCE HELPERS (cloud-safe)
# ============================================================
def yf_download(symbol, period, interval):
    try:
        df = yf.download(
            symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
            threads=False,
            session=_yf_session,
        )
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
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
    df = yf_download(symbol, "1d", "1m")
    if df is None or df.empty:
        return None
    p = float(df["Close"].iloc[-1])
    _price_cache[symbol] = (p, now)
    return p

# ============================================================
# INDICATORS
# ============================================================
def calc_atr(df, period=10):
    hl = df["High"] - df["Low"]
    hc = np.abs(df["High"] - df["Close"].shift(1))
    lc = np.abs(df["Low"] - df["Close"].shift(1))
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()

def get_rsi(df, period=14):
    d = df["Close"].diff()
    g = d.clip(lower=0).rolling(period).mean()
    l = (-d.clip(upper=0)).rolling(period).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

# ============================================================
# STRATEGY 1 — SWEEP + ENGULFING
# ============================================================
def check_sweep(ticker):
    try:
        is_nifty = "^NSE" in ticker
        interval = "1h" if is_nifty else "4h"
        period = "10d" if is_nifty else "30d"
        df = yf_download(ticker, period, interval)
        if df is None or df.empty or len(df) < 10:
            print(f"[WARN] Sweep {ticker}: no data")
            return None
        if not is_nifty:
            df = df.resample("4h").agg({"Open":"first","High":"max","Low":"min","Close":"last"}).dropna()
        if len(df) < 4:
            return None
        c = df.iloc[-2]
        m = df.iloc[-3]
        ts = int(df.index[-2].timestamp() * 1000)
        price = float(c["Close"])
        if c["Low"] < m["Low"] and c["High"] > m["High"] and c["Close"] > m["High"]:
            sl = float(c["Low"])
            risk = price - sl
            if risk <= 0:
                return None
            return ("BULLISH", price, sl, price + risk * 2.0, ts)
        if c["High"] > m["High"] and c["Low"] < m["Low"] and c["Close"] < m["Low"]:
            sl = float(c["High"])
            risk = sl - price
            if risk <= 0:
                return None
            return ("BEARISH", price, sl, price - risk * 2.0, ts)
    except Exception as e:
        print(f"[ERR] Sweep {ticker}: {e}")
    return None

# ============================================================
# STRATEGY 2 — UT BOT
# ============================================================
def check_ut(ticker, kv=2):
    try:
        df15 = yf_download(ticker, "3d", "15m")
        df5 = yf_download(ticker, "1d", "5m")
        if df15 is None or len(df15) < 20 or df5 is None or len(df5) < 40:
            print(f"[WARN] UT {ticker}: no data")
            return None
        df15["xATR"] = calc_atr(df15, 1)
        df15["nLoss"] = kv * df15["xATR"]
        src = df15["Close"].values
        nl = df15["nLoss"].values
        ts_arr = np.zeros(len(df15))
        for i in range(1, len(df15)):
            pts, ps = ts_arr[i-1], src[i-1]
            if src[i] > pts and ps > pts:
                ts_arr[i] = max(pts, src[i] - nl[i])
            elif src[i] < pts and ps < pts:
                ts_arr[i] = min(pts, src[i] + nl[i])
            elif src[i] > pts:
                ts_arr[i] = src[i] - nl[i]
            else:
                ts_arr[i] = src[i] + nl[i]
        i = len(df15) - 2
        buy = src[i] > ts_arr[i] and src[i-1] <= ts_arr[i-1]
        sell = src[i] < ts_arr[i] and src[i-1] >= ts_arr[i-1]
        df5["EMA50"] = df5["Close"].ewm(span=50, adjust=False).mean()
        df15["RSI"] = get_rsi(df15)
        m5c = float(df5["Close"].iloc[-2])
        m5e = float(df5["EMA50"].iloc[-2])
        rsi = float(df15["RSI"].iloc[-2])
        ts = int(df15.index[-2].timestamp() * 1000)
        atr = float(df15["xATR"].iloc[i])
        if buy and m5c > m5e and rsi < 70:
            return ("BULLISH", float(src[i]), atr, ts)
        if sell and m5c < m5e and rsi > 30:
            return ("BEARISH", float(src[i]), atr, ts)
    except Exception as e:
        print(f"[ERR] UT {ticker}: {e}")
    return None

# ============================================================
# TRADE EXECUTION
# ============================================================
def calc_sl_tp(sig, entry, atr):
    if "BULLISH" in sig:
        return entry - atr * 2, entry + atr * 4
    return entry + atr * 2, entry - atr * 4

def calc_qty(account, entry, sl):
    with _lock:
        bal = accounts[account]["balance"]
    risk = bal * 0.02
    dist = abs(entry - sl)
    return 0.0 if dist == 0 else float(risk / dist)

def format_signal_time(ts_ms):
    """Convert timestamp (ms) to bold IST string."""
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=IST)
        return dt.strftime("%d-%b-%Y %H:%M IST")
    except Exception:
        return "Unknown"

def execute(symbol, mtype, account, strat, sig_type, price, a1, a2, a3=None):
    global active_trades
    if "Sweep" in strat:
        sl, tp, ts = float(a1), float(a2), a3
    else:
        atr, ts = float(a1), a2
        sl, tp = calc_sl_tp(sig_type, price, atr)
    with _lock:
        key = f"{symbol}_{ts}_{sig_type}_{account}"
        if key in sent_signals:
            return
        sent_signals[key] = True
        save_json(SENT_SIGNALS_FILE, sent_signals)
        lim = ACCOUNT_LIMITS.get(account, 3)
        if accounts[account]["daily_trades"] >= lim:
            return
        if any(t["symbol"] == symbol and t["account"] == account for t in active_trades):
            return
        qty = calc_qty(account, price, sl)
        if qty <= 0:
            return
        tf = "1H" if ("Sweep" in strat and "^NSE" in symbol) else ("4H" if "Sweep" in strat else "15m")
        trade = {
            "id": f"{symbol}_{int(time.time())}",
            "symbol": symbol, "market": mtype, "account": account,
            "strat": strat, "type": "LONG" if "BULLISH" in sig_type else "SHORT",
            "entry": float(price), "sl": float(sl), "tp": float(tp),
            "qty": float(qty), "trail_sl": float(sl),
            "ts_trigger": ts,
            "time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        }
        active_trades.append(trade)
        accounts[account]["daily_trades"] += 1
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, active_trades)
    risk = abs(price - sl) * qty
    signal_time_str = format_signal_time(ts)
    msg = msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, sl, tp, qty, risk, account, signal_time_str)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📈 Chart", callback_data=f"chart_{symbol}"),
               InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}"))
    safe_send(CHAT_ID, msg, parse_mode="Markdown", reply_markup=markup)
    print(f"[TRADE] {trade['type']} {symbol} @ {price} | Signal: {signal_time_str}")

# ============================================================
# MONITOR TRADES
# ============================================================
def monitor():
    global active_trades
    while True:
        if not active_trades:
            time.sleep(15)
            continue
        to_close = []
        with _lock:
            copy = list(active_trades)
        for t in copy:
            try:
                df = yf_download(t["symbol"], "1d", "1m")
                if df is None or df.empty:
                    continue
                live = float(df["Close"].iloc[-1])
                long = t["type"] == "LONG"
                if long:
                    pct = (live - t["entry"]) / t["entry"] * 100
                else:
                    pct = (t["entry"] - live) / t["entry"] * 100
                if pct >= 1.0:
                    if long:
                        t["trail_sl"] = max(t["trail_sl"], t["entry"] + (live - t["entry"]) * 0.5)
                    else:
                        t["trail_sl"] = min(t["trail_sl"], t["entry"] - (t["entry"] - live) * 0.5)
                hit_tp = (long and live >= t["tp"]) or (not long and live <= t["tp"])
                hit_sl = (long and live <= t["trail_sl"]) or (not long and live >= t["trail_sl"])
                if not (hit_tp or hit_sl):
                    continue
                pnl = abs(t["tp"] - t["entry"]) * t["qty"] if hit_tp else -(abs(t["entry"] - t["trail_sl"]) * t["qty"])
                with _lock:
                    accounts[t["account"]]["balance"] += pnl
                    t["exit_price"] = live
                    t["pnl"] = float(pnl)
                    t["result"] = "WIN" if hit_tp else "LOSS"
                    t["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
                    to_close.append(t)
                    save_json(ACCOUNTS_FILE, accounts)
                hist = load_json(HISTORY_FILE, [])
                hist.append(t)
                save_json(HISTORY_FILE, hist)
                with _lock:
                    bal = accounts[t["account"]]["balance"]
                safe_send(CHAT_ID, msg_trade_closed(t, live, pnl, bal, long, hit_tp), parse_mode="Markdown")
                print(f"[CLOSE] {t['symbol']} {t['result']} {pnl:+.2f}")
            except Exception as e:
                print(f"[ERR] Monitor {t['symbol']}: {e}")
        if to_close:
            with _lock:
                for x in to_close:
                    try:
                        active_trades.remove(x)
                    except ValueError:
                        pass
                save_json(ACTIVE_TRADES_FILE, active_trades)
        time.sleep(15)

# ============================================================
# SCANNER
# ============================================================
MONITORED = [
    ("BTC-USD", "Crypto"),
    ("GC=F", "Gold"),
    ("EURUSD=X", "Forex"),
    ("GBPUSD=X", "Forex"),
    ("USDJPY=X", "Forex"),
    ("^NSEI", "NIFTY 50"),
    ("^NSEBANK", "BANK NIFTY"),
]

def get_acc(symbol):
    return "nifty" if ("NSEI" in symbol or "BANK" in symbol) else "macro"

def scanner():
    print("[SCANNER] Started")
    while True:
        try:
            for symbol, mtype in MONITORED:
                with _lock:
                    if symbol in muted_assets or not is_market_open(symbol):
                        continue
                acc = get_acc(symbol)
                if acc == "nifty" and not is_nifty_open():
                    continue
                ut = check_ut(symbol)
                if ut:
                    target = "ny_session" if is_ny_session() else "macro"
                    execute(symbol, mtype, target, "UT Bot Signals", ut[0], ut[1], ut[2], ut[3])
                sweep = check_sweep(symbol)
                if sweep:
                    execute(symbol, mtype, "sweep_4h", "Sweep + Engulfing", sweep[0], sweep[1], sweep[2], sweep[3], sweep[4])
                time.sleep(2)
            gc.collect()
        except Exception as e:
            print(f"[ERR] Scanner: {e}")
            safe_send(CHAT_ID, msg_error("Scanner", str(e)), parse_mode="Markdown")
        time.sleep(300)

# ============================================================
# DAILY RESET
# ============================================================
def daily_reset():
    last = datetime.now(IST).strftime("%Y-%m-%d")
    while True:
        now = datetime.now(IST)
        today = now.strftime("%Y-%m-%d")
        if last != today:
            with _lock:
                for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
                    accounts[acc]["daily_trades"] = 0
                accounts["last_reset_date"] = today
                save_json(ACCOUNTS_FILE, accounts)
                global sent_signals
                if len(sent_signals) > 500:
                    sent_signals = {k: sent_signals[k] for k in list(sent_signals.keys())[-500:]}
                save_json(SENT_SIGNALS_FILE, sent_signals)
                hist = load_json(HISTORY_FILE, [])
                day_trades = [t for t in hist if t.get("close_time", "").startswith(last)]
                day_pnl = sum(float(t["pnl"]) for t in day_trades)
                safe_send(CHAT_ID, msg_midnight_reset(
                    day_pnl,
                    accounts["macro"]["balance"],
                    accounts["nifty"]["balance"],
                    accounts["ny_session"]["balance"],
                    accounts["sweep_4h"]["balance"]
                ), parse_mode="Markdown")
                if len(hist) > 500:
                    save_json(HISTORY_FILE, hist[-500:])
            last = today
            gc.collect()
        time.sleep(60)

# ============================================================
# TELEGRAM HANDLERS
# ============================================================
@bot.message_handler(commands=["start", "help"])
def cmd_start(m):
    safe_send(m.chat.id, msg_guide(), parse_mode="Markdown")

@bot.message_handler(commands=["test"])
def cmd_test(m):
    chat_id = m.chat.id
    safe_send(chat_id, "🔍 *Testing data fetch...*\nThis may take 10 seconds.")
    def run():
        results = []
        for symbol, mtype in MONITORED:
            try:
                df = yf_download(symbol, "1d", "1m")
                if df is None or df.empty:
                    results.append(f"❌ `{symbol}` — NO DATA (blocked/empty)")
                else:
                    price = float(df["Close"].iloc[-1])
                    results.append(f"✅ `{symbol}` — `${price:,.4f}`")
            except Exception as e:
                results.append(f"❌ `{symbol}` — ERROR: {str(e)[:50]}")
            time.sleep(1)
        body = "\n".join(results)
        safe_send(chat_id, f"📊 *DATA FETCH TEST RESULTS*\n{BR}\n{body}\n{BR}\n💡 If all show ❌, Yahoo is blocking Render. Run this bot locally or on a VPS.", parse_mode="Markdown")
    threading.Thread(target=run, daemon=True).start()

@bot.message_handler(commands=["check"])
def cmd_check(m):
    chat_id = m.chat.id
    safe_send(chat_id, "🔍 *Scanning markets...*")
    def run():
        signals, neutral = [], []
        for symbol, mtype in MONITORED:
            ut = check_ut(symbol)
            sw = check_sweep(symbol)
            if ut:
                signals.append(f"🟢 `{symbol}` ➔ UT Bot *{ut[0]}*")
            elif sw:
                signals.append(f"🟢 `{symbol}` ➔ Sweep *{sw[0]}*")
            else:
                neutral.append(f"⚪ `{symbol}` — No Setup")
            time.sleep(1)
        header = f"🔥 *{len(signals)} SIGNAL{'S' if len(signals)>1 else ''} FOUND*" if signals else "⏳ *NO ACTIVE SETUPS*"
        body = "\n".join(signals) if signals else "\n".join(neutral)
        safe_send(chat_id, f"🔍 *SCAN COMPLETE*\n{BR}\n{header}\n{BR}\n{body}\n{BR2}", parse_mode="Markdown")
    threading.Thread(target=run, daemon=True).start()

@bot.message_handler(commands=["summary"])
def cmd_summary(m):
    lines = []
    for symbol, mtype in MONITORED:
        muted = "🔇 Muted" if symbol in muted_assets else "🟢 Active"
        p = get_price(symbol)
        if p:
            lines.append(f"🟢 `{symbol}` · {mtype} · `${p:,.4f}` · {muted}")
        else:
            lines.append(f"🔴 `{symbol}` · {mtype} · {muted}")
        time.sleep(0.5)
    safe_send(m.chat.id, f"📊 *LIVE SUMMARY*\n{BR}\n{'\n'.join(lines)}\n{BR}\n🕐 `{datetime.now(IST).strftime('%H:%M:%S IST')}`\n{BR2}", parse_mode="Markdown")

@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    hist = load_json(HISTORY_FILE, [])
    def st(acc):
        ts = [x for x in hist if x["account"] == acc]
        w = sum(1 for x in ts if x["result"] == "WIN")
        l = sum(1 for x in ts if x["result"] == "LOSS")
        p = sum(float(x["pnl"]) for x in ts)
        wr = w / (w + l) * 100 if (w + l) else 0
        return w, l, p, wr
    mw, ml, mp, mwr = st("macro")
    nw, nl, np_, nwr = st("nifty")
    nyw, nyl, nyp, nywr = st("ny_session")
    sw, sl, sp, swr = st("sweep_4h")
    def line(e, n, w, l, p, wr):
        s = "+" if p >= 0 else ""
        c = "🟢" if p >= 0 else "🔴"
        return f"{e} *{n}*\n {c} `{w}W / {l}L` · WR: `{wr:.0f}%` · P/L: `{s}₹{p:,.2f}`"
    text = (
        f"📊 *PERFORMANCE*\n{BR}\n"
        f"{line('🌐','Macro',mw,ml,mp,mwr)}\n{BR}\n"
        f"{line('🇮🇳','Nifty',nw,nl,np_,nwr)}\n{BR}\n"
        f"{line('🇺🇸','NY Session',nyw,nyl,nyp,nywr)}\n{BR}\n"
        f"{line('🔵','Sweep 4H',sw,sl,sp,swr)}\n{BR2}"
    )
    safe_send(m.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=["balance"])
def cmd_balance(m):
    with _lock:
        mb = accounts["macro"]["balance"]
        nb = accounts["nifty"]["balance"]
        nyb = accounts["ny_session"]["balance"]
        sb = accounts.get("sweep_4h", {"balance": 100000.0})["balance"]
        md = accounts["macro"]["daily_trades"]
        nd = accounts["nifty"]["daily_trades"]
        nyd = accounts["ny_session"]["daily_trades"]
        sd = accounts.get("sweep_4h", {"daily_trades": 0})["daily_trades"]
    ny = is_ny_session()
    text = (
        f"🏦 *BALANCES*\n{BR}\n"
        f"🌐 *Macro* — `₹{mb:,.2f}` · Trades: `{md}/{ACCOUNT_LIMITS['macro']}`\n"
        f"🇮🇳 *Nifty* — `₹{nb:,.2f}` · Trades: `{nd}/{ACCOUNT_LIMITS['nifty']}`\n"
        f"🇺🇸 *NY* — `₹{nyb:,.2f}` · Trades: `{nyd}/{ACCOUNT_LIMITS['ny_session']}`\n"
        f"🔵 *Sweep* — `₹{sb:,.2f}` · Trades: `{sd}/{ACCOUNT_LIMITS['sweep_4h']}`\n"
        f"{BR}\n{'🟢' if ny else '🔴'} *NY Session:* `{'ACTIVE' if ny else 'INACTIVE'}`\n"
        f"🕐 `{datetime.now(IST).strftime('%H:%M:%S IST')}`\n{BR2}"
    )
    safe_send(m.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=["clear"])
def cmd_clear(m):
    global active_trades
    with _lock:
        active_trades = []
        for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
            accounts[acc] = {"balance": 100000.0, "daily_trades": 0}
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, [])
        save_json(HISTORY_FILE, [])
    safe_send(m.chat.id, f"🗑 *RESET DONE*\n{BR}\n✅ All balances → `₹1,00,000`\n✅ Trades closed\n✅ History wiped\n✅ Counters reset\n{BR2}", parse_mode="Markdown")

@bot.message_handler(commands=["indi1"])
def cmd_indi1(m):
    chat_id = m.chat.id
    safe_send(chat_id, "🔵 *Diagnosing Strategy 1 (Sweep)...*")
    def run():
        out = []
        for symbol, _ in MONITORED:
            if not is_market_open(symbol):
                continue
            r = check_sweep(symbol)
            out.append(f"{'🟢' if r else '⚪'} `{symbol}` → {r[0] if r else 'No Setup'}")
            time.sleep(1)
        safe_send(chat_id, "🔵 *STRATEGY 1 RESULTS*\n" + "\n".join(out), parse_mode="Markdown")
    threading.Thread(target=run, daemon=True).start()

@bot.message_handler(commands=["indi2"])
def cmd_indi2(m):
    chat_id = m.chat.id
    safe_send(chat_id, "🟣 *Diagnosing Strategy 2 (UT Bot)...*")
    def run():
        out = []
        for symbol, _ in MONITORED:
            if not is_market_open(symbol):
                continue
            r = check_ut(symbol)
            out.append(f"{'🟢' if r else '⚪'} `{symbol}` → {r[0] if r else 'No Setup'}")
            time.sleep(1)
        safe_send(chat_id, "🟣 *STRATEGY 2 RESULTS*\n" + "\n".join(out), parse_mode="Markdown")
    threading.Thread(target=run, daemon=True).start()

@bot.message_handler(func=lambda m: True)
def fallback(m):
    if m.text.startswith("/"):
        return
    safe_send(m.chat.id, msg_guide(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: True)
def cb(c):
    try:
        if c.data.startswith("chart_"):
            sym = c.data.split("_", 1)[1]
            bot.answer_callback_query(c.id, "Generating chart...")
            buf = gen_chart(sym)
            if buf:
                bot.send_photo(c.message.chat.id, buf, caption=f"📈 `{sym}`")
            else:
                safe_send(c.message.chat.id, "❌ Chart failed")
        elif c.data.startswith("mute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.add(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(InlineKeyboardButton(f"🔊 Unmute {sym}", callback_data=f"unmute_{sym}"))
            bot.edit_message_text(f"🔇 `{sym}` muted.", c.message.chat.id, c.message.message_id, reply_markup=m)
        elif c.data.startswith("unmute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.discard(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(InlineKeyboardButton(f"🔇 Mute {sym}", callback_data=f"mute_{sym}"))
            bot.edit_message_text(f"🔊 `{sym}` unmuted.", c.message.chat.id, c.message.message_id, reply_markup=m)
    except Exception as e:
        print(f"[ERR] CB: {e}")

# ============================================================
# CHART
# ============================================================
def gen_chart(symbol, tf="1h"):
    with _chart_lock:
        try:
            df = yf_download(symbol, "3d", tf)
            if df is None or df.empty:
                return None
            fig, ax = plt.subplots(figsize=(10, 5), facecolor="#0d1117", dpi=50)
            ax.set_facecolor("#0d1117")
            x = np.arange(len(df))
            c = df["Close"].to_numpy()
            o = df["Open"].to_numpy()
            h = df["High"].to_numpy()
            l = df["Low"].to_numpy()
            colors = np.where(c >= o, "#00ff88", "#ff4444")
            ax.vlines(x, l, h, color=colors, linewidth=1)
            bh = np.abs(c - o) + 1e-8
            bb = np.minimum(o, c)
            ax.bar(x, bh, bottom=bb, width=0.6, color=colors, linewidth=0)
            ax.set_title(f"{symbol} | {tf.upper()}", color="white", fontsize=12, fontweight="bold")
            ax.tick_params(colors="gray", labelsize=6)
            for sp in ax.spines.values():
                sp.set_color("#30363d")
            ax.grid(True, color="#21262d", linestyle="--", linewidth=0.5)
            plt.tight_layout()
            buf = BytesIO()
            plt.savefig(buf, format="png", facecolor="#0d1117")
            buf.seek(0)
            plt.close(fig)
            return buf
        except Exception as e:
            print(f"[ERR] Chart: {e}")
            plt.close()
            return None

# ============================================================
# BOOT
# ============================================================
if __name__ == "__main__":
    init_accounts()
    muted_assets.update(load_json(MUTE_FILE, []))
    active_trades = load_json(ACTIVE_TRADES_FILE, [])
    sent_signals = load_json(SENT_SIGNALS_FILE, {})

    print("=" * 50)
    print(" Trading Bot Starting...")
    print(f" Macro: ₹{accounts['macro']['balance']:,.2f}")
    print(f" Nifty: ₹{accounts['nifty']['balance']:,.2f}")
    print(f" NY Session: ₹{accounts['ny_session']['balance']:,.2f}")
    print(f" Web server: :{os.environ.get('PORT', 10000)}/ping")
    print("=" * 50)

    safe_send(CHAT_ID, "🤖 *Bot started on Render!*\nUse `/test` to check if data fetching works.", parse_mode="Markdown")

    threading.Thread(target=scanner, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=daily_reset, daemon=True).start()

    print("[BOT] Polling Telegram...")
    # FIXED: threaded=False + none_stop=True prevents 409 Conflict
    bot.polling(none_stop=True, interval=3, timeout=60)
