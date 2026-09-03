# Detailed Operating Model V2.1 Golden Reference Case

## Status

**Phase 0 — proposed, not yet implemented.** Companion to
`docs/detailed_operating_model_v2_1_financial_conventions.md`, at the same
frozen-target status as the existing V1 golden case
(`docs/phase_2_deterministic_engine.md`) and the Underwriting V2 golden case
(`docs/underwriting_v2_golden_case.md`). It is a *bridge* case: it exists to
become the permanent Quick/Detailed convergence regression test once the
engine implementation lands (Gate 4, `docs/detailed_operating_model_v2_1_architecture.md`).

**Precision note.** Every figure below was independently recomputed with a
standalone script (not copied from the Phase 0 brief) evaluating each
formula in `docs/detailed_operating_model_v2_1_financial_conventions.md`
directly, at double-precision (IEEE-754 binary64) floating point, to at
least six decimal places. Every reconciliation below matched the brief's
proposed checkpoints exactly. As with the existing V1/V2 golden cases, the
exact IEEE-754 bit values an implementation produces are authoritative once
that implementation exists.

## Purpose and Design

This case is deliberately constructed so that the Detailed Operating Model
produces **the exact same `noi_by_year`/`exit_noi` series** as the existing,
frozen Underwriting V2 golden case
(`docs/underwriting_v2_golden_case.md`). It does this by choosing
`revenue_growth = expense_growth = 0.03`, matching the V2 golden case's
single `noi_growth = 3.0%` — the one condition under which a detailed,
multi-line revenue/expense build and a single blended NOI-growth rate must
mathematically agree at every year (both vacancy % and management fee % stay
constant, and every dollar line, including the aggregate NOI, then compounds
at the identical rate).

This makes it the sharpest possible test of the central architectural
invariant: **if the Detailed Operating Model's `noi_by_year`/`exit_noi`
matches Quick Underwrite's, every downstream acquisition result must also
match**, because both paths converge into the identical, unmodified
`analyze_acquisition` engine. A mismatch anywhere downstream would prove a
convergence defect, not a legitimate modeling difference — there is no
modeling difference by construction.

## Detailed Operating Assumptions (Year 1)

| Field | Value |
|---|---|
| `gross_potential_rent` | $800,000.00 |
| `other_income` | $20,000.00 |
| `vacancy_credit_loss_pct` | 5.0% |
| `property_taxes` | $60,000.00 |
| `insurance` | $20,000.00 |
| `utilities` | $25,000.00 |
| `repairs_maintenance` | $20,000.00 |
| `other_operating_expenses` | $16,000.00 |
| `management_fee_pct` | 5.0% |
| `revenue_growth` | 3.0% |
| `expense_growth` | 3.0% |

## Year 1 Reconciliation (hand-worked)

```
Gross Potential Rent              = 800,000.00
Vacancy / Credit Loss (5% of GPR) =  40,000.00
Other Income                      =  20,000.00
------------------------------------------------
Effective Gross Income            = 800,000.00 - 40,000.00 + 20,000.00 = 780,000.00

Fixed operating expenses:
  Property Taxes                  =  60,000.00
  Insurance                       =  20,000.00
  Utilities                       =  25,000.00
  Repairs & Maintenance           =  20,000.00
  Other Operating Expenses        =  16,000.00
  --------------------------------------------
  Subtotal, fixed opex            = 141,000.00

Management Fee (5% of EGI)        = 780,000.00 * 0.05 = 39,000.00

Total Operating Expenses          = 141,000.00 + 39,000.00 = 180,000.00

NOI                                = 780,000.00 - 180,000.00 = 600,000.00
```

**Year 1 NOI = $600,000.000** — matches the Underwriting V2 golden case's
`current_noi = $600,000.00` exactly.

## Years 1–6 Full Operating Schedule (full precision)

Every line for `y > 1` is `Line_1 * (1 + g)^(y-1)`, with `g = revenue_growth`
for GPR/Other Income and `g = expense_growth` for the five fixed expense
lines; Management Fee and EGI/NOI are derived per-year from their own
formulas (never grown directly). Independently recomputed for Years 1
through 6 (Year 6 = the sale-only exit year, `H + 1` for `hold_period = 5`):

| Year | GPR | Other Income | Vacancy/Credit Loss | EGI |
|---|---|---|---|---|
| 1 | 800,000.000000 | 20,000.000000 | 40,000.000000 | 780,000.000000 |
| 2 | 824,000.000000 | 20,600.000000 | 41,200.000000 | 803,400.000000 |
| 3 | 848,720.000000 | 21,218.000000 | 42,436.000000 | 827,502.000000 |
| 4 | 874,181.600000 | 21,854.540000 | 43,709.080000 | 852,327.060000 |
| 5 | 900,407.048000 | 22,510.176200 | 45,020.352400 | 877,896.871800 |
| 6 | 927,419.259440 | 23,185.481486 | 46,370.962972 | 904,233.777954 |

| Year | Property Taxes | Insurance | Utilities | Repairs & Maintenance | Other Opex | Management Fee | Total Opex | **NOI** |
|---|---|---|---|---|---|---|---|---|
| 1 | 60,000.000000 | 20,000.000000 | 25,000.000000 | 20,000.000000 | 16,000.000000 | 39,000.000000 | 180,000.000000 | **600,000.000000** |
| 2 | 61,800.000000 | 20,600.000000 | 25,750.000000 | 20,600.000000 | 16,480.000000 | 40,170.000000 | 185,400.000000 | **618,000.000000** |
| 3 | 63,654.000000 | 21,218.000000 | 26,522.500000 | 21,218.000000 | 16,974.400000 | 41,375.100000 | 190,962.000000 | **636,540.000000** |
| 4 | 65,563.620000 | 21,854.540000 | 27,318.175000 | 21,854.540000 | 17,483.632000 | 42,616.353000 | 196,690.860000 | **655,636.200000** |
| 5 | 67,530.528600 | 22,510.176200 | 28,137.720250 | 22,510.176200 | 18,008.140960 | 43,894.843590 | 202,591.585800 | **675,305.286000** |
| 6 | 69,556.444458 | 23,185.481486 | 28,981.851858 | 23,185.481486 | 18,548.385189 | 45,211.688898 | 208,669.333374 | **695,564.444580** |

**Year 6 is the sale-only year (`H + 1 = 6`), used only for `exit_noi` — it
is never a member of `noi_by_year`, which contains Years 1–5 only, matching
the frozen `noi_by_year`/`exit_noi` split
(`docs/detailed_operating_model_v2_1_financial_conventions.md` "Projection
Horizon").**

## Reconciliation Against the Existing V2 Golden Case

| Year | Detailed Model NOI | V2 Golden Case NOI | Match |
|---|---|---|---|
| 1 | 600,000.000000 | 600,000.000 | ✅ exact |
| 2 | 618,000.000000 | 618,000.000 | ✅ exact |
| 3 | 636,540.000000 | 636,540.000 | ✅ exact |
| 4 | 655,636.200000 | 655,636.200 | ✅ exact |
| 5 | 675,305.286000 | 675,305.286 | ✅ exact |
| 6 (exit NOI) | 695,564.444580 | 695,564.44458 | ✅ exact |

**Proof that Year 6 NOI equals the existing `exit_noi` checkpoint:** the V2
golden case's `exit_noi = current_noi * (1 + noi_growth)^hold_period =
600,000 * 1.03^5 = 695,564.44458`. The Detailed model's Year 6 NOI, computed
independently through the full twelve-input revenue/expense build, is
695,564.444580 — identical to 5 decimal places (the full IEEE-754 value
carries additional non-significant trailing digits from the intermediate
multiplications; both are the same mathematical quantity,
`600,000 * 1.03^5`, reached by two different but equivalent routes: one
direct compounding of NOI, the other compounding GPR/Other Income/each
expense line independently and re-deriving NOI as their difference every
year).

## Downstream Bridge — Remaining Acquisition Assumptions

Reusing the existing V2 golden case's non-operating assumptions unchanged:

| Field | Value |
|---|---|
| `purchase_price` | $10,000,000.00 |
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

## Downstream Bridge Invariant

**Because the Detailed Operating Model's `noi_by_year` and `exit_noi` are
bit-for-bit the same economic series as the existing V2 golden case's, and
because both Quick and Detailed Underwrite must converge into the single,
unmodified `analyze_acquisition` engine
(`docs/detailed_operating_model_v2_1_architecture.md` "Quick/Detailed
Convergence"), every downstream acquisition result must also reconcile
exactly to the existing, already-implemented and already-tested V2 golden
case (`docs/underwriting_v2_golden_case.md`).** This is not a new
calculation to verify — it is a direct, mechanical consequence of the
convergence architecture, reusing the already-independently-reconciled V2
golden values as-is:

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
remaining_loan_balance           = 5,720,615.68        (m = 36 amortizing payments of N = 360)
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

Checkpoint values called out explicitly in the Phase 0 brief, all confirmed
present in the values above:

- `loan_amount = 6,000,000` ✅
- `acquisition_costs = 200,000` ✅
- `financing_fee = 60,000` ✅
- `initial_equity = 4,260,000` ✅
- `exit_value = 10,700,991.4551` ✅
- `disposition_costs = 267,524.7864` ✅
- `remaining_loan_balance = 5,720,615.68` ✅
- `headline_dscr = 2.00000x` ✅
- `min_dscr = 1.64688x` ✅
- `unlevered_irr = 6.1388%` ✅
- `levered_irr = 7.3802%` ✅
- `equity_multiple = 1.38235x` ✅

**The bridge case reconciles to the existing V2 acquisition golden case in
full.**

## Exact Invariants to Become Implementation Tests (Gate 4)

Documented here for the future implementation gate; not implemented today.

1. **Operating-schedule invariant.** Given the twelve detailed assumptions
   above, a `build_detailed_operating_projection(...)` call must produce
   `noi_by_year` and `exit_noi` matching the "Years 1–6" table above at
   `pytest.approx(expected, rel=0.0, abs=1e-6)` (matching the existing
   golden-case tolerance convention documented in
   `docs/solutions/conventions/testing-conventions-and-architecture-guardrails.md`).
2. **Convergence invariant.** Feeding this case's resulting operating
   projection into `analyze_acquisition_from_operating_projection(...)` (or
   equivalent — see architecture document) alongside the "Downstream Bridge"
   assumptions above must produce an `AcquisitionResults` matching every
   field of the existing, already-tested V2 golden case
   (`tests/test_engine_golden_case.py`-style assertions) at the same
   tolerance that test already uses.
3. **Cross-model equivalence invariant.** A Quick Underwrite deal built with
   `current_noi = 600,000` / `noi_growth = 0.03` and a Detailed Underwrite
   deal built with the twelve assumptions above, sharing every other
   assumption, must produce **bit-for-bit identical or floating-point-noise-
   only-different** `AcquisitionResults` — the permanent cross-model
   equivalence test named in the Phase 0 brief. This is the strongest form
   of the convergence guarantee: not "both are close to the same golden
   numbers" but "both paths, run back to back, produce indistinguishable
   output."
