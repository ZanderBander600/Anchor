# D6 Business Plan & Capital Economics - Phase Closeout

Status: Closeout candidate - awaiting human Phase 6 acceptance
Phase: D6 - Business Plan & Capital Economics (Gates D6.1 through D6.9)
Branch: `feature/d6-9-phase6-closeout` (base `main` @ `9ba3383`)

This document records what Phase 6 shipped and how it was verified. It adds
no convention. `D6_BUSINESS_PLAN_CONVENTIONS.md` stays the single authority
for every Phase 6 financial rule; where the two ever differ, that document
governs.

---

## 1. Purpose

> D5 forecasts the property.
> D6 models the cost of executing the business plan and the resulting
> owner-level cash economics.

Phase 6 lets an analyst schedule one-time Project Capital and recurring Owner
Expenses against any deal, in any operating mode, and see their effect on
owner cash flow, equity requirements and project returns - without moving
NOI, debt sizing, coverage or exit value.

## 2. Final Architecture

```
Quick / Detailed / Lease-Level operating model  ->  NOI (unchanged)
                                                     |
BusinessPlan  (anchor.business_plan.contracts)       |
  -> parse / validate  (parsing.py, validation.py)   |
  -> resolve_business_plan(...)  (resolver.py)       |
  -> OwnerCapitalSchedule  (anchor.engine.contracts) |
       T0 capital, annual Project Capital and        |
       Owner Expenses, post-hold disclosure          |
                                                     v
shared acquisition engine  (one implementation for all three modes)
  -> Owner Cash Flow series
  -> Project Returns  (TEI / TCR / Profit, Equity Multiple, IRR + IrrStatus)
```

- The operating mode determines NOI. The Business Plan determines owner-level
  capital economics. There is one Business Plan implementation, not three.
- The resolver owns items, categories, model months, hold-year bucketing, the
  owner-expense active-year intersection and the post-hold disclosure. The
  engine sees only T0 and annual amounts and never subtracts post-hold
  amounts.
- `anchor.leasing` does not depend on `anchor.business_plan`.

## 3. Capital Channels

| Channel | Authority | Enters | Changed by D6 |
|---|---|---|---|
| Recurring CapEx Reserve | `AcquisitionTerms.annual_capex_reserve` | Property Cash Flow | No |
| Leasing Capital (TI / LC) | Lease-Level rent roll and market leasing | Property Cash Flow | No |
| Project Capital | Business Plan capital items (model month) | T0 closing use (`month = 0`), Owner Cash Flow (`1..12H`), disclosure only (`> 12H`) | New |
| Owner Expenses | Business Plan owner-expense items (hold years) | Owner Cash Flow | New |

The channels stay separate end to end: no merged "CapEx" figure exists in the
engine, the API, the AI payload or the UI. The Capital Plan has no reserve, TI
or LC category, and each channel has one subtraction site.

## 4. Core Cash-Flow Definitions

```
Property Cash Flow_y        = NOI_y - Reserve_y - TI_y - LC_y
Unlevered Owner Cash Flow_y = Property Cash Flow_y - PC_y - OE_y
Levered Owner Cash Flow_y   = Unlevered Owner Cash Flow_y - DS_y

Unlevered Project Cash Flow:
  t = 0       -(Purchase Price + Acquisition Costs + Closing Project Capital)
  t = 1..H-1  Unlevered Owner Cash Flow_t
  t = H       Unlevered Owner Cash Flow_H + Gross Exit Value - Disposition Costs

Equity Cash Flow:
  t = 0       -Initial Equity Requirement
  t = 1..H-1  Levered Owner Cash Flow_t
  t = H       Levered Owner Cash Flow_H + Net Sale Proceeds to Equity
```

Closing Project Capital is equity-funded: it raises the Initial Equity
Requirement and the unlevered basis, never the loan. Project Capital and Owner
Expenses do not affect NOI, DSCR, minimum DSCR, debt yield, loan amount, debt
service, remaining loan balance, exit NOI, gross exit value, disposition costs
or net sale proceeds.

## 5. Project-Return Definitions

```
Net Additional Equity Requirement_y = max(-Equity Cash Flow_y, 0)   y = 1..H
Total Equity Invested (TEI) = |sum of negative Equity Cash Flow periods|
Total Cash Returned   (TCR) = sum of positive Equity Cash Flow periods
Total Profit                = TCR - TEI
Equity Multiple             = TCR / TEI
```

- The Net Additional Equity Requirement is an annual net figure. It is not a
  peak intra-year need and is never called a capital call.
- The IRR algorithm is unchanged (D10). When it reports no IRR, Anchor shows
  N/A with a deterministic `IrrStatus` reason (`MULTIPLE_SIGN_CHANGES`,
  `NO_POSITIVE_CASH_FLOW`, `FIRST_NONZERO_NOT_NEGATIVE`,
  `NO_NONZERO_CASH_FLOW`, `ROOT_OUTSIDE_SEARCH_DOMAIN`,
  `NUMERICAL_FAILURE`) and never selects an alternative root.

## 6. Persistence and Fingerprints

- Deal store schema **v7** adds two child tables, `deal_capital_plan_items`
  and `deal_owner_expense_items`. A storage ordinal preserves the analyst's
  row order.
- An absent Business Plan means an empty one. Duplicating a deal copies its
  plan; deleting a deal removes its rows.
- Fingerprints (`anchor.deals.fingerprint`): the **empty plan adds nothing**,
  so every legacy digest and every snapshot stored against one is preserved
  byte for byte (D11). A non-empty plan always adds the plan key, and every
  field of every item participates. Each collection is sorted by `item_id`,
  so row order never reaches the digest.
- Plan changes invalidate analysis, sensitivity and AI snapshots through the
  fingerprint.

## 7. Secondary Analysis

- Every sensitivity cell and break-even run receives the same Business Plan as
  the base deal. The plan is a required keyword argument, and an AST
  guardrail enforces the threading (D13). D6 adds no Business Plan
  sensitivity targets.
- Quick and Detailed: `/sensitivity/presets`, one-way / two-way sensitivity
  and `/break-even` all carry the plan.
- Lease-Level: one-way / two-way sensitivity carries the plan. Lease-Level has
  no break-even surface; `/break-even` refuses the mode by pre-D6 design
  (D5.8).

## 8. AI Boundary

- The deterministic engine calculates; the AI Analyst interprets only.
- `POST /ai/analysis` receives the request's own plan - the plan the analysis
  used. The payload adds a `business_plan_and_capital_economics` section
  (channels, items, Owner Cash Flow, Sources & Uses, equity requirements,
  project returns, lender / exit note) and an `irr_status` section, only when
  a plan is shown or an IRR is unreported. A deal with no plan whose IRRs are
  both reported sees exactly its pre-D6 payload.
- Grounding rules keep capital below NOI, forbid causal value-creation
  claims, forbid "capital call", and require the supplied IRR reason instead
  of an estimated IRR.
- AI snapshots are schema **v2**; the snapshot version never enters a
  fingerprint.

## 9. Product Surfaces

- **Business Plan editor** (`BusinessPlanEditor`): Project Capital and Owner
  Expense rows under Acquisition (Quick, Detailed) and Acquisition & Debt
  (Lease-Level), with closing / hold-year / post-hold timing tags. It sits
  beside, not inside, the Recurring CapEx Reserve and TI / LC inputs.
- **Capital Economics results view** (`CapitalEconomicsSection`), the second
  Results view in every mode: Sources & Uses at Closing, Project Returns,
  Owner Cash Flow with the Net Additional Equity Requirement, a Capital
  Schedule with one column per channel, and the Post-Hold Project Capital
  disclosure. The frontend performs no financial summation; every figure is
  a backend result.

## 10. Verification Summary

**Session A** (commit `2b85190`; tests, one fixture and one oracle runner, no
production change):

- 79 closeout tests in `tests/test_d6_9_phase6_closeout.py`, mostly over HTTP:
  one canonical plan through analyze, save, reopen, sensitivity, break-even,
  AI grounding, snapshot writes, Plan A -> B -> exact revert, row reorder and
  narrative edits, in all three modes.
- Neutral compatibility: every legacy-visible response (analysis,
  sensitivity, presets, break-even, fingerprints, deal lifecycle) is
  bit-identical to the pre-D6 tree `908499c` for an absent and an explicit
  empty plan - more than 3,000 values compared.
- Material-plan oracles: closing, future, owner-expense, post-hold,
  additional-equity, IRR-status, Sources & Uses and capital-schedule cases,
  plus the lender / exit invariance matrix.
- Five mutation proofs, all killed: the API drops the plan; post-hold capital
  enters Year H; additional equity shifted one year; a row-order-dependent
  fingerprint; duplicate drops the plan.
- 450 architecture guardrail tests and 1,208 D6 backend regression tests
  passed; the terminology audit was clean.

**Session B** (browser QA and broad suites on the final candidate tree):

- Real backend on a scratch database, seeded from
  `tests/fixtures/d6_9_phase6_reference_deals.json`; AI through a
  deterministic local stub (no model call) that received the real prompts.
- Quick (1440): plan hydration, Capital Economics, a Project Capital edit
  resetting results, re-analysis, save, hard reload, exact reopen, and an
  exact revert to the canonical plan.
- Detailed (1280): hydration, Capital Economics, Owner Expenses absent from
  the Operating Statement, save / reopen.
- Lease-Level acceptance deal (1440): all five channels in separate Capital
  Schedule columns, Year 2 carrying TI, LC, Project Capital and an Owner
  Expense together; Additional Equity in Years 1 and 2; defined IRR;
  sensitivity, AI, save / reopen with the sensitivity and AI snapshots
  restored.
- IRR N/A: `MULTIPLE_SIGN_CHANGES` (Quick, Detailed) and
  `NO_POSITIVE_CASH_FLOW` (Quick stress deal) - N/A plus reason in Capital
  Economics, N/A in Summary, the same status received by the AI.
- Widths 1440 / 1280 / 390; every D6 request carried `business_plan`; no
  unexpected console errors, React warnings or 4xx / 5xx.
- Full backend suite (`pytest`): 6,389 passed, no warnings, 96s.
- Full frontend suite (`vitest run`): 1,504 passed in 52 files, no warnings,
  204s.
- Typecheck and production build (`tsc -b && vite build`): clean. Lint
  (`oxlint`): clean.
- Production diff against `9ba3383` after Session B: none.

**Final acceptance patch** (the one authorized production change in D6.9, CSS
only):

- Cause: the Capital Schedule's Closing-row "Not applicable" screen-reader
  spans (`.visually-hidden`, absolutely positioned) had no positioned
  ancestor, so they resolved against the page instead of the table's scroll
  container. At 390px they widened the page from the shell's 508px to 665px;
  at desktop they stretched the document height and added a spurious outer
  scrollbar.
- Fix (`web/src/index.css`): `.capital-economics-na { position: relative; }`
  makes each cell its span's containing block. Inside the narrow (620px)
  container query, the Capital Economics scroll container clips its
  fractional left edge (`clip-path: inset(0 0 0 1px)`), so no scrolled figure
  shows beside the pinned Period column.
- Proof: at 390px the page stays 508px wide with the schedule shown and
  scrolled fully right and back; Period stays pinned; the one-pixel bleed
  column reads zero; the four "Not applicable" cells stay in the
  accessibility tree and visually hidden. At 1280 and 1440 no table cell
  moves at equal available width, and the spurious outer scrollbar is gone.
- Regression tests in `web/src/capitalEconomicsCloseout.test.tsx`. The D6.9
  production ledger now admits exactly `web/src/index.css`.

## 11. Accepted Debt

Non-blocking, carried forward:

1. Global app-shell horizontal overflow near 390px (mode switch, workspace
   nav, Underwrite sub-nav). Pre-D6.
2. Playwright `fill()` concatenates on grouped `NumericInput`; a person's
   own editing is unaffected. QA-tooling quirk.
3. SQLite huge month / year values return HTTP 500 with a rollback.
4. A direct Python call with a huge integer amount raises `OverflowError`.
5. Optional micro-copy: the Owner Cash Flow note says "Lease-Level TI / LC"
   in every mode; "where applicable" would read better in Quick and Detailed.
6. (Session B, optional) Summary shows IRR "N/A" without the reason; the
   deterministic reason is shown in Capital Economics. Accepted as is.

Resolved before acceptance: the Session B P4 (the 390px Lease-Level Capital
Schedule overflow and the pinned-column sliver), by the final acceptance patch
in §10.

Follow-up for the first Phase 7 gate: re-pin
`test_x_d6_9_changes_only_authorized_production_files` from `HEAD` to
`9ba3383..<D6.9 merge>`.

## 12. Explicitly Deferred

Out of scope for Phase 6 (conventions §21): multiple debt tranches,
refinancing, floating-rate extensions, preferred equity, GP promote and LP /
GP waterfalls, capital-call allocation, peak monthly funding requirement,
cash-account balances, payout ratios and retained cash, actual distributions
and actual vs budget, development and construction loans, contingency
reserves, project status tracking, renovation-to-rent causality and yield on
cost, tax modeling, portfolio analytics, a full Overview dashboard, Business
Plan sensitivity targets and formula-based owner expenses.
