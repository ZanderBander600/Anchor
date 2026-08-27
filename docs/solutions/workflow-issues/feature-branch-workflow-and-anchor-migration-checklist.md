---
title: Feature-Branch Workflow in Practice, and the Anchor Migration Checklist
date: 2026-08-27
category: workflow-issues
module: git, process
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "Deciding how main and feature branches should relate in Anchor's repo"
  - "Starting the Mini-Anchor to Anchor migration and deciding what to carry forward deliberately vs. leave behind"
  - "Closing out a development phase that touches a live external API (Azure DI, OpenAI) or a real document"
tags: [git-workflow, feature-branches, main-branch, migration, poc-to-production, acceptance-testing]
related_components: [ingestion, financial_engine, testing_framework]
---

# Feature-Branch Workflow in Practice, and the Anchor Migration Checklist

## Context

`AGENTS.md`'s stated Git rule is simple: "main represents the latest stable approved version... Development occurs on feature branches... Do not commit directly to main unless explicitly instructed. Do not merge branches unless explicitly instructed." Ten phases of Mini-Anchor development followed the "work on a feature branch per phase" half of that rule consistently. The "main reflects the latest approved version" half did not hold in practice past Phase 1 — worth documenting plainly now, since Anchor should either actually restore that half of the rule or consciously replace it, rather than silently inherit a written policy the POC itself didn't follow.

## Guidance

**1. `main` stopped advancing after Phase 1; every later phase lives only on a stacked branch chain.**

`main` is at commit `fd2d42e` ("Merge Phase 1 Excel ingestion"). Every phase from Phase 2 onward — deterministic engine, CLI, FastAPI, web UI, sensitivity, break-even, AI analyst, OM ingestion — was committed to its own named branch (`feature/phase-2-deterministic-engine`, `feature/phase-4-cli-results`, `feature/phase-5-fastapi`, `feature/phase-6-web-ui`, `feature/phase-7-sensitivity-engine`, `feature/phase-8-break-even`, `feature/phase-9-ai-analyst`, `feature/phase-10a-om-ingestion`), and each of those branches' tip is one linear commit chain stacked on the previous phase's branch tip, not on `main`. `git merge-base --is-ancestor main HEAD` confirms `main` is still an ancestor of the current tip — but only because it was never advanced past, never because later work was merged into it. All ten branches, including `main`, exist on `origin` as well (`git branch -a`), so this was a deliberate, consistently-applied branch-per-phase naming discipline — just never closed the loop back to `main`. A separate branch named archive/mini-anchor-poc-v1.0 points at the exact same commit as the tip of feature/phase-10a-om-ingestion (`git rev-parse` on both resolves identically), evidently created as the de facto "this is the finished POC" marker in place of ever merging that state into `main`.

**2. This is not a defect to silently fix retroactively in Mini-Anchor — it's a decision Anchor needs to make deliberately.** Two honest options, not a right answer this doc picks for you:
- **Restore the written rule as literally described**: merge each phase branch back to `main` (in order) before starting the next, so `main` genuinely always reflects "the latest stable approved version" the way `AGENTS.md` says it does.
- **Update the written rule to match the pattern actually used**: a single stacked branch that accumulates all phases in sequence, with `main` deliberately reserved for a later, explicit promotion point (e.g., only at a public release), rather than after every phase.

What matters is that Anchor's `AGENTS.md`-equivalent states whichever choice is made explicitly, so the next agent reading it isn't working from a policy the codebase's own history already contradicts.

**3. Live/manual acceptance testing against real external services was a required, explicit gate before a phase involving an external API could be called done — not an afterthought.**

Phase 10A's own Definition of Done includes, alongside the automated test suite: "Manual smoke check: uploading a sample OM PDF through the running app produces a review screen with at least one `stated`, one `missing`, and (with a suitable fixture OM) one `conflicting` field, and approving a subset correctly pre-fills `AssumptionsForm` without triggering `/analyze`" (`docs/plans/2026-08-26-1343-feat-om-ingestion-foundation-plan.md:439`). This gate is why the three live-testing-derived regressions detailed in [testing-conventions-and-architecture-guardrails](../conventions/testing-conventions-and-architecture-guardrails.md) — Azure DI's F0-tier silent page truncation, magnitude-representation false conflicts, and the occupancy-conflict diagnostic test — were caught before the phase was considered complete, rather than discovered later in production. None of the three were reachable by the mocked/fake-provider automated test suite alone, because each depends on how a real external service or a real (if synthetic) document actually behaves. **The reusable lesson for Anchor:** any phase that adds or changes an integration with a live external service should keep an explicit manual-smoke-test step in its own definition of done, in addition to (never instead of) the automated suite — and any bug that step finds should become a permanent regression test, per the diagnostic-regression-test convention, not just a one-off fix.

This live-acceptance step was, and remains, entirely manual: the repo has no CI configuration of any kind (checked 2026-08-27: no GitHub Actions workflow directory or equivalent exists anywhere in the tree), so `pytest`/`npm test` are developer-run against fakes only, and nothing automatically re-runs a live-provider check after the one-time manual pass that produced each regression test above. Anchor should decide deliberately whether to keep this manual (acceptable for a solo-analyst POC) or introduce a scheduled/gated live-acceptance job once more than one person or a real deployment pipeline depends on the result.

**4. What should be preserved unchanged when Mini-Anchor is migrated and renamed to Anchor** (a consolidated checklist; each item is detailed in its own linked learning):
- The deterministic-engine-as-sole-calculation-authority boundary, and the AI system prompt's specific, enumerated grounding rules (not just its general spirit) — see [deterministic-engine-ai-grounding-boundary](../architecture-patterns/deterministic-engine-ai-grounding-boundary.md).
- The provenance-verification-then-mandatory-analyst-approval shape for any document- or AI-derived value that could reach the engine, and the existing form as the single path such values enter — see [om-ingestion-provenance-and-analyst-approval-gate](../architecture-patterns/om-ingestion-provenance-and-analyst-approval-gate.md).
- The provider-isolation pattern (one adapter module per external SDK, enforced by an AST-based architecture-guardrail test) for any new external integration Anchor adds.
- The golden-case-against-frozen-spec and diagnostic-regression-test testing conventions — see [testing-conventions-and-architecture-guardrails](../conventions/testing-conventions-and-architecture-guardrails.md).
- Backend-only credential handling: every external provider's API key/endpoint is read from backend process environment variables and never referenced anywhere under the frontend source tree.
- The completion ritual from `AGENTS.md`: targeted tests, then full suite, then report exact results, then review `git diff` for unintended changes — reused verbatim in the Phase 10A plan's own Definition of Done rather than restated per phase.
- A deliberate, explicit decision (not a silent carry-forward) on the `main`-vs-feature-branch question in point 2 above.
- Gitignore any environment-dependent temp-artifact path (e.g. the pytest-temp issue) proactively in the new repo, and confirm `TMPDIR`/`TEMP` resolve correctly in whatever environment Anchor's tests run under, rather than discovering the same class of accidental-commit issue again.

## Why This Matters

A rewrite or rename is exactly the moment an unstated or half-followed policy either gets silently carried forward as-is (repeating whatever gap existed) or silently dropped (losing something that was actually load-bearing). Distinguishing the two in advance — "this pattern was fully realized and must be preserved exactly" (the engine boundary, the approval gate, the guardrail tests) versus "this was written down but not actually what happened" (main-as-latest-approved) — means Anchor's own foundational documents can be written to match reality from day one, instead of inheriting a description of Mini-Anchor that was already partly aspirational.

## When to Apply

- Before writing Anchor's own `AGENTS.md`/`CLAUDE.md`-equivalent Git-workflow section: decide and state the `main`-vs-feature-branch relationship explicitly, informed by point 2 above.
- Before closing out any Anchor phase that adds or changes a live external integration: confirm a manual/live acceptance-test step exists in that phase's definition of done, separate from the automated suite.
- At the start of the migration itself: treat this doc's checklist (point 4) as the starting punch list for "what must survive the rename unchanged," and update it as new learnings are captured.

## Related

- [deterministic-engine-ai-grounding-boundary](../architecture-patterns/deterministic-engine-ai-grounding-boundary.md)
- [om-ingestion-provenance-and-analyst-approval-gate](../architecture-patterns/om-ingestion-provenance-and-analyst-approval-gate.md)
- [testing-conventions-and-architecture-guardrails](../conventions/testing-conventions-and-architecture-guardrails.md)
