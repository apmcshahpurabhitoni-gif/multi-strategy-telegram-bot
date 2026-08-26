from pathlib import Path


def test_phase5_human_readable_dates_and_today_label_are_present():
    html = Path("templates/index.html").read_text(encoding="utf-8")
    assert 'function dateLabel(' in html
    assert 'return"Today"' in html
    assert 'return"Yesterday"' in html
    assert 'month:"short"' in html
    assert 'function dateTimeLabel(' in html
    assert 'Asia/Kolkata' in html


def test_phase5_news_impact_is_visually_encoded():
    html = Path("templates/index.html").read_text(encoding="utf-8")
    for cls in ("impact-high", "impact-medium", "impact-low"):
        assert cls in html
    for color in ("--impact-high:#dc2626", "--impact-medium:#f59e0b", "--impact-low:#eab308"):
        assert color in html
    assert 'var ic=impactClass(impact)' in html


def test_phase5_keeps_existing_theme_and_mobile_contract():
    html = Path("templates/index.html").read_text(encoding="utf-8")
    for label in ("Modern Light", "Modern Dark", "Neo-Brutalist Light", "Neo-Brutalist Dark"):
        assert label in html
    assert 'prefers-reduced-motion:reduce' in html
    assert 'position:fixed' in html
    assert 'data-page="news"' in html
