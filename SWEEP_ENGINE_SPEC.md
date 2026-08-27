# Sweep Engine V2 — Canonical Specification

This file is the implementation source of truth for the sweep strategy and its approved compact Telegram presentation.

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
close > previous_high                  -> BUY
previous_low <= close <= previous_high -> NEUTRAL
close < previous_low                   -> SELL
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

## 5. Telegram — approved compact contract

The normal Sweep V2 alert is compact and scan-friendly. The underlying sweep calculation must not be changed to support formatting.

### Canonical first-line rule

The first line MUST use the exact structure:

```text
🔴SWEEP V2 · Bitcoin (BTC) ·  ✅
```

The first icon and final freshness icon have separate meanings:

- BUY → first icon `🟢`
- SELL → first icon `🔴`
- NEUTRAL → first icon is the freshness icon (`✅` when fresh, `⚠️` when stale), because NEUTRAL is not BUY or SELL.
- Freshness `≤60 minutes` → `✅`
- Freshness `>60 minutes` → `⚠️`
- Do not write the word `FRESH` or `STALE` in the first line; the first-line freshness icon is the approved status marker.
- The signal line remains independent: `🟢 BUY`, `🔴 SELL`, or `🟡 NEUTRAL`.

Therefore the canonical header examples are:

```text
🟢SWEEP V2 · <Asset> ·  ✅
🔴SWEEP V2 · <Asset> ·  ✅
⚠️SWEEP V2 · <Asset> ·  ⚠️
```

For a fresh NEUTRAL signal:

```text
✅SWEEP V2 · <Asset> ·  ✅
```

For a stale NEUTRAL signal:

```text
⚠️SWEEP V2 · <Asset> ·  ⚠️
```

The exact spacing after the middle separator is preserved from the approved header contract.

### Approved compact body

The normal alert should contain only useful, readable information:

```text
<approved header>
━━━━━━━━━━━━━━━━━━━━━━
📌 *Signal:* `🟢 BUY`
⏱ *Timeframe:* `4H`
🕯 *Candle closed:* `27-Aug-2026 11:30 IST`
⏳ *Age:* `4 min ago`
📈 *Sweep High:* `<formatted price>`
📉 *Sweep Low:* `<formatted price>`
🎯 *Action:* `PAPER BUY`
💰 *Entry:* `<formatted price>`
🛑 *SL:* `<formatted price>`
🎯 *TP:* `<formatted price>`
🏢 *Account:* `<account>`
📦 *Quantity:* `<formatted quantity>`
💸 *Risk:* `<formatted INR risk>`
━━━━━━━━━━━━━━━━━━━━━━
⚠️ DATA SOURCE: ...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

For SELL, use `🔴 SELL` and `PAPER SELL` with the existing SELL stop-loss/target rules.

For NEUTRAL, use `🟡 NEUTRAL` and `INFORMATIONAL — NO PAPER TRADE`; do not include paper-trade execution fields.

### Freshness rule

Freshness is canonical everywhere in Sweep V2:

```text
age <= 60 minutes  -> FRESH -> first-line `✅`
age > 60 minutes   -> STALE -> first-line `⚠️`
```

The age may be shown as a separate `Age` line, but there must be no duplicate `Signal Status` freshness line.

A stale signal must explicitly state that no new trade should be opened. This display rule is separate from the existing hard execution expiry.

### Asset display rule

User-facing names must be human-readable:

- `GC=F` → **Gold**
- `SI=F` → **Silver**
- `HG=F` → **Copper**
- `BTC-USD` → **Bitcoin (BTC)**

Never show `GC=F` in the user-facing Gold header.

### What must NOT be in the normal compact alert

Do not add back:

- Full Previous Candle OHLC
- Full Current Candle OHLC
- Separate `High Swept: YES/NO` line
- Separate `Low Swept: YES/NO` line
- Close Classification
- Duplicate `Signal Status` freshness line
- Large diagnostic/audit blocks

Detailed candle diagnostics belong in tests/debug views, not the normal live alert.

### Candle timing warning

The bot must compare the **actual candle close time** against the approved schedule, not only the candle start time.

A mismatch must remain visible to the user, for example:

```text
⚠️ Candle timing: `Candle close 10:00 IST is outside configured TradingView schedule`
```

The warning initially flags the signal and does not change the underlying sweep decision.

### Message count

Maximum two messages per qualifying candle:

1. Initial message.
2. `🔔 REMINDER` one hour later.

No additional messages are sent for that candle.

## 6. Data integrity

The free implementation uses the existing Yahoo Finance data layer. OANDA TradingView instruments must carry a visible source warning because Yahoo and OANDA are different feeds.

If candle timing or data cannot be confidently verified, the bot must warn rather than silently treating the result as authoritative.

## 7. Regression case

XAUUSD, 25 Aug 2026, 05:30 IST previously produced a false NEUTRAL alert. TradingView showed the 02:30→06:30 candle still open. V2 must never classify that candle at 05:30.

## 8. Acceptance tests

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
13. BUY header uses `🟢`; SELL header uses `🔴`; NEUTRAL header uses the freshness icon; direction and freshness icons remain independent.
14. Freshness is `≤60m`; stale is `>60m`.
15. Gold is displayed as `Gold`, not `GC=F`.
