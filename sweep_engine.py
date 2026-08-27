"""Canonical, closed-candle sweep logic with instrument-specific schedules."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import pytz

IST = pytz.timezone("Asia/Kolkata")

@dataclass(frozen=True)
class SweepResult:
    direction: str
    timeframe: str
    candle_start: pd.Timestamp
    candle_end: pd.Timestamp
    previous: dict
    current: dict
    high_swept: bool
    low_swept: bool
    schedule_warning: Optional[str] = None


def _ist_index(df: pd.DataFrame, nse: bool = False) -> pd.DataFrame:
    out = df.copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is None:
        idx = idx.tz_localize(IST if nse else "UTC")
    else:
        idx = idx.tz_convert(IST)
    out.index = idx
    return out.sort_index()


def _ohlc(group: pd.DataFrame) -> dict:
    return {
        "Open": float(group["Open"].iloc[0]),
        "High": float(group["High"].max()),
        "Low": float(group["Low"].min()),
        "Close": float(group["Close"].iloc[-1]),
    }


def _resample(df: pd.DataFrame, rule: str, offset: str, now: pd.Timestamp) -> pd.DataFrame:
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    bars = df.resample(rule, origin="start_day", offset=offset, label="left", closed="left").agg(agg).dropna()
    ends = bars.index + pd.Timedelta(rule)
    return bars[ends <= now].copy()


def _fx_or_gold_expected_start(now: pd.Timestamp) -> pd.Timestamp:
    """Return the most recently CLOSED OANDA 4H boundary in IST."""
    now = pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize(IST)
    else:
        now = now.tz_convert(IST)
    day = now.normalize()
    candidates = [
        day + pd.Timedelta(hours=2, minutes=30),
        day + pd.Timedelta(hours=6, minutes=30),
        day + pd.Timedelta(hours=10, minutes=30),
        day + pd.Timedelta(hours=14, minutes=30),
        day + pd.Timedelta(hours=18, minutes=30),
        day + pd.Timedelta(hours=22, minutes=30),
    ]
    prior = [c for c in candidates if c <= now]
    if prior:
        return prior[-1]
    return candidates[-1] - pd.Timedelta(days=1)


def _resample_from_boundaries(df: pd.DataFrame, starts: list[pd.Timestamp], now: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for start in starts:
        end = start + pd.Timedelta(hours=4)
        if end > now:
            continue
        group = df[(df.index >= start) & (df.index < end)]
        if group.empty:
            continue
        rows.append((start, _ohlc(group)))
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"], dtype=float)
    return pd.DataFrame([{**ohlc, "Time": start} for start, ohlc in rows]).set_index("Time").sort_index()


def build_closed_candles(df: pd.DataFrame, symbol: str, now: Optional[datetime] = None):
    if df is None or df.empty:
        return pd.DataFrame(), "", "No market data"

    nse = "^NSE" in symbol or symbol.endswith(".NS")
    x = _ist_index(df, nse=nse)
    now_ts = pd.Timestamp(now or datetime.now(IST))
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize(IST)
    else:
        now_ts = now_ts.tz_convert(IST)

    if symbol in ("^NSEI", "^NSEBANK"):
        bars = _resample(x, "1h", "9h15min", now_ts)
        bars = bars[(bars.index.hour * 60 + bars.index.minute >= 555) &
                    (bars.index.hour * 60 + bars.index.minute <= 855)]
        return bars, "1H", None

    if symbol.endswith(".NS"):
        rows = []
        for day, group in x.groupby(x.index.date):
            base = IST.localize(datetime.combine(day, datetime.min.time()))
            a = group[(group.index >= base + timedelta(hours=9, minutes=15)) &
                      (group.index < base + timedelta(hours=13, minutes=15))]
            b = group[(group.index >= base + timedelta(hours=13, minutes=15)) &
                      (group.index < base + timedelta(hours=15, minutes=15))]
            if not a.empty:
                rows.append((pd.Timestamp(base + timedelta(hours=9, minutes=15)), _ohlc(a), base + timedelta(hours=13, minutes=15)))
            if not b.empty and b.index.max() >= base + timedelta(hours=14, minutes=15):
                rows.append((pd.Timestamp(base + timedelta(hours=13, minutes=15)), _ohlc(b), base + timedelta(hours=15, minutes=15)))
        if not rows:
            return pd.DataFrame(), "4H", "No complete NSE session bars"
        bars = pd.DataFrame([{**ohlc, "Time": start} for start, ohlc, _ in rows]).set_index("Time").sort_index()
        ends = pd.Series([end for _, _, end in rows], index=[start for start, _, _ in rows])
        return bars[ends <= now_ts], "4H", None

    if symbol == "BTC-USD":
        bars = _resample(x, "4h", "1h30min", now_ts)
        return bars, "4H", None

    latest = _fx_or_gold_expected_start(now_ts)
    starts = []
    anchor = latest - pd.Timedelta(days=3)
    while anchor <= latest:
        for h in (2, 6, 10, 14, 18, 22):
            starts.append(anchor.normalize() + pd.Timedelta(hours=h, minutes=30))
        anchor += pd.Timedelta(days=1)
    bars = _resample_from_boundaries(x, starts, now_ts)
    return bars, "4H", None


def _expected_close_schedule(symbol: str) -> tuple[set[int], int]:
    """Return expected candle-close hours/minute in IST for schedule validation."""
    if symbol == "BTC-USD":
        return {5, 9, 13, 17, 21, 1}, 30
    if symbol in ("^NSEI", "^NSEBANK"):
        return {10, 11, 12, 13, 14, 15}, 15
    if symbol.endswith(".NS"):
        return {13, 15}, 15
    return {6, 10, 14, 18, 22, 2}, 30


def detect_sweep(df: pd.DataFrame, symbol: str, now: Optional[datetime] = None):
    bars, tf, warning = build_closed_candles(df, symbol, now)
    if len(bars) < 2:
        return None

    prev, cur = bars.iloc[-2], bars.iloc[-1]
    cur_start = pd.Timestamp(bars.index[-1])
    if symbol.endswith(".NS") and cur_start.hour == 13:
        cur_end = cur_start + pd.Timedelta(hours=2)
    elif tf == "1H":
        cur_end = cur_start + pd.Timedelta(hours=1)
    else:
        cur_end = cur_start + pd.Timedelta(hours=4)

    high_swept = float(cur["High"]) > float(prev["High"])
    low_swept = float(cur["Low"]) < float(prev["Low"])
    if not (high_swept and low_swept):
        return None

    close = float(cur["Close"])
    if close > float(prev["High"]):
        direction = "BULLISH"
    elif close < float(prev["Low"]):
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    expected_hours, expected_minute = _expected_close_schedule(symbol)
    if cur_end.hour not in expected_hours or cur_end.minute != expected_minute:
        warning = f"Candle close {cur_end.strftime('%H:%M IST')} is outside configured TradingView schedule"

    return SweepResult(
        direction=direction,
        timeframe=tf,
        candle_start=cur_start,
        candle_end=cur_end,
        previous={k: float(prev[k]) for k in ("Open", "High", "Low", "Close")},
        current={k: float(cur[k]) for k in ("Open", "High", "Low", "Close")},
        high_swept=high_swept,
        low_swept=low_swept,
        schedule_warning=warning,
    )
