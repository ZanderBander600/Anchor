# Underwriting V2 Golden Reference Case

## Status

**Frozen — Phase 0.** This is the authoritative V2 reference case, companion
to `docs/underwriting_v2_financial_conventions.md`, at the same frozen status
as the existing V1 golden case in `docs/phase_2_deterministic_engine.md`. It
exists to become the permanent V2 regression benchmark once the engine
implementation lands (see that document's "Reference-Case and QA Strategy"
and "Recommended Phased Implementation Sequence").

All five V2 assumptions are nonzero, so every new convention is exercised at
once, alongside an interest-only period that spans a full DSCR-relevant
transition.

**Precision note.** Every figure below was independently reconciled against
the standard closed-form annuity/amortization formulas using multiple
cross-checking derivation methods (Taylor-series log/exp evaluation of
`(1+r)^n`, repeated-squaring binary exponentiation, and reverse-solving
`(1+r)^n` from intermediate figures), carried to at least seven significant
figures throughout, with cent-level precision on every currency figure and
five-decimal precision on every rate/multiple. This case is an independently
verifiable *target* for an implementation to be checked against — the exact
IEEE-754 bit values an implementation produces are authoritative once that
implementation exists, exactly as the existing V1 golden case already treats
its own note about floating-point last-bit noise around contractual
maturity.

## Inputs

| Field | Value |
|---|---|
| `purchase_price` | $10,000,000.00 |
| `current_noi` | $600,000.00 |
| `occupancy` | 0.95 (informational only — confirmed inert, affects no output below) |
| `noi_growth` | 3.0% |
| `hold_period` | 5 years |
| `exit_cap_rate` | 6.5% |
| `ltv` | 60.0% |
| `interest_rate` | 5.0% |
| `amortization` | 30 years |
| `acquisition_cost_pct` | 2.0% |
| `financing_fee_pct` | 1.0% |
| `disposition_cost_pct` | 2.5% |
| `annual_capex_reserve` | $50,000.00/year |
| `io_period` | 2 years |

## Capital Stack

| Quantity | Value | Formula |
|---|---|---|
| Loan amount | **$6,000,000.00** | `10,000,000 × 0.60` |
| Acquisition costs | **$200,000.00** | `10,000,000 × 0.02` |
| Financing fee | **$60,000.00** | `6,000,000 × 0.01` |
| Initial equity | **$4,260,000.00** | `10,000,000 − 6,000,000 + 200,000 + 60,000` |
| Going-in cap rate | 6.00000% | `600,000 / 10,000,000` (unchanged V1 formula) |

## NOI by Year and Annual CapEx

| Year | NOI | Annual CapEx |
|---|---|---|
| 1 | $600,000.000 | $50,000.00 |
| 2 | $618,000.000 | $50,000.00 |
| 3 | $636,540.000 | $50,000.00 |
| 4 | $655,636.200 | $50,000.00 |
| 5 | $675,305.286 | $50,000.00 |

Exit NOI (Year 6, sale-only) = `600,000 × 1.03^5` = **$695,564.44458**

## Debt Schedule

`r = 0.05/12 = 1/240` exactly. `io_months = 24`. `N = 360` (the fixed,
full amortizing-phase payment count — a property of `amortization` alone,
independent of `hold_period`).

- IO-phase monthly payment: `6,000,000 × (1/240) = $25,000.00` exactly
  (interest-only on the unchanged $6,000,000 balance).
- Amortizing-phase monthly payment, from `(1+r)^360 ≈ 4.4677445` (reconciled
  to 7+ significant figures via three independent methods):

**Monthly amortizing payment (PMT) = $32,209.29738**

| Year | Phase | `m` at year-end (amortizing payments made) | Annual Debt Service (ADS) |
|---|---|---|---|
| 1 | Interest-only | — (m=0) | $300,000.00 |
| 2 | Interest-only | — (m=0) | $300,000.00 |
| 3 | Amortizing | 12 | $386,511.56857 |
| 4 | Amortizing | 24 | $386,511.56857 |
| 5 | Amortizing | 36 | $386,511.56857 |

### Remaining loan balance at exit

Sale occurs at month 60 = 24 interest-only months + `m = 36` amortizing
payments into the fixed `N = 360`-payment schedule. `m` (payments made by
exit) and `N` (the fixed schedule length) are distinct quantities — `m` is
exit-date-dependent, `N` is not.

Verify via `B_m = L(1+r)^m − PMT[(1+r)^m−1]/r` with `(1+r)^36 ≈ 1.1614722`,
or equivalently an amortization-table/`CUMPRINC`-style spreadsheet function
for 36 payments into a $6,000,000 / 5% / 360-payment schedule:

**Remaining loan balance at exit (m = 36 of N = 360) = $5,720,615.68**

## Annual DSCR and Minimum DSCR

| Year | DSCR |
|---|---|
| 1 | 2.00000x |
| 2 | 2.06000x |
| 3 | 1.64688x |
| 4 | 1.69629x |
| 5 | 1.74718x |

Full-precision Year 3 value: `636,540 / 386,511.56857 ≈ 1.646884729`, which
displays as **1.64688x** at five decimal places (the sixth digit is 4,
rounding down).

`headline_dscr` (Year 1) = **2.00000x**.
`min_dscr` = **1.64688x** (Year 3 — the year amortization begins, exactly
the compression the IO mechanics are meant to surface; note `min_dscr`
equals the Year 3 `DSCR` value exactly, as it must, since Year 3 is the
minimum of the five-year series).

## Exit Value and Net Sale Proceeds

| Quantity | Value | Formula |
|---|---|---|
| Gross exit value | **$10,700,991.4551** | `695,564.44458 / 0.065` |
| Disposition costs | **$267,524.7864** | `10,700,991.4551 × 0.025` |
| Net levered sale proceeds | **$4,712,850.99** | `10,700,991.4551 − 267,524.7864 − 5,720,615.68` |

## Unlevered Cash Flows

| t | UCF |
|---|---|
| 0 | −$10,200,000.00 |
| 1 | $550,000.00 |
| 2 | $568,000.00 |
| 3 | $586,540.00 |
| 4 | $605,636.20 |
| 5 | $11,058,771.9547 |

## Levered Cash Flows

| t | LCF |
|---|---|
| 0 | −$4,260,000.00 |
| 1 | $250,000.00 |
| 2 | $268,000.00 |
| 3 | $200,028.43143 |
| 4 | $219,124.63143 |
| 5 | $4,951,644.70613 |

## Return Metrics

| Metric | Value | Verification |
|---|---|---|
| Unlevered IRR | **6.1388%** | NPV of the UCF series at 6.14% ≈ −$530 on a $10.2M base (≈0.005%) — solve for the exact zero via `=IRR(...)` on the series above |
| Levered IRR | **7.3802%** | NPV of the LCF series at 7.38% ≈ −$25 on a $4.26M base (≈0.0006%) — solve for the exact zero via `=IRR(...)` on the series above |
| Equity multiple | **1.38235x** | `5,888,797.77 / 4,260,000.00` (sum of positive LCF ÷ \|sum of negative LCF\|) |

Directional sanity check: levered IRR (7.3802%) > unlevered IRR (6.1388%) —
positive leverage, consistent with a 6.00% going-in cap rate against 5.00%
cost of debt even after amortization drag and the full V2 cost/reserve/fee
load. This is the expected shape for these inputs.

## Finalized Reference Values

```
loan_amount                    = 6,000,000.00
acquisition_costs               = 200,000.00
financing_fee                   = 60,000.00
initial_equity                  = 4,260,000.00
going_in_cap_rate               = 0.06
noi_by_year                     = [600,000.000, 618,000.000, 636,540.000, 655,636.200, 675,305.286]
exit_noi                        = 695,564.44458
annual_capex_reserve_by_year    = [50,000.00, 50,000.00, 50,000.00, 50,000.00, 50,000.00]
monthly_debt_service (post-IO)  = 32,209.29738
annual_debt_service             = [300,000.00, 300,000.00, 386,511.56857, 386,511.56857, 386,511.56857]
remaining_loan_balance          = 5,720,615.68        (m = 36 amortizing payments of N = 360)
dscr_by_year                    = [2.00000, 2.06000, 1.64688, 1.69629, 1.74718]
headline_dscr                   = 2.00000
min_dscr                        = 1.64688
exit_value                      = 10,700,991.4551
disposition_costs               = 267,524.7864
net_sale_proceeds               = 4,712,850.99
unlevered_cash_flows            = [-10,200,000.00, 550,000.00, 568,000.00, 586,540.00, 605,636.20, 11,058,771.9547]
levered_cash_flows              = [-4,260,000.00, 250,000.00, 268,000.00, 200,028.43143, 219,124.63143, 4,951,644.70613]
unlevered_irr                   = 0.061388   (6.1388%)
levered_irr                     = 0.073802   (7.3802%)
equity_multiple                 = 1.38235
```
