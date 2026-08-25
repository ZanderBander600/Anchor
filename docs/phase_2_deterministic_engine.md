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

Required implementation: the approved `NonFiniteResultError(ValueError)` defined in `engine/contracts.py` is raised at the point a non-finite value is first detected, analogous in spirit to Phase 1's `InputValidationError` but reporting a single deterministic-computation failure rather than a collected list of input issues (there is nothing to collect against, since Phase 2 does not re-validate `AcquisitionInputs`).

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

`amortization` is a positive whole number of years under the frozen Phase 0 input domain. Therefore, `N` is always a positive multiple of `12`, payment `N` always falls at the end of amortization year `A`, and contractual maturity always occurs at a year boundary. POC V1 has no reachable partial amortization-ending hold year.

`monthly_debt_service` (`PMT`) is calculated by evaluating the following three branches **in this fixed order**. The first branch whose condition holds determines `PMT`; later branches must not be evaluated once an earlier branch applies.

#### Branch 1 — zero loan amount (frozen)

If `loan_amount == 0.0`:

```text
PMT = 0.0
```

This branch is checked, and `PMT = 0.0` is returned, **before** any positive-interest payment denominator is evaluated — regardless of `interest_rate`. A zero loan has zero debt service by financial identity (Phase 0: `L = P * LTV`, so `LTV = 0` implies `L = 0`), and it must never be possible for a zero loan to reach a numerical `0 / 0` payment path. This is not a new financial convention: it makes the Phase 0 zero-loan identity an explicit, ordered implementation branch rather than an incidental consequence of substituting `loan_amount = 0` into the general formulas.

#### Branch 2 — zero interest rate (frozen)

Else, if `interest_rate == 0.0`:

```text
monthly_rate = 0.0
PMT = loan_amount / N
```

This is the frozen Phase 0 zero-interest formula, preserved unchanged.

#### Branch 3 — positive interest rate (frozen, numerically stable evaluation)

Else — `loan_amount != 0.0` and `interest_rate > 0.0`:

```text
monthly_rate = interest_rate / 12          # r
```

`interest_rate` is economically positive on entry to this branch. Branch selection itself is based on the original annual `interest_rate`, not on the derived `monthly_rate`; Branch 3 is taken whenever `interest_rate > 0.0`, even in the numerical edge case described immediately below where the derived `monthly_rate` is not representable as a nonzero `float`.

##### Branch 3a — monthly-rate underflow (frozen POC V1 numerical-boundary rule)

A positive annual `interest_rate` divided by `12` is, in ordinary cases, itself a representable positive `float`. However, for an extremely small but still strictly positive `interest_rate` (below the representable monthly-rate range — i.e. so small that IEEE-754 division by `12` underflows to exactly `0.0`), the derived quantity can fail to be positive even though the input was:

```text
interest_rate > 0.0
monthly_rate = interest_rate / 12
monthly_rate == 0.0      # underflow, not a zero-interest input
```

If this occurs, freeze the following POC V1 numerical-boundary behavior:

```text
PMT = loan_amount / N
```

This is the analytical limit of the positive-rate amortizing payment formula as `monthly_rate` approaches `0` from above, so it is the same numerical value Branch 2 would produce — but it is reached for a different, explicitly documented reason. This is **not** a financial reclassification of the loan as zero-interest, and it is **not** silent coercion: the original annual `interest_rate` remains positive and is never mutated or treated as `0.0`; only the derived, IEEE-754-underflowed `monthly_rate` is `0.0`. No raw `ZeroDivisionError` (or any other arithmetic exception) may occur along this path. It is a documented floating-point numerical-boundary rule, not a new financial convention, and it does not change Phase 0 economics.

For subsequent monthly recurrence in this exact numerical-support case, `monthly_rate` remains the representable Python `float` `0.0`, so:

```text
Interest_t = Beginning Balance_t * 0.0 = 0.0
```

for every month `t`, and the recurrence otherwise follows the existing frozen operation order (Interest, then Principal, then Ending Balance) unchanged — it is not special-cased beyond `monthly_rate` itself already being `0.0`.

##### Branch 3b — representable positive monthly rate (frozen, numerically stable evaluation)

Otherwise, `monthly_rate > 0.0` is representable. The financial formula remains, per Phase 0:

```text
PMT = loan_amount * r / (1 - (1 + r)^(-N))
```

However, the denominator must **not** be evaluated using the naive floating-point expression:

```text
1 - (1 + r) ** (-N)
```

because a valid, extremely small positive rate can satisfy `r > 0` while also satisfying `1.0 + r == 1.0` under IEEE-754 double-precision arithmetic — `r` can be too small for double precision to distinguish `1.0 + r` from `1.0` even though `r` itself is a distinct, genuinely positive `float`. The naive expression would then evaluate to `1 - 1 = 0`, producing a zero denominator despite `r` being positive.

The frozen, numerically stable evaluation of the denominator is:

```text
log_growth           = log1p(r)
discount_exponent     = -N * log_growth
payment_denominator   = -expm1(discount_exponent)
```

using Python standard-library `math.log1p` and `math.expm1`. This is an algebraically equivalent numerical evaluation of the frozen Phase 0 positive-rate denominator: `log1p(r) = ln(1 + r)`, so `discount_exponent = -N * ln(1 + r) = ln((1 + r)^(-N))`, and `expm1(discount_exponent) = (1 + r)^(-N) - 1`, so `payment_denominator = -expm1(discount_exponent) = 1 - (1 + r)^(-N)` — the same denominator, evaluated so that a genuinely positive `r` cannot silently collapse to zero.

**The numerator/division must also be evaluated in a specific, frozen, underflow-safe order.** The financial formula's numerator, `loan_amount * r`, can itself underflow to `0.0` under ordinary IEEE-754 double-precision multiplication for a small-but-finite `loan_amount` and a small-but-representable `r`, even though the true, final `PMT` value is finite and well away from `0`. Evaluating:

```text
(loan_amount * r) / payment_denominator
```

is therefore **not permitted**, because `loan_amount * r` can round to exactly `0.0` before division ever occurs, silently producing `PMT = 0.0` even though the mathematically correct `PMT` is a small but definitely nonzero finite number. The frozen evaluation order divides first and multiplies second:

```text
rate_fraction = r / payment_denominator

PMT = loan_amount * rate_fraction
```

This is algebraically equivalent to the frozen Phase 0 `PMT` formula (`loan_amount * r / payment_denominator = loan_amount * (r / payment_denominator)` in exact real-number arithmetic) and preserves the same zero-rate limiting behavior numerically, but avoids the specific underflow path in which `loan_amount * r` is computed and rounded to `0.0` before it is ever divided. `rate_fraction` and `PMT` must each pass an immediate finiteness check after being computed (see the non-finite detection granularity rules below).

No minimum positive interest rate is imposed. A positive `r` is never converted to `0`. No `Decimal` or arbitrary-precision arithmetic is introduced; the stable evaluation remains ordinary Python `float` (IEEE-754 binary64) arithmetic, consistent with this document's other floating-point conventions.

**`discount_exponent` boundary case.** Under the Phase 0 domains applicable to this branch (`N > 0`, `r > 0`, so `log_growth = log1p(r) > 0`), `discount_exponent = -N * log_growth` is always `<= 0` and, for every ordinary input, a finite negative number. `discount_exponent` can become `-inf` in exactly two related ways, both arising only from an extreme but permitted `amortization`/`interest_rate` combination, and both are resolved identically and deterministically — neither is treated as a numerical failure:

1. **Ordinary IEEE-754 float overflow.** `N * log_growth` itself overflows double precision to `+inf` under ordinary float multiplication (no exception is raised — `N`, already representable as a `float`, multiplies with `log_growth` and the product exceeds the maximum finite `double`), producing `discount_exponent = -inf` directly.
2. **`OverflowError` while constructing/multiplying an extremely large `N`.** `N = amortization * 12` is an arbitrary-precision Python `int`. For an extreme but permitted `amortization`, `N` itself can exceed the magnitude any `float` can represent, so evaluating `N * log_growth` raises a raw `OverflowError` when Python attempts to convert `N` to `float` — before any product is ever formed. This case must be caught, and, provided `N > 0`, `log_growth > 0`, and both source quantities are otherwise valid (finite, correctly signed), the engine must deterministically treat the mathematical result the same as case 1: `discount_exponent = -inf`. The raw `OverflowError` must never leak out of the engine.

In both cases, `math.expm1(-inf)` is defined and returns exactly `-1.0`, so `payment_denominator = -expm1(-inf) = 1.0` exactly (finite), and `rate_fraction = r / 1.0 = r`, so `PMT = loan_amount * r`. This matches the mathematical limit of the closed-form denominator as `(1 + r)^(-N) -> 0`. `discount_exponent = -inf` arising either way is therefore explicitly permitted and must not raise `NonFiniteResultError`, and an `OverflowError` encountered while computing it under condition 2 must not be allowed to propagate. `discount_exponent = +inf` and `discount_exponent = NaN` are not reachable under the Phase 0 domains in this branch; if either is nonetheless observed, it is treated as a finiteness failure like any other required quantity (see the non-finite detection granularity rules below). Likewise, any `OverflowError` encountered anywhere else in Branch 3, or any `OverflowError` that does not satisfy the `N > 0` / `log_growth > 0` / otherwise-valid preconditions above, is not covered by this documented exception and remains an explicit numerical failure.

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

Substituting `loan_amount = 0` into either the zero-rate or positive-rate `PMT` formula (whether `r = 0` or `r != 0`) always yields `PMT = 0.0`, because the numerator `loan_amount * r` (or `loan_amount / N`) is `0`. Consequently every `annual_debt_service[y-1] = 0.0`, every remaining balance is `0.0` at every month (starting from a beginning balance of `0.0`, `Interest_t = 0 * r = 0`, `Principal_t = 0 - 0 = 0`, `Ending Balance_t = 0`), and `remaining_loan_balance = 0.0`. `initial_equity = purchase_price - 0 = purchase_price`.

**A special-cased branch is required in the implementation.** Per the "Loan structure" section above, `PMT` is calculated via Branch 1 (zero loan amount) whenever `loan_amount = 0.0`: `PMT = 0.0` is returned immediately, without evaluating Branch 3's positive-rate denominator, regardless of `interest_rate`. This produces the same result as the substitution described above, but the explicit, first-checked branch guarantees no numerical `0 / 0` or otherwise undefined path is ever reachable for a zero loan — including under an arbitrary, valid positive `interest_rate` — even though algebraic substitution alone would also happen to reach `PMT = 0.0`. This table documents the resulting behavior so an implementer can write a golden-value test without deriving it independently.

### Annual debt service

```text
ADS_y = sum of Monthly Payment_t for t = 12(y - 1) + 1 through 12y,   1 <= y <= H
```

`annual_debt_service[y - 1]` holds `ADS_y`.

**Frozen operation order.** `ADS_y` must be computed by chronological monthly summation, exactly as Phase 0 defines it:

```text
ADS_y = 0.0
for each month t from 12(y - 1) + 1 through 12y, in chronological order:
    ADS_y = ADS_y + Monthly Payment_t
```

Implementations must accumulate `ADS_y` by adding each of the 12 `Monthly Payment_t` values for hold year `y` in chronological month order. `ADS_y` must **not** be implemented as `12 * PMT`, even for a hold year in which every month is contractually active and the two expressions are mathematically equal in exact real-number arithmetic. Repeated IEEE-754 addition of 12 individual `Monthly Payment_t` values and a single floating-point multiplication `12 * PMT` can differ in the last bits, because IEEE-754 addition and multiplication do not always associate or distribute identically. The chronological monthly summation is authoritative because it follows the frozen Phase 0 definition of `ADS_y` directly, rather than an algebraically equivalent shortcut.

Because `N = 12 * A` is always a whole number of months (Phase 0 domain: `A >= 1` integer):

- for `1 <= y <= min(H, A)`: every one of the 12 month-positions in year `y` satisfies `t <= N`, so every `Monthly Payment_t = PMT` for that year, and the chronological summation of those 12 identical `PMT` values produces `ADS_y` (this sum is mathematically equal to `12 * PMT`, but is not computed as that separate expression);
- for `y > A` (only reachable when `H > A`): every month-position in year `y` satisfies `t > N`, so every `Monthly Payment_t = 0.0`, and the chronological summation of those 12 zero values yields `ADS_y = 0.0` exactly.

For zero leverage (`ltv = 0`, so `loan_amount = 0.0` and `PMT = 0.0` via Branch 1 above), every `Monthly Payment_t = 0.0` for every year, so the same chronological summation path yields `ADS_y = 0.0` for every hold year — this is not a separate special case, it is the same summation applied to an all-zero monthly schedule.

Equivalently, if the contractual payment schedule remains active for a hold year, that year contains exactly 12 scheduled payments summed chronologically. If contractual maturity occurred before a hold year begins, ADS for that year is exactly `0.0`. The general month-based payment rules remain authoritative, but a partial final amortization year is not reachable under the current POC V1 input domain: year `A` contains all 12 scheduled payments for that year, payment `N` occurs in its final month, and year `A + 1` is the first fully zero-ADS year. This is not a new assumption — it follows directly from `A`, `H`, and every hold-year boundary being whole numbers under the frozen Phase 0 domains.

The three orderings `A < H`, `A = H`, and `A > H` are all supported by the same chronological-summation procedure with no branching beyond the `min(H, A)` comparison above:

- `A < H`: chronological summation yields `ADS_y` equal to the sum of 12 active `PMT` payments for years `1..A` and `ADS_y = 0.0` for years `A+1..H`; `remaining_loan_balance = 0.0` (the loan is fully amortized before sale).
- `A = H`: chronological summation yields `ADS_y` equal to the sum of 12 active `PMT` payments for every modeled year; `remaining_loan_balance = 0.0` (sale occurs exactly at contractual maturity).
- `A > H`: chronological summation yields `ADS_y` equal to the sum of 12 active `PMT` payments for every modeled year; `remaining_loan_balance` is the actual pre-maturity recurrence balance.

For `LTV = 0`, the already-defined zero-loan behavior applies under all three orderings: every `annual_debt_service` entry and `remaining_loan_balance` are `0.0`.

## Remaining Loan Balance

Per Phase 0, the exact closed-form definition is:

```text
B_m = L * (1 + r)^m - PMT * ((1 + r)^m - 1) / r          (r != 0)
B_m = L - m * PMT                                          (r = 0)
```

For Phase 2 implementation, the specified computation path is the mathematically equivalent month-by-month recurrence, evaluated iteratively rather than via the closed form:

```text
Beginning Balance_1 = loan_amount
monthly_rate = r

for each scheduled payment month t = 1 .. min(H * 12, N):
    Interest_t = Beginning Balance_t * monthly_rate
    Principal_t = Payment_t - Interest_t
    Ending Balance_t = Beginning Balance_t - Principal_t

    then:

    Beginning Balance_(t+1) = Ending Balance_t
```

Implementations must execute this per-month sequence exactly as written: calculate `Interest_t`, then calculate `Principal_t` from that stored interest value, then calculate `Ending Balance_t` from that stored principal value, and only then carry the ending balance forward as the next month's beginning balance. This operation order is the frozen Phase 2B implementation path. It must not be algebraically simplified to:

```text
Beginning Balance_t * (1 + monthly_rate) - Payment_t
```

or to any other mathematically equivalent expression. Python IEEE-754 floating-point operation order can change the last bits of the result.

For `r = 0`, `Interest_t = 0` for every `t`, so `Principal_t = Payment_t = PMT` and the recurrence reduces to `Ending Balance_t = Beginning Balance_t - PMT`, consistent with the closed form `B_m = L - m * PMT`.

`remaining_loan_balance = B_exit`, the ending balance after month `min(H * 12, N)`:

```text
B_exit = B_min(12H, N)
```

**Why the recurrence, not the closed form, is the specified implementation path.** Both formulas are mathematically identical in exact real-number arithmetic. But `(1 + r)^m` evaluated via `pow()` versus an iterative accumulation of individual `Beginning Balance_t - Principal_t` subtractions can differ in the last few bits of IEEE-754 double precision, depending on implementation choices such as library exponentiation and expression evaluation order. Two independent implementations that both follow the recurrence and operation order exactly as written above use the same frozen floating-point path. The recurrence is therefore the authoritative Phase 2 computation for loan balances. The closed form must never replace it.

### Extreme interest-rate numerical boundary

Phase 0 permits any finite annual `interest_rate >= 0` and imposes no upper bound. At extremely large but valid interest rates, IEEE-754 precision can make the calculated monthly principal difference (`Payment_t - Interest_t`) smaller than representable precision relative to a very large outstanding balance. Consequently, before contractual maturity, repeated recurrence balances may appear unchanged or nearly unchanged even though the mathematical fully amortizing loan is amortizing.

This is floating-point behavior, not a different debt convention. Phase 2B must not impose a new upper bound on Interest Rate, silently substitute higher-precision arithmetic, or replace the recurrence. The required IEEE-754 recurrence remains authoritative. At contractual maturity, the frozen `B_N := 0.0` rule below still applies.

### Closed-form balance cross-check boundary

The closed-form remaining-balance formula may be used only as a test/reference oracle for ordinary numerical ranges in which its exponentiation remains finite and its large terms do not suffer destabilizing cancellation. It is not a required oracle for extreme interest rates, where exponentiation may overflow or cancellation between large terms may make the closed form numerically unstable. A closed-form overflow or unstable comparison in such an extreme case does not authorize changing the recurrence and does not make the closed form authoritative. The implementation itself must always use the monthly recurrence; the closed form must never replace it.

### Exact balance at contractual maturity

Ordinary floating-point evaluation of the recurrence above at `m = N` (full contractual maturity) does not always land on exactly `0.0`; it can be a tiny positive or tiny negative value purely from floating-point rounding (observed magnitude in the golden case below: `1.1059455573558807e-07` against a `~32.5 million` starting balance, roughly 1 part in `10^14`). Phase 0 states "the fully amortized balance after payment `N` is zero" as an exact mathematical fact of how `PMT` is derived (an infinite-precision evaluation of the recurrence always reaches exactly `0` at `m = N`, by construction of the annuity formula). The following deterministic treatment reconciles the mathematical fact with floating-point reality, without inventing cent rounding or a general clamping policy:

> At contractual maturity, after payment `N`, `B_N := 0.0`. This is the mathematical identity of a fully amortizing loan and applies only at that single contractual-maturity point.

Consequently:

- The month-`N` recurrence is executed through `Interest_N`, `Principal_N`, and raw `Ending Balance_N`, with the immediate finiteness checks specified below. Only after those required month-`N` quantities are finite is the contractual identity `B_N := 0.0` applied.
- This identity is not a general balance clamp. It must not be applied to any month `m < N`, whether by sign, magnitude, cents, or tolerance. Every pre-maturity balance uses the actual recurrence result exactly as computed.
- The maturity identity must not be used to hide or suppress earlier material numerical drift, and it never excuses a non-finite intermediate. All pre-maturity recurrence values remain unadjusted and subject to their required immediate finiteness checks; no additional tolerance-based drift rule is introduced.
- Whenever `min(H * 12, N) = N` (i.e. `A <= H`, meaning the loan reaches maturity by the sale date), `remaining_loan_balance = 0.0` exactly by the contractual-maturity identity. For month `N + 1` and every later month, `Monthly Payment_t = 0`, no additional amortization recurrence is performed, and the exit balance selected by `B_min(12H, N)` remains `B_N = 0.0`.
- Whenever `min(H * 12, N) < N` (i.e. `A > H`, so exit occurs before maturity), `remaining_loan_balance` is the actual recurrence result at month `H * 12`, used as-is with no maturity adjustment.

No cent rounding, tolerance-based monthly balance clamping, or other balance adjustment is applied anywhere in the amortization schedule.

### Phase 2B non-finite detection granularity

Phase 2B must check finiteness immediately after each required calculated debt quantity at which a non-finite value could arise, including, as applicable:

- `monthly_rate`, immediately after it is calculated (Branch 2's `0.0`, or Branch 3's `interest_rate / 12`). `monthly_rate == 0.0` in Branch 3 (Branch 3a, the monthly-rate-underflow case) is finite by construction and is not a failure; it routes to `PMT = loan_amount / N` as documented above, not to `NonFiniteResultError`;
- for Branch 3b (positive, representable monthly rate) specifically: `log_growth` immediately after `log1p(r)`; `discount_exponent` immediately after `-N * log_growth` (or after the required `OverflowError` catch described below), subject to the documented `-inf` exception below; `payment_denominator` immediately after `-expm1(discount_exponent)`; and `rate_fraction` immediately after `r / payment_denominator`;
- `monthly_debt_service` (`PMT`), immediately after the applicable branch's payment formula (Branch 1's `0.0` is finite by construction and requires no check; Branch 2, Branch 3a, and Branch 3b are each checked);
- every `Interest_t`, immediately after it is calculated;
- every `Principal_t`, immediately after it is calculated;
- every raw `Ending Balance_t`, immediately after it is calculated and before it is carried forward or the contractual-maturity identity is applied;
- every annual debt-service total (`ADS_y`), immediately after its chronological monthly summation completes; and
- `remaining_loan_balance` at exit, immediately after the applicable recurrence balance or contractual-maturity value is selected.

**Documented exception:** `discount_exponent = -inf` is not a finiteness failure when it arises from either of the two deterministically defined cases described in the "Loan structure" section above: (1) `N * log_growth` overflowing to `+inf` under ordinary IEEE-754 float multiplication, or (2) a raw `OverflowError` raised while converting/multiplying an extremely large `N` — provided `N > 0`, `log_growth > 0`, and both source quantities are otherwise valid — which must be caught and deterministically mapped to `discount_exponent = -inf` rather than allowed to propagate. In either case `expm1(-inf) = -1.0`, so `payment_denominator = 1.0` (finite) and `rate_fraction = r` (finite). Every other non-finite value at any of the checkpoints above — including `discount_exponent = +inf` or `discount_exponent = NaN`, and including any `OverflowError` that does not satisfy the case-2 preconditions above — is a finiteness failure.

If evaluating one of these required quantities overflows or produces `NaN`, positive infinity, or negative infinity (other than the single documented `discount_exponent = -inf` exception, in either of its two forms), the engine must raise the approved `NonFiniteResultError` immediately, rather than allowing a raw `ZeroDivisionError`, `OverflowError`, `NaN`, or infinity to leak out as an undocumented result. It must not continue the schedule or wait until `AcquisitionResults` assembly. No required quantity is silently clamped or rounded to avoid the check. This requirement does not reclassify valid `None` values from later return-metric phases as numerical failures: the frozen `None`/"N/A" conventions for IRR, DSCR, and Equity Multiple remain unchanged.

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

For debt calculations specifically, the exact recurrence operation order, extreme-rate numerical behavior, contractual-maturity identity, chronological ADS summation order, and immediate finiteness checks in Phase 2B govern. Implementations must not introduce cent rounding, tolerance-based balance clamping, or a silent higher-precision substitute. For the positive-rate `PMT` denominator specifically, the frozen `log1p`/`expm1` stable evaluation in Phase 2B governs over the naive `1 - (1 + r) ** (-N)` expression, for the numerical-stability reasons stated there; this is not a precision upgrade (no `Decimal` or arbitrary-precision arithmetic is introduced), only a different IEEE-754 evaluation order of the same frozen formula. For the positive-rate `PMT` numerator specifically, the frozen divide-first order (`rate_fraction = r / payment_denominator`, then `PMT = loan_amount * rate_fraction`) governs over the multiply-first order (`(loan_amount * r) / payment_denominator`), because multiplying first can underflow to `0.0` for a small-but-finite `loan_amount` even when the true `PMT` is finite and nonzero; this is likewise a different IEEE-754 evaluation order of the same frozen formula, not a precision upgrade. A positive annual `interest_rate` whose derived `monthly_rate` itself underflows to `0.0` is treated as the documented Branch 3a numerical-boundary case (`PMT = loan_amount / N`), not as a zero-interest input and not as a finiteness failure.

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

All existing Phase 2A tests and rules remain required and unchanged by this Phase 2B specification patch.

**NOI** (`noi.py`): `H = 1`; zero NOI Growth; positive NOI Growth; negative NOI Growth `> -1`; `Current NOI = 0`; Occupancy has no effect on any `NOI_y` regardless of its value.

**Going-in cap** (`noi.py`): ordinary case; `Current NOI = 0` (result is `0.0`, not an error, not `None`).

**Debt** (`debt.py`) must include all of the following Phase 2B coverage:

- leverage boundaries: `LTV = 0` and `LTV = 1`;
- a **required zero-loan payment regression test**: `ltv = 0` (so `loan_amount = 0.0`) combined with an ordinary nonzero `interest_rate`, proving `PMT = 0.0` is produced by Branch 1 without evaluating any positive-interest denominator, with no `0 / 0` path reachable, and with `PMT = 0.0` regardless of the (nonzero) interest rate supplied;
- rate cases: zero interest; ordinary positive interest; very large but finite permitted interest (without imposing a new Interest Rate input bound or substituting higher-precision arithmetic); and a **required very-small positive interest rate regression test**, where the annual `interest_rate` is small enough that `monthly_rate > 0.0` but a naive `1.0 + monthly_rate` evaluates to exactly `1.0` under IEEE-754 double precision. This test must prove: the rate is still treated as strictly positive (Branch 3b is taken, not Branch 2); no `ZeroDivisionError` occurs; the stable `log1p`/`expm1` positive-rate formula is used rather than the naive `1 - (1 + r) ** (-N)` expression; the resulting `PMT` is finite; `PMT` approaches the zero-rate payment `loan_amount / N` as the rate approaches zero; and the rate is never silently converted to `0.0` internally;
- a **required positive-annual-rate, monthly-rate-underflow regression test** (Branch 3a): a positive finite annual `interest_rate` small enough that IEEE-754 division by `12` underflows to exactly `monthly_rate == 0.0` — for example, `interest_rate = 5e-324` (the smallest positive representable `float`), which satisfies `interest_rate > 0.0` while `interest_rate / 12 == 0.0`. With `loan_amount = 32_500_000.0` and `N = 360`, this test must prove: `interest_rate > 0.0` on entry; `monthly_rate == 0.0` arises solely from underflow, not from a zero-rate input; `PMT == loan_amount / N == 90277.77777777778`; no arithmetic exception (in particular no `ZeroDivisionError`) occurs; and the branch taken is documented as the positive-rate numerical-limit case (Branch 3a), not Branch 2;
- a **required underflow-safe PMT numerator regression test** (Branch 3b): a fixture where `loan_amount` is finite and small, `monthly_rate` is positive and representable, `loan_amount * monthly_rate` would itself underflow to `0.0` under naive multiply-then-divide evaluation, but `monthly_rate / payment_denominator` remains representable — for example, `loan_amount = 1e-300`, `interest_rate = 1.2e-24` (so `monthly_rate = interest_rate / 12 == 9.999999999999999e-26`), `amortization = 30` (`N = 360`). Under this fixture, `loan_amount * monthly_rate` rounds to exactly `0.0` (a naive multiply-first implementation would therefore return `PMT = 0.0`), while the frozen divide-first order yields `rate_fraction = 0.002777777777777778` and `PMT = 2.777777777777778e-303` — finite and close to `loan_amount / N = 2.7777777777777778e-303`. The test must assert this exact finite, nonzero `PMT` and must fail if the implementation reverts to computing `(loan_amount * monthly_rate) / payment_denominator`;
- amortization/hold orderings: `A < H`, `A = H`, and `A > H`;
- month boundaries: month `1`, month `12`, month `13`, month `N`, and month `N + 1`, with month `N + 1` verifying `Monthly Payment_(N+1) = 0` and that no post-maturity recurrence is performed;
- exact contractual maturity after payment `N`, including `B_N = 0.0` exactly;
- actual recurrence balances before maturity, with no cent rounding or tolerance-based balance clamping for any `m < N`;
- annual debt-service aggregation with exactly 12 scheduled payments per active amortization year, zero ADS after maturity, and no partial amortization-ending year under the POC V1 input domain;
- a **required regression test proving `ADS_y` is computed by chronological summation of the 12 monthly `Monthly Payment_t` values**, not by an independently computed `12 * PMT` expression. This test must use an actual fixture in which chronological addition of a `Monthly Payment_t` value 12 times and `12 * Monthly Payment_t` produce different IEEE-754 results — for example, `Monthly Payment_t = 268729.3538605583`: summing it 12 times chronologically yields `3224752.2463267003`, while `12 * 268729.3538605583` yields `3224752.2463267` — a real difference of `4.656612873077393e-10` in the last bits. The test must assert the chronological-summation result (`3224752.2463267003`), not the `12 *` shortcut, and must continue to cover zero leverage, active years, years after maturity, and all three `A < H` / `A = H` / `A > H` orderings;
- recurrence-versus-closed-form comparison within an explicit tolerance only for ordinary numerical ranges where the closed form is finite and stable, with no required closed-form oracle comparison for extreme rates;
- a non-finite monthly or other required debt intermediate raising `NonFiniteResultError` immediately, including for `log_growth`, `discount_exponent` (other than the documented `-inf` exception, in either of its two forms), `payment_denominator`, and `rate_fraction` in the positive-rate branch;
- a **required affirmative regression test for the permitted `discount_exponent == -inf` path** covering both documented forms: (1) ordinary float-multiplication overflow — e.g. `interest_rate = 1e300` (so `monthly_rate = 8.333333333333334e+298`, `log_growth = 688.2906212484257`) with `amortization = 3 * 10**305` (so `N = amortization * 12 = 3.6e306` as an integer, still convertible to `float` without error since it is below the ~`1.8e308` `float` maximum) makes `N * log_growth` overflow to `+inf` under ordinary float multiplication, producing `discount_exponent == -inf` with no exception raised; and (2) a raw `OverflowError` raised while converting an extremely large `N` to `float` (e.g. `amortization = 10**400`, so `N = amortization * 12` is itself far beyond the `float` maximum), which the implementation must catch and deterministically map to `discount_exponent = -inf` rather than let propagate. Both fixtures must assert `payment_denominator == 1.0` and a finite resulting `PMT`, and must assert that no raw `OverflowError` escapes the engine in either case; and
- repeated identical calls producing identical results.

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

**Regenerated using the final frozen numerical operation order**: `monthly_rate = interest_rate / 12`; `payment_denominator = -expm1(-N * log1p(monthly_rate))`; `rate_fraction = monthly_rate / payment_denominator`; `PMT = loan_amount * rate_fraction`. This example's `interest_rate = 0.0525` is well within the ordinary representable range, so it exercises Branch 3b (not Branch 3a) — the underflow-safe numerator order still changes the golden `PMT` value in its last bits relative to a prior, superseded multiply-first golden calculation for this same example.

```text
monthly_rate (r)                = 0.0043749999999999995   # 0.0525 / 12
N (scheduled monthly payments)  = 360                       # 30 * 12
log_growth                      = 0.00436545750963998
discount_exponent               = -1.5715647034703928
payment_denominator             = 0.7922800921163993
rate_fraction                   = 0.005522037021418984
monthly_debt_service (PMT)      = 179466.20319611699

annual_debt_service = (
    2153594.438353404,   # ADS_1
    2153594.438353404,   # ADS_2
    2153594.438353404,   # ADS_3
    2153594.438353404,   # ADS_4
    2153594.438353404,   # ADS_5
)
```

All five years are identical because `A = 30 > H = 5`, so every modeled year is fully within the amortization period (each `ADS_y` is the chronological sum of 12 active `PMT` payments, mathematically equal to `12 * PMT` for all `y in 1..5` but not computed as that expression).

Illustrative intermediate amortization points, for validating an independent recurrence implementation (not part of `AcquisitionResults`):

```text
Beginning Balance_1 (= loan_amount) = 32500000.0
Interest_1                          = 142187.49999999997
Principal_1                         = 37278.703196117014
Ending Balance_1 (balance after month 1)   = 32462721.296803884
Ending Balance after month 12               = 32041732.801682245
Ending Balance after month 24               = 31558819.12881365
Ending Balance after month 60 (= B_exit)    = 29948583.641211268
Ending Balance after month 120              = 26633190.900727846
Ending Balance after month 359              = 178684.4586894612
Ending Balance after month 360 (raw recurrence, before the
  contractual-maturity B_N := 0.0 identity is applied) = 1.1059455573558807e-07
```

```text
remaining_loan_balance = 29948583.641211268       # B_exit = B_60 (min(12*5, 360) = 60)
```

### Exit and sale proceeds

```text
exit_value        = 52694276.10454546      # 2898185.18575 / 0.055 (unchanged: no debt dependency)
net_sale_proceeds = 22745692.46333419      # exit_value - remaining_loan_balance
```

### Cash flows

```text
unlevered_cash_flows = (
    -50000000.0,
    2500000.0,
    2575000.0,
    2652250.0,
    2731817.5,
    55508048.12954546,     # NOI_5 + exit_value (unchanged: no debt dependency)
)

levered_cash_flows = (
    -17500000.0,
    346405.56164659606,
    421405.56164659606,
    498655.56164659606,
    578223.0616465961,
    23405870.04998079,    # NOI_5 - ADS_5 + net_sale_proceeds
)
```

### DSCR

```text
dscr_by_year = (
    1.1608499518189,
    1.195675450373467,
    1.231545713884671,
    1.2684920853012112,
    1.3065468478602478,
)
headline_dscr = 1.1608499518189
```

### Equity Multiple

```text
sum of positive levered cash flows = 25250559.79656717
sum of negative levered cash flows = -17500000.0
equity_multiple = 1.44288913123241
```

### IRR

```text
unlevered_irr = 0.062414943980353854      # unchanged: no debt dependency
levered_irr   = 0.07913030056780745       # unchanged at full float precision: the debt-driven
                                            # perturbation to levered_cash_flows is too small to move
                                            # the deterministic bisection procedure's converged x_star
```

Both IRR values were produced by the exact transformation, Horner-evaluated reduced polynomial, bracket-expansion, and 256-iteration bisection procedure specified above and in `docs/financial_conventions.md` — no external solver was used. An independent implementation following the same procedure with the same tolerances is expected to reproduce these values to full `float` precision, since the bisection procedure is itself deterministic and bit-reproducible given identical inputs and IEEE-754 arithmetic. `unlevered_irr`, `going_in_cap_rate`, `noi_by_year`, `exit_noi`, `exit_value`, and every `unlevered_cash_flows` entry are unchanged from any prior golden calculation for this example, because none of them depend on debt; only debt-dependent values (`monthly_debt_service`, `annual_debt_service`, the amortization checkpoints, `remaining_loan_balance`, `net_sale_proceeds`, `levered_cash_flows`, `dscr_by_year`, `headline_dscr`, `equity_multiple`) were regenerated. `levered_irr` is also numerically unchanged at full `float` precision in this particular example, since the debt-order perturbation is too small to change which bisection interval the 256-iteration procedure converges to; this is a property of this specific example, not a general guarantee that `levered_irr` is always insensitive to the PMT operation order.

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
- `monthly_debt_service` (`PMT`) is calculated via three ordered branches, checked in this order and based on the original annual `interest_rate`: (1) zero loan amount (`loan_amount == 0.0` → `PMT = 0.0`, returned before any positive-rate denominator is evaluated, regardless of `interest_rate`); (2) zero interest rate (`interest_rate == 0.0` → `monthly_rate = 0.0`, `PMT = loan_amount / N`); (3) positive interest rate (`interest_rate > 0.0`), which itself has two sub-cases: (3a) the derived `monthly_rate` underflows to exactly `0.0` under IEEE-754 division by `12` even though `interest_rate > 0.0` — `PMT = loan_amount / N`, the positive-rate numerical limit, documented as distinct from Branch 2 even though numerically identical, is not a financial reclassification as zero-interest, and never raises `ZeroDivisionError`; and (3b) `monthly_rate > 0.0` is representable, using the stable positive-rate formula below. This ordering is frozen and is not a change to Phase 0 economics — it makes the already-implied zero-loan identity, and the monthly-rate-underflow numerical limit, explicit, first-checked branches rather than incidental consequences of substitution.
- For Branch 3b (representable positive `monthly_rate`), the `PMT` denominator is evaluated using the frozen numerically stable expression (`log_growth = log1p(r)`, `discount_exponent = -N * log_growth`, `payment_denominator = -expm1(discount_exponent)`), never the naive `1 - (1 + r) ** (-N)` expression, because a genuinely positive but extremely small `r` can satisfy `1.0 + r == 1.0` under IEEE-754 double precision, which would otherwise produce a zero denominator. The numerator is then evaluated divide-first: `rate_fraction = r / payment_denominator`, `PMT = loan_amount * rate_fraction` — never `(loan_amount * r) / payment_denominator`, because that multiply-first order can underflow `loan_amount * r` to exactly `0.0` for a small-but-finite `loan_amount` even when the true `PMT` is finite and nonzero. Both orderings are algebraically equivalent evaluations of the same frozen Phase 0 formula; no minimum positive interest rate is imposed, no positive rate is silently converted to `0`, and no `Decimal`/arbitrary-precision arithmetic is introduced. `discount_exponent = -inf` is a deterministically defined case, not a finiteness failure, when it arises either from ordinary `N * log_growth` float-multiplication overflow, or from a raw `OverflowError` raised while converting/multiplying an extremely large `N` (caught and mapped to `discount_exponent = -inf`, provided `N > 0`, `log_growth > 0`, and both source quantities are otherwise valid) — in both cases `expm1(-inf) = -1.0` exactly, so `payment_denominator = 1.0` and `rate_fraction = r`. No other `OverflowError`, and no other non-finite `discount_exponent`, is covered by this exception.
- `annual_debt_service[y-1]` (`ADS_y`) is computed by chronological summation of the 12 monthly `Monthly Payment_t` values for that hold year, in month order — never as an independently computed `12 * PMT` expression, even for a fully active year where the two are mathematically equal, because repeated IEEE-754 addition and a single multiplication by `12` can differ in the last bits. This divergence is required to be demonstrated by an actual fixture in tests, not merely asserted as a theoretical possibility.
- The month-by-month amortization recurrence is the authoritative Phase 2 implementation path for loan balances. Every month must calculate `Interest_t`, then `Principal_t`, then `Ending Balance_t`, and then carry that ending balance forward, exactly as written in Phase 2B; no algebraically equivalent expression may replace that frozen operation order.
- Amortization is a positive whole number of years, so contractual maturity always occurs after payment `N` at a year boundary. Every active amortization year has 12 scheduled payments (summed chronologically), every modeled year after maturity has zero ADS, and no partial amortization-ending year is reachable under the POC V1 input domain.
- The closed-form `B_m` formula is only a test/reference oracle for ordinary numerical ranges where it is finite and stable. It is not required for extreme-rate comparisons and must never replace the authoritative recurrence.
- `B_N` is assigned exactly `0.0` only at contractual maturity after payment `N`, by the mathematical identity of a fully amortizing loan and only after all raw month-`N` quantities pass their immediate finiteness checks. It is not a general clamp, is never applied before `N`, and must not hide earlier material numerical drift. A pre-maturity exit uses the actual recurrence balance without adjustment.
- Extremely large but finite permitted Interest Rates may cause unchanged or nearly unchanged pre-maturity recurrence balances because of IEEE-754 representational precision. This numerical behavior does not change the debt convention, impose a new rate bound, authorize higher-precision arithmetic, or displace the `B_N := 0.0` maturity identity.
- Required debt finiteness checks occur immediately after the monthly rate (where `monthly_rate == 0.0` under Branch 3a is finite by construction and not a failure); for Branch 3b, `log_growth`, `discount_exponent`, `payment_denominator`, and `rate_fraction`; the monthly payment; each monthly interest, principal, and raw ending balance; each annual debt-service total; and the exit remaining balance, as applicable. A non-finite required debt quantity raises `NonFiniteResultError` immediately rather than waiting for `AcquisitionResults` assembly, and no raw `ZeroDivisionError`, `OverflowError`, `NaN`, or infinity is ever allowed to leak out as an undocumented result. The single documented exception, in either of its two forms (ordinary float-multiplication overflow, or a caught `OverflowError` while converting/multiplying an extremely large `N`), is `discount_exponent = -inf` arising from extreme `amortization`/`interest_rate` overflow, which is deterministically defined (`payment_denominator = 1.0`) and is not treated as a failure.
- Non-finite intermediate or output values outside the fields with a frozen `None`/"N/A" convention (`unlevered_irr`, `levered_irr`, `dscr_by_year` entries, `headline_dscr`, `equity_multiple`) cause the engine to fail explicitly rather than return a partially non-finite `AcquisitionResults`; valid later-phase `None` metrics remain valid and are not numerical failures. This is an implementation safety rule, not a change to Phase 0 economics.
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
