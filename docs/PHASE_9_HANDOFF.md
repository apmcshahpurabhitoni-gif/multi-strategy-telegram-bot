# Phase 9 Persistent Handoff

## Current state

Phase 9 operational-intelligence scope is implemented on `phase-9-operational-intelligence`.

### Completed sequence

1. Inspected the Phase 9 requirements and existing branch behavior.
2. Created the source-derived specification at `docs/PHASE_9_SOURCE_DERIVED_SPEC.md`.
3. Implemented contract-safe candle-close validation without changing Sweep V2 decision logic.
4. Added regression coverage for candle timing, BUY/SELL/NEUTRAL, freshness, compact presentation, and stale behavior.
5. Fixed CI-exposed defects:
   - declared the existing `pytz` runtime dependency;
   - corrected the bootstrap-ordering test;
   - corrected freshness test wall-clock drift;
   - corrected source-candle interval inference used by close-time validation.
6. Verified the relevant acceptance workflow on the pre-acceptance implementation HEAD.
7. Documented acceptance and this persistent handoff.

## Contract that must remain stable

- Sweep V2 uses completed candles only.
- A sweep requires current high > previous high **and** current low < previous low.
- Close above previous high is BULLISH/BUY.
- Close below previous low is BEARISH/SELL.
- Otherwise NEUTRAL.
- Freshness is based on candle close: <=60 minutes FRESH; >60 minutes STALE.
- Candle timing mismatch is a prominent warning, not a new trading rule.
- Telegram alerts remain compact and immediately scannable.
- Signal history is permanent; Telegram reminder expiry is separate.

## Explicit non-rules

Do not add indicators, shorting, new stops/targets, position sizing, leverage, providers, or execution changes under Phase 9 unless a new authorized source specification explicitly requires them.

## CI boundary

The Phase 9 acceptance workflow is `Dashboard Smoke Test`. A separate legacy `fix_phase3_data_mapping.yml` workflow currently reports failure on this branch; that workflow is outside Phase 9 scope and must be handled separately rather than hidden or misreported as green.

## Next phase

Stop here until the next authorized phase is explicitly selected. If the next phase touches the legacy workflow failure, inspect its actual requirements first and follow the same sequence: source → specification → contract-safe implementation → tests → CI → fix failures → document → final-head proof → accept → handoff.
