from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from sweep_engine import build_closed_candles

IST = ZoneInfo("Asia/Kolkata")

NIFTY_STOCKS = [
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
    "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "LT.NS", "HINDUNILVR.NS",
    "AXISBANK.NS", "KOTAKBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "SUNPHARMA.NS",
]
FX_GOLD = [
    "GC=F", "SI=F", "HG=F", "EURUSD=X", "GBPUSD=X", "USDJPY=X",
    "USDCHF=X", "AUDUSD=X", "USDCAD=X", "NZDUSD=X",
]


def minute_frame(start, end):
    idx = pd.date_range(start=start, end=end, freq="15min", tz=IST)
    base = pd.DataFrame(index=idx)
    base["Open"] = 100.0
    base["High"] = 101.0
    base["Low"] = 99.0
    base["Close"] = 100.0
    return base


def test_nifty_and_banknifty_are_1h_at_nse_boundaries():
    now = pd.Timestamp(datetime(2026, 8, 27, 11, 20, tzinfo=IST))
    df = minute_frame("2026-08-27 09:15+05:30", "2026-08-27 11:15+05:30")
    for symbol in ("^NSEI", "^NSEBANK"):
        bars, tf, warning = build_closed_candles(df, symbol, now)
        assert tf == "1H"
        assert warning is None
        assert list(bars.index) == [
            pd.Timestamp("2026-08-27 09:15", tz=IST),
            pd.Timestamp("2026-08-27 10:15", tz=IST),
        ]


def test_all_15_nifty_stocks_use_session_4h_sweep_structure():
    now = pd.Timestamp(datetime(2026, 8, 27, 15, 20, tzinfo=IST))
    df = minute_frame("2026-08-27 09:15+05:30", "2026-08-27 15:00+05:30")
    expected = [pd.Timestamp("2026-08-27 09:15", tz=IST), pd.Timestamp("2026-08-27 13:15", tz=IST)]
    for symbol in NIFTY_STOCKS:
        bars, tf, warning = build_closed_candles(df, symbol, now)
        assert tf == "4H", symbol
        assert warning is None, symbol
        assert list(bars.index) == expected, symbol


def test_gold_and_forex_use_4h_oanda_ist_boundaries():
    now = pd.Timestamp(datetime(2026, 8, 27, 13, 0, tzinfo=IST))
    df = minute_frame("2026-08-27 02:30+05:30", "2026-08-27 10:29+05:30")
    expected = [pd.Timestamp("2026-08-27 02:30", tz=IST), pd.Timestamp("2026-08-27 06:30", tz=IST)]
    for symbol in FX_GOLD:
        bars, tf, warning = build_closed_candles(df, symbol, now)
        assert tf == "4H", symbol
        assert warning is None, symbol
        assert list(bars.index) == expected, symbol


def test_btc_uses_4h_tradingview_ist_boundaries():
    now = pd.Timestamp(datetime(2026, 8, 27, 18, 0, tzinfo=IST))
    df = minute_frame("2026-08-27 01:30+05:30", "2026-08-27 17:29+05:30")
    bars, tf, warning = build_closed_candles(df, "BTC-USD", now)
    assert tf == "4H"
    assert warning is None
    assert list(bars.index)[-3:] == [
        pd.Timestamp("2026-08-27 09:30", tz=IST),
        pd.Timestamp("2026-08-27 13:30", tz=IST),
        pd.Timestamp("2026-08-27 17:30", tz=IST),
    ]


def test_4h_boundary_does_not_include_a_still_forming_candle():
    now = pd.Timestamp(datetime(2026, 8, 27, 13, 7, tzinfo=IST))
    df = minute_frame("2026-08-27 06:30+05:30", "2026-08-27 13:00+05:30")
    bars, tf, warning = build_closed_candles(df, "EURUSD=X", now)
    assert tf == "4H"
    assert pd.Timestamp("2026-08-27 10:30", tz=IST) not in bars.index
