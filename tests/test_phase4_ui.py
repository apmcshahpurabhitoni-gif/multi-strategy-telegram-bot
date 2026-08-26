from pathlib import Path


def test_phase4_template_has_four_theme_variants_and_presentation_rules():
    html = Path('templates/index.html').read_text(encoding='utf-8')
    for label in ('Modern Light', 'Modern Dark', 'Neo-Brutalist Light', 'Neo-Brutalist Dark'):
        assert label in html
    assert 'prefers-reduced-motion:reduce' in html
    assert 'overflow-x:hidden' in html
    assert 'mavis-style' in html and 'mavis-theme' in html and 'mavis-accent' in html
    assert 'id="balance"' in html
    assert 'id="statePill"' in html and 'id="riskPill"' in html
    assert '/api/dashboard' in html and '/api/backtest?' in html


def test_phase4_template_does_not_introduce_runtime_html_injection():
    api = Path('dashboard_api.py').read_text(encoding='utf-8')
    assert 'replace("</body>"' not in api
    assert 'renderSignals' not in api
    assert 'inject' not in api.lower()


def test_phase7_news_today_first_and_backtest_full_report_contract():
    html = Path('templates/index.html').read_text(encoding='utf-8')
    assert 'function sortDateKeys(keys)' in html
    assert 'Today first · future next · past last' in html
    assert 'function normalizeBacktest(raw)' in html
    assert 'trade_details' in html
    assert 'equity_points' in html
    assert 'function drawBacktestCurve(points)' in html
    assert 'function renderBacktestDetails(bt)' in html
    assert 'Profit Factor' in html
    assert 'Max Drawdown' in html
    assert 'Avg Win' in html and 'Avg Loss' in html
