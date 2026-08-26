import unittest
from datetime import datetime

import pytz

from dashboard_api import _normalize_news_event


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


if __name__ == "__main__":
    unittest.main()
