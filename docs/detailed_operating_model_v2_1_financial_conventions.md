# Detailed Operating Model V2.1 Financial Conventions Specification

## Status

**Phase 0 — proposed, not yet implemented.** This is a specification-only
document, produced on `docs/detailed-operating-model-v2-1-spec`, branched
from the frozen V2 demo build (`main` @ `a9b10a9`, tagged
`showcase-v2-2026-09-03`). No `AcquisitionInputs`/`AcquisitionResults`
contract change, no engine code, no validation code, no Excel reader change,
no persistence schema change, no frontend change, and no test has been
implemented as part of producing it. It inherits and extends
`docs/financial_conventions.md` (POC V1) and
`docs/underwriting_v2_financial_conventions.md` (Underwriting V2). Where this
document is silent, those documents govern, and nothing in either is revised,
relaxed, or reinterpreted here.

The current demo's financial results are unaffected by this document and must
remain unaffected until an approved implementation phase begins.

## Purpose

Anchor's engine today only knows how to consume a *summarized* operating
assumption: `current_noi` plus `noi_growth`. This is **Quick Underwrite**.
Detailed Operating Model V2.1 introduces a second way to arrive at the same
kind of NOI schedule — **Detailed Underwrite** — by calculating NOI from
underlying property-level revenue and operating-expense assumptions, rather
than requiring the analyst to summarize them by hand into a single NOI figure
and a single growth rate.

Detailed Underwrite is a second **front door** into the existing acquisition
engine, not a second acquisition engine. Both paths must produce the same
shape of authoritative output (`noi_by_year`, `exit_noi`) and feed the exact
same downstream debt/returns/sensitivity/break-even machinery. See
`docs/detailed_operating_model_v2_1_architecture.md` for how that convergence
is structured.

## Current V1/V2 Model (baseline, verified against the live implementation)

Restated from `docs/underwriting_v2_financial_conventions.md` for context.
Fourteen inputs today (`src/anchor/contracts.py`), all of which remain
unchanged:

- `purchase_price`, `current_noi`, `occupancy` (informational only, never
  read by any calculation — `src/anchor/engine/noi.py` docstring: "Occupancy
  is informational only and is never read here"), `noi_growth`,
  `hold_period`, `exit_cap_rate`, `ltv`, `interest_rate`, `amortization`,
  `acquisition_cost_pct`, `financing_fee_pct`, `disposition_cost_pct`,
  `annual_capex_reserve`, `io_period`.
- NOI (`src/anchor/engine/noi.py`): `NOI_1 = current_noi`;
  `NOI_y = current_noi * (1 + noi_growth)^(y-1)` for `y > 1`;
  `exit_noi = current_noi * (1 + noi_growth)^hold_period`, i.e. `NOI_(H+1)`.
- Everything downstream of `noi_by_year`/`exit_noi` (capital stack, debt
  schedule, exit value, cash flows, DSCR, equity multiple, IRR) is unchanged
  by this document; see `docs/underwriting_v2_financial_conventions.md` for
  its full specification.
- `noi_growth` validation domain today (`src/anchor/validation.py`):
  `noi_growth > -1`, **no upper bound**. This is the existing growth
  convention referenced in Section "Growth Rate Validation" below.

Detailed Operating Model V2.1 changes none of the above. It adds a way to
*produce* `noi_by_year`/`exit_noi` from a different, more granular input set,
which is then handed to the unchanged downstream engine exactly as
`current_noi`/`noi_growth` are today.

## V2.1 Detailed Operating Inputs

Twelve new fields. All currency fields are Year 1 dollar amounts; all
percentage fields are canonical decimal fractions (`0.05` = 5%), consistent
with every existing percentage-shaped field in `AcquisitionInputs`.

### Revenue

| Field | Type | Units | Domain | Meaning |
|---|---|---|---|---|
| `gross_potential_rent` | float | $/year | `>= 0` | Year 1 Gross Potential Rent (GPR) |
| `other_income` | float | $/year | `>= 0` | Year 1 Other Income |
| `vacancy_credit_loss_pct` | float | decimal fraction | `0 <= x <= 1` | Vacancy & credit loss, as a percentage of GPR |

### Operating expenses

| Field | Type | Units | Domain | Meaning |
|---|---|---|---|---|
| `property_taxes` | float | $/year | `>= 0` | Year 1 property taxes |
| `insurance` | float | $/year | `>= 0` | Year 1 insurance |
| `utilities` | float | $/year | `>= 0` | Year 1 utilities |
| `repairs_maintenance` | float | $/year | `>= 0` | Year 1 repairs & maintenance |
| `other_operating_expenses` | float | $/year | `>= 0` | Year 1 other operating expenses |
| `management_fee_pct` | float | decimal fraction | `0 <= x <= 1` | Management fee, as a percentage of EGI |

### Growth

| Field | Type | Units | Domain | Meaning |
|---|---|---|---|---|
| `revenue_growth` | float | decimal fraction | `> -1` (see rule below) | Annual growth applied to GPR and Other Income together |
| `expense_growth` | float | decimal fraction | `> -1` (see rule below) | Annual growth applied to the five fixed-dollar expense lines together |

Twelve fields total. This is intentionally a simple property-level operating
model — no lease-level modeling (Section "Explicit V2.1 Exclusions").

### Growth Rate Validation

**Rule: `revenue_growth > -1` and `expense_growth > -1`, with no additional
upper bound — identical in shape to the existing `noi_growth` domain.**

Rationale, from inspecting `src/anchor/validation.py` and
`docs/financial_conventions.md` line 474 ("this includes permitting 100% LTV
and imposing no additional hard upper bound on NOI Growth"): Anchor's
existing convention for a compounding annual growth rate is a hard floor at
`-1` (exclusive) and no ceiling. The floor is not arbitrary — it is the exact
boundary at which `(1 + g)` stops being strictly positive. For a dollar
amount that compounds multiplicatively year over year (`Amount_y =
Amount_1 * (1 + g)^(y-1)`), `g <= -1` is economically nonsensical for two
distinct reasons:

- `g = -1` collapses every subsequent year to exactly `$0` and holds it
  there — a legitimate (if extreme) downside case, but the formula produces
  `0^0 = 1` at `y = 1` and `0` for every `y > 1`, so `g` must stay strictly
  greater than `-1` to keep the Year 1 anchor (`Amount_1`) meaningful and the
  series well-defined by the same formula used for every other year.
- `g < -1` makes `(1 + g)` negative, and a negative base raised to
  successive integer exponents **alternates sign every year** — Year 2
  positive, Year 3 negative, Year 4 positive, etc. A revenue or expense line
  item flipping sign annually has no economic meaning; no real operating
  statement behaves this way.

No upper bound is imposed, mirroring `noi_growth`'s existing convention:
Anchor validates that a rate is economically well-formed, not that it is
"reasonable" in some subjective sense (an analyst is free to stress-test an
aggressive scenario). A downside scenario as severe as `revenue_growth =
-0.30` (occupancy craters 30%/year) or `expense_growth = -0.15` (aggressive
opex reduction plan) remains fully expressible; only the sign-flipping/
formula-breaking region at and below `-1` is excluded.

**This rule is a Phase 0 recommendation, not yet implemented or validated in
code.** It should be added to `_DOMAIN_DESCRIPTIONS`/the `in_domain` mapping
in `src/anchor/validation.py` following the exact pattern already used for
`noi_growth`, when Gate 1 implementation begins
(`docs/detailed_operating_model_v2_1_architecture.md`).

## Timing Convention

Year 1 values are the actual, as-underwritten Year 1 amounts — not a
run-rate, not a stabilized figure. Growth begins between Year 1 and Year 2,
identical in shape to the existing `noi_growth` timing convention
(`docs/financial_conventions.md`: "Year 1 NOI equals Current NOI, and growth
begins in Year 2").

## Revenue Conventions

For operating year `y`, beginning at `y = 1`:

**Gross Potential Rent:**

```
GPR_1 = gross_potential_rent
GPR_y = gross_potential_rent * (1 + revenue_growth)^(y-1)   for y > 1
```

**Other Income:**

```
OtherIncome_1 = other_income
OtherIncome_y = other_income * (1 + revenue_growth)^(y-1)   for y > 1
```

Both rental revenue and other income use the identical `revenue_growth`
assumption in V2.1. No separate other-income growth rate is introduced.

## Vacancy and Credit Loss Convention

```
VacancyCreditLoss_y = GPR_y * vacancy_credit_loss_pct
```

Vacancy and credit loss applies to Gross Potential Rent **only** — it does
**not** reduce Other Income in V2.1. `vacancy_credit_loss_pct` is held
constant across the entire projection; V2.1 does not model changing
occupancy, lease-up, or a separate vacancy vs. credit-loss split.

**Effective Gross Income:**

```
EGI_y = GPR_y - VacancyCreditLoss_y + OtherIncome_y
```

## Operating Expense Conventions

`property_taxes`, `insurance`, `utilities`, `repairs_maintenance`, and
`other_operating_expenses` are Year 1 dollar amounts. Each grows
independently at the *same* `expense_growth` rate — no line-item-specific
growth assumptions in V2.1:

```
ExpenseLine_y = ExpenseLine_1 * (1 + expense_growth)^(y-1)
```

applied identically to each of the five lines.

**Management fee is structurally different** — it scales from Effective
Gross Income rather than being independently grown from a Year 1 dollar
base:

```
ManagementFee_y = EGI_y * management_fee_pct
```

**Total Operating Expenses:**

```
TotalOpex_y = PropertyTaxes_y + Insurance_y + Utilities_y
            + RepairsMaintenance_y + OtherOperatingExpenses_y
            + ManagementFee_y
```

## NOI Convention

```
NOI_y = EGI_y - TotalOpex_y
```

This is the authoritative NOI produced by Detailed Underwrite — the same
economic quantity `current_noi`/`noi_growth` produce for Quick Underwrite,
just derived from more granular inputs.

**NOI remains a property-level operating metric, computed strictly above the
line.** Consistent with the existing, unchanged Underwriting V2 convention
(`src/anchor/engine/contracts.py`: "CapEx is modeled strictly below NOI, in
the cash-flow series only"; `src/anchor/engine/acquisition.py`:
`calculate_capex_by_year`), the following remain below NOI, in the cash-flow
assembly layer, exactly as they are today:

- `annual_capex_reserve`
- debt service
- financing fees
- acquisition costs
- disposition costs

**Detailed Underwrite does not move CapEx into operating expenses, and does
not change the existing DSCR convention** (`DSCR_y = NOI_y / ADS_y`, computed
on NOI before capital reserves — `docs/underwriting_v2_financial_conventions.md`:
"Standard lender covenant practice computes DSCR on NOI before capital
reserves").

## Projection Horizon

The Detailed Operating Model must project through `hold_period + 1`, not
merely `hold_period` — mirroring the existing V1/V2 `exit_noi` convention
exactly (`src/anchor/engine/noi.py`: `calculate_exit_noi` uses exponent
`hold_period`, i.e. `NOI_(H+1)`, while `calculate_noi_by_year` produces only
`NOI_1..NOI_H`).

```
noi_by_year = NOI_1 .. NOI_H          (Years 1 through H — operating NOI during ownership)
exit_noi    = NOI_(H+1)                (Year H+1 — forward NOI used only for exit valuation)
```

The detailed model **must not** approximate `exit_noi` by applying a single
blended growth rate to `NOI_H`. It must run the actual Year `H+1` detailed
projection (GPR, other income, vacancy, each expense line, management fee,
all grown one more year) and take the resulting `NOI_(H+1)` as `exit_noi`.
This is important today (revenue growth and expense growth are equal in the
V2.1 golden case, so the distinction is invisible there) and becomes
load-bearing the moment a future version lets `revenue_growth` and
`expense_growth` diverge — an approximated exit NOI would silently drift from
the true Year H+1 detailed figure at that point.

## Quick vs. Detailed Behavior

**Quick Underwrite is unchanged and must continue to work exactly as it does
today:**

- `current_noi` remains a direct assumption.
- `occupancy` remains informational only, under its existing convention
  (never read by any calculation).
- `noi_growth` remains the NOI projection assumption.

**Detailed Underwrite:**

- `current_noi` is not manually entered — NOI is calculated from the twelve
  detailed inputs.
- `noi_growth` is not manually entered — the revenue/expense schedule
  produces the NOI series directly; there is no single blended growth rate
  in the detailed path (see "Projection Horizon" above on why `exit_noi`
  must not be approximated with one).
- `vacancy_credit_loss_pct` becomes economically active (Quick Underwrite has
  no equivalent field today).
- `occupancy` must not simultaneously drive the economics and create a
  duplicate vacancy mechanism. See "Occupancy and Vacancy — Resolved
  Relationship" below for the exact resolution.

### Occupancy and Vacancy — Resolved Relationship

This is the one relationship Section 11 of the Phase 0 brief required to be
explicitly resolved before implementation.

**Resolution: Detailed Underwrite does not read `occupancy` at all.**
`vacancy_credit_loss_pct` is the sole, authoritative vacancy/credit-loss
mechanism for the Detailed operating projection. `occupancy` keeps its
existing, unchanged meaning and behavior — informational display only, never
read by any calculation (`src/anchor/engine/noi.py`'s existing, frozen
convention) — identically in both Quick and Detailed mode.

This was chosen over three alternatives, each rejected for the reason noted:

1. **Derive `vacancy_credit_loss_pct` from `occupancy`** (e.g.
   `vacancy_credit_loss_pct = 1 - occupancy`) — rejected because it
   conflates a leasing-status metric (physical occupancy) with an
   underwriting allowance that also includes credit loss (bad debt), which
   are not the same thing and are not always numerically equal in real
   underwriting. It would also make `occupancy` silently load-bearing on
   NOI for the first time, contradicting its frozen "informational only"
   status and the docstring guarantee in `engine/noi.py`.
2. **Let both fields independently affect NOI** — explicitly rejected by the
   Phase 0 brief itself ("Do NOT create two active vacancy mechanisms") and
   would make the same economic effect (units not producing rent) doubly
   counted or ambiguously counted depending on field entry order.
3. **Require `occupancy` and `vacancy_credit_loss_pct` to reconcile /
   validate against each other** — rejected as unnecessary cross-field
   coupling for V2.1's scope; it would require Anchor to define an
   authoritative relationship between two concepts (physical occupancy vs.
   underwriting vacancy allowance) that legitimately diverge in real deals
   (e.g. 95% physical occupancy with a 7% underwritten vacancy/credit-loss
   allowance for conservatism), and the brief's own exclusion list rules out
   this class of lease-level reconciliation for V2.1.

`occupancy` therefore remains present on `AcquisitionInputs` (Quick and
Detailed share one input contract per the architecture document), is still
collected/displayed in Detailed mode for informational/underwriting-narrative
purposes, and simply plays no role in the Detailed NOI calculation — same as
today.

## Explicit V2.1 Exclusions

The following are explicitly **not** part of the initial Detailed Operating
Model, per the Phase 0 brief. They belong to future phases:

rent roll, individual tenants, lease expiration schedules, market rent,
mark-to-market, renewal probability, downtime, TI, leasing commissions,
expense recoveries, reimbursement structures, percentage rent, free rent,
lease-level escalations, development/construction, property tax
reassessment mechanics, depreciation, income taxes, waterfalls, preferred
equity, multiple debt tranches, refinancing, variable-rate debt, portfolio
modeling, separate other-income growth, line-item-specific expense growth,
a separate vacancy vs. credit-loss split, and changing/scheduled occupancy.

V2.1 is a property-level operating-model foundation, not a lease-level
model. See `docs/detailed_operating_model_v2_1_architecture.md` "Future
Extensibility" for where the abstraction boundary sits for a later
lease-level evolution.
