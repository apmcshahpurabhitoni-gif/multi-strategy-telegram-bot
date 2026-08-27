from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import sweep_runtime

IST = ZoneInfo("Asia/Kolkata")


class FakeMain:
    IST = IST
    BR = "━━━━━━━━━━━━━━━━━━━━━━"
    BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    @staticmethod
    def _currency(symbol):
        return "₹"

    @staticmethod
    def display_name(symbol):
        return "Reliance"


def make_result(now, age_minutes=30, direction="BULLISH"):
    end = now - timedelta(minutes=age_minutes)
    start = end - timedelta(hours=4)
    return SimpleNamespace(
        direction=direction,
        timeframe="4H",
        candle_start=start,
        candle_end=end,
        previous={"Open": 1000.0, "High": 1010.0, "Low": 990.0, "Close": 1005.0},
        current={"Open": 1005.0, "High": 1020.0, "Low": 980.0, "Close": 1015.0},
        schedule_warning=None,
    )


def test_freshness_is_one_hour_not_six():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=59)
    assert sweep_runtime._freshness(FakeMain, result.candle_end)[0] == "FRESH"

    result = make_result(now, age_minutes=61)
    assert sweep_runtime._freshness(FakeMain, result.candle_end)[0] == "STALE"


def test_freshness_at_sixty_minutes_remains_fresh():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=59, direction="BULLISH")
    result = result.__class__(**{**result.__dict__, "candle_end": now - timedelta(seconds=3599)})
    assert sweep_runtime._freshness(FakeMain, result.candle_end)[0] == "FRESH"


def test_canonical_main_age_helper_is_also_one_hour():
    now_ms = int(datetime.now(IST).timestamp() * 1000)
    fresh, tag = sweep_runtime._canonical_main_age(now_ms - 3599 * 1000)
    assert fresh.startswith("59 min ago")
    assert tag == "✅ FRESH"
    stale, tag = sweep_runtime._canonical_main_age(now_ms - 3600 * 1000 - 1000)
    assert tag == "⚠️ STALE"
    assert stale.startswith("1 hr")


def test_compact_price_formatting_is_market_appropriate():
    assert sweep_runtime._fmt_price("RELIANCE.NS", 1925.0, "₹") == "₹1,925.00"
    assert sweep_runtime._fmt_price("BTC-USD", 123456.789, "$") == "$123,456.79"
    assert sweep_runtime._fmt_price("EURUSD=X", 1.123456, "") == "1.12346"
    assert sweep_runtime._fmt_price("USDJPY=X", 147.12345, "") == "147.123"
    assert sweep_runtime._fmt_price("GC=F", 2501.567, "$") == "$2,501.57"


def test_compact_message_replaces_legacy_diagnostic_block():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=30, direction="BULLISH")
    message = sweep_runtime._signal_message(
        FakeMain,
        "RELIANCE.NS",
        "NSE",
        result,
        entry=1015.0,
        sl=980.0,
        tp=1085.0,
        account="nifty",
        qty=10.0,
        risk_amt=350.0,
    )

    assert "SWEEP V2 · Reliance · FRESH" in message
    assert "Signal:* `BUY`" in message
    assert "Sweep High" in message
    assert "Sweep Low" in message
    assert "Candle closed" in message
    assert "PAPER BUY" in message
    assert "Entry" in message
    assert "SL" in message
    assert "TP" in message
    assert "Account" in message
    assert "Quantity" in message
    assert "Risk" in message
    assert "₹1,020.00" in message
    assert "₹980.00" in message
    assert "Previous Candle" not in message
    assert "Current Candle" not in message
    assert "High swept" not in message
    assert "Low swept" not in message
    assert "Close classification" not in message
    assert "REMINDER" not in message


def test_stale_message_explicitly_blocks_new_trade():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=61, direction="BEARISH")
    message = sweep_runtime._signal_message(FakeMain, "RELIANCE.NS", "NSE", result)
    assert "STALE" in message
    assert "older than 1 hour" in message
    assert "no new trade should be opened" in message
