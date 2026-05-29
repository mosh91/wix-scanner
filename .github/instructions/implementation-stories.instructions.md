---
description: "Use when implementing Wix Scanner features, planning story execution, or creating code/tests/docs tied to docs/IMPLEMENTATION_STORIES.md. Enforces delivery order, acceptance-first implementation, and Wix integration guardrails."
name: "Wix Scanner Implementation Stories Guardrails"
---
# Wix Scanner Implementation Stories Guardrails

## Scope
- Treat docs/IMPLEMENTATION_STORIES.md as the delivery source of truth.
- Story order can be flexible, but dependencies and prerequisite contracts must be satisfied before starting dependent stories.
- Do not mark a story Done unless all tasks and acceptance criteria pass.

## Story Execution Rules
- Start by identifying the exact story ID and list its blocking dependencies.
- Implement the smallest vertical slice that satisfies all acceptance criteria for that story.
- Add or update tests that directly verify acceptance criteria behavior.
- Update related docs/runbooks when a story changes operator workflows or reliability behavior.

## Wix Integration Critical Rules
- Keep Wix as source of truth for ticket check-in state.
- Enforce idempotency and duplicate prevention across frontend, relay, backend, worker, and reconciliation paths.
- Prefer deterministic conflict handling and explicit state transitions over implicit behavior.
- Never activate event operations when binding/scope/credential/readiness checks are critical or unverified.

## Phase 1 Priorities (Must Be Preserved)
- Prioritize the moved-up Wix integration stories in Phase 1: P1-US-11 through P1-US-15.
- Ensure site-event binding verification, scope verification, auth lifecycle state machine, readiness gate, and reconciliation contract are implemented before later-phase operational assumptions.

## Kiosk and Operator UX Guardrails
- Preserve 3-state kiosk behavior (Idle, Success, Error) with scan reliability over visual complexity.
- Keep Spanish as default locale and ensure static UI strings are translated.
- Surface operator-safe status for scanner health, backend connectivity, queueing/offline conditions, and recent scan outcomes.

## Offline and Resilience Guardrails
- Support degraded operation during Wix/network outages through local queueing and cached ticket manifest validation.
- Ensure replay is idempotent after recovery and reconciliation converges to Wix truth.
- Treat drills and runbooks as production-critical deliverables, not optional documentation.

## Security, Logging, and Observability
- Never log plaintext secrets or sensitive credential values.
- Maintain end-to-end correlation IDs across frontend, backend, workers, relay, and Wix calls.
- Emit structured logs and metrics for scan latency, outcomes, queue depth, sync lag, and auth health.

## Definition of Done Enforcement
- All tasks are implemented.
- All acceptance criteria are verifiably satisfied.
- Relevant automated tests pass.
- Security and redaction requirements are satisfied.
- Documentation/runbook updates are included when applicable.
