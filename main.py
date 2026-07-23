import os
import json
import time
import csv
import threading
import logging
from datetime import datetime
from io import BytesIO

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
#  CONFIG
# ============================================================
TOKEN          = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID        = os.environ.get("TELEGRAM_CHAT_ID")
RR_RATIO       = float(os.environ.get("RR", "2.0"))
ATR_MULT_SL    = 1.5
ATR_MULT_TP    = 3.0
MIN_VOLATILITY = 0.3

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set!")

# Files
ACCOUNTS_FILE      = "accounts.json"
ACTIVE_TRADES_FILE = "active_trades.json"
HISTORY_FILE       = "trade_history.json"
MUTE_FILE          = "muted_assets.json"
TRADE_LOG_CSV      = "trade_log.csv"
PEAKS_FILE         = "peaks.json"

# Globals
accounts      = {}
active_trades = []
trade_history = []
muted_assets  = set()
sent_signals  = {}
peaks         = {}

_lock       = threading.Lock()
_chart_lock = threading.Lock()
_price_cache = {}

IST = pytz.timezone("Asia/Kolkata")

# ============================================================
#  BOT — instantiated BEFORE handlers
# ============================================================
bot = telebot.TeleBot(TOKEN, parse_mode="Markdown")

# ============================================================
#  HELPERS — FILES
# ============================================================
def load_json(filepath, default):
    try:
        if os.path.exists(filepath):
            with open(filepath) as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[WARN] Could not save {filepath}: {e}")

def save_peaks():
    save_json(PEAKS_FILE, peaks)

def load_peaks():
    return load_json(PEAKS_FILE, {})

# ============================================================
#  HELPERS — ACCOUNTS
# ============================================================
def init_accounts():
    global accounts, peaks
    defaults = {
        "macro":      {"balance": 100000.0, "daily_trades": 0},
        "nifty":      {"balance": 100000.0, "daily_trades": 0},
        "ny_session": {"balance": 100000.0, "daily_trades": 0},
    }
    accounts = load_json(ACCOUNTS_FILE, defaults)
    peaks = load_peaks()
    for acc in defaults:
        if acc not in peaks:
            peaks[acc] = accounts[acc]["balance"]
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if accounts.get("last_reset_date") != today:
            accounts[acc]["daily_trades"] = 0
    accounts["last_reset_date"] = datetime.now(IST).strftime("%Y-%m-%d")
    save_json(ACCOUNTS_FILE, accounts)

# ============================================================
#  HELPERS — TIME
# ============================================================
def is_ny_session():
    now = datetime.now(IST)
    h, m = now.hour, now.minute
    return h >= 18 or (h == 1 and m <= 30) or h == 0

def is_nifty_market_open():
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    total_min = now.hour * 60 + now.minute
    return 555 <= total_min <= 930

def is_forex_session():
    now = datetime.now(IST)
    h, m = now.hour, now.minute
    total = h * 60 + m
    return total >= 18 * 60 + 30 or total <= 3 * 60 + 30

# ============================================================
#  HELPERS — PRICE CACHE
# ============================================================
def get_cached_price(symbol, force=False):
    now = time.time()
    if not force and symbol in _price_cache:
        price, ts = _price_cache[symbol]
        if now - ts < 55:
            return price
    try:
        df = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
        if df.empty:
            return None
        price = float(df["Close"].iloc[-1])
        _price_cache[symbol] = (price, now)
        return price
    except Exception:
        return None

# ============================================================
#  HELPERS — PUSH NOTIFICATIONS
# ============================================================
def pushbullet_notify(text):
    try:
        token = os.environ.get("PUSHBULLET_TOKEN")
        if not token:
            return
        clean = (
            text.replace("*", "").replace("`", "").replace("_", "")
                .replace("[", "(").replace("]", ")")
                .replace("━", "-").replace("├", "|").replace("└", "|")
        )
        requests.post(
            "https://api.pushbullet.com/v2/pushes",
            json={"type": "note", "title": "Trading Bot", "body": clean},
            headers={"Access-Token": token}, timeout=5
        )
    except Exception:
        pass

# ============================================================
#  INDICATORS
# ============================================================
def calculate_atr(df, period=10):
    high_low = df["High"] - df["Low"]
    high_cp  = np.abs(df["High"] - df["Close"].shift(1))
    low_cp   = np.abs(df["Low"]  - df["Close"].shift(1))
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()

def is_volatile_enough(df, min_pct=MIN_VOLATILITY):
    try:
        atr   = float(calculate_atr(df, 10).iloc[-1])
        price = float(df["Close"].iloc[-1])
        return (atr / price * 100) >= min_pct
    except Exception:
        return True

def get_rsi(df, period=14):
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def normalise_cols(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

# ============================================================
#  STRATEGY 1 — SWEEP + ENGULFING + INSIDE BAR (4H)
# ============================================================
def check_sweep_engulfing(ticker):
    try:
        df = yf.download(ticker, period="1mo", interval="1h",
                         progress=False, auto_adjust=True)
        df = normalise_cols(df)
        if df.empty or len(df) < 40:
            return None

        if not is_volatile_enough(df):
            return None

        df_4h = (
            df.resample("4h")
            .agg({"Open": "first", "High": "max",
                  "Low": "min",   "Close": "last"})
            .dropna()
        )
        if len(df_4h) < 5:
            return None

        df_4h["ATR"] = calculate_atr(df_4h, 10)
        atr = float(df_4h["ATR"].iloc[-2])

        curr = df_4h.iloc[-2]
        off = 1
        for lookback in range(2, min(8, len(df_4h) - 1)):
            mother = df_4h.iloc[-lookback - 1]
            inside = (
                curr["High"] < mother["High"] and
                curr["Low"]  > mother["Low"]
            )
            if not inside:
                off = lookback
                break
        mother = df_4h.iloc[-off - 1]

        ts = int(df_4h.index[-2].timestamp() * 1000)

        if curr["Low"] < mother["Low"] and curr["Close"] > mother["High"]:
            return ("BULLISH", float(curr["Close"]), atr, ts)
        if curr["High"] > mother["High"] and curr["Close"] < mother["Low"]:
            return ("BEARISH", float(curr["Close"]), atr, ts)

    except Exception as e:
        print(f"[ERR] Sweep strategy {ticker}: {e}")
    return None

# ============================================================
#  STRATEGY 2 — UT BOT (15m + 5m EMA filter)
# ============================================================
def check_ut_bot(ticker, kv=2, atr_period=1):
    try:
        df_15 = yf.download(ticker, period="5d", interval="15m",
                            progress=False, auto_adjust=True)
        df_5  = yf.download(ticker, period="5d", interval="5m",
                            progress=False, auto_adjust=True)
        df_15 = normalise_cols(df_15)
        df_5  = normalise_cols(df_5)

        if df_15.empty or len(df_15) < 30 or df_5.empty or len(df_5) < 50:
            return None

        if not is_volatile_enough(df_15):
            return None

        df_15["xATR"]  = calculate_atr(df_15, atr_period)
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

        df_5["EMA50"] = df_5["Close"].ewm(span=50, adjust=False).mean()
        df_15["RSI"]  = get_rsi(df_15)

        m5_close = float(df_5["Close"].iloc[-2])
        m5_ema   = float(df_5["EMA50"].iloc[-2])
        rsi_15   = float(df_15["RSI"].iloc[-2])

        ts = int(df_15.index[-2].timestamp() * 1000)

        if is_buy and m5_close > m5_ema and rsi_15 < 70:
            return ("BULLISH", float(src[i]), float(df_15["xATR"].iloc[i]), ts)
        if is_sell and m5_close < m5_ema and rsi_15 > 30:
            return ("BEARISH", float(src[i]), float(df_15["xATR"].iloc[i]), ts)

    except Exception as e:
        print(f"[ERR] UT Bot {ticker}: {e}")
    return None

# ============================================================
#  TRADE EXECUTION
# ============================================================
def calc_sl_tp(signal_type, entry, atr):
    sl = entry - atr * ATR_MULT_SL if "BULLISH" in signal_type else entry + atr * ATR_MULT_SL
    tp = entry + atr * ATR_MULT_TP if "BULLISH" in signal_type else entry - atr * ATR_MULT_TP
    return float(sl), float(tp)

def calc_position_size(account, symbol, entry, sl):
    with _lock:
        balance = accounts[account]["balance"]
    risk = balance * 0.02
    sl_dist = abs(entry - sl)
    if sl_dist == 0:
        return 0.0
    if account == "nifty":
        lot = 25 if "NSEI" in symbol else 15
        risk_per_lot = sl_dist * lot
        if risk_per_lot == 0:
            return 0.0
        lots = risk / risk_per_lot
        return float(min(lots, 1)) * lot
    return float(risk / sl_dist)

def append_trade_csv(trade):
    try:
        with open(TRADE_LOG_CSV, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=trade.keys())
            if f.tell() == 0:
                w.writeheader()
            w.writerow(trade)
    except Exception as e:
        print(f"[WARN] CSV write failed: {e}")

def execute_trade(symbol, market_type, account, strat, sig_type, price, atr, ts):
    global active_trades, trade_history, accounts

    with _lock:
        debounce_key = (symbol, ts, sig_type)
        if debounce_key in sent_signals:
            return
        sent_signals[debounce_key] = True

        if accounts[account]["daily_trades"] >= 3:
            return
        if any(t["symbol"] == symbol and t["account"] == account for t in active_trades):
            return

        sl = calc_sl_tp(sig_type, price, atr)[0]
        qty = calc_position_size(account, symbol, price, sl)
        if qty <= 0:
            return

        actual_sl, actual_tp = calc_sl_tp(sig_type, price, atr)
        direction = "LONG" if "BULLISH" in sig_type.upper() else "SHORT"
        tf = "4H" if "Sweep" in strat else "15m"

        trade = {
            "id":         f"{symbol}_{int(time.time())}",
            "symbol":     symbol,
            "market":     market_type,
            "account":    account,
            "strat":      strat,
            "type":       direction,
            "entry":      float(price),
            "sl":         actual_sl,
            "tp":         actual_tp,
            "qty":        float(qty),
            "atr_entry":  float(atr),
            "trail_sl":   actual_sl,
            "ts_trigger": ts,
            "time":       datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        }

        active_trades.append(trade)
        accounts[account]["daily_trades"] += 1
        save_json(ACCOUNTS_FILE, accounts)

    risk_amt = abs(price - actual_sl) * qty
    emoji_dir = "STRONG BULLISH" if "BULLISH" in sig_type else "STRONG BEARISH"

    msg = (
        f"🚨 *HIGH-CONFLUENCE SIGNAL*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 *Asset:* `{symbol}` ({market_type})\n"
        f"⚡ *Strategy:* {strat}\n"
        f"🟢 *Direction:* {emoji_dir}\n"
        f"⏱️ *Timeframe:* {tf}\n"
        f"📈 *Entry:* `${price:,.4f}`\n"
        f"🕒 *Time:* {trade['time']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 *PAPER TRADE EXECUTED*\n"
        f"├ Account: `{account.upper()}`\n"
        f"├ Entry:   `${price:,.4f}`\n"
        f"├ SL:      `${actual_sl:,.4f}`\n"
        f"├ TP:      `${actual_tp:,.4f}`\n"
        f"├ Qty:     `{qty:.4f}`\n"
        f"└ Risk:    `₹{risk_amt:,.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📈 Chart", callback_data=f"chart_{symbol}"),
        InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}")
    )
    bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=markup)
    pushbullet_notify(msg)
    print(f"[TRADE] {direction} {symbol} @ {price} | SL {actual_sl} | TP {actual_tp} | {account}")

# ============================================================
#  MONITOR ACTIVE TRADES
# ============================================================
def monitor_trades():
    global active_trades, trade_history, accounts

    while True:
        if not active_trades:
            time.sleep(15)
            continue

        to_close = []

        for trade in active_trades:
            try:
                df = yf.download(trade["symbol"], period="1d",
                                 interval="1m", progress=False, auto_adjust=True)
                df = normalise_cols(df)
                if df.empty:
                    continue

                live = float(df["Close"].iloc[-1])
                is_long = trade["type"] == "LONG"

                profit_pct = (live - trade["entry"]) / trade["entry"] * 100
                if profit_pct >= 1.5:
                    new_sl = trade["entry"] + (trade["entry"] * 0.005)
                    if is_long:
                        trade["trail_sl"] = max(trade["trail_sl"], new_sl)
                    else:
                        trade["trail_sl"] = min(trade["trail_sl"], new_sl)

                hit_tp = (is_long and live >= trade["tp"]) or (not is_long and live <= trade["tp"])
                hit_sl = (is_long and live <= trade["trail_sl"]) or (not is_long and live >= trade["trail_sl"])

                if not (hit_tp or hit_sl):
                    continue

                pnl = abs(trade["tp"] - trade["entry"]) * trade["qty"] if hit_tp \
                    else -(abs(trade["entry"] - trade["trail_sl"]) * trade["qty"])

                with _lock:
                    accounts[trade["account"]]["balance"] += pnl
                    peaks[trade["account"]] = max(
                        peaks.get(trade["account"], 0),
                        accounts[trade["account"]]["balance"]
                    )

                    trade["exit_price"] = live
                    trade["pnl"]        = float(pnl)
                    trade["result"]     = "WIN" if hit_tp else "LOSS"
                    trade["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
                    trade_history.append(trade)
                    to_close.append(trade)

                append_trade_csv(trade)

                emoji   = "✅" if hit_tp else "❌"
                arrow   = "📈" if hit_tp else "📉"
                money   = "💰" if hit_tp else "💸"
                pnl_str = f"+₹{pnl:,.2f}" if hit_tp else f"-₹{abs(pnl):,.2f}"

                with _lock:
                    bal = accounts[trade["account"]]["balance"]

                msg = (
                    f"{emoji} *TRADE CLOSED — {trade['result']}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{'🟢' if is_long else '🔴'} `{trade['symbol']}` ({trade['strat']})\n"
                    f"💼 Account: `{trade['account'].upper()}`\n"
                    f"{arrow} Exit: `${live:,.4f}`\n"
                    f"{money} P/L: `{pnl_str}`\n"
                    f"🏦 Balance: `₹{bal:,.2f}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                )
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                pushbullet_notify(msg)
                print(f"[CLOSE] {trade['symbol']} {trade['result']} {pnl_str}")
                time.sleep(0.5)

            except Exception as e:
                print(f"[ERR] Monitor {trade['symbol']}: {e}")

        if to_close:
            with _lock:
                for t in to_close:
                    try:
                        active_trades.remove(t)
                    except ValueError:
                        pass
                save_json(ACTIVE_TRADES_FILE, active_trades)
                save_json(ACCOUNTS_FILE, accounts)
                save_json(HISTORY_FILE, trade_history)
                save_peaks()

        time.sleep(15)

# ============================================================
#  DAILY + WEEKLY RESET
# ============================================================
def daily_reset_loop():
    global accounts
    last_reset = None

    while True:
        now = datetime.now(IST)
        today_str = now.strftime("%Y-%m-%d")

        if last_reset != today_str:
            yesterday = accounts.get("last_reset_date", today_str)

            if last_reset is not None:
                day_pnl = sum(
                    float(t["pnl"]) for t in trade_history
                    if t.get("close_time", "").startswith(yesterday)
                )
                msg = (
                    f"🌙 *MIDNIGHT RESET*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 Yesterday P/L: `₹{day_pnl:,.2f}`\n"
                    f"🏦 Balances:\n"
                    f"├ Macro:      `₹{accounts['macro']['balance']:,.2f}`\n"
                    f"├ Nifty:      `₹{accounts['nifty']['balance']:,.2f}`\n"
                    f"└ NY Session: `₹{accounts['ny_session']['balance']:,.2f}`\n"
                    f"🔄 Trade limits reset."
                )
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
                pushbullet_notify(msg)
                print(f"[RESET] Daily P/L: ₹{day_pnl:,.2f}")

            if now.weekday() == 6 and last_reset is not None:
                week_trades = []
                for d in range(1, 8):
                    day_str = (now - pd.Timedelta(days=d)).strftime("%Y-%m-%d")
                    week_trades.extend(
                        t for t in trade_history
                        if t.get("close_time", "").startswith(day_str)
                    )
                week_pnl = sum(float(t["pnl"]) for t in week_trades)
                wins     = [t for t in week_trades if t["result"] == "WIN"]
                losses   = [t for t in week_trades if t["result"] == "LOSS"]
                wr       = len(wins) / (len(wins) + len(losses)) * 100 if (wins or losses) else 0
                best     = max(week_trades, key=lambda t: t["pnl"], default=None)
                worst    = min(week_trades, key=lambda t: t["pnl"], default=None)

                body = (
                    f"📊 Weekly P/L: `₹{week_pnl:,.2f}`\n"
                    f"├ Wins:   {len(wins)}\n"
                    f"├ Losses: {len(losses)}\n"
                    f"└ Win Rate: {wr:.0f}%\n"
                )
                if best:
                    body += f"✅ Best: `{best['symbol']}` `+₹{best['pnl']:,.2f}`\n"
                if worst:
                    body += f"❌ Worst: `{worst['symbol']}` `₹{worst['pnl']:,.2f}`"

                msg = f"📅 *WEEKLY SUMMARY*\n━━━━━━━━━━━━━━━━━━━━━━\n{body}"
                bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

            with _lock:
                for acc in ["macro", "nifty", "ny_session"]:
                    accounts[acc]["daily_trades"] = 0
                accounts["last_reset_date"] = today_str
                save_json(ACCOUNTS_FILE, accounts)

            last_reset = today_str

        time.sleep(60)

# ============================================================
#  BACKGROUND SCANNER
# ============================================================
MONITORED = [
    ("BTC-USD",    "Crypto"),
    ("GC=F",       "Gold"),
    ("EURUSD=X",   "Forex"),
    ("GBPUSD=X",   "Forex"),
    ("USDJPY=X",   "Forex"),
    ("^NSEI",      "NIFTY 50"),
    ("^NSEBANK",   "BANK NIFTY"),
]

def get_account(symbol):
    if "NSEI" in symbol or "BANK" in symbol:
        return "nifty"
    return "macro"

def scanner_loop():
    print("[SCANNER] Started — checking markets every 60s")
    while True:
        try:
            ny_active = is_ny_session()

            for symbol, mtype in MONITORED:
                with _lock:
                    if symbol in muted_assets:
                        continue

                account = get_account(symbol)

                if account == "nifty" and not is_nifty_market_open():
                    continue

                ut = check_ut_bot(symbol)
                if ut:
                    target = "ny_session" if ny_active else "macro"
                    execute_trade(symbol, mtype, target,
                                  "UT Bot Signals", ut[0], ut[1], ut[2], ut[3])

                sweep = check_sweep_engulfing(symbol)
                if sweep:
                    execute_trade(symbol, mtype, "macro",
                                  "Sweep + Engulfing", sweep[0],
                                  sweep[1], sweep[2], sweep[3])

                time.sleep(0.5)

        except Exception as e:
            print(f"[ERR] Scanner: {e}")

        time.sleep(60)

# ============================================================
#  TELEGRAM HANDLERS
# ============================================================
def menu_markup():
    m = InlineKeyboardMarkup()
    m.add(InlineKeyboardButton("🔍 Check Markets",  callback_data="cmd_check"))
    m.add(InlineKeyboardButton("📊 Asset Summary",  callback_data="cmd_summary"))
    return m

GUIDE = (
    "🤖 *TRADING BOT — CONTROL CENTER*\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "I monitor 7 markets 24/7, auto-execute paper trades, "
    "and send alerts with SL/TP.\n\n"
    "📘 *COMMANDS:*\n"
    "▫️ `/check`    — Scan all assets now\n"
    "▫️ `/summary`  — Live prices + status\n"
    "▫️ `/stats`   — Win rate + P/L per account\n"
    "▫️ `/balance` — Virtual account balances\n"
    "▫️ `/clear`   — Reset all accounts to ₹1L\n"
    "▫️ Tap 📈 to generate a chart\n"
    "▫️ Tap 🔇 to mute alerts for that asset\n\n"
    "⚡ *STRATEGIES:*\n"
    "🔵 Sweep + Engulfing (4H)\n"
    "🟣 UT Bot (15m + 5m EMA filter)\n\n"
    "📊 *MARKETS:*\n"
    "🪙 Crypto · 🟡 Gold · 💱 Forex · 📈 NIFTY/BANKNIFTY"
)

@bot.message_handler(commands=["start", "help"])
def cmd_start(m):
    bot.reply_to(m, GUIDE, parse_mode="Markdown", reply_markup=menu_markup())

@bot.message_handler(commands=["check"])
def cmd_check(m):
    bot.send_message(m.chat.id, "🔍 *Scanning all markets...*", parse_mode="Markdown")
    signals, neutral = [], []

    for symbol, mtype in MONITORED:
        ut    = check_ut_bot(symbol)
        sweep = check_sweep_engulfing(symbol)
        if ut:
            signals.append(f"🟢 `{symbol}` ➔ UT Bot {ut[0]} `${ut[1]:,.4f}`")
        if sweep:
            signals.append(f"🟢 `{symbol}` ➔ Sweep {sweep[0]} `${sweep[1]:,.4f}`")
        if not ut and not sweep:
            neutral.append(f"⚪ `{symbol}` — Neutral")
        time.sleep(0.3)

    body = "\n".join(signals + neutral) if signals else "\n".join(neutral)
    status = f"🔥 *{len(signals)} Signals Found*" if signals else "⏳ *No Setups Right Now*"
    text = f"🔍 *MARKET SCAN*\n━━━━━━━━━━━━━━━━━━━━━━\n{status}\n\n{body}"

    markup = InlineKeyboardMarkup()
    if signals:
        sym = signals[0].split("`")[1]
        markup.add(InlineKeyboardButton(f"📈 {sym} Chart", callback_data=f"chart_{sym}"))
    markup.add(InlineKeyboardButton("📊 Summary", callback_data="cmd_summary"))
    bot.reply_to(m, text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(commands=["summary"])
def cmd_summary(m):
    lines = []
    for symbol, mtype in MONITORED:
        status = "🔇 Muted" if symbol in muted_assets else "🟢 Active"
        try:
            price = get_cached_price(symbol) or 0
            lines.append(f"📈 `{symbol}` ({mtype}) ➔ {status} `${price:,.4f}`")
        except Exception:
            lines.append(f"📈 `{symbol}` ({mtype}) ➔ {status}")
        time.sleep(0.3)

    text = (
        f"📊 *MARKET SUMMARY*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n" +
        "\n".join(lines) +
        "\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ All systems scanning 24/7"
    )
    bot.reply_to(m, text, parse_mode="Markdown",
                 reply_markup=InlineKeyboardMarkup().add(
                     InlineKeyboardButton("🔍 Run Scan", callback_data="cmd_check")
                 ))

@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    if not trade_history:
        bot.reply_to(m, "📊 *No closed trades yet.*", parse_mode="Markdown")
        return

    def stats(acc):
        ts = [x for x in trade_history if x["account"] == acc]
        w  = [x for x in ts if x["result"] == "WIN"]
        l  = [x for x in ts if x["result"] == "LOSS"]
        p  = sum(float(x["pnl"]) for x in ts)
        wr = len(w) / (len(w) + len(l)) * 100 if (w or l) else 0
        return len(w), len(l), p, wr

    mw, ml, mp, mwr = stats("macro")
    nw, nl, np_, nwr = stats("nifty")
    nyw, nyl, nyp, nywr = stats("ny_session")

    text = (
        f"📊 *PERFORMANCE REPORT*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 *Macro ({mw}W/{ml}L — {mwr:.0f}%):*\n"
        f"   P/L: `{'+' if mp>0 else ''}₹{mp:,.2f}`\n\n"
        f"🇮🇳 *Nifty ({nw}W/{nl}L — {nwr:.0f}%):*\n"
        f"   P/L: `{'+' if np_>0 else ''}₹{np_:,.2f}`\n\n"
        f"🇺🇸 *NY Session ({nyw}W/{nyl}L — {nywr:.0f}%):*\n"
        f"   P/L: `{'+' if nyp>0 else ''}₹{nyp:,.2f}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(m, text, parse_mode="Markdown", reply_markup=menu_markup())

@bot.message_handler(commands=["balance"])
def cmd_balance(m):
    with _lock:
        macro_bal = accounts["macro"]["balance"]
        nifty_bal = accounts["nifty"]["balance"]
        ny_bal    = accounts["ny_session"]["balance"]
        macro_d   = accounts["macro"]["daily_trades"]
        nifty_d   = accounts["nifty"]["daily_trades"]
        ny_d      = accounts["ny_session"]["daily_trades"]
        ny_active = is_ny_session()

    text = (
        f"🏦 *VIRTUAL BALANCES*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 *Macro* — `₹{macro_bal:,.2f}` | {macro_d}/3 today\n"
        f"🇮🇳 *Nifty* — `₹{nifty_bal:,.2f}` | {nifty_d}/3 today\n"
        f"🇺🇸 *NY Session* — `₹{ny_bal:,.2f}` | {ny_d}/3 today\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ NY Session: {'ACTIVE' if ny_active else 'INACTIVE'}"
    )
    bot.reply_to(m, text, parse_mode="Markdown", reply_markup=menu_markup())

@bot.message_handler(commands=["clear"])
def cmd_clear(m):
    global active_trades, trade_history, accounts, peaks, sent_signals

    with _lock:
        active_trades, trade_history = [], []
        for acc in ["macro", "nifty", "ny_session"]:
            accounts[acc] = {"balance": 100000.0, "daily_trades": 0}
        peaks = {k: 100000.0 for k in peaks}
        sent_signals = {}
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, active_trades)
        save_json(HISTORY_FILE, trade_history)
        save_peaks()

    bot.reply_to(m, "🗑 *All accounts reset to ₹1,00,000.*", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
def cmd_fallback(m):
    bot.reply_to(m, GUIDE, parse_mode="Markdown", reply_markup=menu_markup())

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
                bot.send_photo(c.message.chat.id, buf,
                               caption=f"📈 `{sym}` | 1H Candlestick")
            else:
                bot.send_message(c.message.chat.id, "❌ Chart failed.")
        elif c.data.startswith("mute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.add(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(
                InlineKeyboardButton(f"🔊 Unmute {sym}", callback_data=f"unmute_{sym}")
            )
            bot.edit_message_text(
                f"🔇 `{sym}` muted — no alerts or trades until unmuted.",
                c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=m
            )
        elif c.data.startswith("unmute_"):
            sym = c.data.split("_", 1)[1]
            with _lock:
                muted_assets.discard(sym)
                save_json(MUTE_FILE, list(muted_assets))
            m = InlineKeyboardMarkup().add(
                InlineKeyboardButton(f"🔇 Mute {sym}", callback_data=f"mute_{sym}")
            )
            bot.edit_message_text(
                f"🔊 `{sym}` unmuted — alerts resumed.",
                c.message.chat.id, c.message.message_id,
                parse_mode="Markdown", reply_markup=m
            )
    except Exception as e:
        print(f"[ERR] Callback: {e}")
    bot.answer_callback_query(c.id)

# ============================================================
#  CHART GENERATION (thread-safe)
# ============================================================
def generate_chart(symbol, tf="1h"):
    with _chart_lock:
        try:
            df = yf.download(symbol, period="5d", interval=tf,
                              progress=False, auto_adjust=True)
            df = normalise_cols(df)
            if df.empty:
                return None

            fig, ax = plt.subplots(figsize=(12, 6),
                                    facecolor="#0d1117", dpi=60)
            ax.set_facecolor("#0d1117")

            for _, row in df.iterrows():
                o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
                color = "#00ff88" if c >= o else "#ff4444"
                ax.plot([df.index.get_loc(_) + 1,
                          df.index.get_loc(_) + 1],
                        [l, h], color=color, linewidth=1)
                body_bottom = min(o, c)
                body_height = abs(c - o) + 1e-8
                ax.bar(df.index.get_loc(_) + 1, body_height,
                       width=0.3, bottom=body_bottom,
                       color=color, linewidth=1)

            ax.set_title(f"{symbol} | {tf.upper()} Chart",
                         color="white", fontsize=13, fontweight="bold")
            ax.tick_params(colors="gray", labelsize=7)
            ax.xaxis.set_major_locator(
                plt.MaxNLocator(10))
            for spine in ax.spines.values():
                spine.set_color("#30363d")
            ax.grid(True, color="#21262d", linestyle="--", linewidth=0.5)
            plt.tight_layout()

            buf = BytesIO()
            plt.savefig(buf, format="png", facecolor="#0d1117")
            buf.seek(0)
            plt.close(fig)
            return buf

        except Exception as e:
            print(f"[ERR] Chart {symbol}: {e}")
            try:
                plt.close()
            except Exception:
                pass
            return None

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
    trade_history = load_json(HISTORY_FILE, [])

    print("=" * 50)
    print("  Trading Bot Starting...")
    print(f"  Macro:      ₹{accounts['macro']['balance']:,.2f}")
    print(f"  Nifty:      ₹{accounts['nifty']['balance']:,.2f}")
    print(f"  NY Session: ₹{accounts['ny_session']['balance']:,.2f}")
    print(f"  NY Active:  {is_ny_session()}")
    print(f"  Nifty Open: {is_nifty_market_open()}")
    print("=" * 50)

    threading.Thread(target=scanner_loop,      daemon=True).start()
    threading.Thread(target=monitor_trades,    daemon=True).start()
    threading.Thread(target=daily_reset_loop, daemon=True).start()

    print("[BOT] Connecting to Telegram...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
