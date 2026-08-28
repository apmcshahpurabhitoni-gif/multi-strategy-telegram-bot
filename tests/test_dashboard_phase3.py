import pytz

import dashboard_api


def test_phase3_provider_symbol_display_names():
    assert dashboard_api._display_symbol("GC=F") == "Gold"
    assert dashboard_api._display_symbol("XAUUSD") == "Gold"
    assert dashboard_api._display_symbol("XAU/USD") == "Gold"
    assert dashboard_api._display_symbol("BTC-USD") == "Bitcoin"
    assert dashboard_api._display_symbol("^NSEI") == "NIFTY 50"
    assert dashboard_api._display_symbol("^NSEBANK") == "BANK NIFTY"


def test_phase3_unknown_symbol_is_not_changed():
    assert dashboard_api._display_symbol("RELIANCE.NS") == "RELIANCE.NS"


def test_phase3_display_price_is_dashboard_only():
    raw = 4664.89990234375
    displayed = dashboard_api._display_price(raw)
    assert displayed == 4664.9
    assert raw == 4664.89990234375


def test_phase3_history_signal_fallback_uses_display_symbol():
    history = [{
        "id": "gold-1",
        "symbol": "GC=F",
        "strategy": "Sweep V2",
        "direction": "BULLISH",
        "opened_at": "2026-08-28T10:15:00+00:00",
        "pnl": 100,
    }]
    out = dashboard_api._history_signal_fallback(
        history,
        pytz.timezone("Asia/Kolkata"),
    )
    assert out[0]["sym"] == "Gold"
    assert out[0]["dir"] == "BUY"


def test_phase3_display_mapping_never_exposes_provider_names():
    for symbol in ("GC=F", "XAUUSD", "XAU/USD", "BTC-USD", "^NSEI", "^NSEBANK"):
        displayed = dashboard_api._display_symbol(symbol)
        assert displayed not in {"GC=F", "BTC-USD", "^NSEI", "^NSEBANK"}
