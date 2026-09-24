# Refinance & Capital Events V1

## 1. Status and authority

**Status: RATIFIED — 2026-09-22.** Codex's independent architecture review
accepted this contract in substance on 2026-09-22. It required two
corrections, which are incorporated here:

- DSCR sizing does not consume a valuation (Correction 1);
- the legacy-payoff authority is an explicit, narrow extension (Correction 2).

It also resolved every open question. The decision record is Section 22.

- Drafted and ratified on `design/refinance-capital-events-v1-contract`, from
  `main` at `0e9f8cc` (PR #55, the P7.10 closeout and P7.11 waiver).
- Risk tier: Tier 1 contract (financial / contract critical). The contract
  itself is documentation only.
- **Stage 1 (deterministic engine) was explicitly started** on 2026-09-22
  from `main` at `2e1f84a` (the PR #56 merge of this ratified contract), on
  `feature/refinance-capital-events-v1-stage-1-engine`. It is **implemented
  locally and pending independent review. It is not accepted.** Its
  implementation record is Section 23.
- **Stage 2 and Stage 3 have not started.** No schema, persistence, codec, API,
  UI, memo, report or workbook exists for a refinance. **No implementation
  stage starts automatically** when another is accepted (Section 20).
- Recovery Engine V2 is a separate future program. Nothing here touches it.

### 1.1 Authorities this contract builds on

The following remain in force. This contract amends or extends them only where
Section 22.3 names the amendment explicitly. Everywhere else, the accepted
authority governs.

| Authority | What this contract relies on |
| --- | --- |
| `docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md` | §7.4 Strategy domains (ST-1 to ST-6), §11.3 valuation timepoints (VT-1 to VT-5), §12 Capital Structure (CS-1 to CS-8, FR-1 to FR-5), §12.5 refinance sketch, §13 Partnership (PW-1 to PW-6), §14 return namespaces, §15.4 fingerprint hierarchy (FP-1, FP-2), §15.5 order semantics |
| `docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md` | position contracts, cash authorities (§4), the legacy acquisition-loan adapter (§5), settlement (§6), the model-month convention (§7), structural rules (§8) |
| `docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md` | debt scheduling through the unchanged `debt.py` functions and the capital-structure debt wrapper (§6), claims (§8), subordination and the residual (§9), unresolved funding (§10), position returns (§12), structural metrics (§13) |
| `docs/architecture/P7_8_PRODUCT_INTEGRATION.md` | Investment ownership (§2), the `CAPITAL_STRUCTURE` Strategy domain and whole-domain replacement (§5), position identity P-8 (§6), layered fingerprints (§7) |
| `docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md` | the Common Equity seam (§2), the input contract (§3), period ordering (§7), unavailable states (§13), conservation identities (§14) |
| `docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md` | valuation definitions and timing (§5), direct capitalization and forward NOI (§5.3), the `PctOfValue` boundary (§6, §6.1), availability states (§16), consumed-valuation identity (§22.2), publication dependencies (§22.6), frozen reports (§23.2) |
| `docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md` | the model-month convention (§4), debt / lender invariants (§12) |
| `docs/owner_return_metrics_v3_financial_conventions.md` | the recurring cash-flow series that excludes refinance proceeds |
| Excel Exports 1–3 | the formula-audit precedent. All three explicitly exclude Capital Structure |

### 1.2 Source-model context

`Commercial Template.xlsb` (Marvin) was reviewed as a **requirements
reference only**. It shows that analysts expect:

- a separately visible refinance event and its timing;
- stabilized NOI and contemporaneous value;
- DSCR and LTV constraints;
- replacement-loan terms;
- lender fees and other costs;
- retirement of the old debt;
- gross proceeds, net proceeds and cash returned to equity;
- monthly debt mechanics rolled up to annual reporting.

The workbook is blank, has unresolved names and shows formula errors when its
inputs are empty. **It is not financial authority and not a numerical oracle.**
No figure in this contract comes from it.

No populated external reference model exists. Implementation is verified with:

- exact rational fixtures;
- Anchor's existing debt mathematics;
- accounting identities and conservation tests;
- mutation tests;
- later, an Excel formula-audit export (Section 18).

---

## 2. Purpose

This contract lets an analyst model one refinance of a property's debt during
the hold. The refinance is sized by stated lender constraints against stated
authoritative inputs. Its cash flows through the existing layers:

- Capital Structure;
- Common Equity;
- Partnership;
- decision support, memo and export.

There is no second financial engine and no invented economics.

V1 delivers **`REFINANCE` only**. "Capital Events" is the extensible
architecture that later event kinds may use. V1 builds none of them
(Section 5.2).

---

## 3. User story and analyst workflow

> As an analyst, I own a stabilizing asset with an acquisition loan. I expect
> to refinance at the end of Year 2 once the business plan is complete. The
> lender will lend the least of:
>
> - a stated dollar cap;
> - 65% of the Year-2 stabilized value;
> - the amount a 1.25x DSCR on forward NOI supports.
>
> I want to see what the new loan will be, which constraint binds, what it
> costs to retire the old loan, and how much cash returns to equity. I also
> want to see how that changes my equity and partner returns in every
> Strategy and Scenario I am comparing.

Workflow. Stage 3 provides the surfaces; Stages 1 and 2 provide the engine and
state.

1. **Valuation (LTV only).** Where the event will size by LTV, the analyst
   defines a P7.10 Stabilized or Custom valuation at a hold-year end, for
   example model month 24. DSCR and fixed-cap sizing need no valuation.
2. **The event.** In the Capital Structure (Base or a Strategy's own), the
   analyst adds one refinance event for a scope at that hold-year end. They:
   - choose the debt it retires;
   - author the replacement loan as an ordinary debt position;
   - enable one or more sizing constraints;
   - reference the valuation, only when LTV is enabled;
   - list the event costs.
3. **Per-variant execution.** For each Strategy × Scenario variant, Anchor
   computes each enabled constraint's capacity:
   - fixed cap: from its amount;
   - LTV: from the referenced value;
   - DSCR: from the variant's forward NOI.

   The gross proceeds are the least of these capacities. Anchor then retires
   the old debt at the boundary, funds the replacement, and puts the net
   event cash into Common Equity in that hold year.
4. **Results.** The analyst reads:
   - an event audit bridge (gross → payoffs → fees → costs → net);
   - the binding constraint;
   - the effect on Common Equity, Position and Partner returns;
   - the effect in the Decision Matrix.

   Common Equity after Capital Structure is the primary equity-return view
   (Section 12.5).
5. **Missing dependencies.** The analyst sees a typed unavailable state naming
   the reason. They never see a zero, a purchase-price fallback, or a
   silently skipped refinance.

---

## 4. Definitions

| Term | Meaning |
| --- | --- |
| Capital Event | A dated, typed change to a scope's capital structure that moves cash between capital providers and Common Equity. V1 has one kind, `REFINANCE`. |
| Refinance event | A Capital Event that retires one or more debt positions of one scope, funds one replacement debt position in the same scope, and settles the difference with Common Equity. |
| Event scope | The exact `PositionScope` (`UNIT(unit_id)` or `INVESTMENT`) the event belongs to. |
| Event year `y`, event month `m` | `m = 12y`, with `1 <= y <= H - 1`, where `H` is the variant's hold period. |
| Retiring position | A debt position of the event scope that the event repays in full at `m`: an authored position, or the Unit's legacy acquisition loan. |
| Replacement position | The ordinary `CapitalPosition` with `DebtTerms` that the event funds at `m`. |
| Payoff | A retiring position's principal balance immediately after its scheduled payment in month `m`. |
| Sizing constraint | One enabled lender limit: a fixed maximum, a maximum LTV, or a minimum DSCR. |
| Capacity | The largest gross proceeds one enabled constraint permits. |
| Gross proceeds `G` | The replacement position's funded principal: the least capacity over the enabled constraints. |
| Binding constraint(s) | The enabled constraint(s) whose capacity equals `G` (Section 9.6). |
| Replacement lender fee | A fixed-dollar fee paid to the replacement lender at `m`; a receipt to the replacement position. |
| Retiring lender fee | A fixed-dollar exit or prepayment fee paid to a retiring lender at `m`; a receipt to that retiring position. |
| Third-party transaction cost | A fixed-dollar event cost paid to no capital provider (legal, title, appraisal, recording, …). |
| Net event cash `N` | `G` less payoffs, lender fees and third-party costs: positive for a Common Equity distribution, negative for a contribution, and possibly exactly zero. |
| Value dependency | For an LTV-enabled event only: the P7.10 valuation cell that the event's referenced timepoint resolves to, for the exact event scope, model month and variant. |
| NOI dependency | For a DSCR-enabled event only: the executing Analysis Variant's authoritative forward NOI for the exact event scope at `m` (hold year `y + 1`), read through the shared NOI-at-month authority (Section 8.3). |
| Continuing senior position | A debt position of the event scope, senior to the replacement, that is not retired and is still outstanding after `m`. |
| Acquisition-financing reference view | `AcquisitionResults` levered figures and the `PROJECT` perspective: the acquisition loan held through sale, excluding later capital events (Section 12.5). |

Model months follow D6 §4 and P7.7 §7 exactly:

- month 0 is closing;
- month `m >= 1` falls in hold year `((m - 1) // 12) + 1`.

Month 24 is therefore in Year 2, and month 25 is the first month of Year 3.

---

## 5. Scope and explicit exclusions

### 5.1 In scope for V1

- the `REFINANCE` capital event, at hold-year boundaries only;
- at most one refinance event per exact scope, per resolved Capital Structure;
- retiring one or more debt positions (`SENIOR_DEBT`, `MEZZANINE_DEBT`) of the
  event scope, including a Unit's legacy acquisition loan;
- one replacement position per event: an ordinary `CapitalPosition` with
  `DebtTerms`, executed by the accepted P7.8 debt schedule;
- sizing by any non-empty combination of fixed cap, maximum LTV and minimum
  DSCR;
- fixed-dollar replacement lender fees, retiring lender fees and third-party
  costs, all at `m`;
- net event cash to or from Common Equity in hold year `y`;
- propagation to:
  - Position, Common Equity and Partner returns;
  - the Decision Matrix;
  - the memo and report;
  - a formula-audit export (Stage 3);
- layered fingerprints, typed unavailable states and persistence (Stage 2).

### 5.2 Deferred

V1 must refuse or omit each of the following. None may be approximated.

**Other capital events**

- equity recapitalizations, including a new partner buying in;
- preferred-equity injections, and redeeming preferred equity through an event;
- construction or renovation draws, and scheduled future funding;
- revolving facilities;
- reserve deposits, lender holdbacks, funded reserves and reserve releases
  (Section 11.5);
- CapEx or TI/LC facilities;
- supplemental debt that does not retire the selected old debt;
- distributions unrelated to a refinance;
- loan modifications, extensions or rate resets without a funding event.

**Timing and count**

- intra-year events, events at closing, and events at or after the modeled
  sale;
- more than one refinance event per scope, and sequential refinances of one
  Unit;
- Investment-scope refinancing while any Unit-scoped debt remains outstanding
  after the event (Section 12.4).

**Sizing and fees**

- debt-yield sizing, and every other lender test;
- sizing DSCR on an amortizing-underwrite payment during interest-only, a
  lender-policy option (Section 9.3);
- percentage-of-proceeds fees;
- formula-based prepayment costs (yield maintenance, defeasance). V1 accepts a
  stated fixed amount only.

**Loan features**

- floating rates, sculpted amortization, cash sweeps and cash traps (CS-1);
- cross-collateralization, or using one scope's value, NOI, debt or proceeds to
  size or fund another scope's event.

**Cadence, Scenarios and AI**

- monthly Partnership waterfalls, and monthly cash availability;
- refinance-specific Scenario overrides, and Scenario targets acting on
  authored capital terms (Section 13.3);
- AI-computed refinance figures of any kind.

---

## 6. Domain model

The shapes below are contracts, not code. Names are indicative: Stage 1 fixes
exact class, module and enum names without changing meaning (P7 §21.3).

- Every contract is a frozen, slotted, keyword-only dataclass (P7.7 §2).
- Wire values are lower-case `StrEnum` values (CS-2).

### 6.1 Event identity and the extensible base

```text
CapitalEventKind        StrEnum: REFINANCE ("refinance")          # V1's only member

CapitalEvent            the extensible identity every event kind shares
  event_id              stable, opaque, nonblank; unique across the structure's
                        whole capital-event namespace (funding event ids, fee ids,
                        cost-line ids and event ids share one namespace, P7.7 §8)
  kind                  CapitalEventKind
  scope                 PositionScope                              # exact scope
  timing                EventTiming
  label                 analyst-facing text; presentation only; never economic
```

- **Identity is `event_id`, never `label`.**
  - A label rename changes no fingerprint and no result.
  - An internal id is never shown as an analyst-facing label (Section 15.3).
- **P-8 carried over.** Within one Investment, an `event_id` that appears in
  more than one structure (Base and a Strategy's own) names one economic
  event.
  - Its `kind` and `scope` must agree everywhere. A conflict is refused
    (`capital_event_kind_conflict`, `capital_event_scope_conflict`).
  - Its timing, constraints, retirements, replacement and costs may differ.
    That is what a Strategy is for.

### 6.2 Timing

```text
EventTiming
  model_month           int; must be 12y for an integer y >= 1
  sequence              int; explicit order among capital events of one scope at
                        one model month (P7 §15.5). V1 permits one event per scope,
                        so V1 requires sequence = 1.
```

- `hold_year = m / 12` is derived and never stored separately.
- Whether `y <= H - 1` depends on the variant's hold period. That check
  therefore runs at execution (Section 15.2), not at authoring.

### 6.3 The refinance event

```text
RefinanceEvent (CapitalEvent with kind = REFINANCE)
  retiring              tuple[RetiringPositionRef, ...]            # non-empty
  replacement_position_id   str                                    # an authored position
  sizing                RefinanceSizing
  valuation             RefinanceValuationRef | None               # iff MAX_LTV present
  costs                 tuple[RefinanceCostLine, ...]              # may be empty

RetiringPositionRef     exactly one of:
  AuthoredPositionRef(position_id)                                 # an authored debt position
  LegacyAcquisitionLoanRef(unit_id)                                # the Unit's adapted loan
```

- The legacy loan is referenced by a **typed reference**, never by the
  reserved string `legacy-acquisition-loan:<unit_id>`. That prefix stays
  reserved and is never stored (P7.7 §5).
- `retiring` is order-irrelevant. For fingerprints it is canonicalized by
  (kind, id). A duplicate is refused.

### 6.4 Sizing

```text
RefinanceSizing
  fixed_cap             FixedProceedsCap | None
  max_ltv               MaxLtvConstraint | None
  min_dscr              MinDscrConstraint | None
                        at least one must be present (else no_sizing_constraint)

FixedProceedsCap        amount: finite, > 0
MaxLtvConstraint        max_ltv: finite, 0 < max_ltv <= 1          # the P7.7 funding-pct domain
MinDscrConstraint       min_dscr: finite, > 0

ConstraintKind          StrEnum: FIXED_CAP | MAX_LTV | MIN_DSCR    # canonical order
```

- An absent constraint is disabled, and a disabled constraint has no target.
- There is no separate "enabled" flag that could carry a stale target, so
  exact semantic revert is automatic (FP-1, FP-2).

### 6.5 Dependencies by constraint

Each constraint has its own dependency. **Neither ever substitutes for the
other.**

| Constraint | Consumes | Does not consume |
| --- | --- | --- |
| `FIXED_CAP` | its amount only | any value or NOI |
| `MAX_LTV` | the referenced P7.10 valuation cell for the exact scope and month (Section 8.1) | forward NOI (a direct-cap cell's operand is P7.10's business, not an LTV input) |
| `MIN_DSCR` | the Analysis Variant's authoritative forward NOI for the exact scope and month (Section 8.3) | any P7.10 valuation, value, valuation result or evidence |

```text
RefinanceValuationRef
  timepoint_id          a P7.10 ValuationTimepoint of the same Investment
```

The valuation reference rules:

- **Required iff `max_ltv` is present** (`valuation_reference_required`).
- **Refused when `max_ltv` is absent** (`valuation_reference_unused`),
  including for DSCR-only, fixed-only and fixed-plus-DSCR events. An unused
  reference would otherwise become a consumed dependency that stales and
  blocks for no economic reason (P7.10 §22.6).
- The event stores the reference, never a copied value. The value is always
  resolved fresh for the executing variant.
- A DSCR constraint holds no reference of any kind. Its NOI dependency is
  already part of the Project / Analysis Variant source fingerprint, and its
  target (`min_dscr`) is part of the event (Section 14).

### 6.6 The replacement funding rule

```text
RefinanceProceeds       a new FundingAmountRule member
  capital_event_id      the RefinanceEvent that sizes this funding
```

The replacement position is an ordinary authored `CapitalPosition`:

- `position_class` is `SENIOR_DEBT` or `MEZZANINE_DEBT`, with `DebtTerms`;
- `scope` equals the event scope;
- `funding` is **exactly one** `FundingEvent`, with `model_month = m` and
  `amount_rule = RefinanceProceeds(event_id)`;
- `shortfall_resolution` is explicit, as for every claim-bearing position
  (P7.7 §6.1);
- its `DebtTerms.fees` are the replacement lender fees, each fixed-dollar and
  at model month `m`;
- `priority` follows the succession rule (Section 10.3).

Because the replacement is a first-class member of
`CapitalStructure.positions`, it automatically takes part in:

- scheduling and economic order;
- position identity (P-8) and the `POSITION` perspective;
- fingerprints and persistence.

This is P7 §12.5's "a CapitalPosition funded at m". There is no event-owned
parallel loan.

### 6.7 Event cost lines

```text
RefinanceCostKind       StrEnum: RETIRING_LENDER_FEE | THIRD_PARTY_COST

RefinanceCostLine
  cost_id               stable, opaque; in the capital-event namespace
  kind                  RefinanceCostKind
  amount                fixed dollars; finite, >= 0 (a zero line is an explicit,
                        auditable event that moves nothing, as P7.8 §14.5 accepts)
  recipient             RetiringPositionRef, required for RETIRING_LENDER_FEE and
                        must name one of this event's retiring positions;
                        absent for THIRD_PARTY_COST
  description           presentation only
```

- **Replacement lender fees are not cost lines.** They are the replacement
  position's own `DebtTerms.fees` at `m`, and P7.8 §5 counts them as receipts
  to that position. Recording them in both places would count them twice.
- Every fee and cost is a fixed-dollar amount. No percentage rule exists in
  V1.

### 6.8 Result contracts

```text
RefinanceStatus         StrEnum:
  EXECUTED              sized, funded and settled; downstream results available
  UNAVAILABLE           a required external dependency is missing or invalid
  NOT_EXECUTABLE        dependencies resolved, but the least capacity is <= 0
  BLOCKED               an upstream unresolved Funding Requirement in the scope at
                        or before year y stops settlement (P7.8 §10)

ConstraintCapacity
  kind                  ConstraintKind
  status                AVAILABLE | UNAVAILABLE
  capacity              float | None              # None iff UNAVAILABLE
  operands              typed per kind, reported so the arithmetic is checkable:
    FIXED_CAP:  amount
    MAX_LTV:    max_ltv, scope_value, continuing_senior_balance
    MIN_DSCR:   min_dscr, forward_noi, continuing_senior_service,
                service_capacity, first_year_service_per_dollar
  unavailable_reason    RefinanceUnavailableReason | None
  unavailable_message   analyst-facing | None

SizingOutcome
  capacities            tuple[ConstraintCapacity, ...]   # enabled only, canonical order
  gross_proceeds        float | None                     # None unless every enabled
                                                         # capacity is AVAILABLE
  binding               tuple[ConstraintKind, ...]       # canonical order; empty iff None
  tie                   bool                             # len(binding) > 1

ValueDependency         present iff MAX_LTV is enabled
  timepoint_id, scope, model_month, method, analyst_supplied, status, value

NoiDependency           present iff MIN_DSCR is enabled
  scope, model_month, forward_year (= y + 1), status, forward_noi

RetiringPayoff
  ref                   RetiringPositionRef
  scheduled_payment_at_m    float     # the month-m payment, settled as operating service
  payoff                float         # balance immediately after that payment
  payoff_authority      AUTHORED_SCHEDULE | ACQUISITION_DEBT_BALANCE_SERVICE
  retiring_lender_fees  float         # sum of this position's RETIRING_LENDER_FEE lines

ReplacementFunding
  position_id           str
  funding_month         m
  gross_proceeds        G
  replacement_lender_fees   float     # sum of DebtTerms.fees at m
  first_service_month   m + 1
  first_year_service    float         # months m+1 .. m+12, from the debt schedule
  achieved_ltv          (G + continuing_senior_balance) / scope_value
                        | None where no value dependency exists
  achieved_dscr         forward_noi / (continuing_senior_service + first_year_service)
                        | None where no NOI dependency exists

RefinanceBridge                       # the event audit bridge, Section 11.1
  gross_proceeds        G
  payoffs               sum of RetiringPayoff.payoff
  replacement_lender_fees
  retiring_lender_fees
  third_party_costs
  net_event_cash        N
  direction             DISTRIBUTION | CONTRIBUTION | ZERO

RefinanceResult
  event_id, kind, scope, model_month, hold_year
  status                RefinanceStatus
  value_dependency      ValueDependency | None
  noi_dependency        NoiDependency | None
  sizing                SizingOutcome | None       # present whenever capacities were attempted
  payoffs               tuple[RetiringPayoff, ...] | None
  funding               ReplacementFunding | None  # EXECUTED only
  bridge                RefinanceBridge | None     # EXECUTED only
  unavailable_reason    RefinanceUnavailableReason | None
  unavailable_message   analyst-facing | None
```

Additive changes to existing results. All are defaulted, so every existing
result decodes unchanged:

- `StructuredCapitalResult.capital_events: tuple[RefinanceResult, ...] = ()`.
- `CommonEquityReturns.event_cash_flows: tuple[float, ...] | None`: `N` at
  `t = y`, and `0.0` elsewhere.
- `CommonEquityReturns.recurring_cash_flows`: `cash_flows - event_cash_flows`.
  - Both new series are `None` whenever `cash_flows` is `None`.
  - Both are omitted from the wire and from the fingerprint when no event
    exists (FP-2).
- `PositionCashFlowKind.REFINANCE_PAYOFF` and
  `PositionCashFlowKind.REFINANCE_FUNDING`. An event payoff or replacement
  funding is therefore never confused with a `BALLOON` or a closing `FUNDING`.
- `CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE` (Section 15.4).

---

## 7. Timing convention

### 7.1 The rule

A V1 refinance occurs only at a hold-year boundary:

```text
m = 12y,   1 <= y <= H - 1
```

- **Not at closing (`m = 0`).** Closing financing is the acquisition loan or
  an authored closing position.
- **Not at or after the modeled sale (`m >= 12H`).**
- **Not inside a hold year.** That is deferred: it would need a forward-NOI
  convention inside a year (P7.10 §5.2) and partial waterfall periods (P7.9
  PW-4).

This matches three existing conventions:

- P7.10's storable valuation months (`12y`, `1 <= y <= H - 1`), so an LTV
  event can always be paired with a valuation at its own month;
- P7.10 §5.3's forward-NOI convention at hold-year ends, which is what DSCR
  needs;
- P7.9's annual periods, so event cash falls wholly inside one annual period.

### 7.2 Ordering at the boundary

At model month `m = 12y`, in this order:

1. **Scheduled payment.** Every retiring position makes its ordinary scheduled
   payment for month `m`, exactly as its accepted schedule produces it. That
   payment belongs to hold year `y`, and is settled as ordinary operating debt
   service for year `y` (Section 11.3).
2. **Payoff amount.** Each retiring position's payoff is its remaining
   principal immediately after that month-`m` payment, from its payoff
   authority (Section 10.2).
3. **Funding.** The replacement position funds `G` at month `m`. Its fees, the
   retiring lender fees and the third-party costs are paid at `m`.
4. **Event cash.** `N` belongs to hold year `y` (annual period `t = y`).
5. **New service.** The replacement's first scheduled payment is at month
   `m + 1`, the first month of hold year `y + 1`. Its interest-only and
   amortizing months are counted from its funding: IO months are
   `m + 1 .. m + 12 x io_period`, and the amortizing payments follow.
6. **Sale.** The replacement's balance at the modeled sale is repaid from sale
   proceeds at `12H`, as P7.8 §6 does for every debt position.

### 7.3 "Refinance after Year 2; the new loan starts in month 25"

This is the convention above with `y = 2`:

| Model month | Old loan | New loan | Hold year |
| --- | --- | --- | --- |
| 1 .. 23 | scheduled payments | — | 1, 2 |
| 24 | scheduled payment, then payoff of the remaining balance | funds `G`; fees paid | 2 |
| 25 .. 36 | none | first twelve scheduled payments | 3 |
| 25 .. 12H | none | scheduled payments; sale-date payoff at 12H | 3 .. H |

The whole event falls in Year 2's annual period: the old loan's last payment,
the payoff, the funding, the fees and `N`. The new loan's debt service falls
wholly in Years 3 to `H`.

No annual period is split. The annual Partnership waterfall therefore sees
each period as one net contribution or one net distribution (PW-4), and needs
no partial-period rule.

### 7.4 Replacement maturity

- **Minimum maturity.** `DebtTerms.maturity_month` is a model month and must
  satisfy `maturity_month >= m + 12` (`replacement_maturity_too_early`). A
  replacement maturing inside its first year is bridge financing, which is
  deferred.
- **Modeled payoff.** It follows P7.8 §6 unchanged, with the schedule offset
  to the funding month:
  `modeled_payoff_month = min(maturity_month, 12H, m + io_months + n_payments)`.
- **Earlier maturity.** A legal maturity before `12H` produces a balloon claim
  at maturity, settled exactly as P7.8 settles any debt position's balloon.
  V1 adds no automatic second refinance.

---

## 8. Dependencies: value for LTV, forward NOI for DSCR

### 8.1 The value dependency (LTV only)

A refinance with `max_ltv` enabled needs a value, and it uses exactly one
source. That source is the P7.10 valuation cell that the event's
`timepoint_id` resolves to, subject to all of the following:

- **Same Investment.** The timepoint belongs to the same Investment as the
  Capital Structure.
- **Exact scope.**
  - A `UNIT(u)` event uses that Unit's `UnitValuationResult`.
  - An `INVESTMENT` event uses the `InvestmentValuationResult`. That exists
    only when every member Unit is valued at that month (P7.10 §5.5).
- **Same month.** `timepoint.model_month == m`.
- **Executing variant.** The cell is resolved for the executing Analysis
  Variant, so a Strategy or Scenario that changes forward NOI changes a
  direct-cap value (P7.10 §5.3).
- **Available.** The cell's status is `AVAILABLE`. That includes the Stage 2
  evidence-approval gate for `ANALYST_VALUE` (P7.10 §22.3).

### 8.2 What is never permitted

**For the value:**

- purchase price, transaction price or any cost basis;
- a value from another model month, including the nearest timepoint;
- a value from another scope, or a partial Investment sum;
- the D6 Exit view (which is `12H`, outside V1 timing);
- inferred stabilization, or any automatic choice of timepoint;
- a value copied into the event and reused after the valuation changes.

**For forward NOI:**

- a valuation cell used as the NOI source;
- an analyst-supplied value treated as implying NOI;
- NOI from another year, month or scope;
- NOI derived by the refinance engine itself.

**For both:**

- zero substituted for anything unavailable;
- either dependency falling back to the other.

Each failure produces a typed state (Section 15). None falls back.

### 8.3 The NOI dependency (DSCR only)

The DSCR constraint needs the event scope's forward NOI at `m`. That is hold
year `y + 1`: `noi_by_year[y]` in the zero-indexed tuple, matching P7.10
§5.3's convention at a hold-year end.

**The shared authority.** Forward NOI is read through **one authoritative
NOI-at-month seam over the executing Analysis Variant**. That seam is:

- the function P7.10 already uses (`forward_noi_at` over the variant's
  resolved `ValuationUnitInputs`); or
- the same logic, extracted unchanged into a shared authority that both P7.10
  and the refinance layer call.

The refinance engine contains no NOI mathematics. If Stage 1 extracts the
seam, P7.10's results must stay bit-identical, and the P7.10 guards are
re-pinned rather than relaxed.

**By scope:**

- **Unit scope** reads that Unit's forward NOI.
- **Investment scope** reads the canonical `unit_id`-order sum over the
  variant's included Units. It asserts that the sum reconciles, bit for bit,
  to the accepted consolidated NOI authority
  (`ConsolidatedResults.noi_by_year[y]`) wherever that authority is
  available.

**Reconciliation with a direct-cap valuation.** Where a `DIRECT_CAP`
valuation cell exists for the same scope and month, its recorded
`forward_noi` must equal the shared authority's figure bit for bit. This is a
consistency assertion only: the cell is never the NOI source. A mismatch is an
engine defect, refused as `forward_noi_authority_mismatch`, and is never
reconciled.

**What a DSCR-only event does not touch.** An analyst-supplied valuation is
never a NOI source. A DSCR-only or fixed-plus-DSCR event:

- consumes no P7.10 valuation;
- creates no valuation-definition, valuation-result or evidence-approval
  dependency, and no staleness from any of them;
- can execute when no valuation timepoint exists at all.

**When LTV and DSCR are both enabled,** they share the same scope and the same
event month, but their dependencies stay separate:

- LTV consumes the referenced P7.10 value;
- DSCR consumes the variant's forward NOI;
- if one is unavailable, the other is still reported, and the event is
  unavailable (Section 9.5).

### 8.4 Available, executable, unavailable, none

| State | Meaning | Result |
| --- | --- | --- |
| No refinance configured | the resolved structure has no event for the scope | no `RefinanceResult`; byte-identical to today (Section 19) |
| Available configuration | the event passes structural validation (Section 15.1) | may be saved; says nothing yet about any variant |
| Valid and executable | every enabled constraint's dependency resolves for this variant, and `G > 0` | `EXECUTED`, with the bridge and downstream results |
| Configured but unavailable | a dependency outside the structure is missing or invalid for this variant | `UNAVAILABLE` with a typed reason; downstream N/A (Section 15.4) |
| Configured, not executable | every dependency resolved, but the least capacity is `<= 0` | `NOT_EXECUTABLE`; capacities reported; downstream N/A |
| Configured, blocked | an upstream Funding Requirement in the scope is unresolved at or before `y` | `BLOCKED`; downstream N/A, as P7.8 §10 already requires |

---

## 9. Sizing equations

Notation, for scope `S`, event month `m = 12y`, and the executing variant:

| Symbol | Meaning | Authority | Used by |
| --- | --- | --- | --- |
| `V` | contemporaneous value of `S` at `m` | the referenced P7.10 cell (Section 8.1) | LTV only |
| `NOI_f` | forward NOI of `S` at `m` (hold year `y + 1`) | the shared NOI-at-month authority (Section 8.3) | DSCR only |
| `B_sen` | sum of continuing senior positions' balances immediately after their month-`m` payments | their accepted schedules (Section 10.2 for a continuing legacy loan) | LTV |
| `DS_sen` | sum of continuing senior positions' scheduled payments in months `m+1 .. m+12`, excluding balloons (the P7.8 §13 coverage convention) | their accepted schedules; for a continuing legacy loan, `AcquisitionResults.annual_debt_service[y]` | DSCR |
| `s_1` | replacement first-year scheduled service per dollar of principal | Section 9.3 | DSCR |

### 9.1 Fixed cap

```text
C_FIXED = fixed_cap.amount
```

A cap limits proceeds. It is never an instruction to borrow more than another
enabled constraint allows.

### 9.2 Maximum LTV, through the position

```text
C_LTV = max_ltv x V - B_sen
```

- `max_ltv x V` is the combined debt the lender permits through the
  replacement's rank, and continuing senior debt uses it first.
- Under succession (Section 10.3), `B_sen = 0` whenever the scope's most
  senior debt is being retired, which is the ordinary case. Then
  `C_LTV = max_ltv x V`.
- Positions junior to the replacement are ignored.
- Only the same scope's debt ever enters `B_sen` (Section 12.4).

### 9.3 Minimum DSCR, through the position

```text
service_capacity  = NOI_f / min_dscr - DS_sen
s_1               = first-year scheduled service of a $1 replacement principal,
                    months m+1 .. m+12, from the reused debt schedule
C_DSCR            = service_capacity / s_1
```

- **No mortgage formula in the event engine.** `s_1` comes from the P7.8
  capital-structure debt wrapper (`capital_structure/debt_position.py`), the
  only capital-structure caller of the unchanged `debt.py` functions. It is
  evaluated with the replacement's own `DebtTerms` and a unit principal.
- **Proportionality is a proven precondition, not an assumption.** Anchor's
  scheduled payment is a fixed factor times principal:
  - branch 2: `P / n`;
  - branch 3: `P x rate_fraction`;
  - IO: `P x monthly_rate`.

  Stage 1 must prove, over the fixture set and randomized terms, that the
  wrapper's first-year service of `C_DSCR` equals `service_capacity` within
  `1e-9` relative. If that proof fails for any branch, Stage 1 stops and
  reports rather than adding a solver.
- **Basis: actual first-year service.** DSCR is sized on the replacement's
  actual scheduled service in its first twelve months, including
  interest-only service where `io_period >= 1`.
  - *Disclosure:* some lenders underwrite DSCR on an amortizing payment even
    during an interest-only period. That lender-policy basis is a deferred
    option (Section 21.2). Stage 3 must state the V1 basis beside every DSCR
    capacity.
- **Zero service per dollar.** A 0% interest-only replacement has `s_1 = 0`,
  so DSCR capacity is undefined. With `min_dscr` present it is refused at
  authoring (`dscr_zero_first_year_service`), and never read as unlimited.
- **Achieved DSCR** is reported, not used for sizing:
  `NOI_f / (DS_sen + first_year_service(G))`, from the executed schedule.
  When DSCR binds, it must satisfy `achieved_dscr >= min_dscr x (1 - 1e-9)`.
  Anything less is an engine defect, and Stage 1 stops.

### 9.4 Availability of each capacity

| Constraint | Unavailable when | Reason |
| --- | --- | --- |
| `FIXED_CAP` | never | — |
| `MAX_LTV` | the referenced cell is not `AVAILABLE` for the exact scope and month | `valuation_unavailable`, carrying P7.10's own reason; or `timepoint_not_found`, `model_month_mismatch`, `scope_not_covered`, `evidence_not_approved` |
| `MIN_DSCR` | the variant's shared NOI authority yields no forward NOI for the scope and month | `forward_noi_unavailable` |
| `MIN_DSCR` | `NOI_f <= 0` | `non_positive_forward_noi`. The NOI is never floored (the P7.10 §5.3 precedent) |

A valuation failure never makes `MIN_DSCR` unavailable. A NOI failure never
makes `MAX_LTV` unavailable.

A capacity can be computed and still be `<= 0`, for example when continuing
senior debt already uses the LTV. That is an available capacity with a real
value, and it makes the event `NOT_EXECUTABLE` (Section 9.5).

### 9.5 Executed gross proceeds

```text
if any enabled capacity is UNAVAILABLE:   status = UNAVAILABLE;  G = None
else:
    G = min(C_i for i in enabled)          # exact float min, no rounding
    if G <= 0:                             status = NOT_EXECUTABLE;  G = None
    else:                                  proceed to execution
```

- **Every enabled constraint must be known.** The least of a partial set
  could exceed the unknown one. An unavailable constraint is never dropped
  from the minimum, and the others are still reported.
- **A non-positive limiting capacity is `NOT_EXECUTABLE`.** Anchor never
  silently keeps the old loan in place as though the authored Strategy had no
  refinance.
- **`G > 0` is required.** A zero-dollar position does not exist (P7.7 §8).

### 9.6 Binding constraints and ties

```text
tol_bind = 1e-9 x max(1, |G|)
binding  = [ k for k in canonical order (FIXED_CAP, MAX_LTV, MIN_DSCR)
             if C_k - G <= tol_bind ]
tie      = len(binding) > 1
```

- **The tolerance absorbs floating-point representation only.** For example,
  `0.05 / 12 x 12` is not exactly `0.05`. It sits nine orders of magnitude
  below a cent, so presentation rounding can never decide what binds.
- **`G` is the exact float minimum.** The tie tolerance never alters it.
- **Canonical order fixes list order only.** It confers no priority, and
  every tied constraint is reported as binding.

### 9.7 Rounding and precision

- The engine never rounds a dollar, rate or ratio (P7.8, D6).
- Presentation rounds to cents and display precision only at the
  presentation boundary. A rounded figure never feeds a calculation, a binding
  decision or a fingerprint.
- Conservation identities use the P7.9 §14 tolerance
  `tol = 1e-6 + 1e-12 x |x|` per figure.
- Fixture expectations are exact rationals, compared to float results within
  that tolerance through a test-only `fractions.Fraction` oracle.

---

## 10. Replacement-debt mechanics

### 10.1 An ordinary position

The replacement is a `CapitalPosition` executed by P7.8. There is no parallel
model.

- **Schedule.** Its schedule is P7.8 §6's, offset to funding month `m`
  (Section 7.2), and it reuses the same `debt.py` functions through the same
  wrapper.
- **Execution restrictions.** P7.8 §6's restrictions apply unchanged:
  `pik_rate = 0` and `current_pay_rate = interest_rate`.
- **Claims.** Its annual claims (P7.8 §8) exist for hold years `y + 1 .. H`.
  They are settled by the unchanged `settle_claim` under its own explicit
  resolution.
- **Returns.** Its position returns (P7.8 §12) use the annual series
  `t = 0..H`:
  - zero before `y`;
  - at `y`, `-G` plus its lender fees;
  - then its receipts.

  MOIC and profit follow P7.8 §12 with `funded_amount = G`.
- **Structural metrics** (P7.8 §13) are measured at the event:
  - the attachment basis is `B_sen`;
  - the detachment and last-dollar basis is `B_sen + G`;
  - coverage through the position is `None` before year `y + 1` and after its
    modeled payoff year;
  - P7.8's loan-to-price stays defined against the price basis. Stage 3 labels
    it as such, and shows `achieved_ltv` against the event value beside it
    where an LTV value dependency exists.
- **Everything else is ordinary.** It takes part in fingerprints, the
  `POSITION` perspective, sale payoff, persistence and export exactly as any
  authored debt position does.

### 10.2 Retiring positions and payoff authority

**Authored retiring position.** Its payoff authority is its own accepted P7.8
schedule, produced through the capital-structure debt wrapper:

- The schedule is cut at `m`. It keeps every scheduled payment through
  month `m`.
- Its post-payment balance at `m` becomes a `REFINANCE_PAYOFF` event
  (sequence 2 at `m`), in place of any later payment or balloon.
- It has no events after `m`, and its `modeled_payoff_month` is `m`.
- Its `maturity_month` is reported unchanged. P7.8 never rewrites legal
  maturity.

**Legacy acquisition loan: the acquisition-debt balance service (R-M).**
`AcquisitionResults` records the legacy loan's balance only at the sale date,
but a refinance needs its balance after month `m`. The contract closes that gap
with a narrow, explicit extension of P7.7's boundary:

- **The P7.7 adapter is unchanged.** It still imports no debt function and
  still treats `AcquisitionTerms` as descriptive only.
- **A new engine service.** Refinance execution calls an **authoritative
  acquisition-debt balance service owned by Anchor's existing
  debt / acquisition engine** (the `anchor.engine` package, beside
  `calculate_debt_schedule`). Capital Structure owns no part of it.
- **What it reuses.** It reuses the accepted `debt.py` functions and the
  accepted acquisition-loan inputs: the resolved `AcquisitionTerms` of the
  executing variant, which is the same object that produced its
  `AcquisitionResults`.
  - Capital Structure must not implement its own amortization recurrence.
  - Neither may the export layer or the UI.
  - There is exactly one payoff formula: the accepted recurrence
    (`calculate_amortization_schedule`).
- **What it returns.** The legacy loan's balance immediately after the
  scheduled payment at event month `m`.
- **Reconciliation on every call.** Each figure is recomputed through the same
  accepted functions that produced the accepted figure, and must match bit for
  bit:
  - the accepted acquisition-loan economics: `loan_amount` and
    `monthly_debt_service` equal `AcquisitionResults`;
  - annual scheduled debt service for years `1..y` equals
    `AcquisitionResults.annual_debt_service[0..y-1]`;
  - the balance at `min(12H, io_months + n_payments)` equals
    `AcquisitionResults.remaining_loan_balance`.
- **Failure is an engine defect.** Any reconciliation failure is a typed
  refusal, `legacy_payoff_reconciliation_failure`. It is never adjusted,
  tolerated or silently replaced.
- **Read, never mutate.** The refinance layer consumes the returned balance
  and never mutates `AcquisitionResults`, `AcquisitionTerms` or the legacy
  adapter.
- **Only a refinance calls it.** No-refinance execution never calls the
  service and stays byte-identical (Section 19).
- **Stage 1 proof.** Stage 1 proves this seam with:
  - exact-rational cases;
  - zero-rate, positive-rate amortizing and interest-only cases;
  - a payoff at the IO boundary;
  - mutation tests (F8, F9b; Section 18.3).

**Historical identity.** A retiring position stays identifiable:

- it keeps its `position_id` (or legacy reference), its provider cash flows
  through `m`, its returns, and a `retired_by_event_id`;
- it is never deleted from results;
- it is never shown as outstanding after `m`.

**What may retire.**

- Only `SENIOR_DEBT` or `MEZZANINE_DEBT` positions of the event scope.
- Each must be outstanding after its month-`m` payment (`payoff > 0`). A
  position already extinguished before `m`, by maturity or by full
  amortization, cannot be retired.
- A position whose legal maturity is exactly `m` may be retired. The event
  takes it out at maturity, and its would-be balloon becomes the event
  payoff.

### 10.3 Priority succession (R-N)

The replacement **succeeds** to the rank of the debt it replaces:

- Its `priority` must equal the priority of the most senior retiring position
  (`replacement_priority_not_successor`). When the legacy loan is retired,
  that is priority 1.
- P7.7 §8's uniqueness rule is amended **only** for such a succession pair. A
  retiring position and its replacement may share a priority because their
  outstanding intervals do not overlap:
  - the retiring position is outstanding through `m`;
  - the replacement is funded at `m` and has no claim before `m + 1`.
- Every other duplicate priority in a scope is still refused, and every other
  P7.7 structural rule stands.
- Replacing a senior loan with debt that ranks junior to a continuing position
  is deferred.

### 10.4 No service overlap

- For every month `k > m`, no retiring position has any cash-flow event.
- For every month `k <= m`, the replacement has only its `REFINANCE_FUNDING`
  event and its fees, both at `m`.

Debt service is therefore never doubled at or after the boundary (INV-9).

---

## 11. Event cash waterfall

### 11.1 The bridge

```text
  G                         gross replacement funding
- P  = sum_i payoff_i       payoff of every retiring principal balance
- F_R                       replacement lender fees (replacement DebtTerms.fees at m)
- F_X = sum RETIRING_LENDER_FEE lines
- T  = sum THIRD_PARTY_COST lines
= N                         net refinance cash to (+) or from (-) Common Equity
```

- `N > 0` is a **Common Equity distribution** in hold year `y`.
- `N < 0` is an **explicit Common Equity contribution** in hold year `y`.
- `N = 0` is a real computed zero, with direction `ZERO`. It is shown as `$0`,
  never as N/A.

The retiring positions' month-`m` scheduled payments are **not** in the
bridge. They are ordinary year-`y` operating debt service (Section 11.3).

### 11.2 Provider cash flows at the event

| Party | Cash at `m` (provider sign: received is positive) |
| --- | --- |
| Replacement lender | `-G + F_R` |
| Each retiring lender `i` | `+payoff_i + F_X,i`, plus its ordinary month-`m` scheduled payment, which is recorded separately as service |
| Third parties | `+T` (not a capital position; reported in the bridge only) |
| Common Equity | `+N` |

**Conservation at the event (INV-2):**
`(-G + F_R) + sum_i (payoff_i + F_X,i) + T + N = 0`.

Fees are attributed honestly:

- replacement lender fees are receipts in the replacement position's returns;
- retiring lender fees are receipts in that retiring position's returns;
- third-party costs reach no capital position's returns and reduce Common
  Equity through `N`.

### 11.3 Where the event sits in the annual settlement

For the event scope in hold year `y`:

1. **Operating settlement comes first,** exactly as P7.8 §9 specifies. Every
   year-`y` claim is settled in priority order against the operating residual,
   including each retiring position's scheduled service for months
   `12(y-1)+1 .. 12y`. **A retiring position's year-`y` claim contains no
   payoff.**
2. **The event bridge settles next,** at `m`, after the month-`m` scheduled
   payments (Section 7.2). The payoff and the event fees are paid **by the
   event**, never from operating cash. `N` is added to that year's residual.

```text
CECF_y = CECF_y^operating + N
CECF_t = CECF_t^operating            for t != y
```

- **A negative `N` is an explicit Common Equity contribution, not a Funding
  Requirement.** P7.7's Funding Requirement reports a contractual claim that
  operating cash could not meet. A negative `N` is the event's own stated
  settlement term: FR-2's "common-equity contribution" mechanism, stated as a
  term of the event.
  - It is not a global cure, so FR-3 stands.
  - It is reported as the bridge's `CONTRIBUTION` direction, never as a
    resolved or unresolved Funding Requirement.
  - This refines P7.8 §8 for event payoffs only (Section 22.3).
- **Proceeds never cure an earlier operating shortfall.** They arrive after the
  month-`m` payments, so they are not eligible cash for any year-`y` claim.
- **Downstream layers see the annual net.** The decomposition stays reported
  through `recurring_cash_flows` and `event_cash_flows`.

### 11.4 What the event never changes

The refinance is a capital event (P7 §12.5, P-4). It never changes:

- NOI, EGI, operating expenses, CapEx, TI/LC or any other operating line;
- Project Capital, Owner Expenses or the Business Plan;
- the property value, any P7.10 valuation, the exit value, disposition costs
  or the sale price;
- Owner Cash Flow above financing (the unlevered and pre-structured-capital
  authorities);
- `AcquisitionResults` and `ConsolidatedResults`, which are read and never
  written;
- D6's Net Additional Equity Requirement, which remains a project figure
  (§13.4).

It is also excluded from every recurring measure:

- `AcquisitionResults.levered_cash_on_cash_by_year`, cumulative operating
  distributions and every Owner Return Metrics V3 figure are unaffected by
  construction.
- Any Common Equity recurring measure a later gate adds must read
  `recurring_cash_flows`. V1 adds none.

### 11.5 Reserves and holdbacks

V1 has **no** reserve, holdback, escrow or release field on any wire payload,
persisted table or contract.

- An authoring payload carrying such a field is refused by the codec as an
  unknown field.
- A value is never silently dropped.
- Every dollar of `G` is fully accounted for at `m` by
  `P + F_R + F_X + T + N`.

A later extension may add reserves only with all of the following:

- a complete, deterministic deposit, use and release schedule;
- its own conservation identity;
- its own ratification.

---

## 12. Returns, partnership and presentation semantics

### 12.1 Which namespaces change

| Namespace | Changes? | How |
| --- | --- | --- |
| Project (D6 / `AcquisitionResults`, `PROJECT` perspective) | **No** | P-4 and P7.8B §7: Capital Structure never reaches a Project input, result or fingerprint. Its levered figures keep describing the acquisition loan held through sale |
| Position returns (`POSITION` perspective) | Yes | the retiring and replacement positions, and junior positions whose residual changes after `y` |
| Common Equity after Capital Structure | Yes | `CECF` changes in years `y..H` |
| Partnership and Partner returns (`PARTNER` perspective) | Yes | through the unchanged P7.9 seam |
| Decision Matrix, memo, report, export | Yes, in the Position and Partner perspectives and in Common Equity figures | Stage 3, under Section 12.5 |

Refinance-adjusted returns are **Common Equity returns after Capital
Structure** and, where a Partnership exists, **Partner returns**. They are
never called Project returns (P7 §14; P7.8 §11 NS-1).

### 12.2 Common Equity

`CommonEquityReturns` reads the final residual series, event cash included,
through the unchanged `common_equity_metrics`:

- `evaluate_irr`;
- `calculate_equity_multiple`;
- `calculate_project_return_totals`.

`total_equity_invested` and `total_cash_returned` count `N` through the annual
net in year `y`, exactly as they count every other period.

### 12.3 Partnership

The Partnership consumes `StructuredCapitalResult.common_equity.cash_flows`
through the P7.9 `common_equity_input` adapter (P7.9 §3). The waterfall engine
is unchanged:

- **Period `t = y`.** A positive `CECF_y`, event cash included, enters the
  tiers as distributable cash (step 4). A negative `CECF_y` is allocated as
  partner contributions, which are capital calls (step 3, §13.4).
- **Conservation.** PW-5 and P7.9 §14 identities 1–17 hold in every period,
  including `y`.
- **No refinance-specific treatment.** There is:
  - no refinance tier;
  - no "refinance promote";
  - no special split of refinance proceeds;
  - no carve-out of `N` from the hurdle accounts.
- **Annual only.** V1 stays annual (PW-4).

**The one adapter change (R-O).** When a refinance is `UNAVAILABLE` or
`NOT_EXECUTABLE`, Common Equity is unavailable with the new reason
`refinance_unavailable`.

- The adapter accepts and propagates that exact upstream reason, and the
  event id.
- The Partnership is then `UNAVAILABLE` with `COMMON_EQUITY_UNAVAILABLE`.
- Previously the adapter refused any missing series lacking an
  unresolved-funding reason (`invalid_common_equity_series`). That refusal
  stands for every other missing series.
- The waterfall mathematics do not change.

A `BLOCKED` event keeps P7.7's existing `unresolved_funding_requirement`
reason (Section 15.4).

### 12.4 Multi-unit Investments and scope isolation

- **One event per Unit.** Each Unit may have at most one event, sized only
  from that Unit's value (for LTV), its forward NOI (for DSCR) and its own
  debt, and settled in its own scope.
- **Flow to the Investment.** A Unit's net event cash reaches the Investment
  residual exactly as P7.8 §9 carries every other settled Unit flow: once, in
  canonical `unit_id` order.
- **Timing.** Unit events may fall in different hold years.
- **Netting at the root.** Common Equity at the root is one annual series, so
  Unit A's contribution and Unit B's operating distribution in the same year
  net there. That is ordinary consolidation of the root's common equity. It
  is not cross-collateralization, because neither Unit's claims are settled
  from the other's cash.
- **Investment-scope events.** An `INVESTMENT`-scope event may retire only
  `INVESTMENT`-scoped debt. It sizes against the complete Investment value
  (LTV) and the reconciled Investment forward NOI (DSCR).
  - It is refused (`investment_refinance_with_unit_debt`) while any
    Unit-scoped debt, legacy or authored, is outstanding after `m` in any
    Unit.
  - That case is deferred. V1 never counts another scope's debt in a
    constraint.

### 12.5 Primary return views and labeling (R-P)

The namespace separation above is permanent. Presentation must make it
impossible to mistake one namespace for the other. **When a refinance is
configured and executed** in the variant being presented:

1. **Common Equity after Capital Structure is the primary current
   underwritten equity-return view.** It is reachable, and shown, whether or
   not a Common Equity marker is authored.
2. **Partner returns are the primary investor-return view** where a
   Partnership exists.
3. **The acquisition-loan levered IRR and multiple may remain visible only as
   a clearly labeled reference view,** for example "Acquisition financing —
   excludes later capital events". They are never presented as the current,
   refinance-adjusted headline return.
4. **Acquisition-only levered figures never silently drive** an Investment
   Committee recommendation, a memo headline, a report headline or an export
   headline when the accepted decision case includes an executed refinance.
5. **Any report or matrix that shows both namespaces names the distinction
   explicitly**, beside the figures.
6. **When a configured refinance is not executed** (unavailable,
   not-executable or blocked), the primary view shows that state and its
   reason. The acquisition-only figures never stand in for it.
7. **No arithmetic moves into the UI or reporting layer.** Every figure,
   including every difference between the two views, comes from the backend.
8. **Without a configured refinance, presentation is byte-identical to
   today** (Section 19).

---

## 13. Strategy and Scenario behavior

### 13.1 Strategy ownership

- **Domain.** Refinance events belong to the `CAPITAL_STRUCTURE` Strategy
  domain, inside the same `CapitalStructure` as the positions. There is no new
  Strategy domain.
- **Replacement terms.** Replacement-loan terms are Capital Structure Strategy
  terms in V1.
- **Whole-domain replacement** (ST-2, P7.8B §5):
  - a Strategy that states its own structure brings its own events, or none;
  - a Strategy that inherits the Base structure inherits the Base events;
  - an event is never merged, patched or added on its own.
- **Removing an overlay** restores the Base structure and its events exactly
  (P-6).
- **Other overlays** reach the refinance only through the resolved project
  inputs:
  - a different acquisition loan changes the legacy payoff;
  - a shorter hold can put `m` at or after `12H`
    (`event_outside_hold_horizon`);
  - an unselected Unit follows the existing rule for positions scoped to that
    Unit.

### 13.2 Scenario propagation

A Scenario changes refinance outcomes only by changing accepted upstream
analysis. V1 has no refinance-specific Scenario target.

| Scenario effect | Reaches the refinance through |
| --- | --- |
| NOI targets (`current_noi`, `noi_growth`, and the Detailed and Lease-Level revenue, expense and leasing targets) | `NOI_f`, and so `C_DSCR`; separately, the value of a `DIRECT_CAP` cell, and so `C_LTV` |
| `interest_rate`, `ltv CAP_AT` on the acquisition loan | the legacy loan's payoff at `m`, or its absence (`retiring_position_absent`) |
| `project_capital_*` | operating residuals, not sizing |
| `exit_cap_rate` | the exit and sale payoff only; the P7.10 direct-cap rate is the valuation definition's own |

An `ANALYST_VALUE` cell is constant across Scenarios (P7.10 §5.4), so its
`C_LTV` does not move. `C_DSCR` still moves with the variant's forward NOI, so
the binding constraint can switch between variants (F19).

### 13.3 Deferred: refinance-specific Scenario overrides

The registry's `interest_rate` target is the **acquisition loan's** rate.
Authored capital positions are outside every Scenario, because the Project
pathway never sees Capital Structure (P7.8B §5). A Scenario stating "rates are
150 bp higher" therefore moves the legacy loan, not the replacement.

- V1 models alternative refinance terms as separate Capital Structure
  Strategies.
- Refinance-specific Scenario overrides are deferred (Section 21.2).
- Stage 3 discloses the limitation wherever a Scenario changes
  `interest_rate` and a refinance exists: the replacement loan's rate is a
  Strategy term.

### 13.4 No-refinance parity

A structure with no event resolves, executes, fingerprints, persists and
serializes byte-identically to the accepted baseline (Section 19).

---

## 14. Fingerprints and staleness

### 14.1 Layering

The P7.8B layering is kept. The event joins the existing structured identity,
and no new fingerprint level is added.

```text
PROJECT source fingerprint        unchanged; never sees events (P-4); already carries
        |                         every input that determines forward NOI
STRUCTURED source fingerprint  =  f(project fingerprint,
                                    resolved structure  [positions, and now events],
                                    consumed valuations [PctOfValue, and now the value
                                                         dependency of LTV-enabled
                                                         refinances only; P7.10 §22.2])
```

- **FP-2.** The events payload joins only when non-empty. A structure with no
  event hashes exactly what it hashes today, byte for byte.
- **Only LTV consumes a valuation.** The value dependency of an LTV-enabled
  event joins the structured identity through the payload mechanism P7.10
  §22.2 uses for `PctOfValue`: resolved value, method, `analyst_supplied`,
  status and definition fingerprint for the event scope.
  `structured_variant_fingerprint` must therefore resolve the Project variant
  for such an event, as it already must for `PctOfValue`.
- **DSCR adds no valuation payload.** Its NOI dependency is already inside the
  Project source fingerprint, because every input that determines forward NOI
  is a resolved Project input. Its `min_dscr` target is in the event payload.
  A DSCR-only, fixed-only or fixed-plus-DSCR event therefore adds no valuation
  payload and depends on no valuation definition, result or evidence.

### 14.2 What enters the event's economic payload

In canonical form:

| Enters | Excluded |
| --- | --- |
| `event_id`, `kind`, `scope`, `model_month`, `sequence` | `label` |
| retiring references, sorted by (kind, id) | the order in which retiring positions were listed |
| `replacement_position_id` (its `DebtTerms`, fees, priority and resolution already enter through the position) | the replacement's `name` |
| each present constraint's kind and target, in canonical kind order; absent constraints add nothing | display order |
| for an LTV-enabled event only: `valuation.timepoint_id` plus the consumed-valuation payload | the valuation's label; any valuation for a non-LTV event, which cannot be referenced at all |
| each cost line's `cost_id`, `kind`, `amount` and `recipient`, sorted by `cost_id` | `description` |
| the `RefinanceProceeds` rule on the replacement funding | database ids, timestamps, row order |

### 14.3 Invalidation boundaries

| Change | Structured result; Position and Partner matrices | Project result and Project matrix | Memo freshness |
| --- | --- | --- | --- |
| event timing, constraints, costs, retirements, replacement terms | stale | current | `CAPITAL_STRUCTURE` stale |
| the referenced valuation definition of an **LTV-enabled** event (cap rate, analyst value, month, instruction, evidence) | stale | current | `VALUATION_DEFINITIONS` / `VALUATION_RESULTS` and `CAPITAL_STRUCTURE` stale |
| any valuation definition, for a **DSCR-only, fixed-only or fixed-plus-DSCR** event | **current** | current | valuation freshness only if the memo itself selected that view (P7.10 §22.6); never `CAPITAL_STRUCTURE` |
| upstream NOI, loan terms or hold (base edit, Strategy, Scenario) | stale | stale (as today) | as today |
| retiring position terms (which change its balance at `m`) | stale | current | `CAPITAL_STRUCTURE` stale |
| Partnership terms | Partner results only | current | as today |
| event label, cost description, position name, valuation label | **current** | current | presentation only |

- **Caches.** A cached result is served only while its fingerprint matches
  (Q14). A stale result is never shown as current. It is recomputed from its
  dependencies, never repaired.
- **Published memos.** A published memo version and its frozen report keep
  what the committee received (P7.10 §23.2). Current freshness names the
  changed dependency outside the frozen artifact.
- **Consumed dependency for memo publication (R-R).** Only for an
  **LTV-enabled** refinance of the selected Capital Structure, the referenced
  valuation is a **consumed** dependency for memo publication, exactly like a
  `PctOfValue` consumption.
  - This extends P7.10 §22.6. The P7.10 document itself is not edited, and
    this record is the authority for the extension.
  - A DSCR-only or fixed-only refinance creates no valuation publication
    dependency.

### 14.4 Determinism

- The same resolved inputs give bit-identical results and fingerprints on
  every run.
- Permuting positions, events, retiring references or cost lines changes
  nothing (P-7).
- An exact semantic revert restores the prior fingerprint.

---

## 15. Typed unavailable and refusal states

There are two families (R-Q). They follow P7.10's split between authoring and
economic faults, and P7.8's split between structural and execution
validation.

- **Refusals** are authoring faults wholly inside the Capital Structure.
  - They are refused at save and at execution with a typed issue, and produce
    no result.
  - Engine-defect guards also refuse.
- **Unavailable states** depend on facts outside the structure: a valuation,
  NOI, the hold period, loan terms or unit selection. Those facts can change
  without the structure changing, so:
  - the analysis succeeds;
  - the event reports why it cannot execute;
  - downstream capital-event results are typed N/A.

This differs deliberately from the P7.10 Stage 1 precedent, where an
unresolved `PctOfValue` raises `CapitalStructureExecutionError` (P7.10 §22.4).
That precedent is unchanged for `PctOfValue`.

### 15.1 Refusals (structural and execution validation, and engine defects)

| Code | Refused |
| --- | --- |
| `unsupported_capital_event_kind` | any kind but `refinance` |
| `event_month_not_hold_year_end` | `m <= 0`, or `m` not a multiple of 12 |
| `unsupported_event_sequence` | `sequence != 1` |
| `duplicate_capital_event_id` | an id already used in the capital-event namespace |
| `multiple_refinances_in_scope` | a second event in the same exact scope |
| `capital_event_kind_conflict` / `capital_event_scope_conflict` | P-8 across the Investment's structures |
| `no_retiring_position` | empty `retiring` |
| `retiring_position_not_found` | an authored reference to no position |
| `retiring_position_duplicated` | the same reference twice |
| `retiring_position_scope_mismatch` | a retiring position outside the event scope |
| `retiring_position_not_debt` | preferred equity, common equity, or the replacement itself |
| `replacement_position_not_found` / `replacement_position_not_debt` | as named |
| `replacement_scope_mismatch` | the replacement's scope differs from the event scope |
| `replacement_funding_mismatch` | the replacement lacks exactly one funding event at `m` with `RefinanceProceeds(event_id)` |
| `orphaned_refinance_proceeds` | a `RefinanceProceeds` rule naming no event, or an event other than the one naming that position |
| `replacement_priority_not_successor` | Section 10.3 |
| `replacement_maturity_too_early` | `maturity_month < m + 12` |
| `replacement_fee_timing` | a replacement fee at a month other than `m` |
| `no_sizing_constraint` | no constraint present |
| `invalid_fixed_cap` / `invalid_max_ltv` / `invalid_min_dscr` | outside the Section 6.4 domains |
| `valuation_reference_required` | `max_ltv` present without a valuation reference |
| `valuation_reference_unused` | a valuation reference without `max_ltv` (DSCR-only, fixed-only or fixed-plus-DSCR) |
| `dscr_zero_first_year_service` | Section 9.3 |
| `invalid_retiring_lender_fee_recipient` | a recipient that is not one of this event's retiring positions |
| `invalid_cost_line` | a negative or non-finite amount, a non-fixed-dollar rule, or a third-party cost carrying a recipient |
| `investment_refinance_with_unit_debt` | Section 12.4 |
| `unsupported_event_scope` | an `INVESTMENT` event in a standalone Unit analysis (the P7.8 §4 precedent) |
| `legacy_payoff_reconciliation_failure` | engine defect: the acquisition-debt balance service failed reconciliation (Section 10.2). Never tolerated |
| `forward_noi_authority_mismatch` | engine defect: a direct-cap cell's forward NOI, or the Investment NOI sum, disagrees with the shared NOI authority (Section 8.3). Never tolerated |
| `legacy_authority_splice_mismatch` | engine defect: the levered/unlevered identity behind INV-16 does not hold. Never tolerated |

A refused structure is never partially executed, and no event is ignored.

### 15.2 Unavailable states (`RefinanceUnavailableReason`)

| Reason | Applies to | Status | Meaning |
| --- | --- | --- | --- |
| `event_outside_hold_horizon` | the event | `UNAVAILABLE` | `m >= 12H` for this variant (for example, a Strategy shortened the hold). The same event may execute under a longer hold |
| `timepoint_not_found` | `MAX_LTV` | `UNAVAILABLE` | the referenced timepoint does not exist in the Investment |
| `model_month_mismatch` | `MAX_LTV` | `UNAVAILABLE` | the timepoint's month differs from `m`. Neither is moved to match the other |
| `scope_not_covered` | `MAX_LTV` | `UNAVAILABLE` | the valuation has no cell for the exact event scope |
| `valuation_unavailable` | `MAX_LTV` | `UNAVAILABLE` | the cell is `UNAVAILABLE`, carrying P7.10's own reason (`incomplete_units`, `non_positive_forward_noi`, `unit_not_valued`, `outside_hold_horizon`, …) |
| `evidence_not_approved` | `MAX_LTV` | `UNAVAILABLE` | Stage 2: an analyst-supplied value with unapproved evidence (P7.10 §22.3). The typed amount is never shown |
| `forward_noi_unavailable` | `MIN_DSCR` | `UNAVAILABLE` | the shared NOI authority yields no forward NOI for the scope and month |
| `non_positive_forward_noi` | `MIN_DSCR` | `UNAVAILABLE` | `NOI_f <= 0` |
| `retiring_position_absent` | the event | `UNAVAILABLE` | a referenced legacy loan does not exist in this variant (for example, `ltv` capped at 0) |
| `retiring_position_not_outstanding` | the event | `UNAVAILABLE` | a retiring position's balance after its month-`m` payment is 0 in this variant |
| `non_positive_capacity` | the event | `NOT_EXECUTABLE` | Section 9.5 |
| `upstream_unresolved_funding` | the event | `BLOCKED` | P7.8 §10: an unresolved requirement at or before `y` in the scope, or a senior unresolved position |

`STALE_DEPENDENCY` is a persistence state (Stage 2), not an engine reason. The
engine always resolves its dependencies fresh, so it never consumes a stale
value.

### 15.3 Messages

Every reason pairs a stable machine code with an analyst-facing message. The
message names:

- the event by its label;
- the scope by its Unit or Investment name;
- the valuation by its label;
- positions by their names.

**No opaque id appears in an analyst-facing message** (P7.10 §23.11). Machine
codes and ids travel in separate typed fields.

### 15.4 Downstream effect of a non-executed event

When the event is `UNAVAILABLE`, `NOT_EXECUTABLE` or `BLOCKED`:

- **Upstream stays available.** Project, Business Plan, consolidated and
  valuation results are unaffected.
- **Positions that stay valid:**
  - positions senior to the replacement in the event scope;
  - positions of other Unit scopes.
- **Positions reported N/A with the event's reason** (what they would receive
  after `m` is unknowable):
  - the retiring positions and the replacement;
  - every position ranked at or below the replacement's priority in the
    scope;
  - for a Unit event, every Investment-scoped position.
- **Structural metrics** that do not depend on the event stay reported (P7.8
  §14.4).
- **Common Equity:** `cash_flows = None`.
  - The reason is `refinance_unavailable`, with the event named.
  - An event that is `UNAVAILABLE` or `NOT_EXECUTABLE` dominates any
    simultaneous unresolved Funding Requirement: Common Equity is then
    `refinance_unavailable`, because resolving the funding alone would not make
    it reportable (clarified at Section 23.4).
  - `BLOCKED` keeps P7.7's `unresolved_funding_requirement`, the root cause,
    only when no event is `UNAVAILABLE` or `NOT_EXECUTABLE`.
- **Messages:** P7.7 and P7.8 keep their accepted internals and messages. A
  refinance result restates every analyst-facing message it carries under
  Section 15.3 (clarified at Section 23.4).
- **Partnership:** `UNAVAILABLE`, with the upstream reason (Section 12.3).
- **Presentation:** the state is shown in the primary view (Section 12.5).
- **Nothing is zero-filled,** and nothing falls back to "no refinance".

---

## 16. Persistence, API and UI implications

These are obligations for later stages, stated so the contract is complete.
None is implemented here.

### 16.1 Persistence (Stage 2)

- **Ownership.** Events are children of the existing `capital_structures`
  owner marker, so Base and each Strategy's own structure keep independent
  event sets (P7.8B §3, §4).
- **Additive only**, following P7.8B's relational, typed, no-JSON-blob rule:
  new tables for events, retiring references, constraints, the LTV valuation
  reference and cost lines.
- **The `RefinanceProceeds` link.** The funding rule needs a way to name its
  event. If that cannot be done without `ALTER`ing `capital_funding_events`,
  Stage 2 stops and reports (Protocol §19, stop condition 2).
- **Fail closed** on:
  - unknown tokens;
  - orphans;
  - a refused structure;
  - a reserve-like field;
  - a valuation reference stored for an event without LTV.
- **Legacy references** are stored as `(kind = legacy_acquisition_loan,
  unit_id)`, never as the reserved string.
- **Old databases.** A database without events reads exactly as today, and
  every existing response is identical (Section 19).

### 16.2 API (Stage 2)

- **Authoring payloads.** The existing Capital Structure payloads gain an
  additive `capital_events` array. An absent array is the empty set and
  serializes as today.
- **Results.** The structured-variant response gains the `capital_events`
  results, with their separate value and NOI dependencies, and the Common
  Equity decomposition. Both are omitted when empty.
- **Unavailable and refusal states** use the established structured
  unavailable / N/A representation, with the reason code (P7.10 §6.2). They
  are never a generic server error, a fabricated amount or zero.
- **Primary-view facts.** Every response that carries return figures for a
  refinance-bearing variant also carries a typed indicator of which namespace
  is primary (Section 12.5). The frontend then decides nothing economically.
- **Optional readiness view.** A read-only "refinance readiness" view, the
  analogue of P7.10's `funding_states`, may report each event's capacities
  and reasons without a full analysis. Stage 2 decides whether to include it.

### 16.3 UI, reporting and export (Stage 3)

**Editing and results**

- **Event editor** in the Capital Structure workspace:
  - timing, shown as "End of Year y";
  - retiring debt;
  - the replacement loan (an ordinary position form);
  - constraints, with the valuation selector offered only while LTV is
    enabled;
  - cost lines.
- **Sizing panel.** Each capacity, with its operands and dependency:
  - LTV shows its value and valuation label;
  - DSCR shows its forward NOI, forward year and the V1 first-year-service
    basis disclosure.

  The panel also shows the executed gross, the binding constraint(s) and ties,
  and unavailable constraints with their reasons.
- **Event bridge.** `G`, payoffs, lender fees, third-party costs and `N`, with
  the distribution, contribution or zero direction.
- **Annual presentation.** The event's Year-`y` line is shown separately from
  recurring Common Equity cash.

**Primary return view (Section 12.5)**

- Common Equity after Capital Structure is the primary equity-return view,
  and Partner returns the primary investor view.
- The acquisition-financing figures appear only as a labeled reference, for
  example "Acquisition financing — excludes later capital events".
- Common Equity returns are reachable with no authored Common Equity marker.

**Decision Matrix**

- The `POSITION` and `PARTNER` perspectives reflect the event.
- Wherever the `PROJECT` perspective appears beside a refinance-bearing
  variant, its figures are labeled as the acquisition-financing reference and
  never headlined as the refinance-adjusted return.

**Memo and report**

- A refinance section appears on new publications only; published artifacts
  stay frozen.
- When the accepted decision case includes an executed refinance:
  - the recommendation, memo headline and report headline use Common Equity or
    Partner returns;
  - acquisition-only levered figures appear only as the labeled reference.

**Excel formula-audit export**

- **Exports 1–3** explicitly exclude Capital Structure.
  - Without a refinance, their output stays byte-identical.
  - Where the Deal's Base Capital Structure includes an executed refinance,
    their levered figures must be labeled as the acquisition-financing
    reference view. They must never be the export's headline equity return.
- **A new refinance formula-audit export** (a workbook, or sheets within a
  Capital Structure audit), separately ratified in Stage 3. It reproduces in
  live formulas, and reconciles against Anchor's figures:
  - the retiring loan's monthly amortization to `m`, using the same accepted
    recurrence the engine service uses;
  - each capacity, the minimum and the binding test;
  - the bridge;
  - the replacement schedule to the sale;
  - the Common Equity series.

  Its headline equity return is the Common Equity or Partner return.

**Everywhere**

- **No internal id** on any analyst surface.
- **No arithmetic** in the frontend or the reporting layer (existing
  no-arithmetic guards).
- **Browser QA** at 1440, 1280 and 390 px.
- **AI Analyst** may interpret supplied refinance results, and never computes
  one (AGENTS.md).

---

## 17. Invariants and conservation laws

Tolerances follow Section 9.7. Stage 1 or Stage 2 must provide a test family
for each invariant.

| # | Invariant | Statement |
| --- | --- | --- |
| INV-1 | Scope isolation | An event reads only its own scope's value (LTV), forward NOI (DSCR), debt balances and service. Its payoffs, fees and `N` apply only to its own scope's residual. Changing another scope's value, NOI or debt changes nothing in the event, except through the root's ordinary Common Equity sum |
| INV-2 | Event cash conservation | `G = P + F_R + F_X + T + N`; at `m`, the replacement, retiring, third-party and Common Equity flows sum to zero (Section 11.2) |
| INV-3 | Old-debt retirement | Each retiring position's balance after `REFINANCE_PAYOFF` is exactly `0.0`, and it has no event after `m` |
| INV-4 | Replacement commencement | The replacement's first scheduled payment is at `m + 1`, it has no service at or before `m`, and its principal immediately after funding is `G` |
| INV-5 | Provider cash-flow conservation | For a Unit scope and every `t`: `U_t = CECF_t + sum_p provider_p,t + T x [t = y]`. `U_t` is the Unit's pre-all-debt authority (`unlevered_cash_flows`). `provider_p,t` is each debt position's provider-sign annual flow (funding negative; service, payoffs and fees positive), the legacy loan included. Resolved equity contributions keep the identity. The Investment scope uses its corresponding pre-debt authority |
| INV-6 | Common Equity bridge | `CECF_t = recurring_t + event_t`, with `event_y = N` and `event_t = 0` elsewhere. Profit bridge against the no-refinance run: `sum_t delta_CECF_t = -(sum_t sum_p delta_provider_p,t) - T` (F5) |
| INV-7 | Sale payoff | At `12H`, the replacement's claim includes its balance before payoff (P7.8 §6). A retired position contributes nothing at `12H`, and a retired legacy loan's `remaining_loan_balance` is never subtracted |
| INV-8 | Partnership period conservation | P7.9 §14 identities 1–17 hold for every `t`, including `t = y` |
| INV-9 | No service overlap | Section 10.4 |
| INV-10 | No-refinance parity | Section 19 |
| INV-11 | Deterministic reruns | Section 14.4 |
| INV-12 | Unavailable is not zero | No unavailable capacity, `G`, payoff, `N`, Common Equity or Partner figure is ever `0.0`. `N = 0` appears only when computed |
| INV-13 | No silent fallback | Nothing substitutes for a missing input: not purchase price, another timepoint, another scope, a partial Investment sum, the value for NOI, the NOI for value, a skipped event, or the old loan kept in place. Guarded by mutation tests |
| INV-14 | One event per scope | Section 15.1 |
| INV-15 | Upstream immutability | `AcquisitionResults`, `AcquisitionTerms`, `ConsolidatedResults`, valuation results and every Project fingerprint are bit-identical with and without an event |
| INV-16 | Legacy splice | Stated below |
| INV-17 | Sizing monotonicity | Raising any capacity's input (value, NOI, `max_ltv`, fixed cap), or lowering `min_dscr`, never lowers `G`, and raises `G` exactly when that constraint binds |
| INV-18 | Dependency separation | A DSCR-only, fixed-only or fixed-plus-DSCR event's results and structured fingerprint are invariant under any change to any valuation definition, valuation result or evidence approval. An LTV-enabled event's `C_DSCR` is invariant under a change to its referenced valuation that leaves the variant's forward NOI unchanged |
| INV-19 | One payoff authority | Every legacy payoff comes from the engine's acquisition-debt balance service, and every authored payoff from that position's accepted schedule. No amortization recurrence exists in Capital Structure, the export layer or the UI |

**INV-16, the legacy splice.** When a Unit's legacy loan is retired at `y`, the
Unit's pre-new-structure cash authority becomes:

```text
A_t = levered_cash_flows[t]       for t = 0 .. y     (legacy service through y, subtracted once)
A_t = unlevered_cash_flows[t]     for t = y+1 .. H   (no legacy service, no legacy exit payoff)
```

- The splice composes only accepted authority series. Nothing is added back,
  so the legacy debt is subtracted exactly once (the P7.7 handoff invariant).
- **Precondition, checked on every execution.** For every `t` in `1..H`:
  `levered[t] = unlevered[t] - annual_debt_service[t-1] - remaining_loan_balance x [t = H]`,
  within tolerance.
- **If the identity fails** for any mode, the analysis is refused with
  `legacy_authority_splice_mismatch`, and Stage 1 stops and reports.
- **Then:**
  - the payoff at `m` comes from the acquisition-debt balance service and is
    applied by the bridge;
  - the replacement's claims are settled against `A_t` for `t > y`, in
    priority order.

---

## 18. Canonical acceptance fixtures

### 18.1 The base case

Every fixture uses this base case unless it says otherwise. The figures are
**resolved facts** the fixture must produce. Stage 1 chooses concrete Quick
inputs that yield them and records those inputs. Expected values are exact
rationals derived here, and no external oracle is involved.

**The Unit and its NOI**

- One Unit `U`, standalone (hidden one-unit Investment), with hold `H = 5`.
- Resolved `noi_by_year = (800,000; 800,000; 800,000; 800,000; 800,000)`, so
  the shared NOI authority gives `NOI_f = 800,000` at `m = 24`.

**The legacy acquisition loan**

- Principal `6,000,000`, interest rate `0%`, amortization 25 years
  (`n = 300`), no IO, no financing fee.
- Monthly payment `20,000`; annual service `240,000`.
- Balance after month 24, from the engine service: `5,520,000`.
- Balance at `12H = 60`: `4,800,000`.

**The refinance event `R`**

- Scope `UNIT(U)`, `m = 24` (`y = 2`), retiring the legacy loan.
- Valuation (referenced only by LTV-enabled fixtures): a CUSTOM timepoint at
  month 24, `DIRECT_CAP(6.4%)`, so `V = 800,000 / 0.064 = 12,500,000`. Its
  recorded forward NOI reconciles to `NOI_f`.

**The replacement position**

- `SENIOR_DEBT`, priority 1 by succession, interest rate `5%`,
  `io_period = 5`, `amortization = 30`, `maturity_month = 144`, resolution
  `COMMON_EQUITY_CONTRIBUTION`.
- It is interest-only through the sale:
  - `s_1 = 0.05`;
  - annual service `0.05 G`;
  - balance at 60 equals `G`.

**Costs:** none, unless stated.

The zero-rate legacy loan and IO replacement make every event figure an exact
rational. F9b adds positive-rate and IO legacy cases.

### 18.2 Fixtures

Each fixture states its configuration, its expected authoritative outputs, and
the property it proves.

**F1 — Fixed cap binding.**
- Configuration: fixed `7,500,000`, LTV `65%` (valuation referenced), DSCR
  `2.00x`.
- Capacities: FIXED `7,500,000`; LTV `8,125,000`; DSCR
  `(800,000 / 2) / 0.05 = 8,000,000`.
- Result: `G = 7,500,000`, binding `[FIXED_CAP]`, no tie; `N = 1,980,000`.
- Proves: minimum selection; a cap is a limit.

**F2 — LTV binding.**
- Configuration: LTV `60%` (valuation referenced), DSCR `1.60x`, no fixed cap.
- Capacities: LTV `7,500,000`; DSCR `500,000 / 0.05 = 10,000,000`.
- Result: `G = 7,500,000`, binding `[MAX_LTV]`; `N = 1,980,000`.
- Proves: `C_LTV = max_ltv x V` with `B_sen = 0` under succession.

**F3 — DSCR binding.**
- Configuration: LTV `70%` (`8,750,000`; valuation referenced), DSCR `2.00x`
  (`8,000,000`).
- Result: `G = 8,000,000`, binding `[MIN_DSCR]`; `N = 2,480,000`;
  `achieved_dscr = 800,000 / 400,000 = 2.00`.
- Proves: service capacity is converted to principal through the reused
  schedule; proportionality; the achieved DSCR equals the target.

**F3b — DSCR-only, no valuation.**
- Configuration: DSCR `2.00x` only, **no valuation reference**, and **no
  valuation timepoint anywhere in the Investment**.
- Result: `G = 8,000,000`, binding `[MIN_DSCR]`; `N = 2,480,000`;
  `value_dependency = None`; `noi_dependency.forward_noi = 800,000` from the
  shared NOI authority; `achieved_ltv = None`.
- Adding a valuation reference to this event is refused
  (`valuation_reference_unused`).
- Proves: Correction 1; DSCR needs no valuation.

**F4 — Tie.**
- Configuration: fixed `8,000,000`, LTV `64%` (`8,000,000`), DSCR `2.00x`
  (`8,000,000`).
- Result: `G = 8,000,000`, binding `[FIXED_CAP, MAX_LTV, MIN_DSCR]`,
  `tie = true`.
- Proves: every tied constraint is reported; the float residue of `s_1` does
  not break the tie (Section 9.6).

**F5 — Positive net proceeds.**
- Configuration: as F3, plus a replacement lender fee of `80,000` and a
  third-party cost of `40,000`.
- Bridge: `8,000,000 - 5,520,000 - 80,000 - 40,000 = N = +2,360,000`,
  direction `DISTRIBUTION`.
- Common Equity delta against no refinance:

  | `t` | 0 | 1 | 2 | 3 | 4 | 5 |
  | --- | --- | --- | --- | --- | --- | --- |
  | `delta_CECF_t` | 0 | 0 | +2,360,000 | -160,000 | -160,000 | -3,360,000 |

  - Years 3 and 4: `+240,000` of legacy service removed, `-400,000` of
    replacement service added.
  - Year 5 also swaps the `+4,800,000` legacy payoff for the `-8,000,000`
    replacement payoff.
- Profit bridge:
  - legacy provider delta: `+5,520,000 - 720,000 - 4,800,000 = 0` (a 0% loan
    pays only principal);
  - replacement provider delta:
    `-8,000,000 + 80,000 + 1,200,000 + 8,000,000 = +1,280,000`;
  - third-party costs: `40,000`;
  - so `sum delta = -(0 + 1,280,000) - 40,000 = -1,320,000` (INV-6).
- Proves: INV-2, INV-6; the distribution sign; the recurring series excludes
  `N`.

**F6 — Negative net cash.**
- Configuration: as F5, with a binding fixed cap of `5,000,000`.
- Result: `N = 5,000,000 - 5,520,000 - 120,000 = -640,000`, direction
  `CONTRIBUTION`.
- No Funding Requirement is created, and `CECF_2` falls by `640,000`.
- Proves: an explicit Common Equity contribution, not an FR; proceeds do not
  cure operating claims.

**F7 — Exact zero.**
- Configuration: as F5, with a binding fixed cap of `5,640,000`.
- Result: `N = 0.0`, direction `ZERO`, status `EXECUTED`; `delta_CECF_2 = 0`.
- Proves: a computed zero is not unavailable (INV-12).

**F8 — Legacy retirement through the engine balance service.**
- Configuration: as F3.
- Payoff: `5,520,000`, with `payoff_authority = ACQUISITION_DEBT_BALANCE_SERVICE`.
- Legacy provider series: `t0 -6,000,000`; `t1 +240,000`;
  `t2 +240,000 + 5,520,000`; `t3..t5` zero. Legacy IRR is `0%`.
- `AcquisitionResults` and `AcquisitionTerms` are bit-identical to the
  no-refinance run. The adapter imports no debt function. Every service
  reconciliation holds bit for bit. The INV-16 splice holds, and no legacy
  claim exists after year 2.
- Proves: R-M, INV-15, INV-16, INV-19.

**F9 — Replacement through sale.**
- Configuration: as F3.
- Replacement provider series: `t2 -8,000,000`; `t3 +400,000`; `t4 +400,000`;
  `t5 +400,000 + 8,000,000`.
- IRR exactly `5%`; MOIC `9,200,000 / 8,000,000 = 1.15`.
- First service month 25; `modeled_payoff_month = 60`; no service overlap.
- Proves: INV-4, INV-7, INV-9; ordinary position returns.

**F9b — Legacy payoff seam across debt branches.**
- Cases, each as F3 except the legacy loan:
  - (a) `6%` over 25 years, amortizing;
  - (b) `6%` with a 3-year IO period, retiring at `m = 24` (inside IO: payoff
    equals principal);
  - (c) `6%` with a 2-year IO period, retiring at `m = 24` (exactly at the IO
    boundary);
  - (d) the base zero-rate case.
- Expected payoffs come from a test-only `Fraction` oracle of the frozen
  recurrence, and equal the service's figure within tolerance.
- The service reconciles `annual_debt_service[0..1]` and
  `remaining_loan_balance` bit for bit in every case.
- Mutation tests kill:
  - a recurrence reimplemented in Capital Structure;
  - a payoff taken before the month-`m` payment;
  - a payoff taken at month `m - 1`;
  - a reconciliation that tolerates a mismatch;
  - a service that mutates `AcquisitionResults`.
- Proves: R-M across the zero-rate, positive-rate, IO and IO-boundary
  branches.

**F10 — Fee attribution.**
- Configuration: as F5, plus a fixed retiring lender fee of `30,000` to the
  legacy loan.
- Result: `N = 2,330,000`. Replacement `t2 = -7,920,000`; legacy
  `t2 = +5,790,000`; third parties `40,000` (bridge only).
- INV-2 sums to zero.
- Proves: each fee reaches exactly its recipient; third-party costs reach no
  position.

**F11 — Missing contemporaneous value (LTV).**
- Configuration: LTV `65%` and DSCR `2.00x`, in two variants:
  - the timepoint id does not exist: `timepoint_not_found`;
  - (Stage 2) the value is analyst-supplied with unapproved evidence:
    `evidence_not_approved`. The typed amount is not reported.
- Result, in both: `C_LTV` unavailable; `C_DSCR = 8,000,000` still available
  from the shared NOI authority; `G = None`, status `UNAVAILABLE`; Common
  Equity and Partnership N/A with the reason; Project results unchanged.
- Mutation tests kill:
  - a purchase-price value fallback;
  - DSCR-only execution when LTV is unavailable.
- Proves: INV-12, INV-13.

**F12 — Missing forward NOI (DSCR).**
- Configuration: the variant's `noi_by_year[2] <= 0`, in two variants:
  - (a) LTV and DSCR, with an **analyst-supplied** value (`AVAILABLE`):
    `C_LTV` is available, while `C_DSCR` is unavailable
    (`non_positive_forward_noi`). The analyst value is not read as NOI.
  - (b) DSCR-only, with no valuation reference: `non_positive_forward_noi`.
- Result, in both: status `UNAVAILABLE`.
- Mutation tests kill:
  - NOI read from the valuation cell;
  - a floored NOI;
  - a dropped constraint.
- Proves: Section 8.3; INV-13.

**F13 — Stale referenced valuation, and non-staleness (Stage 2).**
- (a) LTV-enabled, with F1's configuration:
  1. Analyze and cache.
  2. Change the timepoint's cap rate to `8%`, so `V = 10,000,000`.
  3. The cached structured result's fingerprint no longer matches, and it is
     never served.
  4. Recomputation gives `C_LTV = 6,500,000`, which now binds:
     `G = 6,500,000` and `N = 980,000`.
  5. A memo published before the change keeps its frozen figures, and reports
     `VALUATION_RESULTS` and `CAPITAL_STRUCTURE` staleness.
- (b) DSCR-only (F3b) in the same Investment: the same cap-rate edit, a new
  valuation definition, and an evidence-approval change leave the structured
  fingerprint, the cached result and the memo's `CAPITAL_STRUCTURE` freshness
  unchanged (INV-18).
- A label rename changes no fingerprint.
- Proves: Section 14.

**F14 — Scope mismatch.**
- (a) An event in `UNIT(A)` retiring a position in `UNIT(B)`: refused,
  `retiring_position_scope_mismatch`.
- (b) A replacement scoped to `UNIT(B)`: refused,
  `replacement_scope_mismatch`.
- (c) An LTV valuation with no cell for `A`: `scope_not_covered`,
  `UNAVAILABLE`.
- (d) An LTV timepoint at month 36 for an event at 24: `model_month_mismatch`.
  It is never matched to the nearest timepoint.
- (e) DSCR reads `A`'s forward NOI only. Changing `B`'s NOI leaves `C_DSCR`
  unchanged.
- Proves: INV-1, INV-13.

**F15 — Multi-unit isolation.**
- Configuration: a visible Investment with Units `A` (the base case) and `B`
  (no event; different NOI and loan). `A` has an event.
- `B`'s positions, claims and structural metrics are bit-identical to the
  no-refinance run.
- Changing `B`'s NOI or valuation changes no figure of `A`'s event.
- The Investment residual gains `A`'s `N` once, in year 2.
- A second event for `A` is refused (`multiple_refinances_in_scope`).
- An `INVESTMENT` event while `A` carries a legacy loan is refused
  (`investment_refinance_with_unit_debt`).
- Proves: INV-1, INV-14.

**F15b — Investment-scope DSCR reconciliation.**
- Configuration: a two-Unit Investment with no Unit debt, and an
  `INVESTMENT`-scoped authored senior loan retired at `y = 2` with DSCR only.
- `NOI_f` equals the canonical sum of the Units' forward NOI, and reconciles
  bit for bit to `ConsolidatedResults.noi_by_year[2]`.
- A mutant that breaks the reconciliation is refused
  (`forward_noi_authority_mismatch`).
- Proves: Section 8.3 at Investment scope.

**F16 — Partnership conservation.**
- Configuration: F5's Common Equity series allocated by a P7.9 LP 90% / GP 10%
  partnership: `HURDLE` IRR 8% `ANNUAL_COMPOUND` with subject LP, then a 70/30
  `RESIDUAL`.
- Every P7.9 §14 identity holds for every `t`, including `t = 2`, and
  `sum_p distributions_p,2 = max(CECF_2, 0)` includes `N`.
- Contribution variant: F5's costs with a binding fixed cap of `4,000,000`, so
  `N = -1,640,000`.
  - That exceeds year 2's operating Common Equity cash (at most
    `800,000 - 240,000 = 560,000`), so `CECF_2 < 0` is guaranteed.
  - `sum_p contributions_p,2 = max(-CECF_2, 0)`, allocated by commitment
    share as capital calls.
  - The event contribution is netted with operating cash inside the annual
    period, never split out.
- Proves: INV-8; there is no refinance tier.

**F17 — Partner-return change caused by the event.**
- Configuration: F16 against the same partnership with no refinance.
- Partner IRRs, MOICs and Promote Earned differ.
- The difference in each period's total partner cash equals `delta_CECF_t`
  exactly.
- Promote attribution stays tier-attributable (PW-6).
- Proves: the event reaches partners only through the Common Equity seam.

**F18 — Strategy replacement.**
- Configuration: the Base structure has the legacy loan only, with no event.
  Strategy `S1` states its own structure with event `R`. Strategy `S2`
  inherits Base.
- `S2` is bit-identical to Base, including its fingerprint.
- Removing `S1`'s overlay restores Base exactly.
- The same `event_id` with a different scope in `S1` and a third Strategy is
  refused (`capital_event_scope_conflict`).
- An event cannot be added to an inherited structure as a patch.
- Proves: ST-2, P-6, P-8.

**F19 — Scenario-driven capacity.**
- Configuration: Scenario "Downside" scales current NOI by `0.90`, so
  `NOI_f = 720,000` and the direct-cap `V = 11,250,000`. The event is F4
  without the fixed cap.
- Downside:
  - `C_LTV = 0.64 x 11,250,000 = 7,200,000`;
  - `C_DSCR = 360,000 / 0.05 = 7,200,000`;
  - `G = 7,200,000`, tied;
  - `N = 1,680,000` with no costs.
- Analyst-supplied value variant (`12,500,000`), under Downside:
  - `C_LTV = 8,000,000` (unchanged);
  - `C_DSCR = 7,200,000`;
  - binding switches to `[MIN_DSCR]`.
- The legacy payoff is unchanged by NOI.
- Proves: Scenario propagation through accepted upstream analysis only; no
  refinance Scenario target.

**F20 — No-refinance byte parity.**
- Every representative existing response is identical against the
  git-archived `0e9f8cc` tree:
  - Quick, Detailed and Lease-Level analysis;
  - structured variants with and without authored positions;
  - Partnership;
  - the Project, Position and Partner matrices;
  - the Excel Exports 1–3 bytes;
  - memo reports;
  - every fingerprint.
- The acquisition-debt balance service is never called.
- A database from before the Stage 2 schema reads identically.
- Proves: INV-10, FP-2.

**F21 — Through-the-position junior refinance.**
- Configuration: a Unit with the legacy loan (continuing) and an authored
  mezzanine loan retired and replaced at `y = 2`.
- `B_sen` is the continuing legacy balance after month 24, from the engine
  balance service. `DS_sen = annual_debt_service[2]`.
- `C_LTV` and `C_DSCR` are net of them, and the replacement succeeds to the
  mezzanine priority.
- Proves: Sections 9.2 and 9.3; Section 10.3.

**F22 — Not executable, and the horizon.**
- (a) As F21, with LTV set so `max_ltv x V < B_sen`: `NOT_EXECUTABLE`;
  capacities reported; no replacement funded; Common Equity N/A; the old loan
  is not kept in place.
- (b) A Strategy `DISPOSITION` with hold `H = 2`, and the Base event at
  `m = 24`: `event_outside_hold_horizon`.
- Proves: Sections 9.5 and 15.2.

**F23 — Primary-view semantics (Stage 3).**
- Configuration: a refinance-bearing variant (F5) presented in the workspace,
  the Decision Matrix, a newly published memo and report, and an export.
- Common Equity (or Partner) returns are the headline. The acquisition
  levered IRR and multiple appear only under the acquisition-financing
  reference label.
- A mixed matrix names both namespaces. An unavailable refinance (F11) shows
  its state as primary, never the acquisition figures.
- No frontend or report arithmetic exists.
- Proves: Section 12.5.

### 18.3 Mutation proofs

Stages 1 and 2 provide one to five mutants per invariant (Protocol §9). At a
minimum they kill:

**Dependencies and fallbacks**

- a purchase-price value fallback;
- nearest-timepoint matching;
- DSCR reading NOI from a valuation cell or an analyst-supplied value;
- a DSCR-only event consuming or fingerprinting a valuation;
- dropping an unavailable constraint from the minimum;
- `max` in place of `min`.

**Payoff and timing**

- a payoff taken before the month-`m` payment;
- replacement service starting at `m`;
- legacy service kept after `y`;
- an amortization recurrence inside Capital Structure;
- a tolerated legacy-payoff reconciliation mismatch.

**Cash and presentation**

- `N` routed through the retiring position's claim;
- a zero-filled unavailable `N`;
- the event payload joining the fingerprint when empty;
- a label entering the fingerprint;
- an acquisition-only levered IRR selected as the headline for a
  refinance-bearing case.

---

## 19. Compatibility and no-refinance requirements

**Byte parity (F20).** With no event:

- every result, fingerprint, stored row, API response, matrix, memo report,
  PDF and workbook is identical to `0e9f8cc`;
- presentation headlines are unchanged, so the primary-view rules of
  Section 12.5 apply only where a refinance is configured.

**Frozen modules.** The following are expected to stay byte-identical, with
the refinance layer composing around them:

- `debt.py`, `acquisition.py`, `noi.py`, `returns.py` and
  `consolidation/engine.py`;
- the P7.7 modules, including the legacy adapter;
- the valuation engine;
- the P7.9 waterfall engine.

**Foreseen additions and touches** to accepted areas, each named here:

- the engine's new acquisition-debt balance service (R-M). It is a new
  function in the `anchor.engine` package, and adds no behavior to any
  existing debt function;
- the shared NOI-at-month seam, if Stage 1 extracts it from the valuation
  engine instead of calling it in place (Section 8.3);
- the additive contract members of Section 6.8;
- the P7.9 adapter's one accepted reason (R-O).

Stage 1 must enumerate every guard and production ledger these touch
**before coding**, and must re-pin to committed ranges rather than relax them.

**Accepted P7.8 refusals are narrowed, not removed:**

- `unsupported_funding_timing` still refuses every non-closing funding except
  a `RefinanceProceeds` funding at a valid event month;
- `unsupported_fee_timing` still refuses every non-closing fee except a
  replacement fee at `m`;
- `unsupported_amount_rule` is unchanged for everything else.

**P7.10 is unchanged:**

- `PctOfValue` stays closing-only (§6.1). A refinance does not use
  `PctOfValue`, and does not make later `PctOfValue` fundings executable.
- The P7.10 authority text is not edited. The LTV-only consumed-dependency
  extension (R-R) is ratified here.

**Schema.** Stage 2 adds one schema version, additively (Section 16.1). A
database from before that version gains empty tables and nothing else.

---

## 20. Staged implementation roadmap

Each stage starts only on an explicit human instruction. **Stage 1 was
explicitly started on 2026-09-22 from `2e1f84a`; it is implemented locally,
pending independent review, and not accepted** (Section 23). Stage 2 and Stage 3
have not started. **No stage begins automatically** when the previous one is
accepted. Recovery Engine V2 is not part of any stage.

| Stage | Scope | Tier | Exit evidence |
| --- | --- | --- | --- |
| Contract ratification — **complete, 2026-09-22** | This document. Documentation only | 1 (contract) | ratification record (Section 22); `CURRENT_STATE.md` updated |
| Stage 1 — deterministic engine (implemented locally 2026-09-22; pending independent review; not accepted) | Contracts (Section 6); structural and execution validation (Section 15.1); the shared NOI-at-month seam; the acquisition-debt balance service and its reconciliation; sizing (Section 9); the legacy splice; the retiring-schedule cut and replacement offset through the existing wrapper; the event bridge; the Common Equity decomposition; unavailable states; the P7.9 adapter reason; F1–F12, F14–F17, F15b, F19, F21, F22 with exact-rational oracles; F20 engine parity; the Section 18.3 mutation proofs. No persistence, API or UI | 1 | focused and identity tests; mutation kills; domain regression; one final full backend suite |
| Stage 2 — persistence and integration (not started) | An additive schema version; the codec; fingerprints (Section 14); Strategy whole-domain resolution with events; P-8 event identity; the LTV-only consumed-valuation publication dependency; typed API states and primary-view indicators; the optional readiness view; F13, F18, F20 persistence and API parity | 2 over a frozen Tier 1 engine; fingerprints at Tier 1 rigor | round-trip, legacy-reopen and migration oracles; fingerprint revert and order-neutrality; one final relevant suite |
| Stage 3 — product surfaces (not started) | The event editor; the sizing panel; the bridge; annual presentation; the primary-view and labeling rules (Section 12.5) across workspace, Decision Matrix, memo, report and export; the separately ratified refinance formula-audit export; browser QA (1440 / 1280 / 390); F23; human visual acceptance | 3, with the export at Tier 1 | component and interaction tests; no-arithmetic guards; export reconciliation; browser QA evidence; human acceptance |

**Stage 3 acceptance requires**, in addition to the above:

- Common Equity after Capital Structure as the primary current underwritten
  equity-return view whenever a refinance is executed;
- Partner returns as the primary investor view where a Partnership exists;
- acquisition-only levered figures shown only as the labeled
  acquisition-financing reference, never driving a recommendation, memo,
  report or export headline for a refinance-bearing decision case;
- explicit naming of both namespaces wherever both appear;
- Common Equity reachable without an authored marker;
- no UI or reporting arithmetic.

---

## 21. Implementation risks and deferred extensions

### 21.1 Implementation risks

These are execution risks for the stages. None reopens a ratified decision.

- **Namespace presentation.** R-P depends on every surface honoring it,
  including existing surfaces that today headline the Project levered IRR.
  Stage 3 must audit each one.
- **Float ties and proportionality.** These are covered by Section 9.3's proof
  obligation and Section 9.6's tolerance. If proportionality fails for any
  debt branch, Stage 1 stops.
- **Guard ripple.** New engine functions and contract members trip
  closed-gate guards. Enumerate them before coding, and re-pin rather than
  relax.
- **Legacy splice and payoff reconciliation.** Both depend on accepted
  identities holding in every mode, including Lease-Level and Business-Plan
  cases. Stage 1 must prove them across all modes before relying on them.
- **All-or-nothing unavailability.** One unavailable dependency blanks Common
  Equity and Partner returns for the root. Stage 3 must explain why in the
  analyst's terms.
- **Narrow amendments stay narrow.** The succession exception (R-N), the
  balance service (R-M) and the adapter reason (R-O) must not generalize
  beyond their stated scope.

### 21.2 Deferred extensions

Each needs its own contract and ratification:

- intra-year events, with their forward-NOI convention;
- multiple sequential refinances per scope;
- Investment-scope refinancing while Unit-scoped debt remains outstanding;
- supplemental and non-retiring debt;
- recapitalizations and preferred injections;
- reserves and holdbacks, with deposit, use and release schedules;
- debt-yield sizing, and DSCR on an amortizing-underwrite basis during IO;
- percentage-of-proceeds fees, and formula-based prepayment costs;
- floating rates, sculpted amortization, sweeps and traps;
- refinance-specific Scenario overrides, and Scenario targets for authored
  capital terms;
- a Common Equity cash-on-cash measure on `recurring_cash_flows`;
- monthly cash availability and monthly Partnership waterfalls;
- construction and draw facilities (Phase 8).

---

## 22. Ratification record

**Codex independent architecture review: approved 2026-09-22**, with
Corrections 1 and 2 incorporated. Every decision below is **ratified and
resolved**. None remains open.

### 22.1 Codex architecture direction

| ID | Decision | Section | Status |
| --- | --- | --- | --- |
| R-A | Year-end-only event timing: `m = 12y`, `1 <= y <= H - 1`; no event at closing, inside a year, or at or after the sale | 7.1 | Ratified 2026-09-22 |
| R-B | At most one refinance per exact `PositionScope`; a multi-unit Investment may have one per Unit | 5.1, 12.4, 15.1 | Ratified 2026-09-22 |
| R-C | Two separate dependencies, neither falling back to the other. **LTV:** the exact same-scope, same-month P7.10 valuation cell, with no fallback. **DSCR:** the exact same-scope, same-month authoritative forward NOI from the executing Analysis Variant, read through the shared NOI-at-month authority, with no fallback. A valuation reference is required iff LTV is enabled, and refused otherwise. A fixed-only event needs neither | 6.5, 8 | Ratified 2026-09-22 (Correction 1) |
| R-D | Gross proceeds are the minimum of the enabled fixed / LTV / DSCR capacities. Every enabled capacity must be available. Each capacity, the binding set and ties are exposed. Sizing is through the position, net of continuing senior debt in the same scope. DSCR is sized on the replacement's actual first twelve months of scheduled service, IO included (an amortizing-underwrite basis is a deferred lender-policy option). A non-positive limiting capacity is `NOT_EXECUTABLE`, and the old loan is never silently retained. No constraint means invalid | 9 | Ratified 2026-09-22 |
| R-E | At `m`: scheduled payment, then payoff of the remaining balance, then funding. Event cash falls in year `y`. New service starts at `m + 1` (month 25 after a Year-2 refinance). The replacement's balance is repaid from the sale | 7.2, 7.3 | Ratified 2026-09-22 |
| R-F | Payoff settles through the event bridge. Positive `N` is a Common Equity distribution; negative `N` is an explicit Common Equity contribution, not a Funding Requirement; zero is a computed zero. NOI, Project Capital, value, sale price and Owner Cash Flow above financing are unchanged, and the event is excluded from recurring metrics. Fees and costs are fixed-dollar only: replacement lender fees, retiring lender exit or prepayment fees, and third-party costs | 6.7, 11 | Ratified 2026-09-22 |
| R-G | Replacement debt is an ordinary authored `CapitalPosition` with `DebtTerms`, funded by the new `RefinanceProceeds` rule. Retiring positions stay identifiable and cease service after `m` | 6.6, 10 | Ratified 2026-09-22 |
| R-H | Reserves, holdbacks, releases and facilities are deferred; V1 accepts no such field | 11.5 | Ratified 2026-09-22 |
| R-I | Annual Partnership treatment through the unchanged seam and waterfall; no refinance tier; P7.9 conservation is mandatory | 12.3 | Ratified 2026-09-22 |
| R-J | Events belong to the `CAPITAL_STRUCTURE` Strategy domain with whole-domain replacement. Replacement-loan terms are Capital Structure Strategy terms. Scenarios act only through upstream analysis, and refinance-specific Scenario overrides are deferred | 13 | Ratified 2026-09-22 |
| R-K | The event payload joins the structured fingerprint only when present, and labels are excluded. Only an LTV-enabled event adds a consumed-valuation payload. The invalidation boundaries are those of Section 14.3 | 14 | Ratified 2026-09-22 |
| R-L | The V1 exclusions (Section 5.2) and staged delivery (Section 20). No stage starts automatically, and Recovery Engine V2 is excluded | 5.2, 20 | Ratified 2026-09-22 |

### 22.2 Decisions resolved at review

These resolve former questions Q-1 to Q-15. The corresponding text above is
written to each resolution.

| ID | Former question | Ratified resolution | Section |
| --- | --- | --- | --- |
| R-C (Q-1) | Source of DSCR forward NOI | The shared authoritative Analysis Variant NOI-at-month seam. A direct-cap cell's NOI must reconcile bit for bit, and a mismatch is an engine defect. An analyst-supplied valuation is never an NOI source | 8.3 |
| R-N (Q-2) | Replacement seniority | Priority succession: the replacement inherits the most senior retired position's priority. A duplicate priority is permitted only for that non-overlapping retiring / replacement pair | 10.3 |
| R-D (Q-3) | Sizing basis; Investment scope | Through-the-position LTV and DSCR, net of continuing senior debt in the same scope. Investment-scope refinancing is deferred while Unit-scoped debt remains outstanding | 9.2, 9.3, 12.4 |
| R-D (Q-4) | DSCR payment basis | The actual first twelve months of scheduled service, including IO. The amortizing-underwrite basis is a disclosed, deferred lender-policy option | 9.3 |
| R-D (Q-5) | Non-positive capacity | `NOT_EXECUTABLE`; the old loan is never silently retained | 9.5 |
| R-F (Q-6) | Payoff settlement | Through the event bridge. A negative `N` is an explicit Common Equity contribution, not a Funding Requirement | 11.3 |
| R-G (Q-7) | Replacement funding | `RefinanceProceeds` on an ordinary authored replacement `CapitalPosition` | 6.6 |
| R-O (Q-8) | P7.9 adapter | It propagates the exact new `refinance_unavailable` upstream reason. The waterfall mathematics are unchanged | 12.3 |
| R-F (Q-9) | Percentage fees | V1 supports fixed-dollar fees only; percentage-of-proceeds fees are deferred | 6.7 |
| R-P (Q-10) | Return namespaces in presentation | Common Equity returns are reachable without an authored marker, and the full primary-view and labeling rules of Section 12.5 apply | 12.5, 16.3, 20 |
| R-J (Q-11) | Refinance-rate Scenario stress | Replacement-loan terms are Capital Structure Strategy terms in V1; refinance-specific Scenario overrides are deferred | 13.3 |
| R-R (Q-12) | Memo publication dependency | Only an LTV-enabled refinance makes its referenced valuation a consumed dependency | 14.3 |
| R-Q (Q-13) | Failure family | External-dependency failures give a successful analysis with typed unavailable downstream capital-event results. Structural authoring faults remain refusals | 15 |
| R-F (Q-14) | Retiring-lender fees | Fixed-dollar exit or prepayment fees are permitted | 6.7 |
| R-M (Q-15) | Legacy payoff authority | The authoritative acquisition-debt balance service described in Section 10.2 | 10.2 |

New decision identifiers:

| ID | Decision | Section | Status |
| --- | --- | --- | --- |
| R-M | The legacy-payoff authority: an engine-owned acquisition-debt balance service; the P7.7 adapter unchanged; bit-for-bit reconciliation; typed engine-defect refusal; no second payoff formula anywhere | 10.2 | Ratified 2026-09-22 (Correction 2) |
| R-N | Priority succession (above) | 10.3 | Ratified 2026-09-22 |
| R-O | The P7.9 adapter propagates `refinance_unavailable` | 12.3 | Ratified 2026-09-22 |
| R-P | The primary return views and labeling | 12.5 | Ratified 2026-09-22 |
| R-Q | Refusal versus unavailable families | 15 | Ratified 2026-09-22 |
| R-R | LTV-only consumed-valuation dependency | 14.3 | Ratified 2026-09-22 |
| R-S | Unavailable-not-zero and no-refinance byte parity are permanent requirements of every stage (INV-10, INV-12, INV-13) | 15, 19 | Ratified 2026-09-22 |

### 22.3 Amendments to accepted authority

Each is ratified here, and is narrow. The amended documents are not edited;
this record is the authority for each amendment.

1. **P7.7 §5 (legacy adapter boundary), by R-M.** The adapter is unchanged and
   imports no debt function. Refinance execution may additionally call an
   engine-owned acquisition-debt balance service that reads the resolved
   `AcquisitionTerms` operationally and reconciles bit for bit to
   `AcquisitionResults`. Previously only descriptive use of `AcquisitionTerms`
   existed at this boundary.
2. **P7.7 §8 (priority uniqueness and reserved priority 1), by R-N.** A
   duplicate priority is permitted only for a retiring / replacement
   succession pair.
3. **P7.8 §8 (one annual claim holds every contractual receipt), by R-F.** A
   refinance payoff and retiring lender fees are event-settled, outside the
   retiring position's annual claim.
4. **P7.8 execution refusals,** narrowed as stated in Section 19.
5. **P7.9 §3 (adapter refusals), by R-O.** One more accepted upstream reason.
6. **P7.10 §22.6 (consumed dependencies), by R-R.** Extended to the value
   dependency of LTV-enabled refinances only.
7. **P7.10 §22.4 precedent,** not followed for refinance, by R-Q. The
   precedent itself is unchanged for `PctOfValue`.

Two points are clarifications rather than amendments:

- **Return namespaces.** Refinance-adjusted returns are Common Equity and
  Partner returns, never Project returns (P7 §14). R-P governs their
  presentation.
- **P7 §12.5's sketch.** It listed `PCT_OF_VALUE(timepoint)` sizing and
  "fees and reserves". This contract uses the LTV constraint (the same
  economics, stated as a cap on combined debt) and defers reserves (R-H).

### 22.4 Sign-off

| Role | Decision | Date |
| --- | --- | --- |
| Codex independent architecture review | Approved, with Corrections 1 and 2 incorporated | 2026-09-22 |
| Contract status | Ratified | 2026-09-22 |
| Stage 1 | Explicitly started 2026-09-22 from `2e1f84a`; implemented locally, pending independent review; not accepted (Section 23) | 2026-09-22 |

---

## 23. Stage 1 implementation record

**Status: implemented locally, pending independent review. Not accepted.**
Stage 1 was explicitly started on 2026-09-22 from `main` at `2e1f84a` on
`feature/refinance-capital-events-v1-stage-1-engine`. It implements Section
20's Stage 1 row and nothing else: no persistence, schema, codec, fingerprint,
API route or payload, frontend, memo, report or workbook. Stage 2 and Stage 3
have not started. Recovery Engine V2 is untouched.

### 23.1 What shipped

| Module | Responsibility |
| --- | --- |
| `engine/acquisition_debt_balance.py` (new) | R-M: the acquisition loan's balance immediately after the scheduled payment of month `m`, from the unchanged `debt.py` functions, reconciled bit for bit to `AcquisitionResults` on every call; `AcquisitionDebtBalanceReconciliationError` names the first figure that disagrees |
| `capital_structure/events.py` (new) | Shapes only: `CapitalEventKind`, `EventTiming`, the retiring references, the three constraints, `RefinanceSizing`, `RefinanceValuationRef`, the cost lines, `RefinanceEvent`, and `CapitalStructureWithEvents` |
| `capital_structure/event_validation.py` (new) | Every Section 15.1 authoring refusal wholly inside a structure, and the R-N succession pairs |
| `capital_structure/refinance_contracts.py` (new) | Shapes only: statuses and reasons, capacities and their operands, the value and NOI dependencies, payoffs, replacement funding, the bridge, `RefinanceResult`, `UnexecutedPosition`, and the two result subclasses |
| `capital_structure/refinance.py` (new) | The plan of one event for one variant: horizon, retirement through each payoff authority, continuing senior debt, the separate value (LTV) and forward-NOI (DSCR) dependencies, capacities, the minimum and binding set, the replacement schedule offset to the event month, and the bridge |
| `capital_structure/refinance_execution.py` (new) | Execution of an evented structure through P7.8's own admission, scheduling, settlement, returns and Common Equity functions: the INV-16 splice, settlement views without event cash, event cash after settlement, the Common Equity decomposition, and the Section 15.4 unavailability |
| `capital_structure/contracts.py` | Additive: `RefinanceProceeds` joins `FundingAmountRule`; appended refusal codes; `CapitalStructureStatus.REFINANCE_UNAVAILABLE`; `CommonEquityUnavailableReason.REFINANCE_UNAVAILABLE` |
| `capital_structure/validation.py` | Accepts `RefinanceProceeds`, applies the succession exception, and adds the event validation; a structure with no event and no `RefinanceProceeds` validates exactly as before |
| `capital_structure/execution_contracts.py` | Appended enum members only (`REFINANCE_PAYOFF`, `REFINANCE_FUNDING`, the execution refusals, the `REFINANCE_UNAVAILABLE` status and reason) and one widened annotation |
| `capital_structure/execution_validation.py` | The two narrowed refusals of Section 19 and the `unsupported_event_scope` refusal |
| `capital_structure/execution.py` | A dispatch prepended to each executor: a `CapitalStructureWithEvents` goes to the refinance executor; every other structure runs the accepted path statement for statement |
| `partnership/common_equity.py` | R-O: exactly one more accepted upstream reason, `refinance_unavailable`; the waterfall is untouched |

### 23.2 Implementation decisions a reviewer should check

1. **Additive by subclass, not by defaulted field.** `api.py`'s `_wire`
   serializes every field of every dataclass it is handed. So a defaulted
   `CapitalStructure.events`, `StructuredCapitalResult.capital_events` or
   Common Equity decomposition would appear in existing responses. The Section
   6.8 additions therefore live on three subclasses produced only when a
   refinance exists: `CapitalStructureWithEvents`,
   `RefinancedCommonEquityReturns` and `RefinancedCapitalResult`. A plain
   structure and every no-refinance result keep exactly their fields, which is
   how F20 parity holds by construction. Stage 2 must teach the codec,
   fingerprint and API these subclasses; no Stage 1 path produces one from
   stored data.
2. **`UnexecutedPosition`.** The replacement of an event that did not execute
   has no principal, so no schedule, return or structural metric exists for it.
   It is reported in `RefinancedCapitalResult.unexecuted_positions` with the
   event's reason, rather than as a `PositionReturns` with invented zeros.
3. **`CapitalStructureStatus.REFINANCE_UNAVAILABLE`** is the status companion of
   the ratified `refinance_unavailable` reason. The P7.9 adapter accepts exactly
   that status-and-reason pair and nothing else.
4. **Result detail beyond Section 6.8's indicative shapes.** `RetiringPayoff`
   carries `payoff_authority` and, for the acquisition loan only,
   `provider_cash_flows` (P7.7 reports that loan's schedule only to the sale).
   `RefinanceResult` carries separate `value_dependency` and `noi_dependency`
   records (R-C). A retired position's identity is its `RetiringPayoff`; no
   field is added to `PositionReturns`, which would leak.
5. **BLOCKED.** An event is blocked by an unresolved Funding Requirement in its
   scope at or before the event year, or by an unresolved continuing senior
   position. Positions that depend on the event are reported N/A, except a
   position whose own settlement already reports an unresolved or blocked
   claim: that truer root cause is kept, with its requirements. Common Equity
   keeps P7.7's `unresolved_funding_requirement` reason.
6. **The Investment root after a Unit's acquisition loan retires.** The
   Investment residual starts from the consolidated levered series, as P7.8
   does. For each year after the event it gains that Unit's accepted
   `unlevered - levered` difference once. The splice identity check (INV-16)
   proves that difference is exactly the retired loan's claims.
7. **The Investment-scope event with Unit debt**
   (`investment_refinance_with_unit_debt`) is judged after the Unit scopes
   settle, from their final schedules (a replacement's included) and from the
   balance service for acquisition loans.
8. **A Unit event that does not execute inside an Investment** makes every
   Investment-scoped position N/A. An Investment event in the same variant is
   then reported `UNAVAILABLE` with `upstream_capital_event_not_executed`
   (Section 23.4, correction 3). As first implemented it was reported
   `EXECUTED` with no settlement, contrary to this item's original text.
9. **The DSCR proportionality guard** (Section 9.3) raises the package's typed
   internal `CapitalStructureError`, never a plain error.
10. **Stage 2 scope, not implemented here.** `capital_event_kind_conflict` and
    `capital_event_scope_conflict` (P-8 across the Base and a Strategy's
    structures) need persisted structures. `evidence_not_approved` is produced
    only by Stage 2's valuation adapter. F13 and F18 are Stage 2 fixtures and
    F23 is Stage 3.
11. **Fixture F19, adapted.** The ratified P7.1 registry has no `current_noi`
    target, so "scales current NOI by 0.90" cannot run through the accepted
    Scenario path. F19 uses the accepted `noi_growth` target (SET -5%): forward
    NOI 722,000, both capacities 7,220,000 in a tie, and `N = 1,700,000`. The
    property proven is the contract's.

### 23.3 Guards re-pinned

Each accepted guard keeps its own claim. Where a claim was about its own gate,
it is now judged in committed history. No invariant is weakened or deleted.

- **P7.7 architecture:** the "no later-gate economics" scan of `contracts.py`
  and `validation.py` reads the P7.7 merge. Validation's expected imports name
  the pure event validator.
- **P7.8 architecture:** `contracts.py` and `validation.py` leave the
  working-tree freeze, and a test proves they were byte-identical to the P7.7
  merge through `2e1f84a`. The three P7.8 seam modules' "no refinancing" scan
  reads `2e1f84a`. The expected imports name `.events` and
  `.refinance_execution`. The later-funding test asserts the exact narrowed
  conditions.
- **P7.8 execution contracts:** the enum-member pins append the ratified
  members, following the P7.10 precedent.
- **P7.8B architecture:** the refinance files leave its freeze and
  protected-path set. Tests prove the changed files were byte-identical to
  P7.8A's head through `2e1f84a`, and the added files did not exist there.
- **P7.9 architecture and Stage 2:** `contracts.py`, `validation.py` and
  `common_equity.py` are proven frozen through `2e1f84a`. The deferred-scope
  identifier scan of the seam reads `2e1f84a`.
- **P7.10:** Stage 1's frozen and seam-definition claims read `2e1f84a`. The
  valuation-reader allowlist names the three refinance modules. The amount-rule
  claim is proven in the Stage 1 merge and admits exactly `RefinanceProceeds`.
  Stage 4's ledger reads its committed range `9ca957a..a6f1b2b`, exactly as its
  own docstring anticipated.
- **D4.6B G37 and D6.3:** G37's engine freeze is narrowed by exactly the one new
  balance-service file, following its per-gate pattern. D6.3's engine ledger
  reads D6.3's committed range, as its persistence ledger already did.

Stage 1's own guard is `tests/test_refinance_v1_stage_1_architecture.py`. A
later gate re-pins it to Stage 1's committed range.

### 23.4 Independent-review corrections (execution-state boundaries)

The independent review of Stage 1 found three defects. They are corrected in
one local commit on the same branch. **Stage 1 remains pending review and is
not accepted.** The regressions are in
`tests/test_refinance_v1_execution_state_boundaries.py`; mutation proofs
M22–M25 kill each defect's reinstatement.

1. **The reserved priority 1 (R-N, Section 10.3).** The succession pair
   `{retiring, replacement}` excused the pair's shared priority before the
   acquisition-loan reservation was checked. So an authored priority-1
   position and its priority-1 replacement were accepted beside a continuing
   acquisition loan, and sizing then omitted that loan from the continuing
   senior debt. Now:
   - A pair excuses only its own collision. Unit priority 1 stays the
     acquisition loan's unless the Unit's one event retires the
     `LegacyAcquisitionLoanRef` and its replacement holds that rank alone.
   - An authored priority-1 position that was outstanding beside the loan
     before the event is refused, even when the same event retires both.
   - A priority-2-or-lower pair with no other occupant stays valid, and
     ordinary duplicate-priority refusals are unchanged.
   - Below validation, a replacement at priority 1 beside a continuing
     acquisition loan is an engine defect (`CapitalStructureError`). It is never
     sized as though the loan were absent.
2. **The forward-NOI authority boundary (Section 8.3).** `forward_noi` caught
   P7.10's `ValuationError` and returned `None`, which reported an engine
   defect as `forward_noi_unavailable`. `ValuationError` is a programming
   error by P7.10's contract (an invalid internal month, or an NOI series that
   does not span its hold). Now:
   - `forward_noi` returns `None` only when the scope's authority is absent.
   - Every `ValuationError` propagates, and a consolidated NOI series that does
     not reach the event year raises one too.
   - A non-positive NOI is a value. It stays the typed
     `non_positive_forward_noi` state, and F12 is unchanged:
     `noi_by_year[...] <= 0`.
3. **An Investment event after a Unit event that did not execute (Sections
   12.4, 15.2, 15.4).** The Investment scope was correctly left unsettled, but
   its plan was reported as sized. That gave an impossible state: `EXECUTED`,
   with no settlement, no event cash, and its replacement among
   `unexecuted_positions`. **Ratified clarification:**
   - When a Unit event is `UNAVAILABLE` or `NOT_EXECUTABLE`, an Investment-scope
     event that would otherwise execute is `UNAVAILABLE`, with the appended
     reason `upstream_capital_event_not_executed`. Its message names the events
     by label.
   - Gross proceeds, the binding set, payoffs, funding and the bridge are
     absent. The capacities stay, as contractual facts. No event cash is added.
   - Its replacement appears exactly once in `unexecuted_positions`. Common
     Equity stays `refinance_unavailable`.
   - An Investment event that already does not execute on its own facts keeps
     its own reason.
   - No event is reported `EXECUTED` unless its settlement occurred.

   **Precedence when Unit events fail in different ways (ratified).** For an
   Investment event that would otherwise execute:
   - If any upstream Unit event is `UNAVAILABLE` or `NOT_EXECUTABLE`, the
     Investment event is `UNAVAILABLE` with
     `upstream_capital_event_not_executed`.
   - That stays true when another Unit event is also `BLOCKED` by unresolved
     funding. Resolving that funding alone would not let the Investment event
     execute, so `BLOCKED` would mislead.
   - The Investment event is `BLOCKED`, keeping its unresolved-funding meaning
     unchanged, only when no upstream Unit event is `UNAVAILABLE` or
     `NOT_EXECUTABLE` and at least one is blocked by unresolved funding.
   - An Investment event that already does not execute for its own reason
     keeps that reason in every case.

   A second review round corrected three more boundaries in a fourth local
   commit. It is recorded in items 4 to 6 below.

4. **Common Equity follows the dominant non-executed refinance (Section 15.4,
   ratified).**
   - If any event is `UNAVAILABLE` or `NOT_EXECUTABLE`, Common Equity is
     `REFINANCE_UNAVAILABLE` with reason `refinance_unavailable`.
   - Every cash-flow and return field is then unavailable, never partial or
     zero-filled.
   - This dominates any simultaneous unresolved Funding Requirement.
   - Only when no event is `UNAVAILABLE` or `NOT_EXECUTABLE`, but an event is
     `BLOCKED` by unresolved funding, does Common Equity keep P7.7's
     `UNRESOLVED_FUNDING` / `unresolved_funding_requirement`.
   - The rule reads the typed event status, never a message.
5. **A blocked-only upstream blocks the Investment event.**
   - Before: an unresolved Unit requirement blocked every Investment-scoped
     position's settlement, yet a would-be-executed Investment event was still
     reported `EXECUTED`, with a bridge, and nothing of it settled. The first
     correction round missed this case.
   - Now the event is `BLOCKED` with `upstream_unresolved_funding`, so the
     precedence rule above holds end to end.
   - The upstream requirements are the typed objects behind the blocking ids.
6. **No opaque identity in any analyst-facing refinance message (Section
   15.3).**
   - P7.7 and P7.8 build their messages from identities, and they stay exactly
     as accepted. No P7.7 or P7.8 production file changes, and a structure
     without a refinance never reaches the refinance executor.
   - A refinance result restates, from typed objects, every analyst-facing
     message it carries:
     - the capital-event messages, `BLOCKED` included;
     - each position's unresolved and senior-blocked messages;
     - each Funding Requirement's `explanation`, wherever it appears (the
       result, the position and the annual claim carry one object);
     - Common Equity's unresolved-funding message.
   - Positions are named by `name`; the acquisition loan, which has no authored
     name, is "the acquisition loan of Unit X". Events are named by label, and
     periods as Hold Year N or Model Month N.
   - Identities stay in their typed fields. No identity, amount, status or
     order changes, and no message is edited by string replacement.
   - Units carry no analyst name at this layer, so a Unit is still named by its
     id, as throughout P7.7.
   - The guard is `tests/test_refinance_v1_message_boundaries.py`. It walks
     every message of eight representative states under seeded identities, and
     proves the presentation changes messages only.

   Mutation proofs M26–M31 kill the reinstatement of each of items 4 to 6.

   `RefinanceUnavailableReason` gains that one appended member. No other
   contract, schema, persistence, API or presentation surface changes.
