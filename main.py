import os
import json
import time
import threading
import gc
from datetime import datetime, timedelta
from io import BytesIO
from wsgiref.simple_server import make_server

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

matplotlib.use("Agg")
plt.style.use("dark_background")

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set!")
if not CHAT_ID:
    raise ValueError("TELEGRAM_CHAT_ID not set!")

ACCOUNTS_FILE = "/workspace/accounts.json"
ACTIVE_TRADES_FILE = "/workspace/active_trades.json"
HISTORY_FILE = "/workspace/trade_history.json"
MUTE_FILE = "/workspace/muted_assets.json"
SENT_SIGNALS_FILE = "/workspace/sent_signals.json"
PENDING_SWEEPS_FILE = "/workspace/pending_sweeps.json"

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
history = []
pending_sweeps = []
_lock = threading.RLock()
_chart_lock = threading.RLock()
_price_cache = {}
IST = pytz.timezone("Asia/Kolkata")

_yf_session = requests.Session()
_yf_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})
_yf_lock = threading.Lock()


BR = "━━━━━━━━━━━━━━━━━━━━━━"
BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

def msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, actual_sl, actual_tp, qty, risk_amt, account, signal_time_str, fvg_zone=None):
    arrow = "🟢🟢🟢" if "BULLISH" in sig_type else "🔴🔴🔴"
    label = "🚀 STRONG BULLISH" if "BULLISH" in sig_type else "💥 STRONG BEARISH"
    dir_ = "LONG 📈" if "BULLISH" in sig_type else "SHORT 📉"
    fvg_line = ""
    if fvg_zone and "Sweep" in strat:
        fvg_line = f"🎯 *FVG Zone:* `${fvg_zone[0]:,.4f} — ${fvg_zone[1]:,.4f}`\n"
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
        f"⏰ *SIGNAL CANDLE CLOSED AT:*\n"
        f"🔔 `{signal_time_str}`\n"
        f"{BR}\n"
        f"💼 *PAPER TRADE EXECUTED*\n"
        f"{BR}\n"
        f"🏢 *Account:* `{account.upper()}`\n"
        f"📍 *Entry:* `${price:,.4f}`\n"
        f"🛑 *Stop Loss:* `${actual_sl:,.4f}`\n"
        f"🎯 *Take Profit:* `${actual_tp:,.4f}`\n"
        f"{fvg_line}"
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
        f"├ `/indi2` — Diagnose Strategy 2 (UT Bot)\n"
        f"├ `/pending` — Show sweep setups waiting for FVG\n"
        f"└ `/news` — Today's economic calendar & impact\n"
        f"{BR2}"
    )

def msg_error(context, error):
    return f"⚠️ *ERROR — {context}*\n{BR}\n❌ `{error}`\n{BR2}"

# WEB SERVER + WEBHOOK
def run_web():
    def app(environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET")
# Dashboard API routes (additive, does not touch trading logic)
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
    srv = make_server("0.0.0.0", PORT, app)
    srv.serve_forever()

threading.Thread(target=run_web, daemon=True).start()

bot = telebot.TeleBot(TOKEN, parse_mode="Markdown", threaded=False)

def load_json(fp, default):
    key = os.path.basename(fp)
    sup_url = os.environ.get("SUPABASE_URL")
    sup_key = os.environ.get("SUPABASE_KEY")

    # 1. Try Supabase first (survives redeploys)
    if sup_url and sup_key:
        try:
            r = requests.get(
                f"{sup_url}/rest/v1/bot_data?id=eq.{key}",
                headers={
                    "apikey": sup_key,
                    "Authorization": f"Bearer {sup_key}"
                },
                timeout=15
            )
            if r.status_code == 200:
                rows = r.json()
                if rows and len(rows) > 0:
                    # Write locally for fast loads next time
                    try:
                        with open(fp, "w") as f:
                            json.dump(rows[0]["data"], f, indent=4)
                    except:
                        pass
                    return rows[0]["data"]
        except Exception as e:
            print(f"[ERR] Supabase load {key}: {e}")

    # 2. Fallback to local file (if Supabase is down or not configured)
    try:
        if os.path.exists(fp):
            with open(fp) as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(fp, data):
    key = os.path.basename(fp)
    # 1. Always save locally too (fast, works if Supabase is down)
    try:
        tmp = fp + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=4)
        os.replace(tmp, fp)
    except Exception as e:
        print(f"[ERR] local save {fp}: {e}")

    # 2. Sync to Supabase so data survives redeploys
    sup_url = os.environ.get("SUPABASE_URL")
    sup_key = os.environ.get("SUPABASE_KEY")
    if sup_url and sup_key:
        try:
            r = requests.post(
                f"{sup_url}/rest/v1/bot_data",
                headers={
                    "apikey": sup_key,
                    "Authorization": f"Bearer {sup_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates"
                },
                json={"id": key, "data": data},
                timeout=15
            )
            if r.status_code not in (200, 201):
                print(f"[ERR] Supabase save {key}: HTTP {r.status_code}")
        except Exception as e:
            print(f"[ERR] Supabase save {key}: {e}")



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
    if symbol in ("BTC-USD", "GC=F", "XAUUSD=X"):
        return True
    if symbol in ("EURUSD=X", "GBPUSD=X", "USDJPY=X"):
        return w < 5
    if symbol in ("^NSEI", "^NSEBANK"):
        return w < 5 and 555 <= tm <= 930
    return False

_last_yf_call = 0
_yf_min_delay = 1.5  # seconds between yf.download calls

def yf_download(symbol, period, interval):
    global _last_yf_call
    try:
        with _yf_lock:
            # Wait at least 3 seconds between yf.download calls (prevents rate limit)
            elapsed = time.time() - _last_yf_call
            if elapsed < _yf_min_delay:
                time.sleep(_yf_min_delay - elapsed)
            _last_yf_call = time.time()
            
            df = yf.download(
                symbol,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
                threads=False,
                session=_yf_session,
            )
            if df is None or df.empty:
                return None
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
    
    # Use CoinGecko for BTC (avoids Yahoo rate limits completely)
    if symbol == "BTC-USD":
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code == 200:
                p = float(r.json()["bitcoin"]["usd"])
                _price_cache[symbol] = (p, now)
                print(f"[PRICE] BTC via CoinGecko: ${p:,.2f}")
                return p
        except Exception as e:
            print(f"[CRYPTO] CoinGecko error: {e}")
    
    # Use fallback for Gold (GC=F sometimes fails on Yahoo)
    if symbol == "GC=F":
        for gold_sym in ["GC=F", "XAUUSD=X", "GLD"]:
            try:
                df = yf_download(gold_sym, "1d", "1m")
                if df is not None and not df.empty:
                    p = float(df["Close"].iloc[-1])
                    _price_cache[symbol] = (p, now)
                    print(f"[PRICE] Gold via {gold_sym}: ${p:,.2f}")
                    return p
            except Exception:
                continue
        print("[PRICE] All gold symbols failed")
        return None
    
    # Normal Yahoo Finance for everything else
    df = yf_download(symbol, "1d", "1m")
    if df is None or df.empty:
        return None
    p = float(df["Close"].iloc[-1])
    _price_cache[symbol] = (p, now)
    return p
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
        if c["Low"] < m["Low"] and c["High"] > m["High"] and c["Close"] > m["High"]:
            return ("BULLISH", float(c["High"]), float(c["Low"]), ts, ts + 4 * 3600 * 1000)
        if c["High"] > m["High"] and c["Low"] < m["Low"] and c["Close"] < m["Low"]:
            return ("BEARISH", float(c["High"]), float(c["Low"]), ts, ts + 4 * 3600 * 1000)
    except Exception as e:
        print(f"[ERR] Sweep {ticker}: {e}")
    return None

def find_fvg(df_1h, direction, sweep_open_ts_ms):
    try:
        if df_1h is None or len(df_1h) < 3:
            return None
        sweep_open = pd.to_datetime(int(sweep_open_ts_ms), unit="ms")
        idx = df_1h.index
        if getattr(idx, "tz", None) is not None:
            if sweep_open.tz is None:
                sweep_open = sweep_open.tz_localize("UTC")
            else:
                sweep_open = sweep_open.tz_convert(idx.tz)
        mask = idx >= sweep_open
        df = df_1h[mask].reset_index(drop=True)
        if len(df) < 3:
            return None
        for i in range(2, len(df)):
            c_prev2 = df.iloc[i - 2]
            c_curr = df.iloc[i]
            if direction == "BULLISH":
                if float(c_curr["Low"]) > float(c_prev2["High"]):
                    zone_low = float(c_prev2["High"])
                    zone_high = float(c_curr["Low"])
                    if zone_high <= zone_low:
                        continue
                    post = df.iloc[i + 1:]
                    if len(post) > 0 and (post["Low"].astype(float) < zone_low).any():
                        continue
                    return (zone_low, zone_high)
            else:
                if float(c_curr["High"]) < float(c_prev2["Low"]):
                    zone_low = float(c_curr["High"])
                    zone_high = float(c_prev2["Low"])
                    if zone_high <= zone_low:
                        continue
                    post = df.iloc[i + 1:]
                    if len(post) > 0 and (post["High"].astype(float) > zone_high).any():
                        continue
                    return (zone_low, zone_high)
    except Exception as e:
        print(f"[ERR] find_fvg: {e}")
    return None

FVG_EXPIRY_HOURS = 24

def register_pending_sweep(symbol, mtype, sweep):
    global pending_sweeps
    direction, sweep_high, sweep_low, sweep_open_ts, sweep_close_ts = sweep
    with _lock:
        for p in pending_sweeps:
            if (p["symbol"] == symbol and p["direction"] == direction
                    and p["sweep_close_ts"] == sweep_close_ts):
                return
        lim = ACCOUNT_LIMITS.get("sweep_4h", 3)
        if accounts["sweep_4h"]["daily_trades"] >= lim:
            return
        if any(t["symbol"] == symbol and t["account"] == "sweep_4h" for t in active_trades):
            return
        if any(p["symbol"] == symbol and p["status"] in ("waiting_fvg", "waiting_fill")
               for p in pending_sweeps):
            return
        pending_sweeps.append({
            "symbol": symbol,
            "mtype": mtype,
            "direction": direction,
            "sweep_high": float(sweep_high),
            "sweep_low": float(sweep_low),
            "sweep_open_ts": int(sweep_open_ts),
            "sweep_close_ts": int(sweep_close_ts),
            "created_at": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
            "fvg_zone": None,
            "fvg_found_at": None,
            "status": "waiting_fvg",
        })
        accounts["sweep_4h"]["daily_trades"] += 1
        save_json(ACCOUNTS_FILE, accounts)
        save_json(PENDING_SWEEPS_FILE, pending_sweeps)
    sl_extreme = sweep_low if direction == "BULLISH" else sweep_high
    msg = (
        f"🔵 *SWEEP DETECTED — WAITING FOR FVG*\n"
        f"{BR}\n"
        f"🪙 *Asset:* `{symbol}` ({mtype})\n"
        f"📊 *Direction:* {'LONG 📈' if direction == 'BULLISH' else 'SHORT 📉'}\n"
        f"📏 *Sweep Candle:* `${sweep_low:,.4f} — ${sweep_high:,.4f}`\n"
        f"🛑 *SL Extreme:* `${sl_extreme:,.4f}`\n"
        f"⏱ *Sweep closed at:* `{format_signal_time(sweep_close_ts)}`\n"
        f"{BR}\n"
        f"⏳ *Watching 1H for Fair Value Gap...*\n"
        f"🕐 *Expiry:* {FVG_EXPIRY_HOURS}h\n"
        f"{BR2}"
    )
    safe_send(CHAT_ID, msg, parse_mode="Markdown")
    print(f"[PENDING] Sweep {direction} {symbol} @ sweep_close_ts={sweep_close_ts}")


def _refund_sweep_slot():
    with _lock:
        accounts["sweep_4h"]["daily_trades"] = max(0, accounts["sweep_4h"]["daily_trades"] - 1)
        save_json(ACCOUNTS_FILE, accounts)


def manage_pending_sweeps():
    global pending_sweeps
    while True:
        try:
            with _lock:
                copy = list(pending_sweeps)
            to_remove = []
            for p in copy:
                sym = p["symbol"]
                live_df = yf_download(sym, "1d", "1m")
                if live_df is None or live_df.empty:
                    continue
                live = float(live_df["Close"].iloc[-1])
                age_hours = (time.time() * 1000 - p["sweep_close_ts"]) / (3600 * 1000)
                if age_hours > FVG_EXPIRY_HOURS and p["status"] != "entered":
                    with _lock:
                        p["status"] = "expired"
                    to_remove.append(p)
                    _refund_sweep_slot()
                    safe_send(CHAT_ID, (
                        f"⏰ *PENDING SWEEP EXPIRED*\n{BR}\n"
                        f"`{sym}` {p['direction']} — no FVG fill in {FVG_EXPIRY_HOURS}h\n"
                        f"{BR2}"
                    ), parse_mode="Markdown")
                    print(f"[EXPIRED] Pending sweep {sym} {p['direction']}")
                    continue
                if p["direction"] == "BULLISH" and live <= p["sweep_low"]:
                    with _lock:
                        p["status"] = "invalidated"
                    to_remove.append(p)
                    _refund_sweep_slot()
                    safe_send(CHAT_ID, (
                        f"❌ *PENDING SWEEP INVALIDATED*\n{BR}\n"
                        f"`{sym}` BULLISH — price broke sweep low `${p['sweep_low']:,.4f}`\n"
                        f"{BR2}"
                    ), parse_mode="Markdown")
                    print(f"[INVALID] Pending sweep {sym} BULLISH")
                    continue
                if p["direction"] == "BEARISH" and live >= p["sweep_high"]:
                    with _lock:
                        p["status"] = "invalidated"
                    to_remove.append(p)
                    _refund_sweep_slot()
                    safe_send(CHAT_ID, (
                        f"❌ *PENDING SWEEP INVALIDATED*\n{BR}\n"
                        f"`{sym}` BEARISH — price broke sweep high `${p['sweep_high']:,.4f}`\n"
                        f"{BR2}"
                    ), parse_mode="Markdown")
                    print(f"[INVALID] Pending sweep {sym} BEARISH")
                    continue
                if p["fvg_zone"] is None:
                    df_1h = yf_download(sym, "5d", "1h")
                    fvg = find_fvg(df_1h, p["direction"], p["sweep_open_ts"])
                    if fvg:
                        zl, zh = fvg
                        with _lock:
                            p["fvg_zone"] = [float(fvg[0]), float(fvg[1])]
                            p["fvg_found_at"] = int(time.time() * 1000)
                            p["status"] = "waiting_fill"
                            save_json(PENDING_SWEEPS_FILE, pending_sweeps)
                        safe_send(CHAT_ID, (
                            f"🎯 *FVG FORMED — WAITING FOR FILL*\n{BR}\n"
                            f"🪙 `{sym}` {p['direction']}\n"
                            f"📏 *FVG Zone:* `${zl:,.4f} — ${zh:,.4f}`\n"
                            f"⏳ *Watching for price to enter zone...*\n"
                            f"{BR2}"
                        ), parse_mode="Markdown")
                        print(f"[FVG] Found for {sym} {p['direction']}: {zl}-{zh}")
                    continue
                zl, zh = p["fvg_zone"]
                filled = False
                if p["direction"] == "BULLISH":
                    if zl <= live <= zh:
                        filled = True
                else:
                    if zl <= live <= zh:
                        filled = True
                if filled:
                    fvg_entry = {
                        "entry_price": live,
                        "sl": p["sweep_low"] if p["direction"] == "BULLISH" else p["sweep_high"],
                        "sweep_ts": p["sweep_close_ts"],
                        "zone": p["fvg_zone"],
                    }
                    with _lock:
                        p["status"] = "entered"
                    to_remove.append(p)
                    with _lock:
                        if sym in muted_assets:
                            print(f"[MUTED] Skipping FVG fill for {sym} (muted)")
                            pending_sweeps = [pp for pp in pending_sweeps if pp not in to_remove]
                            save_json(PENDING_SWEEPS_FILE, pending_sweeps)
                            continue
                    execute(sym, p["mtype"], "sweep_4h", "Sweep + Engulfing",
                            p["direction"], live, fvg_entry["sl"], 0,
                            p["sweep_close_ts"], fvg_entry=fvg_entry)
                    print(f"[FVG FILL] {sym} {p['direction']} @ {live}")
            if to_remove:
                with _lock:
                    pending_sweeps = [pp for pp in pending_sweeps if pp not in to_remove]
                    save_json(PENDING_SWEEPS_FILE, pending_sweeps)
        except Exception as e:
            print(f"[ERR] manage_pending_sweeps: {e}")
        time.sleep(90)


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
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=IST)
        return dt.strftime("%d-%b-%Y %H:%M IST (+5:30)")
    except Exception:
        return "Unknown"

def execute(symbol, mtype, account, strat, sig_type, price, a1, a2, a3=None, fvg_entry=None):
    global active_trades
    if fvg_entry is not None:
        sl = float(fvg_entry["sl"])
        ts = fvg_entry["sweep_ts"]
        risk = abs(price - sl)
        if risk <= 0:
            return
        if "BULLISH" in sig_type:
            tp = price + risk * 2.0
        else:
            tp = price - risk * 2.0
    elif "Sweep" in strat:
        sl, tp, ts = float(a1), float(a2), a3
    else:
        atr, ts = float(a1), a2
        sl, tp = calc_sl_tp(sig_type, price, atr)
    with _lock:
        key = f"{symbol}_{ts}_{sig_type}_{account}"
        if key in sent_signals and fvg_entry is None:
            return
        if fvg_entry is not None:
            key = f"{symbol}_{ts}_{sig_type}_{account}_fvg_{price:.6f}"
            if key in sent_signals:
                return
        sent_signals[key] = {
            "ts_ms": int(time.time() * 1000),
            "symbol": symbol,
            "sig_type": sig_type,
            "strat": strat,
            "account": account,
            "status": "open",
            "pnl": 0,
            "hint": "",
            "time_str": datetime.now(IST).strftime("%H:%M"),
        }
        save_json(SENT_SIGNALS_FILE, sent_signals)
        lim = ACCOUNT_LIMITS.get(account, 3)
        if fvg_entry is None and accounts[account]["daily_trades"] >= lim:
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
            "time": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)"),
        }
        active_trades.append(trade)
        if fvg_entry is None:
            accounts[account]["daily_trades"] += 1
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, active_trades)
    risk = abs(price - sl) * qty
    signal_time_str = format_signal_time(ts)
    fvg_zone = fvg_entry.get("zone") if fvg_entry else None
    msg = msg_trade_signal(symbol, mtype, strat, sig_type, tf, price, sl, tp, qty, risk, account, signal_time_str, fvg_zone=fvg_zone)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📈 Chart", callback_data=f"chart_{symbol}"),
               InlineKeyboardButton(f"🔇 Mute {symbol}", callback_data=f"mute_{symbol}"))
    safe_send(CHAT_ID, msg, parse_mode="Markdown", reply_markup=markup)
    print(f"[TRADE] {trade['type']} {symbol} @ {price} | Signal: {signal_time_str}")


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
                # Cache the live price so the dashboard API can read it without hitting Yahoo
                with _lock:
                    _price_cache[t["symbol"]] = (live, time.time())
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
                    t["close_time"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST (+5:30)")
                    t["closed_at"] = datetime.now(IST).isoformat()  # 2026-08-03T13:52:00+05:30
                    to_close.append(t)
                    save_json(ACCOUNTS_FILE, accounts)
                    global history
                    history.append(t)
                    save_json(HISTORY_FILE, history)
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

MONITORED = [
    ("BTC-USD", "Crypto"),
    ("GC=F", "Gold"),
    ("XAUUSD=X", "Gold-Backup"),
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
                    register_pending_sweep(symbol, mtype, sweep)
                time.sleep(2)
            gc.collect()
        except Exception as e:
            print(f"[ERR] Scanner: {e}")
            safe_send(CHAT_ID, msg_error("Scanner", str(e)), parse_mode="Markdown")
        time.sleep(300)

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
                global history
                history = load_json(HISTORY_FILE, [])
                day_trades = [t for t in history if t.get("close_time", "").startswith(last)]
                day_pnl = sum(float(t["pnl"]) for t in day_trades)
                safe_send(CHAT_ID, msg_midnight_reset(
                    day_pnl,
                    accounts["macro"]["balance"],
                    accounts["nifty"]["balance"],
                    accounts["ny_session"]["balance"],
                    accounts["sweep_4h"]["balance"]
                ), parse_mode="Markdown")
                if len(history) > 500:
                    history = history[-500:]
                    save_json(HISTORY_FILE, history)
            last = today
            gc.collect()
        time.sleep(60)

# ============================================================
# NEWS MODULE
# ============================================================
NEWS_CACHE = {"data": [], "last_fetch": 0}

def fetch_news():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    # Attempt 1: Normal HTTPS
    try:
        response = requests.get(url, headers=headers, timeout=20)
        if response.status_code == 200 and response.text and response.text.strip():
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                print(f"[NEWS] Fetched {len(data)} events (HTTPS)")
                return data
    except Exception as e:
        print(f"[NEWS] HTTPS attempt failed: {e}")

    # Attempt 2: Disable SSL verification (Render free-tier fix)
    try:
        response = requests.get(url, headers=headers, timeout=20, verify=False)
        if response.status_code == 200 and response.text and response.text.strip():
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                print(f"[NEWS] Fetched {len(data)} events (verify=False)")
                return data
    except Exception as e:
        print(f"[NEWS] verify=False attempt failed: {e}")

    # Attempt 3: Hardcoded backup — never let dashboard go blank
    print("[NEWS] All API attempts failed. Using hardcoded backup.")
    return [
        {"title": "ISM Manufacturing PMI", "country": "USD", "date": "2026-08-03T10:00:00-04:00", "impact": "High", "forecast": "54.0", "previous": "53.3"},
        {"title": "ISM Manufacturing Prices", "country": "USD", "date": "2026-08-03T10:00:00-04:00", "impact": "Medium", "forecast": "70.0", "previous": "73.0"},
        {"title": "NZD Employment Change q/q", "country": "NZD", "date": "2026-08-04T18:45:00-04:00", "impact": "High", "forecast": "0.1%", "previous": "0.2%"},
        {"title": "NZD Unemployment Rate", "country": "NZD", "date": "2026-08-04T18:45:00-04:00", "impact": "High", "forecast": "5.4%", "previous": "5.3%"},
        {"title": "ADP Non-Farm Employment Change", "country": "USD", "date": "2026-08-05T08:15:00-04:00", "impact": "Medium", "forecast": "71K", "previous": "98K"},
        {"title": "ISM Services PMI", "country": "USD", "date": "2026-08-05T10:00:00-04:00", "impact": "Medium", "forecast": "54.5", "previous": "54.0"},
        {"title": "US Unemployment Claims", "country": "USD", "date": "2026-08-06T08:30:00-04:00", "impact": "Medium", "forecast": "205K", "previous": "197K"},
        {"title": "CAD Employment Change", "country": "CAD", "date": "2026-08-07T08:30:00-04:00", "impact": "High", "forecast": "15.0K", "previous": "18.2K"},
        {"title": "US Non-Farm Employment Change", "country": "USD", "date": "2026-08-07T08:30:00-04:00", "impact": "High", "forecast": "88K", "previous": "57K"},
        {"title": "US Unemployment Rate", "country": "USD", "date": "2026-08-07T08:30:00-04:00", "impact": "High", "forecast": "4.2%", "previous": "4.2%"},
    ]

def get_cached_news():
    now = time.time()
    if now - NEWS_CACHE["last_fetch"] > 60:
        try:
            fresh = fetch_news()
            if isinstance(fresh, list) and len(fresh) > 0:
                NEWS_CACHE["data"] = fresh
                NEWS_CACHE["last_fetch"] = now
                print(f"[NEWS CACHE] Updated: {len(fresh)} events")
            else:
                print("[NEWS CACHE] Fetch returned empty, keeping old data")
                # If we have NO data at all, force a re-fetch sooner
                if len(NEWS_CACHE["data"]) == 0:
                    NEWS_CACHE["last_fetch"] = now - 30  # Retry in 30s instead of 60s
        except Exception as e:
            print(f"[NEWS CACHE] Error: {e}")
    return NEWS_CACHE["data"]


def impact_emoji(impact):
    impact = str(impact).upper()
    if impact in ("HIGH", "RED", "H"):
        return "🔴"
    if impact in ("MEDIUM", "ORANGE", "YELLOW", "M"):
        return "🟡"
    if impact in ("LOW", "GREEN", "L"):
        return "🟢"
    return "⚪"

def news_impact_hint(title, currency):
    t = str(title).upper()
    c = str(currency).upper()
    hints = []
    affected = []
    is_nfp = "NON-FARM" in t or "NFP" in t or "EMPLOYMENT CHANGE" in t or "PAYROLLS" in t
    is_cpi = "CPI" in t or "INFLATION" in t or "CONSUMER PRICE" in t
    is_fomc = "FOMC" in t or "FED RATE" in t or "INTEREST RATE" in t or "FEDERAL FUNDS" in t
    is_gdp = "GDP" in t or "GROSS DOMESTIC" in t
    is_pmi = "PMI" in t or "MANUFACTURING" in t or "SERVICES PMI" in t
    is_claims = "CLAIMS" in t or "UNEMPLOYMENT CLAIMS" in t
    is_retail = "RETAIL SALES" in t
    is_ecb = "ECB" in t or "EUROPEAN CENTRAL" in t
    is_boe = "BOE" in t or "BANK OF ENGLAND" in t
    is_boj = "BOJ" in t or "BANK OF JAPAN" in t

    if is_nfp:
        hints.append("💥 NFP → Volatile USD | Better jobs = Strong USD")
        affected = ["EUR/USD", "GBP/USD", "USD/JPY", "Gold", "BTC"]
    elif is_cpi:
        hints.append("💥 CPI → Inflation shock | High CPI = Rate hike fear")
        affected = ["EUR/USD", "GBP/USD", "USD/JPY", "Gold ↑ (hedge)", "BTC mixed"]
    elif is_fomc:
        hints.append("💥 FOMC → Hawkish = USD rally | Dovish = USD dump")
        affected = ["All USD pairs", "Gold", "BTC"]
    elif is_gdp:
        hints.append("📊 GDP → Strong growth = Strong currency")
        affected = [f"{c} pairs", "Gold", "BTC"]
    elif is_pmi:
        hints.append("📊 PMI → >50 expansion, <50 contraction")
        affected = [f"{c} pairs"]
    elif is_claims:
        hints.append("📊 Jobless Claims → Lower = Strong economy")
        affected = ["USD pairs", "Gold"]
    elif is_retail:
        hints.append("📊 Retail Sales → Consumer strength signal")
        affected = [f"{c} pairs"]
    elif is_ecb:
        hints.append("💥 ECB Rate → Hawkish = EUR up")
        affected = ["EUR/USD", "GBP/USD"]
    elif is_boe:
        hints.append("💥 BoE Rate → Hawkish = GBP up")
        affected = ["GBP/USD", "EUR/GBP"]
    elif is_boj:
        hints.append("💥 BoJ → Yen intervention = Safe haven flow")
        affected = ["USD/JPY", "Gold ↑"]
    else:
        hints.append("📊 Monitor price action around release")
        affected = [f"{c} pairs"]

    if c == "USD" and not hints:
        hints.append("🇺🇸 USD news → Moves all dollar pairs + Gold + BTC")
        affected = ["EUR/USD", "GBP/USD", "USD/JPY", "Gold", "BTC"]
    elif c == "EUR":
        hints.append("🇪🇺 EUR news → Mainly EUR/USD, EUR/GBP")
        affected = ["EUR/USD", "EUR/GBP"]
    elif c == "GBP":
        hints.append("🇬🇧 GBP news → Mainly GBP/USD, EUR/GBP")
        affected = ["GBP/USD", "EUR/GBP"]
    elif c == "JPY":
        hints.append("🇯🇵 JPY news → Safe haven flows possible")
        affected = ["USD/JPY", "Gold"]

    return " | ".join(hints), affected


def _extract_time_from_iso(date_str):
    """Extract HH:MM ET from ISO datetime like 2026-08-03T10:00:00-04:00."""
    if not date_str:
        return ""
    try:
        # Parse ISO string
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        # Convert to ET (UTC-4 or UTC-5 depending on DST — approximate)
        et_offset = timedelta(hours=-4)  # EDT
        et_dt = dt.astimezone(pytz.timezone("US/Eastern"))
        return et_dt.strftime("%H:%M")
    except Exception:
        # Fallback: manual extraction
        s = str(date_str)
        if "T" in s:
            time_part = s.split("T")[1]
            return time_part[:5]  # HH:MM
        return ""

def format_news_message(events, title, filter_today_only=True, max_events=15):
    if not events:
        return f"📰 *{title}*\n{BR}\n⚪ No events found.\n{BR2}"
    lines = [f"📰 *{title}*\n{BR}"]
    now = datetime.now(IST)
    today_str = now.strftime("%Y-%m-%d")
    count = 0
    for ev in events:
        if count >= max_events:
            break
        try:
            date = _extract_date(ev.get("date", ""))
            # FIX: Extract time from ISO date string, not from "time" field
            raw_date = ev.get("date", "")
            time_str = _extract_time_from_iso(raw_date)
            impact = str(ev.get("impact", "")).upper()
            title_ev = ev.get("title", "Unknown")
            currency = ev.get("country", ev.get("currency", "???"))
            forecast = ev.get("forecast", "")
            previous = ev.get("previous", "")
            if filter_today_only and date != today_str:
                continue

            # Convert ET time to IST
            ts_ist = ""
            try:
                if time_str and time_str != "All Day":
                    t_parts = time_str.split(":")
                    if len(t_parts) == 2:
                        h = int(t_parts[0])
                        m = int(t_parts[1])
                        ist_h = (h + 9) % 24
                        ist_m = m + 30
                        if ist_m >= 60:
                            ist_h = (ist_h + 1) % 24
                            ist_m -= 60
                        ts_ist = f" | `{ist_h:02d}:{ist_m:02d} IST`"
            except Exception:
                pass

            emoji = impact_emoji(impact)
            hint, affected = news_impact_hint(title_ev, currency)
            affected_str = ", ".join(affected) if affected else ""
            line = f"{emoji} *{currency}* — `{title_ev}`\n🕐 `{time_str} ET{ts_ist}`\n"
            if forecast or previous:
                line += f"📊 Forecast: `{forecast}` | Previous: `{previous}`\n"
            line += f"💡 {hint}\n"
            if affected_str:
                line += f"🎯 Affected: {affected_str}\n"
            line += f"{BR}"
            lines.append(line)
            count += 1
        except Exception as e:
            print(f"[ERR] format_news: {e}")
            continue
    if len(lines) == 1:
        lines.append("⚪ No high-impact events for today.\n")
    lines.append(BR2)
    return "\n".join(lines) 


def _extract_date(date_str):
    """Extract YYYY-MM-DD from ISO datetime string."""
    if not date_str:
        return ""
    s = str(date_str)
    if "T" in s:
        return s.split("T")[0]
    return s[:10] if len(s) >= 10 else s

def get_today_high_impact_news():
    news = get_cached_news()
    now = datetime.now(IST)
    today_str = now.strftime("%Y-%m-%d")
    filtered = []
    for ev in news:
        impact = str(ev.get("impact", "")).upper()
        date = _extract_date(ev.get("date", ""))
        if date == today_str and impact in ("HIGH", "MEDIUM", "H", "M", "RED", "ORANGE", "YELLOW"):
            filtered.append(ev)
    return filtered

def get_weekly_news():
    """Return all upcoming events for the week, grouped by day."""
    news = get_cached_news()
    now = datetime.now(IST)
    today_str = now.strftime("%Y-%m-%d")
    # Filter: only today and future dates
    filtered = []
    for ev in news:
        date = _extract_date(ev.get("date", ""))
        if date >= today_str:
            filtered.append(ev)
    return filtered


def news_alert_loop():
    alerted_events = set()
    morning_sent_today = ""
    while True:
        try:
            now = datetime.now(IST)
            today_str = now.strftime("%Y-%m-%d")
            # Morning digest at 9:00 AM IST
            if now.hour == 9 and now.minute < 5 and morning_sent_today != today_str:
                events = get_today_high_impact_news()
                if events:
                    msg = format_news_message(events, "🌅 MORNING NEWS DIGEST")
                    safe_send(CHAT_ID, msg, parse_mode="Markdown")
                else:
                    safe_send(CHAT_ID, f"📰 *MORNING NEWS DIGEST*\n{BR}\n🟢 No high-impact news today. Relax.\n{BR2}", parse_mode="Markdown")
                morning_sent_today = today_str
            # Pre-news alerts (30 min before)
            news = get_cached_news()
            for ev in news:
                try:
                    impact = str(ev.get("impact", "")).upper()
                    if impact not in ("HIGH", "H", "RED"):
                        continue
                    date = ev.get("date", "")
                    time_str = _extract_time_from_iso(ev.get("date", ""))
                    if date != today_str or not time_str or time_str == "All Day":
                        continue
                    ev_id = f"{date}_{time_str}_{ev.get('title','')}"
                    if ev_id in alerted_events:
                        continue
                    t_parts = time_str.split(":")
                    if len(t_parts) != 2:
                        continue
                    h = int(t_parts[0])
                    m = int(t_parts[1])
                    ist_h = (h + 9) % 24
                    ist_m = m + 30
                    if ist_m >= 60:
                        ist_h = (ist_h + 1) % 24
                        ist_m -= 60
                    ev_dt = now.replace(hour=ist_h, minute=ist_m, second=0, microsecond=0)
                    if ist_h < now.hour and h > 14:
                        ev_dt = ev_dt + timedelta(days=1)
                    mins_until = (ev_dt - now).total_seconds() / 60
                    if 25 <= mins_until <= 35:
                        currency = ev.get("country", ev.get("currency", "???"))
                        title_ev = ev.get("title", "Unknown")
                        forecast = ev.get("forecast", "")
                        previous = ev.get("previous", "")
                        hint, affected = news_impact_hint(title_ev, currency)
                        affected_str = ", ".join(affected) if affected else ""
                        msg = (
                            f"⚠️ *HIGH IMPACT NEWS IN ~30 MIN*\n"
                            f"{BR}\n"
                            f"🔴 *{currency}* — `{title_ev}`\n"
                            f"🕐 `{time_str} ET` → `{ist_h:02d}:{ist_m:02d} IST`\n"
                        )
                        if forecast or previous:
                            msg += f"📊 Forecast: `{forecast}` | Previous: `{previous}`\n"
                        msg += (
                            f"{BR}\n"
                            f"💡 *Bias:* {hint}\n"
                            f"🎯 *Affected:* {affected_str}\n"
                            f"{BR}\n"
                            f"⚠️ *RECOMMENDATION:*\n"
                            f"• Widen stops or reduce position size\n"
                            f"• Avoid new entries 15 min before/after\n"
                            f"• Watch for whipsaws and spread widening\n"
                            f"{BR2}"
                        )
                        safe_send(CHAT_ID, msg, parse_mode="Markdown")
                        alerted_events.add(ev_id)
                        print(f"[NEWS ALERT] Sent for {currency} {title_ev}")
                except Exception as e:
                    print(f"[ERR] news_alert_loop event: {e}")
                    continue
            cutoff = (now - timedelta(days=3)).strftime("%Y-%m-%d")
            alerted_events = {e for e in alerted_events if not e.startswith(cutoff)}
        except Exception as e:
            print(f"[ERR] news_alert_loop: {e}")
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
                signals.append(f"⏳ `{symbol}` ➔ Sweep detected (waiting for FVG)")
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
    safe_send(m.chat.id, f"📊 *LIVE SUMMARY*\n{BR}\n{'\n'.join(lines)}\n{BR}\n🕐 `{datetime.now(IST).strftime('%H:%M:%S IST (+5:30)')}`\n{BR2}", parse_mode="Markdown")

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
        f"🕐 `{datetime.now(IST).strftime('%H:%M:%S IST (+5:30)')}`\n{BR2}"
    )
    safe_send(m.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=["clear"])
def cmd_clear(m):
    global active_trades, history, sent_signals   # ← ADD sent_signals
    with _lock:
        active_trades = []
        history = []
        sent_signals = {}                          # ← ADD THIS
        for acc in ["macro", "nifty", "ny_session", "sweep_4h"]:
            accounts[acc] = {"balance": 100000.0, "daily_trades": 0}
        save_json(ACCOUNTS_FILE, accounts)
        save_json(ACTIVE_TRADES_FILE, [])
        save_json(HISTORY_FILE, [])
        save_json(SENT_SIGNALS_FILE, {})           # ← ADD THIS
    safe_send(m.chat.id, f"🗑 *RESET DONE*\n{BR}\n✅ All balances → `₹1,00,000`\n✅ Trades closed\n✅ History wiped\n✅ Signals wiped\n✅ Counters reset\n{BR2}", parse_mode="Markdown")

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

@bot.message_handler(commands=["pending"])
def cmd_pending(m):
    with _lock:
        copy = list(pending_sweeps)
    if not copy:
        safe_send(m.chat.id, f"📋 *PENDING SWEEPS*\n{BR}\n⚪ No pending setups.\n{BR2}", parse_mode="Markdown")
        return
    lines = [f"📋 *PENDING SWEEPS ({len(copy)})*\n{BR}"]
    now_ts = time.time() * 1000
    for p in copy:
        sym = p["symbol"]
        direction = p["direction"]
        status = p["status"]
        expiry = p["sweep_close_ts"] + FVG_EXPIRY_HOURS * 3600 * 1000
        mins_left = int((expiry - now_ts) / 60000)
        mins_left = max(0, mins_left)
        status_emoji = "⏳" if status == "waiting_fvg" else "🎯" if status == "waiting_fill" else "❓"
        fvg_info = ""
        if p["fvg_zone"]:
            zl, zh = p["fvg_zone"]
            fvg_info = f" | FVG: `${zl:,.2f}-{zh:,.2f}`"
        lines.append(
            f"{status_emoji} `{sym}` {direction} — {status.replace('_',' ').title()}{fvg_info}\n"
            f"   ⏰ Expires in `{mins_left}m`\n"
        )
    lines.append(BR2)
    safe_send(m.chat.id, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=["news"])
def cmd_news(m):
    chat_id = m.chat.id
    safe_send(chat_id, "📰 *Fetching economic calendar...*")
    def run():
        events = get_weekly_news()
        if not events:
            safe_send(chat_id, "📰 *ECONOMIC CALENDAR*\n" + BR + "\n⚪ No upcoming events found.\n" + BR2, parse_mode="Markdown")
            return
        
        # Split into chunks of 10 events max to stay under Telegram 4096 char limit
        chunk_size = 10
        total = len(events)
        for i in range(0, total, chunk_size):
            chunk = events[i:i+chunk_size]
            is_first = (i == 0)
            is_last = (i + chunk_size >= total)
            
            if is_first and is_last:
                title = "📅 UPCOMING WEEK'S ECONOMIC CALENDAR"
            elif is_first:
                title = f"📅 UPCOMING WEEK'S CALENDAR (1–{min(chunk_size, total)} of {total})"
            else:
                title = f"📅 CALENDAR CONTINUED ({i+1}–{min(i+chunk_size, total)} of {total})"
            
            msg = format_news_message(chunk, title, filter_today_only=False, max_events=chunk_size)
            safe_send(chat_id, msg, parse_mode="Markdown")
            time.sleep(0.5)  # Small delay between messages
        
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


# ============================================================
# BOOT
# ============================================================

if __name__ == "__main__":
    init_accounts()
    muted_assets.update(load_json(MUTE_FILE, []))
    active_trades = load_json(ACTIVE_TRADES_FILE, [])
    sent_signals = load_json(SENT_SIGNALS_FILE, {})
    pending_sweeps = load_json(PENDING_SWEEPS_FILE, [])
    history = load_json(HISTORY_FILE, [])

    # MOVE THIS ENTIRE BLOCK INSIDE — with 4 spaces indent:
    def auto_save_loop():
        while True:
            try:
                with _lock:
                    save_json(ACTIVE_TRADES_FILE, active_trades)
                    save_json(HISTORY_FILE, history)
                    save_json(SENT_SIGNALS_FILE, sent_signals)
                    save_json(PENDING_SWEEPS_FILE, pending_sweeps)
                    save_json(ACCOUNTS_FILE, accounts)
                    print(f"[AUTO-SAVE] OK — trades:{len(active_trades)} hist:{len(history)} sigs:{len(sent_signals)}")
            except Exception as e:
                print(f"[AUTO-SAVE] Error: {e}")
            time.sleep(30)

    threading.Thread(target=auto_save_loop, daemon=True).start()

    print("=" * 50)
    # ... rest stays the same

    print(" Trading Bot Starting...")
    print(f" Macro: ₹{accounts['macro']['balance']:,.2f}")
    print(f" Nifty: ₹{accounts['nifty']['balance']:,.2f}")
    print(f" NY Session: ₹{accounts['ny_session']['balance']:,.2f}")
    print(f" Web server: :{os.environ.get('PORT', 10000)}/ping")
    print("=" * 50)

# Force initial news fetch
# Force initial news fetch on startup (wrapped safely)
    # Force initial news fetch on startup
    try:
        initial_news = fetch_news()
        if initial_news:
            NEWS_CACHE["data"] = initial_news
            NEWS_CACHE["last_fetch"] = time.time()
            print(f"[NEWS] Loaded {len(initial_news)} events on startup")
        else:
            print("[NEWS] No events loaded on startup, will retry later")
    except Exception as e:
        print(f"[NEWS] Startup fetch failed: {e}")
    # Continue anyway — bot should not crash
    
    safe_send(CHAT_ID, "🤖 *Bot started on Render!*\nUse `/test` to check if data fetching works.", parse_mode="Markdown")

    threading.Thread(target=scanner, daemon=True).start()
    threading.Thread(target=monitor, daemon=True).start()
    threading.Thread(target=daily_reset, daemon=True).start()
    threading.Thread(target=manage_pending_sweeps, daemon=True).start()
    threading.Thread(target=news_alert_loop, daemon=True).start()

    if WEBHOOK_URL:
        print(f"[BOT] Setting webhook to: {WEBHOOK_URL}")
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.set_webhook(url=WEBHOOK_URL, timeout=20)
            print("[BOT] Webhook active. Bot is listening via HTTP.")
        except Exception as e:
            print(f"[ERR] Webhook setup failed: {e}")
            print("[BOT] Falling back to polling...")
            bot.polling(none_stop=True, interval=3, timeout=60)
    else:
        print("[WARN] WEBHOOK_URL not set. Using polling (may cause 409 if another instance is running).")
        print("[HINT] Set WEBHOOK_URL=https://your-app.onrender.com/webhook in Render env vars.")
        bot.polling(none_stop=True, interval=3, timeout=60)

    print("[BOT] Main thread keeping process alive...")
    while True:
        time.sleep(3600)
