"""Production entry point.

Runs main.py as the real __main__ module so the dashboard, Telegram bot,
paper-trading state, and sweep runtime all share the exact same module
namespace. This is intentionally a thin compatibility launcher.
"""
from __future__ import annotations

import os
import runpy
import sys


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    main_file = os.path.join(base, "main.py")
    # runpy.run_path(..., run_name='__main__') preserves the identity expected
    # by the existing dashboard/API code and avoids the split-namespace bug.
    sys.argv = [main_file, *sys.argv[1:]]
    runpy.run_path(main_file, run_name="__main__")
