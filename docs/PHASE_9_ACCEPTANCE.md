# Phase 9 Acceptance — Operational Intelligence

**Branch:** `phase-9-operational-intelligence`

**Final accepted HEAD:** `c6b6d4d9dc5acff567e4ef5937dce7eec27a9890`

## Gate result

Phase 9 is accepted for the source-authorized operational scope.

### Requirements

- [x] Source-derived Phase 9 specification created.
- [x] Existing Sweep V2 decision rule preserved.
- [x] Closed-candle schedule validation implemented against actual source close timestamps.
- [x] Incorrect candle timing produces a prominent warning.
- [x] Freshness remains `FRESH` through 60 minutes and `STALE` after one hour.
- [x] Six-hour reminder/expiry behavior remains separate from one-hour freshness.
- [x] Compact BUY/SELL/NEUTRAL presentation regression coverage added.
- [x] Persistent signal history remains separate from reminder state.
- [x] Dependency required by the runtime (`pytz`) is declared.
- [x] CI test defects discovered during the phase were fixed and documented by commit history.

## Verification evidence

Relevant acceptance workflow:

- **Dashboard Smoke Test run `33364978083` — SUCCESS**
- Final-head SHA: `c6b6d4d9dc5acff567e4ef5937dce7eec27a9890`
- The workflow executed syntax checks, dashboard wiring checks, and the pytest suite.

A separate legacy workflow, `.github/workflows/fix_phase3_data_mapping.yml` run `33364977209`, is failing on the same final HEAD. It is outside the Phase 9 source-authorized scope and was not modified as part of this phase. It must not be represented as a successful full-repository green state.

## Known boundary

Live Telegram rendering still requires runtime/manual verification with the actual bot environment. Automated tests verify the canonical message construction and warning contract; they do not claim that a real Telegram delivery was observed.

## Handoff

Phase 9 is complete for its approved scope. Do not add new strategy rules, indicators, providers, sizing, stops, targets, or execution behavior under Phase 9. Any remaining legacy workflow failure must be handled as a separate authorized maintenance task.
