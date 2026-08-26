# Phase 8 — Intelligence & Decision Support

## Phase 8A — Signal & Trade Intelligence

**Base:** `baseline-approved-2026-08-26-final`  
**Working branch:** `phase-8-signal-trade-intelligence`  
**Baseline commit:** `51b7d0a475be47ea02fcb2f18a0dc80c428ace6b`

### Objective

Build on the approved dashboard without changing the approved base UI or trading behavior. Phase 8 turns existing bot records into information that explains what happened and how each strategy has performed.

### Hard boundary

- The release baseline is immutable for this phase.
- No theme, navigation, date, News, or Backtest regression.
- No changes to Sweep Engine V2 decisions.
- No changes to TrendPulse decisions.
- No changes to risk calculations.
- No changes to execution or paper-trade behavior.
- No changes to Telegram behavior.
- No new trading decisions are introduced by the intelligence layer.
- Python remains authoritative; the dashboard remains presentation-only.

### 8A data contract

The new `phase8_intelligence.py` module is read-only and derives:

1. **Trade intelligence**
   - Direction
   - WIN / LOSS / FLAT outcome
   - Recorded P&L
   - R-multiple when entry and stop are available
   - Strategy attribution
   - Availability of stop and exit data

2. **Strategy statistics**
   - Trades
   - Wins / losses / flat
   - Win rate
   - Total P&L
   - Average win
   - Average loss
   - Profit factor
   - Expectancy

3. **Signal records**
   - Existing signals are passed through unchanged for later UI explanation.

### Next implementation step: 8B

Expose the 8A payload through the existing dashboard snapshot/API without changing existing fields. Then add UI cards to the approved Signals/Trades/Overview areas.

### 8B planned UI

- Signal detail: **why this signal is visible** using only recorded metadata.
- Trade detail: **what happened** from entry through exit.
- Strategy performance cards.
- Compact win-rate / expectancy / profit-factor summaries.
- Clear empty states when source data does not contain the required field.

### 8C planned analytics

- Strategy comparison.
- Drawdown-aware performance view.
- Win/loss distribution.
- Time-based performance.
- Backtest-vs-live comparison only where the underlying records are genuinely comparable.

### Acceptance rule

Every Phase 8 increment must be additive and reversible. If an intelligence field is unavailable in the source data, the dashboard must say that it is unavailable rather than inventing a reason or metric.
