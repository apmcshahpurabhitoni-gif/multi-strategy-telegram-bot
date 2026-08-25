# Mavis Trading Bot

A multi-strategy Telegram paper-trading bot with a deterministic, session-aware sweep engine, TrendPulse strategy, dashboard, backtester, and persistent virtual trading state.

> **Paper trading only.** The sweep engine is designed to be audited against TradingView before any real-money use.

## Current sweep engine (V2)

The canonical sweep rule is:

```text
Current High > Previous High
AND
Current Low  < Previous Low
```

Both conditions must be true on the **completed current candle**. A touch/equality does not count. Intracandle price path and Open are irrelevant.

Then classify using only the completed candle Close:

```text
Close > Previous High                 -> BUY
Previous Low <= Close <= Previous High -> NEUTRAL SWEEP
Close < Previous Low                  -> SELL
```

If both sides are not broken: **NO SIGNAL**.

Signals are evaluated only after the candle is closed. Every new completed candle is independently compared with the immediately previous completed candle.

### Paper trading

- BUY/SELL open a paper trade.
- Entry = current market price when the closed-candle signal is detected.
- BUY SL = sweeping candle Low.
- SELL SL = sweeping candle High.
- TP = 1:2 risk/reward.
- NEUTRAL never opens a trade.

### Telegram messages

Every sweep message contains the previous and current candle OHLC, exact candle times, swept levels, close classification, and data/source warning information.

For a qualifying candle there are at most **two messages**:

1. Initial signal.
2. `🔔 REMINDER` one hour later.

### Candle schedules

All times below are the user's TradingView display timezone (IST, UTC+5:30).

**Gold / OANDA FX reference:** 02:30, 06:30, 10:30, 14:30, 18:30, 22:30.

**BTC:** 01:30, 05:30, 09:30, 13:30, 17:30, 21:30.

**NIFTY / BANK NIFTY:** 1-hour NSE session candles anchored at 09:15: 09:15→10:15, 10:15→11:15, 11:15→12:15, 12:15→13:15, 13:15→14:15, 14:15→15:15. No synthetic 15:15→16:15 candle is created.

**15 NSE stocks:** session-based sweep bars starting at 09:15 and 13:15. The 13:15 bar ends at the actual session tail (15:15); nonexistent overnight prices are never fabricated.

## Data-source warnings

The free implementation currently uses the repository's existing Yahoo Finance data layer. For instruments where the user's TradingView reference is OANDA (for example OANDA:XAUUSD, OANDA:EURUSD, OANDA:GBPUSD), Telegram explicitly warns that the provider differs and the candle should be verified against TradingView if values do not match.

A confirmed example that drove V2: the bot previously reported an XAUUSD sweep at **25 Aug 2026 05:30 IST**, while TradingView's OANDA 4H candle was still running from **02:30→06:30**. V2 refuses to classify an unfinished candle.

## Architecture

- `main.py` — existing monolithic bot and dashboard integration.
- `sweep_engine.py` — canonical candle construction and two-sided sweep decision logic.
- `sweep_runtime.py` — integrates the new engine with the existing scanner, Telegram alerts, and paper-trading execution.
- `run_bot.py` — production entry point; loads the existing bot, installs Sweep Engine V2, then starts the normal services.
- `backtest.py` — existing backtest engine.
- `dashboard_api.py` / `dashboard/index.html` — dashboard.
- `render.yaml` / `Dockerfile` — both now start `run_bot.py`.

## Running

```bash
pip install -r requirements.txt
python run_bot.py
```

Render and Docker are already configured to use `run_bot.py`.

## Verification checklist

Before trusting a signal, verify:

- [ ] Current candle is completely closed.
- [ ] Current High > previous High.
- [ ] Current Low < previous Low.
- [ ] Close determines BUY / NEUTRAL / SELL.
- [ ] Candle start/end match the configured TradingView schedule.
- [ ] Previous and current OHLC in Telegram match the reference chart.
- [ ] Any data-source mismatch warning has been reviewed.

## Legacy note

Older commits contained a `4H Sweep + FVG` strategy. FVG confirmation is **not part of the current sweep strategy**. Sweep V2 is immediate after candle close: both-side break first, then Close classification, with BUY/SELL paper execution and NEUTRAL informational alerts.
