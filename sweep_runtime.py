"""Runtime integration for the canonical sweep engine."""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timedelta
from sweep_engine import detect_sweep, build_closed_candles

STATE_FILE = "/tmp/workspace/sweep_runtime_state.json"
SIGNAL_HISTORY_FILE = "/tmp/workspace/signal_history.json"
CONTEXT = {}
STATE = {}
STARTUP_BASELINE = {}
_MAIN = None  # set by install(); enables Supabase-backed persistence


def _load():
    global STATE
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f: STATE = json.load(f)
    except Exception: STATE = {}


def _save():
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(STATE, f, indent=2)
    os.replace(tmp, STATE_FILE)


def _save_signal_event(symbol, mtype, result):
    """Persist every confirmed sweep signal. Dashboard history never expires.

    Storage is routed through main.load_json/save_json when available, so the
    archive is mirrored to Supabase and restored after every redeploy. The
    Telegram reminder expiry lives in STATE_FILE only and never touches this.
    """
    try:
        rows = _load_signal_history()
        if not isinstance(rows, list): rows = []
        close_ts = int(result.candle_end.timestamp() * 1000)
        event_id = _key(symbol, close_ts)
        if any(isinstance(x, dict) and x.get("id") == event_id for x in rows): return
        rows.append({
            "id": event_id, "symbol": symbol, "market": mtype, "direction": result.direction,
            "strategy": f"{result.timeframe} Sweep", "timeframe": result.timeframe,
            "candle_start": result.candle_start.isoformat(), "candle_end": result.candle_end.isoformat(),
            "created_at": datetime.now().astimezone().isoformat(), "reminder_sent": False,
        })
        _write_signal_history(rows)
    except Exception as e: print("[SWEEP] signal history save:", e)


def _key(symbol, close_ts): return f"{symbol}:{int(close_ts)}"


def _fmt_ohlc(v, cur):
    return (f"O `{cur}{v['Open']:,.4f}`  H `{cur}{v['High']:,.4f}`  " f"L `{cur}{v['Low']:,.4f}`  C `{cur}{v['Close']:,.4f}`")


def _source_warning(symbol):
    if symbol in {"GC=F", "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X", "AUDUSD=X", "USDCAD=X", "NZDUSD=X"}:
        return "⚠️ *DATA SOURCE WARNING:* Bot data is Yahoo Finance; TradingView reference is OANDA. Verify OHLC before relying on the signal."
    return "⚠️ *DATA SOURCE NOTE:* Bot candle data comes from the configured free provider. Verify against TradingView if prices differ."


def _signal_message(main, symbol, mtype, result, reminder=False):
    cur=main._currency(symbol); name=main.display_name(symbol); prev,curr=result.previous,result.current
    start=result.candle_start.strftime("%d-%b-%Y %H:%M IST"); end=result.candle_end.strftime("%d-%b-%Y %H:%M IST"); prev_duration=result.candle_end-result.candle_start
    pstart=(result.candle_start-prev_duration).strftime("%d-%b-%Y %H:%M IST"); pEnd=result.candle_start.strftime("%d-%b-%Y %H:%M IST")
    icon="🔔" if reminder else ({"BULLISH":"🟢","BEARISH":"🔴","NEUTRAL":"🔥"}[result.direction]); label="REMINDER — " if reminder else ""
    result_label={"BULLISH":"BUY","BEARISH":"SELL","NEUTRAL":"NEUTRAL SWEEP"}[result.direction]
    action="📝 PAPER BUY" if result.direction=="BULLISH" else "📝 PAPER SELL" if result.direction=="BEARISH" else "ℹ️ INFORMATIONAL — NO PAPER TRADE"
    warning=result.schedule_warning or _source_warning(symbol)
    return (f"{icon} *{label}SWEEP — {name}*\n{main.BR}\n" f"🪙 *Asset:* `{name}` (`{symbol}`)\n🌐 *Market:* `{mtype}`\n" f"⏱ *Timeframe:* `{result.timeframe}`\n" f"🕯 *Previous Candle:* `{pstart}` → `{pEnd}`\n{_fmt_ohlc(prev,cur)}\n" f"🕯 *Current Candle:* `{start}` → `{end}`\n{_fmt_ohlc(curr,cur)}\n{main.BR}\n" f"✓ *High swept:* `YES` — {cur}{curr['High']:,.4f} > {cur}{prev['High']:,.4f}\n" f"✓ *Low swept:* `YES` — {cur}{curr['Low']:,.4f} < {cur}{prev['Low']:,.4f}\n" f"📌 *Previous range:* `{cur}{prev['Low']:,.4f}` → `{cur}{prev['High']:,.4f}`\n" f"📍 *Close classification:* `{result_label}`\n{action}\n{main.BR}\n{warning}\n⏰ *Confirmed:* `{end}`\n{main.BR2}")


def install(main):
    global CONTEXT, STARTUP_BASELINE, _MAIN
    _MAIN = main
    _load(); CONTEXT={}; STARTUP_BASELINE={}
    try:
        _load_signal_history()  # hydrate local archive from Supabase for the dashboard
    except Exception:
        pass
    main._sweep_runtime_original_check=main.check_sweep; main._sweep_runtime_original_handle=main.handle_sweep; main._sweep_runtime_original_notify=main.notify_neutral_sweep
    original_msg=main.msg_trade_signal

    def check_sweep_v2(symbol, df=None):
        try:
            now=datetime.now(main.IST); bars,tf,_=build_closed_candles(df,symbol,now)
            if len(bars)<2:return None
            latest_start=bars.index[-1]
            if symbol in ("^NSEI","^NSEBANK"): latest_close=latest_start+timedelta(hours=1)
            elif symbol.endswith(".NS") and getattr(latest_start,"hour",None)==13: latest_close=latest_start+timedelta(hours=2)
            else: latest_close=latest_start+timedelta(hours=4)
            latest_close_ms=int(latest_close.timestamp()*1000)
            if symbol not in STARTUP_BASELINE: STARTUP_BASELINE[symbol]=latest_close_ms; return None
            result=detect_sweep(df,symbol,now)
            if result is None:return None
            close_ts=int(result.candle_end.timestamp()*1000); open_ts=int(result.candle_start.timestamp()*1000); age_ms=int(now.timestamp()*1000)-close_ts
            if age_ms>3600*1000:return None
            if close_ts<=STARTUP_BASELINE[symbol]:return None
            CONTEXT[_key(symbol,close_ts)]=result
            return (result.direction,result.current["High"],result.current["Low"],close_ts,open_ts,result)
        except Exception as e: main.alert_error(f"Sweep candle engine: {symbol}",e); return None

    def msg_trade_signal_v2(symbol,mtype,strat,sig_type,tf,price,sl,tp,qty,risk_amt,account,signal_ts_ms):
        if strat and "Sweep" in strat:
            result=CONTEXT.get(_key(symbol,int(signal_ts_ms)))
            if result is not None:
                base=original_msg(symbol,mtype,strat,sig_type,result.timeframe,price,sl,tp,qty,risk_amt,account,signal_ts_ms)
                return _signal_message(main,symbol,mtype,result)+"\n"+main.BR+"\n"+base
        return original_msg(symbol,mtype,strat,sig_type,tf,price,sl,tp,qty,risk_amt,account,signal_ts_ms)

    def _send_reminder(symbol,mtype,result):
        close_ts=int(result.candle_end.timestamp()*1000); key=_key(symbol,close_ts); state=STATE.setdefault(key,{"initial":False,"reminder":False,"created":int(time.time()*1000)})
        if state.get("reminder") or not state.get("initial") or time.time()*1000<close_ts+3600*1000:return
        main.send_sweep_to_all(_signal_message(main,symbol,mtype,result,reminder=True),parse_mode="Markdown")
        state["reminder"]=True; state["reminder_sent"]=int(time.time()*1000); _save()
        try:
            rows=_load_signal_history();
            for row in rows:
                if row.get("id")==key: row["reminder_sent"]=True
            _write_signal_history(rows)
        except Exception: pass

    def handle_sweep_v2(symbol,mtype,sweep):
        direction,sweep_high,sweep_low,close_ts,open_ts,result=sweep; key=_key(symbol,close_ts); state=STATE.setdefault(key,{"initial":False,"reminder":False,"created":int(time.time()*1000)})
        if state.get("initial"):_send_reminder(symbol,mtype,result); return
        state.update({"initial":True,"direction":direction,"timeframe":result.timeframe,"candle_start":result.candle_start.isoformat(),"candle_end":result.candle_end.isoformat(),"high":result.current["High"],"low":result.current["Low"]})
        _save(); CONTEXT[key]=result; _save_signal_event(symbol,mtype,result)
        if direction=="NEUTRAL": main.send_sweep_to_all(_signal_message(main,symbol,mtype,result),parse_mode="Markdown")
        else:
            account="nifty" if ("^NSE" in symbol or symbol.endswith(".NS")) else "sweep_4h"; entry=main.get_price(symbol)
            if entry is None: state["initial"]=False; _save(); main.alert_error(f"Sweep entry: {symbol}","No live market price available"); return
            sl=sweep_low if direction=="BULLISH" else sweep_high; main.execute(symbol,mtype,account,f"{result.timeframe} Sweep",direction,entry,sl,close_ts)
        _send_reminder(symbol,mtype,result)

    def notify_neutral_v2(symbol,mtype,sweep_high,sweep_low,sweep_ts_ms):
        result=CONTEXT.get(_key(symbol,int(sweep_ts_ms)))
        if result is not None: handle_sweep_v2(symbol,mtype,("NEUTRAL",sweep_high,sweep_low,sweep_ts_ms,0,result))

    main.check_sweep=check_sweep_v2; main.handle_sweep=handle_sweep_v2; main.notify_neutral_sweep=notify_neutral_v2; main.msg_trade_signal=msg_trade_signal_v2
    main.SWEEP_ENGINE_VERSION="v2.2"; main.SWEEP_RULE="closed candle: current high > previous high AND current low < previous low; close classifies BUY/NEUTRAL/SELL"; main.SWEEP_DATA_WARNING=True
    print("[SWEEP V2.2] Canonical candle/sweep engine installed; startup backfill disabled")


def _load_signal_history():
    fn = getattr(_MAIN, "load_json", None)
    if fn:
        try:
            rows = fn(SIGNAL_HISTORY_FILE, [])
            return rows if isinstance(rows, list) else []
        except Exception as e:
            print("[SWEEP] signal history load:", e)
    try:
        with open(SIGNAL_HISTORY_FILE, "r", encoding="utf-8") as f:
            rows = json.load(f)
            return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _write_signal_history(rows):
    fn = getattr(_MAIN, "save_json", None)
    if fn:
        try:
            fn(SIGNAL_HISTORY_FILE, rows)
            return
        except Exception as e:
            print("[SWEEP] signal history save_json:", e)
    try:
        os.makedirs(os.path.dirname(SIGNAL_HISTORY_FILE), exist_ok=True)
        tmp = SIGNAL_HISTORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2)
        os.replace(tmp, SIGNAL_HISTORY_FILE)
    except Exception as e:
        print("[SWEEP] signal history write:", e)