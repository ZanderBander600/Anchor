---
title: Lease-Level Underwriting - D0 Architecture and Financial Conventions
type: feat
date: 2026-09-04
amended: 2026-09-04
topic: lease-level-underwriting
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: docs-only
sprint: D
gate: D0
status: approved-after-human-financial-review
baseline_commit: fffdf34
---

# Lease-Level Underwriting — D0 Architecture and Financial Conventions

## Status

**Planning / architecture gate only. No production code, no engine change, no
contract change, no migration, and no test change was produced by this gate.**

**This document has been amended following human financial and product review.**
Every decision previously marked unresolved is now either **locked**, **approved
as modified**, **rejected and replaced**, or **explicitly deferred to a later
phase where it does not block D1**. Section 32 is the authoritative decision
register.

Verified baseline (`main` @ `fffdf34`, re-run locally):

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

A third underwriting depth — **Lease-Level** — deriving property operating
economics from individual suites and leases (contractual rent, escalations,
expiration, rollover, downtime, TI, LC, free rent, recoveries) rather than from
a single NOI figure (Quick) or a property-level revenue/expense build
(Detailed).

### 1.2 The locked monthly principle

> **Monthly is canonical. Monthly *and* annual are published.**

Lease-Level computes **one** authoritative monthly economic schedule. That same
schedule serves three consumers:

1. user-facing monthly rent-roll, operating-statement and cash-flow views;
2. deterministic annual aggregation for user-facing annual views;
3. the annual adapter into the existing, unchanged downstream acquisition /
   debt / returns engine.

```
LEASE + MARKET ASSUMPTIONS
          |
          v
CANONICAL MONTHLY LEASE SCHEDULES        (one per lease)
          |
          v
CANONICAL MONTHLY PROPERTY PROJECTION    (the single source of truth)
          |
          +---------------------------+
          |                           |
          v                           v
USER-FACING MONTHLY            ANNUAL AGGREGATION
SCHEDULES                      (pure summation / explicit snapshot)
                                       |
                                       +----------------+
                                       |                |
                                       v                v
                              ANNUAL USER VIEWS   DOWNSTREAM ENGINE
                                                       ADAPTER
```

**There is no second Lease-Level financial calculation path.** No annual
quantity is ever computed by an independent annual formula. The monthly
schedule is never discarded after aggregation — it is a first-class, persisted-
in-memory, user-facing output.

### 1.3 The findings that matter most

1. **Lease-Level is a third producer of operating economics, not a third
   acquisition engine.** `analyze_acquisition_from_operating_projection`
   (`src/anchor/engine/acquisition.py:243`) already accepts anything satisfying
   the three-field `OperatingProjectionLike` protocol. Lease-Level's *derived
   annual* projection satisfies it. Debt, exit valuation, transaction costs,
   CapEx, IRR, equity multiple, DSCR and owner return metrics need **no formula
   change**.

2. **A below-NOI variable capital-cost channel is required — but only from
   D4.** TI and LC are capital costs below NOI. Today the *only* below-NOI
   operating-period channel is `capex_by_year`, a constant derived from
   `terms.annual_capex_reserve`. TI/LC vary by year and are produced by the
   lease engine. **D1 has no TI and no LC, so D1 does not touch this and does
   not touch `AcquisitionResults`.** The channel's shape is an explicit D4
   architecture decision (Section 32, HD-1).

3. **Calendar identity is first-class.** The existing engine is date-free
   (`datetime` appears nowhere under `src/anchor/engine/`; only `deals/` uses
   it, for row timestamps). Lease-Level introduces calendar dates, and every
   canonical monthly period carries **both** a sequential model month index and
   its real calendar month. Economic arithmetic still runs on integer month
   indices — never on `date` arithmetic.

4. **Debt does not change, and monthly debt service is never fabricated.**
   `calculate_annual_debt_service` (`src/anchor/engine/debt.py:294`) already
   runs a chronological monthly loop internally. Annual DSCR remains
   `NOI_y / ADS_y`. Any future monthly debt display must come from that
   existing monthly chronology, **never** from `annual_debt_service / 12`.

5. **Exit NOI is the live forward twelve months** — months `12H+1 .. 12H+12` of
   the same canonical monthly projection the user can inspect. This is the
   monthly restatement of Anchor's existing frozen rule
   (`docs/financial_conventions.md`: "Exit Value uses next-twelve-month forward
   NOI after the final hold year"). No separate, hidden exit-NOI calculation
   may exist.

6. **D1 modifies no existing file.** D1 adds a new isolated `anchor.leasing`
   package and its tests, and nothing else. This is a checkable acceptance
   criterion, not an aspiration (Section 30).

### 1.4 Locked convention summary

| Area | Locked convention |
|---|---|
| Granularity | Monthly canonical; monthly **and** annual published (Section 5) |
| Month identity | Every period carries `period_index` **and** its calendar month (Section 5.2) |
| Economic dates | Must be month-aligned. Non-aligned economic dates are a validation **ERROR**, never a coerced approximation (Section 5.5) |
| Aggregation | Flow metrics = chronological sum of twelve months. State metrics = explicitly named snapshot or average, never summed (Section 5.7) |
| Domain model | Property → Suite → Lease; tenant is a lease attribute, not an entity (Section 4) |
| Market rent | Property default + suite override; **annual step growth on `analysis_start_date` anniversaries** (Section 7) |
| Contractual escalation | Tied to the lease's true contractual chronology; acquisition never resets the escalation clock (Section 6.2) |
| Rollover | Deterministic **expected rollover successor**; `p=1` and `p=0` reproduce pure renewal / pure vacate paths; component assumptions preserved for audit (Section 8) |
| Downtime | Whole vacant months plus one explicit fractional boundary-month factor (Section 9) |
| Free rent | Months of abated **base rent only**; above NOI; distinct from downtime (Section 10) |
| TI | `$/SF` × leased area, paid at successor rent commencement, **below NOI** (Section 11) |
| LC | `%` of total contractual base rent over the successor term, including escalations, gross of free rent, untruncated at hold end, **below NOI**, with a method extension seam (Section 12) |
| Operating expenses | Property-level assumptions, reusing Detailed's expense concepts and formulas; separate *input contract* because GPR and vacancy are Lease-Level outputs (Section 13) |
| Vacancy | Physical vacancy modeled explicitly. Detailed's general vacancy field does not exist on any Lease-Level contract (Section 15) |
| Recoveries | NNN / Gross / Modified Gross. Modified Gross requires an **explicit analyst-approved recovery basis** — no invented base year (Section 16) |
| Exit NOI | Live forward months `12H+1..12H+12` of the canonical monthly projection (Section 17) |

### 1.5 Classification

**A — D0 READY TO MERGE AND BEGIN D1 AFTER MERGE.** No human financial decision
blocks D1. Two decisions remain open by design and are scheduled: the below-NOI
channel shape (D4) and the evidence-status / provenance distinction (D5).
Neither affects any D1 contract, formula, gate, or test.

---

## 2. Repository Reconnaissance

Verified by reading the named files at `fffdf34`.

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

`occupancy` is read by nothing; `engine/noi.py`'s docstring states this as a
frozen convention.

### 2.2 Where Detailed produces operating economics

`src/anchor/engine/operating_projection.py` —
`build_detailed_operating_projection(detailed_inputs, *, hold_period, purchase_price) -> OperatingProjection`.

Projects `hold_period + 1` years through the full line-item build (GPR, other
income, vacancy, five fixed expense lines, management fee), takes
`noi_by_year = NOI_1..NOI_H` and `exit_noi = NOI_(H+1)`, and explicitly forbids
approximating `exit_noi` by blending a growth rate onto `NOI_H`.

`OperatingProjection` (`src/anchor/engine/contracts.py:78`) carries twelve
`_by_year` line-item schedules plus the three `OperatingProjectionLike` fields.

### 2.3 Where the two converge

`analyze_acquisition_from_operating_projection(operating_projection: OperatingProjectionLike, terms: AcquisitionTerms) -> AcquisitionResults`
(`src/anchor/engine/acquisition.py:243`).

Both `analyze_acquisition` (Quick) and
`analyze_detailed_acquisition_with_projection` (Detailed) are thin builders of
`(operating_projection, terms)` and call this one function exactly once;
`tests/test_detailed_v2_1_gate3_convergence.py` proves it with
`patch(..., wraps=...)` call-count assertions.

### 2.4 What downstream contract a lease engine must satisfy

`OperatingProjectionLike` (`src/anchor/engine/contracts.py:47`) — a `Protocol`
with exactly:

```python
noi_by_year: tuple[float, ...]   # length H
exit_noi: float                  # scalar, Year H+1, never a member of noi_by_year
going_in_cap_rate: float
```

Structural typing — a Lease-Level *annual* projection satisfies it simply by
declaring these three fields.

### 2.5 Are current annual representations sufficient downstream?

**For NOI: yes.** Every downstream consumer reads only `noi_by_year` /
`exit_noi` / `going_in_cap_rate`.

**For variable capital costs: no.** Every consumer of a below-NOI series:

| Consumer | File:line | Reads |
|---|---|---|
| `calculate_unlevered_cash_flows` | `engine/acquisition.py:91` | `capex_by_year` |
| `calculate_levered_cash_flows` | `engine/acquisition.py:137` | `capex_by_year` |
| `calculate_recurring_levered_cash_flows` | `engine/returns.py:289` | `capex_by_year` |
| `calculate_recurring_unlevered_cash_flows` | `engine/returns.py:314` | `capex_by_year` |

`capex_by_year` is produced by `calculate_capex_by_year`
(`engine/acquisition.py:59`) as a **constant** `annual_capex_reserve` repeated
`H` times, derived from `AcquisitionTerms` — not from the operating projection.
There is today no channel through which an operating-projection producer can
emit a below-NOI, year-varying cost.

**Finding F-1.** This is a **D4** problem. D1, D2 and D3 do not require it:
D1 has no capital costs at all, and D2/D3 compute TI and LC inside
`anchor.leasing` without yet integrating them into `AcquisitionResults`.

### 2.6 Which new contracts must exist

1. Canonical monthly contracts: per-lease monthly schedule, property monthly
   rent-roll schedule, property monthly operating projection (Section 4.7).
2. A **derived** annual operating projection satisfying `OperatingProjectionLike`.
3. A Lease-Level result envelope holding monthly, annual, and rollover audit
   data alongside the unchanged `AcquisitionResults` (D4).
4. Lease / suite / market-leasing / operating input contracts (Section 4).

### 2.7 Which existing contracts stay untouched

`AcquisitionInputs`, `AcquisitionTerms`, `DetailedOperatingInputs`,
`NoiForecast`, `OperatingProjection`, `OperatingProjectionLike`, `CapitalStack`,
`DebtSchedule`, `AcquisitionCashFlows`, `ReturnMetrics`, `OwnerReturnMetrics`,
`DetailedAcquisitionResults`, `AcquisitionResults`, every `anchor.analysis`
contract, every `anchor.ai` contract, and every `anchor.deals` contract.

**Through D3, that list has no exceptions.** `AcquisitionResults` is revisited
only at D4, under HD-1.

### 2.8 Does any architecture assume annual-only operating cash flow?

**Only at the downstream-engine boundary, never structurally.**

- `AcquisitionResults` exposes `_by_year` tuples of length `H` and
  `_cash_flows` of length `H+1`.
- The IRR solver (`engine/returns.py:231`) is an **annual periodic** IRR over a
  length-`H+1` series and would be silently wrong if handed monthly flows. It
  must never receive monthly data.
- `calculate_annual_debt_service` (`engine/debt.py:294`) already runs monthly
  internally and aggregates chronologically, deliberately refusing the
  `12 * PMT` shortcut. That module is the in-repo precedent for the
  monthly-canonical / annual-derived pattern.

### 2.9 Do acquisition / debt / returns depend on NOI rather than broader cash flow?

Yes, and this must be preserved:

- Exit value: `exit_noi / exit_cap_rate` — NOI only.
- DSCR: `NOI_y / ADS_y` — NOI before capital reserves, per
  `docs/underwriting_v2_financial_conventions.md` ("Standard lender covenant
  practice computes DSCR on NOI before capital reserves").
- Year 1 Debt Yield: `NOI_1 / loan_amount` — NOI only.
- Cash flows and owner return metrics: NOI **less** `capex_by_year`.

NOI-based metrics stay NOI-based; only cash-flow-based metrics need the D4
capital-cost channel.

### 2.10 Where lease-level capital costs can live without corrupting NOI

In a below-NOI series **alongside** `capex_by_year` — never inside it, and never
inside `total_operating_expenses`. Anchor's below-NOI list is stated in
`docs/detailed_operating_model_v2_1_financial_conventions.md` ("NOI
Convention"): `annual_capex_reserve`, debt service, financing fees, acquisition
costs, disposition costs. TI and LC join that list at D4.

`capex_by_year`'s current invariant — a constant `annual_capex_reserve` in every
year — is asserted by `tests/test_underwriting_v2_gate3_capex.py` and must stay
true, which is why folding TI/LC into it is not a candidate design.

### 2.11 Persistence

`src/anchor/deals/store.py` — SQLite, `_SCHEMA_VERSION = 4`, two tables
(`deals`, `detailed_deals`), an idempotent `_migrate()` driven by
`PRAGMA table_info` rather than `user_version` alone, and JSON snapshot columns
each paired with a `..._schema_version` and a `..._fingerprint`.
`_ANALYSIS_SNAPSHOT_SCHEMA_VERSION = 1`.

`Deal.__post_init__` (`deals/contracts.py:104`) enforces the mode invariant. A
third mode extends the same pattern. `anchor.deals` never imports an
`anchor.engine` *calculation* module — only result *shapes*
(`tests/test_deals_architecture.py`).

### 2.12 Excel ingestion

Both readers (`excel_reader.py`, `detailed_excel_reader.py`) parse a single
`Inputs` worksheet as a **key/value** table with headers
`("Field ID", "Input", "Value", "Unit")`, one row per scalar field, duplicates
rejected. `workbook_schema.py` reads an optional `Meta` sheet declaring
`anchor_schema` and `schema_version`.

**Finding F-2.** A rent roll is a repeating row-per-lease table. No existing
reader shape accommodates it. D5 problem.

### 2.13 OM ingestion

`ExtractionResult` (9 fields) and `DetailedExtractionResult` (22 fields) are
**flat, fixed-arity** records: one named `FieldCandidates` per scalar field.
`EvidenceStatus` is exactly five states; `Provenance` is
`(page, anchor, snippet)` verified against real `DocumentAnchor`s.

**Finding F-3.** A rent roll is variable-arity (N leases × M fields). The
candidate model needs a repeating-group shape. D5 problem.

### 2.14 Frontend

`web/src/underwrite.ts` defines five Underwrite tabs
(`acquisition | operations | debt | exit | results`) and a `ResultsViewId`
sub-navigation that is already **mode-derived** (`resultsViewsFor(mode)` adds
`operating-statement` only for Detailed). `FieldSection.view` supports per-tab
sub-navigation. `UnderwriteWorkspace.tsx` keeps every tab mounted-but-`hidden`
so unsaved input survives a tab switch. Quick and Detailed keep completely
independent state while sharing one component tree.

`web/src/workspaces.ts` locks five workspaces; the navigation-over-scrolling
philosophy is stated in `docs/workspace_ux_visual_system_v3_spec.md`.

### 2.15 Validation

`src/anchor/validation.py` is deterministic and issue-collecting (unknown IDs →
missing IDs → per-field domain issues in canonical order), raising
`InputValidationError(issues)`. **There is no severity concept** — every issue
is fatal. `InputIssue` already carries `row`/`rows`, used by the Excel reader,
so row-level issue reporting has a precedent.

**Finding F-4.** Lease-Level needs non-fatal warnings. It gets them in a
**leasing-scoped** validation layer; the global validator is not refactored
(Section 19, HD-6).

### 2.16 Sensitivity / break-even

`DETAILED_SUPPORTED_ASSUMPTIONS` (`analysis/sensitivity.py:60`) is exactly the
four `AcquisitionTerms` dimensions (`purchase_price`, `exit_cap_rate`, `ltv`,
`interest_rate`) — no Detailed-only dimension was added. Lease-Level adopts the
identical four-dimension set in D4, for the same reason.
`docs/detailed_operating_model_v2_1_architecture.md` §9 prescribes the pattern
for a scenario carrying non-`AcquisitionInputs` state: wrap the whole deal in
one immutable container and `dataclasses.replace` the container.

### 2.17 Existing architecture guardrails

Per `docs/solutions/conventions/testing-conventions-and-architecture-guardrails.md`,
four reusable shapes exist and must be extended, not reinvented: AST-parsing
import-boundary tests; runtime data-flow spy tests; delegation proofs via
`unittest.mock.patch(..., wraps=...)`; spec-sourced golden cases at
`pytest.approx(expected, rel=0.0, abs=1e-9)`.

---

## 3. Recommended System Architecture

### 3.1 Convergence diagram

```
QUICK                  DETAILED                LEASE-LEVEL
AcquisitionInputs      AcquisitionTerms        AcquisitionTerms
                       + DetailedOperating     + LeaseLevelPropertyInputs
                         Inputs                + Suites / Leases
                                               + MarketLeasingAssumptions  (D2)
                                               + LeaseLevelOperatingInputs (D3/D4)
      |                     |                          |
      v                     v                          v
build_quick_        build_detailed_          build_lease_monthly_schedules
operating_          operating_                        |
projection          projection                        v
      |                     |               MonthlyPropertyProjection
      |                     |                  (CANONICAL, user-facing)
      |                     |                          |
      |                     |                          v
      |                     |               aggregate_monthly_to_annual()
      |                     |                          |
      v                     v                          v
 NoiForecast        OperatingProjection      AnnualOperatingProjection
 (3 fields)         (12 schedules + 3)       (line items + the 3 fields)
      |                     |                          |
      +----------+----------+-------------+------------+
                 |                        |
                 v                        v
      analyze_acquisition_from_operating_projection(
          operating_projection: OperatingProjectionLike,
          terms: AcquisitionTerms,
          [D4: + a neutral below-NOI capital-cost channel — HD-1])
                 |
                 v
         AcquisitionResults
```

Only the **derived annual** projection ever crosses into the downstream engine.
The canonical monthly projection is retained on the Lease-Level result envelope
and served to the UI (Section 23).

### 3.2 Phase-by-phase blast radius outside `anchor.leasing`

| Phase | Files modified outside `anchor.leasing` |
|---|---|
| **D1** | **None.** New package + new tests only |
| **D2** | **None.** New modules inside `anchor.leasing` + new tests |
| **D3** | **None** (recoveries are computed inside `anchor.leasing`) |
| **D4** | `engine/acquisition.py`, `engine/contracts.py`, `contracts.py` (`OperatingMode.LEASE_LEVEL`) — the below-NOI channel and the mode entry point |
| **D5** | `api.py`, `deals/*`, `ingestion/*`, `web/src/*`, plus a new Excel reader |

This staging is what makes HD-1 a D4 decision rather than a D1 blocker: nothing
before D4 needs an answer.

### 3.3 Why not force Lease-Level into `DetailedOperatingInputs`

`DetailedOperatingInputs` requires `gross_potential_rent` and
`vacancy_credit_loss_pct` as *inputs*. In Lease-Level both are *outputs*.
Populating them would mean either fabricating a value (forbidden) or running
two competing revenue and vacancy mechanisms at once. This is the same
reasoning that produced `AcquisitionTerms` rather than a merged 25-field
`AcquisitionInputs` (`docs/detailed_operating_model_v2_1_architecture.md` §2.4),
applied one level down.

### 3.4 Why not replace `OperatingProjectionLike` with a universal cash-flow contract

A unified `PropertyCashFlow` replacing `OperatingProjectionLike` would require
Quick and Detailed to produce fields they have no basis for (monthly schedules,
physical occupancy, leasing costs) — exactly the fabrication the architecture
forbids. `OperatingProjectionLike` is the minimum true common denominator,
proven by two producers. A third producer with a superset shape is strictly
less invasive.

Note this does **not** prejudge HD-1: the D4 below-NOI channel may still be
given a deliberately *property-neutral* name and meaning (Section 32, HD-1),
because a future Development Engine would need the same channel. Neutrality of
the channel and stability of `OperatingProjectionLike` are independent choices.

### 3.5 Module layout

```
src/anchor/leasing/               # new isolated package
    __init__.py                   # public entry points only
    contracts.py                  # D1: property/suite/lease inputs; ModelMonth;
                                  #     LeaseMonthlySchedule; PropertyRentRollSchedule
    validation.py                 # D1: leasing-scoped ERROR/WARNING validation
    calendar.py                   # D1: month identity + alignment predicates
    rent.py                       # D1: contractual base-rent monthly timeline
    aggregation.py                # D1: property monthly build + monthly->annual
    market.py                     # D2: market rent timeline
    rollover.py                   # D2: expiration, expected successor, downtime
    leasing_costs.py              # D2: TI, LC, free rent
    recoveries.py                 # D3: NNN / Gross / Modified Gross
    expenses.py                   # D4: property operating expenses, other income
    projection.py                 # D4: MonthlyPropertyProjection + annual derivation
```

`anchor.leasing` imports from `anchor.contracts` (for `AcquisitionTerms`, from
D4) and `anchor.engine.contracts` (for `ensure_finite` / `NonFiniteResultError`)
and nothing else from `anchor`. It never imports `anchor.engine.acquisition`,
`anchor.engine.debt`, `anchor.engine.noi`, `anchor.engine.returns`,
`anchor.ai`, `anchor.deals`, `anchor.ingestion`, or `anchor.analysis`.
Enforced by `tests/test_leasing_architecture.py` (**G-1**).

At D4, `anchor.engine.acquisition` imports `anchor.leasing` — never the reverse.

---

## 4. Domain Contracts

### 4.1 Entity decisions

| Concept | Decision | Rationale |
|---|---|---|
| **Property** | `LeaseLevelPropertyInputs` — a small scalar record, not an entity graph | Only `analysis_start_date` and `property_area_sf` are financially load-bearing |
| **Suite / Space** | **First-class entity:** `Suite` | A suite persists across leases. It is what rolls over, what sits vacant, and what carries a market-rent override |
| **Tenant** | **No entity.** `tenant_name: str \| None` on `Lease` | A tenant matters financially only via credit and multi-suite rollup, neither in competition scope. Two leases for one tenant are two rows with equal `tenant_name` |
| **Lease** | **First-class entity, separate from `Suite`** | One suite has many leases over time. A successor lease has no known tenant, which a merged Tenant/Lease entity could not represent |
| **Market leasing assumptions** | Property-level default + optional per-suite override (D2) | Simplest structure that credibly handles a mixed-quality building |

### 4.2 `LeaseLevelPropertyInputs`  *(D1)*

| Field | Type | Units | Required | Domain | Meaning | I/D |
|---|---|---|---|---|---|---|
| `analysis_start_date` | `date` | — | required | **first day of a calendar month** | First day of Month 1. The single anchor for month identity and for market-rent growth | input |
| `property_area_sf` | `float` | SF | required | `> 0` | Total rentable area. Denominator for occupancy and the area invariant | input |

Deliberately absent: `property_name`, `address`, `property_type`, `year_built` —
those are `DealContext` (`ingestion/contracts.py:161`), informational, never
engine inputs.

### 4.3 `Suite`  *(D1; D2 adds the override fields)*

| Field | Type | Units | Required | Domain | Meaning | I/D | Phase |
|---|---|---|---|---|---|---|---|
| `suite_id` | `str` | — | required | non-empty, unique in property | Stable identity. **Financial**: the key binding a lease to the space that rolls over | input | D1 |
| `suite_label` | `str \| None` | — | optional | — | Display name ("Suite 300"). Informational | input | D1 |
| `suite_area_sf` | `float` | SF | required | `> 0` | Rentable area | input | D1 |
| `market_rent_psf` | `float \| None` | $/SF/yr | optional | `>= 0` | Suite market-rent override as of `analysis_start_date`; `None` → property default | input | D2 |
| `market_leasing_override` | `MarketLeasingAssumptions \| None` | — | optional | — | Full suite-level override | input | D2 |

A **vacant suite** is a `Suite` with no lease covering a given month — never a
synthetic "vacant lease" row.

### 4.4 `Lease`  *(D1; later phases add only the marked fields)*

| Field | Type | Units | Required | Domain | Meaning | I/D | Phase |
|---|---|---|---|---|---|---|---|
| `lease_id` | `str` | — | required | non-empty, unique in property | Stable identity | input | D1 |
| `suite_id` | `str` | — | required | must match a `Suite.suite_id` | The space this lease occupies | input | D1 |
| `tenant_name` | `str \| None` | — | optional | — | Informational; `None` for a successor lease | input | D1 |
| `leased_area_sf` | `float` | SF | required | `> 0`; `== Suite.suite_area_sf` in D1–D3 | Area this lease covers; basis for rent and (later) TI | input | D1 |
| `rent_commencement_date` | `date` | — | required | **first day of a calendar month** | First date base rent is owed | input | D1 |
| `lease_expiration_date` | `date` | — | required | **last day of a calendar month**, `>= rent_commencement_date` | **Inclusive** last date base rent is owed | input | D1 |
| `lease_start_date` | `date \| None` | — | optional | `<= rent_commencement_date` | Possession date. **Informational only — never enters any economic calculation**, and therefore *not* month-alignment-validated | input | D1 |
| `base_rent_psf` | `float` | $/SF/yr | required | `>= 0` | Contractual annual base rent per SF **as of `rent_commencement_date`** | input | D1 |
| `escalation_pct` | `float` | decimal | required | `> -1` | Annual fixed escalation; `0.0` = flat | input | D1 |
| `escalation_basis` | `EscalationBasis` | enum | required | `NONE` \| `LEASE_ANNIVERSARY` | D1 supports exactly these two | input | D1 |
| `lease_type` | `LeaseType` | enum | required | `NNN` \| `GROSS` \| `MODIFIED_GROSS` | Recovery structure. **Captured in D1; economically inert until D3** | input | D1 |
| `free_rent_months` | `float` | months | optional, default `0.0` | `>= 0` | Abated base rent from rent commencement | input | D2 |
| `recovery_basis` | `RecoveryBasis \| None` | — | required for `MODIFIED_GROSS` at D3 | — | Explicit analyst-approved recovery basis. **Never invented** (Section 16) | input | D3 |
| `origin` | `LeaseOrigin` | enum | derived | `IN_PLACE` \| `SUCCESSOR` | Analyst-supplied vs. rollover-generated | derived | D2 |

#### 4.4.1 `leased_area_sf == Suite.suite_area_sf` in D1–D3

Partial-suite leases require sub-suite space accounting (demising, partial
rollover, partial downtime) — genuine property-management complexity with no
competition payoff. **One suite = one leasable unit.** A physically subdivided
suite is modeled as two `Suite` rows. Mismatch is a validation ERROR.

`leased_area_sf` remains an explicit field because it is what a rent roll
states and what rent and TI are computed from; relaxing the equality later is
then a validation change, not a contract change.

#### 4.4.2 Excluded from D1

A third distinct occupancy date, security deposits, guarantees, option periods,
expansion/contraction/termination rights, percentage rent, CPI indexation,
tenant credit, subleases, holdover terms, explicit dated rent steps
(Section 6.6).

### 4.5 `MarketLeasingAssumptions`  *(D2)*

Property-level default; optionally overridden per suite.

| Field | Type | Units | Domain | Meaning |
|---|---|---|---|---|
| `market_rent_psf` | `float` | $/SF/yr | `>= 0` | Market rent **as of `analysis_start_date`** |
| `market_rent_growth` | `float` | decimal | `> -1` | Annual step growth on `analysis_start_date` anniversaries |
| `renewal_probability` | `float` | decimal | `0 <= p <= 1` | Probability the sitting tenant renews |
| `renewal_rent_psf` | `float \| None` | $/SF/yr | `>= 0` | Explicit renewal rent **as of `analysis_start_date`**; `None` → derived from spread |
| `renewal_rent_spread` | `float` | decimal | `> -1` | Renewal rent as discount/premium to market; `0.0` = at market |
| `renewal_term_months` | `int` | months | `>= 1` | Successor term if renewed |
| `new_term_months` | `int` | months | `>= 1` | Successor term if re-let |
| `renewal_downtime_months` | `float` | months | `>= 0` | Downtime on renewal (typically `0.0`) |
| `new_downtime_months` | `float` | months | `>= 0` | Downtime before a replacement tenant |
| `renewal_free_rent_months` | `float` | months | `>= 0` | Free base rent on renewal |
| `new_free_rent_months` | `float` | months | `>= 0` | Free base rent for a new tenant |
| `renewal_ti_psf` | `float` | $/SF | `>= 0` | TI allowance on renewal |
| `new_ti_psf` | `float` | $/SF | `>= 0` | TI allowance for a new tenant |
| `leasing_commission_method` | `LeasingCommissionMethod` | enum | exactly one member in D2 | The LC method seam (Section 12.3) |
| `renewal_lc_pct` | `float` | decimal | `0 <= x <= 1` | LC rate, renewal |
| `new_lc_pct` | `float` | decimal | `0 <= x <= 1` | LC rate, new tenant |
| `successor_escalation_pct` | `float` | decimal | `> -1` | Annual escalation written into successor leases |

Every renewal-side and new-tenant-side assumption is stored **separately and
permanently**; the expected successor never overwrites or discards them
(Section 8.4).

### 4.6 `LeaseLevelOperatingInputs`  *(D3/D4)*

| Field | Type | Units | Domain | Phase |
|---|---|---|---|---|
| `other_income` | `float` | $/yr | `>= 0` | D4 |
| `other_income_growth` | `float` | decimal | `> -1` | D4 |
| `property_taxes` | `float` | $/yr | `>= 0` | D4 |
| `insurance` | `float` | $/yr | `>= 0` | D4 |
| `utilities` | `float` | $/yr | `>= 0` | D4 |
| `repairs_maintenance` | `float` | $/yr | `>= 0` | D4 |
| `other_operating_expenses` | `float` | $/yr | `>= 0` | D4 |
| `management_fee_pct` | `float` | decimal | `0 <= x <= 1` | D4 |
| `expense_growth` | `float` | decimal | `> -1` | D4 |
| `recoverable_expense_ratio` | `float` | decimal | `0 <= x <= 1` | D3 |
| `credit_loss_pct` | `float` | decimal, default `0.0` | `0 <= x <= 1` | D4 |

`other_income_growth` is separate from any rent growth: Lease-Level has no
single `revenue_growth`, because rent growth comes from lease escalations and
market rent. There is deliberately **no** `vacancy_credit_loss_pct` and no
`occupancy` field (Section 15).

### 4.7 Canonical monthly and derived annual output contracts

#### `ModelMonth` — month identity  *(D1)*

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ModelMonth:
    """One canonical monthly period. Carries BOTH identities so a monthly
    figure can be audited against a calendar without re-deriving it from
    array position."""
    period_index: int      # 1-based sequential model month
    month_start: date      # first calendar day of that month
    hold_year: int         # 1..H for hold months; H+1 for the forward exit window
    is_forward_exit_month: bool
```

Invariants (asserted): `period_index == array position + 1`;
`month_start == analysis_start_date + (period_index - 1) months`;
`hold_year == ((period_index - 1) // 12) + 1`;
`is_forward_exit_month == (period_index > 12 * H)`.

#### `LeaseMonthlySchedule` — per lease  *(D1, extended D2/D3)*

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseMonthlySchedule:
    lease_id: str
    suite_id: str
    origin: LeaseOrigin
    first_rent_period: int | None      # None if the lease never pays in-window
    last_rent_period: int | None
    # flow, $ per month
    contractual_base_rent: tuple[float, ...]   # GROSS, never net of free rent
    free_rent: tuple[float, ...]               # D2; positive, subtracted
    expense_recoveries: tuple[float, ...]      # D3
    tenant_improvements: tuple[float, ...]     # D2; below NOI
    leasing_commissions: tuple[float, ...]     # D2; below NOI
    # state
    occupied_area: tuple[float, ...]           # SF occupied by THIS lease
    occupancy_factor: tuple[float, ...]        # 0.0..1.0; <1 only in a
                                               #   fractional downtime boundary month
```

#### `PropertyRentRollSchedule` — property, monthly  *(D1; the D1 deliverable)*

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class PropertyRentRollSchedule:
    months: tuple[ModelMonth, ...]                 # length 12H + 12
    lease_schedules: tuple[LeaseMonthlySchedule, ...]
    # flow
    contractual_base_rent: tuple[float, ...]
    # state
    occupied_area: tuple[float, ...]
    vacant_area: tuple[float, ...]
    physical_occupancy: tuple[float, ...]
```

#### `MonthlyPropertyProjection` — the canonical projection  *(D4)*

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class MonthlyPropertyProjection:
    months: tuple[ModelMonth, ...]
    rent_roll: PropertyRentRollSchedule            # retained, not collapsed
    # --- flow, above NOI ---
    contractual_base_rent: tuple[float, ...]
    free_rent: tuple[float, ...]
    expense_recoveries: tuple[float, ...]
    other_income: tuple[float, ...]
    credit_loss: tuple[float, ...]
    effective_gross_income: tuple[float, ...]
    property_taxes: tuple[float, ...]
    insurance: tuple[float, ...]
    utilities: tuple[float, ...]
    repairs_maintenance: tuple[float, ...]
    other_operating_expenses: tuple[float, ...]
    management_fee: tuple[float, ...]
    total_operating_expenses: tuple[float, ...]
    noi: tuple[float, ...]
    # --- flow, below NOI ---
    tenant_improvements: tuple[float, ...]
    leasing_commissions: tuple[float, ...]
    # --- state ---
    occupied_area: tuple[float, ...]
    vacant_area: tuple[float, ...]
    physical_occupancy: tuple[float, ...]
    market_rent_psf: tuple[float, ...]
    # --- audit ---
    rollover_events: tuple[RolloverEvent, ...]
```

#### `AnnualOperatingProjection` — derived  *(D4)*

Constructed **solely** by `aggregate_monthly_to_annual(monthly)`. Satisfies
`OperatingProjectionLike`.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class AnnualOperatingProjection:
    # --- flow, Years 1..H: each entry is the chronological sum of 12 months ---
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
    noi_by_year: tuple[float, ...]                 # <- OperatingProjectionLike
    tenant_improvements_by_year: tuple[float, ...] # below NOI
    leasing_commissions_by_year: tuple[float, ...] # below NOI
    # --- state, explicitly named (Section 5.7) ---
    occupied_area_at_year_end: tuple[float, ...]
    vacant_area_at_year_end: tuple[float, ...]
    physical_occupancy_at_year_end: tuple[float, ...]
    average_physical_occupancy_over_year: tuple[float, ...]
    market_rent_psf_at_year_end: tuple[float, ...]
    # --- exit ---
    exit_noi: float                                # <- OperatingProjectionLike
    going_in_cap_rate: float                       # <- OperatingProjectionLike
    exit_window_leasing_costs: float               # DISCLOSED, never deducted
```

#### `RolloverEvent` — audit trail  *(D2)*

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class RolloverEvent:
    suite_id: str
    expiring_lease_id: str
    successor_lease_id: str
    expiration_period: int
    commencement_period: int
    renewal_probability: float
    # component assumptions, preserved verbatim (Section 8.4)
    renewal_rent_psf: float
    new_rent_psf: float
    renewal_term_months: int
    new_term_months: int
    renewal_downtime_months: float
    new_downtime_months: float
    renewal_free_rent_months: float
    new_free_rent_months: float
    renewal_ti_psf: float
    new_ti_psf: float
    renewal_lc_pct: float
    new_lc_pct: float
    # resulting expected successor
    expected_rent_psf: float
    expected_downtime_months: float
    expected_free_rent_months: float
    expected_term_months: int
    tenant_improvements: float
    leasing_commissions: float
    assumption_source: str        # "property_default" | "suite_override"
```

This is the audit surface that lets an analyst — or the AI Analyst, which may
only *describe* it — answer "which assumption produced this rollover, and where
did it come from" from the output alone.

---

## 5. Time: Canonical Monthly Periods

### 5.1 The principle

**Monthly is canonical. Monthly and annual are both published.** Annual values
are derived from monthly values by summation (flow) or by an explicitly named
snapshot/average (state). No annual Lease-Level quantity is ever produced by an
independent annual formula.

Rejected alternatives: **annual-only** (cannot express a mid-year expiration,
downtime, free rent, or rent commencement without inventing a fractional-year
convention per event); **daily** (requires day-count conventions and buys
precision a rent roll's own stated terms do not possess); **quarterly** (leases
are stated in months; no constituency).

`engine/debt.py` is the in-repo precedent for monthly-canonical /
annual-derived — this is a pattern Anchor already trusts, not a novelty.

### 5.2 Month identity

Every canonical month carries a `ModelMonth` (4.7) with **both** a sequential
index and a real calendar month. Consumers must never rely on array position
alone for audit or display.

```
month_index(d) = 12 * (d.year - s.year) + (d.month - s.month) + 1
                 where s = analysis_start_date
```

Pure integer arithmetic — no `timedelta`, no day counts, therefore leap-year-
and timezone-independent by construction.

### 5.3 The period map, stated exactly

For hold period `H` and `analysis_start_date = s`:

| Period | Definition |
|---|---|
| **Month 1** | The calendar month containing `s`. `month_start == s` |
| **Month 12** | Last month of hold Year 1 |
| **Month 13** | First month of hold Year 2 |
| **Month `12(y-1)+1 .. 12y`** | Hold Year `y`, for `1 <= y <= H` |
| **Month `12H`** | **Hold-end month.** The sale occurs at the end of this month |
| **Month `12H+1`** | **First forward exit month** |
| **Month `12H+12`** | **Last forward exit month** |
| **Total months** | `12H + 12` |

Worked example, `s = 2027-01-01`, `H = 5`:

```
Month 1  = Jan 2027      Month 12 = Dec 2027   (end of Year 1)
Month 13 = Jan 2028      (start of Year 2)
Month 60 = Dec 2031      (hold-end month; sale at end of Month 60)
Month 61 = Jan 2032      (first forward exit month)
Month 72 = Dec 2032      (last forward exit month)
Total    = 72 months
```

Acquisition occurs at the instant before Month 1 begins — time `0` in the
existing cash-flow convention. No operating cash flow occurs at time `0`.

### 5.4 Whole monthly economic periods

Lease-Level economics are recognized in **whole monthly periods**. A lease pays
its full monthly base rent in every period from its first rent period through
its last rent period inclusive, and nothing outside that range.

```
first_rent_period(L) = month_index(L.rent_commencement_date)
last_rent_period(L)  = month_index(L.lease_expiration_date)
```

`lease_expiration_date` is **inclusive**: the month containing it is fully paid.

The only fractional monthly factors that exist anywhere in the model are the
two assumption-driven boundary factors defined in Sections 9.3 and 10.3
(downtime and free rent). Contractual leases are never prorated.

### 5.5 Economic dates must be month-aligned  *(HD-3, locked)*

**Rule.**

| Date | Requirement | Violation |
|---|---|---|
| `analysis_start_date` | Must be the **first day** of a calendar month | ERROR `ANALYSIS_START_NOT_MONTH_ALIGNED` |
| `rent_commencement_date` | Must be the **first day** of a calendar month | ERROR `LEASE_DATE_NOT_MONTH_ALIGNED` |
| `lease_expiration_date` | Must be the **last day** of a calendar month | ERROR `LEASE_DATE_NOT_MONTH_ALIGNED` |
| `lease_start_date` | Informational only; **no alignment requirement** | — |

A non-aligned economic date is a **deterministic validation ERROR**. It is
never coerced, never rounded, never warned-and-approximated.

**Why an error and not a full-month approximation.** A lease expiring on the
second day of a month would, under an any-overlap-pays rule, collect an entire
month's rent it is not owed. That is a knowing overstatement of revenue. Anchor
does not produce approximate lease economics where the current scope cannot
model them correctly — it refuses and says so.

**Why exact alignment rather than a materiality threshold.** A threshold ("only
error if more than N days off") is itself a silent approximation with an
arbitrary boundary, and it would make the same rent roll behave differently for
reasons an analyst cannot see. Exact alignment is checkable, explainable, and
has one rule.

**Why the rule is hold-period-independent.** Alignment is validated for every
lease regardless of whether its dates fall inside the projection window. A rule
that depended on `H` would make the same rent roll validate at `H = 5` and fail
at `H = 10` — a surprise with no economic justification.

**How an analyst resolves a genuinely non-aligned lease.** By explicitly
normalizing the date at the approval boundary (e.g. an expiration of
`2028-06-15` becomes `2028-05-31` or `2028-06-30`), recording which they chose
and why. That is an analyst decision on the record, not an engine guess.
Actual-day proration may be added in a later phase if competition cases require
it; it is additive and changes no contract.

**Successor leases** generated by the rollover engine (D2) are month-aligned by
construction — they are created from period indices, never from dates — so this
rule constrains only analyst-supplied leases.

### 5.6 Monthly → annual aggregation of flow metrics

```
AnnualFlow_y = sum of MonthlyFlow_m for m in 12(y-1)+1 .. 12y,
               accumulated in strictly ascending period order
```

The ascending-order requirement is not stylistic. It mirrors
`calculate_annual_debt_service`'s explicit refusal of the `12 * PMT` shortcut:
repeated IEEE-754 addition in a fixed order is reproducible, while the same
values summed in a different order can differ in the last bits, and Anchor
asserts golden cases at `abs=1e-9`.

Every flow metric aggregates this way, with no exceptions and no metric-specific
annual formula: base rent, free rent, recoveries, other income, credit loss,
EGI, every expense line, management fee, NOI, TI, LC, CapEx, property cash flow.

### 5.7 Flow metrics vs. state metrics

**Flow metrics** describe an amount earned or spent *during* a period. They are
summed.

**State metrics** describe a condition *at* a point in time. Summing them is
meaningless and is a real, easy-to-make error.

| Kind | Metrics |
|---|---|
| **Flow** | base rent, free rent, recoveries, other income, credit loss, EGI, each expense line, management fee, NOI, TI, LC, CapEx, property cash flow |
| **State** | occupied SF, vacant SF, physical occupancy %, market rent $/SF, lease status, remaining lease term, loan balance (if ever exposed) |

**Naming rule (enforced).** Every published annual **state** series name must
either begin with `average_` or end with `_at_year_end` / `_at_year_start`. A
state series may never carry a bare `_by_year` name that could be mistaken for a
summable flow. Guardrail **G-M6** asserts this over the dataclass field names.

D4 publishes, for each state metric it exposes:

- `..._at_year_end` — the value in month `12y` (the canonical annual snapshot);
- `average_..._over_year` — the arithmetic mean of the twelve monthly values,
  where an average is the economically meaningful annual figure (occupancy is
  the case that matters; average occupancy is what analysts quote).

Both are published where both are useful, precisely so neither can be mistaken
for the other. Neither is ever a sum.

### 5.8 Debt timing

Debt requires no change. `calculate_debt_schedule` already produces
`annual_debt_service` from a chronological monthly loop and
`remaining_loan_balance` from a monthly amortization recurrence. The lease
engine produces `noi_by_year` on the same Year-1..Year-H boundaries, so
`DSCR_y = NOI_y / ADS_y` compares two quantities covering the identical twelve
months.

**Monthly debt service must never be fabricated as `annual_debt_service / 12`.**
If a monthly debt view is wanted (D4/D5, optional), it must be exposed from the
existing monthly chronology inside `engine/debt.py` and must produce **no
economic change** to any existing figure. Guardrail **G-M11**.

Monthly DSCR, monthly distributions, and monthly IRR are out of scope.

### 5.9 Scale

A 10-year hold is `120 + 12 = 132` canonical months. Competition properties
carry dozens of leases; a large one might carry a few hundred. Two hundred
leases × 132 months × a dozen series is on the order of a few hundred thousand
floats — trivial for Python, and the projection is computed once per analysis.

No premature optimization. But the architecture must avoid four specific
pathologies, each of which is a guardrail rather than a performance note:

1. recomputing lease economics in the frontend (**G-M7**);
2. an independent annual lease engine (**G-M3**);
3. losing calendar identity and relying on array position (**G-M9**);
4. cloning the full schedule repeatedly without reason — each lease schedule is
   built once and aggregated once.

---

## 6. Contractual Base Rent

### 6.1 The formula

For lease `L` and canonical month `m`:

```
if m < first_rent_period(L) or m > last_rent_period(L):
    ContractualBaseRent(L, m) = 0.0
else:
    k = escalation_period_index(L, m)
    AnnualRentPSF(L, m)       = L.base_rent_psf * (1 + L.escalation_pct)^k
    ContractualBaseRent(L, m) = AnnualRentPSF(L, m) * L.leased_area_sf / 12.0
```

`base_rent_psf` is **$/SF/year**. The division by 12 happens **once, last** —
never by converting to a monthly PSF first — so the floating-point operation
order is fixed and reproducible. Every result passes through `ensure_finite`.

### 6.2 Escalation chronology — locked

```
escalation_basis = NONE               ->  k = 0 for every month
escalation_basis = LEASE_ANNIVERSARY  ->  k = floor((m - first_rent_period(L)) / 12)
```

**`first_rent_period(L)` here is the raw, unclamped value** —
`month_index(rent_commencement_date)`, which is zero or negative for a lease
that commenced before acquisition.

**Acquisition does not reset a lease's escalation clock.** An in-place lease
acquired midway through its contractual term continues from the correct
contractual step. A lease that commenced two years before `analysis_start_date`
with 3% anniversary escalations is on step `k = 2` in Month 1, not step `0`.

Worked check (`s = 2026-01-01`, commencement `2024-01-01`):

```
raw first_rent_period = month_index(2024-01-01) = 12*(2024-2026) + (1-1) + 1 = -23
k(m=1)  = floor((1 - (-23)) / 12) = floor(24/12) = 2      -> Jan 2026, third step
k(m=12) = floor((12 + 23) / 12)   = floor(35/12) = 2      -> Dec 2026, same step
k(m=13) = floor((13 + 23) / 12)   = floor(36/12) = 3      -> Jan 2027, next step
```

The anniversary falls in January, exactly as the lease says. Golden case
**D1-G3** pins this (Section 27); failure mode **FM-5** is the error it guards.

`LEASE_ANNIVERSARY` means each 12-month anniversary of **rent commencement** —
not of the analysis start, not of the calendar year. `CALENDAR_YEAR` is a
deferred additive enum member (6.6).

### 6.3 Rent stated as a total rather than per SF

**D1 accepts `base_rent_psf` only.** A rent roll stating total annual rent is
normalized at the approval boundary (`base_rent_psf = annual_rent /
leased_area_sf`), never inside the engine. Two accepted representations would
mean two code paths, a precedence rule, and a reconciliation failure mode when
both are supplied and disagree. The conversion is one division an analyst can
verify.

### 6.4 Leases relative to the hold

| Situation | Treatment |
|---|---|
| Commenced before `analysis_start_date` | Normal. Raw `first_rent_period <= 0`; the schedule starts paying at Month 1; the escalation index uses the **raw** value (6.2) |
| Commencing during the window | Normal. Zero rent before `first_rent_period` |
| Expiring during the window | Normal. Zero rent after `last_rent_period`. **In D1 the space simply goes vacant** — rollover is D2 |
| Expired before `analysis_start_date` | ERROR `LEASE_EXPIRED_BEFORE_ANALYSIS_START` — it is not a lease of this deal |
| Commencing after month `12H+12` | WARNING `LEASE_STARTS_AFTER_HORIZON`. Retained; contributes nothing |
| Expiring after month `12H+12` | Normal, truncated at the window. WARNING `LEASE_EXTENDS_BEYOND_HORIZON` |

### 6.5 Rounding

**No rounding anywhere in the engine.** Full IEEE-754 double precision
end-to-end, as in every existing Anchor calculator. Rounding is presentation
only (`src/anchor/formatting.py`, `web/src/format.ts`). Golden cases assert at
`pytest.approx(expected, rel=0.0, abs=1e-9)`.

### 6.6 Rent structures not supported in D1

| Structure | Earliest phase | Note |
|---|---|---|
| Explicit dated rent steps | D2+ | Needs a `RentStep` child contract. Most likely first extension — real abstracts often state steps rather than a percentage |
| `CALENDAR_YEAR` escalation basis | D2+ | Additive enum member |
| Fixed `$/SF` annual bumps | D2+ | Additive enum member |
| CPI / indexation | Deferred | Requires an inflation assumption Anchor does not have |
| Percentage / turnover rent | Deferred | Requires tenant sales data |
| Monthly scheduled overrides | Deferred | Effectively hand-entering the answer |
| Mid-term abatement other than at commencement | Deferred | Free rent at commencement covers the competition case |

A competition case containing any of these is handled by the analyst
normalizing it into a supported structure at the approval boundary, with the
assumption recorded — never by the engine guessing.

---

## 7. Market Rent  *(D2)*

### 7.1 Structure

**Property-level default with optional suite-level override.** A `Suite` may
override `market_rent_psf` alone (the common case: better or worse space) or the
entire `MarketLeasingAssumptions` record (the rarer case: a retail suite in an
office building).

Rejected: a single property-wide value (cannot express ground-floor retail at
$60/SF in a $35/SF building); per-suite only with no default (guarantees
inconsistency across twenty suites); a `space_type` taxonomy (adds a
classification, its validation, its UI and its precedence rule to buy what the
suite override already buys).

### 7.2 Growth — locked: annual step growth on analysis anniversaries

`market_rent_psf` is measured **as of `analysis_start_date`** — it is the
Month-1 market rent.

```
MarketRentPSF(m) = market_rent_psf * (1 + market_rent_growth)^floor((m - 1) / 12)
```

Growth applies in **annual steps on anniversaries of `analysis_start_date`**,
held flat within each 12-month band. Months 1–12 use exponent `0`, months 13–24
exponent `1`, and so on.

Worked example (`analysis_start_date = 2026-01-01`, `$40.00`, `3.00%`):

```
Months  1-12   $40.000000
Months 13-24   $41.200000
Months 25-36   $42.436000
Months 37-48   $43.709080
Months 49-60   $45.020352400
Months 61-72   $46.370962972
```

Two things this rule explicitly is **not**:

- **Not monthly-compounded.** `(1+g)^((m-1)/12)` is smoother but departs from
  Anchor's frozen annual-growth timing convention, makes every golden case a
  fractional power, and buys precision a market-rent assumption does not
  possess. Deferred as a possible later alternative; not the first version.
- **Not reset per lease anniversary.** Market rent is a *market* assumption
  anchored to the analysis date. Contractual escalation is a *lease* term
  anchored to the lease (Section 6.2). These are different concepts with
  different clocks, and conflating them is failure mode **FM-6**.

Golden case **D2-G1** pins the Month 12 → Month 13 boundary and proves market
rent does **not** step on a lease anniversary.

### 7.3 Market rent at rollover

The rent applied to a successor lease is `MarketRentPSF(c)` where `c` is the
successor's **rent commencement period** — after downtime, never at the
expiration period. Charging pre-downtime market rent is failure mode **FM-18**.

### 7.4 Precedence

```
Suite.market_leasing_override.market_rent_psf   (if the override is not None)
  > Suite.market_rent_psf                        (if not None)
  > MarketLeasingAssumptions.market_rent_psf     (property default; always present)
```

See Section 24 for the full precedence rules.

---

## 8. Lease Expiration and Rollover  *(D2)*

### 8.1 What happens at expiration

At `last_rent_period(L)` for lease `L` on suite `S`, the rollover engine creates
**exactly one** successor lease `L'` on `S`, covering the full `suite_area_sf`.
`L'` is itself eligible to roll over when it expires, so a short remaining term
in a long hold produces a chain. Generation stops when a successor's
commencement period exceeds `12H + 12`.

### 8.2 The expected rollover successor — locked

Let `p = renewal_probability`. The successor's economic parameters are the
`p`-weighted combination of the renewal-side and new-tenant-side assumptions:

```
expected_rent_psf        = p * RenewalRentPSF(c) + (1 - p) * MarketRentPSF(c)
expected_downtime_months = p * renewal_downtime_months + (1 - p) * new_downtime_months
expected_free_rent_months= p * renewal_free_rent_months + (1 - p) * new_free_rent_months
expected_ti_psf          = p * renewal_ti_psf + (1 - p) * new_ti_psf
expected_lc_pct          = p * renewal_lc_pct + (1 - p) * new_lc_pct
expected_term_months     = round_half_up(p * renewal_term_months + (1 - p) * new_term_months)
escalation_pct           = successor_escalation_pct
escalation_basis         = LEASE_ANNIVERSARY
lease_type               = the expiring lease's lease_type
tenant_name              = None
origin                   = SUCCESSOR
```

where `c` is the successor's rent commencement period (8.5) and
`RenewalRentPSF(c)` follows Section 24.3.

`round_half_up` is stated explicitly because term length feeds the *next*
rollover date; the rounding rule must be deterministic and written down rather
than inherited from a language default (Python's `round` is banker's rounding).

### 8.3 Why this convention

- **Deterministic.** Same inputs, same outputs, always. No Monte Carlo anywhere
  in the base underwriting engine.
- **Auditable.** Every weighted parameter is one number, and every component
  that produced it is preserved (8.4).
- **Scenario-compatible.** `p = 1.0` reproduces a pure renewal path exactly;
  `p = 0.0` reproduces a pure vacate / new-tenant path exactly. An analyst who
  wants a named discrete path sets an endpoint.
- **Avoids fractional physical occupancy.** One suite, one successor, integral
  space. Occupancy stays reportable and the area invariant (18.4) holds.
- **Suitable for competition underwriting.** It expresses "most tenants renew"
  without pretending to know which ones do.

**Explicitly rejected: two independent probabilistic cash-flow branches
recursing through the hold.** After the first rollover the branches have
different expiration dates, so the second rollover has no single date; by the
third the result is an average over a tree no analyst can enumerate. It is
unauditable and it makes the rollover log meaningless.

**Explicitly rejected: fractional physical suites.** No suite is ever partly
occupied by a renewing tenant and partly by a replacement.

**Explicitly rejected: Monte Carlo.** Not in the base engine, under any framing.

**No external-product attribution is claimed for this convention.** It is
Anchor's approved competition-underwriting convention, justified by the
properties listed above and nothing else.

### 8.4 The successor is an assumption, not a known tenant

The expected successor is an **expected rollover economic assumption**. It
corresponds to no single real-world outcome: at `p = 0.65` it pays a rent no
actual tenant would pay.

Two consequences are mandatory:

1. **Every component assumption is preserved** on the `RolloverEvent` (4.7) —
   renewal rent, new rent, both terms, both downtimes, both free-rent counts,
   both TI rates, both LC rates, and `p` itself. The expected values never
   overwrite or discard them.
2. **The successor is never presented as a known tenant.** Its `tenant_name` is
   `None`; the UI must label it as an expected rollover assumption, and a
   `WEIGHTED_ROLLOVER_APPLIED` warning is raised whenever `0 < p < 1`. Failure
   mode **FM-19**.

### 8.5 Successor timing

```
e = expiration_period(L) = last_rent_period(L)
D = expected_downtime_months                     (>= 0.0, may be fractional)

commencement_period(L') = c = e + 1 + floor(D)
last_rent_period(L')        = c + expected_term_months - 1
```

Fully vacant periods are `e+1 .. c-1` — exactly `floor(D)` of them. Period `c`
carries the fractional boundary factor defined in 9.3. Section 9.3 proves total
rent forgone equals exactly `D` months for any real `D >= 0`.

### 8.6 Leases extending beyond the window

A lease whose `last_rent_period` exceeds `12H + 12` is truncated: periods beyond
the window are never computed for revenue purposes. No "remaining term value"
adjustment is made — that value is already captured by the exit cap rate applied
to exit NOI, and a second adjustment would double-count.

The single exception is the LC basis, which uses the full contractual term
(Section 12.2) because the commission is a real obligation incurred in full.

### 8.7 Rollover inside the forward exit window

Rollover runs **live** through month `12H+12`. A lease expiring in month
`12H+3` rolls, takes its downtime, and affects `exit_noi`. This is intentional
(Section 17, HD-5).

---

## 9. Downtime  *(D2)*

### 9.1 Definition

The number of months between an expiring lease's last paying period and its
successor's first paying period during which the suite produces no base rent and
no recoveries. Units: months, `float`, `>= 0`. Renewal and new-tenant downtimes
are separate inputs, weighted per 8.2 (renewal downtime is typically `0.0`,
since a renewing tenant does not vacate).

### 9.2 What happens during downtime

| Item | Treatment | Rationale |
|---|---|---|
| Base rent | `0.0` | The suite is empty |
| Expense recoveries (D3) | `0.0` | No tenant to reimburse. Continuing them is **FM-14** |
| Operating expenses | **Continue in full** | Taxes, insurance and R&M do not stop when a suite empties. Under NNN the landlord now bears the previously recovered share — precisely the economic cost of vacancy, and the main reason lease-level beats property-level modeling. Stopping them is **FM-14b** |
| Management fee | Continues, computed on the now-lower EGI | Unchanged mechanic |
| Market rent growth | Continues | A market fact, independent of this suite's status |
| Other income | Continues | Property-level (Section 14) |
| Physical occupancy | The suite's area moves to `vacant_area` | The occupancy series is the audit surface |
| TI / LC | **Not** paid during downtime — paid at successor rent commencement | Sections 11, 12 |

### 9.3 Fractional downtime — the exact rule

Let `e` = expiration period, `D` = downtime months, `c = e + 1 + floor(D)`.

```
occupancy_factor(e + j) = 1 - clamp(D - (j - 1), 0.0, 1.0)      for j >= 1

periods e+1 .. c-1        : factor 0.0   (exactly floor(D) periods)
period  c                 : factor 1 - (D - floor(D))
periods c+1 onward        : factor 1.0
```

Base rent and recoveries in period `c` are multiplied by that factor. Operating
expenses, other income, TI and LC are **never** multiplied by it.

Verification of the invariant *total forgone = D*:

| `D` | `floor(D)` | fully vacant periods | `c` | factor at `c` | forgone |
|---|---|---|---|---|---|
| `0.0` | 0 | none | `e+1` | `1.0` | `0.0` |
| `3.0` | 3 | `e+1..e+3` | `e+4` | `1.0` | `3.0` |
| `5.5` | 5 | `e+1..e+5` | `e+6` | `0.5` | `5 + 0.5 = 5.5` |
| `6.0` | 6 | `e+1..e+6` | `e+7` | `1.0` | `6.0` |

When `D` is a whole number the factor is exactly `1.0` and period `c` is an
ordinary full month — the rule degenerates to the intuitive case with **no
special-cased branch**. Golden case **D2-G3b** pins the fractional case.

### 9.4 No interaction with a general vacancy factor

Lease-Level has no `vacancy_credit_loss_pct` field on any contract
(Section 15), so Detailed's general vacancy cannot be applied on top of modeled
downtime. The mechanism is absent, not merely discouraged. Guardrail **G-M14**.

---

## 10. Free Rent  *(D2)*

### 10.1 Convention

| Question | Answer |
|---|---|
| Units | **Months** (`float`, `>= 0`) |
| Start | At **rent commencement** — the first `F` months of the paying term. Contiguous, never scattered |
| What is abated | **Base rent only** |
| Recoveries during free rent | **Unaffected by free rent itself.** Whether a tenant reimburses during an abatement is a function of the lease's recovery structure (D3), not of the free-rent input. Free rent never implicitly switches recoveries off |
| Above or below NOI | **Above NOI.** Free rent is a revenue abatement, not a capital cost. It is reported as its own positive-valued line, subtracted in the EGI build. It is **never** reclassified as a below-NOI capital cost |
| Renewal vs new tenant | Separate inputs, weighted per 8.2 |
| In-place leases | `Lease.free_rent_months`, default `0.0` |
| Fractional months | Symmetric to downtime (10.3) |

### 10.2 Operating-statement placement

```
Contractual Base Rent          (GROSS -- never netted)
  less Free Rent               <-- here
  plus Expense Recoveries
  plus Other Income
  less Credit Loss
= Effective Gross Income
```

`contractual_base_rent` always reports the **gross** contractual figure. It is
what reconciles to the rent roll and what the LC basis is computed from
(Section 12.2). Netting free rent into it is failure mode **FM-16b**.

### 10.3 Fractional free rent

With `F` free-rent months from commencement period `c`:

```
periods c .. c + floor(F) - 1   : fully abated
period  c + floor(F)            : abated fraction = F - floor(F)
periods after that              : no abatement
```

Total abated equals exactly `F` months. When `F` is whole there is no partial
period.

### 10.4 Downtime and free rent never overlap

Downtime ends at the successor's rent commencement; free rent begins there.
They are sequential by construction. Counting a period as both is failure mode
**FM-13**; guardrail **G-5** asserts the two period-index sets are disjoint for
every successor lease.

---

## 11. Tenant Improvements  *(D2)*

| Question | Answer |
|---|---|
| Basis | `$/SF` × `leased_area_sf` |
| Renewal vs new | Separate rates, weighted per 8.2 |
| Timing | Paid **in full in one period: the successor's rent commencement period `c`** |
| Above or below NOI | **Below NOI.** TI never reduces reported NOI, EGI, DSCR or debt yield |
| Draw schedule | Not supported in D2. Single payment |
| Prorated by a downtime boundary factor? | **No** |
| TI on in-place leases | **None.** An in-place lease's TI was spent by the seller before acquisition. Charging it again is **FM-11** |

```
TI(L') = expected_ti_psf * L'.leased_area_sf,  recognized entirely in period c
```

**Why rent commencement rather than lease signing.** Anchor has no lease-signing
date, and adding one would require a signing-to-commencement lag assumption on
every speculative successor — a number no analyst can source. Rent commencement
is unambiguous and already computed.

**Why single-payment.** A draw schedule moves a below-NOI cost by a few months,
crossing at most one year boundary after annual aggregation. It is not worth a
schedule contract, a validation surface and a UI in D2. Additive later.

**Consequence to disclose:** a rollover late in the hold can push its TI into
the forward exit window, where it is disclosed but not deducted (17.4).

---

## 12. Leasing Commissions  *(D2)*

### 12.1 There is no universal market convention

Institutional practice genuinely varies: percentage of total contractual base
rent over the term; percentage of first-year rent; stepped percentages by lease
year; `$/SF`. Anchor picks one, says so, and does not claim it is universal.

### 12.2 The approved Anchor convention — locked for D2

**`%` of total contractual base rent over the successor lease term, including
contractual escalations, gross of free rent, over the full contractual term
untruncated by the hold horizon.**

```
LC(L') = expected_lc_pct * sum(
             GrossContractualBaseRent(L', m)
             for m in first_rent_period(L') .. last_rent_period(L')
         )
```

recognized entirely in period `c`, **below NOI**.

| Sub-decision | Choice | Why |
|---|---|---|
| Free rent in the basis? | **Included** (gross of free rent) | A commission is earned on the lease signed, not reduced by a concession the landlord chose to grant. It also keeps the basis reconcilable to the rent schedule |
| Escalations in the basis? | **Included** | The commission is on the full contractual rent stream. Excluding escalations would understate LC on nearly every real lease |
| Term truncated at the horizon? | **No — the full contractual term** | The obligation is incurred in full at signing. Truncating it understates a cost the buyer actually pays. Truncation is **FM-17** |

This is the one place the engine evaluates contractual rent **beyond** month
`12H+12` — solely to form a commission basis. Those periods never enter any
revenue, EGI or NOI series.

### 12.3 The method extension seam — required, not optional

`MarketLeasingAssumptions.leasing_commission_method` is a
`LeasingCommissionMethod` enum with **exactly one member in D2**:
`PCT_OF_TOTAL_CONTRACTUAL_BASE_RENT`.

The method lives on the **market leasing assumptions**, never on `Lease`.
Adding `PER_SF` (or `PCT_OF_FIRST_YEAR_RENT`) later means adding one enum member
and the rate fields it needs to `MarketLeasingAssumptions` — **no change to the
`Lease` contract, no change to any lease schedule, no migration of lease data**.

D2 implements one method. The seam exists so that adding a second never requires
replacing the lease contract.

### 12.4 LC on in-place leases

**None** — the commission was paid by the seller, same as TI (11).

---

## 13. Operating Expenses  *(D4; D3 depends on the categories)*

### 13.1 Reuse the Detailed expense concepts and formulas

Property operating expenses stay **property-level assumptions**. Lease-Level
changes how *revenue and occupancy* are derived, not how expenses behave.

The six Detailed expense concepts — Property Taxes, Insurance, Utilities,
Repairs & Maintenance, Other Operating Expenses, and a Management Fee as a
percentage of EGI — are reused **unchanged in meaning and formula**.

**The input contract is separate** (`LeaseLevelOperatingInputs`, 4.6) because
`DetailedOperatingInputs` requires `gross_potential_rent`,
`vacancy_credit_loss_pct` and `revenue_growth`, all of which are Lease-Level
*outputs* or absent concepts. Reusing that contract would force fabricating
three values and would create a second, competing vacancy mechanism.

**The reuse mechanism is a D4.0 implementation decision, with a stated bias
toward extracting a shared, pure expense-growth helper** rather than writing a
second copy of `ExpenseLine_y = ExpenseLine_1 * (1 + g)^(y-1)`. Any such
extraction is a pure refactor of `engine/operating_projection.py` and carries a
hard proof obligation: **G-2** must show the Detailed golden case bit-identical
before anything else in D4 proceeds. If that cannot be shown, D4 falls back to a
parallel implementation in `anchor.leasing/expenses.py`, and the duplication is
accepted as the price of not risking Detailed.

**Detailed's behavior is never changed to accommodate Lease-Level.** Not its
formulas, not its contract, not its outputs.

### 13.2 Monthly formulas

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

The five fixed lines are annual amounts spread evenly across the twelve months
of their hold year. Expense seasonality (a lumpy property-tax bill) is
deliberately not modeled: it changes nothing at annual aggregation, which is the
only resolution any downstream consumer sees, and the monthly display of an
evenly-spread expense is honest about being an accrual.

For the forward exit window (`hold_year = H+1`), the same formulas apply with
`y = H + 1`.

---

## 14. Other Income  *(D4)*

**Property-level, not lease-level.** Parking, storage, signage, antenna and
miscellaneous income are one property-level annual amount growing at
`other_income_growth`, spread evenly across the months of each hold year.

```
OtherIncome_y = other_income * (1 + other_income_growth)^(y-1)
OtherIncome_m = OtherIncome_y / 12.0
```

Attributing parking to individual leases would require a stall count per lease,
a stall rate, and a rule for stalls during downtime — three inputs and a
convention, to move a small revenue line between two buckets that sum to the
same EGI.

Two accepted, disclosed consequences:

1. Other income does not fall when a suite goes vacant. An analyst modeling a
   building whose parking income genuinely tracks occupancy reduces
   `other_income` manually and records why.
2. Percentage rent, being tenant-specific, has no home here and stays deferred
   unless a competition case demonstrably requires it.

Other income is above NOI, is **not** subject to `credit_loss_pct` (which
applies to lease revenue), and is **not** part of the recovery base.

**D1 does not depend on other income in any way.**

---

## 15. Vacancy — locked

### 15.1 Physical vacancy is modeled, never assumed

- A suite with no lease covering month `m` contributes zero rent and its full
  area to `vacant_area[m]`.
- A suite in downtime contributes zero rent (or the boundary factor, 9.3) and
  its area to `vacant_area[m]`.
- `physical_occupancy[m] = occupied_area[m] / property_area_sf`.

### 15.2 Detailed's general vacancy field does not exist here

Applying a blanket vacancy percentage on top of explicitly modeled vacancy would
double-count. **No Lease-Level contract declares `vacancy_credit_loss_pct` or
`occupancy`** — the mechanism is structurally absent, asserted by **G-M14**.

This mirrors how Detailed resolved the same class of problem with `occupancy`
(`docs/detailed_operating_model_v2_1_financial_conventions.md`, "Occupancy and
Vacancy — Resolved Relationship"): the second mechanism is simply absent from
the mode's contract rather than reconciled against the first.

### 15.3 The five vacancy concepts

| Concept | Lease-Level treatment |
|---|---|
| Physical vacancy | Modeled explicitly, per suite, per month |
| Downtime | Modeled explicitly (Section 9) — physical vacancy with a cause |
| Economic vacancy | An **output**: `1 - (actual base rent / market-rent potential)`. Never an input |
| Collection / credit loss | The one optional allowance: `credit_loss_pct` on lease revenue (base rent net of free rent, plus recoveries). Default `0.0` |
| Structural / general vacancy reserve | **Deferred** (15.5) |

### 15.4 Credit loss is not vacancy

| | Detailed | Lease-Level |
|---|---|---|
| Field | `vacancy_credit_loss_pct` (required) | `credit_loss_pct` (optional, default `0.0`) |
| Base | Gross Potential Rent | Base rent net of free rent, plus recoveries |
| Covers | Vacancy **and** credit loss, blended | Credit loss (bad debt) **only** |
| Physical vacancy | Implicit inside the percentage | Explicit, modeled, reported monthly |

An analyst converting a Detailed deal must **not** carry a 7%
`vacancy_credit_loss_pct` across as a 7% `credit_loss_pct`. The UI label must
read "Credit Loss", never "Vacancy & Credit Loss", and a
`UNUSUALLY_HIGH_CREDIT_LOSS` warning fires above 10%.

### 15.5 Why a general vacancy reserve is deferred

A "general vacancy" top-up to a structural minimum is legitimate institutional
practice and also the highest-risk double-count in the model, because it is
*designed* to overlap with modeled downtime and needs a top-up rule
(`max(0, target - modeled)`) that is easy to state and easy to get wrong.

Deferred to post-D4, and only ever with an explicit **top-up, never additive**
convention. Until then, an analyst wanting conservatism raises
`new_downtime_months` or lowers `renewal_probability` — both modeled, visible
and defensible.

---

## 16. Expense Recoveries  *(D3 architecture; not implemented)*

### 16.1 Structures D3 must support

| Structure | Convention |
|---|---|
| **NNN** | Tenant reimburses its pro-rata share of recoverable operating expenses |
| **Gross** | Tenant reimburses nothing. `Recovery = 0` |
| **Modified Gross** | Tenant reimburses its pro-rata share of recoverable expenses **above an explicit contractual basis** |

Three structures, matching `LeaseType`, which D1 already captures.

### 16.2 Modified Gross requires an explicit recovery basis — locked

**A contractual base year or expense stop is not the buyer's first hold year.**
Anchor must never invent one.

D3 requires an explicit, analyst-approved `recovery_basis` on every
`MODIFIED_GROSS` lease. The supported representations are a D3 design decision;
candidates include an explicit expense stop in `$/SF`, an explicit base-year
recoverable-expense amount, or another explicitly contractual basis.

**Locked principle: missing required Modified Gross recovery information must
not be fabricated.** It surfaces as a validation **ERROR**
(`MISSING_MODIFIED_GROSS_RECOVERY_BASIS`) or, once D5's approval workflow
exists, as an unresolved analyst assumption that blocks analysis — never as a
silent default and never as a Hold-Year-1 substitute. Failure mode **FM-24**.

### 16.3 The D3 formulas

```
ProRataShare(L)       = L.leased_area_sf / property_area_sf
RecoverableExpenses_m = (TotalOpex_m - ManagementFee_m) * recoverable_expense_ratio

NNN:             Recovery(L, m) = ProRataShare(L) * RecoverableExpenses_m
GROSS:           Recovery(L, m) = 0.0
MODIFIED_GROSS:  Recovery(L, m) = ProRataShare(L)
                                * max(0.0, RecoverableExpenses_m - Stop_m(L))
```

where `Stop_m(L)` derives from the lease's explicit `recovery_basis`, and for
every structure:

```
Recovery(L, m) = 0.0 whenever the suite is vacant or in downtime in month m
Recovery(L, m) is scaled by the fractional boundary factor in period c (9.3)
```

The management fee is excluded from the recovery base because in most leases it
is either non-recoverable or recovered under a separate admin-fee provision —
and including it would create a circularity (recoveries raise EGI, which raises
the fee, which raises recoveries).

### 16.4 Placement and the fixed computation order

Recoveries are **revenue above EGI**, on their own line (10.2). The circularity
is broken by a fixed, non-iterative per-month order:

```
1. Base rent, free rent, other income        (independent)
2. Fixed operating expense lines             (independent)
3. RecoverableExpenses_m                     (from 2; excludes the fee)
4. Recoveries per lease                      (from 3)
5. Credit loss                               (from 1 and 4)
6. EGI                                       (from 1, 4, 5)
7. Management fee                            (from 6)
8. TotalOpex, then NOI                       (from 2, 7, 6)
```

One deterministic pass, no fixed-point solve. A D3 test asserts this ordering
explicitly.

### 16.5 Deferred recovery features

Admin fees on recoveries; gross-up to stabilized occupancy; recovery caps
(annual and cumulative); floors; per-category recoverability; separate operating
and tax stops. Each is real; none is required to underwrite a competition case
credibly; all are additive to the D3 contracts.

---

## 17. Exit NOI — locked

### 17.1 The convention

```
exit_noi = sum(noi[m] for m in 12H+1 .. 12H+12)
```

taken from **the same canonical monthly projection the user can inspect**, with
rollover, downtime, free rent, recoveries and operating expenses all live in
that window.

### 17.2 Why, and what was rejected

| Candidate | Verdict |
|---|---|
| Year-`H` NOI | **Rejected.** Contradicts the existing convention in both Quick and Detailed; values the property on trailing income |
| **Live forward months `12H+1..12H+12`** | **Approved.** The monthly restatement of `docs/financial_conventions.md`'s "next-twelve-month forward NOI after the final hold year" and of Detailed's `NOI_(H+1)` full-year build |
| `12 ×` a single month | **Rejected.** Hostage to whichever concession falls in that month |
| A smoothed / normalized exit NOI suppressing rollover | **Rejected.** Hides a real cost and would make a building with a Year-6 mass expiry look identical to one leased through Year 10 — exactly the risk lease-level modeling exists to reveal |

### 17.3 Consistency across the three modes

| Mode | `exit_noi` | Same concept? |
|---|---|---|
| Quick | `current_noi * (1 + noi_growth)^H` = `NOI_(H+1)` | Yes |
| Detailed | Full Year `H+1` line-item build | Yes |
| Lease-Level | Sum of monthly NOI, months `12H+1..12H+12` | Yes |

All three answer "what does the property earn in the twelve months after we
sell it," at their own resolution. **No existing convention changes.**

### 17.4 Auditability and the disclosed sharp edges

**There is never a separate exit-NOI lease calculation.** `exit_noi` is a
summation over twelve entries of the canonical monthly projection. The future
monthly UI must be able to show those exact twelve periods beneath the terminal
value. Guardrail **G-M12**; failure mode **FM-22**.

Disclosed consequences:

1. **A rollover just after sale reduces exit value.** At a 6.5% cap rate one
   lost month of NOI moves exit value by roughly 15× that month's NOI. Real, but
   large enough to look like a cliff in a sensitivity grid. A
   `ROLLOVER_IN_EXIT_WINDOW` warning fires.
2. **Free rent inside the window** reduces exit NOI for the same reason.
3. **TI and LC in the window are below NOI**, so they do not reduce `exit_noi`
   and are not paid by the seller. `AnnualOperatingProjection.exit_window_leasing_costs`
   reports them as a **disclosed diagnostic that is never deducted from
   anything**, so the analyst can weigh them against the exit cap rate rather
   than be surprised by them.

### 17.5 Downstream extension required

**None.** `exit_noi` remains a single float consumed by `calculate_exit_value`.
`exit_window_leasing_costs` is read by no engine calculation.

---

## 18. Property Aggregation

### 18.1 Canonical monthly categories, in statement order

**Above NOI (flow):**

1. `contractual_base_rent` — gross scheduled base rent, all leases, in-place and
   successor. **Never** net of free rent
2. `free_rent` — positive, subtracted (D2)
3. `expense_recoveries` (D3)
4. `other_income` (D4)
5. `credit_loss` — positive, subtracted (D4)
6. `effective_gross_income` = 1 − 2 + 3 + 4 − 5
7. the six operating expense lines, then `total_operating_expenses`
8. `noi` = 6 − 7

**Below NOI (flow), never touching any line above:**

9. `tenant_improvements` (D2)
10. `leasing_commissions` (D2)
11. `capex` (D4, from `terms.annual_capex_reserve`)

**State:**

12. `occupied_area`, `vacant_area`, `physical_occupancy`, `market_rent_psf`

### 18.2 Renewal and replacement rent are not separate revenue lines

Under the expected-successor convention there is one successor lease with one
expected rent. Splitting it into "renewal rent" and "replacement rent" lines
would require un-blending a deliberate expectation, and the split would be
fictional.

What the analyst actually needs — which space rolled, when, at what rent, at
what cost, and from which component assumptions — is delivered exactly by
`rollover_events` (4.7) and by the per-lease `LeaseMonthlySchedule`s.

### 18.3 The above/below-NOI boundary is a hard invariant

```
noi[m] never depends on tenant_improvements[m] or leasing_commissions[m],
at any month, under any input.
```

Guardrail **G-3** asserts this by perturbation: doubling every TI and LC input
must leave every `noi` month, every `noi_by_year`, `exit_noi`,
`going_in_cap_rate`, every `dscr_by_year` and `year_1_debt_yield`
**bit-identical**, while changing the cash-flow series and both IRRs once D4
wires the channel. That one test simultaneously proves TI/LC are below NOI, that
DSCR matches lender practice, and that the D4 channel is genuinely connected.

### 18.4 Annual aggregation and the area invariant

Flow: chronological summation (5.6). State: explicit snapshot or average (5.7).

Invariant asserted in **every** month:

```
occupied_area[m] + vacant_area[m] == property_area_sf     (abs=1e-9)
```

This is the structural guarantee that no fractional physical space was ever
created (8.3), and the direct defense against failure mode **FM-12b**.

Validation additionally requires `sum(suite_area_sf) <= property_area_sf`, any
shortfall being common area (Section 19.3).

### 18.5 Reconciliation

Guardrail **G-M4**: for every flow metric and every year,

```
annual[y] == sum(monthly[12(y-1)+1 .. 12y])     (abs=1e-9)
```

asserted directly, on real projections, not merely by construction. This is what
makes the monthly and annual user-facing views provably consistent.

---

## 19. Validation

### 19.1 Leasing-scoped severity — locked (HD-6)

Lease-Level needs ERROR and WARNING. **D1 does not modify Anchor's global
validation architecture to get them.**

A leasing-scoped validation layer is introduced inside `anchor.leasing`:

```python
class LeaseIssueSeverity(StrEnum):
    ERROR = "error"        # default
    WARNING = "warning"

@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseValidationIssue:
    severity: LeaseIssueSeverity = LeaseIssueSeverity.ERROR
    code: str                     # stable machine-readable code
    path: str                     # e.g. "leases[3].lease_expiration_date"
    message: str

@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseValidationResult:
    errors: tuple[LeaseValidationIssue, ...]
    warnings: tuple[LeaseValidationIssue, ...]
```

Any error raises `LeaseValidationError(result)`; warnings are returned and
carried through to the result envelope for display. `src/anchor/validation.py`
is **not touched in D1** — not by an added enum, not by an added field.

Whether Anchor's *global* validation should later gain severity is a separate
architectural decision for a later phase, made on its own merits. D1 is not
coupled to it.

Exact production names may follow repository style; the four properties
(severity, stable code, path, message) are the requirement.

Ordering is deterministic: property-level issues first, then suites in declared
order, then leases in declared order, then per-record fields in canonical field
order. No silent defaults — a missing required value is an issue, never a
substituted zero.

### 19.2 ERROR rules

| Code | Condition |
|---|---|
| `ANALYSIS_START_NOT_MONTH_ALIGNED` | `analysis_start_date` is not the first day of a month |
| `LEASE_DATE_NOT_MONTH_ALIGNED` | `rent_commencement_date` is not the first day of a month, or `lease_expiration_date` is not the last day of a month |
| `PROPERTY_AREA_OUT_OF_DOMAIN` | `property_area_sf <= 0` |
| `SUITE_AREA_OUT_OF_DOMAIN` | `suite_area_sf <= 0` |
| `LEASE_AREA_OUT_OF_DOMAIN` | `leased_area_sf <= 0` |
| `LEASE_AREA_MISMATCH` | `leased_area_sf != suite_area_sf` (D1–D3) |
| `DUPLICATE_SUITE_ID` / `DUPLICATE_LEASE_ID` | Identifier collision |
| `UNKNOWN_SUITE_REFERENCE` | `Lease.suite_id` matches no `Suite` |
| `LEASE_EXPIRES_BEFORE_COMMENCEMENT` | `lease_expiration_date < rent_commencement_date` |
| `LEASE_POSSESSION_AFTER_RENT_START` | `lease_start_date > rent_commencement_date` |
| `LEASE_EXPIRED_BEFORE_ANALYSIS_START` | `last_rent_period < 1` |
| `OVERLAPPING_LEASES_IN_SUITE` | Two leases on one suite with overlapping `[first_rent_period, last_rent_period]` ranges |
| `BASE_RENT_OUT_OF_DOMAIN` | `base_rent_psf < 0` |
| `ESCALATION_OUT_OF_DOMAIN` | `escalation_pct <= -1` |
| `LEASED_AREA_EXCEEDS_PROPERTY_AREA` | `sum(suite_area_sf) > property_area_sf` |
| `NON_FINITE_VALUE` | Any non-finite input or intermediate |
| *D2* `RENEWAL_PROBABILITY_OUT_OF_DOMAIN` | `p` outside `[0, 1]` |
| *D2* `NEGATIVE_DOWNTIME` / `NEGATIVE_FREE_RENT` | `< 0` |
| *D2* `TI_OUT_OF_DOMAIN` / `LC_OUT_OF_DOMAIN` | TI `$/SF < 0`; LC `%` outside `[0, 1]` |
| *D2* `TERM_OUT_OF_DOMAIN` | `renewal_term_months < 1` or `new_term_months < 1` |
| *D2* `MISSING_MARKET_LEASING_ASSUMPTIONS` | A lease expires in-window, or a suite is vacant, with no resolvable assumptions |
| *D3* `MISSING_MODIFIED_GROSS_RECOVERY_BASIS` | A `MODIFIED_GROSS` lease has no explicit `recovery_basis` (16.2) |

### 19.3 WARNING rules

| Code | Condition | Why non-fatal |
|---|---|---|
| `AREA_SHORTFALL_TREATED_AS_COMMON_AREA` | `sum(suite_area_sf) < property_area_sf` | Legitimate (lobbies, mechanical), but occupancy is then computed on a denominator including non-leasable area, which the analyst must intend |
| `LEASE_STARTS_AFTER_HORIZON` | `first_rent_period > 12H+12` | Harmless; contributes nothing |
| `LEASE_EXTENDS_BEYOND_HORIZON` | `last_rent_period > 12H+12` | Expected; noted so the analyst knows revenue is truncated while the LC basis is not (12.2) |
| *D2* `WEIGHTED_ROLLOVER_APPLIED` | `0 < renewal_probability < 1` on any suite | Discloses that the successor is an expected assumption, not a known tenant (8.4) |
| *D2* `ROLLOVER_IN_EXIT_WINDOW` | A rollover commences in months `12H+1..12H+12` | Materially affects `exit_noi` (17.4) |
| *D4* `UNUSUALLY_HIGH_CREDIT_LOSS` | `credit_loss_pct > 0.10` | Usually a Detailed vacancy figure carried across by mistake (15.4) |

### 19.4 What validation deliberately does not do

It does not coerce a date, substitute a default for a missing required value,
infer a recovery basis, or downgrade an economic error to a warning. Where the
current scope cannot model something correctly, validation refuses.

---

## 20. Missing Data

**Anchor never fabricates a lease term.** A missing value is reported as
missing; the analyst supplies it.

| Missing field | Behavior |
|---|---|
| `lease_expiration_date` | **ERROR.** A lease with no end is not a lease |
| `rent_commencement_date` | **ERROR.** For an in-place lease the analyst may set it to `analysis_start_date` with `escalation_basis = NONE` and a recorded note — an analyst decision, never an engine default |
| `base_rent_psf`, `leased_area_sf` | **ERROR** |
| `escalation_pct` | Analyst-supplied, shown as `0.0` in the approval form for explicit acceptance. Never silently applied behind an empty field |
| `lease_type` | Analyst-supplied. Required in D1 though inert until D3, precisely so the analyst confronts it once with the document in hand |
| *D2* `market_rent_psf` | **ERROR** if any rollover or vacant suite exists in-window |
| *D2* `renewal_probability` | **ERROR.** Every plausible default (0, 0.5, 1) implies a materially different deal |
| *D2* downtime / TI / LC | **ERROR** wherever a rollover occurs in-window |
| *D3* Modified Gross `recovery_basis` | **ERROR** (16.2) |

Provenance for analyst-supplied values is a D5 question (Section 32, HD-8) and
does not affect D1–D4.

---

## 21. Ingestion Implications *(design only; nothing implemented)*

### 21.1 The pipeline is unchanged in principle

```
Document / Workbook
       |
       v
Proposed Lease Data          (variable-arity candidates, provenance-verified)
       |
       v
Analyst Approval             (per field, per row)
       |
       v
Canonical Monthly Lease Engine
```

AI/extraction may identify tenant, suite, area, rent, dates, escalations and
lease type. **AI must not calculate the monthly cash-flow schedule.** The
deterministic engine owns monthly economics. Guardrail **G-M8**.

### 21.2 The structural gap and the proposed shape

Both existing extraction contracts are flat and fixed-arity (F-3). A rent roll
is variable-arity:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseCandidateRow:
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

Every existing per-field invariant holds; only the arity is new.

### 21.3 Non-negotiable D5 rules

1. **Approval is per field, not per row.** A row with a `stated` area and a
   `missing` escalation must not be approvable wholesale.
2. **A rejected row produces no lease** — never a zero-rent placeholder.
3. **Market leasing assumptions are never extracted.** No document states
   renewal probability, downtime, TI or LC as fact; proposing them would be
   inventing underwriting judgment.
4. **The classifier never receives raw document bytes** — the existing
   anchors-only rule and its data-flow spy test extend unchanged.
5. **Dates arrive as strings and are normalized deterministically in Python**,
   never by the model. A model returning "month 14" instead of `2027-06-30`
   would be doing lease-timeline arithmetic.
6. **Month-alignment validation applies to extracted dates exactly as to typed
   ones.** A non-aligned extracted date surfaces as an error the analyst
   resolves explicitly (5.5).

### 21.4 Excel rent-roll ingestion

```
Meta sheet:    anchor_schema = "lease_level_acquisition", schema_version = "1.0"
Suites sheet:  Suite ID | Suite Label | Suite Area SF | Market Rent PSF
Leases sheet:  Lease ID | Suite ID | Tenant | Leased Area SF |
               Rent Commencement | Lease Expiration | Base Rent PSF |
               Escalation % | Lease Type | Free Rent Months
Inputs sheet:  the existing Field ID / Input / Value / Unit key-value table
```

The `Inputs` sheet reuses the existing reader wholesale. Only `Suites` and
`Leases` need the new tabular reader, whose issues use the existing
`InputIssue.row` / `.cell` fields.

---

## 22. Persistence Implications *(design only; no migration)*

### 22.1 Source of truth

**Persisted results are not the engine source of truth.** Approved lease inputs
are. Opening a deal re-runs the engine.

| Persisted | Not persisted as truth |
|---|---|
| `AcquisitionTerms` | Successor leases |
| `LeaseLevelPropertyInputs` | `RolloverEvent`s |
| `LeaseLevelOperatingInputs` | Any monthly schedule |
| Property `MarketLeasingAssumptions` | Any annual aggregate |
| `Suite` rows (with overrides) | Any projection |
| `Lease` rows, `origin = IN_PLACE` only | |
| `deal_context` | |
| Analysis / AI snapshots — **cache only** | |

### 22.2 Likely schema shape (D5)

Following the existing two-table precedent, schema version **5** adds:

- `lease_level_deals` — one row per deal, mirroring `detailed_deals`' columns,
  plus JSON-serialized property inputs, operating inputs and property market
  leasing assumptions.
- `lease_level_suites` — `(deal_id, suite_id, ...)`, ordered.
- `lease_level_leases` — `(deal_id, lease_id, suite_id, ...)`, ordered,
  `IN_PLACE` only.

Suites and leases are **relational rows, not one JSON blob**: they are
variable-arity, individually editable, individually validated and individually
shown with row-anchored issues. `_migrate()` extends unchanged in shape —
additive `CREATE TABLE IF NOT EXISTS` plus `PRAGMA table_info`-driven column
adds. No existing table is altered; no Quick or Detailed row is touched.

### 22.3 Monthly results and snapshot payload size

The canonical monthly projection is a **display/cache artifact**, never a
source of truth. A 132-month projection with ~20 flow and state series plus a
per-lease breakdown for a few dozen leases serializes to a payload measured in
hundreds of kilobytes — larger than today's annual-only snapshot, small in
absolute terms.

Three D5 decisions follow, none of which affects D1–D4:

1. **Whether to snapshot the monthly projection at all**, or to recompute it on
   open from approved inputs (cheap: one pass). Recomputation is the simpler
   default and is consistent with "persisted results are not truth."
2. **If snapshotted, whether to store the property-level monthly series only**
   and recompute the per-lease breakdown on demand.
3. **Snapshot schema versioning** follows the existing pattern exactly: a
   version mismatch decodes as "absent" and triggers a re-run, which is the
   already-designed and already-tested degradation path.

### 22.4 Fingerprinting

The deal fingerprint (`deals/fingerprint.py`) must cover **every** suite and
lease field in a stable order, or an edited rent roll would silently reuse a
stale snapshot. This is the highest-risk persistence detail in D5.

---

## 23. UI Implications *(design only; no frontend change)*

### 23.1 Where Lease-Level lives

`Underwrite` workspace → a third `OperatingMode`. The five existing tabs are
retained; only the **Operations** tab and the **Results** sub-navigation change,
both through mechanisms that already exist.

| Tab | Lease-Level content |
|---|---|
| **Acquisition** | Unchanged (`AcquisitionTerms`) |
| **Operations** | Sub-views via the existing `FieldSection.view` mechanism: **Rent Roll**, **Market Leasing**, **Expenses**, **Other Income** |
| **Debt** | Unchanged |
| **Exit** | Unchanged, plus the `exit_window_leasing_costs` disclosure and the rollover-in-exit-window warning |
| **Results** | `resultsViewsFor('lease_level')` → Summary, Cash Flow, Owner Returns, Operating Statement, **Rollover Schedule** |

`resultsViewsFor(mode)` is already mode-derived, so adding a view for one mode
is the extension the function was written for.

### 23.2 The Annual / Monthly toggle

By D5/D6, the relevant Lease-Level result surfaces carry a period toggle:

```
Results -> Operating Statement    [ Annual ] [ Monthly ]
Results -> Cash Flow              [ Annual ] [ Monthly ]
Rent Roll -> [ Lease Detail ] [ Monthly Schedule ]
```

Both views are rendered from authoritative engine output. The monthly view is
**not** a client-side expansion of annual data, and the annual view is **not** a
client-side rollup of monthly data — both come from the engine, and **G-M4**
proves they reconcile.

### 23.3 Monthly rent roll — the one genuinely new surface

```
Tenant / Suite | Jan-27 | Feb-27 | Mar-27 | ...
```

Authoritative values by phase, and nothing beyond them:

- **D1:** contractual base rent; lease status; occupied/vacant state
- **D2:** successor rent; downtime; free rent; TI; LC; rollover status
- **D3:** recoveries

No field may be displayed that the engine does not produce. No value may be
computed in the browser.

### 23.4 Layout constraints, inherited from Sprint C

- **Navigation over long page scrolling.** A 132-column monthly table must not
  turn the page into an unbounded scroll.
- Large monthly tables use **contained horizontal and vertical scrolling**,
  **sticky row labels** (tenant/suite) and **sticky period headers**. The app
  canvas stays stable.
- Every tab stays mounted-but-`hidden` (`UnderwriteWorkspace.tsx`), so an
  in-progress lease row survives a tab switch — structural, not something the
  new component must remember.
- Per-row validation issues anchor to their row, inline, not in a single banner.

### 23.5 The frontend calculates no lease economics

`web/src` must not compute a rent schedule, a month index, an escalated rent, a
rollover date, a TI amount, an LC amount, an annual total from monthly values,
or a monthly value from annual values — not even for a preview. Date→period
normalization is an economic decision (5.5) and belongs in Python. Guardrail
**G-M7**; failure mode **FM-9**.

The one permitted client-side computation is the existing pattern:
presentational formatting of already-computed values (`web/src/format.ts`).

---

## 24. Input Precedence

Every inheritable assumption resolves through exactly one chain.

### 24.1 Market rent level

```
Suite.market_leasing_override.market_rent_psf   (if the override is not None)
  > Suite.market_rent_psf                        (if not None)
  > MarketLeasingAssumptions.market_rent_psf     (property default)
```

### 24.2 Every other market leasing assumption

```
Suite.market_leasing_override.<field>   (if the override is not None)
  > MarketLeasingAssumptions.<field>    (property default)
```

**`market_leasing_override` is all-or-nothing.** When a suite supplies one, that
record is used in full; no field falls through. A partial per-field merge would
make "which value applied" unanswerable without re-running the resolver.
`Suite.market_rent_psf` (24.1) is the single deliberate exception, because
overriding only the rent level is the overwhelmingly common case.

### 24.3 Renewal rent — HD-4, locked

```
resolved.renewal_rent_psf, grown from analysis_start_date to period c   (if not None)
  > MarketRentPSF(c) * (1 + resolved.renewal_rent_spread)
```

**`renewal_rent_psf` is an explicit renewal-rent assumption measured as of
`analysis_start_date`**, the same temporal anchor as `market_rent_psf`. The
engine grows it to the successor's commencement period using the approved market
rent growth convention (7.2):

```
RenewalRentPSF(c) = renewal_rent_psf * (1 + market_rent_growth)^floor((c - 1) / 12)
```

The temporal anchor is stated in the field's documentation and must be visible
in the UI label — for example "Renewal Rent (as of analysis start date)". The
phrase "today's dollars" is **not** used anywhere: it is temporally ambiguous,
since "today" is neither the analysis start nor the rollover date.

This makes the same input produce coherent economics whether a suite rolls in
Year 2 or Year 5, and makes the growth step deterministic and testable.

### 24.4 Contractual lease terms always win

A `Lease`'s own `base_rent_psf`, `escalation_pct`, `escalation_basis`,
`free_rent_months`, `lease_type`, `recovery_basis` and dates are contractual
facts. No market leasing assumption ever overrides them. Market leasing
assumptions apply **only** to successor leases the rollover engine creates and
to vacant suites being leased up.

### 24.5 Resolution is computed once and recorded

The resolver runs once per suite, producing a `ResolvedMarketLeasing` recorded
on every `RolloverEvent` it drives, together with `assumption_source`
(`"property_default"` or `"suite_override"`). An analyst can always answer
"which assumption applied here, and where did it come from" from the output
alone.

---

## 25. Competition-Ready Scope

### 25.1 MUST HAVE (D1–D5)

- Contractual lease rent schedule
- **Monthly rent roll** and **annual rent roll**
- Contractual escalations on true contractual chronology
- Lease commencement and expiration
- Market rent with annual step growth
- Rollover with renewal and new-tenant assumptions
- Downtime
- Free rent
- TI and LC, below NOI
- Common recovery structures (NNN, Gross, Modified Gross with an explicit basis)
- **Monthly property operating view** and **annual property operating view**
- **Annual / Monthly UI toggle**
- Live forward exit NOI, auditable to its twelve months
- Tenant / suite auditability, including the rollover event log
- Explicit physical occupancy and vacancy, no double count
- Full integration with acquisition / debt / returns

### 25.2 SHOULD HAVE (post-D5 if time allows)

- Lease-level overrides beyond the suite level
- Explicit `credit_loss_pct` if a case requires it
- Future LC method expansion via the existing seam (12.3)
- Scenario comparison
- Tenant rollover concentration visualization
- Richer recovery assumptions (caps, admin fees, per-category recoverability)
- Explicit dated rent steps
- A general vacancy top-up with an explicit non-additive rule
- Lease-level sensitivity dimensions

### 25.3 LATER / ARGUS-LIKE COMPLEXITY — deliberately excluded

CPI-linked rent; percentage rent unless a competition demonstrably requires it;
complex contractual options; contraction, expansion and termination rights;
sophisticated recovery caps and floors; detailed gross-up systems; monthly
market-rent compounding alternatives; extensive tenant-credit modeling;
probabilistic Monte Carlo; sub-suite demising and partial-space rollover; TI
draw schedules; development and construction phasing; portfolio rollup; debt
sized on lease-level covenants; monthly IRR and monthly distributions; property
tax reassessment on sale; depreciation and income taxes; waterfalls and promote
structures.

**Competition-ready does not mean copying ARGUS completely.** It means every
lease-level number is correct, auditable and defensible.

### 25.4 The scope test

Would a judge's question be unanswerable without the feature?

- *"What happens when the anchor tenant's lease expires in Year 3?"* — needs
  rollover, downtime, TI, LC. **Must have.**
- *"Show me the twelve months behind your exit NOI."* — needs the monthly view.
  **Must have.**
- *"What is your mark-to-market?"* — needs market rent vs in-place rent.
  **Must have.**
- *"How did you handle the CPI escalator?"* — answerable with "we normalized it
  to a fixed escalation and disclosed the assumption." **Not needed.**
- *"What is the promote at a 20% IRR?"* — a different model. **Not needed.**

---

## 26. Failure Modes — Risk Register

Every entry names its detection mechanism: a validation rule, a golden case, a
guardrail, or a later-gate acceptance test.

| ID | Failure | Why plausible | Detection |
|---|---|---|---|
| **FM-1** | **Annual and monthly schedules disagree** | Two views of the same economics rendered from different sources | **G-M4** reconciliation assertion on real projections; D1.3 test |
| **FM-2** | **A month is omitted during annual aggregation** — 11 months summed into a year | Off-by-one in the `12(y-1)+1 .. 12y` slice | **D1-G8** (100% escalation step makes an omission a 2× error); **G-M4** |
| **FM-3** | **A month is counted twice** — appearing in two years | Same slice error, opposite sign | **D1-G8**; a test asserting the union of year slices is exactly the hold window with no overlap |
| **FM-4** | **Sequential month and calendar month diverge** | Array position used as identity; a lease date normalized against the wrong anchor | `ModelMonth` invariants (4.7); **G-M9**; **D1-G9** |
| **FM-5** | **Contractual escalation restarts at acquisition** — an in-place lease put back on step 0 | Clamping `first_rent_period` to 1 for the schedule invites clamping it for escalation too | **D1-G3**: Month 1 must be on step `k = 2`, and Year 1 must equal **D1-G2**'s Year 3 exactly |
| **FM-6** | **Market-rent growth uses a lease anniversary instead of the analysis anniversary** | The two clocks look interchangeable | **D2-G1**: a lease commencing mid-year must not move the market-rent step |
| **FM-7** | **A flow metric is averaged instead of summed** | Copy-paste from a state-metric aggregation | **G-M5**; **G-M4** would fail by a factor of 12 |
| **FM-8** | **A state metric is summed** — "annual occupancy of 9.6" | `_by_year` naming that hides the distinction | **G-M6** naming rule asserted over dataclass field names; explicit `_at_year_end` / `average_..._over_year` naming (5.7) |
| **FM-9** | **The frontend recalculates annual totals differently** from the engine | A client-side rollup added for a quick toggle | **G-M7** AST/regex test over `web/src/` (D5) |
| **FM-10** | **Rent continues after expiration** | Inclusive vs exclusive period bounds is the commonest indexing error | **D1-G5**: period 30 pays in full, period 31 is exactly `0.0` |
| **FM-11** | **An unsupported partial-month date receives a full month's rent** | The easy "any overlap pays" shortcut | **D1-G10**: non-aligned dates are a validation ERROR (5.5); **G-M15** |
| **FM-11b** | **TI or LC charged on in-place leases** | Applying market leasing assumptions uniformly to every lease | **D1-G1** (zero TI, zero LC); **D2-G2** |
| **FM-12** | **Vacancy double-counted** — a general vacancy % on top of modeled downtime | Habit carried from Detailed; a converted deal | The field does not exist on any Lease-Level contract (15.2); **G-M14** |
| **FM-12b** | **Fractional physical occupancy** from probability weighting | Would follow from cash-flow-branch blending | Prevented by the expected-successor convention (8.3); area invariant (18.4) |
| **FM-13** | **Downtime and free rent double-counted** — one period counted as both | Adjacent, both reduce rent to zero | **G-5** disjointness; **D2-G4** pins the boundary |
| **FM-14** | **Recoveries continue during downtime** | The recovery formula is per-lease; the occupancy gate is easy to forget | D3 test: recoveries exactly `0.0` in every downtime period (16.3) |
| **FM-14b** | **Operating expenses stop during vacancy** | The symmetric error, and intuitively appealing | D4 test: `total_operating_expenses` unchanged when a suite goes vacant, except for the fee's EGI dependence (9.2) |
| **FM-15** | **TI reduces NOI** | One misplaced line in the expense build | **G-3** perturbation: doubling TI leaves NOI, DSCR, debt yield bit-identical |
| **FM-16** | **LC reduces NOI** | Same | **G-3** |
| **FM-16b** | **Free rent netted into contractual base rent** | Reporting one net line instead of two | **D2-G4** asserts the gross line unchanged and the abatement on its own line (10.2) |
| **FM-17** | **LC basis truncated at sale**, or computed net of free rent, or excluding escalations | All three sound defensible; only one matches the convention | **D2-G2** (term extends past the window; basis uses all of it); **D2-G4** (LC bit-identical with and without free rent) |
| **FM-18** | **Successor rent begins before downtime ends** — market rent taken at the expiration period | The two periods are adjacent | **D2-G3**: the expiration-period market rent must appear nowhere |
| **FM-19** | **A weighted successor presented as a known tenant** | It looks like a lease row | `tenant_name is None`; `WEIGHTED_ROLLOVER_APPLIED` warning; component assumptions preserved on `RolloverEvent` (8.4) |
| **FM-20** | **A second rollover ignored** — a successor that expires in-window never rolls | Easy to generate one successor and stop | **D2-G5b**: exactly two `RolloverEvent`s |
| **FM-21** | **Exit NOI uses the wrong twelve-month window** — Year `H`, or `12 ×` one month | Three plausible readings of "exit NOI" | **D2-G5b**: `exit_noi` hand-summed over periods 61–72, and explicitly not equal to `noi_by_year[-1]` or to `12 × noi[61]` |
| **FM-22** | **The displayed monthly exit period differs from the valuation period** | A separate exit calculation drifting from the displayed schedule | **G-M12**: `exit_noi` asserted equal to the slice of the same canonical monthly projection served to the UI |
| **FM-23** | **Monthly debt service fabricated as annual / 12** | The obvious shortcut for a monthly cash-flow view | **G-M11**: no such division exists; any monthly debt view must come from `engine/debt.py`'s existing monthly chronology with zero economic change (D4/D5) |
| **FM-24** | **A Modified Gross base year silently invented** | A Hold-Year-1 fallback is convenient and wrong | `MISSING_MODIFIED_GROSS_RECOVERY_BASIS` ERROR (16.2) |
| **FM-25** | **The monthly schedule discarded after annual aggregation** | Treating monthly as scratch work | **G-M1**: the monthly projection is retained on the result envelope and is the source of every annual figure; a test asserts it is non-empty and reconciles |
| **FM-26** | **Non-deterministic ordering** — iterating a `set`/`dict` of leases and summing in varying order | Python iteration order for some key types | All lease collections are `tuple`, ordered at construction; summation is ascending-period. A 100-run bit-identity test |
| **FM-27** | **Quick or Detailed silently changed** | Touching a shared function or extracting a shared helper | **G-2**: both golden cases bit-identical after every Sprint D gate |
| **FM-28** | **Monthly data leaking downstream** — a monthly tuple reaching the annual IRR solver | The envelope carries both resolutions | **G-6**: the IRR solver receives exactly `H+1` values; no module outside `anchor.leasing` reads a canonical monthly series |
| **FM-29** | **Area over-allocation** — leases summing to more than `property_area_sf` | A rent-roll transcription error | `LEASED_AREA_EXCEEDS_PROPERTY_AREA` ERROR; per-month area invariant (18.4) |

---

## 27. Golden Cases

### 27.1 Shared conventions

Unless a case overrides them:

```
analysis_start_date  = 2026-01-01     (Month 1 = Jan 2026)
hold_period H        = 5              (projection window = periods 1..72)
property_area_sf     = 10,000
purchase_price       = 10,000,000
exit_cap_rate        = 0.065
ltv = 0.0, interest_rate = 0.0, amortization = 30, io_period = 0
acquisition_cost_pct = financing_fee_pct = disposition_cost_pct = 0.0
annual_capex_reserve = 0.0
```

Zero leverage and zero transaction costs are deliberate: they isolate the lease
engine so any drift is unambiguously lease-level. Leverage is exercised by the
existing V2 golden case, which remains untouched.

For cases that reach NOI (D2 and later): all six expense lines `0.0`,
`management_fee_pct = 0.0`, `other_income = 0.0`, `credit_loss_pct = 0.0`,
`recoverable_expense_ratio = 0.0`, so `NOI = EGI = base rent − free rent` and
every figure is hand-checkable. Expense integration is proven separately by a D4
case reusing Detailed's already-verified expense numbers.

Every assertion uses `pytest.approx(expected, rel=0.0, abs=1e-9)`.

**Every D1 case asserts both the exact monthly series and the exact annual
aggregation, and asserts that the annual figure equals the chronological sum of
its twelve months.**

**Two expected values in Section 27 carry ordinary IEEE-754 last-bit
artifacts**, verified against the stated formulas: D2-G2's LC evaluates to
`48599.99999999999` (`0.03 * 60 * 27000.0`) and D2-G5b's per-rollover LC to
`9000.000000000002` (`0.05 * 6 * 30000.0`). Both are within `1e-9` of the exact
decimal figures written below, which is precisely what the stated tolerance
exists to absorb. Tests must compute the expected value from the same operand
order the engine uses rather than typing the decimal literal — the same
discipline the existing golden-case suite already follows.

Period-index reference for `s = 2026-01-01`:

```
month_index(2026-01-01) =  1     month_index(2027-04-01) = 16
month_index(2026-12-31) = 12     month_index(2028-06-30) = 30
month_index(2027-01-01) = 13     month_index(2030-10-31) = 58
month_index(2024-01-01) = -23    month_index(2030-12-31) = 60
```

---

### D1-G1 — Flat in-place lease, full hold

**Inputs.** Suite `S1` 10,000 SF. Lease `L1` on `S1`, 10,000 SF,
`rent_commencement 2024-01-01`, `expiration 2033-12-31`, `base_rent_psf 30.00`,
`escalation_basis NONE`.

**Expected.**

```
raw first_rent_period = -23 ; raw last_rent_period = 96 (truncated at 72)
monthly = 30.00 * 10,000 / 12 = 25,000.000000   for every period 1..72

base_rent_by_year          = (300,000.00, 300,000.00, 300,000.00, 300,000.00, 300,000.00)
forward-window base rent   = 300,000.00        (periods 61-72)
occupied_area[m]           = 10,000    every period
vacant_area[m]             = 0         every period
physical_occupancy[m]      = 1.0       every period
average_physical_occupancy_over_year = (1.0, 1.0, 1.0, 1.0, 1.0)
physical_occupancy_at_year_end       = (1.0, 1.0, 1.0, 1.0, 1.0)
tenant_improvements = leasing_commissions = 0.0 everywhere
going_in_cap_rate (D4) = 300,000 / 10,000,000 = 0.03
```

**Asserts.** Every period exactly `25,000.000000`; annual = sum of its twelve
months; zero TI and zero LC (**FM-11b**); truncation past period 72 raises no
error; area invariant in all 72 periods.

---

### D1-G2 — Annual contractual escalation from acquisition

As D1-G1 but `rent_commencement 2026-01-01`, `escalation_pct 0.03`,
`escalation_basis LEASE_ANNIVERSARY`.

```
first_rent_period = 1 ;  k = floor((m - 1) / 12)

Year  periods   k   PSF               monthly            annual
  1    1-12     0   30.000000         25,000.000000      300,000.000000
  2   13-24     1   30.900000         25,750.000000      309,000.000000
  3   25-36     2   31.827000         26,522.500000      318,270.000000
  4   37-48     3   32.781810         27,318.175000      327,818.100000
  5   49-60     4   33.765264300      28,137.720250      337,652.643000
 fwd  61-72     5   34.778222229      28,981.851858      347,782.222290
```

**Asserts.** Each year's twelve periods are identical to one another and differ
from the adjacent year; annual = sum of twelve months for all five years.

---

### D1-G3 — In-place lease whose escalation chronology began before acquisition

As D1-G2 but `rent_commencement 2024-01-01` (two years pre-acquisition).

```
raw first_rent_period = -23 ;  k(m) = floor((m + 23) / 12)
k(1) = 2      k(12) = 2      k(13) = 3

Year  periods   k   PSF                monthly              annual
  1    1-12     2   31.827000          26,522.500000        318,270.000000
  2   13-24     3   32.781810          27,318.175000        327,818.100000
  3   25-36     4   33.765264300       28,137.720250        337,652.643000
  4   37-48     5   34.778222229       28,981.851858        347,782.222290
  5   49-60     6   35.821568896       29,851.307413        358,215.688959
 fwd  61-72     7   36.896215963       30,746.846636        368,962.159627
```

**Asserts (this is the FM-5 guard).**

- Period 1 rent is `26,522.500000`, **not** `25,000.000000` — acquisition does
  not reset the escalation clock.
- **D1-G3's Year 1 equals D1-G2's Year 3 exactly** (`318,270.000000`), and
  D1-G3's Year `n` equals D1-G2's Year `n+2` for `n = 1, 2, 3` — proving the
  offset is exactly two contractual steps.
- The step occurs between period 12 and period 13 (the lease's January
  anniversary), not at any other period.

---

### D1-G4 — Lease commencing during the horizon

Suite `S1` 10,000 SF. Lease `L1`, `rent_commencement 2027-04-01` (period 16),
`expiration 2032-03-31` (period 75, truncated), `base_rent_psf 30.00`, no
escalation.

```
base rent = 0.0            periods 1-15
base rent = 25,000.000000  periods 16-72

Year 1 (periods  1-12) = 0.00                          (0 paying periods)
Year 2 (periods 13-24) = 9 * 25,000 = 225,000.000000   (periods 16-24)
Year 3 (periods 25-36) = 300,000.000000
Year 4                 = 300,000.000000
Year 5                 = 300,000.000000
forward window         = 300,000.000000

occupancy = 0.0 periods 1-15 ; 1.0 periods 16-72
physical_occupancy_at_year_end       = (0.0, 1.0, 1.0, 1.0, 1.0)
average_physical_occupancy_over_year = (0.0, 9/12, 1.0, 1.0, 1.0)
```

**Asserts.** The Year-2 boundary split is exact; occupancy is a state metric
with both an at-year-end and an average form, and neither is a sum (**FM-8**);
period 16 is April 2027 on its `ModelMonth`.

---

### D1-G5 — Lease expiration mid-hold

As D1-G1 but `rent_commencement 2026-01-01`, `expiration 2028-06-30`
(period 30), no escalation, no rollover (D1).

```
base rent = 25,000.000000  periods 1-30
base rent = 0.0            periods 31-72

Year 1 = 300,000.000000
Year 2 = 300,000.000000
Year 3 = 6 * 25,000 = 150,000.000000     (periods 25-30)
Year 4 = 0.00
Year 5 = 0.00
forward window = 0.00

occupancy: 1.0 periods 1-30 ; 0.0 periods 31-72
vacant_area = 10,000 in periods 31-72
```

**Asserts (FM-10).** Period 30 pays in full; period 31 is exactly `0.0`; Year 3
is exactly half a year; the area invariant holds in every period including the
vacant ones.

---

### D1-G6 — Two tenants, different rent and expiration patterns

| Suite | Area | Lease | PSF | Escalation | Commencement | Expiration | Last period |
|---|---|---|---|---|---|---|---|
| `S1` | 6,000 | `L1` | `30.00` | `0.03` anniversary | 2026-01-01 | 2030-12-31 | 60 |
| `S2` | 4,000 | `L2` | `25.00` | `NONE` | 2026-01-01 | 2027-12-31 | 24 |

```
L1 monthly = 30.00 * 1.03^k * 6,000 / 12 = 15,000.000000 * 1.03^k
  k=0 15,000.000000   k=1 15,450.000000   k=2 15,913.500000
  k=3 16,390.905000   k=4 16,882.632150   periods 61-72: expired, 0.0
L2 monthly = 25.00 * 4,000 / 12 = 8,333.333333...   periods 1-24, else 0.0

Year 1 = 12 * (15,000.000000 + 8,333.333333...) = 280,000.000000
Year 2 = 12 * (15,450.000000 + 8,333.333333...) = 285,400.000000
Year 3 = 12 *  15,913.500000                    = 190,962.000000
Year 4 = 12 *  16,390.905000                    = 196,690.860000
Year 5 = 12 *  16,882.632150                    = 202,591.585800
forward window = 0.00

occupancy: 1.0 periods 1-24 ; 0.6 periods 25-60 ; 0.0 periods 61-72
```

`8,333.333333...` is computed as `25.00 * 4000 / 12` in full double precision,
never typed as a truncated literal.

**Asserts.** The two leases escalate independently; property occupancy steps
`1.0 → 0.6 → 0.0` at exactly periods 25 and 61; the area invariant holds
throughout; annual = sum of twelve months for every year.

---

### D1-G7 — Vacant suite

Suites `S1` 7,000 SF (leased) and `S2` 3,000 SF (**no lease at all**). `L1` on
`S1`: `30.00` PSF, flat, periods 1–72.

```
monthly = 30.00 * 7,000 / 12 = 17,500.000000    every period
annual  = 210,000.000000                        every year
occupied_area = 7,000 ; vacant_area = 3,000 ; physical_occupancy = 0.7
```

**Asserts.** A suite with zero leases is legal in D1; it contributes exactly
`0.0` revenue and 3,000 SF of vacancy in every period; **no synthetic vacant
lease appears in `lease_schedules`**; the area invariant holds.

---

### D1-G8 — Month 12 → Month 13 aggregation boundary

A deliberately extreme unit case: `escalation_pct = 1.00` (100%) so any
off-by-one in the year slice produces a 2× error. Economically absurd by design;
labeled as an aggregation-boundary unit case, not an underwriting example.

Suite `S1` 10,000 SF; `L1` `base_rent_psf 30.00`, `escalation_pct 1.00`,
`LEASE_ANNIVERSARY`, `rent_commencement 2026-01-01`, `expiration 2035-12-31`.

```
Year  periods   k   PSF        monthly              annual
  1    1-12     0   30.00      25,000.000000        300,000.000000
  2   13-24     1   60.00      50,000.000000        600,000.000000
  3   25-36     2  120.00     100,000.000000      1,200,000.000000
  4   37-48     3  240.00     200,000.000000      2,400,000.000000
  5   49-60     4  480.00     400,000.000000      4,800,000.000000
 fwd  61-72     5  960.00     800,000.000000      9,600,000.000000
```

**Asserts (FM-2, FM-3, FM-4).**

- `monthly[12] == 25,000.000000` and `monthly[13] == 50,000.000000`.
- `ModelMonth` for period 12: `period_index == 12`, `month_start == 2026-12-01`,
  `hold_year == 1`, `is_forward_exit_month is False`.
- `ModelMonth` for period 13: `period_index == 13`, `month_start == 2027-01-01`,
  `hold_year == 2`.
- Year 1 contains period 12 and **not** period 13; Year 2 contains period 13 and
  **not** period 12.
- Each year's annual figure equals the chronological sum of exactly twelve
  periods, and the union of the five year-slices is exactly periods 1–60 with no
  gap and no overlap.
- `ModelMonth` for period 61: `hold_year == 6`, `is_forward_exit_month is True`.

---

### D1-G9 — Supported date-boundary validation (passes cleanly)

One suite per lease, all valid, exercising every month-length case:

| Lease | Commencement | Expiration | Note |
|---|---|---|---|
| `A` | 2026-01-01 | 2026-12-31 | 31-day month end |
| `B` | 2026-02-01 | 2026-04-30 | 30-day month end |
| `C` | 2027-01-01 | 2027-02-28 | non-leap February |
| `D` | 2028-01-01 | 2028-02-29 | **leap** February |

**Asserts.** All four validate with zero errors; period indices are
`(1,12) (2,4) (13,14) (25,26)` respectively; every `ModelMonth.month_start`
matches its calendar month; leap and non-leap February both resolve correctly.

---

### D1-G10 — Unsupported non-month-aligned dates → ERROR

Each sub-case is validated independently and must produce exactly one error.

| Sub-case | Input | Expected code |
|---|---|---|
| `a` | `rent_commencement 2026-01-15` | `LEASE_DATE_NOT_MONTH_ALIGNED` |
| `b` | `lease_expiration 2028-06-15` | `LEASE_DATE_NOT_MONTH_ALIGNED` |
| `c` | `lease_expiration 2028-02-28` (2028 is a **leap** year, so Feb has 29 days) | `LEASE_DATE_NOT_MONTH_ALIGNED` |
| `d` | `analysis_start_date 2026-01-15` | `ANALYSIS_START_NOT_MONTH_ALIGNED` |
| `e` | `rent_commencement 2040-01-15` — non-aligned **and entirely outside** the projection window | `LEASE_DATE_NOT_MONTH_ALIGNED` |
| `f` | `lease_start_date 2025-11-17` (informational), all economic dates aligned | **no error** |

**Asserts (FM-11, G-M15).** No sub-case produces a rent schedule; no sub-case is
a warning; sub-case `c` proves the last-day check is calendar-aware; sub-case
`e` proves the rule is hold-period-independent (5.5); sub-case `f` proves
`lease_start_date` is genuinely informational and not alignment-validated.

---

### D2-G1 — Market rent annual step growth

`market_rent_psf = 40.00`, `market_rent_growth = 0.03`,
`analysis_start_date = 2026-01-01`. A lease commencing **2026-07-01** (period 7)
is present in the same case purely to prove it does not move the market clock.

```
periods  1-12   40.000000
periods 13-24   41.200000
periods 25-36   42.436000
periods 37-48   43.709080
periods 49-60   45.020352400
periods 61-72   46.370962972
```

**Asserts (FM-6).** `market_rent_psf[12] == 40.000000` and
`market_rent_psf[13] == 41.200000`; the value does **not** change at period 19
(the lease's anniversary); no fractional exponent appears anywhere — the value
is constant within each 12-period band.

---

### D2-G2 — Renewal path, `p = 1.0`

Suite `S1` 10,000 SF. `L1`: `30.00` PSF, flat, periods 1–24
(`expiration 2027-12-31`).

Market leasing: `market_rent_psf 36.00`, `market_rent_growth 0.00`,
`renewal_probability 1.0`, `renewal_rent_spread -0.10`, `renewal_term_months 60`,
`renewal_downtime_months 0.0`, `renewal_free_rent_months 0.0`,
`renewal_ti_psf 5.00`, `renewal_lc_pct 0.03`, `successor_escalation_pct 0.0`.
Every new-tenant assumption is set to a distinct, conspicuous value to prove it
is unused.

```
e = 24 ; D = 1.0*0.0 + 0.0*(new) = 0.0 ; floor(D) = 0
c = 24 + 1 + 0 = 25 ; boundary factor at c = 1.0
expected_rent_psf = 1.0 * (36.00 * (1 - 0.10)) + 0.0 * 36.00 = 32.400000
successor monthly = 32.400000 * 10,000 / 12 = 27,000.000000
last_rent_period(L') = 25 + 60 - 1 = 84   -> truncated at 72

base rent = 25,000.000000  periods 1-24
base rent = 27,000.000000  periods 25-72

Year 1 = 300,000.000000   Year 2 = 300,000.000000   Year 3 = 324,000.000000
Year 4 = 324,000.000000   Year 5 = 324,000.000000   forward = 324,000.000000

TI = 5.00 * 10,000 = 50,000.000000            entirely in period 25 -> Year 3
LC basis = 60 * 27,000.000000 = 1,620,000.000000    (FULL contractual term)
LC = 0.03 * 1,620,000.000000 = 48,600.000000  entirely in period 25 -> Year 3

tenant_improvements_by_year = (0, 0, 50,000.000000, 0, 0)
leasing_commissions_by_year = (0, 0, 48,600.000000, 0, 0)
occupancy = 1.0 in every period
```

**Asserts.** No downtime period exists; the LC basis uses all 60 contractual
periods although 12 fall past the window (**FM-17**); TI and LC land in Year 3
and leave every NOI figure untouched (**FM-15**, **FM-16**); no new-tenant
assumption influences any number; the `RolloverEvent` still records every
new-tenant component assumption (8.4).

---

### D2-G3 — Vacate path with downtime, `p = 0.0`

As D2-G2 except `renewal_probability = 0.0`, `new_downtime_months = 6.0`,
`new_term_months = 60`, `new_ti_psf = 20.00`, `new_lc_pct = 0.06`,
`new_free_rent_months = 0.0`, `market_rent_growth = 0.03`.

```
e = 24 ; D = 6.0 ; floor(D) = 6 ; c = 24 + 1 + 6 = 31 ; factor at c = 1.0
MarketRentPSF(31) = 36.00 * 1.03^floor(30/12) = 36.00 * 1.03^2 = 38.192400
successor monthly = 38.192400 * 10,000 / 12 = 31,827.000000
last_rent_period(L') = 31 + 60 - 1 = 90 -> truncated at 72

base rent = 25,000.000000  periods 1-24
base rent = 0.0            periods 25-30   (six fully vacant periods)
base rent = 31,827.000000  periods 31-72

Year 1 = 300,000.000000
Year 2 = 300,000.000000
Year 3 = 6*0 + 6*31,827.000000 = 190,962.000000
Year 4 = 381,924.000000
Year 5 = 381,924.000000
forward window = 381,924.000000

TI = 20.00 * 10,000 = 200,000.000000                   period 31 -> Year 3
LC basis = 60 * 31,827.000000 = 1,909,620.000000
LC = 0.06 * 1,909,620.000000 = 114,577.200000          period 31 -> Year 3

occupancy = 1.0 (1-24), 0.0 (25-30), 1.0 (31-72)
vacant_area = 10,000 in periods 25-30
```

**Asserts (FM-18).** Market rent is taken at period 31, not period 24 — the
period-24 value `36.00 * 1.03 = 37.080000` must appear nowhere; exactly six
zero-rent periods; occupancy returns to `1.0` at period 31; TI and LC land at
commencement, not at expiration.

---

### D2-G3b — Fractional downtime

As D2-G3 but `new_downtime_months = 5.5`.

```
e = 24 ; D = 5.5 ; floor(D) = 5 ; c = 24 + 1 + 5 = 30
boundary factor at c = 1 - (5.5 - 5) = 0.5

periods 25-29 : fully vacant (5 periods)
period  30    : 0.5 * 31,827.000000 = 15,913.500000
periods 31-72 : 31,827.000000

MarketRentPSF(30) = 36.00 * 1.03^floor(29/12) = 36.00 * 1.03^2 = 38.192400
last_rent_period(L') = 30 + 60 - 1 = 89 -> truncated at 72

Year 3 = 5*0 + 15,913.500000 + 6*31,827.000000 = 206,875.500000
Year 4 = Year 5 = forward = 381,924.000000

TI = 200,000.000000 in period 30       (NOT prorated by the boundary factor)
LC = 0.06 * 60 * 31,827.000000 = 114,577.200000 in period 30
```

**Asserts.** Rent forgone versus a no-downtime baseline over periods 25–36 is
exactly `12*31,827.000000 - 206,875.500000 = 175,048.500000 = 5.5 *
31,827.000000` — the *total forgone = D months* invariant (9.3). Occupancy in
period 30 is `0.5`. TI and LC are undiminished by the boundary factor.

---

### D2-G4 — TI + LC + free rent

As D2-G3 (`p = 0.0`, `D = 6.0`, `c = 31`, monthly `31,827.000000`) plus
`new_free_rent_months = 3.0`.

```
free-rent periods = 31, 32, 33
contractual_base_rent[31..33] = 31,827.000000 each   (GROSS, unreduced)
free_rent[31..33]             = 31,827.000000 each
net rent periods 31-33        = 0.0
net rent periods 34-72        = 31,827.000000

free_rent_by_year = (0, 0, 95,481.000000, 0, 0)
Year 3 gross = 190,962.000000 ; Year 3 net = 95,481.000000

LC basis is GROSS of free rent: 60 * 31,827.000000 = 1,909,620.000000
LC = 114,577.200000     -- BIT-IDENTICAL to D2-G3
TI = 200,000.000000
```

**Asserts (FM-13, FM-16b, FM-17).** The gross line and the abatement line are
reported separately and never netted; LC is bit-identical to D2-G3, proving the
basis is gross of free rent; the downtime periods (25–30) and free-rent periods
(31–33) are **disjoint**; TI and LC are unchanged while NOI changes.

---

### D2-G5 — Rollover near exit, and a second rollover

Suite `S1` 10,000 SF. `L1`: `30.00` PSF, flat, `rent_commencement 2026-01-01`,
`expiration 2030-10-31` (period 58). Market leasing: `market_rent_psf 36.00`,
`market_rent_growth 0.00`, `renewal_probability 0.0`,
`new_downtime_months 3.0`, `new_ti_psf 10.00`, `new_lc_pct 0.05`,
`new_free_rent_months 0.0`, `successor_escalation_pct 0.0`.

**D2-G5a — `new_term_months = 12`.**

```
Rollover 1: e = 58 ; c = 58 + 1 + 3 = 62 ; L2 periods 62..73 -> truncated at 72
L2 expires at period 73, which is outside the window -> NO second rollover
```

**D2-G5b — `new_term_months = 6` (forces the second rollover).**

```
Rollover 1: e = 58 ; c = 62 ; L2 periods 62..67 ; monthly 30,000.000000
            TI = 100,000.000000 (period 62) ; LC = 0.05*6*30,000 = 9,000.000000
Rollover 2: e = 67 ; c = 67 + 1 + 3 = 71 ; L3 periods 71..76 -> truncated at 72
            TI = 100,000.000000 (period 71) ; LC = 9,000.000000
Rollover 3: L3 expires at period 76, outside the window -> none

base rent = 25,000.000000  periods  1-58
base rent = 0.0            periods 59-61
base rent = 30,000.000000  periods 62-67
base rent = 0.0            periods 68-70
base rent = 30,000.000000  periods 71-72

Year 1 = Year 2 = Year 3 = Year 4 = 300,000.000000
Year 5 (periods 49-60) = 10 * 25,000.000000 = 250,000.000000
exit_noi (periods 61-72)
        = 0 + 6*30,000.000000 + 0 + 2*30,000.000000 = 240,000.000000

exit_window_leasing_costs = 100,000 + 9,000 + 100,000 + 9,000 = 218,000.000000
```

**Asserts (FM-20, FM-21, FM-22).**

- Exactly **two** `RolloverEvent`s — a successor lease itself rolls over.
- `exit_noi == 240,000.000000`, and explicitly **not** `noi_by_year[-1]`
  (`250,000.000000`) and **not** `12 * noi[61]` (`0.0`).
- `exit_noi` equals the sum of the canonical monthly `noi` slice for periods
  61–72 read off the same projection served to the UI.
- `exit_window_leasing_costs == 218,000.000000` and is **not** deducted from
  `exit_noi`, `exit_value`, or any cash flow.
- A `ROLLOVER_IN_EXIT_WINDOW` warning is raised for both rollovers.

---

### 27.2 Coverage matrix

| Case | Phase | Guards |
|---|---|---|
| D1-G1 flat in-place lease | D1 | FM-11b |
| D1-G2 escalation from acquisition | D1 | — |
| D1-G3 pre-acquisition escalation chronology | D1 | **FM-5** |
| D1-G4 commencement in horizon | D1 | FM-8 |
| D1-G5 expiration mid-hold | D1 | **FM-10** |
| D1-G6 two tenants | D1 | FM-26, area invariant |
| D1-G7 vacant suite | D1 | FM-12, area invariant |
| D1-G8 Month 12 → 13 boundary | D1 | **FM-2, FM-3, FM-4** |
| D1-G9 supported date boundaries | D1 | FM-4 |
| D1-G10 non-aligned dates → ERROR | D1 | **FM-11**, G-M15 |
| D2-G1 market rent step | D2 | **FM-6** |
| D2-G2 renewal `p=1` | D2 | FM-15, FM-16, FM-17, FM-11b |
| D2-G3 / G3b vacate + downtime | D2 | **FM-18** |
| D2-G4 TI + LC + free rent | D2 | **FM-13, FM-16b, FM-17** |
| D2-G5a / G5b rollover near exit | D2 | **FM-20, FM-21, FM-22** |

Every D1 case additionally asserts `annual[y] == sum(monthly[12(y-1)+1..12y])`
(**FM-1**, **G-M4**).

---

## 28. D1 Detailed Build Plan

### 28.1 Objective and locked scope

> **D1 objective.** Existing contractual leases produce correct deterministic
> **canonical monthly** rent schedules and **exact annual aggregations** derived
> from them.

**D1 includes:**

- `LeaseLevelPropertyInputs`, `Suite`, `Lease` and their enums
- leasing-scoped validation (ERROR / WARNING), inside `anchor.leasing` only
- deterministic month identity: `ModelMonth`, `month_index`, alignment predicates
- existing in-place leases, including those commenced before acquisition
- future known leases within contractual scope
- base rent on the `$/SF/year` convention
- contractual escalation on true contractual chronology
- lease commencement and expiration
- occupied / vacant suite state and physical occupancy
- multiple suites, multiple leases
- the canonical monthly property rent-roll schedule
- annual rent aggregation **derived from** the monthly schedule
- D1 golden cases (both monthly and annual assertions)
- architecture guardrails

**D1 explicitly excludes:** renewal; weighted/expected rollover; replacement
tenants; market leasing; market-rent-driven successor leases; downtime; free
rent; TI; LC; expense recoveries; operating expenses; other income; NOI;
`OperatingProjectionLike` conformance; acquisition integration;
`AcquisitionResults` changes; debt changes; return changes; sensitivity;
persistence; database migrations; API; frontend; ingestion; AI; snapshot schema
changes; **any change to `src/anchor/validation.py`**.

**D1 deliverable:** a trusted `PropertyRentRollSchedule` (4.7).

### 28.2 Why D1 is cleanly isolated from D2

D1's rent formula (6.1) contains no rollover, market-rent, downtime, free-rent,
TI, LC or recovery term. D2 does not revise any D1 formula — it *adds successor
leases* to the same engine and calls D1's `build_lease_monthly_schedule`
unchanged for each one, then adds new series alongside. The isolation is
structural, not a matter of discipline.

### 28.3 The D1-wide acceptance criterion

**D1 modifies no existing file.** Every D1 commit's `git diff` shows only new
files under `src/anchor/leasing/` and `tests/`. Verified at every gate:

```
git diff --name-only fffdf34..HEAD  ->  only new paths under
                                        src/anchor/leasing/ and tests/
```

and the 1773 pre-existing backend tests and 711 frontend tests pass
**unmodified**.

---

### Gate D1.0 — Contracts and leasing-scoped validation

**Objective.** The Lease-Level input contracts exist and are validated
deterministically, with ERROR / WARNING severity scoped entirely to
`anchor.leasing`.

**Files.** New only: `src/anchor/leasing/__init__.py`,
`src/anchor/leasing/contracts.py`, `src/anchor/leasing/validation.py`.
**`src/anchor/validation.py` is not touched.**

**Contracts introduced.** `LeaseLevelPropertyInputs`, `Suite`, `Lease`,
`EscalationBasis`, `LeaseType`, `LeaseOrigin`, `LeaseIssueSeverity`,
`LeaseValidationIssue`, `LeaseValidationResult`, `LeaseValidationError`.

**Tests.** `tests/test_leasing_d1_0_contracts.py`,
`tests/test_leasing_d1_0_validation.py`, `tests/test_leasing_architecture.py`.

- Every ERROR rule in 19.2 that applies at D1 fires with the correct code and
  path for a minimal input.
- Every WARNING rule in 19.3 that applies at D1 fires and does **not** block.
- **D1-G10** (all six sub-cases) passes, including the leap-February trap and
  the out-of-window case.
- Issue ordering is deterministic across 100 runs.
- A valid multi-suite, multi-lease input constructs cleanly.
- **G-1**: AST-parsed import boundary on `anchor.leasing` (28.7).
- A test asserting `src/anchor/validation.py` contains no `severity` identifier —
  the mechanical proof that D1 did not start a global refactor.

**Stop conditions.** Stop if any D1 validation rule cannot be expressed without
touching `src/anchor/validation.py`.

**Acceptance.** 1773 + 711 pre-existing tests pass unmodified; `git diff` shows
new files only.

**Commit.** `feat(leasing): D1 Gate 0 -- lease-level contracts and scoped validation`

---

### Gate D1.1 — Month identity and calendar

**Objective.** Deterministic, total, hand-checkable month identity, preserving
both sequential and calendar identity.

**Files.** New: `src/anchor/leasing/calendar.py`. `ModelMonth` added to
`contracts.py`.

**Functions.**

```python
def month_index(target: date, *, analysis_start: date) -> int
def month_start_for_index(index: int, *, analysis_start: date) -> date
def last_day_of_month(d: date) -> date
def is_first_day_of_month(d: date) -> bool
def is_last_day_of_month(d: date) -> bool
def projection_month_count(hold_period: int) -> int          # 12 * H + 12
def build_model_months(*, analysis_start: date, hold_period: int) -> tuple[ModelMonth, ...]
```

`month_index` is pure integer arithmetic (5.2). No `timedelta`, no day counts,
leap-year- and timezone-independent by construction.

**Tests.** `tests/test_leasing_d1_1_calendar.py`.

- `month_index(analysis_start) == 1`.
- Round-trip `month_index(month_start_for_index(k)) == k` for `k` in `-120..240`.
- Dates before the analysis start yield indices `<= 0`, never an exception.
- `is_last_day_of_month` correct for Feb 28/29 in leap and non-leap years and
  for 30- and 31-day months.
- `month_index` is monotone non-decreasing in its argument.
- **D1-G9** period indices `(1,12) (2,4) (13,14) (25,26)`.
- `build_model_months` invariants: length `12H+12`; `period_index == i+1`;
  `hold_year == ((i)//12)+1`; `is_forward_exit_month == (period_index > 12H)`;
  `month_start` matches the real calendar month (**G-M9**).
- The worked example of 5.3 for `s = 2027-01-01, H = 5`.

**Stop conditions.** Stop if any function requires a `timedelta` or a day count —
that would mean the whole-month convention has leaked.

**Commit.** `feat(leasing): D1 Gate 1 -- canonical month identity`

---

### Gate D1.2 — Contractual base-rent monthly timeline

**Objective.** One lease produces its exact canonical monthly base-rent series.

**Files.** New: `src/anchor/leasing/rent.py`. `LeaseMonthlySchedule` added to
`contracts.py`.

**Functions.**

```python
def lease_rent_periods(lease, *, analysis_start) -> tuple[int, int]      # raw, unclamped
def escalation_period_index(*, period: int, raw_first_rent_period: int,
                            basis: EscalationBasis) -> int
def monthly_base_rent(*, base_rent_psf: float, leased_area_sf: float,
                      escalation_pct: float, period_index: int) -> float
def build_lease_monthly_schedule(lease, *, analysis_start, months) -> LeaseMonthlySchedule
```

`monthly_base_rent` divides by 12 **once, last** (6.1) and wraps its result in
`ensure_finite`. `escalation_period_index` takes the **raw** first rent period
(6.2) — the signature makes the FM-5 trap hard to fall into.

**Tests.** `tests/test_leasing_d1_2_rent.py`, `tests/test_leasing_golden_d1.py`.

- **D1-G1, D1-G2, D1-G3, D1-G4, D1-G5** — every period asserted at `abs=1e-9`.
- **D1-G3** additionally asserts its Year `n` equals D1-G2's Year `n+2`.
- A lease entirely outside the window yields an all-zero series and
  `first_rent_period is None`.
- `escalation_pct = 0.0` and `escalation_basis = NONE` produce identical series.
- A non-finite intermediate raises `NonFiniteResultError`, never a silent `inf`.

**Stop conditions.** Stop if any golden case cannot be hand-verified from the
formula in 6.1 alone.

**Commit.** `feat(leasing): D1 Gate 2 -- contractual base-rent monthly timeline`

---

### Gate D1.3 — Property monthly schedule and annual derivation

**Objective.** Many leases across many suites aggregate into one canonical
monthly property schedule, with annual figures derived from it and an exact area
reconciliation.

**Files.** New: `src/anchor/leasing/aggregation.py`.
`PropertyRentRollSchedule` added to `contracts.py`.

**Functions.**

```python
def build_property_rent_roll_schedule(
    property_inputs, suites, leases, *, hold_period
) -> PropertyRentRollSchedule

def aggregate_flow_to_annual(monthly: tuple[float, ...], *, hold_period) -> tuple[float, ...]
def snapshot_state_at_year_end(monthly: tuple[float, ...], *, hold_period) -> tuple[float, ...]
def average_state_over_year(monthly: tuple[float, ...], *, hold_period) -> tuple[float, ...]
```

Three separate aggregation functions, named for what they do, so a flow metric
cannot be accidentally averaged and a state metric cannot be accidentally summed
(**FM-7**, **FM-8**). Summation is ascending by period; within a period, leases
are summed in declared tuple order — never `set`- or `dict`-ordered
(**FM-26**).

**Tests.** `tests/test_leasing_d1_3_aggregation.py`, extending
`tests/test_leasing_golden_d1.py`.

- **D1-G6, D1-G7, D1-G8** in full.
- **G-M4**: for every case and every year, `annual[y] == sum(monthly slice)` at
  `abs=1e-9`.
- Year-slice partition test: the union of the `H` year slices is exactly periods
  `1..12H`, with no gap and no overlap (**FM-2**, **FM-3**).
- Area invariant `occupied + vacant == property_area_sf` in every period of
  every case.
- State metrics are exposed only under `_at_year_end` / `average_..._over_year`
  names (**G-M6**).
- 100 repeated runs are bit-identical.
- Reversing the input lease tuple leaves every property total equal at
  `abs=1e-9` (order within a fixed input is what reproducibility requires; the
  tuple order rule fixes it).

**Stop conditions.** Stop if the area invariant cannot hold exactly for any
valid input, or if any annual figure would need an independent formula.

**Commit.** `feat(leasing): D1 Gate 3 -- canonical monthly property schedule and annual derivation`

---

### Gate D1.4 — Guardrails and D1 closeout

**Objective.** D1 is provably isolated, provably monthly-canonical, and provably
inert with respect to Quick and Detailed.

**Files.** New tests only: `tests/test_leasing_architecture.py` (extended),
`tests/test_leasing_d1_4_isolation.py`. No production file changes.

**Tests.**

- **G-1** (extended): AST-parse every file in `src/anchor/leasing/`; assert none
  imports `anchor.engine.acquisition`, `anchor.engine.debt`, `anchor.engine.noi`,
  `anchor.engine.returns`, `anchor.engine.operating_projection`, `anchor.ai`,
  `anchor.deals`, `anchor.ingestion`, `anchor.analysis`, `openai`, or `azure`.
- **G-2**: the Quick V2 golden case and the Detailed V2.1 golden case produce
  bit-identical results to their recorded values.
- **G-M1 / G-M3**: `anchor.leasing` contains no function producing an annual
  figure from anything other than a canonical monthly series — asserted by an
  AST test that every `_by_year`-producing function's only numeric input is a
  monthly tuple, plus the **G-M4** reconciliation.
- **G-M10**: subprocess check — importing `anchor.engine` in a fresh interpreter
  does not pull `anchor.leasing` into `sys.modules`.
- **G-M14** (partial): no Lease-Level contract declares a field named
  `vacancy_credit_loss_pct` or `occupancy`.
- **G-M15**: a non-aligned economic date never yields a rent schedule.
- The D1-wide diff assertion (28.3).

**Stop conditions.** Stop if `anchor.engine` must import `anchor.leasing` at D1 —
it must not; the two are connected only from D4.

**Acceptance.** 1773 backend + 711 frontend pre-existing tests pass unmodified;
all new D1 tests pass; `git diff` shows only new files; results reported exactly.

**Commit.** `test(leasing): D1 Gate 4 -- isolation guardrails and D1 closeout`

### 28.4 What a D1 implementer can answer unambiguously

| Question | Section |
|---|---|
| What contracts to build | 4.2–4.4, 4.7 |
| What a month is | 5.2, 5.3 |
| Which dates are accepted | 5.5 |
| How base rent is calculated | 6.1 |
| How rent escalates, and from when | 6.2 |
| When rent stops | 5.4, 6.4 |
| How multiple leases aggregate | 18.1, 18.4, D1.3 |
| What annual totals mean | 5.6, 5.7 |
| What validation occurs | 19.2, 19.3 |
| What is excluded | 28.1 |
| Which golden cases prove correctness | 27, D1-G1…D1-G10 |
| Which modules must remain untouched | 28.1, 28.3, G-1 |

---

## 29. D2 / D3 / D4 / D5 High-Level Plans

### D2 — Market leasing, rollover, downtime, free rent, TI, LC

All D2 economics are computed in the canonical monthly schedule; annual D2
figures derive from it.

| Gate | Content |
|---|---|
| D2.0 | `MarketLeasingAssumptions`, `LeasingCommissionMethod`, the precedence resolver (Section 24), `ResolvedMarketLeasing`, validation |
| D2.1 | Market rent timeline (7.2). **D2-G1** — annual step growth on analysis anniversaries, not lease anniversaries |
| D2.2 | `rollover.py`: expected successor (8.2), timing (8.5), the successor chain, horizon truncation, `RolloverEvent` with all component assumptions preserved. **D2-G2, D2-G3, D2-G3b** |
| D2.3 | Free rent (Section 10) and the fractional boundary rule (10.3). **G-5** disjointness |
| D2.4 | TI and LC (Sections 11, 12) as below-NOI monthly series **inside `anchor.leasing`**, not yet integrated downstream. **D2-G4**. **G-3** perturbation on the lease-level NOI series |
| D2.5 | **D2-G5a / G5b**, second-order rollover, exit-window warnings, D2 closeout |

**Key risks:** FM-6, FM-13, FM-17, FM-18, FM-19, FM-20 — each with a named
golden case. **D2 still modifies no file outside `anchor.leasing`.**

### D3 — Expense recoveries and lease structures

Recoveries are computed **monthly**, because occupancy changes monthly, downtime
can occur mid-year, successor lease structures may differ from their
predecessors, recoveries stop and restart, and new leases begin within a year.
Annual reimbursements derive from monthly results.

| Gate | Content |
|---|---|
| D3.0 | `RecoveryBasis` contract, `recoverable_expense_ratio`, validation including `MISSING_MODIFIED_GROSS_RECOVERY_BASIS` — **no Hold-Year-1 fallback anywhere** |
| D3.1 | `recoveries.py`: NNN, Gross, Modified Gross; pro-rata share; the vacancy/downtime gate; the fractional boundary factor |
| D3.2 | The fixed non-iterative per-month computation order (16.4), asserted explicitly |
| D3.3 | Recovery golden cases (one per structure), **FM-14** and **FM-14b** tests |

### D4 — Canonical monthly property projection and engine integration

| Gate | Content |
|---|---|
| D4.0 | `LeaseLevelOperatingInputs`; the expense-reuse decision (13.1) with its **G-2** proof obligation; other income |
| D4.1 | `MonthlyPropertyProjection` — the full canonical monthly EGI / expense / NOI build |
| D4.2 | `AnnualOperatingProjection` derived **solely** by `aggregate_monthly_to_annual`; `exit_noi` from periods `12H+1..12H+12` of the same monthly projection; `exit_window_leasing_costs`. **G-M4**, **G-M12**, **G-11** |
| D4.3 | **The one downstream change.** Resolve the below-NOI channel (Section 32, HD-1); `OperatingMode.LEASE_LEVEL`; `analyze_lease_level_acquisition_with_projection`; the Lease-Level result envelope retaining the monthly projection. **G-2** bit-identity, **G-3** perturbation, **G-6** monthly-leak, **G-M11** debt |
| D4.4 | Sensitivity and break-even over the same four `AcquisitionTerms` dimensions Detailed uses (2.16), via the immutable-container `dataclasses.replace` pattern |
| D4.5 | End-to-end golden case with real expenses, reusing Detailed's verified expense numbers; full-suite closeout |

D4 must resolve, in order: the below-NOI variable capital-cost channel; TI/LC
integration; CapEx interaction; monthly NOI → annual NOI; forward exit NOI;
downstream return compatibility; and whether to expose an authoritative monthly
debt-service schedule (only if it requires **no** economic change — 5.8).

**The monthly projection is never discarded after annual integration.**

### D5 — Persistence, API, frontend, ingestion, provenance

| Gate | Content |
|---|---|
| D5.0 | Resolve the evidence-status / provenance question (Section 32, HD-8) |
| D5.1 | Persistence: schema 5, three tables, fingerprint extension, the snapshot decision (22.3) |
| D5.2 | API: `lease_level` branches on `/analyze`, `/sensitivity`, `/break-even`, `/ai/analysis`, `/deals` |
| D5.3 | Frontend: Lease-Level mode, Operations sub-views, Rollover Schedule, the **Annual / Monthly** toggle, the monthly rent-roll table (23.3, 23.4). **G-M7** |
| D5.4 | Ingestion: `RentRollExtractionResult`, the tabular Excel reader, per-field analyst approval |
| D5.5 | AI Analyst: extended grounding rules; **G-M8** |

### D6 — Competition hardening

Excel reconciliation against a reference model, edge cases, performance
sanity at realistic lease counts, and the SHOULD-HAVE items from 25.2 that
survive triage.

**No resequencing of D1–D6 is recommended.** The order matches the dependency
graph found in the code, and each phase has a provable stop condition.

---

## 30. Architecture Guardrails

### 30.1 Structural guardrails

| ID | Guarantee | Mechanism | Gate |
|---|---|---|---|
| **G-1** | Lease-Level does not leak into any other layer | AST import test over `src/anchor/leasing/` + fresh-subprocess `sys.modules` check | D1.0 / D1.4 |
| **G-2** | Quick and Detailed are unchanged | Both existing golden cases bit-identical after every Sprint D gate | Every gate |
| **G-3** | TI and LC stay below NOI | Perturbation: doubling every TI/LC input leaves NOI, `exit_noi`, `going_in_cap_rate`, DSCR and debt yield bit-identical, while changing cash flows and IRRs once D4 wires the channel | D2.4 / D4.3 |
| **G-5** | Free rent and downtime never overlap | Disjoint period-index sets for every successor lease | D2.3 |
| **G-6** | Monthly data never reaches an annual-periodic calculation | The IRR solver receives exactly `H+1` values; no module outside `anchor.leasing` reads a canonical monthly series | D4.3 |
| **G-11** | Exit NOI uses the approved window | `exit_noi` equals the hand-summed periods `12H+1..12H+12`, and explicitly differs from `noi_by_year[-1]` in a case where they diverge | D4.2 |
| **G-12** | Debt conventions untouched | No Lease-Level module imports `anchor.engine.debt`; `annual_debt_service` and `remaining_loan_balance` bit-identical across all three modes for identical `AcquisitionTerms` | D4.3 |

### 30.2 Monthly guardrails

| ID | Guarantee | Mechanism | Gate |
|---|---|---|---|
| **G-M1** | The monthly schedule is canonical and is retained | The monthly projection is a field on the result envelope; a test asserts it is populated and is the source of every annual figure | D1.3 / D4.2 |
| **G-M2** | Annual flow outputs derive solely from monthly outputs | AST test: every `_by_year` flow field is produced only by an aggregation function whose input is a monthly tuple | D1.3 / D4.2 |
| **G-M3** | There is no independent annual Lease-Level rent engine | No function in `anchor.leasing` computes an annual rent figure from lease inputs directly | D1.3 |
| **G-M4** | Monthly and annual reconcile exactly | `annual[y] == sum(monthly[12(y-1)+1..12y])` at `abs=1e-9`, on real projections, for every flow metric and every year | D1.3, every later gate |
| **G-M5** | Flow metrics are summed | Aggregation of a flow metric uses `aggregate_flow_to_annual` and nothing else | D1.3 |
| **G-M6** | State metrics have explicit annual semantics | Every published annual state field name begins with `average_` or ends with `_at_year_end` / `_at_year_start`; asserted over dataclass field names | D1.3 |
| **G-M7** | The frontend calculates no lease economics | AST/regex test over `web/src/`: no period arithmetic, no escalation math, no rollover dates, no annual↔monthly conversion | D5.3 |
| **G-M8** | AI calculates no lease economics | The AI layer receives a computed result envelope and `rollover_events`; delegation asserted with `patch(..., wraps=...)`; grounding rules extended so the AI may describe a rollover but never re-derive a rent, downtime, TI or LC | D5.5 |
| **G-M9** | Calendar and sequential identity stay aligned | `ModelMonth` invariants asserted for every period of every projection | D1.1 |
| **G-M10** | Quick and Detailed remain bit-identical | Same as G-2, asserted also in a fresh subprocess | Every gate |
| **G-M11** | Monthly presentation implies no monthly debt/returns change | No `annual_debt_service / 12` anywhere; any monthly debt view derives from `engine/debt.py`'s existing monthly chronology with zero economic change | D4.3 / D5 |
| **G-M12** | Exit NOI comes from the canonical monthly projection | `exit_noi` asserted equal to the slice of the same monthly series served to the UI — never a separate calculation | D4.2 |
| **G-M13** | TI and LC remain below NOI | Same as G-3 | D2.4 / D4.3 |
| **G-M14** | Lease-Level vacancy is never combined with Detailed general vacancy | No Lease-Level contract declares `vacancy_credit_loss_pct` or `occupancy` | D1.4 |
| **G-M15** | Unsupported partial-month dates fail rather than overstate rent | A non-aligned economic date is an ERROR and yields no schedule | D1.0 |

Every guardrail follows one of the four established shapes from
`docs/solutions/conventions/testing-conventions-and-architecture-guardrails.md`
(AST import test, data-flow spy, `wraps` delegation proof, spec-sourced golden
case) rather than inventing a new pattern.

---

## 31. Consistency Audit

A full-document audit was performed against the terms below. Each was searched
for and either removed or confirmed absent.

| Searched term / contradiction | Result |
|---|---|
| "monthly internal" | **Removed.** Replaced by "monthly canonical" throughout (1.2, 5.1) |
| "annual published" as the sole publication | **Removed.** Replaced by "monthly and annual published" |
| Monthly data discarded after aggregation | **Absent.** Explicitly forbidden by G-M1 and FM-25 |
| A separate annual Lease-Level calculation | **Absent.** Forbidden by G-M2, G-M3 |
| "any-overlap-pays" | **Removed.** Replaced by mandatory month alignment with an ERROR (5.5) |
| Partial-date warning that still pays full rent | **Removed.** `LEASE_DATE_NOT_MONTH_ALIGNED` is an ERROR, not a warning (19.2) |
| Silent boundary coercion | **Absent.** 5.5 and 19.4 forbid it explicitly |
| `AcquisitionResults` changes in D1 | **Removed.** D1 modifies no existing file (28.1, 28.3) |
| Snapshot schema changes in D1 | **Removed.** Snapshot versioning is a D5 concern (22.3) |
| Global `IssueSeverity` changes in D1 | **Removed.** Severity is leasing-scoped (19.1); a D1.0 test asserts `validation.py` is untouched |
| Hold-Year-1 Modified Gross fallback | **Removed.** Explicit recovery basis required; ERROR otherwise (16.2, FM-24) |
| `ANALYST_SUPPLIED` `EvidenceStatus` | **Removed** as a recommendation. Deferred to D5 as an open question (Section 32, HD-8); Section 20 no longer proposes it |
| "today's dollars" | **Removed.** Replaced by "as of `analysis_start_date`" (24.3) |
| ARGUS attribution for the rollover mechanism | **Removed.** No external-product attribution is claimed (8.3). "ARGUS-like complexity" survives only as a scope-category label (25.3) |
| Monthly-compounded market rent | **Absent as the convention.** Annual step growth is locked; monthly compounding is explicitly rejected for the first version (7.2) |
| A general Lease-Level vacancy factor | **Absent.** The field does not exist on any contract (15.2, G-M14) |
| TI above NOI | **Absent.** Below NOI everywhere (11, 18.1, G-3) |
| LC above NOI | **Absent.** Below NOI everywhere (12, 18.1, G-3) |
| LC truncated at exit | **Absent.** Full contractual term (12.2, FM-17, D2-G2) |
| Smoothed exit NOI | **Absent as a default.** Explicitly rejected (17.2) |
| Frontend monthly calculations | **Absent.** Forbidden by 23.5, G-M7, FM-9 |
| `annual_debt_service / 12` | **Absent.** Forbidden by 5.8, G-M11, FM-23 |
| D1 dependencies on rollover / TI / LC / recoveries / other income | **Absent.** 28.1 excludes all of them; 14 states D1 does not depend on other income |

**Two arithmetic corrections were made during this pass**, both in material that
would otherwise have reached an implementer:

1. **A period-index error.** A lease commencing `2027-04-01` with
   `analysis_start_date = 2026-01-01` is period **16**, not 15
   (`12*1 + (4-1) + 1 = 16`). D1-G4 is corrected and now states the derivation.
2. **The fractional-downtime rule used `ceil` where the invariant requires
   `floor`.** With `ceil`, an integer downtime `D = 6` produced only 5 fully
   vacant periods. The corrected rule is
   `c = e + 1 + floor(D)` with a boundary factor `1 - (D - floor(D))` at period
   `c`, which yields exactly `D` months forgone for every real `D >= 0`,
   including whole numbers, with no special case (9.3). D2-G3b is recomputed
   accordingly.

---

## 32. Human Decisions — Final Register

### 32.1 Resolved decisions

| ID | Decision | Status | Blocks D1? |
|---|---|---|---|
| **HD-1** | `AcquisitionResults` / below-NOI leasing-cost channel | **DEFERRED TO D4** | **No** |
| **HD-2** | Rollover convention | **APPROVED** — deterministic expected rollover successor preserving renewal and new-tenant assumptions | No |
| **HD-3** | Whole-month / partial-date convention | **APPROVED AS MODIFIED** — month-aligned economic dates required; unsupported partial-month dates are ERROR; no any-overlap approximation | No |
| **HD-4** | Explicit renewal-rent semantics | **APPROVED AS MODIFIED** — measured **as of `analysis_start_date`**; the temporal anchor is explicit in documentation and UI label | No |
| **HD-5** | Rollover inside the forward exit window | **APPROVED** — fully live, months `12H+1..12H+12` | No |
| **HD-6** | Validation severity | **APPROVED AS MODIFIED** — leasing-scoped ERROR/WARNING architecture; no global validation refactor for D1 | No |
| **HD-7** | Modified Gross missing base-year fallback | **REJECTED AND REPLACED** — explicit analyst-approved recovery basis required; no Hold-Year-1 fallback | No |
| **HD-8** | `ANALYST_SUPPLIED` `EvidenceStatus` | **DEFERRED TO D5** — evidence status vs. data provenance must be distinguished first | No |
| **ND-1** | Monthly schedules | **APPROVED / LOCKED** — monthly Lease-Level schedules are canonical **and** user-facing; annual values derive from monthly | No |
| **ND-2** | Market rent growth | **APPROVED / LOCKED** — annual step growth on `analysis_start_date` anniversaries | No |
| **ND-3** | Initial LC convention | **APPROVED / LOCKED FOR D2** — % of total contractual base rent over the successor term, including escalations, gross of free rent, untruncated at hold end, with a method extension seam on `MarketLeasingAssumptions` | No |

**No human financial decision blocks D1.**

### 32.2 Open questions, scheduled, non-blocking

#### HD-1 — the below-NOI variable capital-cost channel  *(resolve at D4.0)*

**Question.** What is the correct shared shape for a below-NOI, year-varying
property capital cost that an operating-projection producer emits?

Candidates, to be evaluated at D4 with the code in front of the implementer:

| Option | Note |
|---|---|
| `leasing_costs_by_year` | Narrowest. Names the lease-specific cause, which makes the shared acquisition engine lease-aware |
| `variable_below_noi_costs_by_year` | Neutral; contrasts with the constant `capex_by_year` |
| `property_capital_costs_by_year` | Neutral and closest to how a property cash flow is normally described |
| Another neutral additive structure | e.g. a small `BelowNoiCosts` record carrying named components |

**Guidance recorded at D0, not a decision.** Do **not** prematurely make the
shared acquisition engine lease-specific if a broader neutral property
cash-flow concept is more correct — a future Development Engine would need the
same channel for construction and lease-up costs. Whatever is chosen must be
additive, neutral by default (absent ⇒ bit-identical Quick and Detailed
results), and must leave `capex_by_year` reporting the CapEx reserve alone.

**Dependencies.** Snapshot schema versioning (22.3) and the frontend result type
follow this decision, both at D5. Nothing before D4 is affected.

#### HD-8 — evidence status vs. data provenance  *(resolve at D5.0)*

**Question.** Are "evidence quality" and "data origin" the same concept?

An analyst-entered assumption has `origin = analyst` and **no documentary
evidence**. Whether that justifies a sixth `EvidenceStatus` member, or a
separate origin field alongside the existing five-state evidence enum, is a D5
architecture question. `CONCEPTS.md`'s "exactly these five states" is **not**
amended by this document.

**Dependencies.** None before D5. D1–D4 have no ingestion or provenance surface.

### 32.3 Stop conditions

| # | Condition | Status |
|---|---|---|
| 1 | Existing architecture makes the convergence model materially incorrect | **Not triggered.** `OperatingProjectionLike` accommodates a third producer, as `docs/detailed_operating_model_v2_1_architecture.md` §13 anticipated |
| 2 | A lease convention has multiple valid interpretations requiring product intent | **Resolved.** Every such convention is now locked (32.1) |
| 3 | Monthly modeling requires unexpected changes to acquisition/debt/returns semantics | **Not triggered.** Debt is already monthly-internal; returns need no change; the one additive channel is scheduled for D4 and neutral by default |
| 4 | Exit NOI cannot be integrated without changing an existing convention | **Not triggered.** The forward-NOI convention is the existing one, restated monthly (17.3) |
| 5 | D1 cannot be cleanly isolated from D2 | **Not triggered.** D1's rent formula contains no D2 term; D2 adds leases to the same engine (28.2) |
| 6 | Repository state differs materially from the stated baseline | **Not triggered.** `fffdf34`, clean tree, 1773 + 711 tests verified locally |

**No new blocking issue was discovered during this amendment.** Two arithmetic
errors were found and corrected (Section 31); neither required a product
decision.

---

## Appendix A — Total blast radius outside `anchor.leasing`

**None of this is implemented by D0.** Listed so a reviewer sees the whole
surface in one place, with the phase that touches it.

| File | Change | Phase |
|---|---|---|
| *(none)* | — | **D1** |
| *(none)* | — | **D2** |
| *(none)* | — | **D3** |
| `src/anchor/engine/acquisition.py` | The below-NOI channel (HD-1); `analyze_lease_level_acquisition_with_projection` | D4 |
| `src/anchor/engine/contracts.py` | The below-NOI series on `AcquisitionResults`; the Lease-Level result envelope | D4 |
| `src/anchor/contracts.py` | `OperatingMode.LEASE_LEVEL` | D4 |
| `src/anchor/engine/operating_projection.py` | *Possibly* a pure extraction of a shared expense-growth helper — only if **G-2** proves Detailed bit-identical first (13.1) | D4 |
| `src/anchor/analysis/sensitivity.py` | `LEASE_LEVEL_SUPPORTED_ASSUMPTIONS` (the same four dimensions) | D4 |
| `src/anchor/api.py` | `lease_level` branches on five endpoints | D5 |
| `src/anchor/deals/*` | Schema 5, three tables, fingerprint extension | D5 |
| `src/anchor/ingestion/contracts.py` | `LeaseCandidateRow`, `RentRollExtractionResult`; possibly a provenance/origin field (HD-8) | D5 |
| New `src/anchor/lease_level_excel_reader.py` | Tabular rent-roll reader | D5 |
| `src/anchor/validation.py` | *Possibly* global severity — **a separate architectural decision on its own merits**, never a Sprint D prerequisite | Post-D5, if ever |
| `web/src/types.ts`, `convert.ts`, `underwrite.ts` | Lease-Level mode, Operations sub-views, Rollover Schedule, Annual/Monthly toggle | D5 |
| New `web/src/components/RentRollTable.tsx` | The monthly rent-roll surface | D5 |
| `CONCEPTS.md` | Only if HD-8 resolves toward amending `EvidenceStatus` | D5 |

Every entry is additive. No existing formula, field meaning, or convention is
modified anywhere in this list.
