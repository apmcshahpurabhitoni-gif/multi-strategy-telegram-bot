import os, sys, json, time, threading
from datetime import datetime, timedelta
from urllib.parse import parse_qs
import pytz

SNAPSHOT_TTL = 10
_snapshot_cache = {"data": None, "ts": 0}
_snapshot_lock = threading.RLock()
_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML_PATH_PRIMARY = os.path.join(_HERE, "templates", "index.html")
_HTML_PATH_FALLBACK = os.path.join(_HERE, "dashboard", "index.html")

def _get_html_content():
    for p in (_HTML_PATH_PRIMARY, _HTML_PATH_FALLBACK):
        if os.path.exists(p):
            with open(p, "rb") as f: return f.read()
    return b"<h1>Dashboard template index.html not found.</h1>"

def _get_main_module():
    return sys.modules.get("__main__") or sys.modules.get("main")

def _batch_live_prices(symbols):
    if not symbols: return {}
    main = _get_main_module(); out = {}
    if not main: return out
    cache, lock, get_price = getattr(main,"_price_cache",{}), getattr(main,"_lock",None), getattr(main,"get_price",None)
    now=time.time()
    if lock:
        with lock:
            for s,v in cache.items():
                if s in symbols and isinstance(v,(list,tuple)) and len(v)>=2 and now-v[1]<120: out[s]=v[0]
    need=[s for s in symbols if s not in out]
    if need:
        try:
            import yfinance as yf
            df=yf.download(tickers=','.join(need),period='1d',interval='1d',progress=False,threads=True,timeout=15)
            if df is not None and not df.empty:
                close=df['Close']
                if len(need)==1:
                    vals=close.dropna()
                    if not vals.empty: out[need[0]]=float(vals.iloc[-1])
                else:
                    for s in need:
                        try:
                            vals=close[s].dropna()
                            if not vals.empty: out[s]=float(vals.iloc[-1])
                        except Exception: pass
        except Exception as e: print('[DASHBOARD] price fetch:',e)
    if get_price:
        for s in symbols:
            if s not in out:
                try:
                    v=get_price(s)
                    if v is not None: out[s]=float(v)
                except Exception: pass
    return out

def _build_equity_curve(history, starting=400000.0, days=60):
    daily={}
    for t in history:
        d=str(t.get('closed_at',t.get('close_time',t.get('time',''))))[:10]
        if not d: continue
        try: daily[d]=daily.get(d,0)+float(t.get('pnl',0) or 0)
        except Exception: pass
    running=peak=starting; ddmax=ddpct=0; points=[]
    for d in sorted(daily):
        running+=daily[d]; peak=max(peak,running); dd=peak-running
        if dd>ddmax: ddmax=dd; ddpct=(dd/peak*100) if peak else 0
        points.append({'date':d,'equity':round(running,2)})
    points=points[-days:]
    return {'points':points,'current_equity':points[-1]['equity'] if points else starting,'max_drawdown_inr':round(ddmax,2),'max_drawdown_pct':round(ddpct,2)}

def _signal_from_record(sym, sig, key, ist):
    ts=0; direction='NEUTRAL'; strat=''; status='OPEN'; pnl=0; hint=''; tm=''
    if isinstance(sig,dict):
        ts=sig.get('ts_ms',sig.get('timestamp_ms',0)) or 0
        typ=str(sig.get('sig_type',sig.get('direction',sig.get('type','')))).upper()
        if 'BULL' in typ or typ in ('BUY','LONG'): direction='BUY'
        elif 'BEAR' in typ or typ in ('SELL','SHORT'): direction='SELL'
        strat=sig.get('strat',sig.get('strategy','')) or ''
        status=sig.get('status','OPEN') or 'OPEN'; pnl=sig.get('pnl',sig.get('pnl_inr',0)) or 0; hint=sig.get('hint','') or ''
        if not sym: sym=sig.get('symbol','') or ''
        if not ts:
            raw=sig.get('time_str',sig.get('time',''))
            tm=str(raw or '')
    else:
        parts=str(key).split('_')
        if parts:
            sym=sym or parts[0]
        for part in parts[1:]:
            if part.isdigit() and len(part)>=10:
                ts=int(part); break
        typ=' '.join(parts).upper()
        if 'BULL' in typ or 'BUY' in typ: direction='BUY'
        elif 'BEAR' in typ or 'SELL' in typ: direction='SELL'
        strat=parts[-1] if len(parts)>3 else ''
    if ts:
        try: tm=datetime.fromtimestamp(ts/1000,tz=ist).strftime('%d-%b %H:%M')
        except Exception: pass
    return {'time':tm,'sym':sym,'dir':direction,'strategy':strat,'status':status,'pnl':pnl,'hint':hint,'ts_ms':ts}

def _build_snapshot():
    main=_get_main_module()
    if not main: return {'error':'main module not loaded'}
    load_json=getattr(main,'load_json',None); lock=getattr(main,'_lock',None)
    if not load_json or not lock: return {'error':'missing bot globals'}
    IST=getattr(main,'IST',pytz.timezone('Asia/Kolkata'))
    now=datetime.now(IST); today=now.strftime('%Y-%m-%d')
    history=load_json(getattr(main,'HISTORY_FILE','trade_history.json'),[]) or []
    sent=load_json(getattr(main,'SENT_SIGNALS_FILE','sent_signals.json'),{}) or {}
    mem=getattr(main,'sent_signals',{})
    if isinstance(mem,dict) and len(mem)>len(sent): sent=mem
    accounts=getattr(main,'accounts',{}) or {}; active=getattr(main,'active_trades',[]) or []
    limits=getattr(main,'ACCOUNT_LIMITS',{}) or {}
    per_today={k:0.0 for k in accounts}
    for t in history:
        if str(t.get('closed_at',t.get('close_time','')))[:10]==today:
            try: per_today[t.get('account')]=per_today.get(t.get('account'),0)+float(t.get('pnl',0) or 0)
            except Exception: pass
    accounts_view={}
    for k,a in accounts.items():
        if isinstance(a,dict): accounts_view[k]={'name':k.replace('_',' ').title(),'balance':float(a.get('balance',0) or 0),'daily_trades':int(a.get('daily_trades',0) or 0),'daily_limit':int(limits.get(k,0) or 0),'today_pnl':round(per_today.get(k,0),2)}
    symbols=[t.get('symbol') for t in active if t.get('symbol')]; prices=_batch_live_prices(symbols)
    live=[]
    for t in active:
        sym=t.get('symbol'); entry=float(t.get('entry',0) or 0); qty=float(t.get('qty',0) or 0); sl=float(t.get('sl',0) or 0); tp=float(t.get('tp',0) or 0)
        typ=str(t.get('type',t.get('direction','LONG'))).upper(); long=('LONG' in typ or 'BULL' in typ); cur=float(prices.get(sym,entry) or entry)
        pnl=(cur-entry)*qty*(1 if long else -1)
        live.append({'id':t.get('id',''),'symbol':sym,'market':t.get('market',t.get('mtype','')),'account':t.get('account',''),'direction':'LONG' if long else 'SHORT','entry':entry,'current':cur,'sl':sl,'tp':tp,'qty':qty,'pnl_inr':round(pnl,2),'opened':t.get('opened_at',t.get('opened',''))})
    cutoff=int(time.time()*1000)-60*60*1000
    signals=[]
    for key,sig in (sent.items() if isinstance(sent,dict) else []):
        item=_signal_from_record('',sig,key,IST); ts=item['ts_ms']
        if ts and ts>=cutoff: signals.append(item)
    # If the persistent signal store is empty/stale, surface recent executed trades as signals.
    if not signals:
        for t in sorted(history,key=lambda x:str(x.get('closed_at',x.get('close_time',''))),reverse=True)[:20]:
            raw=str(t.get('closed_at',t.get('close_time',t.get('time',''))));
            try: ts=int(datetime.fromisoformat(raw.replace('Z','+00:00')).timestamp()*1000)
            except Exception: ts=0
            if ts and ts>=cutoff:
                typ=str(t.get('direction',t.get('type',''))).upper(); d='BUY' if ('LONG' in typ or 'BUY' in typ or 'BULL' in typ) else 'SELL'
                signals.append({'time':datetime.fromtimestamp(ts/1000,tz=IST).strftime('%d-%b %H:%M'),'sym':t.get('symbol',''),'dir':d,'strategy':t.get('strat',t.get('strategy','')),'status':t.get('result','CLOSED'),'pnl':t.get('pnl',0),'hint':'Executed trade','ts_ms':ts})
    signals.sort(key=lambda x:x.get('ts_ms',0),reverse=True)
    # News: try cache first, then actively fetch when cache is empty.
    news=[]; cached=getattr(main,'get_cached_news',None); fetch=getattr(main,'fetch_news',None)
    try:
        if cached: news=cached() or []
    except Exception as e: print('[DASHBOARD] cached news:',e)
    if not news and fetch:
        try: news=fetch() or []
        except Exception as e: print('[DASHBOARD] fetch news:',e)
    normalized=[]
    for ev in news[:120]:
        if not isinstance(ev,dict): continue
        x=dict(ev); x['impact']=str(x.get('impact') or x.get('importance') or 'LOW').upper(); normalized.append(x)
    history_sorted=sorted(history,key=lambda x:str(x.get('closed_at',x.get('close_time',''))),reverse=True)[:30]
    curve=_build_equity_curve(history)
    total=sum(float(x.get('pnl',0) or 0) for x in history)
    return {'generated_at':now.strftime('%Y-%m-%d %H:%M:%S IST'),'accounts':accounts_view,'live_trades':live,'today_signals':signals,'signals':signals,'history':history_sorted,'history_total':len(history),'pending':[],'news_raw':normalized,'news':normalized,'equity_curve':curve,'risk':{'max_drawdown_inr':curve['max_drawdown_inr'],'max_drawdown_pct':curve['max_drawdown_pct']},'total_pnl':round(total,2)}

def _get_snapshot_cached():
    now=time.time()
    with _snapshot_lock:
        if _snapshot_cache['data'] is not None and now-_snapshot_cache['ts']<SNAPSHOT_TTL:
            return {'cached':True,'cache_age_s':int(now-_snapshot_cache['ts']),**_snapshot_cache['data']}
    snap=_build_snapshot()
    with _snapshot_lock: _snapshot_cache['data'],_snapshot_cache['ts']=snap,now
    return {'cached':False,**snap}

def _json_response(start_response,payload,status='200 OK'):
    body=json.dumps(payload,default=str).encode(); start_response(status,[('Content-Type','application/json'),('Content-Length',str(len(body))),('Cache-Control','no-store')]); return [body]
def _html_response(start_response,body,status='200 OK'):
    if isinstance(body,str): body=body.encode(); start_response(status,[('Content-Type','text/html; charset=utf-8'),('Content-Length',str(len(body))),('Cache-Control','no-store')]); return [body]
    start_response(status,[('Content-Type','text/html; charset=utf-8'),('Content-Length',str(len(body))),('Cache-Control','no-store')]); return [body]

def _route_backtest(start_response,environ):
    try:
        q=parse_qs(environ.get('QUERY_STRING','')); symbol=(q.get('symbol',[''])[0] or '').strip().upper(); strategy=(q.get('strategy',['trendpulse'])[0] or 'trendpulse').lower(); days=max(7,min(int(q.get('days',['30'])[0] or 30),730))
        if not symbol: return _json_response(start_response,{'error':'symbol required'},'400 Bad Request')
        from backtest import BacktestEngine
        eng=BacktestEngine(); res=eng.backtest_sweep(symbol,days) if strategy=='sweep' else eng.backtest_trendpulse(symbol,days)
        if not isinstance(res,dict): res={'error':'backtest failed'}
        if 'error' not in res: res={'metrics':res,'symbol':symbol,'strategy':strategy,'days':days}
        else: res.update({'symbol':symbol,'strategy':strategy,'days':days})
        return _json_response(start_response,res)
    except Exception as e: return _json_response(start_response,{'error':str(e)},'500 Internal Server Error')

def _route_close_trade(start_response,environ):
    try:
        n=int(environ.get('CONTENT_LENGTH',0) or 0); data=json.loads(environ['wsgi.input'].read(n).decode()) if n else {}; tid=data.get('trade_id',''); main=_get_main_module()
        if not tid: return _json_response(start_response,{'success':False,'error':'trade_id required'},'400 Bad Request')
        fn=getattr(main,'force_close_trade',None) if main else None; ok,msg=fn(tid,reason='Dashboard') if fn else (False,'Not found'); return _json_response(start_response,{'success':ok,'message':msg})
    except Exception as e: return _json_response(start_response,{'success':False,'error':str(e)},'500 Internal Server Error')

def _route_refresh_news(start_response,environ):
    main=_get_main_module(); items=[]
    try:
        if main and hasattr(main,'fetch_news'): items=main.fetch_news() or []
        return _json_response(start_response,{'ok':True,'items':len(items)})
    except Exception as e: return _json_response(start_response,{'ok':False,'error':str(e)},'500 Internal Server Error')

def register_routes(path,start_response,environ):
    method=environ.get('REQUEST_METHOD','GET')
    if path in ('/dashboard','/dashboard/'): return _html_response(start_response,_get_html_content())
    if path=='/api/dashboard':
        try: return _json_response(start_response,_get_snapshot_cached())
        except Exception as e: return _json_response(start_response,{'error':str(e)},'500 Internal Server Error')
    if path.startswith('/api/backtest'): return _route_backtest(start_response,environ)
    if path.startswith('/api/prices'):
        syms=parse_qs(environ.get('QUERY_STRING','')).get('symbols',[''])[0].split(','); return _json_response(start_response,{'prices':_batch_live_prices([s for s in syms if s]),'ts':int(time.time())})
    if path=='/api/health': return _json_response(start_response,{'ok':True,'ts':int(time.time())})
    if path=='/api/close-trade' and method=='POST': return _route_close_trade(start_response,environ)
    if path=='/api/refresh-news' and method=='POST': return _route_refresh_news(start_response,environ)
    return None
