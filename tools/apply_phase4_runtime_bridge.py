from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
DB = ROOT / "db.py"


def replace_function(text, name, replacement, next_name):
    pattern = rf"def {re.escape(name)}\([^\n]*\):\n.*?(?=def {re.escape(next_name)}\()"
    new, count = re.subn(pattern, replacement.rstrip() + "\n\n", text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"safe patch refused: could not uniquely locate {name}()")
    return new


def patch_db(text):
    if "def sync_runtime_active_trades" in text:
        return text
    marker = "    def get_pending_sweeps(self)"
    if marker not in text:
        raise RuntimeError("safe patch refused: db.py marker missing")
    methods = '''    def has_trade_state(self) -> bool:
        with sqlite3.connect(SQLITE_DB_PATH) as conn:
            row = conn.execute("SELECT (SELECT COUNT(*) FROM active_trades) + (SELECT COUNT(*) FROM closed_trades)").fetchone()
            return bool(row and row[0])

    def sync_runtime_active_trades(self, trades: List[Dict]):
        """Mirror the runtime active-trade snapshot into the authoritative DB."""
        for trade in trades or []:
            normalized = {
                "id": str(trade.get("id")),
                "symbol": trade.get("symbol", ""),
                "market": trade.get("market", ""),
                "account": trade.get("account", "MACRO"),
                "strat": trade.get("strat", ""),
                "type": trade.get("type", "LONG"),
                "entry": float(trade.get("entry", 0)),
                "sl": float(trade.get("sl", trade.get("trail_sl", 0))),
                "tp": float(trade.get("tp", 0)),
                "qty": float(trade.get("qty", 0)),
                "trail_sl": float(trade.get("trail_sl", trade.get("sl", 0))),
                "ts_trigger": int(trade.get("ts_trigger", trade.get("signal_ts", 0)) or 0),
                "opened_at": trade.get("opened_at", ""),
                "time": trade.get("time", trade.get("time_str", "")),
            }
            if normalized["id"] and normalized["id"] != "None":
                self.add_active_trade(normalized)

    def sync_runtime_closed_history(self, history: List[Dict]):
        """Move runtime history entries into closed_trades exactly once."""
        for item in history or []:
            trade_id = item.get("id") or item.get("trade_id")
            if not trade_id:
                continue
            closed = {
                "id": str(trade_id),
                "symbol": item.get("symbol", ""),
                "market": item.get("market", ""),
                "account": item.get("account", "MACRO"),
                "strat": item.get("strat", item.get("strategy", "")),
                "type": item.get("type", "LONG"),
                "entry": float(item.get("entry", 0)),
                "exit_price": float(item.get("exit_price", item.get("exit", item.get("live", item.get("close_price", item.get("price", item.get("entry", 0))))))),
                "pnl": float(item.get("pnl", 0)),
                "result": item.get("result", ""),
                "exit_reason": item.get("exit_reason", item.get("reason", "")),
                "close_time": item.get("close_time", item.get("closed_at", "")),
                "closed_at": item.get("closed_at", ""),
            }
            try:
                self.close_active_trade(str(trade_id), closed)
            except Exception:
                pass

'''
    return text.replace(marker, methods + marker, 1)


def patch_main(text):
    if "from db import DatabaseManager" not in text:
        anchor = "import dashboard_api\n"
        if anchor not in text:
            raise RuntimeError("safe patch refused: main import anchor missing")
        text = text.replace(anchor, anchor + "from db import DatabaseManager\n", 1)
    if "_trade_db = DatabaseManager()" not in text:
        anchor = "_lock = threading.RLock()\n"
        if anchor not in text:
            raise RuntimeError("safe patch refused: main lock anchor missing")
        text = text.replace(anchor, anchor + "_trade_db = DatabaseManager()\n", 1)

    load_replacement = '''def load_json(path, default=None):
    if default is None:
        default = {}
    path_str = str(path)
    try:
        if path_str == ACTIVE_TRADES_FILE or path_str == HISTORY_FILE:
            if _trade_db.has_trade_state():
                if path_str == ACTIVE_TRADES_FILE:
                    rows = _trade_db.get_active_trades()
                    for row in rows:
                        row["time"] = row.get("time", row.get("time_str", ""))
                    return rows
                return _trade_db.get_trade_history()
    except Exception as exc:
        print(f"[DB WARN] trade-state load fallback: {exc}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    path_str = str(path)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"[WARN] save_json failed for {path}: {exc}")
        return
    if path_str == ACTIVE_TRADES_FILE:
        try:
            _trade_db.sync_runtime_active_trades(data if isinstance(data, list) else [])
        except Exception as exc:
            print(f"[DB WARN] active-trade sync failed: {exc}")
    elif path_str == HISTORY_FILE:
        try:
            _trade_db.sync_runtime_closed_history(data if isinstance(data, list) else [])
        except Exception as exc:
            print(f"[DB WARN] history sync failed: {exc}")
'''
    # Replace load_json only; the replacement contains the new save_json.
    pattern = r"def load_json\([^\n]*\):\n.*?(?=def save_json\()"
    text, count = re.subn(pattern, load_replacement.rstrip() + "\n\n", text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("safe patch refused: load_json() not uniquely found")
    # Remove the old save_json that now follows the inserted canonical one.
    pattern = r"def save_json\([^\n]*\):\n.*?(?=def )"
    matches = list(re.finditer(pattern, text, flags=re.S))
    if len(matches) != 2:
        raise RuntimeError(f"safe patch refused: expected 2 save_json definitions, found {len(matches)}")
    second = matches[1]
    text = text[:second.start()] + text[second.end():]
    return text


def main():
    main_text = MAIN.read_text(encoding="utf-8")
    db_text = DB.read_text(encoding="utf-8")
    new_db = patch_db(db_text)
    new_main = patch_main(main_text)
    if new_db == db_text and new_main == main_text:
        print("Phase 4 runtime bridge already applied")
        return
    compile(new_db, str(DB), "exec")
    compile(new_main, str(MAIN), "exec")
    DB.write_text(new_db, encoding="utf-8")
    MAIN.write_text(new_main, encoding="utf-8")
    print("Phase 4 runtime bridge applied safely")


if __name__ == "__main__":
    main()
