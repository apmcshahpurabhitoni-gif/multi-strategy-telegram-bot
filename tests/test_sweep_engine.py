import unittest
from datetime import datetime
import pandas as pd
import pytz

from sweep_engine import detect_sweep

IST = pytz.timezone("Asia/Kolkata")

class SweepEngineTests(unittest.TestCase):
    def _fx(self, highs, lows, closes, start="02:30"):
        base = IST.localize(datetime(2026, 8, 25, int(start[:2]), int(start[3:])))
        idx = [base + pd.Timedelta(hours=i) for i in range(len(highs))]
        return pd.DataFrame({"Open": closes, "High": highs, "Low": lows, "Close": closes}, index=idx)

    def _now(self, hour, minute):
        return IST.localize(datetime(2026, 8, 25, hour, minute))

    def test_both_sides_and_inside_is_neutral(self):
        df = self._fx([100, 101, 102, 103, 104, 105, 110, 90, 100, 100], [95, 96, 97, 96, 95, 94, 90, 90, 96, 100], [98, 99, 100, 99, 98, 97, 100, 100, 100, 100])
        r = detect_sweep(df, "EURUSD=X", self._now(11, 0))
        self.assertIsNotNone(r)
        self.assertEqual(r.direction, "NEUTRAL")

    def test_touch_does_not_sweep(self):
        # Previous high is 103; current high touches 103 exactly but never exceeds it.
        df = self._fx([100, 101, 102, 103, 103, 103, 103, 102, 101, 101], [95, 96, 97, 96, 95, 94, 90, 90, 96, 98], [98, 99, 100, 99, 98, 97, 98, 98, 98, 98])
        r = detect_sweep(df, "EURUSD=X", self._now(11, 0))
        self.assertIsNone(r)

    def test_close_above_is_buy(self):
        df = self._fx([100,101,102,103,104,105,110,111,112,113], [95,96,97,96,95,94,90,91,92,93], [98,99,100,99,98,97,107,107,107,107])
        r = detect_sweep(df, "EURUSD=X", self._now(11, 0))
        self.assertEqual(r.direction, "BULLISH")

    def test_close_below_is_sell(self):
        df = self._fx([100,101,102,103,104,105,110,111,112,113], [95,96,97,96,95,94,90,91,92,93], [98,99,100,99,98,97,93,93,93,93])
        r = detect_sweep(df, "EURUSD=X", self._now(11, 0))
        self.assertEqual(r.direction, "BEARISH")

    def test_incomplete_candle_is_not_used(self):
        # At 05:30 IST the 02:30→06:30 candle is still open, so no signal may be returned.
        df = self._fx([100,101,102,103,104,105,110], [95,96,97,96,95,94,90], [98,99,100,99,98,97,100])
        r = detect_sweep(df, "GC=F", self._now(5, 30))
        self.assertIsNone(r)

if __name__ == "__main__":
    unittest.main()
