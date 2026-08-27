from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import sweep_runtime

IST = ZoneInfo("Asia/Kolkata")


class FakeMain:
    IST = IST
    BR = "━━━━━━━━━━━━━━━━━━━━━━"
    BR2 = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    def __init__(self):
        self.check_sweep = lambda *args, **kwargs: None
        self.handle_sweep = lambda *args, **kwargs: None
        self.notify_neutral_sweep = lambda *args, **kwargs: None
        self.msg_trade_signal = lambda *args, **kwargs: "legacy"
        self.messages = []
        self.executions = []

    @staticmethod
    def _currency(symbol): return "₹"
    @staticmethod
    def display_name(symbol): return "Reliance"
    @staticmethod
    def load_json(*args, **kwargs): return []
    @staticmethod
    def save_json(*args, **kwargs): pass
    def send_sweep_to_all(self, message, **kwargs): self.messages.append(message)
    @staticmethod
    def alert_error(*args, **kwargs): raise AssertionError(f"unexpected alert_error: {args} {kwargs}")
    @staticmethod
    def get_price(symbol): return 1015.0
    def execute(self, symbol, mtype, account, strat, direction, entry, sl, signal_ts_ms):
        self.executions.append((symbol, mtype, account, strat, direction, entry, sl, signal_ts_ms))
        message = self.msg_trade_signal(
            symbol, mtype, strat, direction, "4H", entry, sl, 1085.0,
            10.0, 350.0, account, signal_ts_ms,
        )
        # Mirror main.py's production execute() contract: execute() obtains the
        # message from msg_trade_signal() and sends it through send_sweep_to_all().
        self.send_sweep_to_all(message, parse_mode="Markdown")


def make_result(candle_end, direction="BULLISH"):
    candle_start = candle_end - timedelta(hours=4)
    return SimpleNamespace(
        direction=direction, timeframe="4H", candle_start=candle_start, candle_end=candle_end,
        previous={"Open": 1000.0, "High": 1010.0, "Low": 990.0, "Close": 1005.0},
        current={"Open": 1005.0, "High": 1020.0, "Low": 980.0, "Close": 1015.0}, schedule_warning=None,
    )


def install_with_mocks(monkeypatch, main, result, baseline_start, new_start):
    # check_sweep_v2 requires at least two closed bars on every invocation:
    # one prior candle plus the latest closed candle. The first call establishes
    # startup baseline; the second call exposes the genuinely new candle.
    calls = iter([
        [baseline_start - timedelta(hours=4), baseline_start],
        [baseline_start, new_start],
    ])

    def fake_build_closed_candles(df, symbol, now):
        starts = next(calls)
        return pd.DataFrame(index=starts), "4H", None

    monkeypatch.setattr(sweep_runtime, "build_closed_candles", fake_build_closed_candles)
    monkeypatch.setattr(sweep_runtime, "detect_sweep", lambda df, symbol, now: result)
    monkeypatch.setattr(sweep_runtime, "_load_signal_history", lambda: [])
    monkeypatch.setattr(sweep_runtime, "_write_signal_history", lambda rows: None)
    monkeypatch.setattr(sweep_runtime, "_save", lambda: None)
    monkeypatch.setattr(sweep_runtime, "_load", lambda: None)
    sweep_runtime.STATE = {}
    sweep_runtime.CONTEXT = {}
    sweep_runtime.STARTUP_BASELINE = {}
    sweep_runtime.install(main)


def test_runtime_blocks_sweep_older_than_one_hour(monkeypatch):
    main = FakeMain(); now = datetime.now(IST)
    # The returned candle close is deliberately old enough to be stale.
    candle_end = now - timedelta(minutes=61)
    result = make_result(candle_end)
    candle_start = candle_end - timedelta(hours=4)
    install_with_mocks(monkeypatch, main, result, candle_start - timedelta(hours=4), candle_start)
    assert main.check_sweep("RELIANCE.NS", object()) is None
    assert main.check_sweep("RELIANCE.NS", object()) is None
    assert main.executions == []
    assert main.messages == []


def test_runtime_sends_compact_message_and_executes_fresh_sweep(monkeypatch):
    main = FakeMain(); now = datetime.now(IST)
    candle_end = now - timedelta(minutes=30)
    result = make_result(candle_end, "BULLISH")
    candle_start = candle_end - timedelta(hours=4)
    # First call establishes startup baseline. Second call exposes a genuinely new
    # closed candle whose close is only 30 minutes old.
    install_with_mocks(monkeypatch, main, result, candle_start - timedelta(hours=4), candle_start)
    assert main.check_sweep("RELIANCE.NS", object()) is None
    sweep = main.check_sweep("RELIANCE.NS", object())
    assert sweep is not None
    main.handle_sweep("RELIANCE.NS", "NSE", sweep)
    assert len(main.executions) == 1
    assert len(main.messages) == 1
    message = main.messages[0]
    assert "SWEEP V2 · Reliance · FRESH" in message
    assert "Signal:* `BUY`" in message
    assert "Timeframe:* `4H`" in message
    assert "Candle closed" in message
    assert "Age" in message
    assert "Sweep High" in message
    assert "Sweep Low" in message
    assert "PAPER BUY" in message
    assert "Entry" in message and "SL" in message and "TP" in message
    assert "Previous Candle" not in message
    assert "Current Candle" not in message
    assert "REMINDER" not in message
