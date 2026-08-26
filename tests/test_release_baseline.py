from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "index.html"
API = ROOT / "dashboard_api.py"


def test_approved_theme_and_mobile_contract_is_present():
    html = TEMPLATE.read_text(encoding="utf-8")

    for label in (
        "Modern Light",
        "Modern Dark",
        "Neo-Brutalist Light",
        "Neo-Brutalist Dark",
    ):
        assert label in html

    assert 'data-style="modern"' in html
    assert 'data-style="neo"' in html
    assert 'data-theme="light"' in html
    assert 'data-theme="dark"' in html
    assert 'data-accent' in html

    # One canonical navigation with the six approved sections.
    assert html.count('id="nav"') == 1
    for page in ("overview", "trades", "signals", "history", "news", "tools"):
        assert f'data-page="{page}"' in html

    assert "prefers-reduced-motion:reduce" in html
    assert "overflow-x:hidden" in html


def test_news_contract_is_date_first_not_impact_first():
    html = TEMPLATE.read_text(encoding="utf-8")

    # Date grouping and per-event presentation are part of the approved UI.
    assert "news-date" in html
    assert "news-item" in html
    assert "news_raw" in html

    # Impact must remain a card-level visual/status field, not the feed hierarchy.
    assert "impact" in html


def test_dashboard_api_has_no_runtime_html_injection():
    api = API.read_text(encoding="utf-8")
    assert 'replace("</body>"' not in api
    assert "renderSignals" not in api
    assert "inject" not in api.lower()


def test_trading_engine_is_not_imported_by_dashboard_template():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "sweep_engine" not in html
    assert "sweep_runtime" not in html
    assert "paper_trade" not in html
