"""Runtime compatibility fixes loaded automatically by Python startup.

This file intentionally contains only safe compatibility aliases. The dashboard
uses human-readable instrument names while the historical data provider expects
provider-specific tickers.
"""

try:
    from backtest import BacktestEngine

    _original_resolve_symbol = BacktestEngine._resolve_symbol

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

    BacktestEngine._resolve_symbol = _resolve_symbol
    print("[BACKTEST PATCH] index aliases enabled")
except Exception as exc:
    # Never prevent the bot from starting because of this compatibility layer.
    print(f"[BACKTEST PATCH] unavailable: {exc}")
