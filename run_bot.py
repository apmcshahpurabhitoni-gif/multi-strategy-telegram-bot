"""Production entry point.

Keep startup explicit: import the application module, install the canonical
Sweep V2 runtime into that module, then call its normal main() entry point.
No source rewriting, string injection, or dynamic execution is used here.
"""
from __future__ import annotations

try:
    from backtest import BacktestEngine
    from backtest_compat import apply_backtest_compat
    apply_backtest_compat(BacktestEngine)
except Exception as exc:
    print(f"[BACKTEST COMPAT] unavailable: {exc}")

import main as _main
import sweep_runtime as _sweep_runtime


if __name__ == "__main__":
    _sweep_runtime.install(_main)
    _main.main()
