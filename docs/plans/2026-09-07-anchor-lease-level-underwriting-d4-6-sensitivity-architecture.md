# Anchor — Lease-Level Sensitivity Architecture (D4.6)

**Gate:** D4.6A — architecture and documentation only.
**Date:** 2026-09-07
**Branch:** `feature/lease-underwriting-d4-property-integration`
**Baseline HEAD:** `84fbbfd` (D4.5B closed; 4401 backend tests passing)
**Status:** **ACCEPTED.** Human financial review completed 2026-09-07; all
six decisions are decided and **no decision blocks D4.6B**. The final rulings,
and the shadow-detection rule measured from shipped code, are in **§38**. Part I
and Part II record the analysis as proposed; where §38 differs, **§38 governs**.
No production code changes.

Governed by, and subordinate to:

- `docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md`
  (the D4 integration architecture, including its §38 D4.5B closeout amendment)
- `docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md`

Where this document and either of those appear to conflict, **they govern** and
this document is wrong.

---

## 0. Summary of what is being proposed

**One sentence.** Add a third pair of sensitivity functions — a Lease-Level
counterpart to the Quick and Detailed pairs that already exist — in a new
module, reusing the existing result contracts unchanged, calling
`analyze_lease_level_acquisition_with_projection` once per scenario.

**The central rule, restated.** Sensitivity perturbs authoritative *inputs* and
re-runs the authoritative analysis. It never touches an output. There is no
`lease_level_sensitivity_noi_formula`, no shortcut terminal value, and no
approximation from baseline cash flows. Every cell is a genuine re-underwrite.

**Recommended answer to the primary architecture question: option C** — a
narrow Lease-Level sensitivity orchestrator that reuses the current
scenario/result contracts. Not a framework refactor, not a generic adapter.
Rationale in §12.

**Six human decisions were required, and all six are now decided** (§35,
finalised in §38). Four approved, two deferred, **none blocking**. The two that
were blocking — market-leasing/suite-override semantics (HD-D4.6-2) and
Lease-Level break-even inclusion (HD-D4.6-5) — were decided as recommended,
because the evidence below showed that guessing either one wrong produces
silently wrong output rather than an error.

**Everything in this document that could be measured, was measured.** The
runtime numbers, the memory numbers, the override-shadowing failure, the
non-monotonicity findings and the undefined-IRR finding are all observed from
the shipped code at `84fbbfd`, not predicted. The scripts are described in
§21–§23 so any of it can be reproduced.

---

# PART I — MAPPING THE EXISTING FRAMEWORK

Nothing about Lease-Level is proposed in Part I. This is what the repository
does today, established by inspection.

## 1. Current sensitivity contracts

All four live in `src/anchor/analysis/contracts.py` and perform no
calculation.

| Contract | Shape |
|---|---|
| `OneWaySensitivityResult` | `assumption`, `metric`, `baseline_assumption_value`, `baseline_metric_value`, `assumption_values: tuple[float, ...]`, `metric_values: tuple[float \| None, ...]` |
| `TwoWaySensitivityResult` | `row_assumption`, `column_assumption`, `metric`, `baseline_row_value`, `baseline_column_value`, `baseline_metric_value`, `row_values`, `column_values`, `matrix: tuple[tuple[float \| None, ...], ...]` |
| `StandardSensitivityPresets` | the three Quick preset matrices plus the DSCR variant |
| `StandardDetailedSensitivityPresets` | the Detailed subset — **no `exit_cap_noi_growth` member**, because `noi_growth` has no `AcquisitionTerms` counterpart |

Three properties of these contracts matter for everything downstream:

1. **They are float-only.** `assumption_values` is `tuple[float, ...]`;
   `matrix` is `tuple[tuple[float | None, ...], ...]`. An enum or a date
   cannot enter them without a contract change.
2. **The assumption is a plain `str`.** There is no structured target — no
   suite id, no contract selector, no path.
3. **There is exactly one `None` channel**, on the metric, and it means *the
   metric is undefined for this scenario* (for example an IRR that does not
   exist). It does **not** mean "this scenario was invalid".

## 2. Current entry points

`src/anchor/analysis/sensitivity.py` (605 lines):

| Function | Mode | Varies |
|---|---|---|
| `run_one_way_sensitivity(inputs, *, assumption, values, metric)` | Quick | `AcquisitionInputs` |
| `run_two_way_sensitivity(inputs, *, row_assumption, row_values, column_assumption, column_values, metric)` | Quick | `AcquisitionInputs` |
| `run_detailed_one_way_sensitivity(terms, detailed_operating_inputs, *, ...)` | Detailed | `AcquisitionTerms` only |
| `run_detailed_two_way_sensitivity(terms, detailed_operating_inputs, *, ...)` | Detailed | `AcquisitionTerms` only |
| `build_*_preset` / `build_standard_presets` / `build_standard_detailed_presets` | both | compose the above |

All are exported from `anchor.analysis`. `api.py` chooses which to call;
`ai/analyst.py` consumes the preset bundles.

## 3. How scenarios are represented

There is **no scenario object**. A scenario is a `Mapping[str, float]` of
changes, applied immediately and locally:

```python
def _build_scenario_inputs(base, changes):
    candidate = dataclasses.replace(base, **changes)
    return validate_acquisition_inputs(dataclasses.asdict(candidate))
```

The Detailed counterpart, `_build_detailed_scenario_terms`, is the same three
lines against `AcquisitionTerms` and `validate_acquisition_terms`.

Two deliberate properties, both documented in the source as the fix for a real
Gate 9A defect: `dataclasses.replace` carries every unnamed field forward
automatically (a hand-maintained field list previously reset the five
Underwriting V2 fields to neutral defaults in every cell), and the result is
routed through the **shared** validator, so domain rules are never
reimplemented and an out-of-domain value fails exactly as it would on the base
analysis.

## 4. What may currently be perturbed

```python
SUPPORTED_ASSUMPTIONS = (
    "purchase_price", "current_noi", "noi_growth",
    "exit_cap_rate", "ltv", "interest_rate",
)                                                    # Quick — 6

DETAILED_SUPPORTED_ASSUMPTIONS = (
    "purchase_price", "exit_cap_rate", "ltv", "interest_rate",
)                                                    # Detailed — 4
```

Both lists are frozen tuples; anything outside raises `UnknownAssumptionError`.

**Three exclusions are already settled by these lists and their comments, and
this document does not reopen them:**

- `occupancy` — informational only under the frozen POC convention.
- `hold_period`, `amortization` — *"discrete structural assumptions, deferred
  to a later phase."*
- Detailed's own operating dimensions (`revenue_growth`,
  `vacancy_credit_loss_pct`, `expense_growth`) — deferred, *"not added here
  merely to claim completeness."*

That last exclusion is the single most important precedent in this document.
**Detailed sensitivity varies only the shared acquisition terms.** It does not
vary the operating inputs that make Detailed *Detailed*.

## 5. How immutable contracts are copied

`dataclasses.replace` on a frozen, slotted, kw-only dataclass, then re-validated
through the shared validator. The base is never mutated. Every scenario is
built from the **original base**, never from the previous scenario.

## 6. Output metrics collected

```python
_METRIC_EXTRACTORS = {
    "levered_irr", "unlevered_irr", "equity_multiple",
    "headline_dscr", "exit_value",
}                                # sensitivity.py — 5
```

Each is a one-line lambda reading a field off `AcquisitionResults`. Break-even
restricts itself to three (`levered_irr`, `headline_dscr`, `equity_multiple`).
Anything else raises `UnknownMetricError`.

## 7. One-way and two-way

Both exist, for both modes. Two-way builds a full cartesian product and
evaluates **every cell from the same baseline** with both perturbations applied
together:

```python
scenario_inputs = _build_scenario_inputs(
    inputs, {row_assumption: row_value, column_assumption: column_value}
)
```

There is no incremental row-then-column construction, so scenario-order
contamination is already structurally impossible. `row_assumption ==
column_assumption` raises.

## 8. How baselines are represented

The baseline is computed by a **separate, extra** analysis call and stored on
the result (`baseline_assumption_value`, `baseline_metric_value`). It is *not*
required to appear among the candidate values. `TwoWaySensitivityResult`'s
docstring is explicit that a domain-filtered preset grid is not guaranteed to
put the baseline at its centre, which is why the baseline values are recorded
rather than inferred from position.

Call count is therefore `1 + N` for one-way and `1 + (R × C)` for two-way — and
this is asserted by guardrail (§10).

## 9. How invalid scenarios are handled

**Two different behaviours, by entry point:**

| Path | Behaviour |
|---|---|
| Explicit `run_*_sensitivity` with an out-of-domain value | `InputValidationError` propagates — **the entire run fails** |
| `build_*_preset` | `_valid_scenario_values` pre-filters: the candidate is **silently omitted**, never clamped and never raised |

The preset filter's docstring accepts the consequence directly: a preset matrix
"can be narrower than 5×5 near a domain boundary."

**There is no per-cell status channel.** No cell can say "invalid"; it can only
say "metric undefined" via `None`, which means something else.

## 10. Deterministic ordering

- Candidate order is the caller's order, preserved: `tuple(values)`.
- Preset filtering preserves order (append in iteration order).
- Rows and columns iterate in given order.
- No sets, no dicts, no sorting anywhere in the evaluation path.
- No RNG, no clock, no I/O.

## 11. Does sensitivity call the real engine for every scenario?

Yes, and it is enforced. `tests/test_analysis_architecture.py` patches the
engine with `wraps=` and asserts the exact call count:

```python
assert mock_analyze.call_count == 1 + len(values)
assert mock_analyze.call_count == 1 + (len(row_values) * len(column_values))
```

## 12. Break-even, and how it relates to sensitivity

`src/anchor/analysis/break_even.py` (1068 lines) deliberately mirrors
`sensitivity.py`: it re-declares its own `_build_scenario_inputs`,
`_build_detailed_scenario_terms` and `_extract_metric` rather than importing
them. It **shares the result contracts' module** but not the helpers.

The search is a plain bounded bisection with a per-assumption tolerance:

```python
_ASSUMPTION_TOLERANCES = {
    "purchase_price": 1_000.0, "exit_cap_rate": 0.00005,
    "noi_growth": 0.00005, "interest_rate": 0.00005, "current_noi": 100.0,
}
```

Five fixed questions (`max_purchase_price`, `max_exit_cap_rate`,
`min_noi_growth`, `max_interest_rate`, `min_current_noi`); Detailed exposes
three. No generic assumption/metric selector.

**A correction to the module's own claim, which matters in Part II.**
`BreakEvenDirection`'s docstring says the solver *"never assumes monotonicity
beyond"* evaluating both endpoints. That is true of the **endpoints**, but the
bisection loop that follows assumes a **single crossing** between the
qualifying and failing points:

```python
midpoint = (qualifying_value + failing_value) / 2
if _meets_hurdle(midpoint_metric, target):
    qualifying_value = midpoint
else:
    failing_value = midpoint
```

On a metric with several crossings this converges to *a* boundary, not the
extremal one, and reports it as `SOLVED`. For Quick and Detailed the five
assumptions produce smooth metrics and the assumption holds. §20 shows it does
not hold for parts of the Lease-Level surface.

## 13. Is sensitivity mode-aware? Is `OperatingMode` involved?

**No, and no.** `grep -rn "OperatingMode" src/anchor/analysis/` returns
**nothing**. Neither `sensitivity.py` nor `break_even.py` imports, references
or branches on the enum.

Mode selection happens one layer up, in `api.py`, which decides *which
function* to call. The sensitivity layer distinguishes modes by **function
identity**, never by a runtime discriminator.

This is decisive: **Lease-Level sensitivity needs no `OperatingMode` member at
all.** HD-D4-9 is not merely respected by the design — it is irrelevant to it.

## 14. Does the current architecture assume only Quick and Detailed?

Partly. Three assumptions are baked in, and only the first is a real
constraint for us:

1. **A scenario perturbs exactly one flat contract.** Both `_build_scenario_*`
   helpers do `dataclasses.replace(base, **changes)` on a single object, and
   the baseline is read with `getattr(inputs, assumption)`. Lease-Level inputs
   span six contracts, two of them inside collections. **This is the one place
   the existing shape genuinely does not fit.**
2. **Adding a mode means adding a parallel function pair.** Detailed did
   exactly this; nothing generic was introduced.
3. **`_ASSUMPTION_TOLERANCES` in break-even is keyed by assumption name** and
   would need entries for any new break-even target.

Nothing else in the framework is Quick/Detailed-specific. The result contracts,
the metric extractors, the ordering discipline, the invalid-value semantics and
the call-count guardrails are all mode-neutral already.

---

# PART II — PROPOSED LEASE-LEVEL ARCHITECTURE

## 15. The seam, and why it is option C

**Recommendation: C — a narrow Lease-Level sensitivity orchestrator reusing the
existing scenario/result contracts.**

| Option | Verdict |
|---|---|
| **A** — extend the current generic framework | **Rejected.** There is no "generic framework" to extend: `run_one_way_sensitivity` is hard-wired to `AcquisitionInputs` and `analyze_acquisition`. Generalising it would mean rewriting the functions that produce every shipped Quick and Detailed number. |
| **B** — a Lease-Level adapter into the existing framework | **Rejected.** An adapter implies a shared dispatcher taking a mode/adapter argument — which is precisely the runtime discriminator §13 shows the framework has deliberately avoided. It would also make `sensitivity.py` import `anchor.leasing`. |
| **C** — narrow orchestrator, existing contracts | **Recommended.** Exactly what Detailed did: a parallel function pair, same result contracts, same conventions, no change to any existing function. |
| **D** — small neutral framework refactor | **Rejected.** Nothing requires it. The gate is explicit: do not refactor for theoretical symmetry. |

### 15.1 A new module, not an addition to `sensitivity.py`

This is the one place the proposal deviates from the Detailed precedent, and
the reason is concrete.

D4.5B established a guardrail that **exactly two modules in the source tree may
import `anchor.leasing`** — `analysis/lease_level.py` and
`analysis/contracts.py`. Putting Lease-Level sensitivity inside
`sensitivity.py` would make a *third*, and would give
`anchor.analysis.sensitivity` — imported by `api.py` on every Quick and
Detailed request — a transitive dependency on the whole leasing package.

**Proposed: `src/anchor/analysis/lease_level_sensitivity.py`.**

The payoff is the strongest possible Quick/Detailed preservation proof:
`sensitivity.py` and `break_even.py` stay **byte-identical**, verifiable with
`git diff` against `84fbbfd` — the same technique D4.5B used for the engine.

The leasing-importer guardrail narrows from two named files to three named
files. It is not weakened.

### 15.2 The dependency direction

```
anchor.leasing
      |
anchor.analysis.lease_level                  (D4.5B — the bridge)
      |
anchor.analysis.lease_level_sensitivity      (D4.6B — THIS)
      |
anchor.engine.acquisition / debt / returns   (unchanged, never imports upward)
```

Sensitivity sits **above** the bridge and calls only its public entry point. It
does not import `anchor.leasing` builders, does not reach D2 rollover, D3
recoveries, D4.3 NOI or the engine returns directly, and does not know that a
`RecursiveRollover` exists.

## 16. Exact scenario evaluation flow

```
        baseline inputs (6 frozen contracts, never mutated)
                              |
        +---------------------+---------------------+
        |                                           |
   ONE extra call                         for each scenario cell:
   for the baseline                       resolve target -> (contract, field)
        |                                 dataclasses.replace on THAT contract
        |                                 re-validate through the shared validator
        |                                           |
        |                     analyze_lease_level_acquisition_with_projection(
        |                         terms, property_inputs, suites, leases,
        |                         market_leasing=..., operating_inputs=...)
        |                                           |
        |                        [ the entire D1->D4.5A pipeline reruns ]
        |                        months, chains, expenses, THE pool,
        |                        recoveries, aggregation, monthly NOI,
        |                        annual adapter, terminal-NOI validation,
        |                        OperatingCapitalSchedule, shared engine
        |                                           |
        +----------> read ONE scalar off AcquisitionResults <----------+
                              |
                  OneWay/TwoWaySensitivityResult
```

Every cell starts from the **same** baseline. No cell sees another cell's
inputs or outputs. Nothing is carried forward.

## 17. Proposed contracts and target representation

### 17.1 Result contracts — reuse, unchanged

`OneWaySensitivityResult` and `TwoWaySensitivityResult` are used **exactly as
they are**. No new field, no Lease-Level result schema. The Detailed precedent
is identical, and inventing a parallel schema would fork presentation and the
AI layer later.

### 17.2 Target representation — a frozen tuple plus an explicit map

Following the existing convention, the public target is a `str` from a frozen
tuple, so `OneWaySensitivityResult.assumption` needs no change:

```python
LEASE_LEVEL_SUPPORTED_ASSUMPTIONS: tuple[str, ...] = (...)   # §18
```

Resolution is an **explicit, exhaustive, module-private map** from that string
to the contract that owns it — never a parsed dotted path:

```python
class _TargetContract(StrEnum):
    TERMS = "terms"                      # AcquisitionTerms
    OPERATING = "operating_inputs"       # LeaseLevelOperatingInputs
    MARKET = "market_leasing"            # MarketLeasingAssumptions

_TARGET_OWNERS: dict[str, _TargetContract] = { ... }   # one entry per target
```

**Why not a dotted-path string.** `"suites[2].market_leasing_override.new_ti_psf"`
would permit mutations nobody approved, would need a parser and its own error
taxonomy, and would silently accept a path into a contract that has no
validator. The gate rules it out and the analysis agrees.

**Why not a typed `SensitivityTarget` enum in the public signature.** It would
change `OneWaySensitivityResult.assumption`'s type or force a `.value`
conversion at the boundary, breaking the "reuse contracts unchanged" property
and every existing consumer's expectations. The frozen-tuple-of-`str`
convention is already the repository's answer, and it is enforced by
`UnknownAssumptionError`. A private `StrEnum` for the *owner* is an
implementation detail and stays private.

### 17.3 The perturbation helper

One helper per owning contract, each three lines, each routed through the
contract's existing validator — mirroring `_build_detailed_scenario_terms`
exactly. No sensitivity-specific domain rules (§19).

## 18. Sensitivity target ownership and classification

Every field of the six input contracts, classified. `S` = supported in D4.6,
`D` = defer, `U` = unsuitable for generic numeric sensitivity, `F` = future
specialised scenario tooling.

### 18.1 Shared acquisition terms — `AcquisitionTerms`

| Field | Class | Reason |
|---|---|---|
| `purchase_price` | **S** | In `DETAILED_SUPPORTED_ASSUMPTIONS` today. Measured monotonic (§20). Highest-value question there is. |
| `exit_cap_rate` | **S** | Same. Measured monotonic. |
| `ltv` | **S** | Same. |
| `interest_rate` | **S** | Same. Measured monotonic. |
| `acquisition_cost_pct`, `financing_fee_pct`, `disposition_cost_pct` | **D** | Not sensitivity dimensions for Quick or Detailed either. Adding them for Lease-Level alone creates an asymmetry with no analytical demand. |
| `annual_capex_reserve` | **D** | Same. Also overlaps conceptually with TI/LC, which are their own channel — varying both invites double-count confusion in reading. |
| `hold_period` | **D** | §22. Discrete; already deferred framework-wide; **measured non-monotonic**. |
| `amortization`, `io_period` | **D** | Discrete; already deferred framework-wide. |

**All four `S` entries are exactly `DETAILED_SUPPORTED_ASSUMPTIONS`.** Lease-Level
inherits the Detailed shared-terms set with no additions and no subtractions.

### 18.2 Property operating assumptions — `LeaseLevelOperatingInputs`

This contract has **no suite-level override anywhere in the codebase**, so
every field here is unambiguously property-wide. That makes it the *safest*
place to add a leasing-side dimension.

| Field | Class | Reason |
|---|---|---|
| `expense_growth` | **S — APPROVED** | Measured monotonic. Property-wide, unambiguous (§38.2). Rebuilds expenses → pool → recoveries → fee via EGI → NOI → exit NOI, exercising the deepest rebuild chain of any target. High analytical value. |
| `recoverable_expense_ratio` | **S — APPROVED** | Measured monotonic and **by far the most influential single assumption tested** — equity multiple moved 0.33 → 1.63 across its domain. Property-wide, unambiguous, and §38.2 proves it is unreachable from any suite override. |
| `credit_loss_pct` | **D** | Legitimate, but low marginal value beside the two above and adds a fourth EGI-side dimension. |
| `management_fee_pct` | **D** | Same. Its circularity proof (D4 §13) is settled; nothing structural blocks it later. |
| `other_income`, `other_income_growth` | **D** | Small magnitude; not a decision driver. |
| `property_taxes`, `insurance`, `utilities`, `repairs_maintenance`, `other_operating_expenses` | **D** | Five separate line items. Varying one is arbitrary; varying all together is a different feature (a scaled-expense scenario), not a scalar sensitivity. `expense_growth` already answers "what if expenses run hotter" in one dimension. |

### 18.3 Market leasing assumptions — `MarketLeasingAssumptions`

**Every field in this contract is subject to the suite-override problem
(§19).** HD-D4.6-2 has since been decided (§38.2): the two approved targets ship
with a mandatory, target-specific shadow check.

| Field | Class | Reason |
|---|---|---|
| `market_rent_psf` | **S — APPROVED** with the §38.2 shadow check | The single highest-value Lease-Level question. Measured monotonic. Shadowed by **either** suite override field. |
| `renewal_probability` | **S — APPROVED** with the §38.2 shadow check | Measured monotonic. The assumption most unique to lease-level underwriting — no Quick or Detailed analogue exists. Shadowed **only** by a full `market_leasing_override`. §25.3 for domain handling. |
| `market_rent_growth` | **D** | Highly correlated with `market_rent_psf` in effect; one rent dimension is enough for D4. |
| `renewal_downtime_months`, `new_downtime_months` | **D** | **Measured non-monotonic** (§20.2). Supportable as a *sensitivity* dimension, but see §20.2 — the discontinuity is real and should be documented before it is exposed. |
| `renewal_free_rent_months`, `new_free_rent_months` | **D** | Same timing-discontinuity family as downtime. |
| `renewal_ti_psf`, `new_ti_psf`, `renewal_lc_pct`, `new_lc_pct` | **D** | Four separate fields; varying one of a renew/new pair is arbitrary, and varying both together is a linked perturbation the framework cannot express (one `assumption` string, one value). See HD-D4.6-1. |
| `renewal_term_months`, `new_term_months` | **D** | Discrete; changes successor chronology. §22. |
| `renewal_rent_psf`, `renewal_rent_spread`, `successor_escalation_pct`, `renewal_expense_stop_psf`, `new_expense_stop_psf` | **D** | Secondary; `renewal_rent_psf` is `float \| None` and its null-vs-value switch is categorical, not scalar. |
| `leasing_commission_method`, `renewal_lease_type`, `new_lease_type`, `renewal_recovery_basis`, `new_recovery_basis` | **U** | Enums. §23. |

### 18.4 Suite overrides — `Suite`

| Field | Class | Reason |
|---|---|---|
| `market_rent_psf`, `market_leasing_override` | **D** for D4.6 | Suite-specific targeting needs a target representation the current `assumption: str` contract cannot carry. HD-D4.6-3. |
| `suite_area_sf` | **U** | Changing it breaks the rentable-area reconciliation the D1 validator enforces, and would need a matching `Lease.leased_area_sf` change — a linked multi-contract edit, not a scalar perturbation. |
| `suite_id`, `suite_label` | **U** | Identity, not economics. |
| `initial_vacancy` | **U / F** | Categorical strategy plus a scalar. §24. |

### 18.5 Initial vacancy — `InitialVacancyAssumptions`

| Field | Class | Reason |
|---|---|---|
| `strategy` | **U** | Categorical. §24. |
| `initial_lease_up_months` | **F** | Scalar and meaningful, but lives *inside a suite*, so it inherits the suite-targeting problem (§18.4) and is additionally `None` under `HOLD_VACANT`. |

### 18.6 In-place lease — `Lease`

| Field | Class | Reason |
|---|---|---|
| `base_rent_psf`, `escalation_pct` | **F** | These are **contractual facts, not assumptions.** Sensitivity over a signed lease's stated rent asks "what if the contract said something else", which is a due-diligence/what-if question, not an underwriting sensitivity. Per-lease targeting also inherits §18.4. |
| `rent_commencement_date`, `lease_expiration_date`, `lease_start_date` | **U** | Dates. §22.2. |
| `lease_type`, `escalation_basis`, `recovery_basis`, `origin` | **U** | Enums. §23. |
| `lease_id`, `suite_id`, `tenant_name` | **U** | Identity. |
| `leased_area_sf`, `expense_stop_psf` | **F** | Area is reconciliation-linked (§18.4); the stop is meaningful only for one recovery basis. |

### 18.7 Property inputs — `LeaseLevelPropertyInputs`

| Field | Class | Reason |
|---|---|---|
| `analysis_start_date` | **U** | A date, and it rebuilds the entire calendar. §22.2. |
| `rentable_area_sf` | **U** | Reconciliation-linked to the sum of suite areas; perturbing it alone makes the rent roll invalid. |

## 19. Property-wide vs suite-specific — the measured problem

### 19.1 What the resolver actually does

`anchor/leasing/market.py::resolve_market_leasing` is the single precedence
authority, and it is **all-or-nothing**:

```
Suite.market_leasing_override.market_rent_psf  >  Suite.market_rent_psf
                                               >  property default   (rent level)
Suite.market_leasing_override.<field>          >  property default   (everything else)
```

> *"When a suite supplies `market_leasing_override`, that record is used in
> full and no field falls through to the property default."*

### 19.2 The measured consequence

A three-suite property, all rolling over inside the hold. Suite A takes the
property default; Suite B carries a scalar rent override at \$48; Suite C
carries a full `market_leasing_override` at \$52. Perturbing the **property
default** market rent:

| property `market_rent_psf` | exit NOI | levered IRR |
|---|---|---|
| 30.00 | 4,415,312.24 | 0.301549 |
| 36.00 | 4,662,289.76 | 0.322961 |
| 42.00 | 4,909,267.28 | 0.343136 |
| 48.00 | 5,156,244.80 | 0.362228 |

That looks fine — because Suite A still responds. Now the same property where
**every** suite carries a full override:

| property `market_rent_psf` | exit NOI | levered IRR |
|---|---|---|
| 30.00 | 4,724,034.14 | 0.328114 |
| 36.00 | 4,724,034.14 | 0.328114 |
| 42.00 | 4,724,034.14 | 0.328114 |
| 48.00 | 4,724,034.14 | 0.328114 |

**Every cell identical.** A 60% swing in market rent moves nothing, and the
output contains no indication that the perturbation was shadowed. An analyst
reads "market rent doesn't matter for this deal" — which is the exact opposite
of the truth.

This is not a hypothetical. It is the shipped resolver behaving exactly as
designed, met by a sensitivity that assumes the property default reaches
everything.

### 19.3 The four candidate semantics

| | Behaviour | Verdict |
|---|---|---|
| **A** property-default only | Perturb `MarketLeasingAssumptions.<field>`; overridden suites unaffected | Truthful about *what it changed*; silently misleading about *what it means*. Produces §19.2. |
| **B** proportional shock to resolved rents | Multiply every suite's resolved market rent | Reaches every suite, **but requires relative semantics** in an absolute-value framework (§21), and mutates suite records the analyst deliberately authored. |
| **C** overwrite all resolved rents | Set every suite's resolved value to the candidate | Destroys the override structure. An analyst who set Suite C to \$52 for a reason sees it silently discarded. Rejected. |
| **D** property-default, **refused when shadowed** | Semantics of A, but raise an explicit error if any suite shadows the target | Never silently wrong. Costs the ability to run the sensitivity on override-carrying properties. |

**Recommended D — and D was APPROVED** (§38.2). It preserves absolute-value
semantics, invents no new financial concept, keeps `resolve_market_leasing` the
sole precedence authority, and converts §19.2's silent flat row into an
explicit, honest refusal. **A, B and C are explicitly rejected for D4**; B is
the right *long-term* answer and is recorded as a deferred capability (§38.2.4),
but it introduces relative-shock semantics, which is a separate decision (§21)
and a larger one than D4.6 should absorb.

The exact detection rule — which turned out to be **target-specific**, not
all-or-nothing — was measured from shipped code and is stated in **§38.2.2**.

### 19.4 If suite targeting is later approved

Target by `suite_id`, never by index or ordering. An unknown `suite_id` is an
explicit unsupported-target error. There is no "first suite" semantics.
Duplicate suite ids are already rejected upstream by D1 validation.

## 20. Monotonicity, and the undefined-IRR finding

### 20.1 The measured surface

Levered cash flows for a representative Lease-Level deal with a rollover inside
the hold (\$40M price, H=5, TI \$25–35/SF, LC 4–6%):

```
[-14,484,000,  +1,676,261,  +1,678,673,  -2,566,172,  +1,860,935,  +31,326,175]
                                          ^^^^^^^^^^
                                  TI/LC in the rollover year
```

**Three sign changes.** The series is non-conventional, so a levered IRR does
not exist, and the engine correctly returns `None`. Equity multiple remains
perfectly well defined (2.14).

**This is not an edge case — it is the normal shape** for a lease-level deal
whose rollover-year leasing costs exceed that year's cash flow after debt
service. Quick essentially cannot produce it (its cash flows are NOI-driven and
sign-stable); Detailed rarely does; Lease-Level does it routinely.

**Consequence for sensitivity:** benign. `metric_values` may be `None` across
whole regions of a `levered_irr` grid, which is exactly what the existing
`float | None` channel is for. `equity_multiple`, `exit_value` and
`headline_dscr` stay defined.

**Consequence for break-even:** severe. Two of break-even's three hurdle
metrics are `levered_irr` and `equity_multiple`; an IRR-hurdle question would
return `NO_SOLUTION_IN_RANGE` for a deal that is in fact perfectly healthy.

### 20.2 Measured monotonicity (equity multiple, 5-point sweeps)

| Target | Direction | Monotonic? |
|---|---|---|
| `purchase_price` | 2.143 → 1.241 | **yes** |
| `exit_cap_rate` | 2.070 → 1.305 | **yes** |
| `interest_rate` | 1.760 → 1.498 | **yes** |
| `market_rent_psf` | 0.734 → 2.534 | **yes** |
| `renewal_probability` | 1.536 → 1.733 | **yes** |
| `expense_growth` | 1.634 → 1.613 | **yes** |
| `recoverable_expense_ratio` | 0.331 → 1.629 | **yes** |
| `new_downtime_months` | 1.619 → 1.536 **→ 1.575** | **NO** |
| `hold_period` | 1.486 → 1.736 **→ 1.507** | **NO** |

### 20.3 Why downtime is non-monotonic — the mechanism, verified

Sweeping `new_downtime_months` with the successor's economics isolated:

| downtime | hold TI | hold LC | exit NOI | EM |
|---|---|---|---|---|
| 0.0–5.0 | 3,500,000 | 954,810 | 3,180,425 | 1.619 → 1.485 |
| **6.0** | 3,500,000 | **983,454** | **3,273,041** | **1.575** |

At six months the successor's commencement crosses into the next market-rent
year. Market rent is a **step function of time** — `market.py` states the
formula outright:

```
MarketRentPSF(m) = market_rent_psf * (1 + market_rent_growth) ** floor((m - 1) / 12)
```

with *"growth applied in annual steps on anniversaries."* So a longer void
makes the successor sign at a **higher** rent, lifting LC (a percentage of
total contractual base rent) and lifting the capitalised forward exit NOI. Past
a threshold, the rent gained by waiting outweighs the rent lost while vacant.

**The general rule this establishes:** any assumption that shifts a
commencement date — downtime, free rent, term length, hold period, lease dates
— produces a **piecewise-constant, discontinuous** metric surface. Bisection on
such a parameter converges to an arbitrary point *inside a flat step*, and
reports it as a solved threshold.

### 20.4 Break-even recommendation

**DEFERRED ENTIRELY — APPROVED (§38.5).** Three independent reasons, each
sufficient:

1. `levered_irr` is undefined for the normal Lease-Level cash-flow shape
   (§20.1), and it is the primary hurdle metric.
2. Two of the plausible targets are measurably non-monotonic (§20.2), and the
   bisection loop assumes a single crossing (§12).
3. `_ASSUMPTION_TOLERANCES` would need new entries, and a tolerance on a
   step-function parameter is meaningless.

**If it is later wanted**, the only defensible starting pair is
`max_purchase_price` and `max_exit_cap_rate` against an **equity-multiple**
hurdle — both measured monotonic, both on a metric that is always defined.
That is a D5+ gate with its own evidence and its own explicit
monotonicity / metric-suitability rules, not a D4.6 add-on. **HD-D4.6-5 —
DEFER.** `analysis/break_even.py` is **not to be modified during D4** (§38.5).

## 21. Absolute vs relative shocks

**Settled by existing convention; not a human decision.**

The framework is strictly **absolute**. `run_one_way_sensitivity(values=...)`
takes absolute assumption values, and `_build_scenario_inputs` writes them
straight onto the contract. Offsets and multipliers exist **only inside preset
builders**, which convert them to absolute values before calling the runner:

```python
_PURCHASE_PRICE_MULTIPLIERS = (0.90, 0.95, 1.00, 1.05, 1.10)
(inputs.purchase_price * m for m in _PURCHASE_PRICE_MULTIPLIERS)   # -> absolute
```

**Lease-Level adopts this unchanged:** absolute values in the public API,
relative offsets permitted only as a preset-construction convenience. No
assumption gets different semantics from any other, so nothing is mixed
silently.

This is also the technical reason §19.3 option B is a larger decision than it
appears: a proportional resolved-rent shock is the first genuinely *relative*
perturbation the framework would contain.

## 22. Discrete and date assumptions

### 22.1 Discrete

**All deferred**, and mostly already settled:

| Field | Status |
|---|---|
| `hold_period`, `amortization` | Already deferred framework-wide — *"discrete structural assumptions, deferred to a later phase."* Not reopened. `hold_period` is additionally **measured non-monotonic**. |
| `io_period` | Same family. |
| `renewal_term_months`, `new_term_months` | Change successor chronology and therefore which months land in the forward exit window — the §20.3 discontinuity family. |

Nothing here is blocked *technically* — every scenario is a full rebuild, so a
changed calendar is handled correctly. They are deferred because a
piecewise-constant "sensitivity" over five integers is a **scenario
comparison**, presented as a table of named cases, not a gradient. Forcing them
into a float grid invites the reader to interpolate between points that have no
between.

### 22.2 Dates

**Not permitted in D4.6.** `assumption_values` is `tuple[float, ...]`; a date
is not a float, and encoding one as an ordinal would be exactly the "generic
scalar sensitivity without explicit semantics" the gate forbids.
`analysis_start_date` additionally rebuilds every schedule in the model. Future
specialised scenario tooling.

## 23. Categorical assumptions

**Structurally excluded, and no decision is needed.** `LeaseType`,
`RecoveryBasis`, `EscalationBasis`, `LeasingCommissionMethod` and
`InitialVacancyStrategy` are enums; the result contracts are float-typed
(§1). An enum cannot enter a `tuple[float, ...]` without a contract change, so
the framework already refuses them.

NNN vs Gross vs Modified Gross is a **scenario comparison** — a small set of
named, fully-underwritten alternatives presented side by side — and belongs to
a future scenario layer that reuses the same one-engine rule. It is not a grid
axis. Encoding it as 0/1/2 would produce a "sensitivity" whose x-axis has no
ordering, no distance and no interpolation meaning.

## 24. Initial vacancy strategy

`HOLD_VACANT` vs `MARKET_LEASE_UP` is categorical, and encoding it as 0/1 is
explicitly ruled out by the gate and by §23. It is also *paired* with
`initial_lease_up_months`, which must be `None` under `HOLD_VACANT` — so the
two fields cannot be varied independently.

**Recommendation:** future strategy/scenario-comparison layer, not D4.6.

## 25. Invalid scenarios and non-positive exit NOI

### 25.1 The new question

Existing invalid values are caught by **input validation**, before any analysis
runs, so presets can pre-filter them cheaply (§9). `NON_POSITIVE_FORWARD_EXIT_NOI`
is different in kind: it is raised **by the analysis itself**, at the D4.5B
acquisition boundary, after the whole monthly model has been built. It cannot
be predicted from the inputs.

A market-rent or exit-cap sensitivity can legitimately drive a cell there. The
gate is explicit that sensitivity must not floor it, capitalise it, zero it, or
skip it.

### 25.2 Recommendation — no new semantics, just a wider `except`

| Path | Behaviour | Consistent with |
|---|---|---|
| Explicit `run_lease_level_*_sensitivity` | `LeaseValidationError` propagates; **the run fails**, naming the offending scenario | Today's explicit-run behaviour for `InputValidationError` |
| `build_lease_level_*_preset` | The candidate is **omitted** from the grid, exactly as an out-of-domain candidate is | Today's preset behaviour, incl. its documented "narrower than 5×5" |

Implementation is one line wider in the preset filter — catch
`LeaseValidationError` alongside `InputValidationError`. **No per-cell status
field, no new `None` meaning, no new contract.**

**The cost, stated plainly:** a preset grid can silently lose a row or column,
and the analyst is not told which scenarios were refused or why. That is
already true today for domain-invalid candidates and is documented as
acceptable — but "this cell is not underwritable" is arguably more interesting
to a reader than "this cell was out of domain."

The alternative (a per-cell status channel) is a genuine improvement but it is
a **framework change affecting Quick and Detailed**, which this gate's
minimality preference argues against. **HD-D4.6-4**, non-blocking: the
recommended option requires no decision to proceed, and the richer option can
be added later without breaking anything built now.

### 25.3 Probability domain

`renewal_probability` keeps its contract domain `0 ≤ p ≤ 1` with **no
clipping**. A candidate of 1.2 is invalid and follows §25.2 exactly like any
other out-of-domain value.

`p = 0` and `p = 1` are **exact branch endpoints** in D2, not limits — at
`p = 0` the renewal branch contributes nothing and the new-tenant branch is the
whole outcome, and vice versa. Both were measured (§20.2: 1.536 at `p=0`,
1.733 at `p=1`) and both must remain reachable as candidate values. A
sensitivity that excluded the endpoints, or that nudged them to 0.001/0.999 to
avoid a branch, would be wrong.

### 25.4 Ratio and percentage domains

All reuse the original contract validators — `validate_acquisition_terms` for
`ltv` / rates, and the leasing validators for `management_fee_pct`,
`credit_loss_pct`, `recoverable_expense_ratio`, LC percentages and growth
rates. **No sensitivity-specific domain is defined anywhere.** No clipping. All
rates are decimals throughout (0.065 is 6.5%), matching the contracts, so no
percent-vs-decimal ambiguity is introduced.

## 26. One-way and two-way design

### 26.1 One-way

```python
run_lease_level_one_way_sensitivity(
    terms, property_inputs, suites, leases, *,
    market_leasing, operating_inputs,
    assumption: str, values: Sequence[float], metric: str,
) -> OneWaySensitivityResult
```

One extra baseline call, then one full re-underwrite per candidate in the
caller's order. Baseline recorded on the result per existing convention, not
required to appear among the candidates. Call count `1 + N`, guardrailed.

### 26.2 Two-way

```python
run_lease_level_two_way_sensitivity(
    ..., row_assumption, row_values, column_assumption, column_values, metric,
) -> TwoWaySensitivityResult
```

Cartesian product; **every cell built from the same baseline with both
perturbations applied together**, mirroring the existing implementation
exactly. No row-then-column incrementalism. `row_assumption ==
column_assumption` raises.

**APPROVED — two-way ships in D4.6B (§38.6).** It is the same code shape as
one-way, the anti-contamination property is inherited from the existing
implementation rather than invented, and §27 shows the runtime is trivial. A
one-way-only gate would leave the highest-value view (price × exit cap)
unavailable for exactly the mode that needs it most.

**Presets: defer to D4.6C or later.** Preset bundles imply a
`StandardLeaseLevelSensitivityPresets` contract and a decision about which
matrices are standard — and they are what the AI/API layers consume, which is
D5 territory under HD-D4-9. The runners are the deterministic core; presets are
presentation packaging.

## 27. Performance, caching, parallelism

### 27.1 Measured

Median of 15 runs, warm, on the D4.5B tree:

| Shape | Median |
|---|---|
| simple property (1 suite, no rollover, H=3) | **0.92 ms** |
| mixed property (4 suites, 2 rollovers, H=3) | **2.70 ms** |
| mixed property, H=10 | **11.35 ms** |

One Lease-Level re-underwrite costs ≈ **14.7×** one Quick scenario.

### 27.2 Estimated grid runtime, full re-underwrite, sequential

| Grid | Cells (incl. baseline) | simple | mixed H=3 | mixed H=10 |
|---|---|---|---|---|
| 5-cell one-way | 6 | 0.006 s | 0.016 s | 0.068 s |
| 9-cell one-way | 10 | 0.009 s | 0.027 s | 0.114 s |
| 5×5 two-way | 26 | 0.024 s | 0.070 s | 0.295 s |
| 10×10 two-way | 101 | 0.093 s | 0.273 s | **1.147 s** |
| three 5×5 presets | 78 | 0.072 s | 0.211 s | 0.886 s |

**Conclusion: performance is a non-issue — findings ACCEPTED (§38.7).** The
worst realistic case is about one second. **No grid-size limit is required by
performance.** Correctness and determinism outrank unnecessary optimization,
and here correctness costs nothing.

### 27.3 Caching — **do not add (APPROVED, §38.7)**

No memoization, at any level. There is no performance problem to solve (§27.2),
and a correct cache would need a dependency-aware fingerprint over six nested
contracts. A cache keyed on anything less would return a stale projection when
an unfingerprinted field changed — precisely the "stale recoverable pool /
stale TI-LC" failure family in §31. The existing framework provides no cache
seam and should not grow one here.

### 27.4 Parallelism — **do not add (APPROVED, §38.7)**

The existing framework is sequential and deterministic. §27.2 shows no need.
Deferred.

## 28. Baseline immutability

Guaranteed structurally rather than by discipline:

- Every input contract is `frozen=True, slots=True, kw_only=True`.
- Every perturbation is `dataclasses.replace` → a **new** object.
- Every scenario is built from the original baseline, never from a predecessor.
- The suites and leases tuples are rebuilt, never mutated in place.

Asserted directly: after a full run, every baseline contract compares equal to
a pre-run deep copy; repeated runs are `float.hex()`-equal; and permuting
candidate order does not change any cell.

## 29. Result retention

### 29.1 Measured cost

For a single-suite H=5 property, one `LeaseLevelAcquisitionResults` pickles to
**22,569 bytes**, of which the `MonthlyPropertyProjection` is **20,766 bytes —
92%**.

| Grid | Retain full envelopes | Retain scalars only |
|---|---|---|
| 5×5 | 0.54 MB | ~0.39 KB |
| 10×10 | 2.15 MB | ~1.56 KB |

A 4-suite H=10 property multiplies the per-cell figure several-fold.

### 29.2 Recommendation

**Retain scalars only per cell — APPROVED (§38.8).** Reuse
`OneWaySensitivityResult` / `TwoWaySensitivityResult` exactly as they are,
holding the candidate value and one metric. The full
`LeaseLevelAcquisitionResults` (and its `MonthlyPropertyProjection`,
`AnnualOperatingProjection` and suite-chain tree) exists **temporarily** during
each scenario's evaluation and is then reduced to the selected metric. This is
a **memory boundary, not a financial shortcut**: every scenario still performs
the complete re-underwrite.

The full baseline audit trail is **not lost**: the caller already holds the
baseline `LeaseLevelAcquisitionResults` from its own analysis call, complete
with its `MonthlyPropertyProjection`. Any individual scenario can be
re-underwritten on demand in ~1–11 ms (§27.1) to obtain its full audit tree.

Retaining 100 complete 12H+12 suite-chain audit trees to answer a question
nobody asked is three orders of magnitude of memory for no analytical gain —
and it would require a new result contract, violating §17.1. This costs
nothing in determinism: the retained scalars are the exact floats the
authoritative pipeline produced.

## 30. Quick / Detailed preservation

Strategy, strongest first:

1. **`sensitivity.py` and `break_even.py` are not edited.** Byte-identity
   against `84fbbfd` is asserted by guardrail via `git diff --name-only`, the
   technique D4.5B used for the engine package.
2. `anchor.engine` and `anchor.leasing` are not edited either.
3. The new module is additive; no existing function changes signature or
   behaviour.
4. The 624-object Quick/Detailed hex matrix is re-run against `964c9a7` and
   must show **0 differences**.
5. A guardrail asserts Quick and Detailed sensitivity do **not** route through
   the Lease-Level module (mutation 13, §33).

**No neutral framework refactor is recommended**, so nothing needs a
preservation proof beyond file identity.

## 31. Failure modes

| # | Failure | Guarded by |
|---|---|---|
| 1 | Output-level perturbation instead of input re-underwrite | Call-count guardrail; AST guardrails banning NOI/IRR/exit-value arithmetic |
| 2 | Cumulative scenario mutation (cell *n* built from cell *n−1*) | Baseline-immutability golden; mutation 2; every scenario built from the frozen base |
| 3 | Two-way applying columns cumulatively | Mutation 3; both perturbations applied in one `replace` from the same baseline |
| 4 | **Property shock silently shadowed by a suite override** | §19.2 — **measured**; HD-D4.6-2; the recommended refusal |
| 5 | Suite-target shock applied to the wrong suite | Not reachable in D4.6 (suite targeting deferred); guardrail asserts no suite-level target exists |
| 6 | Renewal probability silently clipped | §25.3; mutation 6; domain delegated to the contract validator |
| 7 | Non-positive forward exit NOI capitalised anyway | §25.2; mutation 7; D4.5B's `require_capitalizable_exit_noi` still runs inside every scenario |
| 8 | Exit-cap change altering exit **NOI** (not just value) | Mutation 8; exit NOI is produced upstream of the engine |
| 9 | Interest-rate change altering NOI | Mutation 9; NOI is computed before debt |
| 10 | Stale recoverable pool after an expense change | Mutation 10; the pool is rebuilt inside `analyze_lease_level_...` every scenario |
| 11 | Stale recoveries / TI / LC after a probability change | Mutation 11 |
| 12 | Stale exit NOI | Full re-underwrite; no partial update path exists |
| 13 | Baseline mutation | §28; immutability golden |
| 14 | Partial re-underwrite | One entry point, one call; no direct D2/D3/D4.3/engine calls (guardrail) |
| 15 | Quick/Detailed regression | §30; byte-identity + 624-object matrix |
| 16 | Public-mode leakage / implicit Lease-Level publication | HD-D4-9 guardrails carried forward; §32 |
| 17 | Invalid cell silently treated as zero | §25.2 — omitted or raised, **never zero**; a zero would be a fabricated return |
| 18 | Break-even on a non-monotonic parameter | §20 — **measured**; break-even deferred entirely |
| 19 | Scenario-order dependence | Permutation golden; determinism golden |
| 20 | Caching stale dependent economics | §27.3 — no cache |
| 21 | Memory explosion from retained audit trees | §29 — **measured**; scalars only |
| 22 | Undefined IRR misread as failure | §20.1 — `None` is the correct, existing channel for an undefined metric |

## 32. Public-mode interaction (HD-D4-9)

D4.6 **does not touch** `OperatingMode`. §13 establishes that the sensitivity
layer has never referenced it: modes are distinguished by function identity,
and Lease-Level gets its own functions.

No FastAPI, web, persistence, AI or CLI wiring. The D4.5B guardrails that keep
`"lease_level"` out of the public surface, and `POST /analyze` returning 422,
are carried forward unchanged and must still pass.

D5 remains the owner of atomic public-mode publication.

---

# PART III — D4.6B PLAN

## 33. Expected implementation surface

| File | Change |
|---|---|
| `src/anchor/analysis/lease_level_sensitivity.py` | **NEW** — the runners, the target map, the perturbation helpers |
| `src/anchor/analysis/__init__.py` | exports only |
| `tests/test_analysis_d4_6b_lease_level_sensitivity.py` | **NEW** — goldens |
| `tests/test_analysis_d4_6b_architecture.py` | **NEW** — guardrails |
| `tests/test_analysis_architecture.py` | narrow guardrail additions |
| `tests/test_leasing_architecture.py` | narrow the leasing-importer guardrail from two files to three |

**No change expected to:** `analysis/sensitivity.py`, `analysis/break_even.py`,
`analysis/contracts.py`, `analysis/lease_level.py`, any `engine/` file, any
`leasing/` file, `ai/`, `api.py`, `web/`, persistence, ingestion.

**No financial-module change is required.** Every number comes from the
existing pipeline; sensitivity only chooses inputs and reads one output field.

## 34. Golden plan

| # | Golden |
|---|---|
| 1 | **Baseline identity** — a one-way run whose candidate equals the baseline produces a cell `float.hex()`-equal to a direct `analyze_lease_level_acquisition_with_projection` call |
| 2 | Purchase-price sensitivity — monotone decreasing EM; exit **NOI unchanged** across cells |
| 3 | Exit-cap sensitivity — exit *value* moves, exit **NOI does not** |
| 4 | Interest-rate sensitivity — NOI and exit NOI **bit-identical** across cells; DSCR and levered returns move |
| 5 | Market-rent sensitivity **(approved)** — successor rent, LC, exit NOI and returns all move together |
| 6 | Renewal-probability sensitivity **(approved)** — including exact `p=0` and `p=1` endpoints fed through the normal pipeline |
| 7 | Expense sensitivity — expenses, pool, recoveries, management fee and NOI all rebuilt; a cell with `recoverable_expense_ratio=0` differs from `=1` by the full recovery line |
| 8 | TI/LC — *(deferred; not in scope)* |
| 9 | Invalid-domain candidate — explicit run raises; preset omits |
| 10 | A candidate driving `NON_POSITIVE_FORWARD_EXIT_NOI` — explicit run raises that code; **no cell is zero, floored or capitalised** |
| 11 | One-way ordering — cells align positionally with candidates, in caller order |
| 12 | Two-way independence — cell (i,j) equals a direct analysis with both perturbations; and equals the same cell when rows/columns are permuted |
| 13 | Suite-target semantics — *(deferred by HD-D4.6-3; guardrail asserts no suite target exists)* |
| 14 | **Market-rent shadow golden (MANDATORY, §38.9)** — a suite override shadows the property default; property-level market-rent sensitivity is **refused** with the shadow error. Not four identical cells, not a silent no-op, not an override overwrite |
| 14b | **Renewal-probability shadow golden (MANDATORY, §38.9)** — a full `market_leasing_override` shadows it and is refused; a suite carrying **only** the scalar `market_rent_psf` override does **not** shadow it and the run proceeds |
| 14c | **Unshadowed operating targets** — `expense_growth` and `recoverable_expense_ratio` are never shadowed, on any suite shape |
| 15 | Quick/Detailed preservation — existing sensitivity results unchanged; 624-object hex matrix |
| 16 | Repeated-run equality — two identical runs are `float.hex()`-equal |
| 17 | Baseline immutability — all six contracts compare equal to a pre-run deep copy |
| 18 | Call count — `1 + N` and `1 + R×C` calls to the Lease-Level entry point |
| 19 | **Undefined-metric golden (MANDATORY, §38.4)** — a *valid* TI/LC-heavy scenario yields a `None` levered-IRR cell **and the run stays valid**, while `equity_multiple` stays defined; then a separate *invalid* scenario **fails validation** rather than producing `None`. The distinction is separately guardrailed |

## 34.1 Mutation plan

1. Metric estimated from the baseline instead of re-underwriting.
2. Scenario *n* built from scenario *n−1*'s contracts.
3. Two-way applies columns cumulatively along a row.
4. Property market-rent shock overwrites a suite override.
5. Suite-target shock applied to the wrong suite (must be unreachable).
6. `renewal_probability` clipped into `[0,1]` instead of refused.
7. `require_capitalizable_exit_noi` bypassed inside the sensitivity path.
8. Exit-cap change also scales exit NOI.
9. Interest-rate change also scales NOI.
10. Expense change reuses a cached recoverable pool.
11. Probability change reuses baseline TI/LC.
12. Candidate order changes results (sorting candidates internally).
13. Quick or Detailed routed through the Lease-Level adapter.
14. Baseline metric computed from cell 0 instead of its own call.
15. Preset filter swallows `LeaseValidationError` **and** returns 0.0 for it.
16. `dataclasses.replace` targeted at the wrong owning contract.
17. A second `OperatingCapitalSchedule` built inside sensitivity.
18. Target map made permissive (arbitrary `setattr` by string).

## 34.2 Architecture guardrail plan

- No NOI, IRR, exit-value, DSCR or recovery formula in the module — AST ban on
  arithmetic beyond scenario-value construction.
- `analyze_lease_level_acquisition_with_projection` is invoked exactly
  `1 + N` / `1 + R×C` times (patch with `wraps=`).
- No direct call into D2 rollover, D3 recoveries, D4.3 projection or
  `engine.returns` / `engine.debt`.
- Every scenario constructed from the baseline object (no reassignment of the
  baseline names — AST).
- `OperatingMode.LEASE_LEVEL` still absent; `POST /analyze` still 422.
- `anchor.engine` imports nothing from `anchor.analysis`; `anchor.leasing`
  imports nothing from `anchor.analysis`.
- `analysis/sensitivity.py` and `analysis/break_even.py` unchanged since
  `84fbbfd`; `ai/`, `api.py`, `web/`, persistence, ingestion unchanged.
- No arbitrary field-path mutation: no `setattr`, no `getattr` with a
  non-literal, in the perturbation path.
- Unsupported targets raise explicitly; the supported tuple is frozen and its
  membership is asserted.
- No suite-level or lease-level target exists in D4.6.
- Invalid scenarios follow exactly one contract (§25.2).
- No `functools.cache` / `lru_cache` / module-level dict anywhere in the module.
- No `threading`, `multiprocessing`, `asyncio` or `concurrent` import.

---

# PART IV — HUMAN DECISIONS

## 35. HD-D4.6 register

**All six are decided as of the 2026-09-07 human review. No decision blocks
D4.6B.** Full rulings in §38.

| ID | Decision | Outcome | Blocking now |
|---|---|---|---|
| HD-D4.6-1 | Minimum supported D4 sensitivity dimensions | **APPROVED** (option C) | none |
| HD-D4.6-2 | Market-leasing sensitivity vs suite overrides | **APPROVED** (option D, target-specific) | none |
| HD-D4.6-3 | Suite-specific sensitivity scope | **DEFER** | none |
| HD-D4.6-4 | Invalid-cell representation | **APPROVED** (option A) | none |
| HD-D4.6-5 | Lease-Level break-even inclusion | **DEFER** | none |
| HD-D4.6-6 | Two-way sensitivity in D4.6B | **APPROVED** | none |

Absolute-vs-relative semantics (§21), categorical assumptions (§23), dates
(§22.2), `hold_period`/`amortization` (§18.1) and result retention (§29) are
**not** listed as human decisions: each is already settled by shipped code,
existing frozen conventions, or measurement.

### HD-D4.6-1 — Minimum supported D4 sensitivity dimensions — **APPROVED (option C)**

**A.** Shared terms only — `purchase_price`, `exit_cap_rate`, `ltv`,
`interest_rate`. Exactly `DETAILED_SUPPORTED_ASSUMPTIONS`.
**B.** Shared terms **+ 3 lease-level dimensions** — `market_rent_psf`,
`renewal_probability`, `expense_growth`.
**C.** B **+ `recoverable_expense_ratio`** (7 total).

**Recommendation: C.**

*Consequence.* A is the safest and most symmetric with Detailed — but it makes
Lease-Level sensitivity **analytically pointless**: it would answer only
questions Detailed already answers, while the lease-level economics that
justify the entire D4 sprint stay fixed. B adds the two highest-value
lease-level questions (what if market rent is wrong; what if tenants don't
renew) plus the deepest operating rebuild. C adds the single most influential
assumption measured — `recoverable_expense_ratio` moved equity multiple
0.33 → 1.63 — at zero marginal architectural cost, since it shares
`expense_growth`'s owning contract, which has **no suite override** and
therefore no HD-D4.6-2 exposure.

*Decided:* **approved**. It unblocks the supported-assumption tuple, the target map and goldens 2–7. Exact approved names in §38.1.

### HD-D4.6-2 — Market-leasing sensitivity vs suite overrides — **APPROVED (option D)**

Evidence: §19.2 — measured, a property whose suites all carry overrides returns
**four identical cells** for a 60% market-rent swing, with no indication in the
output.

**A.** Property-default only; overridden suites unaffected (silent flat row).
**B.** Proportional shock to every suite's **resolved** rent.
**D.** Property-default semantics, but **refuse** the run when any suite
shadows the target.

**Recommendation: D**, with B recorded as a deferred capability.

*Consequence.* A ships a sensitivity that can report "market rent doesn't
matter" for a deal where it matters enormously — the worst class of defect this
project guards against, because it is silent and plausible. B is analytically
the best answer but introduces the framework's first **relative** perturbation
(§21), mutates suite records the analyst deliberately authored, and needs its
own semantics for a suite carrying a full override versus a scalar one. D is
never wrong, needs no new concept, and costs only the ability to run these two
targets on override-carrying properties — which the analyst can still do by
editing the override.

*Decided:* **D approved**; A, B and C explicitly rejected for D4. It unblocks
both market-leasing targets. The detection rule turned out to be
**target-specific** rather than record-level — measured in §38.2.2 — so
`renewal_probability` and `market_rent_psf` have **different** shadow
conditions, and goldens 14 and 14b test them separately.

### HD-D4.6-3 — Suite-specific sensitivity scope — **DEFER (option A)**

**A.** Property-level targets only in D4.6.
**B.** Add suite-targeted variants keyed by `suite_id`.

**Recommendation: A.**

*Consequence.* B requires a composite target the current `assumption: str`
contract cannot carry, so it forces either a result-contract change (breaking
§17.1 and every existing consumer) or an encoded string like
`"suite:B:market_rent_psf"` — which is the arbitrary-path pattern the gate
rules out. A keeps D4.6 additive. If B is ever wanted, §19.4 fixes the
semantics in advance: target by `suite_id`, unknown id is an explicit error, no
"first suite".

*Decided:* **deferred**. Goldens 13 and mutation 5 stay written as "must be
unreachable"; no composite target contract is required in D4.6B.

### HD-D4.6-4 — Invalid-cell representation — **APPROVED (option A)**

**A.** Reuse existing semantics exactly — explicit runs raise, presets omit
(§25.2).
**B.** Add a per-cell status channel to the result contracts.

**Recommendation: A.**

*Consequence.* A requires no contract change and no new behaviour — only a
wider `except` in the preset filter. Its cost is that a preset grid can lose a
row without telling the reader that a scenario was *not underwritable* (as
opposed to merely out of domain). B is a real improvement in explanatory power
but is a **framework change touching Quick and Detailed**, which contradicts
this gate's minimality preference and would require its own preservation proof.

*Decided:* **A approved**. Nothing was blocked; A ships now and B can be added
later without invalidating anything built under A. The `None`-versus-validation-
failure distinction is locked in §38.4.1 and must be guardrailed.

### HD-D4.6-5 — Lease-Level break-even inclusion — **DEFER (option A)**

**A.** Defer entirely from D4.6.
**B.** Include, restricted to `max_purchase_price` / `max_exit_cap_rate` on an
equity-multiple hurdle.

**Recommendation: A.**

*Consequence.* Evidence against B in D4.6 is strong and measured: `levered_irr`
is **undefined** for the normal Lease-Level cash-flow shape (three sign
changes, §20.1); two plausible targets are **measurably non-monotonic**
(§20.2); market rent is a **step function of time** so any timing parameter is
piecewise-constant (§20.3); and the bisection loop assumes a single crossing
(§12). B's restriction to two monotonic targets on an always-defined metric is
defensible on today's evidence — but "defensible on two sweeps" is not the
standard this project has held, and a break-even that reports `SOLVED` at an
arbitrary point inside a flat step is exactly the silent-wrongness class.

*Decided:* **deferred entirely**. D4.6B has **no** break-even deliverable,
`_ASSUMPTION_TOLERANCES` gains no Lease-Level entries, and
`analysis/break_even.py` must not be modified during D4 at all (§38.5).

### HD-D4.6-6 — Two-way sensitivity in D4.6B — **APPROVED (option A)**

**A.** One-way and two-way together.
**B.** One-way only; two-way in a later gate.

**Recommendation: A.**

*Consequence.* Two-way is the same code shape as one-way and inherits its
anti-contamination property from the existing implementation rather than
inventing it. Runtime is ≈0.07 s for a 5×5 (§27.2). B would withhold the
highest-value view — price × exit cap — from the mode that most needs it, for
no risk reduction.

*Decided:* **approved**. Two-way ships in D4.6B; golden 12 and mutation 3 are in scope (§38.6).

## 36. Blocking decisions, restated

**NONE.** All six decisions were taken at the 2026-09-07 human review (§38).
D4.6B is unblocked and may begin when a D4.6B gate authorises it — this gate
does not.

## 37. Classification

**A — D4.6A FINANCIALLY ACCEPTED, READY FOR D4.6B.**

*(Originally classified "ready for human review" on 2026-09-07; that review
completed the same day and accepted the architecture. See §38.)*

The existing framework is fully mapped from source. The seam is chosen and
justified against the Detailed precedent. Every target is classified with a
reason. The three questions that could have been guessed wrong —
override shadowing, monotonicity, and undefined IRR — were **measured against
the shipped code** and each turned out to matter. Performance and memory are
quantified and neither constrains the design. No production change is required
outside one new analysis module and its tests, and Quick/Detailed preservation
reduces to file identity.

Six human decisions were enumerated and **all six are now decided; none
blocks D4.6B** (§38).

**D4.6B has not begun. Nothing is merged.**

---

# PART V — HUMAN REVIEW CLOSEOUT

## 38. D4.6A Closeout Amendment — 2026-09-07

**Amendment, not a rewrite.** Parts I–IV record the mapping, the design and the
options as presented for review. This section records the decisions taken at
the D4.6A human financial review, which **accepted the architecture**. Where
this section and an earlier one differ on a decided point, **this section
governs**; earlier conditional language ("recommendation", "if approved",
"blocking") has been reconciled in place and now points here.

**Status: D4.6A FINANCIALLY ACCEPTED. No human decision blocks D4.6B.**

### 38.1 HD-D4.6-1 — Supported D4 dimensions — **APPROVED**

D4.6B supports the smallest coherent Lease-Level sensitivity set: **eight
targets**.

**Shared acquisition targets — exactly the four already in
`DETAILED_SUPPORTED_ASSUMPTIONS`.** Read from
`src/anchor/analysis/sensitivity.py` at `cce2d6f`, not inferred:

```python
DETAILED_SUPPORTED_ASSUMPTIONS: tuple[str, ...] = (
    "purchase_price",
    "exit_cap_rate",
    "ltv",
    "interest_rate",
)
```

All four exist on `AcquisitionTerms` under those exact names.

**Lease-Level additive targets — four:**

| Target | Owning contract |
|---|---|
| `market_rent_psf` | `MarketLeasingAssumptions` |
| `renewal_probability` | `MarketLeasingAssumptions` |
| `expense_growth` | `LeaseLevelOperatingInputs` |
| `recoverable_expense_ratio` | `LeaseLevelOperatingInputs` |

**No other Lease-Level sensitivity target is in D4.6B.** Explicitly deferred,
at minimum: `market_rent_growth`; renewal/new rent spreads and
`renewal_rent_psf`; `successor_escalation_pct`; renewal/new downtime; renewal/new
free rent; renewal/new TI; renewal/new LC; the five individual fixed operating
expense lines; `other_income` and `other_income_growth`; `credit_loss_pct`;
`management_fee_pct`; the acquisition/financing/disposition cost percentages
not in the approved shared set; `annual_capex_reserve`; `renewal_term_months`
and `new_term_months`; `hold_period`; `amortization`; `io_period`; all dates;
all categorical lease structures; initial-vacancy strategy.

**The purpose of D4.6B is to prove correct full re-underwriting across a useful
minimum target set — not maximum target coverage.**

### 38.2 HD-D4.6-2 — Property default vs suite overrides — **APPROVED**

D4.6B supports **property-default market-leasing sensitivity only**. A scenario
whose selected target is shadowed by a suite-specific override is **rejected**.

#### 38.2.1 Prohibited alternatives

Options A, B and C of §19.3 are **explicitly rejected for D4**. D4.6B must not
overwrite a suite override, must not proportionally shock resolved suite
values, must not silently perturb only the un-overridden suites, and must not
report a property-wide-looking sensitivity whose target did not apply
consistently to the intended property-default population.

The rule is deliberately conservative because **the current sensitivity result
contracts cannot communicate affected-suite coverage** (§1) — there is no field
in which "this cell moved 2 of your 4 suites" could be stated.

#### 38.2.2 The exact shadow-detection rule, measured from shipped code

The review asked whether override behaviour is all-or-nothing at the record
level or field-level, and required the answer be taken from the code rather
than assumed. **It is both**, and therefore the check is **target-specific**.

`anchor/leasing/market.py::resolve_market_leasing` applies two distinct
mechanisms:

1. `market_leasing_override` (a whole `MarketLeasingAssumptions` record) is
   **all-or-nothing**: when present it replaces the property default entirely
   and *no* field falls through.
2. `Suite.market_rent_psf` (a bare `float | None`) is a **single-field**
   override applied on top of whichever record won — and it is the only such
   field on `Suite`.

`Suite` carries exactly these two override fields and no others:
`market_rent_psf: float | None`, `market_leasing_override:
MarketLeasingAssumptions | None`.

**Measured at the resolver** (property default rent \$30, renewal probability
0.70; override record rent \$48, renewal probability 0.25):

| Suite shape | resolved rent | resolved renewal prob | source |
|---|---|---|---|
| no override | 30.00 *(property)* | 0.70 *(property)* | `property_default` |
| scalar `market_rent_psf` only | 48.00 *(suite)* | **0.70 *(property)*** | `property_default` |
| full `market_leasing_override` | 48.00 *(override)* | **0.25 *(override)*** | `suite_override` |
| full override + scalar | 52.00 *(scalar wins)* | 0.25 *(override)* | `suite_override` |

**Confirmed end to end** — does perturbing the property default move exit NOI?
(renewal and new-tenant economics deliberately differentiated, so
`renewal_probability` is not inert by construction):

| Suite shape | `market_rent_psf` | `renewal_probability` |
|---|---|---|
| no override | MOVES | MOVES |
| scalar `market_rent_psf` only | **SHADOWED** | MOVES |
| full `market_leasing_override` | SHADOWED | **SHADOWED** |
| full override + scalar | SHADOWED | SHADOWED |

**The D4 rule, stated exactly:**

```
shadowed(suite, target) :=
    suite.market_leasing_override is not None
      or (target == "market_rent_psf" and suite.market_rent_psf is not None)
```

A run is rejected if **any** suite shadows the selected target. A two-way run
is rejected if **either** target is shadowed by any suite.

**The two operating targets are never shadowed and require no check.**
`expense_growth` and `recoverable_expense_ratio` live on
`LeaseLevelOperatingInputs`, which shares **no field name with `Suite`** and is
not reachable from any suite override — verified by field-set intersection,
which is empty. The check therefore applies only to the two market-leasing
targets.

#### 38.2.3 The validation concept

```
SENSITIVITY_TARGET_SHADOWED_BY_SUITE_OVERRIDE
```

**This is an ANALYSIS sensitivity validation, not a leasing financial-domain
validation.** It belongs to `anchor/analysis/lease_level_sensitivity.py` and
must **not** be added to `LeaseIssueCode` or to `anchor/leasing/validation.py`:
nothing about the rent roll is invalid, and the identical inputs remain
perfectly analysable through `analyze_lease_level_acquisition_with_projection`.
What is refused is *this sensitivity question about these inputs*.

Its message must name the shadowed target and the shadowing suite ids, so the
analyst can see exactly which suites made the question unanswerable.

D4.6B's exact error type and placement are an implementation detail of that
module, subject to the no-financial-formula rule (§38.10).

#### 38.2.4 Deferred future capability

Both remain deferred and neither may appear in D4.6B: **(A)** explicit
suite-specific sensitivity keyed by `suite_id`; **(B)** proportional shock to
resolved market economics. §19.4 fixes A's semantics in advance if it is ever
approved.

### 38.3 HD-D4.6-3 — Suite-specific targeting — **DEFER**

D4.6B does not support `suite_id` + assumption targeting, suite-index
targeting, or all-suite proportional targeting. The approved Lease-Level market
targets operate **only** on the property-default market-leasing assumptions,
subject to §38.2.

**No composite target contract is required in D4.6B.**

### 38.4 HD-D4.6-4 — Invalid scenario semantics — **APPROVED**

Current explicit-run semantics are preserved: **one invalid explicit scenario
fails the sensitivity run.** No per-cell validation-status contract is
introduced in D4.

#### 38.4.1 The `None`-versus-invalid distinction, locked

| | Meaning |
|---|---|
| **`None`** | The scenario was **valid** and fully underwritten; the requested output metric is **mathematically undefined**. Levered IRR may legitimately be `None` for a valid Lease-Level cash-flow shape — see §20.1, where TI/LC in a rollover year produce three sign changes. |
| **Validation failure** | The scenario **itself cannot be underwritten**. Examples: `renewal_probability` outside `[0,1]`; exit cap outside its domain; `NON_POSITIVE_FORWARD_EXIT_NOI`; a market-leasing target shadowed under §38.2. |

**Validation failure must never be encoded as `None`, `0`, `NaN`, or a sentinel
IRR.** A zero would be a fabricated return; a `None` would be indistinguishable
from a legitimately undefined metric.

The underlying Lease-Level validation remains authoritative — sensitivity
neither restates nor softens it.

Preset candidate generation may continue to exclude known invalid
**input-domain** values per existing framework convention (§9).

#### 38.4.2 `NON_POSITIVE_FORWARD_EXIT_NOI`

A scenario driving `exit_noi <= 0` must surface the existing
`NON_POSITIVE_FORWARD_EXIT_NOI` failure raised by
`analyze_lease_level_acquisition_with_projection`. Sensitivity must **not**
catch and convert it to `None`, convert it to zero, floor exit NOI, capitalise
it anyway, or continue the grid silently. Under §38.4 the explicit run fails.

### 38.5 HD-D4.6-5 — Lease-Level break-even — **DEFER ENTIRELY**

No Lease-Level break-even in D4.6B — no public and no internal entry point.
Four reasons, confirmed by this gate's investigation:

1. Normal Lease-Level levered cash flow can contain **multiple sign changes**,
   making levered IRR legitimately undefined (§20.1: `[-14.5M, +1.68M, +1.68M,
   −2.57M, +1.86M, +31.3M]`).
2. The current bisection **assumes a usable single crossing**, even though the
   module's own language says it does not assume monotonicity (§12).
3. Lease-Level timing-sensitive variables can be **non-monotonic / piecewise**
   because lease events cross market-rent anniversaries and other monthly
   boundaries (§20.2, §20.3).
4. Timing / term / rollover economics create discontinuities unsuitable for a
   generic bisection assumption.

**`analysis/break_even.py` must not be modified during D4** — not to "fix" the
monotonicity language, not to add tolerances, not at all. Quick and Detailed
break-even behaviour remains frozen and its outputs must be proven unchanged.

Future Lease-Level break-even requires its **own architecture** with explicit
monotonicity and metric-suitability rules.

### 38.6 HD-D4.6-6 — Two-way sensitivity — **APPROVED**

D4.6B includes both one-way and two-way sensitivity. Every scenario and every
cell is a **full independent re-underwrite from the same immutable baseline**:

```
baseline
  -> immutably replace row target
  -> immutably replace column target
  -> full Lease-Level analysis
```

or an equivalent immutable replacement sequence. **No row result becomes the
baseline of another row. No column result becomes the baseline of another
column. No cumulative scenario state.** Requested candidate ordering is
preserved deterministically.

### 38.7 Confirmed conventions

**Absolute value semantics — CONFIRMED.** D4.6B candidate values are **absolute
assumption values**: `exit_cap_rate = 0.065`, `market_rent_psf = 45.0`,
`renewal_probability = 0.70`. They are **not** relative shocks — not `+50 bps`,
not `+5%`, not `−10%`. **No relative shocks in D4**, and absolute and relative
semantics are never mixed. Preset builders may still convert offsets or
multipliers into absolute values before calling a runner (§21).

**Probability — CONFIRMED.** `renewal_probability` remains governed by its
source contract, `0 <= p <= 1`, with **no clipping**. `p = 0` and `p = 1`
remain valid **exact D2 branch endpoints**, and sensitivity must feed those
exact values through the normal deterministic pipeline.

**Performance — findings ACCEPTED.** No D4 grid-size limit is required by
performance (§27.2). **No memoization, no cache, no parallel execution, no
approximate updates** in D4.6B. Sequential full re-underwriting is the
reference behaviour; correctness and determinism outrank unnecessary
optimization.

### 38.8 Result retention — **APPROVED**

Cells retain only the existing sensitivity scalar result/metric surface. D4.6B
must **not** retain, per cell, a complete `LeaseLevelAcquisitionResults`,
`MonthlyPropertyProjection`, `AnnualOperatingProjection` or suite-chain tree.

**Every scenario must still perform the full re-underwrite.** The completed
full object may exist **temporarily** during scenario evaluation and is then
reduced to the selected result metric. This is a **memory boundary, not a
financial shortcut**. Baseline auditability remains available through the
caller's ordinary Lease-Level analysis.

### 38.9 Mandatory D4.6B goldens arising from this review

Three are named by the review and are **mandatory**; they are folded into the
golden plan at §34 (items 14, 14b, 14c and 19).

1. **Market-rent shadow golden.** A property where a suite override shadows the
   property-default `market_rent_psf`. Property-default market-rent sensitivity
   is attempted. Expected: an **explicit sensitivity-target-shadowed validation
   failure** — *not* four identical result cells, *not* a silent no-op, *not*
   an override overwrite.
2. **Renewal-probability shadow golden.** The same principle applied to
   `renewal_probability`, against the **measured** resolution behaviour of
   §38.2.2 — and it differs, which is the point: a full `market_leasing_override`
   shadows it and must be refused, while a suite carrying **only** the scalar
   `market_rent_psf` override does **not** shadow it and the run must proceed
   normally. Both halves are required; assuming symmetry with `market_rent_psf`
   would be wrong.
3. **Undefined-metric golden.** A **valid** Lease-Level scenario whose levered
   IRR is `None` under the existing engine because of its cash-flow shape —
   expected cell `None`, **run remains valid**. Then, separately, an **invalid**
   scenario — expected **validation failure, not `None`**. This distinction must
   be architecture-guardrailed, not merely asserted in a golden.

### 38.10 Confirmed D4.6B implementation surface

**New module: `src/anchor/analysis/lease_level_sensitivity.py`**, holding a
third parallel pair of Lease-Level sensitivity runners that call
`analyze_lease_level_acquisition_with_projection` for every scenario.

**`analysis/sensitivity.py` and `analysis/break_even.py` must not be refactored
for symmetry, and should remain byte-identical.** Quick/Detailed financial
engines remain unchanged, and D4.6B regression must prove current sensitivity
and break-even outputs are unchanged.

**The module MAY:** validate supported target names; resolve whether a target
is shadowed; immutably replace approved assumptions; invoke Lease-Level
analysis; extract the selected existing result metric; assemble the existing
sensitivity result contracts.

**The module MAY NOT calculate:** NOI, recoveries, rent, exit value, IRR,
equity multiple, DSCR, cash flow, or terminal NOI. Every scenario must call the
real Lease-Level analysis.

**Target representation.** An explicit immutable supported-name set plus a
single deterministic replacement mapping (§17.2). Unsupported names raise an
explicit error. **No arbitrary `getattr`/`setattr` traversal, no `eval`, no
string-path mutation, no unrestricted field paths.**

**`OperatingMode` — HD-D4-9 unchanged.** `OperatingMode.LEASE_LEVEL` is **not**
added during D4.6B. Lease-Level sensitivity is distinguished by **function
identity**, consistent with the current analysis architecture (§13). D5
publishes the mode atomically across its exhaustive consumers.

### 38.11 Consistency audit

Every active statement on the reviewed topics was audited and reconciled. No
stale alternative is left presented as open.

| Topic | Status after this amendment |
|---|---|
| Supported targets | §18 and §38.1 agree: 4 shared + 4 lease-level = 8. `recoverable_expense_ratio` and `expense_growth` upgraded from "recommended" to **APPROVED** |
| `market_rent_psf` | §18.3 and §38.2 agree: **APPROVED** with the target-specific shadow check |
| `renewal_probability` | Same, and §38.2.2 records that its shadow condition **differs** from `market_rent_psf`'s |
| Suite overrides | §19.3 options A/B/C explicitly **rejected for D4**; D approved. §19.2's measured flat-row evidence retained as the justification |
| `suite_id` sensitivity | §18.4 and §38.3 agree: **deferred**, no composite target contract |
| Absolute shocks | §21 and §38.7 agree: absolute only, **confirmed convention**, not an open decision |
| Relative shocks | Explicitly **rejected for D4**; recorded as deferred capability B (§38.2.4) |
| Invalid cells | §25.2 and §38.4 agree: explicit run fails, presets omit, **no per-cell status contract** |
| `None` metrics | §20.1, §25.2 and §38.4.1 agree: `None` means **valid scenario, undefined metric** — never a validation failure |
| `NON_POSITIVE_FORWARD_EXIT_NOI` | §25.2 and §38.4.2 agree: surfaced, never floored/zeroed/capitalised/skipped |
| Break-even | §20.4, §26/§35 and §38.5 agree: **deferred entirely**; `break_even.py` frozen for D4 |
| Two-way sensitivity | §26.2 and §38.6 agree: **approved**, same-baseline cells, no cumulative state |
| `OperatingMode.LEASE_LEVEL` | §13, §32 and §38.10 agree: **not added**; function identity distinguishes the mode |
| Result retention | §29.2 and §38.8 agree: scalars only, full object temporary, **memory boundary not a shortcut** |
| Caching | §27.3 and §38.7 agree: **none** |
| Parallelism | §27.4 and §38.7 agree: **none**, sequential is the reference behaviour |

One correction was made to this document's own earlier text: §19.3 described
the shadow condition as though it followed from record-level all-or-nothing
override semantics alone. Measurement (§38.2.2) shows the condition is
**target-specific**, because `Suite.market_rent_psf` is a genuine single-field
override. The rule in §38.2.2 is authoritative.

### 38.12 Status

**D4.6A is financially accepted.** Six decisions taken; four approved, two
deferred; **none blocking**.

**D4.6B has not begun, and this gate does not authorise it.** Nothing is
merged.
