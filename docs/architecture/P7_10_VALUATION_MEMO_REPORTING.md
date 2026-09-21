# P7.10 Valuation Timepoints, Investment Memo, and Institutional Reporting

Status: **Ratified.** P7.10 was explicitly started on 2026-09-20 from accepted
`main` at `9c65843` (PR #48). Decisions R-A through R-J were ratified on
2026-09-20 by the human's delegation of P7.10 architecture ratification; the
completed ratification record is Section 20.

Stage status:

- **Stage 1 is implemented, merged, and human accepted.** PR #49 merged to
  `main` at `f6f3680` on 2026-09-20. It delivers the deterministic valuation
  layer and `PctOfValue` **closing** execution, and nothing else. Its boundary
  is Section 6.1 and its Stage 2 obligation is Section 6.2.
- **Stage 2 is implemented, merged, and human accepted.** PR #51 merged to
  `main` at `ababa50` on 2026-09-21. It delivers persistence, the Investment
  Memo domain, versioning, the unavailable-state adapter and the typed API, and
  nothing else. Its ratified implementation clarifications are Section 22.
- **Stages 3 and 4 are not started.** Each requires its own explicit human
  start.
- **Finishing Stage 1 does not automatically start Stage 2, and accepting
  Stage 2 does not start Stage 3.**

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

### Stage 3 — grounded AI proposals — **not started**

- Investment/variant/position/partner grounding package;
- field-level AI proposal lifecycle;
- AI snapshot schema bump and explicit invalidation of older AI reports;
- prompt and presentation guards preventing calculation, recommendation,
  unsupported facts, and causal value-creation claims.

### Stage 4 — Memo workstation, institutional report, and browser QA — **not started**

- Investment Memo workspace;
- valuation and decision-support presentation;
- report preview, publish flow, and PDF export;
- desktop and mobile accessibility/responsiveness;
- rendered-PDF visual QA and cross-mode end-to-end proof;
- final human product acceptance.

Finishing Stage 4 does not start P7.11 automatically.

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

- **Stage 1 is implemented, merged, and human accepted.** Its accepted scope is
  limited to Section 17: the deterministic valuation layer and safe
  `PctOfValue` closing execution, with no persistence, migration, schema version
  change, API route, memo storage, AI grounding, PDF generation, or frontend
  change.
- **Stage 2 is implemented, merged, and human accepted.** Its accepted scope is
  limited to Section 17 and the ratified clarifications in Section 22. It does
  not start Stage 3.
- **Stages 3 and 4 are not started.**
- P7.10 does not start P7.11.

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
