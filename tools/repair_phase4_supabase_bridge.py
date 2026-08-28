from pathlib import Path
import re

MAIN = Path(__file__).resolve().parents[1] / "main.py"

COMBINED = '''def load_json(fp, default=None):
    """Load legacy state while making active/history DB-backed and restart-safe."""
    if default is None:
        default = {}
    path_str = str(fp)
    is_trade_state = path_str in (ACTIVE_TRADES_FILE, HISTORY_FILE)

    if is_trade_state:
        try:
            if _trade_db.has_trade_state():
                if path_str == ACTIVE_TRADES_FILE:
                    rows = _trade_db.get_active_trades()
                    for row in rows:
                        row["time"] = row.get("time", row.get("time_str", ""))
                    return rows
                return _trade_db.get_trade_history()
        except Exception as exc:
            print(f"[DB WARN] trade-state load failed; falling back to legacy store: {exc}")

    key = os.path.basename(fp)
    sup_url, sup_key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if sup_url and sup_key:
        try:
            r = requests.get(
                f"{sup_url}/rest/v1/bot_data?id=eq.{key}",
                headers={"apikey": sup_key, "Authorization": f"Bearer {sup_key}"},
                timeout=15,
            )
            if r.status_code == 200 and r.json():
                rows = r.json()
                if rows:
                    data = rows[0]["data"]
                    try:
                        with open(fp, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=4)
                    except Exception:
                        pass
                    if is_trade_state:
                        try:
                            if path_str == ACTIVE_TRADES_FILE:
                                _trade_db.sync_runtime_active_trades(data if isinstance(data, list) else [])
                            else:
                                _trade_db.sync_runtime_closed_history(data if isinstance(data, list) else [])
                        except Exception as exc:
                            print(f"[DB WARN] legacy-to-DB migration failed: {exc}")
                    return data
        except Exception as e:
            print(f"[ERR] Supabase load {key}: {e}")
    try:
        if os.path.exists(fp):
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            if is_trade_state:
                try:
                    if path_str == ACTIVE_TRADES_FILE:
                        _trade_db.sync_runtime_active_trades(data if isinstance(data, list) else [])
                    else:
                        _trade_db.sync_runtime_closed_history(data if isinstance(data, list) else [])
                except Exception as exc:
                    print(f"[DB WARN] legacy-to-DB migration failed: {exc}")
            return data
    except Exception:
        pass
    return default


def save_json(fp, data):
    """Preserve existing local/Supabase state persistence and mirror trade state to DB."""
    key = os.path.basename(fp)
    try:
        with open(fp + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        os.replace(fp + ".tmp", fp)
    except Exception as e:
        print(f"[ERR] local save {fp}: {e}")

    sup_url, sup_key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if sup_url and sup_key:
        try:
            requests.post(
                f"{sup_url}/rest/v1/bot_data",
                headers={
                    "apikey": sup_key,
                    "Authorization": f"Bearer {sup_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates",
                },
                json={"id": key, "data": data},
                timeout=15,
            )
        except Exception as e:
            print(f"[ERR] Supabase save {key}: {e}")

    if fp == ACTIVE_TRADES_FILE:
        try:
            _trade_db.sync_runtime_active_trades(data if isinstance(data, list) else [])
        except Exception as exc:
            print(f"[DB WARN] active-trade sync failed: {exc}")
    elif fp == HISTORY_FILE:
        try:
            _trade_db.sync_runtime_closed_history(data if isinstance(data, list) else [])
        except Exception as exc:
            print(f"[DB WARN] history sync failed: {exc}")
'''


def replace_functions(text):
    pattern = r"def load_json\([^\n]*\):\n.*?(?=def safe_send\()"
    new, count = re.subn(pattern, COMBINED.rstrip() + "\n\n", text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("safe repair refused: load_json/save_json block not uniquely found")
    compile(new, str(MAIN), "exec")
    return new


def main():
    text = MAIN.read_text(encoding="utf-8")
    repaired = replace_functions(text)
    MAIN.write_text(repaired, encoding="utf-8")
    print("Phase 4 Supabase-compatible runtime bridge repaired")


if __name__ == "__main__":
    main()
