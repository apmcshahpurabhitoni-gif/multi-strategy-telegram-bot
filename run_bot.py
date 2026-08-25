"""Production entry point.

Execute main.py directly in this module's global namespace. The dashboard API
reads the live bot state from sys.modules["__main__"], so using exec here is
intentional: it keeps the bot, dashboard, Telegram handlers, and paper-trading
state in one shared module namespace.
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
