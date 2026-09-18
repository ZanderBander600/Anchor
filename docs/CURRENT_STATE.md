# Anchor Current State

Last synchronized: 2026-09-17

This is the single live status record for Anchor. It reports project state; it
does not replace any financial convention or architecture authority. Update it
whenever an accepted gate merges or the active gate changes.

## Accepted Baseline

- Repository: `ZanderBander600/Anchor`
- Accepted baseline: `main` at `3f23ba4` (PR #36, P7.9 Stage 3 Partnership
  product UI, Partner Decision Matrix integration and browser QA).
- Last accepted financial implementation merge: `70b92e2` (PR #34, P7.9
  Stage 1 deterministic contracts and engine).
- Active gate: **P7.9 Partnership Waterfalls + Investor Returns**. The ratified
  contract is `docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`.
  - **Stage 1** (deterministic contracts and engine): **complete and accepted**
    in PR #34 (`70b92e2`).
  - **Stage 2** (persistence, migration, fingerprints, API, Partner Decision
    Matrix; Section 17.2): **complete and accepted** in PR #35 (`543c1b2`).
    Tier 2 is integrated over the frozen Stage 1 engine.
  - **Stage 3** (product UI, browser QA; Section 17.3): **implementation
    complete and merged** in PR #36 (`3f23ba4`). Final hands-on human product
    acceptance is pending before P7.9 closes.
- Open PR: none at the time of this synchronization.
- **AM1 Managed Assets + Monthly Performance** was explicitly started from
  `main` at `63c2ac0`, on branch
  `feature/am1-managed-assets-monthly-performance`. It is an independent
  post-acquisition feature: it is not P7.10 and is not part of P7.10. Its
  authority is `docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md`.
  Implementation is complete on that branch and is not pushed, merged or
  accepted.
- P7.9 final hands-on human acceptance remains pending.
- P7.10 has not started.
- Autopilot: off; the manual Claude Code -> independent review -> human merge
  workflow is active
- Autonomous merge: not authorized
- Autonomous next-gate transition: not authorized

Git and GitHub remain operational truth for the exact current HEAD and open PR
state. If `main` has moved beyond the baseline above, inspect the intervening
accepted merge before updating this file.

## Completed Milestones

- Original POC phases: deterministic engine, Excel ingestion, API, web UI,
  sensitivity, break-even, AI interpretation, and OM ingestion
- Underwriting V2, Detailed Operating Model V2.1, Owner Return Metrics V3,
  One-Page Owner Summary V3, and Workspace UX V3
- Lease-Level Underwriting D0-D5
- D6 Business Plan & Capital Economics, including D6 closeout
- P7.0 Competition Decision Architecture, ratified
- P7.1 Scenario Engine
- P7.2 Investment shell and Scenario persistence/fingerprints
- P7.3 Scenario UI and Decision Matrix v0
- P7.4 Strategy Engine and persistence
- P7.5 Strategy x Scenario Decision Matrix v1
- P7.6 Multi-Unit Investments and Consolidation
- P7.7 Capital Structure Foundation and legacy debt adapter
- P7.8 Structured Position Cash Flows, Position Returns, persistence, product
  integration, Position Decision Matrix, browser QA, and human visual acceptance
- P7.9 Stage 1 deterministic Partnership Waterfall contracts and engine
- P7.9 Stage 2 Partnership persistence, migration, fingerprints, API and
  Partner Decision Matrix
- P7.9 Stage 3 Partnership product UI, Partner Decision Matrix integration and
  browser QA implementation (PR #36; final hands-on human acceptance pending)

## Next Work

**P7.9: Partnership Waterfalls + Investor Returns** is active. Its contract is
ratified (PR #33). Human engine-scope approval (Q16) covers the P7.9
Partnership Waterfall and Investor Return layer only. The gate runs in three
stages, each started explicitly:

1. Stage 1: deterministic contracts and engine. **Complete and accepted in
   PR #34 (`70b92e2`).**
2. Stage 2: persistence, migration, fingerprints, API and the Partner
   Decision Matrix. **Complete and accepted in PR #35 (`543c1b2`).**
3. Stage 3: product UI with browser QA. **Implementation complete and merged
   in PR #36 (`3f23ba4`); final hands-on human product acceptance is pending.**

The next action is the human workflow test of the merged Stage 3 product.
P7.9 remains active until that acceptance is recorded. P7.10 has not started,
and finishing P7.9 will not start it automatically.

A bounded stabilization sweep remains available for separate human
authorization. It is not automatically active. Its source issues are:

- #26: product polish and technical-debt backlog
- #29: multifamily rent-roll abstraction improvements
- #30: negative forward exit-NOI error presentation

Do not treat #29 as authority to redesign the Lease-Level engine inside a
polish gate. A full multifamily abstraction is separate product scope. Small
unit-label, validation, diagnostic, and regression-fixture improvements may be
scoped independently.

After P7.9, the ratified sequence is:

1. P7.10 Valuation Timepoints + remaining Decision Support / AI integration
2. P7.11 Competition Closeout

Refinancing / recapitalization remains a separately authorized potential
sub-gate.

## Current Architecture Authorities

- Development protocol:
  `docs/development/ANCHOR_DEVELOPMENT_PROTOCOL.md`
- Base financial conventions: `docs/financial_conventions.md`
- Underwriting V2 and Detailed V2.1:
  `docs/underwriting_v2_financial_conventions.md` and
  `docs/detailed_operating_model_v2_1_financial_conventions.md`
- Lease-Level: the D0-D4 documents in `docs/plans/`, read with their historical
  status notices and later amendments
- D6: `docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`
- P7: `docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`
- P7.7 and P7.8 implemented records:
  `docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md`,
  `docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md`, and
  `docs/architecture/P7_8_PRODUCT_INTEGRATION.md`
- P7.9 ratified contract (Stages 1 and 2 accepted; Stage 3 merged, with final
  hands-on human acceptance pending):
  `docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`

## Historical-Document Rule

Documents under `docs/plans/` are frozen design and gate records. Documents
under `docs/solutions/` are lessons and patterns, some inherited from the
Mini-Anchor predecessor. They may intentionally contain old paths, branch
names, baselines, test counts, and statements about what had not yet shipped
at the time. Use them for rationale and invariants, never for live status.

When a historical statement conflicts with this file only about current state,
this file governs. When a financial convention conflicts, stop and resolve the
applicable ratified authority; this file has no power to change economics.
