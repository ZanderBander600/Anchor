---
title: Lease-Level Underwriting - D0 Architecture and Financial Conventions
type: feat
date: 2026-09-04
topic: lease-level-underwriting
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: docs-only
sprint: D
gate: D0
baseline_commit: fffdf34
---

# Lease-Level Underwriting — D0 Architecture and Financial Conventions

## Status

**Planning / architecture gate only. No production code, no engine change, no
contract change, no migration, and no test change was produced by this gate.**

Verified baseline at the time of writing (`main` @ `fffdf34`, re-run locally):

- Backend: `1773 passed` (`pytest`, 35.79s).
- Frontend: `711 passed` (`npm test -- --run` in `web/`, 25 files).
- Financial golden case: zero drift.

This document inherits and extends, and revises nothing in:

- `docs/financial_conventions.md` (POC V1)
- `docs/underwriting_v2_financial_conventions.md` (Underwriting V2)
- `docs/detailed_operating_model_v2_1_financial_conventions.md` (Detailed V2.1)
- `docs/detailed_operating_model_v2_1_architecture.md` (Detailed V2.1 architecture)
- `docs/owner_return_metrics_v3_financial_conventions.md` (Owner Return Metrics V3)

Where this document is silent, those documents govern. Nothing in Quick or
Detailed Underwrite is changed, relaxed, or reinterpreted here.

---

## 1. Executive Summary

### 1.1 What Sprint D is building

A third underwriting depth — **Lease-Level** — deriving property operating cash
flow from individual suites and leases (contractual rent, escalations,
expiration, rollover, downtime, TI, LC, free rent, recoveries) rather than from
a single NOI figure (Quick) or a property-level revenue/expense build
(Detailed).

### 1.2 The five findings that matter most

1. **Lease-Level is a third producer of an operating projection, not a third
   acquisition engine.** `analyze_acquisition_from_operating_projection`
   (`src/anchor/engine/acquisition.py:243`) already accepts anything satisfying
   the three-field `OperatingProjectionLike` protocol. A Lease-Level projection
   satisfies it. Debt, exit valuation, transaction costs, CapEx, IRR, equity
   multiple, DSCR, and owner return metrics need **no formula change**.

2. **One additive downstream extension is unavoidable: a below-NOI
   leasing-cost channel.** TI and LC are capital costs below NOI. Today the
   *only* below-NOI operating-period channel is `capex_by_year`, produced from
   the constant `terms.annual_capex_reserve`. TI/LC vary by year and are
   produced by the lease engine, not by `AcquisitionTerms`. They require a new
   `leasing_costs_by_year` series threaded into exactly four existing
   consumers. This is the single engine-boundary change D0 requires, and it is
   the subject of Human Decision **HD-1**.

3. **Internal time granularity must be monthly; every published output stays
   annual.** The engine is calendar-date-free today (`datetime` appears nowhere
   under `src/anchor/engine/`; only `deals/` uses it, for row timestamps).
   Lease-Level introduces calendar dates at the *contract* boundary only, and
   normalizes them once, deterministically, into integer month indices relative
   to an explicit `analysis_start_date`. Every calculator then operates on
   integer month indices and floats — never on `date` arithmetic.

4. **Debt does not change.** `calculate_annual_debt_service`
   (`src/anchor/engine/debt.py:294`) already runs a chronological monthly loop
   and aggregates to annual, deliberately refusing the `12 * PMT` shortcut.
   Anchor's debt engine is *already* monthly-internal with annual outputs —
   exactly the shape the lease engine will adopt. Annual DSCR remains
   `NOI_y / ADS_y` and remains valid.

5. **Exit NOI is the next twelve months of lease-level NOI after the sale
   date** — months `12H+1 .. 12H+12`. This is not a new convention: it is the
   literal monthly restatement of Anchor's existing frozen rule
   (`docs/financial_conventions.md`: "Exit Value uses next-twelve-month forward
   NOI after the final hold year"). It requires the lease engine to project
   `12H + 12` months and to run rollover through that whole window.

### 1.3 Headline convention recommendations

| Area | Recommendation |
|---|---|
| Time granularity | Monthly internal, annual published (Section 5) |
| Month semantics | Whole-month rent recognition; any overlap pays a full month (Section 5.4) |
| Domain model | Property → Suite → Lease; tenant is a lease attribute, not an entity (Section 4) |
| Market rent | Property default + suite override; annual growth on analysis anniversaries (Section 7) |
| Rollover | Weighted-assumption **single** successor lease (ARGUS-style); `p=1`/`p=0` give pure paths (Section 8) |
| Downtime | Whole vacant months + one fractional boundary-month revenue factor (Section 9) |
| Free rent | Months of abated **base rent only**; above NOI; recoveries stay payable (Section 10) |
| TI | `$/SF` of leased area, paid in full at successor rent commencement, below NOI (Section 11) |
| LC | `%` of total contractual base rent over the successor term, gross of free rent, below NOI (Section 12) |
| Operating expenses | New `LeaseLevelOperatingInputs` composing Detailed's six expense concepts; **not** a reuse of `DetailedOperatingInputs` (Section 13) |
| Vacancy | No general vacancy factor. Physical vacancy is modeled explicitly. Optional `credit_loss_pct` on lease revenue, default `0.0` (Section 15) |
| Exit NOI | NTM lease-level NOI, months `12H+1..12H+12`, rollover live in that window (Section 17) |

### 1.4 Classification

**B — D0 COMPLETE WITH UNRESOLVED DECISIONS.** Eight human decisions
(**HD-1 … HD-8**, Section 30) require product/CRE judgment. Two of them
(**HD-1**, **HD-3**) block D1 directly; the rest block D2 or later. No STOP
CONDITION from the brief was triggered — see Section 30.10.

---

## 2. Repository Reconnaissance

Everything in this section was verified by reading the named files at
`fffdf34`.

### 2.1 Where Quick produces operating economics

`src/anchor/engine/noi.py`.

- `calculate_noi_by_year` — `NOI_1 = current_noi`;
  `NOI_y = current_noi * (1 + noi_growth)^(y-1)`.
- `calculate_exit_noi` — `current_noi * (1 + noi_growth)^H`, i.e. `NOI_(H+1)`.
- `calculate_going_in_cap_rate` — `current_noi / purchase_price`.
- `forecast_noi(inputs) -> NoiForecast`, wrapped by
  `build_quick_operating_projection(inputs) -> NoiForecast`.

`NoiForecast` (`src/anchor/engine/contracts.py:44`) has exactly three fields:
`noi_by_year`, `exit_noi`, `going_in_cap_rate`.

`occupancy` is read by nothing. `engine/noi.py`'s module docstring states this
as a frozen convention.

### 2.2 Where Detailed produces operating economics

`src/anchor/engine/operating_projection.py` —
`build_detailed_operating_projection(detailed_inputs, *, hold_period, purchase_price) -> OperatingProjection`.

It projects `hold_period + 1` years through the *full* line-item build (GPR,
other income, vacancy, five fixed expense lines, management fee), takes
`noi_by_year = NOI_1..NOI_H` and `exit_noi = NOI_(H+1)`, and explicitly forbids
approximating `exit_noi` by blending a growth rate onto `NOI_H`.

`OperatingProjection` (`src/anchor/engine/contracts.py:78`) carries twelve
`_by_year` line-item schedules plus the same three `OperatingProjectionLike`
fields.

### 2.3 Where the two converge

`analyze_acquisition_from_operating_projection(operating_projection: OperatingProjectionLike, terms: AcquisitionTerms) -> AcquisitionResults`
(`src/anchor/engine/acquisition.py:243`).

Both `analyze_acquisition` (Quick) and
`analyze_detailed_acquisition_with_projection` (Detailed) are thin builders of
`(operating_projection, terms)` and call this one function exactly once.
`tests/test_detailed_v2_1_gate3_convergence.py` proves this with
`patch(..., wraps=...)` call-count assertions.

### 2.4 What downstream contract a lease engine must satisfy

`OperatingProjectionLike` (`src/anchor/engine/contracts.py:47`) — a `Protocol`
with exactly:

```python
noi_by_year: tuple[float, ...]   # length H
exit_noi: float                  # scalar, Year H+1, never a member of noi_by_year
going_in_cap_rate: float
```

Structural typing — a new Lease-Level projection dataclass satisfies it simply
by declaring these three fields, with no inheritance and no registration.

### 2.5 Are current annual representations sufficient downstream?

**For revenue and NOI: yes.** Every downstream consumer reads only
`noi_by_year` / `exit_noi` / `going_in_cap_rate`.

**For capital costs: no.** Verified by reading every consumer of a below-NOI
series:

| Consumer | File:line | Reads |
|---|---|---|
| `calculate_unlevered_cash_flows` | `engine/acquisition.py:91` | `capex_by_year` |
| `calculate_levered_cash_flows` | `engine/acquisition.py:137` | `capex_by_year` |
| `calculate_recurring_levered_cash_flows` | `engine/returns.py:289` | `capex_by_year` |
| `calculate_recurring_unlevered_cash_flows` | `engine/returns.py:314` | `capex_by_year` |

`capex_by_year` itself is produced by `calculate_capex_by_year`
(`engine/acquisition.py:59`) as a **constant** `annual_capex_reserve` repeated
`H` times, derived from `AcquisitionTerms` — not from the operating projection.
There is today **no channel through which an operating-projection producer can
emit a below-NOI, year-varying cost.** TI and LC are exactly such a cost.

This is finding **F-1**, the one real architectural gap.

### 2.6 Which new contracts must exist

1. `LeaseLevelOperatingProjection` — satisfies `OperatingProjectionLike`, adds
   monthly and annual lease-level line items **and**
   `tenant_improvements_by_year` / `leasing_commissions_by_year`.
2. `LeaseLevelAcquisitionResults` — envelope mirroring
   `DetailedAcquisitionResults` (`engine/contracts.py:255`), pairing the
   projection with the unchanged `AcquisitionResults`.
3. The lease / suite / market-leasing input contracts (Section 4).
4. `LeaseLevelOperatingInputs` — expense, other-income and credit-loss
   assumptions (Section 13).

### 2.7 Which existing contracts stay untouched

`AcquisitionInputs`, `AcquisitionTerms`, `DetailedOperatingInputs`,
`NoiForecast`, `OperatingProjection`, `OperatingProjectionLike`, `CapitalStack`,
`DebtSchedule`, `AcquisitionCashFlows`, `ReturnMetrics`, `OwnerReturnMetrics`,
`DetailedAcquisitionResults`, every `anchor.analysis` contract, and every
`anchor.ai` contract.

`AcquisitionResults` is the sole exception — see F-1 / **HD-1**.

### 2.8 Does any architecture assume annual-only operating cash flow?

**Only at the published-output boundary, never structurally.**

- `AcquisitionResults` exposes only `_by_year` tuples of length `H` (plus
  `_cash_flows` of length `H+1`).
- The IRR solver (`engine/returns.py:231`) is explicitly an **annual periodic**
  IRR over a length-`H+1` series and would be silently wrong if handed monthly
  flows. It must never receive monthly data.
- `calculate_annual_debt_service` (`engine/debt.py:294`) already runs monthly
  internally and aggregates chronologically. **Anchor already has a
  monthly-internal / annual-output precedent in its most numerically
  conservative module.** The lease engine should mirror it exactly.

### 2.9 Do acquisition / debt / returns depend on NOI rather than broader cash flow?

Yes, and this is correct and must be preserved:

- Exit value: `exit_noi / exit_cap_rate` — NOI only.
- DSCR: `NOI_y / ADS_y` — NOI before capital reserves, per
  `docs/underwriting_v2_financial_conventions.md` ("Standard lender covenant
  practice computes DSCR on NOI before capital reserves").
- Year 1 Debt Yield: `NOI_1 / loan_amount` — NOI only.
- Cash flows and owner return metrics: NOI **less** `capex_by_year`.

So NOI-based metrics stay NOI-based; only the cash-flow-based metrics need the
new leasing-cost channel. This is exactly the split `capex_by_year` already
established, which is why extending it is the low-risk path.

### 2.10 Where lease-level capital costs can live without corrupting NOI

In a **new** `leasing_costs_by_year` series alongside `capex_by_year` — never
inside it, and never inside `total_operating_expenses_by_year`. Anchor's
below-NOI list is stated explicitly in
`docs/detailed_operating_model_v2_1_financial_conventions.md` ("NOI
Convention"): `annual_capex_reserve`, debt service, financing fees, acquisition
costs, disposition costs. TI and LC join that list.

**Why a separate series rather than folding TI/LC into `capex_by_year`:** the
two are economically distinct (a recurring physical-plant reserve vs. a
lease-triggered leasing commitment); an analyst must see them separately to
defend the underwriting; and `capex_by_year`'s current invariant — a constant
`annual_capex_reserve` in every year — is asserted by existing tests
(`tests/test_underwriting_v2_gate3_capex.py`) and should stay true.

### 2.11 Persistence

`src/anchor/deals/store.py` — SQLite, `_SCHEMA_VERSION = 4`, **two** tables
(`deals` for Quick, `detailed_deals` for Detailed), an idempotent `_migrate()`
driven by `PRAGMA table_info` rather than `user_version` alone, and JSON
snapshot columns each paired with a `..._schema_version` and a
`..._fingerprint`. `_ANALYSIS_SNAPSHOT_SCHEMA_VERSION = 1`.

`Deal.__post_init__` (`deals/contracts.py:104`) enforces the mode invariant: a
`QUICK` deal has `inputs` and no `terms`; a `DETAILED` deal has `terms` +
`detailed_operating_inputs` and no `inputs`. A third mode extends this same
pattern.

`anchor.deals` never imports an `anchor.engine` *calculation* module — only
result *shapes*. A guardrail test (`tests/test_deals_architecture.py`) enforces
this.

### 2.12 Excel ingestion

Both readers (`excel_reader.py`, `detailed_excel_reader.py`) parse a single
`Inputs` worksheet as a **key/value** table with headers
`("Field ID", "Input", "Value", "Unit")`, one row per scalar field, duplicates
rejected. `workbook_schema.py` reads an optional `Meta` sheet declaring
`anchor_schema` ∈ {`quick_acquisition`, `detailed_acquisition`} and
`schema_version` (`SUPPORTED_DETAILED_SCHEMA_VERSION = "2.1"`).

**A rent roll is a repeating row-per-lease table, not a key/value table.** No
existing reader shape accommodates it. This is finding **F-2**.

### 2.13 OM ingestion

`src/anchor/ingestion/contracts.py`. `ExtractionResult` (9 fields) and
`DetailedExtractionResult` (22 fields) are both **flat, fixed-arity** records:
one named `FieldCandidates` per scalar field. `EvidenceStatus` is exactly five
states. `Provenance` is `(page, anchor, snippet)`, verified against real
`DocumentAnchor`s.

A rent roll is **variable-arity**: N leases × M fields. The candidate model must
gain a repeating-group shape. This is finding **F-3**.

### 2.14 Frontend

`web/src/underwrite.ts` defines five Underwrite tabs
(`acquisition | operations | debt | exit | results`) and a `ResultsViewId`
sub-navigation that is already **mode-derived** (`resultsViewsFor(mode)` adds
`operating-statement` only for Detailed). `FieldSection.view` supports per-tab
sub-navigation. `UnderwriteWorkspace.tsx` keeps every tab mounted-but-`hidden`
so unsaved input survives a tab switch.

Quick and Detailed already keep **completely independent state** while sharing
one component tree. A third mode fits this seam without restructuring.

`web/src/workspaces.ts` locks five workspaces; Sprint C's
navigation-over-scrolling philosophy is explicit in
`docs/workspace_ux_visual_system_v3_spec.md`.

### 2.15 Validation

`src/anchor/validation.py`. Deterministic, issue-collecting, ordered (unknown
IDs → missing IDs → per-field domain issues in canonical order), raising
`InputValidationError(issues)`.

**There is no severity concept.** `InputIssue` carries
`category`/`message`/`field_id`/`row`/`cell`/`rows`/`value` — every issue is
fatal. Lease-Level needs non-fatal warnings. This is finding **F-4** / **HD-6**.

`InputIssue` already carries `row`/`rows`, which the Excel reader uses for
row-level issues — so per-lease-row issue reporting has a precedent.

### 2.16 Sensitivity / break-even

`SUPPORTED_ASSUMPTIONS` / `DETAILED_SUPPORTED_ASSUMPTIONS`
(`analysis/sensitivity.py:45,60`). Detailed's set is exactly the four
`AcquisitionTerms` dimensions (`purchase_price`, `exit_cap_rate`, `ltv`,
`interest_rate`) — no Detailed-only dimension was added. **Lease-Level should
adopt the identical four-dimension set in D4**, for the same reason.

`docs/detailed_operating_model_v2_1_architecture.md` §9 already prescribes the
pattern for a scenario carrying non-`AcquisitionInputs` state: wrap the whole
deal in one immutable container and `dataclasses.replace` the container, never
reconstruct a subset.

### 2.17 Existing architecture guardrails

Per `docs/solutions/conventions/testing-conventions-and-architecture-guardrails.md`,
four reusable shapes exist and must be extended, not reinvented:

1. AST-parsing import-boundary tests, one file per isolated layer.
2. Runtime data-flow spy tests for properties that are really about data flow.
3. Delegation proofs via `unittest.mock.patch(..., wraps=...)` plus call-count.
4. Spec-sourced golden cases at `pytest.approx(expected, rel=0.0, abs=1e-9)`.

---

## 3. Recommended System Architecture

### 3.1 Convergence diagram (derived from the actual code)

```
QUICK                     DETAILED                   LEASE-LEVEL
AcquisitionInputs         AcquisitionTerms           AcquisitionTerms
                          + DetailedOperatingInputs  + LeaseLevelPropertyInputs
                                                     + Suites / Leases
                                                     + MarketLeasingAssumptions
                                                     + LeaseLevelOperatingInputs
      |                          |                          |
      v                          v                          v
build_quick_          build_detailed_            build_lease_level_
operating_projection  operating_projection       operating_projection
      |                          |                          |
      v                          v                          v
 NoiForecast          OperatingProjection      LeaseLevelOperatingProjection
 (3 fields)           (12 schedules + 3)       (monthly + annual schedules + 3
                                                + tenant_improvements_by_year
                                                + leasing_commissions_by_year)
      |                          |                          |
      +-------------+------------+-------------+------------+
                    |                          |
                    v                          v
     analyze_acquisition_from_operating_projection(
         operating_projection: OperatingProjectionLike,
         terms: AcquisitionTerms,
         *, leasing_costs_by_year: tuple[float, ...] | None = None)  <-- ONLY new parameter
                    |
                    v
            AcquisitionResults
     (+ leasing_costs_by_year; all-zero for Quick/Detailed)
```

### 3.2 The one downstream extension, stated precisely

`analyze_acquisition_from_operating_projection` gains one keyword-only
parameter defaulting to `None`:

```python
def analyze_acquisition_from_operating_projection(
    operating_projection: OperatingProjectionLike,
    terms: AcquisitionTerms,
    *,
    leasing_costs_by_year: tuple[float, ...] | None = None,
) -> AcquisitionResults:
    ...
    capex_by_year = calculate_capex_by_year(...)           # unchanged
    leasing_costs = leasing_costs_by_year or _zeros(terms.hold_period)
    below_noi_by_year = calculate_below_noi_costs_by_year(
        capex_by_year=capex_by_year, leasing_costs_by_year=leasing_costs
    )
```

`below_noi_by_year` — **not** `capex_by_year` — is then passed to
`calculate_unlevered_cash_flows`, `calculate_levered_cash_flows`, and
`calculate_owner_return_metrics`. Those four functions need **no signature
change at all**: each already takes a `capex_by_year`-shaped parameter and
subtracts it.

D0 recommends **not** renaming their parameter in D4 (keeping the diff
minimal), and instead documenting at the call site that the argument is the
total below-NOI operating cost. `AcquisitionResults.capex_by_year` continues to
report the CapEx reserve alone, unchanged.

**Neutrality proof obligation (D4 gate):** with `leasing_costs_by_year=None`,
`below_noi_by_year` must equal `capex_by_year` element-wise and bit-for-bit
(`x + 0.0 == x` exactly for every finite IEEE-754 `x`, and `capex >= 0` by
domain, so no signed-zero subtlety arises). Quick and Detailed results must be
asserted bit-identical to `fffdf34` output.

`AcquisitionResults` gains `leasing_costs_by_year: tuple[float, ...]` as the
last field. Its Quick/Detailed value is **HD-1**.

### 3.3 Why not force Lease-Level into `DetailedOperatingInputs`

Because `DetailedOperatingInputs` requires `gross_potential_rent` and
`vacancy_credit_loss_pct` as *inputs*. In Lease-Level both are *outputs* of the
lease engine. Populating them would mean either fabricating a value (which
Anchor forbids) or running two competing revenue mechanisms at once. This is the
identical reasoning that produced `AcquisitionTerms` rather than a merged
25-field `AcquisitionInputs`
(`docs/detailed_operating_model_v2_1_architecture.md` §2.4), applied one level
down.

### 3.4 Why not a new canonical `PropertyCashFlow` contract

Evaluated and **rejected for D1–D4**. A unified `PropertyCashFlow` replacing
`OperatingProjectionLike` would require Quick and Detailed to produce fields
they have no basis for (monthly schedules, physical occupancy, leasing costs),
forcing exactly the fabrication the architecture forbids.
`OperatingProjectionLike` is already the minimum true common denominator, proven
by two producers. A third producer with a *superset* shape, plus one optional
downstream parameter, is strictly less invasive and equally correct.

Revisit only if a fourth producer (a Development Engine) needs a below-NOI
channel of a materially different shape.

### 3.5 Module layout

```
src/anchor/leasing/                 # new isolated package
    __init__.py                     # public entry points only
    contracts.py                    # Suite, Lease, MarketLeasingAssumptions,
                                    #   LeaseLevelPropertyInputs,
                                    #   LeaseLevelOperatingInputs,
                                    #   LeaseSchedule, PropertyRentRollSchedule,
                                    #   LeaseLevelOperatingProjection, RolloverEvent
    validation.py                   # D1: lease-level validation (errors + warnings)
    calendar.py                     # D1: date -> month-index normalization
    rent.py                         # D1: contractual base-rent timeline
    rollover.py                     # D2: expiration, renewal weighting, successor leases
    leasing_costs.py                # D2: TI, LC, free rent
    recoveries.py                   # D3: NNN / Gross / Modified Gross
    aggregation.py                  # D4: suite -> property, monthly -> annual
    projection.py                   # D4: build_lease_level_operating_projection
```

`anchor.leasing` imports from `anchor.contracts` (for `AcquisitionTerms`) and
`anchor.engine.contracts` (for `ensure_finite`) and **nothing else** from
`anchor`. It never imports `anchor.engine.acquisition`, `anchor.engine.debt`,
`anchor.engine.noi`, `anchor.engine.returns`,
`anchor.engine.operating_projection`, `anchor.ai`, `anchor.deals`, or
`anchor.ingestion`. Enforced by `tests/test_leasing_architecture.py`
(guardrail **G-1**, Section 29).

`build_lease_level_operating_projection` is called from a new
`analyze_lease_level_acquisition_with_projection` in
`anchor/engine/acquisition.py`, mirroring
`analyze_detailed_acquisition_with_projection` exactly — so `anchor.engine`
imports `anchor.leasing`, never the reverse.

---

## 4. Domain Contracts

### 4.1 Entity decisions

| Concept | Decision | Rationale |
|---|---|---|
| **Property** | `LeaseLevelPropertyInputs` — a small scalar record, not an entity graph | Only `property_area_sf` and `analysis_start_date` are financially load-bearing |
| **Suite / Space** | **First-class entity:** `Suite` | A suite persists across leases. It is what rolls over, what sits vacant, and what carries a market-rent override. Without it, "vacant suite" and "replacement tenant" have no home |
| **Tenant** | **No entity.** `tenant_name: str \| None` on `Lease` | A tenant matters financially only via credit and multi-suite rollup, neither of which is in competition scope (Section 25). Two leases for one tenant are two `Lease` rows with equal `tenant_name` — expressible, just not linked |
| **Lease** | **First-class entity, separate from `Suite`** | One suite has many leases over time (in-place, then successor, then successor-of-successor). A future lease may have no known tenant |
| **Market leasing assumptions** | Property-level default + optional per-suite override | Option D of the brief. Simplest structure that credibly handles a mixed-quality building |
| **Lease-level override** | A nullable field on `Lease`/`Suite` that, when non-`None`, wins | Section 24 |

**Explicitly rejected: merging Tenant and Lease into one entity.** Rejected for
a reason opposite to the usual — not because a Tenant entity is needed, but
because a `Lease` that *is* its tenant cannot represent a speculative successor
lease with no tenant yet, which the rollover engine creates at every expiration.
`Lease.tenant_name` is nullable precisely for this.

### 4.2 `LeaseLevelPropertyInputs`

| Field | Type | Units | Required | Domain | Financial meaning | Input/Derived | Phase |
|---|---|---|---|---|---|---|---|
| `analysis_start_date` | `date` | — | required | first day of a month | First day of hold Month 1. Single anchor for every date→month normalization | input | D1 |
| `property_area_sf` | `float` | SF | required | `> 0` | Total rentable area. Denominator for occupancy and for area reconciliation | input | D1 |

**`analysis_start_date` must be the first day of a month** — ERROR otherwise. It
is the origin of every month index; a mid-month origin would make every
subsequent month a mid-month band and silently convert "whole-month rent
recognition" into an unstated proration convention. This is a normalization the
analyst can always satisfy.

Deliberately **not** on this contract: `property_name`, `address`,
`property_type`, `year_built`. Those are `DealContext`
(`ingestion/contracts.py:161`) — informational, never engine inputs. Anchor's
existing separation is preserved.

### 4.3 `Suite`

| Field | Type | Units | Required | Domain | Financial meaning | I/D | Phase |
|---|---|---|---|---|---|---|---|
| `suite_id` | `str` | — | required | non-empty, unique in property | Stable identity. **Financial**, not merely informational: the key binding a lease to the space that rolls over | input | D1 |
| `suite_label` | `str \| None` | — | optional | — | Display name ("Suite 300"). Informational only | input | D1 |
| `suite_area_sf` | `float` | SF | required | `> 0` | Rentable area of this suite | input | D1 |
| `market_rent_psf` | `float \| None` | $/SF/yr | optional | `>= 0` | Suite-level market-rent override; `None` → property default | input | D2 |
| `market_leasing_override` | `MarketLeasingAssumptions \| None` | — | optional | — | Full suite-level override of rollover assumptions | input | D2 |

**Suite identifiers are financial.** Rollover, downtime, occupancy, and area
reconciliation are all computed per-suite. A `suite_id` typo is an ERROR, not a
cosmetic issue.

**Vacant suites are represented by a `Suite` with no lease covering a given
month** — never by a synthetic "vacant lease" row. A suite vacant at
`analysis_start_date` with no lease at all is the ordinary D2 lease-up case.

### 4.4 `Lease`

| Field | Type | Units | Required | Domain | Financial meaning | I/D | Phase |
|---|---|---|---|---|---|---|---|
| `lease_id` | `str` | — | required | non-empty, unique in property | Stable identity | input | D1 |
| `suite_id` | `str` | — | required | must match a `Suite.suite_id` | The space this lease occupies | input | D1 |
| `tenant_name` | `str \| None` | — | optional | — | Informational. `None` for a speculative/successor lease | input | D1 |
| `leased_area_sf` | `float` | SF | required | `> 0` | Area this lease covers. Must equal `Suite.suite_area_sf` in D1–D3 (4.4.1) | input | D1 |
| `rent_commencement_date` | `date` | — | required | — | First date base rent is owed. Drives the first rent month | input | D1 |
| `lease_expiration_date` | `date` | — | required | `>= rent_commencement_date` | Last date base rent is owed | input | D1 |
| `lease_start_date` | `date \| None` | — | optional | `<= rent_commencement_date` | Possession date, distinct from rent start. **Informational only in D1–D3** | input | D1 |
| `base_rent_psf` | `float` | $/SF/yr | required | `>= 0` | Contractual annual base rent per SF at `rent_commencement_date` | input | D1 |
| `escalation_pct` | `float` | decimal | required | `> -1` | Annual fixed escalation. `0.0` = flat | input | D1 |
| `escalation_basis` | `EscalationBasis` | enum | required | `NONE` \| `LEASE_ANNIVERSARY` | When escalation applies. D1 supports these two only | input | D1 |
| `lease_type` | `LeaseType` | enum | required | `NNN` \| `GROSS` \| `MODIFIED_GROSS` | Recovery structure. **Captured in D1, economically inert until D3** | input | D1 / D3 |
| `free_rent_months` | `float` | months | optional, default `0.0` | `>= 0` | Months of abated base rent from rent commencement | input | D2 |
| `origin` | `LeaseOrigin` | enum | derived | `IN_PLACE` \| `SUCCESSOR` | Whether the analyst supplied this lease or the rollover engine created it | derived | D2 |

#### 4.4.1 Why `leased_area_sf` must equal `Suite.suite_area_sf` in D1–D3

Allowing a lease to cover part of a suite means a suite can be simultaneously
partly leased and partly vacant, requiring sub-suite space accounting (demising,
partial rollover, partial downtime). That is genuine property-management
complexity with no competition payoff.

**D1–D3 rule: one suite = one leasable unit.** A physically subdivided suite is
modeled as two `Suite` rows. `leased_area_sf != suite_area_sf` is an ERROR.

`leased_area_sf` is nonetheless kept as an explicit field (rather than derived
from the suite) because it is what a rent roll actually states, it is the basis
for TI and for `base_rent_psf`, and relaxing the equality later then becomes a
validation change rather than a contract change.

#### 4.4.2 Fields deliberately excluded from D1

A third distinct `occupancy_start_date` (subsumed by `lease_start_date`),
security deposits, guarantees, option periods, expansion/contraction rights,
percentage rent, CPI indexation, tenant credit rating, sublease structure,
holdover terms. See Section 25.

### 4.5 `MarketLeasingAssumptions`

Property-level default; optionally overridden per suite.

| Field | Type | Units | Required | Domain | Financial meaning | I/D | Phase |
|---|---|---|---|---|---|---|---|
| `market_rent_psf` | `float` | $/SF/yr | required | `>= 0` | Market rent measured **at `analysis_start_date`** | input | D2 |
| `market_rent_growth` | `float` | decimal | required | `> -1` | Annual market-rent growth | input | D2 |
| `renewal_probability` | `float` | decimal | required | `0 <= p <= 1` | Probability the sitting tenant renews | input | D2 |
| `renewal_rent_psf` | `float \| None` | $/SF/yr | optional | `>= 0` | Explicit renewal rent level at `analysis_start_date`; `None` → derived (4.5.1) | input | D2 |
| `renewal_rent_spread` | `float` | decimal | required | `> -1` | Renewal rent as discount/premium to market. `0.0` = at market | input | D2 |
| `renewal_term_months` | `int` | months | required | `>= 1` | Successor term if renewed | input | D2 |
| `new_term_months` | `int` | months | required | `>= 1` | Successor term if re-let to a new tenant | input | D2 |
| `renewal_downtime_months` | `float` | months | required | `>= 0` | Downtime on renewal. Typically `0.0` | input | D2 |
| `new_downtime_months` | `float` | months | required | `>= 0` | Downtime before a replacement tenant | input | D2 |
| `renewal_free_rent_months` | `float` | months | required | `>= 0` | Free base rent granted on renewal | input | D2 |
| `new_free_rent_months` | `float` | months | required | `>= 0` | Free base rent granted to a new tenant | input | D2 |
| `renewal_ti_psf` | `float` | $/SF | required | `>= 0` | TI allowance on renewal | input | D2 |
| `new_ti_psf` | `float` | $/SF | required | `>= 0` | TI allowance for a new tenant | input | D2 |
| `renewal_lc_pct` | `float` | decimal | required | `0 <= x <= 1` | LC as % of successor total base rent, renewal | input | D2 |
| `new_lc_pct` | `float` | decimal | required | `0 <= x <= 1` | LC as % of successor total base rent, new tenant | input | D2 |
| `successor_escalation_pct` | `float` | decimal | required | `> -1` | Annual escalation written into successor leases | input | D2 |

#### 4.5.1 `renewal_rent_psf` vs `renewal_rent_spread`

Both are offered because both appear in real underwriting. Precedence
(Section 24): an explicit `renewal_rent_psf` wins; otherwise
`renewal_rent = market_rent_at_commencement * (1 + renewal_rent_spread)`.

`renewal_rent_psf`, when supplied, is a **level measured at
`analysis_start_date`** and is grown by `market_rent_growth` to the commencement
month, so the same input produces consistent economics regardless of when the
rollover occurs. This is stated explicitly because the alternative reading (a
fixed nominal rent regardless of rollover date) is equally plausible and would
produce materially different answers — see **HD-4**.

### 4.6 `LeaseLevelOperatingInputs`

Derivation in Section 13.

| Field | Type | Units | Required | Domain | Phase |
|---|---|---|---|---|---|
| `other_income` | `float` | $/yr | required | `>= 0` | D4 |
| `other_income_growth` | `float` | decimal | required | `> -1` | D4 |
| `property_taxes` | `float` | $/yr | required | `>= 0` | D4 |
| `insurance` | `float` | $/yr | required | `>= 0` | D4 |
| `utilities` | `float` | $/yr | required | `>= 0` | D4 |
| `repairs_maintenance` | `float` | $/yr | required | `>= 0` | D4 |
| `other_operating_expenses` | `float` | $/yr | required | `>= 0` | D4 |
| `management_fee_pct` | `float` | decimal | required | `0 <= x <= 1` | D4 |
| `expense_growth` | `float` | decimal | required | `> -1` | D4 |
| `credit_loss_pct` | `float` | decimal | optional, default `0.0` | `0 <= x <= 1` | D4 |
| `recoverable_expense_ratio` | `float` | decimal | required at D3 | `0 <= x <= 1` | D3 |

`other_income_growth` is a **separate** rate here, unlike Detailed (which shares
one `revenue_growth` across GPR and other income). Lease-Level has no
`revenue_growth` at all — rent growth comes from lease escalations and market
rent growth — so other income must carry its own rate or it cannot grow.

### 4.7 Output contracts

#### `LeaseSchedule` (D1)

Per lease, per month, over months `1 .. 12H+12`:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseSchedule:
    lease_id: str
    suite_id: str
    first_rent_month: int | None       # None if the lease never pays in-window
    last_rent_month: int | None
    base_rent_by_month: tuple[float, ...]       # length 12H+12, $ for that month
    occupied_area_by_month: tuple[float, ...]   # length 12H+12, SF
```

#### `PropertyRentRollSchedule` (D1)

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PropertyRentRollSchedule:
    months: int                                  # == 12H + 12
    lease_schedules: tuple[LeaseSchedule, ...]
    contractual_base_rent_by_month: tuple[float, ...]
    occupied_area_by_month: tuple[float, ...]
    vacant_area_by_month: tuple[float, ...]      # property_area_sf - occupied
    physical_occupancy_by_month: tuple[float, ...]
```

#### `LeaseLevelOperatingProjection` (D4)

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseLevelOperatingProjection:
    # --- monthly detail (audit surface; never consumed downstream) ---
    contractual_base_rent_by_month: tuple[float, ...]
    free_rent_by_month: tuple[float, ...]
    expense_recoveries_by_month: tuple[float, ...]
    other_income_by_month: tuple[float, ...]
    credit_loss_by_month: tuple[float, ...]
    effective_gross_income_by_month: tuple[float, ...]
    total_operating_expenses_by_month: tuple[float, ...]
    noi_by_month: tuple[float, ...]
    tenant_improvements_by_month: tuple[float, ...]
    leasing_commissions_by_month: tuple[float, ...]
    physical_occupancy_by_month: tuple[float, ...]

    # --- annual, Years 1..H ---
    base_rent_by_year: tuple[float, ...]
    free_rent_by_year: tuple[float, ...]
    expense_recoveries_by_year: tuple[float, ...]
    other_income_by_year: tuple[float, ...]
    credit_loss_by_year: tuple[float, ...]
    effective_gross_income_by_year: tuple[float, ...]
    property_taxes_by_year: tuple[float, ...]
    insurance_by_year: tuple[float, ...]
    utilities_by_year: tuple[float, ...]
    repairs_maintenance_by_year: tuple[float, ...]
    other_operating_expenses_by_year: tuple[float, ...]
    management_fee_by_year: tuple[float, ...]
    total_operating_expenses_by_year: tuple[float, ...]
    noi_by_year: tuple[float, ...]              # <- OperatingProjectionLike

    # --- below NOI, Years 1..H ---
    tenant_improvements_by_year: tuple[float, ...]
    leasing_commissions_by_year: tuple[float, ...]

    # --- exit ---
    exit_noi: float                             # <- OperatingProjectionLike
    going_in_cap_rate: float                    # <- OperatingProjectionLike
    exit_ntm_leasing_costs: float               # DISCLOSED, never deducted

    # --- diagnostics ---
    rollover_events: tuple[RolloverEvent, ...]
```

`RolloverEvent` records, per rollover: `suite_id`, `expiring_lease_id`,
`successor_lease_id`, `expiration_month`, `commencement_month`,
`downtime_months`, `renewal_probability_applied`, `successor_rent_psf`,
`ti_amount`, `lc_amount`. This is the audit trail that makes a lease-level
result defensible in competition Q&A, and it is the mechanism by which the AI
Analyst can *describe* rollover without recomputing it.

---

## 5. Time Granularity

### 5.1 Recommendation: **B — monthly internal, annual published**

Rejected alternatives:

- **Annual only.** Cannot express a mid-year expiration, a 4-month downtime, a
  3-month free-rent period, or a rent commencement in month 7 without inventing
  a fractional-year convention per event. Every one of those is standard
  competition content. Rejected on financial correctness.
- **Daily.** Requires day-count conventions (30/360 vs actual/actual), makes
  every golden case hand-calculation an exercise in day arithmetic, and buys
  precision that no rent roll's own stated terms actually justify. Rejected on
  complexity for no financial gain.
- **Quarterly.** Standard leases are stated in months; quarters would require
  the same rounding decisions as annual, one step less coarsely. No constituency.

Anchor already runs monthly-internal / annual-output in `engine/debt.py`. This
is precedent, not novelty.

### 5.2 What a "month" is

- Month index `m` is a **1-based integer**. Month `1` is the calendar month
  containing `analysis_start_date`, which by validation is the first day of a
  month.
- Month `m` therefore spans calendar dates
  `[analysis_start_date + (m-1) months, analysis_start_date + m months)`.
- **Acquisition occurs at the instant before Month 1 begins** (time `0` in the
  existing cash-flow convention). No operating cash flow occurs at time `0`.
- The projection window is months `1 .. 12H + 12`. Nothing outside it is ever
  computed.

### 5.3 Month-to-year aggregation

```
Hold year y spans months 12(y-1)+1 .. 12y,  for 1 <= y <= H
Exit NTM  spans months 12H+1     .. 12H+12
```

```
AnnualLine_y = sum of MonthlyLine_m for m in that year,
               summed in strictly ascending month order
```

**The ascending-order summation is a requirement, not a note.** It mirrors
`calculate_annual_debt_service`'s explicit refusal of the `12 * PMT`
shortcut — repeated IEEE-754 addition in a fixed order is reproducible; the
same values summed in a different order may differ in the last bits, and Anchor
asserts golden cases at `abs=1e-9`.

### 5.4 Start-of-month vs end-of-month events, and partial months

**Recommended D1 convention: whole-month rent recognition, any-overlap-pays.**

```
first_rent_month(lease) = month_index(rent_commencement_date)
last_rent_month(lease)  = month_index(lease_expiration_date)
```

where `month_index(d) = 12*(d.year - s.year) + (d.month - s.month) + 1` for
`s = analysis_start_date`. A lease pays full base rent in every month from
`first_rent_month` through `last_rent_month` inclusive, and nothing outside it.

Properties of this rule:

- **Exact** whenever a lease commences on the 1st and expires on the last day of
  a month — which is what rent rolls overwhelmingly state, and what every
  successor lease the engine generates will do by construction.
- **Deterministic and hand-checkable**, requiring no day counts.
- **Biased** when a real lease commences or expires mid-month: up to one extra
  month of rent is recognized at each end.

Two mandatory mitigations:

1. **WARNING** (`LEASE_DATE_NOT_MONTH_ALIGNED`) whenever
   `rent_commencement_date` is not the 1st of its month or
   `lease_expiration_date` is not the last day of its month. The analyst is told
   the approximation applies to that specific lease, and can normalize the dates.
2. **ERROR** (`OVERLAPPING_LEASES_IN_SUITE`) whenever two leases on the same
   `suite_id` have overlapping `[first_rent_month, last_rent_month]` ranges.
   Without this, a lease expiring June 15 and its replacement commencing June 16
   would both collect full June rent — double-counted revenue *and* physically
   impossible occupancy. This validation closes the only serious hole the
   whole-month rule opens.

Day-level proration is offered as the alternative in **HD-3**.

### 5.5 Where fractional months are permitted

Exactly one place: **downtime and free rent**, both of which are
*assumptions* (analyst-chosen durations), not *contract dates*. A downtime of
`3.5` months or a weighted downtime of `3.85` months is expressed as
`floor(D)` fully-zero months plus one boundary month carrying a revenue factor
of `1 - frac(D)`. See Section 9.3.

This does **not** reintroduce proration of contractual leases; it prorates a
single assumption-driven gap month. Free rent works identically (Section 10).

### 5.6 Does debt need to become monthly?

**No.** Verified by inspection:

- `calculate_debt_schedule` (`engine/debt.py:437`) already produces
  `annual_debt_service` from a chronological monthly loop, and
  `remaining_loan_balance` from a monthly amortization recurrence.
- The lease engine produces `noi_by_year` on the same Year-1..Year-H boundaries
  that `annual_debt_service` uses. `DSCR_y = NOI_y / ADS_y` therefore compares
  two quantities covering the identical twelve months.

Monthly DSCR, monthly cash sweeps, monthly distributions, and monthly IRR are
all out of scope and would each require a genuine debt-engine change. None is
needed for competition readiness.

### 5.7 Must lease-level cash flow align with debt timing?

It already does at the annual boundary, which is where the two ever meet. They
never meet monthly: no downstream consumer reads a monthly lease figure. The
monthly schedules on `LeaseLevelOperatingProjection` are an **audit and display
surface only** — a guardrail test (**G-6**) asserts no engine module outside
`anchor.leasing` reads any `_by_month` field.

---

## 6. Contractual Base Rent Conventions

### 6.1 The D1 base-rent formula

For lease `L` and month `m`:

```
if m < first_rent_month(L) or m > last_rent_month(L):
    BaseRent(L, m) = 0.0
else:
    k = escalation_period_index(L, m)
    AnnualRentPSF(L, m) = L.base_rent_psf * (1 + L.escalation_pct)^k
    BaseRent(L, m) = AnnualRentPSF(L, m) * L.leased_area_sf / 12.0
```

Units: `base_rent_psf` is **$/SF/year**; dividing by 12 after multiplying by
area yields the month's dollars. Division by 12 happens **once, last** — never
by converting `base_rent_psf` to a monthly PSF first — so the ordering of
floating-point operations is fixed and reproducible.

### 6.2 Escalation timing

```
escalation_basis = NONE               ->  k = 0 for every month
escalation_basis = LEASE_ANNIVERSARY  ->  k = floor((m - first_rent_month) / 12)
```

`LEASE_ANNIVERSARY` means the escalation applies on each 12-month anniversary of
**rent commencement**, not of the analysis start and not of the calendar year.
Months `first_rent_month .. first_rent_month+11` are at `k=0`; the next twelve
at `k=1`; and so on. This matches the plain reading of "3% annual increases" in
a lease abstract.

**Calendar-year escalations are deferred to D2+** (`escalation_basis =
CALENDAR_YEAR`, `k = m.calendar_year - rent_commencement.calendar_year`). They
are real but second-order, and adding a third enum member later is additive.

### 6.3 Rent stated as a total, not per SF

**D1 accepts `base_rent_psf` only.** A rent roll stating total annual rent is
normalized at the *ingestion/approval* boundary
(`base_rent_psf = annual_rent / leased_area_sf`), never inside the engine, so
the engine has exactly one rent representation and one code path.

Rationale: two accepted representations means two paths, a precedence rule
between them, and a reconciliation failure mode when both are supplied and
disagree. The conversion is a single division the analyst can verify.

### 6.4 Leases relative to the hold

| Situation | D1 treatment |
|---|---|
| Lease commenced before `analysis_start_date` | Normal. `first_rent_month <= 1`, clamped to 1 in the schedule; the escalation index `k` is still measured from the true `rent_commencement_date`, so an in-place lease is on the correct step in Month 1 |
| Lease commencing during the hold (known future lease) | Normal. Zero rent before `first_rent_month` |
| Lease expiring during the hold | Normal. Zero rent after `last_rent_month`. **D1 does not roll it over** — the space simply goes to zero rent and shows as vacant. Rollover is D2 |
| Lease expiring before `analysis_start_date` | **ERROR** (`LEASE_EXPIRED_BEFORE_ANALYSIS_START`). It is not a lease of this deal |
| Lease commencing after month `12H+12` | **WARNING** (`LEASE_STARTS_AFTER_HORIZON`). Kept in the input set, contributes nothing |

The clamping of `first_rent_month` to `1` is display/aggregation only; the
escalation index in 6.2 must use the raw, unclamped
`first_rent_month`, or an in-place lease three years into a 3%-escalating term
would restart at its original rent. This is failure mode **FM-4**.

### 6.5 Rounding

**No rounding anywhere in the engine.** Full IEEE-754 double precision is
carried end-to-end, exactly as every existing Anchor calculator does. Rounding
is a presentation concern (`src/anchor/formatting.py`, `web/src/format.ts`).
Golden cases assert at `pytest.approx(expected, rel=0.0, abs=1e-9)`.

### 6.6 Rent structures explicitly unsupported in D1

Deferred, with the phase each would land in if approved:

| Structure | Phase | Note |
|---|---|---|
| Calendar-year escalation basis | D2 | Additive enum member |
| Explicit rent steps (a schedule of dated rent levels) | D2 | Needs a `RentStep` child contract; the most likely first extension, because real abstracts often state steps rather than a % |
| Fixed `$/SF` annual bumps (rather than %) | D2 | Additive enum member on `escalation_basis` |
| CPI / indexation | Deferred indefinitely | Requires an inflation assumption Anchor does not have |
| Percentage rent / turnover rent | Deferred indefinitely | Requires tenant sales data |
| Monthly scheduled overrides | Deferred indefinitely | Effectively hand-entering the answer |
| Mid-term rent abatement (other than at commencement) | Deferred | Free rent at commencement covers the competition case |

Anything on this list appearing in a competition case is handled by the analyst
normalizing it into a supported structure at the approval boundary, with a
recorded note — never by the engine guessing.

---

## 7. Market Rent Conventions

### 7.1 Structure: **Option D — property default with suite-level override**

`MarketLeasingAssumptions` at the property level supplies every rollover
assumption. A `Suite` may override `market_rent_psf` alone (the common case: one
suite is inferior/superior space) or the entire `MarketLeasingAssumptions`
record (the less common case: a retail suite in an office building).

Rejected:

- **A single property-wide value.** Cannot express a ground-floor retail suite
  at $60/SF in a $35/SF office building. Real competition cases do this.
- **Per-suite only, no default.** Forces the analyst to retype identical
  assumptions for every suite; guarantees inconsistency in a 20-suite building.
- **By space type.** Adds a `space_type` taxonomy that then needs its own
  validation, its own UI, and its own precedence rule, to buy exactly what the
  suite override already buys. Rejected as complexity without payoff.

### 7.2 Market rent measurement date and growth

`market_rent_psf` is measured **at `analysis_start_date`** — i.e. it is the
Month-1 market rent, not a "today" figure from an undated market study.

```
MarketRentPSF(m) = market_rent_psf * (1 + market_rent_growth)^floor((m - 1) / 12)
```

- Growth applies on **analysis anniversaries**, held flat within each 12-month
  band. Months 1–12 use exponent `0`; months 13–24 use `1`; and so on.
- This mirrors Anchor's existing, frozen growth timing convention exactly
  ("Year 1 equals the input; growth begins in Year 2"), applied at monthly
  resolution.

**Rejected: monthly compounding of market rent growth**
(`(1+g)^((m-1)/12)`). It is smoother, but it (a) departs from Anchor's stated
annual-growth timing convention, (b) makes every golden case require a fractional
power, and (c) buys precision that a market-rent assumption does not possess.

### 7.3 Market rent at rollover

The market rent applied to a successor lease is `MarketRentPSF(c)` where `c` is
the successor's **rent commencement month** — after downtime, not at the
expiration month. Charging pre-downtime market rent is failure mode **FM-3**.

### 7.4 Precedence

See Section 24. In short:

```
Suite.market_leasing_override.market_rent_psf
  > Suite.market_rent_psf
  > property MarketLeasingAssumptions.market_rent_psf
```

Growth (`market_rent_growth`) follows the same chain independently, so a suite
can override the level without overriding the growth.

---

## 8. Rollover Conventions

### 8.1 What happens at expiration

At `last_rent_month(L)` for a lease `L` on suite `S`, the rollover engine
creates **exactly one** successor lease `L'` on `S`, covering the full
`suite_area_sf`. `L'` is itself eligible to roll over when it expires, so a
3-year remaining term in a 10-year hold produces a chain of successors. The
chain is computed until a successor's `first_rent_month > 12H + 12`, at which
point it contributes nothing and generation stops.

### 8.2 Deterministic renewal treatment — the recommendation

**Recommended: weighted-assumption single successor lease (ARGUS convention).**

This is Option A of the brief's Part 9 **applied at the assumption level, not at
the cash-flow level**, and it subsumes Option B: setting `renewal_probability =
1.0` gives a pure Renew path and `0.0` gives a pure Vacate path, so an analyst
who wants a deterministic named path simply picks an endpoint.

Let `p = renewal_probability`. Every successor parameter is a `p`-weighted blend
of the renewal and new-tenant assumptions:

```
successor_rent_psf   = p * RenewalRentPSF(c) + (1 - p) * MarketRentPSF(c)
downtime_months      = p * renewal_downtime_months + (1 - p) * new_downtime_months
free_rent_months     = p * renewal_free_rent_months + (1 - p) * new_free_rent_months
ti_psf               = p * renewal_ti_psf + (1 - p) * new_ti_psf
lc_pct               = p * renewal_lc_pct + (1 - p) * new_lc_pct
term_months          = round_half_up(p * renewal_term_months + (1 - p) * new_term_months)
escalation_pct       = successor_escalation_pct
lease_type           = the expiring lease's lease_type
tenant_name          = None
origin               = SUCCESSOR
```

where `c` is the successor's rent commencement month (8.4) and
`RenewalRentPSF(c)` follows 4.5.1.

### 8.3 Why this, and what was rejected

| Option | Verdict |
|---|---|
| **A. Expected-value weighting of two full cash-flow branches** (run a Renew model and a Vacate model, average the results) | **Rejected.** After the first rollover the two branches have different expiration dates, so the second rollover has no single date, and by the third the "blend" is an average over a tree whose leaves no analyst can enumerate. It is unauditable, and it makes the `RolloverEvent` log meaningless. It also silently implies fractional physical occupancy |
| **A′. Weighted assumptions, one successor lease** (recommended) | Deterministic; produces one physically coherent lease per suite; every weighted parameter is a single number an analyst can check; it is what ARGUS actually does with Renewal Probability; competition judges recognize it immediately |
| **B. Analyst-selected path per lease (Renew / Vacate / Expected)** | **Subsumed**, not rejected. `p ∈ {0, 1}` gives exactly this. Offering it as a *separate* mechanism would create two ways to say the same thing |
| **C. One fixed base-case convention** (e.g. always re-let at market) | **Rejected.** Ignores renewal economics entirely; overstates TI/LC and downtime on every rollover; not defensible for a stabilized building with sticky tenants |
| **D. Explicit scenario branches** (a named Downside/Base/Upside set) | **Deferred, not rejected.** This is a *scenario* feature layered above the engine, orthogonal to the rollover convention. It belongs with sensitivity work, post-D4 |

**The critical property A′ preserves and A destroys:** physical space stays
integral. A suite is either occupied or vacant in a given month. Occupancy is
reportable, the area-reconciliation invariant holds, and no downstream consumer
ever sees "65% of Suite 300."

**The honest weakness of A′**, which must be disclosed in the UI: a weighted
successor is an economic average that corresponds to no single real-world
outcome. A `p=0.65` successor pays a rent no actual tenant would pay. This is
the standard, accepted trade in institutional underwriting, but it means the
model answers "what is the expected economics" and not "what will actually
happen." The `RolloverEvent` log records
`renewal_probability_applied` so this is never hidden.

### 8.4 Successor timing

```
expiration_month(L)          = last_rent_month(L)
downtime_months              = weighted, per 8.2  (>= 0.0, may be fractional)
commencement_month(L')       = expiration_month(L) + 1 + ceil(downtime_months)
last_rent_month(L')          = commencement_month(L') + term_months - 1
```

`ceil(downtime_months)` determines how many months are *skipped entirely*; the
fractional part is recovered as a partial-month revenue factor in the
commencement month, so no rent is lost or gained by the ceiling. See 9.3 for the
exact mechanics, which are the reason a `ceil` here is not an approximation.

### 8.5 Leases extending beyond exit

A lease (in-place or successor) whose `last_rent_month > 12H + 12` is simply
truncated at the window: months beyond `12H+12` are never computed. No
"remaining term value" adjustment is made — that value is already captured by
the exit cap rate applied to exit NOI. Making a second adjustment would
double-count.

### 8.6 Rollover during the exit NTM window

Rollover **runs live through month `12H+12`**. A lease expiring in month
`12H+3` therefore rolls, takes its downtime, and depresses `exit_noi`
accordingly. This is intentional and is the financially correct reading of
"next-twelve-month forward NOI." See Section 17 and **HD-5**.

---

## 9. Downtime

### 9.1 Definition

Downtime is the number of months between an expiring lease's last paying month
and its successor's first paying month during which the suite produces no base
rent and no recoveries.

Units: **months**, `float`, `>= 0`. Renewal and new-tenant downtimes are
separate inputs and are `p`-weighted per 8.2 (typically
`renewal_downtime_months = 0.0`, since a renewing tenant does not vacate).

### 9.2 What happens during downtime

| Item | Treatment | Rationale |
|---|---|---|
| Base rent | `0.0` | The suite is empty |
| Expense recoveries (D3) | `0.0` | No tenant to reimburse. Continuing them is failure mode **FM-9** |
| Operating expenses | **Continue in full** | Taxes, insurance, and R&M do not stop when a suite empties. Under NNN, the *landlord* now bears the previously-recovered share — which is precisely the economic cost of vacancy and the main reason a lease-level model beats a property-level one |
| Management fee | Continues, computed on the (now lower) EGI | Unchanged mechanic: `% of EGI` |
| Market rent growth | Continues | Market rent is a market fact, not a function of this suite's status |
| Other income | Continues | Property-level, not suite-level (Section 14) |
| Physical occupancy | The suite's area moves to `vacant_area_by_month` | The occupancy series is what makes this auditable |
| TI / LC | **Not** paid during downtime — paid at successor rent commencement | Sections 11, 12 |

### 9.3 Fractional downtime

Let `D = downtime_months`, `e = expiration_month`, `n = ceil(D)`,
`f = n - D` (so `0 <= f < 1`).

- Months `e+1 .. e+n` are the downtime block.
- Months `e+1 .. e+n-1` produce zero rent.
- Month `e+n` — the successor's commencement month — produces rent multiplied by
  a **partial-month occupancy factor** `f`.
- Every month from `e+n+1` onward is a full rent month.

When `D` is a whole number, `f = 0` and month `e+n` is fully vacant, so the rule
degenerates exactly to the intuitive whole-month case with no special-casing.

Total rent forgone is exactly `D` months' worth, for any real `D >= 0`. This is
the invariant that makes `ceil` in 8.4 safe.

**The partial-month factor applies to base rent and recoveries only.** It never
applies to operating expenses, other income, TI, or LC.

### 9.4 Downtime vs. Detailed-mode vacancy — no double counting

Lease-Level **has no `vacancy_credit_loss_pct` field at all.**
`LeaseLevelOperatingInputs` (4.6) deliberately omits it. There is therefore no
mechanism by which Detailed's vacancy factor could be applied on top of modeled
downtime, because the field does not exist on the contract.

This mirrors exactly how Detailed resolved the same class of problem with
`occupancy` (`docs/detailed_operating_model_v2_1_financial_conventions.md`,
"Occupancy and Vacancy — Resolved Relationship"): rather than reconciling two
mechanisms, the second mechanism is simply absent from the mode's contract.

Guardrail **G-4** asserts that no field named `vacancy_credit_loss_pct` or
`occupancy` exists anywhere on the Lease-Level input contracts.

The one surviving revenue-loss allowance is `credit_loss_pct` — see Section 15,
which explains precisely why it is *not* a vacancy factor.

---

## 10. Free Rent

### 10.1 Convention (D2)

| Question | D2 answer |
|---|---|
| Units | **Months** (`float`, `>= 0`) |
| When it starts | At **rent commencement**, i.e. the first `free_rent_months` of the paying term. Contiguous, never scattered |
| What is abated | **Base rent only** |
| Recoveries during free rent | **Still payable.** Free rent is a base-rent concession; a NNN tenant in a free-rent period still pays its expense share. This is standard, and conflating the two is failure mode **FM-6** |
| Above or below NOI | **Above NOI.** Free rent is a revenue abatement, not a capital cost. It is reported as its own line, `free_rent_by_month` / `free_rent_by_year`, as a **positive** number subtracted in the EGI build |
| Renewal vs new tenant | Separate inputs (`renewal_free_rent_months`, `new_free_rent_months`), `p`-weighted per 8.2 |
| In-place leases | `Lease.free_rent_months` on an analyst-supplied lease, if any remains at `analysis_start_date`. Defaults to `0.0` |
| Fractional months | Handled exactly as fractional downtime (9.3): whole free months, then one boundary month at factor `1 - f` |

### 10.2 Operating-statement placement

```
Contractual Base Rent
  less Free Rent                      <-- here
  plus Expense Recoveries
  plus Other Income
  less Credit Loss
= Effective Gross Income
```

Free rent sits immediately under base rent so an analyst reading the statement
sees gross scheduled rent and the concession side by side. **It never nets into
`contractual_base_rent_by_month`**, which must always report the gross
contractual figure — that is what LC is computed from (Section 12) and what
reconciles to the rent roll.

### 10.3 Interaction with downtime

Downtime and free rent are **sequential, never overlapping**: downtime ends at
the successor's rent commencement; free rent begins there. Counting a month as
both is failure mode **FM-6**. Guardrail **G-5** asserts that for every
successor lease, the free-rent months and the downtime months are disjoint
month-index sets.

---

## 11. Tenant Improvements

### 11.1 Convention (D2)

| Question | D2 answer |
|---|---|
| Basis | `$/SF` × `leased_area_sf` |
| Which area | The **leased area of the successor lease** (= `suite_area_sf` under 4.4.1) |
| Renewal vs new | Separate rates (`renewal_ti_psf`, `new_ti_psf`), `p`-weighted per 8.2 |
| Timing | **Paid in full, in one month: the successor's rent commencement month** |
| Above or below NOI | **Below NOI**, in `tenant_improvements_by_year` |
| Multiple payments / draw schedule | **Not supported in D2.** Single payment only |
| TI on in-place leases | **None.** An in-place lease's TI was spent by the seller before acquisition. Charging it again is failure mode **FM-11** |

```
TI(L') = weighted_ti_psf * L'.leased_area_sf,
         recognized entirely in month commencement_month(L')
```

### 11.2 Why rent commencement, not lease signing

Anchor has no lease-signing date field, and adding one would require an
assumption about the signing-to-commencement lag on every speculative successor
lease — a number no analyst can source. Rent commencement is unambiguous, is
already computed, and is within one or two months of the true spend in practice.
The convention is stated so a reviewer can judge it rather than infer it.

**Consequence to disclose:** because TI lands at commencement (after downtime),
a rollover late in the hold may push its TI into the exit NTM window, where it
is *disclosed* but not deducted. See 17.4.

### 11.3 Why single-payment

A draw schedule (e.g. 50% at commencement, 50% at 6 months) changes the timing
of a below-NOI cost by a few months. At annual aggregation, it moves dollars
across at most one year boundary. It is not worth a schedule contract, a
validation surface, and a UI in D2. Deferred; additive if later required.

---

## 12. Leasing Commissions

### 12.1 There is no universal convention — stated plainly

Institutional practice genuinely varies:

- **% of total contractual base rent over the term** — most common in
  institutional US office/industrial models; scales correctly with term length.
- **% of first-year rent** — common in brokerage quotes; understates a 10-year
  deal relative to a 3-year one.
- **Stepped % by year** (e.g. 6% years 1–5, 3% years 6–10) — common in practice,
  hardest to model.
- **$/SF** — common in some markets and property types.

Anchor must pick one for D2 and say so. It should not pretend the choice is
settled by the market.

### 12.2 Recommendation (D2)

**`%` of total contractual base rent over the successor lease term, computed
gross of free rent.**

```
LC(L') = weighted_lc_pct * sum(
             GrossContractualBaseRent(L', m)
             for m in first_rent_month(L') .. last_rent_month(L')
         )
```

recognized entirely in **month `commencement_month(L')`**, below NOI, in
`leasing_commissions_by_year`.

Three sub-decisions, each stated explicitly:

| Sub-decision | Choice | Why |
|---|---|---|
| Free rent in the basis? | **Included** (basis is gross of free rent) | A broker's commission is earned on the lease signed, not on the concession the landlord chose to grant. This is the majority convention, and it makes the basis reconcile to the rent schedule |
| Escalations in the basis? | **Included** | The commission is on the full contractual rent stream, escalations and all. Excluding them would understate LC on any escalating lease, which is nearly all of them |
| Term truncated at the horizon? | **No — the full contractual term is used**, even where it extends past month `12H+12` | The commission is a real obligation incurred in full at signing. Truncating it would understate a cost the buyer actually pays |

The last point is worth emphasizing: the LC calculation is the one place where
the engine computes rent **beyond** the `12H+12` window. It does so only to form
a commission basis; those months never enter any revenue or NOI series.

### 12.3 Configurable method

**Deferred.** A `LeasingCommissionMethod` enum (`PCT_OF_TOTAL_RENT`,
`PCT_OF_FIRST_YEAR_RENT`, `PER_SF`) is a clean additive extension if a
competition case demands it, but shipping three methods in D2 means three sets
of golden cases and three precedence questions for no near-term gain. One
convention, stated and defensible, beats three configurable ones.

### 12.4 LC on in-place leases

**None**, for the same reason as TI (11.1): the commission on an in-place lease
was paid by the seller.

---

## 13. Operating Expenses

### 13.1 Recommendation: **Option C — compose Detailed's expense concepts with lease revenue, via a new contract**

Not Option A (reuse `DetailedOperatingInputs` directly) and not Option B
(a wholly separate expense model).

**Why not A:** `DetailedOperatingInputs` requires `gross_potential_rent`,
`vacancy_credit_loss_pct`, and `revenue_growth`. In Lease-Level, GPR is an
output, vacancy is modeled explicitly, and there is no single revenue growth
rate. Reusing the contract would force fabricating three values — exactly what
Anchor forbids — and would create two competing vacancy mechanisms.

**Why not B:** the six expense concepts (Property Taxes, Insurance, Utilities,
Repairs & Maintenance, Other Operating Expenses, Management Fee) and their
formulas are correct and should not be re-derived. Redefining them would risk
silent drift between modes on the same economic quantity.

**Option C** keeps the *formulas* identical and gives them a mode-appropriate
*input contract*. `LeaseLevelOperatingInputs` (4.6) carries the same six expense
concepts plus `expense_growth`, and adds only what Lease-Level genuinely needs
(`other_income_growth`, `credit_loss_pct`, `recoverable_expense_ratio`).

### 13.2 Formulas (identical to Detailed, restated at monthly resolution)

For hold year `y` containing month `m`:

```
FixedExpenseLine_y = FixedExpenseLine_1 * (1 + expense_growth)^(y-1)
FixedExpenseLine_m = FixedExpenseLine_y / 12.0

ManagementFee_m    = EGI_m * management_fee_pct

TotalOpex_m        = PropertyTaxes_m + Insurance_m + Utilities_m
                   + RepairsMaintenance_m + OtherOperatingExpenses_m
                   + ManagementFee_m

NOI_m              = EGI_m - TotalOpex_m
```

The five fixed lines are stated as annual amounts and **spread evenly across the
twelve months of their hold year** (`/12.0`). Expense seasonality (a lumpy
property-tax bill) is deliberately not modeled: it would change nothing at
annual aggregation, which is the only resolution any downstream consumer sees.

The management fee remains structurally different — a percentage of EGI, not a
grown dollar base — exactly as in Detailed.

### 13.3 Protecting existing Detailed behavior

`build_detailed_operating_projection` is not called, imported, modified, or
refactored by any Lease-Level code. `anchor.leasing` does not import
`anchor.engine.operating_projection` at all (guardrail **G-1**). The two modes
share a *specification*, not a code path. This is a deliberate, small amount of
duplicated arithmetic in exchange for a hard guarantee that a Lease-Level change
cannot alter a Detailed result.

Guardrail **G-2** additionally asserts the Detailed golden case is bit-identical
before and after every Sprint D gate.

---

## 14. Other Income

### 14.1 Recommendation: **property-level, not lease-level**

Parking, storage, signage, antenna, and miscellaneous income are a single
property-level annual amount (`other_income`) growing at `other_income_growth`,
spread evenly across the months of each hold year:

```
OtherIncome_y = other_income * (1 + other_income_growth)^(y-1)
OtherIncome_m = OtherIncome_y / 12.0
```

### 14.2 Why not lease-level

Attributing parking to individual leases requires a stall count per lease, a
stall rate, and a rule for what happens to those stalls during downtime — three
new inputs and one new convention, to move a small revenue line between two
buckets that sum to the same EGI. No competition case turns on it.

Two consequences, both accepted and disclosed:

1. Other income does **not** fall when a suite goes vacant. For a building whose
   parking income genuinely tracks occupancy, the analyst should reduce
   `other_income` manually and note it.
2. Percentage rent, being tenant-specific, has no home here and stays deferred
   (Section 25).

### 14.3 Placement

Above NOI, in the EGI build (10.2). Other income is **not** subject to
`credit_loss_pct` (which applies to lease revenue only) and is **not** part of
the recovery base.

---

## 15. Vacancy

### 15.1 Lease-Level has no general vacancy factor

Physical vacancy is **modeled, not assumed**:

- A suite with no lease covering month `m` contributes zero rent and its area to
  `vacant_area_by_month`.
- A suite in downtime contributes zero rent and its area to
  `vacant_area_by_month`.
- `physical_occupancy_by_month[m] = occupied_area_by_month[m] / property_area_sf`.

Applying any additional percentage vacancy allowance on top of this would
double-count. The contract makes that impossible by omitting the field (9.4).

### 15.2 The five vacancy concepts, and where each lands

| Concept | Lease-Level treatment |
|---|---|
| **Physical vacancy** | Modeled explicitly, per suite, per month. Reported, never assumed |
| **Downtime** | Modeled explicitly (Section 9). It *is* physical vacancy, with a cause |
| **Economic vacancy** | Emerges as an output: `1 - (actual base rent / gross potential rent at market)`. Never an input |
| **Collection / credit loss** | The single optional allowance: `credit_loss_pct`, applied to lease revenue (base rent net of free rent, plus recoveries). Default `0.0` |
| **Structural / general vacancy reserve** | **Deferred.** See 15.4 |

### 15.3 How this differs from Detailed

| | Detailed | Lease-Level |
|---|---|---|
| Input | `vacancy_credit_loss_pct` (required) | `credit_loss_pct` (optional, default `0.0`) |
| Base | Gross Potential Rent | Base rent net of free rent, plus recoveries |
| Covers | Vacancy **and** credit loss, blended | Credit loss **only** |
| Physical vacancy | Implicit inside the percentage | Explicit, modeled, reported per month |
| Can they both be active? | n/a | **No** — `vacancy_credit_loss_pct` does not exist on any Lease-Level contract |

An analyst moving a deal from Detailed to Lease-Level must **not** carry a 7%
`vacancy_credit_loss_pct` across as a 7% `credit_loss_pct`: the first is mostly
vacancy (now modeled) and the second is bad debt only. The UI must say so at the
point of entry, and the field label must read "Credit Loss," never "Vacancy &
Credit Loss."

### 15.4 Why a general vacancy reserve is deferred

Institutional models often add a "general vacancy" line topping total vacancy up
to a structural minimum, to avoid underwriting a building as 100% leased for ten
years. It is legitimate. It is also the single highest-risk double-count in the
entire model, because it is *designed* to overlap with modeled downtime and
requires a top-up rule (`max(0, structural_target - modeled_vacancy)`) that is
easy to state and easy to get wrong.

**Deferred to post-D4**, and only with an explicit top-up (never additive)
convention. Until then, an analyst wanting conservatism raises
`new_downtime_months` or lowers `renewal_probability` — both of which are
modeled, visible, and defensible.

---

## 16. Expense Recoveries (D3 architecture; not implemented)

### 16.1 What D3 must support

| Structure | D3 support | Convention |
|---|---|---|
| **NNN** | **Required** | Tenant reimburses its pro-rata share of recoverable operating expenses, with no stop or base year |
| **Gross** | **Required** | Tenant reimburses nothing. `Recovery = 0` |
| **Modified Gross (base-year stop)** | **Required** | Tenant reimburses its pro-rata share of recoverable expenses **above the base-year amount** |

Three structures, matching `LeaseType` (4.4), which D1 already captures.

### 16.2 The D3 formulas

```
ProRataShare(L)          = L.leased_area_sf / property_area_sf
RecoverableExpenses_m    = (TotalOpex_m - ManagementFee_m) * recoverable_expense_ratio

NNN:
  Recovery(L, m) = ProRataShare(L) * RecoverableExpenses_m

GROSS:
  Recovery(L, m) = 0.0

MODIFIED_GROSS:
  Recovery(L, m) = ProRataShare(L)
                 * max(0.0, RecoverableExpenses_m - BaseYearExpenses_m(L))
```

with, for every structure:

```
Recovery(L, m) = 0.0  whenever the suite is vacant or in downtime in month m
Recovery(L, m) is scaled by the partial-month factor f in a boundary month (9.3)
```

`recoverable_expense_ratio` is a single property-level fraction of non-management
operating expenses deemed recoverable. The management fee is excluded from the
recovery base because in most leases it is either non-recoverable or recovered
under a separate admin-fee provision — modeling it inside the base and *also*
computing it from EGI creates a circularity (recoveries raise EGI, which raises
the fee, which raises recoveries).

`BaseYearExpenses_m(L)` is the recoverable expense run-rate in the lease's base
year. **Recommended D3 convention:** the base year is hold Year 1 for every
in-place `MODIFIED_GROSS` lease, and the successor's first hold year for every
successor lease, stored on the lease as a derived scalar at construction. This is
an approximation for an in-place lease whose real base year predates
acquisition — flagged as **HD-7**.

### 16.3 Placement in the operating statement

Recoveries are **revenue above EGI**, on their own line:

```
Contractual Base Rent
  less Free Rent
  plus Expense Recoveries        <-- here
  plus Other Income
  less Credit Loss
= Effective Gross Income
  less Total Operating Expenses
= NOI
```

### 16.4 Management fee interaction — the ordering rule

Recoveries raise EGI; the management fee is a percentage of EGI; so recoveries
raise the management fee. That is correct and intended. The circularity is broken
by the ordering rule in 16.2: **the recovery base excludes the management fee.**
Computation order per month is therefore fixed and non-iterative:

```
1. Base rent, free rent, other income          (independent)
2. Fixed operating expense lines               (independent)
3. RecoverableExpenses_m                       (from step 2, no fee)
4. Recoveries per lease                        (from step 3)
5. Credit loss                                 (from steps 1 and 4)
6. EGI                                         (from steps 1, 4, 5)
7. Management fee                              (from step 6)
8. TotalOpex, then NOI                         (from steps 2, 7, 6)
```

No iteration, no fixed-point solve, one deterministic pass. This ordering must be
asserted by a D3 test.

### 16.5 Deferred recovery features

Admin fees on recoveries; gross-up to a stabilized occupancy; recovery caps
(annual and cumulative); recovery floors; per-category recoverability (taxes
recoverable but not utilities); expense stops expressed in `$/SF` rather than a
base year; separate operating and tax stops. Each is real; none is required to
underwrite a competition case credibly. All are additive to the D3 contracts.

---

## 17. Exit NOI

### 17.1 Recommendation

```
exit_noi = sum(NOI_m for m in 12H+1 .. 12H+12)
```

with rollover, downtime, free rent, and recoveries all live in that window.

### 17.2 Why this and not the alternatives

| Candidate | Verdict |
|---|---|
| **Annual Year-`H` NOI** | **Rejected.** Contradicts Anchor's existing frozen convention in both Quick and Detailed, and would value the property on trailing rather than forward income |
| **NTM after the sale date (months `12H+1..12H+12`)** | **Recommended.** It is the literal monthly restatement of `docs/financial_conventions.md`'s "next-twelve-month forward NOI after the final hold year," and of Detailed's `NOI_(H+1)` from a full Year-`H+1` build |
| **Year `H+1` NOI as a separate annual build** | Identical to the recommendation, since hold Year `H+1` *is* months `12H+1..12H+12`. Stated separately only to note they do not diverge |
| **Monthly-annualized forward NOI** (e.g. `12 × NOI` of month `12H+1`) | **Rejected.** A single month is hostage to whichever concession happens to fall in it. Annualizing a free-rent month understates value by an enormous margin |
| **A normalized / stabilized exit NOI** (rollover suppressed in the window) | **Rejected as the default**, offered as **HD-5**. It hides a real cost the buyer faces |

### 17.3 Consistency with Quick and Detailed

| Mode | `exit_noi` | Same convention? |
|---|---|---|
| Quick | `current_noi * (1 + noi_growth)^H` = `NOI_(H+1)` | Yes |
| Detailed | Full Year `H+1` line-item build | Yes |
| Lease-Level | Sum of monthly NOI, months `12H+1..12H+12` | Yes |

All three answer the identical question — "what does the property earn in the
twelve months after we sell it" — at their own resolution. **No existing
convention changes.** This directly resolves STOP CONDITION 4 of the brief:
exit NOI integrates without altering any existing financial convention.

### 17.4 The sharp edges, disclosed

1. **A rollover just after sale depresses exit value.** A lease expiring in month
   `12H+2` takes downtime inside the NTM window, cutting `exit_noi` and therefore
   `exit_value = exit_noi / exit_cap_rate`. This is economically real — a buyer
   does discount a building with an imminent expiry — but at a 6.5% cap rate a
   single month of lost NOI is magnified roughly 15×, so the effect is large and
   can look like a cliff in a sensitivity grid.
2. **Free rent inside the NTM window** understates exit NOI for the same reason.
3. **TI and LC in the NTM window are below NOI and are therefore not deducted
   from exit NOI, and are not paid by the seller** — the model is silent on a
   real cost the buyer will bear.

Mitigation for (3), and partial disclosure for (1) and (2):
`LeaseLevelOperatingProjection.exit_ntm_leasing_costs` reports the TI + LC
falling in months `12H+1..12H+12` as a **disclosed diagnostic that is never
deducted from anything**. The analyst sees it, can reason about the exit cap
rate in light of it, and is never surprised by it. The UI must surface it on the
Exit view.

### 17.5 Downstream extension required?

**None.** `exit_noi` remains a single float consumed by `calculate_exit_value`.
`exit_ntm_leasing_costs` lives on the Lease-Level projection envelope only and is
read by no engine calculation.

---

## 18. Property Aggregation

### 18.1 Canonical monthly categories

**Above NOI**, in strict statement order:

1. `contractual_base_rent_by_month` — gross scheduled base rent, all leases,
   in-place and successor. Never net of free rent
2. `free_rent_by_month` — positive number, subtracted
3. `expense_recoveries_by_month` (D3; `0.0` before then)
4. `other_income_by_month`
5. `credit_loss_by_month` — positive number, subtracted
6. `effective_gross_income_by_month` = 1 − 2 + 3 + 4 − 5
7. the six operating-expense lines, then `total_operating_expenses_by_month`
8. `noi_by_month` = 6 − 7

**Below NOI**, never touching any line above:

9. `tenant_improvements_by_month`
10. `leasing_commissions_by_month`

**Non-financial:**

11. `physical_occupancy_by_month`, `occupied_area_by_month`, `vacant_area_by_month`

### 18.2 Renewal and replacement rent are *not* separate revenue lines

The brief lists "renewal rent" and "replacement-tenant rent" as candidate
monthly categories. **Recommendation: do not create them.** Under the weighted-
assumption convention (8.2) there is no separable renewal or replacement rent —
there is one successor lease with one blended rent. Splitting it would require
un-blending an intentional average, and the split would be fictional.

What the analyst actually needs — *which* space rolled, *when*, *at what rent*,
*at what cost* — is delivered by `rollover_events` and by the per-lease
`LeaseSchedule`s, both of which are exact.

### 18.3 The above/below-NOI boundary is a hard invariant

```
NOI_m never depends on tenant_improvements_by_month or
leasing_commissions_by_month, at any month, under any input.
```

Guardrail **G-3** asserts this by perturbation: doubling every TI and LC input
must leave every `noi_by_month`, every `noi_by_year`, `exit_noi`,
`going_in_cap_rate`, every `dscr_by_year`, and `year_1_debt_yield`
**bit-identical**, while changing `unlevered_cash_flows`, `levered_cash_flows`,
`levered_cash_on_cash_by_year`, `unlevered_cash_yield_by_year`,
`cumulative_operating_distributions_by_year`, and both IRRs.

That single test simultaneously proves TI/LC are below NOI, that DSCR is
unaffected (matching lender practice), and that the leasing-cost channel is
genuinely wired into the cash-flow series.

### 18.4 Annual aggregation and the area invariant

```
AnnualLine_y = sum over m in 12(y-1)+1 .. 12y, ascending order    (5.3)
```

Invariant asserted every month:

```
occupied_area_by_month[m] + vacant_area_by_month[m] == property_area_sf
```

to `abs=1e-9`. This is the structural guarantee that the weighted-rollover
convention never produced fractional space (8.3), and it is the direct defense
against failure mode **FM-8**.

Validation additionally requires `sum(suite_area_sf) <= property_area_sf`, with
any shortfall interpreted as common area (Section 19).

---

## 19. Validation

### 19.1 ERROR vs WARNING

Anchor has no severity concept today (2.15). **Recommendation: add one**, as an
additive `IssueSeverity` StrEnum with `ERROR` as the default, so every existing
`InputIssue` construction and every existing test is unaffected. Lease-Level is
the first consumer. See **HD-6** for the alternative (errors-only).

- **ERROR** — the economics are wrong or undefined. Analysis is refused.
- **WARNING** — the economics are computable and defensible, but a convention
  the analyst should know about is being applied. Analysis proceeds; the warning
  is surfaced in the UI and carried on the result envelope.

### 19.2 ERROR rules

| Rule | Category |
|---|---|
| `property_area_sf <= 0` | `OUT_OF_DOMAIN_VALUE` |
| `analysis_start_date` is not the first day of a month | `INVALID_ANALYSIS_START_DATE` |
| `suite_area_sf <= 0` | `OUT_OF_DOMAIN_VALUE` |
| `leased_area_sf <= 0` | `OUT_OF_DOMAIN_VALUE` |
| `leased_area_sf != suite_area_sf` (D1–D3) | `LEASE_AREA_MISMATCH` |
| Duplicate `suite_id` or duplicate `lease_id` | `DUPLICATE_FIELD_ID` |
| `Lease.suite_id` matches no `Suite` | `UNKNOWN_SUITE_REFERENCE` |
| `lease_expiration_date < rent_commencement_date` | `LEASE_EXPIRES_BEFORE_COMMENCEMENT` |
| `lease_start_date > rent_commencement_date` | `LEASE_POSSESSION_AFTER_RENT_START` |
| Lease expires before `analysis_start_date` | `LEASE_EXPIRED_BEFORE_ANALYSIS_START` |
| Two leases on one suite with overlapping month ranges | `OVERLAPPING_LEASES_IN_SUITE` |
| `base_rent_psf < 0` | `OUT_OF_DOMAIN_VALUE` |
| `escalation_pct <= -1` | `OUT_OF_DOMAIN_VALUE` |
| `renewal_probability` outside `[0, 1]` | `OUT_OF_DOMAIN_VALUE` |
| Any downtime or free-rent months `< 0` | `OUT_OF_DOMAIN_VALUE` |
| Any TI `$/SF` `< 0`; any LC `%` outside `[0, 1]` | `OUT_OF_DOMAIN_VALUE` |
| `renewal_term_months < 1` or `new_term_months < 1` | `OUT_OF_DOMAIN_VALUE` |
| `sum(suite_area_sf) > property_area_sf` | `LEASED_AREA_EXCEEDS_PROPERTY_AREA` |
| A lease expires in-window with no resolvable market leasing assumptions (D2) | `MISSING_MARKET_LEASING_ASSUMPTIONS` |
| A vacant suite exists with no resolvable market leasing assumptions (D2) | `MISSING_MARKET_LEASING_ASSUMPTIONS` |
| Any non-finite value anywhere | `NON_FINITE_VALUE` |

### 19.3 WARNING rules

| Rule | Category | Why a warning and not an error |
|---|---|---|
| `rent_commencement_date` is not the 1st of a month, or `lease_expiration_date` is not the last day | `LEASE_DATE_NOT_MONTH_ALIGNED` | Whole-month recognition applies; the result is computable and the bias is bounded at one month |
| `sum(suite_area_sf) < property_area_sf` | `AREA_SHORTFALL_TREATED_AS_COMMON_AREA` | Legitimate (lobbies, corridors, mechanical), but occupancy is then computed on a denominator including non-leasable area, which the analyst must intend |
| A lease commences after month `12H+12` | `LEASE_STARTS_AFTER_HORIZON` | Harmless; contributes nothing |
| A lease's `last_rent_month` exceeds `12H+12` | `LEASE_EXTENDS_BEYOND_HORIZON` | Expected and normal; noted so the analyst knows the term is truncated for revenue but not for the LC basis (12.2) |
| A rollover's commencement month falls inside the exit NTM window | `ROLLOVER_IN_EXIT_NTM_WINDOW` | Materially affects `exit_noi` (17.4); the analyst must see it |
| `0 < renewal_probability < 1` on any suite | `WEIGHTED_ROLLOVER_APPLIED` | Discloses that the successor is an economic blend corresponding to no single real outcome (8.3) |
| `credit_loss_pct > 0.10` | `UNUSUALLY_HIGH_CREDIT_LOSS` | Usually a Detailed `vacancy_credit_loss_pct` carried across by mistake (15.3) |

### 19.4 Determinism

Issue ordering follows the existing convention exactly: unknown identifiers
first, then missing required values, then per-record issues in
`(suite_id, lease_id, canonical field order)` order. Every `InputIssue` for a
lease carries the lease's row/index so the UI can anchor it. No silent defaults:
a missing required value is an issue, never a substituted zero.

---

## 20. Missing Data

### 20.1 The rule

**Anchor never fabricates a lease term.** A missing value is reported as
missing, and the analyst supplies it — with the fact that they supplied it
recorded.

### 20.2 Per-field behavior

| Missing field | Behavior |
|---|---|
| `lease_expiration_date` | **ERROR.** There is no defensible default; a lease with no end is not a lease |
| `rent_commencement_date` | **ERROR** if the lease is not in place at `analysis_start_date`. For an in-place lease, the analyst may set it to `analysis_start_date` with `escalation_basis = NONE` and an explicit note — a decision the analyst makes, not the engine |
| `base_rent_psf` | **ERROR** |
| `leased_area_sf` | **ERROR** |
| `escalation_pct` | **Analyst-supplied, defaulting to `0.0` at the approval UI only.** Flat rent is a real, common, conservative lease term; but the value must be *shown as* `0.0` in the form for the analyst to accept, never silently applied behind an empty field |
| `lease_type` | **Analyst-supplied.** No engine default. Required in D1 even though inert until D3, precisely so the analyst confronts it once with the document in hand |
| `market_rent_psf` | **ERROR at D2** if any rollover or vacant suite exists in-window; harmless otherwise |
| `renewal_probability` | **ERROR at D2.** Every plausible default (0, 0.5, 1) implies a materially different deal |
| downtime / TI / LC | **ERROR at D2** wherever a rollover occurs in-window |

### 20.3 Provenance for analyst-supplied values

Anchor already has the exact mechanism: `EvidenceStatus`
(`stated | interpreted | conflicting | unverifiable | missing`) plus verified
`Provenance` (`ingestion/contracts.py`), gated by the Analyst Approval Gate.

Lease-Level extends it with **one additional status: `analyst_supplied`** — a
value with no document support that the analyst entered deliberately. It is
distinct from `interpreted` (the model inferred it from the document) and from
`missing` (nothing was provided at all).

This matters because a competition rent roll routinely states area, rent, and
expiration but never states renewal probability, downtime, TI, or LC. Under the
current five states, every one of those would read as `missing` forever, even
after the analyst supplied it. `analyst_supplied` is what lets the review UI show
"12 of 20 fields document-backed, 8 analyst-supplied" — which is exactly the
provenance summary a judge asks about.

**This is an additive sixth member of `EvidenceStatus`.** `CONCEPTS.md` states
"Exactly these five states — no other value is valid," so this is a deliberate,
flagged amendment to a documented concept, not an incidental change — see
**HD-8**.

---

## 21. Ingestion Implications (design only; nothing implemented)

### 21.1 The structural gap

Both existing extraction contracts are **flat and fixed-arity** (2.13). A rent
roll is **variable-arity**. `ExtractionResult` cannot express "N leases."

### 21.2 Proposed candidate shape

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseCandidateRow:
    """Proposed values for ONE lease. Every field is FieldCandidates:
    zero candidates means missing, never a fabricated value."""
    row_index: int                      # source order; the analyst's anchor
    suite_label: FieldCandidates
    tenant_name: FieldCandidates
    leased_area_sf: FieldCandidates
    rent_commencement_date: FieldCandidates
    lease_expiration_date: FieldCandidates
    base_rent_psf: FieldCandidates
    escalation_pct: FieldCandidates
    lease_type: FieldCandidates

@dataclass(frozen=True, slots=True, kw_only=True)
class RentRollExtractionResult:
    property_area_sf: FieldCandidates
    lease_rows: tuple[LeaseCandidateRow, ...]
```

`FieldCandidates.value` stays a free-form string exactly as proposed, with
verified `Provenance`, exactly as today. Every existing invariant holds
per-field; only the *arity* is new.

### 21.3 Approval boundary

Unchanged in principle, extended in granularity:

```
Rent roll document
  -> RentRollExtractionResult (N candidate rows, each field provenance-verified)
  -> Analyst reviews EVERY row, EVERY field: approve / edit / reject
  -> Approved rows become Suite + Lease contracts
  -> validate_lease_level_inputs
  -> Deterministic engine
```

Non-negotiable rules for D5+:

1. **Row-level approval is per-field, not per-row.** A row where area is
   `stated` and escalation is `missing` must not be approvable wholesale.
2. **A rejected row produces no lease.** It never becomes a
   zero-rent placeholder.
3. **Market leasing assumptions are never extracted.** No OM states renewal
   probability, downtime, TI, or LC as fact; a model proposing them would be
   inventing underwriting judgment, which the core product principle forbids.
   They are always `analyst_supplied`.
4. **The classifier never receives the raw document bytes** — the existing
   `StructuredDocument`-anchors-only rule, with its existing data-flow spy test
   (`tests/test_ingestion_architecture.py`), extends unchanged.
5. **Dates arrive as strings and are normalized deterministically in Python**,
   never by the model. A model returning "month 14" instead of "2027-06-30"
   would be doing lease-timeline arithmetic.

### 21.4 Excel rent-roll ingestion

The new reader shape (F-2) is a **row-per-lease** worksheet:

```
Meta sheet:  anchor_schema = "lease_level_acquisition", schema_version = "1.0"
Suites sheet:   Suite ID | Suite Label | Suite Area SF | Market Rent PSF
Leases sheet:   Lease ID | Suite ID | Tenant | Leased Area SF |
                Rent Commencement | Lease Expiration | Base Rent PSF |
                Escalation % | Lease Type | Free Rent Months
Inputs sheet:   the existing Field ID / Input / Value / Unit key-value table,
                for AcquisitionTerms + LeaseLevelOperatingInputs +
                property-level MarketLeasingAssumptions
```

The `Inputs` sheet reuses the existing reader wholesale. Only `Suites` and
`Leases` need the new tabular reader, whose issues use the existing
`InputIssue.row`/`.cell` fields — already present for exactly this purpose.

---

## 22. Persistence Implications (design only; no migration)

### 22.1 What needs persisting

`AcquisitionTerms`, `LeaseLevelPropertyInputs`, `LeaseLevelOperatingInputs`,
property-level `MarketLeasingAssumptions`, the `Suite` set (with overrides), the
`Lease` set, `deal_context`, and the analysis/AI snapshots.

**Never persisted as source of truth:** successor leases, `RolloverEvent`s, any
schedule, or any projection. All are derived; all are recomputed by the engine
on open. The snapshot remains a *cache*, exactly as
`docs/detailed_operating_model_v2_1_architecture.md` §6 and
`deals/contracts.py`'s docstring already require.

### 22.2 Likely schema shape

Following the existing two-table precedent, schema version **5** would add:

- `lease_level_deals` — one row per deal, mirroring `detailed_deals`' columns
  (name, context, snapshot JSON + schema version + fingerprint, timestamps),
  plus JSON-serialized `LeaseLevelPropertyInputs`,
  `LeaseLevelOperatingInputs`, and the property `MarketLeasingAssumptions`.
- `lease_level_suites` — `(deal_id, suite_id, ...)`, foreign-keyed, ordered.
- `lease_level_leases` — `(deal_id, lease_id, suite_id, ...)`, foreign-keyed,
  ordered, `origin = IN_PLACE` only.

Two design points:

1. **Suites and leases are relational rows, not one JSON blob.** They are
   variable-arity, individually editable, individually validated, and
   individually shown in the UI. A blob would make row-level diffs and
   row-level issue anchoring impossible.
2. **`_migrate()` extends unchanged in shape** — additive `CREATE TABLE IF NOT
   EXISTS` plus `PRAGMA table_info`-driven column adds. No existing table is
   altered; no Quick or Detailed row is touched or rewritten.

### 22.3 Snapshot and fingerprint implications

- `_ANALYSIS_SNAPSHOT_SCHEMA_VERSION` bumps to `2` **if and only if** HD-1 adds
  `leasing_costs_by_year` to `AcquisitionResults`. The existing decode path
  already treats a version mismatch as "snapshot absent," so old Quick and
  Detailed snapshots degrade to a re-run rather than an error. That is the
  designed behavior, and it is why HD-1 is safe.
- The deal fingerprint (`deals/fingerprint.py`) must cover **every** suite and
  lease field, in a stable order, or an edited rent roll would silently reuse a
  stale snapshot. This is the highest-risk persistence detail in D5.

---

## 23. UI Implications (design only; no frontend change)

### 23.1 Where Lease-Level lives

`Underwrite` workspace → a third `OperatingMode`. The existing five tabs are
retained; only the **Operations** tab and the **Results** sub-navigation change,
both through mechanisms that already exist:

| Tab | Lease-Level content |
|---|---|
| **Acquisition** | Unchanged (`AcquisitionTerms` fields) |
| **Operations** | Four sub-views via the existing `FieldSection.view` mechanism: **Rent Roll**, **Market Leasing**, **Expenses**, **Other Income** |
| **Debt** | Unchanged |
| **Exit** | Unchanged, plus the `exit_ntm_leasing_costs` disclosure (17.4) and the rollover-in-NTM warning |
| **Results** | `resultsViewsFor('lease_level')` returns Summary, Cash Flow, Owner Returns, Operating Statement, **Rollover Schedule** |

`resultsViewsFor(mode)` is *already* mode-derived (2.14), so adding a
`rollover-schedule` view for one mode is the exact extension the function was
written for.

### 23.2 Rent Roll is the one genuinely new surface

Everything else is more fields in the existing `AssumptionFieldGrid`. The rent
roll is a **table with row add/edit/delete** — a component shape the app does not
have. Design constraints, all inherited from Sprint C:

- **It must not become a long vertical page.** A 20-lease rent roll in a
  full-height scrolling grid violates the navigation-over-scrolling philosophy
  (`docs/workspace_ux_visual_system_v3_spec.md`). Recommended: a compact,
  independently scrolling table region inside the tab's viewport, with row
  editing in a side panel or inline expansion — never a page that grows with the
  lease count.
- **Every tab stays mounted-but-`hidden`** (`UnderwriteWorkspace.tsx`), so an
  in-progress lease row survives a tab switch. This is structural, not something
  the new component must remember.
- **Per-row validation issues anchor to their row** (using `InputIssue.row`),
  shown inline, not collected in a single banner at the top.
- **The Live Case rail keeps working**: it reads `AcquisitionResults`, which is
  unchanged in shape.

### 23.3 The frontend calculates nothing

`web/src` must not compute a rent schedule, a month index, an escalated rent, a
rollover date, a TI amount, or an LC amount — not even for a preview. Date→month
normalization is an economic decision (Section 5.4) and belongs in Python. The
frontend sends dates; the backend returns schedules. Guardrail **G-7**.

The one permitted frontend computation is the existing pattern: presentational
formatting of already-computed values (`web/src/format.ts`).

---

## 24. Input Precedence

Every inheritable assumption resolves through exactly one chain. Where an
override is `None`, resolution falls through; there is no partial merge except
where explicitly stated.

### 24.1 Market rent level

```
Suite.market_leasing_override.market_rent_psf   (if override is not None)
  > Suite.market_rent_psf                        (if not None)
  > MarketLeasingAssumptions.market_rent_psf     (property default; always present)
```

### 24.2 Every other market leasing assumption

(growth, renewal probability, terms, downtimes, free rent, TI, LC, successor
escalation)

```
Suite.market_leasing_override.<field>            (if override is not None)
  > MarketLeasingAssumptions.<field>             (property default)
```

**`market_leasing_override` is all-or-nothing**: when a suite supplies one, that
record is used in full and no field falls through to the property default. A
partial per-field merge would make "which value applied" unanswerable without
re-running the resolver, which is exactly the ambiguity this section exists to
eliminate. `Suite.market_rent_psf` is the single, deliberate exception in 24.1,
because overriding just the rent level is the overwhelmingly common case.

### 24.3 Renewal rent

```
resolved.renewal_rent_psf grown to commencement month     (if not None)
  > MarketRentPSF(commencement) * (1 + resolved.renewal_rent_spread)
```

per 4.5.1 and **HD-4**.

### 24.4 Lease-level values always win over any assumption

A `Lease`'s own `base_rent_psf`, `escalation_pct`, `free_rent_months`,
`lease_type`, and dates are contractual facts. No market leasing assumption ever
overrides them. Market leasing assumptions apply **only** to successor leases the
rollover engine creates, and to vacant suites being leased up.

### 24.5 Resolution is computed once and logged

The resolver runs once per suite, at the start of the rollover pass, producing a
`ResolvedMarketLeasing` value recorded on every `RolloverEvent` it drives. An
analyst can therefore always answer "which assumption applied to this rollover,
and where did it come from" from the output alone.

---

## 25. Competition-Ready Scope

### 25.1 MUST HAVE (D1–D4)

- Rent roll: suites, leases, area, contractual rent, dates
- Fixed % annual escalation on lease anniversary
- Correct monthly timeline: commencement, expiration, in-place leases, future
  leases, mid-hold events
- Market rent with growth; property default + suite override
- Lease expiration and rollover with renewal probability
- Downtime
- Free rent
- TI and LC, below NOI
- Expense recoveries: NNN, Gross, Modified Gross (base-year stop)
- Property-level operating expenses and management fee
- Explicit physical occupancy and vacancy, no double count
- Correct exit NOI on the NTM convention
- Full integration with acquisition / debt / returns
- A rollover audit trail

### 25.2 SHOULD HAVE (post-D4, pre-competition if time allows)

- Explicit rent steps (dated rent levels) — the most likely gap in a real
  abstract
- Calendar-year escalation basis
- A general vacancy top-up with an explicit non-additive rule (15.4)
- A per-lease renewal-probability override (as opposed to per-suite)
- Recovery caps and admin fees
- Lease-level sensitivity dimensions (market rent, renewal probability)

### 25.3 LATER / ARGUS-LIKE — deliberately excluded

Percentage rent; CPI indexation; option periods; expansion, contraction and
termination rights; tenant credit ratings and credit-adjusted cash flows;
sub-suite demising and partial-space rollover; TI draw schedules; gross-up to
stabilized occupancy; per-category recoverability; separate operating and tax
stops; development and construction phasing; portfolio rollup; debt sized on
lease-level covenants; monthly IRR or monthly distributions; property tax
reassessment on sale; depreciation and income taxes; waterfalls and promote
structures.

### 25.4 The scope test

For each candidate feature, ask: *would a judge's question be unanswerable
without it?*

- "What happens when the anchor tenant's lease expires in Year 3?" — needs
  rollover, downtime, TI, LC. **Must have.**
- "What is your mark-to-market?" — needs market rent vs in-place rent.
  **Must have.**
- "How did you handle the CPI escalator in the ground-floor lease?" — answerable
  with "we normalized it to a 2.5% fixed escalation and disclosed the
  assumption." **Not needed.**
- "What is the promote to the GP at a 20% IRR?" — a different model entirely.
  **Not needed.**

Competition-ready means every lease-level number is *correct and defensible*,
not that every ARGUS feature is present.

---

## 26. Failure Modes — Risk Register

Ordered by expected damage. Each has a named guardrail or golden case.

| ID | Failure | Why it is plausible | Detection |
|---|---|---|---|
| **FM-1** | **Double-counted vacancy** — a general vacancy % applied on top of modeled downtime | Habit carried from Detailed; a Detailed deal converted to Lease-Level | The field does not exist on any Lease-Level contract (9.4). Guardrail **G-4** |
| **FM-2** | **Rent continues after expiration** — an off-by-one on `last_rent_month` | Inclusive vs exclusive month bounds is the single most common indexing error | **Golden 3** (mid-hold expiration) asserts the exact last paying month and the exact first zero month |
| **FM-3** | **Market rent applied too early** — successor rent set at the expiration month instead of after downtime | The two months are adjacent and easy to conflate | **Golden 8** asserts the successor's rent equals `MarketRentPSF(commencement)`, not `MarketRentPSF(expiration)` |
| **FM-4** | **Escalations applied at the wrong date** — an in-place lease's escalation index restarted at Month 1 instead of measured from its true `rent_commencement_date` | Clamping `first_rent_month` to 1 for aggregation (6.4) invites clamping it for escalation too | **Golden 2b**: a lease commenced 2 years pre-acquisition must be on step `k=2` in Month 1 |
| **FM-5** | **TI or LC reduces NOI** | A single misplaced line in the expense build | Guardrail **G-3**: doubling TI/LC leaves NOI, DSCR, and debt yield bit-identical (18.3) |
| **FM-6** | **Free rent and downtime double-counted** — a month counted as both | They are adjacent and both reduce rent to zero | Guardrail **G-5**: disjoint month-index sets. **Golden 9** asserts the exact boundary month |
| **FM-7** | **LC computed on the wrong basis** — net of free rent, or excluding escalations, or truncated at the horizon | All three are defensible-sounding; only one matches the stated convention | **Golden 9** pins the LC dollar amount from a hand-computed rent sum (12.2) |
| **FM-8** | **Fractional physical occupancy** from probability weighting | Would follow immediately from cash-flow-level expected-value weighting | Prevented by the weighted-*assumption* convention (8.3). Asserted by the area invariant in 18.4 |
| **FM-9** | **Recoveries continue while the suite is vacant** | The recovery formula is per-lease and it is easy to forget the occupancy gate | D3 test: recoveries are exactly `0.0` in every downtime month (16.2) |
| **FM-10** | **Expenses stop during vacancy** | Symmetric error to FM-9, and intuitively appealing | D3/D4 test: `total_operating_expenses_by_month` is unchanged by a suite going vacant, except for the management fee's EGI dependence (9.2) |
| **FM-11** | **TI/LC charged on in-place leases** | Applying market leasing assumptions uniformly to every lease | **Golden 1**: a single in-place lease over a full hold produces exactly zero TI and zero LC |
| **FM-12** | **Terminal NOI from the wrong period** — Year `H` instead of the NTM window, or a single annualized month | Three plausible readings of "exit NOI" (17.2) | **Golden 10** asserts `exit_noi` against a hand-summed months `12H+1..12H+12` |
| **FM-13** | **Future rollover ignored** — a successor lease not itself rolled when it expires in-window | Easy to generate one successor and stop | **Golden 10**: a short successor term forces a second rollover before exit |
| **FM-14** | **Quick or Detailed silently changed** by the `leasing_costs_by_year` threading | Touching a shared function | Guardrail **G-2**: both golden cases bit-identical to `fffdf34` |
| **FM-15** | **Monthly data leaking downstream** — a `_by_month` tuple reaching the annual IRR solver | The projection carries both resolutions | Guardrail **G-6**: no module outside `anchor.leasing` reads any `_by_month` field |
| **FM-16** | **Area over-allocation** — leases summing to more than `property_area_sf` | A rent roll with a transcription error | Validation ERROR (19.2) plus the per-month area invariant (18.4) |
| **FM-17** | **Non-deterministic ordering** — iterating a `dict` or `set` of leases and summing in varying order | Python `set` iteration order is not stable across runs for some key types | All lease collections are `tuple`, ordered at construction; all summation is ascending-month. A repeated-run determinism test asserts bit-identical output across 100 runs |

---

## 27. Golden Cases

Shared conventions for every case below unless overridden:

```
analysis_start_date = 2026-01-01     (so Month 1 = Jan 2026)
property_area_sf    = 10,000
hold_period H       = 5              (projection window = months 1..72)
purchase_price      = 10,000,000
exit_cap_rate       = 0.065
ltv = 0.0, interest_rate = 0.0, amortization = 30, io_period = 0
acquisition_cost_pct = financing_fee_pct = disposition_cost_pct = 0.0
annual_capex_reserve = 0.0
```

Zero leverage and zero transaction costs are deliberate: they isolate the lease
engine, so any drift is unambiguously lease-level. Leverage is exercised
separately by the existing V2 golden case, which remains untouched.

Operating assumptions for cases that reach NOI (Goldens 7–10): all six expense
lines `0.0`, `management_fee_pct = 0.0`, `other_income = 0.0`,
`credit_loss_pct = 0.0`, `recoverable_expense_ratio = 0.0`. So `NOI = EGI =
base rent − free rent` and every case is hand-checkable. Expense integration is
proven separately by a D4 case that reuses Detailed's already-verified expense
golden numbers.

Tolerance for every assertion: `pytest.approx(expected, rel=0.0, abs=1e-9)`.

---

### GOLDEN 1 — Single lease, no escalation, full hold *(D1)*

**Inputs**

| | |
|---|---|
| Suite | `S1`, 10,000 SF |
| Lease | `L1`, `S1`, 10,000 SF |
| Rent commencement | 2024-01-01 (2 years pre-acquisition) |
| Expiration | 2033-12-31 (beyond the window) |
| `base_rent_psf` | `30.00` |
| `escalation_basis` | `NONE` |

**Expected**

```
first_rent_month = -23  (raw)  ->  clamped to 1 for the schedule
last_rent_month  = 96   (raw)  ->  truncated at 72
BaseRent(m) = 30.00 * 10,000 / 12 = 25,000.00   for every m in 1..72
base_rent_by_year[y] = 300,000.00               for y = 1..5
occupied_area_by_month[m] = 10,000              for every m
vacant_area_by_month[m]   = 0                   for every m
physical_occupancy_by_month[m] = 1.0            for every m
tenant_improvements_by_year = (0,0,0,0,0)
leasing_commissions_by_year = (0,0,0,0,0)
exit_noi (D4) = 12 * 25,000.00 = 300,000.00
going_in_cap_rate = 300,000 / 10,000,000 = 0.03
```

**Assertions:** every month exactly `25,000.00`; zero TI and zero LC (FM-11);
truncation past month 72 produces no error; `occupied + vacant ==
property_area_sf` in all 72 months.

---

### GOLDEN 2 — Annual rent escalation *(D1)*

**2a — commences at acquisition.** As Golden 1 but rent commencement
`2026-01-01`, `escalation_pct = 0.03`, `escalation_basis = LEASE_ANNIVERSARY`.

```
first_rent_month = 1;  k = floor((m - 1) / 12)

Year 1 (m 1-12)   k=0   PSF 30.000000   monthly 25,000.000000   annual 300,000.000000
Year 2 (m 13-24)  k=1   PSF 30.900000   monthly 25,750.000000   annual 309,000.000000
Year 3 (m 25-36)  k=2   PSF 31.827000   monthly 26,522.500000   annual 318,270.000000
Year 4 (m 37-48)  k=3   PSF 32.781810   monthly 27,318.175000   annual 327,818.100000
Year 5 (m 49-60)  k=4   PSF 33.765264.. monthly 28,137.720250   annual 337,652.643000
NTM   (m 61-72)   k=5   PSF 34.778222.. monthly 28,981.851858   annual 347,782.222290
exit_noi = 347,782.222290
```

**2b — commenced two years before acquisition (FM-4 guard).** Identical, but
rent commencement `2024-01-01`.

```
raw first_rent_month = -23;  k = floor((m - (-23)) / 12) = floor((m + 23) / 12)
m = 1  ->  k = 2       PSF 31.827000    monthly 26,522.500000
```

**Assertion:** Month 1 rent is `26,522.50`, **not** `25,000.00`. Escalation is
measured from the true commencement date, never from the clamped schedule start.

---

### GOLDEN 3 — Mid-hold expiration *(D1)*

As Golden 1, but expiration `2028-06-30` (month 30), no rollover (D1).

```
last_rent_month = 30
BaseRent(m) = 25,000.00   for m in 1..30
BaseRent(m) = 0.0         for m in 31..72

base_rent_by_year = (300,000.00, 300,000.00, 150,000.00, 0.0, 0.0)
occupied_area_by_month[m] = 10,000  for m <= 30, else 0
physical_occupancy_by_month[30] = 1.0 ; [31] = 0.0
```

**Assertions:** month 30 pays in full, month 31 pays exactly `0.0` (FM-2);
Year 3 is exactly half a year of rent; the area invariant holds in every month.

---

### GOLDEN 4 — Lease commencement during the hold *(D1)*

Suite `S1` 10,000 SF; lease `L1` with rent commencement `2027-04-01` (month 15),
expiration `2032-03-31`, `base_rent_psf = 30.00`, no escalation.

```
BaseRent(m) = 0.0         for m in 1..14
BaseRent(m) = 25,000.00   for m in 15..72

base_rent_by_year = (0.0, 250,000.00, 300,000.00, 300,000.00, 300,000.00)
```

Year 2 = months 13–24 = 10 paying months × 25,000 = `250,000.00`.

**Assertions:** the year-boundary split is exact; occupancy is `0.0` in months
1–14 and `1.0` from 15.

---

### GOLDEN 5 — Two tenants, different expirations *(D1)*

| Suite | Area | Lease | Rent PSF | Escalation | Commencement | Expiration |
|---|---|---|---|---|---|---|
| `S1` | 6,000 | `L1` | `30.00` | `0.03` anniversary | 2026-01-01 | 2030-12-31 (m 60) |
| `S2` | 4,000 | `L2` | `25.00` | `NONE` | 2026-01-01 | 2027-12-31 (m 24) |

```
L1: monthly = 30.00 * (1.03)^k * 6,000 / 12 = 15,000.00 * (1.03)^k
      m 1-12  15,000.000000     m 13-24 15,450.000000
      m 25-36 15,913.500000     m 37-48 16,390.905000
      m 49-60 16,882.632150     m 61-72 0.0            (expired at m 60)
L2: monthly = 25.00 * 4,000 / 12 = 8,333.333333...     m 1-24, else 0.0

property base_rent_by_year:
  Y1 = 12*(15,000.000000 + 8,333.333333...) = 280,000.000000
  Y2 = 12*(15,450.000000 + 8,333.333333...) = 285,400.000000
  Y3 = 12* 15,913.500000                    = 190,962.000000
  Y4 = 12* 16,390.905000                    = 196,690.860000
  Y5 = 12* 16,882.632150                    = 202,591.585800
  NTM= 0.0

occupancy: 1.0 in months 1-24 ; 0.6 in months 25-60 ; 0.0 in months 61-72
```

`8,333.333333...` is `25.00 * 4000 / 12` in full double precision; the test
computes it the same way rather than typing a truncated literal.

**Assertions:** the two leases escalate independently; property occupancy steps
`1.0 → 0.6 → 0.0` at exactly months 25 and 61; the area invariant holds
throughout.

---

### GOLDEN 6 — Vacant suite *(D1)*

Suites `S1` 7,000 SF (leased) and `S2` 3,000 SF (no lease at all).
`L1` on `S1`: `30.00` PSF, no escalation, months 1–72.

```
BaseRent(m) = 30.00 * 7,000 / 12 = 17,500.00   for every m
base_rent_by_year[y] = 210,000.00              for y = 1..5
occupied_area_by_month[m] = 7,000
vacant_area_by_month[m]   = 3,000
physical_occupancy_by_month[m] = 0.7
```

**Assertions:** a suite with zero leases is legal in D1 and contributes exactly
`0.0` revenue and `3,000` SF of vacancy in every month; no synthetic
"vacant lease" appears in `lease_schedules`; the area invariant holds.

---

### GOLDEN 7 — Lease renewal, `p = 1.0` *(D2)*

Suite `S1` 10,000 SF. `L1`: `30.00` PSF, no escalation, months 1–24
(expires 2027-12-31).

Market leasing: `market_rent_psf = 36.00`, `market_rent_growth = 0.00`,
`renewal_probability = 1.0`, `renewal_rent_spread = -0.10`,
`renewal_term_months = 60`, `renewal_downtime_months = 0.0`,
`renewal_free_rent_months = 0.0`, `renewal_ti_psf = 5.00`,
`renewal_lc_pct = 0.03`, `successor_escalation_pct = 0.0`.
Every new-tenant assumption is set to a distinct value to prove it is unused.

```
expiration_month = 24
downtime = 1.0*0.0 + 0.0*(new) = 0.0
commencement_month = 24 + 1 + ceil(0.0) = 25
successor_rent_psf = 1.0 * (36.00 * (1 - 0.10)) + 0.0 * 36.00 = 32.40
last_rent_month(L') = 25 + 60 - 1 = 84  -> truncated at 72

BaseRent(m) = 25,000.00                        m 1-24
BaseRent(m) = 32.40 * 10,000 / 12 = 27,000.00  m 25-72

base_rent_by_year = (300,000, 300,000, 324,000, 324,000, 324,000)
exit_noi = 12 * 27,000.00 = 324,000.00

TI = 5.00 * 10,000 = 50,000.00, entirely in month 25 -> Year 3
LC basis = full 60-month contractual term = 60 * 27,000.00 = 1,620,000.00
LC  = 0.03 * 1,620,000.00 = 48,600.00, entirely in month 25 -> Year 3

tenant_improvements_by_year = (0, 0, 50,000.00, 0, 0)
leasing_commissions_by_year = (0, 0, 48,600.00, 0, 0)
occupancy = 1.0 in every month
```

**Assertions:** no downtime month exists; the LC basis uses all 60 contractual
months even though 12 fall past the window (12.2 / FM-7); TI and LC land in
Year 3 and leave `noi_by_year` untouched (FM-5); no new-tenant assumption
influences any number.

---

### GOLDEN 8 — Vacate, downtime, replacement tenant, `p = 0.0` *(D2)*

Identical to Golden 7 except `renewal_probability = 0.0`, and:
`new_downtime_months = 6.0`, `new_term_months = 60`, `new_ti_psf = 20.00`,
`new_lc_pct = 0.06`, `new_free_rent_months = 0.0`,
`market_rent_growth = 0.03`.

```
expiration_month = 24
downtime = 6.0  ->  n = 6, f = 0
commencement_month = 24 + 1 + 6 = 31
MarketRentPSF(31) = 36.00 * (1.03)^floor((31-1)/12) = 36.00 * (1.03)^2 = 38.192400
successor_rent_psf = 38.192400
monthly = 38.192400 * 10,000 / 12 = 31,827.000000
last_rent_month = 31 + 60 - 1 = 90  -> truncated at 72

BaseRent(m) = 25,000.000000    m 1-24
BaseRent(m) = 0.0              m 25-30      (six downtime months)
BaseRent(m) = 31,827.000000    m 31-72

base_rent_by_year:
  Y1 = 300,000.000000
  Y2 = 300,000.000000
  Y3 (m 25-36) = 6 * 0 + 6 * 31,827.000000 = 190,962.000000
  Y4 = 381,924.000000
  Y5 = 381,924.000000
exit_noi = 381,924.000000

TI = 20.00 * 10,000 = 200,000.000000  in month 31 -> Year 3
LC basis = 60 * 31,827.000000 = 1,909,620.000000
LC = 0.06 * 1,909,620.000000 = 114,577.200000  in month 31 -> Year 3

occupancy = 1.0 (m 1-24), 0.0 (m 25-30), 1.0 (m 31-72)
vacant_area_by_month = 10,000 in months 25-30
```

**Assertions:** market rent is measured at month 31, not month 24 (FM-3 — the
month-24 value `36.00 * 1.03 = 37.08` must not appear anywhere); exactly six
zero-rent months; occupancy returns to `1.0` at month 31; TI and LC land at
commencement, not at expiration.

**8b — fractional downtime.** `new_downtime_months = 5.5`:

```
n = ceil(5.5) = 6, f = 6 - 5.5 = 0.5
commencement_month = 31
BaseRent(m) = 0.0 for m 25-30 ... EXCEPT month 30? No:
  months 25..29 are fully vacant (n-1 = 5 months)
  month 30 is the LAST downtime month
  month 31 is commencement, carrying factor f = 0.5
```

Restating precisely against 9.3 with `e = 24`, `n = 6`, `f = 0.5`: the downtime
block is months `25..30`; months `25..29` are zero; month `30` is zero; the
commencement month `e + n = 30`... **the block and the commencement month must
not be conflated.** The exact D2 rule to implement and assert:

```
commencement_month = e + 1 + ceil(D) = 24 + 1 + 6 = 31   (8.4)
zero-rent months    = e+1 .. commencement_month - 1 = 25..30   (6 months)
partial month       = commencement_month = 31, factor (1 - f) = 0.5
full months         = 32 onward
total months forgone = 6 - 0.5 = 5.5 = D   ✓
```

```
BaseRent(31) = 0.5 * 31,827.000000 = 15,913.500000
BaseRent(m)  = 31,827.000000  for m 32-72
Y3 = 15,913.500000 + 5 * 31,827.000000 = 175,048.500000
```

**Assertion:** total rent forgone equals exactly `5.5` months' worth
`= 5.5 * 31,827.000000 = 175,048.500000` less than a no-downtime baseline over
months 25–36. TI and LC still land in month 31, undiminished by the partial
factor (they are not prorated).

---

### GOLDEN 9 — TI + LC + free rent *(D2)*

As Golden 8 (`p = 0.0`, downtime `6.0`, commencement month 31, successor PSF
`38.192400`, monthly `31,827.000000`), plus `new_free_rent_months = 3.0`.

```
free-rent months = 31, 32, 33   (three months from commencement)
free_rent_by_month[31..33] = 31,827.000000 each
contractual_base_rent_by_month[31..33] = 31,827.000000 each   (GROSS, unreduced)
net rent months 31-33 = 0.0
BaseRent net (m) = 31,827.000000 for m 34-72

free_rent_by_year = (0, 0, 95,481.000000, 0, 0)
Y3 net = 190,962.000000 - 95,481.000000 = 95,481.000000

LC basis is GROSS of free rent: 60 * 31,827.000000 = 1,909,620.000000
LC = 0.06 * 1,909,620.000000 = 114,577.200000        (UNCHANGED by free rent)
TI = 200,000.000000
```

**Assertions:**
- `contractual_base_rent_by_month` reports the **gross** figure in months 31–33
  and `free_rent_by_month` reports the offset — never netted into one line (10.2).
- LC is bit-identical to Golden 8, proving the basis is gross of free rent
  (12.2 / FM-7).
- Downtime months (25–30) and free-rent months (31–33) are **disjoint**
  (FM-6 / **G-5**).
- `noi_by_year` changes; `tenant_improvements_by_year` and
  `leasing_commissions_by_year` do not (FM-5).

---

### GOLDEN 10 — Rollover near exit, and a second rollover *(D2 / D4)*

Suite `S1` 10,000 SF. `L1`: `30.00` PSF, no escalation, expires month 58
(2030-10-31). Market leasing: `market_rent_psf = 36.00`,
`market_rent_growth = 0.0`, `renewal_probability = 0.0`,
`new_downtime_months = 3.0`, `new_term_months = 12`, `new_ti_psf = 10.00`,
`new_lc_pct = 0.05`, `new_free_rent_months = 0.0`,
`successor_escalation_pct = 0.0`.

```
Rollover 1:
  expiration 58 -> commencement 58 + 1 + 3 = 62
  successor L2: PSF 36.00, monthly 30,000.000000, months 62-73
  TI = 10.00 * 10,000 = 100,000.000000     month 62  -> NTM window
  LC = 0.05 * 12 * 30,000.000000 = 18,000.000000  month 62 -> NTM window

Rollover 2 (FM-13):
  L2 expires month 73 -> BEYOND the window (72). No second rollover occurs.
```

**10b — forcing the second rollover.** Set `new_term_months = 6`:

```
L2: months 62-67, PSF 36.00, monthly 30,000.000000
L2 expires 67 -> L3 commencement 67 + 1 + 3 = 71
L3: months 71-76 -> truncated at 72

BaseRent(m) = 25,000.000000   m 1-58
BaseRent(m) = 0.0             m 59-61     (downtime 1)
BaseRent(m) = 30,000.000000   m 62-67
BaseRent(m) = 0.0             m 68-70     (downtime 2)
BaseRent(m) = 30,000.000000   m 71-72

exit_noi = sum of months 61..72
         = 0 (m61) + 6*30,000 (m62-67) + 0 (m68-70) + 2*30,000 (m71-72)
         = 240,000.000000

base_rent_by_year[4] (m 49-60) = 12 * 25,000.000000 = 300,000.000000
base_rent_by_year[5] (m 49-60)... Y5 = m 49-60 = 10 paying + 2 zero
   -> 10 * 25,000 = 250,000.000000    (months 59, 60 are downtime)

exit_ntm_leasing_costs = TI(m62) + LC(m62) + TI(m71) + LC(m71)
   = 100,000.000000 + 0.05*6*30,000.000000
   + 100,000.000000 + 0.05*6*30,000.000000
   = 100,000 + 9,000 + 100,000 + 9,000 = 218,000.000000
```

**Assertions:**
- A successor lease itself rolls over (FM-13) — `rollover_events` has exactly
  two entries in 10b.
- `exit_noi` is the hand-summed months 61–72, **not** `12 × NOI_month_61` (which
  would be `0.0`) and **not** Year-5 NOI (FM-12).
- `exit_ntm_leasing_costs` reports `218,000.00` and is **not** deducted from
  `exit_noi`, `exit_value`, or any cash flow (17.4).
- A `ROLLOVER_IN_EXIT_NTM_WINDOW` warning is raised for both rollovers.

---

### Golden-case coverage matrix

| Case | D1 | D2 | Guards |
|---|---|---|---|
| 1 Single lease | ✓ | | FM-11 |
| 2a/2b Escalation | ✓ | | FM-4 |
| 3 Mid-hold expiration | ✓ | | FM-2 |
| 4 Commencement in hold | ✓ | | |
| 5 Two tenants | ✓ | | FM-17, area invariant |
| 6 Vacant suite | ✓ | | FM-1, area invariant |
| 7 Renewal `p=1` | | ✓ | FM-5, FM-7, FM-11 |
| 8 / 8b Vacate + downtime | | ✓ | FM-3, FM-6 |
| 9 TI + LC + free rent | | ✓ | FM-5, FM-6, FM-7 |
| 10 / 10b Rollover near exit | | ✓ | FM-12, FM-13 |

---

## 28. D1 Detailed Build Plan

**D1 objective:** existing contractual leases produce correct deterministic
monthly base-rent cash flows and a correct monthly occupancy schedule.

**D1 explicitly excludes:** renewal, replacement tenants, TI, LC, free rent,
recoveries, operating expenses, NOI, `OperatingProjectionLike` conformance, any
change to `analyze_acquisition_from_operating_projection`, persistence, API,
frontend, and ingestion. D1 produces a `PropertyRentRollSchedule` and stops.

**Why this isolates cleanly from D2** (brief STOP CONDITION 5): D1's output
contract, `PropertyRentRollSchedule`, is a pure function of analyst-supplied
leases. D2 adds *more leases* (successors) to the same engine and reuses D1's
`build_lease_schedule` unchanged for each. There is no D1 formula D2 revises —
only new leases fed to it, plus two new below-NOI series. Verified by inspection
of the rent formula (6.1), which contains no rollover term.

---

### Gate D1.0 — Contracts and validation

**Objective.** The lease-level input contracts exist, are validated
deterministically, and reject every ERROR case in 19.2.

**Files.** New: `src/anchor/leasing/__init__.py`,
`src/anchor/leasing/contracts.py`, `src/anchor/leasing/validation.py`.
Modified: none. (An `IssueSeverity` addition to `src/anchor/validation.py`
depends on **HD-6**; if approved it lands here as an additive enum plus a
defaulted `InputIssue.severity` field.)

**Contracts introduced.** `LeaseLevelPropertyInputs`, `Suite`, `Lease`,
`EscalationBasis`, `LeaseType`, `LeaseOrigin`.

**Tests.** `tests/test_leasing_gate_d1_0_contracts.py`,
`tests/test_leasing_gate_d1_0_validation.py`,
`tests/test_leasing_architecture.py` (guardrail G-1, on this gate per the
day-one rule in the guardrails solution doc).

- Every ERROR rule in 19.2 fires, with the right category, for a minimal input.
- Every WARNING rule in 19.3 fires and does **not** prevent construction.
- Issue ordering is deterministic across 100 runs.
- A valid multi-suite, multi-lease input constructs cleanly.
- G-1: `anchor.leasing` imports no forbidden module (AST-parsed).

**Stop conditions.** Stop if HD-6 is unresolved and any WARNING rule cannot be
expressed. Stop if `IssueSeverity` cannot be added without changing an existing
test.

**Acceptance.** All 1773 existing backend tests still pass, unmodified. New
tests pass. `git diff` touches only new files (plus `validation.py`'s additive
severity, if approved).

**Commit.** `feat(leasing): D1 Gate 0 -- lease-level contracts and validation`

---

### Gate D1.1 — Calendar normalization

**Objective.** Deterministic, total, hand-checkable date → month-index
normalization.

**Files.** New: `src/anchor/leasing/calendar.py`.

**Functions.**

```python
def month_index(target: date, *, analysis_start: date) -> int
def month_start(index: int, *, analysis_start: date) -> date
def last_day_of_month(d: date) -> date
def is_month_start(d: date) -> bool
def is_month_end(d: date) -> bool
def projection_months(hold_period: int) -> int   # 12 * H + 12
```

`month_index` is pure integer arithmetic:
`12 * (t.year - s.year) + (t.month - s.month) + 1`. It never uses `timedelta`,
never uses `days`, and is therefore leap-year- and timezone-independent by
construction.

**Tests.** `tests/test_leasing_gate_d1_1_calendar.py`.

- `month_index(analysis_start) == 1`.
- Round-trip: `month_index(month_start(k)) == k` for `k` in `-120..240`.
- Dates before the analysis start yield indices `<= 0` (never an exception).
- Leap years, 28/29/30/31-day months, and year boundaries all behave.
- `is_month_end` is correct for Feb 28/29 in leap and non-leap years.
- A property test: `month_index` is monotone non-decreasing in its argument.

**Stop conditions.** Stop if any function needs a `timedelta` or a day count —
that would mean the whole-month convention (5.4) has leaked.

**Acceptance.** Full suite green. `calendar.py` imports only `datetime.date`.

**Commit.** `feat(leasing): D1 Gate 1 -- deterministic month-index calendar`

---

### Gate D1.2 — Contractual base-rent timeline

**Objective.** One lease produces its exact monthly base-rent series.

**Files.** New: `src/anchor/leasing/rent.py`. `LeaseSchedule` added to
`contracts.py`.

**Functions.**

```python
def lease_rent_months(lease, *, analysis_start) -> tuple[int | None, int | None]
def escalation_period_index(*, month: int, raw_first_rent_month: int,
                            basis: EscalationBasis) -> int
def monthly_base_rent(*, base_rent_psf: float, leased_area_sf: float,
                      escalation_pct: float, period_index: int) -> float
def build_lease_schedule(lease, *, analysis_start, months) -> LeaseSchedule
```

`monthly_base_rent` implements 6.1 with the division by 12 **last**, and wraps
its result in `ensure_finite`, matching every existing Anchor calculator.

**Tests.** `tests/test_leasing_gate_d1_2_rent.py` plus
`tests/test_leasing_golden_cases.py` (Goldens 1, 2a, 2b, 3, 4).

- Goldens 1–4 assert every month at `abs=1e-9`.
- Golden 2b specifically asserts Month 1 is on escalation step `k=2` (FM-4).
- Golden 3 asserts month 30 pays and month 31 is exactly `0.0` (FM-2).
- A lease entirely outside the window yields `(None, None)` and an all-zero
  series.
- `escalation_pct = 0.0` and `escalation_basis = NONE` produce identical series.
- A non-finite intermediate raises `NonFiniteResultError`, never a silent `inf`.

**Stop conditions.** Stop if any golden case cannot be hand-verified from the
formula in 6.1 alone.

**Acceptance.** Goldens 1–4 pass at `rel=0.0, abs=1e-9`. Full suite green.

**Commit.** `feat(leasing): D1 Gate 2 -- contractual base-rent timeline`

---

### Gate D1.3 — Property aggregation and occupancy

**Objective.** Many leases across many suites aggregate to one property monthly
schedule with an exact area reconciliation.

**Files.** New: `src/anchor/leasing/aggregation.py` (D1 portion only).
`PropertyRentRollSchedule` added to `contracts.py`.

**Functions.**

```python
def build_property_rent_roll_schedule(
    property_inputs, suites, leases, *, hold_period
) -> PropertyRentRollSchedule
```

Summation is ascending by month, and within a month, leases are summed in their
declared tuple order — fixed, never `set`- or `dict`-ordered (FM-17).

**Tests.** `tests/test_leasing_gate_d1_3_aggregation.py` plus Goldens 5 and 6.

- Golden 5: two leases, independent escalation, occupancy stepping
  `1.0 → 0.6 → 0.0`.
- Golden 6: a suite with zero leases produces `0.0` revenue and its area in
  `vacant_area_by_month`, with no synthetic lease row.
- Area invariant `occupied + vacant == property_area_sf` at `abs=1e-9` in every
  month of every case (18.4).
- Determinism: 100 repeated runs are bit-identical.
- Lease ordering does not affect any total (compare a reversed input tuple; the
  *sum* is asserted equal at `abs=1e-9`, not bit-for-bit, since addition order
  legitimately changes the last bits — the tuple order rule fixes the order for
  a given input, which is what reproducibility requires).

**Stop conditions.** Stop if the area invariant cannot hold exactly for any
valid input.

**Acceptance.** Goldens 1–6 pass. Full suite green.

**Commit.** `feat(leasing): D1 Gate 3 -- property rent-roll aggregation`

---

### Gate D1.4 — Guardrails and D1 closeout

**Objective.** D1 is provably isolated and provably inert with respect to Quick
and Detailed.

**Files.** New: `tests/test_leasing_architecture.py` (extended),
`tests/test_leasing_gate_d1_4_isolation.py`. No production file changes.

**Tests.**

- **G-1** (extended): AST-parse every file in `src/anchor/leasing/`; assert none
  imports `anchor.engine.acquisition`, `anchor.engine.debt`, `anchor.engine.noi`,
  `anchor.engine.returns`, `anchor.engine.operating_projection`, `anchor.ai`,
  `anchor.deals`, `anchor.ingestion`, `anchor.analysis`, `openai`, or `azure`.
- **G-2**: the Quick V2 golden case and the Detailed V2.1 golden case produce
  bit-identical results to their recorded values.
- Subprocess check: importing `anchor.engine` in a fresh interpreter does not
  pull `anchor.leasing` into `sys.modules` (mirrors the existing
  `test_ai_architecture.py` shape).
- **G-4** (partial): no Lease-Level contract declares a field named
  `vacancy_credit_loss_pct` or `occupancy`.

**Stop conditions.** Stop if `anchor.engine` must import `anchor.leasing` at D1 —
it must not; the two are connected only from D4 onward.

**Acceptance.** 1773 pre-existing tests pass **unmodified**. `git diff` shows no
change to any file under `src/anchor/engine/`, `web/`, or any existing test.
Backend and frontend suites both green, results reported exactly.

**Commit.** `test(leasing): D1 Gate 4 -- isolation guardrails and D1 closeout`

---

## 29. D2 / D3 / D4 High-Level Plan

### D2 — Rollover, market leasing, TI, LC, free rent, downtime

**Objective.** An expiring lease produces a deterministic successor with correct
timing, rent, downtime, free rent, TI, and LC.

| Gate | Content |
|---|---|
| D2.0 | `MarketLeasingAssumptions` contract, precedence resolver (Section 24), validation. `ResolvedMarketLeasing` recorded per suite |
| D2.1 | Market rent timeline (Section 7); assert growth applies on analysis anniversaries |
| D2.2 | `rollover.py`: successor generation, weighted assumptions (8.2), timing (8.4), the successor chain, horizon truncation. `RolloverEvent` log. **Goldens 7, 8, 8b** |
| D2.3 | Free rent (Section 10) and the fractional-month factor (9.3). **Golden 9** free-rent portion. **G-5** disjointness |
| D2.4 | TI and LC (Sections 11, 12), below-NOI series. **Golden 9** full. **G-3** perturbation |
| D2.5 | **Golden 10 / 10b**, second-order rollover, exit-window warnings, D2 closeout |

**Key risks.** FM-3 (market rent timing), FM-6 (free rent vs downtime), FM-7 (LC
basis), FM-13 (second rollover). All have a named golden case.

**Gate blocked by:** HD-2 (rollover convention), HD-4 (renewal rent semantics).

---

### D3 — Expense recoveries and lease structures

**Objective.** NNN, Gross, and Modified Gross recoveries compute correctly and
stop during vacancy.

| Gate | Content |
|---|---|
| D3.0 | `recoverable_expense_ratio`, base-year derivation, validation |
| D3.1 | `recoveries.py`: the three structures (16.2), pro-rata share, the vacancy gate |
| D3.2 | The fixed non-iterative computation order (16.4), asserted explicitly |
| D3.3 | Recovery golden cases (a NNN case, a Gross case, a base-year-stop case), FM-9 and FM-10 tests |

**Gate blocked by:** HD-7 (base year for in-place Modified Gross leases).

---

### D4 — Property aggregation and engine integration

**Objective.** Lease-Level produces an `OperatingProjectionLike` and flows
through the unchanged downstream engine.

| Gate | Content |
|---|---|
| D4.0 | `LeaseLevelOperatingInputs` contract and validation |
| D4.1 | Full monthly EGI/expense/NOI build (Section 13), monthly → annual aggregation (18.4) |
| D4.2 | `exit_noi` on the NTM convention (Section 17), `exit_ntm_leasing_costs` |
| D4.3 | **The one engine change:** `leasing_costs_by_year` threading (3.2), `AcquisitionResults` extension, `LeaseLevelAcquisitionResults` envelope, `analyze_lease_level_acquisition_with_projection`. **G-2** bit-identity, **G-3** perturbation, **G-6** monthly-leak |
| D4.4 | Sensitivity and break-even over the same four `AcquisitionTerms` dimensions Detailed uses (2.16); the immutable-container `dataclasses.replace` pattern |
| D4.5 | An end-to-end golden case with real expenses, reusing Detailed's verified expense numbers; full-suite closeout |

**Gate blocked by:** HD-1 (`AcquisitionResults` extension shape), HD-5 (exit-NOI
rollover treatment).

D5 (persistence, API, UI, ingestion) and D6 (competition hardening, Excel
reconciliation, edge cases) follow the brief's sequence unchanged. D0 recommends
**no resequencing** of D1–D6: the proposed order matches the dependency graph
found in the code, and each phase has a provable stop condition.

---

## 30. Architecture Guardrails

| ID | Guarantee | Mechanism | Gate |
|---|---|---|---|
| **G-1** | Lease-Level does not leak into any other layer | AST import test over `src/anchor/leasing/`, plus a fresh-subprocess `sys.modules` check | D1.0 / D1.4 |
| **G-2** | Quick and Detailed are unchanged | Both existing golden cases assert bit-identical results after every Sprint D gate | Every gate |
| **G-3** | TI and LC stay below NOI | Perturbation: doubling every TI/LC input leaves `noi_by_month`, `noi_by_year`, `exit_noi`, `going_in_cap_rate`, `dscr_by_year`, and `year_1_debt_yield` bit-identical, while changing both cash-flow series, both IRRs, and every owner return metric | D2.4 / D4.3 |
| **G-4** | Vacancy is not double-counted | No Lease-Level contract declares `vacancy_credit_loss_pct` or `occupancy` (field-name assertion over the dataclass fields) | D1.4 |
| **G-5** | Free rent and downtime never overlap | For every successor lease, the free-rent and downtime month-index sets are disjoint | D2.3 |
| **G-6** | Monthly logic never alters annual conventions | AST test: no module outside `anchor.leasing` references any identifier ending `_by_month`. Runtime test: the IRR solver receives exactly `H+1` values | D4.3 |
| **G-7** | The frontend calculates no lease economics | AST/regex test over `web/src/`: no month-index arithmetic, no escalation math, no rollover date math. Mirrors the existing engine-boundary tests | D5 |
| **G-8** | AI calculates no lease economics | The AI layer receives an already-computed `LeaseLevelAcquisitionResults` and its `rollover_events`; delegation asserted with `patch(..., wraps=...)`. Grounding rules extended: the AI may describe a rollover but never re-derive a rent, a downtime, a TI, or an LC | D5 |
| **G-9** | Persistence is not the source of truth | Successor leases, schedules, and projections are never persisted; opening a deal re-runs the engine. Asserted by a store test that no `lease_level_*` table has a rent, schedule, or projection column | D5 |
| **G-10** | Deterministic inputs give deterministic outputs | 100 repeated runs bit-identical; lease-collection ordering fixed at construction; no `set`/`dict` iteration in any summation | D1.3, every gate |
| **G-11** | Exit NOI uses the approved convention | `exit_noi` asserted equal to the hand-summed months `12H+1..12H+12`, and explicitly **not** equal to `noi_by_year[-1]` in a case where they differ | D4.2 |
| **G-12** | Debt conventions are untouched | AST test: no Lease-Level module imports `anchor.engine.debt`. Golden: `annual_debt_service` and `remaining_loan_balance` are bit-identical for identical `AcquisitionTerms` across all three modes | D4.3 |

Each of G-1 through G-12 follows one of the four established shapes from
`docs/solutions/conventions/testing-conventions-and-architecture-guardrails.md`
(AST import test, data-flow spy, `wraps` delegation proof, spec-sourced golden
case) rather than inventing a new pattern.

---

## 31. Human Decisions Required Before D1

Each decision below genuinely requires product or CRE judgment. None can be
resolved by reading the code.

---

### HD-1 — Shape of the `AcquisitionResults` leasing-cost extension  *(blocks D4; decide before D1 so contracts are stable)*

**Question.** How should the new below-NOI leasing-cost series be exposed on
`AcquisitionResults`, given that Quick and Detailed have no such cost?

**Option A (recommended).** Add `leasing_costs_by_year: tuple[float, ...]` to
`AcquisitionResults`, always length `H`, all zeros for Quick and Detailed.

- *Financial consequence:* every mode's cash-flow series becomes fully
  reconcilable from published fields alone: `UCF_y = NOI_y − CapEx_y −
  LeasingCosts_y`. Nothing is hidden.
- *Implementation consequence:* `_ANALYSIS_SNAPSHOT_SCHEMA_VERSION` bumps to 2.
  Existing Quick/Detailed snapshots decode as "absent" and the UI re-runs the
  engine — the already-designed behavior for a version mismatch
  (`deals/store.py:_decode_snapshot`). The frontend `AcquisitionResults` type
  gains an optional field. No existing *value* changes.

**Option B.** Leave `AcquisitionResults` untouched; expose leasing costs only on
the `LeaseLevelAcquisitionResults` envelope.

- *Financial consequence:* **bad.** `unlevered_cash_flows` and
  `levered_cash_flows` inside `AcquisitionResults` would already be net of TI/LC,
  but nothing on that contract would explain the difference. A reviewer
  reconciling `NOI_y − CapEx_y` against `UCF_y` would find an unexplained gap.
  This is exactly the auditability failure Anchor's conventions exist to prevent.
- *Implementation consequence:* no snapshot bump. Cheaper, and wrong.

**Option C.** Fold TI/LC into `capex_by_year`.

- *Financial consequence:* conflates a recurring physical reserve with
  lease-triggered leasing costs; makes `capex_by_year` non-constant, breaking
  its documented meaning and an existing test.
- *Rejected.*

**Recommendation: A.** The snapshot bump is a designed, already-tested
degradation path; unexplained cash flows are not.

---

### HD-2 — The rollover convention  *(blocks D2)*

**Question.** How is renewal probability applied?

**Option A (recommended) — weighted assumptions, one successor lease.**
Blend rent, downtime, free rent, TI, LC, and term by `p`; create one successor
covering the full suite (8.2).

- *Financial consequence:* results are expected-value economics. Physical space
  stays integral; occupancy is reportable; rollover chains stay coherent. Matches
  ARGUS and judge expectations. The successor's rent corresponds to no single
  real outcome — disclosed via the `WEIGHTED_ROLLOVER_APPLIED` warning.
- *Implementation consequence:* one successor chain per suite. Fractional
  downtime and free rent need the partial-month factor (9.3) — one contained
  mechanism.

**Option B — analyst-selected path only (`p ∈ {0, 1}`).**

- *Financial consequence:* every rollover is a discrete stated bet. Maximally
  interpretable; no blended fiction. But a 20-suite building requires 20 explicit
  bets, and the model cannot express "most tenants renew."
- *Implementation consequence:* strictly simpler — no weighting, no fractional
  months at all. Note that Option A **contains** Option B at `p ∈ {0, 1}`.

**Option C — expected-value blending of two full cash-flow branches.**

- *Financial consequence:* unauditable beyond the first rollover (8.3); implies
  fractional occupancy.
- *Rejected.*

**Recommendation: A**, because it subsumes B at the endpoints while also
expressing the common case. If the project owner prefers maximum
interpretability over ARGUS familiarity, B is a legitimate choice that makes D2
meaningfully simpler.

---

### HD-3 — Whole-month vs day-prorated rent recognition  *(blocks D1)*

**Question.** How is a lease commencing or expiring mid-month treated?

**Option A (recommended) — whole-month, any-overlap-pays**, with a
`LEASE_DATE_NOT_MONTH_ALIGNED` warning and an `OVERLAPPING_LEASES_IN_SUITE`
error (5.4).

- *Financial consequence:* exact for month-aligned leases (the overwhelming
  majority and all successor leases). Up to one extra month of rent recognized
  per non-aligned lease end. On a 5-year hold with a $30/SF lease, a single
  mid-month expiration overstates that year's rent by up to ~8%.
- *Implementation consequence:* pure integer arithmetic. Every golden case is
  hand-checkable. No day-count convention needed anywhere.

**Option B — day-level proration** in the commencement and expiration months.

- *Financial consequence:* exact for every lease. Removes the bias entirely.
- *Implementation consequence:* requires a day-count convention decision
  (actual/actual vs 30/360 — themselves a further sub-decision), makes every
  golden case a day-arithmetic exercise, and introduces `timedelta` into an
  otherwise integer-only calendar module. Roughly doubles D1.1 and D1.2 test
  surface.

**Option C — reject non-aligned dates outright** (ERROR, force the analyst to
normalize).

- *Financial consequence:* no bias, but a real rent roll with one mid-month
  expiration cannot be analyzed at all until the analyst edits a contractual
  fact — which distorts the record.
- *Rejected.*

**Recommendation: A.** The bias is bounded, disclosed per-lease, and eliminated
in the case that actually occurs. B is the right upgrade if a competition rent
roll turns out to be systematically non-aligned; it is additive.

---

### HD-4 — Semantics of an explicit `renewal_rent_psf`  *(blocks D2)*

**Question.** When an analyst supplies an explicit renewal rent, is it a level
measured today, or a nominal rent at the future rollover date?

**Option A (recommended).** A level at `analysis_start_date`, grown by
`market_rent_growth` to the commencement month (4.5.1).

- *Financial consequence:* consistent with how `market_rent_psf` is defined; the
  same input yields comparable economics regardless of when the rollover falls;
  a suite rolling in Year 2 and one rolling in Year 4 are treated coherently.
- *Implementation consequence:* one growth application, shared with market rent.

**Option B.** A nominal rent applied verbatim at commencement, ungrown.

- *Financial consequence:* the analyst states exactly what the successor pays —
  maximum control. But a single property-level `renewal_rent_psf` then means
  different things for a Year-2 and a Year-5 rollover, and it will silently drift
  below market as the hold extends.
- *Implementation consequence:* marginally simpler.

**Recommendation: A**, with the field labeled "Renewal Rent (today's dollars)"
in the UI so the semantics are visible at the point of entry. If B is chosen,
the field must be labeled "Renewal Rent at Rollover."

---

### HD-5 — Rollover inside the exit NTM window  *(blocks D4)*

**Question.** Should rollover, downtime, and free rent be live in months
`12H+1..12H+12` when computing `exit_noi`?

**Option A (recommended) — yes, fully live.** `exit_noi` is the true forward
twelve months (17.1).

- *Financial consequence:* economically honest — a buyer really does face that
  expiry. But at a 6.5% cap, one lost month of NOI moves exit value by roughly
  15× that month's NOI, so a lease expiring in month `12H+2` can produce a large,
  cliff-like drop that surprises an analyst who has not read this section.
  Mitigated by the `ROLLOVER_IN_EXIT_NTM_WINDOW` warning and by
  `exit_ntm_leasing_costs` disclosure.
- *Implementation consequence:* none beyond projecting the window, which is
  required regardless.

**Option B — a normalized exit NOI** that suppresses downtime and free rent in
the NTM window (i.e. values the property as if the space were re-let seamlessly).

- *Financial consequence:* smoother, closer to how a broker would quote a cap
  rate on in-place income. But it hides a real cost and would let a deal with a
  Year-6 mass expiry look identical to one fully leased through Year 10 — exactly
  the risk a lease-level model exists to reveal.
- *Implementation consequence:* a second NOI build over the same window with
  different rules; two exit conventions to test and explain.

**Recommendation: A.** Anchor's value proposition is showing the rollover risk,
not smoothing it. If B is ever wanted, it belongs as an explicit,
analyst-selected *exit convention* toggle, never as a silent default.

---

### HD-6 — Introduce an issue severity concept  *(blocks D1)*

**Question.** Should `InputIssue` gain a severity, or should Lease-Level use
errors only?

**Option A (recommended).** Add `IssueSeverity` (`ERROR` default, `WARNING`) as
an additive field on `InputIssue`.

- *Financial consequence:* the analyst is told about applied conventions
  (mid-month dates, weighted rollover, rollover in the exit window, area
  shortfall) without being blocked. Under an errors-only model these facts would
  be invisible, which is a real risk of financially plausible-but-misunderstood
  results.
- *Implementation consequence:* one enum, one defaulted dataclass field, one API
  serialization field, one UI treatment. Every existing issue keeps `ERROR` by
  default, so no existing test changes.

**Option B.** Errors only; surface advisories through a separate
`LeaseLevelDiagnostics` object on the result envelope.

- *Financial consequence:* equivalent information, but split across two channels
  — input-time issues in one place, applied-convention notices in another. The
  analyst has two places to look.
- *Implementation consequence:* no change to `validation.py` at all; a new
  contract instead.

**Recommendation: A.** Warnings are genuinely input-validation feedback
(`LEASE_DATE_NOT_MONTH_ALIGNED` is about an input, not a result) and belong in
the same channel as errors.

---

### HD-7 — Base year for in-place Modified Gross leases  *(blocks D3)*

**Question.** What is the expense base year for a `MODIFIED_GROSS` lease already
in place at acquisition, whose real base year predates the analysis?

**Option A (recommended).** Hold Year 1 for every in-place lease.

- *Financial consequence:* systematically **understates** recoveries, because a
  real base year several years in the past would be a lower expense level and
  therefore a larger reimbursable excess. Conservative, and conservative in the
  direction a buyer prefers.
- *Implementation consequence:* zero new inputs.

**Option B.** Add an optional `base_year_expense_stop_psf` per lease; fall back
to Hold Year 1 when absent.

- *Financial consequence:* exact when the rent roll states the stop, which good
  rent rolls do. Best answer where the data exists.
- *Implementation consequence:* one nullable field, one precedence rule, one
  validation rule, one more UI field. Small.

**Recommendation: B**, with A as the documented fallback. The cost is one
nullable field and the accuracy gain on a Modified Gross building is material.
Decide before D3.0; it does not affect D1 or D2.

---

### HD-8 — Adding `analyst_supplied` to `EvidenceStatus`  *(blocks D5; decide early)*

**Question.** `CONCEPTS.md` states `EvidenceStatus` has "exactly these five
states — no other value is valid." Lease-Level needs to distinguish an
analyst-entered assumption from a document-missing one (20.3). Amend the concept?

**Option A (recommended).** Add a sixth member, `analyst_supplied`, and amend
`CONCEPTS.md` accordingly.

- *Financial consequence:* the review UI can report "12 of 20 fields
  document-backed, 8 analyst-supplied" — exactly the provenance summary a
  competition judge asks for. Without it, every renewal probability, downtime,
  TI, and LC reads as `missing` forever.
- *Implementation consequence:* a StrEnum member, a UI treatment, and an
  amendment to a documented project concept. Existing five-state assertions in
  `tests/test_ingestion_contracts.py` would need extending — a **test change**,
  which is why this must be an explicit decision rather than an incidental one.

**Option B.** Keep five states; track analyst-supplied values with a separate
boolean on the approval record.

- *Financial consequence:* same information, expressed as two fields instead of
  one. Slightly more awkward to render, but the concept stays frozen.
- *Implementation consequence:* no `EvidenceStatus` change, no existing test
  change. A new field on whatever contract carries the approval decision.

**Recommendation: A.** `analyst_supplied` is genuinely a sixth evidence state,
not a flag about one — it answers the same question the other five answer ("how
is this value supported?"). But this amends a documented, deliberately frozen
concept and must be approved rather than assumed.

---

### 30.9 Decision dependency summary

| Decision | Blocks | Must be resolved before |
|---|---|---|
| HD-1 | `AcquisitionResults` shape | D1.0 (contract stability) |
| HD-3 | Month recognition rule | D1.1 |
| HD-6 | Issue severity | D1.0 |
| HD-2 | Rollover convention | D2.0 |
| HD-4 | Renewal rent semantics | D2.0 |
| HD-8 | Evidence status | D5.0 (decide early — it affects the D5 ingestion contracts) |
| HD-5 | Exit-NOI rollover | D4.2 |
| HD-7 | Modified Gross base year | D3.0 |

### 30.10 STOP CONDITIONS — none triggered

| # | Condition | Status |
|---|---|---|
| 1 | Existing architecture makes the convergence model materially incorrect | **Not triggered.** `OperatingProjectionLike` accommodates a third producer exactly as `docs/detailed_operating_model_v2_1_architecture.md` §13 anticipated |
| 2 | A lease convention has multiple valid interpretations requiring product intent | **Triggered as intended, not as a stop.** Eight such conventions are surfaced as HD-1…HD-8 with recommendations, per the brief's own instruction to flag rather than bury them |
| 3 | Monthly modeling requires unexpected changes to acquisition/debt/returns semantics | **Not triggered.** Debt is already monthly-internal; returns need no change; the single additive change (`leasing_costs_by_year`) is expected, not unexpected, and is neutral by default |
| 4 | Exit NOI cannot be integrated without changing an existing convention | **Not triggered.** The NTM convention is the existing convention, restated monthly (17.3) |
| 5 | D1 cannot be cleanly isolated from D2 | **Not triggered.** D1's rent formula (6.1) contains no rollover term; D2 adds leases to the same engine (Section 28 preamble) |
| 6 | Repository state differs materially from the stated baseline | **Not triggered.** `fffdf34`, clean tree, 1773 backend and 711 frontend tests verified locally |

---

## Appendix A — Summary of every change this plan will eventually require outside `anchor.leasing`

Listed so a reviewer can see the total blast radius in one place. **None is
implemented by D0.**

| File | Change | Phase |
|---|---|---|
| `src/anchor/engine/acquisition.py` | One keyword-only `leasing_costs_by_year` parameter; a `calculate_below_noi_costs_by_year` helper; `analyze_lease_level_acquisition_with_projection` | D4.3 |
| `src/anchor/engine/contracts.py` | `AcquisitionResults.leasing_costs_by_year`; `LeaseLevelAcquisitionResults` envelope | D4.3 |
| `src/anchor/contracts.py` | `OperatingMode.LEASE_LEVEL` | D4.3 |
| `src/anchor/validation.py` | `IssueSeverity` (additive, `ERROR` default) — HD-6 | D1.0 |
| `src/anchor/api.py` | A `lease_level` branch in `/analyze`, `/sensitivity`, `/break-even`, `/ai/analysis`, `/deals` | D5 |
| `src/anchor/deals/*` | Schema version 5, three new tables, fingerprint extension | D5 |
| `src/anchor/ingestion/contracts.py` | `LeaseCandidateRow`, `RentRollExtractionResult`; `EvidenceStatus.ANALYST_SUPPLIED` — HD-8 | D5 |
| New `src/anchor/lease_level_excel_reader.py` | Tabular rent-roll reader | D5 |
| `web/src/types.ts`, `convert.ts`, `underwrite.ts` | Lease-Level mode, Operations sub-views, Rollover Schedule results view | D5 |
| New `web/src/components/RentRollTable.tsx` | The one genuinely new UI surface | D5 |
| `CONCEPTS.md` | `EvidenceStatus` amendment — HD-8 | D5 |

Every entry above is additive. No existing formula, field meaning, or convention
is modified anywhere in this list.
