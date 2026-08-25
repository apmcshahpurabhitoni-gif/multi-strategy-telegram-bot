"""Production entry point.

Execute main.py directly in this module's global namespace. The dashboard API
reads the live bot state from sys.modules["__main__"], so using exec here is
intentional: it keeps the bot, dashboard, Telegram handlers, and paper-trading
state in one shared module namespace.

Phase 1 runtime hardening is applied here so the deployed entry point has one
freshness rule even before the larger source refactor: <=60m FRESH, >60m STALE.
Phase 2 upgrades the dashboard History view into a complete filtered trade
ledger before main.py starts.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def _apply_phase1_fixes(base: str) -> None:
    """Apply Phase 1 invariants to the deployed runtime sources, idempotently."""
    main_path = Path(base) / "main.py"
    s = main_path.read_text(encoding="utf-8")

    s = s.replace(
        "MAX_SIGNAL_AGE_HOURS = 6  # Strictly 6 hours maximum limit",
        "MAX_SIGNAL_AGE_HOURS = 1  # Authoritative freshness window: 1 hour",
    )

    old_age = '''def get_signal_age_str(ts_ms):
    if not ts_ms:
        return "Unknown", "⚠️ STALE"
    now_ms = int(time.time() * 1000)
    diff_ms = now_ms - ts_ms
    diff_min = int(diff_ms / 60000)
    diff_hr = int(diff_min / 60)
    if diff_min < 60:
        age_str = f"{diff_min} min ago"
        tag = "✅ FRESH" if diff_min <= 60 else "⚠️ STALE"
    else:
        age_str = f"{diff_hr} hr {diff_min % 60} min ago"
        tag = "✅ FRESH" if diff_hr < 2 else "⚠️ STALE"
    return age_str, tag
'''
    new_age = '''def get_signal_age_str(ts_ms):
    """Authoritative rule: <=60 minutes is FRESH; >60 minutes is STALE."""
    if not ts_ms:
        return "Unknown", "⚠️ STALE"
    now_ms = int(time.time() * 1000)
    diff_ms = max(0, now_ms - int(ts_ms))
    diff_min = int(diff_ms / 60000)
    if diff_min <= 60:
        return f"{diff_min} min ago", "✅ FRESH"
    diff_hr = diff_min // 60
    return f"{diff_hr} hr {diff_min % 60} min ago", "⚠️ STALE"
'''
    if old_age in s:
        s = s.replace(old_age, new_age)

    if "def send_startup_notice_once(message: str, **kwargs):" not in s:
        marker = "def send_to_personal_only(message: str, **kwargs):\n"
        helper = '''STARTUP_NOTICE_FILE = "/tmp/workspace/startup_notice_state.json"
STARTUP_NOTICE_DEDUPE_S = 15 * 60


def send_startup_notice_once(message: str, **kwargs):
    """Suppress duplicate startup notices during rapid restarts/redeploys."""
    now = time.time()
    try:
        state = load_json(STARTUP_NOTICE_FILE, {"last_sent_ts": 0})
        last = float(state.get("last_sent_ts", 0) or 0) if isinstance(state, dict) else 0.0
        if now - last < STARTUP_NOTICE_DEDUPE_S:
            print(f"[STARTUP] Duplicate startup notice suppressed ({int(now - last)}s since last)")
            return False
        save_json(STARTUP_NOTICE_FILE, {"last_sent_ts": now})
    except Exception as e:
        print(f"[STARTUP] Dedupe state unavailable: {e}")
    send_to_personal_only(message, **kwargs)
    return True

'''
        if marker not in s:
            raise RuntimeError("Phase 1: startup insertion point not found in main.py")
        s = s.replace(marker, helper + marker, 1)

    s = s.replace(
        '    send_to_personal_only(start_msg, parse_mode="Markdown")',
        '    send_startup_notice_once(start_msg, parse_mode="Markdown")',
        1,
    )
    main_path.write_text(s, encoding="utf-8")

    dashboard_api_path = Path(base) / "dashboard_api.py"
    d = dashboard_api_path.read_text(encoding="utf-8")
    old_dashboard_age = '''        age_ms = time.time() * 1000 - ts_ms
        age_hr = age_ms / 3600000
        if age_hr < 1:
            tag = "🔥 FRESH"
        elif age_hr > 4:
            tag = "⚠️ STALE"
        else:
            tag = ""
'''
    new_dashboard_age = '''        age_ms = max(0, time.time() * 1000 - ts_ms)
        age_hr = age_ms / 3600000
        tag = "🔥 FRESH" if age_hr <= 1 else "⚠️ STALE"
'''
    if old_dashboard_age in d:
        d = d.replace(old_dashboard_age, new_dashboard_age, 1)
    dashboard_api_path.write_text(d, encoding="utf-8")

    # Mobile: use only the fixed bottom navigation. The desktop/top nav is hidden.
    html_path = Path(base) / "dashboard" / "index.html"
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        mobile_marker = "@media(max-width:820px){body{padding-bottom:"
        if "@media(max-width:820px){.nav{display:none}" not in html and mobile_marker in html:
            html = html.replace(
                mobile_marker,
                "@media(max-width:820px){.nav{display:none}body{padding-bottom:",
                1,
            )
            html_path.write_text(html, encoding="utf-8")


def _apply_phase2_fixes(base: str) -> None:
    """Apply the Phase 2 History ledger migration before the bot starts."""
    from phase2_history import apply as apply_phase2_history
    apply_phase2_history(base)


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    _apply_phase1_fixes(base)
    _apply_phase2_fixes(base)
    main_file = os.path.join(base, "main.py")
    sys.argv = [main_file, *sys.argv[1:]]
    with open(main_file, "rb") as f:
        code = compile(f.read(), main_file, "exec")
    exec(code, globals(), globals())
