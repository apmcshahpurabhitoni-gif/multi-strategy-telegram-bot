import json
import os
import sys
import threading
import time
from datetime import datetime
from urllib.parse import parse_qs
import pytz
SNAPSHOT_TTL=10
_snapshot_cache={"data":None,"ts":0};_snapshot_lock=threading.RLock();_HERE=os.path.dirname(os.path.abspath(__file__));_HTML_PATH=os.path.join(_HERE,"templates","index.html")
def _get_html_content():
    try:
        with open(_HTML_PATH,"rb") as f:return f.read()
    except Exception as exc:
        print("[DASHBOARD] template load:",exc);return b"<h1>Dashboard template index.html not found.</h1>"
def _get_main_module():return sys.modules.get("__main__") or sys.modules.get("main")
def _load_file(main,path,default):
    try:
        fn=getattr(main,"load_json",None)
        if fn:
            value=fn(path,default);return value if value is not None else default
    except Exception as exc:print("[DASHBOARD] load:",exc)
    try:
        if os.path.exists(path):
            with open(path,"r",encoding="utf-8") as f:return json.load(f)
    except Exception as exc:print("[DASHBOARD] file load:",exc)
    return default
def _parse_ts(value,default=0):
    if value is None or value=="":return default
    if isinstance(value,(int,float)):
        v=float(value);return int(v if v>10_000_000_000 else v*1000)
    text=str(value).strip()
    try:
        v=float(text);return int(v if v>10_000_000_000 else v*1000)
    except Exception:pass
    try:return int(datetime.fromisoformat(text.replace("Z","+00:00")).timestamp()*1000)
    except Exception:return default
def _direction(value):
    text=str(value or "").upper()
    if "BULL" in text or text in ("BUY","LONG"):return "BUY"
    if "BEAR" in text or text in ("SELL","SHORT"):return "SELL"
    return "NEUTRAL"
def _batch_live_prices(symbols):
    if not symbols:return {}
    main=_get_main_module()
    if not main:return {}
    out={};cache=getattr(main,"_price_cache",{});lock=getattr(main,"_lock",None);get_price=getattr(main,"get_price",None);now=time.time()
    if lock:
        with lock:
            for symbol,value in cache.items():
                if symbol in symbols and isinstance(value,(list,tuple)) and len(value)>=2 and now-value[1]<120:out[symbol]=value[0]
    missing=[s for s in symbols if s not in out]
    if missing:
        try:
            import yfinance as yf
            df=yf.download(tickers=','.join(missing),period="1d",interval="1d",progress=False,threads=True,timeout=15)
            if df is not None and not df.empty:
                close=df["Close"]
                if len(missing)==1:
                    values=close.dropna()
                    if not values.empty:out[missing[0]]=float(values.iloc[-1])
                else:
                    for symbol in missing:
                        try:
                            values=close[symbol].dropna()
                            if not values.empty:out[symbol]=float(values.iloc[-1])
                        except Exception:pass
        except Exception as exc:print("[DASHBOARD] price fetch:",exc)
    if get_price:
        for symbol in symbols:
            if symbol not in out:
                try:
                    value=get_price(symbol)
                    if value is not None:out[symbol]=float(value)
                except Exception:pass
    return out
def _build_equity_curve(history,starting=400000.0,days=60):
    daily={}
    for trade in history:
        date=str(trade.get("closed_at",trade.get("close_time",trade.get("time",""))))[:10]
        if not date:continue
        try:daily[date]=daily.get(date,0)+float(trade.get("pnl",0) or 0)
        except Exception:pass
    running=peak=starting;max_dd=max_dd_pct=0.0;points=[]
    for date in sorted(daily):
        running+=daily[date];peak=max(peak,running);drawdown=peak-running
        if drawdown>max_dd:max_dd=drawdown;max_dd_pct=drawdown/peak*100 if peak else 0
        points.append({"date":date,"equity":round(running,2)})
    points=points[-days:]
    return {"points":points,"current_equity":points[-1]["equity"] if points else starting,"max_drawdown_inr":round(max_dd,2),"max_drawdown_pct":round(max_dd_pct,2)}
def _history_signal_fallback(history,ist):
    out=[]
    for trade in history:
        if not isinstance(trade,dict):continue
        strategy=str(trade.get("strat",trade.get("strategy","")) or "")
        symbol=str(trade.get("symbol","") or "").strip()
        if not symbol or not strategy:continue
        direction=trade.get("direction",trade.get("type",trade.get("sig_type","")))
        if not direction:continue
        ts=_parse_ts(trade.get("signal_ts_ms",trade.get("opened_at",trade.get("opened",trade.get("time","")))),0)
        if not ts:ts=_parse_ts(trade.get("closed_at",trade.get("close_time","")),0)
        if not ts:continue
        try:dt=datetime.fromtimestamp(ts/1000,tz=ist)
        except Exception:continue
        out.append({"id":f"trade-signal:{trade.get('id',symbol)}:{ts}","time":dt.strftime("%d-%b %H:%M"),"sym":symbol,"dir":_direction(direction),"strategy":strategy,"status":"EXECUTED TRADE","pnl":float(trade.get("pnl",0) or 0),"hint":"Recovered from trade history","ts_ms":ts,"reminder":False,"date":dt.strftime("%Y-%m-%d")})
    out.sort(key=lambda x:x["ts_ms"],reverse=True)
    seen=set();unique=[]
    for item in out:
        key=(item["sym"],item["ts_ms"],item["dir"])
        if key in seen:continue
        seen.add(key);unique.append(item)
    return unique
def _build_actual_signals(main,ist,history=None):
    archive_path=os.environ.get("SIGNAL_HISTORY_FILE","/tmp/workspace/signal_history.json")
    rows=_load_file(main,archive_path,[]);signals=[]
    if isinstance(rows,list):
        for record in rows:
            if not isinstance(record,dict):continue
            timestamp=_parse_ts(record.get("candle_end"),0);symbol=str(record.get("symbol") or "").strip()
            if not symbol or not timestamp:continue
            try:dt=datetime.fromtimestamp(timestamp/1000,tz=ist)
            except Exception:continue
            signals.append({"id":record.get("id",f"{symbol}:{timestamp}"),"time":dt.strftime("%d-%b %H:%M"),"sym":symbol,"dir":_direction(record.get("direction")),"strategy":record.get("strategy") or f"{record.get('timeframe','4H')} Sweep","status":"REMINDER SENT" if record.get("reminder_sent") else "SIGNAL SAVED","pnl":0,"hint":"Confirmed sweep signal","ts_ms":timestamp,"reminder":bool(record.get("reminder_sent")),"date":dt.strftime("%Y-%m-%d")})
    if not signals and history:signals=_history_signal_fallback(history,ist)
    signals.sort(key=lambda item:item["ts_ms"],reverse=True);return signals
def _build_snapshot():
    main=_get_main_module()
    if not main:return {"error":"main module not loaded"}
    load_json=getattr(main,"load_json",None);lock=getattr(main,"_lock",None)
    if not load_json or not lock:return {"error":"missing bot globals"}
    ist=getattr(main,"IST",pytz.timezone("Asia/Kolkata"));now=datetime.now(ist);today=now.strftime("%Y-%m-%d")
    history=load_json(getattr(main,"HISTORY_FILE","trade_history.json"),[]) or [];accounts=getattr(main,"accounts",{}) or {};active=getattr(main,"active_trades",[]) or [];limits=getattr(main,"ACCOUNT_LIMITS",{}) or {}
    per_today={key:0.0 for key in accounts}
    for trade in history:
        if str(trade.get("closed_at",trade.get("close_time","")))[:10]==today:
            try:
                account=trade.get("account");per_today[account]=per_today.get(account,0)+float(trade.get("pnl",0) or 0)
            except Exception:pass
    accounts_view={}
    for key,account in accounts.items():
        if isinstance(account,dict):accounts_view[key]={"name":key.replace("_"," ").title(),"balance":float(account.get("balance",0) or 0),"daily_trades":int(account.get("daily_trades",0) or 0),"daily_limit":int(limits.get(key,0) or 0),"today_pnl":round(per_today.get(key,0),2)}
    symbols=[trade.get("symbol") for trade in active if trade.get("symbol")];prices=_batch_live_prices(symbols);live=[]
    for trade in active:
        symbol=trade.get("symbol");entry=float(trade.get("entry",0) or 0);qty=float(trade.get("qty",0) or 0);sl=float(trade.get("sl",trade.get("trail_sl",0)) or 0);tp=float(trade.get("tp",0) or 0);trade_type=str(trade.get("type",trade.get("direction","LONG"))).upper();is_long="LONG" in trade_type or "BULL" in trade_type or trade_type=="BUY";current=float(prices.get(symbol,entry) or entry);pnl=(current-entry)*qty*(1 if is_long else -1)
        live.append({"id":trade.get("id",""),"symbol":symbol,"market":trade.get("market",trade.get("mtype","")),"account":trade.get("account",""),"direction":"LONG" if is_long else "SHORT","entry":entry,"current":current,"sl":sl,"tp":tp,"qty":qty,"pnl_inr":round(pnl,2),"opened":trade.get("opened_at",trade.get("opened","")),"strategy":trade.get("strat",trade.get("strategy",""))})
    signals=_build_actual_signals(main,ist,history);news=[];cached=getattr(main,"get_cached_news",None);fetch=getattr(main,"fetch_news",None)
    try:
        if cached:news=cached() or []
    except Exception as exc:print("[DASHBOARD] cached news:",exc)
    if not news and fetch:
        try:news=fetch() or []
        except Exception as exc:print("[DASHBOARD] fetch news:",exc)
    normalized_news=[]
    for event in news[:120]:
        if isinstance(event,dict):
            item=dict(event);item["impact"]=str(item.get("impact") or item.get("importance") or "LOW").upper();normalized_news.append(item)
    history_sorted=sorted(history,key=lambda item:str(item.get("closed_at",item.get("close_time",item.get("time","")))),reverse=True)[:30];curve=_build_equity_curve(history);total=sum(float(item.get("pnl",0) or 0) for item in history)
    recent_trades=[]
    for trade in history_sorted:
        if not isinstance(trade,dict):continue
        recent_trades.append({"id":trade.get("id",""),"symbol":trade.get("symbol",""),"market":trade.get("market",trade.get("mtype","")),"account":trade.get("account",""),"direction":"LONG" if "LONG" in str(trade.get("type",trade.get("direction",""))).upper() or "BUY" in str(trade.get("direction","")).upper() else "SHORT","entry":trade.get("entry",0),"current":trade.get("exit",trade.get("close_price",trade.get("live",0))),"sl":trade.get("trail_sl",trade.get("sl",0)),"tp":trade.get("tp",0),"qty":trade.get("qty",0),"pnl_inr":float(trade.get("pnl",0) or 0),"opened":trade.get("opened_at",trade.get("opened",trade.get("time",""))),"closed":trade.get("closed_at",trade.get("close_time","")),"strategy":trade.get("strat",trade.get("strategy","")),"status":"CLOSED"})
    return {"generated_at":now.strftime("%Y-%m-%d %H:%M:%S IST"),"accounts":accounts_view,"live_trades":live,"recent_trades":recent_trades,"today_signals":signals,"signals":signals,"history":history_sorted,"history_total":len(history),"pending":[],"news_raw":normalized_news,"news":normalized_news,"equity_curve":curve,"risk":{"max_drawdown_inr":curve["max_drawdown_inr"],"max_drawdown_pct":curve["max_drawdown_pct"]},"total_pnl":round(total,2)}
def _get_snapshot_cached():
    now=time.time()
    with _snapshot_lock:
        if _snapshot_cache["data"] is not None and now-_snapshot_cache["ts"]<SNAPSHOT_TTL:return {"cached":True,"cache_age_s":int(now-_snapshot_cache["ts"]),**_snapshot_cache["data"]}
    snapshot=_build_snapshot()
    with _snapshot_lock:_snapshot_cache["data"]=snapshot;_snapshot_cache["ts"]=now
    return {"cached":False,**snapshot}
def _json_response(start_response,payload,status="200 OK"):
    body=json.dumps(payload,default=str).encode("utf-8");start_response(status,[("Content-Type","application/json"),("Content-Length",str(len(body))),("Cache-Control","no-store")]);return [body]
def _html_response(start_response,body,status="200 OK"):
    if isinstance(body,str):body=body.encode("utf-8")
    start_response(status,[("Content-Type","text/html; charset=utf-8"),("Content-Length",str(len(body))),("Cache-Control","no-store")]);return [body]
def _route_backtest(start_response,environ):
    try:
        query=parse_qs(environ.get("QUERY_STRING",""));symbol=(query.get("symbol",[""])[0] or "").strip().upper();strategy=(query.get("strategy",["trendpulse"])[0] or "trendpulse").lower();days=max(7,min(int(query.get("days",["30"])[0] or 30),730))
        if not symbol:return _json_response(start_response,{"error":"symbol required"},"400 Bad Request")
        from backtest import BacktestEngine
        engine=BacktestEngine();result=engine.backtest_sweep(symbol,days) if strategy=="sweep" else engine.backtest_trendpulse(symbol,days)
        if not isinstance(result,dict):result={"error":"backtest failed"}
        if "error" not in result:result={"metrics":result,"symbol":symbol,"strategy":strategy,"days":days}
        else:result.update({"symbol":symbol,"strategy":strategy,"days":days})
        return _json_response(start_response,result)
    except Exception as exc:return _json_response(start_response,{"error":str(exc)},"500 Internal Server Error")
def _route_close_trade(start_response,environ):
    try:
        length=int(environ.get("CONTENT_LENGTH",0) or 0);data=json.loads(environ["wsgi.input"].read(length).decode("utf-8")) if length else {};trade_id=data.get("trade_id","");main=_get_main_module()
        if not trade_id:return _json_response(start_response,{"success":False,"error":"trade_id required"},"400 Bad Request")
        fn=getattr(main,"force_close_trade",None) if main else None;ok,message=fn(trade_id,reason="Dashboard") if fn else (False,"Not found");return _json_response(start_response,{"success":ok,"message":message})
    except Exception as exc:return _json_response(start_response,{"success":False,"error":str(exc)},"500 Internal Server Error")
def _route_refresh_news(start_response,environ):
    main=_get_main_module()
    try:
        items=main.fetch_news() if main and hasattr(main,"fetch_news") else [];return _json_response(start_response,{"ok":True,"items":len(items or [])})
    except Exception as exc:return _json_response(start_response,{"ok":False,"error":str(exc)},"500 Internal Server Error")
def register_routes(path,start_response,environ):
    method=environ.get("REQUEST_METHOD","GET")
    if path in ("/dashboard","/dashboard/"):return _html_response(start_response,_get_html_content())
    if path=="/api/dashboard":
        try:return _json_response(start_response,_get_snapshot_cached())
        except Exception as exc:return _json_response(start_response,{"error":str(exc)},"500 Internal Server Error")
    if path.startswith("/api/backtest"):return _route_backtest(start_response,environ)
    if path.startswith("/api/prices"):
        symbols=parse_qs(environ.get("QUERY_STRING","" )).get("symbols",[""])[0].split(",");return _json_response(start_response,{"prices":_batch_live_prices([symbol for symbol in symbols if symbol]),"ts":int(time.time())})
    if path=="/api/health":return _json_response(start_response,{"ok":True,"ts":int(time.time())})
    if path=="/api/close-trade" and method=="POST":return _route_close_trade(start_response,environ)
    if path=="/api/refresh-news" and method=="POST":return _route_refresh_news(start_response,environ)
    return None
