# Anchor Current State

Last synchronized: 2026-09-20 (P7.10 Stage 1 accepted after PR #49)

This is the single live status record for Anchor. It reports project state; it
does not replace any financial convention or architecture authority. Update it
whenever an accepted gate merges or the active gate changes.

## Accepted Baseline

- Repository: `ZanderBander600/Anchor`
- Accepted repository and product implementation baseline: `main` at `f6f3680`
  (PR #49, P7.10 contract ratification and Stage 1 deterministic valuation and
  `PctOfValue` closing execution).
- Last financial-engine implementation merge: `f6f3680` (PR #49, P7.10 Stage
  1 deterministic valuation and `PctOfValue` closing execution).
- Active gate: **P7.10 Valuation Timepoints + remaining Decision Support / AI
  integration.** The P7.10 contract is **ratified**; decisions R-A through R-J
  are closed within the gate and recorded in Section 20 of
  `docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`, the ratified
  authority. **Stage 1 is implemented, merged, and human accepted.** **Stage 2
  has not started** and requires a separate explicit start.
- Autopilot: off; the manual Claude Code -> independent review -> human merge
  workflow is active.
- Autonomous merge: not authorized.
- Autonomous next-gate transition: not authorized.

Git and GitHub remain operational truth for the exact current HEAD and open PR
state. If `main` moves beyond the accepted baseline above, inspect the
intervening merge before updating this file.

## 2026-09-20 P7.10 Stage 1 Acceptance

The human explicitly accepted P7.10 Stage 1 after PR #49 merged to `main` at
`f6f3680`. The accepted scope is the ratified P7.10 contract, deterministic
valuation authority, and `PctOfValue` **closing** execution, including the
typed unresolved result and the boundaries recorded in Sections 6.1 and 6.2
of the P7.10 authority.

This acceptance does not broaden Stage 1: later valuation timepoints remain
reporting-only for funding purposes, and later financing still requires an
explicitly authorized refinancing or event-timing stage. It also does not
start Stage 2, persistence, an API or presentation adapter, memo storage,
grounded AI, institutional reporting, or PDF generation.

## 2026-09-20 Human Acceptance and Closeout

The human explicitly accepted all work through the current merged `main`. A
final isolated acceptance sweep against the merged product then confirmed the
major workflows below at desktop and 390px mobile widths, with no page-level
overflow and no browser console warnings or errors. The sweep used temporary
data and did not alter the production database or the user's active browser
session.

The following gates and bounded extensions are **accepted and closed**:

- **P7.9 Partnership Waterfalls + Investor Returns**, all three stages:
  - Stage 1 contracts and deterministic engine, PR #34 (`70b92e2`);
  - Stage 2 persistence, migration, fingerprints, API, and Partner Decision
    Matrix, PR #35 (`543c1b2`);
  - Stage 3 product UI and browser QA, PR #36 (`3f23ba4`), including the later
    P7.9 QA corrections merged through PR #42.
  - The acceptance sweep ran the Partnership analysis and verified Partner
    returns, benchmark differences, Promote Earned, benchmark capital
    subordination, promote attribution by tier, the Tier Audit, and the Partner
    Decision Matrix.
- **AM1 Managed Assets + Monthly Performance**, PR #38 (`3048976`), including
  the Managed Asset deletion extension in PR #39 and the later AM1 QA and
  commentary-only corrections merged through PR #42. The acceptance sweep
  verified the Managed Assets list, acquisition linkage, monthly budget versus
  actual reporting, KPI cards, operating statement, attention items,
  commentary, and responsive presentation.
- **Asset Types 1**, PR #43: the controlled Asset Type and analyst-authored
  subtype are accepted across Deals, Investments, and Managed Asset snapshots.
- **Excel Export 1**, Quick Underwrite formula-audit workbook, PR #44 plus the
  PR #45 presentation polish (`b9437e4`).
- **Excel Export 2**, Detailed Underwrite formula-audit workbook, PR #46
  (`fe70d40`).
- **Excel Export 3**, Lease-Level Underwrite formula-audit workbook, PR #47
  (`1afd003`).
  - The acceptance sweep completed one export in each underwriting mode and
    confirmed the mode-specific success status and filename.

This closeout changes status only. It changes no calculation, convention,
schema, fingerprint, API contract, workbook, or product behavior. It did not
itself start P7.10, a later Asset Types phase, another Asset Management phase,
or another Excel Export gate. P7.10 was started later by a separate explicit
human instruction recorded above.

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
- P7.9 Partnership Waterfalls + Investor Returns, Stages 1–3, human accepted
- AM1 Managed Assets + Monthly Performance, including deletion and focused
  commentary updates, human accepted
- Asset Types 1 controlled classification and analyst-authored subtypes, human
  accepted
- Excel Exports 1–3 formula-audit workbooks for Quick, Detailed, and
  Lease-Level Underwrite, human accepted
- P7.10 Stage 1 deterministic valuation authority and `PctOfValue` closing
  execution, human accepted

## Next Work

**P7.10 Valuation Timepoints + remaining Decision Support / AI integration**
remains the current program. Its contract is ratified; decisions R-A through
R-J are closed within this gate and recorded in Section 20 of
`docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`. Stage 1 is implemented,
merged, and human accepted. Stage 2 has not started.

Stage 1 implements the deterministic valuation layer and `PctOfValue`
**closing** execution only. It adds no persistence, migration, schema version
change, API route, memo storage, AI grounding, PDF generation, or frontend
change. Its implementation is accepted at `main` `f6f3680` through PR #49.

Two boundaries carry into Stage 2 and are recorded in the contract:

- **Closing-only execution (Section 6.1).** The valuation authority resolves
  As-Is, Stabilized and Custom timepoints alike, but the capital execution seam
  can use `PctOfValue` only at closing, model month 0. A later Stabilized or
  Custom valuation is a reporting value that cannot presently create a later
  funding event. Supporting one requires an explicitly authorized refinancing
  or event-timing stage. This is a product limitation — never a zero, and never
  a fallback to the purchase price.
- **The unavailable-state adapter (Section 6.2).** Stage 1 stops internal
  execution with the typed `UnresolvedFundingRequirement`. Stage 2 must
  translate unresolved valuation and funding states into the established
  structured unavailable / N/A representation with a specific reason on the API
  and presentation surfaces, and must not expose them as a generic server
  error, fabricate an amount, or collapse them into zero.

Stage 2 persistence and the later memo, AI, and reporting stages each require a
separate explicit human start.

After P7.10, the ratified sequence ends with **P7.11 Competition Closeout**.
Refinancing / recapitalization remains a separately authorized potential
sub-gate.

A bounded stabilization sweep remains available for separate human
authorization. It is not automatically active. Its source issues are:

- #26: product polish and technical-debt backlog
- #29: multifamily rent-roll abstraction improvements
- #30: negative forward exit-NOI error presentation

Do not treat #29 as authority to redesign the Lease-Level engine inside a
polish gate. A full multifamily abstraction is separate product scope. Small
unit-label, validation, diagnostic, and regression-fixture improvements may be
scoped independently.

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
- P7.9 Partnership Waterfalls + Investor Returns:
  `docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md` — **implemented and human
  accepted; P7.9 is closed.**
- AM1 Managed Assets + Monthly Performance:
  `docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md` — **implemented
  and human accepted.** It remains an independent post-acquisition feature,
  not P7.10.
- Asset Types 1 classification:
  `docs/architecture/ASSET_TYPES_1_CLASSIFICATION.md` — **implemented and human
  accepted.** It starts no later Asset Types phase.
- Excel Export 1 Quick Underwrite formula audit:
  `docs/architecture/EXCEL_EXPORT_1_QUICK_FORMULA_AUDIT.md` — **implemented and
  human accepted.**
- Excel Export 2 Detailed Underwrite formula audit:
  `docs/architecture/EXCEL_EXPORT_2_DETAILED_FORMULA_AUDIT.md` — **implemented
  and human accepted.**
- Excel Export 3 Lease-Level Underwrite formula audit:
  `docs/architecture/EXCEL_EXPORT_3_LEASE_LEVEL_FORMULA_AUDIT.md` — **implemented
  and human accepted.**
- P7.10 Valuation Timepoints, Investment Memo, and Institutional Reporting:
  `docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md` — **ratified
  2026-09-20; Stage 1 implemented, merged, and human accepted at `f6f3680`;
  Stages 2-4 not started.**

## Historical-Document Rule

Documents under `docs/plans/` are frozen design and gate records. Documents
under `docs/solutions/` are lessons and patterns, some inherited from the
Mini-Anchor predecessor. They may intentionally contain old paths, branch
names, baselines, test counts, and statements about what had not yet shipped
at the time. Use them for rationale and invariants, never for live status.

When a historical statement conflicts with this file only about current state,
this file governs. When a financial convention conflicts, stop and resolve the
applicable ratified authority; this file has no power to change economics.
