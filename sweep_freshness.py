"""Canonical freshness policy for Sweep V2.

This module is intentionally independent of ``main`` so freshness is a
strategy contract, not a startup monkey-patch or global application setting.
"""
from __future__ import annotations

import time


SWEEP_FRESHNESS_SECONDS = 60 * 60


def signal_age(signal_ts_ms: int | float | None, now_ms: int | float | None = None) -> tuple[str, str]:
    """Return minute-only age and the canonical FRESH/STALE status."""
    if not signal_ts_ms:
        return "Unknown", "⚠️ STALE"
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    diff_ms = max(0, now_ms - int(signal_ts_ms))
    minutes = diff_ms // 60000
    status = "✅ FRESH" if diff_ms <= SWEEP_FRESHNESS_SECONDS * 1000 else "⚠️ STALE"
    return f"{minutes} min ago", status


def is_fresh(signal_ts_ms: int | float | None, now_ms: int | float | None = None) -> bool:
    """Return whether a Sweep V2 signal is still actionable."""
    if not signal_ts_ms:
        return False
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    return max(0, now_ms - int(signal_ts_ms)) <= SWEEP_FRESHNESS_SECONDS * 1000
