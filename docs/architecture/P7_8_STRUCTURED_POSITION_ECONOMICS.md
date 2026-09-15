# P7.8 Structured Position Cash Flows + Position Returns

Status: Session A (backend financial execution) decision record, awaiting human
financial review.
Base: `main` @ `a9f9b09` (the P7.7 merge).
Branch: `feature/p7-8-structured-position-returns`.
Risk: Tier 1 (financial / contract critical).

`docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md` is the authority
(Sections 3, 12, 14 and 21), and
`docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md` records the foundation
this gate executes on. This record states only what P7.8 Session A decided and
shipped. It reopens no ratified decision and no P7.7 contract.

---

## 1. Engine-scope approval (Q16)

P7.8's Tier 1 approval covers:

- executing authored `CapitalPosition` contracts downstream of completed
  project economics;
- resolving `FixedAmount` and `PctOfPrice` funding;
- scheduling authored debt through the unchanged `debt.py` pure functions;
- preferred current pay and contractual accrual under the conventions below;
- deterministic claim settlement by scope and priority;
- Funding Requirement propagation;
- the Common Equity residual;
- position returns and structural metrics;
- annual aggregation of model-month position events;
- new result contracts.

`debt.py`, `acquisition.py`, `noi.py`, `returns.py` and `consolidation/engine.py`
are byte-identical to `a9f9b09`. So are the four P7.7 modules `contracts.py`,
`validation.py`, `legacy.py` and `foundation.py`.

## 2. What shipped

New modules in `src/anchor/capital_structure/`. The package `__init__.py` gains
exports only.

| Module | Contents |
|---|---|
| `execution_contracts.py` | Shapes only: execution issues and `CapitalStructureExecutionError`; `PriceBasis`, `ResolvedFundingEvent`, `PositionCashFlowEvent`, the debt and preferred schedules, `ScheduledPosition`, `PositionAnnualClaim`; `PositionReturns`, `CommonEquityReturns`, `StructuredCapitalResult`. |
| `execution_validation.py` | `validate_structured_execution`: execution compatibility of a structurally valid structure. |
| `funding.py` | Funding resolution, the funded amount and the closing events. |
| `debt_position.py` | The thin wrapper over the `debt.py` helpers. It is the only importer of `anchor.engine.debt`. |
| `preferred.py` | The preferred current-pay, accrual and redemption schedule. |
| `metrics.py` | Annual aggregation, position and common-equity returns, coverage and debt yield. It is the only importer of `anchor.engine.returns`. |
| `execution.py` | `execute_unit_capital_structure`, `execute_investment_capital_structure` and `schedule_position`. |

The P7.7 facades (`analyze_*_capital_structure`) are unchanged: they still
execute only the legacy loans and the residual, and still refuse any authored
position. The executors run them first, as the foundation.

## 3. Executable scope

- **Classes.** `SENIOR_DEBT` and `MEZZANINE_DEBT` share one schedule: the class
  orders payment and reporting and never selects a formula. `PREFERRED_EQUITY`
  has its own schedule. An authored `COMMON_EQUITY` position only names the
  residual.
- **Scopes.**
  - A standalone Unit executes Unit-scoped positions.
  - A visible Investment executes every Unit scope, then the Investment scope.
- **Order.** Economic order is `validation.economic_order`: scope, then
  priority. Every sum runs in canonical order: positions by scope and priority,
  events by (model month, sequence, event id), Units by `unit_id`. A permutation
  of `CapitalStructure.positions` changes nothing.

## 4. Structural vs execution validation

P7.7's `validate_capital_structure` runs first and is unchanged: an invalid
structure still raises `CapitalStructureValidationError`.

`validate_structured_execution` then refuses a *valid* contract that the first
executor does not execute, and raises `CapitalStructureExecutionError`:

| Code | Refused |
|---|---|
| `unsupported_funding_timing` | a funding event at a month other than 0 |
| `unsupported_amount_rule` | `PctOfValue` |
| `unsupported_fee_timing` | a fee at a month other than 0 |
| `unsupported_debt_pik` | `pik_rate != 0` |
| `unsupported_debt_current_pay` | `current_pay_rate != interest_rate` |
| `unsupported_preferred_current_pay` | a preferred `current_pay_rate > preferred_rate` |
| `unpermitted_preferred_accrual` | `preferred_rate > current_pay_rate` without `accrual_permitted` |
| `unsupported_redemption_timing` | a preferred redemption within a hold year before the exit |
| `unsupported_scope` | an Investment-scoped position in a standalone Unit |
| `unsupported_common_equity_scope` | a common-equity marker not scoped to the analysis root |
| `multiple_common_equity_markers` | more than one marker |
| `claim_below_common_equity` | a claim ranked below the marker in its scope |
| `duplicate_result_event_id` | an authored funding or fee id equal to a scheduled event id |

Nothing is moved to a supported convention, ignored or partially executed.

## 5. Funding

- **Closing only.** Every executable funding event and fee is at model month 0.
  Scheduled and construction draws remain Phase 8.
- **`FixedAmount`** is its dollars.
- **`PctOfPrice`** is `pct` of:
  - the Unit's resolved `AcquisitionTerms.purchase_price` (Unit scope);
  - `ConsolidatedResults.transaction_price` (Investment scope).

  The basis is recorded on each `ResolvedFundingEvent`.
- **Multiple events.** Each event is resolved on its own. `funded_amount` is
  their canonical-order sum.
- **Fees.** Debt fees at month 0 only. A fee is:
  - a positive receipt to the position;
  - a Common Equity use.

  It never changes the funded amount, Property economics or the acquisition
  loan.

## 6. Debt (cash pay)

- **Rates.** `interest_rate` is the total coupon and the rate the debt
  functions use. P7.8 requires `pik_rate = 0` and
  `current_pay_rate = interest_rate`.
- **Principal.** The funded amount. The executor never calls
  `calculate_capital_stack` or `calculate_debt_schedule`, and builds no
  `AcquisitionTerms`.
- **Reused unchanged** (no formula copied):
  - `calculate_scheduled_payment_count`;
  - `calculate_monthly_rate`;
  - `calculate_io_months`;
  - `calculate_io_payment`;
  - `calculate_monthly_debt_service`;
  - `calculate_monthly_payment`;
  - `calculate_amortization_schedule`.
- **Payoff.** `modeled_payoff_month = min(maturity_month, 12H)`.
  `maturity_month` is never rewritten.
- **Events.**
  - Each month `1..payoff` carries its scheduled payment (sequence 1).
  - The remaining balance after that month's payment is the balloon
    (sequence 2), in the payoff month.
  - A loan fully amortized by then has no balloon.
- **Balance at maturity or exit.** The balance immediately before the balloon.

## 7. Preferred equity

- **Rate split.**
  - `accrual_rate = preferred_rate - current_pay_rate`, with
    `0 <= current_pay_rate <= preferred_rate`.
  - A positive accrual rate requires `accrual_permitted` (so an explicit
    convention). Without accrual, the two rates are equal.
- **Current pay.** `current_pay_rate x unreturned principal`. It is a cash
  claim, paid at the year-end month `12y`.
- **Accrual.** Annual, recognized at each hold-year end up to and including the
  redemption year:
  - `SIMPLE`: `principal x accrual_rate`;
  - `ANNUAL_COMPOUND`: `(principal + beginning_accrued) x accrual_rate`.

  It is not a cash claim before redemption. It is **never** a cure: a
  current-pay shortfall is a Funding Requirement under the position's own
  resolution, and is never added to the accrued balance.
- **Redemption.**
  - Its timing:
    - the stated month, when it is a hold-year end (`12, 24, ...`) before the
      exit;
    - the exit month `12H`, when the stated month falls at or after the exit.
  - Any other month is refused. No partial year is prorated, and no monthly
    accrual exists.
  - In the redemption year, current pay comes first, then that year's accrual.
    The redemption then pays principal plus the accrued balance (sequence 2).
  - Nothing follows it.
- **Balance at maturity or exit.** Principal plus accrued return, immediately
  before redemption.

## 8. Claims and Funding Requirements

- **One annual claim per position per hold year.** Cash availability is
  annual, so every contractual receipt of a position in hold year `y`
  (scheduled payments, a balloon, current pay, a redemption) forms one
  `PositionAnnualClaim`.
  - Its `component_event_ids` name the exact model-month events.
  - The P7.7 identity `<position_id>/hold_year/<y>` therefore never collides.
  - The legacy ids are unchanged.
- **Settlement.** Each claim is settled by the unchanged P7.7 `settle_claim`:
  - against eligible cash `max(residual, 0)`;
  - under the position's own explicit resolution.

  There is no second shortfall engine and no default resolution.

## 9. Structural subordination and the Common Equity residual

Starting from the scope's authority series:

- **Unit scope.** `AcquisitionResults.levered_cash_flows`, in which the
  acquisition loan is already paid once. The legacy loan is never rebuilt,
  subtracted again or re-sized.
- **Investment scope.** `ConsolidatedResults.levered_cash_flows`, after each
  settled Unit position's closing flows and paid claims are applied to it once.
  P7.6 is never reconstructed.

Then, in priority order:

```
t = 0   residual += funding received;  residual -= fees
t = y   eligible  = max(residual_y, 0)
        residual_y -= claim paid (from cash + any resolved equity contribution)
```

- A negative project year stays negative.
- A resolved shortfall adds a further negative contribution.
- Equity contributed to cure one position is never cash for the next.
- A Unit-scoped claim reads only its own Unit's cash, never another Unit's
  surplus.
- The Common Equity Cash Flow is never floored.

## 10. Unresolved funding

- **The position.** A position with an unresolved requirement is
  `UNRESOLVED_FUNDING`: returns are N/A with the requirement ids.
  - Its later years are still settled one by one.
  - An unpaid amount is reported. It is never carried forward, accrued, cured
    or written off.
- **Junior positions.** Every position junior to it in its scope is
  `BLOCKED_BY_SENIOR_UNRESOLVED` and is not settled at all.
- **Investment-scoped positions.** Once any Unit scope is unresolved, every
  Investment-scoped position is blocked.
- **Senior and independent positions.** Senior positions, and positions in
  other Unit scopes, stay valid.
- **Common equity.** Unavailable, through the P7.7 `common_equity_outcome` and
  its reason.
- **Upstream.** Untouched.

## 11. Common equity

- **The residual.** Always produced, and never funded by a `FundingEvent`.
- **The marker.** At most one authored marker may name it, scoped to the
  analysis root. Otherwise `position_id` is `None`.
- **Returns.** `CommonEquityReturns` reads the *final* residual series:
  - `evaluate_irr`;
  - `calculate_equity_multiple`;
  - `calculate_project_return_totals` (TEI, TCR, profit).

  It is the Common Equity IRR after structured positions, never the project
  levered IRR (NS-1). Partnership allocation is P7.9's.

## 12. Position returns

- **Sign convention (provider side).**
  - Funding: negative.
  - Fee, scheduled debt service, balloon, current pay and redemption:
    positive.
- **Annual series.** `annual_cash_flows` is the canonical aggregation of the
  events into D6 periods `t = 0..H`.
- **IRR.** `evaluate_irr` on that series, with its `IrrStatus`. There is no
  XIRR and no monthly IRR.
- **MOIC and profit.**
  - `total_cash_received` is every positive receipt, fees included.
  - `moic = total_cash_received / funded_amount`.
  - `profit = total_cash_received - funded_amount`.
  - Fees are never netted against funded capital. The IRR series is net per
    period.
- **Availability.** Returns are reported only for a `COMPLETE` position.

## 13. Structural metrics

Structural metrics are contractual and closing facts, reported whatever the
cash settlement.

- **Attachment basis.** The funded capital structurally senior to the
  position.
  - Unit scope: that Unit's `loan_amount`, plus its authored positions of
    lower priority.
  - Investment scope: `ConsolidatedResults.loan_amount`, plus every Unit's
    authored positions, plus Investment positions of lower priority.
  - Fees and accrued return never enter it.
- **Detachment and last-dollar basis.** Detachment basis = last-dollar basis =
  attachment basis + funded amount.
- **Loan-to-price.** Measured against `PriceBasis`:
  - `UNIT_PURCHASE_PRICE`, or `INVESTMENT_TRANSACTION_PRICE`;
  - never as-is, stabilized or market value;
  - never capped.
- **Debt yield through.** `calculate_year_1_debt_yield`: Year-1 NOI of the
  scope (the Unit's, or the consolidated) over the last-dollar basis.
- **Coverage through, by year.** `calculate_dscr_by_year`: NOI of the scope
  over the cumulative current cash service through the position.
  - The service counts:
    - the legacy (or consolidated legacy) debt service;
    - every structurally senior authored position's scheduled payments or
      current pay;
    - the position's own.
  - It excludes balloons, redemptions, accrued return, fees and funding.
  - Headline is Year 1; minimum is the lowest defined year.

## 14. Implementation decisions for review

1. **Coverage after payoff.** Coverage is `None` in years after the position's
   modeled payoff year, as well as where the service is zero. The position is
   no longer outstanding then, and a value would describe only its seniors.
2. **Unresolved later years.** They are settled one by one, and no unpaid
   amount is carried forward (Section 10).
3. **Standalone Unit.** It refuses Investment-scoped positions. A standalone
   Unit has no Investment scope; P7.8B owns the product surface.
4. **Structural metrics** are reported for unresolved and blocked positions.
5. **Zero fees** are reported as events; they move nothing.
6. **A closing funding above the Initial Equity Requirement** may make the
   Common Equity closing flow positive. It is reported, not refused.

## 15. Deferred

- **P7.8B:**
  - persistence and the schema migration;
  - the Strategy `CAPITAL_STRUCTURE` domain;
  - financial fingerprints;
  - the API;
  - the `POSITION` decision perspective;
  - the Capital Structure UI and its QA.
- **Beyond P7.8:**
  - later funding months and scheduled draws (Phase 8);
  - `PctOfValue` and valuation timepoints (P7.10);
  - debt PIK and non-closing fees;
  - partial-year preferred redemption and monthly accrual;
  - refinancing and recapitalization (the SHOULD-HAVE sub-gate);
  - partnership and investor returns (P7.9);
  - further shortfall resolutions;
  - monthly cash availability and any other IRR cadence.

## 16. Evidence

The Session A gate report records the test counts, the oracles, the mutation
results and the suite results.
