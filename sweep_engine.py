"""Canonical candle construction and two-sided sweep logic."""
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
    return {"Open": float(group["Open"].iloc[0]), "High": float(group["High"].max()), "Low": float(group["Low"].min()), "Close": float(group["Close"].iloc[-1])}


def _resample(df, rule, offset, now):
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    bars = df.resample(rule, origin="start_day", offset=offset, label="left", closed="left").agg(agg).dropna()
    ends = bars.index + pd.Timedelta(rule)
    return bars[ends <= now]


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
        bars = bars[(bars.index.hour * 60 + bars.index.minute >= 555) & (bars.index.hour * 60 + bars.index.minute <= 855)]
        return bars, "1H", None

    if symbol.endswith(".NS"):
        rows = []
        for day, group in x.groupby(x.index.date):
            base = IST.localize(datetime.combine(day, datetime.min.time()))
            a = group[(group.index >= base + timedelta(hours=9, minutes=15)) & (group.index < base + timedelta(hours=13, minutes=15))]
            b = group[(group.index >= base + timedelta(hours=13, minutes=15)) & (group.index < base + timedelta(hours=15, minutes=15))]
            if not a.empty:
                o = _ohlc(a); rows.append((pd.Timestamp(base + timedelta(hours=9, minutes=15)), o))
            if not b.empty and b.index.max() >= base + timedelta(hours=14, minutes=15):
                o = _ohlc(b); rows.append((pd.Timestamp(base + timedelta(hours=13, minutes=15)), o))
        if not rows:
            return pd.DataFrame(), "4H", "No complete NSE session bars"
        bars = pd.DataFrame([{**o, "Time": t} for t, o in rows]).set_index("Time")
        ends = pd.Series([t + (pd.Timedelta(hours=2) if t.hour == 13 else pd.Timedelta(hours=4)) for t in bars.index], index=bars.index)
        return bars[ends <= now_ts], "4H", None

    if symbol == "BTC-USD":
        return _resample(x, "4h", "1h30min", now_ts), "4H", None

    return _resample(x, "4h", "2h30min", now_ts), "4H", None


def detect_sweep(df: pd.DataFrame, symbol: str, now: Optional[datetime] = None):
    bars, tf, warning = build_closed_candles(df, symbol, now)
    if len(bars) < 2:
        return None
    prev, cur = bars.iloc[-2], bars.iloc[-1]
    cur_start = pd.Timestamp(bars.index[-1])
    cur_end = cur_start + (pd.Timedelta(hours=1) if tf == "1H" else pd.Timedelta(hours=2) if symbol.endswith(".NS") and cur_start.hour == 13 else pd.Timedelta(hours=4))
    high_swept = float(cur["High"]) > float(prev["High"])
    low_swept = float(cur["Low"]) < float(prev["Low"])
    if not (high_swept and low_swept):
        return None
    close = float(cur["Close"])
    if close > float(prev["High"]): direction = "BULLISH"
    elif close < float(prev["Low"]): direction = "BEARISH"
    else: direction = "NEUTRAL"
    if symbol == "BTC-USD": expected = {1,5,9,13,17,21}; expected_minute = 30
    elif symbol in ("^NSEI", "^NSEBANK"): expected = {9,10,11,12,13,14}; expected_minute = 15
    elif symbol.endswith(".NS"): expected = {9,13}; expected_minute = 15
    else: expected = {2,6,10,14,18,22}; expected_minute = 30
    if cur_start.hour not in expected or cur_start.minute != expected_minute:
        warning = f"Candle start {cur_start.strftime('%H:%M IST')} is outside configured TradingView schedule"
    return SweepResult(direction, tf, cur_start, cur_end,
                       {k: float(prev[k]) for k in ("Open","High","Low","Close")},
                       {k: float(cur[k]) for k in ("Open","High","Low","Close")},
                       high_swept, low_swept, warning)
