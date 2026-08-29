from pathlib import Path


def test_production_entrypoint_uses_explicit_sweep_runtime_bootstrap():
    source = Path("run_bot.py").read_text(encoding="utf-8")
    assert "import main as _main" in source
    assert "import sweep_runtime as _sweep_runtime" in source
    assert "_sweep_runtime.install(_main)" in source
    assert "_main.main()" in source
    assert "source.replace(" not in source
    assert "exec(code" not in source


def test_production_entrypoint_does_not_rewrite_main_source():
    source = Path("run_bot.py").read_text(encoding="utf-8")
    assert "open(main_file" not in source
    assert "compile(source" not in source
    assert "main.py as text" not in source
