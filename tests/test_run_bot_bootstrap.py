from pathlib import Path


def test_production_entrypoint_installs_sweep_runtime_before_startup():
    source = Path("run_bot.py").read_text(encoding="utf-8")
    marker = 'if __name__ == "__main__":'
    bootstrap = "import sweep_runtime as _sweep_runtime"
    assert bootstrap in source
    assert source.index(bootstrap) < source.index(marker)
    assert "_sweep_runtime.install(sys.modules[__name__])" in source


def test_startup_filter_no_longer_advertises_six_hour_sweep_stale_rule():
    source = Path("run_bot.py").read_text(encoding="utf-8")
    assert "Sweep alerts older than 1h" in source
    assert "Stale signals older than {MAX_SIGNAL_AGE_HOURS}h" in source
