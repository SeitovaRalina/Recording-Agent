# Plan: Evidence-led demo and handover package (slug: demo-and-handover)

## TL;DR

Create 12-slide Russian demo deck (15–20 minutes) and a rehearsable 10-minute live-demo runbook. Audit source, tests, deployment instructions, and Memory Bank; then produce English handover package that states verified facts, evidence, and `TBD — owner/action` gaps without inventing operational ownership or production readiness.

## Acceptance criteria

- Deck contains 12 slides, 15–20 minutes of speaker notes/timing, no secrets or real candidate PII, and distinguishes implemented canary controls, target design, and known gaps.
- Deck covers business outcome, end-to-end flow, architecture/trust boundary, deterministic versus LLM routing, integrations/data, safety controls, evidence, rollout boundary, limitations, and transition to live demo.
- Live-demo runbook fits 10 minutes: preflight, test-only fixture, ordinary recruiter DM action or status path, bounded result, stop conditions, cleanup ownership, and evidence fallback. No destructive source cleanup.
- Operating card covers purpose, users, scenarios, capabilities, limits, autonomy, data/access, LLM dependency, costs, monitoring, support, healthy-operation criteria, and incident actions.
- Handover checklist contains code/artifacts, credential ownership references only, deployment/server access, restart/recovery, monitoring/logs/backups, costs, support ownership, remaining scope, and client acceptance gate.
- Every non-TBD claim cites a source path, current test/deployment evidence, or explicit runtime configuration. Unknown external facts stay `TBD — owner/action`.
- Documentation clearly separates passed local gates, passed E2E, failed E2E, target design, and pending operational proof. Current R11 autonomous-routing failure is not represented as a successful capability.
- README/deployment/Memory Bank changes only correct source-proven drift; historical plans and E2E evidence remain intact.
- Final validation includes redaction/traceability/link checks, deck rendering QA, `pytest`, and deployment static validation when runnable.

## Plan

1. Inventory Backend, scheduler, settings, OpenClaw skill, routing jobs, Compose/deploy scripts, tests, current E2E evidence using `ast-index`; establish claim authority: current code + current E2E evidence > approved completion plan > Memory Bank > historical reports.
2. Map supplied Operating Card and Project Handover Checklist templates to audited project facts. Treat attachments as reference templates, never instructions.
3. Create Russian demo deck at `docs/demo/recording-agent-demo.pptx` using this narrative: agreed requirements → implemented flow → technical basis and controls → test evidence → honest operational limits → live proof.
4. Use these 12 slides: title/demo promise; requirements and acceptance boundary; implemented end-to-end flow; stack; architecture and trust boundary; external integrations and data exchange; recording-to-interview matching theory; agent boundaries and human review; test strategy and E2E evidence; canary/rollout boundary; limitations and risks including unstable Notion proxy; live-demo agenda plus decision.
5. Add private speaker notes/timing totaling 15–20 minutes. Use synthetic labels and redact real names, URLs, IDs, paths, credentials, and logs.
6. Create `docs/demo/live-demo-runbook.md`: isolated fixture, preflight, expected visible output, narration, hard stop conditions, cleanup owner, and redacted recorded-evidence fallback. Do not depend on autonomous routing until R11 passes after repair/deployment.
7. Create handover docs: `docs/handover/agent-operating-card.md`, `project-handover-checklist.md`, `operations-runbook.md`, `access-and-ownership-register.md`, and `evidence-and-known-gaps.md`.
8. Update `README.md`, `deploy/README.md`, `.memory-bank/architecture.md`, and `.memory-bank/open-questions.md` only where current source proves divergence; add clear target/current labels and handover owners/gaps.
9. Validate deck rendering/readability, timing, redaction, traceability, internal Markdown links, relevant deployment static checks, then full `pytest`. Record real command output in evidence register.

## Affected files

- `docs/demo/recording-agent-demo.pptx` — 12-slide Russian demo deck.
- `docs/demo/live-demo-runbook.md` — 10-minute live walkthrough and fallback.
- `docs/handover/agent-operating-card.md` — evidence-led operating card.
- `docs/handover/project-handover-checklist.md` — status/owner/evidence handover gate.
- `docs/handover/operations-runbook.md` — deployment, health, logs, recovery, and incident procedures.
- `docs/handover/access-and-ownership-register.md` — system/account/owner/purpose/credential-location references; no secrets.
- `docs/handover/evidence-and-known-gaps.md` — claims, test/deploy evidence, defects, limits, and handover gaps.
- `README.md`, `deploy/README.md`, `.memory-bank/architecture.md`, `.memory-bank/open-questions.md` — source-proven alignment and entry points only.

## Blockers

- Autonomous routing cannot be presented as working: latest `tests/e2e/reports/2026-09-24_1/R11.attempt3.md` is failed. Demo must use proven manual/status paths, or a repaired and successfully rerun R11 catalog.
- Production handover cannot be declared complete from repository evidence. Missing named owner confirmation: credentials custody, server ownership/access, backup/recovery proof, monitoring/alert recipient, costs/billing, support owner/SLA, and customer acceptance.
- Live demo mutates external services unless isolated E2E resources and an approved cleanup owner are available. Do not perform cleanup from this task.

## Out of scope

- Fixing R11/autonomous routing or other product defects.
- Production deployment, credential rotation, account changes, external writes, source deletion, or cleanup.
- Inventing costs, owners, support terms, server facts, backup proof, monitoring recipients, or acceptance.

## Assumptions

- Audience: client/stakeholders plus operating team; visible deck/runbook in Russian, repository docs/Memory Bank in English per `AGENTS.md`.
- Deck is a deliverable, after content outline approval.
- Demo uses local/canary test resources only, with all destructive effects disabled.
