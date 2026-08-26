import unittest

from backtest import BacktestEngine


class Phase6BacktestReportingTests(unittest.TestCase):
    def test_trade_count_is_scalar_and_details_are_preserved(self):
        engine = BacktestEngine(starting_balance=100000)
        trades = [
            {"type": "LONG", "entry": 100.0, "exit": 102.0, "pnl": 200.0, "result": "WIN"},
            {"type": "SHORT", "entry": 100.0, "exit": 101.0, "pnl": -100.0, "result": "LOSS"},
        ]

        metrics = engine._compute_metrics(trades, 100100.0)

        self.assertEqual(metrics["trades"], 2)
        self.assertIsInstance(metrics["trades"], int)
        self.assertEqual(metrics["trade_details"], trades)
        self.assertEqual(metrics["total_trades"], 2)

    def test_empty_result_has_scalar_trade_count(self):
        engine = BacktestEngine(starting_balance=100000)
        metrics = engine._compute_metrics([], 100000.0)

        self.assertEqual(metrics["trades"], 0)
        self.assertIsInstance(metrics["trades"], int)
        self.assertEqual(metrics["trade_details"], []) if "trade_details" in metrics else None

    def test_index_aliases_remain_supported(self):
        engine = BacktestEngine()
        self.assertEqual(engine._resolve_symbol("NIFTY 50"), "^NSEI")
        self.assertEqual(engine._resolve_symbol("BANK NIFTY"), "^NSEBANK")


if __name__ == "__main__":
    unittest.main()
