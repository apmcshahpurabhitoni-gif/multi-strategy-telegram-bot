from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow_texts():
    return [p.read_text(encoding="utf-8") for p in WORKFLOWS.glob("*.yml")]


def test_all_workflows_are_read_only():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "contents: write" not in text, f"write permission in {path}"
        assert "git push" not in text, f"workflow can push source: {path}"
        assert "git commit" not in text, f"workflow can commit source: {path}"


def test_required_workflows_declare_read_only_permissions():
    for name in ("dashboard-smoke.yml", "phase10-production.yml", "sweep-tests.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "permissions:" in text
        assert "contents: read" in text


def test_render_production_contract_is_declarative():
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "branch: main" in text
    assert "healthCheckPath: /ping" in text
    assert "sync: false" in text
    assert "TELEGRAM_BOT_TOKEN" in text
    assert "TELEGRAM_CHAT_ID" in text
    assert "SUPABASE_URL" in text
    assert "SUPABASE_KEY" in text


def test_no_broker_ordering_is_introduced_by_phase10_controls():
    for text in _workflow_texts():
        lowered = text.lower()
        assert "place_order" not in lowered
        assert "broker order" not in lowered


def test_phase10_spec_exists_and_preserves_non_goals():
    spec = ROOT / "docs" / "PHASE10_SOURCE_DERIVED_SPEC.md"
    text = spec.read_text(encoding="utf-8")
    assert "CI must be read-only" in text
    assert "No new trading strategy." in text
    assert "No broker order placement." in text
    assert "No changes to canonical Sweep V2 decision logic." in text
