from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import sweep_engine
import sweep_runtime


IST = ZoneInfo("Asia/Kolkata")


class FakeMain:
    IST = IST
    BR = "━━━━━━━━━━━━━━━━━━━━━━"
    BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    @staticmethod
    def _currency(symbol):
        return "$" if symbol == "GC=F" else "₹"

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


def make_nifty_bars(prev_high=24133.60, prev_low=24090.85, cur_high=24167.85, cur_low=24107.10, cur_close=24120.00):
    idx = pd.date_range("2026-08-28 09:15", periods=24, freq="5min")
    rows = []
    for i, ts in enumerate(idx):
        if i < 12:
            high, low = prev_high if i == 11 else 24120.0, prev_low if i == 11 else 24100.0
            close = 24110.0
        else:
            high, low = cur_high if i == 12 else 24150.0, cur_low if i == 12 else 24110.0
            close = cur_close if i == 23 else 24120.0
        rows.append({"Open": close, "High": high, "Low": low, "Close": close})
    return pd.DataFrame(rows, index=idx)


def test_freshness_is_one_hour_not_six():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=59)
    assert sweep_runtime._freshness(FakeMain, result.candle_end)[0] == "FRESH"

    result = make_result(now, age_minutes=61)
    assert sweep_runtime._freshness(FakeMain, result.candle_end)[0] == "STALE"


def test_legacy_age_formatter_also_stays_in_minutes_for_stale_sweeps(monkeypatch):
    fake_now_ms = 1_900_000_000_000
    monkeypatch.setattr(sweep_runtime.time, "time", lambda: fake_now_ms / 1000)

    fresh_text, fresh_status = sweep_runtime._canonical_main_age(fake_now_ms - 59 * 60 * 1000)
    stale_text, stale_status = sweep_runtime._canonical_main_age(fake_now_ms - 4 * 60 * 60 * 1000)

    assert fresh_text == "59 min ago"
    assert fresh_status == "✅ FRESH"
    assert stale_text == "240 min ago"
    assert stale_status == "⚠️ STALE"
    assert "hr" not in stale_text


def test_approved_header_uses_green_for_buy_and_fresh_check():
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

    assert message.startswith("🟢SWEEP V2 · Reliance ·  ✅")
    assert "Signal:* `🟢 BUY`" in message
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
    assert "Previous Candle" not in message
    assert "Current Candle" not in message
    assert "Signal Status:" not in message
    assert "REMINDER" not in message


def test_approved_header_uses_red_for_sell_and_fresh_check():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=30, direction="BEARISH")
    message = sweep_runtime._signal_message(FakeMain, "RELIANCE.NS", "NSE", result)
    assert message.startswith("🔴SWEEP V2 · Reliance ·  ✅")
    assert "Signal:* `🔴 SELL`" in message
    assert "⚠️ *STALE" not in message


def test_neutral_keeps_yellow_signal_and_fresh_header_check():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=4, direction="NEUTRAL")
    message = sweep_runtime._signal_message(FakeMain, "RELIANCE.NS", "NSE", result)
    assert message.startswith("✅SWEEP V2 · Reliance ·  ✅")
    assert "Signal:* `🟡 NEUTRAL`" in message
    assert "INFORMATIONAL — NO PAPER TRADE" in message
    assert "⚠️ *STALE" not in message


def test_stale_message_explicitly_blocks_new_trade():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=61, direction="BEARISH")
    message = sweep_runtime._signal_message(FakeMain, "RELIANCE.NS", "NSE", result)
    assert message.startswith("🔴SWEEP V2 · Reliance ·  ⚠️")
    assert "Signal:* `🔴 SELL`" in message
    assert "STALE" in message
    assert "older than 1 hour" in message
    assert "no new trade should be opened" in message


def test_phase2_gold_uses_gold_name_not_provider_symbol():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=5, direction="BULLISH")
    message = sweep_runtime._signal_message(
        FakeMain,
        "GC=F",
        "GOLD",
        result,
        entry=4666.6001,
        sl=4616.0,
        tp=4767.8003,
        account="sweep_4h",
        qty=34.9942,
        risk_amt=1770.71,
    )
    assert "SWEEP V2 · Gold" in message
    assert "GC=F" not in message
    assert "Candle closed" in message
    assert "Age" in message
    assert "$4,666.60" in message
    assert "$4,616.00" in message
    assert "$4,767.80" in message
    assert "PAPER BUY" in message
    assert "Account:* `SWEEP_4H`" in message
    assert "Quantity:* `34.99`" in message
    assert "Risk:* `₹1,770.71`" in message
    assert "DATA SOURCE: Yahoo Finance" in message


def test_phase2_gold_stale_keeps_sell_direction_and_changes_only_freshness():
    now = datetime.now(IST)
    result = make_result(now, age_minutes=61, direction="BEARISH")
    message = sweep_runtime._signal_message(FakeMain, "GC=F", "GOLD", result)
    assert message.startswith("🔴SWEEP V2 · Gold ·  ⚠️")
    assert "Signal:* `🔴 SELL`" in message
    assert "Age:* `61 min ago`" in message
    assert "STALE" in message
    assert "GC=F" not in message


def test_phase1_nifty_bad_example_does_not_sweep():
    df = make_nifty_bars()
    result = sweep_engine.detect_sweep(
        df,
        "^NSEI",
        datetime(2026, 8, 28, 11, 16, tzinfo=IST),
    )
    assert result is None


def test_phase1_nifty_requires_both_sides_to_sweep():
    df = make_nifty_bars(cur_high=24167.85, cur_low=24080.00, cur_close=24120.00)
    result = sweep_engine.detect_sweep(
        df,
        "^NSEI",
        datetime(2026, 8, 28, 11, 16, tzinfo=IST),
    )
    assert result is not None
    assert result.high_swept is True
    assert result.low_swept is True
    assert result.direction == "NEUTRAL"
    assert result.candle_start.hour == 10
    assert result.candle_start.minute == 15
    assert result.candle_end.hour == 11
    assert result.candle_end.minute == 15


def test_phase1_nifty_uses_only_approved_session_starts():
    df = make_nifty_bars(cur_high=24167.85, cur_low=24080.00, cur_close=24170.00)
    bars, tf, warning = sweep_engine.build_closed_candles(
        df,
        "^NSEI",
        datetime(2026, 8, 28, 11, 16, tzinfo=IST),
    )
    assert tf == "1H"
    assert warning is None
    assert list(bars.index.hour) == [9, 10]
    assert all(ts.minute == 15 for ts in bars.index)
    assert all(ts.hour != 15 for ts in bars.index)
