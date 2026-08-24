# Mini-Anchor POC V1 Financial Conventions

## Purpose

This document defines and freezes the financial conventions for Mini-Anchor POC V1. It is the Phase 0 specification for the deterministic acquisition engine. The engine, rather than AI, is the authoritative source for every financial calculation described here.

## Terminology

The POC V1 core inputs and formula symbols are:

| Term | Symbol | Definition |
| --- | --- | --- |
| Purchase Price | `P` | Property purchase price. |
| Current NOI | `NOI_current` | Current annual in-place net operating income after vacancy and operating expenses, but before debt service. |
| Occupancy | `O` | Informational occupancy input. It does not modify NOI in POC V1. |
| NOI Growth | `g` | Annual NOI growth rate. |
| Hold Period | `H` | Hold period in years. |
| Exit Cap Rate | `c_exit` | Capitalization rate applied to forward NOI to calculate Exit Value. |
| LTV | `LTV` | Loan-to-value ratio applied to Purchase Price. |
| Interest Rate | `i` | Annual fixed interest rate. |
| Amortization | `A` | Loan amortization period in years. |
| Loan Amount | `L` | Initial loan principal. |
| Monthly Debt Payment | `PMT` | Fixed scheduled monthly principal-and-interest payment. |
| Annual Debt Service | `ADS_y` | Sum of scheduled monthly debt payments in hold year `y`. |
| Remaining Loan Balance | `B_m` | Loan principal remaining after scheduled monthly payment `m`. |
| Exit Value | `V_exit` | Gross property value at the end of the final hold year. |
| Initial Equity | `E_0` | Purchase Price less Loan Amount. |

All percentage inputs—Occupancy, NOI Growth, Exit Cap Rate, LTV, and Interest Rate—are represented internally as decimal fractions. For example, 5% is represented as `0.05`. Hold Period and Amortization are expressed in years.

## Input Domains

All nine POC V1 inputs must satisfy the following domains before any financial calculations are performed:

1. **Purchase Price (`P`)** must be a finite numeric value strictly greater than `0`.
2. **Current NOI (`NOI_current`)** must be a finite numeric value greater than or equal to `0`.
3. **Occupancy (`O`)** must be a finite decimal fraction satisfying `0.0 <= O <= 1.0`. Occupancy is informational only in POC V1 and must never be multiplied into Current NOI or forecast NOI.
4. **NOI Growth (`g`)** must be a finite decimal fraction strictly greater than `-1.0`. POC V1 imposes no additional hard upper bound. Unusually large positive values may generate validation warnings in a later phase, but warnings are outside this Phase 0 specification.
5. **Hold Period (`H`)** must be a positive whole number of years satisfying `H >= 1`.
6. **Exit Cap Rate (`c_exit`)** must be a finite decimal fraction strictly greater than `0`.
7. **LTV (`LTV`)** must be a finite decimal fraction satisfying `0.0 <= LTV <= 1.0`. An LTV of `1.0`, or 100%, is permitted.
8. **Interest Rate (`i`)** must be a finite decimal fraction greater than or equal to `0`.
9. **Amortization (`A`)** must be a positive whole number of years satisfying `A >= 1`. Therefore, `N = 12 * A` is always a positive whole number of months.

## Exact Formula Definitions

### NOI forecast and going-in cap rate

Current NOI already reflects vacancy. Occupancy is therefore informational only and must not be multiplied by Current NOI or any forecast NOI.

For hold year `y`, where `1 <= y <= H`:

```text
NOI_1 = NOI_current
NOI_y = NOI_current * (1 + g)^(y - 1)
```

Year 1 NOI equals Current NOI, and growth begins in Year 2.

Going-in cap rate is:

```text
Going-In Cap Rate = Current NOI / Purchase Price
                  = NOI_current / P
```

Going-In Cap Rate is a deterministic, engine-calculated informational acquisition metric. It does not itself drive another POC V1 calculation and is not an additional input.

### Loan and debt service

The loan amount and initial equity are:

```text
L   = P * LTV
E_0 = P - L
```

The debt is fixed-rate and fully amortizing. Define the monthly interest rate and total number of scheduled monthly payments as:

```text
r = i / 12
N = A * 12
```

For a nonzero monthly interest rate, the fixed monthly payment is:

```text
PMT = L * r / (1 - (1 + r)^(-N))
```

For a zero monthly interest rate, the fixed monthly payment is:

```text
PMT = L / N
```

`N = A * 12` is 12 times Amortization in years, and `PMT` is the scheduled monthly loan payment. For month `t`, the payment schedule is:

```text
Monthly Payment_t = PMT    for 1 <= t <= N
Monthly Payment_t = 0      for t > N
```

Annual debt service for hold year `y` equals the sum of the scheduled monthly payments falling within that hold year:

```text
ADS_y = sum of Monthly Payment_t
        for t = 12(y - 1) + 1 through 12y
```

Because Amortization and Hold Period are whole numbers of years, every modeled hold year through year `A` contains 12 scheduled monthly payment positions, so `ADS_y = 12 * PMT` for `1 <= y <= min(H, A)`. For any modeled hold year `y > A`, the loan has fully amortized and `ADS_y = 0`.

For a nonzero monthly interest rate, the remaining balance after `m` scheduled monthly payments, where `0 <= m <= N`, is:

```text
B_m = L * (1 + r)^m - PMT * ((1 + r)^m - 1) / r
```

For a zero monthly interest rate:

```text
B_m = L - m * PMT
```

The fully amortized balance after payment `N` is zero. The remaining balance at exit is the balance after every scheduled monthly payment through the hold period has been applied:

```text
B_exit = B_min(12H, N)
```

### Exit value

The property is sold at the end of hold year `H`. Exit Value uses next-twelve-month forward NOI after the final hold year:

```text
NOI_(H + 1) = NOI_current * (1 + g)^H
             = NOI_H * (1 + g)

V_exit = NOI_(H + 1) / c_exit
```

`NOI_(H + 1)` is used to calculate Exit Value; it is not an additional operating cash flow during the hold.

## Cash-Flow Timing

Cash flows are annual periodic cash flows at times `0` through `H`.

- Time `0` is acquisition.
- Each time `y` from `1` through `H` represents the corresponding hold year.
- The final scheduled monthly debt payments through hold year `H` are applied before the remaining balance at exit is determined.
- The sale occurs at the end of hold year `H`, and sale proceeds are included in the time-`H` cash flow.

Acquisition costs and sale costs are both zero in POC V1.

### Unlevered cash flows

```text
UCF_0 = -P

UCF_y = NOI_y                         for 1 <= y < H

UCF_H = NOI_H + V_exit
```

### Levered cash flows

```text
LCF_0 = -E_0 = -(P - L)

LCF_y = NOI_y - ADS_y                 for 1 <= y < H

LCF_H = NOI_H - ADS_H + V_exit - B_exit
```

## Boundary Consistency

The POC V1 input domains establish the following boundary behavior:

- Because `H >= 1`, `UCF_0` and `LCF_0` refer only to acquisition at time `0`, operating-period cash flows begin at Year `1`, and final-year operating and sale cash flows occur at Year `H`. No `H = 0` case exists in POC V1.
- Because `c_exit > 0`, Exit Value is always mathematically defined.
- Because `A >= 1`, `N = 12 * A` is always a positive whole number of months, and the `PMT` and loan-balance formulas are never evaluated with `N = 0`.

## Debt Conventions

- Debt is fixed-rate and fully amortizing.
- The monthly rate is the annual Interest Rate divided by 12.
- The number of scheduled monthly payments is Amortization in years multiplied by 12.
- Debt service is calculated monthly and summed by hold year.
- The exit loan balance is calculated after all scheduled monthly payments through the hold period.
- POC V1 has one debt tranche and no refinancing.

## Exit Conventions

- The property is sold at the end of the final hold year.
- Exit Value is based on next-twelve-month forward NOI after the final hold year, divided by Exit Cap Rate.
- Sale costs are zero, so gross Exit Value is included in the unlevered final-year cash flow.
- Levered final-year sale proceeds equal Exit Value less the remaining loan balance.

## Return Conventions

### DSCR

Year-by-year DSCR and headline DSCR are:

```text
DSCR_y = NOI_y / ADS_y    if ADS_y > 0
DSCR_y = N/A              if ADS_y = 0

Headline DSCR = DSCR_1
```

This rule applies regardless of why scheduled debt service is zero, including zero leverage or a fully amortized loan.

### IRR validity

IRR uses annual periodic cash flows. When evaluating an applicable cash-flow series `CF_0` through `CF_H` for IRR, zero cash flows are ignored for sign-change analysis only; all cash flows retain their original annual time indices in the NPV calculation. The nonzero cash-flow sequence must satisfy all of the following conditions:

- it contains at least one negative cash flow and at least one positive cash flow;
- its first nonzero cash flow is negative; and
- it has exactly one sign change.

If any of these conditions is not satisfied, IRR is reported as `N/A` for POC V1. This convention intentionally avoids selecting among multiple mathematically valid IRRs for non-conventional cash-flow streams.

The same annual periodic convention and validity rules apply to the unlevered cash-flow series and the levered cash-flow series.

### IRR numerical solution

For a valid conventional cash-flow series, solve:

```text
NPV(r) = sum from t = 0 through H of CF_t / (1 + r)^t = 0
```

for `r > -1`. Within this subsection, `r` is the candidate annual periodic IRR and is distinct from the monthly interest-rate symbol `r` in the debt formulas.

Use the transformation:

```text
x = 1 / (1 + r)
r = (1 / x) - 1
```

For `r > -1`, `x > 0`. Substituting `x` into the IRR equation gives:

```text
0 = sum from t = 0 through H of CF_t * x^t
```

The IRR validity rules in the preceding subsection remain unchanged: ignore zero cash flows when evaluating sign changes; require at least one negative and one positive nonzero cash flow; require the first nonzero cash flow to be negative; and require exactly one sign change in the nonzero sequence. Otherwise, IRR is `N/A` for POC V1.

For a valid series, the deterministic transformation-based bracket-and-bisection procedure is:

1. Let `t0` be the index of the first nonzero cash flow.
2. Factor out `x^t0`.
3. Define the reduced polynomial over all `t` from `t0` through the final cash-flow period:

   ```text
   F(x) = sum from t = t0 through H of CF_t * x^(t - t0)
   ```

4. Because the first nonzero cash flow is negative and the permitted nonzero sequence has exactly one sign change, `F(x)` has one positive real root for `x > 0`.

Every required evaluation of `F(x)` must use Horner's method over the reduced polynomial coefficients in descending exponent order. For a candidate `x`, evaluate:

```text
horner_value = CF_H

for t = H - 1 down through t0:
    horner_value = horner_value * x + CF_t

F(x) = horner_value
```

The initial `horner_value`, every updated `horner_value`, and the resulting `F(x)` must be finite. If any of them is NaN, positive infinity, negative infinity, or any other non-finite numeric result, the evaluation has failed and IRR is reported as `N/A` for POC V1. The result of an `F(x)` evaluation must pass this finiteness requirement before it is used for an exact-root check, a tolerance check, or a positive-or-negative sign comparison.

This rule applies to every required `F(x)` evaluation during initial bracket evaluation, upper-bound expansion, exact-root checks, and bisection iterations. A non-finite evaluation is a numerical-support failure, not evidence of a positive or negative polynomial sign. The solver must not infer a bracket direction from positive infinity, negative infinity, NaN, or any other non-finite value.

Financial validity and numerical support are separate determinations. A cash-flow series is financially valid for POC V1 when it satisfies the sign rules above and therefore has a unique positive `x` root mathematically. The POC V1 numerical implementation intentionally searches for that root only within:

```text
0 < x <= 1e12
```

A mathematically valid root that requires `x > 1e12` is outside the supported POC V1 numerical search domain, so IRR is reported as `N/A`. A mathematically valid series also returns IRR as `N/A` if ordinary floating-point evaluation cannot produce a finite result for every required Horner evaluation within the supported procedure. These numerical-support limits are intentional and deterministic; they are not additional financial-validity rules.

Use the following bracketing procedure:

1. Set:

   ```text
   x_low  = 0
   x_high = 1
   ```

2. Evaluate:

   ```text
   f_low  = F(x_low)
   f_high = F(x_high)
   ```

   Evaluate both values using the required Horner method. If either evaluation produces a non-finite result, report IRR as `N/A` immediately, before any exact-root or sign comparison.
3. After `f_low` passes the finiteness requirement, the valid-series rules imply `f_low < 0`: the first term of the reduced polynomial is the first nonzero cash flow, so `F(0)` is finite and negative.
4. If `f_high == 0`, set `x_star = x_high` and proceed directly to conversion back to IRR. Do not enter bisection.
5. While `f_high < 0`:

   a. If `x_high >= 1e12`, report IRR as `N/A` because the root is outside the supported POC V1 numerical search domain.

   b. Otherwise, set:

      ```text
      x_high = min(2 * x_high, 1e12)
      ```

   c. Immediately evaluate:

      ```text
      f_high = F(x_high)
      ```

      Use the required Horner method.

   d. If the evaluation of `f_high` produces a non-finite result, report IRR as `N/A` immediately. Do not use that result as a sign or infer a bracket direction from it.

   e. If `f_high == 0`, set `x_star = x_high` and proceed directly to conversion back to IRR. Do not enter bisection.

6. If the loop ends because `f_high > 0`, the strict bracket is:

   ```text
   F(x_low)  < 0
   F(x_high) > 0
   ```

The boundary `x = 1e12` is evaluated before the solver can return `N/A` for exceeding the supported numerical search domain. An exact root at `x = 1e12` is therefore accepted. If its finite evaluated value is negative, the next loop check returns `N/A`; if it is positive, the strict bracket has been established. If the boundary evaluation is non-finite, IRR is `N/A` under the numerical-support rule above, and no sign or bracket direction is inferred.

Once the strict bracket exists, use bisection on `x` for at most 256 iterations. For each iteration:

1. Compute:

   ```text
   x_mid = (x_low + x_high) / 2
   ```

2. Evaluate:

   ```text
   f_mid = F(x_mid)
   ```

   Use the required Horner method. If the evaluation produces a non-finite result, report IRR as `N/A` immediately. Do not apply an exact-root check, a tolerance check, or a sign comparison to that result.

3. After `f_mid` passes the finiteness requirement, and before modifying either bracket endpoint, check the stopping conditions in this order:

   a. If `f_mid == 0`, set `x_star = x_mid` and stop.

   b. If:

      ```text
      abs(f_mid) <= 1e-10 * max_abs_cash_flow
      ```

      set `x_star = x_mid` and stop.

   c. If:

      ```text
      (x_high - x_low) <= 1e-12 * max(1, abs(x_mid))
      ```

      set `x_star = x_mid` and stop.

   `max_abs_cash_flow` is the largest absolute cash-flow magnitude in the applicable series.

4. Only if no stopping condition was met, update one bracket endpoint:

   - If `f_mid < 0`, set `x_low = x_mid`.
   - If `f_mid > 0`, set `x_high = x_mid`.

5. Continue to the next iteration.
6. If 256 iterations complete without satisfying a stopping condition, set:

   ```text
   x_star = (x_low + x_high) / 2
   ```

   provided `x_star` is finite and strictly greater than zero. Otherwise, report IRR as `N/A`.

Once `x_star` has been established, convert it back to the annual periodic IRR:

```text
IRR = (1 / x_star) - 1
```

If `x_star <= 0`, `x_star` is non-finite, the calculated IRR is non-finite, or the calculated IRR is less than or equal to `-1`, report IRR as `N/A`. Otherwise, return the calculated annual periodic IRR.

The deterministic engine, not AI, must calculate IRR. The implementation may use ordinary floating-point arithmetic for POC V1, but it must follow this algorithm and tolerance convention exactly unless this specification is explicitly revised. Ordinary floating-point arithmetic does not guarantee recovery of every mathematically valid IRR for arbitrary finite inputs.

Factoring from the first nonzero index preserves cases in which `CF_0 = 0`, including a possible 100% LTV levered series: `t0` is the index of the actual first nonzero cash flow, and the original spacing between all subsequent annual cash flows remains represented by the exponents in `F(x)`.

Increasingly large positive `x` values correspond to rates increasingly close to `-1`. The transformation avoids imposing a fixed lower search bound directly in rate space, but the POC V1 numerical solver does not cover every mathematically possible `r > -1`: it supports only roots satisfying `0 < x <= 1e12`. A mathematically valid root beyond that range is reported as `N/A` under the intentional numerical-support limit above.

### Equity Multiple

Equity Multiple is calculated from the levered equity cash-flow series:

```text
Equity Multiple = sum(max(LCF_t, 0)) / abs(sum(min(LCF_t, 0)))
                  for t = 0 through H
```

In words, Equity Multiple equals total positive levered equity cash flows divided by the absolute value of total negative levered equity cash flows.

If the denominator equals zero, Equity Multiple is reported as `N/A`. This includes a possible 100% LTV case in which `LCF_0 = 0` and no later levered cash flow is negative, so no negative equity contribution exists. Equity Multiple must not be reported as infinity.

## Numeric Precision and Rounding

The following numeric precision and rounding rules are frozen for POC V1:

- Financial calculations retain full available numerical precision through intermediate calculations.
- Monthly `PMT` is not rounded to cents before being used in loan-balance calculations.
- NOI forecasts are not rounded between years.
- ADS, loan balances, Exit Value, cash flows, IRR, Equity Multiple, DSCR, and other financial outputs are calculated from unrounded intermediate values.
- Rounding is presentation-only.
- UI or CLI display formatting must not alter the underlying stored or calculated value.
- Currency outputs may later be displayed to appropriate dollar precision.
- Percentage outputs may later be displayed to appropriate decimal precision.
- Presentation formatting is outside the authoritative financial calculation.

## Worked Timing Example: Five-Year Hold

For the permitted case `H = 5`, time `0` contains acquisition only, operating cash flows begin in Year `1`, and the final operating and sale cash flows occur in Year `5`. The timing is:

The payment ranges below identify the month positions in each hold year; any month `t > N` has `Monthly Payment_t = 0`.

| Time | NOI used as operating cash flow | Monthly debt payments included | Unlevered cash flow | Levered cash flow | Other event |
| --- | --- | --- | --- | --- | --- |
| `0` | None | None | `-P` | `-(P - L)` | Acquisition. |
| `1` | `NOI_1 = NOI_current` | Payments 1–12 | `NOI_1` | `NOI_1 - ADS_1` | No NOI growth is applied in Year 1. |
| `2` | `NOI_2 = NOI_current * (1 + g)` | Payments 13–24 | `NOI_2` | `NOI_2 - ADS_2` | NOI growth begins. |
| `3` | `NOI_3 = NOI_current * (1 + g)^2` | Payments 25–36 | `NOI_3` | `NOI_3 - ADS_3` | Continue the hold. |
| `4` | `NOI_4 = NOI_current * (1 + g)^3` | Payments 37–48 | `NOI_4` | `NOI_4 - ADS_4` | Continue the hold. |
| `5` | `NOI_5 = NOI_current * (1 + g)^4` | Payments 49–60 | `NOI_5 + V_exit` | `NOI_5 - ADS_5 + V_exit - B_exit` | Apply payments through month 60, determine `B_exit`, and sell at year-end. |

The forward NOI used only for the sale is:

```text
NOI_6 = NOI_current * (1 + g)^5
V_exit = NOI_6 / c_exit
B_exit = B_min(60, N)
```

There is no separate Year 6 operating cash flow.

## Explicit Exclusions

POC V1 excludes:

- acquisition costs;
- sale costs;
- taxes;
- capital expenditures (CapEx);
- tenant improvements (TI);
- leasing commissions (LC);
- refinancing;
- waterfalls; and
- additional debt tranches.

Acquisition costs and sale costs are explicitly set to zero.

## Frozen Decisions

The conventions in this document are frozen for POC V1. In particular:

- all nine POC V1 input domains, including their finiteness, whole-number, and boundary requirements, are frozen exactly as specified in the Input Domains section; this includes permitting 100% LTV and imposing no additional hard upper bound on NOI Growth;
- Occupancy is informational and must never be multiplied into Current NOI or forecast NOI;
- Year 1 NOI equals Current NOI, NOI growth starts in Year 2, and terminal value uses forward NOI;
- time `0` contains acquisition only, operating cash flows begin at Year `1`, and the final operating and sale cash flows occur at Year `H`;
- debt is calculated monthly using the stated payment, annual debt-service, and remaining-balance conventions;
- DSCR is `N/A` whenever `ADS_y = 0`, regardless of the reason;
- Equity Multiple uses all positive and negative levered equity cash flows as specified and is `N/A`, never infinity, when its denominator is zero;
- financial calculations use unrounded intermediate values, and rounding is presentation-only; and
- IRR uses annual periodic cash flows, ignores zeros for sign-change analysis, applies the stated conventional-series validity conditions, is `N/A` when those conditions fail, evaluates the reduced polynomial with the stated Horner method, treats any non-finite `F(x)` evaluation as a numerical-support failure that returns `N/A` without inferring a sign, searches only the supported numerical domain `0 < x <= 1e12` while evaluating the inclusive upper boundary before returning `N/A`, reports `N/A` for a mathematically valid root outside that numerical domain, and uses the stated deterministic transformation-based bracket-and-bisection procedure, iteration limit, and stopping tolerances.

Implementations must not reinterpret or silently change these decisions. The deterministic engine, not AI, is authoritative for all calculations.

## Questions Deferred Beyond POC V1

The following questions are intentionally unanswered in POC V1:

- Whether Occupancy should affect forecast NOI in a future version.
- Whether and how acquisition costs or sale costs should be modeled in a future version.
- Whether and how taxes, CapEx, TI, LC, refinancing, waterfalls, or additional debt tranches should be modeled in a future version.

No answer to these questions is assumed by POC V1.
