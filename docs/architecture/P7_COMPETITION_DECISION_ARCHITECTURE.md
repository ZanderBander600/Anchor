# P7 Competition Decision Architecture

Status: **Proposed - awaiting human ratification.** Nothing in this document is
ratified until a human marks it so. Where it restates a Phase 6 rule, the Phase 6
document stays the authority.
Phase: P7 - Generalized Investment Decision Architecture
Gate: P7.0 (architecture only; no financial calculation implemented)
Base: `main` @ `0593baa` (Phase 6 complete)
Branch: `feature/p7-0-competition-decision-architecture`

> Phase 5 forecasts the property. Phase 6 models the cost of executing the
> business plan. Phase 7 lets an analyst ask: *given this opportunity, what
> should we do, why, and how robust is that decision?*

---

## 0. Authority, Scope and Numbering

- Once ratified, this document is the architectural authority for Phase 7. Every
  P7 gate implements against it and must settle what it leaves open (§21)
  explicitly, never incidentally.
- `docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md` stays the authority for
  every Phase 6 financial rule. P7 extends Phase 6 and never redefines it. The
  earlier conventions (`docs/financial_conventions.md`, underwriting V2, detailed
  operating model v2.1, owner return metrics v3, and the D0-D4 lease-level
  documents in `docs/plans/`) also stay authoritative.
- `docs/development/ANCHOR_DEVELOPMENT_PROTOCOL.md` governs every P7 gate.
- **Numbering.** "Phase 7 / P7" continues the D-series gate numbering (D0-D6).
  It is unrelated to the numbered Development Sequence in `AGENTS.md`, and to
  the historical "Phase 7" named in the `anchor.analysis.sensitivity` module
  docstring (that module predates the D-series).
- **Engine input expansion.** `AGENTS.md` requires explicit approval to expand
  the core engine's inputs. Scenario and Strategy resolution (§7) produce
  *existing* contracts and so do not expand them. Consolidation, Capital
  Structure and Partnership are new deterministic layers **downstream** of
  the engine. Each P7 gate that adds a financial input or a calculation layer
  must still record its own explicit approval, just as D6 decision D1 did (§21,
  Q16).

### Anti-overfitting rule (permanent)

Historical competition cases are **acceptance archetypes** (§17). They never
define production architecture. No production identifier, module, enum member,
table, route, component or copy string may name a case, a competition, a
sponsor or a specific transaction. The test is always *"can the generic
architecture represent this case?"* and never *"how do we code this case?"*
`tests/test_p7_0_decision_architecture.py` enforces this for `src/anchor` and
`web/src`.

---

## 1. Purpose

P7.0 designs the permanent architecture that lets Anchor underwrite and
compare the broad range of investment cases that arise in an institutional
case competition or in professional acquisitions work:

- stabilized, value-add and lease-up acquisitions;
- mixed-use properties and multi-property portfolios, across any property
  type whose operations one of Anchor's operating modes can represent;
- debt investments and structured capital: senior, mezzanine, preferred
  equity, common equity and rescue capital;
- recapitalizations and refinancing;
- joint ventures, LP / GP waterfalls and promotes;
- alternative business plans, financing structures and hold / sell /
  recapitalize decisions, each under Base / Downside / Upside views of the
  world;
- and, from Phase 8, development and redevelopment.

It must do this **without case-specific engines**, and without destabilizing
the mature Quick / Detailed / Lease-Level implementation that Phase 6 ratified.

## 2. Product Objective

Anchor should be able to produce, for one investment opportunity:

```
                     Downside        Base          Upside
Strategy A              x              x              x
Strategy B              x              x              x
Strategy C              x              x              x
```

Each cell is one complete, deterministic Anchor analysis, produced by the
**same** financial engine. The analyst's decision rests on comparing the
cells, reading the qualitative context beside them (§16 and the Decision layer in §5), and on
AI interpretation that never becomes financial truth.

The simplest workflow stays simple. An analyst underwriting one ordinary
acquisition must never have to create a portfolio, a scenario, a strategy or
a partnership (§15.1).

---

## 3. Permanent Principles

These principles bind every P7 gate. They extend the Phase 6 invariants and
never replace them.

| # | Principle |
|---|---|
| P-1 | **One engine.** Every number comes from the existing deterministic pipeline: an operating mode produces NOI, the resolver turns the Business Plan into an `OwnerCapitalSchedule`, and `analyze_acquisition_from_operating_projection` does the rest. No P7 layer re-derives an operating, debt or return figure that engine already produces. |
| P-2 | **Resolve, then run.** Scenarios and Strategies are resolved *before* the engine, into ordinary existing input contracts (`AcquisitionInputs`, `AcquisitionTerms`, `DetailedOperatingInputs`, Lease-Level contracts, `BusinessPlan`). The engine never learns that a scenario exists. |
| P-3 | **Consume, never recompute.** Layers downstream of the engine (consolidation, capital structure, partnership, decision) read completed `AcquisitionResults` fields. Wherever they need a metric on a new series (for example an IRR on a consolidated or partner series), they call the *existing* `anchor.engine.returns` functions. The IRR algorithm (D10) never changes. |
| P-4 | **Layers never flow backwards.** Property economics determine available cash. Capital structure determines who is paid, and in what order. Partnership economics allocate the common equity among investors. The Decision layer compares results. No downstream layer writes to an upstream one: capital structure never changes NOI, and partnership terms never change project cash flow. |
| P-5 | **The comparison layer is read-only.** Decision comparison is a *presentation over* deterministic results. It never computes a separate financial truth. Any cross-cell figure (a delta, a worst case) is computed by a backend module over already-computed results, never by the frontend or the AI. |
| P-6 | **No silent mutation.** Base assumptions are never modified by a scenario or a strategy. Removing an override restores the exact base value, because the base was never changed. |
| P-7 | **Economic order is explicit.** Where order is economically meaningful (capital priority, waterfall tiers, same-year capital events), it is a named rank field. List position is only ever presentation. Where order is economically irrelevant, the canonical form sorts by stable ID (§15.5). |
| P-8 | **Stable identity for everything addressable.** Every unit, item, suite, lease, scenario, override, strategy, position, tier and partner has a stable opaque ID. This is what makes provenance (§16.3), fingerprints and exact revert possible. |
| P-9 | **Absent means absent.** A metric that cannot be computed honestly is reported as N/A with a deterministic reason. It is never averaged, zero-filled or fabricated. That covers a consolidated occupancy when a Quick unit has no area, and an IRR on a multiple-sign-change series. |
| P-10 | **Additive schema only.** Existing saved deals reopen, analyze and fingerprint exactly as they do today. P7 adds tables and never rewrites a legacy row (§15). |
| P-11 | **Opt-in complexity.** Every P7 structure has an implicit default equal to today's behavior (1 unit, Base strategy, Base scenario, no structured capital, no partnership). Wrappers materialize in storage only when the analyst opts in, and never appear as meaningless UI chrome (§15.1). |
| P-12 | **Documents -> Proposed Inputs -> Analyst Approval -> Deterministic Engine -> Decision Support.** AI proposes and interprets; the analyst decides; the engine calculates (§16). |

---

## 4. Current Architecture Map (audit of `0593baa`)

### 4.1 Domain and engine

| Concept | Where | What it is today | Scope today |
|---|---|---|---|
| `Deal` | `src/anchor/deals/contracts.py` | One saved, named record. `operating_mode` (`QUICK` / `DETAILED` / `LEASE_LEVEL`) is the discriminator; `__post_init__` enforces a total per-mode dispatch. It nests the frozen engine contracts directly, never a parallel representation. | One property = one deal = one investment. |
| Quick inputs | `AcquisitionInputs` (`src/anchor/contracts.py`) | The 9 POC fields plus 5 Underwriting V2 fields. `acquisition_terms_from_inputs` projects them to `AcquisitionTerms`. | Deal |
| Detailed inputs | `AcquisitionTerms` + `DetailedOperatingInputs` | 11 terms + 11 Year-1 operating assumptions with growth. | Deal |
| Lease-Level inputs | `AcquisitionTerms` + `LeaseLevelPropertyInputs`, `LeaseLevelOperatingInputs`, `MarketLeasingAssumptions`, `Suite[]`, `Lease[]` (`anchor.leasing`) | Monthly canonical model from a rent roll. `analysis_start_date` is a calendar anchor. Suites may carry a market-rent or full market-leasing override. | Deal |
| `AcquisitionTerms` | `src/anchor/contracts.py` | Purchase price, hold, exit cap, the one acquisition loan (LTV, rate, amortization, IO), cost percentages and the recurring reserve. Shared by Detailed and Lease-Level. | Deal |
| `BusinessPlan` | `src/anchor/business_plan/contracts.py` | Capital Plan items (model month) and Owner Expense items (hold years), in one item-ID namespace. Mode-agnostic. | Deal |
| `OwnerCapitalSchedule` | `src/anchor/engine/contracts.py` | Resolved T0 and annual owner capital, plus a post-hold disclosure. A generic engine contract. | Deal |
| `OperatingCapitalSchedule` | `src/anchor/engine/contracts.py` | Annual TI / LC, below NOI. Deliberately not named for leasing: a future Development engine needs the same channel. | Deal |
| Debt | `src/anchor/engine/debt.py` | One fixed-rate loan: `loan = purchase_price x ltv`, level-payment amortization with an IO period, `financing_fee = loan x pct`, all costs equity-funded, balloon at H. | Deal |
| Exit | `src/anchor/engine/acquisition.py` | `exit_value = exit_noi (Year H+1) / exit_cap_rate`; disposition costs are a percentage of gross value; `net_sale_proceeds = exit_value - disposition - remaining balance`. | Deal |
| Engine entry | `analyze_acquisition_from_operating_projection(projection, terms, operating_capital=None, *, owner_capital=None)` | The single shared seam. Quick, Detailed and Lease-Level all converge here; `anchor.analysis.business_plan_analysis` provides the three `*_with_business_plan` entry points. | Deal |
| `ReturnMetrics` / `AcquisitionResults` | `src/anchor/engine/contracts.py` | The flat result contract: capital stack, debt, NOI, the owner cash-flow chain, both project cash-flow series, IRRs with `IrrStatus`, EM, DSCR, CoC, cash yield, TEI / TCR / Profit, NAER, Sources & Uses. | Deal |
| Mode envelopes | `DetailedAcquisitionResults`, `LeaseLevelAcquisitionResults` | The operating projection beside the unchanged `AcquisitionResults`. | Deal |

### 4.2 Secondary analysis

| Concept | Where | Notes |
|---|---|---|
| Sensitivity | `anchor.analysis.sensitivity`, `lease_level_sensitivity` | One- and two-way grids over approved targets. Quick has 6 (`SUPPORTED_ASSUMPTIONS`), Detailed 4, Lease-Level 8 (`_TARGETS`: owner contract + literal accessor + suite-shadowing predicate). The metrics are 5. Values are absolute. The Business Plan is held fixed (D13). An invalid cell raises; an undefined metric is `None`. |
| Break-even | `anchor.analysis.break_even` | Quick has 5 solvers and Detailed 3. Lease-Level has no break-even surface (D5.8). |
| **Internal vocabulary** | `_build_scenario_inputs`, `_scenario_contracts`, `_scenario_metric`; AI prompt text | **"Scenario" here means one sensitivity cell.** This collides with the P7 Scenario concept (§7). See §7.6. |

### 4.3 Persistence and fingerprints

| Concept | Where | Notes |
|---|---|---|
| Tables | `src/anchor/deals/store.py`, schema **v7** | `deals` (Quick), `detailed_deals` + `detailed_operating_inputs`, `lease_level_deals` + 5 child tables, the mode-blind `deal_sensitivity_snapshots`, and the mode-blind `deal_capital_plan_items` / `deal_owner_expense_items`. The mode is inferred from which parent table holds the id (uuid4 hex). There are no foreign-key pragmas; child rows are deleted explicitly. |
| Snapshots | parent-table columns + sensitivity table | Analysis snapshot v1 (Quick and Detailed only: Lease-Level results are recomputed on open, D5 decision A). AI snapshot v2. Sensitivity snapshot v1. Every snapshot is guarded by a source fingerprint; a stale or undecodable snapshot reads as absent. |
| Fingerprints | `src/anchor/deals/fingerprint.py` | sha256 of canonical sorted-key JSON of every economic input. A non-empty Business Plan adds one key; the empty plan adds nothing (D11). Suites, leases and plan items are sorted by ID. `fingerprint_ai` = f(analysis fingerprint, `deal_context`). |
| Lifecycle | `/deals` CRUD, `/duplicate`, `/fingerprint`, and the snapshot `PUT`s in `src/anchor/api.py` | Duplicate copies the plan; delete removes every child row. |

### 4.4 AI and web

| Concept | Where | Notes |
|---|---|---|
| AI context | `anchor.ai.contracts.AnalysisContext` | Mode, inputs, results, sensitivities, break-even, hurdle targets, `deal_context`, `business_plan`. The output is `AIAnalysis` + `DealStory`. Grounding rules forbid derived deltas and causal value-creation claims. |
| Web state | `web/src/App.tsx` | Quick and Detailed state live as parallel `useState` families (~80 hooks) in one ~124 KB component. Lease-Level state is `useLeaseLevelDeal`; Business Plan state is `useBusinessPlan`. New P7 state should follow those dedicated hooks rather than add to `App.tsx`. |
| Web IA | `workspaces.ts`, `underwrite.ts` | Workspaces: Overview / Underwrite / Risk / AI Analyst / Documents. Underwrite tabs: Acquisition / Operations / Debt / Exit / Results. `resultsViewsFor(mode)` includes the shared `CapitalEconomicsSection`. |
| Frontend arithmetic | guarded (`capitalEconomics.test.tsx`, `businessPlan.test.ts`) | The frontend performs no financial summation. |
| **UI vocabulary** | `web/src/components/StrategyStrip.tsx` | **"Strategy" is today the visible label for the `deal_context` free text.** It collides with the P7 Strategy concept (§7.6). |

### 4.5 Audit answers

**1. Naturally unit-scoped already.** Every operating-mode input; the Lease-Level
rent roll and market leasing; exit cap and exit NOI; the recurring reserve;
TI / LC; the `BusinessPlan` and its resolved `OwnerCapitalSchedule`; the whole
`AcquisitionResults` and each mode envelope; per-deal sensitivity and
break-even; the economic fingerprint. These describe one independently
forecastable economic thing.

**2. Deal-scoped today, and investment-scoped in general.** The deal name and the
`deal_context` thesis; the AI analysis and its hurdle targets; "the" returns
(IRR, EM, TEI / TCR / Profit); Sources & Uses; the hold period as the
investment horizon; the acquisition loan as *the* financing; the saved-deal
lifecycle. Today deal = unit = investment, so these coincide. They separate as
soon as there is more than one unit.

**3. Ambiguous with multiple units / components.**
- `purchase_price`: allocated vs. total transaction price (§11).
- `hold_period`: unit vs. investment horizon.
- `ltv` / `interest_rate` / `amortization` / `io_period`: a property mortgage
  vs. portfolio financing.
- `acquisition_cost_pct`: unit vs. transaction costs.
- Owner Expenses: asset management is usually charged at the investment
  level.
- `initial_equity`, IRR, EM, NAER, DSCR: unit-level vs. consolidated.
- `deal_context`, AI analysis, sensitivity targets ("which unit's exit cap?")
  and break-even ("max purchase price" of what?).
- The word "Deal" itself.

**4. Contracts that stay untouched.** `AcquisitionInputs`, `AcquisitionTerms`,
`DetailedOperatingInputs`, every Lease-Level input contract, `BusinessPlan` and
its items, `OwnerCapitalSchedule`, `OperatingCapitalSchedule`,
`AcquisitionResults` (no P7 field is appended to it), the mode envelopes,
`IrrStatus`, `debt.py`, `returns.py` (D10), the three per-unit fingerprint
functions, every existing table and column, and the existing sensitivity and
break-even modules. These are the Base-variant path.

**5. Where a parent layer attaches.** Two seams already exist and are enough:
- **Pre-engine: input-contract replacement.** Sensitivity already builds a
  modified input with `dataclasses.replace` and routes it through the shared
  validators. Scenario and Strategy resolution reuse exactly that seam
  (P-2).
- **Post-engine: `AcquisitionResults` consumption.** Consolidation, capital
  structure, partnership and decision are new packages that read completed
  results (P-3).

Neither seam requires rewriting the single-deal engine.

---

## 5. Recommended Domain Hierarchy

The foundational hypothesis (INVESTMENT CASE -> UNITS / STRATEGIES / SCENARIOS
/ CONSOLIDATION / CAPITAL STRUCTURE / PARTNERSHIP / DECISION) is **adopted with
three corrections**:

1. **Strategies and Scenarios are not siblings of the units in the data flow.**
   They are *resolution layers* applied to unit inputs (and, later, to
   investment-level structures) before the engine runs. They sit above the
   units, not beside them.
2. **Capital Structure and Partnership are Strategy domains, not independent
   roots.** A financing choice or a JV term sheet is an analyst decision, so it
   varies by Strategy. It is never varied by Scenario, except in the narrow
   financing-market case covered in §7.3.
3. **The Investment is optional.** A standalone deal remains a complete
   analysis root. An Investment is materialized only when the analyst opts
   into structure (§15.1).

```
INVESTMENT  (optional parent; materialized on opt-in)
 |
 |-- UNDERWRITING UNITS  (1..n; each is an existing Deal record, unchanged)
 |      Quick | Detailed | Lease-Level | (Phase 8: Development)
 |      each: operating inputs + AcquisitionTerms + BusinessPlan
 |
 |-- INVESTMENT-LEVEL INPUTS  (only when n > 1 or opted in)
 |      transaction price + allocation, investment-level Business Plan,
 |      investment-level transaction costs
 |
 |-- STRATEGIES  (Base is implicit; others are typed domain overlays)
 |      acquisition | financing / capital structure | Business Plan |
 |      operating outcome | disposition | partnership
 |
 |-- SCENARIOS  (Base is implicit; others are typed override sets)
 |
 v   resolution:  Base inputs -> Strategy overlay -> Scenario overrides
 |                -> ordinary validated contracts
 |
 |   ANALYSIS VARIANT = (root, strategy, scenario)  -- one deterministic run
 |
 |   per unit:  the existing engine  ->  AcquisitionResults
 |   CONSOLIDATION        units + investment-level channels  ->  consolidated series
 |   CAPITAL STRUCTURE    who is paid, and in what order  ->  position cash flows,
 |                        common equity cash flow
 |   PARTNERSHIP          common equity  ->  partner contributions / distributions
 |
 v
DECISION LAYER  (read-only)  strategy x scenario matrix, perspectives,
                              qualitative memo, AI interpretation
```

---

## 6. Definitions

**Investment.** The opportunity under evaluation: one negotiated transaction or
position, possibly spanning several units, which the investor decides on as a
whole. An Investment owns its units, its investment-level inputs, its
Strategies, its Scenarios and its qualitative memo. *(Naming: §21 Q1. "Case" is
rejected: it collides with "Base case" and with competition cases.)*

**Underwriting Unit (Unit).** One independently forecastable economic
component whose operations, Business Plan, valuation and leasing assumptions
(and possibly financing) are analyzed separately. **In code a Unit is an existing
`Deal` record, unchanged** (§8, Option A). A standalone deal is a one-unit analysis root. A Unit may be a whole property, one
asset in a portfolio, one separately valued mixed-use component, or (Phase 8)
a development phase. Its `unit_kind` is reporting metadata only.

**Strategy.** An analyst-controlled decision configuration: *what we choose to
do*. It is expressed as typed, domain-level overlays on the Base inputs
(§7.4). The Base strategy is the stored inputs themselves.

**Scenario.** A coherent, internally consistent view of uncertain external or
operating outcomes: *what the world does to us*. It is a typed set of approved
assumption overrides (§7.2). The Base scenario has no overrides.

**Analysis Variant.** The pair (Strategy, Scenario) applied to one analysis
root: one complete deterministic run through the same engine. It is an
analysis-layer identity, not an input entity (§7.5).

**Consolidation.** Combining the unit-level results of one Analysis Variant,
plus the investment-level channels, into investment-level series. Additive
figures are summed in a canonical order; ratios and returns are then derived
from the summed series (§9).

**Capital Position.** One source of capital with a contractual claim on the
cash: senior debt, mezzanine debt, preferred equity or common equity. It
carries an explicit priority, a scope (one unit or the whole investment), a
funding amount and typed terms (§12).

**Partnership.** The agreement among common-equity investors: who contributes
what, and how common-equity distributions are split through an ordered
waterfall (§13).

**Decision Comparison.** The read-only presentation of Analysis Variants side
by side, through a typed perspective (project, position or partner), plus the
analyst's qualitative context (§14.1, §16.2).

---

## 7. Strategy vs Scenario Convention

### 7.1 The rule

- **Strategy = decision.** Something the analyst or investor controls or
  negotiates: bid price, business plan, redevelopment choice, financing
  structure, capital-stack position, partnership terms, and hold / sell /
  refinance timing.
- **Scenario = uncertainty.** Something the market or the asset's operation
  determines: market rents and rent growth, leasing velocity, renewal
  probability, vacancy, expense growth, construction cost and timing, exit
  cap rates, and debt pricing or availability when treated as a market
  outcome.
- **The same Strategy is tested under every Scenario.** A Scenario must mean the
  same worldview whichever Strategy it is applied to. That requirement drives
  §7.2's override operators.
- **A Strategy may set strategy-conditional outcomes.** A renovation strategy
  may assert a higher achievable rent. That is the strategy's own base-case
  outcome (D6 §11: capital does not create rent; the analyst asserts it
  explicitly). Scenarios then perturb it.

### 7.2 Scenario contract (typed override set)

```
Scenario
  scenario_id        stable, opaque, nonempty; "base" is reserved and implicit
  name               analyst-defined, nonempty; arbitrary ("Downside", "Recession 2027", ...)
  description        optional
  overrides          set of ScenarioOverride (order irrelevant)

ScenarioOverride
  unit_id            the Unit (Deal) it applies to; always explicit, even with one unit
  target             an approved token from the Scenario Target Registry (§7.3)
  operation          SET | ADD | SCALE | CAP_AT   (allowed operations depend on the target)
  value              finite number on the wire scale (decimals for rates, dollars for money)
```

Rules:

- **SC-1 Uniqueness.** A scenario has at most one override per
  `(unit_id, target)`. Duplicates are refused, never composed, so override
  order can never matter.
- **SC-2 Operations.**
  - `SET` replaces the value.
  - `ADD` adds to it (for example `+0.005` = +50 bps on an exit cap).
  - `SCALE` multiplies it (for example `0.90` = market rent down 10%).
  - `CAP_AT` replaces it with `min(current, value)`. This is the only way to
    express *availability* (for example "lenders will lend at most 55% LTV")
    without overriding the strategy's financing *choice*.
  - Each registry target lists the operations it allows.
- **SC-3 Cross-strategy coherence.** Relative operations (`ADD`, `SCALE`,
  `CAP_AT`) apply to the *strategy-resolved* value. "Downside = market rent
  x 0.90" therefore keeps a renovation premium's relative position in every
  strategy. `SET` is available where an absolute market fact is intended (for
  example "exit cap = 7.25%"). The analyst must understand that `SET` erases
  strategy differences on that target.
- **SC-4 No clipping.** The resolved value is validated by the same validator
  the base input uses (`validate_acquisition_inputs`,
  `validate_acquisition_terms`, the Detailed and Lease-Level validators). An
  out-of-domain result (for example `renewal_probability` above 1 after `ADD`)
  makes that variant **invalid**, with an explicit reason. It is never
  clipped, skipped or rendered as `None` (the D4.6B §38.4.1 precedent: `None`
  means valid but undefined; invalid raises).
- **SC-5 Unresolvable override.** An override whose unit does not exist in the
  variant makes that variant invalid, with an explicit reason. It is never
  silently ignored.
- **SC-6 Exact revert.** Base inputs are never mutated (P-6). Deleting an
  override, or the scenario, restores the base result exactly, fingerprint
  included (§15.4).
- **SC-7 Same engine.** A scenario run is an ordinary run of the existing
  entry point on resolved contracts. No scenario-specific financial code path
  exists.

**Why a typed override set, not snapshots and not a JSON patch** (see §22.3):

- A full snapshot per scenario copies every input and silently diverges when
  a base fact is corrected.
- An untyped JSON patch can reach any field (hold period, a lease date, a
  category) with no domain rule, no operation semantics and no audit.

The registry is the precedent `_TARGETS` already set in
`lease_level_sensitivity.py`: an approved name, the contract that owns it,
and a literal accessor. There is no field-path traversal, no `setattr` and no
`eval`.

### 7.3 Scenario Target Registry (scope of scenario-aware inputs)

Each target carries a **semantic class**:

- `UNCERTAINTY`: scenario-aware.
- `DECISION`: strategy-only.
- `BOTH`: scenario-aware only through the operations listed.

The candidate P7.1 set is below. The exact tokens, and the final set, are
ratified in P7.1. The list reuses existing sensitivity target names wherever
they exist.

| Target | Owner contract | Modes | Class | Scenario operations |
|---|---|---|---|---|
| `exit_cap_rate` | `AcquisitionTerms` / Quick inputs | Q D LL | UNCERTAINTY | SET, ADD |
| `interest_rate` | `AcquisitionTerms` / Quick inputs | Q D LL | UNCERTAINTY (debt pricing) | SET, ADD |
| `ltv` | `AcquisitionTerms` / Quick inputs | Q D LL | BOTH (choice vs. availability) | CAP_AT only |
| `current_noi` | `AcquisitionInputs` | Q | UNCERTAINTY | SET, SCALE |
| `noi_growth` | `AcquisitionInputs` | Q | UNCERTAINTY | SET, ADD |
| `gross_potential_rent`, `other_income` | `DetailedOperatingInputs` | D | UNCERTAINTY | SET, SCALE |
| `vacancy_credit_loss_pct`, `revenue_growth`, `expense_growth` | `DetailedOperatingInputs` | D | UNCERTAINTY | SET, ADD |
| `market_rent_psf` | `MarketLeasingAssumptions` | LL | UNCERTAINTY | SET, SCALE (suite-override semantics: §21 Q10) |
| `market_rent_growth`, `renewal_probability` | `MarketLeasingAssumptions` | LL | UNCERTAINTY | SET, ADD |
| `expense_growth`, `recoverable_expense_ratio` | `LeaseLevelOperatingInputs` | LL | UNCERTAINTY | SET, ADD |
| `project_capital_cost_scale` | the unit's `BusinessPlan` (all capital items) | Q D LL | UNCERTAINTY (cost) | SCALE |
| `project_capital_delay_months` | the unit's `BusinessPlan` (items with `month >= 1`) | Q D LL | UNCERTAINTY (timing) | ADD (integer) |

Deliberately **not** scenario-aware (they are decisions, or structural):

- `purchase_price`;
- `hold_period`, `amortization`, `io_period`;
- the acquisition, financing and disposition cost percentages;
- `annual_capex_reserve`;
- Owner Expense items;
- individual plan items;
- every date, every lease-structure category, every suite- or lease-specific
  field;
- initial-vacancy strategy.

Each can be promoted later by an explicit registry decision. None is reachable
until then.

Business Plan targets, precisely:

- **Plan-wide only.** The two Business Plan targets act on every capital item
  of the unit's *resolved* plan, so they stay meaningful when a Strategy
  swaps in a different plan. Item-addressed overrides are deferred: an item
  that exists in one strategy's plan and not another's cannot mean one
  worldview.
- **Delay.** A delay moves only items with `month >= 1`. A closing item stays
  at closing. A delay that pushes an item past `12H` makes it post-hold
  capital, excluded and disclosed exactly as D6 §19 already defines. The
  scenario changes no D6 semantics.
- **Owner Expenses are not scenario-aware.** They are contractual owner
  decisions.

**Scenario vs. Sensitivity.**
- A Scenario is a coherent multi-variable worldview, named and persisted, and
  compared as a column.
- A Sensitivity is a controlled perturbation of one or two parameters around
  one Analysis Variant, as a grid.

Both use the same engine through the same input-replacement seam. Sensitivity
keeps its own frozen target lists. Where a Scenario target and a Sensitivity
target share a name, they must mean the same field of the same contract, and a
P7.1 guard asserts that, just as D4.6B asserted that the Lease-Level shared
targets equal `DETAILED_SUPPORTED_ASSUMPTIONS`. Sensitivity over a non-Base
variant is a later extension (§20).

### 7.4 Strategy contract (typed domain overlays)

```
Strategy
  strategy_id        stable, opaque; "base" is reserved and implicit (= the stored inputs)
  name, description
  overlays           at most one overlay per (domain, unit_id | investment)
```

Strategy domains. Each is a *whole-domain replacement* or a typed override set,
never an untyped patch:

| Domain | Scope | Overlay form | Replaces |
|---|---|---|---|
| `ACQUISITION` | unit (or investment price + allocation, §11) | whole block | `purchase_price`, `acquisition_cost_pct` |
| `FINANCING` | unit | whole block | the acquisition loan (`ltv`, `interest_rate`, `amortization`, `io_period`, `financing_fee_pct`) |
| `BUSINESS_PLAN` | unit, or investment-level plan | whole `BusinessPlan` | the unit's `BusinessPlan` (same contract, same resolver, D6 untouched) |
| `OPERATING_OUTCOME` | unit | typed override set: Scenario Target Registry tokens with `SET` only, any class | strategy-conditional outcomes (for example a renovated market rent) |
| `DISPOSITION` | unit / investment | whole block | `hold_period` (and later a unit sale year, §9.5) |
| `CAPITAL_STRUCTURE` | investment / unit | whole position set | the capital stack (§12) |
| `PARTNERSHIP` | investment | whole partnership | the waterfall (§13) |
| `UNIT_SELECTION` (later) | investment | set of unit IDs | which units are acquired (bid-on-part strategies) |

Rules:

- **ST-1 Base is the stored inputs.** Creating a strategy copies nothing.
  Correcting a base fact (a lease date, a tax bill) propagates to every
  strategy that does not overlay that domain, which is the correctness reason
  for rejecting full copies (§22.4).
- **ST-2 Whole-domain replacement.** A financing choice is one coherent
  package, and a renovation plan is one coherent plan. Replacing a whole
  domain keeps each strategy's decision self-consistent and makes a
  strategy's content inspectable as a list of what it replaces.
- **ST-3 Resolution order.** Base -> Strategy overlays -> Scenario overrides
  -> validation -> engine. It is deterministic and it is the only order.
- **ST-4 Inspectability.** For every variant the backend can return the fully
  resolved inputs ("what exactly ran"). This is the debuggability counterweight
  to overlays.
- **ST-5 Different horizons are allowed.** Strategies with different hold periods
  are legitimately comparable on IRR, EM and Total Profit. Their annual rows
  are not aligned, and the matrix never pretends they are (§19).

### 7.5 Analysis Variant

- **Identity:** `(root_id, strategy_id, scenario_id)`, where `root_id` is a
  standalone deal id or an investment id.
- **Validity:** a variant's result is current when its stored
  `source_fingerprint` equals the **resolved-input fingerprint** (§15.4).
- **Recommendation: an analysis-layer composition, not a persisted input
  entity.** There is nothing to author on a variant; everything authored lives
  on the strategy and the scenario. Only its *cached result* is persisted, in
  a mode-blind snapshot table keyed by the identity plus the source
  fingerprint. That follows the `deal_sensitivity_snapshots` precedent.
  - Lease-Level variants follow D5 decision A: they are recomputed, not
    cached, unless a human re-decides (§21 Q14).
- **Base x Base of a legacy deal is today's analysis.** It is served by the
  existing analysis snapshot. It is never a duplicate row.

### 7.6 Edge cases and vocabulary

| Case | Resolution |
|---|---|
| Financing availability / pricing | Rate spreads are UNCERTAINTY (`interest_rate` ADD). Leverage *choice* is a Strategy (`FINANCING`); leverage *availability* is `CAP_AT`. |
| Construction cost overrun | Scenario `project_capital_cost_scale`. Choosing a bigger renovation is Strategy `BUSINESS_PLAN`. |
| "Delay the renovation" | An *uncertain* delay is Scenario `project_capital_delay_months`. A *chosen* phasing is Strategy `BUSINESS_PLAN`. |
| Renovated rent premium | Strategy `OPERATING_OUTCOME` (analyst-asserted). Scenario `SCALE` then perturbs it coherently. |
| Bid price | Always Strategy. "What if we must pay more" is a bid strategy or a sensitivity, never a scenario. |
| Exit cap by strategy (a renovated asset trades tighter) | Strategy `OPERATING_OUTCOME` may `SET` a strategy-specific exit cap. Scenario `ADD` widens every strategy by the same bps. |
| Hold / sell / refinance | Strategy `DISPOSITION` + `CAPITAL_STRUCTURE`. Never a scenario. |
| Legacy word "scenario" in sensitivity code | Private helpers keep their names (guards pin them). New code and new UI say **"sensitivity case"** for a grid cell. The P7 AI gate disambiguates the prompt text. |
| Legacy UI label "Strategy" on `deal_context` | The `StrategyStrip` label must be renamed (for example to "Deal Context" or "Thesis") in the first gate that ships the Strategy concept to the UI. This is a Tier 4 copy change, recorded now so it is not missed. |

---

## 8. Unit / Portfolio / Mixed-Use Convention

### 8.1 Existing Deal as the Underwriting Unit

**Recommendation: Option A** (full comparison in §22.1 and §22.2).

- **A. Parent Investment over unchanged Deals (recommended).**
  - Every current contract, table, fingerprint, snapshot, API route and guard
    stays as it is.
  - A new `investment_units` membership table links an Investment to existing
    deal ids.
  - Migration cost: none. Legacy compatibility: total.
  - Flexibility: high. A Development unit (Phase 8) is just another
    `operating_mode`.
  - Cost: the code noun `Deal` now means "unit". The UI keeps "Deal" for
    standalone analysis and says "Unit" (with its kind) inside an Investment.
- **B. Rewrite `Deal` into a nested `Investment { units[] }`.** Every table,
  fingerprint (legacy digests break or need an adapter), API payload, web
  state family (`App.tsx`) and hundreds of architecture guard tests would have
  to move. Rejected: months of Tier 1-2 churn for no economic gain.
- **C. Add `components[]` to `Deal`.** The Deal's per-mode dispatch becomes
  nested, every mode's parent table has to be split per component, and
  fingerprints change shape. Rejected: Option B's cost with less clarity.

### 8.2 Unit rules

| Aspect | Rule |
|---|---|
| Identity | `unit_id` is the existing deal id. A unit belongs to **at most one** Investment (§21 Q3); reuse means duplicating it. |
| Display name | The deal's `name`. Inside an Investment the membership row adds an optional short label and `unit_kind`. |
| `unit_kind` | `PROPERTY` / `COMPONENT` / `PHASE`. **Reporting and UI metadata only**, like the D6 categories. Nothing may branch on it financially. |
| Analysis mode | The deal's own `operating_mode`. Units in one Investment may use different modes. |
| Acquisition allocation | The unit's `AcquisitionTerms.purchase_price` *is* its allocated price (§11). |
| Business Plan | The unit's own `BusinessPlan` (D6, unchanged). Shared costs go in the investment-level plan (§10). |
| Operating projection | Produced by the unit's own mode. The unit owns it. |
| Valuation | The unit's own exit cap and exit NOI (D6 exit semantics unchanged), plus valuation timepoints (§11.3). |
| Financing | The unit's acquisition loan (`AcquisitionTerms`), if any. Investment-level financing is a Capital Position (§12). |
| Relationship to consolidated results | Unit results are complete, correct `AcquisitionResults` for that unit alone. Consolidated results never alter them (§9). |

### 8.3 Mixed-use vs. portfolio: one architecture

**Recommendation: one Unit / consolidation architecture for both.** A mixed-use
component and a portfolio asset differ only in presentation:

| | Portfolio asset | Mixed-use component |
|---|---|---|
| `unit_kind` | `PROPERTY` | `COMPONENT` |
| UI grouping | "Assets" | "Components" of one property |
| Typical financing | Often per-unit mortgages | Usually one investment-level loan |
| Typical sale | Separately saleable | Usually sold with the whole (a component sale is a Strategy) |
| Financial semantics | **Identical**: consolidation, allocation, plans, positions and scenarios all work the same way | |

A mixed-use component should become a separate Unit when it needs a different
exit cap, operating-expense structure, business plan or valuation. Components
that differ only in leasing assumptions can stay suites of one Lease-Level unit.
Suites already carry per-suite market-leasing overrides, so no new structure is
needed for that case.

---

## 9. Consolidation Rules

Consolidation applies to one Analysis Variant of an Investment. It consumes each
unit's `AcquisitionResults` and the investment-level channels, and produces a
new `ConsolidatedResults` contract. `AcquisitionResults` is never re-used as the
consolidated contract, because its single-loan and single-price semantics do not
hold for an Investment.

### 9.1 Preconditions (first multi-unit gate)

- **CON-1 Common timeline.** Every unit shares closing `T0` and the same hold
  period `H` (the investment horizon). Lease-Level units share one
  `analysis_start_date`. Quick and Detailed units align by model-year index.
  A mismatch is refused with an explicit reason. It is never padded or
  truncated.
  - This rule is **validation, not structure**. The contracts must not assume
    it, so staggered acquisitions and unit sales (§9.5) and Phase 8
    phases can relax it later by ratified convention.
- **CON-2 Annual consolidation.** Consolidated series are annual (`t = 0..H`).
  Lease-Level monthly detail stays unit-level.
- **CON-3 Canonical order.** Units are unordered economically but summed in
  ascending `unit_id` order. Floating-point addition is not associative, and
  results must be bit-reproducible whatever the analyst's display order.

### 9.2 Additive (period-by-period sums across units)

These are summed, then the investment-level channels (§10) are applied at their
single subtraction site:

- NOI_y.
- Revenue and expense lines, **only when every unit reports that line with the
  same definition**. Quick exposes NOI only, so a portfolio containing a Quick
  unit has no consolidated revenue line (P-9).
- Recurring reserve_y, TI_y, LC_y, Property Cash Flow_y.
- Project Capital_y and Owner Expenses_y (unit + investment-level),
  Unlevered Owner Cash Flow_y.
- Acquisition-loan debt service_y, Levered Owner Cash Flow_y.
- Unlevered Project Cash Flow_t, Equity Cash Flow_t (after investment-level
  channels).
- Closing uses and sources: purchase price (allocated), acquisition costs,
  financing fees, closing project capital, investment-level transaction costs,
  loan amount, initial equity.
- Remaining loan balance at H, exit NOI, gross exit value, disposition costs,
  net sale proceeds. These are valid **only at the common exit date** (CON-1).
- Post-hold project capital (disclosure).
- **Total Profit.** It equals the sum of all Equity Cash Flow periods, so it is
  additive.

### 9.3 Derived after consolidation (never averaged)

Each is computed **from the consolidated series or totals**, with the existing
`anchor.engine.returns` functions wherever one exists (P-3):

| Metric | Derivation |
|---|---|
| Unlevered / Levered IRR + `IrrStatus` | `evaluate_irr` on the consolidated series |
| TEI, TCR | From the consolidated Equity Cash Flow. **Not additive:** one unit's negative year can offset another's positive year. |
| Equity Multiple | Consolidated TCR / TEI |
| Net Additional Equity Requirement_y | `max(-consolidated ECF_y, 0)`. **Not additive**, for the same reason. |
| Aggregate DSCR_y, min, headline | Consolidated NOI_y / consolidated acquisition-loan DS_y. Labeled "Aggregate DSCR". |
| Year-1 debt yield | Consolidated NOI_1 / consolidated loan amount |
| Going-in cap rate | Sum of NOI_1 / sum of allocated purchase price |
| Implied exit cap | Sum of exit NOI / sum of exit value. Reporting only, labeled *implied*; never an input. |
| Cash-on-Cash_y, Cash Yield_y | Consolidated owner cash flow / the consolidated D6 §8 basis |
| Occupancy, rent / sf | Area-weighted: sum of occupied or rent / sum of area, over units with area data. **N/A unless every unit has area** (§21 Q11). |

### 9.4 Not meaningfully consolidated (never shown as an investment metric)

- Averages or sums of unit IRRs, EMs, DSCRs, cap rates or occupancies.
- The minimum of unit minimum DSCRs *presented as the investment DSCR*. It may
  be shown only as a separately labeled "Lowest unit DSCR", which is a
  legitimate per-loan covenant view.
- Quick's informational `occupancy` scalar, which has no area.
- Values at different dates.
- A unit's IRR status reason as the investment's.
- Unit sensitivity or break-even results. Investment-level sensitivity re-runs
  the consolidated variant.

### 9.5 Deferred: unit sale before the horizon

A component or asset sale in year `k < H` ("sell the retail") is a legitimate
Strategy. Its convention would be: the unit's series stops at `k`, its exit is
realized in `k`, and it contributes zero afterwards. That is additive on cash
flows, but it makes values and exit NOI non-contemporaneous. It needs its own
ratified convention and is **not** in the first multi-unit gate (§21 Q9).

### 9.6 Identities every consolidation gate must test

- Each additive consolidated series equals the canonical-order sum of the unit
  series, plus or minus the investment-level channels.
- Consolidated Total Profit equals the sum of consolidated ECF, which equals
  consolidated TCR minus TEI.
- A one-unit Investment with no investment-level inputs reproduces that unit's
  `AcquisitionResults` exactly, series by series and metric by metric.
- **Allocation invariance.** With uniform unit terms (the same cost
  percentages and LTV) and investment-level financing, consolidated results
  are invariant to the purchase-price allocation.

---

## 10. Business Plan Scope

D6's Business Plan economics are ratified and unchanged. P7 **reuses the D6
authority** and adds no capital-plan engine.

| Layer | Contract | Resolved by | Enters |
|---|---|---|---|
| Unit plan | the unit's `BusinessPlan` (unchanged) | `resolve_business_plan` (unchanged) | that unit's engine run, exactly as today |
| Investment-level plan (shared costs) | a `BusinessPlan` owned by the Investment: **same contract, same validator, same resolver**, its own item-ID namespace | `resolve_business_plan` for the investment horizon `H` | consolidation only (the one new subtraction site per channel) |

Rules:

- **BP-1 Single-deal compatibility.** A standalone deal's plan behaves exactly as
  in D6. The empty investment-level plan adds nothing, to consolidation or to
  any fingerprint (the D11 pattern).
- **BP-2 No allocation of shared costs.** Investment-level items are never
  pushed into unit plans. Allocating them would distort every unit's
  standalone returns with an arbitrary key. Unit results exclude them;
  consolidated results include them once.
- **BP-3 No double counting.** An item lives in exactly one plan. D6's one
  subtraction site per channel extends to one site per channel *per layer*:
  - the unit engine subtracts unit items;
  - consolidation subtracts investment items;
  - no layer subtracts the other's.
- **BP-4 Closing investment-level capital** (`month = 0`) raises the
  consolidated Initial Equity Requirement and unlevered basis, never a loan.
  That mirrors D6 §4.
- **BP-5 Scenarios act on resolved plans** (plan-wide targets, §7.3).
  **Strategies replace whole plans** (§7.4).
- **BP-6 Fingerprints.** A unit plan stays in the unit fingerprint (D6.5,
  unchanged). A non-empty investment plan enters the investment fingerprint
  (§15.4).
- The existence of an investment-level plan is itself a new calculation site
  and needs ratification (§21 Q7). The rejected alternative (forced
  allocation into unit plans) is in the decision record.

---

## 11. Purchase Price, Basis and Valuation Timepoints

### 11.1 Price and allocation

| Term | Meaning | Financial effect |
|---|---|---|
| Transaction price | The one price negotiated for the whole Investment (an investment-level input). | Validation and reporting only. |
| Allocated unit price | The unit's `AcquisitionTerms.purchase_price`: the **underwriting allocation**. | Drives the unit's loan (`LTV x price`), its acquisition costs, going-in cap and unlevered basis. Exactly today's semantics. |
| Seller / tax allocation | An optional per-unit reporting figure from the purchase agreement. | **None** until tax modeling exists (D6 §21 defers tax). |
| Unit value | A valuation output at a timepoint (§11.3). | Reporting. Only the exit event produces cash. |

- **PP-1 One engine allocation.** The engine sees exactly one price per unit:
  the underwriting allocation. It may differ from the seller allocation.
- **PP-2 Conservation.** The sum of allocated unit prices must equal the
  transaction price within a documented absolute tolerance (§21 Q6). Otherwise
  the Investment is invalid, with an explicit reason. It is never silently
  rescaled. The consolidated purchase price reported is the sum of the
  allocations, which is the engine truth.
- **PP-3 No double counting.** The transaction price is never added to the unit
  prices, and never enters a cash flow on its own.
- **PP-4 Analyst-entered allocation.** Anchor does not invent an allocation
  (for example pro-rata by NOI) unless a later gate ratifies a deterministic
  helper.

### 11.2 Acquisition costs

| Cost | Representation | Treatment |
|---|---|---|
| Unit-level percentage costs | `acquisition_cost_pct` on the unit's terms (existing) | Applied to the allocated price. Equity-funded, in the unit basis (unchanged). |
| Investment-level fixed transaction costs (portfolio legal, one closing) | A new investment-level closing use (§21 Q8) | Equity-funded, in the consolidated unlevered basis and Initial Equity Requirement. Not allocated to units. Never a loan driver. |
| Allocated costs | Not supported | Would double-count with unit percentages. Rejected. |

### 11.3 Valuation timepoints

D6 exit semantics stay intact: the exit value is exit NOI (the forward year)
divided by the exit cap, and it is **the only valuation that produces cash**.

```
ValuationTimepoint
  timepoint_id, label          ("As-Is", "Stabilized", "Refinance", ... arbitrary)
  model_year                   end of hold year y, 0..H (0 = closing)
  per-unit method:
    DIRECT_CAP(cap_rate)       forward NOI after the timepoint / cap_rate
    ANALYST_VALUE(amount)      an explicit value with provenance
```

- **VT-1 Always tied to a model year.** A valuation is a statement about a
  date. Forward NOI after year `y < H` is the existing `noi_by_year[y]`; at
  `y = H` it is `exit_noi`. No new projection is needed.
- **VT-2 Units may stabilize at different years.** "Stabilized" is a label the
  analyst assigns per unit. It is not auto-detected; an occupancy-threshold
  rule would be a new convention.
- **VT-3 Consolidated value** at a timepoint is the sum of unit values only
  when every unit has a value at that same model year. Otherwise it is
  reported incomplete (P-9).
- **VT-4 Timepoints never produce cash.** Sale proceeds come only from a
  disposition event (the exit, or a ratified unit-sale event, §9.5), so
  they cannot be double-counted. A refinance *uses* a valuation to size debt
  (§12.5), and the cash effect belongs to that financing event.
- **VT-5 Direct cap and explicit value coexist per unit and per timepoint.**
  The method is recorded; neither overrides the D6 exit.

---

## 12. Capital Structure Boundary

### 12.1 Principle

Property and Business Plan economics determine the **cash available**. Capital
Structure determines the **source** of capital, its priority, its contractual
payments and repayment, and each investor position's economics. It **never**
changes NOI, Project Capital, Owner Expenses, exit value or disposition costs
(P-4).

### 12.2 Position contract (small core, typed terms)

```
CapitalPosition
  position_id        stable, opaque
  name
  position_class     SENIOR_DEBT | MEZZANINE_DEBT | PREFERRED_EQUITY | COMMON_EQUITY
  priority           explicit integer rank within its scope; unique; lower = senior
  scope              UNIT(unit_id) | INVESTMENT
  funding            amount rule + timing
                       amount: FIXED(amount) | PCT_OF_PRICE(pct) | PCT_OF_VALUE(timepoint, pct)
                       timing: at closing (P7); scheduled draws (contract-ready for Phase 8)
  terms              exactly one typed variant, chosen by position_class:
                       DebtTerms:            rate, amortization, io_period, maturity_year,
                                             origination_fee_pct, exit_fee_pct,
                                             current_pay_rate, pik_rate
                       PreferredEquityTerms: preferred_rate, current_pay_rate,
                                             accrual (compounding convention),
                                             redemption_year, participation (later)
                       COMMON_EQUITY:        no terms at this layer (Partnership, §13)
```

- **CS-1 No mega-union.** Floating rates, sculpted amortization, cash sweeps,
  cash traps, recourse, cross-collateralization and extension options are
  separate later term variants, each with its own ratified convention.
  Structural metadata (recourse, guarantees) may be stored as reporting-only
  notes.
- **CS-2 Class names** follow the codebase `StrEnum` convention (upper-case
  members, lower-case wire values, for example `"senior_debt"`). Names are
  ratified in the capital-structure gate.

### 12.3 Scope and structural subordination

- **CS-3 One scope mechanism.** `UNIT(unit_id)` or `INVESTMENT`. There is no
  portfolio-specific debt engine.
- **CS-4 Structural subordination.** Unit-scoped positions are paid from that
  unit's cash. Investment-scoped positions are paid only from cash that has
  cleared every unit-scoped position of every unit (property-level mortgages
  are senior to holdco mezzanine or preferred equity). Within a scope,
  `priority` orders payment.
- **CS-5 Investment-scoped senior debt** (a cross-collateralized portfolio
  loan) is allowed only when the units carry no acquisition loan (`ltv = 0`).
  Otherwise it is refused, so one dollar is never financed twice.
- **CS-6 Cash available.**
  - A unit-scoped junior position reads the unit's Levered Owner Cash Flow_y
    and Net Sale Proceeds (after the acquisition loan).
  - An investment-scoped position reads the consolidated equivalents after
    every unit-scoped position and the investment-level channels.
  - At closing, junior funding reduces the common equity required; junior
    fees are closing uses.
- **CS-7 Shortfall convention.** When cash is below a contractual current
  payment:
  - debt current pay is paid in full, and the shortfall is funded by common
    equity. It appears as negative common equity cash flow and NAER, exactly
    as a negative Levered Owner Cash Flow is equity-funded today;
  - preferred equity accrues its unpaid preferred return per its terms.
  - Ratification: §21 Q12.
- **CS-8 Period.** Annual periods, aligned to the existing annual cash-flow
  series. Monthly accrual is later (§21 Q13).

### 12.4 Existing debt engine: migration

**Recommendation: facade + read-only adapter** (§22.5).

- The unit's `AcquisitionTerms` loan stays exactly as it is: the **acquisition
  loan**, computed by the existing `debt.py` and reported in
  `AcquisitionResults`. A one-loan deal needs nothing new and stays simple.
- The capital-structure layer reads the acquisition loan through an adapter,
  as that unit's priority-1 `SENIOR_DEBT` position. The adapter's cash flows
  are **read off `AcquisitionResults`** (`loan_amount`, `financing_fee`,
  `annual_debt_service`, `remaining_loan_balance`), never recomputed.
- New debt positions (junior, or investment-scoped senior) reuse `debt.py`'s
  pure functions (`calculate_monthly_debt_service`,
  `calculate_annual_debt_service`, `calculate_remaining_loan_balance`,
  `calculate_amortization_schedule`) through thin wrappers. `debt.py` stays
  byte-identical, and no debt formula is duplicated.
- **Parity oracle (required).** A variant whose capital structure is only the
  acquisition loan must produce common-equity cash flow identical to
  `AcquisitionResults.levered_cash_flows`, bit for bit, because the adapter
  passes it through. That makes the capital-structure layer provably neutral
  for every existing deal.

### 12.5 Refinance and recapitalization

A refinance is a **capital event**, never revenue, NOI, Project Capital or sale
proceeds.

```
CapitalEvent (REFINANCE)
  event_id, year k (end of hold year k), sequence (explicit, for same-year events)
  retires            position_ids repaid at k (balance at k from the existing
                     amortization functions)
  new_position       a CapitalPosition funded at k
  sizing             FIXED | PCT_OF_VALUE(timepoint k) | later: DSCR / debt-yield constrained
  costs              fees and reserves funded at k
```

- At `k`: new proceeds, less the retired balances, fees and reserves, flow to
  common equity. The result is a distribution, or a contribution if it is
  negative.
- After `k`, the new position's debt service replaces the old.
- At `H`, net sale proceeds use the new position's balance.
- NOI, Project Capital, the exit value and the Owner Cash Flow chain above debt
  service are untouched.
- Refinance proceeds are excluded from Cash-on-Cash and the recurring
  owner-return series. The owner return metrics v3 convention already
  excludes them.
- A recapitalization (a new equity partner buying in, a pref injection) is the
  same event shape with an equity position. It is sequenced after
  refinancing (§19).

### 12.6 Position economics

The Capital Structure results give each position:

- a cash-flow series (funding negative, receipts positive);
- IRR (`evaluate_irr`), MOIC, profit;
- for debt and preferred positions: coverage through the position (NOI /
  cumulative debt service through that priority), debt yield through the
  position, attachment and detachment LTV against a stated valuation basis,
  last-dollar basis (the cumulative balance through the position), and the
  balance at maturity or exit.

These are **position returns**, a namespace distinct from project returns (§14).

---

## 13. Partnership Boundary

### 13.1 Flow

```
PROPERTY / BUSINESS PLAN  ->  CAPITAL STRUCTURE  ->  COMMON EQUITY CASH FLOW
  ->  PARTNERSHIP WATERFALL  ->  PARTNER CONTRIBUTIONS / DISTRIBUTIONS  ->  PARTNER RETURNS
```

The input is the variant's **Common Equity Cash Flow** series. With no
structured positions, that is exactly today's `AcquisitionResults.levered_cash_flows`,
or the consolidated ECF for an Investment. Partnership therefore **does not
depend on structured debt** and can ship first (§19).

### 13.2 Contract

```
Partnership
  partners[]            Partner{ partner_id, name, role (LP | GP | CO_INVESTOR: reporting only),
                                 commitment_share }          shares sum to 1
  contribution_rule     PRO_RATA_BY_COMMITMENT (P7); later: GP-funds-overruns, fixed amounts
  tiers[]               WaterfallTier (ordered by explicit `sequence`)

WaterfallTier
  tier_id, sequence     explicit, unique; economic order
  kind                  HURDLE | CATCH_UP | RESIDUAL
  hurdle (HURDLE)       conditions: [ IRR(rate, compounding) | MOIC(multiple) ]
                        combinator: ALL (the later of) | ANY (the earlier of)
                        basis: the partner set whose capital accounts measure it
                               (default: every partner, pro rata)
  split                 { partner_id: share }  sums to 1;  or PRO_RATA_BY_CONTRIBUTION
  catch_up (CATCH_UP)   recipient, catch-up rate, target share of cumulative profit
```

That is three tier kinds. They are the smallest coherent set and they represent
the whole required range:

| Structure | Tiers |
|---|---|
| Pari passu | one `RESIDUAL`, pro rata |
| Return of capital | `HURDLE` MOIC(1.0x), pro rata |
| Simple or accrued preferred return | `HURDLE` IRR(r) with `SIMPLE` or `ANNUAL` compounding |
| IRR hurdles / tiered promote | successive `HURDLE` IRR tiers with changing splits |
| MOIC hurdles | `HURDLE` MOIC(m) |
| "Greater of 1.5x or 12%" | `HURDLE` [MOIC 1.5, IRR 12%], `ALL` |
| "Lesser of ..." | `ANY` |
| GP catch-up | `CATCH_UP` |
| Residual split | `RESIDUAL` |

### 13.3 Calculation convention (designed now, implemented in the waterfall gate)

- **PW-1 Hurdle accounts, not IRR root-finding.** Each hurdle keeps a capital
  account per basis partner:
  `balance_t = balance_(t-1) x (1 + r) + contributions_t - distributions_t`.
  Simple compounding accrues on outstanding capital only; MOIC accounts are
  `m x cumulative contributions - cumulative distributions`. A tier
  distributes until its accounts reach zero.
  - This is deterministic, it never meets D10's multiple-root problem, and on
    annual periods it is exactly equivalent to "partner IRR = r when the tier
    binds". That gives the waterfall gate a built-in oracle.
- **PW-2 Annual periods.** Common Equity Cash Flow is net annual, so each period
  is either a net contribution or a net distribution, and no intra-period
  ordering question arises. Monthly waterfalls are later.
- **PW-3 Conservation identities (required tests).**
  - Per period, the sum of partner contributions equals
    `max(-CECF_t, 0)` and the sum of partner distributions equals
    `max(CECF_t, 0)`.
  - The sum of partner profit equals common equity Total Profit.
- **PW-4 Promote earned** (reporting): GP distributions minus the distributions
  the GP would have received pro rata by its contribution share.

### 13.4 Contributions vs. D6 equity metrics (Part T)

- D6's **Net Additional Equity Requirement** stays an annual *project* funding
  need. It is never renamed.
- Only the Partnership layer turns funding needs into **partner capital
  contributions**:
  - `T0` initial equity and each NAER_y are allocated by the contribution
    rule;
  - this is the first place "capital call" is a legitimate term.
- The D6 prohibition on "capital call" (D6 §7) still holds everywhere outside
  Partnership results.

---

## 14. Project vs. Investor Returns

Three separate namespaces. None overwrites another, and each is its own result
contract, never fields appended to `AcquisitionResults`:

| Namespace | Contents | Contract |
|---|---|---|
| **Project returns** | Project levered and unlevered IRR, EM, TEI, TCR, Total Profit, NAER, DSCR, CoC (unit-level `AcquisitionResults`; consolidated `ConsolidatedResults`) | existing / consolidation |
| **Position returns** | Per `position_id`: IRR, MOIC, profit, coverage, attachment and detachment, last-dollar basis, **common equity IRR / EM after all positions** | capital structure |
| **Partner returns** | Per `partner_id`: contributions, distributions, IRR, MOIC, profit, promote earned | partnership |

- **NS-1** `AcquisitionResults.levered_irr` keeps its meaning: equity after the
  acquisition loan. When junior positions exist, the common equity IRR is a
  *different* field in position returns, and the UI never relabels one as the
  other.
- **NS-2** The AI payload carries each namespace in its own section, and the
  grounding forbids attributing an LP figure to the project, or the reverse.

### 14.1 Decision comparison and the Strategy x Scenario matrix (Parts U, V)

- **DC-1 Read-only (P-5).** The matrix displays Analysis Variant results. The
  decision package imports result contracts only, never an engine calculation
  module. That is the same boundary `anchor.deals` already keeps.
- **DC-2 Every cell is honest.** For each selected metric, a cell shows one of:
  - a value;
  - `N/A` with its deterministic reason (`IrrStatus`);
  - `Invalid variant` with its validation reason (SC-4, SC-5);
  - `Not applicable to this perspective`.

  A missing figure is never shown as zero or blank.
- **DC-3 Typed, result-aware perspectives.** The metric catalog depends on the
  investor's position. A debt investment is compared on position metrics;
  forcing a project IRR onto it would mislead.

| Perspective | Candidate metrics |
|---|---|
| `PROJECT` (unit or Investment) | Initial Equity Requirement, TEI, levered / unlevered IRR, EM, Total Profit, NAER by year, exit value, going-in cap, minimum DSCR, Year-1 debt yield |
| `POSITION(position_id)` | funded amount, IRR / yield, MOIC, profit, attachment / detachment, last-dollar basis, coverage through the position, balance at maturity or exit |
| `PARTNER(partner_id)` | contributions, distributions, IRR, MOIC, profit, promote earned |

  A matrix has one perspective. A metric the perspective does not produce is
  never shown.
- **DC-4 Horizons.** Variants with different hold periods are compared only on
  horizon-independent metrics (IRR, EM, Total Profit, TEI). Annual rows are
  never aligned across different horizons (ST-5).
- **DC-5 Cross-cell figures** are computed by the backend comparison module from
  already-computed results, and each records the source fingerprints of the
  cells it read. That covers a delta vs. Base, the worst case across scenarios
  and a range. The frontend no-arithmetic guards and the AI rule against
  derived deltas stay in force.
- **DC-6 No expected value.** There is no probability weighting across scenarios
  (Q19).
- **DC-7 Currency.** A cell is current iff its source fingerprint matches its
  resolved inputs (§15.4). Stale cells are marked stale and never silently mixed
  with current ones.

---

## 15. Fingerprints, Persistence and Migration

### 15.1 Defaults and opt-in (Parts Z, AA)

| An analyst who... | ...gets |
|---|---|
| underwrites one deal (Quick / Detailed / Lease-Level) | exactly today's product. No Investment, strategy, scenario, capital structure or partnership exists, in storage or in the UI. |
| adds a first Scenario or Strategy to a standalone deal | a **hidden one-unit Investment** materialized in storage. The UI still says "Deal", and the scenario columns appear beside the results. |
| adds a second unit | the Investment becomes visible, with units listed by kind |
| adds structured capital or a partnership | the corresponding Strategy domain on the Investment |

- **Base** strategy and **Base** scenario are implicit, reserved and never
  stored as rows.
- One owner type (Investment) for scenarios, strategies, capital structure and
  partnership avoids dual ownership (deal-owned *and* investment-owned
  scenarios) and any later migration between the two.

### 15.2 Persistence (additive, schema v8+)

New tables are created via `CREATE TABLE IF NOT EXISTS`. There is no `ALTER` of
any legacy table, and no legacy row is read-and-rewritten. They are mode-blind,
keyed by stable IDs, and child rows are deleted explicitly, all following the
v5-v7 precedent. Indicative only; each gate owns its exact schema:

- `investments`: id, name, transaction price, memo fields, timestamps.
- `investment_units`: investment_id, unit (deal) id, ordinal (presentation),
  label, `unit_kind`.
- Investment-level plan items: the D6 tables' shape, keyed by investment id.
- `scenarios`, `scenario_overrides`.
- `strategies` and one typed table per strategy domain.
- `capital_positions`, `capital_events`, `partners`, `waterfall_tiers`.
- `variant_snapshots`: root_id, strategy_id, scenario_id, snapshot,
  schema_version, source_fingerprint, generated_at. This is the
  `deal_sensitivity_snapshots` pattern.

Lifecycle:

- Deleting an Investment deletes its structure rows. Whether it also deletes or
  releases its units is §21 Q3.
- Duplicating an Investment duplicates its units and structure.
- Deleting a unit that belongs to an Investment requires removing it from the
  Investment first. It is never silently orphaned.

### 15.3 Compatibility (Part AB)

Every existing saved deal:

- reopens unchanged, because its tables are untouched;
- analyzes through the same entry points;
- keeps its fingerprint byte for byte (§15.4);
- keeps its analysis, AI and sensitivity snapshots valid;
- needs no user migration;
- acquires no new economics, because every P7 default is neutral.

Each P7 gate that touches the engine path carries a **neutral oracle** against
`0593baa`, following the D6.2, D6.4 and D6.9 oracle precedents: with no P7
structure present, every legacy-visible response is bit-identical.

A P7 AI gate that changes the AI context bumps the AI snapshot schema. As at
D6.8, that invalidates every stored AI report, which is a known and accepted
cost to be stated in that gate.

### 15.4 Fingerprint hierarchy

**Key idea: fingerprint the resolved inputs, not the recipe.** A variant's
source fingerprint is the *existing* per-unit fingerprint function applied to
the unit's **resolved** contracts (after strategy and scenario). Consequences:

- **Base x Base = today's fingerprint, exactly** (D11 preserved by
  construction, since no overrides means identical resolved inputs).
- Any two variants that resolve to identical inputs share a fingerprint. That
  is correct, because they produce identical numbers.
- **Exact semantic revert is automatic.** Removing an override restores the
  resolved inputs, and so the fingerprint.
- A base edit invalidates every dependent variant, because its resolved
  inputs change.

| Level | Persisted? | Composition |
|---|---|---|
| Unit fingerprint | Yes (existing) | unchanged `fingerprint_{quick,detailed,lease_level}_inputs` |
| Variant source fingerprint | Yes, on `variant_snapshots` | per unit: the unit fingerprint of the resolved inputs. For an Investment: a hash over the (unit_id, resolved unit fingerprint) pairs sorted by unit_id, the investment plan (only when non-empty), the transaction price and investment costs, the resolved capital structure (canonicalized by scope then `priority`), and the resolved partnership (partners by `partner_id`, tiers by `sequence`) |
| AI fingerprint | Yes (existing pattern) | f(variant source fingerprint, narrative context: deal context, memo, scenario and strategy names) |
| Strategy / Scenario fingerprint | **No** | They are ingredients. Snapshot validity comes from the resolved-input fingerprint. They may be computed for debugging. |
| Decision comparison fingerprint | **No** | Derived as a hash of its cells' source fingerprints. The matrix is current iff every cell is current. |

- **FP-1 Names and descriptions** of scenarios and strategies are excluded from
  financial fingerprints, because they never reach a calculation. They are
  included in the AI fingerprint, because the AI reads them (§21 Q15). This
  differs deliberately from D6 plan-item descriptions, which live *inside* an
  engine input contract.
- **FP-2 Empty adds nothing.** An absent investment plan, capital structure or
  partnership adds no key (the D11 pattern).

### 15.5 Order semantics (Part AD)

| Order-irrelevant: canonicalize by stable ID | Order-significant: an explicit rank field; canonicalize by it; duplicates refused |
|---|---|
| Units in an Investment (consolidation sums in unit_id order, CON-3) | Capital position `priority` within a scope |
| Scenario overrides (unique per `(unit_id, target)`, SC-1) | Waterfall tier `sequence` |
| Strategy overlays (unique per domain and scope) | Capital events: `year`, then explicit `sequence` |
| Scenarios and strategies as lists (presentation) | Funding draws: `month` (Phase 8) |
| Partners (by `partner_id`) | |
| Business Plan items, suites, leases (existing) | |

Rule (P-7): economically meaningful order is never inferred from list position.
Reordering a presentation list never changes a fingerprint. Changing a rank
field always does.

---

## 16. AI Boundary

### 16.1 Permanent principle

Documents / Data -> Proposed Inputs -> Analyst Approval -> Deterministic Engine
-> Decision Support.

| AI may | AI may not |
|---|---|
| extract and normalize case documents into *proposed* inputs, scenarios and terms | silently select, or approve, any financial assumption |
| compare supplied variant results in prose | compute a delta, ranking statistic or worst case that the backend did not supply |
| explain drivers, risks and structural protections | calculate waterfall allocations, position returns or consolidated economics |
| draft IC memo language and qualitative risk lists as proposals | fabricate a scenario or a cell result |

### 16.2 Qualitative decision support (Part W)

An **Investment Memo** belongs to the Investment. A standalone deal keeps its
`deal_context`, and an optional memo materializes the hidden Investment. Each
Strategy may carry notes. Fields:

- thesis;
- key risks, each with mitigants;
- structural protections;
- execution complexity (an analyst rating);
- return-on-time notes;
- reputational concerns;
- dealbreakers;
- terms, grouped as required / desired / negotiable.

Rules:

- The memo is analyst-authored and authoritative.
- AI drafts go through the Analyst Approval Gate pattern already used for OM
  ingestion: proposed, then accepted or edited.
- The memo never enters a financial fingerprint. It enters the AI fingerprint
  (the `deal_context` precedent).

### 16.3 Assumption provenance (Part X)

P7.0 implements no citation system. It ensures one stays possible:

- **PV-1** Every addressable input has a stable identity: entity ID plus a
  field token from the target registry or the contract field name (P-8).
- **PV-2** A future `AssumptionSource` sidecar, keyed by (entity, id, field),
  records a source kind and a reference:
  - source kinds: `CASE_DOCUMENT`, `RENT_COMP`, `SALES_COMP`,
    `BROKER_RESEARCH`, `ANALYST_ASSUMPTION`, `IMPORTED_MODEL`,
    `AI_EXTRACTED_APPROVED`;
  - reference: document anchor, snippet or note.

  It reuses the existing ingestion Provenance / Evidence Status vocabulary.
- **PV-3** Provenance never enters a financial fingerprint, because changing a
  source changes no number.

---

## 17. Competition Acceptance Archetypes

### 17.1 Use of cases

Historical cases become **fixtures, acceptance matrices and QA scenarios**:
generically named files under `tests/fixtures/`, with independently prepared
expected values (hand or spreadsheet oracles for consolidation and waterfalls).
They never become production branches.

### 17.2 Stress test of the generic architecture

| Archetype | Representation | Needs |
|---|---|---|
| A. Single-asset acquisition | one Deal, today | nothing new |
| B. Mixed-use / component valuation | Investment + component Units (any modes), consolidation, investment-level loan | units, consolidation, investment-scoped position |
| C. Multi-asset portfolio | Investment + property Units, per-unit acquisition loans, allocation | units, consolidation |
| D. Structured capital | the property variant + `CapitalPosition`s; the decision perspective is a position | capital structure, position returns |
| E. JV / waterfall | Common Equity CF -> `Partnership` tiers | partnership |
| F. Alternative business plans | Strategies (`BUSINESS_PLAN`, `OPERATING_OUTCOME`, `DISPOSITION`) | strategies |
| G. Uncertainty | Scenarios with the §7.3 targets | scenarios |

### 17.3 Required acceptance fixtures (generic names)

1. `mixed_use_structured_capital`: three or more component units, an
   investment-level senior loan plus a mezzanine or preferred position,
   Base / Downside / Upside, and a position perspective.
2. `portfolio_property_debt_jv`: three or more property units, per-unit
   mortgages, allocation, an LP / GP waterfall with a preferred return,
   catch-up and two promote tiers.
3. `lease_level_value_add`: one Lease-Level unit, a Business Plan, two
   strategies, three scenarios.
4. `redevelopment_alternative_use`: in P7, a lease-as-is vs. a
   renovate-and-reposition strategy using existing modes (a Lease-Level
   lease-up via initial vacancy plus project capital). Full ground-up
   development waits for Phase 8.
5. `stabilized_acquisition`: one Quick or Detailed deal, unchanged. It is the
   neutral regression anchor.

---

## 18. Competition-Ready Definition

**ANCHOR COMPETITION READY** means: an analyst can take an unseen case of any
archetype in §17.2 (except ground-up development), build it in Anchor from the
case documents in a working session, and defend a recommendation. That defense
rests on deterministic, persisted, oracle-verified comparisons of strategies
under scenarios, from the perspective the case asks for (project, position or
partner). Decision capability matters, not feature count.

| MUST have (November) | SHOULD have | LATER |
|---|---|---|
| Quick / Detailed / Lease-Level units (exist) | Refinance / recap events | Development engine (Phase 8), construction loans, draws |
| Business Plan (exists) | Valuation timepoints (as-is / stabilized) | Floating rate, sculpting, sweeps, cash traps |
| Named Scenarios (typed overrides), any count | Sensitivity and break-even on any variant | Monthly waterfalls and monthly capital accrual |
| Strategies (acquisition, financing, plan, outcome, disposition) | Investment-level Business Plan and transaction costs | Staggered acquisitions, unit sales before the horizon |
| Strategy x Scenario matrix with IRR N/A reasons and invalid-variant reasons | Qualitative Investment Memo with AI-drafted proposals | Probability-weighted scenarios, Monte Carlo |
| Multi-unit consolidation (portfolio and mixed-use) with allocation conservation | Printable IC summary / institutional export | Tax, depreciation, seller-allocation tax effects |
| LP / GP waterfall: ROC, preferred return, IRR hurdles, catch-up, promote tiers, partner returns | AI grounding for positions and partners | Clawback, sponsor-fee routing, GP-funds-overruns |
| Senior + one junior position type (mezzanine **or** preferred) with position returns, attachment / detachment, last-dollar basis | Both junior types | Participations, kickers, recourse modeling |
| Reliable persistence and fingerprints for all of the above | Provenance sidecar (source per assumption) | Actual vs. budget, cash accounts |
| AI interpretation grounded on variant, position and partner results | | |
| All five §17.3 fixtures passing end to end | | |

---

## 19. Recommended Gate Sequence

### 19.1 Dependency analysis

- **Scenarios before multi-unit: yes.** Scenarios deliver value to every case
  immediately, on single deals, at the lowest risk. The override contract
  carries `unit_id` from day one, so multi-unit changes nothing in it.
- **Strategy is a gate of its own.** The hypothesis roadmap had no Strategy
  gate, but Strategy overlays are the other half of the matrix. They reuse
  the scenario resolution seam, so they are cheap directly after it.
- **Partnership does not depend on structured debt.** Its input is Common
  Equity Cash Flow, which today is `levered_cash_flows`. It can ship before
  Capital Structure and still serve Archetype E fully.
- **Capital Structure needs unit scope only for investment-scoped positions.**
  The scope field exists from its first gate. Placing it after multi-unit
  avoids re-opening it.
- **Decision comparison arrives incrementally.** A scenario-only matrix (one
  strategy row) ships with the scenario UI, gains rows with strategies, and
  gains perspectives with positions and partners.
- **Persistence is split from engine work,** as in D6. Each Tier 1 domain gate
  proves the calculation over request-carried inputs before a Tier 2 gate
  persists it.

### 19.2 Proposed gates

| Gate | Scope | Tier |
|---|---|---|
| P7.1 | Scenario engine: contracts, target registry (§7.3), resolver, variant analysis for all three modes over request-carried scenarios, neutral oracle vs. `0593baa` | 1 |
| P7.2 | Investment shell (hidden one-unit), scenario persistence, `variant_snapshots`, resolved-input fingerprints, API | 2 |
| P7.3 | Scenario UI + decision matrix v0 (scenario columns, one strategy row), `StrategyStrip` relabel if Strategy terminology surfaces | 3 |
| P7.4 | Strategy overlays: domains, resolution order, persistence, full Strategy x Scenario matrix | 1 (resolution) + 2 (persistence); matrix UI Tier 3 |
| P7.5 | Partnership waterfall: contracts, hurdle accounts, contributions, partner returns, conservation identities; UI | 1; UI Tier 3 |
| P7.6 | Multi-unit and consolidation: membership, allocation conservation, CON rules, investment-level plan and costs (if ratified) | 1 |
| P7.7 | Multi-unit persistence, API and UI | 2 / 3 |
| P7.8 | Capital structure: position core, acquisition-loan adapter + parity oracle, one junior class, position returns, attachment / detachment | 1 |
| P7.9 | Second junior class, refinance / recap events | 1 |
| P7.10 | Decision support: perspectives, robustness summaries (backend), Investment Memo, AI grounding for variants, positions and partners | 2 / 3 |
| P7.11 | Competition acceptance closeout: the five §17.3 fixtures, cross-feature QA, human acceptance | 1 closeout |

### 19.3 Two-week near-term objective (Part AI)

**P7.1 -> P7.2 -> P7.3**, and then P7.4 if velocity allows (Phase 6 closed nine
gates in two days). That yields a Strategy x Scenario matrix on any single deal.
It is the highest decision value per unit of risk, it applies to every archetype,
and all of it is permanent architecture. No temporary competition fork is
created.

### 19.4 Verification depth (Part AJ)

| Tier | P7 examples | Verification |
|---|---|---|
| 1 | scenario application, strategy resolution, consolidation, capital structure, waterfall, position and partner returns | focused and identity tests, neutral oracle vs. `0593baa`, parity oracle (capital structure), conservation identities (waterfall, consolidation), 1-5 mutants per invariant, one final full backend suite (and frontend when contracts change) |
| 2 | persistence, migrations, fingerprints, variant snapshots, API, AI grounding | round-trip and legacy-reopen tests, fingerprint revert and order-neutrality tests, browser E2E for save / reopen, one final relevant suite |
| 3 | scenario editor, decision matrix, investment UI | component and interaction tests, browser QA (1440 / 1280 / 390), frontend no-arithmetic guards, type / lint / build |
| 4 | copy (`StrategyStrip` relabel), docs | the source-text guardrails touched, build, visual review |

---

## 20. Deferred Scope

Not in Phase 7 unless a later ratification adds it:

- Development and construction (Phase 8): the construction period, budget
  and draws, construction loans, lease-up engine.
- Staggered acquisitions; unit sales before the horizon (§9.5).
- Monthly consolidation, monthly capital accrual, monthly waterfalls.
- Floating-rate debt, sculpted amortization, cash sweeps and traps,
  extension options, cross-collateralization mechanics.
- Participating preferred equity, kickers, clawback, GP-funds-overruns
  contribution rules, sponsor-fee routing to the GP.
- Probability-weighted scenarios and Monte Carlo.
- Item-addressed scenario overrides; suite-level scenario targets.
- Sensitivity and break-even on non-Base variants and on consolidated
  investments (a SHOULD in §18, not in the first gates).
- Tax, depreciation, seller-allocation effects.
- Automatic stabilization detection; automatic price allocation.
- Every item already deferred by D6 §21 that this document does not
  explicitly take up.

---

## 21. Open Questions Requiring Human Ratification

Every item below must be decided by a human before the named gate starts.

| # | Question | Recommendation | Gate |
|---|---|---|---|
| Q1 | Parent noun: `Investment`, `InvestmentCase` or `Case`? | `Investment` ("Case" collides with "Base case" and competition cases) | P7.2 |
| Q2 | Adopt Option A (existing `Deal` = Underwriting Unit, parent Investment over it)? | Yes | P7.2 |
| Q3 | May a unit belong to more than one Investment? When an Investment is deleted, are its units deleted or released? | At most one Investment. Deleting an Investment releases its units as standalone deals (nothing is lost) | P7.2 / P7.7 |
| Q4 | Hidden one-unit Investment materialized on first opt-in (§15.1)? | Yes | P7.2 |
| Q5 | Scenario operations `SET` / `ADD` / `SCALE` / `CAP_AT`, vs. absolute-only | The four operations, per-target allow-lists | P7.1 |
| Q6 | Allocation conservation tolerance (PP-2) | Absolute $0.01 on the wire value | P7.6 |
| Q7 | Investment-level Business Plan consumed in consolidation (a new subtraction site), vs. forced allocation | Investment-level plan, no allocation (BP-2) | P7.6 |
| Q8 | Investment-level fixed transaction costs as a new closing use | Yes, equity-funded, not allocated | P7.6 |
| Q9 | First multi-unit gate requires a common `T0` and `H` (CON-1); unit sales before the horizon deferred | Yes | P7.6 |
| Q10 | Lease-Level `market_rent_psf` `SCALE`: does it scale suite-level market-rent overrides too (a coherent worldview), or inherit the D4.6B shadowing refusal? | Scale property default and suite overrides together, with the rule stated in the registry | P7.1 |
| Q11 | Consolidated occupancy and rent / sf when a unit lacks area data | N/A (P-9), no partial coverage figure | P7.6 |
| Q12 | Capital shortfall convention (CS-7): debt current pay always paid and equity-funded; preferred equity accrues | Yes | P7.8 |
| Q13 | Annual periods for positions and waterfalls, monthly deferred | Yes | P7.5 / P7.8 |
| Q14 | Lease-Level variants: recompute (D5 decision A) or cache? | Recompute. Revisit only on measured latency | P7.2 |
| Q15 | Scenario and strategy names excluded from financial fingerprints, included in the AI fingerprint (FP-1) | Yes | P7.2 |
| Q16 | AGENTS.md engine-scope approval for each P7 calculation layer (the D6 D1 equivalent) | Record one approval per Tier 1 gate: P7.1, P7.4, P7.5, P7.6, P7.8, P7.9 | each |
| Q17 | Gate sequence §19.2 and the two-week scope §19.3 | As proposed | P7.1 |
| Q18 | MUST / SHOULD / LATER split in §18 | As proposed | P7.1 |
| Q19 | Scenario probabilities / weights | Out of Phase 7 | - |
| Q20 | Waterfall hurdle basis default (§13.2): all partners pro rata, vs. LP-only accounts | All partners pro rata; an explicit basis set when terms differ | P7.5 |
| Q21 | Preferred-return compounding default | `ANNUAL` compounding; `SIMPLE` available | P7.5 |
| Q22 | Robustness summaries (worst case, range across scenarios) computed in a backend comparison module | Yes, backend only; none in the frontend or AI | P7.10 |
| Q23 | Promote-earned reporting definition (PW-4) | As stated | P7.5 |
| Q24 | Strategy domain `OPERATING_OUTCOME` may `SET` UNCERTAINTY-class targets (strategy-conditional outcomes) | Yes | P7.4 |

Left to the named gate (implementation detail, no convention change):

- exact contract, module and enum names;
- exact table schemas and the schema version number;
- API payload shapes;
- the exact scenario target token list within §7.3;
- operational payload limits;
- the exact numerical golden cases.

---

## 22. Architecture Options Considered (Part AK)

### 22.1 Parent Investment vs. extending the current Deal directly

| Option | Benefit | Cost | Migration risk | Flexibility |
|---|---|---|---|---|
| **Parent `Investment` over Deals** | No existing contract moves; opt-in; one-unit analysis unchanged | A new membership table; "Deal" means unit in code | None (additive tables) | High: any number and mode of units |
| Extend `Deal` with investment fields | No new root entity | Every deal carries empty investment state; multi-unit still needs a second table | Medium: columns on 3 parent tables | Low: a deal still cannot contain deals |

**Recommendation:** a parent Investment.

### 22.2 Existing Deal as the Unit vs. new nested Unit contracts

| Option | Benefit | Cost | Migration risk | Flexibility |
|---|---|---|---|---|
| **Deal = Unit (Option A)** | Reuses every mode, persistence and fingerprint path; every existing guard test intact | Naming debt ("Deal" = unit) | None | High |
| New `Unit` contracts nested in `Investment` (Option B) | Clean names | Rewrites contracts, tables, fingerprints (legacy digests), API, web state | High: every saved deal migrates | High, but only after months of rework |
| `components[]` on Deal (Option C) | One record | Nested mode dispatch, per-component mode tables, fingerprint reshaping | High | Medium |

**Recommendation:** Option A.

### 22.3 Scenario snapshots vs. typed override model

| Option | Benefit | Cost | Migration risk | Flexibility |
|---|---|---|---|---|
| Full input snapshot per scenario | Trivially "what ran" | Silent divergence when base facts are corrected; cannot mean the same worldview across strategies | Low | Low |
| Untyped JSON patch | Anything is overridable | No domain rules, no operation semantics, reaches structural fields, weak audit | Low | Dangerous |
| **Typed override set over an approved registry** | Exact revert, cross-strategy coherence (SC-3), per-target validation, sensitivity precedent | Each new target needs an explicit registry decision | Low (additive) | High, and controlled |

**Recommendation:** the typed override set.

### 22.4 Strategy full-copy vs. compositional overlay

| Option | Benefit | Cost | Migration risk | Flexibility |
|---|---|---|---|---|
| Full Deal copy per strategy (today's Duplicate) | Maximally independent; debuggable | Base corrections do not propagate (silent divergence); scenarios must be kept in sync across copies; consolidation over copies is ambiguous | Low | Low |
| Field-level patch | Minimal storage | A strategy becomes an unreadable diff; incoherent partial packages | Low | Medium |
| **Domain-level overlay + resolved-input inspection (ST-2, ST-4)** | Coherent decision packages; one authority for shared facts; the resolved view gives debuggability | Resolution logic and an inspect endpoint | Low (additive) | High |

**Recommendation:** the domain-level overlay.

### 22.5 Current debt adapter vs. replacement debt engine

| Option | Benefit | Cost | Migration risk | Flexibility |
|---|---|---|---|---|
| Replace `debt.py` with a capital-stack engine | One general engine | Breaks the D5 / D6 bit-identity oracles and guards; re-derives mature math | High | High |
| Legacy loan as a separate parallel path forever | Simple | Two authorities for "the loan"; positions cannot rank against it | Low | Low |
| **Facade + read-only adapter, reusing `debt.py` pure functions for new positions** | The one-loan deal is untouched; a parity oracle proves neutrality; no formula duplicated | Adapter + parity tests | Low | High |

**Recommendation:** facade + adapter (§12.4).

### 22.6 Generic waterfall tiers vs. specialized structures

| Option | Benefit | Cost | Migration risk | Flexibility |
|---|---|---|---|---|
| Specialized structures ("American", "European", named templates) | Familiar | Each variant is new code; case-shaped | Low | Low |
| **Three-kind generic tiers (`HURDLE` / `CATCH_UP` / `RESIDUAL`) with conditions and a combinator** | Represents the whole required range (§13.2); hurdle-account math is uniform and oracle-able | A careful convention gate | Low | High |

**Recommendation:** generic tiers. Named templates may exist later as UI
presets that *produce* tier lists, never as engine branches.

---

## 23. Decision Record

None of these decisions is ratified. Every row awaits human ratification.

| Decision | Recommendation | Why | Alternative rejected | Needs human ratification? |
|---|---|---|---|---|
| Strategy vs. Scenario are separate concepts | Yes: decision vs. uncertainty, with the §7.6 edge rules | The matrix needs the same worldview across strategies | One merged "case" concept | Yes |
| Scenario representation | Typed override set over an approved registry (§7.2-7.3) | Exact revert, cross-strategy coherence, per-target validation | Snapshots; untyped JSON patch | Yes |
| Scenario operations | SET / ADD / SCALE / CAP_AT per target | Relative operations keep one worldview across strategies; CAP_AT models availability | Absolute-only | Yes (Q5) |
| Strategy representation | Domain-level overlays; Base = stored inputs | Coherent packages; base facts have one authority | Full copies; field patches | Yes |
| Analysis Variant | Analysis-layer identity; only results cached, by resolved-input fingerprint | Nothing to author on a variant | Persisted variant entity | Yes |
| Existing Deal relationship | Deal = Underwriting Unit (Option A) under an optional Investment | Zero migration; all Phase 6 guards intact | Nested rewrite (B); components on Deal (C) | Yes (Q2) |
| Parent noun | `Investment` | Avoids "case" collisions | `Case`, `InvestmentCase` | Yes (Q1) |
| Mixed-use and portfolio | One Unit / consolidation architecture; `unit_kind` is metadata | Identical financial semantics | Two architectures | Yes |
| Consolidation | Canonical-order sums for additive items; ratios derived from consolidated series; §9.4 list never shown | Averaging ratios is wrong; float order must be deterministic | Averaging unit metrics | Yes |
| Multi-unit timeline | Common T0 and H in the first gate, as validation not structure | Keeps additivity exact; Phase 8 can relax it | Padding or truncating series | Yes (Q9) |
| Price allocation | Analyst allocation in unit terms; conservation vs. transaction price; seller allocation is metadata | One engine price per unit; no double count | Auto-allocation; allocated costs | Yes (Q6) |
| Business Plan scope | D6 plan per unit + optional investment-level plan through the same resolver | Reuses the D6 authority; no forced allocation | Forced allocation; a second plan engine | Yes (Q7) |
| Valuation timepoints | Model-year timepoints, reporting only; the D6 exit is the only cash-producing valuation | No double-counted proceeds | Hardcoded as-is / stabilized fields | Yes |
| Financing scope | One scope mechanism (UNIT / INVESTMENT) with structural subordination | No portfolio debt engine | Separate portfolio debt path | Yes |
| Existing debt | Facade + read-only adapter + parity oracle | Keeps every one-loan deal bit-identical | Replacing `debt.py` | Yes |
| Refinance | A capital event; never revenue, NOI, capital or sale proceeds | Financing is below NOI | Modeled as a sale or as income | Yes |
| Partnership | A separate layer on Common Equity CF; three-kind tiers; hurdle accounts | Generic, oracle-able, independent of structured debt | Case-shaped templates; IRR root-finding | Yes (Q20, Q21) |
| Project vs. investor returns | Three namespaces, separate contracts | Never overwrite project fields | Appending LP / GP fields to `AcquisitionResults` | Yes |
| Capital call | Only as a Partnership contribution; D6 NAER unchanged | D6 §7 | Renaming NAER | Yes |
| Fingerprints | Fingerprint the resolved inputs; persist unit and variant (and AI) levels only | Automatic revert; Base x Base = legacy | A fingerprint per layer | Yes |
| Order semantics | Explicit rank fields for economic order; ID sort otherwise | Presentation never moves numbers | Inferring order from list position | Yes |
| Defaults | Implicit Base / Base; hidden one-unit Investment on opt-in | The simplest workflow stays simple | Always-visible wrappers | Yes (Q4) |
| AI boundary | Proposes and interprets only; no derived deltas or allocations | P-12 | AI-computed comparisons | Yes |
| Gate sequence | §19.2; the two-week scope is P7.1-P7.3 (+ P7.4) | Value per risk; Partnership has no structured-debt dependency | Hypothesis order without a Strategy gate | Yes (Q17) |
| Competition-ready | The §18 MUST / SHOULD / LATER split | Decision capability, not feature count | "Everything mandatory" | Yes (Q18) |

---

## 24. P7.0 Gate Record

- Authorized changes:
  - this document;
  - the re-pin of `test_x_d6_9_changes_only_authorized_production_files` to
    `9ba3383..0593baa`;
  - a new boundary test (`test_x_the_d6_9_ledger_boundary_is_the_phase_6_merge`);
  - `tests/test_p7_0_decision_architecture.py` (the anti-overfitting and
    document-structure guards).
- No production file (`src/anchor/**`, `web/src/**`), migration, API contract,
  financial calculation or UI changed.
- P7.1 must not begin until a human ratifies this document, or ratifies it
  with amendments.
