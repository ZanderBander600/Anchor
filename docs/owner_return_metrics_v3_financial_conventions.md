# Owner Return Metrics V3 — Financial Conventions Specification

## Status

**Gate A1 — proposed, not yet implemented.** This is a specification-only
document, produced on `feature/owner-return-metrics-v3`, branched from `main`
after the Detailed Operating Model V2.1 merge (`main` @ `5460afc`, tag
`v2.1.0`; V2.1 demo freeze remains `ea67313`, tag `showcase-v2.1-2026-09-03`,
unmoved). No `AcquisitionResults`/`AcquisitionTerms`/`DebtSchedule` contract
change, no engine code, no validation code, no API/frontend change, and no
test has been implemented as part of producing it. It inherits
`docs/financial_conventions.md`, `docs/underwriting_v2_financial_conventions.md`,
and `docs/detailed_operating_model_v2_1_financial_conventions.md` unmodified;
where this document is silent, those govern.

The current V2.1 demo/production results are unaffected by this document and
must remain unaffected until an approved implementation phase begins.

## Purpose

Sprint A ("Owner Return Metrics") adds a small set of investor-facing return
metrics that are **derived from**, not computed by, the existing
deterministic engine. Per `AGENTS.md`'s Core Architecture Rule, this
document defines presentation-layer arithmetic over already-authoritative
engine outputs (`noi_by_year`, `capex_by_year`, `annual_debt_service`,
`initial_equity`, `loan_amount`, `levered_cash_flows`) — it introduces no new
IRR, DSCR, NOI, debt-service, or exit-value logic, and changes no existing
one.

## Architecture: where these metrics live

Confirmed from `src/anchor/contracts.py` and `src/anchor/engine/contracts.py`:

- `AcquisitionTerms` (`src/anchor/contracts.py:46`) is the acquisition/debt/exit
  input set shared, unmodified, by both Quick and Detailed Underwrite
  (`purchase_price`, `hold_period`, `exit_cap_rate`, `ltv`, `interest_rate`,
  `amortization`, `acquisition_cost_pct`, `financing_fee_pct`,
  `disposition_cost_pct`, `annual_capex_reserve`, `io_period`).
- `AcquisitionResults` (`src/anchor/engine/contracts.py:172`) is the single
  shared downstream output contract both modes converge into
  (`loan_amount`, `acquisition_costs`, `financing_fee`, `initial_equity`,
  `annual_debt_service`, `remaining_loan_balance`, `noi_by_year`,
  `capex_by_year`, `levered_cash_flows`, `unlevered_cash_flows`, …). Detailed
  mode exposes this identically via `DetailedAcquisitionResults.results`
  (`src/anchor/engine/contracts.py:214`); Quick mode returns it bare.

Because both modes produce byte-identical `AcquisitionResults` shapes
regardless of how `noi_by_year` was derived (Quick's `current_noi`/`noi_growth`
vs. Detailed's `OperatingProjection`), every metric below is defined **once**,
against `AcquisitionTerms` + `AcquisitionResults` fields only. No Quick-specific
or Detailed-specific formula is introduced, per Sprint A charter Section 8.

**Implementation note (non-blocking):** `purchase_price` is not itself a field
on `AcquisitionResults` — it lives on `AcquisitionTerms`, which the metrics
layer must also receive. (It is not to be back-derived from
`going_in_cap_rate = NOI_1 / purchase_price`, which would reintroduce a
division the caller doesn't need.) Any call site that already has an
`AcquisitionResults` also has the `AcquisitionTerms` that produced it, so this
is a function-signature detail for implementation, not an open question.

## Shared building block: "recurring" cash flow

Every metric below excludes sale proceeds, refinance proceeds, and terminal
liquidation proceeds. The engine's existing `levered_cash_flows` and
`unlevered_cash_flows` tuples (`src/anchor/engine/acquisition.py`) do **not**
exclude these in their final entry:

- `levered_cash_flows[H] = NOI_H - ADS_H - CapEx_H + net_sale_proceeds`
  (`calculate_levered_cash_flows`, `src/anchor/engine/acquisition.py:151`)
- `unlevered_cash_flows[H] = NOI_H - CapEx_H + exit_value - disposition_costs`
  (`calculate_unlevered_cash_flows`, `src/anchor/engine/acquisition.py:115`)

So Sprint A metrics **must not** read `levered_cash_flows[H]` /
`unlevered_cash_flows[H]` for the final hold year. Instead, every year
(including the final year) uses two new, independently-defined series:

```
Recurring Levered Cash Flow_y   = NOI_y - CapEx_y - ADS_y         (y = 1 .. H)
Recurring Unlevered Cash Flow_y = NOI_y - CapEx_y                 (y = 1 .. H)
```

using `noi_by_year`, `capex_by_year`, and `annual_debt_service` directly —
the same three series `calculate_levered_cash_flows`/
`calculate_unlevered_cash_flows` already consume, just without the terminal
`net_sale_proceeds` / `exit_value - disposition_costs` addition. This
requires no new engine calculation: it is `noi_by_year[y] - capex_by_year[y]
(- annual_debt_service[y])`, arithmetic already available on
`AcquisitionResults`.

No special case is needed for the final year, a one-year hold, or an IO
year — all of them fall out of this same formula:
- **IO years**: `ADS_y` is already the interest-only payment for those years
  in `annual_debt_service`; the recurring formula consumes it unchanged.
- **One-year hold (`hold_period = 1`)**: year 1 is simultaneously "the only
  year" and "the final year" — since the recurring formula never branches on
  `y == H`, no special case exists or is needed.
- **Final hold year**: covered above — this is precisely the reason the
  recurring series exists as a separate construct from `levered_cash_flows`.

## 1. Levered Cash-on-Cash Return

```
Levered CoC_y = Recurring Levered Cash Flow_y / Initial Equity Investment
```

**Denominator — confirmed from `src/anchor/engine/debt.py`:**

```
loan_amount     = purchase_price * ltv                                 (calculate_loan_amount, debt.py:19)
acquisition_costs = purchase_price * acquisition_cost_pct              (calculate_acquisition_costs, debt.py:25)
financing_fee   = loan_amount * financing_fee_pct                      (calculate_financing_fee, debt.py:37)
initial_equity  = purchase_price - loan_amount + acquisition_costs
                  + financing_fee                                      (calculate_initial_equity, debt.py:48)
```

`initial_equity` **includes** `financing_fee` (equity-funded per its
docstring: "Funded entirely by equity — never affects `loan_amount`") and
`acquisition_costs`. This is the sole, already-authoritative Initial Equity
figure (`AcquisitionResults.initial_equity`) — Sprint A introduces no second
computation of it. Verified against the golden case below:
`10,000,000 - 6,000,000 + 200,000 + 60,000 = 4,260,000`, matching the
sprint brief's stated authoritative value exactly.

This denominator is **fixed** across the hold (computed once, at
acquisition) — it is never recomputed per year and never reduced by
cumulative distributions or amortization.

**Edge cases:**

| Case | Behavior |
|---|---|
| `initial_equity == 0` | `Levered CoC_y = None` for every year (undefined — divide-by-zero), for the same reason `calculate_equity_multiple` returns `None` rather than `inf` when its denominator is zero (`src/anchor/engine/returns.py:82`). This is reachable: `ltv` is validated to `0 <= ltv <= 1` (`validation.py:150`), so at `ltv = 1.0` with `acquisition_cost_pct = financing_fee_pct = 0`, `initial_equity = 0` exactly. `initial_equity` can never be negative under current validation domains. |
| `initial_equity < 0` | Not reachable under current validation domains (see above); not specified further. |
| Negative recurring levered cash flow | Reported as a negative `Levered CoC_y` (e.g. `-0.04`). Never floored at zero, never suppressed. |
| IO years | No special case — see "Shared building block" above. |
| Final hold year | Uses `Recurring Levered Cash Flow_H`, **not** `levered_cash_flows[H]`. Never includes `net_sale_proceeds`. |
| Explicit zero CapEx | `annual_capex_reserve = 0` flows through `capex_by_year` as all-zero; no special case, formula unchanged. |
| All-cash acquisition (`ltv = 0`) | `loan_amount = 0` ⟹ `financing_fee = 0` (per `calculate_financing_fee`'s docstring: "Naturally `0.0` whenever `loan_amount` is `0.0`") and `annual_debt_service` is all-zero (`calculate_monthly_debt_service` on a zero balance). `initial_equity = purchase_price + acquisition_costs`, which is **identical** to the Unlevered Cash Yield denominator (Section 2) — so `Levered CoC_y == Unlevered Cash Yield_y` for every year in this case. This identity is a useful implementation-time sanity check, not a separate rule. |

**Existing levered IRR cash flows (`AcquisitionResults.levered_cash_flows`,
`levered_irr`) are unchanged.** Levered CoC is a new, additional series, not
a replacement.

## 2. Unlevered Cash Yield

Deliberately **not** named "cash-on-cash" — there is no financing/equity
denominator.

```
Unlevered Cash Yield_y = Recurring Unlevered Property Cash Flow_y
                          / Total Unlevered Acquisition Basis

Total Unlevered Acquisition Basis = Purchase Price + Acquisition Costs
```

**Transaction-cost review (per Section 2's instruction to confirm, not
assume):** the capital stack (`src/anchor/engine/debt.py`) has exactly two
transaction-cost terms: `acquisition_costs` (percentage of purchase price)
and `financing_fee` (percentage of *loan amount*). There is no third
transaction-cost term anywhere in `CapitalStack`/`AcquisitionResults`.
`financing_fee` is excluded from the unlevered basis deliberately: it is
purely debt-related (`= loan_amount * financing_fee_pct`, `0` whenever
`loan_amount = 0`), and the existing unlevered cash-flow series already
excludes it on the same reasoning (`calculate_unlevered_cash_flows`'s
docstring: "a financing fee, being debt-related, never appears in the
unlevered series either"). `acquisition_costs`, by contrast, is a
property-basis cost incurred regardless of financing structure (it is
`purchase_price`-based, not `loan_amount`-based), so it belongs in an
unlevered basis. **Decision: basis = Purchase Price + Acquisition Costs.**
Purchase price alone was considered and rejected — it would silently ignore a
real day-one cash outlay that is capitalized identically whether or not the
deal is levered.

This denominator is **fixed** across the hold, same as Initial Equity above.

**Edge cases:**

| Case | Behavior |
|---|---|
| Basis `== 0` | Only reachable if `purchase_price == 0` (with `acquisition_costs` therefore also `0`) — outside any realistic input domain, but specified for completeness: `Unlevered Cash Yield_y = None` for every year, same convention as Section 1. |
| Negative recurring unlevered cash flow | Reported as negative. Never floored at zero. (Only possible when `CapEx_y > NOI_y`.) |
| Explicit zero CapEx | No special case. |
| Financing fee | Never included in the denominator (see rationale above) — this is an unlevered metric by definition. |

## 3. Cumulative Operating Distributions

```
Cumulative Operating Distributions through Year y =
    sum(Recurring Levered Cash Flow_1 .. Recurring Levered Cash Flow_y)
```

Excludes sale proceeds and refinance proceeds (same recurring series as
Section 1's numerator — reused, not recomputed).

**Negative-year handling:** if `Recurring Levered Cash Flow_y < 0` in any
year, it **reduces** the running cumulative total — it is never floored at
zero and never excluded from the sum. A property that returns capital in
Year 1 but requires a capital call in Year 2 shows a cumulative total lower
than Year 1's alone.

**Naming boundary:** this metric answers "how much operating cash has the
investment distributed to equity during ownership" — it is explicitly not
"Total Equity Distributions." Terminal sale/refinance proceeds are never
folded into it under any circumstance, including the final hold year. A
`Total Equity Distributions` metric (operating + sale/refinance) is out of
scope for Sprint A per the charter (Section 3) and is not specified here.

## 4. Debt Yield

**Year 1 convention (implemented in Sprint A):**

```
Year 1 Debt Yield = Year 1 NOI / Original Loan Amount
                   = noi_by_year[0] / AcquisitionResults.loan_amount
```

**Annual/current debt-yield schedule: deferred.** Reviewed
`DebtSchedule`/`AcquisitionResults` (`src/anchor/engine/contracts.py:130`,
`:172`) — the only loan-balance fields exposed are `loan_amount` (original,
scalar) and `remaining_loan_balance` (final, scalar, at end of hold). There
is no beginning-of-year (or any per-year) loan-balance series anywhere in the
engine's public contracts. Per this charter's explicit instruction ("Do not
approximate balances in presentation code"), an annual `Debt Yield_y = NOI_y
/ Beginning-of-Year Loan Balance_y` schedule is **not** implemented in
Sprint A. It is deferred until the engine exposes an authoritative per-year
balance series (or is expected to be a small, separately-scoped engine
addition, not a presentation-layer approximation).

**Edge cases:**

| Case | Behavior |
|---|---|
| `loan_amount == 0` (all-cash) | `Year 1 Debt Yield = None`. Same zero-denominator convention as Sections 1–2. |

## 5. AAR / Average Annual Return

**SPEC STATUS: DEFERRED — awaiting Aaron's actual dashboard/workbook formula.**

Aaron's verbal description ("cumulative return including cash distributions
annualized over ownership duration") is compatible with multiple,
economically-different formulas — e.g. a simple-average annual-return
approximation, `(Equity Multiple - 1) / Hold Period`, an XIRR/CAGR-style
annualization of total cash returned, or something else entirely specific to
his workbook. No Anchor-invented version is specified or implemented here.
Once the source template is provided, this document will be updated with the
exact institutional convention, replicated and documented before any
implementation.

## 6. Current Equity / Current LTV / Current Implied Value

**SPEC STATUS: DEFERRED** to the later Current Valuation / Deal Tracker /
Capital Strategy sprint.

These require a current-value denominator the engine does not produce today.
`AcquisitionResults` has no intermediate-year valuation field, and this
charter explicitly prohibits assuming original purchase price stays current
or auto-applying the terminal exit cap rate to intermediate years as a
valuation convention. Not specified further here.

## 7. Existing Metric Integrity

Sprint A metrics are read-only consumers of already-authoritative engine
output. They introduce no change to: NOI, the operating statement, the debt
schedule, IRR, Equity Multiple, DSCR, exit value, sensitivity, break-even, or
Quick/Detailed convergence. Confirmed above: every formula in this document
reads `AcquisitionTerms`/`AcquisitionResults` fields only, and computes no
value that flows back into any existing calculation.

## 8. Zero/Undefined-Denominator Convention

Every metric above follows the engine's existing pattern for a
divide-by-zero condition — return `None`, never `0.0`, never `inf`/`-inf`,
and never raise:

- `calculate_dscr_by_year`: `DSCR_y = None` when `ADS_y == 0`
  (`src/anchor/engine/returns.py:27`).
- `calculate_equity_multiple`: `None` when its denominator is `0.0`, and
  explicitly guarded against ever returning `inf`
  (`src/anchor/engine/returns.py:73`).

Sprint A metrics apply the identical rule: `None` whenever the metric's
denominator (`initial_equity`, unlevered basis, or `loan_amount`) is exactly
`0.0`. No metric in this document ever divides by zero silently.

## 9. Presentation vs. Internal Precision

Internal computation stays full `float` precision, `ensure_finite`-guarded
(the same helper every existing engine calculation uses,
`src/anchor/engine/contracts.py`) — no rounding inside the metric functions
themselves. Rounding/formatting to percentage or currency display strings is
a presentation-layer concern (`src/anchor/ai/presentation.py`'s existing
`format_metric_value`/`format_percent` pattern), out of scope for the
calculation layer this document specifies.

## Open Questions for Alex

1. **AAR formula** (Section 5) — blocked entirely on the source
   dashboard/workbook; nothing to decide until that arrives.
2. **Whether a `Total Equity Distributions` metric (operating + sale/refinance,
   Section 3) belongs in Sprint A** — the charter marks it optional ("if it
   already falls out cleanly from existing contracts"). It does fall out
   cleanly (`Cumulative Operating Distributions through Year H +
   net_sale_proceeds`), so this is a scope call, not a technical blocker: add
   it now, or hold it for a later sprint?
3. **Function-signature detail, not a convention question:** confirm the new
   metrics module should take `(terms: AcquisitionTerms, results:
   AcquisitionResults)` rather than duplicating `purchase_price` onto
   `AcquisitionResults` — flagged in the Architecture section above so it
   isn't rediscovered mid-implementation.

Everything else in this document is a locked convention, directly confirmed
against the current production code cited inline above.
