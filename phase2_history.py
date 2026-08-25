"""Phase 2 dashboard History migration.

This module is executed on every production startup by run_bot.py.  It must be
idempotent and must tolerate later dashboard phases changing the HTML.  Phase 3
already contains the completed History UI, so Phase 2 should recognize that UI
instead of trying to patch the old HTML a second time.
"""
from __future__ import annotations

import os
from pathlib import Path

MARKER = "data-phase2-history=1"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one known legacy anchor, with a useful error if truly missing."""
    if old not in text:
        raise RuntimeError(f"Phase 2: {label} insertion point not found")
    return text.replace(old, new, 1)


def _history_ui_is_already_modern(html: str) -> bool:
    """Return True for the Phase 2/3 History implementation already in index.html."""
    # Phase 3's History page uses the full ledger/filter implementation.  Do not
    # depend on one exact sentence because later visual phases may change copy.
    signatures = (
        'id="historySearch"',
        'id="historyResultFilter"',
        'id="historyStrategyFilter"',
        'class="filters"',
        "Full trade ledger",
        "function exactTime(v)",
    )
    return sum(signature in html for signature in signatures) >= 2


def _patch_dashboard_api(dashboard_api: Path) -> None:
    d = dashboard_api.read_text(encoding="utf-8")

    # Keep the larger history payload when this legacy Phase 2 anchor still
    # exists.  If a later phase already changed it, simply leave it alone.
    old_limit = 'last_history = sorted(history, key=lambda x: str(x.get("closed_at", "")), reverse=True)[:15]'
    new_limit = 'last_history = sorted(history, key=lambda x: str(x.get("closed_at", x.get("close_time", ""))), reverse=True)[:500]'
    if old_limit in d:
        d = d.replace(old_limit, new_limit, 1)

    old_meta = '"history": last_history, "history_total": len(history),'
    new_meta = '"history": last_history, "history_total": len(history), "history_limit": 500,'
    if old_meta in d and '"history_limit": 500' not in d:
        d = d.replace(old_meta, new_meta, 1)

    dashboard_api.write_text(d, encoding="utf-8")


def apply(base: str) -> None:
    root = Path(base)
    dashboard_api = root / "dashboard_api.py"
    html_path = root / "dashboard" / "index.html"

    if dashboard_api.exists():
        _patch_dashboard_api(dashboard_api)

    if not html_path.exists():
        return

    html = html_path.read_text(encoding="utf-8")

    # Already migrated by an earlier startup.
    if MARKER in html:
        return

    # Phase 3 replaced the original History markup.  The old Phase 2 patch was
    # matching that original markup literally, so it crashed here after Phase 3
    # changed the page.  Treat the newer implementation as already migrated.
    if _history_ui_is_already_modern(html):
        html = html.replace(
            "</body>",
            '<span ' + MARKER + ' hidden></span>\n</body>',
            1,
        )
        html_path.write_text(html, encoding="utf-8")
        return

    # Legacy dashboard support.  These anchors are intentionally conservative;
    # if the dashboard is neither the known legacy version nor the modern one,
    # fail with a clear message rather than partially corrupting the HTML.
    legacy_head = '<div class="section-head"><div><h2>🕘 History</h2><div class="sub">Short records · no raw timestamps</div></div></div><div id="historySummary" class="history-summary"></div>'
    if legacy_head in html:
        history_html = '''<div id="historyToolbar" class="history-toolbar">
  <input id="historySearch" type="search" placeholder="Search symbol, account, strategy…" autocomplete="off">
  <select id="historyResultFilter"><option value="ALL">All results</option><option value="WIN">Wins</option><option value="LOSS">Losses</option></select>
  <select id="historyStrategyFilter"><option value="ALL">All strategies</option></select>
  <button id="historyClear" class="control small clear-history" type="button">Clear filters</button>
</div>
<div id="historyCount" class="history-count">Showing all completed trades</div>'''
        html = _replace_once(
            html,
            legacy_head,
            '<div class="section-head"><div><h2>🕘 History</h2><div class="sub">Full trade ledger · exact timestamps · filters</div></div></div><div id="historySummary" class="history-summary"></div>' + history_html,
            "history toolbar",
        )
        html = html.replace('</body>', '<span ' + MARKER + ' hidden></span>\n</body>', 1)
        html_path.write_text(encoding="utf-8", errors="strict")
        return

    raise RuntimeError(
        "Phase 2: dashboard History markup is neither the legacy template nor "
        "the modern Phase 3 template; refusing to patch blindly"
    )


if __name__ == "__main__":
    apply(os.path.dirname(os.path.abspath(__file__)))
