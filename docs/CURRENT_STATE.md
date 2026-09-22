# Anchor Current State

Last synchronized: 2026-09-21 (P7.10 Stage 4 implemented, pending review)

This is the single live status record for Anchor. It reports project state; it
does not replace any financial convention or architecture authority. Update it
whenever an accepted gate merges or the active gate changes.

## Accepted Baseline

- Repository: `ZanderBander600/Anchor`
- Accepted repository and product implementation baseline: `main` at `ababa50`
  (PR #51, P7.10 Stage 2 persistence, fingerprints, Investment Memo domain,
  immutable versioning, unavailable-state adapter, and typed API).
- Last financial-engine implementation merge: `f6f3680` (PR #49, P7.10 Stage
  1 deterministic valuation and `PctOfValue` closing execution).
- Active gate: **P7.10 Valuation Timepoints + remaining Decision Support / AI
  integration.** The P7.10 contract is **ratified**; decisions R-A through R-J
  are closed within the gate and recorded in Section 20 of
  `docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`, the ratified
  authority. **Stage 1 is implemented, merged, and human accepted at
  `f6f3680`. Stage 2 is implemented, merged, and human accepted at
  `ababa50`.** **Stage 4 is implemented and pending independent review and
  human acceptance**; it is not merged and not accepted. **Stage 3 is deferred
  and unstarted**, and Stage 4 neither starts it nor depends on it.
- Autopilot: off; the manual Claude Code -> independent review -> human merge
  workflow is active.
- Autonomous merge: not authorized.
- Autonomous next-gate transition: not authorized.

Git and GitHub remain operational truth for the exact current HEAD and open PR
state. If `main` moves beyond the accepted baseline above, inspect the
intervening merge before updating this file.

## 2026-09-21 P7.10 Stage 4 Implementation (pending review)

Stage 4 was explicitly started from accepted `main` at `9ca957a` and is
implemented on `feature/p7-10-stage-4-memo-workstation-report`. It is **not
merged, not accepted, and does not start Stage 3 or P7.11.**

The human explicitly authorized Stage 4 **ahead of** Stage 3. That ordering is
recorded as a contract clarification in Section 23 of the P7.10 authority:

- **Stage 3 is optional and deferred**, not cancelled and not implicitly begun.
- **Stage 4 does not depend on Stage 3** and is manual-first: it works
  completely with manually authored memo content.
- No empty AI panel, disabled AI control, placeholder prompt or "coming soon"
  surface appears anywhere in the product, and two guards prove that absence
  rather than asserting it.
- A future explicitly authorized Stage 3 may integrate proposals into the
  accepted workstation without changing its financial or publication authority.

Its scope is Section 17's Stage 4 list and nothing else: the Investment
Committee memo workstation, the institutional report on screen, the PDF export,
and desktop and 390px browser QA. It adds one presentation package
(`anchor.reporting`), four read-only API routes and fourteen frontend modules.

**It adds no schema change, no migration, and no financial calculation.** Stage
1's valuation package and Stage 2's memo package are byte-identical to their
accepted merges; Stage 4 presents them and redefines neither.

Four things a reviewer should look at deliberately, each recorded with its
reasoning in Section 23:

- a published version freezes its content, evidence and valuations but not its
  returns, so those are **recomputed** from the cell the version recorded and
  the freshness check says whether they still match. A stale version exports,
  watermarked, and is never rewritten;
- the Stage 2 unavailable `reason` names records by their opaque ids, so Stage 4
  translates the stable `reason_code` instead of repeating the message;
- **Anchor stores no market or location**, so the concept's location line and
  market panel are omitted rather than invented;
- **ReportLab was added.** Anchor had no PDF generator at all, and Section 13.3
  requires a paginated institutional report. It is the same shape of dependency
  as XlsxWriter, and under `invariant=1` two exports of one version are
  byte-identical.

Browser and rendered-PDF QA found six defects, all fixed and all recorded in the
commit that fixes them: an unbounded request loop, internal ids in an analyst
view, raw ISO timestamps, a currency figure broken across two lines, PDF
typography and orphan headings, and a 311px horizontal page scroll at 390px
caused by an absolutely positioned screen-reader label escaping its scroll
region.

## 2026-09-21 P7.10 Stage 2 Acceptance

The human explicitly accepted P7.10 Stage 2 after PR #51 merged to `main` at
`ababa50`. The accepted scope is schema version 15's nineteen additive tables,
persisted valuation definitions and claim-level Evidence References, the
Investment Memo domain, one mutable draft and immutable published versions,
the layered dependency ledger and precise stale reasons, the structured
unavailable / N/A adapter, and the typed backend API.

The accepted publication gate validates selected or consumed valuation
dependencies, not unrelated exploratory definitions. Published versions freeze
their selected and consumed valuations, structured memo content, dependency
ledger, Evidence References, and claim-to-evidence relationships.

This acceptance does not start grounded AI proposals, the Memo workstation,
institutional PDF reporting, browser QA, Stage 3, Stage 4, or P7.11.

## 2026-09-21 P7.10 Stage 2 Corrections (accepted)

Independent review approved Stage 2 in principle subject to two focused
contract corrections. Both were implemented, merged through PR #51, and human
accepted at `ababa50`. Their acceptance does not start Stage 3.

- **Publication validates the dependencies, not the workspace.** A valuation
  blocks publication only where the memo *selected* it for inclusion or a
  `PctOfValue` funding of the selected Capital Structure *consumed* it.
  Selection is an explicit stored relationship, never inferred from display
  order, existence or recency, and a refusal carries the valuation's own
  structured reason code. An exploratory definition no longer forces an analyst
  to delete their working view in order to publish.
- **Evidence is traceable to the individual claim (R-G).** Every claim-bearing
  memo item links to zero or more Evidence References as normalized rows;
  publishing freezes those relationships into the immutable version, and no
  later draft edit, relink or deletion reaches the frozen copy. Link changes
  participate in the memo-content fingerprint and in stale analysis. Evidence
  stays traceable and never mandatory.

Both are recorded with their reasoning in Sections 22.6 and 22.7 of the P7.10
authority, which now state the ratified resolutions rather than the two
superseded judgements. Schema version 15 accordingly declares **nineteen**
additive tables; the migration is unchanged in kind.

## 2026-09-20 P7.10 Stage 2 Implementation (accepted)

Stage 2 was explicitly started from accepted `main` at `46650a7`, implemented
on `feature/p7-10-stage-2-memo-persistence-api`, merged through PR #51, and
human accepted at `ababa50`. It does not start Stage 3.

Its scope is Section 17's Stage 2 list and nothing else: schema version 15's
nineteen purely additive tables, persisted valuation definitions and Evidence
References, the Investment Memo domain with one mutable draft and immutable
published versions, the layered dependency ledger and precise stale reasons,
the structured unavailable / N/A adapter Section 6.2 obliges, and 24 typed API
routes.

It adds no frontend file, no AI surface, no prompt, no PDF and no report
layout. The `PctOfValue` closing-only boundary in Section 6.1 is unchanged: a
later Stabilized or Custom valuation resolves to a real reporting value that no
funding event can consume, reported with a named reason rather than a zero.

Two changes a reviewer should look at deliberately, both recorded with their
reasoning in Section 22 of the P7.10 authority:

- a valuation a `PctOfValue` rule **consumes** now participates in the
  structured source fingerprint, as Section 6 requires. Every structured digest
  that existed before this gate is preserved byte for byte, because the payload
  joins only when non-empty;
- the P7.8B refusal of a `pct_of_value` amount rule at the authoring door was
  retired. Its own message said the rule "arrives with valuation timepoints",
  and they have arrived; without this the capability Stage 1 activated would be
  unreachable through the product.

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
- P7.10 Stage 2 persistence, fingerprints, Investment Memo domain, immutable
  versioning, unavailable-state adapter, and typed API, human accepted

## Next Work

**P7.10 Valuation Timepoints + remaining Decision Support / AI integration**
remains the current program. Its contract is ratified; decisions R-A through
R-J are closed within this gate and recorded in Section 20 of
`docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`. Stage 1 is implemented,
merged, and human accepted. **Stage 2 is implemented, merged, and human
accepted at `ababa50`; its two ratified review corrections are part of the
accepted implementation.** **Stage 4 is implemented and awaiting review and
human acceptance.** **Stage 3 is deferred and unstarted.**

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

Stage 2 was separately started, implemented, merged, and accepted. Stage 4
(the Memo workstation, institutional report and PDF export) was then explicitly
started **ahead of** Stage 3 and is implemented, pending review. Stage 3
(grounded AI proposals) remains deferred and unstarted; Stage 4 neither starts
it nor depends on it, and accepting Stage 4 would not begin it.

Stage 4 has since had **one round of independent review**, whose four required
corrections are implemented on the branch and are also pending review. They are
recorded in Sections 23.2 and 23.9 of the P7.10 authority, and the load-bearing
ones are:

- **A published memo version's report and PDF are frozen.** Publication stores
  the issued report and the exact PDF bytes, so what a committee read does not
  change when the underwriting, the Strategy, the Scenario, the capital
  structure, the Partnership, a valuation definition or the presentation code
  does. Schema **version 16** adds exactly one additive table for it; no table
  is altered and no existing row is rewritten. The write is atomic with the
  publication, and no supported operation updates or deletes a stored report or
  PDF.
- **Versions published before schema 16** stay fully readable, gain no report,
  and answer the report and PDF routes with the typed
  `REPORT_SNAPSHOT_NOT_AVAILABLE` state telling the analyst to publish a new
  version. They are **not** backfilled by recomputation.
- **A published artifact and current freshness are different questions.** The
  workspace says beside a historical version that the analysis has moved, in
  analyst-facing dependency names, outside the frozen document; the report
  itself gains no stale watermark and no replaced figure.
- **No native browser dialog appears in the memo workflow.** The memo-switch
  warning is an accessible in-application confirmation, and a guard forbids
  `confirm`, `alert` and `prompt` in every Stage 4 production file.
- **Cross-mode browser QA is complete** at 1440px and 390px over all twelve
  enumerated cases, against an isolated QA database, with every page of the
  representative PDFs inspected. It found three substantive defects -- absent
  partner returns on every Partner-perspective memo, backend sentences naming
  records by their opaque ids on analyst surfaces, and a dead PDF link on
  pre-v16 versions -- all fixed with regression tests. Section 23.10 records the
  QA and its findings in full.

**P7.11 Competition Closeout has not started.** Finishing Stage 4 does not
start it.

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
  Stage 2 implemented, merged, and human accepted at `ababa50`, with its
  implementation record and every ratified clarification in Section 22; Stage 4
  implemented and pending review, with its implementation record in Section 23;
  Stage 3 deferred and unstarted.**

## Historical-Document Rule

Documents under `docs/plans/` are frozen design and gate records. Documents
under `docs/solutions/` are lessons and patterns, some inherited from the
Mini-Anchor predecessor. They may intentionally contain old paths, branch
names, baselines, test counts, and statements about what had not yet shipped
at the time. Use them for rationale and invariants, never for live status.

When a historical statement conflicts with this file only about current state,
this file governs. When a financial convention conflicts, stop and resolve the
applicable ratified authority; this file has no power to change economics.
