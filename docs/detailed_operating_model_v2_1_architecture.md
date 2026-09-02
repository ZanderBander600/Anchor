# Detailed Operating Model V2.1 Architecture Specification

## Status

**Phase 0 — proposed, not yet implemented.** No production code, test, API
route, persistence schema, Excel format, or frontend file has been changed to
produce this document. This document specifies the contracts, calculation
layers, and gated implementation sequence for Detailed Operating Model V2.1,
built on `docs/detailed_operating_model_v2_1_financial_conventions.md` and
proven against `docs/detailed_operating_model_v2_1_golden_case.md`.

## 1. Current-State Findings

Inspection was performed read-only against `main` @ `a9b10a9` (the frozen
`showcase-v2-2026-09-03` demo commit). No file was modified during
inspection.

### 1.1 `AcquisitionInputs` (`src/anchor/contracts.py`)

A single frozen, `kw_only`, `slots` dataclass, fourteen fields: the nine
original POC V1 fields plus five Underwriting V2 fields, each V2 field
defaulting to its neutral value so a nine-field construction remains valid.
There is exactly one input contract — no separate "V1 inputs" and "V2
inputs" type.

### 1.2 `AcquisitionResults` / engine contracts (`src/anchor/engine/contracts.py`)

Five frozen dataclasses form a strict pipeline: `NoiForecast` →
(`CapitalStack`, `DebtSchedule`) → `AcquisitionCashFlows` → `ReturnMetrics` →
`AcquisitionResults`. `AcquisitionResults` itself performs no calculation —
it is assembled once, by `analyze_acquisition`, from the other four. This is
the existing pattern this proposal's operating-projection contract should
match.

### 1.3 NOI projection logic (`src/anchor/engine/noi.py`)

This is the seam. `forecast_noi(inputs: AcquisitionInputs) -> NoiForecast`
is a **13-line function** with three responsibilities:
`calculate_noi_by_year`, `calculate_exit_noi`, `calculate_going_in_cap_rate`
— each taking `current_noi`/`noi_growth`/`hold_period` as bare keyword
arguments, not the full `AcquisitionInputs`. `forecast_noi` is the only
function in the file that touches `AcquisitionInputs` directly. This means
the *seam is already almost exactly where it needs to be*: everything
downstream of `NoiForecast` (`acquisition.py`, `debt.py`, `returns.py`)
already depends only on the `NoiForecast` contract's fields
(`noi_by_year`, `exit_noi`, `going_in_cap_rate`), never on
`current_noi`/`noi_growth` directly. Building a second producer of
`NoiForecast` requires touching no downstream file.

### 1.4 Exit NOI calculation

`calculate_exit_noi` uses exponent `hold_period` (not `hold_period - 1`),
i.e. `exit_noi = current_noi * (1 + noi_growth)^H = NOI_(H+1)` — confirmed
by direct comparison against `calculate_noi_by_year`'s `NOI_y = current_noi *
(1+g)^(y-1)`. This is the exact `hold_period + 1` horizon convention Section
8 of the Phase 0 brief requires the Detailed model to replicate structurally
(not by approximation — see conventions doc "Projection Horizon").

### 1.5 Debt engine (`src/anchor/engine/debt.py`)

Consumes `AcquisitionInputs` directly (`calculate_capital_stack`,
`calculate_debt_schedule`), reading only `purchase_price`, `ltv`,
`acquisition_cost_pct`, `financing_fee_pct`, `interest_rate`,
`amortization`, `io_period`, `hold_period` — never `current_noi` or
`noi_growth`. **The debt engine has zero dependency on how NOI was
produced.** No change needed for Detailed Underwrite.

### 1.6 Returns engine (`src/anchor/engine/returns.py`)

Consumes only already-assembled `noi_by_year`, `annual_debt_service`,
`unlevered_cash_flows`, `levered_cash_flows` — no dependency on
`AcquisitionInputs` at all. No change needed.

### 1.7 Acquisition orchestration (`src/anchor/engine/acquisition.py`)

`analyze_acquisition(inputs: AcquisitionInputs) -> AcquisitionResults` is
"the sole public engine entry point" (its own docstring) and performs no
calculation of its own — it calls `forecast_noi(inputs)` exactly once, then
`calculate_capital_stack`/`calculate_debt_schedule`/exit-value/cash-flow
assembly/`calculate_return_metrics`, each exactly once, then assembles
`AcquisitionResults`. **This is the one function that must remain the single
downstream authority** — Section 10 below proposes how it should be
decomposed so Quick and Detailed both reach it without duplicating any of
its logic.

### 1.8 Validation (`src/anchor/validation.py`)

`ALL_FIELD_IDS = FIELD_IDS + V2_FIELD_IDS`. `validate_acquisition_inputs`
normalizes one flat mapping into one `AcquisitionInputs`, with unknown-ID,
missing-ID, and per-field domain checks each driven by static tuples/dicts
keyed by field id (`_DOMAIN_DESCRIPTIONS`, `_YEAR_FIELD_IDS`, the `in_domain`
mapping). This is a single-contract validator today; Section 6 discusses
what changes when a second, disjoint field set (the twelve detailed
operating fields) needs the identical validate-then-construct treatment.

### 1.9 Sensitivity / break-even (`src/anchor/analysis/sensitivity.py`,
`src/anchor/analysis/break_even.py`)

Both already fixed the exact bug class Section 15 of the Phase 0 brief warns
against (Gate 9A, documented in
`tests/test_analysis_v2_reconciliation.py` and both modules' own
docstrings): an earlier version reconstructed each scenario's
`AcquisitionInputs` from a hand-maintained field-id list, which silently
reset every V2 field to its neutral default. The fix —
`dataclasses.replace(base, **changes)` re-validated through
`validate_acquisition_inputs(dataclasses.asdict(candidate))` — carries every
untouched field of the frozen base dataclass forward automatically,
including any field added in the future. **This is exactly the pattern
Section 15's recommendation below generalizes**, and it is already proven
correct and regression-tested in this codebase.

### 1.10 Persistence (`src/anchor/deals/contracts.py`, `src/anchor/deals/store.py`)

`Deal.inputs` nests `AcquisitionInputs` directly — no flattened/duplicated
field set, no stored `AcquisitionResults`. SQLite storage is one `deals`
table with one column per `AcquisitionInputs` field (`REAL`/`INTEGER`,
verified bit-for-bit round-trip-safe by
`test_deals_store.test_stored_inputs_round_trip_exactly`), migrated forward
via `PRAGMA user_version`-gated `ALTER TABLE ADD COLUMN` statements
(`_migrate`, `_V2_MIGRATION_COLUMNS`) — the exact precedent for the
Underwriting V2 Gate 5 migration, and the direct template for a Detailed
Operating Model migration (Section 8 below).

### 1.11 Excel ingestion (`src/anchor/excel_reader.py`)

A single `"Inputs"` sheet, `Field ID`/`Input`/`Value`/`Unit` columns,
validated against the same `ALL_FIELD_IDS` the API uses — the fourteen-field
workbook format is a direct rendering of `AcquisitionInputs`' current field
set, with no per-mode branching today.

### 1.12 OM ingestion (`src/anchor/ingestion/contracts.py`, mirrored in
`web/src/types.ts`)

`ExtractionResult` carries `FieldCandidates` for exactly the nine original
V1 fields plus a fixed five-field `DealContext` (property name, address,
etc.) — the five V2 fields are "never extracted by OM ingestion in this
gate" (frontend `types.ts` comment, confirming this was a deliberate,
documented scope boundary, not an oversight).

### 1.13 API request/response contracts (`src/anchor/api.py`)

`/analyze` accepts one flat `dict[str, Any]` payload, validates it with
`validate_acquisition_inputs`, and calls `analyze_acquisition` — no mode
field, no branching. `/sensitivity`, `/sensitivity/presets`, `/break-even`,
`/ai/analysis` all wrap one nested `inputs` object the same way. `/deals*`
CRUD routes validate then delegate to `anchor.deals`.

### 1.14 Frontend types/conversion (`web/src/types.ts`, referenced
`web/src/convert.ts`)

`AcquisitionFormValues` (form strings) → `AcquisitionRequest` (typed
payload) is a manual field-by-field mirror of `AcquisitionInputs`, with
`ACQUISITION_FIELD_IDS`/`V2_FIELD_IDS` constants kept in lockstep with
`validation.py`'s Python-side tuples by convention (not by codegen).
`AcquisitionResults` (TS) mirrors `engine/contracts.py`'s `AcquisitionResults`
1:1. No frontend code is modified by this Phase 0 document.

### 1.15 Existing V2 golden case (`docs/underwriting_v2_golden_case.md`)

The authoritative regression benchmark this proposal's bridge case
(`docs/detailed_operating_model_v2_1_golden_case.md`) reuses in full for its
downstream half — see that document's "Downstream Bridge Invariant".

### 1.16 Existing architecture guardrails
(`docs/solutions/conventions/testing-conventions-and-architecture-guardrails.md`)

Three reusable test shapes already exist and should be extended, not
reinvented, for Detailed Underwrite:

1. **AST-parsing import-boundary tests** (`test_ai_architecture.py`,
   `test_analysis_architecture.py`, `test_ingestion_architecture.py`) — a
   per-layer guardrail that a forbidden import never enters a frozen layer.
2. **Delegation-via-`wraps` tests** — proving a layer calls the authoritative
   engine entry point rather than reimplementing its own version of a
   calculation.
3. **Spec-sourced golden-case tests at `pytest.approx(expected, rel=0.0,
   abs=1e-9)`** (`test_engine_golden_case.py`) — the pattern
   `docs/detailed_operating_model_v2_1_golden_case.md`'s Gate 4 tests should
   follow exactly.

**Resolution note (added before implementation, still Phase 0/docs-only).**
Section 2.2 and Section 4 below originally left one question open: how should
a Detailed deal populate `AcquisitionInputs.current_noi`/`.noi_growth`, which
`analyze_acquisition_from_operating_projection` was proposed to keep
requiring? That question is now closed, not deferred: the downstream
engine's shared-parameter shape is a new, concrete `AcquisitionTerms`
contract (Section 2.2) that simply has no `current_noi`/`noi_growth` fields
at all — a Detailed deal is never required to fabricate, zero-out, or derive
an approximate value for either. See Section 2.2 and Section 4 for the full
resolution; Section 12 records this as closed.

## 2. Proposed Contracts

### 2.1 `OperatingProjection` — the canonical operating contract

A new frozen, `kw_only`, `slots` dataclass in `src/anchor/engine/contracts.py`
(alongside `NoiForecast`, which it supersedes as the NOI-facing contract —
see 2.1.1), containing the authoritative Year-1..H (and H+1, for `exit_noi`)
schedules named in Section 9 of the Phase 0 brief, using explicit tuple
fields rather than a dictionary (matching every existing contract in this
file — `NoiForecast`, `CapitalStack`, `DebtSchedule`,
`AcquisitionCashFlows`, `ReturnMetrics` are all explicit dataclasses, never
dicts, for exactly the deterministic-field-ordering-and-typing reason the
brief names):

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class OperatingProjection:
    gross_potential_rent_by_year: tuple[float, ...]
    other_income_by_year: tuple[float, ...]
    vacancy_credit_loss_by_year: tuple[float, ...]
    effective_gross_income_by_year: tuple[float, ...]

    property_taxes_by_year: tuple[float, ...]
    insurance_by_year: tuple[float, ...]
    utilities_by_year: tuple[float, ...]
    repairs_maintenance_by_year: tuple[float, ...]
    other_operating_expenses_by_year: tuple[float, ...]
    management_fee_by_year: tuple[float, ...]

    total_operating_expenses_by_year: tuple[float, ...]
    noi_by_year: tuple[float, ...]

    exit_noi: float
    going_in_cap_rate: float
```

Every `_by_year` field above has length `hold_period` (Years 1..H only);
`exit_noi` is the single scalar Year `H+1` value. `going_in_cap_rate` is
folded in here (rather than left a separate return value) because it is
`noi_by_year[0] / purchase_price` — a NOI-derived quantity — matching
`NoiForecast`'s existing field.

**2.1.1 Quick Underwrite's projection is a degenerate `OperatingProjection`.**
Quick Underwrite does not need its own separate contract: given
`current_noi`/`noi_growth`, every revenue/expense schedule above except
`noi_by_year` and `exit_noi` is either undefined or trivially zero for a
summarized deal. Two options were considered:

- **(A) Reuse `OperatingProjection` for both paths**, with Quick Underwrite
  populating only `noi_by_year`/`exit_noi`/`going_in_cap_rate` and leaving
  every revenue/expense line-item field as an explicit sentinel (e.g. an
  empty tuple, distinct from "zero for every year") — rejected because it
  makes the contract's field meaning conditional on which mode produced it,
  which is exactly the ambiguity explicit dataclasses over dicts are meant
  to avoid, and it would force every downstream consumer of the line-item
  fields to branch on "is this populated."
- **(B) Keep `NoiForecast` as the minimal contract `analyze_acquisition`
  actually consumes downstream, and treat `OperatingProjection` as a
  strictly richer contract that Detailed Underwrite produces and Quick
  Underwrite does not** — **recommended.** `analyze_acquisition`'s downstream
  calls (capital stack, debt, exit value, cash flows, returns) already
  consume only three fields: `noi_by_year`, `exit_noi`, `going_in_cap_rate`.
  Both Quick's `NoiForecast` and Detailed's `OperatingProjection` can satisfy
  that same narrow shape (`OperatingProjection` is a strict superset of
  `NoiForecast`'s three fields), so the convergence point (Section 2.2) can
  accept either without needing to know which mode produced it. Detailed
  Underwrite's richer line-item schedule is additional information available
  for display (the "institutional operating statement" UI, Section 5) and
  for a future Detailed-specific golden-case/regression check — it is never
  required by the downstream acquisition/debt/returns engine itself.

Recommendation: **(B)**. Keep `NoiForecast` exactly as it is (Quick's output
shape, unchanged); add `OperatingProjection` as Detailed's output shape;
define the convergence function (2.2) to accept anything exposing
`noi_by_year`/`exit_noi`/`going_in_cap_rate` — in practice, either contract.

### 2.2 `AcquisitionTerms` — the shared acquisition/debt contract

The downstream acquisition/debt/returns calculation needs exactly two kinds
of input: an operating projection (Section 2.2.1) and the assumptions that
are **independent of how NOI was produced** — purchase economics, financing
structure, exit assumptions, and the hold period. These are identical
between Quick and Detailed by construction (both modes underwrite the same
transaction; only the operating build differs), so they belong on one
concrete, shared contract rather than being re-derived or duplicated per
mode:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionTerms:
    purchase_price: float
    hold_period: int
    exit_cap_rate: float
    ltv: float
    interest_rate: float
    amortization: int
    acquisition_cost_pct: float
    financing_fee_pct: float
    disposition_cost_pct: float
    annual_capex_reserve: float
    io_period: int
```

New frozen, `kw_only`, `slots` dataclass in `src/anchor/contracts.py`,
alongside `AcquisitionInputs`. Eleven fields — every existing
`AcquisitionInputs` field *except* `current_noi`, `occupancy`, and
`noi_growth`, which is exactly the three-field difference Section 4 below
resolves.

**Why a concrete dataclass, not only a `typing.Protocol`.** The Phase 0
architecture proposed a structural `Protocol` here; after inspection this is
upgraded to a concrete dataclass because `AcquisitionTerms` is not merely a
*read shape* two existing contracts happen to satisfy (that description does
fit `OperatingProjectionLike`, Section 2.2.1, since `NoiForecast` and
`OperatingProjection` are both genuinely pre-existing/independently-motivated
contracts) — it is a *new, real value* that must be independently
constructed for a Detailed deal, which has no `AcquisitionInputs` instance
supplying it implicitly. A concrete dataclass also gives Gate 5 persistence
(Section 6) something to store directly for a Detailed deal, and gives
`debt.py` (Section 2.2.2) a narrower, explicit parameter type instead of an
unnamed structural shape.

**Where `occupancy` belongs — inspected, not mechanically forced in.**
`occupancy` is excluded from `AcquisitionTerms`. Three findings from
inspection support this:

1. `occupancy` is not an acquisition/debt/exit assumption — it has never
   been read by `debt.py`, `acquisition.py`'s exit/cash-flow assembly, or
   `returns.py` (confirmed in Section 1.5/1.6/1.9 and the frozen
   `engine/noi.py` docstring: "Occupancy is informational only and is never
   read here"). Every field on `AcquisitionTerms` is read by
   `calculate_capital_stack`/`calculate_debt_schedule`
   (Section 2.2.2) or the exit-value/cash-flow functions in
   `acquisition.py`; `occupancy` would be the one field on the contract that
   no downstream calculation touches, breaking the contract's own
   "everything here is a shared, load-bearing acquisition/debt assumption"
   invariant.
2. Putting `occupancy` on the shared contract would make it visible, and
   therefore attach economic expectations to it, in Detailed mode — which is
   precisely the "second active vacancy mechanism" the Phase 0 brief (and
   this document's own "Occupancy and Vacancy — Resolved Relationship" in
   the conventions doc) already ruled out. Keeping it off the shared
   contract is a structural enforcement of that ruling, not just a
   docstring promise.
3. `occupancy` remains exactly where it already is: a field on
   `AcquisitionInputs` only, Quick-mode's own contract, informational,
   never read by any calculation, unchanged. A Detailed deal simply has no
   `occupancy` field today — see Section 4 and Gate 6 for whether a future,
   explicitly non-economic display field is worth adding to
   `DetailedOperatingInputs` later; V2.1 does not add one, since nothing in
   Section 3 of the financial-conventions document calls for it.

**2.2.1 `OperatingProjectionLike` — reconsidered and kept minimal.**
Re-examined during this update per the instruction to confirm it only
exposes what the downstream engine genuinely requires. `going_in_cap_rate`
is `noi_by_year[0] / purchase_price` in every existing case
(`NoiForecast.going_in_cap_rate` is literally `current_noi / purchase_price`,
and `current_noi == noi_by_year[0]` by the frozen `NOI_1 = current_noi`
convention) — so it is mathematically derivable from `noi_by_year[0]` and
`AcquisitionTerms.purchase_price` alone, and does not strictly need to be a
protocol field. It is kept anyway, for one concrete reason found during
inspection: both `NoiForecast` and `OperatingProjection` already declare it
as a first-class field (Section 2.1), and `AcquisitionResults.going_in_cap_rate`
already reads it directly off the forecast object today
(`acquisition.py`: `going_in_cap_rate=noi_forecast.going_in_cap_rate`) —
re-deriving it downstream instead would be a second, redundant computation
of the same value from the same inputs, which is exactly the kind of
duplication this whole proposal is designed to avoid. The protocol therefore
stays exactly as originally proposed:

```python
class OperatingProjectionLike(Protocol):
    noi_by_year: tuple[float, ...]
    exit_noi: float
    going_in_cap_rate: float
```

Confirmed minimal: **not** `noi_by_year`, `exit_noi`, and the eleven
Detailed-only line-item schedules — those never cross into
`analyze_acquisition_from_operating_projection` (Section 3.1), matching the
Phase 0 instruction "Do not make downstream calculations depend on detailed
operating line items."

**2.2.2 Downstream signature consequence.** `calculate_capital_stack` and
`calculate_debt_schedule` (`src/anchor/engine/debt.py`) currently take the
whole `inputs: AcquisitionInputs` but, per Section 1.5, read only the eleven
fields that are now exactly `AcquisitionTerms`' field set
(`purchase_price`, `ltv`, `acquisition_cost_pct`, `financing_fee_pct`,
`interest_rate`, `amortization`, `io_period`, `hold_period` — plus
`exit_cap_rate`/`disposition_cost_pct`/`annual_capex_reserve`, read by the
exit-value/cash-flow functions in `acquisition.py` rather than `debt.py`
itself, but from the same shared assumption set). Gate 1/3 retypes both
functions' parameter from `AcquisitionInputs` to `AcquisitionTerms` — a type
narrowing with no behavior change, since every field either function reads
already exists, under the identical name, on `AcquisitionTerms`. This is
what makes "Both: `AcquisitionTerms` + `OperatingProjectionLike` →
authoritative acquisition/debt/returns engine" true as a literal function
signature, not only as a conceptual diagram (Section 10).

**2.2.3 `acquisition_terms_from_inputs` — the Quick-side adapter.**

```python
def acquisition_terms_from_inputs(inputs: AcquisitionInputs) -> AcquisitionTerms:
    """Deterministic field projection, no validation of its own -- inputs
    is already a validated AcquisitionInputs, and every AcquisitionTerms
    field is copied verbatim from an identically-named AcquisitionInputs
    field. Never re-validates, never recomputes, never defaults a field
    AcquisitionInputs didn't already have a valid value for."""
    return AcquisitionTerms(
        purchase_price=inputs.purchase_price,
        hold_period=inputs.hold_period,
        exit_cap_rate=inputs.exit_cap_rate,
        ltv=inputs.ltv,
        interest_rate=inputs.interest_rate,
        amortization=inputs.amortization,
        acquisition_cost_pct=inputs.acquisition_cost_pct,
        financing_fee_pct=inputs.financing_fee_pct,
        disposition_cost_pct=inputs.disposition_cost_pct,
        annual_capex_reserve=inputs.annual_capex_reserve,
        io_period=inputs.io_period,
    )
```

Placed in `src/anchor/contracts.py` beside both dataclasses it bridges. This
is the **only** place the Quick path constructs an `AcquisitionTerms` — it
does not duplicate `validate_acquisition_inputs`' validation (Section
"Do not duplicate validation semantics" in Gate 1 below): `inputs` has
already been validated by the time this adapter runs, and every field is a
bare, no-op copy. A Detailed deal never calls this adapter; it constructs
`AcquisitionTerms` directly from its own validated fields (there is no
`AcquisitionInputs` instance in the Detailed path at all — see Section 4).

### 2.3 Detailed operating inputs

A new frozen, `kw_only`, `slots` dataclass, `src/anchor/contracts.py`
(alongside `AcquisitionInputs`, not merged into it — see Section 2.4 for
why):

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class DetailedOperatingInputs:
    gross_potential_rent: float
    other_income: float
    vacancy_credit_loss_pct: float
    property_taxes: float
    insurance: float
    utilities: float
    repairs_maintenance: float
    other_operating_expenses: float
    management_fee_pct: float
    revenue_growth: float
    expense_growth: float
```

(Eleven fields, not twelve — `management_fee_pct` was double-counted in the
Phase 0 brief's Section 3 "twelve" framing; the brief's own field list under
"Revenue"/"Operating expenses"/"Growth" enumerates exactly eleven distinct
identifiers. The golden-case document's Year 1 reconciliation uses all
eleven.)

### 2.4 Why separate contracts, not a merged 25-field `AcquisitionInputs`

Three reasons, in order of weight:

1. **Backward compatibility is structurally guaranteed, not just tested.** A
   nine-field or fourteen-field `AcquisitionInputs` construction must remain
   valid forever (Section "Quick Underwrite Compatibility" below). If the
   eleven detailed fields were added to `AcquisitionInputs` itself (even with
   neutral defaults), every existing saved deal, Excel workbook, and API
   payload would still work, but `AcquisitionInputs` would carry eleven
   fields that are meaningless for a Quick deal and would need their own
   defaults + docstring caveats explaining they're inert unless
   `operating_mode == DETAILED`. A separate, optional-and-absent-for-Quick
   contract keeps that conditionality structural rather than convention-based.
2. **Two of the detailed fields' names collide in spirit with existing V1
   fields at different semantics** (`vacancy_credit_loss_pct` vs. the
   existing informational `occupancy`; effectively `revenue_growth`/
   `expense_growth` vs. `noi_growth`). Keeping them on a separate contract
   makes "these are Detailed-only, and Quick's `noi_growth`/`occupancy` are
   untouched" a type-level fact, not a runtime convention enforced by
   validation logic alone.
3. **It matches the existing `Deal`/engine-contracts precedent exactly**:
   `Deal.inputs: AcquisitionInputs` nests one frozen contract inside another
   rather than flattening fields (Section 1.10); the same pattern extends
   naturally to a Detailed deal nesting `DetailedOperatingInputs` alongside
   `AcquisitionTerms` (Section 6) — not alongside a full `AcquisitionInputs`,
   which is the point Section 4 resolves.

The identical reasoning applies to `AcquisitionTerms` vs. flattening its
eleven fields onto some new Detailed-only mega-contract: `AcquisitionTerms`
is deliberately the *same* eleven fields for both modes (Section 2.2), never
duplicated or re-declared per mode, which is what makes the downstream
engine's signature mode-agnostic (Section 2.2.2).

### 2.5 Validation

`DetailedOperatingInputs` needs its own `validate_detailed_operating_inputs`
function, following `validate_acquisition_inputs`'s exact existing shape
(unknown-ID / missing-ID / domain-issue ordering, `InputIssue`/
`InputValidationError`, `_DOMAIN_DESCRIPTIONS`-style dict) rather than
extending `ALL_FIELD_IDS`/`validate_acquisition_inputs` itself — because the
eleven detailed fields are never optional-with-a-neutral-default the way the
five V2 fields are (there is no meaningful "neutral" `gross_potential_rent`);
they are either all present (Detailed mode) or all absent (Quick mode),
which is a different validation shape than "present or defaulted." A new,
sibling `DETAILED_FIELD_IDS` tuple and `IssueCategory` values (or shared
reuse of the existing `IssueCategory` enum, extended with detailed-specific
categories only if a genuinely new failure mode is found — e.g. none
identified today beyond the existing category shapes) follow the same
pattern.

`revenue_growth`/`expense_growth` validation: `> -1`, no upper bound — see
the financial-conventions document's "Growth Rate Validation" section for
the full rationale, mirroring `noi_growth`'s existing domain exactly.

## 3. Proposed Calculation Layers

New module: `src/anchor/engine/operating_projection.py`, sibling to
`noi.py`, `debt.py`, `returns.py`, `acquisition.py` — following this
package's existing one-module-per-calculation-stage convention.

```python
def build_quick_operating_projection(inputs: AcquisitionInputs) -> NoiForecast:
    """Exactly today's forecast_noi(inputs) — renamed at the call site
    for symmetry with build_detailed_operating_projection, not reimplemented.
    """

def build_detailed_operating_projection(
    detailed_inputs: DetailedOperatingInputs,
    *,
    hold_period: int,
    purchase_price: float,
) -> OperatingProjection:
    """New: computes every _by_year schedule in Section 2.1, through
    hold_period + 1 (Section "Projection Horizon"), then going_in_cap_rate
    from noi_by_year[0] / purchase_price.
    """
```

`build_quick_operating_projection` is not a new calculation — it is
`forecast_noi` under a name symmetric with its Detailed counterpart. The
recommendation is to **add this as an alias/thin wrapper in `noi.py`,
leaving `forecast_noi` itself and its call site in `acquisition.py`
unchanged**, so the rename does not itself become a source of behavioral
risk during Gate 3 (Section 11) — `forecast_noi` keeps working exactly as it
does today for any code that already calls it directly (e.g. existing
tests), while `build_quick_operating_projection` becomes the name
`analyze_acquisition_from_operating_projection`'s Quick-path caller uses.

`build_detailed_operating_projection` takes `hold_period` and
`purchase_price` as separate keyword arguments rather than the whole
`AcquisitionInputs`, mirroring `noi.py`'s existing style of narrow,
bare-keyword-argument calculation functions (`calculate_noi_by_year`,
`calculate_exit_noi`) rather than passing a full contract into a function
that only needs two of its fields. This also keeps `operating_projection.py`
free of any dependency on `AcquisitionInputs` beyond what it structurally
needs, matching `debt.py`'s/`returns.py`'s existing narrow-signature
convention.

### 3.1 `analyze_acquisition_from_operating_projection`

New function in `src/anchor/engine/acquisition.py`, extracted from the
existing body of `analyze_acquisition` with **zero formula changes** — a
pure refactor:

```python
def analyze_acquisition_from_operating_projection(
    operating_projection: OperatingProjectionLike,
    terms: AcquisitionTerms,
) -> AcquisitionResults:
    """Everything analyze_acquisition does today, from
    calculate_capital_stack(terms) onward, taking noi_by_year/exit_noi/
    going_in_cap_rate from operating_projection instead of computing them
    via forecast_noi(inputs) internally, and terms (not the whole
    AcquisitionInputs) for every acquisition/debt/exit assumption."""
    capital_stack = calculate_capital_stack(terms)
    debt_schedule = calculate_debt_schedule(terms)
    # ... exactly the existing body, reading operating_projection.noi_by_year /
    # .exit_noi / .going_in_cap_rate wherever it previously read noi_forecast.*,
    # and terms.* wherever it previously read inputs.* for a field
    # AcquisitionTerms carries (every field calculate_capital_stack/
    # calculate_debt_schedule/exit-value/cash-flow assembly ever reads --
    # Section 2.2.2).
    ...

def analyze_acquisition(inputs: AcquisitionInputs) -> AcquisitionResults:
    """Unchanged public behavior. Now: build_quick_operating_projection(inputs)
    + acquisition_terms_from_inputs(inputs), then
    analyze_acquisition_from_operating_projection(projection, terms)."""
    operating_projection = build_quick_operating_projection(inputs)
    terms = acquisition_terms_from_inputs(inputs)
    return analyze_acquisition_from_operating_projection(operating_projection, terms)

def analyze_detailed_acquisition(
    terms: AcquisitionTerms,
    detailed_inputs: DetailedOperatingInputs,
) -> AcquisitionResults:
    """The Detailed public entry point (Gate 3). No AcquisitionInputs
    instance is constructed, read, or required anywhere in this call --
    current_noi/noi_growth/occupancy simply do not exist in this path."""
    operating_projection = build_detailed_operating_projection(
        detailed_inputs, hold_period=terms.hold_period, purchase_price=terms.purchase_price
    )
    return analyze_acquisition_from_operating_projection(operating_projection, terms)
```

`terms: AcquisitionTerms` — not `inputs: AcquisitionInputs` — is what
`analyze_acquisition_from_operating_projection` now requires, resolving the
question the original Phase 0 proposal left open. This is the direct
consequence of Section 2.2.2's signature narrowing: `calculate_capital_stack`
and `calculate_debt_schedule` read only fields `AcquisitionTerms` already
carries, so nothing about the Detailed path ever needs an
`AcquisitionInputs` instance — not a real one, not a fabricated one, not one
with `current_noi`/`noi_growth` zeroed out. `analyze_acquisition` (Quick)
builds its `AcquisitionTerms` via the trivial `acquisition_terms_from_inputs`
adapter (Section 2.2.3); `analyze_detailed_acquisition` (Detailed) builds
`AcquisitionTerms` directly from its own already-validated fields. Both
converge on the exact same `analyze_acquisition_from_operating_projection`
call, which is oblivious to which path constructed its `terms` argument —
the whole point of the refactor is that the only thing that changes between
modes is *where `operating_projection` and `terms` come from*, never how
either is consumed downstream.

### 3.2 The Quick/Detailed convergence invariant, stated precisely

**`analyze_acquisition_from_operating_projection` is the single authoritative
downstream acquisition calculation path.** It is called exactly once by
`analyze_acquisition` (Quick) and exactly once by a future
`analyze_detailed_acquisition` (Detailed, Gate 3/5). Neither caller
duplicates any line of debt, exit-valuation, transaction-cost, CapEx, IRR,
equity-multiple, DSCR, sensitivity, or break-even logic — every one of those
calculations continues to live in exactly the files that own them today
(`debt.py`, `acquisition.py`'s existing exit/cash-flow functions,
`returns.py`, `analysis/sensitivity.py`, `analysis/break_even.py`), touched
by this proposal not at all.

## 4. Detailed-Mode Relationship to `current_noi` / `occupancy` / `noi_growth` — Resolved

**Resolution: a Detailed deal has no `AcquisitionInputs` instance, ever.**
`current_noi`, `noi_growth`, and `occupancy` are not populated, mirrored,
approximated, defaulted, or zeroed for a Detailed deal — they are simply
**absent**, because the Detailed path is built entirely from
`AcquisitionTerms` (Section 2.2) + `DetailedOperatingInputs` (Section 2.3),
neither of which has any of those three fields. This replaces the Phase 0
proposal's original "derive-and-mirror" recommendation (Section 12 below
records this as the closed migration risk it was).

- **Quick Underwrite (unchanged):** `AcquisitionInputs.current_noi`/
  `.noi_growth` are the direct, analyst-entered assumptions, exactly as
  today. `occupancy` remains informational-only, never read by any
  calculation — unchanged. `AcquisitionInputs` is still the one public,
  backward-compatible Quick contract; `analyze_acquisition(inputs)` derives
  `AcquisitionTerms` from it internally via `acquisition_terms_from_inputs`
  (Section 2.2.3) but this is invisible to every existing caller.
- **Detailed Underwrite:** the analyst never enters, and the system never
  stores or displays, a `current_noi` or `noi_growth` value for a Detailed
  deal. There is no field to leave blank, default, or reconcile — the
  concept does not exist in this path's type signature.
  `vacancy_credit_loss_pct` (`DetailedOperatingInputs`) is the sole active
  vacancy mechanism; `occupancy` has no equivalent field on the Detailed
  side at all (Section 2.2's "Where `occupancy` belongs" finding) — not
  because it was forced out mechanically, but because nothing in the
  Detailed calculation path (`build_detailed_operating_projection`,
  `analyze_acquisition_from_operating_projection`) ever needs it, and
  giving it a home there would recreate exactly the "second active vacancy
  mechanism" risk the brief warned against.
- **Historical reports/exports that need "the deal's NOI."** Any future
  consumer that wants a single headline NOI figure for a deal — regardless
  of which mode produced it — should read `OperatingProjection.noi_by_year[0]`
  (Detailed) or `NoiForecast.noi_by_year[0]` (Quick) at the point of use,
  never assume `AcquisitionInputs.current_noi` exists universally. Both
  already satisfy the shared `OperatingProjectionLike` shape (Section
  2.2.1), so a mode-agnostic consumer can be written against that
  protocol's `noi_by_year[0]` without branching on mode at all. This
  supersedes the Phase 0 proposal's "informational mirror on
  `AcquisitionInputs`" idea outright — there is no longer a Detailed
  `AcquisitionInputs` to mirror onto.

This resolution was possible only because of Section 2.2.2's signature
narrowing (`calculate_capital_stack`/`calculate_debt_schedule` retyped to
`AcquisitionTerms`) — without that narrowing, the Detailed path would still
need *something* shaped like `AcquisitionInputs` to satisfy those two
functions' old signatures, which is exactly what would have forced a fake or
derived `current_noi`/`noi_growth` value into existence. Narrowing the
signature removed the need for the value entirely, rather than finding a
less-bad way to manufacture it.

## 5. API Concept

No route is implemented today. Recommended shape for Gate 5:

- `POST /analyze` gains an optional `operating_mode` discriminator
  (`"quick"` default / `"detailed"`). The existing flat `inputs` payload
  (fourteen `AcquisitionInputs` fields) remains exactly as-is and is what a
  `"quick"`/absent `operating_mode` request sends — **additive, not
  breaking**. A `"detailed"` request sends `terms` (the eleven
  `AcquisitionTerms` fields — no `current_noi`/`noi_growth`/`occupancy` keys
  at all, matching Section 4's resolution) and
  `detailed_operating_inputs` (the eleven `DetailedOperatingInputs` fields)
  instead of `inputs`.
- When `operating_mode == "detailed"`, the route validates `terms` (a small
  `validate_acquisition_terms`, mirroring `validate_acquisition_inputs`'
  shape but over `AcquisitionTerms`' eleven fields) and
  `detailed_operating_inputs` via `validate_detailed_operating_inputs`,
  builds the projection via `build_detailed_operating_projection`, and calls
  `analyze_detailed_acquisition` (Section 3.1) instead of
  `analyze_acquisition`. Response shape (`AcquisitionResults`) is
  **unchanged** either way — the frontend does not need a second results
  type.
- Considered and rejected: a separate `/analyze/detailed` endpoint. Rejected
  because it would require the frontend (and any API consumer) to branch on
  which endpoint to call rather than on one payload field, and because
  `/sensitivity`, `/break-even`, `/ai/analysis` would each then need their
  own detailed variant too — multiplying the surface area for no benefit,
  since every one of those already takes one `inputs` object today and can
  take one discriminated union tomorrow.

## 6. Persistence Concept

**Status: implemented (Gate 5b), superseding the original single-table
proposal below.** During implementation, the originally-proposed "option
1" (widen `current_noi`/`noi_growth`/`occupancy` to nullable on the
existing `deals` table) turned out to require a full SQLite table rebuild
-- `ALTER TABLE` cannot relax an existing `NOT NULL` constraint, only add/
rename/drop columns. That is a materially different, riskier migration than
every other gate's purely additive `ALTER TABLE ADD COLUMN`. Resolved (user
direction) by splitting storage across two purely additive new tables
instead, leaving `deals` structurally untouched forever:

- `deals` (Quick) -- unchanged: same columns, same `NOT NULL` constraints,
  same rows, forever. Never gains a Detailed row.
- `detailed_deals` (new) -- the eleven `AcquisitionTerms` fields, one row
  per Detailed deal.
- `detailed_operating_inputs` (new) -- the eleven `DetailedOperatingInputs`
  fields, `deal_id` a 1:1 primary key referencing `detailed_deals.id`.

Both new tables are created via `CREATE TABLE IF NOT EXISTS`,
unconditionally, on every connection -- exactly like `deals` itself. No
`ALTER` of any existing column, ever. Schema version bumped `1 -> 2`; the
existing Underwriting V2 Gate 5 `ALTER TABLE ADD COLUMN` migration step is
untouched and still runs for a genuine pre-V2 database.

`Deal` (`deals/contracts.py`) is one domain-level abstraction with an
`operating_mode` field: a `QUICK` deal has `inputs` populated and `terms`/
`detailed_operating_inputs` both `None`; a `DETAILED` deal has `terms`/
`detailed_operating_inputs` populated and `inputs` `None` -- enforced by a
`__post_init__` invariant, never a fabricated `AcquisitionInputs`.
`create_deal`/`update_deal` keep their exact pre-Gate-5b signatures and
behavior (Quick-only); `create_detailed_deal`/`update_detailed_deal` are
their new Detailed counterparts; `get_deal`/`list_deals`/`delete_deal`/
`duplicate_deal` dispatch across both tables by id (ids are never shared
between the two tables), presenting the one unified domain interface.
`POST`/`PUT /deals` gained the same `operating_mode` discriminator as
`/analyze`.

See `src/anchor/deals/store.py`'s module docstring and
`tests/test_deals_store_detailed_v2_1.py` for the full implementation and
its regression coverage (existing-Quick-database migration safety, Quick
economics unchanged, Detailed-creates-no-Quick-row, exact round-trips for
both new contracts, cross-mode CRUD, restart, and migration idempotency).

### Original Phase 0 proposal (superseded, kept for history)

Extending the existing `deals` table (Section 1.10), following the exact
`PRAGMA user_version`-gated migration precedent already proven for
Underwriting V2 Gate 5:

- New column `operating_mode TEXT NOT NULL DEFAULT 'QUICK'` — every
  currently-saved deal naturally becomes `QUICK` on migration (matches its
  actual, unchanged assumptions; requires no data backfill logic beyond the
  column default itself, exactly like `_V2_MIGRATION_COLUMNS`' `DEFAULT
  0.0`/`DEFAULT 0` today).
- New nullable columns for the eleven `DetailedOperatingInputs` fields
  (`gross_potential_rent REAL`, ..., `expense_growth REAL`), `NULL` for
  every `QUICK` deal, populated only for `DETAILED` deals.
- **Persist assumptions, not calculated schedules** — `Deal` never gains a
  stored `OperatingProjection`, matching the existing, explicit
  `deals/contracts.py` principle ("A `Deal` never carries a stored
  `AcquisitionResults` ... the engine remains the sole authority for every
  derived number"). Reopening a Detailed deal means recomputing
  `build_detailed_operating_projection` from the stored
  `DetailedOperatingInputs`, exactly as reopening any deal today means
  recomputing `AcquisitionResults` from stored `AcquisitionInputs`.
- **Post-Section-4 resolution: a `DETAILED` row never populates
  `current_noi`/`noi_growth`/`occupancy` at all** — not even as a
  nullable/defaulted value. Two persistence shapes were considered:

  1. **Keep one `deals` table with one row shape**, where `current_noi`,
     `noi_growth`, and `occupancy` become `NULL`-able columns, `NULL` for
     every `DETAILED` row (and `NOT NULL` — unchanged — for `QUICK`), and
     the eleven `AcquisitionTerms` fields (already present as columns since
     Underwriting V2 Gate 1/5 — `purchase_price`, `hold_period`,
     `exit_cap_rate`, `ltv`, `interest_rate`, `amortization`,
     `acquisition_cost_pct`, `financing_fee_pct`, `disposition_cost_pct`,
     `annual_capex_reserve`, `io_period`) are simply shared, unconditionally
     populated columns for both modes. `Deal.inputs: AcquisitionInputs`
     becomes reconstructible only for `QUICK` rows; a `DETAILED` row's
     `_row_to_deal`-equivalent constructs `AcquisitionTerms` +
     `DetailedOperatingInputs` instead, never an `AcquisitionInputs` with
     null-turned-into-fake-zero fields.
  2. **Two `Deal` shapes** (`QuickDeal`/`DetailedDeal`, or one `Deal` with
     a `mode`-discriminated union field) with genuinely different schemas —
     rejected for Gate 5 as a larger migration/API-surface change than the
     resolution requires; option 1 already gets the "no fabricated
     current_noi/noi_growth" property without a schema split, by simply
     widening three existing `NOT NULL` columns to nullable and leaving
     every other column exactly as Underwriting V2 Gate 5 already defined
     it.

  **Recommended: option 1** — smallest change consistent with the
  `PRAGMA user_version` migration precedent (Section 1.10), and the schema
  a `DETAILED` row ends up with is simply "every `AcquisitionTerms` column
  populated, every Quick-only column (`current_noi`/`noi_growth`/
  `occupancy`) `NULL`, every `DetailedOperatingInputs` column populated" —
  no new table, no new join.
- No migration is implemented today. This is a design-only recommendation
  for Gate 5.

## 7. Excel / OM Concept

Not implemented today. Documented future behavior:

- **Excel:** the current fourteen-field `"Inputs"` sheet remains the Quick
  Underwrite workbook format, unchanged. A future Detailed workbook format
  is a **separate sheet or separate workbook template** (e.g. an
  `"Operating Model"` sheet alongside `"Inputs"`), read by a new
  `read_detailed_operating_inputs_*` function paralleling
  `read_acquisition_inputs_*`'s existing structure
  (`ExcelIntakeReport`-style report object) — not a fourteen-plus-eleven
  merged sheet, to keep the existing Quick workbook byte-for-byte compatible
  and independently testable. Analyst review remains required before either
  workbook's parsed values are loaded into a live deal — unchanged principle.
- **OM:** `ExtractionResult` gains an optional, additive
  `detailed_operating_candidates` block (mirroring `FieldCandidates`'
  existing per-field `stated`/`interpreted`/`conflicting`/`unverifiable`/
  `missing` evidence-status shape) once OM extraction is taught to look for
  revenue/expense line items — a future gate, not V2.1's initial scope. The
  core Anchor principle is unchanged and explicitly preserved: **Documents →
  Proposed Data → Analyst Approval → Deterministic Engine → Decision
  Support.** AI never calculates NOI itself when the deterministic Detailed
  model can — this is a direct extension of the existing frozen boundary
  documented in
  `docs/solutions/architecture-patterns/deterministic-engine-ai-grounding-boundary.md`
  and enforced today by `test_ai_architecture.py`'s AST-import guardrail; the
  same guardrail shape should cover the Detailed operating-projection module
  once it exists (no AI-package import ever reaches
  `engine/operating_projection.py`, and vice versa).

## 8. Frontend Concept

Not implemented today. Documented future concept, consistent with the
brief's Section 18:

- An "Underwriting Mode" toggle (`Quick Underwrite` / `Detailed Underwrite`)
  drives which form section renders and which `operating_mode` value the
  built `AcquisitionRequest`-equivalent payload carries.
- Quick keeps today's fourteen-field experience unchanged.
- Detailed renders the existing transaction/acquisition assumption fields
  (`purchase_price`, `hold_period`, `exit_cap_rate`, `ltv`, `interest_rate`,
  `amortization`, the four V2 cost/reserve/IO fields) plus a new "Operating
  Model" section for the eleven detailed fields — reusing the existing
  form-field components/validation-display patterns in `web/src/convert.ts`
  rather than introducing a new form framework.
- Detailed results add an institutional operating-statement view (GPR, Less:
  Vacancy & Credit Loss, Other Income, EGI, Operating Expenses, NOI, CapEx,
  Debt Service, Levered Cash Flow per year) sourced directly from
  `OperatingProjection`'s fields — no client-side recalculation, matching
  the existing, explicit frontend principle already stated in `types.ts`
  ("Every value here is engine-computed — the frontend never recalculates
  any of it").
- No rent-roll UI. Out of scope per Section 19 of the brief.

## 9. Sensitivity / Break-Even Implications

Not implemented today (no new sensitivity dimension). Documented behavior
once Detailed Underwrite exists:

**Principle (restated from the brief): a sensitivity or break-even candidate
must modify only the requested assumption while preserving the selected
operating model and every other assumption.** The existing
`dataclasses.replace(base, **changes)` pattern (Section 1.9) already
satisfies this for `AcquisitionInputs`-only fields and is the direct
precedent to extend, not replace, once a scenario can also carry Detailed
fields. Recommended shape for a future gate (not implemented today):

- Wrap `(AcquisitionInputs, DetailedOperatingInputs | None)` in one
  immutable top-level "deal" container — e.g. a
  `DetailedDeal`/`AcquisitionDeal` union or a single dataclass with an
  optional `detailed: DetailedOperatingInputs | None` field — and have
  every sensitivity/break-even scenario built via `dataclasses.replace` on
  *that* complete container, never on `AcquisitionInputs` alone once a
  Detailed field is the one being varied. This is the direct generalization
  of Gate 9A's fix (Section 1.9): the bug there was reconstructing an
  *incomplete* input contract from a hand-maintained field list; the fix was
  immutable replacement of the *complete* frozen contract. Extending the
  contract from one dataclass to a two-dataclass container changes nothing
  about which pattern avoids the bug — replace the whole thing, always,
  never reconstruct a subset.
- A sensitivity dimension varying a Detailed-only field (e.g. `revenue_growth`)
  would call `build_detailed_operating_projection` fresh for each scenario
  value, then `analyze_acquisition_from_operating_projection` — never
  `analyze_acquisition` (which only knows the Quick path) — mirroring
  exactly how today's sensitivity loop calls `analyze_acquisition` once per
  scenario.
- Revenue growth, vacancy, and expense growth as sensitivity dimensions are
  explicitly out of scope for V2.1's initial implementation, per the brief —
  documented here as a natural Gate 8 candidate, not scheduled.

## 10. Quick/Detailed Convergence Summary

```
QUICK UNDERWRITE                          DETAILED UNDERWRITE
AcquisitionInputs                         AcquisitionTerms (direct)
(current_noi, noi_growth,                 + 11 DetailedOperatingInputs
 occupancy, + 11 terms fields)
        |            \                            |
        |             \                           |
        v              v                          v
build_quick_        acquisition_terms_    build_detailed_operating_projection
operating_          from_inputs                   |
projection                |                        |
        |                 |                        |
        v                 v                        v
   NoiForecast      AcquisitionTerms        OperatingProjection
   (noi_by_year,    (11 shared fields,      (full line-item schedule +
    exit_noi,        no current_noi/         noi_by_year, exit_noi,
    going_in_cap_     noi_growth/             going_in_cap_rate)
    rate)             occupancy)                    |
        |                 |                         |
        +-----+     +-----+          +--------------+
              |     |                |
              v     v                v
     analyze_acquisition_    analyze_detailed_acquisition(terms,
     from_operating_          detailed_inputs)
     projection(projection, terms)          |
              |                             |
              +--------------+--------------+
                             |
                             v
          analyze_acquisition_from_operating_projection
           (operating_projection: OperatingProjectionLike,
            terms: AcquisitionTerms)
                             |
                             v
                    AcquisitionResults
       (one contract, one calculation path, unchanged --
        no current_noi/noi_growth/occupancy anywhere in the
        Detailed half of this diagram)
```

`analyze_acquisition` (Quick) and `analyze_detailed_acquisition` (Detailed)
are both thin, mode-specific *builders* of `(operating_projection, terms)`;
neither performs any acquisition/debt/returns calculation itself, and both
call the identical `analyze_acquisition_from_operating_projection` exactly
once. This is the literal, signature-level form of the brief's "only one
downstream acquisition calculation path" requirement — not just a shared
formula, but a shared function neither mode duplicates or wraps redundantly.

## 11. Implementation Sequence

Improved from the brief's suggested eight-gate shape after inspection —
Gate 3 is split from Gate 2 to isolate the pure-refactor step (extracting
`analyze_acquisition_from_operating_projection` with zero formula change)
from the new-calculation step, since a refactor-only gate can be verified by
"identical output, different call path" while a new-calculation gate needs
new golden-case coverage; keeping them separate makes each gate's
regression obligation unambiguous.

### Gate 1 — Operating contracts + validation

- **Scope:** `AcquisitionTerms` dataclass + `acquisition_terms_from_inputs`
  adapter (Section 2.2/2.2.3); `DetailedOperatingInputs` dataclass;
  `OperatingProjection` dataclass; `OperatingProjectionLike` protocol;
  `validate_detailed_operating_inputs`; growth-rate domain rule (`> -1`)
  implemented per the conventions document. `AcquisitionTerms` itself needs
  no new validation function of its own at Gate 1 (see "Do not duplicate
  validation semantics" below) beyond what Gate 5's future
  `validate_acquisition_terms` will add once a Detailed deal can be
  constructed independently of `AcquisitionInputs` via the API.
- **Do not duplicate validation semantics:** `acquisition_terms_from_inputs`
  performs no validation (Section 2.2.3) — it only runs on an
  already-validated `AcquisitionInputs`. Every domain rule for the eleven
  `AcquisitionTerms` fields already exists in
  `validate_acquisition_inputs`/`_DOMAIN_DESCRIPTIONS`
  (`src/anchor/validation.py`) under the same field names; Gate 1 does not
  re-declare or duplicate those rules for `AcquisitionTerms` — a Quick
  deal's terms are validated exactly once, when its `AcquisitionInputs` is
  validated. A standalone `validate_acquisition_terms` (needed once the
  Detailed API path can submit `terms` directly, Gate 5) should reuse the
  same domain-description dict/logic rather than re-authoring it — flagged
  here so Gate 5 does not reintroduce a second, drifting copy of these
  eleven rules.
- **Acceptance criteria:** every field/domain in
  `docs/detailed_operating_model_v2_1_financial_conventions.md` has a
  corresponding validation rule; unit tests for each domain boundary
  (mirroring `test_validation.py`'s existing per-field boundary-test shape);
  `acquisition_terms_from_inputs(inputs)` produces an `AcquisitionTerms`
  whose eleven fields match `inputs`' corresponding fields exactly, for
  every existing golden-case/test input.
- **Required regression tests:** none of the existing suite should change
  behavior — a new `test_validation_detailed.py`-style file, plus
  `test_contracts.py`-adjacent tests for `AcquisitionTerms`
  immutability/field set and the adapter's field-by-field correctness.
- **Explicit exclusions:** no calculation logic yet; no engine wiring (the
  `debt.py` signature narrowing from Section 2.2.2 is Gate 3's change, not
  Gate 1's — Gate 1 only adds the new contracts, it does not yet retype any
  existing function).

### Gate 2 — Detailed operating schedule calculations

- **Scope:** `build_detailed_operating_projection` in
  `engine/operating_projection.py`, implementing every formula in the
  conventions document.
- **Acceptance criteria:** the golden-case document's Years 1–6 table
  reproduced exactly, at `pytest.approx(expected, rel=0.0, abs=1e-9)`.
- **Required regression tests:** new `test_engine_operating_projection.py`
  (unit-level, one test per formula/edge case) plus a golden-case test
  sourced directly from
  `docs/detailed_operating_model_v2_1_golden_case.md`, following the
  existing spec-sourced golden-case pattern
  (`docs/solutions/conventions/testing-conventions-and-architecture-guardrails.md`
  item 4).
- **Explicit exclusions:** `build_detailed_operating_projection` is not yet
  wired into `analyze_acquisition`-adjacent orchestration; no API/
  persistence/frontend change.

### Gate 3 — Quick/Detailed convergence into one acquisition path

- **Scope:**
  1. Retype `calculate_capital_stack`/`calculate_debt_schedule`
     (`src/anchor/engine/debt.py`) from `inputs: AcquisitionInputs` to
     `terms: AcquisitionTerms` (Section 2.2.2) — every field either
     function reads already exists under the same name on
     `AcquisitionTerms`, so this is a type narrowing with zero formula
     change.
  2. Extract `analyze_acquisition_from_operating_projection(operating_projection,
     terms)` from `analyze_acquisition`'s existing body (pure refactor,
     zero formula change beyond the (1) narrowing already makes necessary).
  3. Add `build_quick_operating_projection` as `forecast_noi`'s
     Detailed-symmetric name (thin wrapper, `noi.py` unchanged).
  4. Add `acquisition_terms_from_inputs` (Section 2.2.3, contract added at
     Gate 1; wired into `analyze_acquisition`'s body here).
  5. Add `analyze_detailed_acquisition(terms, detailed_inputs) ->
     AcquisitionResults` composing `build_detailed_operating_projection` +
     `analyze_acquisition_from_operating_projection` — no
     `AcquisitionInputs` constructed anywhere in this function (Section 4).
- **Acceptance criteria:** `analyze_acquisition`'s output is bit-for-bit
  unchanged for every existing test input (proves the refactor introduced
  no behavior change); `analyze_detailed_acquisition` exists and is callable
  end-to-end for the golden case (output not yet asserted against the V2
  golden case — that is Gate 4); `analyze_detailed_acquisition`'s signature
  contains no `AcquisitionInputs`/`current_noi`/`noi_growth`/`occupancy`
  parameter, checked by an explicit test (e.g. `inspect.signature`
  assertion) so this invariant cannot silently regress in a later gate.
- **Required regression tests:** full existing suite must pass unchanged
  (this is the refactor-safety gate, covering the `debt.py` retyping too);
  a new `test_engine_analyze_acquisition.py`-adjacent test asserting
  `analyze_acquisition(inputs)` and
  `analyze_acquisition_from_operating_projection(build_quick_operating_projection(inputs),
  acquisition_terms_from_inputs(inputs))` produce identical
  `AcquisitionResults` for a range of inputs (the refactor's own delegation
  proof, in the existing `wraps=`-assertion style where applicable).
- **Explicit exclusions:** no API/persistence/frontend change; no
  cross-model equivalence test yet (Gate 4).

### Gate 4 — Golden-case bridge + complete regression

- **Scope:** implement the three invariants named in
  `docs/detailed_operating_model_v2_1_golden_case.md` "Exact Invariants to
  Become Implementation Tests" as actual pytest tests.
- **Acceptance criteria:** all three invariants pass, including the
  cross-model equivalence test (Quick golden case vs. Detailed bridge case,
  same downstream `AcquisitionResults`, floating-point-noise tolerance
  only).
- **Required regression tests:** the new `test_detailed_v2_1_golden_case.py`
  (or equivalent name) becomes a **permanent** regression file, run in the
  full suite going forward — matching the brief's own instruction ("This
  should eventually become a permanent cross-model equivalence test").
- **Explicit exclusions:** no API/persistence/frontend change yet.

### Gate 5 — API and persistence

- **Scope:** Section 5 (`operating_mode` discriminator on `/analyze` and
  the sensitivity/break-even/AI-analysis routes) and Section 6 (`deals`
  table migration, `Deal.detailed_operating_inputs`).
- **Acceptance criteria:** an existing nine/fourteen-field `/analyze`
  payload with no `operating_mode` key is unaffected (regression); a new
  `operating_mode: "detailed"` payload round-trips through
  `analyze_detailed_acquisition`; a pre-Gate-5 SQLite database migrates
  forward with every existing deal defaulting to `QUICK`
  (`test_deals_store_v2_migration.py`-style migration test, extended).
- **Required regression tests:** full existing `test_api*.py` and
  `test_deals*.py` suites unchanged; new `test_api_detailed_analyze.py`,
  `test_deals_detailed_migration.py`-style additions.
- **Explicit exclusions:** no frontend change; no Excel/OM change.

### Gate 6 — Frontend Quick/Detailed mode

- **Scope:** Section 8's UI concept — mode toggle, Operating Model form
  section, institutional operating-statement results view.
- **Acceptance criteria:** Quick mode's existing behavior/tests
  (`web/src/App.test.tsx` etc.) unchanged; new Detailed-mode component
  tests parallel to `SensitivityPanel.test.tsx`/`BreakEvenPanel.test.tsx`'s
  existing shape.
- **Required regression tests:** existing frontend test suite unchanged;
  new tests for the added components.
- **Explicit exclusions:** no rent-roll UI (permanent exclusion, not just
  this gate's).

### Gate 7 — Excel / OM integration, if approved

- **Scope:** Section 7's Excel Detailed workbook format and OM
  `detailed_operating_candidates` extraction, each independently approvable
  (this gate may split into 7a/7b).
- **Acceptance criteria:** existing fourteen-field Excel workbook and
  existing `ExtractionResult` shape both unaffected; new detailed
  ingestion paths tested to the same `ExcelIntakeReport`-style /
  provenance-status-style rigor as their Quick/V1 counterparts.
- **Required regression tests:** full existing `test_excel_reader.py`,
  `test_ingestion_*.py` suites unchanged; new detailed-ingestion test files
  following the same AST-import-boundary + delegation + live-smoke-test
  shapes documented in
  `docs/solutions/architecture-patterns/om-ingestion-provenance-and-analyst-approval-gate.md`.
- **Explicit exclusions:** no reimbursement/recovery modeling (permanent
  exclusion).

### Gate 8 — Sensitivity / break-even extensions, if approved

- **Scope:** Section 9's Detailed-aware scenario container
  (`dataclasses.replace` on the complete top-level deal contract); new
  sensitivity dimensions (`revenue_growth`, `vacancy_credit_loss_pct`,
  `expense_growth`) if approved at that time.
- **Acceptance criteria:** existing Quick-only sensitivity/break-even
  behavior and presets unchanged; new Detailed dimensions follow the
  existing `SUPPORTED_ASSUMPTIONS`/`_METRIC_EXTRACTORS` extension pattern
  with no duplicated formula.
- **Required regression tests:** `test_analysis_v2_reconciliation.py`-style
  reconciliation test extended to prove a Detailed scenario never silently
  drops back to a Quick-neutral default (the direct generalization of the
  Gate 9A regression).
- **Explicit exclusions:** none named beyond what Section 9 already scopes
  out (not scheduled without separate approval).

## 12. Identified Migration Risks

1. **RESOLVED (was open in the original Phase 0 proposal).**
   `current_noi`/`noi_growth` mirroring on a Detailed deal is no longer a
   design question: Section 4 resolves it by removing the need for any
   `AcquisitionInputs` instance in the Detailed path at all, via the
   `AcquisitionTerms` signature narrowing (Section 2.2.2). No mirrored,
   derived, or defaulted `current_noi`/`noi_growth` value is ever
   constructed. A consumer that wants "the deal's NOI" regardless of mode
   reads `OperatingProjectionLike.noi_by_year[0]` instead (Section 4).
2. **RESOLVED.** The persistence-layer form of the same question (Section
   6) is closed the same way: a `DETAILED` `deals` row leaves
   `current_noi`/`noi_growth`/`occupancy` `NULL` rather than populating them
   with any value, matching Section 4 exactly at the storage layer too
   (Section 6, "option 1").
3. **Frontend type-mirroring drift.** `web/src/types.ts` mirrors Python
   contracts by convention, not codegen (Section 1.14). Adding
   `DetailedOperatingInputs`/`OperatingProjection` doubles the number of
   hand-mirrored contracts; a documentation comment discipline (already
   present for every existing type in `types.ts`) should be treated as a
   Gate 5/6 acceptance-criterion, not left implicit.
4. **Excel workbook format proliferation** (Section 7) — a second workbook
   format increases the ingestion surface the existing
   AST-import-boundary/architecture guardrail tests need to cover; Gate 7
   should extend those guardrail tests on the same PR that introduces the
   new format, per the existing convention
   (`docs/solutions/conventions/testing-conventions-and-architecture-guardrails.md`:
   "add its own `test_<layer>_architecture.py` ... on the same PR that
   introduces the layer, not as a follow-up").
5. **No architectural conflict with a frozen V2 financial convention was
   found during this inspection.** Every downstream calculation (debt, exit
   value, cash flows, DSCR, IRR, equity multiple) is confirmed to depend
   only on `noi_by_year`/`exit_noi`/`going_in_cap_rate` plus fields already
   on `AcquisitionInputs` — nothing in Underwriting V2's frozen conventions
   needs to change, relax, or be reinterpreted to support Detailed
   Underwrite.

## 13. Future Extensibility — Abstraction Boundary

The property-level → lease-level evolution path (Section 20 of the brief)
should sit **entirely inside `OperatingProjection`'s producer side** — i.e.
a future lease-level model replaces or extends
`build_detailed_operating_projection` (and, if the line-item schedule needs
new fields such as reimbursements, extends `OperatingProjection` itself
additively), while `analyze_acquisition_from_operating_projection` and
everything downstream of it (debt, exit valuation, transaction costs, CapEx,
returns, sensitivity, break-even) needs no change at all, because it already
depends only on the narrow `OperatingProjectionLike` shape
(`noi_by_year`/`exit_noi`/`going_in_cap_rate`), never on how those three
values were derived. This is the same seam this proposal already uses to
keep Quick and Detailed converged (Section 3.2) — a future lease-level model
is a third producer of the same shape, not a third acquisition engine.

A future Development Engine (referenced in the brief) should follow the
identical pattern: it produces its own operating projection (pre-stabilization
ramp, construction-period NOI, etc.) satisfying the same
`OperatingProjectionLike` shape, and converges into the identical downstream
path — never a fourth acquisition/debt/returns engine.

## 14. Explicit Non-Goals (V2.1)

Restated from the financial-conventions document's "Explicit V2.1
Exclusions" at the architecture level: no rent-roll data model, no
lease/tenant entities, no reimbursement/recovery calculation engine, no
waterfall/preferred-equity capital-stack modeling, no multi-tranche/
variable-rate/refinancing debt modeling, no development/construction
phasing, no tax/depreciation modeling, no portfolio-level aggregation. None
of these require a different abstraction boundary than the one proposed
here — Section 13 shows the boundary already accommodates their eventual
addition as new producers of the same `OperatingProjection` shape — but
none are implemented, scaffolded, or stubbed in this Phase 0 proposal.
