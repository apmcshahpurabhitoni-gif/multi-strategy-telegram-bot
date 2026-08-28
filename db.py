import os
import sqlite3
import requests
import json
import time
from typing import Dict, List, Optional, Any

SQLITE_DB_PATH = os.environ.get("BOT_STATE_DB_PATH", "/tmp/workspace/state.db")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

class DatabaseManager:
    def __init__(self):
        db_dir = os.path.dirname(SQLITE_DB_PATH) or "."
        os.makedirs(db_dir, exist_ok=True)
        self._init_sqlite()

    def _init_sqlite(self):
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS accounts (name TEXT PRIMARY KEY, balance REAL DEFAULT 100000.0, daily_trades INTEGER DEFAULT 0, last_reset_date TEXT DEFAULT '')")
            cur.execute("CREATE TABLE IF NOT EXISTS active_trades (id TEXT PRIMARY KEY, symbol TEXT, market TEXT, account TEXT, strat TEXT, type TEXT, entry REAL, sl REAL, tp REAL, qty REAL, trail_sl REAL, ts_trigger INTEGER, opened_at TEXT, time_str TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS closed_trades (id TEXT PRIMARY KEY, symbol TEXT, market TEXT, account TEXT, strat TEXT, type TEXT, entry REAL, exit_price REAL, pnl REAL, result TEXT, exit_reason TEXT, close_time TEXT, closed_at TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS pending_sweeps (id TEXT PRIMARY KEY, symbol TEXT, mtype TEXT, direction TEXT, sweep_high REAL, sweep_low REAL, sweep_open_ts INTEGER, sweep_close_ts INTEGER, created_at TEXT, fvg_zone_low REAL, fvg_zone_high REAL, fvg_tf TEXT, status TEXT, target_account TEXT)")
            cur.execute("CREATE TABLE IF NOT EXISTS sent_signals (sig_key TEXT PRIMARY KEY, send_count INTEGER DEFAULT 1, last_sent_ts INTEGER)")
            conn.commit()

    def _supabase_request(self, method: str, endpoint: str, data: Any = None) -> Optional[Any]:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return None
        url = f"{SUPABASE_URL}/rest/v1/{endpoint}"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
        try:
            if method == "GET": r = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                headers["Prefer"] = "resolution=merge-duplicates"
                r = requests.post(url, headers=headers, json=data, timeout=10)
            elif method == "DELETE": r = requests.delete(url, headers=headers, timeout=10)
            else: return None
            if r.status_code in (200, 201, 204): return r.json() if r.text else True
        except Exception as e:
            print(f"[DB WARN] Supabase {method} {endpoint} failed: {e}")
        return None

    def init_accounts(self, defaults: Dict[str, float], today_str: str) -> Dict[str, Any]:
        result = {}
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            cur = conn.cursor()
            for acc_name, default_bal in defaults.items():
                cur.execute("SELECT balance, daily_trades, last_reset_date FROM accounts WHERE name = ?", (acc_name,))
                row = cur.fetchone()
                if not row:
                    cur.execute("INSERT INTO accounts VALUES (?, ?, 0, ?)", (acc_name, default_bal, today_str))
                    result[acc_name] = {"balance": default_bal, "daily_trades": 0, "last_reset_date": today_str}
                else:
                    bal, trades, last_date = row
                    if last_date != today_str:
                        trades = 0
                        cur.execute("UPDATE accounts SET daily_trades = 0, last_reset_date = ? WHERE name = ?", (today_str, acc_name))
                    result[acc_name] = {"balance": bal, "daily_trades": trades, "last_reset_date": today_str}
            conn.commit()
        return result

    def update_account_balance(self, acc_name: str, pnl: float):
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            conn.execute("UPDATE accounts SET balance = balance + ? WHERE name = ?", (pnl, acc_name)); conn.commit()

    def increment_daily_trades(self, acc_name: str):
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            conn.execute("UPDATE accounts SET daily_trades = daily_trades + 1 WHERE name = ?", (acc_name,)); conn.commit()

    def get_active_trades(self) -> List[Dict]:
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute("SELECT * FROM active_trades").fetchall()]

    def add_active_trade(self, trade: Dict):
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            conn.execute("INSERT OR REPLACE INTO active_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (trade["id"], trade["symbol"], trade["market"], trade["account"], trade["strat"], trade["type"], trade["entry"], trade["sl"], trade["tp"], trade["qty"], trade["trail_sl"], trade["ts_trigger"], trade["opened_at"], trade["time"])); conn.commit()
        self._supabase_request("POST", "active_trades", trade)

    def close_active_trade(self, trade_id: str, closed_data: Dict):
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM active_trades WHERE id = ?", (trade_id,))
            if cur.rowcount != 1: return False
            cur.execute("INSERT OR REPLACE INTO closed_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (closed_data["id"], closed_data["symbol"], closed_data.get("market", ""), closed_data["account"], closed_data["strat"], closed_data["type"], closed_data["entry"], closed_data["exit_price"], closed_data["pnl"], closed_data["result"], closed_data.get("exit_reason", ""), closed_data.get("close_time", ""), closed_data.get("closed_at", ""))); conn.commit()
        self._supabase_request("DELETE", f"active_trades?id=eq.{trade_id}")
        self._supabase_request("POST", "closed_trades", closed_data)
        return True

    def update_trade_trail_sl(self, trade_id: str, new_trail_sl: float):
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            conn.execute("UPDATE active_trades SET trail_sl = ? WHERE id = ?", (new_trail_sl, trade_id)); conn.commit()

    def get_pending_sweeps(self) -> List[Dict]:
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM pending_sweeps WHERE status != 'expired' AND status != 'invalidated'").fetchall()
            out=[]
            for r in rows:
                d=dict(r); d["fvg_zone"]=[d["fvg_zone_low"],d["fvg_zone_high"]] if d.get("fvg_zone_low") is not None and d.get("fvg_zone_high") is not None else None; out.append(d)
            return out

    def add_pending_sweep(self, sweep_data: Dict):
        sid=f"{sweep_data['symbol']}_{sweep_data['sweep_close_ts']}"
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            fvg=sweep_data.get("fvg_zone"); conn.execute("INSERT OR REPLACE INTO pending_sweeps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (sid,sweep_data["symbol"],sweep_data["mtype"],sweep_data["direction"],sweep_data["sweep_high"],sweep_data["sweep_low"],sweep_data["sweep_open_ts"],sweep_data["sweep_close_ts"],sweep_data["created_at"],fvg[0] if fvg else None,fvg[1] if fvg else None,sweep_data.get("fvg_tf"),sweep_data["status"],sweep_data["target_account"])); conn.commit()

    def update_pending_sweep_status(self, sid: str, status: str, fvg_zone: Optional[List[float]] = None, fvg_tf: Optional[str] = None):
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            if fvg_zone: conn.execute("UPDATE pending_sweeps SET status=?, fvg_zone_low=?, fvg_zone_high=?, fvg_tf=? WHERE id=?", (status,fvg_zone[0],fvg_zone[1],fvg_tf,sid))
            else: conn.execute("UPDATE pending_sweeps SET status=? WHERE id=?", (status,sid))
            conn.commit()

    def remove_pending_sweep(self, sid: str):
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            conn.execute("DELETE FROM pending_sweeps WHERE id = ?", (sid,)); conn.commit()

    def check_and_increment_signal(self, sig_key: str, max_count: int = 2) -> bool:
        now_ms=int(time.time()*1000)
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            cur=conn.cursor(); cur.execute("SELECT send_count FROM sent_signals WHERE sig_key=?",(sig_key,)); row=cur.fetchone()
            if row:
                if row[0]>=max_count: return False
                cur.execute("UPDATE sent_signals SET send_count=send_count+1,last_sent_ts=? WHERE sig_key=?",(now_ms,sig_key))
            else: cur.execute("INSERT INTO sent_signals VALUES (?,1,?)",(sig_key,now_ms))
            conn.commit()
        return True

    def get_trade_history(self, limit: int = 500) -> List[Dict]:
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            conn.row_factory=sqlite3.Row
            return [dict(r) for r in conn.execute("SELECT * FROM closed_trades ORDER BY closed_at DESC LIMIT ?",(limit,)).fetchall()]
