import importlib
import sqlite3

# Phase 4 guarded migration trigger: runtime persistence must be verified before deployment.

def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("BOT_STATE_DB_PATH", str(db_path))
    import db
    db = importlib.reload(db)
    return db, db_path


def _trade(trade_id="gold-1"):
    return {
        "id": trade_id,
        "symbol": "GC=F",
        "market": "Gold",
        "account": "sweep_4h",
        "strat": "4H Sweep",
        "type": "LONG",
        "entry": 4666.60,
        "sl": 4616.00,
        "tp": 4767.80,
        "qty": 34.99,
        "trail_sl": 4616.00,
        "ts_trigger": 1756376100000,
        "opened_at": "2026-08-28T10:15:00+05:30",
        "time": "2026-08-28 10:15 IST (+5:30)",
    }


def _closed(trade):
    return {
        "id": trade["id"], "symbol": trade["symbol"], "market": trade["market"],
        "account": trade["account"], "strat": trade["strat"], "type": trade["type"],
        "entry": trade["entry"], "exit_price": 4767.80, "pnl": 3539.0,
        "result": "WIN", "exit_reason": "TP", "close_time": "2026-08-28 14:15 IST (+5:30)",
        "closed_at": "2026-08-28T14:15:00+05:30",
    }


def test_phase4_trade_survives_runtime_reconstruction(tmp_path, monkeypatch):
    db, db_path = _fresh_db(tmp_path, monkeypatch)
    manager = db.DatabaseManager()
    trade = _trade()
    manager.add_active_trade(trade)
    manager2 = db.DatabaseManager()
    restored = manager2.get_active_trades()
    assert len(restored) == 1
    assert restored[0]["id"] == trade["id"]
    assert restored[0]["symbol"] == "GC=F"
    assert restored[0]["entry"] == trade["entry"]
    assert db_path.exists()


def test_phase4_close_is_atomic_and_idempotent(tmp_path, monkeypatch):
    db, _ = _fresh_db(tmp_path, monkeypatch)
    manager = db.DatabaseManager()
    trade = _trade()
    manager.add_active_trade(trade)
    closed = _closed(trade)
    assert manager.close_active_trade(trade["id"], closed) is True
    assert manager.get_active_trades() == []
    assert len(manager.get_trade_history()) == 1
    assert manager.close_active_trade(trade["id"], closed) is False
    assert manager.get_active_trades() == []
    assert len(manager.get_trade_history()) == 1


def test_phase4_restart_reads_same_sqlite_file(tmp_path, monkeypatch):
    db, db_path = _fresh_db(tmp_path, monkeypatch)
    manager = db.DatabaseManager()
    manager.add_active_trade(_trade("restart-gold"))
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT id, symbol FROM active_trades WHERE id=?", ("restart-gold",)).fetchone()
    assert row == ("restart-gold", "GC=F")
