"""Canonical Sweep V2 backtest signal runner.

Signal generation is delegated entirely to sweep_engine.detect_sweep(). This
module deliberately does not implement a second sweep algorithm. It returns
canonical SweepResult events for a historical candle set; execution/P&L
simulation remains the responsibility of BacktestEngine until its legacy
method is surgically migrated.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from sweep_engine import SweepResult, _ist_index, build_closed_candles, detect_sweep


def iter_sweep_signals(df_1h: pd.DataFrame, symbol: str, now: datetime | None = None) -> list[SweepResult]:
    """Return the canonical Sweep V2 signals available in historical data.

    The detector is called once per closed candle. No 4H resampling or legacy
    directional-sweep calculation is performed here.
    """
    if df_1h is None or df_1h.empty:
        return []

    nse = symbol.startswith("^") or symbol.endswith(".NS")
    data = _ist_index(df_1h.copy(), nse=nse)
    if data.empty:
        return []

    data_end = pd.Timestamp(data.index.max())
    bars, _, _ = build_closed_candles(data, symbol, data_end)
    if len(bars) < 2:
        return []

    results: list[SweepResult] = []
    seen: set[tuple[str, int]] = set()
    for candle_start in bars.index:
        candle_start = pd.Timestamp(candle_start)
        result = detect_sweep(data, symbol, candle_start + (pd.Timedelta(hours=1) if symbol in {"^NSEI", "^NSEBANK"} else pd.Timedelta(hours=4)))
        if result is None or result.candle_start != candle_start:
            continue
        key = (symbol, int(result.candle_end.timestamp() * 1000))
        if key in seen:
            continue
        seen.add(key)
        results.append(result)
    return results
