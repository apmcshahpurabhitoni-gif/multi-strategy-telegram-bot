"""Production entry point.

Startup applies only explicit compatibility adapters. Sweep V2 freshness and
candle rules live in the canonical strategy modules; no source rewriting or
runtime monkey-patching is used for freshness.
"""
from __future__ import annotations

try:
    from backtest import BacktestEngine
    from backtest_compat import apply_backtest_compat
    apply_backtest_compat(BacktestEngine)
except Exception as exc:
    print(f"[BACKTEST COMPAT] unavailable: {exc}")

import main as _main


if __name__ == "__main__":
    _main.main()
