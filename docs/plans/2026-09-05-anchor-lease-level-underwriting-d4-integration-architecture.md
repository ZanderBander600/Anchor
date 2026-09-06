---
title: Lease-Level Underwriting - D4 Property Integration Architecture and Financial Conventions
type: feat
date: 2026-09-05
amended: 2026-09-05
topic: lease-level-underwriting
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: docs-only
sprint: D
gate: D4.0
status: awaiting-human-financial-review
baseline_commit: 66cb6b7
---

# Lease-Level Underwriting — D4 Property Integration Architecture and Financial Conventions

## Status

**Architecture / financial-proof gate only. No production code, no engine
change, no contract change, no migration, and no test change is produced by
this gate.**

Verified baseline (`main` @ `66cb6b7`, re-run locally before this document was
written):

- Backend: `3657 passed` (`pytest -q`, 47.38s).
- Working tree: clean. `main == origin/main`.
- D3 merge commit `66cb6b7`, parents `175af87` / `87d3854` (PR #17).

This document inherits and revises nothing in:

- `docs/financial_conventions.md` (POC V1)
- `docs/underwriting_v2_financial_conventions.md` (Underwriting V2)
- `docs/detailed_operating_model_v2_1_financial_conventions.md` (Detailed V2.1)
- `docs/detailed_operating_model_v2_1_architecture.md` (Detailed V2.1 architecture)
- `docs/owner_return_metrics_v3_financial_conventions.md` (Owner Return Metrics V3)
- `docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md` (D0)
- `docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md` (D2)
- `docs/plans/2026-09-05-anchor-lease-level-underwriting-d3-recovery-conventions.md` (D3)

**One exception, and it is the headline finding of this gate.** D4 inspection
revealed an *active arithmetic contradiction* between D0 Section 18.1's EGI
formula and the D2.3 concession mechanics that shipped. The contradiction, its
proof, and the narrow correction are Section 5.4 and **HD-D4-5**. A single
dated amendment block has been added to D0 Section 18.1 and Section 4.7
pointing here. Nothing else in D0 is touched, and no prior decision is
rewritten.

**Classification: D4.0 HAS BLOCKING HUMAN DECISIONS** — seven, listed in
Section 33, of which three block D4.1/D4.2 and four block later gates.

---

## 1. Executive Summary

### 1.1 What D4 is

D4 turns the completed lease-level leasing engine (D1–D3) into a third
**operating producer** for the existing, unmodified acquisition / debt /
returns framework:

```
lease-level monthly economics
  -> property monthly operating economics          (D4 builds this)
  -> annual operating adapter                      (D4 builds this)
  -> the EXISTING acquisition/debt/returns engine  (D4 adds one channel)
```

D4 creates **no** `LeaseLevelReturnsEngine`, **no** `LeaseLevelDebtEngine`,
**no** `LeaseLevelAcquisitionEngine`. There remains exactly one
acquisition/debt/returns framework, entered at exactly one function:
`analyze_acquisition_from_operating_projection`.

### 1.2 The five findings that matter most

1. **D0 Section 18.1's EGI formula is arithmetically wrong wherever fractional
   downtime exists.** `cash_base_rent != contractual_base_rent - free_rent` in
   a fractional commencement month, because the two series differ by the
   *downtime* portion of that month, not only by the abatement. Proven in
   Section 5.4. D4's EGI must consume `cash_base_rent` directly and publish a
   third line so the statement stays additive. (**HD-D4-5**)

2. **There is no property-level operating aggregator.** D3.5 built
   `build_property_recovery_schedule` for recoveries, but nothing aggregates
   *cash base rent, free rent, TI, LC or occupied area* across suites in a
   rollover-aware way. `build_property_rent_roll_schedule` (D1.3) sums only
   **contractual base rent from raw in-place leases** and knows nothing about
   rollover. D0's D4 gate table jumps straight from `LeaseLevelOperatingInputs`
   to "the full canonical monthly EGI / expense / NOI build" and never
   schedules this. It is a gate of its own (Section 30, gate D4.2).

3. **D0 Section 13.1's preferred expense-helper extraction is blocked by
   G-1.** `anchor.leasing` may import only `anchor.contracts` and
   `anchor.engine.contracts`; `anchor.engine.operating_projection` is on the
   forbidden list. A shared growth helper therefore cannot live where D0
   assumed. D0 Section 13.1's own stated fallback — a documented mirror in
   `anchor/leasing/expenses.py` — becomes the recommendation, which has the
   side benefit of making **G-2 trivially true** (Detailed is not touched at
   all). (**HD-D4-1**)

4. **The management-fee circularity is provably absent**, not merely avoided by
   convention. Because the management fee is excluded from the recoverable
   pool, the dependency graph from fixed expenses to NOI is a DAG with a
   topological order of length 8. Proven algebraically in Section 13. No
   iterative solver, no fixed point, no spreadsheet circularity.

5. **The Owner Return Metrics V3 recurring series will silently overstate
   Lease-Level distributions unless TI/LC enter them.** `returns.py` already
   subtracts `capex_by_year` from `RLCF_y` and `RUCF_y`; TI and LC are the same
   class of below-NOI property capital. Omitting them would report a
   cash-on-cash return the property does not earn. (**HD-D4-3**)

### 1.3 Locked-by-inspection summary

Everything in this table was **already decided** by D0/D2/D3 or by shipped
code. It is restated because D4 is the gate that consumes it, not because it is
being decided now.

| Question | Answer | Authority |
|---|---|---|
| Which rent enters NOI | `cash_base_rent` | D0 10.2; D2 7.1; **corrected** by 5.4 below |
| Physical vacancy deduction | **None.** Modeled explicitly per suite per month | D0 15.1-15.2, G-M14 |
| Credit loss | `credit_loss_pct`, optional, default `0.0`, on lease revenue only | D0 4.6, 15.3-15.4 |
| Other income | Property-level annual amount, own growth rate, `/12` | D0 14 |
| Fixed opex | Five Detailed lines, `Line_1 * (1+g)^(y-1) / 12` | D0 13.2 |
| Growth anniversary | Hold-year boundary (period index), never calendar January | D0 7.2, code |
| Recoverable pool | `(TotalOpex_m - ManagementFee_m) * recoverable_expense_ratio` | D0 16.3, D3 3.1 |
| Management fee basis | `EGI_m * management_fee_pct`, EGI including recoveries | D0 13.2, 16.4 |
| NOI | `EGI_m - TotalOpex_m` (recoveries stay revenue, expenses stay gross) | D0 13.2, 18.1 |
| TI / LC | Strictly below NOI | D0 18.3, G-3 |
| Exit NOI | `sum(noi[m] for m in 12H+1..12H+12)` | D0 17.1, G-11 |
| Forward-window TI/LC | Neither a seller cash flow nor a reduction to exit NOI; disclosed only | D0 17.4 |
| Exit value | `exit_noi / exit_cap_rate`, unchanged | `acquisition.py` |
| DSCR | `NOI_y / ADS_y`, unchanged | `returns.py` |
| IRR timing | Annual, `H+1` points, unchanged | `returns.py`, G-6 |

---

## 2. Existing-State Code Inspection

Every statement in this section was verified by reading the file named, at
`66cb6b7`. Nothing here is inferred from a name.

### 2.1 The single downstream entry point

`src/anchor/engine/acquisition.py` —
`analyze_acquisition_from_operating_projection(operating_projection, terms)`.

It reads exactly three fields off `operating_projection`:

```
operating_projection.noi_by_year        # tuple[float, ...], length H
operating_projection.exit_noi           # float
operating_projection.going_in_cap_rate  # float
```

and every acquisition/debt/exit assumption off `terms: AcquisitionTerms`. It
then calls, in order: `calculate_capital_stack`, `calculate_debt_schedule`,
`calculate_exit_value`, `calculate_disposition_costs`,
`calculate_net_sale_proceeds`, `calculate_capex_by_year`,
`calculate_unlevered_cash_flows`, `calculate_levered_cash_flows`,
`calculate_return_metrics`, `calculate_owner_return_metrics`.

**This function is the convergence seam and it already exists.** D4 does not
create it and must not duplicate it.

### 2.2 `OperatingProjectionLike` — the shared shape

`src/anchor/engine/contracts.py` defines a `Protocol` with exactly the three
fields above, documenting deliberately that "every calculation downstream of
`analyze_acquisition_from_operating_projection` ... reads only `noi_by_year`,
`exit_noi`, and `going_in_cap_rate`".

Because it is a `Protocol` and Python uses structural typing, a third producer
satisfies it **without importing it**. That is what keeps the D4 dependency
direction clean (Section 27).

### 2.3 Quick's downstream seam, exactly

```
AcquisitionInputs
  -> engine/noi.py::build_quick_operating_projection   (a wrapper over forecast_noi)
  -> NoiForecast(noi_by_year, exit_noi, going_in_cap_rate)
  -> analyze_acquisition_from_operating_projection(
         projection, acquisition_terms_from_inputs(inputs))
  -> AcquisitionResults
```

`noi_by_year[y-1] = current_noi * (1 + noi_growth)^(y-1)`;
`exit_noi = current_noi * (1 + noi_growth)^H`;
`going_in_cap_rate = current_noi / purchase_price`. `occupancy` is read by
nothing.

### 2.4 Detailed's downstream seam, exactly

```
AcquisitionTerms + DetailedOperatingInputs
  -> engine/operating_projection.py::build_detailed_operating_projection(
         inputs, hold_period=H, purchase_price=P)
  -> OperatingProjection (12 annual line-item schedules + exit_noi + going_in_cap_rate)
  -> analyze_acquisition_from_operating_projection(projection, terms)
  -> DetailedAcquisitionResults(operating_projection, results)
```

The Detailed build loop, verified line by line, for `year in 1..H+1` with
`year_index = year - 1`:

```
revenue_factor        = (1 + revenue_growth) ** year_index
expense_factor        = (1 + expense_growth) ** year_index
gpr_y                 = gross_potential_rent * revenue_factor
other_income_y        = other_income * revenue_factor
vacancy_credit_loss_y = gpr_y * vacancy_credit_loss_pct
egi_y                 = gpr_y - vacancy_credit_loss_y + other_income_y
<five fixed lines>_y  = <input> * expense_factor
management_fee_y      = egi_y * management_fee_pct
total_opex_y          = five fixed lines + management_fee_y
noi_y                 = egi_y - total_opex_y
exit_noi              = noi_by_year[-1]        # the Year H+1 entry, then sliced off
going_in_cap_rate     = noi_by_year[0] / purchase_price
```

**Four facts D4 depends on, all confirmed here:**

1. `vacancy_credit_loss_pct` is a **single combined field** covering vacancy
   *and* credit loss, applied to GPR. It is the exact double-count hazard D0
   Section 15.2 rules out for Lease-Level.
2. Growth is **annual step growth indexed by hold year**, not by calendar year
   and not compounded monthly. Year 1 is the base year (`exponent = 0`).
3. `management_fee = EGI * pct`, where EGI is already net of the vacancy /
   credit-loss deduction and already includes other income.
4. `exit_noi` is a **full Year H+1 build**, never `NOI_H` grown mechanically.
   Lease-Level's forward-window convention is the same concept at monthly
   resolution.

### 2.5 What the shared engine does with `noi_by_year`

Verified in `acquisition.py` and `returns.py`:

```
capex_by_year[y]           = terms.annual_capex_reserve        (constant, length H)
UCF_0                      = -(purchase_price + acquisition_costs)
UCF_y (y<H)                = NOI_y - CapEx_y
UCF_H                      = NOI_H - CapEx_H + exit_value - disposition_costs
LCF_0                      = -initial_equity
LCF_y (y<H)                = NOI_y - ADS_y - CapEx_y
LCF_H                      = NOI_H - ADS_H - CapEx_H + net_sale_proceeds
DSCR_y                     = NOI_y / ADS_y          (None when ADS_y == 0)
year_1_debt_yield          = NOI_1 / loan_amount
RLCF_y                     = NOI_y - CapEx_y - ADS_y      (recurring, no sale term)
RUCF_y                     = NOI_y - CapEx_y
levered_cash_on_cash_y     = RLCF_y / initial_equity
unlevered_cash_yield_y     = RUCF_y / (purchase_price + acquisition_costs)
cumulative_distributions_y = running sum of RLCF
IRR                        = frozen bisection over H+1 annual points
```

**There is exactly one below-NOI channel today and it is `capex_by_year`,
sourced from `terms.annual_capex_reserve`.** It is consumed in **five** places:
both cash-flow series and both recurring series (and, through those, cash-on-
cash, cash yield and cumulative distributions). Any new below-NOI channel must
be wired into the same five places, or the reported metrics will disagree with
one another.

### 2.6 Debt

`engine/debt.py` is already monthly-internal: `calculate_annual_debt_service`
accumulates twelve monthly payments in chronological order per year and
explicitly refuses the `12 * PMT` shortcut; `calculate_remaining_loan_balance`
runs the month-by-month amortization recurrence to month
`min(12H, io_months + N)`.

**D4 requires zero debt change.** A future monthly Lease-Level debt *view*
reuses this chronology; it does not add a formula. `annual_debt_service` and
`remaining_loan_balance` are functions of `AcquisitionTerms` alone and are
therefore already bit-identical across all three modes for identical terms
(G-12 asserts it).

### 2.7 The leasing package, as shipped

| Module | Owns | Property-level aggregate? |
|---|---|---|
| `calendar.py` | `ModelMonth`, `build_model_months`, `projection_month_count` | n/a |
| `rent.py` | The one contractual-rent formula | no |
| `market.py` | Market-rent rate schedules, per suite | **no** — explicitly refuses to aggregate a rate |
| `rollover.py` | Branches, waterfall, expected + recursive + initial-vacancy chains | no |
| `leasing_costs.py` | TI amount, LC amount, event placement | no |
| `recoveries.py` | The recovery formulas, per lease / successor / chain | no |
| `aggregation.py` | `build_property_rent_roll_schedule` (D1.3), `build_property_recovery_schedule` (D3.5), the three annual reducers | **partly** |
| `validation.py` | Leasing-scoped ERROR/WARNING | n/a |

`aggregation.py` imports `anchor.engine.contracts` for `ensure_finite` — the
only `anchor.engine` import anywhere in the package, and one of the two
permitted by `tests/test_leasing_architecture.py::_PERMITTED_ANCHOR_IMPORTS`
(`anchor.engine.contracts`, `anchor.contracts`).

### 2.8 The property-aggregation gap — verified, not assumed

`grep -n "def build_property\|def suite_" src/anchor/leasing/*.py` returns
exactly four functions:

```
aggregation.py:202  build_property_rent_roll_schedule
aggregation.py:319  suite_recovery_projection
aggregation.py:372  build_property_recovery_schedule
market.py:291       build_property_market_rent_schedules
```

`build_property_rent_roll_schedule` takes raw `suites` and `leases`, builds one
`LeaseMonthlySchedule` per lease through `rent.py`, and sums
`contractual_base_rent` and `occupied_area`. It never touches `rollover.py`,
has no `cash_base_rent`, no `free_rent`, no `tenant_improvements`, no
`leasing_commissions`, and cannot see a successor. `PropertyRentRollSchedule`
has exactly six fields and none of the missing ones.

**Conclusion:** the D1.3 rent roll is the *contractual* rent roll, correct for
what D1 scoped and insufficient as a D4 revenue source on its own. D4 must
build the rollover-aware property operating aggregate, and D3.5's
`suite_recovery_projection` / `build_property_recovery_schedule` pair is the
exact template to follow.

### 2.9 The D3 pool seam, as contracted

`RecoverableExpensePool` carries `months` and `recoverable_expenses` — one
dollar figure per canonical `ModelMonth`, already net of every exclusion, with
**no category breakdown**, so that "no code here can infer, or silently
re-police, what went into it". Its docstring names D4 as the owner of its
construction. Domain `>= 0` and finite; `__post_init__` enforces one figure per
month.

Consumed by `build_lease_recovery_schedule`,
`build_successor_recovery_schedule`, `build_expected_rollover_recovery`,
`build_recursive_rollover_recovery` and
`build_initial_vacancy_rollover_recovery` — all keyword-only `pool:`.

`build_property_recovery_schedule` produces
`PropertyRecoverySchedule.expense_recovery` (monthly),
`.annual_expense_recovery` (Years 1..H) and
`.forward_exit_window_expense_recovery` (scalar). **That is the completed
recovery revenue D4 consumes. D4 rebuilds none of it.**

### 2.10 The suite chain builders D4 will consume

`RecursiveRollover` is the full-chain result: verified in
`rollover.py::build_recursive_rollover`, the accumulator is seeded with the
**known lease's own** `contractual_base_rent` (into both `face` and `cash`) and
`occupied_area` before any successor mass propagates, so
`expected_contractual_base_rent`, `expected_cash_base_rent`,
`expected_free_rent`, `expected_tenant_improvements`,
`expected_leasing_commissions` and `expected_occupied_area_sf` each describe
the complete suite, not the successors alone.

`tests/test_leasing_d2_6_recursive_rollover.py::
test_with_no_second_rollover_it_reproduces_expected_rollover` proves recursion
subsumes the single-rollover case. `InitialVacancyRollover` provides the same
field set for a suite that began vacant, including an explicit all-zero series
for `HOLD_VACANT`.

**Consequence for D4:** one authoritative per-suite rule suffices —
`build_recursive_rollover` for every suite carrying a known lease,
`build_initial_vacancy_rollover` for every suite carrying
`initial_vacancy`. `build_expected_rollover` remains a diagnostic path and is
not the property-level source.

### 2.11 Occupancy denominators differ between the suite and property layers

`RecursiveRollover.expected_occupancy` and `.expected_vacancy` use
**`suite.suite_area_sf`** as the denominator (`occupied / suite_area` in
`build_recursive_rollover`). The property metric uses
**`rentable_area_sf`** (D0 Section 15.1).

D4 must therefore aggregate `expected_occupied_area_sf` (an **area**, additive)
and divide once by `rentable_area_sf`. Averaging or summing the per-suite
`expected_occupancy` *ratios* would be wrong for any property whose suites
differ in size. Failure mode **FM-D4-31**.

### 2.12 Sensitivity and break-even

`analysis/sensitivity.py` already carries the two-mode pattern:
`SUPPORTED_ASSUMPTIONS` (Quick, five dimensions) and
`DETAILED_SUPPORTED_ASSUMPTIONS` (four `AcquisitionTerms` dimensions), with
`_build_detailed_scenario_terms` using `dataclasses.replace` on the immutable
terms. Lease-Level follows the Detailed pattern exactly. That is gate D4.6, not
D4.0, and it introduces no new dimension.

---

## 3. Exact Quick Convergence Today

```
AcquisitionInputs (14 fields)
      |
      | acquisition_terms_from_inputs()      (pure field projection, 11 fields)
      |------------------------------> AcquisitionTerms
      |
      | build_quick_operating_projection()
      v
NoiForecast
  noi_by_year        : tuple[float, ...]   length H
  exit_noi           : float
  going_in_cap_rate  : float
      |
      +---------------> analyze_acquisition_from_operating_projection(proj, terms)
                                          |
                                          v
                                  AcquisitionResults
```

Seam contract: `NoiForecast` satisfies `OperatingProjectionLike` structurally.
`current_noi`, `noi_growth` and `occupancy` never leave the Quick path.

---

## 4. Exact Detailed Convergence Today

```
AcquisitionTerms          DetailedOperatingInputs (11 fields)
      |                             |
      |    build_detailed_operating_projection(inputs, hold_period, purchase_price)
      |                             v
      |                    OperatingProjection
      |                      11 annual line-item schedules (display + its own golden)
      |                      noi_by_year, exit_noi, going_in_cap_rate  <- the seam
      |                             |
      +-----------------------------+
                     |
                     v
      analyze_acquisition_from_operating_projection(proj, terms)
                     |
                     v
             AcquisitionResults
                     |
                     v   (wrapped, not modified)
       DetailedAcquisitionResults(operating_projection, results)
```

Two properties D4 copies verbatim:

1. **The richer contract is wrapped in an envelope, never merged into
   `AcquisitionResults`.** `DetailedAcquisitionResults` holds both. Lease-Level
   gets the same treatment.
2. **The operating projection is built exactly once** and reused for both the
   engine call and the envelope field.

---

## 5. Proposed Lease-Level Convergence and the Monthly Revenue Stack

### 5.1 The convergence diagram

```
AcquisitionTerms
LeaseLevelPropertyInputs + Suites + Leases + MarketLeasingAssumptions
LeaseLevelOperatingInputs                                     (D4.1, new)
        |
        |  build_model_months(analysis_start, hold_period)     [D1.1, existing]
        v
   months : tuple[ModelMonth, ...]   length 12H + 12
        |
        +----------------------------------------------+
        |                                              |
   (A) PROPERTY EXPENSES                          (B) LEASING
        |                                              |
  build_property_expense_schedule()             per suite:
     [D4.1, new, leasing/expenses.py]             build_recursive_rollover()      [D2.6]
        |                                          or build_initial_vacancy_rollover() [D3.6]
        v                                              |
  MonthlyPropertyExpenseSchedule                       v
   five fixed lines, monthly                    suite chains
        |                                              |
        | build_recoverable_expense_pool()             |
        v      [D4.1, new] -- closes HD-D3-8           |
  RecoverableExpensePool  ------------------------->   |
        |                                              |
        |                          build_recursive_rollover_recovery(pool=...)  [D3.4]
        |                                              v
        |                                    suite recovery results
        |                                              |
        |                          suite_recovery_projection() [D3.5] ->
        |                          build_property_recovery_schedule()  [D3.5]
        |                                              v
        |                                    PropertyRecoverySchedule
        |                                              |
        |                          suite_operating_projection()      [D4.2, new]
        |                          build_property_operating_schedule()[D4.2, new]
        |                                              v
        |                                    PropertyOperatingSchedule
        |                                     (cash rent, contractual rent,
        |                                      free rent, absent rent, TI, LC,
        |                                      occupied area)
        |                                              |
        +----------------------+-----------------------+
                               |
                               v
              build_monthly_property_projection()      [D4.3, new, leasing/projection.py]
                               |
                               v
                   MonthlyPropertyProjection    <-- CANONICAL, user-facing, retained
                               |
                               v
              aggregate_monthly_to_annual()             [D4.4, new]
                               |
                               v
                   AnnualOperatingProjection    <-- satisfies OperatingProjectionLike
                               |
                               v
      analyze_acquisition_from_operating_projection(
          annual, terms, operating_capital=OperatingCapitalSchedule(...))   [D4.5]
                               |
                               v
                        AcquisitionResults
                               |
                               v
        LeaseLevelAcquisitionResults(monthly_projection, annual_projection, results)
```

**Only the derived annual projection crosses into the engine.** The canonical
monthly projection is retained on the envelope and never touched by a
downstream calculation (G-6).

### 5.2 The narrowest common downstream adapter — do not invent one

The question "what is the narrowest common downstream adapter for the three
modes?" is already answered by the repository: it is
`OperatingProjectionLike`, proven by two producers and consumed by exactly one
function. D4 adds a third producer with a superset shape.

**No `CommonAcquisitionOperatingInputs` is created.** Adding an abstraction
above `OperatingProjectionLike` would require Quick and Detailed to produce
fields they have no basis for, which is the fabrication D0 Section 3.4 already
rejected. The convergence seam is **additive**: one optional below-NOI
parameter, neutral by default.

### 5.3 The monthly property revenue stack — exact

For every canonical month `m` in `1 .. 12H + 12`:

```
 1  contractual_base_rent_m     <- property aggregate of suite chains (audit line)
 2  absent_rent_m               <- rent forgone to downtime/vacancy    (audit line)
 3  free_rent_m                 <- concession abatement, positive      (audit line)
 4  cash_base_rent_m            <- AUTHORITATIVE cash revenue
                                   identity: 1 - 2 - 3 == 4            (asserted)
 5  expense_recovery_m          <- PropertyRecoverySchedule.expense_recovery
 6  other_income_m              <- other_income_y / 12
 7  credit_loss_m               <- credit_loss_pct * (4 + 5)
 8  effective_gross_income_m    =  4 + 5 + 6 - 7
 9  property_taxes_m            \
10  insurance_m                  |
11  utilities_m                  |  each = Line_1 * (1+expense_growth)^(y-1) / 12
12  repairs_maintenance_m        |
13  other_operating_expenses_m  /
14  fixed_operating_expenses_m  =  9 + 10 + 11 + 12 + 13
15  management_fee_m            =  8 * management_fee_pct
16  total_operating_expenses_m  =  14 + 15
17  noi_m                       =  8 - 16
--- BELOW NOI, never touching any line above ---
18  tenant_improvements_m       <- property aggregate of suite chains
19  leasing_commissions_m       <- property aggregate of suite chains
--- STATE ---
20  occupied_area_m, vacant_area_m, physical_occupancy_m
--- AUDIT ---
21  recoverable_expense_pool_m  =  (14) * recoverable_expense_ratio
```

Compared with the candidate stack in the D4.0 brief, the repository's accepted
economics differ in exactly two places, and both are corrections rather than
preferences:

- **Line 2 (`absent_rent`) exists.** The brief's stack has no such line, and
  without it lines 1, 3 and 4 do not reconcile (Section 5.4).
- **Credit loss is line 7, based on `4 + 5`, not on gross rent.** D0
  Section 15.4 binds the base to "base rent net of free rent, plus
  recoveries" — explicitly *not* Detailed's gross-potential-rent base, and
  explicitly excluding other income (D0 Section 14).

CapEx is deliberately **not** in this stack. See Section 20.

### 5.4 Contractual vs cash base rent — the correction

**The financial answer to "which enters NOI" is `cash_base_rent`, and both D0
and this document agree.** Free rent is an above-NOI revenue concession;
contractual rent is an audit and leasing metric. Neither is counted twice, and
free rent is never placed below NOI.

**But D0 Section 18.1 states the mechanism wrongly.** It gives

```
EGI = contractual_base_rent - free_rent + expense_recoveries + other_income - credit_loss
```

and that expression is not equal to the cash rent the leasing engine actually
produced whenever a successor commences on a fractional downtime boundary.

**Proof, from shipped code.** `rollover.py::build_successor_contribution`:

```python
cash.append(successor_face * cash_factor[position])
free_rent.append(successor_face * abatement_months[position])
```

with `successor_occupancy_factors` giving `O_c = 1 - frac(D)` at the
commencement period `c`, and `free_rent_waterfall` giving
`cash_factor_m = O_m - free_abatement_m`. Therefore, in month `c`, writing `R`
for the successor's full contractual monthly rent:

```
contractual_base_rent_c = R
free_rent_c             = R * a          where a = free_abatement_c
cash_base_rent_c        = R * (O_c - a)

contractual - free_rent = R * (1 - a)
cash_base_rent          = R * (O_c - a)
difference              = R * (1 - O_c) = R * frac(D)     > 0 whenever frac(D) > 0
```

**Worked instance, using D2 Section 7.2's own approved reference case.** Lease
expires 30 June; downtime `D = 2.25`; free rent 2.5 months; successor
commences in September with `O_September = 0.75`, and the waterfall consumes
`a = 0.75` there. Let `R = 100,000`.

| Series | September value |
|---|---|
| `contractual_base_rent` | `100,000` |
| `free_rent` | `75,000` |
| `contractual - free_rent` (D0 18.1) | **`25,000`** |
| `cash_base_rent` (shipped code) | `100,000 * (0.75 - 0.75)` = **`0`** |

D0 Section 18.1's formula would recognise `25,000` of revenue in a month in
which the tenant is present for three-quarters of the month and pays nothing at
all. The `25,000` is the *downtime* quarter — space that was vacant — being
silently counted as collected rent.

**Correction (HD-D4-5).** D4 publishes `cash_base_rent` as the authoritative
revenue line and adds `absent_rent` so the statement remains additive and
auditable:

```
absent_rent_m = contractual_base_rent_m - free_rent_m - cash_base_rent_m
```

`absent_rent_m >= 0` always, is exactly `0` for every suite with no fractional
downtime, and is asserted to reconcile at `abs=1e-9` in every month
(guardrail **G-D4-1**). It is computed per suite and summed, never as a
property-level residual, so a sign error in one suite cannot be masked by
another.

Two properties of this correction worth stating:

1. **It changes no lease-level number.** Every D1–D3 series is untouched; only
   the property statement's presentation and the EGI formula change.
2. **It is arithmetically forced, not a modelling preference.** There is no
   defensible reading in which the downtime quarter of a boundary month is
   collected revenue.

### 5.5 Exact EGI formula

```
EGI_m = cash_base_rent_m
      + expense_recovery_m
      + other_income_m
      - credit_loss_m

credit_loss_m = credit_loss_pct * (cash_base_rent_m + expense_recovery_m)
```

With the default `credit_loss_pct = 0.0`, `credit_loss_m` is exactly `0.0` and
`EGI_m = cash_base_rent_m + expense_recovery_m + other_income_m`.

**Never** `contractual_base_rent` in place of `cash_base_rent`. **Never** a
second free-rent subtraction. **Never** a physical-vacancy factor.

### 5.6 Exact NOI formula

```
fixed_operating_expenses_m = property_taxes_m + insurance_m + utilities_m
                           + repairs_maintenance_m + other_operating_expenses_m

management_fee_m           = EGI_m * management_fee_pct

total_operating_expenses_m = fixed_operating_expenses_m + management_fee_m

NOI_m                      = EGI_m - total_operating_expenses_m
```

Recovery revenue stays on the revenue side. Operating expenses stay gross.
**Nothing is netted.** TI, LC and CapEx appear nowhere in this formula, under
any input (G-3 asserts it by perturbation).

---

## 6. Physical Vacancy Treatment

### 6.1 The rule

**Lease-Level applies no vacancy percentage of any kind to scheduled rent.**
Physical vacancy is already modeled, per suite, per month, through four
mechanisms that shipped in D1–D3:

| Mechanism | Effect on the month |
|---|---|
| Suite with no lease | `occupied_area` 0, rent 0, recovery 0 |
| Initial vacancy (`HOLD_VACANT`) | Explicit all-zero series (D3.6) |
| Initial vacancy (`MARKET_LEASE_UP`) | Zero until lease-up, then the chain's own economics |
| Rollover downtime | `O_m = 0` (or the boundary fraction), rent 0, recovery 0 |

A vacant suite already produces zero rent, zero recovery and zero occupancy.
Applying a further percentage would deduct the same vacancy twice
(**FM-D4-1**).

### 6.2 The Detailed field is combined — confirmed by inspection

`DetailedOperatingInputs.vacancy_credit_loss_pct` is one required field whose
product with GPR is a single `vacancy_credit_loss_by_year` line. Vacancy and
credit loss are **not separable** in Detailed.

Therefore Lease-Level cannot "reuse the vacancy half" of that input. The only
sound options are to carry a *credit-loss-only* assumption or to carry none.

### 6.3 How Lease-Level leaves a credit-loss path open

`LeaseLevelOperatingInputs` declares `credit_loss_pct` (default `0.0`) and
declares **no** `vacancy_credit_loss_pct` and **no** `occupancy`. The absent
mechanism is structurally absent, asserted by **G-M14** over dataclass field
names, exactly as Detailed resolved the same class of problem by omitting
`occupancy` from `AcquisitionTerms`.

An analyst migrating a Detailed deal must not carry a 7%
`vacancy_credit_loss_pct` across as a 7% `credit_loss_pct`; the UI label reads
"Credit Loss", never "Vacancy & Credit Loss", and an
`UNUSUALLY_HIGH_CREDIT_LOSS` WARNING fires above 10% (D0 Section 15.4).

---

## 7. Credit Loss Decision

### 7.1 The three options, evaluated

| Option | Description | Verdict |
|---|---|---|
| **A** | No separate credit loss in D4; physical vacancy modeled; credit loss deferred | Rejected — reopens a D0-locked decision for no gain |
| **B** | Explicit credit-loss-only assumption, `credit_loss_pct`, default `0.0` | **RECOMMENDED** |
| **C** | Reuse a combined vacancy/credit-loss input with separated semantics | Rejected — impossible; the Detailed field is not separable (Section 6.2), and reuse re-creates the double-count |

### 7.2 Recommendation: B, exactly as D0 already locked it

**This is not a new assumption and it is not theoretical completeness.** D0
Section 4.6 declares the field, Section 15.3 places it in the five-vacancy-
concept table as "the one optional allowance", Section 15.4 fixes its base and
its UI label, and Section 19 schedules its WARNING. Choosing A would be an
amendment to a locked D0 convention, not a simplification.

Financial reasoning:

- **Default `0.0` makes it economically neutral.** A competition model that
  never sets it produces numbers bit-identical to Option A. The cost of
  carrying it is one field, one multiply and one validation rule.
- **It is the only remaining revenue risk not otherwise modeled.** Physical
  vacancy, downtime and rollover are explicit; bad debt is not, and an
  underwriter asked "what if the anchor tenant stops paying" has no lever
  under Option A.
- **Removing it later is harder than adding it now**, because the D5 API,
  persistence schema and UI would then have to be revised.

**Basis, locked by D0 Section 15.4:** `credit_loss_pct * (cash_base_rent +
expense_recovery)`. Not gross contractual rent (that would tax free rent the
landlord never billed), and not other income (D0 Section 14 excludes it —
parking receipts and antenna licences are not tenant lease receivables).

**Ordering:** credit loss is computed *after* recoveries and *before* EGI, so
the management fee applies to revenue net of credit loss. This matches Detailed,
where `management_fee = egi_y * pct` and `egi_y` is already net of
`vacancy_credit_loss_y`.

**Status: not a blocking human decision.** Recorded as **HD-D4-6** at
`CONFIRM ONLY` severity, because a reviewer may legitimately wish to restate
that D0's lock still stands now that the code exists.

---

## 8. Other-Income Treatment

### 8.1 What Detailed does

`other_income` is a single annual dollar input grown by `revenue_growth` — the
*same* growth rate as gross potential rent — added to EGI after the vacancy
deduction, and therefore inside the management-fee basis and inside `exit_noi`.
It is not reduced by vacancy (the deduction applies to GPR alone).

### 8.2 What Lease-Level does — D0 Section 14, locked

| Question | Answer |
|---|---|
| Input units | `other_income`: dollars per year, `>= 0` |
| Month 1 / Year 1 basis | Year 1 annual amount; `OtherIncome_m = OtherIncome_y / 12` |
| Monthly allocation | Level within each hold year; no seasonality |
| Growth convention | `OtherIncome_y = other_income * (1 + other_income_growth)^(y-1)`, stepping on analysis-start anniversaries |
| Does vacancy affect it | **No.** Disclosed consequence: an analyst whose parking income genuinely tracks occupancy lowers the input and records why |
| Does it enter the management-fee EGI | **Yes** — it is an EGI component and the fee is a percentage of EGI |
| Does it enter exit NOI | **Yes** — it is inside `noi_m` for every forward month |
| Is it in the recovery base | **No** — it is revenue, not an expense |
| Is it subject to credit loss | **No** (D0 Section 14) |

### 8.3 Why a separate growth rate, and why no suite-level other income

`other_income_growth` is a distinct field, **not** `revenue_growth` and **not**
`market_rent_growth`. Lease-Level has no single `revenue_growth`: rent growth
arrives through contractual escalations and market-rent growth at rollover.
Tying parking income to market office rent growth would be an invented
economic link (**FM-D4-10**).

Suite-level other income is not invented in D4. Attributing parking to
individual leases needs a stall count, a stall rate and a downtime rule —
three inputs and a convention, to move a small line between two buckets that
sum to the same EGI.

### 8.4 Minimum competition-ready approach

One property-level annual amount and one growth rate. Setting `other_income =
0.0` makes the line vanish cleanly, so a deal with no ancillary income costs
nothing.

**Status: no human decision required.** D0 Section 14 answers every sub-question.

---

## 9. Property Operating Expenses — the Input Contract

### 9.1 The three reuse options

| Option | Description | Verdict |
|---|---|---|
| **A** | Lease-Level reuses `DetailedOperatingInputs` directly | **Rejected** |
| **B** | Extract a neutral shared property-expense contract out of `DetailedOperatingInputs` | **Rejected for D4** |
| **C** | A Lease-Level-specific input contract over the same six expense concepts | **RECOMMENDED** (D0 Section 4.6 already specifies it) |

**Why A fails.** `DetailedOperatingInputs` requires `gross_potential_rent`,
`vacancy_credit_loss_pct` and `revenue_growth`. In Lease-Level, GPR is an
*output*, `vacancy_credit_loss_pct` is a forbidden second vacancy mechanism
(G-M14), and there is no single `revenue_growth`. Reuse would force
fabricating three values — precisely the fabrication D0 Section 3.3 forbids —
and would put `vacancy_rate`-shaped fields on a Lease-Level contract where
they must be ignored, which is how FM-D4-1 gets written by accident.

**Why B is rejected for D4.** Extracting a shared expense sub-contract means
editing `DetailedOperatingInputs`, `validate_detailed_operating_inputs`, the
Detailed API request model, the persisted deal schema and the frontend type —
a refactor of Detailed, during the gate whose hard obligation is to prove
Detailed bit-identical. D0 Section 13.1's rule is explicit: "Detailed's
behavior is never changed to accommodate Lease-Level." B remains available
post-D4 as a pure refactor on its own merits.

**Why C is right.** The *concepts* and *formulas* are reused unchanged; only
the input container differs, exactly as `AcquisitionTerms` was introduced
alongside `AcquisitionInputs` rather than merging them.

### 9.2 The recommended contract

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseLevelOperatingInputs:
    """Property operating assumptions for Lease-Level (D0 Section 4.6).

    These are PROPERTY OPERATING assumptions, not lease-market assumptions.
    Nothing here belongs on MarketLeasingAssumptions, which describes how
    space re-lets, not what the building costs to run.
    """
    # revenue
    other_income: float                 # $/yr,   >= 0
    other_income_growth: float          # decimal, > -1
    credit_loss_pct: float = 0.0        # decimal, 0 <= x <= 1
    # the five fixed expense lines, Year 1 annual dollars
    property_taxes: float               # $/yr,   >= 0
    insurance: float                    # $/yr,   >= 0
    utilities: float                    # $/yr,   >= 0
    repairs_maintenance: float          # $/yr,   >= 0
    other_operating_expenses: float     # $/yr,   >= 0
    # rates
    management_fee_pct: float           # decimal, 0 <= x <= 1
    expense_growth: float               # decimal, > -1
    recoverable_expense_ratio: float    # decimal, 0 <= x <= 1
```

Placement: `src/anchor/leasing/contracts.py` (D0 Section 3.5 places every
Lease-Level contract there). Validation: `src/anchor/leasing/validation.py`,
under the existing leasing-scoped ERROR/WARNING architecture (HD-6), mirroring
`validate_recovery_inputs`. `src/anchor/validation.py` is **not** touched at
D4 — it owns the API-boundary field rules for Quick and Detailed, and the
Lease-Level API boundary is D5.

### 9.3 `recoverable_expense_ratio` location — HD-D3-8 resolved

It belongs on `LeaseLevelOperatingInputs`, with the property operating and
recovery assumptions — **not** on `Lease`, **not** on `Suite`, **not** on
`MarketLeasingAssumptions`. It is a fact about the building's expense
structure, identical for every tenant, and putting it on a lease would invite
per-lease ratios that the aggregate-pool model (D3 Section 3.1) does not
support.

**No silent default.** D0 Section 4.6 gives it no default and neither does this
document; a Lease-Level deal supplies it explicitly. A default of `1.0` would
quietly make every expense recoverable (**FM-D4-6**); a default of `0.0` would
quietly zero every NNN recovery.

---

## 10. Monthly Fixed Operating-Expense Convention

### 10.1 The formula — D0 Section 13.2, locked

For hold year `y` containing month `m` (with `y = H + 1` for the forward exit
window):

```
FixedExpenseLine_y = FixedExpenseLine_1 * (1 + expense_growth)^(y - 1)
FixedExpenseLine_m = FixedExpenseLine_y / 12.0
```

Level allocation inside each model year. `y` is derived from
`ModelMonth.hold_year`, which is `((period_index - 1) // 12) + 1` — the
**analysis-start anniversary**, never calendar January.

### 10.2 The worked case, on the brief's own example

`analysis_start_date = 2027-07-01`; Year-1 annual property tax `1,200,000`;
`expense_growth = 0.03`.

| Model month | Calendar | Hold year | Annual | Monthly |
|---|---|---|---|---|
| 1 | Jul-2027 | 1 | `1,200,000` | `100,000` |
| 12 | Jun-2028 | 1 | `1,200,000` | `100,000` |
| **13** | **Jul-2028** | **2** | `1,236,000` | **`103,000`** |
| 24 | Jun-2029 | 2 | `1,236,000` | `103,000` |

The step falls in **July 2028**, not January 2028. A January step would be
failure mode **FM-D4-12**.

### 10.3 No monthly compounding

`(1 + expense_growth)^(y-1)` is computed once per model year with an **integer**
exponent, exactly as `engine/operating_projection.py` does. There is no
`(1 + g)^(1/12)`, no `g/12`, and no month-over-month accumulation anywhere
(**FM-D4-11**). Monthly compounding would make Lease-Level's annual expense
totals differ from Detailed's for identical inputs, which golden case 14
forbids.

### 10.4 The overflow-safe growth factor

`engine/noi.py` and `engine/operating_projection.py` each carry a private
`_growth_factor` that converts CPython's `OverflowError` on `float ** int` into
`inf`, so `ensure_finite` can reject it explicitly. The second copy carries the
comment "Mirrors `engine/noi.py`'s `_growth_factor` exactly, for the same
reason".

Lease-Level needs the identical behaviour. Where that helper should live is
**HD-D4-1** (Section 33).

### 10.5 No seasonality — accepted and stated explicitly

D4 does **not** model monthly tax seasonality, utility seasonality, annual
true-ups or expense accrual schedules. Nothing in the existing architecture
supports any of them.

**This simplification is accepted and disclosed.** It changes nothing at annual
aggregation — the only resolution any downstream consumer sees — and the
monthly display of an evenly spread expense is honest about being an accrual.
A lumpy November property-tax bill would change the monthly *display* and no
annual figure, no NOI, no cash flow, no return.

---

## 11. Expense Growth Convention

```
Each of the five fixed lines grows annually, on analysis-start anniversaries,
by expense_growth. Year 1 is the base year (exponent 0).

The management fee does NOT use expense_growth. It is percentage-derived from
EGI and therefore grows with revenue, exactly as in Detailed.

Other income does NOT use expense_growth. It uses other_income_growth.

Base rent does NOT use expense_growth, revenue_growth, or any generic revenue
growth rate. It grows through contractual escalation (rent.py) and market-rent
growth at rollover (market.py) -- and through nothing else.

The recoverable pool follows the ACTUAL grown monthly expenses; it is never
grown independently.
```

**Semantic consistency with Detailed is exact.** Both apply
`(1 + expense_growth)^(year_index)` to the same five Year-1 annual inputs, with
Year 1 as base. Lease-Level then divides by 12 to reach the canonical month;
summing those twelve months returns the Detailed annual figure to within
ordinary IEEE-754 last-bit drift, which golden case 14 asserts at `abs=1e-9`.

**The rent-growth prohibition is load-bearing.** Applying Detailed's
`revenue_growth` to Lease-Level base rent would grow rent twice — once through
the lease's own escalation and once generically (**FM-D4-9**). If
`revenue_growth` appears anywhere in Lease-Level, it is a bug;
`LeaseLevelOperatingInputs` deliberately has no such field.

---

## 12. Recoverable Pool Construction — HD-D3-8 Resolved

### 12.1 The exact formula

```
fixed_operating_expenses_m   = property_taxes_m + insurance_m + utilities_m
                             + repairs_maintenance_m + other_operating_expenses_m

recoverable_expense_pool_m   = fixed_operating_expenses_m * recoverable_expense_ratio
```

This is exactly D0 Section 16.3 / D3 Section 3.1's
`(TotalOpex_m - ManagementFee_m) * recoverable_expense_ratio`, with
`TotalOpex_m - ManagementFee_m` expanded to the five fixed lines it equals by
construction. **The expanded form is the one D4 implements**, because it never
computes a total only to subtract a component back out, and because it cannot
accidentally pick up a future sixth expense line without an explicit decision.

Both forms are asserted equal in a golden (case 10).

### 12.2 Eligibility — verified against D0 and D3

| Item | In the pool | Authority |
|---|---|---|
| Property taxes | **Yes**, times the ratio | D0 13.1, D3 3.3 |
| Insurance | **Yes**, times the ratio | D0 13.1, D3 3.3 |
| Utilities | **Yes**, times the ratio | D0 13.1, D3 3.3 |
| Repairs and maintenance | **Yes**, times the ratio | D0 13.1, D3 3.3 |
| Other fixed operating expenses | **Yes**, times the ratio | D0 13.1, D3 3.3 |
| **Management fee** | **No** | D0 16.3, D3 3.2 — circularity and market practice |
| Capital expenditures | **No** | D3 3.3 — capital, not operating |
| Tenant improvements | **No** | D3 3.3 — below NOI, and specific to one lease |
| Leasing commissions | **No** | D3 3.3 — below NOI, same reasoning |
| Debt service | **No** | D3 3.3 — not a property operating expense |
| Acquisition costs | **No** | Transaction item, never in an operating statement |
| Financing fees | **No** | Transaction item, debt-related |
| Disposition costs | **No** | Transaction item, applied at sale |

**Not every expense is recoverable.** `recoverable_expense_ratio` is applied to
the *eligible* five lines only; it is not a licence to recover the fee or the
capital items.

### 12.3 Per-category recoverability stays deferred

HD-D3-5 (`CAN DEFER`) is not reopened. D4 builds one aggregate pool. If
per-category recoverability arrives later, the pool becomes a sum of category
pools and every consumer is unaffected, because `RecoverableExpensePool`
carries a single monthly figure by design.

### 12.4 The pool contract D4 satisfies

```python
build_recoverable_expense_pool(
    expenses: MonthlyPropertyExpenseSchedule,
    *,
    recoverable_expense_ratio: float,
) -> RecoverableExpensePool
```

Returns the **existing, unmodified** `RecoverableExpensePool`, carrying the
same `months` tuple by reference so the month-identity checks throughout
`recoveries.py` pass. `recoverable_expenses[i] >= 0` holds automatically
because every fixed line is `>= 0` and the ratio is in `[0, 1]`.

**HD-D3-8 is hereby resolved as Option A**, exactly as D3 recommended: D3
injects, D4 supplies. No expense engine ever enters `anchor.leasing`'s
recovery modules, and `recoveries.py` needs no change at D4.

---

## 13. Management-Fee Circularity — Algebraic Proof

### 13.1 The claim

There is no circular dependency between the management fee and tenant
recoveries, and therefore no fixed-point solve, no iteration and no
spreadsheet-style circular reference anywhere in the Lease-Level monthly
build.

### 13.2 The proof

Fix a month `m` and write the quantities as functions of the inputs.

**Step 1 — the fixed expense lines depend on inputs only.**

```
F_m = (T_1 + I_1 + U_1 + R_1 + O_1) * (1 + g_e)^(y(m) - 1) / 12
```

where `y(m) = ((m - 1) // 12) + 1`. Every symbol on the right is an element of
`LeaseLevelOperatingInputs` or of the calendar. `F_m` is a function of
`(inputs, m)` alone. In particular:

```
partial F_m / partial EGI_m       = 0
partial F_m / partial Recovery_m  = 0
partial F_m / partial Fee_m       = 0
```

**Step 2 — the pool depends only on `F_m`.**

```
P_m = F_m * rho              (rho = recoverable_expense_ratio)
```

The management fee is *not* a term of `F_m`. This is the entire reason the
exclusion in D0 Section 16.3 is load-bearing rather than merely conventional.
Hence `partial P_m / partial Fee_m = 0`.

**Step 3 — recoveries depend only on the pool and on lease structure.**

For every supported structure, `recoveries.py` computes

```
NNN:  Rec(L, m) = O_L,m * share_L * P_m
GRS:  Rec(L, m) = 0
MG :  Rec(L, m) = O_L,m * max(0, share_L * P_m - stop_L)
```

`O_L,m` comes from D1 contractual activity, `share_L` from area, `stop_L` from
the lease. None is a function of EGI or of the fee. Summing over leases,
`Recovery_m = f(P_m, lease structure)`, so
`partial Recovery_m / partial Fee_m = 0`.

**Step 4 — EGI depends on rent, recoveries, other income and credit loss.**

```
EGI_m = C_m + Recovery_m + OI_m - c * (C_m + Recovery_m)
      = (1 - c) * (C_m + Recovery_m) + OI_m
```

`C_m` (cash base rent) comes from the leasing engine and is a function of
leases, market assumptions and the calendar. `OI_m` is an input. Hence
`partial EGI_m / partial Fee_m = 0`.

**Step 5 — the fee depends on EGI.**

```
Fee_m = phi * EGI_m
```

Substituting Steps 1–4:

```
Fee_m = phi * [ (1 - c) * ( C_m + f(F_m * rho, structure) ) + OI_m ]
```

The right-hand side contains no occurrence of `Fee_m`. The equation is
**explicit**, not implicit: it is already solved.

**Step 6 — NOI closes the pass.**

```
NOI_m = EGI_m - F_m - Fee_m
      = (1 - phi) * EGI_m - F_m
```

again with no occurrence of `NOI_m` on the right.

### 13.3 The dependency graph is a DAG

```
inputs ──> F_m ──> P_m ──> Recovery_m ──┐
   │        │                            ├──> EGI_m ──> Fee_m ──┐
   │        │        C_m ────────────────┤                       ├──> NOI_m
   │        │        OI_m ───────────────┘                       │
   │        └──────────────────────────────────────────────────> ┘
   └──> credit_loss_pct ──> credit_loss_m ──> EGI_m
```

Every edge points forward. There is **no** edge from `Fee_m` back to `F_m`,
`P_m`, `Recovery_m` or `EGI_m`. The hypothetical loop

```
management fee -> recoverable pool -> recovery -> EGI -> management fee
```

requires the first edge, and that edge does not exist because Step 1 shows
`partial F_m / partial Fee_m = 0`.

### 13.4 The forced computation order

D0 Section 16.4's eight-step ordering is therefore not merely *a* convention
that works — it is the topological order of a DAG, and it is the only one:

```
1. cash base rent, free rent, absent rent, other income   (independent)
2. the five fixed expense lines                           (independent)
3. recoverable_expense_pool_m                             (from 2)
4. per-lease and per-suite recoveries, then the property sum (from 3)
5. credit_loss_m                                          (from 1 and 4)
6. EGI_m                                                  (from 1, 4, 5)
7. management_fee_m                                       (from 6)
8. total_operating_expenses_m, then NOI_m                 (from 2, 6, 7)
```

**One deterministic pass. No solver. No iteration. No convergence tolerance.**
Guardrail **G-D4-2** asserts the ordering by spying on call order, and a second
test asserts that no D4 module imports any root-finding or iteration utility.

### 13.5 What would break the proof

Recorded so a future gate cannot reintroduce the loop by accident:

- Making the management fee recoverable (adds the missing edge directly).
- Introducing an admin fee on recoveries computed as a percentage of the fee.
- A recovery cap or floor expressed as a percentage of total operating
  expenses *including* the fee.
- Gross-up computed against an EGI-derived occupancy target.

All four are already D0 Section 16.5-deferred. Each would require a fixed-point
solve and would need its own human decision.

---

## 14. Management-Fee Basis

### 14.1 The two candidates

| | **A — fee on total EGI including recoveries** | **B — fee on EGI excluding recovery reimbursements** |
|---|---|---|
| Formula | `phi * (C + Rec + OI - CL)` | `phi * (C + OI - CL)` |
| Matches Detailed's definition ("% of EGI") | **Yes** | No — a second, Lease-Level-only fee definition |
| Matches D0 13.2 / 16.4 | **Yes** | No |
| Institutional practice | Common; management agreements usually read "gross collections" or "gross revenues", which include reimbursements | Also seen, usually as an explicit carve-out |
| Effect on NOI | Lower NOI in a NNN building | Higher NOI in a NNN building |
| Risk | A fully-NNN building pays a fee on money that passes through | A silent divergence between two Anchor modes |

### 14.2 Recommendation: A

**Recommended: the management fee is `management_fee_pct * EGI_m`, with EGI
including expense recoveries.**

Reasoning, in priority order:

1. **It preserves existing Anchor convention exactly.** Detailed's fee is
   "percent of EGI" and Lease-Level's fee is "percent of EGI". The *sentence*
   is identical; only the set of EGI components differs, because Lease-Level
   has a revenue line Detailed does not. Option B would make the two modes
   answer "what is the management fee" differently, which the D4 brief
   explicitly forbids.
2. **D0 has already locked it** (Section 13.2's formula, Section 16.4's step
   7). Choosing B is an amendment.
3. **It is conservative in the direction that matters.** A is the lower-NOI,
   lower-value answer. In a competition setting an understated fee is the
   dangerous error, not an overstated one.
4. **B needs an input Anchor does not have.** "Excluding recoveries" is really
   "excluding whichever reimbursements the management agreement carves out",
   which varies by contract and would need its own field.

### 14.3 The magnitude, stated plainly

For the reconciliation property of golden case 11 (100% NNN, 100,000 SF,
ratio 1.0):

```
cash base rent     250,000
expense recovery   100,000
other income         5,000
EGI                355,000
fee at 3%           10,650      <- Option A
fee at 3% on 255,000 = 7,650    <- Option B
difference           3,000 per month = 36,000 per year
```

At a 6.5% exit cap that difference is roughly `554,000` of exit value. It is
financially meaningful, which is why it is recorded as **HD-D4-2** at
`CONFIRM ONLY` severity rather than silently adopted — the recommendation is
firm, but the reviewer should see the number.

---

## 15. Recovery Presentation vs NOI Mathematics

Anchor keeps **Expense Recovery Revenue** and **Property Operating Expenses**
as two separate lines and never nets them, even where the economics of a
100% NNN building make them offset.

Five reasons, all of which fail under a netting shortcut:

1. **Lease structures differ.** A Gross tenant recovers nothing; netting would
   have to net a per-lease amount against a property-level expense.
2. **Vacancy creates unrecovered expense.** In a half-empty building the
   landlord bears half the pool. A netted line would report a smaller expense
   than the landlord actually pays, hiding the carry cost of vacancy —
   precisely what lease-level modeling exists to reveal.
3. **Modified Gross thresholds matter.** Below the stop, recovery is zero
   while the expense is fully incurred.
4. **Auditability.** An analyst must be able to read the recovery line against
   the pool line and check the ratio.
5. **It would corrupt the management-fee basis**, because a netted expense is
   not an EGI component and the fee would silently change.

The 100% NNN offset (Section 24, golden 11) is therefore a **reconciliation
check**, never an implementation shortcut. Failure mode **FM-D4-4**.

---

## 16. Physical Occupancy — the Property View

### 16.1 The monthly metric

```
occupied_area_m     = sum over suites of that suite's chain occupied area in m
vacant_area_m       = rentable_area_sf - occupied_area_m
physical_occupancy_m = occupied_area_m / rentable_area_sf
```

The denominator is `LeaseLevelPropertyInputs.rentable_area_sf` (D0
Section 15.1), and because validation makes
`sum(suite_area_sf) == rentable_area_sf` an ERROR when violated, the invariant

```
occupied_area_m + vacant_area_m == rentable_area_sf     (abs = 1e-9)
```

holds in every month, in every projection.

**Areas are summed; ratios are not.** Each suite chain publishes
`expected_occupied_area_sf` (an area, additive) alongside `expected_occupancy`
(a suite-relative ratio, **not** additive — its denominator is
`suite_area_sf`, verified in Section 2.11). D4 sums the areas and divides once.

### 16.2 The annual view

`aggregation.py` already provides both reducers, and D0 Section 4.7's
`AnnualOperatingProjection` already declares both fields with G-M6-compliant
names:

```
physical_occupancy_at_year_end        = snapshot_state_at_year_end(monthly, H)
average_physical_occupancy_over_year  = average_state_over_year(monthly, H)
```

**Recommendation: publish both; the headline / default reported metric is the
annual average.** Average physical occupancy is what an analyst quotes, and a
year-end snapshot alone would hide an eleven-month vacancy that re-let in
December. Publishing both costs one tuple and removes all ambiguity, which is
the point of G-M6's naming rule.

**No ambiguous annual occupancy exists anywhere in the contract**: every
annual state field name begins with `average_` or ends with `_at_year_end`.

### 16.3 This metric calculates nothing

`physical_occupancy` is **descriptive**. It is read by no revenue formula, no
expense formula and no recovery formula. It never becomes a vacancy deduction.
Guardrail **G-D4-3** asserts that no D4 revenue or expense function references
it.

### 16.4 Economic occupancy is not invented

D2 and D3 produce economic responsibility factors (`O_m`, `cash_rent_factor`,
`economic_responsibility_factor`) for fractional boundary months. Those are
**calculation factors**, and D4 consumes their finished dollar results.

They do **not** imply a reported "economic occupancy" KPI. D0 Section 15.3
defines economic vacancy as an available output
(`1 - actual base rent / market-rent potential`) but nothing in the engine
needs it, no D4 formula consumes it, and computing it would require a
property-level market-rent aggregate that `market.py` deliberately refuses to
produce. **Deferred to D5 as a presentation concern**, if wanted at all.

---

## 17. Below-NOI Channel — the Central Architecture Decision

### 17.1 What must flow

| Component | Source | Timing |
|---|---|---|
| Tenant improvements | Suite chains (`expected_tenant_improvements`) | Monthly, aggregated to hold years |
| Leasing commissions | Suite chains (`expected_leasing_commissions`) | Monthly, aggregated to hold years |
| CapEx reserve | `AcquisitionTerms.annual_capex_reserve` | Annual, already flowing |

### 17.2 The recommended contract

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class OperatingCapitalSchedule:
    """Below-NOI, year-varying property capital outflows, Years 1..H.

    Deliberately NOT named for leasing: a future Development Engine needs the
    same channel for construction and lease-up capital, and the shared
    acquisition engine must not become lease-aware (D0 HD-1). The COMPONENTS
    are named for their real cause, because an analyst auditing a cash flow
    must be able to see which dollars were TI and which were LC.

    Absent  =>  the engine behaves exactly as it does today.
    """
    tenant_improvements_by_year: tuple[float, ...]   # length H
    leasing_commissions_by_year: tuple[float, ...]   # length H
```

Resolving D0's **HD-1** option table:

| D0 candidate | Verdict |
|---|---|
| `leasing_costs_by_year` | Rejected — makes the shared engine lease-aware, which HD-1's own guidance warns against |
| `variable_below_noi_costs_by_year` | Rejected — a single opaque number destroys the TI/LC audit split |
| `property_capital_costs_by_year` | Close, but a bare tuple has the same audit problem |
| **A small neutral record with named components** | **RECOMMENDED** — neutral container, honest components, additive for a future producer |

### 17.3 The engine signature change

```python
def analyze_acquisition_from_operating_projection(
    operating_projection: OperatingProjectionLike,
    terms: AcquisitionTerms,
    operating_capital: OperatingCapitalSchedule | None = None,   # NEW, keyword-optional
) -> AcquisitionResults:
```

`None` means "no variable below-NOI capital", which is materialised once as an
all-zeros pair of length `H`. Quick and Detailed pass nothing and are
**bit-identical**, because `x - 0.0 == x` exactly in IEEE-754 for every finite
`x`.

### 17.4 The five wiring points

From Section 2.5, `capex_by_year` is consumed in five places. The new channel
must reach all five, or `levered_cash_flows` and
`cumulative_operating_distributions_by_year` would disagree:

```
UCF_y  (y<H)  = NOI_y - CapEx_y - TI_y - LC_y
UCF_H         = NOI_H - CapEx_H - TI_H - LC_H + exit_value - disposition_costs
LCF_y  (y<H)  = NOI_y - ADS_y - CapEx_y - TI_y - LC_y
LCF_H         = NOI_H - ADS_H - CapEx_H - TI_H - LC_H + net_sale_proceeds
RLCF_y        = NOI_y - CapEx_y - TI_y - LC_y - ADS_y      (HD-D4-3)
RUCF_y        = NOI_y - CapEx_y - TI_y - LC_y              (HD-D4-3)
DSCR_y        = NOI_y / ADS_y                              (UNCHANGED -- Section 22)
debt_yield    = NOI_1 / loan_amount                        (UNCHANGED)
```

`RLCF` and `RUCF` are **HD-D4-3** because including TI/LC changes reported
cash-on-cash and cumulative distributions. See Section 33.

### 17.5 `AcquisitionResults` exposure

Two fields are added, always length `H`, always populated (zeros for Quick and
Detailed), mirroring how `capex_by_year` is already exposed:

```
tenant_improvements_by_year: tuple[float, ...]
leasing_commissions_by_year: tuple[float, ...]
```

Adding fields to `AcquisitionResults` is already precedented four times
(Underwriting V2 Gates 2/3/4, Owner Return Metrics V3 A2) and is additive: no
existing field changes meaning, and `noi_by_year` in particular is never
reduced by either new series.

### 17.6 What must not happen

- TI/LC subtracted from NOI (**FM-D4-15**, **FM-D4-16**).
- TI/LC included in exit NOI (**FM-D4-18**).
- TI/LC folded into `acquisition_costs` or `purchase_price` (**FM-D4-25**).
- TI/LC folded into `capex_by_year`, which must keep reporting the CapEx
  reserve alone (D0 HD-1's explicit requirement).

---

## 18. CapEx Treatment

### 18.1 The two options

| Option | Description | Verdict |
|---|---|---|
| **A** | CapEx stays on `AcquisitionTerms`; TI/LC enter through the additive channel | **RECOMMENDED** |
| **B** | All below-NOI property capital normalised into one shared schedule | Rejected for D4 |

**Why A.** CapEx already works, is already reported as `capex_by_year`, is
already shared by Quick and Detailed, and is a **constant nominal annual
reserve** — a different kind of quantity from an event-driven TI cheque. B
would mean editing the Quick and Detailed paths to construct a schedule they
do not need, during the gate obliged to prove them bit-identical. D0 HD-1 also
requires explicitly that whatever is chosen "must leave `capex_by_year`
reporting the CapEx reserve alone".

### 18.2 Monthly presentation vs annual authority

Lease-Level is monthly canonical, so a reader will reasonably expect a monthly
CapEx line. The rule:

```
The SHARED ACQUISITION ENGINE remains the sole authority for CapEx in every
cash flow. It subtracts terms.annual_capex_reserve once per hold year, from
capex_by_year, exactly as it does today.

Any monthly CapEx figure is PRESENTATION ONLY:
    capex_presentation_m = annual_capex_reserve / 12.0
It is NOT a member of MonthlyPropertyProjection's flow series that feed the
annual adapter, and no annual figure is ever derived from it.
```

**Recommendation: omit the monthly CapEx line from `MonthlyPropertyProjection`
in D4 entirely.** It is not needed by any D4 calculation, and every line that
exists in the canonical projection is a line the annual adapter might one day
be tempted to sum. Adding it in D5 as a display-only field, clearly outside the
adapter's input set, is strictly safer.

This is the **only** defence against **FM-D4-24** (CapEx subtracted twice) that
does not rely on discipline: the double-count cannot occur if the second series
does not exist.

### 18.3 CapEx is not in NOI, ever

D0 Section 18.1 places CapEx below NOI, and `engine/contracts.py` already
documents that "`noi_by_year` is never reduced by `capex_by_year`". Unchanged.

---

## 19. Hold Period, Forward Window, and Sale-Month Chronology

### 19.1 The canonical chronology

```
month 1 ............................ analysis_start_date, hold year 1
month 12H .......................... final hold month, hold year H
                                     >>> SALE OCCURS AT THE END OF THIS MONTH <<<
month 12H+1 .. 12H+12 .............. forward exit window, hold year H+1
                                     is_forward_exit_month == True
```

`build_model_months` produces exactly `12H + 12` entries with these
invariants already asserted (G-M9).

### 19.2 Mapping onto the existing annual sale convention

The existing engine places the sale in the `H`-th annual cash flow:
`LCF_H = NOI_H - ADS_H - CapEx_H + net_sale_proceeds`, and
`remaining_loan_balance` is taken at month `min(12H, io_months + N)`.

Both statements agree that the disposition is at the **end of month 12H**.
D4 therefore creates **no second disposition convention**: it maps months
`12(H-1)+1 .. 12H` into annual cash flow `H`, and everything after month `12H`
is post-sale.

### 19.3 What the forward window is for, and what it is not

| The forward window IS | The forward window IS NOT |
|---|---|
| The source of `exit_noi` | A period the seller owns |
| Live for rollover, lease-up, rent steps, free rent, recoveries, expense growth, management fee | A source of seller cash flow |
| Twelve months, always | A Year `H+1` entry in any `_by_year` series |

`aggregate_flow_to_annual` returns exactly `H` values and
`aggregate_flow_over_forward_exit_window` returns a scalar, so a forward figure
cannot be mistaken for a hold-year one by construction.

### 19.4 The sale-month cutoff must not suppress forward leasing

A common implementation error is to stop the projection at month `12H`, which
would freeze the rent roll at the sale date and make exit NOI reflect a
building that never re-lets. Anchor's projection is `12H + 12` months long by
construction and D2's recursion runs to the projection end (HD-D2-3), so
lease-up and rollover inside the forward window are fully live (HD-D2-5,
"APPROVED — fully live"). Failure mode **FM-D4-27**.

---

## 20. The Annual Operating Adapter

### 20.1 Flow variables — chronological summation

For hold year `y` in `1..H`:

```
annual_X_y = sum of monthly X_m for m in 12(y-1)+1 .. 12y
```

accumulated in strictly ascending period order, through the existing
`aggregate_flow_to_annual`. Applied to every flow line:

```
cash_base_rent_by_year, contractual_base_rent_by_year, free_rent_by_year,
absent_rent_by_year, expense_recoveries_by_year, other_income_by_year,
credit_loss_by_year, effective_gross_income_by_year,
property_taxes_by_year, insurance_by_year, utilities_by_year,
repairs_maintenance_by_year, other_operating_expenses_by_year,
management_fee_by_year, total_operating_expenses_by_year,
noi_by_year,                                    <-- OperatingProjectionLike
tenant_improvements_by_year,                    <-- below NOI
leasing_commissions_by_year                     <-- below NOI
```

**Ascending order is a requirement, not a style note.** It mirrors
`calculate_annual_debt_service`'s explicit refusal of the `12 * PMT` shortcut:
repeated IEEE-754 addition in a fixed order is reproducible, and Anchor asserts
goldens at `abs=1e-9`.

### 20.2 State variables — explicit semantics

```
occupied_area_at_year_end             = snapshot_state_at_year_end(...)
vacant_area_at_year_end               = snapshot_state_at_year_end(...)
physical_occupancy_at_year_end        = snapshot_state_at_year_end(...)
average_physical_occupancy_over_year  = average_state_over_year(...)
```

Every published annual state field name begins with `average_` or ends with
`_at_year_end` (G-M6). **No state metric is ever summed** and no flow metric is
ever averaged; the two reducers are separate functions with separate names for
exactly this reason.

### 20.3 Exit figures

```
exit_noi                    = aggregate_flow_over_forward_exit_window(noi, H)
exit_window_leasing_costs   = aggregate_flow_over_forward_exit_window(TI, H)
                            + aggregate_flow_over_forward_exit_window(LC, H)
going_in_cap_rate           = noi_by_year[0] / purchase_price
```

`exit_window_leasing_costs` is a **disclosed diagnostic, never deducted from
anything** (D0 Section 17.4). It is read by no engine calculation, which
Section 21.3 proves is required.

### 20.4 There is no independent annual model

Every annual figure above is produced by one of the three reducers, each of
which takes a canonical monthly tuple and nothing else. No annual value is ever
computed from a lease input, a growth rate or an annual expense directly
(G-M2, G-M3). **FM-D4-13** is the failure mode; **G-M4** the reconciliation
proof, asserted on real projections at `abs=1e-9`.

---

## 21. Exit NOI and Forward TI/LC

### 21.1 The exact formula

```
exit_noi = sum(noi_m for m in 12H+1 .. 12H+12)
```

taken from the **same canonical monthly projection served to the user**
(G-M12), with rollover, initial-vacancy lease-up, rent steps, free rent,
recoveries, operating-expense growth and the management fee all live in those
twelve months.

Explicitly **not**:

- `noi_by_year[-1] * (1 + g)` — Hold Year `H` grown mechanically (**FM-D4-19**)
- `12 * noi[12H+1]` — hostage to whichever concession falls in that month
- a smoothed or "stabilized" NOI suppressing a real rollover
- contractual rent ignoring free rent

### 21.2 Exit NOI exclusions

Excluded from `exit_noi`: tenant improvements, leasing commissions, CapEx,
debt service, acquisition costs, financing fees, disposition costs. All are
below-NOI or transaction items and none appears in the `noi_m` formula
(Section 5.6).

### 21.3 Forward TI/LC — the load-bearing rule

**Locked.** For any TI or LC event falling in months `12H+1 .. 12H+12`:

```
It MUST NOT be charged as a seller hold-period cash outflow.
    The property was sold at the end of month 12H. The buyer signs that lease
    and writes that cheque.

It MUST NOT reduce exit NOI.
    TI and LC are below NOI in every month of the projection, including the
    forward window. Section 5.6's NOI formula has no TI or LC term at all.

It IS disclosed, as AnnualOperatingProjection.exit_window_leasing_costs,
    read by no engine calculation.
```

**The distinction D4 must hold, stated precisely:**

| A — forward *operating* assumptions | B — forward *below-NOI* events |
|---|---|
| Forward rent, free rent, recoveries, operating expenses, management fee | Forward TI, forward LC |
| **Do** affect `exit_noi`, hence exit value | Affect **nothing** in the engine |
| Live in months `12H+1..12H+12` | Occur in months `12H+1..12H+12` |
| Are what the buyer will earn | Are what the buyer will spend |

The mechanism that enforces it is structural, not procedural: the annual
adapter builds `tenant_improvements_by_year` with `aggregate_flow_to_annual`,
which returns exactly `H` values and physically cannot reach past month `12H`.
The forward months are collected separately by
`aggregate_flow_over_forward_exit_window` into a field the engine never reads.

### 21.4 The disclosed sharp edge

A rollover just after the sale date reduces exit value: at a 6.5% cap rate one
lost month of NOI moves exit value by roughly 15x that month's NOI. This is
real economics — the buyer is buying that rollover — and a
`ROLLOVER_IN_EXIT_WINDOW` WARNING fires so the analyst weighs it against the
exit cap rate rather than being surprised by it.

### 21.5 Exit value seam — unchanged

```
gross_exit_value = exit_noi / exit_cap_rate           (calculate_exit_value)
disposition_costs = gross_exit_value * disposition_cost_pct
net_sale_proceeds = gross_exit_value - disposition_costs - remaining_loan_balance
```

**Lease-Level changes the SOURCE of `exit_noi`, never the capitalization
convention.** `calculate_exit_value` is not modified.

### 21.6 Negative NOI and negative exit value

Lease-Level must permit negative monthly NOI: a fully vacant property still
incurs its fixed operating expenses (Section 25). **NOI is never floored at
zero, at any resolution.**

Inspected behaviour with a negative `exit_noi`:

- `calculate_exit_value` returns a negative value; `ensure_finite` passes it.
- `calculate_disposition_costs` returns a negative number (a credit), which is
  economically meaningless.
- `net_sale_proceeds` becomes strongly negative.
- The IRR solver's `_is_valid_irr_series` will typically reject the series and
  return `None` rather than crash.

**No floor is invented.** The recommendation is a leasing-scoped WARNING,
`NEGATIVE_FORWARD_EXIT_NOI`, raised at D4.4 when
`exit_noi <= 0`, with the engine's existing behaviour unchanged. Recorded as
**HD-D4-7**.

---

## 22. DSCR Treatment

**Confirmed by inspection.** `calculate_dscr_by_year` is
`NOI_y / ADS_y`, with `None` when `ADS_y == 0`. It receives `noi_by_year` and
`annual_debt_service` and nothing else.

**Lease-Level annual DSCR uses annual Lease-Level NOI, before TI, LC and
CapEx.** This is both standard lender practice (a debt-service coverage
covenant is tested on NOI) and the existing engine convention, which already
excludes `capex_by_year` from the numerator.

**The numerator is not reduced by TI or LC.** Doing so would be **FM-D4-26**,
and would make Lease-Level's DSCR incomparable with Quick's and Detailed's.
`year_1_debt_yield = NOI_1 / loan_amount` is likewise unchanged.

Guardrail **G-3** proves this by perturbation: doubling every TI and LC input
must leave every `noi` month, every `noi_by_year` entry, `exit_noi`,
`going_in_cap_rate`, every `dscr_by_year` entry and `year_1_debt_yield`
**bit-identical**, while changing both cash-flow series and both IRRs.

---

## 23. Return Timing

**Inspected: IRR is annual.** `calculate_irr` receives a tuple of `H + 1`
annual cash flows and solves for an annual periodic rate through the frozen
bracket-and-bisection procedure. Equity multiple, cash-on-cash, cash yield and
cumulative distributions are all annual.

**D4 introduces no monthly IRR and no second return-timing convention.**
Lease-Level's monthly economics aggregate into the existing annual cash flows
and the existing solver runs unchanged. Guardrail **G-6** asserts that the IRR
solver receives exactly `H + 1` values and that no module outside
`anchor.leasing` reads a canonical monthly series.

**The limitation, documented rather than hidden:** a Lease-Level deal whose
concessions and TI cheques fall unevenly within a year will show an IRR that
treats them as occurring at year end. That is the same approximation Quick and
Detailed already make, and it is the price of one shared return convention.
Monthly returns are a post-D4 question requiring a decision of their own.

---

## 24. Quick / Detailed / Lease-Level Convergence and Bit Preservation

### 24.1 The convergence architecture

```
Quick      -> NoiForecast                 -\
Detailed   -> OperatingProjection          |--> OperatingProjectionLike
Lease-Level-> AnnualOperatingProjection   -/          |
                                                      v
        analyze_acquisition_from_operating_projection(proj, terms, operating_capital=None)
                                                      |
                                                      v
                                              AcquisitionResults
```

The seam already exists. D4 adds one optional keyword parameter and nothing
else.

### 24.2 Bit preservation

| Mode | Obligation | Mechanism |
|---|---|---|
| Quick | **Bit-identical** for every accepted case | G-2 / G-M10, asserted after every gate and in a fresh subprocess |
| Detailed | **Bit-identical** for every accepted case | Same |

This is why Section 9 rejects extracting a shared expense contract out of
`DetailedOperatingInputs` and why Section 33's HD-D4-1 recommends mirroring the
growth helper rather than refactoring `operating_projection.py`. **No Quick or
Detailed formula is refactored to make Lease-Level architecture look
symmetrical.** The convergence seam is additive; the producers are not touched.

Bit-identity is exact, not approximate: `operating_capital=None` materialises
all-zero tuples, and `x - 0.0 == x` bit-for-bit in IEEE-754 for every finite
`x`, including negative zero handling in the sums involved.

---

## 25. Multi-Suite, Fully Vacant and Partially Vacant Properties

### 25.1 Mixed states must work

D4 must aggregate, in one property, any mixture of:

- occupied suites with known in-place leases
- suites underwritten as `MARKET_LEASE_UP` initial vacancy
- suites underwritten as `HOLD_VACANT`
- Gross, NNN and Modified Gross leases, including branch-specific successor
  types (HD-D3-1/2)

Property NOI reflects the completed D1–D3 outputs. **No suite-level formula is
recreated in D4** — guardrail **G-D4-4** extends `_PROPERTY_FORBIDDEN_NAMES`
from `tests/test_leasing_architecture.py` to the new property operating
aggregator, so it cannot name a lease type, an expense stop, a pro-rata share,
a responsibility factor, a probability or the pool.

### 25.2 Fully vacant property — the case that proves the model

Every suite `HOLD_VACANT`:

```
contractual_base_rent    0
cash_base_rent           0
free_rent                0
expense_recovery         0
occupied_area            0
physical_occupancy       0
other_income             > 0   (property-level, not occupancy-linked)
fixed_operating_expenses > 0   <-- STILL INCURRED
management_fee           = other_income * pct   (a small positive number)
NOI                      < 0
```

**Property operating expenses do not disappear because occupancy is zero.**
A landlord still pays taxes, insurance and utilities on an empty building.
Failure mode **FM-D4-30** exists precisely to catch an implementation that
scales expenses by occupancy.

Worked numbers are golden case 5 (Section 31): monthly NOI `-95,150`.

### 25.3 Partially vacant property — no automatic compensation

With no gross-up (HD-D3-6, deferred), a half-empty building shows:

- lower cash base rent (the vacant suite pays none)
- lower recoveries (the vacant suite reimburses none of the pool)
- **unchanged** fixed operating expenses

The landlord absorbs the vacant share of the pool. **This is the accepted
economic result and D4 does not compensate for it.** Redistributing the vacant
share onto paying tenants is gross-up, which is deferred and requires its own
convention and validation.

---

## 26. Reconciliation Cases

### 26.1 100% NNN reconciliation

For a property that is 100% occupied by NNN leases, with
`recoverable_expense_ratio = 1.0` and `O_L,m = 1` for every lease and month,
pro-rata shares sum to exactly `1.0` (D1's exact area reconciliation), so:

```
Recovery_m = sum_L share_L * P_m = 1.0 * F_m * 1.0 = F_m
```

Therefore:

```
NOI_m = EGI_m - F_m - Fee_m
      = (C_m + F_m + OI_m) - F_m - Fee_m
      = C_m + OI_m - Fee_m
```

i.e. **NOI before the management fee economically equals cash rent plus other
income plus the nonrecoverable expenses, which here are zero.** With
`rho < 1.0` the nonrecoverable remainder `F_m * (1 - rho)` survives as a
landlord cost, which is the general form.

**This is a reconciliation golden, never an implementation shortcut.** The
implementation still computes and reports `Recovery_m` and `F_m` as separate
lines (Section 15).

### 26.2 Gross reconciliation

100% Gross: `Recovery_m = 0` for every lease and every month. All property
operating expenses remain a landlord burden, and NOI is
`C_m + OI_m - F_m - Fee_m`.

### 26.3 Modified Gross reconciliation

For a property whose pool grows across a fixed expense stop, property recovery
begins in exactly the month D3 says it begins, and D4 applies **no threshold
formula of its own**. The pool grows; `recoveries.py` performs the
`max(0, share * P_m - stop)` comparison; D4 sums the result. Golden case 3
places the crossing in Hold Year 4 with an exact hand-computed figure.

---

## 27. Module Boundary and Dependency Graph

### 27.1 The recommended placement

```
src/anchor/leasing/
    expenses.py      NEW (D4.1)  monthly property expense schedule;
                                 recoverable pool construction
    aggregation.py   EXTENDED (D4.2)  suite_operating_projection();
                                 build_property_operating_schedule()
    projection.py    NEW (D4.3/D4.4)  MonthlyPropertyProjection; the EGI/NOI
                                 stack; aggregate_monthly_to_annual();
                                 AnnualOperatingProjection
    contracts.py     EXTENDED  LeaseLevelOperatingInputs and the new results
    validation.py    EXTENDED  operating-input domain rules and warnings
```

This matches D0 Section 3.5's declared layout (`expenses.py`, `projection.py`)
with one refinement: **suite-to-property summation stays in `aggregation.py`**,
because that module already owns exactly this responsibility for D1.3 and D3.5
and already carries the "reprices nothing" guardrail. `projection.py` owns the
statement arithmetic and nothing else.

### 27.2 A or B — where does the property operating projection live?

| Option | Verdict |
|---|---|
| **A** — inside `anchor.leasing`, adapted outward | **RECOMMENDED** |
| **B** — at a separate analysis/integration layer that imports leasing | Rejected |

**Why A.** The property operating projection is built entirely from leasing
outputs plus one leasing input contract. Everything it needs is already inside
`anchor.leasing`, and `AnnualOperatingProjection` satisfies
`OperatingProjectionLike` **structurally** — it does not even need to import
the Protocol. A new integration package would import leasing, re-export leasing
concepts, and add a layer whose only content is a function call.

**The bridge is still made in the required direction.** `anchor.leasing`
produces the projection; `anchor.engine.acquisition` imports `anchor.leasing`
to obtain it. D1–D3's isolation guarantee (nothing imports leasing) is replaced
at D4 by the weaker, still-acyclic guarantee: **only
`anchor.engine.acquisition` imports leasing, and leasing imports no engine
module except `anchor.engine.contracts`.**

### 27.3 The dependency graph

```
                       anchor.contracts
                    (AcquisitionInputs, AcquisitionTerms,
                     DetailedOperatingInputs, OperatingMode)
                              ^          ^
                              |          |
              anchor.engine.contracts    |
        (ensure_finite, OperatingProjectionLike,
         NoiForecast, OperatingProjection, CapitalStack,
         DebtSchedule, AcquisitionResults, ...)
                    ^                     ^
                    |  (permitted)        |
    +---------------+---------+           |
    |                         |           |
anchor.leasing.*        anchor.engine.noi |
    |                   anchor.engine.debt
    |                   anchor.engine.returns
    |                   anchor.engine.operating_projection
    |                         |           |
    |                         v           v
    +----------------> anchor.engine.acquisition        <-- D4: the ONE new edge
                              ^
                              |
              anchor.analysis, anchor.deals, anchor.api, anchor.ai, anchor.cli
```

Inside `anchor.leasing` (all edges downward, no cycles):

```
contracts.py
   ^  ^  ^  ^  ^  ^  ^  ^
   |  |  |  |  |  |  |  |
calendar  rent  market  leasing_costs  validation
             ^     ^         ^
             |     |         |
           rollover ---------+
             ^        ^
             |        |
        recoveries    |
             ^        |
             |        |
  expenses (D4.1)     |
             ^        |
             |        |
       aggregation ---+   (D1.3 + D3.5 + D4.2)
             ^
             |
       projection (D4.3/D4.4)
```

`expenses.py` depends only on `calendar`, `contracts` and
`anchor.engine.contracts`. It does **not** depend on `recoveries.py`, and
`recoveries.py` does not depend on it — the injected-pool seam (HD-D3-8) keeps
them independent, which is what lets the market-leasing engine remain usable
before any expense schedule exists.

### 27.4 Guardrail changes required at D4

`tests/test_leasing_architecture.py` currently asserts that **no** package
imports `anchor.leasing`. At D4.5 that assertion narrows:

```
_FORBIDDEN_LEASING_IMPORTS stays exactly as it is.
_PERMITTED_ANCHOR_IMPORTS stays {anchor.engine.contracts, anchor.contracts}
    (unless HD-D4-1 resolves to option B, which widens it by one name).
test_no_existing_package_imports_anchor_leasing narrows to permit exactly
    src/anchor/engine/acquisition.py, and continues to forbid every other
    file in engine/, analysis/, deals/, ai/, ingestion/ and the top level.
test_importing_anchor_engine_does_not_pull_in_anchor_leasing is REPLACED by
    an assertion that importing anchor.engine.debt / .noi / .returns /
    .operating_projection alone still does not pull in anchor.leasing.
```

The narrowing is itself a deliverable of D4.5 and must be reviewed as such —
loosening an architecture guardrail silently is how the boundary erodes.

---

## 28. Contract Flow

```
LeaseLevelPropertyInputs (analysis_start_date, rentable_area_sf)
  + Suites (with optional initial_vacancy, market_leasing_override)
  + Leases
  + MarketLeasingAssumptions (property defaults)
        |
        |  require_valid_lease_level_inputs()                 [D1.0]
        |  build_model_months()                               [D1.1]
        v
  months : tuple[ModelMonth, ...]
        |
        |  build_property_market_rent_schedules()             [D2.1]
        v
  tuple[MarketRentSchedule, ...]           (one per suite)
        |
        |  per suite: build_recursive_rollover()              [D2.6]
        |          or build_initial_vacancy_rollover()        [D3.6]
        v
  RecursiveRollover | InitialVacancyRollover     (one per suite)


LeaseLevelOperatingInputs                                     [D4.1 NEW]
        |
        |  build_property_expense_schedule(inputs, months=months)
        v
  MonthlyPropertyExpenseSchedule                              [D4.1 NEW]
    property_taxes, insurance, utilities, repairs_maintenance,
    other_operating_expenses, fixed_operating_expenses         (all monthly)
        |
        |  build_recoverable_expense_pool(expenses, recoverable_expense_ratio=rho)
        v
  RecoverableExpensePool                        (EXISTING D3 contract)


  RecursiveRollover|InitialVacancyRollover  +  RecoverableExpensePool
        |
        |  build_recursive_rollover_recovery(pool=...)        [D3.4]
        |  build_initial_vacancy_rollover_recovery(pool=...)  [D3.6]
        v
  RecursiveRolloverRecovery | InitialVacancyRolloverRecovery
        |
        |  suite_recovery_projection()                        [D3.5]
        |  build_property_recovery_schedule()                 [D3.5]
        v
  PropertyRecoverySchedule
    .expense_recovery                            (monthly, FINAL)


  RecursiveRollover | InitialVacancyRollover | LeaseMonthlySchedule
        |
        |  suite_operating_projection()                       [D4.2 NEW]
        v
  SuiteOperatingProjection                                    [D4.2 NEW]
    suite_id, months, contractual_base_rent, cash_base_rent, free_rent,
    absent_rent, tenant_improvements, leasing_commissions, occupied_area
        |
        |  build_property_operating_schedule()                [D4.2 NEW]
        v
  PropertyOperatingSchedule                                   [D4.2 NEW]


  PropertyOperatingSchedule
  + PropertyRecoverySchedule
  + MonthlyPropertyExpenseSchedule
  + LeaseLevelOperatingInputs
        |
        |  build_monthly_property_projection()                [D4.3 NEW]
        v
  MonthlyPropertyProjection                                   [D4.3 NEW]
    (CANONICAL; retained on the envelope; served to the UI at D5)
        |
        |  aggregate_monthly_to_annual(monthly, hold_period=H,
        |                              purchase_price=terms.purchase_price)
        v
  AnnualOperatingProjection                                   [D4.4 NEW]
    noi_by_year, exit_noi, going_in_cap_rate   <-- OperatingProjectionLike
    + line items, state fields, exit_window_leasing_costs
        |
        |  OperatingCapitalSchedule(                          [D4.5 NEW]
        |      tenant_improvements_by_year=annual.tenant_improvements_by_year,
        |      leasing_commissions_by_year=annual.leasing_commissions_by_year)
        v
  analyze_acquisition_from_operating_projection(annual, terms, operating_capital)
        |
        v
  AcquisitionResults
        |
        v
  LeaseLevelAcquisitionResults(                               [D4.5 NEW]
      monthly_projection, annual_projection, results)
```

---

## 29. Proposed Contract Inventory

### 29.1 New contracts, in `anchor/leasing/contracts.py`

| Contract | Gate | Purpose |
|---|---|---|
| `LeaseLevelOperatingInputs` | D4.1 | The eleven property operating assumptions (Section 9.2) |
| `MonthlyPropertyExpenseSchedule` | D4.1 | Five monthly fixed lines + their monthly total |
| `SuiteOperatingProjection` | D4.2 | The single extraction seam onto the property boundary |
| `PropertyOperatingSchedule` | D4.2 | The summed rollover-aware property rent / concession / leasing-cost / area series |
| `MonthlyPropertyProjection` | D4.3 | The canonical monthly statement (D0 Section 4.7) |
| `AnnualOperatingProjection` | D4.4 | The derived annual view; satisfies `OperatingProjectionLike` |
| `LeaseLevelAcquisitionResults` | D4.5 | The result envelope, mirroring `DetailedAcquisitionResults` |

### 29.2 New contract, in `anchor/engine/contracts.py`

| Contract | Gate | Purpose |
|---|---|---|
| `OperatingCapitalSchedule` | D4.5 | The neutral below-NOI channel (Section 17.2) |

### 29.3 The minimum `MonthlyPropertyProjection`

Using **actual current naming** from the shipped D1–D3 contracts, and including
nothing merely for symmetry:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class MonthlyPropertyProjection:
    months: tuple[ModelMonth, ...]                    # 12H + 12

    # --- revenue, above NOI ---
    contractual_base_rent: tuple[float, ...]          # audit
    absent_rent: tuple[float, ...]                    # audit  (Section 5.4)
    free_rent: tuple[float, ...]                      # audit
    cash_base_rent: tuple[float, ...]                 # AUTHORITATIVE
    expense_recovery: tuple[float, ...]               # from D3.5, verbatim
    other_income: tuple[float, ...]
    credit_loss: tuple[float, ...]
    effective_gross_income: tuple[float, ...]

    # --- expenses, above NOI ---
    property_taxes: tuple[float, ...]
    insurance: tuple[float, ...]
    utilities: tuple[float, ...]
    repairs_maintenance: tuple[float, ...]
    other_operating_expenses: tuple[float, ...]
    fixed_operating_expenses: tuple[float, ...]
    management_fee: tuple[float, ...]
    total_operating_expenses: tuple[float, ...]

    noi: tuple[float, ...]

    # --- below NOI ---
    tenant_improvements: tuple[float, ...]
    leasing_commissions: tuple[float, ...]

    # --- state ---
    occupied_area: tuple[float, ...]
    vacant_area: tuple[float, ...]
    physical_occupancy: tuple[float, ...]

    # --- audit ---
    recoverable_expense_pool: tuple[float, ...]

    # --- retained sources, not collapsed ---
    operating_schedule: PropertyOperatingSchedule
    recovery_schedule: PropertyRecoverySchedule
    expense_schedule: MonthlyPropertyExpenseSchedule
```

**Deliberately excluded, with reasons:**

| Field | Why excluded |
|---|---|
| `capex` | Section 18.2 — its existence invites a double-count and no D4 calculation needs it |
| `market_rent_psf` | `market.py` refuses to aggregate a rate across suites; a property figure is an area-weighted **presentation** concern. **HD-D4-4** |
| `rollover_events` | D2.6 already publishes `event_states` / `transitions` per suite, which is the audit surface D0 Section 4.7's `RolloverEvent` sketch anticipated. Duplicating it at property level would create a second event list |
| `economic_occupancy` | Section 16.4 — a calculation factor, not a KPI |
| `gross_potential_rent` | Not a Lease-Level concept; it is a Detailed *input* |

---

## 30. D4 Gate Plan

### 30.1 The recommended sequence

The brief's candidate sequence is sound but bundles the property operating
aggregation gap (Section 2.8) invisibly inside its D4.2. Splitting it makes
every gate smaller, not larger:

| Gate | Content | Files |
|---|---|---|
| **D4.0** | This document. Architecture, financial conventions, HD register, goldens, failure modes | docs only |
| **D4.1** | `LeaseLevelOperatingInputs`; `MonthlyPropertyExpenseSchedule`; monthly fixed-expense build with anniversary growth; `build_recoverable_expense_pool` closing HD-D3-8; leasing-scoped validation | `leasing/contracts.py`, new `leasing/expenses.py`, `leasing/validation.py` |
| **D4.2** | `SuiteOperatingProjection`; `build_property_operating_schedule`; the `absent_rent` identity; area-based occupancy. **The gap D0 did not schedule** | `leasing/contracts.py`, `leasing/aggregation.py` |
| **D4.3** | `MonthlyPropertyProjection`: other income, credit loss, EGI, management fee, NOI. The fixed 8-step order asserted | `leasing/contracts.py`, new `leasing/projection.py` |
| **D4.4** | `AnnualOperatingProjection` derived solely by `aggregate_monthly_to_annual`; `exit_noi`; `exit_window_leasing_costs`; `going_in_cap_rate`. **G-M4, G-M12, G-11** | `leasing/projection.py`, `leasing/contracts.py` |
| **D4.5** | **The one downstream change.** `OperatingCapitalSchedule`; the engine parameter; the five wiring points; `OperatingMode.LEASE_LEVEL`; `analyze_lease_level_acquisition_with_projection`; `LeaseLevelAcquisitionResults`; the guardrail narrowing. **G-2, G-3, G-6, G-12, G-M11** | `engine/contracts.py`, `engine/acquisition.py`, `engine/returns.py`, `contracts.py`, `tests/test_leasing_architecture.py` |
| **D4.6** | Sensitivity and break-even over the same four `AcquisitionTerms` dimensions Detailed uses, via `dataclasses.replace` | `analysis/sensitivity.py`, `analysis/contracts.py` |
| **D4.7** | End-to-end golden with real expenses; three-mode convergence proof; full regression; D4 closeout | tests + docs |

### 30.2 Why this ordering

- **D4.1 before everything** because the pool is an input to D3's recovery
  builders, and every later gate needs a real expense schedule to test against.
- **D4.2 before D4.3** because the statement cannot be assembled from series
  that do not exist yet, and because the `absent_rent` identity (Section 5.4)
  must be proven on its own before EGI depends on it.
- **D4.4 before D4.5** because `exit_noi` must be provably correct before it
  reaches a valuation.
- **D4.5 last among the engine gates** so that exactly one gate carries the
  bit-identity obligation and the guardrail narrowing, and it can be reviewed
  as a unit.
- **D4.6 after D4.5** because sensitivity re-runs the whole pipeline and needs
  it to exist.

### 30.3 Deliberate non-goals for every D4 gate

No gross-up; no per-category recoverability; no recovery abatements; no
stochastic lease-up; no partial-suite leasing; no lease restructuring; no
percentage rent; no retail breakpoints; no expense caps or floors; no calendar
true-ups; no CPI escalations; no monthly return engine; no new debt products;
no refinancing; no balloon enhancements; no variable-rate debt; no
multi-tranche debt. None is made unavoidable by an active requirement.

**No D5 leakage.** D4 designs no UI, no API, no persistence, no OM ingestion,
no AI analyst behaviour and no Excel export. D4 produces deterministic engine
behaviour only.

---

## 31. Golden Case Inventory

### 31.1 The shared base property

Unless a case says otherwise:

```
analysis_start_date  2027-01-01          (case 13 uses 2027-07-01)
rentable_area_sf     100,000
hold_period H        5                   (months 1..60 hold; 61..72 forward)
Suite S1             60,000 SF
Suite S2             40,000 SF
purchase_price       40,000,000

LeaseLevelOperatingInputs
  other_income                  60,000 /yr   -> 5,000 /month in Year 1
  other_income_growth           0.03
  credit_loss_pct               0.00
  property_taxes               600,000 /yr
  insurance                    120,000 /yr
  utilities                    240,000 /yr
  repairs_maintenance          180,000 /yr
  other_operating_expenses      60,000 /yr
  fixed total                1,200,000 /yr   -> 100,000 /month in Year 1
  management_fee_pct            0.03
  expense_growth                0.03
  recoverable_expense_ratio     1.00         (0.90 where a case says so)

Base rent where used: both suites at $30.00 /SF/yr, flat
  S1 60,000 x 30 / 12 = 150,000 /month
  S2 40,000 x 30 / 12 = 100,000 /month
```

Derived Year-1 monthly figures used repeatedly:

```
fixed_operating_expenses_m  = 100,000
recoverable_expense_pool_m  = 100,000   (rho = 1.00)   /  90,000 (rho = 0.90)
Year 2 monthly fixed        = 1,236,000 / 12 = 103,000
Year 3 monthly fixed        = 1,272,080... /12 -> 100,000 * 1.03^2 = 106,090.00
Year 4 monthly fixed        = 100,000 * 1.03^3 = 109,272.70
```

### 31.2 The twenty-five cases

| # | Case | Setup | Expected, exactly |
|---|---|---|---|
| **1** | **Occupied NNN** | Both suites NNN, full hold, `rho = 1.00` | `cash 250,000`; `recovery 100,000`; `OI 5,000`; `EGI 355,000`; `fixed 100,000`; `fee 10,650`; `total opex 110,650`; **`NOI 244,350`** per Year-1 month |
| **2** | **Occupied Gross** | Both suites GROSS, `rho = 1.00` | `recovery 0`; `EGI 255,000`; `fee 7,650`; `total opex 107,650`; **`NOI 147,350`** per Year-1 month. Fixed expenses unchanged at `100,000` |
| **3** | **Modified Gross below then above stop** | S1 MODIFIED_GROSS, `expense_stop_psf = 13.00`, S2 GROSS, `rho = 1.00`. Monthly stop `13 x 60,000 / 12 = 65,000`; `share_S1 = 0.6` | Y1 `0.6 x 100,000 = 60,000 < 65,000` -> **recovery `0`**; Y2 `0.6 x 103,000 = 61,800` -> **`0`**; Y3 `0.6 x 106,090.00 = 63,654.00` -> **`0`**; **Y4 `0.6 x 109,272.70 = 65,563.62` -> recovery `563.62`/month**. Recovery begins exactly in Hold Year 4 |
| **4** | **Partially vacant** | S1 NNN occupied, S2 `HOLD_VACANT`, `rho = 1.00` | `cash 150,000`; `recovery = 0.6 x 100,000 = 60,000`; `occupied_area 60,000`; `physical_occupancy 0.60`; `fixed 100,000` **unchanged**; `EGI 215,000`; `fee 6,450`; **`NOI 108,550`**. The `40,000` unrecovered pool share is the landlord's |
| **5** | **Fully vacant, negative NOI** | Both suites `HOLD_VACANT` | `cash 0`; `recovery 0`; `occupancy 0.0`; `OI 5,000`; `EGI 5,000`; `fixed 100,000`; `fee 150`; `total opex 100,150`; **`NOI -95,150`** per Year-1 month. Not floored |
| **6** | **Initial vacancy MARKET_LEASE_UP** | S2 `MARKET_LEASE_UP`, `initial_lease_up_months = 6`; S1 NNN | Months 1-6: S2 contributes `0` rent, `0` recovery, `0` occupied area; from month 7 its chain economics appear. Property occupancy steps `0.60 -> 1.00` |
| **7** | **Free rent affects cash rent once** | A successor with 3 months free rent, integral downtime | In each abated month `contractual_base_rent = R`, `free_rent = R`, `absent_rent = 0`, `cash_base_rent = 0`, and `EGI` excludes `R` exactly once. Doubling `free_rent_months` must not change `contractual_base_rent` in any month |
| **7b** | **Fractional downtime identity** | D2 Section 7.2 reference case: `D = 2.25`, free rent `2.5`, `R = 100,000` | September: `contractual 100,000`, `free_rent 75,000`, **`absent_rent 25,000`**, `cash_base_rent 0`. Asserts `contractual - absent - free == cash` at `abs=1e-9`, and asserts the D0 18.1 formula would have produced `25,000` (the regression this golden exists to prevent) |
| **8** | **TI below NOI** | Any TI event in a hold month | Doubling `renewal_ti_psf` and `new_ti_psf` leaves every `noi` month, `noi_by_year`, `exit_noi`, `going_in_cap_rate`, `dscr_by_year` and `year_1_debt_yield` **bit-identical**; `unlevered_cash_flows`, `levered_cash_flows` and both IRRs change |
| **9** | **LC below NOI** | Same, for `renewal_lc_pct` / `new_lc_pct` | Same assertions |
| **10** | **Recoveries separate from expenses** | Case 1 | `expense_recovery` and `total_operating_expenses` are both reported at full gross; no field equals a netted difference. Also asserts `(total_opex - fee) * rho == recoverable_expense_pool` (the two pool forms agree) |
| **11** | **100% NNN recovery reconciliation** | Case 1 | `sum of pro-rata shares == 1.0` exactly; `property recovery == recoverable_expense_pool` in every month; `NOI + fee == cash + OI` (`244,350 + 10,650 == 250,000 + 5,000`) |
| **12** | **Management-fee basis** | A constructed month with `cash 100,000`, `recovery 20,000`, `other income 5,000` | `EGI = 125,000`; `management_fee = 0.03 x 125,000 =` **`3,750`**. Asserts the fee basis includes recoveries; the Option-B figure `3,150` must **not** appear |
| **13** | **Non-January analysis start** | `analysis_start_date = 2027-07-01` | Months 1-12 (Jul-2027..Jun-2028) fixed `100,000`/mo; **month 13 (Jul-2028) `103,000`/mo**. Asserts January 2028 is *not* a step month |
| **14** | **Annual expense-growth anniversary + Detailed parity** | Any case | `sum(monthly property_taxes over hold year y) == 600,000 * 1.03^(y-1)` at `abs=1e-9`, i.e. equals Detailed's `property_taxes_by_year[y-1]` for the same inputs |
| **15** | **Market-rent growth separate from property revenue growth** | `market_rent_growth = 0.04`, `other_income_growth = 0.02` | Successor starting rents follow `0.04`; `other_income` follows `0.02`. Changing `other_income_growth` leaves every rent series bit-identical, and vice versa |
| **16** | **Mixed suite structures** | S1 NNN in place; S2 `MARKET_LEASE_UP` whose successor is MODIFIED_GROSS via `new_lease_type`; a third suite Gross | Property NOI equals the sum of the suite chains' finished dollars; no property-level threshold, probability or responsibility factor exists |
| **17** | **Hold-year annual NOI equals the monthly sum** | Any case | `noi_by_year[y-1] == sum(noi[12(y-1)..12y])` at `abs=1e-9` for every `y` (G-M4) |
| **18** | **Annual TI/LC equals the hold-month sum** | TI+LC event in **month 59** (Hold Year 5) | `tenant_improvements_by_year[4]` includes it. Same economics shifted to **month 61**: `tenant_improvements_by_year` is entirely zero and the amount appears only in `exit_window_leasing_costs` |
| **19** | **Forward exit NOI window** | A suite vacant part of the hold, leasing before exit, with free rent, recoveries and expense growth live in months 61-72 | `exit_noi == sum(noi[60:72])` hand-summed; and `exit_noi != noi_by_year[-1] * (1 + any growth rate)` — the two must provably diverge (G-11) |
| **20** | **Forward TI/LC excluded from seller cash flow** | Successor commencing **month 63** with TI `3,000,000` and a positive LC, and positive forward rent | Forward rent/recovery **do** raise `exit_noi`; forward TI/LC appear in **no** `_by_year` series, in **no** `unlevered_cash_flows` or `levered_cash_flows` entry, and reduce `exit_noi` by **nothing**. They appear only in `exit_window_leasing_costs` |
| **21** | **Exit value from forward NOI** | Case 19 | `exit_value == exit_noi / exit_cap_rate` exactly, through the unmodified `calculate_exit_value` |
| **22** | **DSCR uses NOI** | Case 8's perturbation | `dscr_by_year` and `year_1_debt_yield` bit-identical before and after doubling TI/LC, while `levered_cash_flows` change |
| **23** | **Quick unchanged** | The existing Quick golden | Bit-identical after every D4 gate, asserted also in a fresh subprocess (G-2 / G-M10) |
| **24** | **Detailed unchanged** | The existing Detailed golden | Bit-identical after every D4 gate, same mechanism |
| **25** | **Lease-Level annual adapter deterministic** | Any case, built twice from the same inputs, with suites supplied in two different orders | Every field of `AnnualOperatingProjection` **value-equal**, and every monthly series byte-identical. Proves the `fsum` + sorted-suite ordering holds for the operating aggregate as it already does for recoveries |

### 31.3 Additional case for the negative-exit edge

| # | Case | Expected |
|---|---|---|
| **26** | Fully vacant through the forward window (case 5 extended) | `exit_noi < 0`; `exit_value < 0`; `NEGATIVE_FORWARD_EXIT_NOI` WARNING raised; no floor applied anywhere; IRR returns `None` rather than raising |

---

## 32. Failure-Mode Register

| ID | Failure | Detection |
|---|---|---|
| **FM-D4-1** | Physical vacancy applied twice (a vacancy % on top of modeled vacancy) | G-M14: no Lease-Level contract declares `vacancy_credit_loss_pct` or `occupancy`; golden 4 |
| **FM-D4-2** | Free rent deducted twice (once inside `cash_base_rent`, again from it) | Golden 7: `EGI` excludes the abated rent exactly once; identity assertion in golden 7b |
| **FM-D4-3** | Contractual **and** cash base rent both counted in EGI | AST test: the EGI expression references `cash_base_rent` and never `contractual_base_rent` |
| **FM-D4-4** | Recoveries netted against expenses | Golden 10: both lines reported gross; no field equals a netted difference |
| **FM-D4-5** | Recoveries recalculated inside D4 | G-D4-4: the property operating aggregator may not name a lease type, stop, share, factor, probability or the pool |
| **FM-D4-6** | Recoverable pool includes the management fee | Section 12.1's expanded five-line form; golden 10 asserts both pool forms agree |
| **FM-D4-7** | Management-fee / recovery circularity, or an iterative solve | Section 13's proof; G-D4-2 asserts the 8-step call order; a test asserts no root-finding import in any D4 module |
| **FM-D4-8** | Management fee on the wrong revenue basis | Golden 12: `3,750`, not `3,150` |
| **FM-D4-9** | Base rent receives a generic `revenue_growth` on top of lease escalation | `LeaseLevelOperatingInputs` has no `revenue_growth` field; AST test that no leasing module references the name |
| **FM-D4-10** | Market-rent growth used for property other income | Golden 15: the two growth rates are independently perturbable |
| **FM-D4-11** | Expenses compounded monthly instead of annual-step | Golden 14: hold-year sums equal `Line_1 * (1+g)^(y-1)` exactly |
| **FM-D4-12** | Expense growth resets in calendar January | Golden 13: the step is July 2028 for a July 2027 start |
| **FM-D4-13** | An annual NOI computed independently of the monthly series | G-M2 (AST: every `_by_year` flow field produced only by an aggregation function over a monthly tuple); G-M4 |
| **FM-D4-14** | Fixed expenses disappear or scale down during vacancy | Golden 5: `fixed 100,000` at zero occupancy; golden 4: unchanged at 60% |
| **FM-D4-15** | TI included in NOI | G-3 perturbation; golden 8 |
| **FM-D4-16** | LC included in NOI | G-3 perturbation; golden 9 |
| **FM-D4-17** | Forward-window TI/LC charged as a seller cash flow after the sale | Golden 20; structurally impossible because `aggregate_flow_to_annual` returns `H` values |
| **FM-D4-18** | Forward-window TI/LC reduce exit NOI | Golden 20; NOI formula has no TI/LC term |
| **FM-D4-19** | Exit NOI grown mechanically from Hold Year `H` | G-11 / golden 19: `exit_noi` must provably differ from `noi_by_year[-1] * (1+g)` |
| **FM-D4-20** | Exit NOI taken as `12 x` a single forward month | Golden 19 hand-sums all twelve |
| **FM-D4-21** | Exit NOI computed from contractual rent, ignoring free rent | Golden 19 includes free rent inside the forward window |
| **FM-D4-22** | Sale-month cutoff prevents forward lease-up | Golden 19: a suite leases during months 61-72 and raises `exit_noi` |
| **FM-D4-23** | A second disposition convention introduced | No new sale-timing code; `calculate_exit_value` / `calculate_net_sale_proceeds` unmodified |
| **FM-D4-24** | CapEx subtracted twice (monthly presentation summed into the adapter) | Section 18.2: no monthly CapEx series exists in `MonthlyPropertyProjection` |
| **FM-D4-25** | TI/LC omitted from the investment cash flow, or hidden inside acquisition cost | Golden 8/9: both cash-flow series and both IRRs must change under perturbation |
| **FM-D4-26** | DSCR numerator reduced by TI/LC | Golden 22: `dscr_by_year` bit-identical under perturbation |
| **FM-D4-27** | Lease-Level acquires a separate debt engine | G-12: no leasing module imports `anchor.engine.debt`; `annual_debt_service` and `remaining_loan_balance` identical across modes for identical terms |
| **FM-D4-28** | Lease-Level acquires separate returns formulas | G-6: one `analyze_acquisition_from_operating_projection`; a `wraps` delegation proof that the Lease-Level entry point calls it |
| **FM-D4-29** | Quick or Detailed regression | G-2 / G-M10 after every gate, plus a fresh-subprocess run |
| **FM-D4-30** | A `HOLD_VACANT` property incorrectly shows zero operating expenses | Golden 5 |
| **FM-D4-31** | Property occupancy computed by averaging suite occupancy ratios | Golden 1 and 4: areas summed, divided once by `rentable_area_sf`; `occupied + vacant == rentable_area_sf` at `abs=1e-9` in every month |
| **FM-D4-32** | Wrong property expense denominator or ratio (e.g. ratio applied to `total_opex` including the fee) | Golden 10 |
| **FM-D4-33** | Duplicate recovery revenue (a suite counted twice, or in-place plus chain) | D3.5's completeness checking and sorted-suite `fsum`; golden 25 |
| **FM-D4-34** | Initial-vacancy rent omitted from forward NOI | Golden 19: a `MARKET_LEASE_UP` suite leasing before exit raises `exit_noi` |
| **FM-D4-35** | Monthly / annual divergence in any published series | G-M4 asserted on real projections, every flow metric, every year |
| **FM-D4-36** | `absent_rent` computed as a property-level residual, masking a per-suite sign error | D4.2 computes it per suite and sums; a test perturbs one suite and asserts the identity fails loudly if the per-suite value is wrong |

**Count: 36.**

---

## 33. Human Decisions — HD-D4 Register

Decisions already answered by D0/D2/D3 or by shipped code are **not** restated
here as open questions. Seven items remain.

### HD-D4-1 — Where the expense-growth helper lives *(blocks D4.1)*

**Question.** D0 Section 13.1 states a bias toward extracting a shared,
pure expense-growth helper rather than writing a second copy of
`Line_y = Line_1 * (1 + g)^(y-1)`. Inspection shows that extraction is blocked
where D0 assumed it would live. Where does it go?

| | **A — mirror in `anchor/leasing/expenses.py`** | **B — extract `anchor/engine/growth.py`** |
|---|---|---|
| Detailed touched | **No** | Yes — `operating_projection.py` and `noi.py` refactored |
| G-2 obligation | **Trivially satisfied** (nothing changes) | Must be proven for two modes |
| Guardrail change | None | `_PERMITTED_ANCHOR_IMPORTS` widened by one name |
| Duplication | A third copy of a 6-line overflow-safe helper | One copy |
| Precedent | `operating_projection.py` already mirrors `noi.py` deliberately, with a comment saying so | None |

**Recommended: A.** The blocking fact is that `anchor.leasing` may import only
`anchor.contracts` and `anchor.engine.contracts`;
`anchor.engine.operating_projection` is on `_FORBIDDEN_LEASING_IMPORTS`. Option
B therefore requires either putting arithmetic into `engine/contracts.py`
(documented as performing "no calculation of its own") or creating a new engine
module and widening an architecture guardrail — both during the gate obliged to
prove Detailed bit-identical. D0 Section 13.1 names A as its own explicit
fallback.

**Financial reasoning.** The duplication risk is that the two copies diverge.
That risk is retired by **golden 14**, which asserts Lease-Level's hold-year
expense sums equal Detailed's `_by_year` values at `abs=1e-9` for identical
inputs. A test is a stronger guarantee than shared code, because it catches
divergence in the *result* rather than only in the *implementation*.

**Architecture consequence.** `anchor/leasing/expenses.py` carries a private
`_growth_factor` with the same mirror comment `operating_projection.py`
already carries. No file outside `anchor.leasing` is touched at D4.1.

---

### HD-D4-2 — Management-fee basis *(blocks D4.3)* — **CONFIRM ONLY**

**Question.** Does the Lease-Level management fee apply to total EGI including
expense recoveries, or to EGI excluding reimbursements?

**Option A.** `fee = pct * (cash_base_rent + expense_recovery + other_income - credit_loss)`
**Option B.** `fee = pct * (cash_base_rent + other_income - credit_loss)`

**Recommended: A.** Reasoning in Section 14.2. It preserves the existing
Anchor sentence ("percent of EGI") across all modes, it is what D0 Sections
13.2 and 16.4 already lock, it is the conservative (lower-NOI) answer, and B
would require an input Anchor does not have.

**Financial magnitude.** For golden case 1: `10,650` vs `7,650` per month —
`36,000` per year, roughly `554,000` of exit value at a 6.5% cap.

**Architecture consequence.** None under A: the fee is one multiplication
against the already-computed `EGI_m`. Under B, EGI would need a second
"fee-basis EGI" field, which would be a genuinely new concept.

**Why it is listed.** The magnitude is material enough that the reviewer should
confirm the lock rather than inherit it silently.

---

### HD-D4-3 — Do TI and LC enter the Owner Return Metrics recurring series? *(blocks D4.5)*

**Question.** `calculate_recurring_levered_cash_flows` and
`calculate_recurring_unlevered_cash_flows` currently compute
`NOI_y - CapEx_y - ADS_y` and `NOI_y - CapEx_y`. Do TI and LC join CapEx there?

**Option A — yes.** `RLCF_y = NOI_y - CapEx_y - TI_y - LC_y - ADS_y`.
**Option B — no.** Leave the recurring series NOI-and-CapEx only.

**Recommended: A.**

**Financial reasoning.** The recurring series feed Levered Cash-on-Cash Return,
Unlevered Cash Yield and Cumulative Operating Distributions — figures that
purport to answer "what did the owner actually receive this year". TI and LC
are real cash the owner pays out of operations. Under B, a Lease-Level deal
with a `3,000,000` TI cheque in Year 3 would report Year-3 distributions as
though that cheque never left the account. The established Anchor convention
already subtracts below-NOI property capital from these series (`CapEx_y` is
there today), so A is the consistent reading and B would create a second
definition of "recurring".

**Architecture consequence.** Both functions take an additional
`operating_capital_by_year` (or the two component tuples) with an all-zeros
default, so Quick and Detailed remain bit-identical.
`calculate_owner_return_metrics` passes it through. `year_1_debt_yield` is
**not** affected — it is NOI-based by definition.

**Why it blocks.** It changes reported returns for Lease-Level only, and the
metric names ("Cash-on-Cash", "Cumulative Operating Distributions") are
owner-facing.

---

### HD-D4-4 — Property-level `market_rent_psf` on the monthly projection *(blocks D4.3)* — low materiality

**Question.** D0 Section 4.7 lists `market_rent_psf: tuple[float, ...]` as a
state field on `MonthlyPropertyProjection`. `market.py` explicitly refuses to
aggregate a rate across suites, calling any property-level figure "an
area-weighted presentation concern and not a D2.1 output". Does D4 publish one?

**Option A — omit it from D4; publish per-suite `MarketRentSchedule`s on the
envelope and leave any property figure to D5 presentation.**
**Option B — publish an area-weighted property rate:**
`sum(suite_area_sf * market_rent_psf_suite) / rentable_area_sf`.

**Recommended: A.** It is descriptive, no D4 calculation consumes it, and D4's
contract rule is "no fields merely for symmetry". Publishing a blended rate
also risks it being read as a revenue driver, which it is not.

**Financial reasoning.** Zero — the field affects no dollar in the model.

**Architecture consequence.** A narrow amendment to D0 Section 4.7's field
sketch, recorded in the same amendment block as HD-D4-5.

---

### HD-D4-5 — The D0 Section 18.1 EGI-formula correction *(blocks D4.3)*

**Question.** D0 Section 18.1 defines `EGI = contractual_base_rent - free_rent
+ recoveries + other_income - credit_loss`. Section 5.4 proves that expression
is not equal to the cash revenue the shipped leasing engine produces whenever a
successor commences on a fractional downtime boundary, overstating revenue by
`R * frac(D)` in that month. Is the correction approved?

**Option A — approve.** EGI consumes `cash_base_rent` directly; a third
`absent_rent` audit line is published so the statement stays additive; D0
Section 18.1 receives a dated amendment block.
**Option B — reject and keep D0's formula.**

**Recommended: A.**

**Financial reasoning.** B recognises, as collected revenue, rent for a period
in which the space was **vacant**. In the D2 Section 7.2 reference case that is
`25,000` on a `100,000` monthly rent — a 25% overstatement of that month's base
rent, flowing straight into EGI, the management fee, NOI, and (if the month
falls in the forward window) into exit value at roughly 15x. There is no
reading under which it is correct.

**Architecture consequence.** One extra series on
`SuiteOperatingProjection`, `PropertyOperatingSchedule` and
`MonthlyPropertyProjection`; one identity assertion (**G-D4-1**); a dated
amendment block on D0 Sections 18.1 and 4.7. **No lease-level number changes**
— D1–D3 are untouched.

**Why it blocks.** It amends a D0 convention that was approved after human
financial review. The arithmetic is not in doubt; the sign-off is required.

---

### HD-D4-6 — Credit loss in D4 *(blocks D4.3)* — **CONFIRM ONLY**

**Question.** Does Lease-Level D4 carry `credit_loss_pct` now, or defer it?

**Recommended: carry it, exactly as D0 Sections 4.6 / 15.3 / 15.4 lock it** —
optional, default `0.0`, applied to `cash_base_rent + expense_recovery`, never
to other income, with an `UNUSUALLY_HIGH_CREDIT_LOSS` WARNING above 10% and a
UI label reading "Credit Loss", never "Vacancy & Credit Loss".

**Financial reasoning.** Section 7.2. At the default it is economically
neutral, so it is not theoretical completeness; it is the only remaining
revenue-risk lever, and removing it now is more disruptive than keeping it.

**Architecture consequence.** One field, one multiply, one validation warning.
Deferring it would mean amending D0 and revisiting D5's API, schema and UI.

---

### HD-D4-7 — Behaviour when forward exit NOI is negative *(blocks D4.4)*

**Question.** A deliberately vacant or high-expense property can produce
`exit_noi <= 0`, which capitalises to a negative exit value. What should Anchor
do?

**Option A — WARNING, no engine change.** Raise a leasing-scoped
`NEGATIVE_FORWARD_EXIT_NOI` WARNING; `calculate_exit_value` behaves exactly as
today.
**Option B — ERROR.** Refuse to produce results.
**Option C — floor `exit_noi` at zero.**

**Recommended: A.**

**Financial reasoning.** C invents a convention and would silently value a
loss-making building at zero rather than negatively, hiding the very result the
analyst needs to see. B is too strong: a negative forward NOI is a legitimate
intermediate state in a heavy-lease-up scenario, and Anchor's existing
non-finite policy refuses only values that are *undefined*, not values that are
merely bad. A preserves the disclosed sharp edge without inventing a floor —
consistent with how the engine already permits negative NOI, negative cash
flows and `None` IRRs rather than clamping.

**Architecture consequence.** One WARNING code in
`anchor/leasing/validation.py`; no change to `acquisition.py`. Golden 26
documents the observed behaviour, including `IRR -> None`.

---

### 33.1 Which decisions block which gate

| HD | Blocks | Severity |
|---|---|---|
| **HD-D4-1** expense-growth helper | **D4.1** | Decision required |
| **HD-D4-5** EGI-formula correction | **D4.2 / D4.3** | Decision required (amends locked D0) |
| **HD-D4-4** property `market_rent_psf` | **D4.3** | Decision required, low materiality |
| **HD-D4-2** management-fee basis | D4.3 | Confirm only |
| **HD-D4-6** credit loss | D4.3 | Confirm only |
| **HD-D4-7** negative exit NOI | D4.4 | Decision required |
| **HD-D4-3** TI/LC in recurring returns | D4.5 | Decision required |

**D4.1 can begin on HD-D4-1 alone.** D4.2 additionally needs HD-D4-5.

---

## 34. Deferred Items

### 34.1 D3 deferred items carried forward, unchanged

| ID | Item | Status after D4.0 |
|---|---|---|
| **HD-D3-5** | Per-category recoverability | Still `CAN DEFER`. D4 builds one aggregate pool; per-category is additive (the pool becomes a sum of category pools) |
| **HD-D3-6** | Explicit pro-rata share override; gross-up | Still `CAN DEFER`. **No gross-up in D4** — a partially vacant building's unrecovered share stays the landlord's (Section 25.3) |
| **HD-D3-7** | Recovery abatement clauses | Still `CAN DEFER`. Never inferred from free rent |
| **HD-D3-8** | Authoritative pool construction | **RESOLVED at D4.0** as Option A: D3 injects, D4 supplies. Formula in Section 12.1; location in Section 27.1 |

### 34.2 D0 deferred items

| ID | Item | Status |
|---|---|---|
| **HD-1** | Below-NOI variable capital-cost channel | **RESOLVED at D4.0** — `OperatingCapitalSchedule`, Section 17.2. Ratified as **HD-D4-3**'s architecture consequence |
| **HD-8** | Evidence status vs data provenance | Still D5 |

### 34.3 Deferred by this gate

| Item | Reason |
|---|---|
| General vacancy reserve / structural vacancy top-up | D0 Section 15.5. Post-D4, and only ever as `max(0, target - modeled)` |
| Economic occupancy as a reported KPI | Section 16.4 — a calculation factor, not a KPI. D5 presentation if wanted |
| Monthly IRR / monthly return timing | Section 23 — needs its own decision |
| Monthly debt-service view | Only if it requires zero economic change (D0 Section 5.8, G-M11) |
| Extracting a shared property-expense contract from `DetailedOperatingInputs` | Section 9.1 Option B — a pure Detailed refactor on its own merits, post-D4 |
| Expense seasonality, true-ups, accrual schedules | Section 10.5 — changes nothing at annual resolution |
| Percentage rent, retail breakpoints, CPI escalation, expense caps/floors | D0 Section 25.3 |

---

## 35. Implementation Surface Forecast

**Nothing below is edited by D4.0.** Listed so a reviewer sees the whole
surface at once.

### 35.1 New files

| File | Gate | Content |
|---|---|---|
| `src/anchor/leasing/expenses.py` | D4.1 | Monthly fixed-expense build; `build_recoverable_expense_pool`; a mirrored `_growth_factor` (HD-D4-1 A) |
| `src/anchor/leasing/projection.py` | D4.3 / D4.4 | `build_monthly_property_projection`; `aggregate_monthly_to_annual` |
| `tests/test_leasing_d4_1_expenses.py` | D4.1 | |
| `tests/test_leasing_d4_2_property_operating.py` | D4.2 | |
| `tests/test_leasing_d4_3_projection.py` | D4.3 | |
| `tests/test_leasing_d4_4_annual_adapter.py` | D4.4 | |
| `tests/test_leasing_d4_5_engine_integration.py` | D4.5 | |
| `tests/test_leasing_d4_6_sensitivity.py` | D4.6 | |
| `tests/test_leasing_d4_7_closeout.py` | D4.7 | |

### 35.2 Existing files, additive changes only

| File | Gate | Change | Why |
|---|---|---|---|
| `src/anchor/leasing/contracts.py` | D4.1–D4.5 | Seven new dataclasses (Section 29) | Every Lease-Level contract lives here (D0 3.5) |
| `src/anchor/leasing/validation.py` | D4.1, D4.4 | `validate_lease_level_operating_inputs`; `UNUSUALLY_HIGH_CREDIT_LOSS`; `NEGATIVE_FORWARD_EXIT_NOI` | Leasing-scoped severity (HD-6); one validation authority |
| `src/anchor/leasing/aggregation.py` | D4.2 | `suite_operating_projection`, `build_property_operating_schedule` | This module already owns suite-to-property summation (D1.3, D3.5) and already carries the "reprices nothing" guardrail |
| `src/anchor/leasing/__init__.py` | D4.1–D4.4 | New public exports | Public entry points only |
| **`src/anchor/engine/contracts.py`** | **D4.5** | `OperatingCapitalSchedule`; two new `AcquisitionResults` fields | The below-NOI channel must be a shared contract, because both `acquisition.py` and `returns.py` consume it; `AcquisitionResults` must report TI/LC by year or the analyst cannot audit the cash flow. Additive: no existing field changes meaning, and `noi_by_year` is never reduced by either |
| **`src/anchor/engine/acquisition.py`** | **D4.5** | One optional parameter on `analyze_acquisition_from_operating_projection`; TI/LC terms in both cash-flow builders; `analyze_lease_level_acquisition_with_projection`; `LeaseLevelAcquisitionResults` assembly; `import anchor.leasing` | This is **the one downstream change** D0 Appendix A anticipated. It is where the three producers converge, so it is the only place the channel can enter without duplicating the engine |
| **`src/anchor/engine/returns.py`** | **D4.5** | Optional below-NOI terms on `calculate_recurring_levered_cash_flows` and `calculate_recurring_unlevered_cash_flows`; pass-through in `calculate_owner_return_metrics` | **HD-D4-3.** Without this the Owner Return Metrics would report distributions the owner never received. `calculate_dscr_by_year` and `calculate_year_1_debt_yield` are **not** touched — both stay NOI-based (Section 22) |
| `src/anchor/contracts.py` | D4.5 | `OperatingMode.LEASE_LEVEL` | D0 Appendix A |
| `src/anchor/analysis/sensitivity.py` | D4.6 | `LEASE_LEVEL_SUPPORTED_ASSUMPTIONS` + the four scenario builders | Mirrors the Detailed pattern exactly; no new dimension |
| `src/anchor/analysis/contracts.py` | D4.6 | `StandardLeaseLevelSensitivityPresets` | Mirrors `StandardDetailedSensitivityPresets` |
| `tests/test_leasing_architecture.py` | D4.5 | Narrow `test_no_existing_package_imports_anchor_leasing` to permit `engine/acquisition.py`; replace the fresh-subprocess assertion | Section 27.4. Reviewed as a deliverable, never loosened silently |
| `src/anchor/engine/operating_projection.py` | — | **No change** under HD-D4-1 option A | This is what makes G-2 trivially true |

### 35.3 Explicitly out of scope for all of D4

`src/anchor/api.py`, `src/anchor/deals/*`, `src/anchor/ingestion/*`,
`web/src/*`, any new Excel reader, `src/anchor/ai/*`, `CONCEPTS.md`. All D5.

---

## 36. Consistency Audit

| Check | Result |
|---|---|
| Does any recommendation change Quick's formulas? | **No.** |
| Does any recommendation change Detailed's formulas? | **No** (HD-D4-1 option A). |
| Does any recommendation change debt formulas? | **No.** |
| Does any recommendation change exit capitalization? | **No** — only the source of `exit_noi`. |
| Does any recommendation change DSCR or debt yield? | **No.** |
| Does any recommendation create a second returns engine? | **No** — one optional parameter on the existing function. |
| Does any recommendation create a cycle in the module graph? | **No** — Section 27.3. |
| Does any recommendation reopen a locked D0/D2/D3 decision? | **One**: D0 Section 18.1's EGI formula, as HD-D4-5, on proven arithmetic grounds. |
| Does any recommendation defer something D0 required at D4? | **No.** Every D0 D4 obligation is scheduled in Section 30.1. |
| Does D4.0 write production code? | **No.** |
| Is `recoverable_expense_ratio` given a silent default? | **No** — Section 9.3. |
| Is every annual state field name G-M6 compliant? | **Yes** — Section 20.2. |
| Are the D2.6 merge-key premises disturbed? | **No** — D4 adds no successor input; the pool is path-independent (D3 Section 10.2). |

---

## 37. Final Classification

**B — D4.0 HAS BLOCKING HUMAN DECISIONS.**

The architecture is coherent, the financial conventions are complete, the
circularity proof holds, and the gate plan is implementable. Five of the seven
open items have firm recommendations with stated reasoning; two are
confirm-only. **HD-D4-5** is the one that genuinely requires financial sign-off,
because it corrects a formula in a document that was itself approved after
human financial review.

**D4.1 is unblocked the moment HD-D4-1 is answered.**
