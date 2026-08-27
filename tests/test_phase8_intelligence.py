from phase8_intelligence import build_intelligence, enrich_trade, strategy_statistics


def test_enrich_trade_reports_outcome_and_r_multiple():
    trade = {"symbol": "GC=F", "strategy": "TrendPulse 1H", "direction": "BUY", "entry": 100, "exit": 106, "sl": 98, "pnl": 600}
    result = enrich_trade(trade)
    assert result["intelligence"]["outcome"] == "WIN"
    assert result["intelligence"]["direction"] == "BUY"
    assert result["intelligence"]["r_multiple"] == 3.0


def test_strategy_statistics_groups_existing_results_only():
    history = [{"strategy": "Sweep", "pnl": 100}, {"strategy": "Sweep", "pnl": -40}, {"strategy": "TrendPulse", "pnl": 60}]
    rows = strategy_statistics(history)
    assert rows[0]["strategy"] == "Sweep"
    assert rows[0]["trades"] == 2
    assert rows[0]["wins"] == 1
    assert rows[0]["losses"] == 1
    assert rows[0]["pnl_inr"] == 60
    assert rows[0]["profit_factor"] == 2.5


def test_build_intelligence_is_explicitly_read_only():
    history = [{"strategy": "Sweep", "pnl": 100}]
    signals = [{"symbol": "BTC-USD", "direction": "SELL", "strategy": "4H Sweep"}]
    payload = build_intelligence(history, signals)
    assert payload["version"] == "8A"
    assert payload["read_only"] is True
    assert payload["summary"]["win_rate_pct"] == 100.0
    assert payload["strategy_stats"][0]["pnl_inr"] == 100
    assert payload["signals"][0]["symbol"] == "BTC-USD"
