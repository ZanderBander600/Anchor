---
title: "Lease-Level Underwriting — D3 Expense Recovery Conventions"
gate: D3.0
status: Awaiting human financial review
supersedes: nothing
governed_by:
  - docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md
  - docs/plans/2026-09-05-anchor-lease-level-underwriting-d2-rollover-conventions.md
---

# Lease-Level Underwriting — D3 Expense Recovery Conventions

## Status

**Architecture and financial-convention gate only. No production code, no test,
no change to `src/anchor/leasing/`, no change to D1 or D2 economics.**

Verified baseline (`main` @ `175af87`, PR #16): full leasing 1436 passed, full
backend 3209 passed, D1 787 passed, architecture guardrails 82 passed, Quick 217
and Detailed 62 passed. `anchor.leasing` remains dark to the rest of Anchor.

This document does **not** overwrite D0 or the D2 conventions. Where D0 already
locked a recovery rule (Section 16), this document restates it and resolves the
design decisions D0 explicitly left to D3. Every departure is recorded.

**One D0-scale finding drives the whole design** (Section 3): the recoverable
expense pool excludes the management fee, which makes it independent of EGI.
That single fact removes the revenue/expense circularity *and* lets D3 be built
before the expense engine exists.

---

## 1. Objective

D3 teaches Anchor how a commercial lease structure converts property operating
expenses into **tenant reimbursement revenue**, for `NNN`, `GROSS` and
`MODIFIED_GROSS`.

D3 does **not** integrate Lease-Level into acquisition, debt, returns or NOI.
That is D4.

### 1.1 The core question

> For every suite and every canonical `ModelMonth`: how much of the property's
> recoverable operating expense is this tenant contractually responsible for
> reimbursing, and when?

### 1.2 The first principle — recoveries are revenue

Expense recoveries are **revenue on their own line**. They are never:

- a reduction to contractual base rent,
- a reduction to property operating expenses,
- a negative expense,
- a leasing cost, TI or LC.

D0 §10.2 already fixes the statement order and this document does not move it:

```
Contractual Base Rent          (GROSS -- never netted)
  less Free Rent
  plus Expense Recoveries      <-- D3
  plus Other Income
  less Credit Loss
= Effective Gross Income
```

Property operating expenses remain property expenses **in full**. Netting a
recovery against an expense would make both figures unrecognisable against a
real operating statement and is failure mode **FM-D3-1**.

**Consistency check against the existing architecture.** Detailed
(`engine/operating_projection.py`) computes `NOI = EGI − TotalOpex` with the
five fixed expense lines gross and a management fee on EGI. A recoveries line
added to EGI composes with that structure without changing it: Detailed's
formulas, contract and outputs are untouched (D0 §13.1). Confirmed compatible.

---

## 2. Terminology

| Term | Meaning |
|---|---|
| **Recoverable expense pool** | The portion of monthly property operating expense that any tenant may be asked to reimburse. Excludes the management fee (Section 3) |
| **Pro-rata share** | The fraction of the pool a given lease is responsible for |
| **Recovery basis** | The explicit contractual threshold a Modified Gross tenant reimburses *above* |
| **Economic responsibility factor** | The fraction of a canonical month for which a lease is economically responsible for expenses (Section 7) |
| **Recovery** | The resulting reimbursement **revenue**, in dollars, for one lease in one month |

Deliberately *not* used: "CAM", which in practice means anything from
common-area maintenance only to the entire pool, and would be ambiguous in a
field name.

---

## 3. The recoverable expense pool

### 3.1 Structure — one aggregate pool, via a ratio

**Decision: option A, a single aggregate recoverable pool**, exactly as D0 §16.3
and §4.6 already specify:

```
RecoverableExpenses_m = (TotalOpex_m − ManagementFee_m) × recoverable_expense_ratio
```

`recoverable_expense_ratio ∈ [0, 1]` is already declared on
`LeaseLevelOperatingInputs` (D0 §4.6) and phased **D3**.

Per-category recoverability is D0 §16.5-deferred. It is real, and it is the
first extension anyone will want; it is not required to underwrite a competition
case credibly, and adding it later is additive (Section 15).

### 3.2 Why the management fee is excluded — and why it matters more than D0 said

D0 §16.3 excludes the management fee because it is usually non-recoverable or
recovered under a separate admin-fee provision, **and** because including it
would be circular: recoveries raise EGI, EGI raises the fee, the fee raises
recoveries.

That exclusion has a second consequence D0 did not draw out, and it is
load-bearing for D3's feasibility:

> **The recoverable pool depends only on the five fixed expense lines and
> expense growth. It does not depend on EGI, on rent, on occupancy, or on
> recoveries.**

So the pool is computable *before* any revenue is known, in one pass, with no
fixed-point solve. D0 §16.4's eight-step ordering is therefore not merely a
convention that works — it is forced by the structure, and D3 can be built and
proven without an EGI engine existing at all.

### 3.3 What is never in the pool

| Item | In pool? | Why |
|---|---|---|
| Property taxes, insurance, utilities, R&M, other opex | **Yes**, times the ratio | The five Detailed fixed lines (D0 §13.1) |
| Management fee | **No** | D0 §16.3 — circularity and market practice |
| Capital expenditures | **No** | Capital, not operating. Above the line it is not |
| TI | **No** | Below NOI, and a leasing cost of a *specific* lease (D0 §11) |
| LC | **No** | Below NOI, same reasoning (D0 §12) |
| Debt service | **No** | Not a property operating expense at all |

TI and LC are especially worth naming: they are landlord costs incurred to sign
one tenant, not shared building costs, and recovering them from the whole rent
roll would double-charge the very tenant they were spent on. Including any of
these four is failure mode **FM-D3-8**.

### 3.4 The expense-schedule seam — the one real sequencing problem

**The monthly recoverable-expense series D3 needs does not exist today.**

Verified against the code: `engine/operating_projection.py` produces
`property_taxes_by_year`, `insurance_by_year`, … — **annual only**, with the
management fee as `egi_y × management_fee_pct`. There is no monthly expense
schedule anywhere in Anchor, and `LeaseLevelOperatingInputs` is phased **D4**.
`anchor.leasing` is additionally guardrail-forbidden from importing
`anchor.engine.operating_projection`.

D0 §13.2 defines the monthly form (`FixedExpenseLine_y / 12.0`) but assigns the
implementation to D4, with a hard **G-2** proof obligation that Detailed's
golden case stays bit-identical through any shared-helper extraction.

**Decision: D3 consumes an injected monthly recoverable-expense series and
builds no expense engine.**

```
build_lease_recovery_schedule(lease, ..., recoverable_expenses: tuple[float, ...])
```

one figure per canonical `ModelMonth`. This is the narrowest seam that:

- keeps a second expense engine out of `anchor.leasing`, which D0 §13.1
  explicitly warns against;
- touches no `anchor.engine` file before D4's G-2 proof;
- respects the existing forbidden-import guardrail without an exemption;
- makes every D3 golden hand-calculable, because the test supplies the pool
  directly rather than deriving it through a growth model.

D4 then supplies the real schedule from `LeaseLevelOperatingInputs`. D3 states
the contract that schedule must satisfy; it does not build it.

**Non-goal made explicit:** D3 does not decide how expenses grow, how they are
spread across months, or whether the Detailed helper is extracted or duplicated.
All three are D4.0 decisions and D0 §13.1 already frames them.

---

## 4. Pro-rata share

### 4.1 The default denominator

```
ProRataShare(L) = L.leased_area_sf / LeaseLevelPropertyInputs.rentable_area_sf
```

exactly as D0 §16.3 states. Both figures are rentable area on the identical
basis (D0 §4.2.1).

**This denominator is unusually safe in Anchor**, because D1 made the area
reconciliation *exact*: `sum(suite_area_sf) == rentable_area_sf` is a
`RENTABLE_AREA_NOT_RECONCILED` **ERROR**, not a warning, and vacant space is a
`Suite` with no lease rather than a residual. So:

> Across a fully-leased property, pro-rata shares sum to exactly `1.0`, and the
> property can never recover more than 100% of the pool through the ordinary
> path.

That is the multi-suite reconciliation golden (Section 12, case 10), and it is a
property of D1's design rather than something D3 must enforce.

### 4.2 What is deferred

- **Explicit contractual share override.** Real leases sometimes state a share
  that differs from the area quotient. Deferred (**HD-D3-6**); when added it is
  one nullable field whose presence wins, with the area quotient as the
  fallback — the same precedence idiom as `Suite.market_rent_psf`.
- **A denominator other than building rentable area** (e.g. occupied area, or a
  gross-up to stabilised occupancy). **Gross-up is D0 §16.5-deferred** and stays
  deferred: it materially changes recoveries in a vacant building and needs its
  own convention and validation. Using occupied area silently would be failure
  mode **FM-D3-6**.

**Anchor never infers a denominator.** With no override supported in D3, the
area quotient is the *only* denominator, which is unambiguous by construction.

---

## 5. Lease structures

### 5.1 NNN — first-dollar, pro-rata

```
Recovery(L, m) = ProRataShare(L) × RecoverableExpenses_m × ResponsibilityFactor(L, m)
```

Answering the ten questions precisely:

| # | Question | D3 answer |
|---|---|---|
| 1 | Which categories? | The aggregate pool of Section 3.1. Per-category is deferred |
| 2 | Base year? | **No.** NNN recovers from the first dollar |
| 3 | First-dollar? | **Yes** |
| 4 | Does free rent reduce it? | **No** (Section 8) |
| 5 | Does fractional commencement prorate it? | **Yes**, by the responsibility factor (Section 7) |
| 6 | Does it stop during downtime? | **Yes** — factor is `0`, so recovery is `0` |
| 7 | Expenses after expiration? | Not this tenant's. Factor is `0` |
| 8 | Successor inheritance? | **HD-D3-1** — recommended to come from branch assumptions, not inheritance |
| 9 | Caps? | **Not in D3.** D0 §16.5-deferred |
| 10 | Admin fees? | **Not in D3.** D0 §16.5-deferred |

### 5.2 Gross — zero

```
Recovery(L, m) = 0.0
```

The landlord bears the operating expenses in full. **Confirmed as the intended
D3 baseline.**

**A Gross lease with an expense stop is `MODIFIED_GROSS` in Anchor, not
`GROSS`.** The two names overlap in market usage, and allowing a stop on a
`GROSS` lease would create two ways to express one economic structure and make
`lease_type` unreliable as a discriminator. The rule is: *a stop implies
Modified Gross*. Validation enforces it (Section 11).

### 5.3 Modified Gross — above an explicit basis

```
Recovery(L, m) = ProRataShare(L) × max(0, RecoverableExpenses_m − Stop_m(L)) × ResponsibilityFactor(L, m)
```

Note the placement of the share: the tenant reimburses **its share of the
excess**, not the excess of its share. With one aggregate pool and a stop
expressed at property level the two are algebraically identical; they diverge
the moment per-category pools or per-lease stops in `$/SF` arrive, so the form
is fixed now (Section 6.2) to avoid a silent change later.

`max(0, …)` means a Modified Gross tenant never receives money when expenses
fall below the basis. Negative recovery is not a concept Anchor has.

---

## 6. The explicit basis — the load-bearing D3 rule

### 6.1 No silent base, ever

D0 §16.2 locked this and D3 restates it as binding:

> **A contractual base year or expense stop is never inferred.** Anchor may not
> derive it from the first projection year, the first full calendar year, the
> analysis year, the acquisition date, or the current expense schedule.

A missing basis on a `MODIFIED_GROSS` lease is a validation **ERROR** —
`MISSING_MODIFIED_GROSS_RECOVERY_BASIS` — never a default, never a Hold-Year-1
substitute. Failure mode **FM-24** / **FM-D3-5**.

The reason is not pedantry. A base year is a *contract term* that predates the
acquisition; the buyer's first hold year is an *artifact of when they bought*.
Substituting one for the other changes recovery revenue on every Modified Gross
lease in the rent roll, in a direction that depends on nothing more than the
closing date.

### 6.2 Representation — decision

**Decision: D3 supports exactly one representation, an expense stop in `$/SF`
per year**, carried through a one-member enum seam:

```
class RecoveryBasis(StrEnum):
    EXPENSE_STOP_PSF = "expense_stop_psf"        # the only member in D3
```

with the value on the lease (`expense_stop_psf: float | None`, `>= 0`), and

```
Stop_m(L) = L.expense_stop_psf × rentable_area_sf / 12.0
```

so the stop is expressed the way a lease expresses it — per square foot per
year — and converted to a property-level monthly dollar amount once, dividing
by 12 last, exactly as D1 does for rent.

**Why the stop and not a base-year amount**, chosen deliberately over the
alternative:

1. **It needs no historical data.** A base *year* — "Base Year: 2027" against an
   `analysis_start` of 2028-07-01 — requires the 2027 recoverable-expense
   actuals, which are not in the forward projection and which Anchor has no
   source for. Supporting it would either demand a historical expense input
   Anchor does not collect, or tempt exactly the Hold-Year-1 substitution §6.1
   forbids. This is the calendar base-year problem, and the stop dissolves it.
2. **It is what the analyst can actually source.** A stop is stated in the lease
   abstract in the same units as everything else on the rent roll.
3. **It is one number.** A base-year amount needs a year *and* an amount, and
   the year is then a second thing to validate against the projection.

**The base-year amount is not rejected — it is the enum's second member**, added
if a competition rent roll forces it. Adding it costs one enum member plus one
nullable field, with no change to `Lease`'s other fields and no migration. This
is deliberately the same extension-seam idiom D2.4 used for
`LeasingCommissionMethod`, which worked.

### 6.3 Does the basis escalate? — decision

**Decision: the stop is nominally fixed for the life of the lease.**

```
Stop_m(L) is constant in m
```

Reasons: it is the commonest institutional form of an expense stop; it is the
smallest deterministic model that captures the economically meaningful case
(expenses grow, the stop does not, recoveries emerge and then grow); and it is
explicit rather than assumed.

**The economically interesting behaviour is preserved, not lost.** Because the
pool grows with expense growth and the stop does not, a Modified Gross lease
that recovers nothing in year 1 begins recovering the moment the pool crosses
the stop — which is golden case 5 (Section 12) and the main thing this structure
exists to model.

A growing stop is additive later: one optional `expense_stop_growth` field
defaulting to nothing, or a third enum member. Flagged **HD-D3-4** because a
reviewer may hold a different market view, and the cost of changing it later is
one field.

---

## 7. Economic responsibility — which factor drives recoveries

### 7.1 The decision

D0 §16.3 already states that recovery is zero during vacancy and downtime and is
**"scaled by the fractional boundary factor in period `c`"**. D3 confirms this
and gives the factor a name and a general definition covering in-place leases
too:

```
ResponsibilityFactor(L, m) =
    1.0                              L is an in-place lease, contractually active in m
    successor_occupancy_factor(m)    L is a successor  (D2.3)
    0.0                              otherwise
```

For a successor this is exactly D2.3's series: `0` in a fully vacant downtime
period, `1 − frac(D)` in the commencement period `c`, `1` thereafter, `0` after
the term ends.

### 7.2 Why the occupancy *factor* and not physical occupancy — proof

The worked case: a new tenant with `D = 2.25` commences in September, where
`O_September = 0.75` while month-end **physical** occupancy is `1` (the tenant is
in possession by month-end — D2 HD-D2-2).

September recovery must be **75% of a month's recovery**, not 100%:

1. **It matches what the tenant is being charged for.** Recoveries reimburse
   *expenses incurred while the tenant was economically present*. The tenant was
   present for three-quarters of September; charging a full month bills them for
   a quarter-month of expenses incurred while the suite was dark and no lease
   existed.
2. **It keeps one clock.** September's *rent* is recognised at `0.75` under the
   accepted D2.3 monthly approximation. Recognising rent at `0.75` and
   recoveries at `1.00` in the same month would mean the same lease is
   simultaneously three-quarters and fully commenced — two different tenancy
   start conventions inside one period.
3. **Physical occupancy is the wrong quantity by construction.** D2 HD-D2-2
   binds `physical_occupancy` to be an *integral month-end state*, deliberately
   so it can never be read as an economic fraction. Using it here would import
   a state metric into a flow calculation, which is precisely the distinction
   D0 §5.7 exists to protect.

Using physical occupancy is failure mode **FM-D3-4**.

**One consequence to disclose:** because the factor is `0` in every fully vacant
month, an expense incurred while a suite is dark is borne entirely by the
landlord. That is correct — there is no tenant to reimburse it — and it is the
mechanism by which vacancy hurts NOI twice, through lost rent and unrecovered
expenses. Golden case 8 pins it.

---

## 8. Free rent — locked

**Free rent does not reduce expense recoveries.**

This is already locked upstream and D3 restates rather than decides it. D2
Section 7.3:

> Recoveries (D3): **No automatic effect.** Whether a tenant reimburses during
> an abatement is a function of the lease's recovery structure, not of the
> free-rent input.

and D2 Section 7.4: during free rent the successor **is in possession**, so
recoveries continue.

Concretely: a fully-occupied NNN tenant with 100% of base rent abated still owes
its full pro-rata share of recoverable expenses. `ResponsibilityFactor` is
driven by occupancy, not by cash rent, so this falls out of Section 7's
definition rather than needing a rule of its own.

**A recovery abatement is a different concession and is UNSUPPORTED in D3.** It
is never inferred from `free_rent_months`. If a lease genuinely abates
recoveries, that is a separate input a later gate may add explicitly. Inferring
it is failure mode **FM-D3-3**.

---

## 9. Existing leases and successors

### 9.1 In-place leases — LeaseType becomes live

`LeaseType` has been captured since D1.0 and economically **inert** through D2.
D3 is the first gate where it changes a number. D0 §4.4 already anticipated
this: `recovery_basis` is listed on `Lease`, "required for `MODIFIED_GROSS` at
D3".

D3 therefore adds to `Lease`, additively and nullable:

```
recovery_basis: RecoveryBasis | None = None
expense_stop_psf: float | None = None
```

Both default to `None`, so every D1/D2 call site constructs an identical lease
and **no D1 or D2 economics move** — the same additive discipline
`Lease.origin` followed at D2.2.

**No existing contractual base-rent semantics change.** D3 reads `lease_type`;
it does not touch `base_rent_psf`, escalation, dates, or any D1 formula.

### 9.2 Successor lease type — the significant open decision

**Today's behaviour, verified in code:** `build_recursive_rollover` passes
`lease_type=expiring.lease_type` where `expiring` is the **original in-place
lease**, at *every* generation. So the entire rollover chain — first successor,
fifth successor — carries the original rent roll's lease type forever.

That was harmless while `LeaseType` was inert. At D3 it becomes an economic
assertion, and a questionable one: *"a Gross tenant vacates in year 6, and the
replacement tenant Anchor finds also signs Gross, and so does every replacement
after that, forever."* Real re-lettings routinely change structure — a legacy
Gross tenant leaves and the space is re-let NNN at prevailing terms.

**Recommended (HD-D3-1): the successor's lease type comes from branch-specific
market-leasing assumptions**, not from inheritance:

```
MarketLeasingAssumptions.renewal_lease_type: LeaseType
MarketLeasingAssumptions.new_lease_type:     LeaseType
```

A renewal plausibly keeps the sitting tenant's structure; a new letting
plausibly takes the market's. Making both explicit lets the analyst say so, and
`renewal_lease_type` set to the in-place type reproduces today's behaviour
exactly when that is what is meant.

### 9.3 Successor recovery terms

Symmetrically, and for the same reason (**HD-D3-2**):

```
renewal_recovery_basis / renewal_expense_stop_psf
new_recovery_basis     / new_expense_stop_psf
```

so a renewal can stay Modified Gross on a negotiated stop while a new letting
signs NNN. Anchor will need this; the question is only whether D3 is where it
lands.

---

## 10. Composition and recursion

### 10.1 Expected recoveries — weight dollars, as always

D2's approved methodology applies unchanged (HD-D2-1). Each branch computes its
**own** recovery series from its own lease type, own basis and own pro-rata
share; only the finished dollars are weighted:

```
ExpectedRecovery_m = p × RenewalRecovery_m + (1 − p) × NewTenantRecovery_m
```

**Never probability-weight** a lease type, an expense stop, a recovery basis, a
pro-rata share or a recoverable ratio. A weighted lease type is not a lease
type; `0.65 × NNN + 0.35 × GROSS` is not a structure any tenant signs. This is
the same nonlinearity that invalidated D0 §8.2 (D2 §1.3) and it applies with
extra force here, because `max(0, …)` in the Modified Gross formula is not even
linear in the pool: `E[max(0, X − s)] ≠ max(0, E[X] − s)` in general. Weighting
before the `max` is failure mode **FM-D3-10**.

The recovery series simply becomes an eleventh weighted series on
`ExpectedRollover` and `RecursiveRollover`, composed by the existing
`weighted_outcome` primitive. No new weighting rule is introduced.

### 10.2 D2.6 merge-key compatibility — the critical analysis

D2.6's recursion merges two scenario paths that reach the same expiration period
because their **futures are identical**. The sufficient state key
(D2 §5.5.1) is

```
(suite_id, expiration_period, lease_type, leased_area_sf)
```

reducing in practice to the expiration period, because the other three are
invariant. **D3 introduces the first economics that could break that**, so the
question must be settled before implementation.

**The rule that preserves it, stated as binding:**

> A successor's lease type and recovery terms must be a function of
> **(branch kind, resolved market-leasing assumptions, commencement period)**
> and **never** of the lease it replaces.

Under the recommended design (Sections 9.2–9.3) this holds:

| Quantity | Source | Path-dependent? |
|---|---|---|
| Successor lease type | `renewal_lease_type` / `new_lease_type` | **No** — a function of its own branch kind |
| Successor recovery basis / stop | branch-specific assumption | **No** |
| Pro-rata share | suite area / rentable area | **No** — constant |
| Recoverable pool | property expense schedule | **No** — same for all paths |
| Responsibility factor | `c`, `D`, term | **No** — a function of `(branch, e)` |

Every input to a successor's recoveries is therefore determined by its own
branch kind and its own commencement period. A renewal successor has
`renewal_lease_type` **regardless of what its parent was**, so two paths meeting
at the same expiration period still have identical futures.

> **Conclusion: the D2.6 merge key is unchanged. `states ≤ N` and
> `transitions ≤ 2N` still hold, and no arbitrary cap becomes necessary.**

**The design that would break it, named so it is not adopted by accident:**
chain inheritance — a successor taking its lease type or its stop *from its
immediate predecessor*. Then a renewal-of-an-NNN and a renewal-of-a-Gross
arriving at the same period would face different futures, `lease_type` would
re-enter the merge key as a live dimension, and the state count would multiply
by the number of reachable structures. Anchor would still be correct, but it
would have paid for a feature it did not choose.

**Required guardrail (D3.4):** a test asserting that the successor-construction
path reads no recovery term off a predecessor lease — the direct analogue of
D2.6's existing "successor engine never reads a predecessor lease" guardrail,
which is what makes the merge proof mechanical rather than aspirational.

Note this is *also* an argument for the recommended design on its own merits:
assumption-sourced terms are both more realistic **and** strictly cheaper
computationally than inheritance.

---

## 11. Validation

Leasing-scoped only (`anchor.leasing.validation`). No change to
`anchor.validation` — the D0 §19/HD-6 boundary is unchanged.

| Code | Severity | Rule |
|---|---|---|
| `MISSING_MODIFIED_GROSS_RECOVERY_BASIS` | **ERROR** | `MODIFIED_GROSS` without an explicit basis (§6.1, FM-24) |
| `RECOVERY_BASIS_ON_NON_MODIFIED_GROSS` | **ERROR** | A stop supplied on `NNN` or `GROSS`, which would make `lease_type` unreliable (§5.2) |
| `EXPENSE_STOP_OUT_OF_DOMAIN` | **ERROR** | `expense_stop_psf < 0` or non-finite |
| `RECOVERABLE_EXPENSE_RATIO_OUT_OF_DOMAIN` | **ERROR** | outside `[0, 1]` or non-finite |
| `UNSUPPORTED_RECOVERY_BASIS` | **ERROR** | A `RecoveryBasis` member D3 does not implement |
| `RECOVERABLE_EXPENSES_OUT_OF_DOMAIN` | **ERROR** | A negative or non-finite figure in the injected pool series |

Deliberately **not** validated: that recoveries are "reasonable" relative to
rent, or that a stop is near current expenses. Both are analyst judgement, and
D0 §19.4 forbids inventing economically meaningful defaults or downgrading a
mathematically invalid input to a warning.

---

## 12. Golden cases

All hand-calculable. Shared frame: `analysis_start = 2027-01-01`, 10,000 SF
suite in a 10,000 SF property (share `1.0`) unless stated; recoverable pool
stated directly, per §3.4.

| # | Case | Proves |
|---|---|---|
| **1** | NNN, pool $10,000/mo, share 1.0 | Recovery `$10,000`. First-dollar, no basis |
| **2** | Gross, same pool | Recovery **exactly `0.0`** in every month |
| **3** | Modified Gross, pool below stop | Recovery **exactly `0.0`**; never negative |
| **4** | Modified Gross, pool above stop | `share × (pool − stop)`, hand-checked |
| **5** | Expense growth crosses the stop | Zero recovery, then positive from the crossing month. **The case Modified Gross exists to model** |
| **6** | Fractional commencement, `D = 2.25` | September recovery is **`0.75 ×`** a full month (§7.2) |
| **7** | Full free-rent month, NNN | Base-rent cash `0`, recovery **unchanged and payable** (§8) |
| **8** | Fully vacant downtime month | Recovery **exactly `0.0`**; landlord bears the expense |
| **9** | Suite pro-rata share | 4,000 SF in 10,000 SF recovers exactly `0.40` of the pool |
| **10** | Multi-suite reconciliation | Three suites summing to `rentable_area_sf` recover **exactly the pool**, no more |
| **11** | Property default vs suite override | Only if §4.2's override is adopted; otherwise asserts no override path exists |
| **12** | Renewal NNN vs new-tenant Gross | Branch-specific structures produce different recoveries from one rollover |
| **13** | Probability-weighted expected recovery | `p × R + (1−p) × N` on **dollars**; and that it differs from applying `max(0, …)` to a weighted pool |
| **14** | Recursive later-generation recovery | A third-generation successor recovers on its own terms |
| **15** | Modified Gross with no basis | Validation **ERROR**, never a silent base |
| **16** | Non-January analysis start | Recovery timing follows the canonical calendar, not the calendar year |
| **17** | Forward exit window | Recoveries continue through `12H+12` |
| **18** | Annual equals monthly | `sum(monthly) == annual` exactly; no independent annual formula |

Cases 5, 6, 7, 8, 13 and 15 are the acceptance set: each pins a rule that a
plausible-looking wrong implementation would violate silently.

---

## 13. Failure-mode register

| ID | Failure | Detection |
|---|---|---|
| **FM-D3-1** | Recoveries netted against operating expenses | Statement-order test; expenses stay gross |
| **FM-D3-2** | Recoveries folded into `contractual_base_rent` | Golden 1; base rent bit-identical with and without recoveries |
| **FM-D3-3** | Free rent silently eliminating recoveries | **Golden 7** |
| **FM-D3-4** | Physical occupancy used instead of the responsibility factor | **Golden 6** — September is `0.75`, not `1.0` |
| **FM-D3-5** | A Modified Gross base silently inferred | **Golden 15**, ERROR |
| **FM-D3-6** | Wrong pro-rata denominator (occupied area, gross building area) | Golden 9/10; shares sum to exactly `1.0` |
| **FM-D3-7** | All expenses treated as recoverable | Ratio applied; management fee excluded by construction |
| **FM-D3-8** | CapEx / TI / LC entering the pool | Guardrail: the recovery module may not name them |
| **FM-D3-9** | Annual and monthly recovery formulas diverging | **Golden 18**; annual derives solely from monthly |
| **FM-D3-10** | A lease structure, stop or share probability-weighted | Guardrail + Golden 13; `E[max(0,·)] ≠ max(0,E[·])` |
| **FM-D3-11** | The D2.6 merge key becoming insufficient | §10.2 guardrail: successor terms never read a predecessor |
| **FM-D3-12** | Recovery starting before the tenant is responsible | Golden 6; factor is `0` before `c` |
| **FM-D3-13** | Recovery continuing through downtime or after expiry | **Golden 8** |
| **FM-D3-14** | The stop growing unintentionally | §6.3; stop constant in `m` unless a growth field is added |
| **FM-D3-15** | A successor inheriting a lease type the assumptions contradict | §9.2 / HD-D3-1 |
| **FM-D3-16** | Recovery revenue double-counted at property aggregation | Golden 10; property total equals the sum of lease schedules |
| **FM-D3-17** | Negative recovery from a Modified Gross lease | Golden 3; `max(0, …)` |

---

## 14. Proposed gate sequence

Reordered from the candidate for one reason: **the pool and the pro-rata share
are not separable proofs.** A share is only checkable against a pool, and both
are trivial arithmetic; splitting them makes D3.1 a gate that proves a division.
Merging them, and pairing them with the two structures that need no basis, gives
each gate a real financial claim.

| Gate | Objective | Proves | Touches |
|---|---|---|---|
| **D3.0** | *This document* | Conventions locked; D2.6 merge key proven safe | `docs/` only |
| **D3.1** | Recoverable pool, pro-rata share, **NNN and Gross** | The pool contract and injected series; shares summing to `1.0`; first-dollar NNN; Gross exactly zero; the responsibility factor including the fractional boundary; free rent not reducing recovery; downtime zero | new `recoveries.py` |
| **D3.2** | **Modified Gross** + the explicit basis | `max(0, pool − stop)`; the `RecoveryBasis` seam; the missing-basis ERROR; the growth-crossing case | `recoveries.py`, `validation.py` |
| **D3.3** | Successor recovery assumptions | Branch-specific lease type and basis; **the merge-key guardrail**; renewal ≠ new-tenant structures | `contracts.py`, `rollover.py` |
| **D3.4** | Expected + recursive recoveries | The eleventh weighted series through `weighted_outcome`; recursion across generations; `p=0`/`p=1` endpoint identity; explicit-tree oracle extended | `rollover.py` |
| **D3.5** | Property recovery aggregation + D3 closeout | Lease → property monthly recovery; annual derived solely from monthly; full D3 golden suite; guardrails | `aggregation.py`, tests |

D3.1 is deliberately the largest: it establishes the pool contract and the
responsibility factor, which everything after it reuses. D3.3 is small but is
where the merge-key guardrail lands, and it must precede D3.4 so recursion is
never built on an unproven key.

---

## 15. Property aggregation — where the boundary sits

**Recommendation: D3.5 owns lease → property monthly recovery aggregation,
inside `anchor.leasing`. D4 owns conversion into the operating projection and
NOI.**

Justification: D1.3 already established that combining lease-level monthly
series into a property monthly series is a *leasing* concern
(`build_property_rent_roll_schedule`), and that annual figures derive solely
from monthly ones. A recovery series is a monthly series like any other and
composes into that existing structure without inventing a boundary.

What is *not* D3: EGI, the management fee (which consumes EGI), credit loss,
NOI, exit NOI, and the eight-step ordering of D0 §16.4 — every one of those
needs the expense engine and the revenue build that D4 owns. D3 stops at
"monthly recovery revenue, by lease and by property".

---

## 16. Monthly and annual convention

Monthly remains canonical (D0 §5.1). Annual recovery is the chronological sum of
the exact monthly figures, through the existing
`aggregation.aggregate_flow_to_annual`, with **no independent annual recovery
formula**. Recovery is a **flow** metric and is never averaged; the responsibility
factor is a **fraction**, not a state metric, and is never summed across months.

---

## 17. Human decisions

| ID | Question | Option A | Option B | Recommended | Why | Consequence | Blocks? |
|---|---|---|---|---|---|---|---|
| **HD-D3-1** | Where does a successor's **lease type** come from? | Inherit the original lease's type (today's behaviour) | Branch-specific `renewal_lease_type` / `new_lease_type` | **B** | A Gross tenant leaving and the space re-letting NNN is routine; inheritance asserts the structure never changes, forever. B also *preserves* the D2.6 merge key and is computationally cheaper than chain inheritance | Two fields on `MarketLeasingAssumptions`; setting `renewal_lease_type` to the in-place type reproduces A exactly | **BLOCKS D3.3** |
| **HD-D3-2** | May renewal and new tenant have **different recovery terms**? | One shared set | Branch-specific basis and stop | **B** | Symmetric with HD-D3-1 and with every other D2 assumption, all of which are already branch-specific. A renewal negotiating a stop while a new letting signs NNN is the normal case | Two nullable fields per branch | **BLOCKS D3.3** |
| **HD-D3-3** | Which **basis representation** does D3 implement? | Expense stop `$/SF` | Base-year amount | **A** | The stop needs no historical expense data and so cannot tempt the Hold-Year-1 substitution §6.1 forbids; it is what a lease abstract states. B remains available as a second enum member at zero structural cost | One enum member, one nullable field | **BLOCKS D3.2** |
| **HD-D3-4** | Does the stop **escalate**? | Nominally fixed | Grows at a stated rate | **A** | Commonest institutional form, smallest deterministic model, and it preserves the economically interesting behaviour (the pool crosses a fixed stop). Explicitly recorded rather than assumed | An optional growth field is additive later | **BLOCKS D3.2** |
| **HD-D3-5** | Does D3 support **per-category** recoverability? | Aggregate pool × ratio | Explicit categories | **A** | D0 §4.6/§16.3 already specify the ratio; per-category is D0 §16.5-deferred and is the first thing an institutional user will want, but it is not needed to underwrite credibly | Additive: the pool becomes a sum of category pools | **CAN DEFER** |
| **HD-D3-6** | Explicit **pro-rata share override**? | Area quotient only | Optional override wins | **A for D3** | D1's exact area reconciliation makes the quotient reliable, and no override means no denominator ambiguity. Real leases do state shares, so B will come | One nullable field, same precedence idiom as `Suite.market_rent_psf` | **CAN DEFER** |
| **HD-D3-7** | Are **recovery abatements** supported? | Unsupported; never inferred | Inferred from free rent | **A** | D2 §7.3 already locks that free rent has no automatic recovery effect. Inferring one would silently change every NNN lease with free rent | If needed later, an explicit input — never an inference | **CAN DEFER** |
| **HD-D3-8** | Does the **injected pool** stay injected through D4? | D3 injects; D4 supplies | D3 builds an expense engine | **A** | D0 §13.1 explicitly warns against a second expense engine in `anchor.leasing`, and D4 carries the G-2 obligation to prove Detailed bit-identical | D3 defines the contract; D4 satisfies it | **CAN DEFER** |

**Three decisions block implementation: HD-D3-1, HD-D3-2 (both D3.3) and
HD-D3-3, HD-D3-4 (both D3.2).** None blocks **D3.1**, which needs only the pool,
the share, NNN, Gross and the responsibility factor — all settled here.

---

## 18. Remaining risks

1. **The expense-schedule seam is a real dependency, not a formality.** D3 is
   provable in isolation, but Lease-Level NOI is not demonstrable until D4
   supplies the pool. The mitigation is that D3's contract is one tuple of
   floats per month, which D4 can satisfy however it resolves the
   extract-versus-duplicate question.
2. **The `max(0, …)` non-linearity is easy to get wrong under composition.**
   Golden 13 exists specifically because weighting a pool and then clipping is a
   natural-looking implementation that is wrong.
3. **HD-D3-1 is more consequential than it looks.** Choosing inheritance would
   not be incorrect, but it would put `lease_type` back into the D2.6 merge key
   and multiply the state count — a computational cost paid for an economic
   assertion (structures never change) that is probably not intended.
4. **Gross-up remains deferred and matters in a vacant building.** With no
   gross-up, a half-empty property recovers only half its pool. That is the
   honest arithmetic of the chosen convention, and it should be a disclosed
   sharp edge rather than a surprise at D4.

---

## 19. Non-goals

D3.0 designs and implements none of the following, and D3 as a sprint touches
none of them except where a seam must be named: acquisition, debt, returns or
`AcquisitionResults` integration; NOI or exit NOI; below-NOI costs; the
management fee, EGI or credit loss; API, persistence, UI, ingestion or AI
extraction; the D5 rent-anchor cleanup; the D4 magnitude-aware reconciliation
rule; percentage rent, natural breakpoints or sales reporting; CAM audits,
reconciliation true-ups, real invoice billing or tenant AR; recovery caps,
floors, admin fees or gross-up (all D0 §16.5-deferred).

---

## 20. Scope statement

This gate changed `docs/` only — one file, this document. No file under `src/`,
`tests/` or `web/`, no migration, no dependency, no configuration. D1 and D2
economics are untouched, `anchor.leasing` is unmodified, and D0 is unmodified.

No D3 production code exists. **D3.1 may begin once HD-D3-1 through HD-D3-4 are
answered** — or immediately, since none of the four blocks D3.1 itself.
