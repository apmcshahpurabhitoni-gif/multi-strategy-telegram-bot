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
    def _currency(symbol): return "₹"

    @staticmethod
    def display_name(symbol): return symbol


def make_result(now, age_minutes=30, direction="BULLISH"):
    end = now - timedelta(minutes=age_minutes)
    return SimpleNamespace(
        direction=direction, timeframe="4H", candle_start=end - timedelta(hours=4), candle_end=end,
        previous={"Open": 1000.0, "High": 1010.0, "Low": 990.0, "Close": 1005.0},
        current={"Open": 1005.0, "High": 1020.0, "Low": 980.0, "Close": 1015.0}, schedule_warning=None,
    )


def test_gold_display_name_is_human_readable():
    assert sweep_runtime._display_name(FakeMain, "GC=F") == "Gold"


def test_btc_display_name_is_human_readable():
    assert sweep_runtime._display_name(FakeMain, "BTC-USD") == "Bitcoin (BTC)"


def test_direction_header_and_freshness_are_independent():
    now = datetime.now(IST)
    for direction, icon in (("BULLISH", "🟢"), ("BEARISH", "🔴"), ("NEUTRAL", "🟡")):
        msg = sweep_runtime._signal_message(FakeMain, "GC=F", "FOREX", make_result(now, 30, direction))
        assert f"{icon}SWEEP V2 · Gold · ✅" in msg
        assert "GC=F" not in msg.split("\n")[0]
        assert "Signal Status:* `✅ FRESH`" in msg


def test_gold_stale_uses_warning_but_keeps_direction():
    now = datetime.now(IST)
    msg = sweep_runtime._signal_message(FakeMain, "GC=F", "FOREX", make_result(now, 61, "BEARISH"))
    assert "🔴SWEEP V2 · Gold · ⚠️" in msg
    assert "GC=F" not in msg.split("\n")[0]
    assert "STALE" in msg
