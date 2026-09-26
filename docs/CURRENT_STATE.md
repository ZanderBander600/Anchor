# Anchor Current State

Last synchronized: 2026-09-26 (P7.10 closed; P7.11 waived and administratively
closed; Refinance & Capital Events V1 contract ratified; Stage 1 deterministic
engine merged through PR #57 and accepted; Stage 2 persistence and integration
merged through PR #60 and accepted; Stage 3 product surfaces merged through
PR #62 and accepted; Refinance & Capital Events V1 complete for its ratified
V1 scope; UI/UX workstation refinement implemented on a feature branch and
awaiting human review -- not accepted)

This is the single live status record for Anchor. It reports project state; it
does not replace any financial convention or architecture authority. Update it
whenever an accepted gate merges or the active gate changes.

## Accepted Baseline

- Repository: `ZanderBander600/Anchor`
- **Last accepted product implementation commit: `main` at `b941582`** (PR #62,
  Refinance & Capital Events V1 Stage 3 product surfaces). This is the newest
  commit that changed product behavior. Without a refinance, every result is
  presented as before and Excel Exports 1–3 stay byte-identical. The previous
  product implementation commits were `879f577` (PR #60, Stage 2), `6de7644`
  (PR #57, the Stage 1 engine) and `d7e4d75` (PR #53, P7.10 Stage 4).
- **Documentation-only work since then:** the **P7.10 Stage 4 acceptance
  documentation merged through PR #54**, and the P7.10 closeout / P7.11 waiver
  record described below. They change status and architecture records only;
  they change no calculation, convention, schema, fingerprint, API contract,
  workbook, or product behavior.
- **This acceptance record's branch started from `main` at `b941582`.** That is
  the branch point, not a claim about where `main` sits once the record merges.
  **Git and GitHub remain operational truth for the current `main` commit.**
- Last financial-engine implementation merge: `6de7644` (PR #57, Refinance &
  Capital Events V1 Stage 1 deterministic engine). The previous one was
  `f6f3680` (PR #49, P7.10 Stage 1 deterministic valuation and `PctOfValue`
  closing execution).
- **Accepted baseline: `main` at `b941582`** (the PR #62 merge of the accepted
  Refinance & Capital Events V1 Stage 3 product surfaces; reviewed head
  `79250eb`). It is the product merge, not the later documentation-only
  acceptance merge.
- **Active gate: none.** Refinance & Capital Events V1 Stages 1, 2 and 3 are
  **accepted**, and V1 is complete for its ratified V1 scope. P7.10 is closed,
  and P7.11 is waived and administratively closed. No gate begins by
  implication; the next one starts only on an explicit human instruction.
- Autopilot: off; the manual Claude Code -> independent review -> human merge
  workflow is active.
- Autonomous merge: not authorized.
- Autonomous next-gate transition: not authorized.

Git and GitHub remain operational truth for the exact current HEAD and open PR
state. If `main` moves beyond the accepted baseline above, inspect the
intervening merge before updating this file.

## 2026-09-26 UI/UX Workstation Refinement (implemented; awaiting human review)

By explicit human instruction, a presentation and interaction refinement of
the whole workstation was implemented from `main` at `278a84f` on
`claude/compassionate-keller-hi5y87`. **It is not accepted and not merged**;
the accepted baseline above is unchanged.

- Scope: a shared design system (`web/src/workstation.css`, documented in
  `docs/design/WORKSTATION_DESIGN_SYSTEM.md`), converged colour tokens, and
  refined shell, headers, navigation, tables, metrics, editors (Capital
  Structure, Refinance, Partnership), Investment Committee and Asset
  Management surfaces, with responsive and accessibility QA.
- No calculation, convention, schema, fingerprint, persistence, API shape,
  workbook or published artifact changed. One backend presentation string
  changed: a Partner Decision Matrix IRR reason no longer prints the engine's
  internal status token (typed `irr_status` and `reason` unchanged).
- It starts no product gate. **Active gate: none.**

## 2026-09-25 Refinance & Capital Events V1 Stage 3 Acceptance

By explicit human instruction, Refinance & Capital Events V1 Stage 3 --
product surfaces, refinance-aware reporting and the refinance formula-audit
export -- is **accepted** on 2026-09-25.

- Stage 3 PR: #62 (https://github.com/ZanderBander600/Anchor/pull/62), 15
  commits: the seven original Stage 3 commits `ef2711f` to `c5d8b9d`,
  unchanged, and eight correction commits `8b8b459` to the independently
  reviewed head `79250eb`.
- Merged to `main` on 2026-09-25 as `b941582` (parents `bd77433` and
  `79250eb`). The merged product tree is identical to the reviewed head.
- **The accepted baseline advances to `main` at `b941582`**, the product
  merge, not this later documentation-only acceptance merge.
- **Stage 1 remains accepted** at `6de7644`, and **Stage 2 remains accepted**
  at `879f577`.
- **The temporary Stage 2 refinance-reporting gate
  (`refinance_reporting_not_available`) is removed** by accepted Stage 3.
  Refinance-aware memo, report and PDF presentation replaces it; publication
  refuses only an unexecuted refinance (`refinance_result_unavailable`).
- **All three Refinance & Capital Events V1 stages are accepted. Refinance &
  Capital Events V1 is complete for its ratified V1 scope.**
- **Active gate: none.** No subsequent phase starts automatically.
- **Recovery Engine V2: not started.**
- **Upload / extraction integration: deferred.**
- The reviewed head's final verification: full frontend suite 94 files and
  2,349 tests passed at `79250eb`; full backend 11,528 passed, 297 skipped;
  native Excel 742 passed; architecture guards 2,194 backend and 329 frontend
  passed; TypeScript, lint, build and Pyright at baseline; browser QA at 1440
  and 390 px. It is recorded in PR #62 and in Section 25 of the contract.
- This entry is documentation only. It changes no calculation, convention,
  schema, fingerprint, API contract, workbook or product behavior.

## 2026-09-24 Refinance & Capital Events V1 Stage 3 (implemented; accepted 2026-09-25)

By explicit human instruction, Stage 3 -- product surfaces, refinance-aware
reporting and the refinance formula-audit export -- was started from `main` at
`bd77433` (the PR #61 acceptance-record merge, whose product tree is the
accepted Stage 2 baseline `879f577`) on
`feature/refinance-capital-events-v1-stage-3-product-surfaces`.

- **Implementation was completed on the feature branch** (the start record
  `ef2711f`, then `1952683`, `3696254`, `e9660af`, `68a497c`, `1984eb7` and its
  tests, guards and record `c5d8b9d`), **corrected after independent review**
  in eight normal commits `8b8b459` to `79250eb` (contract Section 25.7),
  published, and **merged through PR #62 as `b941582`**. It was accepted on
  2026-09-25 (see the entry above). The temporary
  `refinance_reporting_not_available` report gate is removed.
- Until its acceptance, the accepted baseline stayed `main` at `879f577`. On
  acceptance it advanced to `main` at `b941582`.
- Stage 1 and Stage 2 remain accepted; their engine and persistence are not
  reopened.
- Its scope is the contract's Section 20 Stage 3 row. The ratified Stage 3
  refinance formula-audit export sub-contract and the implementation record
  are Section 25 of `docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`.
- **Recovery Engine V2: not started.**
- **Upload / extraction integration: deferred.**

## 2026-09-24 Refinance & Capital Events V1 Stage 2 Acceptance

By explicit human instruction, Refinance & Capital Events V1 Stage 2 --
persistence and integration -- is **accepted**.

- Stage 2 PR: #60 (https://github.com/ZanderBander600/Anchor/pull/60), 15
  commits from `34db116` to the independently reviewed head `ff12d04`.
- Merged to `main` on 2026-09-24 as `879f577` (parents `f2b5cef` and
  `ff12d04`). The merged product tree is identical to the reviewed head.
- **The accepted baseline advances to `main` at `879f577`.**
- **Stage 1 remains accepted** at `6de7644`; its engine stayed byte-frozen
  through Stage 2.
- **The temporary report gate is part of accepted Stage 2.** A memo whose
  selected Capital Structure configures a capital event is neither published
  nor previewed (`refinance_reporting_not_available`) until Stage 3 provides
  refinance-aware reporting.
- **Stage 3: not started.** It requires an explicit start. No frontend
  refinance workstation or refinance-aware report exists.
- **Active gate: none.**
- **Recovery Engine V2: not started.**
- **Upload / extraction integration: deferred.**
- This entry is documentation only. It changes no calculation, convention,
  schema, fingerprint, API contract, workbook or product behavior, and reports
  no new verification evidence. The reviewed verification is recorded in PR
  #60 and in Section 24 of the contract.

## 2026-09-24 Refinance & Capital Events V1 Stage 2 (implemented; accepted 2026-09-24)

By explicit human instruction, Stage 2 -- persistence and integration -- was
started from `main` at `f2b5cef` (the PR #59 merge, whose product tree is the
accepted Stage 1 baseline `6de7644`) on
`feature/refinance-capital-events-v1-stage-2-persistence-integration`.

- **Stage 1 remains accepted at `6de7644`**, and its engine is byte-frozen
  through Stage 2.
- **Implementation was completed on the feature branch, independently reviewed
  in three rounds, published, and merged through PR #60 as `879f577`.** It was
  accepted on 2026-09-24 (see the entry above).
- **The first review's corrections** (contract Section 24.10): exact-scope
  evidence, fingerprints and publication, and typed message propagation.
- **The second review's corrections** (contract Section 24.11): the temporary
  report gate, the additive P7.10 `EVIDENCE_NOT_APPROVED` valuation reason,
  typed consumers with truthful refusal wording, exact-scope report rows, and a
  hardened consumption record.
- **The third review's correction** (contract Section 24.12): an
  Investment-scoped value reports `evidence_not_approved` only when evidence is
  the sole cause; a mixed cause keeps `valuation_unavailable` /
  `incomplete_units`.
- None of the corrections changed a ratified financial decision.
- **Stage 3 has not started.** It alone removes the temporary report gate,
  once refinance-aware returns, memo sections and headlines exist and are
  tested.
- Until its acceptance, the accepted baseline stayed `main` at `6de7644`. On
  acceptance it advanced to `main` at `879f577`.
- Its scope is the contract's Section 20 Stage 2 row: an additive schema
  version, the codec, fingerprints, Strategy whole-domain resolution with
  events, P-8 event identity, the LTV-only consumed-valuation publication
  dependency, typed API states and primary-view facts, and F13, F18 and F20.
  Its implementation record is Section 24 of
  `docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`.

## 2026-09-24 Refinance & Capital Events V1 Stage 1 Acceptance

By explicit human instruction, Refinance & Capital Events V1 Stage 1 is
**accepted**.

- Stage 1 PR: #57 (https://github.com/ZanderBander600/Anchor/pull/57), five
  commits `a4dc802`, `1171f17`, `c08c4a1`, `cbebaa2`, `4f248e7`; the
  production and test tree is the independently reviewed `cbebaa2` tree.
- Merged to `main` on 2026-09-24 as `6de7644` (parents `2e1f84a` and
  `4f248e7`).
- **The accepted baseline advances to `main` at `6de7644`.**
- **Stage 2 and Stage 3: not started.** Stage 2 requires an explicit start.
- **Recovery Engine V2: not started.**
- **Upload / extraction integration: deferred.**
- This entry is documentation only. It changes no calculation, convention,
  schema, fingerprint, API contract, workbook or product behavior, and reports
  no new verification evidence.

## 2026-09-22 Refinance & Capital Events V1 Stage 1 (implemented; accepted 2026-09-24)

By explicit instruction, Stage 1 -- the deterministic refinance engine -- was
started from `main` at `2e1f84a` on
`feature/refinance-capital-events-v1-stage-1-engine`.

- **Implementation was completed on the feature branch, published, and merged
  through PR #57 as `6de7644`.** It was accepted on 2026-09-24 (see the entry
  above).
- Its scope is the contract's Section 20 Stage 1 row only: the refinance
  contracts and validation, the engine's acquisition-debt balance service
  (R-M), sizing on separate LTV value and DSCR forward-NOI dependencies,
  retirement, replacement scheduling, the event bridge, the Common Equity
  decomposition, typed unavailable states, and the one P7.9 adapter reason.
- No persistence, schema, codec, fingerprint, API, frontend, memo, report or
  workbook changed. Without a refinance, every result is bit-identical to the
  accepted product baseline.
- The implementation record, including the decisions a reviewer should check
  and every guard re-pin, is Section 23 of
  `docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`.
- **Stage 2 and Stage 3: not started.**
- **Recovery Engine V2: not started.**
- **Upload / extraction integration: deferred.**
- Until its acceptance, the accepted baseline stayed `main` at `2e1f84a`. On
  acceptance it advanced to `main` at `6de7644`.

## 2026-09-22 Refinance & Capital Events V1 Contract Ratified

By explicit instruction, the Refinance & Capital Events V1 contract-design
gate ran as documentation and architecture work only.

- **The contract is ratified.** `docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`
  was approved by Codex's independent architecture review on 2026-09-22. That
  approval incorporated two corrections:
  - a DSCR-only refinance consumes no valuation;
  - the legacy-payoff authority is an explicit, narrow engine extension.

  All decisions R-A to R-S are resolved in its Section 22, including the
  narrow amendments to P7.7, P7.8, P7.9 and P7.10 listed in Section 22.3.
- **Stage 1 deterministic engine: not started.** Stage 1 requires an explicit
  start. No implementation stage starts automatically. No engine, schema
  migration, API, UI, test, workbook or financial calculation has been
  written.
- **Recovery Engine V2: not started.**
- **Upload / extraction integration: deferred.**
- **The accepted baseline is unchanged:**
  - `main` is at `0e9f8cc`;
  - the last accepted product implementation commit is still `d7e4d75`;
  - this entry changes no calculation, convention, schema, fingerprint, API
    contract, workbook or product behavior.

## 2026-09-22 P7.10 Closeout and P7.11 Waiver

This is a documentation-only closeout recording explicit human decisions made
on 2026-09-22. It changes no calculation, convention, schema, fingerprint, API
contract, workbook, or product behavior, and it reports no new verification
evidence.

### P7.10 is closed

- **P7.10 is closed.**
- **P7.10 Stages 1, 2, and 4 are implemented and human accepted.**
- **P7.10 Stage 3 remained deferred and unstarted**, and was **explicitly not
  required for closeout.** It is not completed, accepted, passed, or fulfilled.

Each stage acceptance was recorded when it was made, on that stage's own
evidence, and is unchanged by this closeout.

Stage 3 — grounded AI memo proposals — was never started. Specifically, **no
P7.10 Stage 3 grounded memo-proposal module, prompt, proposal lifecycle,
grounding snapshot, AI snapshot, or product surface was built**, and two guards
prove that absence rather than asserting it. This statement is about Stage 3
only. It says nothing about Anchor's existing AI capability: the AI Analyst
interpretation and AI-assisted ingestion features remain in the product,
accepted and unchanged.

**A future grounded-AI proposal feature would require a separately authorized
new program.** Closing P7.10 neither silently starts nor cancels such a
program. The Stage 3 text in the P7.10 authority is a preserved design contract
for work that has not been done.

The full closeout record is Section 24 of
`docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`.

### P7.11 is waived and administratively closed

**P7.11 Competition Closeout is waived and administratively closed by explicit
human decision.** It was not run.

Specifically, and without ambiguity:

- **P7.11's five §17.3 fixtures were not executed.**
- **P7.11's independent source-model oracles were not built or consulted.**
- **P7.11's cross-feature acceptance exercise was not performed.**

No claim to the contrary is made anywhere, and none may be added.

**P7.11's closure is a scope decision, not evidence that an unperformed
acceptance exercise passed.** Read the P7.11 acceptance evidence as absent —
neither positive nor negative.

P7.11's original ratified contract is preserved unchanged in
`docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md` §17.3 and §19.2.
This closeout does not rewrite it and does not imply it was fulfilled.

The P7 authority owns the P7.11 contract and owns its waiver. **The waiver
record is Section 25 of
`docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`.** The P7.10
document is not the authority for P7.11 and only notes the waiver in passing.

### What the accepted implementation still rests on

Waiving P7.11 withdraws no evidence that already exists. **The accepted P7
implementation remains supported by the gate-specific automated evidence, the
completed acceptance sweeps, and the human acceptances already recorded** in
this file and in each gate's architecture record. That evidence is gate-scoped;
it is not a substitute for the cross-feature exercise P7.11 described, and this
closeout does not present it as one.

### Scope of this closeout

This closeout starts nothing. Upload / extraction work, new AI surfaces,
collaboration expansion, and productionization all remain outside it, as do
Refinancing & Capital Events and Recovery Engine V2 (see **Next Work**).

## 2026-09-21 P7.10 Stage 4 Acceptance

The human explicitly accepted P7.10 Stage 4 after PR #53 merged to `main` at
`d7e4d75`. The accepted scope is the manual-first Investment Committee memo
library and workstation, valuation and decision-support presentation, claim-
level evidence workflow, preview and immutable publication flow, version
history, institutional report, exact issued PDF, responsive accessibility, and
cross-mode browser and rendered-PDF QA.

Schema version 16's single additive report-artifact table freezes the canonical
report document and exact PDF bytes atomically with each new memo version.
Later underwriting or presentation changes may alter current freshness but
never alter what the committee received. Versions published before schema 16
remain readable and honestly report that no issued report snapshot exists.

The Investment Committee decision remains a separate act under R-F. A decision
recorded after publication appears in the workspace and version history but
does not rewrite the issued report or PDF.

This acceptance does not start Stage 3, P7.11, refinancing, another reporting
format, or any AI proposal workflow. P7.10 remains open pending an explicit
human decision on its deferred Stage 3 and final closeout.

## 2026-09-21 P7.10 Stage 4 Implementation (accepted)

Stage 4 was explicitly started from accepted `main` at `9ca957a` and is
implemented on `feature/p7-10-stage-4-memo-workstation-report`, merged through
PR #53, and human accepted at `d7e4d75`. It does not start Stage 3 or P7.11.

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
Committee memo workstation, the institutional report on screen, the exact PDF
export, and desktop and 390px browser QA. It adds the `anchor.reporting`
presentation package, four read-only API routes, the memo frontend, and schema
version 16's one additive immutable-artifact table. It adds no financial
calculation and redefines no Stage 1 or Stage 2 authority.

The accepted clarifications in Section 23 include:

- publication freezes a canonical typed report document and exact PDF bytes in
  one transaction; published values are never recomputed;
- current freshness is presented outside the frozen historical artifact;
- a later Investment Committee decision remains separate and does not rewrite
  the issued document;
- Stage 4 translates stable unavailable `reason_code` values into analyst-
  facing labels and never exposes opaque record ids;
- Anchor stores no market or location, so the concept's unsupported location
  line and Market Snapshot are omitted rather than invented;
- ReportLab is the accepted deterministic PDF renderer.

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
- P7.10 Stage 4 manual-first Investment Committee workstation, immutable
  institutional report and PDF, and cross-mode browser QA, human accepted
- P7.10 Valuation Timepoints, Investment Memo, and Institutional Reporting,
  **closed 2026-09-22**. Stages 1, 2 and 4 are implemented and human accepted;
  Stage 3 remained deferred and unstarted and was explicitly not required for
  closeout — it is not completed, accepted, passed, or fulfilled
- P7.11 Competition Closeout, **waived and administratively closed 2026-09-22**
  by explicit human decision. It was not run; its fixtures, oracles and
  cross-feature acceptance exercise were not executed
- Refinance & Capital Events V1, **complete for its ratified V1 scope
  2026-09-25**: Stage 1 deterministic engine (`6de7644`), Stage 2 persistence
  and integration (`879f577`) and Stage 3 product surfaces (`b941582`), each
  human accepted

## Next Work

**There is currently no active development gate.** P7.10 is closed and P7.11 is
waived and administratively closed (see the 2026-09-22 closeout above). No gate
begins by implication; the next one starts only on an explicit human
instruction.

**Refinancing & Capital Events** and **Recovery Engine V2** were named as the
next product priorities at the P7.10 closeout. Neither was started or ratified
by that closeout. Each needs its own explicit authorization, its own contract,
and its own gate record before any work begins. Their status is now:

- **Refinance & Capital Events V1:** contract ratified on 2026-09-22. Stage 1
  (deterministic engine) was explicitly started from `2e1f84a`, merged
  through PR #57 as `6de7644`, and **accepted** on 2026-09-24 (see the
  entries above). Stage 2 (persistence and integration) was explicitly started
  from `f2b5cef`, merged through PR #60 as `879f577`, and **accepted** on
  2026-09-24. Stage 3 (product surfaces) was explicitly started from
  `bd77433`, merged through PR #62 as `b941582`, and **accepted** on
  2026-09-25. **Refinance & Capital Events V1 is complete for its ratified V1
  scope.** The contract, not this file, holds the design decisions.
- **Recovery Engine V2:** unstarted and unratified.

**Recovery Engine V2 is a successor gate, not a first implementation.** Anchor
already has accepted recovery functionality: the Lease-Level D3 recoveries
implementation is complete and in the product. Nothing here should be read as
saying Anchor lacks recovery capability. What is unstarted and unratified is
specifically Recovery Engine V2.

Also explicitly outside this closeout, and unstarted: upload / extraction work,
new AI surfaces — meaning surfaces beyond the existing accepted AI Analyst
interpretation and AI-assisted ingestion, including any future grounded-AI memo
proposal feature, which would require a separately authorized new program —
collaboration expansion, and productionization.

A bounded stabilization sweep remains available for separate human
authorization. It is not automatically active. Its source issues are:

- #26: product polish and technical-debt backlog
- #29: multifamily rent-roll abstraction improvements
- #30: negative forward exit-NOI error presentation

Do not treat #29 as authority to redesign the Lease-Level engine inside a
polish gate. A full multifamily abstraction is separate product scope. Small
unit-label, validation, diagnostic, and regression-fixture improvements may be
scoped independently.

### Retained P7.10 accepted-scope record

The rest of this section describes the accepted P7.10 implementation and its
boundaries. It is a record of completed, accepted work, not a queue.

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
started **ahead of** Stage 3, implemented, merged, and accepted. Stage 3
(grounded AI proposals) remains deferred and unstarted; Stage 4 neither starts
it nor depends on it.

Stage 4's independent-review corrections are accepted and recorded in Sections
23.2 and 23.9 of the P7.10 authority. The load-bearing ones are:

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

**P7.11 Competition Closeout was never started.** It was waived and
administratively closed on 2026-09-22 by explicit human decision, and it is not
queued work.
Its five §17.3 fixtures, independent source-model oracles, and cross-feature
acceptance exercise were **not executed**. Its closure is a scope decision, not
evidence that an unperformed acceptance exercise passed.

Refinancing / recapitalization was a separately authorized potential sub-gate
in the ratified P7 sequence. Its V1 contract is ratified, and its Stage 1
engine is merged (PR #57, `6de7644`) and accepted; Stage 2 is merged (PR #60,
`879f577`) and accepted; Stage 3 is merged (PR #62, `b941582`) and accepted,
completing V1 for its ratified scope; see **Refinancing & Capital Events**
above.

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
- P7: `docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md` — **P7.1
  through P7.9 complete and human accepted. P7.10 closed 2026-09-22, with
  Stages 1, 2 and 4 implemented and human accepted and Stage 3 deferred,
  unstarted, and explicitly not required for closeout. P7.11 waived and
  administratively closed 2026-09-22 without being run; this document owns the
  waiver record, in its Section 25.** Its §17.3 fixtures and §19.2 gate
  sequence are preserved as the original ratified contract, not as fulfilled
  work.
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
  implemented, merged, and human accepted at `d7e4d75`, with its implementation
  record and every ratified clarification in Section 23; Stage 3 deferred and
  unstarted and explicitly not required for closeout. P7.10 closed 2026-09-22 —
  closeout record in Section 24. The P7.11 waiver is recorded in Section 25 of
  the P7 authority, not here.**
- Refinance & Capital Events V1:
  `docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md` — **ratified
  2026-09-22** (Codex independent architecture approval, Corrections 1 and 2
  incorporated). It is the authority for its narrow amendments to P7.7, P7.8,
  P7.9 and P7.10 (its Section 22.3). **Stage 1 accepted 2026-09-24, merged
  through PR #57 as `6de7644`** (its Section 23); **Stage 2 accepted
  2026-09-24, merged through PR #60 as `879f577`** (its Section 24); **Stage
  3 accepted 2026-09-25, merged through PR #62 as `b941582`** (its Section
  25). **V1 is complete for its ratified V1 scope.**

## Historical-Document Rule

Documents under `docs/plans/` are frozen design and gate records. Documents
under `docs/solutions/` are lessons and patterns, some inherited from the
Mini-Anchor predecessor. They may intentionally contain old paths, branch
names, baselines, test counts, and statements about what had not yet shipped
at the time. Use them for rationale and invariants, never for live status.

When a historical statement conflicts with this file only about current state,
this file governs. When a financial convention conflicts, stop and resolve the
applicable ratified authority; this file has no power to change economics.
