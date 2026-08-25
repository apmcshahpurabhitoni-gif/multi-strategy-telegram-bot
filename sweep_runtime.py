"""Runtime integration for the canonical sweep engine."""
from __future__ import annotations
import json
import os
import time
from datetime import datetime
from sweep_engine import detect_sweep

STATE_FILE = "/tmp/workspace/sweep_runtime_state.json"
CONTEXT = {}
STATE = {}


def _load():
    global STATE
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            STATE = json.load(f)
    except Exception:
        STATE = {}


def _save():
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(STATE, f, indent=2)
    os.replace(tmp, STATE_FILE)


def _key(symbol, close_ts):
    return f"{symbol}:{int(close_ts)}"


def _fmt_ohlc(v, cur):
    return (f"O `{cur}{v['Open']:,.4f}`  H `{cur}{v['High']:,.4f}`  "
            f"L `{cur}{v['Low']:,.4f}`  C `{cur}{v['Close']:,.4f}`")


def _source_warning(symbol):
    if symbol in {"GC=F", "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X", "USDCAD=X", "NZDUSD=X"}:
        return "⚠️ *DATA SOURCE WARNING:* Bot data is Yahoo Finance; TradingView reference is OANDA. Verify OHLC before relying on the signal."
    return "⚠️ *DATA SOURCE NOTE:* Bot candle data comes from the configured free provider. Verify against TradingView if prices differ."


def _signal_message(main, symbol, mtype, result, reminder=False):
    cur = main._currency(symbol)
    name = main.display_name(symbol)
    prev, curr = result.previous, result.current
    start = result.candle_start.strftime("%d-%b-%Y %H:%M IST")
    end = result.candle_end.strftime("%d-%b-%Y %H:%M IST")
    prev_duration = result.candle_end - result.candle_start
    pstart = (result.candle_start - prev_duration).strftime("%d-%b-%Y %H:%M IST")
    pEnd = result.candle_start.strftime("%d-%b-%Y %H:%M IST")
    icon = "🔔" if reminder else ({"BULLISH":"🟢", "BEARISH":"🔴", "NEUTRAL":"🔥"}[result.direction])
    label = "REMINDER — " if reminder else ""
    result_label = {"BULLISH":"BUY", "BEARISH":"SELL", "NEUTRAL":"NEUTRAL SWEEP"}[result.direction]
    action = "📝 PAPER BUY" if result.direction == "BULLISH" else "📝 PAPER SELL" if result.direction == "BEARISH" else "ℹ️ INFORMATIONAL — NO PAPER TRADE"
    warning = result.schedule_warning or _source_warning(symbol)
    return (
        f"{icon} *{label}SWEEP — {name}*\n{main.BR}\n"
        f"🪙 *Asset:* `{name}` (`{symbol}`)\n🌐 *Market:* `{mtype}`\n"
        f"⏱ *Timeframe:* `{result.timeframe}`\n"
        f"🕯 *Previous Candle:* `{pstart}` → `{pEnd}`\n{_fmt_ohlc(prev, cur)}\n"
        f"🕯 *Current Candle:* `{start}` → `{end}`\n{_fmt_ohlc(curr, cur)}\n{main.BR}\n"
        f"✓ *High swept:* `YES` — {cur}{curr['High']:,.4f} > {cur}{prev['High']:,.4f}\n"
        f"✓ *Low swept:* `YES` — {cur}{curr['Low']:,.4f} < {cur}{prev['Low']:,.4f}\n"
        f"📌 *Previous range:* `{cur}{prev['Low']:,.4f}` → `{cur}{prev['High']:,.4f}`\n"
        f"📍 *Close classification:* `{result_label}`\n{action}\n{main.BR}\n"
        f"{warning}\n⏰ *Confirmed:* `{end}`\n{main.BR2}"
    )


def install(main):
    global CONTEXT
    _load(); CONTEXT = {}
    main._sweep_runtime_original_check = main.check_sweep
    main._sweep_runtime_original_handle = main.handle_sweep
    main._sweep_runtime_original_notify = main.notify_neutral_sweep
    original_msg = main.msg_trade_signal

    def check_sweep_v2(symbol, df=None):
        try:
            result = detect_sweep(df, symbol, datetime.now(main.IST))
            if result is None:
                return None
            close_ts = int(result.candle_end.timestamp() * 1000)
            open_ts = int(result.candle_start.timestamp() * 1000)
            CONTEXT[_key(symbol, close_ts)] = result
            return (result.direction, result.current["High"], result.current["Low"], close_ts, open_ts, result)
        except Exception as e:
            main.alert_error(f"Sweep candle engine: {symbol}", e)
            return None

    def msg_trade_signal_v2(symbol, mtype, strat, sig_type, tf, price, sl, tp, qty, risk_amt, account, signal_ts_ms):
        if strat and "Sweep" in strat:
            result = CONTEXT.get(_key(symbol, int(signal_ts_ms)))
            if result is not None:
                base = original_msg(symbol, mtype, strat, sig_type, result.timeframe, price, sl, tp, qty, risk_amt, account, signal_ts_ms)
                return _signal_message(main, symbol, mtype, result) + "\n" + main.BR + "\n" + base
        return original_msg(symbol, mtype, strat, sig_type, tf, price, sl, tp, qty, risk_amt, account, signal_ts_ms)

    def _send_reminder(symbol, mtype, result):
        close_ts = int(result.candle_end.timestamp() * 1000)
        key = _key(symbol, close_ts)
        state = STATE.setdefault(key, {"initial": False, "reminder": False, "created": int(time.time() * 1000)})
        if state.get("reminder") or not state.get("initial") or time.time() * 1000 < close_ts + 3600 * 1000:
            return
        main.send_sweep_to_all(_signal_message(main, symbol, mtype, result, reminder=True), parse_mode="Markdown")
        state["reminder"] = True; state["reminder_sent"] = int(time.time() * 1000); _save()

    def handle_sweep_v2(symbol, mtype, sweep):
        direction, sweep_high, sweep_low, close_ts, open_ts, result = sweep
        key = _key(symbol, close_ts)
        state = STATE.setdefault(key, {"initial": False, "reminder": False, "created": int(time.time() * 1000)})
        if state.get("initial"):
            _send_reminder(symbol, mtype, result); return
        state.update({"initial": True, "direction": direction, "timeframe": result.timeframe,
                      "candle_start": result.candle_start.isoformat(), "candle_end": result.candle_end.isoformat(),
                      "high": result.current["High"], "low": result.current["Low"]})
        _save(); CONTEXT[key] = result
        if direction == "NEUTRAL":
            main.send_sweep_to_all(_signal_message(main, symbol, mtype, result), parse_mode="Markdown")
        else:
            account = "nifty" if ("^NSE" in symbol or symbol.endswith(".NS")) else "sweep_4h"
            entry = main.get_price(symbol)
            if entry is None:
                state["initial"] = False; _save(); main.alert_error(f"Sweep entry: {symbol}", "No live market price available"); return
            sl = sweep_low if direction == "BULLISH" else sweep_high
            main.execute(symbol, mtype, account, f"{result.timeframe} Sweep", direction, entry, sl, close_ts)
        _send_reminder(symbol, mtype, result)

    def notify_neutral_v2(symbol, mtype, sweep_high, sweep_low, sweep_ts_ms):
        result = CONTEXT.get(_key(symbol, int(sweep_ts_ms)))
        if result is not None:
            handle_sweep_v2(symbol, mtype, ("NEUTRAL", sweep_high, sweep_low, sweep_ts_ms, 0, result))

    main.check_sweep = check_sweep_v2
    main.handle_sweep = handle_sweep_v2
    main.notify_neutral_sweep = notify_neutral_v2
    main.msg_trade_signal = msg_trade_signal_v2
    main.SWEEP_ENGINE_VERSION = "v2.1"
    main.SWEEP_RULE = "closed candle: current high > previous high AND current low < previous low; close classifies BUY/NEUTRAL/SELL"
    main.SWEEP_DATA_WARNING = True
    print("[SWEEP V2.1] Canonical candle/sweep engine installed")
