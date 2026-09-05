---
title: Lease-Level Underwriting - D2 Rollover Financial Conventions
type: feat
date: 2026-09-05
topic: lease-level-underwriting
artifact_contract: ce-unified-plan/v1
artifact_readiness: awaiting-human-financial-decision
execution: docs-only
sprint: D
gate: D2.0
baseline_commit: 9cca23d
---

# Lease-Level Underwriting — D2 Rollover Financial Conventions

## Status

**Financial-design gate only. No production code, no test, no change to
`src/anchor/leasing/`, no change to D1 economics.** This document resolves the
deterministic economics of lease rollover *before* those conventions enter
code.

Verified baseline (`main` @ `9cca23d`): leasing suite 810 passed, full backend
2583 passed, Quick and Detailed bit-identical, D1 isolated from the rest of
Anchor.

This document **does not overwrite**
`docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md`
(hereafter D0). Where it recommends changing a D0-approved convention, that
change is recorded explicitly in Section 3 and **requires human approval before
D2.1 begins**.

---

## 1. Executive Summary

### 1.1 The question D2 exists to answer

D1 answers *what do the signed contractual leases pay?* D2 must answer *what
happens when those leases expire?*

### 1.2 The finding that drives this document

D0 §8.2 locks a **weighted-assumption synthetic successor** (Option A):
average the renewal-side and new-tenant-side *parameters*, then build one
successor lease from the averages.

**Worked against D0's own review example, that method is materially wrong.**
Renewal probability 65%; renewal = $40/SF, 0 downtime, 0 free rent, $10/SF TI,
2% LC, 60-month term; new tenant = $44/SF, 9 months downtime, 6 months free
rent, $80/SF TI, 6% LC, 120-month term; 10,000 SF suite.

| Month after expiry | True expectation | D0 §8.2 synthetic | Error |
|---|---|---|---|
| 1 | `21,666.67` | `0.00` | **−21,666.67** |
| 2–5 | `21,666.67` | `0.00` | **−21,666.67** each |
| 6 | `21,666.67` | `31,050.00` | +9,383.33 |
| 7–15 | `21,666.67` | `34,500.00` | +12,833.33 each |

The synthetic successor reports **zero rent for the first five months after
expiration**. In reality there is a 65% chance the sitting tenant simply
renewed with no downtime at all and is paying full rent throughout. Those five
months are worth `21,666.67` each in expectation, and the model shows nothing.

Cumulative effects over the same case:

| Quantity | True expectation | D0 §8.2 synthetic | Error |
|---|---|---|---|
| First 24 months of rent | `635,500.00` | `652,050.00` | **+2.6%** |
| Leasing commission | `118,400.00` | `95,013.00` | **−19.8%** |
| Next rollover period | m60 (renewal) / m129 (new) | m84 | a date that occurs in neither scenario |

### 1.3 Why it is wrong, stated once

D0 §8.2 computes **f(E[parameters])**. The expected cash flow is
**E[f(parameters)]**. These coincide only when `f` is linear in every weighted
parameter.

- **Rent per month is linear in rent PSF** — but only if both branches are
  paying in that month. Different downtimes break that, and that is the entire
  first-five-months error above.
- **Leasing commission is a product of two branch-specific quantities**
  (`lc_pct × Σ contractual rent`). `E[XY] ≠ E[X]E[Y]` whenever X and Y are
  correlated, and here they are perfectly correlated by branch. That is the
  −19.8%.
- **Term is not weightable at all.** `0.70 × 60 + 0.30 × 61 = 60.3` months. A
  lease cannot expire 0.3 of a month into a canonical period under D1's
  month-aligned contract. D0's `round_half_up` disposes of the fraction, but
  rounding silently moves the next rollover — and the *unrounded* 81-month term
  in the example is itself a date belonging to neither branch.

The term problem is the one D0 anticipated. The rent-timing and LC problems are
larger and were not anticipated.

### 1.4 Recommendation

**Adopt Option B — weight the outcomes, not the parameters.**

Build the renewal path and the new-tenant path as two complete deterministic
monthly schedules, then form the expected monthly series:

```
E[series_m] = p · renewal_series_m + (1 − p) · new_series_m
```

Exact by linearity of expectation. Handles different terms natively with no
rounding and no forced equality. Reproduces `p = 1` and `p = 0` trivially. Both
branch assumption sets survive intact for audit, because they are what the
engine actually computes rather than inputs it averages away.

Two consequences require human approval (Section 3):

- **HD-D2-1** — this reverses D0 §8.2 and §8.3's explicit rejection of branch
  economics.
- **HD-D2-2** — after a rollover, occupancy becomes a probability-weighted
  *expected* occupancy, not a contractual *physical* one. D0 §8.3 claims the
  synthetic method "avoids fractional physical occupancy." Anchor must instead
  report the two as distinct, clearly labelled series.

### 1.5 Classification

**B — D2.0 COMPLETE, HUMAN FINANCIAL DECISION REQUIRED.** Four decisions
(HD-D2-1 … HD-D2-4). The first two block D2.1.

---

## 2. What D0 Already Locks, Confirmed Unchanged

Re-read against the merged D1 implementation. These stand:

| # | Convention | Status |
|---|---|---|
| 1 | Deterministic underwriting; no Monte Carlo anywhere in the base engine | **Confirmed.** Option B is deterministic expected-value arithmetic, not sampling |
| 2 | `p = 1` reproduces pure renewal; `p = 0` reproduces pure new-tenant | **Confirmed, and strengthened** — under Option B these are exact by construction, not by a limiting argument |
| 3 | Renewal and new-tenant assumptions stay separately auditable | **Confirmed, and strengthened** — they are the computed paths, not discarded inputs |
| 4 | A speculative successor is an expected underwriting assumption, never a known tenant | **Confirmed.** `tenant_name` stays `None`; the `WEIGHTED_ROLLOVER_APPLIED` warning stands |
| 5 | Market rent measured at `analysis_start_date` | **Confirmed** (Section 9) |
| 6 | Market rent grows by annual step on analysis anniversaries | **Confirmed** (Section 9) |
| 7 | Contractual escalation follows lease chronology, distinct from market growth | **Confirmed** (Section 10) |
| 8 | Downtime begins after contractual expiration | **Confirmed** (Section 6) |
| 9 | Fractional downtime formula `c = e + 1 + floor(D)`, boundary factor `1 − frac(D)` | **Confirmed exact** — verified for D ∈ {0, 2.25, 3, 5.5, 6} in Section 6.2 |
| 10 | Fractional downtime is an underwriting assumption; D1 contractual partial-month dates remain ERROR | **Confirmed** (Section 6.4) |
| 11 | Free rent: base rent only, above NOI, after downtime, distinct from downtime, does not itself remove recoveries | **Confirmed** (Section 7) |
| 12 | TI: `$/SF × leased area`, paid at successor rent commencement, below NOI | **Confirmed** (Section 8) |
| 13 | LC: % of total contractual base rent over the successor term, including escalation, gross of free rent, untruncated by the hold | **Confirmed, with the basis tightened** (Section 8.3) |
| 14 | LC architecture leaves room for a future `$/SF` method | **Confirmed** — the method enum lives on `MarketLeasingAssumptions`, never on `Lease` |
| 15 | No general Lease-Level vacancy percentage | **Confirmed** |
| 16 | Exit NOI uses live canonical months `12H+1 … 12H+12`; rollover active there | **Confirmed** (Section 11) |
| 17 | TI/LC do not reduce exit NOI | **Confirmed** |

**No external-product attribution is claimed anywhere in this document.** D0
deliberately removed such claims and this gate does not restore them. Every
convention below is justified on financial and architectural grounds only.

---

## 3. Proposed Changes to D0 — HUMAN APPROVAL REQUIRED

Recorded in the required form. D0 itself is **not edited by this gate**.

### HD-D2-1 — The rollover composition method

**CURRENT D0** (§8.2, §8.3). One synthetic successor built from
probability-weighted *parameters*: `expected_rent_psf`,
`expected_downtime_months`, `expected_free_rent_months`, `expected_ti_psf`,
`expected_lc_pct`, and `expected_term_months = round_half_up(...)`. §8.3
explicitly rejects "two independent probabilistic cash-flow branches recursing
through the hold" as "unauditable" and as making "the rollover log
meaningless."

**PROPOSED D2.0.** Two deterministic branch schedules per rollover, combined at
the **monthly output** level: `E[x_m] = p·x_m^renewal + (1−p)·x_m^new`. No
parameter is averaged. No term is rounded.

**WHY.**

1. **It is the actual expectation.** D0's method computes `f(E[params])`; the
   expected cash flow is `E[f(params)]`. They differ whenever the branches
   differ in *timing* or whenever a quantity is a *product* of two
   branch-specific values.
2. **The error is large and one-sided in the first year.** Five months of zero
   reported rent against a true `21,666.67`/month, in D0's own example.
3. **The LC error is −19.8%** in the same example, because LC is
   `lc_pct × Σrent` and both factors are branch-specific.
4. **Different terms need no convention at all.** `0.70 × 60 + 0.30 × 61` never
   arises: each branch keeps its own integer term and its own expiration.
   D0's `round_half_up` is deleted rather than defended.
5. **The audit story improves.** D0 §8.3 feared an unauditable tree. The
   rollover log under Option B shows *two named, real scenarios and one weight*
   — which is what an analyst can actually check. D0's synthetic successor is
   the harder thing to defend: a lease at $41.40/SF with 3.15 months of
   downtime and an 81-month term, none of which any tenant would sign.

**The one thing D0 was right to fear** is unbounded recursion at the second and
later rollovers. Section 5 bounds it explicitly rather than rejecting the
method.

**HUMAN APPROVAL REQUIRED.** This reverses an explicitly locked D0 convention.

---

### HD-D2-2 — Physical occupancy versus expected occupancy

**CURRENT D0** (§8.3). "Avoids fractional physical occupancy. One suite, one
successor, integral space. Occupancy stays reportable and the area invariant
(18.4) holds." §18.4 asserts
`occupied_area[m] + vacant_area[m] == rentable_area_sf` exactly.

**PROPOSED D2.0.** Anchor reports **two distinct occupancy concepts**, never
one blended number:

| Concept | Meaning | Where it exists |
|---|---|---|
| **Contractual physical occupancy** | Space covered by a *signed* lease. Always integral | D1 today; every month before a suite's first rollover |
| **Expected occupancy** | `p·(renewal path occupied) + (1−p)·(new path occupied)`. May be fractional | Only in months at or after a suite's first rollover |

The area invariant holds in **both** series independently:
`occupied + vacant == rentable_area_sf` remains exact, because the weights sum
to one.

**WHY.** A suite whose lease has expired is not physically occupied by anyone —
it is occupied by an *assumption*. Reporting `0.65 × 10,000 SF` as *expected*
occupancy is honest; reporting it as *physical* occupancy is not, and reporting
an integral figure derived from averaged parameters is not either. D0's own
§8.4 already insists the successor "is never presented as a known tenant"; this
extends the same honesty to the occupancy series.

The frontend must label the two differently, and the month at which a suite
crosses from contractual to expected must be visible.

**HUMAN APPROVAL REQUIRED.** This adds a concept D0 does not have and softens
a stated D0 property.

---

### HD-D2-3 — Second and later rollovers

**CURRENT D0.** §8.1 states a successor "is itself eligible to roll over when
it expires, so a short remaining term in a long hold produces a chain," and
§8.3 rejects recursion as unauditable. D0 does not reconcile the two.

**PROPOSED D2.0.** Recurse with per-rollover independence, **bounded by an
explicit validated cap**: rollover depth ≤ 4 per suite, i.e. at most 16 chains.
Exceeding it is a validation ERROR naming the suite, not a silent truncation
and not a silent approximation. See Section 5.

**WHY.** Independence is the true model. The cap is what makes it auditable and
bounded, and 4 covers every realistic competition case (Section 5.2). An
analyst who trips it has a rent roll with sub-2-year terms across a 10-year
hold and should be told, not quietly given an averaged answer.

**HUMAN APPROVAL REQUIRED** — for the cap value and for the error-rather-than-
approximate behaviour.

---

### HD-D2-4 — Free-rent and downtime boundary interaction

**CURRENT D0.** §9.3 defines the downtime boundary factor; §10.3 says downtime
and free rent are sequential and disjoint. Neither states what happens when a
*fractional* downtime boundary month is also the first free-rent month.

**PROPOSED D2.0.** The two factors are **independent and multiplicative** in
that single month:
`rent(c) = contractual(c) × (1 − frac(D)) × (1 − free_rent_factor(c))`.
Continuous in both D and F, one rule, no special case. Section 7.3.

**WHY.** The alternatives each introduce a discontinuity (free rent "winning"
the month makes `F = 0` pay 75% and `F = 0.01` pay 0%) or a second convention
("free rent starts at the first full month"). Under Option B both D and F are
per-branch analyst assumptions and are normally integers, so this edge is rare
— but it must be defined rather than discovered in code.

**HUMAN APPROVAL REQUIRED** — minor, but it is a financial convention.

---

## 4. Methodology Analysis

### 4.1 Option A — synthetic expected successor lease (D0 §8.2 as locked)

Average the parameters, build one successor.

Field-by-field, is the weighting mathematically defensible?

| Field | Weighting valid? | Why |
|---|---|---|
| `rent_psf` | **Only if both branches pay in the same months** | Monthly rent is linear in rent PSF, so `E[rent]` is exact *given* both branches are in their paying term. Different downtimes break the precondition |
| `downtime_months` | **No** | Downtime selects *which* months pay. `f(E[D])` produces one vacancy block; `E[f(D)]` is a blend of two differently-timed blocks. This is the five-month zero-rent error |
| `free_rent_months` | **No, same reason** | Selects which months are abated |
| `ti_psf` | **Only if both branches commence in the same month** | The dollar amount weights linearly; the *timing* does not. With commencements at m1 and m10 the true expectation is two payments in two months, not one payment in m4 |
| `lc_pct` | **No** | LC is `lc_pct × Σrent`, a product of two branch-correlated quantities. `E[XY] ≠ E[X]E[Y]`. Measured error −19.8% |
| `term_months` | **No — cannot be collapsed at all** | The weighted value is generally fractional (`0.70×60 + 0.30×61 = 60.3`). D1 leases expire on month boundaries. Rounding moves the next rollover; not rounding is unrepresentable |
| `escalation_pct` | **Yes** | `successor_escalation_pct` is a single common assumption, not branch-specific |
| `lease_type` | **Yes** | Inherited from the expiring lease, common to both branches |

**Fields that cannot be safely collapsed without an additional convention:**
`downtime_months`, `free_rent_months`, `term_months`, `lc_pct`, and the
*timing* of `ti_psf`. That is five of the eight — the majority of the
rollover's economics.

**Verdict.** Defensible only in the degenerate case where the branches share
downtime *and* term, and even then LC remains biased. It is a heuristic, not an
expectation.

### 4.2 Option B — probability-weighted branch economics (recommended)

Compute the renewal path and the new-tenant path as complete deterministic
monthly schedules over the canonical timeline, then weight the **outputs**:

```
contractual_base_rent[m] = p · rent_R[m] + (1 − p) · rent_N[m]
occupied_area[m]         = p · occ_R[m]  + (1 − p) · occ_N[m]     (expected)
free_rent[m]             = p · free_R[m] + (1 − p) · free_N[m]
tenant_improvements[m]   = p · ti_R[m]   + (1 − p) · ti_N[m]
leasing_commissions[m]   = p · lc_R[m]   + (1 − p) · lc_N[m]
expense_recoveries[m]    = p · rec_R[m]  + (1 − p) · rec_N[m]      (D3)
```

Every one of these is exact by linearity of expectation, because each branch
series is deterministic and the weights are constants.

| Property | Result |
|---|---|
| Rent | Exact |
| Occupancy | Exact **as an expectation**; fractional after rollover (HD-D2-2) |
| Downtime | Exact — each branch has its own integer or fractional downtime, applied within its own path |
| Free rent | Exact, same reasoning |
| TI | Exact, **including timing** — each branch pays at its own commencement month |
| LC | Exact — computed per branch from that branch's own contractual rent and rate, then weighted |
| Term / expiration | No conflict — each branch keeps its own; nothing is rounded |
| Future rollover | Each branch rolls on its own schedule (Section 5) |
| Recoveries (D3) | Compose cleanly — recoveries are a monthly series like any other |
| Exit NOI | Composes cleanly — the forward window is just months `12H+1…12H+12` of the weighted series |

**The one genuine cost:** fractional expected occupancy after the first
rollover, and branch growth at the second and later rollovers. Both are
addressed — HD-D2-2 and Section 5 respectively.

**On D0 §8.3's objection.** D0 rejected this as producing "an average over a
tree no analyst can enumerate." For the *first* rollover the tree is exactly two
leaves and is trivially enumerable — and it is the deeper tree D0 was really
worried about, which Section 5 bounds. The rollover log under Option B is
strictly more informative than under Option A: it shows two real scenarios and
one weight, rather than one synthetic lease whose parameters describe no
scenario at all.

### 4.3 Option C — require matching successor terms

Keep the synthetic successor but require
`renewal_term_months == new_term_months` in V1.

**This does not work, and the reason is worth stating.** Matching *terms* does
not produce matching *expirations*, because expiration is
`commencement + term − 1` and commencement depends on **downtime**:

```
renewal: downtime 0 -> c = e+1  -> expires e+60
new:     downtime 9 -> c = e+10 -> expires e+69
```

Same 60-month term, expirations nine months apart. To make the synthetic lease
well-defined you must *also* require `renewal_downtime == new_downtime` — which
forces renewal downtime to equal new-tenant downtime, and the entire point of
modelling renewal is that a renewing tenant does **not** vacate.

Call the fully-constrained variant **C′** (matching term *and* downtime). Even
C′ leaves LC biased, because `E[lc_pct × rent] ≠ E[lc_pct] × E[rent]`
(≈2.3% at p = 0.5 on the review example's rates).

| Criterion | Assessment |
|---|---|
| Financial correctness | Fails: forbids the central real-world asymmetry (renewal has no downtime) |
| Simplicity | High, but bought by making the model unable to express the normal case |
| Competition usefulness | Low. Every competition rent roll has renewal downtime ≈ 0 and new-tenant downtime of 6–12 months |
| Real-world limitation | Severe |
| Acceptable V1 guardrail? | **No** |
| Future extensibility | Poor — relaxing the constraint later means switching methodology anyway, so the work is done twice |

**Rejected.** Not because it is easy, but because the constraint it imposes
deletes the phenomenon being modelled.

### 4.4 Option D — alternatives considered

**D-i — Perfectly correlated branch paths.** Run exactly two paths per suite
for the whole projection (always-renew, always-re-let) and weight once. Bounded
at 2 chains forever, and immune to branch explosion.
*Rejected as the default:* it assumes a tenant that renews once renews forever,
which understates turnover risk late in a long hold. Retained as a **documented
fallback** if HD-D2-3's cap proves impractical.

**D-ii — Analyst-selected discrete path per suite.** Force `p ∈ {0, 1}`.
Maximally interpretable and exactly representable, but cannot express "most
tenants renew," which is the assumption competition cases actually make.
*Rejected as the default; it is available for free under Option B by setting an
endpoint.*

**D-iii — Scenario comparison above the engine.** Run the whole model twice
(all-renew, all-vacate) and present both. Genuinely useful, and Option B makes
it nearly free, but it answers a different question than "what is the expected
NOI." *Recommended as a post-D4 UI feature, not as the rollover convention.*

### 4.5 Decision matrix

Scale: ✔ good · ~ acceptable · ✘ poor.

| Criterion | A (D0 §8.2) | **B (recommended)** | C′ (matched) | D-i (correlated) |
|---|---|---|---|---|
| Mathematical correctness | ✘ f(E) ≠ E(f); −19.8% LC | **✔ exact** | ~ LC still biased | ~ exact given its assumption |
| Deterministic | ✔ | **✔** | ✔ | ✔ |
| Auditability | ~ synthetic lease matches no scenario | **✔ two real scenarios + one weight** | ~ | ✔ |
| Monthly implementation complexity | ✔ simplest | ~ two schedules per rollover | ✔ | ✔ |
| Physical-occupancy semantics | ✔ integral, but derived from fiction | ~ needs expected/physical split (HD-D2-2) | ✔ | ~ same split |
| Different renewal/new terms | ✘ requires rounding | **✔ native** | ✘ forbidden | ✔ native |
| Second-rollover support | ~ one synthetic chain | ~ bounded tree (HD-D2-3) | ~ | ✔ 2 chains |
| Exit-NOI correctness | ✘ inherits the rent-timing error | **✔** | ~ | ✔ |
| D3 recovery compatibility | ~ recoveries follow a fictional occupancy | **✔ per-branch, then weighted** | ~ | ✔ |
| Explaining it to an analyst | ~ "your successor pays $41.40 with 3.15 months downtime" | **✔ "65% renew at $40, 35% re-let at $44 after 9 months"** | ~ | ✔ |
| Competition readiness | ~ | **✔** | ✘ | ~ |
| Future extensibility | ~ | **✔** | ✘ | ~ |

**Recommendation: Option B**, with HD-D2-2 (occupancy split) and HD-D2-3
(bounded recursion) as its two required companions, and D-i retained as the
documented fallback.

---

## 5. Second and Later Rollovers

### 5.1 The structure

Under Option B a suite's future is a **tree of lease chains**, each chain
deterministic and carrying a probability. After `r` rollovers inside the
projection window there are `2^r` chains, and the expected series is the
probability-weighted sum over them. Expectation stays exact at every depth;
only the enumeration grows.

Chain probabilities multiply: renew-then-renew is `p²`, renew-then-vacate is
`p(1−p)`, and so on, summing to 1.

### 5.2 How deep does it actually go?

Rollovers inside a `12H + 12` window, by successor term:

| Hold | Window | 10-yr terms | 5-yr terms | 3-yr terms | 1-yr terms |
|---|---|---|---|---|---|
| 5 yr | 72 mo | 1 | 2 | 2 | 6 |
| 10 yr | 132 mo | 2 | 3 | 4 | 11 |

Chains = `2^r`: a 10-year hold with 5-year terms is 8 chains per suite; with
3-year terms, 16. A 20-suite property at depth 4 is 320 chains × 132 months —
entirely tractable. One-year terms (2048 chains) are the pathological case, and
they are also not a realistic commercial rent roll.

### 5.3 Recommendation

**Recurse with per-rollover independence, capped at rollover depth 4 per
suite** (≤ 16 chains). Exceeding the cap is a validation **ERROR** naming the
suite and its term, never a silent truncation and never a silent switch to a
cheaper method.

Rationale: depth 4 covers every case in the table above except 1-year terms;
the failure is loud, explains itself, and has an obvious analyst remedy (state
a longer successor term, or shorten the hold). Silently approximating at depth
5 would reintroduce exactly the class of hidden convention this gate exists to
eliminate.

**Dependency on the primary methodology.** This recommendation exists *because*
Option B was chosen. Under Option A there is one synthetic chain and no tree;
under D-i there are permanently two. If HD-D2-1 is declined, HD-D2-3 is moot.

### 5.4 Truncation at the horizon is unchanged

A chain stops when its successor's commencement exceeds `12H + 12`. Nothing
beyond the window is computed for revenue. D0 §8.6's rule stands, and the LC
basis remains untruncated (Section 8.3).

---

## 6. Downtime — Exact Monthly Semantics

### 6.1 The rule, restated from D0 §9.3

Let `e` be the expiring lease's last paying period and `D ≥ 0` the branch's
downtime in months.

```
c                  = e + 1 + floor(D)          successor rent commencement
fully vacant       = periods e+1 … c−1         exactly floor(D) periods
boundary factor    = 1 − frac(D)               applied in period c only
full periods       = c+1 onward
```

### 6.2 Worked examples — verified exact

Expiration `e`; "forgone" is measured in months of the successor's contractual
rent.

| `D` | `floor(D)` | fully vacant | `c` | factor at `c` | forgone at `c` | **total forgone** |
|---|---|---|---|---|---|---|
| `0` | 0 | *none* | `e+1` | `1.00` | `0.00` | **`0.00`** ✓ |
| `2.25` | 2 | `e+1, e+2` | `e+3` | `0.75` | `0.25` | **`2.25`** ✓ |
| `3` | 3 | `e+1 … e+3` | `e+4` | `1.00` | `0.00` | **`3.00`** ✓ |
| `5.5` | 5 | `e+1 … e+5` | `e+6` | `0.50` | `0.50` | **`5.50`** ✓ |
| `6` | 6 | `e+1 … e+6` | `e+7` | `1.00` | `0.00` | **`6.00`** ✓ |

The identity **forgone rent months = D** holds exactly for every real `D ≥ 0`,
subject only to normal floating-point representation. When `D` is a whole
number the factor is `1.00` and period `c` is an ordinary full month — the rule
degenerates with no special case.

### 6.3 Under Option B

Each branch applies this rule with **its own** `D`. Renewal downtime is
typically `0` (a renewing tenant does not vacate); new-tenant downtime is
typically 6–12 months. Nothing is averaged, so no weighted fractional downtime
arises from the methodology. Fractional `D` remains permitted purely because an
analyst may legitimately state `4.5`.

### 6.4 D1 is untouched

Fractional downtime is an **underwriting assumption about a speculative
future**, expressed as a duration. D1's contractual dates remain month-aligned
and a non-aligned contractual date remains a validation **ERROR**. These are
different things and D2 does not blur them.

---

## 7. Free Rent — Exact Semantics

### 7.1 Fractional free rent: permitted, symmetric with downtime

With `F ≥ 0` free months from the successor's commencement period `c`:

```
fully abated   = periods c … c + floor(F) − 1        exactly floor(F) periods
partial period = c + floor(F), abated by frac(F)
no abatement   = thereafter
```

Total abated = exactly `F` months of contractual rent.

| `F` | fully abated | partial | total abated |
|---|---|---|---|
| `0` | *none* | *none* | `0` |
| `2` | `c, c+1` | *none* | `2` |
| `2.5` | `c, c+1` | `c+2` at `0.5` | `2.5` |
| `6` | `c … c+5` | *none* | `6` |

**Permitted rather than required.** Under Option B each branch carries its own
free-rent assumption, normally a whole number ("six months free"). Fractional
`F` exists only because an analyst may state it.

### 7.2 What free rent does and does not do

| | |
|---|---|
| Abates | Contractual **base rent** only |
| Above or below NOI | **Above** — it is a revenue abatement, reported on its own line, never netted into `contractual_base_rent`, never reclassified as a capital cost |
| Occupancy | **No effect.** The tenant is in possession and the suite is occupied |
| Recoveries (D3) | **No automatic effect.** Whether a tenant reimburses during an abatement is a function of the lease's recovery structure, not of the free-rent input |
| LC basis | **No effect** — the basis is gross of free rent (Section 8.3) |

### 7.3 The boundary-month interaction — HD-D2-4

When period `c` is both the fractional downtime boundary *and* a free-rent
period, the two factors are **independent and multiplicative**:

```
rent(c) = contractual(c) × (1 − frac(D)) × (1 − free_rent_factor(c))
```

Worked: `D = 2.25`, `F = 1`, contractual `10,000`/month →
`10,000 × 0.75 × 0 = 0`. With `F = 0.5` → `10,000 × 0.75 × 0.5 = 3,750`.

Continuous in both `D` and `F`, one rule, no special case. The alternatives
were rejected: "free rent wins the month" is discontinuous at `F = 0⁺`, and
"free rent starts at the first full month" needs a second convention and makes
a tenant with six months free still pay a stub month.

**Consequence, stated:** free-rent consumption is measured in **contract months
from `c`**, so when a boundary month exists the *dollars* abated are slightly
less than `F` full months. That is correct — the lease grants `F` months of
contract time, and the tenant only occupied part of the first one.

### 7.4 Downtime versus free rent — locked

| | **Downtime** | **Free rent** |
|---|---|---|
| Physical state | Space is **vacant**; no successor in possession | Successor **is in possession** |
| Occupancy | Suite counts as vacant | Suite counts as occupied |
| Base rent | Zero (no tenant) | Zero (abated concession) |
| Recoveries (D3) | **Stop** — no tenant to reimburse | **Unaffected by free rent itself** |
| TI timing | TI is *not* paid during downtime | TI already paid at `c` |
| Sequence | Ends at `c` | Begins at `c` |
| Cause | Time to re-let | Concession to win the lease |

They never overlap: downtime ends at `c`, free rent begins at `c`. The single
period `c` may carry a downtime *factor* and a free-rent *factor*
simultaneously (7.3), but it is unambiguously an **occupied** period.

This distinction is load-bearing for D3 recoveries, for the occupancy series,
and for TI timing, which is why it is locked here rather than in D2.3.

---

## 8. TI and LC

### 8.1 TI timing — confirmed

TI is `ti_psf × leased_area_sf`, recorded **in full, in the single period `c`**,
below NOI. It is **not** prorated by the downtime boundary factor and **not**
spread across a draw schedule in D2.

Worked, exactly as the review asked: lease expires **June 30**, downtime
**2.25** months.

```
July      vacant
August    vacant
September = c, rent factor 0.75  ->  FULL TI recorded here
```

**Confirmed: September.** The tenant's improvement allowance is a lump
obligation triggered by commencement; the fact that Anchor's monthly grid
recognises only 75% of September's *rent* does not divide the *allowance*. No
daily proration anywhere.

Under Option B each branch records its own TI in its own commencement period,
and the expected series is the weighted sum — so the review example's
`p = 0.65` case correctly shows `0.65 × 10 × area` in the renewal branch's
month and `0.35 × 80 × area` in the new branch's month, rather than one blended
payment in a month belonging to neither.

**TI is never charged on an in-place D1 lease** — that improvement was funded by
the seller before acquisition.

### 8.2 LC method for D2 V1

```
LC = lc_pct × Σ ContractualBaseRent(successor, m)  for m over the FULL contract term
```

recorded **in full, in period `c`**, below NOI.

The method lives on `MarketLeasingAssumptions` as a
`LeasingCommissionMethod` enum with exactly one member in D2
(`PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT`). It is **never** a `Lease` field, so
adding `PER_SF` later means one enum member plus its rate fields — no lease
contract change, no schedule change, no data migration.

### 8.3 The LC basis, tightened — contractual face rent

The basis is the successor's **contractual face rent**, not the cash Anchor
happens to recognise:

| Question | Answer |
|---|---|
| Escalations included? | **Yes** — the commission is on the whole contractual stream |
| Gross of free rent? | **Yes** — the broker earns on the lease signed, not on the landlord's concession |
| Truncated at the hold horizon? | **No** — the obligation is incurred in full at signing |
| **Reduced by a fractional first month from downtime?** | **No** |

That last row is the tightening this gate adds. If downtime is `2.25` months,
Anchor recognises `0.75` of a month's *cash* in period `c` — but the lease
still says "60 months at $40/SF escalating 3%". The commission is computed on
those 60 full contractual months.

**Rule: the LC denominator is `term_months` full contractual months beginning
at `c`. The downtime boundary factor is a cash-recognition artifact of the
monthly grid and never enters the LC basis.** This is the one place the engine
evaluates contractual rent beyond the projection window; those periods enter no
revenue, EGI or NOI series.

### 8.4 LC under Option B

Computed **per branch** from that branch's own `lc_pct`, own rent and own term,
then weighted:

```
LC_expected = p · lc_pct_R · Σ rent_R  +  (1 − p) · lc_pct_N · Σ rent_N
```

Exact. Contrast with D0 §8.2's
`(p·lc_R + (1−p)·lc_N) × Σ(weighted rent over a rounded term)`, which measured
**−19.8%** low on the review example because it multiplies two averages instead
of averaging two products.

**TI and LC are never charged on an in-place D1 lease, and neither reduces NOI
or exit NOI** — both remain strictly below NOI, per D0 §17.4 and §18.3.

---

## 9. Market Rent

### 9.1 The lookup rule — confirmed exactly as D0 §7.2

```
MarketRentPSF(m) = market_rent_psf × (1 + market_rent_growth) ^ floor((m − 1) / 12)
```

Measured **as of `analysis_start_date`**; annual **step** growth on
`analysis_start_date` anniversaries; held flat within each 12-period band.

Worked, `analysis_start = 2027-07-01`, `$40.00`, `3%`:

| Periods | Calendar | `MarketRentPSF` |
|---|---|---|
| 1–12 | Jul-2027 – Jun-2028 | `40.000000` |
| 13–24 | Jul-2028 – Jun-2029 | `41.200000` |
| 25–36 | Jul-2029 – Jun-2030 | `42.436000` |
| 37–48 | Jul-2030 – Jun-2031 | `43.709080` |

Explicitly **not** monthly-compounded, and explicitly **not** reset on a lease
anniversary. Market rent is a market fact anchored to the analysis date; a
lease's anniversary is a contract fact. Confusing them is failure mode
**FM-D2-12/13**.

### 9.2 The rate at a fractional-downtime boundary month

**Rule: use the canonical calendar period `c`, exactly as for any other
period.** `MarketRentPSF(c) = market_rent_psf × (1 + g) ^ floor((c − 1) / 12)`.

The downtime boundary factor scales the *rent recognised* in period `c`; it
does **not** shift which 12-period growth band `c` falls in, and it introduces
no day-count. A successor commencing in period `c` with a `0.75` factor takes
the market rent of period `c` and pays 75% of one month of it.

Worked: `analysis_start = 2027-07-01`, `$40`, `3%`, expiry at period 11
(May-2028), downtime `2.25` → `c = 11 + 1 + 2 = 14` (Aug-2028), which is in the
second band → `MarketRentPSF(14) = 41.20`. The successor's contractual rent is
`$41.20/SF` and period 14 recognises `0.75` of one month of it.

### 9.3 Which value wins — override hierarchy, confirmed from D0 §24

```
Suite.market_leasing_override.market_rent_psf     (if the override is not None)
  > Suite.market_rent_psf                          (if not None)
  > MarketLeasingAssumptions.market_rent_psf       (property default, always present)
```

For **every other** market leasing assumption — growth, renewal probability,
terms, downtimes, free rent, TI, LC rates, successor escalation:

```
Suite.market_leasing_override.<field>   (if the override is not None)
  > MarketLeasingAssumptions.<field>    (property default)
```

`market_leasing_override` is **all-or-nothing**: when a suite supplies one, that
record is used in full and no field falls through. `Suite.market_rent_psf` is
the single deliberate exception, because overriding only the rent level is the
overwhelmingly common case.

The resolver runs **once per suite** and the resolved record plus its source
(`"property_default"` / `"suite_override"`) is recorded on every `RolloverEvent`
it drives, so "which assumption applied here, and where did it come from" is
answerable from the output alone.

---

## 10. Successor Contractual Escalation vs Market Growth — locked

Two different clocks, and the distinction is load-bearing.

| | **Market rent growth** | **Successor contractual escalation** |
|---|---|---|
| What it is | A market assumption | A term of the signed successor lease |
| Anchored to | `analysis_start_date` anniversaries | The successor's own commencement `c` |
| Field | `market_rent_growth` | `successor_escalation_pct` |
| What it determines | The **starting** rent available at `c` | How that rent **steps thereafter** |
| Stops mattering | The moment the successor commences | At the successor's expiration |

**Rule.** Market growth is used **once per successor**, to price its starting
rent at `c`. From `c` onward the successor is an ordinary contractual lease and
escalates on **its own anniversaries** (`c`, `c+12`, `c+24`, …) at
`successor_escalation_pct`, through exactly the D1 rent formula and
`EscalationBasis.LEASE_ANNIVERSARY`. Market rent continues growing in the
background for the *next* rollover, and has no further effect on this lease.

Worked, `analysis_start = 2027-01-01`, market `$40` growing `5%`, successor
commencing `c = 25` (Jan-2029) with `successor_escalation_pct = 3%`:

```
MarketRentPSF(25) = 40 × 1.05^2 = 44.100000     <- starting rent, from MARKET growth
periods 25–36     = 44.100000                    <- successor year 1
periods 37–48     = 44.100000 × 1.03 = 45.423    <- successor's OWN escalation
periods 49–60     = 44.100000 × 1.03^2 = 46.78569
```

Note periods 37–48 are `45.423`, **not** `40 × 1.05^3 = 46.305`. Continuing
market growth as though it were the contractual escalation is failure mode
**FM-D2-14**.

Setting `successor_escalation_pct == market_rent_growth` makes the two numerically
equal; that is a coincidence of inputs, never an identity of concepts.

---

## 11. Forward Exit Window — confirmed

Rollover remains **fully live** in periods `12H+1 … 12H+12`. A lease expiring
in period `12H+3` rolls, its branches take their downtime, and the weighted
result flows into those months. Nothing is smoothed to stabilise terminal
value.

Under Option B the forward window is simply the tail of the same weighted
monthly series — there is no second projection and no separate exit
calculation. D0 §17.4's `exit_window_leasing_costs` disclosure (TI + LC falling
in the forward window, reported but never deducted) composes unchanged: it is
the weighted sum of the branches' forward-window leasing costs.

`ROLLOVER_IN_EXIT_WINDOW` remains a WARNING, and under Option B it should fire
when **any branch** commences in the window.

---

## 12. Assumption Inventory

Extracted from D0 §4.5. No assumption is invented here. Weighting validity is
assessed for Option A (D0 §8.2) to show why Option B avoids the question — under
Option B **nothing is weighted at the parameter level**, so the column reads
"n/a: used per branch."

| Field | Unit | Temporal anchor | Domain | Branch | Weighting valid under A? | Affects cash flow | Affects occupancy | Affects successor expiration | Gate |
|---|---|---|---|---|---|---|---|---|---|
| `market_rent_psf` | $/SF/yr | `analysis_start_date` | `≥ 0` | common | ✔ linear | at `c` | no | no | D2.1 |
| `market_rent_growth` | decimal | analysis anniversaries | `> −1` | common | ✔ | at `c` | no | no | D2.1 |
| `renewal_probability` | decimal | n/a | `0 ≤ p ≤ 1` | common | n/a — it *is* the weight | all | **yes (expected)** | no | D2.5 |
| `renewal_rent_psf` | $/SF/yr | `analysis_start_date` | `≥ 0`, nullable | renewal | ~ only if timing matches | from `c_R` | no | no | D2.2 |
| `renewal_rent_spread` | decimal | n/a | `> −1` | renewal | ~ | from `c_R` | no | no | D2.2 |
| `renewal_term_months` | months | from `c_R` | `≥ 1` | renewal | **✘ fractional** | term length | no | **yes** | D2.2 |
| `renewal_downtime_months` | months | from expiry | `≥ 0` | renewal | **✘ timing** | vacancy block | **yes** | **yes** (shifts `c`) | D2.2 |
| `renewal_free_rent_months` | months | from `c_R` | `≥ 0` | renewal | **✘ timing** | abatement | no | no | D2.2 |
| `renewal_ti_psf` | $/SF | paid at `c_R` | `≥ 0` | renewal | ~ amount yes, timing no | at `c_R`, below NOI | no | no | D2.4 |
| `renewal_lc_pct` | decimal | paid at `c_R` | `0 ≤ x ≤ 1` | renewal | **✘ product** | at `c_R`, below NOI | no | no | D2.4 |
| `new_term_months` | months | from `c_N` | `≥ 1` | new | **✘ fractional** | term length | no | **yes** | D2.3 |
| `new_downtime_months` | months | from expiry | `≥ 0` | new | **✘ timing** | vacancy block | **yes** | **yes** | D2.3 |
| `new_free_rent_months` | months | from `c_N` | `≥ 0` | new | **✘ timing** | abatement | no | no | D2.3 |
| `new_ti_psf` | $/SF | paid at `c_N` | `≥ 0` | new | ~ | at `c_N`, below NOI | no | no | D2.4 |
| `new_lc_pct` | decimal | paid at `c_N` | `0 ≤ x ≤ 1` | new | **✘ product** | at `c_N`, below NOI | no | no | D2.4 |
| `leasing_commission_method` | enum | n/a | one member in D2 | common | n/a | LC basis | no | no | D2.4 |
| `successor_escalation_pct` | decimal | successor anniversaries | `> −1` | common | ✔ | from `c+12` | no | no | D2.2 |
| *(new-tenant rent)* | — | — | — | new | — | — | — | — | — |

**One gap found in D0, and it is deliberate rather than missing.** There is no
`new_rent_psf` field: the new-tenant branch prices at `MarketRentPSF(c_N)` by
definition, while the renewal branch has both an explicit
`renewal_rent_psf` and a `renewal_rent_spread` (D0 §24.3 precedence: explicit
level, grown from `analysis_start_date` to `c`, wins; otherwise
`MarketRentPSF(c) × (1 + renewal_rent_spread)`). This asymmetry is correct — a
renewal is negotiated relative to market, a new letting *is* market — and needs
no new field.

**No other concept required by Option B is missing from D0.** Option B needs
strictly fewer conventions than Option A: it deletes `round_half_up`, the
weighted-parameter definitions, and the fractional-downtime-from-weighting
requirement.

---

## 13. Carried-Forward Items

### 13.1 The rent anchor — recommendation on timing

D1's accepted limitation: `Lease.base_rent_psf` is anchored to
`rent_commencement_date`, while real rent rolls often state *current*
contractual rent or explicit dated rent steps. D0 §6.6 schedules the fix as a
`RentStep` child contract, "D2+", and calls it "the most likely first
extension."

**Recommendation: not in D2.** Reasons:

1. D2 is already the most financially complex gate in Sprint D. Adding a second
   rent *representation* while changing the rollover *methodology* risks both,
   and makes any golden-case failure ambiguous between the two.
2. The problem is an **input-representation** problem, not a rollover problem.
   It is best solved where a rent roll's stated basis is actually known — at
   the D5 ingestion/approval boundary.
3. It is cheap whenever it is done, and D1.4 verified the isolation that keeps
   it cheap: `aggregation.py` is guardrail-forbidden from naming a rent
   assumption, so `rent_anchor_date` or `RentStep` is a change to `rent.py`
   plus one nullable `Lease` field and nothing else.
4. It does not block D2. Every D2 golden case in Section 15 is expressible under
   the current contract.

**Recommended placement: D5 (ingestion and analyst approval)**, with a
standalone gate earlier only if a specific competition rent roll forces it. This
is a scheduling recommendation, not a financial convention, and it does not
require a human decision to proceed with D2.

### 13.2 Floating-point reconciliation — carried forward unchanged

D1 closeout characterised a **1-ULP** difference (`7.45e-09` absolute,
`1.86e-16` relative) at a ~$40M total between `sum(annual) + forward` and
`sum(monthly)`. Correct IEEE-754 behaviour from two summation groupings, not a
defect.

**No floating-point policy changes in D2.** D2 monthly formulas continue
Anchor's normal convention: full double precision, no rounding, no `Decimal`,
`ensure_finite` on every result, division by 12 once and last.

**Carried forward as a D4 requirement, restated so it is not lost:** when
reconciling NOI and property cash flows at larger magnitudes, guardrail G-M4
must use an explicitly approved **magnitude-aware** comparison (relative
tolerance, or an explicit ULP bound) rather than assuming `abs=1e-9` is
universally appropriate. `abs=1e-9` is only meaningful below roughly $4.5M,
where it still exceeds one ULP.

One D2-specific note: under Option B the weighted series is
`p·x + (1−p)·y`, which introduces one extra rounding per month per rollover
relative to a single-path model. The magnitudes are unchanged, so the existing
convention remains appropriate for D2's own golden cases; it is D4's
aggregate-magnitude reconciliation that needs the new rule.

---

## 14. Proposed D2 Gate Sequence

Reordered from the prompt's candidate sequence for one reason: **under Option B
the pure paths are the engine, and the probability weight is a thin final
layer.** Building the branches first means every branch is proven in isolation
before any weighting exists, and `p = 1` / `p = 0` are then regression tests of
already-verified code rather than new claims.

| Gate | Objective | Proves | Touches |
|---|---|---|---|
| **D2.0** | *This document* | Conventions locked, D0 changes flagged | `docs/` only |
| **D2.1** | Market rent timeline | Annual step growth on analysis anniversaries; suite override precedence; no monthly compounding; no lease-anniversary reset | new `market.py` |
| **D2.2** | Pure renewal path (`p = 1`) | One expiring lease produces one renewal successor: rent from spread or explicit level, own term, own escalation from `c`, second rollover if it expires in-window | new `rollover.py` |
| **D2.3** | Pure new-tenant path (`p = 0`) + downtime + free rent | Market-priced successor after downtime; the exact `D` and `F` boundary rules of Sections 6–7; downtime/free-rent distinction visible in the occupancy series | `rollover.py` |
| **D2.4** | TI + LC | Both below NOI, both at `c`, LC on contractual face rent untruncated and gross of free rent; **G-3 perturbation** (doubling TI/LC leaves NOI bit-identical) | new `leasing_costs.py` |
| **D2.5** | Expected rollover composition | The weighting `E[x] = p·x_R + (1−p)·x_N`; `p=1`/`p=0` reproduce D2.2/D2.3 **bit-identically**; expected vs physical occupancy split (HD-D2-2) | `rollover.py` |
| **D2.6** | Recursive rollover + closeout | Bounded tree (HD-D2-3), depth cap and its ERROR, forward-window rollover, full D2 golden suite, guardrails | `rollover.py`, tests |

**The D2.5 bit-identity requirement is the key safety property**: `p = 1` must
reproduce D2.2's output bit-for-bit and `p = 0` must reproduce D2.3's, because
under Option B the weighting is literally `1.0 × x + 0.0 × y`. If it does not,
the composition layer has a bug, and the test finds it before any blended case
is trusted.

Each gate is small enough for human financial review, and each ends at a point
where the economics are complete and checkable.

**Nothing in D2 integrates acquisition, debt or returns.** `anchor.leasing`
remains dark to the rest of Anchor through D2; D4 owns integration.

---

## 15. D2 Golden Case Plan

Every case states the exact financial question it settles. Shared frame:
`analysis_start = 2027-01-01`, 10,000 SF single suite unless stated, expiry at a
stated period `e`.

| # | Case | Setup | Proves |
|---|---|---|---|
| **1** | `p = 1` pure renewal | renewal $40, `D=0`, `F=0`, term 60 | Renewal successor commences at `e+1`, prices from the renewal rule, escalates on its own anniversary. **No new-tenant assumption influences any number** |
| **2** | `p = 0` pure new tenant | new = market, `D=6`, `F=0`, term 60 | Successor prices at `MarketRentPSF(c)`, not at `MarketRentPSF(e)`. **No renewal assumption influences any number** |
| **3** | `0 < p < 1` | the §1.2 review example | The weighted monthly series equals `p·case1 + (1−p)·case2` month by month; **months 1–5 after expiry are non-zero**, which is the defect that motivated Option B |
| **4** | Zero downtime | `D = 0` | `c = e+1`, boundary factor `1.00`, no vacant period |
| **5** | Integer downtime | `D = 3` | Exactly 3 fully vacant periods, `c = e+4`, factor `1.00` |
| **6** | Fractional downtime | `D = 2.25` and `D = 5.5` | Section 6.2's table exactly; **total forgone = D** to `abs=1e-9` |
| **7** | Zero free rent | `F = 0` | Successor pays full contractual rent from `c` |
| **8** | Integer free rent | `F = 6` | Six abated periods from `c`; `contractual_base_rent` stays **gross**; abatement on its own line |
| **9** | Fractional free rent + boundary | `D = 2.25`, `F = 2.5` | The multiplicative rule of 7.3: period `c` pays `contractual × 0.75 × 0.5` |
| **10** | TI | `ti_psf = 10`, `D = 2.25`, expiry June | Full TI in **September** (period `c`), never prorated, never in a downtime period, **NOI bit-identical** when TI doubles |
| **11** | LC | term 60, `D = 2.25`, `F = 6`, escalating | LC on **60 full contractual months**, gross of free rent, untruncated by the horizon, unaffected by the `0.75` boundary factor; recorded at `c`; **NOI bit-identical** when LC doubles |
| **12** | Market step before rollover | expiry period 11, `D = 0` → `c = 12`; expiry period 12, `D = 0` → `c = 13` | The successor commencing in period 13 prices one growth band higher. Market rent steps on the **analysis** anniversary |
| **13** | Market step during downtime | expiry period 10, `D = 4` → `c = 15` | Successor prices at `MarketRentPSF(15)`, the band containing `c` — **not** the band at expiry, and **not** day-count interpolated |
| **14** | Successor escalation after commencement | `c = 25`, market growth 5%, `successor_escalation_pct` 3% | Periods 37–48 are `44.100 × 1.03`, **not** `40 × 1.05³`. Market growth prices the start; the lease escalates thereafter |
| **15** | Expiry just before the forward window | expiry period `12H`, `D = 0` | Successor commences at `12H+1`, the first forward period; the hold-year annual series excludes it while the forward scalar includes it |
| **16** | Rollover inside the forward window | expiry period `12H+3`, `D = 6` | Rollover is live in the window; downtime depresses the forward-window rent; `ROLLOVER_IN_EXIT_WINDOW` warns; TI/LC land in the window and are **disclosed, not deducted** |
| **17** | Successor expires inside the projection | term 24, hold 5 | A second rollover occurs; chain probabilities multiply; both branches' second rollovers appear in the log |
| **18** | **Different renewal/new terms — the design stress test** | `p = 0.65`, renewal 60 mo / `D=0` / $40, new 120 mo / `D=9` / $44 | **Mandatory.** The exact case D0 §8.2 cannot represent. Proves: no term is rounded; the renewal branch expires at `e+60` and the new branch at `e+129`; both dates appear in the rollover log; the weighted rent in periods `e+1…e+5` is `p × renewal rent` and **not zero**; LC is `p·lc_R·Σrent_R + (1−p)·lc_N·Σrent_N`; TI appears in **two** periods, not one |

Case 18 additionally records, as a regression against the rejected method, the
numbers from §1.2: first-24-month rent `635,500.00` (not `652,050.00`) and LC
`118,400.00` (not `95,013.00`) for a 10,000 SF suite.

Cases 1–2 and 18 together are the acceptance set for HD-D2-1.

---

## 16. D2 Failure-Mode Register

Extends D0 §26 (FM-1 … FM-29). Each entry names its detection mechanism.

| ID | Failure | Detection |
|---|---|---|
| **FM-D2-1** | `renewal_probability` outside `[0, 1]` | Validation ERROR `RENEWAL_PROBABILITY_OUT_OF_DOMAIN` (D0 §19.2) |
| **FM-D2-2** | Weighting does not reproduce the endpoints — `p=1` differs from the pure renewal path | D2.5 bit-identity test against D2.2 and D2.3 |
| **FM-D2-3** | Hidden rounding of a successor term | Option B rounds nothing; a guardrail asserts no `round`/`round_half_up` appears in `rollover.py` |
| **FM-D2-4** | Different branch terms mishandled — collapsed, rounded, or one branch's term silently used for both | **Golden 18**; the rollover log must show two distinct expirations |
| **FM-D2-5** | Downtime off-by-one — `c` computed as `e + floor(D)` or `e + 1 + ceil(D)` | Golden 4/5/6; the `total forgone = D` identity |
| **FM-D2-6** | Fractional downtime over- or under-recognised | Golden 6, asserted at `abs=1e-9` |
| **FM-D2-7** | Free rent confused with downtime | Golden 9; the occupancy series differs between them (Section 7.4) |
| **FM-D2-8** | Free rent reducing occupancy | Golden 8: occupancy is `1.0` throughout an abated period |
| **FM-D2-9** | TI paid in the wrong month — at expiry, during downtime, or prorated by the boundary factor | Golden 10 |
| **FM-D2-10** | LC computed on cash net of free rent instead of contractual face rent | Golden 11: LC is bit-identical with and without free rent |
| **FM-D2-11** | LC truncated at the hold horizon | Golden 11: the basis uses all `term_months`, some beyond the window |
| **FM-D2-11b** | LC basis reduced by the fractional first month | Golden 11 (Section 8.3) |
| **FM-D2-12** | Market rent compounded monthly instead of annual-stepped | Golden 12: constant within each 12-period band |
| **FM-D2-13** | Market rent reset on a lease anniversary | Golden 12/13: a mid-year lease does not move the market clock |
| **FM-D2-14** | Successor contractual escalation confused with market growth | **Golden 14** |
| **FM-D2-15** | Rollover ignored inside the forward exit window | Golden 16 |
| **FM-D2-16** | TI/LC reducing exit NOI | **G-3 perturbation**: doubling TI/LC leaves every NOI figure and `exit_noi` bit-identical |
| **FM-D2-17** | Recursive branch explosion | Depth cap (Section 5.3) with an ERROR, plus a scale test at depth 4 |
| **FM-D2-18** | A successor presented as a known tenant | `tenant_name is None`; `WEIGHTED_ROLLOVER_APPLIED` warning when `0 < p < 1` |
| **FM-D2-19** | Physical occupancy silently made fractional without the expected/physical distinction | HD-D2-2: two named series; a guardrail asserts the contractual series stays integral in every pre-rollover period |
| **FM-D2-20** | The current-rent anchor inadvertently changed | A guardrail asserts `Lease.base_rent_psf`'s meaning and `rent.py`'s formula are untouched by D2 |
| **FM-D2-21** | Expected occupancy and expected rent inconsistent — a period showing rent but zero expected occupancy, or the reverse | Invariant test: for every period, expected occupancy `> 0` whenever expected rent `> 0` (a zero-rent branch lease is the one legitimate exception and is asserted explicitly) |
| **FM-D2-22** | Branch probabilities failing to sum to 1 at depth | Invariant test over the chain tree at every rollover depth |

---

## 17. Human Decisions Required Before D2.1

| ID | Decision | Recommendation | Blocks |
|---|---|---|---|
| **HD-D2-1** | Rollover composition: D0 §8.2 weighted parameters, or Option B weighted outcomes? | **Option B.** D0's method reports zero rent for five months where the expectation is `21,666.67`/month, and misstates LC by −19.8% | **D2.1** |
| **HD-D2-2** | Does Anchor report a fractional *expected* occupancy after rollover, distinct from contractual *physical* occupancy? | **Yes — two named series.** Required by Option B and more honest than either alternative | **D2.1** |
| **HD-D2-3** | Second and later rollovers: recursion depth cap of 4, with an ERROR beyond it? | **Yes.** Covers every realistic case; fails loudly rather than approximating. Moot if HD-D2-1 is declined | D2.6 |
| **HD-D2-4** | Downtime and free-rent factors multiplicative in a shared boundary month? | **Yes.** The only continuous single-rule option | D2.3 |

**If HD-D2-1 is declined** and D0 §8.2 stands, this document's Sections 6–13
remain valid as written — they are methodology-independent. Only Sections 4, 5,
14 and the Option-B-specific golden cases (3, 17, 18) would need revision, and
the accepted consequence would be the quantified errors in §1.2.

---

## 18. Scope Statement

This gate changed `docs/` only. No file under `src/`, `tests/`, `web/`, no
migration, no dependency, no configuration. D1 economics are untouched and
`anchor.leasing` is unmodified.

No D2 production code exists. D2.1 begins only after HD-D2-1 and HD-D2-2 are
answered.
