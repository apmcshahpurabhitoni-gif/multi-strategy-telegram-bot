import unittest
from datetime import datetime

import pytz

from dashboard_api import _display_price, _display_symbol, _history_signal_fallback, _normalize_news_event


class NewsNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.ist = pytz.timezone("Asia/Kolkata")

    def test_normalizes_common_calendar_fields(self):
        item = _normalize_news_event(
            {
                "title": "Unemployment Claims",
                "country": "USD",
                "date": "2026-08-26T14:30:00+00:00",
                "impact": "Medium",
                "forecast": "220K",
                "previous": "215K",
            },
            self.ist,
        )
        self.assertEqual(item["title"], "Unemployment Claims")
        self.assertEqual(item["source"], "Economic Calendar")
        self.assertEqual(item["impact"], "MEDIUM")
        self.assertEqual(item["country"], "USD")
        self.assertEqual(item["forecast"], "220K")
        self.assertEqual(item["previous"], "215K")
        self.assertEqual(item["time"], "26-Aug 20:00 IST")
        self.assertGreater(item["ts_ms"], 0)

    def test_never_returns_blank_display_metadata(self):
        item = _normalize_news_event({"event": "Policy Meeting", "impact": "critical"}, self.ist)
        self.assertEqual(item["title"], "Policy Meeting")
        self.assertEqual(item["source"], "Economic Calendar")
        self.assertEqual(item["time"], "Time unavailable")
        self.assertEqual(item["impact"], "LOW")

    def test_ignores_non_dict_events(self):
        self.assertIsNone(_normalize_news_event("bad event", self.ist))

    def test_gold_uses_user_facing_name_everywhere(self):
        self.assertEqual(_display_symbol("GC=F"), "Gold")
        self.assertEqual(_display_symbol("XAUUSD"), "Gold")
        self.assertEqual(_display_symbol("XAU/USD"), "Gold")

    def test_other_market_symbols_use_approved_dashboard_names(self):
        self.assertEqual(_display_symbol("BTC-USD"), "Bitcoin")
        self.assertEqual(_display_symbol("^NSEI"), "NIFTY 50")
        self.assertEqual(_display_symbol("^NSEBANK"), "BANK NIFTY")

    def test_dashboard_price_display_is_compact(self):
        self.assertEqual(_display_price(4664.89990234375), 4664.9)
        self.assertEqual(_display_price("4725.090529739667"), 4725.09)

    def test_history_fallback_never_leaks_provider_symbol(self):
        history = [
            {
                "id": "gold-1",
                "symbol": "GC=F",
                "strategy": "4H Sweep",
                "direction": "BUY",
                "closed_at": "2026-08-28T10:30:00+00:00",
                "pnl": 1250.50,
            },
            {
                "id": "nifty-1",
                "symbol": "^NSEI",
                "strategy": "1H Sweep",
                "direction": "SELL",
                "closed_at": "2026-08-28T11:30:00+00:00",
                "pnl": -500.0,
            },
        ]
        rows = _history_signal_fallback(history, self.ist)
        self.assertEqual([row["sym"] for row in rows], ["NIFTY 50", "Gold"])
        self.assertNotIn("GC=F", {row["sym"] for row in rows})
        self.assertEqual(rows[0]["dir"], "SELL")
        self.assertEqual(rows[1]["dir"], "BUY")

    def test_dashboard_display_normalization_does_not_change_backend_symbol_or_price(self):
        provider_symbol = "GC=F"
        execution_price = 4664.89990234375
        self.assertEqual(provider_symbol, "GC=F")
        self.assertEqual(execution_price, 4664.89990234375)
        self.assertEqual(_display_symbol(provider_symbol), "Gold")
        self.assertEqual(_display_price(execution_price), 4664.9)


if __name__ == "__main__":
    unittest.main()
