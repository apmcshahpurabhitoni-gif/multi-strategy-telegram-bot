# Phase 9 — Source-Derived Operational Intelligence Specification

## Authority

This specification is derived from the Phase 9 continuation handoff and the approved project continuity material. It is an operational/presentation specification. It does **not** authorize changes to the underlying Sweep V2 trading decision.

## Scope

Phase 9 covers:

- canonical signal freshness;
- candle-close schedule validation;
- prominent warning for incorrect candle timing;
- compact, readable Telegram presentation;
- consistent display formatting;
- regression/CI verification; and
- persistent signal-history separation from Telegram reminder expiry.

## Canonical Sweep V2 rule

The existing strategy decision remains unchanged:

1. Use completed candles only.
2. The current candle must take both the previous high and previous low.
3. Close classification determines the direction:
   - close above previous high → `BULLISH` / BUY;
   - close below previous low → `BEARISH` / SELL;
   - otherwise → `NEUTRAL`.
4. Operational formatting, freshness, and candle-time warnings must not alter this calculation.

## Approved candle schedules

Schedules are defined in Asia/Kolkata and are expressed as approved candle boundaries/starts. Validation must be performed against the resulting **candle close time**.

| Market | Timeframe | Approved starts | Corresponding closes |
|---|---|---|---|
| NIFTY / BANK NIFTY | 1H | 09:15, 10:15, 11:15, 12:15, 13:15, 14:15, 15:15 IST | +1 hour |
| BTC / Crypto | 4H | 01:30, 05:30, 09:30, 13:30, 17:30, 21:30 IST | +4 hours |
| Forex / Gold | 4H | 02:30, 06:30, 10:30, 14:30, 18:30, 22:30 IST | +4 hours |
| NSE stocks | Session bars | 09:15 and 13:15 IST | 13:15 and 15:15 IST |

No alternative schedule may be silently invented.

## Candle-time warning

The actual close timestamp represented by source observations must be compared with the approved scheduled close. A mismatch is an operational warning, not a hard signal block in this phase.

The normal message must prominently identify:

- `⚠️ CANDLE TIME WARNING`
- expected close time;
- received close time;
- that the candle close may be wrong; and
- that the signal may be unreliable.

## Freshness

Freshness is based on candle close time, not candle start time:

- age `<= 60 minutes` → `FRESH`;
- age `> 60 minutes` → `STALE`.

The separate six-hour execution expiry remains a different safety rule and must not be conflated with the one-hour presentation freshness state.

## Telegram presentation contract

The first line must contain strategy, asset, and freshness. BUY/SELL/NEUTRAL must be immediately scannable.

Normal alerts must remain compact and must not contain:

- full previous/current candle OHLC dumps;
- separate `High Swept: YES` or `Low Swept: YES` diagnostic lines;
- close-classification diagnostics;
- duplicate freshness lines; or
- large audit/debug blocks.

Useful sweep high/low levels, candle-close time, and trade levels may remain when applicable.

## Data integrity and architecture

Provider-specific behavior remains outside the strategy engine. Canonical candle construction must preserve instrument, timeframe, session, timezone, expected boundary, and completion state. Permanent signal history is separate from Telegram reminder expiry.

## Non-rules — do not invent

Phase 9 does not authorize:

- a new trading indicator;
- a new strategy rule;
- shorting changes;
- new stop/target logic;
- leverage or position-sizing changes;
- a new provider without the required provider-selection review;
- replacing the canonical dashboard source;
- runtime HTML/JavaScript injection; or
- treating a candle-time mismatch as a hard trade block without further evidence.

## Acceptance gates

Phase 9 is accepted only when:

1. source requirements have been reviewed;
2. this specification is tracked;
3. implementation preserves Sweep V2 decision logic;
4. regression tests execute rather than merely being present;
5. correct candle timing produces no warning;
6. incorrect candle timing produces a prominent warning;
7. `<=60m` is FRESH and `>60m` is STALE;
8. BUY, SELL, and NEUTRAL presentation is covered;
9. price/quantity/risk formatting is covered where the applicable path exists;
10. GitHub Actions passes on the final HEAD; and
11. the accepted state and evidence are recorded in the changelog/handoff.

Actual Telegram output remains a live/manual verification item where credentials/runtime access is required; it must not be falsely claimed as verified by unit tests alone.
