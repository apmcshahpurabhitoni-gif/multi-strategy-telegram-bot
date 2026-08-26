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
