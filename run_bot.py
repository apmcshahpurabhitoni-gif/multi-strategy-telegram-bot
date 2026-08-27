"""Production entry point.

Keep startup simple: execute main.py in the same global namespace so the
Telegram bot, dashboard API, and paper-trading state continue to share the
same process. Dashboard HTML migrations and UI patches must be committed to
source files, not rewritten during every Render restart.
"""
from __future__ import annotations

import os
import sys


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    # Explicitly load the Phase 6 backtest response compatibility layer before
    # main.py imports BacktestEngine. This is deterministic on Render and does
    # not depend on Python's optional sitecustomize discovery behavior.
    try:
        from backtest import BacktestEngine
        from backtest_compat import apply_backtest_compat
        apply_backtest_compat(BacktestEngine)
    except Exception as exc:
        print(f"[BACKTEST COMPAT] unavailable: {exc}")

    main_file = os.path.join(base, "main.py")
    with open(main_file, "r", encoding="utf-8") as f:
        source = f.read()

    # main.py is the legacy production module and starts its scanner inside
    # the __main__ block. Inject the canonical Sweep V2 runtime immediately
    # before that block so every scanner cycle uses the closed-candle engine,
    # one-hour freshness rule, and compact Telegram message before startup.
    bootstrap = """
# Phase 9 Sweep V2 runtime bootstrap: install before production startup.
try:
    import sweep_runtime as _sweep_runtime
    _sweep_runtime.install(sys.modules[__name__])
except Exception as _sweep_bootstrap_error:
    print(f\"[SWEEP BOOTSTRAP] unavailable: {_sweep_bootstrap_error}\")
"""
    marker = 'if __name__ == "__main__":'
    if marker not in source:
        raise RuntimeError("main.py startup marker not found; refusing to run unpatched production code")
    source = source.replace(marker, bootstrap + "\n" + marker, 1)

    # The startup notice must describe the actual Sweep V2 rule, not the old
    # global six-hour wording that caused the Telegram confusion.
    source = source.replace(
        'f"⚠️ *FILTER ACTIVE:* Stale signals older than {MAX_SIGNAL_AGE_HOURS}h or sent >={MAX_MSG_SEND_COUNT}x are suppressed.\\n"',
        'f"⚠️ *FILTER ACTIVE:* Sweep alerts older than 1h or sent >={MAX_MSG_SEND_COUNT}x are suppressed.\\n"',
        1,
    )
    source = source.replace(
        'print(f"[INIT] Bot running with clean names, {MAX_SIGNAL_AGE_HOURS}h stale limit, and {MAX_MSG_SEND_COUNT}x repetition cap.")',
        'print(f"[INIT] Bot running with Sweep V2 one-hour freshness limit and {MAX_MSG_SEND_COUNT}x repetition cap.")',
        1,
    )

    sys.argv = [main_file, *sys.argv[1:]]
    code = compile(source, main_file, "exec")
    exec(code, globals(), globals())
