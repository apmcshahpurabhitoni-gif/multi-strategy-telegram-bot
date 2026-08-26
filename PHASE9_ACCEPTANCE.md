# Phase 9 Acceptance Checklist

This checklist is used only after implementation of Phase 9.

## Safety

- [ ] No Sweep Engine V2 decision changes
- [ ] No Sweep Engine timing changes
- [ ] No TrendPulse decision changes
- [ ] No risk-sizing changes
- [ ] No paper-execution changes
- [ ] No Telegram behavior changes

## Backend

- [ ] Existing dashboard snapshot fields preserved
- [ ] Operational-health payload is additive
- [ ] Signal lifecycle data comes only from real persisted/server state
- [ ] Trade-quality metrics are server-side
- [ ] Empty/missing/stale/error states are explicit

## Frontend

- [ ] Canonical dashboard only
- [ ] No runtime HTML/JS injection
- [ ] Four themes work
- [ ] Mobile widths 320–430px verified
- [ ] No horizontal overflow
- [ ] Existing navigation preserved
- [ ] Existing Overview hierarchy preserved
- [ ] Phase 8B intelligence preserved

## Verification

- [ ] Python compileall passes
- [ ] Full unittest suite passes
- [ ] Dashboard JavaScript syntax passes
- [ ] `/ping` passes
- [ ] `/dashboard` loads
- [ ] `/api/dashboard` passes
- [ ] `/api/dashboard?force=1` passes
- [ ] Backtest endpoint remains functional
- [ ] Paper close-trade action remains functional
- [ ] News refresh remains functional
- [ ] Full diff reviewed
- [ ] CI result verified
- [ ] Deployment/runtime verified where tooling permits

## Acceptance

Phase 9 is accepted only when every applicable checkbox above is satisfied and no known regression remains.
