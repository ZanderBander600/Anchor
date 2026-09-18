# AM1 — Managed Assets and Monthly Performance

Status: Implemented and merged in PR #38 (`3048976`), pending human product acceptance
Gate: AM1
Started from: `main` at `63c2ac0`
Branch: `feature/am1-managed-assets-monthly-performance`
Schema: v12 → v13 (additive)
Risk tier: Tier 1 financial/contract critical, with Tier 2 persistence and
Tier 3 product behavior

AM1 is an independent post-acquisition feature. It is **not** P7.10, it is not
part of P7.10, and it does not advance the P7 competition sequence. P7.9 final
human acceptance remains pending and is unaffected by this gate.

---

## 1. Purpose and scope

### 1.1 The lifecycle AM1 completes

```
Acquisition Deal
  → approved acquisition basis
    → Managed Asset
      → monthly operating reports
        → actual performance versus the frozen approved budget
```

Anchor until now underwrote purchases. AM1 adds the other half: reporting on a
building the owner already holds. The two are different products over the same
asset, which is why Asset Management is a **separate primary workspace** rather
than another Deal workspace tab beside Underwrite, Risk and AI Analyst.

AM1 changes no acquisition, Capital Structure, Partnership or underwriting
calculation. Every one of those modules is consumed as-is or not consumed at
all.

### 1.2 Production ledger

Backend, exactly:

| File | Change |
| --- | --- |
| `src/anchor/asset_management/__init__.py` | new — package exports |
| `src/anchor/asset_management/contracts.py` | new — identity, inputs, errors, results |
| `src/anchor/asset_management/validation.py` | new — structural validation |
| `src/anchor/asset_management/performance.py` | new — **the sole financial authority** |
| `src/anchor/deals/store.py` | schema v13, two tables, the AM1 lifecycle |
| `src/anchor/api.py` | the eight AM1 routes |

Frontend, exactly:

| File | Change |
| --- | --- |
| `web/src/assetManagementTypes.ts` | new — wire contracts |
| `web/src/assetManagementFormat.ts` | new — formatting and labels only |
| `web/src/assetManagementFixture.ts` | new — the recorded engine response |
| `web/src/useManagedAssets.ts` | new — Asset Management state |
| `web/src/components/AssetManagementShell.tsx` | new — the separate workspace |
| `web/src/components/ManagedAssetWorkspace.tsx` | new — one owned asset |
| `web/src/components/MonthlyPerformancePanel.tsx` | new — the monthly view |
| `web/src/components/MonthlyReportEditor.tsx` | new — budget and actuals entry |
| `web/src/components/NoiTrendChart.tsx` | new — inline-SVG trend |
| `web/src/components/CreateManagedAssetPanel.tsx` | new — the Deal-side action |
| `web/src/api.ts` | AM1 client, appended |
| `web/src/App.tsx` | the primary workspace switch |
| `web/src/components/AppSidebar.tsx` | Acquisitions / Asset Management |
| `web/src/index.css` | AM1 styles |

`tests/test_am1_architecture.py` holds this ledger and fails if anything else
changed.

### 1.3 Re-pinned prior-gate guards

A schema bump moves version assertions that earlier gates pinned to their own
era. AM1 re-pins them exactly as P7.9 Stage 2 did when it bumped v11 → v12
(commit `82fd7ed`): the version literal advances and the comment names the new
gate's tables. No behavioural assertion was weakened, and nothing was deleted.

Version and table-inventory pins: `test_analysis_d4_5b_architecture.py`,
`test_d5_4_migration_and_fingerprint.py`,
`test_d5_8a_deal_analysis_persistence.py`,
`test_d6_5_business_plan_migration.py`,
`test_p7_2_scenario_persistence.py`, `test_p7_2_compatibility_oracle.py`,
`test_p7_4_strategy_persistence.py`, `test_p7_4_compatibility_oracle.py`,
`test_p7_6_investment_persistence.py`, `test_p7_6_compatibility_oracle.py`,
`test_p7_8b_capital_structure_persistence.py`,
`test_p7_9_stage_2_persistence.py`, `test_p7_9_stage_2_compatibility_oracle.py`,
`test_p7_9_stage_2_architecture.py`, and `_p7_2_fixtures.py` (which gains an
`AM1_TABLES` constant beside the existing per-gate ones).

Two guards needed a correction rather than a re-pin, because each measured more
than it claimed to:

- `test_d6_5_business_plan_persistence_architecture.py`'s inventory of
  plan-aware store calls gains AM1's two. The behavioural guard beside it
  (`test_the_store_threads_the_stored_plan_everywhere`) passed unchanged:
  `_deal_analysis_fingerprint` does pass `business_plan=` in every mode.
- `web/src/investmentArchitecture.test.ts`'s "P7.6 styles free of good / bad
  colour" check sliced the stylesheet from the P7.6 marker to **end of file**,
  so it silently covered every stylesheet appended after P7.6. It is now bounded
  to the P7.6 section it names. AM1's assessment column is meant to carry a
  favorable/unfavorable colour, and it is the first later gate to use a token
  that slice forbade.

One AM1 change was made in response to a guard rather than by re-pinning it:
`test_p7_9_stage_2_architecture.py`'s "api.py catches no `ValueError`" tripped on
two narrow `date.fromisoformat` guards AM1 had added. Rather than re-pin it, the
parsing moved into `asset_management.validation.parse_iso_date`, which reports a
malformed string by returning `None`. `api.py` is back to its original count and
that guard passes untouched — the right outcome, since every validation error in
the repository subclasses `ValueError` and a catch at the transport boundary is
one refactor away from swallowing a typed domain refusal.

---

## 2. The Managed Asset contract

### 2.1 What it is

A Managed Asset is an owned building. It is **not** a Deal: it has its own id,
its own name, its own lifecycle, and no acquisition assumption of any kind.

| Field | Meaning |
| --- | --- |
| `id` | server-generated, opaque |
| `source_deal_id` | provenance, not ownership |
| `name` | copied from the Deal at creation |
| `acquisition_date` | authored |
| `property_type` | optional; `None` is "not stated" |
| `market` | optional; `None` is "not stated" |
| `acquisition_fingerprint` | the Deal's authoritative analysis fingerprint, frozen at creation |
| `created_at` / `updated_at` | timestamps |

### 2.2 Rules

- A saved Deal creates **at most one** Managed Asset, enforced by
  `UNIQUE (source_deal_id)` in the database rather than by a check a future
  write path could forget.
- Creating the asset requires a current saved Deal analysis (see 2.3).
- The Deal's authoritative fingerprint is captured once, by
  `create_managed_asset`, and written by no other statement.
- Later Deal edits do not rewrite the asset, its budgets or its historical
  reports. The divergence between the Deal's current fingerprint and the
  asset's frozen copy is provenance the product may show — never a trigger to
  rewrite anything.
- The original Deal is never modified. No AM1 write path issues an `INSERT`,
  `UPDATE` or `DELETE` against `deals`, `detailed_deals`,
  `detailed_operating_inputs` or `lease_level_deals`.
- AM1 adds **no** general acquisition lifecycle or status model.
- A Managed Asset may be deleted only through the explicit asset-level
  workflow added after the initial AM1 merge. Deletion permanently removes the
  asset and all monthly reports it owns in one transaction, while leaving the
  source Deal and every acquisition-underwriting row unchanged. The product
  must name both consequences and require inline confirmation before sending
  the request.
- There is no independent monthly-report deletion workflow. A frozen report is
  removed only as a dependent of a deleted Managed Asset.

### 2.3 Resolution: the current-analysis requirement is mode-aware

**Decision.** Quick and Detailed Deals must have a current cached analysis
snapshot. Lease-Level Deals are exempt.

**Why.** `lease_level_deals` has no `analysis_snapshot` column at all — D5.4
gave that table family `ai_snapshot` only. A Lease-Level Deal therefore
*structurally cannot* carry a cached deterministic analysis, and applying the
check uniformly would bar an entire operating mode from Asset Management as a
side effect of an unrelated persistence gap, not because anything about its
basis is less trustworthy.

What AM1 actually freezes is the fingerprint, and
`_deal_analysis_fingerprint` produces one from a Lease-Level Deal's own stored
rows exactly as it does for the other two modes. A saved Lease-Level Deal
qualifies on the same evidence the other modes' snapshots stand on: assumptions
that are on file and reassemble into the contracts the engine consumes.

This is recorded as an explicit resolution because it is a real product
asymmetry, and it is pinned by
`test_lease_level_is_exempt_from_the_snapshot_check_by_storage_not_by_policy`.

---

## 3. Monthly report inputs

A report is identified by `(managed_asset_id, reporting_month)`. The month is
normalized to the **first day of the month** at every boundary, so two
spellings of March cannot become two rows that each freeze a different budget.

Each report carries an **Approved Budget** and **Actual Results**, each stating
all thirteen authored values:

occupancy, rental revenue, other income, property taxes, insurance, utilities,
repairs and maintenance, payroll, management fees, other operating expenses,
capital expenditures, debt service — plus optional management commentary.

### 3.1 Validation

- Every monetary value is **finite and non-negative**. Nothing is clamped or
  repaired: a clamp would put a number the analyst never entered into a frozen
  budget.
- Occupancy is a **fraction in `[0, 1]`**, matching the repository's existing
  occupancy convention (`anchor.validation`'s `0 <= value <= 1`). It is
  presented in percent and its variance in percentage points; both are display
  conversions, never a second stored scale.
- `True` is not a number. A boolean in a money field is refused.
- Commentary is optional. `None` is "none written"; a whitespace-only string is
  refused rather than stored.
- Every issue is reported in one round trip, in deterministic statement order,
  each naming its scope (`budget` / `actual`) and its exact field.

### 3.2 The frozen budget

The first save creates both the approved budget and the initial actuals. After
that:

- Budget fields are **immutable**.
- Actuals and commentary may be updated.
- A budget change attempt fails with a **typed conflict**
  (`BudgetImmutableError` → HTTP 409, code `budget_immutable`), naming every
  changed field.
- A budget is never silently replaced or revised.

**The conflict is deliberately not a validation error.** The submitted budget
may be perfectly well-formed; what is refused is the *authority* to change it.
A 422 would tell the product "fix these numbers", which is exactly the wrong
instruction. `BudgetImmutableError` subclasses `Exception`, not `ValueError`,
so a caller catching validation failures cannot swallow it.

**The freeze is structural, not merely checked.** `create_monthly_report` holds
the only statement that writes a `budget_*` column.
`update_monthly_report_actuals` names only `actual_*`, `commentary` and
`updated_at` in its `SET` clause — there is no SQL in the module capable of
revising a budget.

### 3.3 Budgets are entered, never derived

A monthly budget is always the budget the analyst explicitly entered. AM1 never
divides an annual underwriting result by twelve, and never implies that an
annual forecast is a monthly plan. The engine has no entry point that would
accept an annual figure, and
`test_no_monthly_figure_is_derived_from_an_annual_one` measures this over
executable code with docstrings stripped, so the explanation of the rule cannot
be what satisfies it.

---

## 4. The deterministic financial contract

**All calculations belong in Python.** `anchor.asset_management.performance` is
the sole authority. React formats and displays; it never calculates.

### 4.1 Totals

For both budget and actual:

```
total_revenue            = rental_revenue + other_income

total_operating_expenses = property_taxes
                         + insurance
                         + utilities
                         + repairs_and_maintenance
                         + payroll
                         + management_fees
                         + other_operating_expenses

net_operating_income     = total_revenue - total_operating_expenses
cash_flow_after_capex    = net_operating_income - capital_expenditures
net_cash_flow            = cash_flow_after_capex - debt_service
```

Capital expenditures and debt service are **not** operating expenses. Including
either would silently change NOI — the single most consequential way this
contract could be got wrong, and the subject of a dedicated mutation proof.

### 4.2 NOI margin

```
noi_margin = net_operating_income / total_revenue
```

When total revenue is zero, the margin is **unavailable** (`None`) — not zero
and not infinite. A zero margin would assert that the asset earned nothing on
revenue it did earn.

### 4.3 Variance

```
variance     = actual - budget
variance_pct = variance / abs(budget)
```

When the budget is zero, `variance_pct` is **unavailable**. The variance itself
is always present: the difference is well defined even when the ratio is not.

`abs(budget)` is deliberate — the percentage states how far actual landed from
plan as a share of the plan's magnitude, so its sign must come from the
variance alone. A signed divisor would flip the reported sign whenever the
budget was negative.

### 4.4 Assessment

| Lines | Positive variance | Negative variance | Zero |
| --- | --- | --- | --- |
| Revenue, occupancy, NOI, net cash flow | Favorable | Unfavorable | On plan |
| Each operating-expense line, and their total | Unfavorable | Favorable | On plan |
| Capital expenditures, debt service | Neutral | Neutral | Neutral |

`neutral` is a statement, not an absence: the line has no favorable direction
at all, which is why it is never confused with `on_plan` (a line that has a
direction and landed on it).

AM1 **never** infers that lower CapEx is favorable. Underspending CapEx is
deferred work, often the opposite of good news, and debt service is
contractual.

Direction is declared once, in `_LINE_DIRECTION`, and carried on every
`LineVariance` as `direction`, so the frontend never re-derives favorability
from a line's name — the one place that could quietly disagree with the engine.

**Resolution: `cash_flow_after_capex` is neutral.** The authorized assessment
rules name revenue, occupancy, NOI and net cash flow as directional and are
silent on this subtotal. It embeds capital expenditures, whose variance carries
no favorability at all, so giving it a direction would launder a neutral line
into a verdict. Net cash flow is explicitly authorized as higher-is-favorable
and keeps that. Where the contract is silent, AM1 does not infer.

### 4.5 Occupancy

Occupancy variance is reported in **percentage points**
(`variance_points`), on the percent line only. It is `None` on every currency
line — percentage points are not a thing a dollar line has.

### 4.6 Year to date

YTD monetary totals sum January through the selected reporting month, over the
saved reports of that calendar year. A month with no saved report contributes
nothing; it is never a zero month that would read as an asset earning nothing.

**Occupancy is not summed, and not reported year to date at all.** Three months
at 95% is not 285% occupancy, and no average is invented either. Rather than
report a meaningless number, the year-to-date line set omits occupancy
entirely, and the product says why.

### 4.7 Attention items

Derived **only** from deterministically unfavorable `LineVariance` values the
engine already computed. No model is consulted, no threshold is tuned, and no
favorable, on-plan or neutral line can appear. Each message states its
direction in words ("2.5 pts below plan", "$2,000 over budget"), so the item is
complete to a reader who cannot distinguish red from green.

### 4.8 Result contracts

`PeriodTotals`, `LineVariance`, `AttentionItem`, `NoiTrendPoint`,
`PeriodPerformance`, `AssetPerformanceResult`.

---

## 5. Persistence

### 5.1 Schema v13, additive

Two tables, created by `_connect` via `CREATE TABLE IF NOT EXISTS` exactly as
every table since version 2. `_migrate` records the version and touches no
existing row. A v12 database simply gains two empty tables.

### 5.2 `managed_assets`

Typed columns; `UNIQUE (source_deal_id)` enforces one asset per Deal.

### 5.3 `monthly_asset_reports`

`PRIMARY KEY (managed_asset_id, reporting_month)` enforces one report per asset
per month. `FOREIGN KEY (managed_asset_id) REFERENCES managed_assets (id)`.

Both statements are stored as **twelve typed `REAL` columns each**, prefixed
`budget_` / `actual_` — never a JSON financial blob. A figure is queryable,
typed, and cannot acquire a field no contract declares. The column list is
derived from `MONETARY_FIELDS` itself, so a field added to the contract is a
schema change the module notices at import rather than silently drops on write.

### 5.4 Nothing computed is persisted

No total, variance, percentage, assessment, attention item or trend point has a
column. Every one is derived on read by the engine.

### 5.5 Compatibility oracle

`tests/test_am1_compatibility_oracle.py` builds a real schema-v12 database from
`main` at `63c2ac0` (exported with `git archive` — objects only, no stash and no
second checkout, per protocol 11.1/11.2) holding Deals in all three operating
modes, a Business Plan, a visible Investment, a Scenario, a Strategy, a Capital
Structure and a Partnership. It proves:

- the v12 → v13 migration adds exactly two empty tables, alters nothing,
  rewrites no row, and is idempotent under repeated connections and a direct
  `_migrate` call;
- every response that tree recorded — including its refusals — is answered byte
  for byte identically;
- replaying every read writes nothing and materializes no Managed Asset.

---

## 6. API

| Method | Path |
| --- | --- |
| POST | `/managed-assets` |
| GET | `/managed-assets` |
| GET | `/managed-assets/{id}` |
| DELETE | `/managed-assets/{id}` |
| GET | `/managed-assets/{id}/reports` |
| GET | `/managed-assets/{id}/reports/{month}` |
| POST | `/managed-assets/{id}/reports` |
| PUT | `/managed-assets/{id}/reports/{month}` |
| GET | `/managed-assets/{id}/performance/{month}` |

Nine routes. The single DELETE is the bounded Managed Asset lifecycle action:
it removes the asset and its reports, never the source Deal. There is no DELETE
for an individual report.

Bodies use the repository's `_exact_keys` contract — every field is stated
explicitly, including the ones that are `null`, so nothing a request does not
say can be filled in from anywhere else. Responses use `_wire`. Refusals follow
the established contracts: 404 for a missing entity, structured 422 for a
contract refusal, 409 for a conflict.

**No AI endpoint and no paid AI call is part of AM1.**

---

## 7. Frontend

### 7.1 A separate workspace

The primary application-level distinction is Acquisitions / Asset Management,
in the dark navy rail, above every Deal workspace tab. Asset Management
replaces the whole shell rather than nesting inside it: sharing the
Acquisitions sidebar would keep New Deal, the Deal Library and every
underwriting entry point one click away while the analyst is reporting on a
building they already own.

Asset Management provides Portfolio Overview, Managed Assets, Monthly
Reporting, a managed-asset list, and an individual owned-asset workspace. The
asset workspace has **Overview** and **Monthly Performance**, and nothing else:
the concept's Business Plan, Debt & Covenants and Documents tabs are
deliberately absent, because AM1 renders no dead future tabs.

The acquisition appears only as quiet provenance, through **View Acquisition
Basis**. No Quick Underwrite, Detailed Underwrite, Analyze or other acquisition
control is reachable from inside Asset Management.

### 7.2 The monthly view

1. Summary cards: Net Operating Income, Occupancy, Operating Expenses, Net Cash
   Flow.
2. Actual-versus-budget table: Financial Line, Approved Budget, Actual,
   Variance, Variance %, Assessment.
3. Attention Required: explicit unfavorable items, in words as well as colour.
4. Management Commentary.
5. A restrained Budget NOI versus Actual NOI trend, **implemented as inline SVG
   with no charting dependency**. Its figures also appear in a visually hidden
   table, so a chart is never the only place a number exists.
6. Monthly and Year-to-Date views.

### 7.3 Presentation rules

- Numeric headers and values are both right-aligned, so a header edge and its
  digits share one edge; figures use `font-variant-numeric: tabular-nums`.
- `null` renders as an em dash — never `0`, never `N/A`.
- Negative figures use accounting parentheses.
- Colour is never the sole carrier of meaning: every assessment is also a word.
- On initial creation Budget and Actual are both editable. After saving, the
  budget column is rendered as read-only text — not a disabled input, because a
  locked budget is a figure of record rather than a field that happens to be
  unavailable.
- In-card horizontal scrolling is preserved on narrow screens, so the page
  itself never scrolls sideways. The 390px layout stacks rather than shrinking
  a desktop design.

### 7.4 No financial arithmetic in TypeScript

`test_am1_architecture.py` scans every AM1 TypeScript file for arithmetic
applied to a name this contract computes, and for any local favorability
classification. Both are forbidden.

---

## 8. Out of scope (deferred)

Accounting/general-ledger integration; CSV or Excel import; account mapping;
Investment-level or portfolio consolidation calculations; independent report
deletion; reforecasting; budget revisions; approvals or permissions;
multiple currencies; leasing workflows; capital-project tracking; valuation
marks; dispositions; AI-generated calculations or commentary; P7.10 work.

No dependency was added.

---

## 9. The authorized demo case

March 2027, Harbor Point Apartments.

| Line | Budget | Actual |
| --- | ---: | ---: |
| Occupancy | 95.0% | 92.5% |
| Rental revenue | $100,000 | $96,000 |
| Other income | $5,000 | $6,500 |
| Property taxes | $10,000 | $10,000 |
| Insurance | $5,000 | $5,000 |
| Utilities | $5,000 | $6,000 |
| Repairs and maintenance | $6,000 | $8,000 |
| Payroll | $6,000 | $6,000 |
| Management fees | $4,000 | $4,000 |
| Other operating expenses | $2,000 | $2,000 |
| Capital expenditures | $10,000 | $10,000 |
| Debt service | $32,500 | $32,500 |

Commentary: "Two renewals moved into April. Repairs were elevated by an
unplanned HVAC replacement."

Expected results, all reproduced exactly:

| Figure | Budget | Actual |
| --- | ---: | ---: |
| Total revenue | $105,000 | $102,500 |
| Total operating expenses | $38,000 | $41,000 |
| Net operating income | $67,000 | $61,500 |
| Net cash flow | $24,500 | $19,000 |

NOI variance −$5,500 / −8.2%, unfavorable. Occupancy 2.5 percentage points
below plan. CapEx and debt service neutral.

This data exists only in tests and in ignored local QA data. It is not a
production seed and no database is tracked.

---

## 10. Architecture controls

`tests/test_am1_architecture.py` (61 guards) proves:

- the production ledger, backend and frontend;
- no AM1 financial arithmetic in TypeScript, and no local favorability
  classification;
- a Managed Asset is not a Deal: the package imports no acquisition, Scenario,
  Strategy, Capital Structure, Partnership, decision or AI module, declares no
  acquisition assumption, and has its own identity;
- monthly reports cannot mutate acquisition underwriting: no AM1 write path
  names a deal table in an `INSERT`/`UPDATE`/`DELETE`, and creating an asset
  performs exactly one write;
- budget updates fail after creation, with the typed conflict, and the update
  path contains no budget SQL;
- zero-budget percentages and zero-revenue margins return `None`, never `0.0`;
- expense favorability is directionally correct, every reportable line declares
  a direction, and CapEx / debt service / cash flow after CapEx are neutral;
- the schema migration is additive and idempotent, and nothing computed has a
  column;
- no AM1 module imports or invokes AI, and no AM1 route reaches one;
- the route surface is exactly the nine authorized routes, with one bounded
  asset DELETE and no independent report DELETE;
- no P7.9 engine or Partnership module changed, and no earlier financial module
  changed.

`tests/test_am1_mutation_proofs.py` (7 proofs) confirms these bite: flipping an
expense direction, giving CapEx a direction, returning zero instead of
unavailable, folding CapEx into operating expenses, summing occupancy year to
date, and removing the budget conflict each produce a visibly different result.

---

## 10.1 Independent-review corrections

Five defects found by independent review after the initial implementation, each
now carrying a regression test.

**Stale results under the wrong asset or month.** `useAssetPerformance` retained
the previous asset's reports and performance across a change of asset, and the
previous month's performance across a change of month — so Asset A's financials
could render beneath Asset B's header, or March's while February was selected.
Every returned value is now *derived from the key that produced it*: each request
stores its outcome tagged with the asset (and month) it was made for, and the
hook returns it only while that tag matches what is on screen. Stale rendering is
no longer a race to win but a state the model cannot represent. The shared
`isLoading` boolean, which either request could clear for both, is replaced by
two derived statuses (`reportsStatus`, `performanceStatus`); "loading" now means
"no settled outcome for the current key", which is true synchronously from the
moment the key changes. While reports are unresolved the workspace says it is
loading rather than asserting "No reporting yet", which is a claim about the
asset that is not yet known to be true.

**An echoed budget was compared before it was validated.**
`update_monthly_report_actuals` validated the frozen budget and the actuals but
not a caller-supplied `budget`, then called `float()` on each of its fields — so
an echoed `payroll: null` raised an uncaught `TypeError` and surfaced as a 500
for what is plainly a bad request. The supplied budget is now validated through
the same AM1 contract before any comparison reads it, producing the structured
422 and writing nothing. A valid-but-changed budget remains the typed
`budget_immutable` 409, and an identical valid budget remains accepted.

**Exact-plan occupancy claimed a direction.** An occupancy variance assessed
`on_plan` rendered "0.0 pts below plan · On Plan" — a direction that does not
exist, contradicting the verdict beside it. The percent case was formatted at the
call site and skipped the on-plan branch; both units now go through
`summaryDelta`, which returns plain "On plan" with no magnitude, no direction
word and no direction marker.

**The Create Managed Asset form could carry a draft between Deals.** It
initialized its name from `dealName` once, so a draft authored for Deal A could
remain and be submitted for Deal B. The form's open-state is now the Deal's
identity rather than a boolean, and the panel is keyed by it — navigating to
another Deal unmounts the form and discards the draft, deterministically during
render and with no set-state-in-effect.

**Internal and misleading provenance.** The raw `acquisition_fingerprint` was
rendered to the analyst; it stays on the contract and the wire, where it is what
actually freezes the basis, but a digest is not something an asset manager can
act on, and showing it invites comparing two hashes by eye. "View Acquisition
Basis" remains the human-facing provenance action. The month bar's "Approved
Acquisition Plan · captured <acquisition date>" was wrong twice — that date is
not when the basis was captured, and a monthly budget is never derived from an
acquisition plan — and now reads "Monthly budgets are entered explicitly and
lock after first save."

---

## 11. Pre-existing failures, not caused by AM1

A full backend suite run against `main` at `63c2ac0` in a separate worktree
(protocol 11.1 — `git worktree`, never `git stash`) reports **3 failed, 9336
passed** before AM1 exists:

- `test_analysis_d4_6b_architecture.py::test_g37_the_financial_layers_are_unchanged_and_only_dispatch_moved`
- `test_p7_9_stage_2_architecture.py::test_stage_2_changed_exactly_its_authorized_production_files`
- `test_p7_9_stage_2_architecture.py::test_an_upstream_or_frontend_path_is_unchanged[web]`

The two P7.9 Stage 2 failures are stale-ledger debt: Stage 2's ledger is measured
from `main` at `1df2760` and declares `web/` unchanged, but **Stage 3** then
changed `web/src/components/PartnershipWorkspace.tsx`,
`web/src/partnershipApi.test.ts` and others without re-pinning it. AM1
deliberately does **not** re-pin that ledger: doing so would erase the signal
that Stage 3 left it stale, and P7.9 has not yet been accepted. It belongs to
P7.9's closeout.

These three remain failing on the AM1 branch, unchanged and for the same
reasons.

### 11.1 One environmental frontend flake

The final full frontend run reported `1 failed | 1949 passed`, in
`src/leaseLevelSensitivity.test.tsx` — a file AM1 does not touch and which is
not in its ledger. Re-run in isolation it passes **60/60**. An earlier full run
had failed a *different* untouched file instead. Both are consistent with
per-test timeouts under fully parallel load rather than a regression (protocol
5.4, 7.2): the host was on AC power with 4.2 GB of 15.8 GB free, and the suite
runs ~356s with heavy worker parallelism. Diagnosed and recorded rather than
answered with repeated full-suite attempts (protocol 7.3).

## 12. Implementation status

Implemented and verified on `feature/am1-managed-assets-monthly-performance`,
then merged to `main` in PR #38 (`3048976`). Human product acceptance is
pending, so AM1 is not yet accepted.

The user-authorized Managed Asset deletion extension is implemented on
`feature/am1-delete-managed-asset` and merged to `main` in PR #39 (`60be780`).
It does not change the schema or any financial calculation: it adds one
transactional asset-level lifecycle action, an inline confirmation, and no
report-level delete action. Hands-on AM1 product acceptance remains pending.

Deletion-extension verification on 2026-09-18:

- 145 focused backend persistence, API and architecture tests passed;
- 53 focused frontend API, state, interaction and staleness tests passed;
- TypeScript and the production build are clean; lint has zero errors and the
  same five pre-existing effect warnings;
- the changed Python modules have the unchanged 42-error pyright baseline
  (2 in `api.py`, 40 in `store.py`), with no error on the deletion code;
- browser QA at 1280x720 and 390x844 verified the inline disclosure, safe-focus
  default, cancellation focus return, responsive layout and zero console
  errors. The live QA database was left unchanged; destructive success is
  covered by the persistence, API, client-state and shell tests;
- the final backend suite reported 9,597 passed and the same three inherited
  architecture-ledger failures already present after the AM1 merge.

P7.9 final human acceptance remains pending and is unaffected by this gate.
P7.10 has not started.

## 13. Closeout QA correction record

Hands-on browser QA of the merged AM1 product found presentation defects. The
P7.9 / AM1 closeout branch `fix/p7-9-closeout-and-am1-qa-corrections` (from
`main` at `c637d1e`) corrects them. **AM1 is not accepted by this record**: the
correction awaits independent review, merge and hands-on human acceptance.

- **List alignment.** The Managed Assets and Monthly Reporting headers
  inherited the browser's centred `th` default above left-aligned values. Each
  column now states one alignment class on its header and its cells. The
  classes are scoped to `.am-list-table`, so the monthly statement's
  right-aligned figures are unchanged.
- **Accessible action headers.** The empty action-column header is now a
  visually hidden "Actions".
- **Mobile header actions.** At 390px the asset header measured 461px wide and
  clipped "Edit Actuals". The actions now wrap, and they are ordered by the
  operating workflow: Edit Actuals (or Add Monthly Report), View Acquisition
  Basis, then Delete Asset. Delete stays visibly destructive, and its inline
  confirmation, warning, Cancel focus and focus return are unchanged.
- **Hidden trend-table overflow.** Monthly Performance measured 411px at 390px
  because the NOI trend's visually hidden data table still laid out at full
  width. A table sizes to its content regardless of its `width`, so the hiding
  class moved to a wrapping element. The table and its figures are still
  available to assistive technology.
- **Acquisition date.** The Overview shows the acquisition date as the rest of
  Asset Management does ("Sep 2026") rather than the raw ISO string.
- **Duplicate acquisition-basis action.** "View Acquisition Basis" appears
  once, in the asset header, where both tabs can reach it. The Overview's
  provenance panel keeps its explanation.
- **Stale guards.** The AM1 production ledger measured `63c2ac0` against the
  working tree. It is pinned to AM1's committed range `63c2ac0..366b31b` (the
  feature and its deletion extension). The D4.6B G37 frontend allowlist records
  AM1's ten production modules by name.
- **No calculation, schema or lifecycle change.** `performance.py`, the v13
  schema, the budget freeze, the deletion lifecycle and every API route are
  unchanged.
