---
title: "Lease-Level Underwriting — D3 Expense Recovery Conventions"
gate: D3.0
status: D3 COMPLETE -- D3.0 through D3.6 implemented and verified; ready for final human review
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

**Amended after D3.0 human financial review.** The architecture was accepted.
Four decisions are now **locked** — HD-D3-1 through HD-D3-4 (Section 17) — and
the Modified Gross formula is restated in an explicitly dimensioned,
tenant-level form (Section 5.3). No accepted D0, D1 or D2 convention changed,
and the four `CAN DEFER` items remain open and undecided.

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

Per-category recoverability is D0 §16.5-deferred and **is not reopened in D3**.
It is real, and it is the first extension anyone will want; it is not required
to underwrite a competition case credibly, and adding it later is additive
(Section 15). The D3 competition model uses **one aggregate recoverable pool**,
whose eligibility exclusions (Section 3.3) are likewise not reopened.

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

Stated as three prohibitions, so the boundary cannot erode:

- **D3 does not project property operating expenses.**
- **D3 does not derive the monthly pool from the engine's annual expenses.**
- **D3 builds no shadow expense engine**, in `anchor.leasing` or anywhere else.

D3.1 therefore proves *tenant recovery arithmetic against an injected pool*, and
nothing more. D4 later owns constructing that pool from the authoritative
operating-expense projection, applying `recoverable_expense_ratio` to the
eligible expenses under the accepted D0 convention. D3 states the contract that
schedule must satisfy; it does not build it.

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

### 5.0 Notation — fixed, and dimensioned

Every recovery formula below uses these symbols, and each carries its units
explicitly. Recovery arithmetic mixes property-level dollars, tenant-level
dollars and a `$/SF` rate, so the units are stated once here rather than being
inferred at each use.

| Symbol | Meaning | Units |
|---|---|---|
| `P_m` | Recoverable property expense pool in month `m` (Section 3) | **dollars** |
| `A_t` | The lease's `leased_area_sf` | SF |
| `A_p` | `LeaseLevelPropertyInputs.rentable_area_sf` | SF |
| `share` | `A_t / A_p` (Section 4) | dimensionless |
| `S` | The contractual expense stop | **`$/SF/year`** |
| `O_m` | Economic responsibility factor in month `m` (Section 7) | dimensionless, `[0, 1]` |
| `recovery_m` | Recognised reimbursement revenue | **dollars** |

Two derived quantities, both in **dollars per month**:

```
tenant_expense_share_m        = share × P_m
monthly_expense_stop_dollars  = S × A_t / 12
```

`S` is divided by 12 **once, last**, exactly as D1 does for `base_rent_psf`.

### 5.1 NNN — first-dollar, pro-rata

```
recovery_m = O_m × share × P_m
```

First dollar. No stop, no base, no free-rent reduction.

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
| 8 | Successor inheritance? | **None.** HD-D3-1 is APPROVED: a successor's type comes from branch assumptions, never from its predecessor |
| 9 | Caps? | **Not in D3.** D0 §16.5-deferred |
| 10 | Admin fees? | **Not in D3.** D0 §16.5-deferred |

### 5.2 Gross — zero

```
recovery_m = 0.0
```

The landlord bears the operating expenses in full. **Locked at D3.0 review as
the intended D3 baseline.**

**A Gross lease with an expense stop is `MODIFIED_GROSS` in Anchor, not
`GROSS`.** The two names overlap in market usage, and allowing a stop on a
`GROSS` lease would create two ways to express one economic structure and make
`lease_type` unreliable as a discriminator. The rule is: *a stop implies
Modified Gross*. Validation enforces it (Section 11).

### 5.3 Modified Gross — above an explicit basis

**Authoritative form — tenant-level, and the one to implement:**

```
full_month_recovery_m = max(0, tenant_expense_share_m − monthly_expense_stop_dollars)
                      = max(0, share × P_m − S × A_t / 12)

recovery_m            = O_m × full_month_recovery_m
```

Both terms inside `max` are **tenant-level dollars per month**, which is what
makes the comparison auditable: it is the tenant's share of this month's pool
against the tenant's own monthly stop, in the units a lease abstract states.

**Equivalent property-level form**, recorded because it is sometimes the more
convenient reading and because the two must never be allowed to drift apart:

```
recovery_m = O_m × share × max(0, P_m − S × A_p / 12)
```

The two are algebraically identical for `share > 0`, since
`share × P_m − S × A_t / 12 = share × (P_m − S × A_p / 12)`. **The tenant-level
form is authoritative for implementation.**

**Rejected — the unit-incompatible shorthand:**

```
share × max(0, P_m − S)          <-- WRONG: dollars compared to $/SF
```

`P_m` is dollars and `S` is `$/SF/year`. Subtracting one from the other is not
a smaller number, it is a meaningless one, and because both are positive it
would still produce a plausible-looking figure. This is failure mode
**FM-D3-18** and Golden 4 is dimensioned specifically to catch it.

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

**Decision (HD-D3-3, LOCKED at D3.0 human review): D3 supports exactly one
representation, an explicit contractual expense stop in `$/SF/YEAR`**, carried
through a one-member enum seam. **No calendar-year or base-year label is
implemented in D3**, because a true historical base year would require actual
expense history Anchor does not possess — and Anchor must never reconstruct
that history from Hold Year 1, the analysis year, the acquisition year, the
first projected year, or the current forward expense schedule.

```
class RecoveryBasis(StrEnum):
    EXPENSE_STOP_PSF = "expense_stop_psf"        # the only member in D3
```

with the value on the lease (`expense_stop_psf: float | None`, `>= 0`), and

The field is `expense_stop_psf`, and its units are **`$/SF/YEAR`** — stated on
the contract, not inferred. It converts to the tenant's own monthly dollar stop
once, dividing by 12 last, exactly as D1 does for `base_rent_psf`:

```
monthly_expense_stop_dollars = expense_stop_psf × A_t / 12.0
```

The property-level conversion `expense_stop_psf × A_p / 12.0` appears only in
the equivalent property-level form of Section 5.3 and is never mixed with the
tenant-level one in the same expression.

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

**The base-year amount is not rejected on its merits — it is reserved as the
enum's second member**, to be added only if a competition rent roll forces it
*and* the historical expense data it needs can be sourced. It is **not
implemented in D3**. Adding it costs one enum member plus one
nullable field, with no change to `Lease`'s other fields and no migration. This
is deliberately the same extension-seam idiom D2.4 used for
`LeasingCommissionMethod`, which worked.

### 6.3 Does the basis escalate? — decision

**Decision (HD-D3-4, LOCKED at D3.0 human review): the stop is nominally fixed
through the lease term.**

```
expense_stop_psf is constant in m, in $/SF/year
```

It explicitly does **not**:

- grow with property expense growth,
- grow with market rent growth,
- grow with contractual rent escalation,
- reset annually,
- reset at acquisition.

Future support for an escalating stop may be added only as an **explicit
contractual assumption**. D3 never infers one.

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
O_m =
    1.0                              L is an in-place lease AND contractually active in m
    successor_occupancy_factor(m)    L is a successor  (D2.3)
    0.0                              otherwise
```

For a successor this is exactly D2.3's series: `0` in a fully vacant downtime
period, `1 − frac(D)` in the commencement period `c`, `1` thereafter, `0` after
the term ends.

**An in-place lease does not simply get `1.0` for every canonical month.** It
gets `1.0` **only while it is contractually active** — that is, within its own
inclusive `[rent_commencement_date, lease_expiration_date]` window reduced to
canonical periods. Before commencement and after expiration it is `0.0`, and a
suite whose only lease has expired recovers nothing, which is the same rule
Section 7.3 states for downtime.

Because D1 requires both lease dates to be **month-aligned**, a known in-place
lease has **no fractional responsibility month** under current D1 conventions:
its factor is only ever `0.0` or `1.0`. Fractional values arise solely from a
successor's downtime boundary. If a future gate ever admitted a non-aligned
contractual date, this rule would need re-deriving — but D1 makes that a
validation ERROR, so it cannot arise today.

### 7.1.1 Where the factor is applied — locked

`O_m` scales the **full-month recovery obligation**, computed first:

```
full_month_recovery_m = the structure's own monthly obligation, at O_m = 1
recovery_m            = O_m × full_month_recovery_m
```

So `O_m = 0.75` means **75% of the otherwise-applicable monthly reimbursement is
recognised** — not 75% of one input compared against 100% of another.

**For Modified Gross this placement is load-bearing.** The wrong form scales the
expense share but not the stop:

```
max(0, 0.75 × share × P_m − S × A_t / 12)     <-- WRONG
0.75 × max(0, share × P_m − S × A_t / 12)     <-- CORRECT
```

The wrong form compares three-quarters of a month's expense share against a
whole month's stop, so it under-recovers in every fractional commencement month
and can report zero where the lease genuinely owes money. It is failure mode
**FM-D3-19**, and Golden 6 is constructed on a Modified Gross lease specifically
to catch it.

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

**Behaviour as of D3.0, verified in code and since removed at D3.3:**
`build_recursive_rollover` passed `lease_type=expiring.lease_type` where
`expiring` is the **original in-place lease**, at *every* generation. So the
entire rollover chain — first successor, fifth successor — carried the original
rent roll's lease type forever.

That was harmless while `LeaseType` was inert. At D3 it becomes an economic
assertion, and a questionable one: *"a Gross tenant vacates in year 6, and the
replacement tenant Anchor finds also signs Gross, and so does every replacement
after that, forever."* Real re-lettings routinely change structure — a legacy
Gross tenant leaves and the space is re-let NNN at prevailing terms.

**Decision (HD-D3-1, LOCKED at D3.0 human review): the successor's lease type
comes from branch-specific market-leasing assumptions**, not from inheritance.
An existing `GROSS` lease whose renewal is `MODIFIED_GROSS` and whose
new-tenant replacement is `NNN` must be representable:

```
MarketLeasingAssumptions.renewal_lease_type: LeaseType
MarketLeasingAssumptions.new_lease_type:     LeaseType
```

A renewal plausibly keeps the sitting tenant's structure; a new letting
plausibly takes the market's. Making both explicit lets the analyst say so, and
`renewal_lease_type` set to the in-place type reproduces today's behaviour
exactly when that is what is meant.

### 9.3 Successor recovery terms

**Decision (HD-D3-2, LOCKED at D3.0 human review): recovery terms are
branch-specific too**, and are never inherited from the predecessor:

```
renewal_recovery_basis / renewal_expense_stop_psf
new_recovery_basis     / new_expense_stop_psf
```

so a renewal can stay Modified Gross on a negotiated stop while a new letting
signs NNN.

**Neither the lease type nor any recovery term is ever inherited from the
predecessor lease.** That is not merely a modelling preference: it is what keeps
future successor economics path-independent, and therefore what keeps the D2.6
merge key valid (Section 10.2). Exact contract naming is chosen at D3.3.

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

The composition reuses the existing `weighted_outcome` primitive, and **no
new weighting rule is introduced** — that part is unchanged and is what the
section is really about.

> **Amended at D3.4 — where the composed series lives.** This section
> originally said the recovery series "becomes an eleventh weighted series on
> `ExpectedRollover` and `RecursiveRollover`". That placement is no longer
> available, and the reason is an architecture decision taken after it was
> written.
>
> D3.1 §3.4 and D3.3 established that the recoverable expense pool is
> **injected at the recovery boundary**: no D2 builder accepts a
> `RecoverableExpensePool`, so the market-leasing engine stays usable before
> any property expense schedule exists — which is the whole point of the
> injected-pool contract (HD-D3-8), and is now enforced by an architecture
> guardrail. Adding a recovery field to `ExpectedRollover` or
> `RecursiveRollover` would force `build_expected_rollover` and
> `build_recursive_rollover` to take a pool, reversing that decision.
>
> D3.4 therefore composes into **separate D3 result contracts** —
> `ExpectedRolloverRecovery` and `RecursiveRolloverRecovery` — each retaining
> the authoritative D2 result rather than modifying it. The financial content
> is exactly what this section specifies: pure branch schedules, weighted once,
> on completed dollars, through the one primitive. Only the field's address
> changed.
>
> `RecursiveRolloverRecovery` owns **no recursion**. It walks the retained
> `RecursiveRollover`'s `transitions` — the authoritative event list — rebuilds
> each successor through the same D2 engine, and accumulates
> `mass × dollars`. There is one production event queue and it is D2.6's.

### 10.2 D2.6 merge-key compatibility — the critical analysis

D2.6's recursion merges two scenario paths that reach the same expiration period
because their **futures are identical**. The sufficient state key
(D2 §5.5.1) is

```
(suite_id, expiration_period, lease_type, leased_area_sf)
```

reducing in practice to the expiration period. At D2 that reduction rested on
all three non-period dimensions being **invariant**. **D3 introduces the first
economics that could break that**, so the question must be settled before
implementation.

> **Amended at D3.3.** The invariance premise for `lease_type` is no longer
> true, and saying otherwise would leave a false statement supporting a true
> conclusion. Under HD-D3-1 a successor's type is resolved per branch, so a
> renewal and a new letting may differ from each other and from their
> predecessor. The reduction survives on the stronger ground stated below:
> `lease_type` is not merely constant, it is **not an input to any future
> economics**, and a quantity nothing reads cannot distinguish two states.
> `suite_id` and `leased_area_sf` remain genuinely invariant.

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

**Re-derived and asserted in code at D3.3**, as this section required, rather
than carried forward on the D2.6 analysis:

- `build_successor_contribution` lost its `lease_type` parameter. Its full
  argument list is now `(suite, analysis_start, months, market_schedule,
  parent_expiration_period, branch, lease_id_stem)` — no predecessor input of
  any kind survives — and that list is asserted **exhaustively**, so widening
  it fails a test.
- The production queue is `dict[int, list[float]]`, keyed on the expiration
  period alone. The annotation itself is asserted, so a key widened back to a
  tuple carrying `lease_type` fails rather than silently multiplying states.
- Four predecessors differing in lease type, recovery basis, expense stop,
  rent and identity, but sharing suite, area and expiration, produce
  **hex-identical** successor economics on both branches — dates, rent, term,
  TI, LC, chosen successor structure and recovery dollars — and identical
  recursion state and transition counts.
- Chain inheritance is banned by an AST guardrail across the whole package,
  not only at the call site that used to do it.

**What changed in production to make this true**: through D2.6 every caller
passed `lease_type=expiring.lease_type`, taken from the *original in-place
lease*, so a whole rollover chain carried the opening rent roll's structure
forever. That was the inheritance this section named as the design that would
break the key. D3.3 removed it.

**The design that would break it, named so it is not adopted by accident:**
chain inheritance — a successor taking its lease type or its stop *from its
immediate predecessor*. Then a renewal-of-an-NNN and a renewal-of-a-Gross
arriving at the same period would face different futures, `lease_type` would
re-enter the merge key as a live dimension, and the state count would multiply
by the number of reachable structures. Anchor would still be correct, but it
would have paid for a feature it did not choose.

**Required guardrail (D3.3, before D3.4 builds recursion on it):** a test that
**fails** if successor recovery pricing or successor lease-type resolution
begins reading, as a financial input, the predecessor's

- lease type,
- expense stop,
- recovery basis,
- or any recovery history.

This is the direct analogue of D2.6's existing "successor engine never reads a
predecessor lease" guardrail, which is what makes the merge proof mechanical
rather than aspirational.

> **Binding rule.** D3 may retain the D2.6 event-state merge architecture
> **only because** future successor recovery economics are path-independent. If
> such a dependency is ever introduced, the D2.6 state-sufficiency proof must be
> **re-derived, and the merge key re-established, before that change merges.**

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
| **4** | Modified Gross, pool above stop, **with `A_t ≠ A_p`** | `max(0, share × P_m − S × A_t / 12)`, hand-checked. Areas and the stop are chosen so the unit-incompatible form (FM-D3-18) yields a visibly different number |
| **5** | Expense growth crosses the stop | Zero recovery, then positive from the crossing month. **The case Modified Gross exists to model** |
| **6** | Fractional commencement, `D = 2.25`, on a **Modified Gross** lease | September recovery is **`0.75 ×`** the full-month obligation — the factor scales the obligation, not the expense share alone (§7.1.1, FM-D3-19) |
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
| **FM-D3-18** | **Dimensional error** — property-level pool dollars compared to a `$/SF` stop | **Golden 4**, dimensioned so the wrong form gives an obviously wrong figure (§5.3) |
| **FM-D3-19** | The responsibility factor applied to the expense share but **not** to the stop | **Golden 6**, built on a Modified Gross lease in a fractional commencement month (§7.1.1) |

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
| **D3.3** | Successor recovery assumptions | Branch-specific lease type and basis (HD-D3-1/2, both decided); **the merge-key guardrail — required here, before D3.4 builds recursion on it**, and the sufficiency proof re-derived rather than cited; renewal ≠ new-tenant structures; pure-branch recovery schedules | `contracts.py`, `rollover.py`, `recoveries.py`, `validation.py` |
| **D3.4** | Expected + recursive recoveries | Composition through `weighted_outcome` on completed branch dollars; recursion across generations by consuming D2.6's authoritative transitions rather than duplicating them; `p=0`/`p=1` endpoint identity; explicit-tree recovery oracle | `contracts.py`, `recoveries.py`, `rollover.py` (one identity helper and one resolver made public) |
| **D3.5** | Property recovery aggregation + D3 closeout | Lease → property monthly recovery; annual derived solely from monthly; full D3 golden suite; guardrails | `aggregation.py`, `contracts.py`, `validation.py`, tests |

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
| **HD-D3-1** | Where does a successor's **lease type** come from? | Inherit the original lease's type (today's behaviour) | Branch-specific `renewal_lease_type` / `new_lease_type` | **B — APPROVED** | A Gross tenant leaving and the space re-letting NNN is routine; inheritance asserts the structure never changes, forever. B also *preserves* the D2.6 merge key and is computationally cheaper than chain inheritance | Two fields on `MarketLeasingAssumptions`; setting `renewal_lease_type` to the in-place type reproduces A exactly. Exact naming chosen at D3.3 | **DECIDED** |
| **HD-D3-2** | May renewal and new tenant have **different recovery terms**? | One shared set | Branch-specific basis and stop | **B — APPROVED** | Symmetric with HD-D3-1 and with every other D2 assumption, all of which are already branch-specific. A renewal negotiating a stop while a new letting signs NNN is the normal case | Two nullable fields per branch; **never inherited** (§9.3, §10.2) | **DECIDED** |
| **HD-D3-3** | Which **basis representation** does D3 implement? | Expense stop `$/SF/year` | Base-year amount / calendar base year | **A — APPROVED** | A true base year needs historical actual expenses Anchor does not possess, and supporting it would tempt exactly the Hold-Year-1 substitution §6.1 forbids. The stop is what a lease abstract states. B remains available as a second enum member at zero structural cost | One enum member, one nullable field, units **`$/SF/YEAR`** | **DECIDED** |
| **HD-D3-4** | Does the stop **escalate**? | Nominally fixed | Grows at a stated rate | **A — APPROVED** | Commonest institutional form, smallest deterministic model, and it preserves the economically interesting behaviour (the pool crosses a fixed stop). Explicitly recorded rather than assumed | An optional growth field is additive later, as an **explicit** contractual assumption only | **DECIDED** |
| **HD-D3-5** | Does D3 support **per-category** recoverability? | Aggregate pool × ratio | Explicit categories | **A** | D0 §4.6/§16.3 already specify the ratio; per-category is D0 §16.5-deferred and is the first thing an institutional user will want, but it is not needed to underwrite credibly | Additive: the pool becomes a sum of category pools | **CAN DEFER** |
| **HD-D3-6** | Explicit **pro-rata share override**? | Area quotient only | Optional override wins | **A for D3** | D1's exact area reconciliation makes the quotient reliable, and no override means no denominator ambiguity. Real leases do state shares, so B will come | One nullable field, same precedence idiom as `Suite.market_rent_psf` | **CAN DEFER** |
| **HD-D3-7** | Are **recovery abatements** supported? | Unsupported; never inferred | Inferred from free rent | **A** | D2 §7.3 already locks that free rent has no automatic recovery effect. Inferring one would silently change every NNN lease with free rent | If needed later, an explicit input — never an inference | **CAN DEFER** |
| **HD-D3-8** | Does the **injected pool** stay injected through D4? | D3 injects; D4 supplies | D3 builds an expense engine | **A** | D0 §13.1 explicitly warns against a second expense engine in `anchor.leasing`, and D4 carries the G-2 obligation to prove Detailed bit-identical | D3 defines the contract; D4 satisfies it | **CAN DEFER** |

**All four blocking decisions are now DECIDED at D3.0 human financial review.**
HD-D3-1 and HD-D3-2 are approved as branch-specific and never inherited;
HD-D3-3 is approved as an explicit `$/SF/YEAR` expense stop with no base-year
label; HD-D3-4 is approved as a nominally fixed stop.

**No human decision blocks any D3 gate.** The four remaining items —
HD-D3-5 through HD-D3-8 — stay `CAN DEFER` and are deliberately left
**unresolved**: this amendment does not decide them, and D3 must not decide them
silently. Each has a stated D3 behaviour that is safe in the interim (aggregate
pool, area-quotient share, unsupported recovery abatement, injected pool).

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
3. **HD-D3-1 is decided, and the risk it carried is now closed.** Inheritance
   would have put `lease_type` back into the D2.6 merge key and multiplied the
   state count — a computational cost paid for an economic assertion
   (structures never change) that was not intended. The approved
   branch-specific design avoids both. The residual risk is only that a future
   change reintroduces inheritance by accident, which is what the D3.3
   guardrail (§10.2) exists to catch.
4. **Gross-up remains deferred and matters in a vacant building.** With no
   gross-up, a half-empty property recovers only half its pool. That is the
   honest arithmetic of the chosen convention, and it should be a disclosed
   sharp edge rather than a surprise at D4.

---

## 18A. Consistency audit — performed after the D3.0 review amendment

Every active statement was searched and reconciled against the four locked
decisions. Historical or rejected alternatives survive only where explicitly
labelled as such.

| Searched term | Result |
|---|---|
| Modified Gross formula | **Corrected.** Section 5.3 now states the tenant-level form as authoritative, records the equivalent property-level form, and names the unit-incompatible shorthand as rejected (FM-D3-18) |
| `expense stop` / `expense_stop_psf` | **Consistent.** Units stated as `$/SF/YEAR` at Sections 5.0, 6.2 and in the HD table. Converted to tenant monthly dollars by `× A_t / 12` |
| `base year` | **No active support.** Every occurrence is either the rejected calendar-base-year option (§6.2, HD-D3-3) or the prohibition on inferring one (§6.1) |
| Hold Year 1 | **Only** in §6.1's prohibition and §6.2's rationale. Never a fallback anywhere |
| successor lease type | **Locked branch-specific** (§9.2, HD-D3-1). No active statement implies permanent inheritance |
| `inherit` | Survives only in §9.2's description of *today's* D2 placeholder behaviour and in §9.3/§10.2 naming inheritance as the design **not** adopted |
| recovery basis | **Locked branch-specific and never inherited** (§9.3). Explicit-basis rule unchanged (§6.1) |
| recoverable expense pool | **Consistent.** One aggregate pool, management fee / CapEx / TI / LC / debt service excluded, categories not reopened (§3.1, §3.3) |
| responsibility factor | **Clarified.** In-place leases get `1.0` only while contractually active (§7.1); the factor scales the full-month obligation (§7.1.1) |
| free rent | **Consistent.** Does not reduce recoveries; abatement unsupported and never inferred (§8) |
| downtime | **Consistent.** `O_m = 0` in a fully vacant month; the fractional boundary uses D2.3's factor (§7.1, §7.3) |
| D2.6 / merge key | **Consistent and strengthened.** §10.2 now states the binding re-derivation rule and moves the guardrail to **D3.3**, before recursion is built on it |
| `CAN DEFER` items | **Untouched.** HD-D3-5 through HD-D3-8 remain undecided |

No financial convention accepted at D0, D1 or D2 was altered by this amendment.
Sections 1–4, 8 and 11–16 are substantively unchanged.

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

The post-review amendment is likewise documentation only — this one file. It
locked four decisions, corrected the Modified Gross formula's dimensions, and
clarified three rules. It changed no accepted financial convention.

No D3 production code exists. **HD-D3-1 through HD-D3-4 are decided, so no human
decision blocks any D3 gate. D3.1 may begin.**


---

## 21. D3 closeout — recorded at D3.5

**D3.0 through D3.5 are implemented**, and every gate was accepted at human
financial review. `anchor.leasing` remains dark to the rest of Anchor: nothing
outside the package changed across the sprint.

> **Closed at D3.6.** Section 21.4 disclosed one limitation — a suite vacant
> at the analysis start recovered zero for the whole projection, with no
> lease-up and no way to say whether that was intended. Section 22 is now
> **implemented**: an initially vacant suite states `HOLD_VACANT` or
> `MARKET_LEASE_UP` explicitly, and stating neither is an error at every
> future-looking gate. Everything else in Section 21 is unchanged.

### 21.1 The delivered contracts

| Layer | Contract | Question it answers |
|---|---|---|
| Input | `RecoverableExpensePool` | What is recoverable this month, at the property? (**injected**, never built here) |
| Known lease | `LeaseRecoverySchedule` | What does this sitting tenant reimburse? |
| Pure branch | `SuccessorRecoverySchedule` | What would a renewal — or a new letting — reimburse? |
| First rollover | `ExpectedRolloverRecovery` | What does one rollover reimburse in expectation? |
| All generations | `RecursiveRolloverRecovery` | ...and across every successor generation? |
| Aggregation seam | `SuiteRecoveryProjection` | One suite's finished dollars, and nothing else |
| Property | `PropertyRecoverySchedule` | What does the property reimburse, monthly and annually? |

`suite_recovery_projection` is the single extraction seam: any of the three
authoritative full-chain results projects onto the same narrow boundary, so
property aggregation has one input shape rather than one formula per result
type. It copies an already-computed series and performs no arithmetic.

### 21.2 Where each economic decision lives — exactly once

The NNN rule, the Gross zero, the Modified Gross clip, the `$/SF/YEAR` → monthly
conversion and the responsibility-factor placement are each singular in
`recoveries.py`. Probability weighting is singular in `weighted_outcome`. The
rollover event recursion is singular in `build_recursive_rollover`. Property
aggregation adds a sum and nothing else. Each of those is asserted structurally,
not merely tested.

### 21.3 Failure-mode closeout

All nineteen registered failure modes (Section 13) are closed and **traceable**:
each is cited in the contract, validator, architecture guardrail or golden that
enforces it, so the register can be walked from the document to the test that
would fail. No failure mode is deferred.

### 21.4 Carried forward — deliberately unresolved

| Item | Status | D3 behaviour in the interim |
|---|---|---|
| **HD-D3-5** per-category recoverability | `CAN DEFER`, undecided | One aggregate pool × ratio (Section 3.1) |
| **HD-D3-6** pro-rata override / gross-up denominator | `CAN DEFER`, undecided | Area quotient only; **no gross-up** (Section 4) |
| **HD-D3-7** recovery abatement clauses | `CAN DEFER`, undecided | Unsupported and never inferred from free rent |
| **HD-D3-8** authoritative pool construction | `CAN DEFER`, undecided | Pool injected; D4 supplies it |

**No human decision blocks D4.** Each interim behaviour is a stated convention
with a guardrail, not an accident.

#### The initial-vacancy limitation — **closed at D3.6**

This section originally recorded a product limitation: D2/D3 rollover begins
from a **known lease's expiration**, so a suite vacant at the analysis start
had no expiration event, no successor chain, and recovered zero for the entire
projection with no lease-up modelled.

**D3.6 closed it.** An initially vacant suite now states its treatment
explicitly on `Suite.initial_vacancy`:

- **`HOLD_VACANT`** — the same zero economics as before, but now a *stated
  assumption* recorded on the result and visible in the property aggregation;
- **`MARKET_LEASE_UP`** — the space lets after an explicit
  `initial_lease_up_months`, the first tenant is a deterministic market new
  tenant, and its eventual expiration enters the existing D2.6 recursion.

**Stating neither is an ERROR** at every future-looking gate — the
initial-vacancy builder and property recovery aggregation
(`MISSING_INITIAL_VACANCY_TREATMENT`). D1 is unchanged: a bare vacant suite is
still valid there, because zero contractual rent for empty space is an
observation rather than a speculation (HD-D3.6-1).

Section 22 carries the full conventions, the worked cases and the failure
modes.

**Two limitations remain, and both are honest consequences of accepted
conventions rather than gaps:**

1. **No gross-up** (HD-D3-6, deferred). A half-empty property recovers only
   about half its pool, because unrecovered expense is never redistributed
   onto the tenants who do pay (Section 18.4). With `MARKET_LEASE_UP` now
   available, a vacant suite's *own* recovery can begin once it lets — but
   during the lease-up period its share of the pool is still simply
   unrecovered.
2. **Lease-up is deterministic.** `MARKET_LEASE_UP` states one lease-up
   period, not a distribution over several. Stochastic or phased lease-up,
   multiple competing tenants and partial-floor demising all remain non-goals
   (Section 22.20).

### 21.5 What D3 deliberately does not do

D3 stops at *"monthly recovery revenue, by lease and by property"*. It builds
no expense schedule, applies no `recoverable_expense_ratio`, computes no
management fee, and never nets a recovery against an expense — recoveries are
revenue on their own line (D0 Section 10.2). EGI, credit loss, NOI, exit NOI
and the D0 Section 16.4 ordering all need the expense engine and the revenue
build that **D4** owns.

---

## 22. D3.6 — initial vacancy lease-up

**Part A** (architecture and proof) was accepted at human review. **Part B is
implemented**: the conventions below are production behaviour, verified by 61
goldens in `tests/test_leasing_d3_6_initial_vacancy.py`, 13 architecture
guardrails and 15 mutants.

Part A's baseline was `3e324b3`: full backend 3583, full leasing 1810, D1 787,
D3.1 78, D3.2 76, D3.3 56, D3.4 61, D3.5 45, architecture guardrails 140,
Quick 217, Detailed 62. After Part B: full backend 3657, full leasing 1884,
architecture guardrails 153, with every earlier gate's count unchanged and D1,
D2 and D3.1–D3.5 economics **bit-identical** (300 series, 9,740 values).

**What Part B changed relative to Part A's proposal**, and nothing else:

- the D2.6 propagation loop was extracted into `_propagate_rollover_mass`
  exactly as designed. The accumulators are passed **in already seeded** so the
  sequence of floating-point additions is unchanged by construction — the
  refactor is bit-preserving rather than merely intended to be;
- the timing seam is an explicit `event_downtime_months` parameter on
  `build_successor_contribution`, defaulting to `None`. Part A left the seam's
  shape open; an explicit parameter was chosen over an assumptions adapter
  because it overrides **timing only**, is structurally confined to the one
  call that passes it, and cannot write back onto the resolved assumptions;
- D3.4's transition walk was factored into `_attach_recovery_to_transitions`,
  so the occupied and vacant recovery paths share one attachment as well as one
  state machine.

### 22.1 The limitation being closed

Section 21.4 disclosed it: D2/D3 rollover begins from a **known lease's
expiration**. A suite vacant at the analysis start has no lease, therefore no
expiration event, therefore no successor chain — so it produces zero rent and
zero recovery for the entire projection, and Anchor models no lease-up.

That answer is correct *only* when the analyst intends to hold the space
vacant. Today it is also what happens when lease-up assumptions were simply
never supplied, and the two are indistinguishable in the output. For a
value-add acquisition — the case where vacant space is the whole thesis — a
silent zero is the most expensive kind of wrong number, because it looks like
a modelled result.

**D3.6 makes the treatment explicit.** It does not change what a
deliberately-vacant suite produces; it makes "deliberately" a stated input.

### 22.2 The two treatments — LOCKED

```
InitialVacancyStrategy.HOLD_VACANT      -- no speculative lease-up, by choice
InitialVacancyStrategy.MARKET_LEASE_UP  -- leases after a stated lease-up period
```

A one-member enum was not an option here: the whole point is that the two
outcomes are different underwriting statements, and a suite must say which it
is.

### 22.3 Where the assumption lives — **`Suite`**, not `MarketLeasingAssumptions`

**Decision: a nullable `Suite.initial_vacancy` field holding an immutable
`InitialVacancyAssumptions` record.**

```
class InitialVacancyStrategy(StrEnum):
    HOLD_VACANT = "hold_vacant"
    MARKET_LEASE_UP = "market_lease_up"


@dataclass(frozen=True, slots=True, kw_only=True)
class InitialVacancyAssumptions:
    strategy: InitialVacancyStrategy
    initial_lease_up_months: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Suite:
    ...
    initial_vacancy: InitialVacancyAssumptions | None = None
```

**Why not `MarketLeasingAssumptions`**, despite that record already existing
and already being resolvable per suite:

1. **It answers a different question.** `MarketLeasingAssumptions` describes
   *how the market lets space* and governs **every future rollover of every
   suite**. Initial vacancy describes **one suite's starting state**, which
   happens once and never recurs. Putting a starting-state field on a
   market-behaviour record makes it meaningless on every occupied suite.
2. **Vacant suites genuinely differ.** A ground-floor retail unit and a
   fourth-floor office suite in the same building lease up on different
   timelines. A property-level default with a per-suite override would express
   that, but the default has no natural value: there is no "property-wide
   initial lease-up period" that means anything.
3. **The all-or-nothing override rule would bite.** `MarketLeasingAssumptions`
   requires **every** field with no defaults (D0 §24.2), enforced
   structurally. Adding two fields there would force every existing suite-level
   override to state an initial-lease-up assumption it does not have.
4. **D5 has to ask a question.** The UI question is *"this suite is empty —
   how should we underwrite it?"*, asked once per vacant suite. A field on
   `Suite` is exactly that question in the data model.

**Consequence: no property default, no suite override, no resolution
hierarchy.** The assumption is stated per vacant suite or it is absent, and
absent is an error (§22.10) rather than a default.

### 22.4 Lease-up timing — LOCKED, and it is the D2.3 rule at period 0

For a market lease-up period `L ≥ 0` (months, finite, fractional allowed):

```
c0 = 0 + 1 + floor(L)

O_m = 0            for m < c0
O_m = 1 − frac(L)  at m = c0
O_m = 1            thereafter, while the first lease is active
```

`initial_lease_up_months` is a **distinct field** and is never
`new_downtime_months` (LOCKED). Downtime after a *future* expiration is a
re-letting delay on space a departing tenant just vacated; initial lease-up is
how long empty space at acquisition takes to fill. They are different
underwriting judgements and today they would alias onto one field.

| `L` | `c0` | Months 1…c0−1 | `O` at `c0` |
|---|---|---|---|
| `0` | 1 | none | `1.00` |
| `2` | 3 | 1–2 vacant | `1.00` |
| `2.25` | 3 | 1–2 vacant | `0.75` |
| `14` | 15 | 1–14 vacant | `1.00` |

**No mid-month lease date.** The lease commences on
`month_start(c0)`; the fraction is carried entirely by `O`, exactly as D2.3
established. The total month-equivalents forgone is exactly `L`.

### 22.5 The architecture — period 0 into the **existing** successor engine

**Decision: build the first tenant with
`build_successor_contribution(parent_expiration_period=0, branch=NEW_TENANT)`,
and seed the existing D2.6 propagation at its expiration.**

This was verified against the shipped code before being proposed, not assumed:

| Probe | Result |
|---|---|
| `successor_commencement_period(e=0, D=L)` | returns `1 + floor(L)` — the required formula, no lower bound on `e` |
| `build_successor_contribution(parent=0)` | **accepted unmodified** for `L ∈ {0, 2.25, 14, 60}` |
| `O` for `L = 2.25` | `[0, 0, 0.75, 1, 1]` — exactly the rule above |
| `physical_occupancy` at the boundary | `1.0` — integral, HD-D2-2 preserved |
| `occupied_area` at the boundary | full suite area — integral |
| `contractual_base_rent` at the boundary | **full** month's face rent; the fraction lands in `cash_base_rent` via `O` |
| Market pricing, `L = 14` | `$41.20` = `$40 × 1.03¹` at `c0 = 15`, **not** the analysis-start `$40` |
| TI / LC | TI in the first `O > 0` month; LC on full untruncated contractual term |
| Recovery through `build_successor_recovery_schedule` | `[0, 0, 7500, 10000, 10000]` for MG at a `$10,000` stop — no new seam |

**Every `SuccessorContribution` invariant holds at `parent = 0`:**

- *"zero at or before the parent's expiration"* is **vacuous**: no `ModelMonth`
  has `period_index ≤ 0`, so month 1 is free to be non-zero, which is exactly
  what `L = 0` needs.
- *"successor expiration strictly later than the parent's"* holds trivially,
  since `e1 = c0 + T − 1 ≥ 1 > 0`.

#### Period 0 is a boundary, not a lease

`0` is **not** a `ModelMonth`, **not** a lease expiration, and **never**
surfaced as a fake historical lease. It is the integer immediately before
canonical month 1, and it exists so that one commencement formula serves both
entry paths. **No fake lease, zero-day lease, dummy expiration, synthetic
tenant or fabricated contractual rent is created anywhere** — the prohibition
is absolute and is proposed as an architecture guardrail (§22.16).

### 22.6 First-tenant economics — reuse, confirmed safe

The first tenant is economically a **market new tenant**. Every economic input
other than the lease-up *timing* reuses the approved new-tenant assumptions:

| Input | Source | Safe to reuse? |
|---|---|---|
| Starting rent | `MarketRentPSF(c0)` | **Yes** — the market moved while the space sat empty; pricing at `c0` is the same rule every successor already follows |
| Term | `new_term_months` | Yes |
| Escalation | `successor_escalation_pct` | Yes |
| Free rent | `new_free_rent_months` | Yes — D2.3 waterfall unchanged |
| TI | `new_ti_psf` | Yes |
| LC | `new_lc_pct`, full-term face basis | Yes |
| Lease type | `new_lease_type` | Yes |
| Recovery basis / stop | `new_recovery_basis`, `new_expense_stop_psf` | Yes |
| **Lease-up delay** | **`initial_lease_up_months`** | **No — distinct field, LOCKED** |

`renewal_rent_psf` and `renewal_rent_spread` are **never** consulted: there is
no incumbent to renew. No parallel "initial TI / initial LC / initial term /
initial structure" fields are created — inventing them for symmetry would
double the assumption surface for no financial content, and the competition
model changes only the *time*.

### 22.7 Probability — the first tenant is deterministic

There is no incumbent, so there is no renewal/new-tenant split at the initial
event. The first tenant is a **new tenant at probability mass `1.0`**.
`renewal_probability` is **not** applied to it and no `p·x + (1−p)·y`
composition occurs.

`p` enters at the **first lease's expiration** and not before:

```
initial vacancy ──(mass 1.0, deterministic)──▶ first tenant
                                                    │ expires at e1
                                                    ▼
                                        ┌───────────┴───────────┐
                                     p  │                       │ 1−p
                                   renewal                 new tenant
                                        └── existing D2.6, unchanged ──▶
```

**Mass invariants.** Before `e1`, the first-tenant path carries mass `1.0`.
At `e1`, mass `1.0` splits into `p` and `1−p`, and D2.6's existing
conservation applies from there. `HOLD_VACANT` creates no scenario split at
all. If `c0 > N` no lease begins, so no rollover mass is ever created and
terminal mass is `1.0` at the un-rolled state.

### 22.8 The D2.6 handoff, and the one refactor required

| First lease outcome | Behaviour |
|---|---|
| `c0 > N` | Vacant every month. No in-window rent, occupancy, TI, LC or recovery. **No state seeded.** |
| `c0 ≤ N`, `e1 ≥ N` | First tenant contributes through month `N`. LC still on the **full** contractual term. **No state seeded** — D2.6 already declines to enqueue a child expiring at or beyond the horizon. |
| `e1 < N` | First tenant contributes; **the existing propagation is seeded at `(e1, mass 1.0)`** and owns every later generation. |

#### The refactor: one propagation core, two entry paths

`build_recursive_rollover` today does three things in one body: (1) seeds its
accumulators with the **in-place lease's own** monthly history, (2) seeds
`incoming = {initial_expiration: [1.0]}`, and (3) runs the mass-propagation
loop. Only (3) is shared.

**Proposed narrow refactor** — extract (3) into an internal
`_propagate_rollover_mass(...)` taking the suite, months, resolved
assumptions, market schedule, renewal probability, an identifier stem root,
and a mapping of **seed expiration periods to probability mass**; returning
successor-only accumulations, the transition and event-state audits, and the
terminal mass.

```
build_recursive_rollover      : in-place lease history  + _propagate({e_inplace: 1.0})
build_initial_vacancy_rollover: first-tenant contribution + _propagate({e1: 1.0})
```

This is the **only** structural change to D2, it is behaviour-preserving by
construction (the loop body moves unmodified), and Part B must prove D1, D2
and D3.1–D3.5 **bit-identical** for every property containing no
market-lease-up suite.

**No second recursion engine.** Initial vacancy is a new *entry path* into the
one production state machine, never a parallel queue. The existing D3.4
guardrails — no `while` loop and no queue vocabulary outside `rollover.py` —
extend unchanged, and a new guardrail asserts exactly one propagation core
exists and that both builders call it.

#### Why not simply call `build_recursive_rollover` on the first lease

**Rejected, and the reason is financial.** That function treats its argument
as a *known in-place lease*: it contributes `initial_schedule` — a plain D1
contractual rent schedule — which has **no** lease-up vacancy, **no**
fractional boundary factor, **no** free-rent waterfall, **no** TI and **no**
LC. Feeding the first speculative lease in that way would silently discard
every concession and cost that makes it speculative, and would assert the
tenant was already in place at acquisition. The first tenant is a
*successor*, and must be built by the successor engine.

### 22.9 Anti-double-counting — the structural rule

> **An initial-vacancy chain has no known in-place lease.** The first tenant is
> a **successor contribution at mass 1.0 relative to period 0**, and it already
> carries the vacancy months as zeros. Generations 2+ come only from the
> propagation core, seeded once at `e1`. Therefore each of the vacancy period,
> the first tenant, and every later successor is recognised **exactly once**,
> and there is no lease history that could be added twice.

Enforced structurally, not by inspection:

- `InitialVacancyRollover` declares **no** `initial_lease` / `initial_schedule`
  field — there is no known lease, so no field can hold one.
- The first contribution's `parent_expiration_period` is asserted `== 0`.
- The propagation core returns **successor-only** series, and its seed is
  `e1`, so no generation re-counts an earlier one.
- The existing `SuccessorContribution` invariant already forbids a child
  contributing at or before its own parent's expiration.

Verified: with `L = 2.25`, the first contribution's months 1–2 are zero in
rent, occupied area, TI and LC; TI lands in month 3, the first `O > 0` month.

### 22.10 Validation — the missing-treatment error is the point

| Code | Severity | Rule |
|---|---|---|
| `MISSING_INITIAL_VACANCY_TREATMENT` | **ERROR** | A suite with no lease and no `initial_vacancy`. *This is the limitation being closed.* |
| `INITIAL_VACANCY_ON_OCCUPIED_SUITE` | **ERROR** | A suite that has a lease but also carries `initial_vacancy` — a financial field that would be silently ignored |
| `MISSING_INITIAL_LEASE_UP_MONTHS` | **ERROR** | `MARKET_LEASE_UP` without `initial_lease_up_months` |
| `INITIAL_LEASE_UP_ON_HOLD_VACANT` | **ERROR** | `HOLD_VACANT` carrying a lease-up period — half-stated intent |
| `INITIAL_LEASE_UP_OUT_OF_DOMAIN` | **ERROR** | `initial_lease_up_months` negative or non-finite |

**Scope: a separate `validate_initial_vacancy_inputs`, not
`validate_lease_level_inputs`** — the same discipline D3.1 established for
recoveries. A bare vacant suite remains valid input to **D1**, where zero
contractual rent for empty space is a fact rather than a speculation. The
error fires at the gates that model the *future*: the initial-vacancy builder
and property aggregation. See **HD-D3.6-1**.

**No silent fallback is permitted anywhere**: a missing treatment never means
hold-vacant, missing lease-up months never fall back to `new_downtime_months`,
missing first-tenant structure is never inherited from a predecessor that does
not exist, missing recovery terms are never inferred as Gross, starting rent is
never frozen at the analysis start, and the first tenant is never
probability-weighted.

### 22.11 Result contracts

**`InitialVacancyRollover`** — the full chain: vacancy, the deterministic first
tenant, and every later expected successor generation, through `12H + 12`.

Its monthly series carry **the same names as `RecursiveRollover`'s**
(`expected_contractual_base_rent`, `expected_cash_base_rent`,
`expected_free_rent`, `expected_tenant_improvements`,
`expected_leasing_commissions`, `expected_occupied_area_sf`,
`expected_occupancy`, `expected_vacant_area_sf`, `expected_vacancy`,
`expected_successor_occupancy_factor`, `expected_free_rent_abatement_months`,
`expected_cash_rent_factor`), so **D4 sees one economic shape** whether a suite
began occupied or empty. It additionally retains the strategy, the lease-up
months, and the first-tenant `SuccessorContribution` for audit, plus the event
and transition audits and terminal mass from the propagation core.

For `HOLD_VACANT` the same contract is returned with every series zero, the
strategy recorded, no first-tenant contribution, no transitions and terminal
mass `1.0`. One builder, one return type, and the intention is visible in the
output.

**`InitialVacancyRolloverRecovery`** — the recovery analogue, mirroring
`RecursiveRolloverRecovery`: `expected_expense_recovery` plus the
contribution audits. Because there is no known in-place lease, the "in-place"
series is identically zero and the full chain equals the successor series;
Part B should decide whether to keep the three-series shape for symmetry with
D3.4 or collapse it (**recommend: keep it**, so `suite_recovery_projection`
and any D4 reader see one shape).

**The pool stays injected.** No D2 builder gains a `RecoverableExpensePool`
parameter; the recovery result is produced from the finished leasing result
plus the pool, exactly as D3.3–D3.5 established.

### 22.12 D3.5 property aggregation

`suite_recovery_projection` gains `InitialVacancyRolloverRecovery` as a fourth
accepted authoritative result. Nothing else in aggregation changes: it still
sums finished dollars, still performs no gross-up, still applies no
probability.

- **`MARKET_LEASE_UP`** → a projection carrying the suite's full-chain recovery
  dollars.
- **`HOLD_VACANT`** → an **explicit all-zero projection** (recommended over
  omission), so the suite appears in `suite_projections` and a reader can see
  it was deliberately underwritten as vacant rather than forgotten. See
  **HD-D3.6-3**.

D3.5's completeness rule extends from *"every suite with a lease"* to *"every
suite with a lease **or** an explicit initial-vacancy treatment"*.
`MISSING_SUITE_RECOVERY_SCHEDULE` then covers a forgotten vacant suite too.
**No fake `LeaseRecoverySchedule` is ever synthesized.**

### 22.13 State merging after the first lease — proved

Once the first speculative lease expires, its event state must be
**financially indistinguishable** from an equivalent event on an
originally-occupied suite. Otherwise initial-state history would re-enter the
D2.6 merge key and the state-compression architecture would break.

**Proved against the shipped engine.** Two origins reaching expiration period
14 in the same suite under the same resolved assumptions — one a vacant-suite
first tenant (`L = 2.25`, `T = 12`), one an ordinary occupied lease — produce
successors whose **ten monthly series and eight scalars are all identical**,
on both branches:

```
renewal      10/10 series identical, 8/8 scalars identical
new_tenant   10/10 series identical, 8/8 scalars identical
only difference: the lease_id label, already proven inert
```

This follows from D3.3's result: a successor is a function of
`(suite, resolved assumptions, parent expiration period, branch kind, months,
market schedule)` and of nothing else. None of those carries initial-state
history. **The D2.6 merge key remains the expiration period alone.**

### 22.14 Computational complexity

One deterministic first-tenant contribution, then at most **one** seed state
into the existing propagation. States stay bounded by `N` and transitions by
`2N`, unchanged. No path tree, no new cap, no explosion — an initially vacant
suite costs one extra contribution over an occupied one.

### 22.15 Hand-worked cases

Frame: `analysis_start = 2027-01-01`, 20,000 SF suite in a 100,000 SF property
(share `0.20`), `H = 3` so `N = 48`. Market `$40.00/SF/YR` growing `3%`
annually on analysis-start anniversaries. Monthly recoverable pool `$100,000`,
so the tenant share is `$20,000/month`.

**CASE A — `HOLD_VACANT`.** Every month: face rent `0`, cash rent `0`, free
rent `0`, TI `0`, LC `0`, occupied area `0`, occupancy `0`, recovery `0`. No
lease object, no transitions, terminal mass `1.0`. Identical numbers to
today's silent result — but now a stated assumption, visible in the output.

**CASE B — `MARKET_LEASE_UP`, `L = 0`.** `c0 = 1`, `O_1 = 1.0`. Verified: the
first tenant commences 2027-01-01, `e1 = 12` for `T = 12`, starting rent
`$40.0000` (Month 1 market, no step yet), TI `$1,000,000` at `$50/SF`, LC
`$48,000` = `6% × $800,000` full-term face.

**CASE C — `L = 2.25`.** `c0 = 3`. Verified `O = [0, 0, 0.75, 1, 1, …]`.
Months 1–2 fully vacant. Month 3: physical occupancy `1`, occupied area
`20,000 SF`, face rent the **full** `$66,667`, cash rent `0.75 × $66,667 =
$50,000`. The fraction is economic, never physical, never a mid-month date.

**CASE D — market step.** `L = 14` → `c0 = 15`, in hold year 2. Verified
starting rent `$41.2000 = $40 × 1.03¹`, **not** `$40`. Market rent moves while
the space sits empty.

**CASE E — lease-up vs future downtime.** `initial_lease_up_months = 6`,
`new_downtime_months = 2`. First tenant waits **6** months (`c0 = 7`); a
replacement after a future expiration waits **2** (`c = e + 3`). Confirmed
these alias onto one field today, which is why the distinct field is required.

**CASE F — free rent + TI + LC.** `L = 2.25`, `F = 2.5`. Verified:

| Month | `O` | abatement | cash factor | face | cash |
|---|---|---|---|---|---|
| 1 | 0 | 0 | 0 | 0 | 0 |
| 2 | 0 | 0 | 0 | 0 | 0 |
| 3 | 0.75 | 0.75 | 0 | 66,667 | 0 |
| 4 | 1 | 1.00 | 0 | 66,667 | 0 |
| 5 | 1 | 0.75 | 0.25 | 66,667 | 16,667 |
| 6 | 1 | 0 | 1.00 | 66,667 | 66,667 |

Vacancy and free rent stay **distinct**: months 1–2 have no tenant and consume
no abatement; month 3 has a tenant present for 0.75 of the month who consumes
0.75 of the 2.5-month grant. TI lands in month 3 — the first `O > 0` month —
and LC on the full contractual face rent.

**CASE G — first tenant Modified Gross.** `new_lease_type = MODIFIED_GROSS`,
stop `$6.00/SF/YR` on 20,000 SF = `$10,000/month`; tenant share `$20,000`.
Verified recovery `[0, 0, 7500, 10000, 10000, …]` — zero during vacancy,
`0.75 × max(0, 20,000 − 10,000)` at the boundary with the factor **outside**
the clip, then the full `$10,000`. No initial-vacancy recovery formula exists.

**CASE H — expiry inside horizon, then `p`.** `L = 2` (`c0 = 3`), `T = 12`
→ `e1 = 14 < 48`. Periods 3–14: first tenant, mass `1.0`, no `p` anywhere.
At period 14 mass `1.0` splits `0.60 / 0.40`, and D2.6 owns everything after.

**CASE I — term beyond horizon.** `L = 0`, `T = 120` → `c0 = 1`,
`e1 = 120 > 48`. Verified: contributes through month 48 (`$70,747` in month
48 with escalation), LC basis `$8,759,777` on the **full** term versus
`$3,297,286` of in-window face rent — untruncated, as D2.4 requires. No state
seeded, no recursion.

**CASE J — commencement beyond horizon.** `L = 60` → `c0 = 61 > 48`. Verified
every in-window series is zero: rent, cash, occupied area, TI, LC. No state
seeded. Lease-up is never moved earlier and no `ModelMonth` is fabricated.

**CASE K — expiry in the forward exit window.** `e1` in months `12H+1 … 12H+12`
is still `< N`, so the state is seeded and later successors contribute in the
remaining forward months. **No sale-month cutoff** — the same rule D3.4 already
follows.

**CASE L — mixed property.** Suite A occupied NNN; Suite B vacant
`MARKET_LEASE_UP`; Suite C vacant `HOLD_VACANT`; Suite D occupied Gross.
Property recovery sums A's chain, B's full chain, C's explicit zeros and D's
zeros. Every suite appears in the aggregation audit; **none disappears
silently**.

**CASE M — future state is origin-independent.** Proved in §22.13 against the
shipped engine: identical successors from a vacant-origin and an
occupied-origin chain reaching the same period.

### 22.16 Failure modes — D3.6 additions

| ID | Failure | Detection |
|---|---|---|
| **FM-D3-20** | A vacant suite silently stays vacant because assumptions were never supplied | `MISSING_INITIAL_VACANCY_TREATMENT` ERROR; hold-vacant must be *stated* |
| **FM-D3-21** | A fake / zero-day / expired dummy lease used as the entry state | Guardrail: no `Lease` is constructed with a fabricated expiration; `InitialVacancyRollover` declares no in-place lease field |
| **FM-D3-22** | Initial lease-up silently reusing `new_downtime_months` | Distinct field; CASE E golden with `6` vs `2` |
| **FM-D3-23** | The first tenant probability-weighted | Guardrail: `weighted_outcome` never reached with the first contribution; CASE H |
| **FM-D3-24** | Market rent frozen at analysis start for the first tenant | CASE D — `$41.20`, not `$40.00` |
| **FM-D3-25** | The fractional boundary published as fractional *physical* occupancy | CASE C — physical `1`, economic `0.75`; extends FM-D2-19 |
| **FM-D3-26** | Initial vacancy and free rent conflated | CASE F table |
| **FM-D3-27** | First TI or LC omitted, or LC truncated to the projection | CASES B, F, I |
| **FM-D3-28** | Recovery charged during initial vacancy | CASE G — zero before `c0` |
| **FM-D3-29** | The first lease counted twice — as both a contribution and known history | §22.9 structural rule; no in-place field exists to hold it |
| **FM-D3-30** | The first lease fed into `build_recursive_rollover`, losing its concessions and costs | §22.8 rejection; guardrail that the initial-vacancy builder does not call it |
| **FM-D3-31** | A second, vacancy-specific recursion engine | Guardrail: exactly one propagation core; both builders call it |
| **FM-D3-32** | Initial-vacancy history contaminating future D2.6 state merging | CASE M / §22.13 |
| **FM-D3-33** | Recovery or recursion truncated at the sale month | CASE K |
| **FM-D3-34** | `HOLD_VACANT` indistinguishable from missing assumptions | Distinct enum member, recorded on the result, and an explicit all-zero projection |

### 22.17 Human decisions

| ID | Question | Options | Recommended | Why | Consequence | Blocks Part B? |
|---|---|---|---|---|---|---|
| **HD-D3.6-1** | Should a bare vacant suite (no treatment) be an ERROR in the **general** D1 validator, or only at the gates that model the future? | A: general `validate_lease_level_inputs` — every existing caller must now state a treatment. B: scoped `validate_initial_vacancy_inputs`, used by the initial-vacancy builder and property aggregation | **B** | D1 is contractual rent: zero for empty space is a *fact*, not a speculation, and A would break every existing D1 call site and test for no financial gain. B places the error precisely where a silent zero would be a *modelling* claim. Mirrors the D3.1 scoping decision exactly | B keeps D1 bit-identical; the guarantee is slightly narrower — a D1-only caller can still aggregate a bare vacant suite | **No** — recommendation is safe either way |
| **HD-D3.6-2** | When `c0 > N`, should the first-tenant contribution be built at all? | A: build it; every in-window series is already zero, and the full-term metadata records *why* nothing appears. B: skip construction and return zeros directly | **A** | Verified all in-window series are zero, so A and B are financially identical. A is auditable — a reader can see the lease-up period pushed commencement to period 61 — and it needs no branch in the builder, so there is no second code path to keep correct | A retains a `SuccessorContribution` whose in-window contribution is zero; Part B must assert that zero rather than assume it | **No** |
| **HD-D3.6-3** | Should `HOLD_VACANT` produce an explicit all-zero recovery projection, or no projection at all? | A: explicit all-zero projection. B: no projection, as for a suite with no lease today | **A** | The whole gate is about making deliberate vacancy *visible*. Under B a hold-vacant suite is indistinguishable in the aggregation audit from one nobody thought about — the exact failure D3.6 exists to close (FM-D3-34) | A means `suite_projections` lists every suite; D3.5's completeness rule extends to vacant suites carrying a treatment | **No** |

**No decision blocks Part B.** Each recommendation is implementable as stated
and none changes the locked timing, probability or reuse rules.

### 22.18 Part B implementation plan

1. **`contracts.py`** — `InitialVacancyStrategy`, `InitialVacancyAssumptions`,
   `Suite.initial_vacancy`, `InitialVacancyRollover`,
   `InitialVacancyRolloverRecovery`.
2. **`rollover.py`** — extract `_propagate_rollover_mass` from
   `build_recursive_rollover` (behaviour-preserving); add
   `build_initial_vacancy_rollover` calling the successor engine at
   `parent_expiration_period = 0` and seeding the core at `e1`.
3. **`recoveries.py`** — `build_initial_vacancy_rollover_recovery`, reusing
   `build_successor_recovery_schedule` and the existing `_recovery_series`
   core. No new formula.
4. **`aggregation.py`** — `suite_recovery_projection` accepts the new result;
   extend D3.5 completeness to vacant suites carrying a treatment.
5. **`validation.py`** — the five codes in §22.10, in a scoped validator.
6. **Tests** — a new `tests/test_leasing_d3_6_initial_vacancy.py` with CASES
   A–M as goldens, plus a **test-only explicit chain oracle** (§22.19).
7. **Architecture guardrails** — one propagation core and both builders using
   it; no fake lease construction; the first contribution never weighted; no
   aliasing of `new_downtime_months`; no in-place field on the vacancy result.
8. **Mutation tests** — at minimum: first tenant probability-weighted; lease-up
   aliased to `new_downtime_months`; market rent frozen at analysis start;
   fractional boundary applied to physical occupancy; first lease counted
   twice; a separate vacancy queue; recovery charged during vacancy;
   `HOLD_VACANT` silently equal to a missing treatment.
9. **Bit-identity proof** — D1, D2 and D3.1–D3.5 hex-identical against
   `3e324b3` for every property with no market-lease-up suite.
10. **Docs** — convert this section from *proposed* to *implemented* at
    closeout, and update Section 21.4 to record the limitation as closed.

### 22.19 The explicit-chain oracle (test only)

For a short horizon, enumerate the complete scenario chain independently:
vacancy → deterministic first tenant → one or two renewal/new splits, pricing
each path with the D3 formulas and weighting by its own path probability.
Compare against production within the accepted `rel 1e-12 / abs 1e-9`. It is
the same idiom as D3.4's recovery oracle, extended by one deterministic step
at the front, and it stays **test-only** — an explicit path tree is exactly
what the accepted architecture replaces.

### 22.20 Non-goals

D3.6 does not implement NOI, EGI, the management fee, property expense
construction, `recoverable_expense_ratio`, or any acquisition, debt or returns
integration; nor gross-up, recovery abatements, per-category recoverability,
tenant-specific leasing probability, stochastic or phased lease-up, multiple
competing tenants, or partial-floor demising. The interim behaviours recorded
in §21.4 for HD-D3-5 through HD-D3-8 are unchanged.
