"""Explicit compatibility layer for the production backtest API.

Unlike sitecustomize.py, this module is imported deliberately by the production
entry point. That makes the reporting contract deterministic on Render and in
unit tests.
"""

from __future__ import annotations

from typing import Any


def apply_backtest_compat(BacktestEngine: Any) -> None:
    """Normalize backtest reporting and repair the Binance fallback path."""
    if getattr(BacktestEngine, "_phase6_compat_applied", False):
        return

    original_compute_metrics = BacktestEngine._compute_metrics
    original_fetch_binance_klines = BacktestEngine._fetch_binance_klines
    original_resolve_symbol = BacktestEngine._resolve_symbol

    def resolve_symbol(self, symbol):
        s = str(symbol or "").strip().upper()
        aliases = {
            "NIFTY 50": "^NSEI",
            "NIFTY50": "^NSEI",
            "NIFTY": "^NSEI",
            "BANK NIFTY": "^NSEBANK",
            "BANKNIFTY": "^NSEBANK",
        }
        if s in aliases:
            return aliases[s]
        return original_resolve_symbol(self, symbol)

    def compute_metrics(self, trades, final_balance):
        result = original_compute_metrics(self, trades, final_balance)
        if not isinstance(result, dict):
            return result

        details = result.get("trades")
        if isinstance(details, list):
            result["trade_details"] = details
            result["trades"] = len(details)
        elif "trades" not in result:
            result["trades"] = int(result.get("total_trades", 0) or 0)
        return result

    def fetch_binance_klines(self, symbol="BTCUSDT", days=30):
        """Use Binance's intended 1h interval when Yahoo data is unavailable."""
        try:
            import requests
            import pandas as pd

            limit = min(max(int(days), 1) * 24, 1000)
            url = (
                "https://api.binance.com/api/v3/klines"
                f"?symbol={symbol}&interval=1h&limit={limit}"
            )
            response = requests.get(url, timeout=15)
            if response.status_code != 200:
                return None

            frame = pd.DataFrame(response.json(), columns=[
                "Open time", "Open", "High", "Low", "Close", "Volume",
                "Close time", "Quote asset volume", "Number of trades",
                "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore",
            ])
            frame["Open time"] = pd.to_datetime(frame["Open time"], unit="ms")
            frame.set_index("Open time", inplace=True)
            return frame[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        except Exception:
            return original_fetch_binance_klines(self, symbol=symbol, days=days)

    BacktestEngine._resolve_symbol = resolve_symbol
    BacktestEngine._compute_metrics = compute_metrics
    BacktestEngine._fetch_binance_klines = fetch_binance_klines
    BacktestEngine._phase6_compat_applied = True
