"""Runtime compatibility fixes loaded automatically by Python startup.

This file contains small, isolated compatibility patches that keep provider
aliases and the dashboard/backtest response contract stable without changing
live trading strategy logic.
"""

try:
    from backtest import BacktestEngine

    _original_resolve_symbol = BacktestEngine._resolve_symbol
    _original_compute_metrics = BacktestEngine._compute_metrics
    _original_fetch_binance_klines = BacktestEngine._fetch_binance_klines

    def _resolve_symbol(self, symbol):
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
        return _original_resolve_symbol(self, symbol)

    def _compute_metrics(self, trades, final_balance):
        """Keep the dashboard contract JSON-friendly and backward-compatible.

        Older backtest responses exposed the full trade list as ``metrics.trades``.
        The dashboard displays that field as a scalar trade count, which caused
        JavaScript to render Python/JSON objects as ``[object Object]``.
        Preserve the detailed records under ``trade_details`` and expose the
        count as ``trades``.
        """
        result = _original_compute_metrics(self, trades, final_balance)
        if isinstance(result, dict):
            details = result.get("trades")
            if isinstance(details, list):
                result["trade_details"] = details
                result["trades"] = len(details)
            elif "trades" not in result:
                result["trades"] = int(result.get("total_trades", 0) or 0)
        return result

    def _fetch_binance_klines(self, symbol="BTCUSDT", days=30):
        """Retry the legacy Binance helper with its intended 1h interval.

        The previous implementation referenced an undefined local ``interval``
        variable, causing the fallback path to fail before the HTTP request.
        """
        try:
            limit = min(days * 24, 1000)
            import requests
            import pandas as pd

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
            return _original_fetch_binance_klines(self, symbol=symbol, days=days)

    BacktestEngine._resolve_symbol = _resolve_symbol
    BacktestEngine._compute_metrics = _compute_metrics
    BacktestEngine._fetch_binance_klines = _fetch_binance_klines
    print("[BACKTEST PATCH] aliases, reporting contract and Binance fallback enabled")
except Exception as exc:
    # Never prevent the bot from starting because of this compatibility layer.
    print(f"[BACKTEST PATCH] unavailable: {exc}")
