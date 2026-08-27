# Sweep Engine V2 — Canonical Specification

This file is the implementation source of truth for the sweep strategy.

## 1. Decision model

For every newly completed strategy candle, compare it with the immediately previous completed strategy candle.

### Required sweep

```text
current_high > previous_high
AND
current_low < previous_low
```

Strict inequality is mandatory. Equal/touching is not a sweep.

If either side is not broken: **NO SIGNAL**.

### Close classification

Only the final current-candle Close matters after both sides are swept:

```text
close > previous_high                 -> BUY
previous_low <= close <= previous_high -> NEUTRAL
close < previous_low                  -> SELL
```

Open is irrelevant. Intracandle path is irrelevant. Multiple crossings during the candle do not create multiple signals. Only the final closed OHLC is evaluated.

## 2. Completion rule

Never classify a candle while it is still forming. The bot may detect a completed candle a few minutes late; that is acceptable. A premature signal is not acceptable.

## 3. Market schedules (IST / UTC+5:30)

### OANDA Gold / FX reference

02:30, 06:30, 10:30, 14:30, 18:30, 22:30.

### BTC

01:30, 05:30, 09:30, 13:30, 17:30, 21:30.

### NIFTY / BANK NIFTY

1H session candles:

- 09:15→10:15
- 10:15→11:15
- 11:15→12:15
- 12:15→13:15
- 13:15→14:15
- 14:15→15:15

Do not fabricate a 15:15→16:15 candle.

### 15 NSE stocks

Session bars start at 09:15 and 13:15. The second bar uses only actual NSE session data through 15:15; overnight/nonexistent prices must not be fabricated.

## 4. Paper trading

BUY and SELL only.

- Entry: current market price when the completed-candle signal is detected.
- BUY SL: current/sweeping candle Low.
- SELL SL: current/sweeping candle High.
- TP: 2R (1:2 risk/reward).
- NEUTRAL: no trade.

## 5. Telegram

Every sweep alert must use the approved compact header contract:

```text
BUY:     🟢SWEEP V2 · <Market Name> ·  ✅
SELL:    🔴SWEEP V2 · <Market Name> ·  ✅
STALE:   same BUY/SELL direction icon, but final status icon becomes ⚠️
NEUTRAL: freshness icon in the header; signal line remains 🟡 NEUTRAL
```

The direction icon and freshness status are independent. A BUY header is never red, a SELL header is never green, and a fresh signal is never shown with the stale warning icon.

The signal line must independently show:

- `🟢 BUY`
- `🔴 SELL`
- `🟡 NEUTRAL`

Gold must be displayed as **Gold**, never `GC=F`. BTC must be displayed as **Bitcoin (BTC)**. Prices in Telegram must use the asset-appropriate compact precision; Gold is 2 decimals, BTC is 2 decimals, NSE instruments are 2 decimals, USD/JPY is 3 decimals, and other FX is 5 decimals.

Every sweep alert must also show:

- Timeframe.
- Candle close time and age.
- Sweep High and Sweep Low.
- Action.
- Entry/SL/TP/account/quantity/risk for BUY/SELL paper trades.
- Source warning when applicable.
- A stale warning when the signal is older than one hour; stale signals must not open a new trade.

Maximum two messages per qualifying candle:

1. Initial message.
2. `🔔 REMINDER` one hour later.

## 6. Dashboard display contract

Dashboard presentation must not leak provider tickers when a user-facing market name is defined.

- `GC=F` → **Gold**.
- `BTC-USD` → **Bitcoin**.
- `^NSEI` → **NIFTY 50**.
- `^NSEBANK` → **BANK NIFTY**.

Dashboard live/history prices are presentation values only and must be compactly rounded to 2 decimals. This must never modify backend execution prices, risk calculations, or stored trade data.

## 7. Data integrity

The free implementation uses the existing Yahoo Finance data layer. OANDA TradingView instruments must carry a visible source warning because Yahoo and OANDA are different feeds.

If candle timing or data cannot be confidently verified, the bot must warn rather than silently treating the result as authoritative.

## 8. Regression case

XAUUSD, 25 Aug 2026, 05:30 IST previously produced a false NEUTRAL alert. TradingView showed the 02:30→06:30 candle still open. V2 must never classify that candle at 05:30.

## 9. Acceptance tests

1. One-sided break → no signal.
2. Touch only → no signal.
3. Both sides + close inside → NEUTRAL.
4. Both sides + close exactly on either boundary → NEUTRAL.
5. Both sides + close above previous High → BUY.
6. Both sides + close below previous Low → SELL.
7. Still-open candle → no confirmed signal.
8. Consecutive qualifying candles may each signal independently.
9. NEUTRAL never opens a paper trade.
10. BUY/SELL use market entry, signal-candle SL and 1:2 TP.
11. Reminder occurs once one hour after initial signal, never more than twice total.
12. Timing/source mismatch is visible to the user.
13. BUY header is green and SELL header is red.
14. Fresh header status is `✅`; stale header status is `⚠️`.
15. Gold is displayed as Gold, never GC=F.
16. Dashboard prices are compact display values and do not alter execution values.
