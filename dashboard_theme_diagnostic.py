"""Temporary Phase 1 theme diagnostic.

This file is intentionally standalone. It can be imported by the dashboard API
without changing trading/backtest logic. It exposes a small JSON payload describing
the deployed dashboard source and the theme implementation we expect to serve.
"""
from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "dashboard" / "index.html"


def diagnostic_payload():
    text = HTML.read_text(encoding="utf-8") if HTML.exists() else ""
    return {
        "phase": "phase1-theme-diagnostic",
        "source_exists": HTML.exists(),
        "source_sha256": hashlib.sha256(text.encode()).hexdigest() if text else None,
        "theme_button": bool(re.search(r'id=[\"\']themeBtn[\"\']', text)),
        "theme_popup": bool(re.search(r'id=[\"\']themePop[\"\']', text)),
        "theme_choices": len(re.findall(r'class=[\"\'][^\"\']*theme-choice', text)),
        "light_theme": "data-theme=\"light\"" in text or "data-theme='light'" in text,
        "dark_theme": "data-theme=\"dark\"" in text or "data-theme='dark'" in text,
        "local_storage": "mavis-theme" in text,
        "apply_prefs": "function applyPrefs" in text,
        "theme_click_handler": bool(re.search(r'themeBtn.*click', text, re.S)),
    }
