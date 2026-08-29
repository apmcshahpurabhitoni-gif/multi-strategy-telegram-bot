"""Application adapter for the canonical Sweep V2 engine.

The adapter deliberately contains no sweep rules.  It translates the typed
SweepResult into the small tuple shape consumed by the existing application,
so the legacy scanner can be migrated without duplicating strategy logic.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sweep_engine import SweepResult, detect_sweep


def detect_canonical_sweep(df: Any, symbol: str, now: datetime | None = None):
    """Return the canonical Sweep V2 result in the legacy-compatible shape.

    Returns ``None`` when no closed candle pair has a two-sided sweep.
    Otherwise returns ``(direction, high, low, candle_start_ms, candle_end_ms)``.
    ``candle_end_ms`` is the timestamp used by the canonical one-hour freshness
    gate for NIFTY/BANK NIFTY and by the strategy's configured candle close for
    other instruments.
    """
    result: SweepResult | None = detect_sweep(df, symbol, now)
    if result is None:
        return None

    start_ms = int(result.candle_start.timestamp() * 1000)
    end_ms = int(result.candle_end.timestamp() * 1000)
    return (
        result.direction,
        result.current["High"],
        result.current["Low"],
        start_ms,
        end_ms,
    )


def canonical_sweep_status(df: Any, symbol: str, now: datetime | None = None) -> dict[str, Any]:
    """Expose typed metadata for dashboards/tests without leaking engine logic."""
    result: SweepResult | None = detect_sweep(df, symbol, now)
    if result is None:
        return {"signal": None, "timeframe": None, "warning": None}
    return {
        "signal": result.direction,
        "timeframe": result.timeframe,
        "candle_start": result.candle_start.isoformat(),
        "candle_end": result.candle_end.isoformat(),
        "high_swept": result.high_swept,
        "low_swept": result.low_swept,
        "warning": result.schedule_warning,
    }
