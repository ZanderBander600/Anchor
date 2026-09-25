# P7.10 Valuation Timepoints, Investment Memo, and Institutional Reporting

Status: **Ratified and closed.** P7.10 was explicitly started on 2026-09-20
from accepted `main` at `9c65843` (PR #48). Decisions R-A through R-J were
ratified on 2026-09-20 by the human's delegation of P7.10 architecture
ratification; the completed ratification record is Section 20. **P7.10 was
closed by explicit human decision on 2026-09-22. Stages 1, 2 and 4 are
implemented and human accepted; Stage 3 remained deferred and unstarted and was
explicitly not required for closeout.** The closeout record is Section 24.

Stage status:

- **Stage 1 is implemented, merged, and human accepted.** PR #49 merged to
  `main` at `f6f3680` on 2026-09-20. It delivers the deterministic valuation
  layer and `PctOfValue` **closing** execution, and nothing else. Its boundary
  is Section 6.1 and its Stage 2 obligation is Section 6.2.
- **Stage 2 is implemented, merged, and human accepted.** PR #51 merged to
  `main` at `ababa50` on 2026-09-21. It delivers persistence, the Investment
  Memo domain, versioning, the unavailable-state adapter and the typed API, and
  nothing else. Its ratified implementation clarifications are Section 22.
- **Stage 3 remained deferred and unstarted**, and was **explicitly not
  required for P7.10 closeout**. It is not completed, accepted, passed, or
  fulfilled. It is optional, not cancelled, and it is not implied by anything
  Stage 4 delivers. No part of it was built, and closing P7.10 neither started
  nor cancelled it.
- **Stage 4 is implemented, merged, and human accepted.** PR #53 merged to
  `main` at `d7e4d75` on 2026-09-21. It delivers the Investment Committee memo
  workstation, the institutional report, PDF export and browser QA, and nothing
  else. Its ratified implementation record is Section 23.
- **Finishing Stage 1 does not automatically start Stage 2, accepting Stage 2
  does not start Stage 3, and Stage 4 does not start Stage 3 either.**

Gate: P7.10

Risk tier: Tier 1 for valuation and `PctOfValue` closing execution; Tier 2 for
persistence, fingerprints, memo versioning, and AI grounding; Tier 3 for the
Memo workspace, institutional report, PDF generation, and browser behavior.

This document specializes the ratified P7 authority in
`P7_COMPETITION_DECISION_ARCHITECTURE.md`. It does not reopen that document's
financial conventions. Where this contract is silent, the ratified P7, D6,
underwriting-mode, Capital Structure, and Partnership authorities continue to
govern.

---

## 1. Product outcome

P7.10 turns Anchor's deterministic underwriting and decision comparisons into
a defensible investment decision package. An analyst can:

1. select one Investment, Strategy, Scenario, and decision perspective;
2. inspect As-Is, Stabilized, and Exit valuation views;
3. state the decision ask, recommendation, conditions, thesis, risks,
   mitigants, terms, and dealbreakers;
4. ask AI to draft narrative from approved Anchor results and approved
   evidence;
5. accept or edit every narrative field;
6. publish an immutable, fingerprint-bound memo version; and
7. export a professional Investment Committee memorandum whose numerical
   appendices are assembled entirely from backend results.

The output answers: **what decision is requested, why this is the preferred
choice, what could invalidate it, and what authoritative result or approved
source supports every material claim?**

## 2. Frozen boundaries

The following are not design choices left to P7.10:

- The deterministic engine is the only source of financial calculations.
- D6's exit value is the only valuation that creates sale proceeds or cash.
- As-Is, Stabilized, and custom valuation views are reporting values unless a
  Capital Structure `PctOfValue` rule explicitly consumes one.
- A memo belongs to an Investment. Opting a standalone Deal into a memo may
  materialize its hidden one-unit Investment; it never changes the Deal.
- Strategy and Scenario resolution, consolidation, position returns,
  Partnership returns, and every Decision Matrix figure are reused. P7.10 does
  not reproduce them.
- AI may explain supplied results and draft prose. It may not calculate a
  value, delta, ranking, sensitivity, break-even, allocation, or return; select
  a Strategy; approve a recommendation; or invent a market fact.
- Memo prose and evidence never enter an underwriting financial fingerprint.
- Missing, stale, invalid, or unavailable information is never rendered as
  zero or silently omitted where the omission could mislead.
- P7.10 does not automatically start P7.11.

## 3. Scope

### 3.1 In scope

- hold-year-end valuation timepoints;
- As-Is, Stabilized, custom, and system Exit views;
- direct-cap and analyst-supplied valuation methods;
- unit and contemporaneous Investment-level valuations;
- closing execution of the already-representable Capital Structure
  `PctOfValue` rule (Section 6.1);
- a structured, analyst-authoritative Investment Memo;
- one mutable draft and immutable published memo versions;
- selection of a Strategy, Scenario, and Project / Position / Partner
  perspective for the recommendation;
- evidence references for qualitative memo claims;
- fingerprinted freshness and precise stale reasons;
- AI narrative proposals with field-level analyst approval;
- a Memo workspace and a deterministic report preview;
- a PDF Investment Committee memorandum with conditional appendices;
- existing sensitivity, break-even, Decision Matrix, Capital Structure,
  Partnership, and valuation availability presented honestly.

### 3.2 Out of scope

- live market-data, mapping, demographic, rent-comparable, or sales-comparable
  integrations;
- AI-generated or automatically approved recommendations;
- automatic stabilization detection;
- automatic cap-rate selection, appraisal, or purchase-price allocation;
- asset-type-specific underwriting logic, benchmarks, templates, or KPIs;
- new Lease-Level or Investment-level break-even solvers, which ratified
  Decision R-I excludes from P7.10;
- arbitrary-cell sensitivity;
- scenario probabilities, expected value, or Monte Carlo;
- refinancing or recapitalization;
- unit sales before the common exit date;
- tax modeling;
- Word, PowerPoint, or editable report exports;
- authentication, verified electronic signatures, or an IC voting system;
- storing generated PDFs as authoritative source records.

## 4. Vocabulary

| Term | Meaning |
| --- | --- |
| Valuation definition | Analyst-approved instructions for valuing units at one model month. |
| Valuation result | A deterministic value produced for one selected Analysis Variant. |
| As-Is | Closing-time reporting value. It is not purchase price and not automatically inferred from it. |
| Stabilized | Analyst-declared reporting value at a selected hold-year end. Anchor never auto-detects stabilization. |
| Exit | The existing D6 terminal value at the common exit month. It is system-derived and read-only. |
| Memo draft | The one mutable analyst workspace belonging to an Investment. |
| Memo version | An immutable publication of memo content plus the exact results it cites. |
| Analyst recommendation | The analyst's proposed action. It is not the committee's decision. |
| IC decision | A separately entered record of the committee outcome. It is never produced by AI. |
| Evidence reference | An approved source citation or analyst assertion supporting a qualitative memo claim. |
| Decision package | The selected variant, perspective, valuations, comparison figures, memo version, and report data assembled for export. |

## 5. Valuation definitions

### 5.1 Contract

The persisted definition is:

```text
ValuationTimepoint
  timepoint_id       stable opaque id; unique within the Investment
  investment_id      owner
  kind               AS_IS | STABILIZED | CUSTOM
  label              required analyst-facing label
  model_month        0 or a hold-year end, 12y, within the common horizon
  unit_instructions  exactly one instruction for every included unit

UnitValuationInstruction
  unit_id            an Investment member
  method             DIRECT_CAP(cap_rate) | ANALYST_VALUE(amount, evidence_id)
```

`EXIT` is reserved and is not stored as a `ValuationTimepoint`. The selected
variant's existing D6 exit NOI, exit cap, exit value, disposition costs, and
net sale proceeds produce the Exit view. There is no second exit calculation
and no user-editable Exit method in this contract.

### 5.2 Timing

- `AS_IS` must use model month 0.
- `STABILIZED` uses an analyst-selected hold-year end. It is never inferred
  from occupancy, lease-up, NOI growth, construction completion, or a Business
  Plan schedule.
- `CUSTOM` may use closing or any hold-year end.
- A storable month is therefore closing, or a hold-year end strictly before the
  exit: `0`, or `12y` with `1 <= y <= H - 1`. The exit month `12H` is **not**
  storable. Its value is the reserved system Exit view (R-B), and a stored
  definition there would be a second terminal value able to drift from D6's,
  which is exactly what that decision prevents. A definition at the exit month
  resolves to a typed unavailable result naming the Exit view, and a month
  beyond `12H` is outside that variant's horizon and may resolve under a longer
  hold.
- An initial P7.10 timepoint cannot occur inside a hold year. Monthly valuation
  would require a new forward-NOI convention and is deferred.
- The model month is economic identity. A label change is presentation-only;
  a model-month change is a different valuation definition.

### 5.3 Direct capitalization

For `DIRECT_CAP(cap_rate)`:

- `cap_rate` is finite and greater than zero;
- at model month 0, forward NOI is Year 1 NOI;
- at hold-year end `y < H`, forward NOI is the existing `noi_by_year[y]`;
- at the exit month, the report uses the system Exit view instead of a stored
  direct-cap definition;
- no smoothing, annualization, stabilization adjustment, market-rent uplift,
  or AI estimate is permitted;
- a non-positive forward NOI makes direct capitalization unavailable with a
  typed reason. It is not floored, replaced, or divided by the cap rate.

The selected Strategy and Scenario may change the authoritative forward NOI.
The valuation therefore resolves separately for each Analysis Variant without
duplicating Strategy or Scenario logic.

### 5.4 Analyst-supplied value

`ANALYST_VALUE` is finite and non-negative. It is an explicit external value,
not an Anchor engine conclusion. It requires an approved Evidence Reference
and is displayed as **Analyst-Supplied Value** everywhere.

An analyst-supplied value is constant across Strategies and Scenarios because
it is the definition's stated amount. P7.10 adds no valuation Strategy domain
and no Scenario target. A later gate may add those only with an explicit
economic convention.

### 5.5 Investment value

- One unit's value is its resolved instruction at the timepoint.
- An Investment value is the canonical-order sum of its unit values only when
  every Investment member has a valid value at the same model month.
- Missing one unit makes the Investment value unavailable, with the missing
  unit and reason named. Anchor never sums a partial portfolio and presents it
  as the Investment value.
- Values at different dates are never added or compared as though
  contemporaneous.
- For a hidden one-unit Investment, the Investment and unit value are equal but
  remain separately labeled scopes.

### 5.6 Value progression and attribution

The report may display `Purchase Basis -> As-Is -> Stabilized -> Exit` as four
distinct amounts. It may calculate the signed arithmetic difference between
adjacent values in the backend.

It may not label those differences as rent growth, renovation value creation,
cap-rate movement, or another causal attribution unless a separately ratified
backend decomposition calculates that attribution. Capital spending never
implies value creation by itself.

## 6. `PctOfValue` execution

P7.7 already represents `PctOfValue(timepoint_id, pct)` and refuses to execute
it. P7.10 activates that existing rule without adding a new amount-rule shape.

**Stage 1 activates `PctOfValue` closing execution, not `PctOfValue`
generally.** The two halves of that boundary are separate, and neither is the
other's excuse:

- The named timepoint must belong to the same Investment as the Capital
  Structure.
- The funding event's model month must equal the timepoint's model month in the
  initial implementation.
- The valuation must be complete for the position's exact scope and current
  variant.
- Funding equals `pct * resolved_scope_value`, with the existing validation
  preserved exactly: `pct` is finite, greater than zero, and at most one.
- If the definition, forward NOI, evidence, unit membership, or valuation is
  missing or invalid, the Funding Requirement remains unresolved with a typed
  reason. It is never read as zero.
- The existing Capital Structure priority, availability, shortfall, fee, and
  cash-flow rules remain unchanged.
- A report-only valuation that no position consumes changes valuation and memo
  freshness but not the underlying Acquisition analysis.
- A valuation consumed by `PctOfValue` is an economic dependency of the
  resolved Capital Structure and therefore participates in its financial
  identity and downstream invalidation.

### 6.1 The closing-only execution boundary

Recorded explicitly so no reader, guard or later stage infers more than Stage 1
delivered:

- The **valuation authority** resolves valid `AS_IS`, `STABILIZED` and `CUSTOM`
  timepoints alike, exactly as Section 5 states. It is not the limitation.
- The **capital execution seam** can use `PctOfValue` only when the funding
  event occurs at closing, model month 0. The P7.8 rule that this executor
  funds positions at closing only is unchanged, and P7.10 does not relax it.
- A later `STABILIZED` or `CUSTOM` valuation may therefore be used for
  **reporting**, but cannot presently create a later funding event. It resolves
  to a real value; no funding event can consume it.
- Supporting a later funding event would require an **explicitly authorized
  refinancing or event-timing stage**. P7.10 does not silently infer one, and
  no event is moved to closing to make one work.
- This is a **product limitation**. It is not a zero-valued result, and it is
  never an excuse to fall back to the purchase price or any other basis.

### 6.2 What Stage 1 stops at, and the Stage 2 obligation

Stage 1 is a pure engine layer with no API or presentation surface, so it may
stop internal execution with the typed `UnresolvedFundingRequirement`. That
record deliberately states no dollars at all: it carries no amount and no scope
value, and shares no money-bearing field with P7.7's `FundingRequirement`,
which reports a claim the eligible cash could not meet.

**Stage 2 must** translate every unresolved valuation and funding state into
the established structured unavailable / N/A representation, carrying the
specific reason, on both the API and the presentation surfaces.

**Stage 2 must not** expose such a state as a generic server error, fabricate
an amount for it, or collapse it into zero.

That adapter is Stage 2 work and is deliberately not implemented in Stage 1.

P7.10 does not add refinancing. A later refinance gate may use the same
timepoint contract for a later funding event; that future event's cash-flow
semantics require their own ratification.

## 7. Investment Memo domain

### 7.1 Ownership and materialization

The memo belongs to an Investment. Creating the first memo for a standalone
Deal materializes or reuses its hidden one-unit Investment through the existing
opt-in seam. It does not create a visible Investment, alter the Deal, or change
any Deal fingerprint.

Each Investment has at most one mutable draft and any number of immutable
published versions.

### 7.2 Draft fields

```text
InvestmentMemoDraft
  memo_id
  investment_id
  prepared_by                 optional display text; not an authenticated identity
  decision_ask
  analyst_recommendation      APPROVE | APPROVE_WITH_CONDITIONS |
                              REVISE_AND_RESUBMIT | DECLINE |
                              INSUFFICIENT_INFORMATION
  executive_summary
  thesis_items[]
  risk_items[]
  structural_protections[]
  execution_complexity       LOW | MODERATE | HIGH | NOT_ASSESSED
  return_on_time_notes
  reputational_concerns[]
  dealbreakers[]
  terms[]                     REQUIRED | DESIRED | NEGOTIABLE
  conditions_to_approval[]
  selected_decision
  evidence_references[]        the reusable register; claims link into it
  selected_valuations[]        the valuation views this memo includes
```

All narrative fields are analyst-authoritative. Empty optional sections remain
absent; the report never manufactures boilerplate to fill them.

Every structured item that can carry a claim — a thesis item, a risk and its
mitigant, a condition, a term, a business-plan milestone — additionally states
the Evidence References it rests on, by id and in authored order. Zero is a
legitimate answer: the link makes a claim *traceable*, and never makes one
mandatory. See Section 22.7 for the ratified model.

`selected_valuations[]` is the memo's explicit statement of which valuation
views it includes. It is the only thing that makes a view a published
dependency; nothing is inferred from order, existence or recency. See
Section 22.6.

### 7.3 Selected decision

The draft names exactly one:

- Strategy key, including the implicit Base Strategy;
- Scenario key, including the implicit Base Scenario;
- perspective: `PROJECT`, `POSITION(position_id)`, or `PARTNER(partner_id)`.

The selection identifies the recommended decision cell; it does not change any
Strategy, Scenario, position, or Partnership. The selected cell must currently
resolve and complete before a memo version can be published.

The report may show the complete Strategy x Scenario matrix around that cell.
Every delta, worst case, range, status, and stakeholder return comes from the
existing backend comparison packages.

### 7.4 Structured risks and terms

Each thesis, risk, mitigant, protection, condition, term, concern, and
dealbreaker has a stable item id. List position is presentation-only. Explicit
display order is stored separately.

A risk may record analyst-authored `severity` and `residual_risk` labels, but
those labels are qualitative and never calculated from returns. A mitigant
does not automatically turn a risk green or resolved.

### 7.5 IC decision

The committee outcome is separate from the analyst recommendation:

```text
InvestmentCommitteeDecision
  memo_version_id
  decision       PENDING | APPROVED | APPROVED_WITH_CONDITIONS |
                 DEFERRED | DECLINED
  decision_note  optional analyst-entered record
  decided_at     optional timestamp
```

P7.10 provides no voting workflow and no verified signature. `prepared_by` and
decision notes are display text, not security identities. AI cannot write or
change the IC decision.

## 8. Evidence and provenance

P7.10 implements a bounded memo-evidence layer, not a universal data room or
full provenance system for every engine input.

```text
MemoEvidenceReference
  evidence_id
  source_kind       CASE_DOCUMENT | RENT_COMP | SALES_COMP |
                    BROKER_RESEARCH | ANALYST_ASSUMPTION |
                    IMPORTED_MODEL | AI_EXTRACTED_APPROVED | OTHER
  title
  reference         document anchor, URL, or analyst note
  as_of_date        optional
  approved          analyst approval state
```

- External market or property claims need an approved Evidence Reference to be
  presented as sourced facts.
- An unsupported analyst statement is labeled **Analyst Assertion — Source Not
  Attached**. It is never silently upgraded to a fact.
- AI may use only approved evidence. It may point out missing evidence, but may
  not browse for, invent, or auto-approve a source.
- Evidence changes no financial fingerprint. It changes memo/AI identity and
  invalidates a published memo whose narrative used it.
- P7.10 does not copy source documents into the database. It stores references
  only and reuses existing document security boundaries.

## 9. Memo publication and versioning

Publishing creates an immutable `InvestmentMemoVersion` containing:

- monotonically increasing version number within the Investment;
- an immutable copy of the approved memo content and item order;
- selected Strategy, Scenario, and perspective identities;
- selected variant source fingerprint;
- valuation-definition fingerprint and resolved valuation-result fingerprint;
- identities/fingerprints of the Decision Matrix, Capital Structure,
  Partnership, position, and partner results actually included;
- approved evidence identities and content fingerprints;
- approved AI narrative fingerprint, when AI text is included;
- creation time and optional `prepared_by` display text.

Publishing never overwrites an earlier version. Editing resumes in the mutable
draft and produces a new version when published again.

A memo version is `CURRENT` only when every recorded dependency still matches.
Otherwise it is `STALE` with a structured list of changed or unavailable
dependencies. Reopening a stale version is allowed; presenting it as current or
exporting it without a visible stale watermark is not.

## 10. Fingerprints and identity

P7.10 adds layered identity rather than widening every existing fingerprint:

| Identity | Includes | Excludes |
| --- | --- | --- |
| Valuation-definition fingerprint | timepoint ids, kinds, model months, unit ids, methods, cap rates, analyst values, required evidence id | labels and display order |
| Valuation-result fingerprint | selected variant source fingerprint + valuation-definition fingerprint + resolved unit values/statuses | memo prose |
| Memo-content fingerprint | all authoritative memo fields, stable item ids, explicit display order, selected decision, evidence content fingerprints | generated PDF bytes |
| Memo-AI fingerprint | memo-content fingerprint + selected backend context + approved AI proposal text/model metadata | financial identity |
| Published-version fingerprint | dependency identities above + immutable version content | IC decision entered after publication |

Exact semantic revert restores the applicable fingerprint. Canonical order is
by stable id except where an explicit display-order field governs
presentation. A label rename never changes a valuation calculation; changing a
cap rate, amount, timepoint, unit, selected variant, or perspective does.

## 11. AI proposal and approval boundary

### 11.1 AI inputs

The AI grounding package may contain only backend-produced or analyst-approved
content:

- selected Strategy and Scenario definitions and resolved-input summary;
- selected variant results;
- Project, Position, or Partner Decision Matrix figures;
- valuation results and availability states;
- Capital Structure, Funding Requirement, position-return, Partnership, and
  investor-return results;
- existing sensitivity and break-even results when available;
- authoritative memo draft fields;
- approved Evidence References.

The backend precomputes every number, delta, comparison, ranking field, and
availability state the model may mention.

### 11.2 AI outputs

AI may propose text for individual memo fields. Each proposal records:

- target field or item id;
- proposed text;
- grounding fingerprint;
- model/provider metadata already permitted by the AI subsystem;
- generation timestamp;
- `PROPOSED`, `ACCEPTED`, `EDITED`, or `REJECTED` state.

Accepting or editing a proposal copies text into the authoritative memo draft.
Rejecting it changes no memo content. Regeneration never overwrites approved
text.

### 11.3 Forbidden claims

The AI may not:

- make or approve the investment recommendation;
- imply that an analyst-supplied value is an Anchor valuation;
- infer stabilization;
- derive a value-creation attribution;
- call leverage conservative, a basis attractive, or a return compelling
  without an approved comparison that supports the phrase;
- turn an unavailable sensitivity or break-even into an estimate;
- restate unsupported market information as fact;
- conceal an unresolved Funding Requirement, N/A return, stale result, or
  multiple-sign-change IRR.

## 12. Decision support reach

P7.10 composes, rather than recreates, existing decision support:

- Strategy x Scenario matrices are the primary comparison surface.
- Project, Position, and Partner perspectives remain distinct.
- Quick and Detailed existing sensitivity and break-even results may be
  included for the selected variant when current.
- Lease-Level sensitivity may be included where the existing Lease-Level
  surface provides it.
- Lease-Level break-even and Investment-level sensitivity/break-even are
  reported **Unavailable — Not Implemented for This Scope**. No unit result is
  relabeled as an Investment result.

Ratified Decision R-I fixes that bounded reach for P7.10. P7.10 adds no new
solver. A readiness gap discovered later requires its own focused
authorization; it does not widen this gate.

## 13. Institutional report

### 13.1 Page one — decision page

The first page contains, when applicable:

- Investment and property identity;
- decision ask;
- Analyst Recommendation and separate IC Decision;
- preparation date, analysis freshness, version, and prepared-by display text;
- key decision metrics, not asset-type-specific benchmarks;
- As-Is, Stabilized, and Exit valuation views;
- selected Strategy, Scenario, and perspective;
- thesis, principal risks/mitigants, and conditions to approval;
- Sources & Uses and Capital Structure summary;
- Project, Position, or Partner returns appropriate to the selected
  perspective;
- Business Plan milestones already present in authoritative contracts.

The first page does not repeat a second recommendation banner. It contains no
decorative market photograph or unsupported market statistic.

### 13.2 Conditional appendices

Appendices are emitted only when their authoritative data exists:

1. valuation timepoint details;
2. operating projection and cash-flow trend;
3. Sources & Uses and Capital Structure;
4. Strategy x Scenario comparison;
5. position returns;
6. Partnership and investor returns;
7. sensitivity and break-even availability/results;
8. evidence and assumption-source register;
9. memo version, freshness, and AI approval history.

No empty Partnership, position, sensitivity, or break-even appendix is
generated. The report instead states a material unavailable condition where a
reader could otherwise infer zero or completeness.

### 13.3 Rendering and export

- The initial export is PDF.
- Report assembly is deterministic. AI supplies only approved narrative text.
- Generated page numbers, table continuation, totals, and labels are
  presentation logic; financial arithmetic remains in backend contracts.
- Wide financial tables repeat headers and never shrink below the readable
  minimum merely to force one page.
- The PDF carries the memo version fingerprint, generation timestamp,
  current/stale status, and confidentiality footer.
- Exporting writes no financial state. It may record an operational export
  event only if a later audit-log convention authorizes one.
- Generated PDF bytes are not persisted as the source of truth.

## 14. UI vision

P7.10 adds an **Investment Memo** workspace, not another underwriting tab. The
sections are:

1. **Decision** — ask, recommendation, selected Strategy/Scenario/perspective,
   conditions, and IC decision;
2. **Valuation** — definitions, As-Is/Stabilized/Exit views, completeness, and
   value progression;
3. **Thesis & Risk** — thesis, structured risks/mitigants, protections,
   concerns, and dealbreakers;
4. **Terms & Execution** — required/desired/negotiable terms, execution
   complexity, return-on-time notes, and Business Plan milestones;
5. **Evidence** — source references and unsupported-assertion warnings;
6. **Draft with AI** — field-level proposals and approval state;
7. **Preview & Publish** — freshness, validation, immutable version creation,
   and PDF export.

The product disables publication with specific reasons when dependencies are
invalid, incomplete, stale, or unapproved. It never relies on a generic failed
toast for a decision-critical refusal.

## 15. Persistence and API principles

- Live valuation, memo, item, evidence, proposal, and version records use
  typed tables; no opaque JSON blob becomes the authoritative contract.
- Repeating items have stable ids and explicit display order.
- All writes validate Investment ownership and fail closed on foreign ids.
- Draft updates are narrow by section or item; a commentary-style edit never
  resends unrelated financial or memo fields.
- Publishing is one transaction: either the complete immutable version and
  dependency ledger exist, or neither does.
- The PDF route is read-only with respect to financial and memo content.
- The wire carries explicit `status`, `reason_code`, and analyst-facing
  `reason` for every unavailable or stale result.
- Exact schemas, route names, and payload limits are implementation-stage
  details, provided they preserve this contract.

## 16. Availability and refusal states

At minimum the contract distinguishes:

- `AVAILABLE`;
- `NOT_AUTHORED`;
- `INCOMPLETE_UNITS`;
- `NON_POSITIVE_FORWARD_NOI`;
- `EVIDENCE_NOT_APPROVED`;
- `VARIANT_INVALID`;
- `FUNDING_REQUIREMENT_UNRESOLVED`;
- `RESULT_UNAVAILABLE` with the existing typed result reason;
- `STALE_DEPENDENCY`;
- `NOT_IMPLEMENTED_FOR_SCOPE`.

The UI and report pair the state with the exact affected scope. `N/A`,
Unavailable, and Stale never share the same meaning.

**Amendment (2026-09-24, Refinance & Capital Events V1 Stage 2 review
correction).** `ValuationUnavailableReason` gains the additive member
`EVIDENCE_NOT_APPROVED`, mapped explicitly to
`UnavailableReasonCode.EVIDENCE_NOT_APPROVED`, so the Unit cell the Stage 2
evidence gate withholds carries a stable typed reason like every other
unavailable state. Stage 1 never produces it, and no valuation arithmetic or
result without an evidence-blocked analyst value changes. The record is
`REFINANCE_CAPITAL_EVENTS_V1.md` Section 24.11.

## 17. Staged implementation

Each stage starts explicitly and stops for independent review. Completing one
stage never authorizes the next.

### Stage 1 — deterministic valuation and `PctOfValue` closing execution — **implemented 2026-09-20**

- valuation contracts and validation;
- direct-cap and analyst-value resolution;
- unit and contemporaneous Investment aggregation;
- reserved system Exit view;
- `PctOfValue` **closing** execution and typed unresolved results
  (Sections 6.1 and 6.2);
- neutral legacy oracle and financial mutation proofs.

Stage 1 adds no persistence, migration, schema version change, API route, memo
record, AI grounding, PDF generation, or frontend change. Stage 1 is pure and
deterministic.

Stage 1 was human accepted after PR #49 merged to `main` at `f6f3680` on
2026-09-20. Its acceptance does not start Stage 2 or authorize any later
financing event.

### Stage 2 — persistence, fingerprints, memo domain, and API — **implemented and accepted 2026-09-21**

- the unavailable / N/A presentation adapter Section 6.2 obliges;
- additive schema migration;
- valuation definitions and evidence references;
- memo draft, structured items, selected decision, and IC decision;
- immutable version publication and dependency ledger;
- layered fingerprints and stale reasons;
- typed API surface and compatibility oracle.

Stage 2 adds no frontend file, no AI surface, no prompt, no PDF and no report
layout. Schema version 15 adds nineteen purely additive tables; no table is
altered and no existing row is read or rewritten.

Stage 2 was human accepted after PR #51 merged to `main` at `ababa50` on
2026-09-21. Its acceptance does not start Stage 3 or Stage 4.

### Stage 3 — grounded AI proposals — **deferred and unstarted; not required for closeout**

Stage 4 was explicitly authorized ahead of this stage, so Stage 3 is now out of
sequence rather than merely next. On 2026-09-22 the human closed P7.10 with
this stage **deferred and unstarted**, and explicitly decided that **Stage 3 is
not required for P7.10 closeout** (Section 24). It was never begun and no part
of it was implemented. It remains **optional and unstarted**: nothing
in Stage 4 begins it, depends on it, or reserves a place for it. Stage 4 ships
no AI module, prompt, proposal state, grounding snapshot, AI snapshot, empty AI
panel, disabled AI control or "coming soon" surface, and
`tests/test_p7_10_stage_4_architecture.py` and `web/src/memoArchitecture.test.ts`
both prove that absence rather than asserting it.

Every "no AI" statement in this document is scoped to P7.10 — to the Stage 3
grounded memo-proposal capability and to what Stage 4 shipped. None of them
claims that Anchor contains no AI capability. Anchor's existing AI Analyst
interpretation and AI-assisted ingestion features are accepted, in the product,
and outside P7.10's scope; the guards above constrain the memo surface, not
those features.

Because P7.10 closed without it, a grounded-AI proposal capability is no longer
a stage waiting inside an open gate. Building one would require a **separately
authorized new program**. Closing P7.10 neither starts nor cancels such a
program. Should one be authorized, it may add field-level proposals into the
accepted workstation **without changing its financial or publication
authority**: a proposal would write into the mutable draft through the same
analyst approval the contract already requires, and the analyst recommendation,
the Investment Committee decision, publication eligibility and the immutable
published version would stay exactly where Stage 2 and Stage 4 put them.

Its scope, when started, is unchanged:

- Investment/variant/position/partner grounding package;
- field-level AI proposal lifecycle;
- AI snapshot schema bump and explicit invalidation of older AI reports;
- prompt and presentation guards preventing calculation, recommendation,
  unsupported facts, and causal value-creation claims.

### Stage 4 — Memo workstation, institutional report, and browser QA — **implemented and accepted 2026-09-21**

- Investment Memo workspace;
- valuation and decision-support presentation;
- report preview, publish flow, and PDF export;
- desktop and mobile accessibility/responsiveness;
- rendered-PDF visual QA and cross-mode end-to-end proof;
- final human product acceptance.

Stage 4 is **manual-first**: it works completely with manually authored memo
content and offers no AI surface of any kind. It adds no financial calculation;
it adds one presentation package (`anchor.reporting`), four read-only API
routes and the memo frontend.

It advances the schema exactly once, to **version 16**, which adds one purely
additive table: the immutable report artifact stored with each published memo
version (Section 23.2). No table is altered and no existing row is rewritten.

Finishing Stage 4 does not start Stage 3 and does not start P7.11
automatically.

Stage 4 was human accepted after PR #53 merged to `main` at `d7e4d75` on
2026-09-21. Its acceptance does not start Stage 3, P7.11, or any AI proposal
workflow.

## 18. Verification contract

### 18.1 Tier 1

- exact direct-cap golden cases for all three underwriting modes;
- As-Is month-0 and every supported hold-year-end mapping;
- system Exit equality with the existing D6 result;
- no valuation except Exit creates cash;
- complete/incomplete multi-unit aggregation;
- `PctOfValue` amount, timing, scope, invalidation, and unresolved cases;
- one to five mutation proofs per financial invariant;
- neutral oracle proving that absent P7.10 structure leaves every legacy
  response byte-identical.

### 18.2 Tier 2

- schema migration from the accepted baseline database, additive and
  idempotent;
- typed round trips and fail-closed decoding;
- exact-revert fingerprints;
- stale-reason proofs for every dependency class;
- immutable version and transactional-publication proofs;
- foreign-id and cross-Investment mutation refusals;
- AI grounding snapshots and approval lifecycle;
- proof that narrative/evidence changes do not alter financial identity.

### 18.3 Tier 3

- complete keyboard and focus behavior;
- explicit publication refusals;
- Project, Position, and Partner memo cases;
- Quick, Detailed, and Lease-Level reports;
- a visible multi-unit Investment report;
- conditional appendix inclusion;
- desktop and 390px mobile QA with no page-level overflow;
- PDF rendering review at normal print scale;
- no clipped text, overlapping labels, empty misleading sections, formula-like
  user text execution, or unsourced facts presented as approved;
- zero unexpected browser console errors.

## 19. Human acceptance criteria

P7.10 is not complete until the human can:

1. author As-Is and Stabilized views and verify Exit is unchanged;
2. select a Strategy, Scenario, and perspective;
3. author the decision ask, recommendation, conditions, thesis, risks,
   mitigants, terms, and evidence;
4. generate, accept, edit, and reject AI proposals without changing any number;
5. publish an immutable memo version;
6. see precise staleness after changing a financial or narrative dependency;
7. export and review the PDF decision package; and
8. confirm that unavailable features are disclosed rather than approximated.

**Closeout note (2026-09-22).** The list above is the original ratified
criteria list and is preserved unchanged. Criterion 4 — generating, accepting,
editing and rejecting AI proposals — belongs to Stage 3, which was never
started. It was therefore **not exercised and is not claimed as satisfied**.
The human closed P7.10 on 2026-09-22 having accepted Stages 1, 2 and 4 on their
own evidence, and having decided that the deferred Stage 3 is not required for
closeout (Section 24). Criteria 1, 2, 3, 5, 6, 7 and 8 were exercised against
the merged product.

## 20. Ratification record

All ten decisions were **ratified on 2026-09-20**. The human delegated P7.10
architecture ratification, and the ratifying instruction stated each decision
below. No decision remains open. Reopening any of them requires a new explicit
human instruction and a new gate; a later stage may not quietly widen one.

| Decision | Ratified decision | Status | Main tradeoff accepted |
| --- | --- | --- | --- |
| **R-A — Timepoint granularity** | Initial valuation timepoints are month 0 and hold-year ends only. No inside-year valuation. | **Ratified 2026-09-20** | Honest reuse of existing forward NOI; no monthly valuation flexibility. |
| **R-B — Exit ownership** | Exit is a reserved, system-derived view over the existing D6 exit result. It is not a persisted editable valuation. | **Ratified 2026-09-20** | Prevents drift; analysts cannot substitute a different terminal method. |
| **R-C — Stabilization** | Stabilization is analyst-declared by model month and method. Anchor never automatically detects it. | **Ratified 2026-09-20** | Requires judgment; avoids embedding a hidden stabilization convention. |
| **R-D — Methods** | Initial methods are `DIRECT_CAP` and explicitly labeled `ANALYST_VALUE`. Analyst-supplied values require approved evidence. | **Ratified 2026-09-20** | Covers current need without DCF or appraisal-method sprawl. |
| **R-E — `PctOfValue`** | Activate `PctOfValue` only when the funding event and the valuation timepoint use the same model month and the exact position scope has a complete value. | **Ratified 2026-09-20** | Enables value-sized funding safely; defers refinancing semantics. |
| **R-F — Decision authority** | Analyst Recommendation and IC Decision are separate. AI may set neither. | **Ratified 2026-09-20** | More workflow fields; preserves human authority. |
| **R-G — Provenance reach** | P7.10 adds evidence references for memo claims, not a universal provenance system for every engine input. | **Ratified 2026-09-20** | Delivers defensible reporting sooner; full assumption provenance remains later scope. |
| **R-H — Version model** | Each Investment has one mutable memo draft and immutable published versions. Published versions are never edited in place. | **Ratified 2026-09-20** | More records; strong auditability and stale detection. |
| **R-I — Decision-support reach** | Reuse existing Decision Matrices and existing sensitivity/break-even capabilities. Do not add Lease-Level or Investment-level break-even solvers. Unsupported scopes are disclosed as unavailable. | **Ratified 2026-09-20** | Keeps P7.10 bounded; a later readiness gap requires its own focused authorization. |
| **R-J — Export format** | P7.10's institutional export format is PDF only. DOCX and PPTX are out of scope. | **Ratified 2026-09-20** | Strong controlled presentation; less downstream editability. |

## 21. Current position and next action

This contract is ratified and closed to further negotiation within P7.10.
**P7.10 itself is closed as of 2026-09-22** (Section 24); there is no active
development gate.

- **Stage 1 is implemented, merged, and human accepted.** Its accepted scope is
  limited to Section 17: the deterministic valuation layer and safe
  `PctOfValue` closing execution, with no persistence, migration, schema version
  change, API route, memo storage, AI grounding, PDF generation, or frontend
  change.
- **Stage 2 is implemented, merged, and human accepted.** Its accepted scope is
  limited to Section 17 and the ratified clarifications in Section 22. It does
  not start Stage 3.
- **Stage 4 is implemented, merged, and human accepted**, on the explicit human
  authorization to take it ahead of Stage 3. Its accepted record is Section 23.
- **Stage 3 remained deferred and unstarted**, and Stage 4 neither starts it
  nor depends on it. It was explicitly not required for closeout, and it is not
  completed, accepted, passed, or fulfilled.
- P7.10 does not start P7.11. P7.11 was separately **waived and
  administratively closed** by explicit human decision on 2026-09-22. This
  document is not the authority for P7.11; its waiver record is Section 25 of
  `docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`.
- The next action is **no action**. There is no active gate, and none begins
  by implication.

## 22. Stage 2 implementation record

Stage 2 was implemented from accepted `main` at `46650a7` on branch
`feature/p7-10-stage-2-memo-persistence-api`, merged through PR #51, and human
accepted at `ababa50` on 2026-09-21. The implementation clarifications below,
including the two independent-review corrections, are ratified as part of that
acceptance.

The clarifications the implementation required are recorded here as the
accepted interpretation, rather than remaining implicit in a diff.

### 22.1 Identity and fingerprint layering

Section 10 names five identities. The implementation defines **thirteen
dependency classes** and records one fingerprint per class per scope on a
published version, rather than one hash per identity, because "which dependency
class changed" is only answerable if the classes are recorded separately:
`INVESTMENT_MEMBERSHIP`, `UNDERWRITING`, `BUSINESS_PLAN`, `STRATEGY`,
`SCENARIO`, `PROJECT_VARIANT`, `CAPITAL_STRUCTURE`, `PARTNERSHIP`,
`VALUATION_DEFINITIONS`, `VALUATION_RESULTS`, `DECISION_PERSPECTIVE`,
`EVIDENCE` and `MEMO_CONTENT`.

An Investment whose variant resolves no Partnership records twelve of them; see
below.

Three of them — Business Plan, Strategy and Scenario — **overlap**
`PROJECT_VARIANT` by construction, because the ratified P7 identity model folds
them into the resolved inputs. They are recorded *beside* it, never instead of
it, and the report order puts the more specific statement first. A reviewer
should confirm this is the intended reading of "distinguish which dependency
class changed" rather than a parallel authority.

`PARTNERSHIP` is absent from a version whose variant resolves no Partnership,
following FP-2.

### 22.2 The consumed valuation joins the structured identity

Section 6 states that a valuation consumed by `PctOfValue` "participates in
[the resolved Capital Structure's] financial identity and downstream
invalidation". The implementation therefore extends `fingerprint_structured_source`
with the resolved valuations a `PctOfValue` rule actually names.

**Every structured digest that existed before this gate is preserved byte for
byte**: the payload joins only when non-empty, exactly as the D6.5 Business Plan
rule works, and a structure with no such rule hashes what it always hashed. A
report-only valuation no position consumes is deliberately excluded — it moves
valuation and memo freshness, and not the Acquisition analysis.

One consequence a reviewer should weigh: `structured_variant_fingerprint` must
resolve the Project variant when a `PctOfValue` rule exists, because the
identity depends on the resolved value. That costs a Project analysis for those
structures and nothing for any other. It is not optional — an identity that
differed between the fingerprint door and the analysis door would silently mean
two different variants.

### 22.3 The evidence gate is Stage 2's own

Stage 1 validates that an analyst-supplied value *names* an Evidence Reference.
Whether that reference exists and is **approved** is a persisted fact Stage 1
cannot see, so the gate lives in the Stage 2 resolution layer (Section 8; R-D).

An unapproved source produces no value, and **the amount the analyst typed is
not reported** — presenting it would be the "silently upgraded to a fact"
Section 8 forbids. A blocked valuation is also withheld from the `PctOfValue`
funding authority; because the Stage 1 funding layer would then report
`TIMEPOINT_NOT_FOUND`, which is misleading for a timepoint that *is* authored,
the Stage 2 adapter reports `EVIDENCE_NOT_APPROVED` instead. No Stage 1 file was
changed to achieve this.

### 22.4 Two honest surfaces for an unresolved value-sized funding

The accepted Stage 1 executor refuses an unresolved `PctOfValue` with a typed
`CapitalStructureExecutionError`. That is a specific refusal and was left
exactly as accepted.

It is not, however, the "structured unavailable / N/A representation on the API
surface" Section 6.2 requires, so the valuation-views route additionally reports
`funding_states`: every `PctOfValue` rule, sized or typed-unavailable **with no
amount**, read-only and ahead of time. An analyst can see why a value-sized
funding cannot be sized without running an analysis that would refuse.

A reviewer should confirm that two surfaces is the right answer, rather than
changing Stage 1 so an unresolved funding becomes a successful analysis with
N/A returns. The latter would change accepted Stage 1 behaviour and was
deliberately not done.

### 22.5 `PctOfValue` became authorable

P7.8B refused a `pct_of_value` amount rule at the authoring door, and its own
message said why: the rule "arrives with valuation timepoints". They have
arrived, so the refusal was retired. Without this the capability Stage 1
activated would be unreachable through the product.

Nothing downstream moved. A rule naming a timepoint the Investment does not
define is stored and resolves to a typed unavailable funding state with no
amount.

### 22.6 Stale-reason ownership and publication prerequisites

Freshness is computed by comparing a version's recorded ledger against the
current state. A dependency that can no longer be computed at all — the selected
Strategy was deleted, the variant no longer resolves — is reported as a named
stale condition with no current fingerprint, never as an error and never as a
silent equality.

Publication fails closed on: an ill-formed draft, no selected decision, a
missing Strategy, Scenario or perspective, a cell that does not resolve, a blank
decision ask, a cited Evidence Reference that is missing or unapproved, and any
**required** valuation view with no value.

**Ratified resolution (Correction 1).** The first implementation required
*every authored* valuation definition to resolve. That was rejected on review
and is superseded. A valuation is a dependency of the package, and therefore
blocks publication, in exactly two cases:

- the memo **selected** it for inclusion, through the explicit
  `selected_valuation_timepoint_ids` relationship on the draft; or
- a `PctOfValue` funding of the **selected** Capital Structure **consumes** it,
  whether or not the report ever displays it.

An authored definition that is neither selected nor consumed is exploratory
working state. It may sit unavailable indefinitely without blocking a memo that
never leaned on it, and an analyst is never made to delete their own working
view in order to publish.

Selection is an explicit typed relationship — `memo_selected_valuations`, one
row per included view, scoped to the same Investment and validated on save. It
is **never** inferred from display order, from a definition's existence, or from
recency. Where a required view is unavailable, publication refuses with the
valuation's *own* structured reason code carried through on the refusal
(`unavailable_reason`), never a generic failure, and never zero, the purchase
price, another timepoint's value, or a silent omission. Exit remains
system-controlled and later timepoints remain reporting-only; neither is
reachable through selection.

Which views a memo selects is memo **content**: the selection participates in
`MEMO_CONTENT` and therefore in the published-version fingerprint and in stale
analysis. It moves no valuation, variant or structured identity, because
including a view in a memo changes no economics. A published version freezes
`selected` and `consumed` on each of its own valuation rows, so a later reader
can see which views that version was required to resolve without recomputing a
draft that has since moved on.

One consequence is worth naming: resolving valuations does not execute the
structured positions, so the dependency layer reads the valuation surface
*before* anything that executes, and keeps it even when execution refuses. That
is what lets a consumed-but-unavailable valuation refuse publication with its
specific reason instead of collapsing into "the selected cell does not
resolve".

### 22.7 Claim-level evidence linkage (R-G)

**Ratified resolution (Correction 2).** The first implementation stored only the
draft-level `evidence_references[]` register of Section 7.2 and left per-item
citation out. That was rejected on review and is superseded: R-G requires that
evidence be traceable to the specific claim it supports, and a flat register
cannot answer "what does *this* risk rest on".

The draft keeps its reusable register — an Evidence Reference is authored once
and may support many claims — and in addition every structured item that can
carry a claim references zero or more Evidence References **explicitly**:

- `MemoItem` (thesis, business-plan milestone, condition to approval, and every
  other contract-authorized narrative section);
- `MemoRiskItem` (the risk and its mitigant);
- `MemoTermItem` (a condition or term).

Links are normalized typed persistence, not an opaque JSON list:
`memo_claim_evidence(memo_id, claim_kind, item_id, evidence_id, ordinal)` for
the draft and `memo_version_claim_evidence(version_id, …)` for the frozen
snapshot, both with `claim_kind` constrained to `item | risk | term`. Evidence
identity (`evidence_id`) and item identity (`item_id`) are the analyst's own
stable ids, so a link survives an edit to either side's text.

Scope and validity are enforced at the store: a link may only name an Evidence
Reference of the *same* Investment and only within a valid draft context, and a
nonexistent or cross-Investment reference is refused rather than stored. A
source a claim still cites cannot be deleted out from under it — the link is a
use, exactly as a citation in the register is — so no dangling reference is ever
created.

Publishing **snapshots** the item-to-evidence relationships into the immutable
version alongside the frozen content and the frozen evidence content. Every
source any claim cites is frozen, including one cited by a claim but absent from
the register. Nothing an analyst does afterwards reaches that snapshot:
re-pointing a claim, unlinking one, editing an item, deleting the source, or
deleting the draft entirely leaves the published rows byte-identical, and
republishing records the new relationships on a *new* version.

Evidence-link changes participate in the memo-content fingerprint and therefore
in stale analysis: re-pointing a claim at a different appraisal changes what the
memo asserts even when every word and every registered source is untouched.
Authored link order participates too, because it is the order a reader is asked
to follow the support in.

Two boundaries this does **not** cross. Evidence is never *required*: a claim
may cite nothing, and purely subjective or decision-authority fields — the
analyst recommendation, the execution-complexity judgement, the decision ask,
the committee outcome — demand no citation. And this is claim-level traceability
for memo items only, not a universal provenance system over every value in the
product. No AI generates, suggests or verifies a citation; Stage 2 ships no AI
surface at all.

### 22.8 Guards re-pinned

Each re-pin is documented in place in the test that carries it. No earlier
invariant was weakened; where a guard genuinely conflicted with this gate, the
claim it proved was restated as the historical fact it still proves.

- P7.10 Stage 1's ledger, protected paths and API freeze now read Stage 1's
  committed range `9c65843..7237d7a`, as that file's own docstring anticipated.
  The accepted package gained a *stronger* freeze: byte-identical to its merge
  now, not merely unchanged during Stage 1.
- P7.9 Stage 1 released `deals/structured_variants.py` from its working-tree
  freeze, restating the claim as "byte-identical from P7.9 through accepted
  P7.10 Stage 1".
- P7.1's two scenario-layer guards widened by one named file, the identity
  module.
- P7.4's wrapper-collapse guard now asks about all eight kinds a wrapper can
  hold.
- P7.8B retired `UNSUPPORTED_AMOUNT_RULE` from its unexecutable-convention list
  and gained a counterpart test.
- Excel Export 3's no-migration guard measures its own committed range.
- The P7.2, P7.4, P7.6 and P7.9 Stage 2 compatibility oracles and four
  fresh-store assertions moved to schema 15 with P7.10's nineteen tables
  named, so every set comparison stays exact.


## 23. Stage 4 implementation record

Stage 4 was implemented from accepted `main` at `9ca957a` (PR #52, over the
accepted Stage 2 implementation `ababa50`) on branch
`feature/p7-10-stage-4-memo-workstation-report`, merged through PR #53, and
human accepted at `d7e4d75` on 2026-09-21. The implementation clarifications
below, including every independent-review correction, are ratified as part of
that acceptance.

### 23.1 Stage 4 ahead of Stage 3, and what that fixes

The human explicitly authorized Stage 4 before Stage 3 on 2026-09-21. The
ordering is recorded rather than inferred:

- Stage 3 is **optional and deferred**, not cancelled and not implicitly begun.
- Stage 4 **does not depend on** Stage 3 and works completely with manually
  authored memo content.
- No empty AI panel, disabled AI control, placeholder prompt or "coming soon"
  surface appears anywhere in the product.
- A future explicitly authorized Stage 3 may integrate proposals into the
  accepted workstation without changing its financial or publication authority.

### 23.2 Where a published memo's numbers come from — the frozen report artifact

**Revised at the Stage 4 independent review (Correction 1).** The first
implementation recomputed a published version's returns, Capital Structure and
Partnership figures from the cell the version recorded, and relied on the Stage 2
freshness check plus a watermark to disclose that they had moved. That was
rejected, and rightly: a published memo version is an **immutable decision
artifact**, and a record whose numbers change after the decision is not a record
of it. A stale badge or watermark is not a substitute for historical
immutability.

Publication therefore **stores the issued report**. Schema version 16 adds one
additive table, `memo_version_report_artifacts`, one row per published version,
holding:

- the canonical serialization of the typed report document;
- the report-schema version it was written under;
- the content hash of that document;
- the exact PDF bytes that were generated, and their hash;
- the stable filename, the page count, and the creation timestamp.

Reading a published version's report decodes that row. Downloading its PDF
returns those stored bytes. **Neither path recomputes anything**, and no
supported store or API operation updates or deletes a stored report or PDF.
The payload is produced exclusively from the typed backend assembly, carries an
explicit schema version, decodes fail-closed — an unknown version, a missing
field or a wrong type refuses rather than guesses — and contains no formula and
no hidden recalculation.

The consequence is what the correction asked for: the displayed figures and the
downloaded PDF of a published version do not change when the Deal or Investment
inputs change, when the Strategy or Scenario changes, when the capital structure
or the Partnership changes, when a valuation definition changes, when the
current analysis is rerun, when presentation code changes, or when the current
package becomes stale.

#### 23.2.1 Publication is one transaction

Publishing resolves and validates the draft, assembles the typed report,
generates the deterministic PDF, and creates the version, its child rows, the
report snapshot and the PDF **atomically**. A failure anywhere leaves no
version at all — never a published version with no report, and never a report
belonging to a version that does not exist.

#### 23.2.2 Versions published before schema 16

They remain fully readable and keep every row they have. They have no report
artifact, because the tree that published them stored none, so the report and
PDF endpoints answer with the typed `REPORT_SNAPSHOT_NOT_AVAILABLE` state,
which tells the analyst plainly that no report was issued with that version and
that publishing a new version is how to obtain one. They are **not backfilled
by recomputation** — that would manufacture exactly the fiction this correction
exists to prevent — and no existing row is mutated.

#### 23.2.3 The published artifact versus current freshness

The two questions are kept apart. The frozen report says what was issued; the
workspace and the version history say, **outside** the artifact, whether current
underwriting still matches it, using the Stage 2 freshness check and its stale
reason classes. The published report document is not altered, the stored PDF
gains no stale watermark, and no figure in either is replaced.

The draft preview remains current by construction, and is marked plainly as
`DRAFT — NOT PUBLISHED`, on screen and in the PDF.

#### 23.2.4 One consequence, stated plainly

The analyst recommendation and the committee's decision are separate acts
(R-F), and the committee records its decision **after** the version is
published. A frozen report therefore shows the committee outcome as *not yet
recorded*, because that is what was true when the report was issued. The
recorded decision is held against the version and is readable on the version
surface; it is not retrofitted into the issued document.

### 23.3 The report is handed finished text, not numbers

`anchor.reporting.contracts` carries every figure as a **string the backend has
already formatted**. A renderer holding raw floats is a renderer one edit away
from summing two of them; a renderer holding finished text cannot compute even
by accident, and `pdf.py` is additionally handed nothing but the package — no
store, no engine, no analysis function, no result contract.

The frontend follows the same rule: report figures are displayed as received.
The one raw number the memo UI formats is the Stage 2 valuation surface's, which
is the engine's own surface rather than a report package, and it goes through
the product's existing `formatCurrency`.

### 23.4 Unavailable states are translated, not repeated

The Stage 2 adapter's `reason` is a precise developer-facing sentence that names
the Investment, the Unit and the timepoint by their opaque ids. That is correct
for a log and for a test, and it is exactly the implementation vocabulary
Section 2 keeps out of an analyst view.

Stage 4 therefore translates the stable `reason_code` — the contract — and never
repeats the raw message. Nothing is softened: each sentence says what the code
means, including that there is no value. Two tables, one per side, are held to
the same key set by a guard, and every member of both reason enums is covered.

### 23.5 Anchor stores no market or location

The accepted visual concept shows a location line and a market panel with
population, job growth and occupancy statistics. Anchor records none of those:
there is no location, address or market field anywhere in the product.

They are therefore **omitted entirely** rather than invented, in the report, in
the PDF and in the library. This is the Section 13.1 rule that the first page
carries no unsupported market statistic, applied at the point where it would
have been easiest to fabricate one.

### 23.6 Decision-support reach, disclosed rather than hidden

Ratified decision R-I is unchanged. Investment-scope sensitivity and break-even
are reported **Unavailable — Not Implemented for This Scope** as a stated
disclosure rather than a hidden section, and a variant that resolves no
Partnership produces a disclosure saying so is an absence rather than a zero.

### 23.7 One new dependency

Anchor had no PDF generator: `pypdf` reads, and XlsxWriter writes workbooks
only. Section 13.3 requires a paginated institutional report with repeated table
headers, page numbers and a confidentiality footer, so **ReportLab** was added —
the same shape of dependency as XlsxWriter and for the same reason: write-only,
no system libraries, and deterministic. Built with `invariant=1` it fixes the
document id and creation date, so two exports of one memo version are
byte-identical rather than merely semantically identical.

A reviewer should confirm that adding it is the right answer, rather than
hand-rolling a PDF writer or deferring the export.

### 23.8 Guards re-pinned

Each re-pin is documented in place in the test that carries it. No earlier
invariant was weakened; where a guard genuinely reached this gate, the claim it
proved was restated as the historical fact it still proves.

- P7.10 Stage 2's ledger now measures its own committed range
  `46650a7..ababa50`, exactly as its `_changes_since` docstring anticipated. Its
  later-stage identifier scan stops at Stage 4's marker in `api.py`, and its
  route ledger names and excludes Stage 4's four read-only routes rather than
  growing into a list of whatever the application serves.
- Excel Export 2 and Excel Export 3 measure their own committed ranges for the
  no-new-dependency claim, and their route guards are narrowed to the `.xlsx`
  workbooks they have always been about. A memorandum PDF is a different
  artifact of a different gate.
- D4.6B's G37 frontend allowlist gains the fourteen named Stage 4 modules, and
  at the independent review the two the corrections added: `ConfirmDialog.tsx`
  and `useAsyncResource.ts`.
- **Re-pinned at the independent review.** Schema 16 reaches four Stage 2
  guards that assert facts about *Stage 2's own* migration — that the store
  declared one schema version and it was fifteen, that the migration created
  nineteen tables and altered nothing, that every one is registered on the
  connection, and that no Stage 2 module imported a document library. Those are
  settled facts about a merged gate, so each now reads Stage 2's merge
  `ababa50` and its committed range rather than a working tree later gates
  advance. `memo_dependencies.py` is read as Stage 2 merged it, because
  generating a document at publication is Stage 4's act and is held by Stage 4's
  own guards. Stage 2's v14 oracle names the later-gate table explicitly, so it
  still asserts an exact set of added tables rather than a loosened one.

### 23.9 Corrections applied at the independent review

Four corrections were required before publication; the ratified decisions that
accompanied them — ReportLab as the PDF engine, omitting the unsupported
location line and market panel, translating the stable reason codes, and
Playwright as the browser-QA driver — are recorded above and unchanged.

1. **The published report and PDF are frozen.** Section 23.2, rewritten above.
2. **No native browser dialog in the Stage 4 workflow.** `window.confirm` is
   replaced by `ConfirmDialog`, an in-application modal that names the memo
   being left, the memo being opened and the unsaved work at stake; focuses the
   safe action; supports Escape; traps focus; restores focus to the control that
   opened it; navigates nowhere when cancelled; and is not shown at all when
   nothing would be discarded. An architecture guard proves no native `confirm`,
   `alert` or `prompt` in any Stage 4 production file, including the memo
   functions inside the shared `App.tsx`.
3. **No new lint debt.** The six `react(set-state-in-effect)` warnings the
   branch introduced are removed by one reusable, tested loading abstraction,
   `useAsyncResource`, which derives loading during render instead of setting it
   in an effect. No rule is disabled, no suppression comment is added, and the
   lint configuration is untouched; the branch's warning set is identical to
   accepted `main`'s. Request cancellation, stale-response protection, loading
   behaviour and the Phase 1 request-loop fix are all preserved.
4. **Cross-mode browser QA.** Recorded in Section 23.10.

### 23.10 Cross-mode browser QA

Driven with Playwright against an **isolated QA database** built by a seed
script through the real store and contracts, with the backend pointed at it by
``ANCHOR_DB_PATH``; the product database was never opened. Screenshots are kept
under the ignored ``scratchpad/`` location and are untracked.

Every enumerated case was exercised at **1440px and 390px** through the memo
workspace, the preview, publication, the published version and the PDF
download -- not merely route loading:

| # | Case | Outcome |
|---|------|---------|
| 1 | Quick Underwrite Investment | published; 4-page PDF |
| 2 | Detailed Underwrite Investment | published; 7-year projection; 4-page PDF |
| 3 | Lease-Level Underwrite Investment | published; 4-page PDF |
| 4 | Multi-unit Investment | published; Investment-scope disclosure; 4-page PDF |
| 5 | Capital Structure with ``PctOfValue`` | funding sized from the As-Is view; the view reports "Included; consumed by funding" |
| 6 | Position decision perspective | Senior Loan funded amount, position IRR, MOIC, cash received, profit, detachment LTV |
| 7 | Partnership and Partner perspective | LP contributions, IRR, multiple, distributions and profit **after the defect below was fixed** |
| 8 | No-Partnership case | the absence is disclosed, and no partner figure is printed |
| 9 | Selected unavailable valuation | publication is refused, in translated analyst language, and no version exists |
| 10 | Stale historical published version | the frozen report still shows $11.0m against current underwriting of $13.75m; staleness is stated **outside** the document |
| 11 | Immutable version N, then a changed draft and N+1 | v1 keeps its ask and summary; v2 carries the revised ones; distinct verification codes |
| 12 | Migrated version with no report snapshot | the typed explanation is shown, no PDF is offered, nothing is backfilled, and publishing a new version issues a working report and PDF |

Representative PDFs from the Quick, Detailed, Lease-Level, multi-unit,
Position and Partnership cases were rendered and **every page inspected**:
masthead and status on each page, repeated table headers, right-aligned
figures, no orphaned heading, no clipped or overlapping text, the
confidentiality marking and page number in every footer, and the version
appendix carrying the verification code.

#### What browser QA found, and what was done

Three defects reached the browser that the backend suites did not catch. Each
is fixed, with a regression test that fails on the old behaviour:

1. **Partner-perspective memos reported no partner returns at all**, beneath a
   disclosure claiming the Investment resolved no Partnership -- on Investments
   that plainly had one. The Partnership was read from the structured capital
   result, which carries no such field, and the partner totals were named by
   fields the P7.9 contract does not define. Both faults were silent and
   pointed the same way, and the backend test that existed asserted the very
   disclosure that always fired. The report now resolves the Partnership
   variant, reads P7.9's own field names, and discloses an absence only where
   there is one. The cover also now names the partner as its Partnership does
   ("Partner – LP", not "Partner – lp").
2. **Analyst-facing surfaces repeated backend sentences that name records by
   their opaque ids.** Publication readiness printed the refusal's own message
   -- *"Investment '2fa67abf…' has no value at valuation timepoint 'as-is-3b93ed':
   '5889bb98…' (unit_not_valued)"* -- on the surface whose whole job is to tell
   an analyst what to fix, and the report's "did not resolve" disclosure
   rendered the raising layer's exception text inside the published document and
   its PDF. Refusals are now translated from their stable code, exactly as
   unavailable valuations already were, with the upstream reason appended so
   nothing specific is lost; the disclosure says the same thing in the analyst's
   terms. Guards hold the new table to ``PublicationRefusalCode`` and forbid an
   id in either vocabulary.
3. **A version published before schema 16 was still offered a "Download PDF"**
   that could only refuse, landing the analyst on a raw refusal payload. The
   version list now says "No issued PDF" with the typed explanation beneath.

A fourth was cosmetic and fixed with the rest: report tables keyed their rows
and cells by their own text, so a Unit whose NOI and levered cash flow were the
same figure produced duplicate React keys and a console error. They are keyed by
position, which is what the backend fixes and nothing reorders.

Two further observations were raised at that review as open judgement calls.
Both were decided against the first implementation and are now closed:

- **the library reflows at phone width.** Below 640px the Investment Committee
  library is a list of cards rather than a table scrolled sideways, because it
  is a navigation and status surface rather than a financial comparison table.
  Both presentations render one `describeEntry` description, so they cannot
  disagree about a memo, and `display: none` leaves exactly one reachable action
  per memo at any width. The desktop table is unchanged above that width, where
  comparing a column of recommendations across a portfolio is what a table is
  for. A card carries every column the table carries, plus the decision cell,
  and the Investment name is the card's heading and is never truncated;
- **an analyst-facing scope is a name, never an id.** A refusal's `scope_id` is
  an identity the API must carry; what an analyst reads is the label the scope's
  own register gives it, resolved from the lists the workspace has already
  loaded. A scope whose record no longer exists says so -- "Selected valuation
  view (no longer available)" -- and the id is never the fallback. The same rule
  now holds in the report and the PDF, where a value-sized funding disclosure
  named its position by the stored key.

### 23.11 No identifier reaches a normal analyst view

Guarded rather than asserted. `tests/test_p7_10_stage_4_architecture.py` proves
that no Stage 4 presentation module renders an expression whose whole value is a
stored identifier, that every `MemoReportDisclosure` scope is a fixed word, a
table label or a resolved display name, that the refusal-scope resolver returns
a sentence for a code it does not know and never returns its argument, and that
every "no longer available" sentence names no record.

The rule is deliberately narrow: it looks for an identifier being *rendered*,
not for one being passed to a function, used as a React key, built into a URL or
compared. A guard that rejected those would reject the identity the product
legitimately needs and would be switched off within a gate. As written it found
two real leaks that had survived the first QA pass -- the valuation panel's
unresolved-funding heading, and the report disclosure's position scope.

Identifiers remain exactly where they belong: in the API, the store, the
dependency ledger, React keys, export URLs and the published version's
verification code, which Section 13.3 requires and which is labelled as what it
is.

---

## 24. P7.10 closeout record — 2026-09-22

This section records an explicit human decision. It is a **documentation-only**
record: it changes no calculation, convention, schema, fingerprint, API
contract, workbook, or product behavior, and it reports no new verification
evidence.

### 24.1 The decision

On **2026-09-22** the human explicitly decided:

- **P7.10 is closed.**
- **P7.10 Stages 1, 2, and 4 are implemented and human accepted.**
- **P7.10 Stage 3 remained deferred and unstarted**, and was **explicitly not
  required for P7.10 closeout.** It is not completed, accepted, passed, or
  fulfilled.

Each stage acceptance above was recorded when it was made, on its own gate
evidence, and is unchanged by this record. This section adds only the closure
of the gate as a whole.

### 24.2 Stage 3 and any future grounded-AI capability

Stage 3 — grounded AI memo proposals — was **never started**. Precisely: **no
P7.10 Stage 3 grounded memo-proposal module, prompt, proposal lifecycle,
grounding snapshot, AI snapshot, or product surface was built**, and two guards
prove that absence rather than asserting it (Section 17, Stage 4).

That statement is scoped to Stage 3. It is **not** a claim that Anchor contains
no AI capability. Anchor's existing AI Analyst interpretation and AI-assisted
ingestion features are accepted, in the product, and untouched by P7.10. What
was never built is the Stage 3 grounded memo-proposal capability this contract
describes.

Closing P7.10 does not cancel the idea and does not quietly begin it. **A
future grounded-AI proposal feature would require a separately authorized new
program.** Closing P7.10 neither starts nor cancels such a program. Until one
is explicitly authorized, the Stage 3 text in this document is a preserved
design contract for work that has not been done.

### 24.3 P7.11 was separately waived

**P7.11 Competition Closeout was separately waived and administratively closed
by explicit human decision on 2026-09-22.** It was not run.

This document is **not** the authority for P7.11. The P7 authority owns the
P7.11 contract and owns its waiver: the full waiver record, including what was
not executed and why the closure is a scope decision rather than acceptance
evidence, is **Section 25 of
`docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`**.

### 24.4 What this record does not do

It does not start Stage 3, P7.11, Refinancing & Capital Events, Recovery
Engine V2, ingestion, extraction, a new AI surface, collaboration expansion,
productionization, or any other development gate. **There is currently no
active development gate.**
