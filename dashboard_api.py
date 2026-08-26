import os, sys, json, time, threading
from datetime import datetime
from urllib.parse import parse_qs
import pytz

SNAPSHOT_TTL=10
_snapshot_cache={"data":None,"ts":0}
_snapshot_lock=threading.RLock()
_HERE=os.path.dirname(os.path.abspath(__file__))
_HTML_PATH_PRIMARY=os.path.join(_HERE,"templates","index.html")
_HTML_PATH_FALLBACK=os.path.join(_HERE,"dashboard","index.html")


def _get_html_content():
    for p in (_HTML_PATH_PRIMARY,_HTML_PATH_FALLBACK):
        if os.path.exists(p):
            with open(p,"rb") as f: body=f.read()
            override=b'''<script>(function(){function e(s){return String(s==null?'':s).replace(/[&<>\"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]})}function d(v){v=String(v||'').toUpperCase();return v.indexOf('BUY')>=0||v.indexOf('BULL')>=0?'BUY':v.indexOf('SELL')>=0||v.indexOf('BEAR')>=0?'SELL':'NEUTRAL'}function r(a){var g={};(a||[]).forEach(function(x){var k=x.date||String(x.time||'').slice(0,10)||'Other';(g[k]||(g[k]=[])).push(x)});var ks=Object.keys(g).sort().reverse();return ks.map(function(k){var items=g[k].sort(function(a,b){return Number(b.ts_ms||0)-Number(a.ts_ms||0)}).map(function(x){var q=d(x.dir||x.direction);var cls=q==='BUY'?'p3-buy':q==='SELL'?'p3-sell':'p3-neutral';return '<div class="p3-signal"><div class="p3-main"><div><div class="p3-symbol">'+e(x.sym||x.symbol||'—')+'</div><div class="p3-sub">'+e(x.strategy||'Sweep')+' · '+e(x.time||'')+'</div></div><div class="p3-side"><span class="p3-dir '+cls+'">'+q+'</span><span class="p3-pnl">'+e(x.status||'SIGNAL')+'</span></div></div></div>'}).join('');return '<div class="p3-date">'+e(k==='Other'?'OTHER':k)+'</div>'+items}).join('')||'<div class="empty">No saved signals.</div>'}function load(){fetch('/api/dashboard',{cache:'no-store'}).then(function(x){return x.json()}).then(function(d){var el=document.getElementById('signalsList'),latest=document.getElementById('latest'),s=d.signals||d.today_signals||[];if(el)el.innerHTML=r(s);if(latest)latest.innerHTML=(s||[]).slice(0,3).map(function(x){var q=d(x.dir||x.direction),c=q==='BUY'?'p3-buy':q==='SELL'?'p3-sell':'p3-neutral';return '<div class="p3-signal"><div class="p3-main"><div><div class="p3-symbol">'+e(x.sym||x.symbol)+'</div><div class="p3-sub">'+e(x.strategy||'Sweep')+' · '+e(x.time||'')+'</div></div><span class="p3-dir '+c+'">'+q+'</span></div></div>'}).join('')||'<div class="empty">No signals yet.</div>';var h=document.querySelector('#signals .muted');if(h)h.textContent='All saved signals'})}).catch(function(){})}load();setInterval(load,30000)})();</script>'''
            marker=b'</body>'
            if marker in body: body=body.replace(marker,override+marker,1)
            return body
    return b"<h1>Dashboard template index.html not found.</h1>"


def _get_main_module(): return sys.modules.get("__main__") or sys.modules.get("main")


def _load_file(main,path,default):
    try:
        fn=getattr(main,"load_json",None)
        if fn:return fn(path,default) or default
    except Exception as e:print("[DASHBOARD] load:",e)
    try:
        if os.path.exists(path):
            with open(path,"r",encoding="utf-8") as f:return json.load(f)
    except Exception as e:print("[DASHBOARD] file load:",e)
    return default


def _parse_ts(value,default=0):
    if value is None or value=="":return default
    if isinstance(value,(int,float)):
        v=float(value);return int(v if v>10_000_000_000 else v*1000)
    s=str(value).strip()
    try:
        v=float(s);return int(v if v>10_000_000_000 else v*1000)
    except Exception:pass
    try:return int(datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()*1000)
    except Exception:return default


def _direction(value):
    s=str(value or "").upper()
    if "BULL" in s or s in ("BUY","LONG"):return "BUY"
    if "BEAR" in s or s in ("SELL","SHORT"):return "SELL"
    return "NEUTRAL"


def _batch_live_prices(symbols):
    if not symbols:return {}
    main=_get_main_module();out={}
    if not main:return out
    cache=getattr(main,"_price_cache",{});lock=getattr(main,"_lock",None);get_price=getattr(main,"get_price",None);now=time.time()
    if lock:
        with lock:
            for s,v in cache.items():
                if s in symbols and isinstance(v,(list,tuple)) and len(v)>=2 and now-v[1]<120:out[s]=v[0]
    need=[s for s in symbols if s not in out]
    if need:
        try:
            import yfinance as yf
            df=yf.download(tickers=','.join(need),period="1d",interval="1d",progress=False,threads=True,timeout=15)
            if df is not None and not df.empty:
                close=df["Close"]
                if len(need)==1:
                    vals=close.dropna()
                    if not vals.empty:out[need[0]]=float(vals.iloc[-1])
                else:
                    for s in need:
                        try:
                            vals=close[s].dropna()
                            if not vals.empty:out[s]=float(vals.iloc[-1])
                        except Exception:pass
        except Exception as e:print("[DASHBOARD] price fetch:",e)
    if get_price:
        for s in symbols:
            if s not in out:
                try:
                    v=get_price(s)
                    if v is not None:out[s]=float(v)
                except Exception:pass
    return out


def _build_equity_curve(history,starting=400000.0,days=60):
    daily={}
    for t in history:
        d=str(t.get("closed_at",t.get("close_time",t.get("time",""))))[:10]
        if not d:continue
        try:daily[d]=daily.get(d,0)+float(t.get("pnl",0) or 0)
        except Exception:pass
    running=peak=starting;ddmax=ddpct=0;points=[]
    for d in sorted(daily):
        running+=daily[d];peak=max(peak,running);dd=peak-running
        if dd>ddmax:ddmax=dd;ddpct=dd/peak*100 if peak else 0
        points.append({"date":d,"equity":round(running,2)})
    points=points[-days:]
    return {"points":points,"current_equity":points[-1]["equity"] if points else starting,"max_drawdown_inr":round(ddmax,2),"max_drawdown_pct":round(ddpct,2)}


def _build_actual_signals(main,ist):
    rows=_load_file(main,"/tmp/workspace/signal_history.json",[])
    if not isinstance(rows,list):rows=[]
    # Migration fallback: expose existing confirmed runtime sweeps so the new permanent store does not start blank.
    if not rows:
        state=_load_file(main,"/tmp/workspace/sweep_runtime_state.json",{})
        if isinstance(state,dict):
            for key,rec in state.items():
                if isinstance(rec,dict) and rec.get("initial"):
                    rows.append({"id":key,"symbol":str(key).split(":",1)[0],"direction":rec.get("direction"),"strategy":f"{rec.get('timeframe','4H')} Sweep","timeframe":rec.get("timeframe","4H"),"candle_start":rec.get("candle_start"),"candle_end":rec.get("candle_end"),"reminder_sent":bool(rec.get("reminder"))})
    signals=[]
    for record in rows:
        if not isinstance(record,dict):continue
        ts=_parse_ts(record.get("candle_end"),0);symbol=str(record.get("symbol") or "").strip()
        if not symbol or not ts:continue
        try:dt=datetime.fromtimestamp(ts/1000,tz=ist)
        except Exception:continue
        signals.append({"id":record.get("id",f"{symbol}:{ts}"),"time":dt.strftime("%d-%b %H:%M"),"sym":symbol,"dir":_direction(record.get("direction")),"strategy":record.get("strategy") or f"{record.get('timeframe','4H')} Sweep","status":"REMINDER SENT" if record.get("reminder_sent") else "SIGNAL","pnl":0,"hint":"Confirmed sweep signal","ts_ms":ts,"reminder":bool(record.get("reminder_sent")),"date":dt.strftime("%Y-%m-%d")})
    signals.sort(key=lambda x:x["ts_ms"],reverse=True)
    return signals


def _build_snapshot():
    main=_get_main_module()
    if not main:return {"error":"main module not loaded"}
    load_json=getattr(main,"load_json",None);lock=getattr(main,"_lock",None)
    if not load_json or not lock:return {"error":"missing bot globals"}
    IST=getattr(main,"IST",pytz.timezone("Asia/Kolkata"));now=datetime.now(IST);today=now.strftime("%Y-%m-%d")
    history=load_json(getattr(main,"HISTORY_FILE","trade_history.json"),[]) or [];accounts=getattr(main,"accounts",{}) or {};active=getattr(main,"active_trades",[]) or {};limits=getattr(main,"ACCOUNT_LIMITS",{}) or {}
    per_today={k:0.0 for k in accounts}
    for t in history:
        if str(t.get("closed_at",t.get("close_time","")))[:10]==today:
            try:acc=t.get("account");per_today[acc]=per_today.get(acc,0)+float(t.get("pnl",0) or 0)
            except Exception:pass
    accounts_view={}
    for k,a in accounts.items():
        if isinstance(a,dict):accounts_view[k]={"name":k.replace("_"," ").title(),"balance":float(a.get("balance",0) or 0),"daily_trades":int(a.get("daily_trades",0) or 0),"daily_limit":int(limits.get(k,0) or 0),"today_pnl":round(per_today.get(k,0),2)}
    symbols=[t.get("symbol") for t in active if t.get("symbol")];prices=_batch_live_prices(symbols);live=[]
    for t in active:
        sym=t.get("symbol");entry=float(t.get("entry",0) or 0);qty=float(t.get("qty",0) or 0);sl=float(t.get("sl",t.get("trail_sl",0)) or 0);tp=float(t.get("tp",0) or 0);typ=str(t.get("type",t.get("direction","LONG"))).upper();long="LONG" in typ or "BULL" in typ or typ=="BUY";cur=float(prices.get(sym,entry) or entry);pnl=(cur-entry)*qty*(1 if long else -1)
        live.append({"id":t.get("id",""),"symbol":sym,"market":t.get("market",t.get("mtype","")),"account":t.get("account",""),"direction":"LONG" if long else "SHORT","entry":entry,"current":cur,"sl":sl,"tp":tp,"qty":qty,"pnl_inr":round(pnl,2),"opened":t.get("opened_at",t.get("opened",""))})
    signals=_build_actual_signals(main,IST)
    news=[];cached=getattr(main,"get_cached_news",None);fetch=getattr(main,"fetch_news",None)
    try:
        if cached:news=cached() or []
    except Exception as e:print("[DASHBOARD] cached news:",e)
    if not news and fetch:
        try:news=fetch() or []
        except Exception as e:print("[DASHBOARD] fetch news:",e)
    normalized_news=[]
    for ev in news[:120]:
        if isinstance(ev,dict):
            x=dict(ev);x["impact"]=str(x.get("impact") or x.get("importance") or "LOW").upper();normalized_news.append(x)
    history_sorted=sorted(history,key=lambda x:str(x.get("closed_at",x.get("close_time",""))),reverse=True)[:30];curve=_build_equity_curve(history);total=sum(float(x.get("pnl",0) or 0) for x in history)
    return {"generated_at":now.strftime("%Y-%m-%d %H:%M:%S IST"),"accounts":accounts_view,"live_trades":live,"today_signals":signals,"signals":signals,"history":history_sorted,"history_total":len(history),"pending":[],"news_raw":normalized_news,"news":normalized_news,"equity_curve":curve,"risk":{"max_drawdown_inr":curve["max_drawdown_inr"],"max_drawdown_pct":curve["max_drawdown_pct"]},"total_pnl":round(total,2)}


def _get_snapshot_cached():
    now=time.time()
    with _snapshot_lock:
        if _snapshot_cache["data"] is not None and now-_snapshot_cache["ts"]<SNAPSHOT_TTL:return {"cached":True,"cache_age_s":int(now-_snapshot_cache["ts"]),**_snapshot_cache["data"]}
    snap=_build_snapshot()
    with _snapshot_lock:_snapshot_cache["data"],_snapshot_cache["ts"]=snap,now
    return {"cached":False,**snap}


def _json_response(start_response,payload,status="200 OK"):
    body=json.dumps(payload,default=str).encode();start_response(status,[("Content-Type","application/json"),("Content-Length",str(len(body))),("Cache-Control","no-store")]);return [body]


def _html_response(start_response,body,status="200 OK"):
    if isinstance(body,str):body=body.encode()
    start_response(status,[("Content-Type","text/html; charset=utf-8"),("Content-Length",str(len(body))),("Cache-Control","no-store")]);return [body]


def _route_backtest(start_response,environ):
    try:
        q=parse_qs(environ.get("QUERY_STRING",""));symbol=(q.get("symbol",[""])[0] or "").strip().upper();strategy=(q.get("strategy",["trendpulse"])[0] or "trendpulse").lower();days=max(7,min(int(q.get("days",["30"])[0] or 30),730))
        if not symbol:return _json_response(start_response,{"error":"symbol required"},"400 Bad Request")
        from backtest import BacktestEngine
        eng=BacktestEngine();res=eng.backtest_sweep(symbol,days) if strategy=="sweep" else eng.backtest_trendpulse(symbol,days)
        if not isinstance(res,dict):res={"error":"backtest failed"}
        if "error" not in res:res={"metrics":res,"symbol":symbol,"strategy":strategy,"days":days}
        else:res.update({"symbol":symbol,"strategy":strategy,"days":days})
        return _json_response(start_response,res)
    except Exception as e:return _json_response(start_response,{"error":str(e)},"500 Internal Server Error")


def _route_close_trade(start_response,environ):
    try:
        n=int(environ.get("CONTENT_LENGTH",0) or 0);data=json.loads(environ["wsgi.input"].read(n).decode()) if n else {};tid=data.get("trade_id","");main=_get_main_module()
        if not tid:return _json_response(start_response,{"success":False,"error":"trade_id required"},"400 Bad Request")
        fn=getattr(main,"force_close_trade",None) if main else None;ok,msg=fn(tid,reason="Dashboard") if fn else (False,"Not found")
        return _json_response(start_response,{"success":ok,"message":msg})
    except Exception as e:return _json_response(start_response,{"success":False,"error":str(e)},"500 Internal Server Error")


def _route_refresh_news(start_response,environ):
    main=_get_main_module()
    try:
        items=main.fetch_news() if main and hasattr(main,"fetch_news") else []
        return _json_response(start_response,{"ok":True,"items":len(items or [])})
    except Exception as e:return _json_response(start_response,{"ok":False,"error":str(e)},"500 Internal Server Error")


def register_routes(path,start_response,environ):
    method=environ.get("REQUEST_METHOD","GET")
    if path in ("/dashboard","/dashboard/"):return _html_response(start_response,_get_html_content())
    if path=="/api/dashboard":
        try:return _json_response(start_response,_get_snapshot_cached())
        except Exception as e:return _json_response(start_response,{"error":str(e)},"500 Internal Server Error")
    if path.startswith("/api/backtest"):return _route_backtest(start_response,environ)
    if path.startswith("/api/prices"):
        syms=parse_qs(environ.get("QUERY_STRING","")).get("symbols",[""])[0].split(",")
        return _json_response(start_response,{"prices":_batch_live_prices([s for s in syms if s]),"ts":int(time.time())})
    if path=="/api/health":return _json_response(start_response,{"ok":True,"ts":int(time.time())})
    if path=="/api/close-trade" and method=="POST":return _route_close_trade(start_response,environ)
    if path=="/api/refresh-news" and method=="POST":return _route_refresh_news(start_response,environ)
    return None
