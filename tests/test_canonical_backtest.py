import unittest
from datetime import datetime

import pandas as pd
import pytz

from canonical_backtest import iter_sweep_signals
from sweep_engine import detect_sweep


IST = pytz.timezone("Asia/Kolkata")


class CanonicalBacktestTests(unittest.TestCase):
    def test_empty_history_has_no_signals(self):
        self.assertEqual(iter_sweep_signals(pd.DataFrame(), "^NSEI"), [])

    def test_runner_delegates_signal_generation_to_canonical_engine(self):
        idx = pd.date_range(
            start="2026-08-28 09:15",
            periods=8,
            freq="1h",
            tz="Asia/Kolkata",
        )
        df = pd.DataFrame(
            {
                "Open": [100, 101, 102, 103, 104, 105, 106, 107],
                "High": [102, 103, 104, 105, 106, 107, 108, 109],
                "Low": [99, 100, 101, 102, 103, 104, 105, 106],
                "Close": [101, 102, 103, 104, 105, 106, 107, 108],
                "Volume": [1] * 8,
            },
            index=idx,
        )
        expected = []
        for t in idx:
            result = detect_sweep(df, "^NSEI", t + pd.Timedelta(hours=1))
            if result is not None:
                expected.append((result.candle_start, result.candle_end, result.direction))
        actual = [(r.candle_start, r.candle_end, r.direction) for r in iter_sweep_signals(df, "^NSEI")]
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
