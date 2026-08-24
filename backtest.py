import json
import time
import os
import requests
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

matplotlib.use("Agg")

class BacktestEngine:
    def __init__(self, starting_balance: float = 100000.0, risk_per_trade: float = 0.02):
        self.starting_balance = starting_balance
        self.risk_per_trade = risk_per_trade
        self.trades: List[Dict] = []
        self.equity_curve: List[float] = []

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        hl = df["High"] - df["Low"]
        hc = np.abs(df["High"] - df["Close"].shift(1))
        lc = np.abs(df["Low"] - df["Close"].shift(1))
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, adjust=False).mean()

    def _get_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        d = df["Close"].diff()
        g = d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
        l = (-d.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
        rs = g / l.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    def _calc_macd(self, series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series]:
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return macd_line, signal_line

    def _calc_qty(self, balance: float, entry: float, sl: float) -> float:
        risk = balance * self.risk_per_trade
        dist = abs(entry - sl)
        if dist == 0 or dist < entry * 0.001:
            return 0.0
        return risk / dist

    def _safe_float(self, val: Any) -> float:
        try:
            result = float(val)
            return 0.0 if (np.isnan(result) or np.isinf(result)) else result
        except (ValueError, TypeError):
            return 0.0

    def _resolve_symbol(self, symbol: str) -> str:
        s = symbol.strip().upper()
        mapping = {
            "BTCUSD": "BTC-USD",
            "ETHUSD": "ETH-USD",
            "SOLUSD": "SOL-USD",
            "BNBUSD": "BNB-USD",
            "XRPUSD": "XRP-USD",
            "ADAUSD": "ADA-USD",
            "DOGEUSD": "DOGE-USD",
            "XAUUSD": "GC=F",
            "EURUSD": "EURUSD=X",
            "GBPUSD": "GBPUSD=X",
            "USDJPY": "USDJPY=X",
            "USDCHF": "USDCHF=X",
            "AUDUSD": "AUDUSD=X",
            "USDCAD": "USDCAD=X",
            "NZDUSD": "NZDUSD=X"
        }
        if s in mapping:
            return mapping[s]
        if s.startswith("^") or s.endswith(".NS") or "-USD" in s or "-USDT" in s or "=" in s:
            return s
        if len(s) == 6 and not any(char.isdigit() for char in s):
            return s + "=X"
        return s

    def _fetch_binance_klines(self, symbol: str = "BTCUSDT", days: int = 30) -> Optional[pd.DataFrame]:
        try:
            limit = min(days * 24, 1000)
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                return None
            df = pd.DataFrame(r.json(), columns=[
                "Open time", "Open", "High", "Low", "Close", "Volume",
                "Close time", "Quote asset volume", "Number of trades",
                "Taker buy base asset volume", "Taker buy quote asset volume", "Ignore"
            ])
            df["Open time"] = pd.to_datetime(df["Open time"], unit="ms")
            df.set_index("Open time", inplace=True)
            return df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        except Exception:
            return None

    def _download_candles(self, symbol: str, days: int) -> Optional[pd.DataFrame]:
        yf_symbol = self._resolve_symbol(symbol)
        safe_days = max(7, min(days + 30, 720))
        end = datetime.now()
        start = end - timedelta(days=safe_days)

        try:
            df = yf.download(
                yf_symbol,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1h",
                progress=False,
                auto_adjust=True,
                threads=False
            )
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                if len(df) >= 30:
                    return df
        except Exception as e:
            print(f"[BACKTEST DATA] yfinance download error for {yf_symbol}: {e}")

        if "BTC" in yf_symbol:
            df_binance = self._fetch_binance_klines("BTCUSDT", days=safe_days)
            if df_binance is not None and len(df_binance) >= 30:
                return df_binance
        elif "ETH" in yf_symbol:
            df_binance = self._fetch_binance_klines("ETHUSDT", days=safe_days)
            if df_binance is not None and len(df_binance) >= 30:
                return df_binance

        return None

    def _simulate_trade(self, entry: float, sl: float, tp: float, qty: float, direction: str, df_outcome: pd.DataFrame, max_bars: int = 100) -> Tuple[float, str, float]:
        if len(df_outcome) == 0:
            return 0.0, "BREAKEVEN", entry
        bars_to_check = min(len(df_outcome), max_bars)
        for idx in range(bars_to_check):
            high, low = self._safe_float(df_outcome.iloc[idx]["High"]), self._safe_float(df_outcome.iloc[idx]["Low"])
            if direction == "LONG":
                if high >= tp: return (tp - entry) * qty, "WIN", tp
                if low <= sl: return (sl - entry) * qty, "LOSS", sl
            else:
                if low <= tp: return (entry - tp) * qty, "WIN", tp
                if high >= sl: return (entry - sl) * qty, "LOSS", sl
        last_price = self._safe_float(df_outcome.iloc[bars_to_check - 1]["Close"])
        pnl = (last_price - entry) * qty if direction == "LONG" else (entry - last_price) * qty
        return pnl, "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN"), last_price

    def backtest_trendpulse(self, symbol: str, days: int = 30) -> Dict[str, Any]:
        print(f"[BACKTEST] TrendPulse on {symbol} for {days} days...")
        df_1h = self._download_candles(symbol, days)
        if df_1h is None or len(df_1h) < 50:
            return {"error": f"Insufficient historical data available for {symbol}."}

        df_4h = df_1h.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        if len(df_4h) < 15:
            return {"error": "Insufficient 4H timeframe data after candle resampling."}

        df_4h["EMA50"], df_4h["ATR"] = df_4h["Close"].ewm(span=50, adjust=False).mean(), self._calc_atr(df_4h, 14)
        df_1h["EMA20"], df_1h["RSI"], df_1h["ATR"] = df_1h["Close"].ewm(span=20, adjust=False).mean(), self._get_rsi(df_1h, 14), self._calc_atr(df_1h, 14)
        macd_line, signal_line = self._calc_macd(df_1h["Close"])
        df_1h["MACD"], df_1h["MACD_SIGNAL"] = macd_line, signal_line

        balance = self.starting_balance
        trades = []
        in_trade, trade_entry, trade_sl, trade_tp, trade_qty, trade_type, trade_entry_idx = False, 0.0, 0.0, 0.0, 0.0, "", 0

        for i in range(50, len(df_1h) - 1):
            if in_trade:
                high, low, close = self._safe_float(df_1h.iloc[i]["High"]), self._safe_float(df_1h.iloc[i]["Low"]), self._safe_float(df_1h.iloc[i]["Close"])
                exit_triggered, exit_price, pnl, result, exit_reason = False, 0.0, 0.0, "", ""

                if trade_type == "LONG":
                    if high >= trade_tp: exit_price, pnl, result, exit_reason, exit_triggered = trade_tp, (trade_tp - trade_entry) * trade_qty, "WIN", "TP", True
                    elif low <= trade_sl: exit_price, pnl, result, exit_reason, exit_triggered = trade_sl, (trade_sl - trade_entry) * trade_qty, "LOSS", "SL", True
                else:
                    if low <= trade_tp: exit_price, pnl, result, exit_reason, exit_triggered = trade_tp, (trade_entry - trade_tp) * trade_qty, "WIN", "TP", True
                    elif high >= trade_sl: exit_price, pnl, result, exit_reason, exit_triggered = trade_sl, (trade_entry - trade_sl) * trade_qty, "LOSS", "SL", True

                if not exit_triggered:
                    mc, sc, mp, sp = self._safe_float(df_1h["MACD"].iloc[i]), self._safe_float(df_1h["MACD_SIGNAL"].iloc[i]), self._safe_float(df_1h["MACD"].iloc[i-1]), self._safe_float(df_1h["MACD_SIGNAL"].iloc[i-1])
                    if trade_type == "LONG" and mp >= sp and mc < sc: exit_price, pnl, result, exit_reason, exit_triggered = close, (close - trade_entry) * trade_qty, "WIN" if (close - trade_entry) * trade_qty > 0 else "LOSS", "MACD", True
                    elif trade_type == "SHORT" and mp <= sp and mc > sc: exit_price, pnl, result, exit_reason, exit_triggered = close, (trade_entry - close) * trade_qty, "WIN" if (trade_entry - close) * trade_qty > 0 else "LOSS", "MACD", True

                if not exit_triggered and (i - trade_entry_idx) >= 48:
                    pnl = (close - trade_entry) * trade_qty if trade_type == "LONG" else (trade_entry - close) * trade_qty
                    exit_price, result, exit_reason, exit_triggered = close, "WIN" if pnl > 0 else "LOSS", "TIMEOUT", True

                if exit_triggered:
                    balance += pnl
                    trades.append({"type": trade_type, "entry": trade_entry, "exit": exit_price, "pnl": pnl, "result": result, "bars_held": i - trade_entry_idx, "exit_reason": exit_reason})
                    in_trade = False

            if not in_trade:
                aligned_4h = df_4h[df_4h.index <= df_1h.index[i]]
                if len(aligned_4h) < 2:
                    continue
                htf_close, htf_ema50, htf_atr = self._safe_float(aligned_4h["Close"].iloc[-2]), self._safe_float(aligned_4h["EMA50"].iloc[-2]), self._safe_float(aligned_4h["ATR"].iloc[-2])
                atr_pct = (htf_atr / htf_close) * 100 if htf_close > 0 else 0
                if atr_pct < 0.2 or atr_pct > 10:
                    continue

                m1_close, m1_ema20, m1_rsi, m1_atr = self._safe_float(df_1h["Close"].iloc[i-1]), self._safe_float(df_1h["EMA20"].iloc[i-1]), self._safe_float(df_1h["RSI"].iloc[i-1]), self._safe_float(df_1h["ATR"].iloc[i-1])
                mc, mp, sc, sp = self._safe_float(df_1h["MACD"].iloc[i-1]), self._safe_float(df_1h["MACD"].iloc[i-2]), self._safe_float(df_1h["MACD_SIGNAL"].iloc[i-1]), self._safe_float(df_1h["MACD_SIGNAL"].iloc[i-2])

                if htf_close > htf_ema50 and mp <= sp and mc > sc and 50 < m1_rsi < 80 and m1_close > m1_ema20:
                    sl = m1_close - m1_atr * 1.5
                    tp = m1_close + m1_atr * 3.0
                    qty = self._calc_qty(balance, m1_close, sl)
                    if qty > 0: in_trade, trade_entry, trade_sl, trade_tp, trade_qty, trade_type, trade_entry_idx = True, m1_close, sl, tp, qty, "LONG", i
                elif htf_close < htf_ema50 and mp >= sp and mc < sc and 20 < m1_rsi < 50 and m1_close < m1_ema20:
                    sl = m1_close + m1_atr * 1.5
                    tp = m1_close - m1_atr * 3.0
                    qty = self._calc_qty(balance, m1_close, sl)
                    if qty > 0: in_trade, trade_entry, trade_sl, trade_tp, trade_qty, trade_type, trade_entry_idx = True, m1_close, sl, tp, qty, "SHORT", i
        return self._compute_metrics(trades, balance)

    def backtest_sweep(self, symbol: str, days: int = 30) -> Dict[str, Any]:
        print(f"[BACKTEST] 4H Sweep (immediate entry) on {symbol} for {days} days...")
        df_1h = self._download_candles(symbol, days)
        if df_1h is None or len(df_1h) < 50:
            return {"error": f"Insufficient historical data available for {symbol}."}

        df_4h = df_1h.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        if len(df_4h) < 10:
            return {"error": "Insufficient 4H timeframe data after candle resampling."}

        balance, trades = self.starting_balance, []
        for i in range(5, len(df_4h) - 1):
            c, m = df_4h.iloc[i-1], df_4h.iloc[i-2]

            # Directional Sweep Conditions
            direction = None
            if c["Low"] < m["Low"] and c["High"] <= m["High"] and c["Close"] > m["Low"]:
                direction = "BULLISH"
            elif c["High"] > m["High"] and c["Low"] >= m["Low"] and c["Close"] < m["High"]:
                direction = "BEARISH"

            if not direction:
                continue

            sweep_high, sweep_low = float(c["High"]), float(c["Low"])

            # Immediate entry: first 1H bar after the sweep candle closed.
            df_after_1h = df_1h[df_1h.index > df_4h.index[i-1]]
            if len(df_after_1h) < 2:
                continue
            entry_price = self._safe_float(df_after_1h.iloc[0]["Open"])

            if direction == "BULLISH":
                sl_price = sweep_low * 0.999
                risk = abs(entry_price - sl_price)
                if risk <= 0:
                    continue
                qty = self._calc_qty(balance, entry_price, sl_price)
                if qty <= 0:
                    continue
                pnl, result, exit_price = self._simulate_trade(entry_price, sl_price, entry_price + risk * 2.0, qty, "LONG", df_after_1h.iloc[1:])
                balance += pnl
                trades.append({"type": "LONG", "entry": entry_price, "exit": exit_price, "pnl": pnl, "result": result, "exit_reason": "TP" if result == "WIN" else "SL"})
            else:
                sl_price = sweep_high * 1.001
                risk = abs(sl_price - entry_price)
                if risk <= 0:
                    continue
                qty = self._calc_qty(balance, entry_price, sl_price)
                if qty <= 0:
                    continue
                pnl, result, exit_price = self._simulate_trade(entry_price, sl_price, entry_price - risk * 2.0, qty, "SHORT", df_after_1h.iloc[1:])
                balance += pnl
                trades.append({"type": "SHORT", "entry": entry_price, "exit": exit_price, "pnl": pnl, "result": result, "exit_reason": "TP" if result == "WIN" else "SL"})

        return self._compute_metrics(trades, balance)

    def _compute_metrics(self, trades: List[Dict], final_balance: float) -> Dict[str, Any]:
        if not trades:
            return {"total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "profit_factor": 0, "total_pnl": 0, "final_balance": final_balance, "max_drawdown_pct": 0, "sharpe": 0, "avg_trade": 0, "avg_win": 0, "avg_loss": 0, "trades": [], "return_pct": 0, "equity_points": []}
        wins, losses = [t for t in trades if t["result"] == "WIN"], [t for t in trades if t["result"] == "LOSS"]
        total_pnl, win_pnl, loss_pnl = sum(t["pnl"] for t in trades), sum(t["pnl"] for t in wins), abs(sum(t["pnl"] for t in losses))
        equity, peak, max_dd = self.starting_balance, self.starting_balance, 0.0
        equity_points = [self.starting_balance]
        for t in trades:
            equity += t["pnl"]
            equity_points.append(equity)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100)
            
        returns = [t["pnl"] for t in trades]
        sharpe = (np.mean(returns) / np.std(returns) * np.sqrt(252)) if len(returns) > 1 and np.std(returns) > 0 else 0.0
        
        try:
            os.makedirs("/tmp/workspace", exist_ok=True)
            color = "green" if equity_points[-1] >= self.starting_balance else "red"
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.fill_between(range(len(equity_points)), equity_points, color=color, alpha=0.3)
            ax.plot(equity_points, color=color, linewidth=1.5)
            ax.set_title(f"Equity Curve: {self.starting_balance} -> {equity_points[-1]:.2f}")
            ax.grid(alpha=0.2)
            plt.savefig("/tmp/workspace/backtest_chart.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
        except Exception as e:
            print(f"[WARN] Failed to generate backtest chart: {e}")
            
        return {"total_trades": len(trades), "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / len(trades) * 100, "profit_factor": round(win_pnl / loss_pnl, 2) if loss_pnl > 0 else 999.99, "total_pnl": round(total_pnl, 2), "final_balance": round(final_balance, 2), "max_drawdown_pct": round(max_dd, 2), "sharpe": round(sharpe, 2), "avg_trade": round(total_pnl / len(trades), 2), "avg_win": round(win_pnl / len(wins), 2) if wins else 0, "avg_loss": round(loss_pnl / len(losses), 2) if losses else 0, "trades": trades[:50], "return_pct": round((final_balance - self.starting_balance) / self.starting_balance * 100, 2), "equity_points": equity_points}
