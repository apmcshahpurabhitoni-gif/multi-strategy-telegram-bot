# Phase 10 — Source-Derived Production Specification

Status: implementation baseline
Source basis: Mavis scratch rebuild package (`00_MASTER_SPECIFICATION.md`, `08_TESTING_AND_ACCEPTANCE.md`, `09_ARCHITECTURE_AND_DEPLOYMENT.md`, `10_BUILD_PLAN.md`, `99_BUG_REGISTRY.md`) plus the accepted Phase 9 repository baseline.

## 1. Scope

Phase 10 is the production-hardening phase. It covers only CI, deployment controls, monitoring/observability, health checks, rollback readiness, and production acceptance. It must not change Sweep V2, TrendPulse, risk calculations, paper execution, Telegram presentation, persistence semantics, market-data rules, or dashboard behavior unless required to make the production controls truthful.

## 2. Authoritative requirements

- Production deployment requires passing tests.
- CI must be read-only with `contents: read` and must never push to `main`, rewrite application source, commit generated production source, or apply hidden production migrations.
- Production deploy flow is: developer branch -> PR -> CI -> review -> protected `main` -> deployment -> post-deploy smoke checks.
- Production deploys only known-good commits.
- Secrets remain in environment/secret storage; never commit secrets.
- Observability must cover provider failures, candle validation, signals, data mismatches, paper trades, Telegram delivery, API errors, and unexpected exceptions without logging secrets.
- Health checks are required but are not sufficient for acceptance; actual application smoke verification is also required.
- The system remains paper-trading only unless separately authorized; no broker order placement is introduced by Phase 10.
- Time remains timezone-aware; NSE uses Asia/Kolkata.
- The canonical data flow remains `market data -> normalized candle -> strategy engine -> SignalResult -> consumers`.
- No duplicate strategy/business logic or runtime source injection is permitted.
- A failing P0/P1 issue blocks phase completion.
- DONE requires code, unit/integration/regression tests, CI execution/pass, output contract verification, documentation, and no unresolved P0/P1 issue.

## 3. Production control checklist

### CI

1. Every production-relevant workflow has read-only repository permissions.
2. Test dependencies are installed before tests execute.
3. Python compilation executes.
4. The full pytest suite executes and passes.
5. Dashboard JavaScript/source smoke checks execute.
6. Existing regression suites remain active.
7. CI contains no source mutation or `git push` behavior.

### Deployment

1. `render.yaml` remains declarative and points production deployment at `main`.
2. The configured health endpoint is `/ping`.
3. Required secrets are environment-provided, not source-controlled.
4. Production is deployed only from a CI-passing reviewed commit on `main`.
5. No broker execution is introduced.

### Health and observability

The existing application health endpoint is the minimum liveness contract. Production acceptance additionally requires smoke checks against real application endpoints/UI and inspection of runtime behavior. Logs must not expose secrets.

### Rollback

Rollback must be to a previously known-good Git commit/release, not an ad-hoc source edit on the running service. The accepted production commit and prior rollback target must be recorded in release documentation.

## 4. Existing repository findings at Phase 10 start

- Accepted Phase 9 HEAD was `879a63094f633174befc1c1a58260c964da4d900`.
- `render.yaml` declares a free Render service, `/ping` health check, `main` deployment branch, and environment-provided Telegram/Supabase secrets.
- `requirements.txt` requires `pytz` because the canonical sweep engine is timezone-aware.
- Legacy mutating CI workflows are not part of the Phase 10 production path.
- The retained Dashboard Smoke workflow now declares `contents: read`.

## 5. Acceptance gate

Phase 10 is not accepted merely because CI is green. Acceptance requires:

- production controls are source-derived and documented;
- CI is read-only and executes the relevant test suites;
- no active workflow can rewrite or push application source;
- production configuration is reviewed;
- health and smoke checks are executed;
- runtime logs and actual application behavior are verified after deployment;
- rollback target is documented;
- no unresolved P0/P1 issue remains;
- the exact accepted commit and CI/deployment proof are recorded in the persistent handoff.

## 6. Explicit non-goals

- No new trading strategy.
- No provider substitution while provider choice remains unspecified by the source package.
- No new risk percentage or sizing rule.
- No broker order placement.
- No UI redesign.
- No changes to canonical Sweep V2 decision logic.
