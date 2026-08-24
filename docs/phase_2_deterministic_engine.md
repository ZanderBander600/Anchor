# Mini-Anchor POC V1 Phase 2: Deterministic Acquisition Engine

## Purpose and Authority

This document is the authoritative Phase 2 specification for the deterministic acquisition engine that converts one validated `AcquisitionInputs` object into one `AcquisitionResults` object. It inherits every financial rule frozen in `docs/financial_conventions.md` (Phase 0) and every ingestion rule frozen in `docs/phase_1_excel_ingestion.md` (Phase 1). It does not revise, relax, or reinterpret either document.

`docs/financial_conventions.md` remains the authoritative source for all financial rules. Where this document restates a Phase 0 formula, the restatement is for implementation convenience only; the prose in `docs/financial_conventions.md` governs in the event of any discrepancy.

Phase 2 is a calculation boundary only. It consumes `AcquisitionInputs` and produces `AcquisitionResults`. It performs no ingestion, no Excel access, no AI interpretation, and no presentation formatting.

This is a specification-only task. No Python source, test, Excel, or dependency file is created or modified as part of producing this document.

## Phase 2 Objective

Define the deterministic financial engine that converts:

```text
AcquisitionInputs -> AcquisitionResults
```

The engine must be:

- deterministic — the same `AcquisitionInputs` value always produces the same `AcquisitionResults` value;
- testable — every stage (NOI, debt, exit, cash flows, returns) is independently verifiable;
- auditable — every output is traceable to a frozen Phase 0 formula, with no hidden AI or heuristic step;
- independent of Excel — no `openpyxl` import anywhere in the engine package;
- independent of AI — no model call, prompt, or AI-derived value anywhere in the engine package; and
- independent of UI/API frameworks — no web framework, CLI framework, or presentation formatting in the engine package.

## Input Contract

The engine consumes the existing, unmodified `AcquisitionInputs` (defined in `src/mini_anchor/contracts.py` and frozen by `docs/phase_1_excel_ingestion.md`):

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionInputs:
    purchase_price: float
    current_noi: float
    occupancy: float
    noi_growth: float
    hold_period: int
    exit_cap_rate: float
    ltv: float
    interest_rate: float
    amortization: int
```

Phase 2 does not modify `AcquisitionInputs`. The engine assumes it is only ever given an `AcquisitionInputs` instance that already satisfies the Phase 0 input domains, because construction of `AcquisitionInputs` outside the engine (via `validate_acquisition_inputs` or the Excel reader) already enforces those domains. The engine does not re-validate domains; it is not a second validation boundary.

Occupancy (`occupancy`) remains informational only in POC V1. It is carried through unread by every Phase 2 calculation. Current NOI (`current_noi`) already reflects vacancy and must never be multiplied by Occupancy at any point in the engine.

## Phase 2 Output Contract

Define an immutable standard-library dataclass:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionResults:
    going_in_cap_rate: float
    loan_amount: float
    initial_equity: float
    monthly_debt_service: float
    annual_debt_service: tuple[float, ...]
    remaining_loan_balance: float
    noi_by_year: tuple[float, ...]
    exit_noi: float
    exit_value: float
    net_sale_proceeds: float
    unlevered_cash_flows: tuple[float, ...]
    levered_cash_flows: tuple[float, ...]
    unlevered_irr: float | None
    levered_irr: float | None
    equity_multiple: float | None
    dscr_by_year: tuple[float | None, ...]
    headline_dscr: float | None
```

Every field is a plain built-in `float`, `float | None`, or an immutable `tuple` of those types. No field is a list, dict, custom object, or mutable container. No field carries a narrative string, a recommendation, a confidence score, a sensitivity table, a scenario label, provenance metadata, or UI formatting.

### Deviations from the minimum field list, and why

The task instructions list a minimum output set that includes `annual_debt_service` (singular name) and `remaining_loan_balance` (singular name) without indicating whether each is a scalar or a per-year series. Both names are ambiguous as written, because Phase 0 defines `ADS_y` as a per-year quantity (`ADS_y = 0` once `y > A`, so it is not constant across years whenever `A < H`), while `B_exit` is a single point-in-time quantity (the balance at the moment of sale). This ambiguity is Phase 2 task-prompt ambiguity, not Phase 0 ambiguity, and is resolved explicitly below rather than silently:

- **`annual_debt_service` is a `tuple[float, ...]` of length `H`, indexed by hold year `1..H`.** A single scalar cannot represent `ADS_y` correctly whenever `A != H`, because `ADS_y` is `12 * PMT` for `1 <= y <= min(H, A)` and `0` for `y > A`. Exposing the full per-year series is required for `dscr_by_year` and for the per-year levered cash flows to be independently auditable from `AcquisitionResults` alone, without recomputing debt internals. This mirrors the already-mandated `dscr_by_year` field.
- **`remaining_loan_balance` is a single `float`: the balance immediately after the last scheduled monthly payment through the sale date (`B_exit` in Phase 0 terms).** It is not a full month-by-month schedule. The task's minimum field list uses the singular form, and Phase 0's cash-flow formulas (`LCF_H`, `Net Sale Proceeds`) only ever require the single exit-date balance. The full monthly amortization schedule is an internal computation detail of `engine/debt.py`, independently unit-testable at the module level; it is not part of the audited result contract, because no downstream Phase 2 or Phase 3 consumer needs it and adding it would be an unjustified extra field under the task's own instruction to explain any addition first.

One additional field beyond the task's minimum list is proposed:

- **`noi_by_year: tuple[float, ...]` of length `H`, indexed by hold year `1..H`.** The task's minimum list includes `exit_noi` (the single forward NOI used only for sale) but no field exposing the in-hold NOI series itself, even though every unlevered and levered cash flow depends on it. Without `noi_by_year`, an auditor cannot verify the NOI forecast component of `unlevered_cash_flows` / `levered_cash_flows` without re-deriving `NOI_y` from `current_noi` and `noi_growth` by hand. Exposing it costs nothing (it is already computed and immutable) and directly serves the "auditable" objective stated for Phase 2. It introduces no new assumption and states no opinion; it is a plain restatement of an already-computed Phase 0 quantity.

No other field is added. In particular, no monthly-level schedule, no sensitivity output, and no duplicate/derived convenience field (e.g., a separately stored `total_debt_service` sum) is introduced.

## Phase 2A — NOI Forecast

This section restates `docs/financial_conventions.md` "NOI forecast and going-in cap rate" and "Loan and debt service" (capital-stack portion) exactly; Phase 0 governs on any conflict.

### NOI series

For hold year `y`, `1 <= y <= H`:

```text
NOI_1 = Current NOI
NOI_y = Current NOI * (1 + NOI Growth)^(y - 1)          for y >= 2
```

`noi_by_year[y - 1]` holds `NOI_y` for `y` in `1..H`. NOI Growth begins in Year 2; Year 1 is always exactly `current_noi`, unmodified. Occupancy is never multiplied into any `NOI_y`.

### Exit NOI (forward NOI used only for sale)

```text
Exit NOI = NOI_(H+1) = Current NOI * (1 + NOI Growth)^H = NOI_H * (1 + NOI Growth)
```

`exit_noi` holds this value. It is used only inside the Exit Value formula (Phase 2C); it is never an operating cash flow and never appears as an entry in `noi_by_year`, `unlevered_cash_flows`, or `levered_cash_flows`.

### Going-in cap rate

```text
going_in_cap_rate = current_noi / purchase_price
```

This is a deterministic, engine-calculated informational metric. It does not drive any other Phase 2 calculation.

### Boundary behavior

| Input condition | NOI series behavior |
| --- | --- |
| `Current NOI = 0` | Every `NOI_y = 0` and `Exit NOI = 0` regardless of `NOI Growth`, because every term is `0 * (1 + g)^k = 0`. `going_in_cap_rate = 0 / P = 0.0` (finite; `purchase_price > 0` is already guaranteed by the input domain, so this is never a division by zero). `exit_value = 0 / c_exit = 0.0`. |
| `NOI Growth = 0` | `NOI_y = Current NOI` for every `y`, and `Exit NOI = Current NOI`. The NOI series is flat. |
| `NOI Growth` negative, `> -1` | `(1 + g)` is a positive fraction less than `1`, so `NOI_y` decays geometrically toward (but never reaches) `0` as `y` grows, and `Exit NOI < NOI_H`. All values remain finite and positive for any finite `H`. |
| `NOI Growth` large positive | `NOI_y` grows geometrically. For sufficiently large `g` and `H` this can overflow IEEE-754 double precision to `inf`. Per the non-finite rule below, an overflowed `NOI_y` or `Exit NOI` must cause the engine to fail explicitly rather than propagate `inf` into `AcquisitionResults`. |
| `Hold Period = 1` | `noi_by_year = (NOI_1,)`, i.e. a single element equal to `current_noi`. `Exit NOI = Current NOI * (1 + g)^1`. `unlevered_cash_flows` and `levered_cash_flows` each have exactly two entries, `[UCF_0, UCF_1]` / `[LCF_0, LCF_1]`, and the single hold-year entry is simultaneously the first and the final year (it includes the sale proceeds). |

### Non-finite intermediate values (Phase 2 implementation safety rule)

`docs/financial_conventions.md` does not resolve what happens when an intermediate or output value becomes non-finite through ordinary floating-point evaluation (for example, extreme NOI Growth compounded over a long hold overflowing to `inf`, or a pathological input combination producing `NaN`). This is flagged here as a genuine Phase 0 gap, not silently resolved by changing Phase 0 economics. The following rule is proposed and adopted for Phase 2 only, as an implementation safety rule:

> If any required financial intermediate or output value becomes `NaN`, positive infinity, or negative infinity at any point during deterministic engine calculation — outside of the fields that already have a frozen `None` ("N/A") convention (`unlevered_irr`, `levered_irr`, each entry of `dscr_by_year`, `headline_dscr`, `equity_multiple`) — the engine must fail explicitly (raise an exception) rather than construct a partially non-finite `AcquisitionResults`.

This rule does not change any financial economics; it only prevents an `AcquisitionResults` instance from silently carrying an `inf` or `NaN` value in a field where Phase 0 defines no `None`/"N/A" fallback (e.g., `going_in_cap_rate`, `loan_amount`, `noi_by_year`, `exit_value`, `unlevered_cash_flows`). It does not apply to `unlevered_irr`, `levered_irr`, DSCR entries, or `equity_multiple`, because Phase 0 already specifies exactly how non-finite intermediate values are handled for those four output categories (they resolve to `None`, per their own frozen rules, not to an engine-level failure). No clamping, rounding, or substitution is introduced by this rule; it only converts an otherwise-silent non-finite value into an explicit failure.

Recommended implementation: a dedicated exception, e.g. `NonFiniteResultError(ValueError)` defined in `engine/contracts.py`, raised at the point a non-finite value is first detected, analogous in spirit to Phase 1's `InputValidationError` but reporting a single deterministic-computation failure rather than a collected list of input issues (there is nothing to collect against, since Phase 2 does not re-validate `AcquisitionInputs`).

## Phase 2B — Acquisition / Debt

This section restates the Phase 0 "Loan and debt service" formulas exactly.

### Capital stack

```text
loan_amount    = purchase_price * ltv
initial_equity = purchase_price - loan_amount
```

Acquisition costs are `0` (Phase 0 exclusion; no field or term represents them).

### Loan structure

```text
r = interest_rate / 12
N = amortization * 12
```

For nonzero `r`:

```text
PMT = loan_amount * r / (1 - (1 + r)^(-N))
```

For `r = 0`:

```text
PMT = loan_amount / N
```

`monthly_debt_service` holds `PMT`. It is a single scalar because POC V1 has one fixed-rate, fully amortizing debt tranche with one constant scheduled payment amount for every month `1 <= t <= N` (Phase 0: "Debt is fixed-rate and fully amortizing"). Payment timing:

```text
Monthly Payment_t = PMT    for 1 <= t <= N
Monthly Payment_t = 0      for t > N
```

### LTV = 0 special case

Per Phase 0, `LTV` may be exactly `0`. When `ltv = 0`:

```text
loan_amount = 0.0
```

Substituting `loan_amount = 0` into the `PMT` formula (whether `r = 0` or `r != 0`) always yields `PMT = 0.0`, because the numerator `loan_amount * r` (or `loan_amount / N`) is `0`. Consequently every `annual_debt_service[y-1] = 0.0`, every remaining balance is `0.0` at every month (starting from a beginning balance of `0.0`, `Interest_t = 0 * r = 0`, `Principal_t = 0 - 0 = 0`, `Ending Balance_t = 0`), and `remaining_loan_balance = 0.0`. `initial_equity = purchase_price - 0 = purchase_price`. No special-cased branch is required in the implementation beyond what the formulas already produce; this table documents the resulting behavior so an implementer can write a golden-value test without deriving it independently.

### Annual debt service

```text
ADS_y = sum of Monthly Payment_t for t = 12(y - 1) + 1 through 12y,   1 <= y <= H
```

`annual_debt_service[y - 1]` holds `ADS_y`. Because `N = 12 * A` is always a whole number of months (Phase 0 domain: `A >= 1` integer):

- for `1 <= y <= min(H, A)`: every one of the 12 month-positions in year `y` satisfies `t <= N`, so `ADS_y = 12 * PMT` exactly;
- for `y > A` (only reachable when `H > A`): every month-position in year `y` satisfies `t > N`, so `ADS_y = 0.0` exactly.

There is no partial-year case in POC V1 because `A` and `H` are both whole numbers of years, so a hold year is either entirely within the amortization period or entirely after it; the "partial debt service in the amortization-ending year" case referenced by the task's phrasing does not arise from a partial *year*, but is fully captured by the boundary at `y = A` versus `y = A + 1` above (year `A` itself is still fully serviced; year `A + 1` is the first fully zero year). This is not a new assumption — it follows directly from `A`, `H`, and every hold-year boundary being whole numbers under the frozen Phase 0 domains.

The three orderings `A < H`, `A = H`, and `A > H` are all supported by the same formula with no branching beyond the `min(H, A)` comparison above:

- `A < H`: `annual_debt_service` is nonzero for years `1..A` and `0.0` for years `A+1..H`; `remaining_loan_balance = 0.0` (the loan is fully amortized before sale).
- `A = H`: `annual_debt_service` is nonzero for every modeled year; `remaining_loan_balance = 0.0` (sale occurs exactly at contractual maturity).
- `A > H`: `annual_debt_service` is nonzero for every modeled year; `remaining_loan_balance` is strictly positive (the loan is not yet fully amortized at sale).

## Remaining Loan Balance

Per Phase 0, the exact closed-form definition is:

```text
B_m = L * (1 + r)^m - PMT * ((1 + r)^m - 1) / r          (r != 0)
B_m = L - m * PMT                                          (r = 0)
```

For Phase 2 implementation, the specified computation path is the mathematically equivalent month-by-month recurrence, evaluated iteratively rather than via the closed form:

```text
Beginning Balance_1 = loan_amount

for each scheduled payment month t = 1 .. min(H * 12, N):
    Interest_t         = Beginning Balance_t * r
    Principal_t         = Payment_t - Interest_t
    Ending Balance_t   = Beginning Balance_t - Principal_t
    Beginning Balance_(t+1) = Ending Balance_t
```

For `r = 0`, `Interest_t = 0` for every `t`, so `Principal_t = Payment_t = PMT` and the recurrence reduces to `Ending Balance_t = Beginning Balance_t - PMT`, consistent with the closed form `B_m = L - m * PMT`.

`remaining_loan_balance = B_exit`, the ending balance after month `min(H * 12, N)`:

```text
B_exit = B_min(12H, N)
```

**Why the recurrence, not the closed form, is the specified implementation path.** Both formulas are mathematically identical for exact real-number arithmetic, and either is an acceptable *definition*. But `(1 + r)^m` evaluated via `pow()` versus an iterative accumulation of 360 (or more) individual `Beginning - Principal` subtractions can differ in the last few bits of IEEE-754 double precision, depending on implementation choices (e.g., library `pow` vs. repeated multiplication, or evaluation order of the closed-form fraction). Two independent implementations that both correctly follow "the closed form" are not guaranteed to be bit-identical. Two independent implementations that both follow the recurrence exactly as written above — same operation order, same per-month state update — are guaranteed to be bit-identical for the same inputs, because IEEE-754 arithmetic is deterministic given a fixed sequence of operations. The recurrence is therefore adopted as the single authoritative Phase 2 computation path for `remaining_loan_balance` and for `annual_debt_service`'s underlying per-month payments, in order to satisfy the "deterministic" and "two implementations do not diverge" requirements. The closed form remains a useful independent check in tests (e.g., asserting the recurrence result is within an explicit numerical tolerance of the closed-form result) but is not itself the implementation.

### Tiny residual balance at contractual maturity

Ordinary floating-point evaluation of the recurrence above at `m = N` (full contractual maturity) does not always land on exactly `0.0`; it can be a tiny positive or tiny negative value purely from floating-point rounding (observed magnitude in the golden case below: approximately `3.4e-7` against a `~32.5 million` starting balance, roughly 1 part in `10^14`). Phase 0 states "the fully amortized balance after payment `N` is zero" as an exact mathematical fact of how `PMT` is derived (an infinite-precision evaluation of the recurrence always reaches exactly `0` at `m = N`, by construction of the annuity formula). The following deterministic treatment reconciles the mathematical fact with floating-point reality, without inventing cent rounding or a general clamping policy:

> `B_N` (the balance after exactly `N` scheduled payments, i.e. full contractual maturity) is defined as exactly `0.0`, by the mathematical identity that `PMT` is derived to fully retire `loan_amount` over `N` payments. This is a single boundary-point definition, not a rounding or clamping rule applied to balances in general. For every `m < N`, the recurrence's floating-point result is used exactly as computed, with no adjustment, regardless of sign or magnitude.

Consequently:

- Whenever `min(H * 12, N) = N` (i.e. `A <= H`, meaning the loan reaches or passes full maturity by the sale date), `remaining_loan_balance = 0.0` exactly, by definition, independent of the floating-point recurrence's raw last-step output.
- Whenever `min(H * 12, N) < N` (i.e. `A > H`, sale occurs before maturity), `remaining_loan_balance` is the recurrence's ordinary floating-point result at month `H * 12`, used as-is. This value is always strictly positive for a genuine (nonzero) loan under the Phase 0 domains, so a "materially negative" residue cannot arise in this branch; the only place a sign-flip residue could ever appear is exactly at `m = N`, which is the single point already special-cased above.

No other rounding, clamping, or cent-level adjustment is applied anywhere in the amortization schedule. This preserves "no invented cent rounding" and "full available floating-point precision" while giving two independent implementations one unambiguous, bit-reproducible value at the maturity boundary.

## Phase 2C — Exit Value

The property sells at the end of hold year `H`, using forward NOI (Phase 2A's `exit_noi`):

```text
exit_value = exit_noi / exit_cap_rate
```

Sale costs are `0` (Phase 0 exclusion). Because `exit_cap_rate > 0` is guaranteed by the input domain, this division is always defined.

```text
net_sale_proceeds = exit_value - remaining_loan_balance
```

`net_sale_proceeds` is the **levered** net sale proceeds, used inside `levered_cash_flows[H]` (see below). For the unlevered cash flow, exit proceeds equal `exit_value` directly — there is no separate "unlevered net sale proceeds" field, because it is identical to `exit_value` and adding a duplicate field would be an unjustified addition.

## Unlevered Cash Flows

```text
UCF_0 = -purchase_price

UCF_y = NOI_y                              for 1 <= y < H

UCF_H = NOI_H + exit_value
```

`unlevered_cash_flows` is a `tuple[float, ...]` of length `H + 1`, indexed `[UCF_0, UCF_1, ..., UCF_H]`. No debt term appears anywhere in this series. Acquisition costs and sale costs are `0` and are not separately represented.

## Levered Cash Flows

```text
LCF_0 = -initial_equity

LCF_y = NOI_y - ADS_y                      for 1 <= y < H

LCF_H = NOI_H - ADS_H + net_sale_proceeds
      = NOI_H - ADS_H + exit_value - remaining_loan_balance
```

`levered_cash_flows` is a `tuple[float, ...]` of length `H + 1`, indexed `[LCF_0, LCF_1, ..., LCF_H]`. `net_sale_proceeds` (Phase 2C) is used directly for the sale component of `LCF_H` rather than re-expanding `exit_value - remaining_loan_balance` inline, so the single computed value is reused rather than recomputed. No taxes, CapEx, TI, LC, refinancing, waterfalls, or additional debt tranches are introduced, per Phase 0's explicit exclusions.

## DSCR

```text
DSCR_y = NOI_y / ADS_y     if ADS_y > 0
DSCR_y = None                if ADS_y = 0
```

`dscr_by_year` is a `tuple[float | None, ...]` of length `H`, indexed by hold year `1..H`, holding each `DSCR_y`. This rule applies uniformly regardless of *why* `ADS_y = 0` — zero leverage (`ltv = 0`), a hold year past full amortization (`y > A`), or both.

```text
headline_dscr = dscr_by_year[0]     # DSCR_1
```

`headline_dscr` is `None` whenever `dscr_by_year[0]` is `None` (i.e. `ADS_1 = 0`, meaning `ltv = 0` or `A < 1`, though `A >= 1` is always guaranteed by the input domain so `A < 1` cannot occur — the only reachable zero-`ADS_1` case in POC V1 is `ltv = 0`).

`None` is the Python representation for DSCR "N/A", per the task's stated preference and consistent with `IssueCategory`-style explicit values already used elsewhere in this codebase; no compelling architectural reason exists to deviate.

## Equity Multiple

```text
Equity Multiple = sum(max(LCF_t, 0) for t in 0..H) / abs(sum(min(LCF_t, 0) for t in 0..H))
```

If the denominator (`abs(sum(min(LCF_t, 0) for t in 0..H))`) is `0`, `equity_multiple = None`. Equity Multiple is never reported as infinity.

**Treatment of zero cash flows.** A cash flow exactly equal to `0` contributes `max(0, 0) = 0` to the positive-sum numerator and `min(0, 0) = 0` to the negative-sum denominator; it therefore has no effect on either sum and is neither a positive nor a negative contribution. This includes the possible `LCF_0 = 0` case at 100% LTV combined with no other levered cash flow being negative, per Phase 0's explicit callout — in that case the denominator sum is `0` and `equity_multiple = None`, not `0` and not infinity.

If the denominator is nonzero but the numerator is `0` (every levered cash flow is `<= 0`, i.e. a total loss with no positive return at any point), `equity_multiple = 0.0` — a well-defined, finite result (a "0.0x" multiple), not `None`. `None` is reserved exclusively for the zero-denominator case defined by Phase 0.

## IRR

`docs/financial_conventions.md` "IRR validity" and "IRR numerical solution" define the frozen algorithm exactly. This section reproduces it in full for Phase 2 implementation; the prose in `docs/financial_conventions.md` governs on any discrepancy. The same algorithm applies independently to `unlevered_cash_flows` (producing `unlevered_irr`) and to `levered_cash_flows` (producing `levered_irr`).

No `numpy_financial`, no `numpy.irr`, no `scipy`, no Excel `IRR`/`XIRR`, no Newton-Raphson, no secant method, and no other general-purpose solver may be used. Only the exact procedure below is implemented.

### Validity (sign) rules

Given an annual periodic cash-flow series `CF_0 .. CF_H`, ignore zero cash flows for sign-change analysis only; every cash flow retains its original annual time index in the NPV/polynomial evaluation. The nonzero subsequence must satisfy all of:

- at least one negative and at least one positive nonzero cash flow exist;
- the first nonzero cash flow is negative; and
- the nonzero subsequence has exactly one sign change.

If any condition fails, the IRR for that series is `None`.

### Transformation and reduced polynomial

```text
x = 1 / (1 + r)      r = (1 / x) - 1      (r > -1  <=>  x > 0)

F(x) = sum from t = t0 through H of CF_t * x^(t - t0)
```

where `t0` is the index of the first nonzero cash flow.

Every evaluation of `F(x)` uses Horner's method over the reduced coefficients in descending exponent order:

```text
horner_value = CF_H
for t = H - 1 down through t0:
    horner_value = horner_value * x + CF_t
F(x) = horner_value
```

Every intermediate `horner_value` and the final `F(x)` must be finite (not `NaN`, not `+inf`, not `-inf`). Any non-finite evaluation at any point (bracket, expansion, exact-root check, or bisection) is a numerical-support failure: return `None` immediately, and never infer a positive/negative sign or bracket direction from a non-finite value.

### Bracketing

```text
x_low  = 0
x_high = 1
f_low  = F(x_low)
f_high = F(x_high)
```

If either is non-finite, return `None` immediately, before any exact-root or sign comparison. (Given a valid series, `f_low < 0` always, because `F(0)` reduces to the first — negative — nonzero cash flow.)

If `f_high == 0`: set `x_star = x_high` and go directly to conversion (skip bisection).

Otherwise, while `f_high < 0`:

1. If `x_high >= 1e12`: return `None` (root requires `x > 1e12`, outside the supported domain).
2. `x_high = min(2 * x_high, 1e12)`.
3. Evaluate `f_high = F(x_high)` via Horner.
4. If non-finite: return `None` immediately.
5. If `f_high == 0`: set `x_star = x_high` and go directly to conversion (skip bisection).

When the loop exits because `f_high > 0`, the strict bracket `F(x_low) < 0 < F(x_high)` is established. The boundary `x = 1e12` is always evaluated before returning `None` for exceeding the domain, so an exact root at `x = 1e12` is accepted; a negative evaluation there yields `None` on the next loop check, a positive evaluation establishes the bracket, and a non-finite evaluation there yields `None` under the numerical-support rule.

### Bisection

Up to 256 iterations. Each iteration:

1. `x_mid = (x_low + x_high) / 2`.
2. `f_mid = F(x_mid)` via Horner. If non-finite: return `None` immediately (no exact-root, tolerance, or sign check on a non-finite value).
3. In this exact order, once `f_mid` is confirmed finite:
   - if `f_mid == 0`: `x_star = x_mid`; stop.
   - else if `abs(f_mid) <= 1e-10 * max_abs_cash_flow` (the largest absolute cash-flow magnitude in the series): `x_star = x_mid`; stop.
   - else if `(x_high - x_low) <= 1e-12 * max(1, abs(x_mid))`: `x_star = x_mid`; stop.
4. Only if no stopping condition matched, update exactly one endpoint: `x_low = x_mid` if `f_mid < 0`, else `x_high = x_mid`.

If all 256 iterations complete without a stopping condition, `x_star = (x_low + x_high) / 2`, provided it is finite and strictly positive; otherwise return `None`.

### Conversion back to IRR

```text
IRR = (1 / x_star) - 1
```

If `x_star <= 0`, `x_star` is non-finite, the resulting `IRR` is non-finite, or `IRR <= -1`: return `None`. Otherwise return the computed `IRR` as the annual periodic rate.

`None` is the Python representation for IRR "N/A", per the task's stated preference; no compelling architectural reason exists to deviate.

## Floating-Point / Rounding

Preserving the Phase 0 convention exactly:

- all calculations use full available IEEE-754 double-precision (`float`) precision throughout every intermediate step;
- no intermediate cent rounding of `PMT`, loan balances, NOI, ADS, Exit Value, or cash flows;
- no intermediate rounding of NOI between years;
- IRR, DSCR, and Equity Multiple are computed from unrounded intermediate values and are not themselves rounded;
- rounding is presentation-only and out of scope for the engine — no field of `AcquisitionResults` is ever rounded for display, and no presentation-formatting code exists in the engine package; and
- ordinary Python `float` (IEEE-754 binary64) arithmetic is the implementation target for deterministic equivalence between independent implementations, consistent with Phase 0's acknowledgment that "ordinary floating-point arithmetic does not guarantee recovery of every mathematically valid IRR for arbitrary finite inputs."

Financial outputs that become non-finite fail explicitly, per the Phase 2A non-finite rule, rather than flowing silently into a returned `AcquisitionResults`.

## Architecture

Recommended minimal structure (files are not created by this specification task):

```text
src/mini_anchor/engine/
    __init__.py       # re-exports analyze_acquisition and AcquisitionResults
    contracts.py       # AcquisitionResults dataclass; NonFiniteResultError
    noi.py              # NOI forecast, exit NOI, going-in cap rate
    debt.py             # loan amount, PMT, amortization recurrence, ADS, remaining balance
    returns.py          # IRR solver, Equity Multiple, DSCR
    acquisition.py       # orchestrates the above into AcquisitionResults
```

Responsibilities:

- **`noi.py`** — NOI forecast only: the `NOI_y` series, `exit_noi`, and `going_in_cap_rate`. No debt, no cash flows, no returns.
- **`debt.py`** — loan amount, initial equity, `PMT`, the month-by-month amortization recurrence, `annual_debt_service`, and `remaining_loan_balance`. No NOI forecasting, no cash-flow assembly, no return metrics.
- **`returns.py`** — return-metric utilities only: the frozen IRR solver (used identically for both unlevered and levered series), Equity Multiple, and DSCR. Takes already-assembled cash-flow tuples and already-computed `ADS` as input; does not itself compute NOI or debt.
- **`acquisition.py`** — orchestrates `noi.py`, `debt.py`, and `returns.py` (exit value, cash-flow assembly, and the final `AcquisitionResults` construction) into the single public `analyze_acquisition` entry point. Contains no formula of its own beyond assembling values already computed by the other modules (exit value, unlevered/levered cash-flow tuples, and net sale proceeds are thin compositions, not new financial logic).

No module in `src/mini_anchor/engine/` imports `openpyxl`, at any depth. This is directly testable (e.g., a test asserting no engine module's import graph reaches `openpyxl`).

## Implementation Sequence

Phase 2 implementation (a future task, not this specification) proceeds in these controlled, independently testable parts:

**Phase 2A** — `engine/contracts.py` (`AcquisitionResults`, `NonFiniteResultError`) and `engine/noi.py` (NOI forecast, exit NOI, going-in cap rate); plus the acquisition capital-stack basics (`loan_amount`, `initial_equity`) that require no debt-schedule machinery.

**Phase 2B** — `engine/debt.py`: `PMT`, the monthly amortization recurrence, `annual_debt_service`, `remaining_loan_balance`, including the `A < H` / `A = H` / `A > H` and `LTV = 0` boundary behaviors.

**Phase 2C** — exit NOI consumption into `exit_value`, `net_sale_proceeds`, `unlevered_cash_flows`, and `levered_cash_flows`, in `acquisition.py`, built on top of the Phase 2A/2B outputs.

**Phase 2D** — `engine/returns.py`: `dscr_by_year`, `headline_dscr`, `equity_multiple`, and the frozen IRR solver, applied to the Phase 2C cash-flow tuples.

**Phase 2E** — the integrated `analyze_acquisition` function in `acquisition.py` assembling every prior part into one `AcquisitionResults`, plus end-to-end integration tests covering the full `AcquisitionInputs -> AcquisitionResults` path, including the Phase 1 example workbook.

Each part is independently testable against this specification's formulas and the golden case below before the next part begins.

## Public Engine Entry Point

```python
def analyze_acquisition(inputs: AcquisitionInputs) -> AcquisitionResults:
    ...
```

This is the sole public entry point of the engine package. It:

- accepts `AcquisitionInputs` directly (never a file path, workbook, or raw mapping);
- does not open Excel, know about `openpyxl`, know about Azure, know about GPT/OpenAI, or format output for any UI/API layer; and
- is a pure function of its input: identical `AcquisitionInputs` values always produce identical `AcquisitionResults` values (field-for-field, including tuple contents), given a fixed implementation version.

```text
Excel Reader ──────┐
                    │
Azure Parser ───────┼──> AcquisitionInputs
                    │
UI/API ─────────────┘
                          │
                          v
                  analyze_acquisition()
                          │
                          v
                  AcquisitionResults
```

## Test Requirements

The future Phase 2 implementation is not complete without automated tests covering at least the following, organized to mirror the module boundaries above:

**NOI** (`noi.py`): `H = 1`; zero NOI Growth; positive NOI Growth; negative NOI Growth `> -1`; `Current NOI = 0`; Occupancy has no effect on any `NOI_y` regardless of its value.

**Going-in cap** (`noi.py`): ordinary case; `Current NOI = 0` (result is `0.0`, not an error, not `None`).

**Debt** (`debt.py`): `LTV = 0`; `LTV = 1`; zero interest; positive interest; `A < H`; `A = H`; `A > H`; exact maturity (`B_N` treated as exactly `0.0`); remaining balance at several known months (validated against both the recurrence and the closed form within an explicit tolerance); annual debt-service aggregation for each of `A < H`, `A = H`, `A > H`; no debt service after maturity (`ADS_y = 0` for `y > A`).

**Exit** (`acquisition.py` / `noi.py`): forward-NOI convention (`exit_noi != NOI_H` whenever `g != 0`); `H = 1`; zero growth; positive growth; negative growth; no sale costs deducted.

**Cash flows** (`acquisition.py`): exact `UCF` timing including the `UCF_H` sale inclusion; exact `LCF` timing including the `LCF_H` sale inclusion and loan payoff; zero leverage (`LTV = 0`, so `LCF = UCF - 0` throughout except `LCF_0 = -purchase_price` too, since `initial_equity = purchase_price`); 100% leverage (`LTV = 1`, so `LCF_0 = 0`).

**DSCR** (`returns.py`): ordinary debt; zero leverage (`ADS_y = 0` for every `y`, every `DSCR_y = None`); fully amortized before exit (`DSCR_y = None` for `y > A`); `headline_dscr = None` when `ADS_1 = 0`.

**Equity Multiple** (`returns.py`): ordinary case; zero denominator returns `None` (including the `LTV = 1` sub-case with no negative levered cash flow anywhere); zero numerator with nonzero denominator returns `0.0`, not `None`; a cash flow of exactly `0` contributes to neither sum.

**IRR** (`returns.py`): ordinary positive IRR; zero IRR; negative IRR; very large positive IRR; IRR near `-100%` but within the supported domain; a root requiring `x > 1e12` returns `None`; exact root at `x = 1`; exact root at `x = 1e12` if constructible; leading zero cash flows; `LCF_0 = 0`; first nonzero cash flow positive (returns `None`); no positive cash flow (returns `None`); no negative cash flow (returns `None`); more than one sign change (returns `None`); zero cash flows ignored for sign-change counting; non-finite Horner evaluation at any stage returns `None`; deterministic (bit-identical) results across repeated calls with the same input.

**Integration** (`acquisition.py`, end-to-end): valid `AcquisitionInputs` produces the exact `AcquisitionResults` expected from this specification's formulas; the same inputs produce the same outputs across repeated calls; the Phase 1 example workbook, read through `read_acquisition_inputs`, produces the expected `AcquisitionResults` when passed to `analyze_acquisition`; no module under `mini_anchor.engine` imports `openpyxl`; every tuple field of `AcquisitionResults` is immutable; `AcquisitionResults` itself is frozen and slotted; no field is ever presentation-rounded.

## Golden Case

**This section computes test/golden expected numeric results for a specific example. It is not itself a financial convention. If any number below appears to conflict with a formula stated earlier in this document or in `docs/financial_conventions.md`, the formula governs and the golden number is presumed miscalculated, not the reverse.**

Inputs:

```text
purchase_price = 50,000,000
current_noi    = 2,500,000
occupancy      = 0.95
noi_growth     = 0.03
hold_period    = 5
exit_cap_rate  = 0.055
ltv            = 0.65
interest_rate  = 0.0525
amortization   = 30
```

These values were used to independently execute this document's formulas (NOI forecast, amortization recurrence, exit value, cash-flow assembly, DSCR, Equity Multiple, and the frozen IRR bisection algorithm exactly as specified above) in order to produce the expected values below. `occupancy = 0.95` is included only to demonstrate that it has no effect on any result.

### NOI and capital stack

```text
going_in_cap_rate = 0.05

noi_by_year = (
    2500000.0,                 # NOI_1
    2575000.0,                 # NOI_2
    2652250.0,                 # NOI_3
    2731817.5,                 # NOI_4
    2813772.0250000004,        # NOI_5
)
exit_noi = 2898185.18575       # NOI_6, forward NOI used only for sale

loan_amount    = 32500000.0
initial_equity = 17500000.0
```

### Debt

```text
r (monthly)                    = 0.0043749999999999995   # 0.0525 / 12
N (scheduled monthly payments) = 360                       # 30 * 12
monthly_debt_service (PMT)     = 179466.20319611664

annual_debt_service = (
    2153594.4383533997,   # ADS_1
    2153594.4383533997,   # ADS_2
    2153594.4383533997,   # ADS_3
    2153594.4383533997,   # ADS_4
    2153594.4383533997,   # ADS_5
)
```

All five years are identical because `A = 30 > H = 5`, so every modeled year is fully within the amortization period (`ADS_y = 12 * PMT` for all `y in 1..5`).

Illustrative intermediate amortization points, for validating an independent recurrence implementation (not part of `AcquisitionResults`):

```text
Beginning Balance_1 (= loan_amount) = 32500000.0
Interest_1                          = 142187.49999999997
Principal_1                         = 37278.703196116665
Ending Balance_1 (balance after month 1)   = 32462721.296803884
Ending Balance after month 12               = 32041732.801682245
Ending Balance after month 24               = 31558819.12881365
Ending Balance after month 60 (= B_exit)    = 29948583.641211294
Ending Balance after month 120              = 26633190.900727887
Ending Balance after month 359              = 178684.45868969124
Ending Balance after month 360 (raw recurrence, before the
  contractual-maturity B_N := 0.0 identity is applied) = 3.4199911169707775e-07
```

```text
remaining_loan_balance = 29948583.641211294       # B_exit = B_60 (min(12*5, 360) = 60)
```

### Exit and sale proceeds

```text
exit_value        = 52694276.10454546      # 2898185.18575 / 0.055
net_sale_proceeds = 22745692.463334166     # exit_value - remaining_loan_balance
```

### Cash flows

```text
unlevered_cash_flows = (
    -50000000.0,
    2500000.0,
    2575000.0,
    2652250.0,
    2731817.5,
    55508048.12954546,     # NOI_5 + exit_value
)

levered_cash_flows = (
    -17500000.0,
    346405.5616465998,
    421405.5616465998,
    498655.5616465998,
    578223.0616465998,
    23405870.049980767,    # NOI_5 - ADS_5 + net_sale_proceeds
)
```

### DSCR

```text
dscr_by_year = (
    1.160849951818902,
    1.195675450373469,
    1.2315457138846733,
    1.2684920853012134,
    1.30654684786025,
)
headline_dscr = 1.160849951818902
```

### Equity Multiple

```text
sum of positive levered cash flows = 25250559.796567164
sum of negative levered cash flows = -17500000.0
equity_multiple = 1.4428891312324095
```

### IRR

```text
unlevered_irr = 0.062414943980353854
levered_irr   = 0.07913030056780745
```

Both IRR values were produced by the exact transformation, Horner-evaluated reduced polynomial, bracket-expansion, and 256-iteration bisection procedure specified above and in `docs/financial_conventions.md` — no external solver was used. An independent implementation following the same procedure with the same tolerances is expected to reproduce these values to full `float` precision, since the bisection procedure is itself deterministic and bit-reproducible given identical inputs and IEEE-754 arithmetic.

## Definition of Done

Phase 2 (the future implementation) is complete only when:

- `AcquisitionInputs` can be analyzed without Excel (`analyze_acquisition` accepts only `AcquisitionInputs`);
- the NOI forecast follows Phase 0 exactly, including the Year-1/Year-2-growth-start rule and Occupancy having no effect;
- the debt schedule follows Phase 0 exactly, including the `A < H` / `A = H` / `A > H` and `LTV = 0` boundaries;
- sale timing follows Phase 0 exactly (forward NOI, end-of-`H` sale, zero sale costs);
- cash flows follow Phase 0 exactly, including exact `UCF`/`LCF` timing and the sale/payoff inclusion at year `H`;
- DSCR follows Phase 0 exactly, including the `None` convention for `ADS_y = 0` regardless of cause;
- Equity Multiple follows Phase 0 exactly, including the `None` convention for a zero denominator and never returning infinity;
- IRR follows the frozen custom bracket-and-bisection algorithm exactly, with no substitute solver;
- all financial calculations are deterministic (same inputs, same outputs, every call);
- non-finite results fail explicitly rather than propagating into `AcquisitionResults`, except where Phase 0 already defines a `None` convention;
- the full automated test suite (targeted module tests plus integration tests) passes;
- no `openpyxl` import exists anywhere in `src/mini_anchor/engine/`;
- no AI dependency (model call, prompt, or AI-derived value) exists anywhere in the engine code; and
- no UI/API/CLI framework dependency exists anywhere in the engine code.

## Frozen Phase 2 Decisions

- The engine's sole public entry point is `analyze_acquisition(inputs: AcquisitionInputs) -> AcquisitionResults`; it accepts only `AcquisitionInputs` and returns only `AcquisitionResults`.
- `AcquisitionResults` is the exact immutable, slotted, keyword-only dataclass specified in this document, with the field set: `going_in_cap_rate`, `loan_amount`, `initial_equity`, `monthly_debt_service`, `annual_debt_service`, `remaining_loan_balance`, `noi_by_year`, `exit_noi`, `exit_value`, `net_sale_proceeds`, `unlevered_cash_flows`, `levered_cash_flows`, `unlevered_irr`, `levered_irr`, `equity_multiple`, `dscr_by_year`, `headline_dscr`.
- `annual_debt_service` and `dscr_by_year` are per-hold-year `tuple`s of length `H`; `noi_by_year` is a per-hold-year `tuple` of length `H`; `unlevered_cash_flows` and `levered_cash_flows` are `tuple`s of length `H + 1`; `remaining_loan_balance`, `exit_noi`, `exit_value`, and `net_sale_proceeds` are single scalars representing the exit-date/forward-period quantity.
- The month-by-month amortization recurrence (not the closed-form `B_m` formula) is the specified Phase 2 implementation path for loan-balance and payment computation, adopted specifically to guarantee bit-reproducible determinism between independent implementations; the closed form remains a valid cross-check but not the authoritative computation.
- `B_N` (the balance at exact contractual maturity, `m = N`) is defined as exactly `0.0` by mathematical identity, independent of the raw floating-point recurrence result at that single point; no other balance, payment, NOI, ADS, cash flow, DSCR, Equity Multiple, or IRR value is ever rounded, clamped, or adjusted for floating-point residue.
- Non-finite intermediate or output values, outside the four fields with a frozen `None`/"N/A" convention (`unlevered_irr`, `levered_irr`, `dscr_by_year` entries, `headline_dscr`, `equity_multiple`), cause the engine to fail explicitly rather than return a partially non-finite `AcquisitionResults`; this is an implementation safety rule, not a change to Phase 0 economics.
- `None` is the Python representation for every "N/A" case (IRR, DSCR, Equity Multiple), per the task's stated preference.
- The frozen custom IRR bracket-and-bisection algorithm, exactly as specified in `docs/financial_conventions.md` and restated in this document, is the only permitted IRR solver; no third-party or general-purpose numerical solver may be substituted.
- The engine package (`src/mini_anchor/engine/`) never imports `openpyxl`, and no engine module knows about Azure, GPT/OpenAI, or any UI/API/CLI framework.
- All financial calculations use full IEEE-754 double-precision `float` arithmetic with no intermediate rounding; rounding is presentation-only and out of scope for the engine.

## Deferred Beyond Phase 2

- sensitivity analysis
- scenario analysis
- rent roll modeling
- individual leases
- CapEx
- TI
- LC
- taxes
- acquisition costs
- sale costs
- multiple debt tranches
- interest-only debt
- refinancing
- waterfalls/promotes
- development modeling
- construction draws
- Azure extraction
- GPT analysis
- FastAPI
- frontend dashboard
- database
- provenance/confidence
- alternate calculation conventions
