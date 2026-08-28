import unittest
from datetime import datetime
import pandas as pd
import pytz

from sweep_engine import detect_sweep, build_closed_candles

IST = pytz.timezone("Asia/Kolkata")


class SweepEngineTests(unittest.TestCase):
    def _fx(self, highs, lows, closes, start="02:30"):
        base = IST.localize(datetime(2026, 8, 25, int(start[:2]), int(start[3:])))
        idx = [base + pd.Timedelta(hours=i) for i in range(len(highs))]
        return pd.DataFrame({"Open": closes, "High": highs, "Low": lows, "Close": closes}, index=idx)

    def _nifty(self, candles):
        """Build one provider bar at each approved NSE strategy-candle start."""
        starts = [IST.localize(datetime(2026, 8, 28, 9 + i, 15)) for i in range(len(candles))]
        return pd.DataFrame(candles, index=starts, columns=["Open", "High", "Low", "Close"])

    def _now(self, hour, minute):
        return IST.localize(datetime(2026, 8, 25, hour, minute))

    def _nifty_now(self, hour, minute):
        return IST.localize(datetime(2026, 8, 28, hour, minute))

    def test_both_sides_and_inside_is_neutral(self):
        df = self._fx([100, 101, 102, 103, 104, 105, 110, 90, 100, 100], [95, 96, 97, 96, 95, 94, 90, 90, 96, 100], [98, 99, 100, 99, 98, 97, 100, 100, 100, 100])
        r = detect_sweep(df, "EURUSD=X", self._now(11, 0))
        self.assertIsNotNone(r)
        self.assertEqual(r.direction, "NEUTRAL")

    def test_touch_does_not_sweep(self):
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
        df = self._fx([100,101,102,103,104,105,110], [95,96,97,96,95,94,90], [98,99,100,99,98,97,100])
        r = detect_sweep(df, "GC=F", self._now(5, 30))
        self.assertIsNone(r)

    def test_nifty_one_sided_high_break_is_not_a_sweep(self):
        # Exact regression from the observed bad NIFTY message:
        # previous H/L = 24133.60 / 24090.85
        # current  H/L = 24167.85 / 24107.10 -> high swept, low NOT swept.
        df = self._nifty([
            (24133.60, 24133.60, 24090.85, 24090.85),
            (24120.00, 24167.85, 24107.10, 24140.00),
        ])
        r = detect_sweep(df, "^NSEI", self._nifty_now(11, 15))
        self.assertIsNone(r)

    def test_nifty_both_sides_swept_and_close_inside_is_neutral(self):
        df = self._nifty([
            (24100.00, 24133.60, 24090.85, 24110.00),
            (24110.00, 24167.85, 24080.00, 24120.00),
        ])
        r = detect_sweep(df, "^NSEI", self._nifty_now(11, 15))
        self.assertIsNotNone(r)
        self.assertEqual(r.timeframe, "1H")
        self.assertEqual(r.candle_start.strftime("%H:%M"), "10:15")
        self.assertEqual(r.candle_end.strftime("%H:%M"), "11:15")
        self.assertTrue(r.high_swept)
        self.assertTrue(r.low_swept)
        self.assertEqual(r.direction, "NEUTRAL")

    def test_nifty_session_boundaries_are_exact_and_no_1515_to_1615_bar(self):
        df = self._nifty([
            (100, 110, 90, 100),
            (100, 111, 89, 100),
            (100, 112, 88, 100),
            (100, 113, 87, 100),
            (100, 114, 86, 100),
            (100, 115, 85, 100),
        ])
        bars, tf, warning = build_closed_candles(df, "^NSEI", self._nifty_now(16, 0))
        self.assertEqual(tf, "1H")
        self.assertIsNone(warning)
        self.assertEqual([x.strftime("%H:%M") for x in bars.index], ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15"])
        self.assertNotIn("15:15", [x.strftime("%H:%M") for x in bars.index])

    def test_nifty_open_1015_candle_is_not_used_before_1115(self):
        df = self._nifty([
            (100, 110, 90, 100),
            (100, 120, 80, 110),
        ])
        r = detect_sweep(df, "^NSEI", self._nifty_now(10, 59))
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
