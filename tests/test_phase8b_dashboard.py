from phase8_dashboard import build_dashboard_intelligence


def test_phase8b_builds_signal_trade_and_strategy_views():
    payload = {
        "summary": {"trades": 2, "wins": 1, "losses": 1, "win_rate_pct": 50.0},
        "signals": [{"id": "s1", "sym": "NIFTY", "dir": "BUY", "strategy": "Sweep", "hint": "Confirmed sweep signal"}],
        "trades": [{"id": "t1", "symbol": "NIFTY", "entry": 100, "exit": 110, "sl": 95, "pnl": 1000,
                     "intelligence": {"direction": "BUY", "outcome": "WIN", "pnl_inr": 1000, "r_multiple": 2.0,
                                      "strategy": "Sweep", "has_stop": True, "has_exit": True}}],
        "strategy_stats": [{"strategy": "Sweep", "trades": 1, "wins": 1, "losses": 0, "flat": 0, "win_rate_pct": 100.0,
                             "pnl_inr": 1000, "expectancy_inr": 1000, "profit_factor": None, "avg_win_inr": 1000, "avg_loss_inr": 0}],
    }
    out = build_dashboard_intelligence(payload)
    assert out["version"] == "8B"
    assert out["read_only"] is True
    assert out["signals"][0]["symbol"] == "NIFTY"
    assert out["signals"][0]["explanation"] == "Confirmed sweep signal"
    assert out["trades"][0]["outcome"] == "WIN"
    assert out["trades"][0]["r_multiple"] == 2.0
    assert out["strategies"][0]["strategy"] == "Sweep"


def test_phase8b_does_not_invent_missing_metrics():
    out = build_dashboard_intelligence({"strategy_stats": [{"strategy": "Unknown"}]})
    card = out["strategies"][0]
    assert card["profit_factor"] is None
    assert card["expectancy_inr"] is None


def test_phase8b_empty_payload_is_safe():
    out = build_dashboard_intelligence({})
    assert out == {"version": "8B", "read_only": True, "summary": {}, "signals": [], "trades": [], "strategies": []}
