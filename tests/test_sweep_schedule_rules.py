from datetime import datetime
from zoneinfo import ZoneInfo

import sweep_engine

IST = ZoneInfo("Asia/Kolkata")


def test_expected_close_schedule_matches_rules():
    assert sweep_engine._expected_close_schedule("^NSEI") == ({10, 11, 12, 13, 14, 15}, 15)
    assert sweep_engine._expected_close_schedule("^NSEBANK") == ({10, 11, 12, 13, 14, 15}, 15)
    assert sweep_engine._expected_close_schedule("RELIANCE.NS") == ({13, 15}, 15)
    assert sweep_engine._expected_close_schedule("BTC-USD") == ({1, 5, 9, 13, 17, 21}, 30)
    assert sweep_engine._expected_close_schedule("GC=F") == ({2, 6, 10, 14, 18, 22}, 30)
    assert sweep_engine._expected_close_schedule("EURUSD=X") == ({2, 6, 10, 14, 18, 22}, 30)


def test_fx_gold_latest_closed_boundary_is_not_future():
    now = sweep_engine.IST.localize(datetime(2026, 8, 27, 13, 7))
    latest = sweep_engine._fx_or_gold_expected_start(now)
    assert latest == sweep_engine.IST.localize(datetime(2026, 8, 27, 10, 30))
    assert latest <= now
