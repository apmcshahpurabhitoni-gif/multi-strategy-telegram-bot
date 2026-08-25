"""Phase 2 dashboard history upgrade.

Keeps the existing dashboard architecture but upgrades History from a 15-row
summary into a real paper-trade ledger with filters, exact close timestamps,
and complete trade details. The migration is idempotent and runs from the
production entrypoint before main.py is executed.
"""
from __future__ import annotations

from pathlib import Path

MARKER = "data-phase2-history=1"


HISTORY_CSS = r'''
.history-toolbar{display:grid;grid-template-columns:1.5fr .8fr .8fr auto;gap:7px;margin:0 0 10px}
.history-toolbar input,.history-toolbar select{width:100%;min-width:0;border:2px solid var(--line);background:var(--surface2);color:var(--text);border-radius:8px;padding:8px 9px;font-size:11px;font-weight:800}
.history-count{font-size:9px;color:var(--muted);font-weight:900;margin:-3px 0 9px}
.history-card .history-detail-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:8px}
.history-card .history-detail{background:var(--surface);border:1px solid var(--line);border-radius:7px;padding:6px;min-width:0}
.history-card .history-detail .stat-label{margin-bottom:2px}
.history-card .history-detail .stat-value{font-size:10px}
.history-exact{font-size:9px;color:var(--muted);font-weight:800;margin-top:3px}
@media(max-width:820px){.history-toolbar{grid-template-columns:1fr 1fr}.history-toolbar input{grid-column:1/-1}.history-toolbar .clear-history{grid-column:1/-1}.history-card .history-detail-grid{grid-template-columns:repeat(2,1fr)}}
'''

HISTORY_HTML = r'''
<div id="historyToolbar" class="history-toolbar">
  <input id="historySearch" type="search" placeholder="Search symbol, account, strategy…" autocomplete="off">
  <select id="historyResultFilter"><option value="ALL">All results</option><option value="WIN">Wins</option><option value="LOSS">Losses</option></select>
  <select id="historyStrategyFilter"><option value="ALL">All strategies</option></select>
  <button id="historyClear" class="control small clear-history" type="button">Clear filters</button>
</div>
<div id="historyCount" class="history-count">Showing all completed trades</div>
'''

OLD_HISTORY_CARD = r'''function historyCard(t){const c=document.createElement('article');c.className='history-card';const d=dir(t.direction||t.type),r=String(t.result||t.status||'CLOSED').toUpperCase(),p=Number(t.pnl||0),top=document.createElement('div');top.className='history-top';const l=document.createElement('div');l.innerHTML=`<div class="symbol">${esc(t.symbol||t.sym||'Trade')}</div><div class="sub">${time(t.closed_at||t.close_time||t.time)} · ${esc(t.strat||t.strategy||'Strategy')}</div>`;top.append(l,badge(d==='LONG'?'▲ BUY':'▼ SELL',d==='LONG'?'long':'short'));c.append(top);const m=document.createElement('div');m.className='trade-foot';m.style.marginTop='6px';m.appendChild(badge(r==='WIN'?'✓ WIN':r==='LOSS'?'✕ LOSS':'● CLOSED',r==='WIN'?'long':r==='LOSS'?'short':'neutral'));const v=document.createElement('b');v.className=p>=0?'good-text':'bad-text';v.textContent=money(p);m.appendChild(v);c.append(m);return c}'''

NEW_HISTORY_CARD = r'''function exactTime(v){const d=date(v);if(!d)return String(v||'—');return new Intl.DateTimeFormat('en-IN',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false,timeZone:'Asia/Kolkata'}).format(d)+' IST'}
function historyCard(t){const c=document.createElement('article');c.className='history-card';const d=dir(t.direction||t.type),r=String(t.result||t.status||'CLOSED').toUpperCase(),p=Number(t.pnl||0),top=document.createElement('div');top.className='history-top';const l=document.createElement('div');l.innerHTML=`<div class="symbol">${esc(t.symbol||t.sym||'Trade')}</div><div class="sub">${esc(t.strat||t.strategy||'Strategy')} · ${esc(t.account||'Account')}</div><div class="history-exact">Closed: ${esc(exactTime(t.closed_at||t.close_time||t.time))}</div>`;top.append(l,badge(d==='LONG'?'▲ BUY':'▼ SELL',d==='LONG'?'long':'short'));c.append(top);const m=document.createElement('div');m.className='trade-foot';m.style.marginTop='6px';m.appendChild(badge(r==='WIN'?'✓ WIN':r==='LOSS'?'✕ LOSS':'● CLOSED',r==='WIN'?'long':r==='LOSS'?'short':'neutral'));const v=document.createElement('b');v.className=p>=0?'good-text':'bad-text';v.textContent=money(p);m.appendChild(v);c.append(m);const g=document.createElement('div');g.className='history-detail-grid';[['Entry',num(t.entry,2)],['Exit',num(t.exit_price??t.exit,2)],['Quantity',num(t.qty??t.quantity,4)],['Exit reason',esc(t.exit_reason||'—')]].forEach(([k,v])=>{const x=document.createElement('div');x.className='history-detail';x.innerHTML=`<div class="stat-label">${k}</div><div class="stat-value">${v}</div>`;g.appendChild(x)});c.append(g);return c}'''

OLD_RENDER_HISTORY = r'''function renderHistory(items){const all=items||[],total=all.reduce((s,x)=>s+Number(x.pnl||0),0),todayKey=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Kolkata'}),today=all.filter(x=>day(x.closed_at||x.close_time||x.time)===todayKey).reduce((s,x)=>s+Number(x.pnl||0),0),wins=all.filter(x=>String(x.result||'').toUpperCase()==='WIN').length,losses=all.filter(x=>String(x.result||'').toUpperCase()==='LOSS').length;const h=$('historySummary');h.replaceChildren();[[total,'Total P&L'],[today,"Today's P&L"],[`${wins}/${losses}`,'Wins / Losses']].forEach(([v,l])=>{const c=document.createElement('div');c.className='summary-chip';c.innerHTML=`<b class="${typeof v==='number'?(v>=0?'good-text':'bad-text'):''}">${typeof v==='number'?money(v):v}</b><span>${l}</span>`;h.appendChild(c)});groupDate(all,x=>day(x.closed_at||x.close_time||x.time),$('historyGroups'),historyCard,'No completed trades')}'''

NEW_RENDER_HISTORY = r'''let historyState={items:[],query:'',result:'ALL',strategy:'ALL'};
function populateHistoryFilters(items){const s=$('historyStrategyFilter');if(!s)return;const current=historyState.strategy;const values=[...new Set((items||[]).map(x=>String(x.strat||x.strategy||'Unknown')).filter(Boolean))].sort();s.replaceChildren(new Option('All strategies','ALL'));values.forEach(v=>s.appendChild(new Option(v,v)));s.value=values.includes(current)?current:'ALL';historyState.strategy=s.value}
function applyHistoryFilters(){const q=historyState.query.trim().toLowerCase(),r=historyState.result,str=historyState.strategy;return historyState.items.filter(x=>{const result=String(x.result||x.status||'CLOSED').toUpperCase(),strategy=String(x.strat||x.strategy||'Unknown'),hay=[x.symbol,x.account,x.strat,x.strategy,x.result,x.exit_reason].map(v=>String(v??'').toLowerCase()).join(' ');return (!q||hay.includes(q))&&(r==='ALL'||result===r)&&(str==='ALL'||strategy===str)})}
function renderHistory(items){historyState.items=items||[];populateHistoryFilters(historyState.items);const all=applyHistoryFilters(),total=all.reduce((s,x)=>s+Number(x.pnl||0),0),todayKey=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Kolkata'}),today=all.filter(x=>day(x.closed_at||x.close_time||x.time)===todayKey).reduce((s,x)=>s+Number(x.pnl||0),0),wins=all.filter(x=>String(x.result||'').toUpperCase()==='WIN').length,losses=all.filter(x=>String(x.result||'').toUpperCase()==='LOSS').length;const h=$('historySummary');h.replaceChildren();[[total,'Filtered P&L'],[today,"Today's P&L"],[`${wins}/${losses}`,'Wins / Losses']].forEach(([v,l])=>{const c=document.createElement('div');c.className='summary-chip';c.innerHTML=`<b class="${typeof v==='number'?(v>=0?'good-text':'bad-text'):''}">${typeof v==='number'?money(v):v}</b><span>${l}</span>`;h.appendChild(c)});const count=$('historyCount');if(count)count.textContent=`Showing ${all.length} of ${historyState.items.length} completed trades`;groupDate(all,x=>day(x.closed_at||x.close_time||x.time),$('historyGroups'),historyCard,'No completed trades match the current filters')}
function wireHistoryFilters(){const q=$('historySearch'),r=$('historyResultFilter'),s=$('historyStrategyFilter'),clear=$('historyClear');if(!q||q.dataset.wired)return;q.dataset.wired='1';q.oninput=()=>{historyState.query=q.value;renderHistory(historyState.items)};r.onchange=()=>{historyState.result=r.value;renderHistory(historyState.items)};s.onchange=()=>{historyState.strategy=s.value;renderHistory(historyState.items)};clear.onclick=()=>{historyState.query='';historyState.result='ALL';historyState.strategy='ALL';q.value='';r.value='ALL';s.value='ALL';renderHistory(historyState.items)}}'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Phase 2: {label} insertion point not found")
    return text.replace(old, new, 1)


def apply(base: str) -> None:
    root = Path(base)
    dashboard_api = root / "dashboard_api.py"
    html_path = root / "dashboard" / "index.html"

    d = dashboard_api.read_text(encoding="utf-8")
    d = _replace_once(
        d,
        'last_history = sorted(history, key=lambda x: str(x.get("closed_at", "")), reverse=True)[:15]',
        'last_history = sorted(history, key=lambda x: str(x.get("closed_at", x.get("close_time", ""))), reverse=True)[:500]',
        "history API depth",
    )
    d = d.replace(
        '"history": last_history, "history_total": len(history),',
        '"history": last_history, "history_total": len(history), "history_limit": 500,',
        1,
    )
    dashboard_api.write_text(d, encoding="utf-8")

    html = html_path.read_text(encoding="utf-8")
    if MARKER in html:
        return

    html = _replace_once(html, '</style>', HISTORY_CSS + '\n</style>', "history CSS")
    html = _replace_once(
        html,
        '<div class="section-head"><div><h2>🕘 History</h2><div class="sub">Short records · no raw timestamps</div></div></div><div id="historySummary" class="history-summary"></div>',
        '<div class="section-head"><div><h2>🕘 History</h2><div class="sub">Full trade ledger · exact timestamps · filters</div></div></div><div id="historySummary" class="history-summary"></div>' + HISTORY_HTML,
        "history toolbar",
    )
    html = _replace_once(html, OLD_HISTORY_CARD, NEW_HISTORY_CARD, "history card renderer")
    html = _replace_once(html, OLD_RENDER_HISTORY, NEW_RENDER_HISTORY, "history renderer")
    html = _replace_once(html, "function renderSnapshot(s){", "function renderSnapshot(s){wireHistoryFilters();", "history filter wiring")
    html = html.replace('</body>', '<span ' + MARKER + ' hidden></span>\n</body>', 1)
    html_path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    import os
    apply(os.path.dirname(os.path.abspath(__file__)))
