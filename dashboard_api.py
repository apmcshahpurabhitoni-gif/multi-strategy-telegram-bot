import os
import sys
import json
import time
import threading
from datetime import datetime, timedelta
from urllib.parse import parse_qs
import pytz

PRICE_TTL = 60
SNAPSHOT_TTL = 15
NEWS_TTL = 600

_snapshot_cache = {"data": None, "ts": 0}
_snapshot_lock = threading.RLock()

_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML_PATH_PRIMARY = os.path.join(_HERE, "templates", "index.html")
_HTML_PATH_FALLBACK = os.path.join(_HERE, "dashboard", "index.html")

def _get_html_content() -> bytes:
    if os.path.exists(_HTML_PATH_PRIMARY):
        with open(_HTML_PATH_PRIMARY, "rb") as f: return f.read()
    if os.path.exists(_HTML_PATH_FALLBACK):
        with open(_HTML_PATH_FALLBACK, "rb") as f: return f.read()
    return b"<h1>Dashboard template index.html not found.</h1>"

def _get_main_module():
    main = sys.modules.get("__main__")
    if main is not None: return main
    return sys.modules.get("main")

def _batch_live_prices(symbols):
    if not symbols: return {}
    main = _get_main_module()
    if main is None: return {}
    _price_cache = getattr(main, "_price_cache", None)
    _lock = getattr(main, "_lock", None)
    get_price_fn = getattr(main, "get_price", None)
    now = time.time(); out = {}
    if _price_cache is not None and _lock is not None:
        with _lock:
            for s in symbols:
                if s in _price_cache:
                    p, ts = _price_cache[s]
                    if now - ts < 120: out[s] = p
    need = [s for s in symbols if s not in out]
    indices = [s for s in need if s.startswith("^")]
    regular = [s for s in need if not s.startswith("^")]
    if regular:
        try:
            import yfinance as yf
            df = yf.download(tickers=",".join(regular), period="1d", interval="1d", progress=False, threads=True, timeout=15)
            if df is not None and not df.empty:
                if len(regular) == 1:
                    close = df["Close"].dropna()
                    if not close.empty: out[regular[0]] = float(close.iloc[-1])
                else:
                    for s in regular:
                        try:
                            if s in df["Close"].columns:
                                val = df["Close"][s].dropna()
                                if not val.empty: out[s] = float(val.iloc[-1])
                        except Exception: pass
        except Exception as e: print(f"[PRICE] batch yf.download failed: {e}")
    for s in indices:
        if get_price_fn:
            try:
                p = get_price_fn(s)
                if p: out[s] = float(p)
            except Exception: pass
        time.sleep(0.2)
    still_need = [s for s in symbols if s not in out]
    if get_price_fn and still_need:
        for s in still_need:
            try:
                p = get_price_fn(s)
                if p: out[s] = float(p)
            except Exception: pass
            time.sleep(0.2)
    return out

DEFAULT_STARTING_EQUITY = 400000.0

def _build_equity_curve(history, starting_equity=DEFAULT_STARTING_EQUITY, days=60):
    if not history: return {"points": [], "current_equity": starting_equity, "max_drawdown_inr": 0.0, "max_drawdown_pct": 0.0}
    def _closed_key(t): return str(t.get("closed_at", t.get("close_time", t.get("time", t.get("timestamp", "")))))
    daily_pnl = {}
    for t in history:
        date_part = _closed_key(t)[:10]
        if not date_part: continue
        try: pnl = float(t.get("pnl", 0))
        except Exception: pnl = 0.0
        daily_pnl[date_part] = daily_pnl.get(date_part, 0.0) + pnl
    running=peak=starting_equity; max_dd_inr=max_dd_pct=0.0; points=[]
    for date in sorted(daily_pnl.keys()):
        running += daily_pnl[date]; peak=max(peak,running); dd=peak-running; dd_pct=(dd/peak*100.0) if peak>0 else 0.0
        if dd>max_dd_inr: max_dd_inr,max_dd_pct=dd,dd_pct
        points.append({"date":date,"equity":round(running,2)})
    points=points[-days:]
    return {"points":points,"current_equity":points[-1]["equity"] if points else starting_equity,"max_drawdown_inr":round(max_dd_inr,2),"max_drawdown_pct":round(max_dd_pct,2)}

def _build_risk(live_trades_view, equity_curve):
    total_exposure=total_risk_inr=0.0; trades_risk=[]
    for t in live_trades_view:
        entry=float(t.get("entry",0) or 0); sl=float(t.get("sl",0) or 0); cur=float(t.get("current",0) or entry); qty=float(t.get("qty",0) or 0); is_long=t.get("direction")=="LONG"
        exposure=abs(entry*qty); total_exposure+=exposure; risk_per_unit=abs(entry-sl) if sl else 0.0; initial_risk=risk_per_unit*qty; total_risk_inr+=initial_risk
        r_multiple=round(((cur-entry) if is_long else (entry-cur))/risk_per_unit,2) if risk_per_unit>0 else 0.0
        trades_risk.append({"symbol":t.get("symbol"),"account":t.get("account"),"direction":t.get("direction"),"r_multiple":r_multiple,"risk_inr":round(initial_risk,2)})
    return {"total_exposure_inr":round(total_exposure,2),"total_risk_inr":round(total_risk_inr,2),"open_trades_risk":trades_risk,"max_drawdown_inr":equity_curve.get("max_drawdown_inr",0.0),"max_drawdown_pct":equity_curve.get("max_drawdown_pct",0.0)}

def _build_snapshot():
    main=_get_main_module()
    if main is None:return {"error":"main module not loaded"}
    accounts,active_trades,_lock=getattr(main,"accounts",{}),getattr(main,"active_trades",[]),getattr(main,"_lock",None)
    load_json=getattr(main,"load_json",None); ACCOUNT_LIMITS,is_ny_session=getattr(main,"ACCOUNT_LIMITS",{}),getattr(main,"is_ny_session",None); HISTORY_FILE=getattr(main,"HISTORY_FILE","trade_history.json"); SENT_SIGNALS_FILE=getattr(main,"SENT_SIGNALS_FILE","sent_signals.json"); get_cached_news=getattr(main,"get_cached_news",None); IST_tz=getattr(main,"IST",pytz.timezone("Asia/Kolkata"))
    if not all([_lock,load_json,IST_tz]):return {"error":"missing bot globals"}
    try: now=datetime.now(IST_tz)
    except Exception: now=datetime.now()
    today_str,week_start=now.strftime("%Y-%m-%d"),(now-timedelta(days=7)).strftime("%Y-%m-%d")
    history=load_json(HISTORY_FILE,[]) if load_json else []; sent=load_json(SENT_SIGNALS_FILE,{}) if load_json else []; sent_memory=getattr(main,"sent_signals",{})
    if isinstance(sent_memory,dict) and len(sent_memory)>len(sent):sent=sent_memory
    per_acc_today={k:0.0 for k in accounts}; per_acc_week={k:0.0 for k in accounts}
    for t in history:
        acc=t.get("account")
        try:pnl=float(t.get("pnl",0))
        except Exception:pnl=0.0
        ts=str(t.get("closed_at",t.get("close_time","")))[:10]
        if acc in per_acc_today:
            if ts==today_str:per_acc_today[acc]+=pnl
            if ts>=week_start:per_acc_week[acc]+=pnl
    accounts_view={}
    for key,acc in (accounts or {}).items():
        if not isinstance(acc,dict):continue
        ny_active=False
        if key=="ny_session" and is_ny_session:
            try:ny_active=is_ny_session()
            except Exception:pass
        accounts_view[key]={"name":key.replace("_"," ").title(),"balance":float(acc.get("balance",0)),"daily_trades":int(acc.get("daily_trades",0)),"daily_limit":int(ACCOUNT_LIMITS.get(key,0)),"today_pnl":round(per_acc_today.get(key,0.0),2),"week_pnl":round(per_acc_week.get(key,0.0),2),"is_active":ny_active}
    symbols=list({t.get("symbol") for t in active_trades if t.get("symbol")}); live=_batch_live_prices(symbols) if symbols else {}; live_trades_view=[]
    for t in active_trades:
        sym=t.get("symbol"); entry,sl,tp,qty=float(t.get("entry",0)),float(t.get("sl",0)),float(t.get("tp",0)),float(t.get("qty",0)); direction=str(t.get("type",t.get("direction","LONG"))).upper(); is_long="BULL" in direction or "LONG" in direction; cur=live.get(sym,entry); pnl=(cur-entry)*qty*(1 if is_long else -1)
        if is_long and tp!=entry:progress=max(0.0,min(100.0,(cur-entry)/(tp-entry)*100.0))
        elif (not is_long) and entry!=tp:progress=max(0.0,min(100.0,(entry-cur)/(entry-tp)*100.0))
        else:progress=0.0
        live_trades_view.append({"id":t.get("id",""),"symbol":sym,"market":t.get("market",t.get("mtype","—")),"account":t.get("account",""),"direction":"LONG" if is_long else "SHORT","entry":entry,"current":cur,"sl":sl,"tp":tp,"qty":qty,"pnl_inr":round(pnl,2),"progress":round(progress,1),"opened":t.get("opened_at",t.get("opened",""))})
    today_signals=[]; cutoff=time.time()*1000-24*3600*1000
    for key,sig in (sent or {}).items():
        ts_ms=sig.get("ts_ms",0) if isinstance(sig,dict) else 0; sym=sig.get("symbol","") if isinstance(sig,dict) else ""; sig_type=sig.get("sig_type","") if isinstance(sig,dict) else ""; strat=sig.get("strat","") if isinstance(sig,dict) else ""; status=sig.get("status","open") if isinstance(sig,dict) else "open"; pnl=sig.get("pnl",0) if isinstance(sig,dict) else 0; hint=sig.get("hint","") if isinstance(sig,dict) else ""; time_str=sig.get("time_str","") if isinstance(sig,dict) else ""
        if not isinstance(sig,dict):
            parts=str(key).split("_")
            if len(parts)>=3:sym,ts_ms,sig_type,strat=parts[0],int(parts[1]) if parts[1].isdigit() else 0,parts[2],parts[3] if len(parts)>3 else ""
        if ts_ms:
            try:time_str=datetime.fromtimestamp(ts_ms/1000,tz=IST_tz).strftime("%d-%b %H:%M")
            except Exception:pass
        if ts_ms<cutoff:continue
        age_hr=(time.time()*1000-ts_ms)/3600000
        tag="🔥 FRESH" if age_hr<=1 else ("⚠️ STALE" if age_hr>=2 else "◷ AGING")
        today_signals.append({"time":time_str,"sym":sym,"dir":"LONG" if "BULL" in str(sig_type).upper() else "SHORT","strategy":strat,"status":status,"pnl":pnl,"hint":hint,"tag":tag,"ts_ms":ts_ms})
    today_signals.sort(key=lambda x:x.get("ts_ms",0),reverse=True)
    last_history=sorted(history,key=lambda x:str(x.get("closed_at","")),reverse=True)[:15]
    news=[]
    if get_cached_news:
        try:
            raw_news=get_cached_news()
            if raw_news:news=[dict(ev,impact=str(ev.get("impact","")).upper()) for ev in raw_news[:120]]
        except Exception as e:print(f"[DASHBOARD] Failed to load news: {e}")
    strategy_stats={}
    for t in history:
        strat=t.get("strat","Unknown")
        if strat not in strategy_stats:strategy_stats[strat]={"wins":0,"losses":0,"pnl":0.0,"trades":0}
        strategy_stats[strat]["trades"]+=1
        if t.get("result")=="WIN":strategy_stats[strat]["wins"]+=1
        elif t.get("result")=="LOSS":strategy_stats[strat]["losses"]+=1
        try:strategy_stats[strat]["pnl"]+=float(t.get("pnl",0))
        except Exception:pass
    for s in strategy_stats.values():s["win_rate"]=round((s["wins"]/s["trades"]*100.0) if s["trades"] else 0.0,1)
    equity_curve=_build_equity_curve(history); risk=_build_risk(live_trades_view,equity_curve)
    return {"generated_at":datetime.now(IST_tz).isoformat(),"accounts":accounts_view,"live_trades":live_trades_view,"today_signals":today_signals,"history":last_history,"news_raw":news,"risk":risk,"equity_curve":equity_curve,"strategy_stats":strategy_stats}

def get_snapshot(force=False):
    now=time.time()
    with _snapshot_lock:
        if not force and _snapshot_cache["data"] is not None and now-_snapshot_cache["ts"]<SNAPSHOT_TTL:return _snapshot_cache["data"]
        data=_build_snapshot(); _snapshot_cache.update(data=data,ts=now); return data

def register_routes(path,start_response,environ):
    if path in ("","/"):
        body=_get_html_content(); start_response("200 OK",[("Content-Type","text/html; charset=utf-8"),("Cache-Control","no-store")]); return [body]
    if path=="/api/dashboard":
        qs=parse_qs(environ.get("QUERY_STRING","")); data=get_snapshot(force=qs.get("force",["0"])[0]=="1"); body=json.dumps(data,default=str).encode(); start_response("200 OK",[("Content-Type","application/json; charset=utf-8"),("Cache-Control","no-store")]); return [body]
    if path=="/api/close-trade":
        if environ.get("REQUEST_METHOD")!="POST":start_response("405 Method Not Allowed",[("Content-Type","application/json")]);return [b'{"error":"POST required"}']
        try:
            length=int(environ.get("CONTENT_LENGTH") or 0); payload=json.loads(environ["wsgi.input"].read(length) or b"{}"); trade_id=str(payload.get("trade_id","")); main=_get_main_module()
            fn=getattr(main,"close_trade_by_id",None) if main else None
            if not fn:raise RuntimeError("Close-trade endpoint unavailable")
            result=fn(trade_id); body=json.dumps(result,default=str).encode(); start_response("200 OK",[("Content-Type","application/json")]); return [body]
        except Exception as e:
            body=json.dumps({"success":False,"error":str(e)}).encode();start_response("400 Bad Request",[("Content-Type","application/json")]);return [body]
    if path=="/api/refresh-news":
        if environ.get("REQUEST_METHOD")!="POST":start_response("405 Method Not Allowed",[("Content-Type","application/json")]);return [b'{"ok":false,"error":"POST required"}']
        try:
            main=_get_main_module(); fn=getattr(main,"get_cached_news",None) if main else None
            if not fn:raise RuntimeError("News provider unavailable")
            items=fn(force=True); _snapshot_cache["ts"]=0; body=json.dumps({"ok":True,"items":len(items or [])}).encode();start_response("200 OK",[("Content-Type","application/json")]);return [body]
        except Exception as e:
            body=json.dumps({"ok":False,"error":str(e)}).encode();start_response("400 Bad Request",[("Content-Type","application/json")]);return [body]
    if path=="/api/backtest":
        try:
            main=_get_main_module(); fn=getattr(main,"run_backtest_api",None) if main else None
            if not fn:raise RuntimeError("Backtest endpoint unavailable")
            qs=parse_qs(environ.get("QUERY_STRING","")); symbol=qs.get("symbol",["^NSEI"])[0]; strategy=qs.get("strategy",["sweep"])[0]; days=int(qs.get("days",[30])[0]); result=fn(symbol,strategy,days); body=json.dumps(result,default=str).encode();start_response("200 OK",[("Content-Type","application/json")]);return [body]
        except Exception as e:
            body=json.dumps({"error":str(e)}).encode();start_response("400 Bad Request",[("Content-Type","application/json")]);return [body]
    start_response("404 Not Found",[("Content-Type","application/json")]);return [b'{"error":"Not found"}']
