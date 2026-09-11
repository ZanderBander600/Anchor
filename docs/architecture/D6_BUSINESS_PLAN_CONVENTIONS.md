# D6 Business Plan & Capital Economics Conventions

Status: Ratified
Phase: D6 - Business Plan & Capital Economics
Applies to: D6.1 through D6.9
Supersedes: exploratory D6.0 alternatives where this document makes an explicit decision

> D5 forecasts the property.
> D6 models the cost of executing the business plan and the resulting
> owner-level cash economics.

---

## 0. Authority and Scope

- This document is the single source of truth for Phase 6 financial
  conventions. Where the exploratory D6.0 architecture report differs, this
  document governs. D6.0 alternatives that were not adopted here are closed.
- Existing financial conventions stay authoritative unless this document
  explicitly extends them. That includes `docs/financial_conventions.md`
  (including IRR validity and the IRR numerical solution), the underwriting V2,
  detailed operating model v2.1 and owner return metrics v3 conventions, and
  the D0-D4 lease-level conventions in `docs/plans/`.
- **Core engine input expansion.** `AGENTS.md` requires explicit approval to
  expand the core engine beyond its nine acquisition inputs. Decision D1 (§24)
  is that approval. It covers only the Business Plan contract defined here
  and no other input expansion.
- **Numbering.** "Phase 6 / D6" follows the D-series gate numbering (D0-D5).
  It is unrelated to the numbered Development Sequence in `AGENTS.md`.
- Every D6 gate follows `docs/development/ANCHOR_DEVELOPMENT_PROTOCOL.md`.
  §22 gives the default risk tier for each gate.
- §25 lists the decisions this document leaves to named implementation gates.
  Those gates must decide them explicitly, never incidentally. None of them
  alters a financial definition. No financial-definition question remains
  open before D6.1.

Notation used below:

| Symbol | Meaning |
|---|---|
| `H` | Hold period, in years |
| `y` | Hold year, `1..H` |
| `t` | Annual cash-flow period, `0..H` (`0` = closing) |
| `m` | Model month (§4) |
| `PC_0` | Closing Project Capital |
| `PC_y` | Project Capital in hold year `y` |
| `OE_y` | Owner Expenses in hold year `y` |
| `Reserve_y` | Recurring CapEx Reserve in hold year `y` |
| `TI_y`, `LC_y` | Lease-Level tenant improvements and leasing commissions in hold year `y` (zero in Quick and Detailed) |
| `DS_y` | Debt Service in hold year `y` |

---

## 1. Phase 6 Architecture

```
Operating Models
Quick / Detailed / Lease-Level
        |
        v
       NOI
        |
        v
Business Plan / Capital Economics
        |
        v
Owner Cash Flow
        |
        v
Future Capital Structure / Partnership Economics
```

The Business Plan is:

- mode-agnostic;
- separate from `AcquisitionTerms`;
- separate from all operating-mode inputs;
- resolved once into a generic engine schedule;
- consumed by the shared acquisition engine.

The engine input surface is explicitly expanded to accept the Business Plan
(D1).

Business Plan fields must **not** be placed on:

- `AcquisitionTerms`;
- Quick `AcquisitionInputs`;
- `DetailedOperatingInputs`;
- Lease-Level leasing contracts.

---

## 2. Capital Channels

There are three distinct capital channels.

| Channel | Authority | D6 change |
|---|---|---|
| A. Recurring CapEx Reserve | `AcquisitionTerms.annual_capex_reserve` | None |
| B. Leasing Capital | Lease-Level TI / LC schedules | None |
| C. Project / Business-Plan Capital | New Business Plan Capital Plan | New |

### A. Recurring CapEx Reserve

- Unchanged from D5.
- A flat annual scalar.
- Below NOI.
- Affects project cash flow and returns.
- Does not affect NOI, DSCR, debt yield, exit NOI or exit value.
- Must not be renamed, migrated, deprecated or converted into Capital Plan
  items.

### B. Leasing Capital (TI / LC)

- Unchanged from D5.
- TI and LC stay below NOI.
- Their monthly authority, annual aggregation and exit-window treatment are
  unchanged.
- They have no effect on DSCR, debt yield or exit NOI. That is unchanged.

### C. Project / Business-Plan Capital

- Analyst-entered.
- One-time scheduled items.
- Below NOI.
- Affects owner and project cash flow.
- Does not automatically create NOI.
- Does not automatically create value.
- Does not alter debt sizing, DSCR, debt yield, exit NOI or gross exit value.
- Does not alter net sale proceeds directly.

**The three channels must remain separate.** No merged generic "CapEx" field
may erase their identities.

---

## 3. Capital Plan Contract

Conceptual contract: `CapitalPlanItem`.

| Field | Rules |
|---|---|
| `item_id` | Stable, opaque, nonempty, unique across the entire Business Plan (see "Item ID namespace" below). It has no financial meaning. The normal UI may mint UUIDs, but the contract must not require UUID format. A reasonable storage length limit may be enforced later. |
| `description` | Required and nonempty. Used for reporting and audit. |
| `category` | Reporting metadata **only**. |
| `month` | An integer model-month index (§4). `bool` is rejected. Must be `>= 0`. The core financial contract sets no maximum. |
| `amount` | Nominal dollars. Must be finite and `>= 0`. Zero is allowed. |

### Item ID namespace

The Business Plan has **one shared item-ID namespace**. Every `item_id`
across all `CapitalPlanItem` and `OwnerExpenseItem` entries must be unique
when considered together.

For example, `CapitalPlanItem(item_id="abc")` and
`OwnerExpenseItem(item_id="abc")` in the same Business Plan is invalid.

IDs remain stable, opaque and nonempty, and carry no financial meaning. The
normal UI may mint UUIDs; the financial contract must not require UUID
syntax.

### Capital categories

Ratified categories:

- `VALUE_ADD_RENOVATION`
- `DEFERRED_MAINTENANCE`
- `BUILDING_SYSTEMS`
- `EXTERIOR_COMMON_AREA`
- `OTHER`

Explicitly excluded: `CONTINGENCY`, `RECURRING_REPLACEMENT`, `RESERVE`, `TI`,
`LC`.

**No category may alter any financial calculation.**

### Not in D6

The Capital Plan does not carry a recurrence flag, status, certainty, notes,
draw schedule, escalation, funding source or lender future funding.

---

## 4. Timing Convention

The Capital Plan uses canonical **model-month** timing (D15). A model month is
an index, not a calendar date.

| `month` | Meaning |
|---|---|
| `0` | Closing / T0 |
| `1..12H` | Model month in hold year `((month - 1) // 12) + 1` |
| `> 12H` | After the hold period (§19) |

Boundaries:

| Months | Hold year |
|---|---|
| 1-12 | Year 1 |
| 13-24 | Year 2 |
| `12(y-1)+1` to `12y` | Year `y` |

Month 1 is a model month, not closing.

Month precision belongs in the Business Plan even though the Quick and
Detailed operating models stay annual.

### T0 project capital (`month = 0`)

- A closing use (§10).
- Equity-funded in D6.
- Increases the Initial Equity Requirement.
- Increases the unlevered basis.
- Does **not** increase acquisition loan size.
- Does **not** create loan-to-cost behavior.

### Future project capital (`1 <= month <= 12H`)

- Is **not** treated as closing equity and is not pre-funded at closing.
- Enters the cash flow of its hold year.
- Is netted with that year's other equity cash flows.

### Post-hold capital (`month > 12H`)

- Accepted.
- Excluded from seller economics.
- Excluded from project cash flows.
- Does not reduce exit value.
- Disclosed separately (§19).

---

## 5. Owner Expense Plan

D6 includes a narrow Owner Expense Plan.

Conceptual contract: `OwnerExpenseItem`.

| Field | Rules |
|---|---|
| `item_id` | Same identity rules as `CapitalPlanItem.item_id`, in the same shared namespace (§3). |
| `description` | Required and nonempty. |
| `category` | Reporting metadata **only**. |
| `annual_amount` | Fixed nominal dollars per hold year. Must be finite and `>= 0`. |
| `first_year` | An integer hold year. `bool` is rejected. Must be `>= 1`. |
| `last_year` | An integer hold year, or `None`. `bool` is rejected. When an integer, must be `>= first_year`. `None` means "through the current underwriting hold period" (see below). |

Ratified reporting-only categories:

- `ASSET_MANAGEMENT`
- `LEGAL_PARTNERSHIP`
- `OTHER`

### Owner expense timing

- **No Year-0 owner expense.** `first_year >= 1`. Closing-time costs belong
  in closing / acquisition economics (§10), not in this ongoing owner-expense
  contract.
- **`last_year = None`** means "through the current underwriting hold
  period". It does **not** mean forever.
- **Explicit `last_year`** must satisfy `last_year >= first_year`.

Financial treatment. The resolver computes each item's **active years**:

```
active years = [first_year .. last_year] ∩ [1 .. H]

where last_year = None is read as last_year = H
```

`OE_y` is the sum of `annual_amount` over every item whose active years
include `y`. Only active years affect financial results.

| `H` | `first_year` | `last_year` | Active years (financial effect) |
|---|---|---|---|
| 5 | 2 | `None` | 2, 3, 4, 5 |
| 5 | 4 | 8 | 4, 5 (years 6-8 have no financial effect) |
| 5 | 7 | 10 | none (no financial effect) |

Items that extend beyond, or lie entirely beyond, the hold period are
accepted. Their out-of-hold years have no financial effect.

- **No aggregate post-hold owner-expense dollar result.** Unlike post-hold
  project capital (§19), D6 creates no "post-hold owner expenses" total. A
  recurring expense with `last_year = None` has no meaningful finite
  post-hold total.
- The resolver may expose reporting / audit treatment classifying each item
  as **fully inside hold**, **partially outside hold** or **fully outside
  hold**. The exact reporting contract is finalized in D6.1 (§25). It carries
  no financial effect beyond the active-years rule above.
- **Changing the hold period re-resolves every owner-expense item.** A
  `None`-ended item therefore extends automatically through the new hold.

### Behavior

Owner expenses:

- reduce Unlevered Owner Cash Flow;
- reduce Levered Owner Cash Flow;
- reduce project returns;
- do **not** reduce NOI;
- do **not** affect DSCR;
- do **not** affect debt yield;
- do **not** affect exit NOI;
- do **not** affect exit value;
- do **not** enter expense recoveries.

D6 owner expenses are fixed nominal annual dollars only. D6 does not
implement:

- percentage of revenue;
- percentage of EGI;
- percentage of equity;
- sponsor-recipient economics;
- waterfall allocation.

**Property management fee.** The property management fee stays a property
operating expense, above NOI. It must not be duplicated as an owner expense.

---

## 6. Cash Flow Vocabulary

These terms are the preferred vocabulary for all new D6 UI, AI and
architecture work (D6):

- NOI
- Property Cash Flow
- Unlevered Owner Cash Flow
- Levered Owner Cash Flow
- Equity Cash Flow

Legacy recurring-cash-flow fields may remain for backward compatibility.
"Recurring" terminology is **not** the conceptual authority for D6, because
project capital, TI/LC and owner expenses may all be non-recurring.

### Authoritative owner cash-flow chain

```
NOI
 |
 v
Property Cash Flow
 |
 v
Unlevered Owner Cash Flow
 |
 v
Levered Owner Cash Flow
 |
 v
Equity Cash Flow
```

- D6.2 establishes these as **authoritative financial result series**. The
  Unlevered Project Cash Flow series is derived from Unlevered Owner Cash Flow
  as defined below.
- Metrics consume these authoritative series rather than creating parallel
  owner-cash-flow equations wherever possible (§8).
- Existing UCF / LCF expression ordering is preserved where necessary to meet
  the ratified D5 neutral-input bit-identity oracle (§14).

### Definitions

NOI is the unchanged output of the operating mode.

```
Property Cash Flow_y        = NOI_y - Reserve_y - TI_y - LC_y

Unlevered Owner Cash Flow_y = Property Cash Flow_y - PC_y - OE_y

Levered Owner Cash Flow_y   = Unlevered Owner Cash Flow_y - DS_y
```

**Unlevered Project Cash Flow** (the unlevered IRR series):

```
t = 0          -(Purchase Price + Acquisition Costs + Closing Project Capital)
t = 1..H-1     Unlevered Owner Cash Flow_t
t = H          Unlevered Owner Cash Flow_H + Gross Exit Value - Disposition Costs
```

**Equity Cash Flow** (the levered IRR and equity-multiple series):

```
t = 0          -Initial Equity Requirement
t = 1..H-1     Levered Owner Cash Flow_t
t = H          Levered Owner Cash Flow_H + Net Sale Proceeds to Equity
```

### Arithmetic rules

- These definitions are algebraic. Implementations must keep the existing
  arithmetic grouping where D5 bit compatibility requires it. The order in
  which terms are presented does not dictate the order in which they are
  evaluated.
- Some legacy expressions are algebraically equal but group floating-point
  operations differently (for example, the existing levered cash-flow and
  recurring levered cash-flow expressions). Tests must not assert bitwise
  equality between such expressions. Compare them within tolerance.

### Legacy recurring cash-flow fields

- Legacy recurring cash-flow fields and helpers are kept where backward
  compatibility requires them.
- The authoritative D6 vocabulary is Property Cash Flow, Unlevered Owner Cash
  Flow, Levered Owner Cash Flow and Equity Cash Flow.
- D6.2 should avoid creating independent duplicate financial formulas solely
  to preserve legacy naming. Where technically compatible with the D5
  bit-identity requirements, legacy fields should consume / reuse the
  authoritative owner cash-flow results.
- Existing arithmetic grouping is preserved where necessary for bit-compatible
  D5 outputs.
- Economically, the legacy recurring levered and recurring unlevered series
  follow Levered Owner Cash Flow and Unlevered Owner Cash Flow, so project
  capital and owner expenses reduce them (§8).
- New D6 UI, AI and architecture documentation must use the Owner Cash Flow
  terminology. Do not introduce "recurring" terminology into any new D6
  concept whose series contains non-recurring project capital or leasing
  capital.

### Legacy cumulative operating distribution field

- `cumulative_operating_distributions_by_year` remains for backward
  compatibility.
- Its economics follow the authoritative Levered Owner Cash Flow series:
  project capital and owner expenses reduce it.
- It is a legacy compatibility field. Its naming is **not** D6 product
  vocabulary.
- New UI and AI must not describe a negative amount as a "negative
  distribution". Describe it as **negative owner cash flow** or as a **Net
  Additional Equity Requirement** (§7), as appropriate.

---

## 7. Equity Funding Terminology

Do **not** use "Capital Call" unless a future partnership or funding model
explicitly supports it.

Ratified terms:

- Initial Equity Requirement
- Net Additional Equity Requirement by Year
- Total Equity Invested
- Total Cash Returned
- Total Profit

Initial Equity Requirement is `-Equity Cash Flow_0`.

```
Net Additional Equity Requirement_y = max(-Equity Cash Flow_y, 0)    for y = 1..H only
```

This is an **annual net** requirement. It is **not**:

- a peak intra-year funding requirement;
- a formal capital call;
- proof of the exact date equity must be contributed.

**Example.** Suppose a large expenditure in Month 49 is offset by sale
proceeds in Month 60. Year 5 may then show a Net Additional Equity Requirement
of zero.

A future monthly owner-cash-flow framework may introduce a Peak Funding
Requirement. That is deferred (§21).

---

## 8. Project Return Definitions

All four definitions use the Equity Cash Flow series, `t = 0..H`.

```
Total Equity Invested (TEI) = |sum of all negative Equity Cash Flow periods|
Total Cash Returned   (TCR) = sum of all positive Equity Cash Flow periods
Total Profit                = TCR - TEI
Equity Multiple             = TCR / TEI        when TEI > 0
```

- The definitions must stay algebraically consistent. TEI and TCR are the
  same quantities as the Equity Multiple denominator and numerator, so the two
  can never diverge.
- The existing Equity Multiple behavior when `TEI = 0` is unchanged.
- It follows that `TEI = Initial Equity Requirement + sum of Net Additional
  Equity Requirement_y` (compare within floating-point tolerance).

### Existing return metrics under D6

**Principle.** If an existing metric represents owner / project cash
economics, Phase 6 Project Capital and Owner Expenses must affect it
consistently. A misleading D5 numerator must **not** be preserved merely to
avoid moving a metric.

| Metric | Series / numerator | Denominator / basis | D6 effect |
|---|---|---|---|
| Levered IRR | Equity Cash Flow | n/a | Affected through Equity Cash Flow. |
| Unlevered IRR | Unlevered Project Cash Flow | n/a | Affected through Unlevered Project Cash Flow. |
| Equity Multiple | Total Cash Returned | Total Equity Invested | Affected. Future negative Equity Cash Flow periods increase Total Equity Invested. |
| Levered Cash-on-Cash (annual) | Levered Owner Cash Flow_y | Initial Equity Requirement | Numerator affected. Closing Project Capital raises the denominator. Future Net Additional Equity Requirements do **not** change the denominator. |
| Unlevered Cash Yield (annual) | Unlevered Owner Cash Flow_y | Purchase Price + Acquisition Costs + Closing Project Capital | Numerator affected. Closing Project Capital raises the basis. Future project capital does **not** retroactively change the basis. |
| Cumulative operating distributions (legacy) | Running sum of Levered Owner Cash Flow | n/a | Affected (§6). |

- **IRR.** The IRR **algorithm** is unchanged (§9, D10). Only its input
  series change.
- **Equity Multiple** continues to use
  `Total Cash Returned / Total Equity Invested`, as defined above.
- **Cash-on-Cash remains a return on INITIAL equity, not on cumulative
  invested equity.** Its denominator is the existing fixed `initial_equity`,
  which Closing Project Capital increases (§4, §10). D6 does not silently
  redefine this metric; any cumulative-equity variant would need a separate
  ratified convention.
- **Cash Yield basis.** Financing fees remain outside the unlevered basis,
  as in the existing owner return metrics v3 convention. The basis is fixed
  at acquisition, as before.
- The existing zero-denominator convention (`None` when the denominator is
  exactly `0.0`) is unchanged for both annual yield metrics.

### New result fields

These fields are ratified conceptually:

- `closing_project_capital`
- `project_capital_by_year`
- `post_hold_project_capital`
- `owner_expenses_by_year`
- `property_cash_flow_by_year`
- `unlevered_owner_cash_flow_by_year`
- `levered_owner_cash_flow_by_year`
- `net_additional_equity_requirement_by_year`
- `total_equity_invested`
- `total_cash_returned`
- `total_profit`
- `total_closing_uses`
- `total_closing_sources`

Do not add redundant synonyms where an authoritative field already exists.
Specifically:

- the existing `initial_equity` is the Initial Equity Requirement;
- `capex_by_year` stays the Recurring CapEx Reserve only;
- `tenant_improvements_by_year` and `leasing_commissions_by_year` stay the
  leasing-capital authority.

There is deliberately **no** aggregate post-hold owner-expense field (§5).

---

## 9. IRR Convention

- **The current IRR algorithm does not change in D6** (D10). The "IRR
  validity" and "IRR numerical solution" sections of
  `docs/financial_conventions.md` stay authoritative. They apply to both the
  Unlevered Project Cash Flow and the Equity Cash Flow series.
- When the algorithm returns no IRR, Anchor must **not** invent or select one.
  That covers multiple sign changes and every other condition the convention
  defines: no negative or no positive cash flow, a first nonzero cash flow
  that is not negative, and the numerical-support limits.
- D6 adds deterministic status and reason information so the UI and AI can
  explain why IRR is unavailable.
- Preferred user-facing wording: **"N/A - cash flows contain multiple sign
  changes"**.
- Exact internal enum and status names must reflect the actual implementation
  semantics. They are finalized in D6.3.
- **Known consequence of D10.** A typical value-add profile (for example, a
  positive Year 1 followed by a capital-driven negative Year 2) has multiple
  sign changes, so IRR will be N/A more often. This is not a defect.
- Any future attempt to produce an IRR for streams with multiple sign changes
  needs a separate **Tier 1** financial-convention specification and explicit
  ratification. The algorithm must not change incidentally during D6.

---

## 10. Sources & Uses

```
ACQUISITION USES
  Purchase Price
  Acquisition Costs
  Financing Fees

BUSINESS PLAN AT CLOSING
  Closing Project Capital

TOTAL CLOSING USES
  = Purchase Price + Acquisition Costs + Financing Fees + Closing Project Capital

CLOSING SOURCES
  Acquisition Debt
  Initial Equity

TOTAL CLOSING SOURCES
  = Acquisition Debt + Initial Equity
```

- Closing Project Capital raises Initial Equity. It does not raise
  Acquisition Debt (§4, §12).
- Total Closing Uses and Total Closing Sources are algebraically equal.
  Floating-point grouping may differ, so tests compare them within tolerance.
- **Future project capital is not a closing use.** It is reported under
  **Future Capital Requirements**.
- Do **not** treat future capital as pre-funded at closing.

---

## 11. Value Creation Language

Spending capital does **not** automatically create NOI, rent growth, value or
exit value. Anchor must never infer a deterministic causal relationship just
because capital was spent.

Allowed reporting concepts:

- total project capital invested;
- exit value;
- exit value vs total cost basis;
- operating cash generated;
- debt paydown;
- total profit.

Avoid causal statements such as *"$2M of renovation created $5M of value."*
They may be used only if a future scenario-attribution framework explicitly
supports them.

Deferred:

- NOI-growth attribution;
- cap-rate attribution;
- value created per capital dollar;
- yield on cost;
- renovation-to-rent causality.

---

## 12. Debt / Lender Invariants

| D6 project capital and owner expenses do **not** affect | They **do** affect |
|---|---|
| NOI | Unlevered project cash flow |
| DSCR | Equity cash flow |
| Minimum DSCR | Owner cash flow |
| Debt yield | IRR |
| Loan amount | Equity multiple |
| Debt service | Profit |
| Remaining loan balance | Cash-on-cash and cash yield (§8) |
| Exit NOI | Cumulative operating distributions, legacy field (§6) |
| Gross exit value | |
| Disposition costs | |
| Net sale proceeds (directly) | |

D6 has:

- no lender future-funding mechanics;
- no loan-to-cost sizing;
- no lender cash-trap mechanics.

---

## 13. Cross-Mode Architecture

Quick, Detailed and Lease-Level must all converge into the **same** Business
Plan and owner-cash-flow layer.

- The **operating mode** determines property operations and NOI.
- The **Business Plan** determines owner-level capital economics.

There must **not** be three independent Business Plan financial
implementations.

Dependency direction (names are indicative and finalized in D6.1):

```
BusinessPlan
    |
    v
resolve_business_plan(...)
    |
    v
OwnerCapitalSchedule
    |
    v
analyze_acquisition_from_operating_projection(...)
```

- The generic engine schedule knows only T0 and annual amounts.
- The resolver owns items, categories, months, hold-year bucketing, the
  owner-expense active-year intersection (§5) and the post-hold disclosure.
- The engine never subtracts post-hold amounts, including out-of-hold
  owner-expense years.
- `anchor.leasing` must not depend on `anchor.business_plan`.

---

## 14. Backward Compatibility

- An empty Business Plan must preserve every existing D5 financial output.
- Neutral D6 inputs must reproduce D5 Quick, Detailed and Lease-Level
  economics.
- `annual_capex_reserve` is unchanged.
- TI/LC are unchanged.
- Legacy deals with no Business Plan behave as before.

Fingerprints:

- An empty Business Plan should preserve legacy fingerprints, if that is
  technically safe (D11).
- A non-empty Business Plan must affect deal fingerprints.

Snapshots:

- The snapshot schema may be bumped where new required result fields cannot
  safely be defaulted (D12).
- Old snapshots must **not** be decoded by fabricating required derived
  financial fields.

---

## 15. Persistence / API Principles

These principles describe expected future behavior. D6.0A implements none of
it, and D6.5 owns the exact schema.

- The Business Plan is persisted with the deal.
- Capital items are stored relationally.
- Owner-expense items are stored relationally.
- Duplicating a deal copies its Business Plan.
- Deleting a deal removes its Business Plan rows.
- Business Plan changes invalidate financial snapshots, AI results and
  sensitivities.
- An absent Business Plan means an empty Business Plan.

---

## 16. Sensitivity / Break-Even Principles

- Every sensitivity cell and break-even run must use the **same** Business Plan
  as the base deal. The only exception would be a future sensitivity target
  that varies the Business Plan itself.
- D6 adds **no** Business Plan sensitivity targets.
- Plan changes invalidate existing sensitivity snapshots.
- The Business Plan is threaded as a required keyword argument, and an
  architecture / AST guardrail enforces it (D13).
- Break-even behavior when IRR is undefined must stay explicit and
  conservative.
- The Business Plan must never be silently omitted.

---

## 17. AI Principles

- AI receives deterministic Phase 6 results in a later gate (D6.8).
- AI must not calculate authoritative totals.
- AI may interpret:
  - plan items;
  - capital timing;
  - total project capital;
  - owner expenses;
  - Sources & Uses;
  - Net Additional Equity Requirements;
  - Total Equity Invested;
  - Total Cash Returned;
  - Total Profit;
  - Owner Cash Flows;
  - IRR availability and the reason it is unavailable.

Grounding rules:

- Capital sits below NOI, and spending capital does not imply value creation.
- Do not use "capital call" unless a future partnership contract supports it.

---

## 18. Validation Conventions

The core financial contract:

- sets no maximum number of Capital Plan items;
- sets no maximum month;
- allows zero-dollar items;
- rejects negative amounts;
- rejects non-finite amounts;
- rejects duplicate IDs across the whole Business Plan (capital and
  owner-expense items share one namespace, §3);
- rejects `bool` for integer month and year fields;
- rejects `OwnerExpenseItem.first_year < 1`;
- rejects an integer `OwnerExpenseItem.last_year < first_year`;
- accepts owner-expense years beyond the hold period (§5).

Practical UI / API payload limits may be added later for operational reasons.
Such limits must not change financial semantics.

---

## 19. Post-Hold Capital

Capital scheduled after the hold period (`month > 12H`):

- remains part of the Business Plan;
- is excluded from seller cash flows;
- is excluded from project returns;
- does not reduce exit value;
- does not create a buyer credit;
- is disclosed separately (`post_hold_project_capital`).

This keeps the plan intact without pretending the seller funds post-sale
work.

Owner expenses follow the active-years rule in §5 instead. Their
out-of-hold years have no financial effect, and there is no aggregate
post-hold owner-expense dollar result.

---

## 20. Double-Count Protection

Structural protections:

- The Capital Plan has no recurring or reserve category.
- The Capital Plan has no TI category.
- The Capital Plan has no LC category.
- `annual_capex_reserve` stays separate.
- TI/LC stay separate.
- The engine has one subtraction site per capital channel.
- `MonthlyPropertyProjection` stays free of generic CapEx and project-capital
  lines.
- The frontend performs no financial summation.

**Lease-Level residual risk (D14).** An analyst could manually enter an amount
that economically duplicates TI/LC under another project-capital category. D6
accepts this residual risk. Mitigations are UI guidance, documentation, labels
and AI explanation. Do not attempt fuzzy semantic detection.

---

## 21. Phase 6 Deferred Scope

The following are explicitly **out of scope** for D6:

- multiple debt tranches
- refinancing
- floating-rate debt extensions
- preferred equity
- GP promote
- LP/GP waterfall
- capital-call allocation
- peak monthly funding requirement
- cash-account balances
- payout ratios
- retained cash
- actual distributions
- actual vs budget
- development construction schedule
- construction loans
- contingency reserves
- project status / committed / spent
- renovation-to-rent causality
- yield on cost
- tax modeling
- portfolio analytics
- full Overview dashboard
- Business Plan sensitivity targets
- formula-based owner expenses

§3, §5, §11 and §12 list further exclusions: Capital Plan item fields, owner
expense formulas, value attribution, and lender mechanics.

---

## 22. Ratified D6 Gate Sequence

| Gate | Scope | Risk tier |
|---|---|---|
| D6.1 | Business Plan contracts, validation and resolver | Tier 1 |
| D6.2 | Owner Cash Flow engine bridge, T0 capital, Sources & Uses, owner cash-flow fields | Tier 1 |
| D6.3 | Project Returns, Net Additional Equity Requirement, TEI/TCR/Profit, IRR status | Tier 1 |
| D6.4 | Thread the Business Plan through sensitivity, break-even and analytical callers | Tier 1 |
| D6.5 | API, persistence, fingerprints, schema v7 if confirmed necessary | Tier 2 |
| D6.6 | Business Plan input UI | Tier 3 |
| D6.7 | Results and reporting: Capital Schedule, Owner Cash Flow, Sources & Uses, Project Returns, post-hold disclosure | Tier 3 |
| D6.8 | AI grounding | Tier 2 |
| D6.9 | Cross-mode closeout and human acceptance | Tier 1 closeout |

Each gate is started explicitly. Finishing one gate never starts the next.

---

## 23. Reference Cases

This is the minimum Phase 6 oracle set, carried forward from D6.0:

1. No Phase 6 additions
2. Future $1M project-capital expenditure
3. $1M closing project capital
4. Recurring reserve + project capital
5. Lease-Level TI/LC + project capital in the same year
6. Owner expense without project capital
7. Future negative equity cash flow
8. Final-year capital + sale
9. Post-hold capital
10. Multiple sign changes / IRR unavailable

These are architecture oracles. The gate that implements each behavior creates
the exact numerical golden cases.

---

## 24. Authoritative Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Separate BusinessPlan contract (includes explicit approval to expand the engine input surface) | APPROVED |
| D2 | Keep `annual_capex_reserve` unchanged | APPROVED |
| D3 | One-time Capital Plan items / month index | APPROVED |
| D4 | Five reporting-only capital categories | APPROVED |
| D5 | Post-hold capital: exclude + disclose | APPROVED |
| D6 | New Owner Cash Flow vocabulary | APPROVED |
| D7 | T0 capital increases initial equity / basis | APPROVED |
| D8 | Narrow Owner Expense Plan | APPROVED |
| D9 | Annual Net Additional Equity semantics | APPROVED |
| D10 | Existing IRR algorithm unchanged | APPROVED |
| D11 | Empty-plan legacy fingerprint preservation | APPROVED |
| D12 | Snapshot schema bump where required | APPROVED |
| D13 | Required threading + AST guardrail | APPROVED |
| D14 | TI/LC duplication residual risk accepted | APPROVED |
| D15 | Model-month timing | APPROVED |
| D16 | Owner expense timing: `first_year >= 1`; `last_year = None` means through the current hold; active years = item range ∩ `1..H`; no post-hold owner-expense total (§5) | APPROVED |
| D17 | One shared item-ID namespace across the Business Plan (§3) | APPROVED |
| D18 | Existing owner / project cash metrics follow the authoritative owner cash-flow series; Cash-on-Cash stays a return on initial equity (§6, §8) | APPROVED |

---

## 25. Not Decided by This Document

The named gate must settle each of these explicitly, consistent with the
conventions above. None of them may be settled incidentally.

Every item below is an implementation or reporting detail. None of them
alters a financial convention. **No financial-definition question remains
open before D6.1.**

Resolved by D6.0A final convention resolution, and no longer open:

- `OwnerExpenseItem` year validation and hold-period treatment: §5, D16.
- Shared item-ID namespace: §3, D17.
- Existing return metrics and legacy cash-flow fields under D6: §6, §8, D18.

| Item | Owning gate |
|---|---|
| Contract type names, module layout and enum string values | D6.1 |
| Exact reporting / audit contract for owner-expense hold-period treatment (fully inside / partially outside / fully outside hold), within §5 | D6.1 |
| Implementation mechanism by which legacy fields reuse the authoritative owner cash-flow series while preserving D5 bit identity, within §6 and §8 | D6.2 |
| IRR status / reason enum names and values | D6.3 |
| Break-even handling of undefined IRR (within §16) | D6.4 |
| Persistence schema, migration version and the mechanism for empty-plan fingerprint preservation | D6.5 |
| Operational UI / API payload limits and the `item_id` storage length limit | Later operational gate (no financial effect) |
| Exact numerical golden cases | The gate implementing each behavior |
