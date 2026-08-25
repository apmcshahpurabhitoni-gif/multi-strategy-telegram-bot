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
    main_file = os.path.join(base, "main.py")
    sys.argv = [main_file, *sys.argv[1:]]
    with open(main_file, "rb") as f:
        code = compile(f.read(), main_file, "exec")
    exec(code, globals(), globals())
