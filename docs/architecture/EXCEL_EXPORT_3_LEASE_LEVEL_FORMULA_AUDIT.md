# Excel Export 3: Lease-Level Underwrite Formula Audit

Status: **implemented on `feature/excel-export-3-lease-level-formula-audit`,
pending independent review and human acceptance -- not accepted.** Baseline:
`main` at `fe70d40` (Excel Export 2 merged in PR #46; schema v14). Risk tier: 1
(the workbook independently reproduces the whole Lease-Level rent roll,
rollover chain, recoveries, property statement, debt, exit value, equity cash
flow, equity multiple and IRR), with Tier 2 eligibility behaviour and Tier 3
export interaction. No financial calculation, fingerprint, stored analysis,
schema or AI behaviour changes.

## 1. Scope

A saved **Lease-Level Underwrite** Deal can be downloaded as one `.xlsx`
workbook that is both a readable underwriting deliverable and an independent,
formula-level audit of Anchor's Lease-Level engine.

Explicitly excluded: Investments, Scenarios, Strategies, Capital Structure,
Partnership Waterfalls and Asset Management exports; P7.10; any schema,
fingerprint, AI or financial-engine change. Quick Underwrite (Excel Export 1)
and Detailed Underwrite (Excel Export 2) keep their own workbooks, unchanged.

## 2. The no-analysis-snapshot decision

**This is the one structural difference from Quick and Detailed, and it is
deliberate.**

`lease_level_deals` has no `analysis_snapshot` column. That is an accepted
Lease-Level design decision (D5), not an oversight, and this export does not
change it: no column is added, no migration is written, and the schema stays
v14.

So the server:

1. reads the saved Deal and **all** its typed child records -- property
   inputs, operating inputs, market leasing defaults, every Suite and every
   Lease -- in **one consistent read**
   (`store.get_lease_level_export_provenance`, one connection);
2. **re-runs the existing authoritative analysis** over exactly those inputs,
   through `analyze_lease_level_acquisition_with_business_plan` -- the same
   entry point the analyze route calls. No second analysis pathway exists;
3. treats that result as the **frozen Anchor comparison** for this export;
4. **writes nothing**;
5. proves the read-only property by database byte and `iterdump` comparison
   (Section 10).

**There is therefore no "saved analysis missing" state and no
snapshot-staleness state for Lease-Level.** The export analyses the saved state
it reads. Its refusal vocabulary says so: `analysis_missing` and
`analysis_stale` do not exist in it, and two codes exist that the other two
exports have no use for.

Unsaved browser edits still block the action in the UI, because only saved
inputs are exported (Section 9).

### 2.1 The workbook says so, on every sheet that makes the claim

The decision above is not only a server-side fact; it is something the
workbook itself asserts in front of the analyst. Four places in the shared
builder describe where Anchor's numbers came from, and their defaults describe
Quick's and Detailed's **stored** snapshot:

| Where | Quick / Detailed (default) | Lease-Level (override) |
| --- | --- | --- |
| Summary, "Status at export" | "Saved Deal; saved analysis current for the saved inputs" | "Saved Deal; Anchor analysis recalculated at export from the saved inputs" |
| Anchor Results, title note | "...saved with this Deal's current analysis" | "...at export from this Deal's saved inputs" |
| Audit Metadata, "Source" | "The saved Anchor Deal and its current saved analysis..." | "The saved Anchor Deal. Anchor reran the authoritative Lease-Level analysis at export from the saved inputs and Business Plan. The analysis fingerprint identifies those saved inputs." |
| Anchor Results, debt-balance note | "The saved analysis records the loan balance only at the sale..." | "Anchor's analysis records the loan balance only at the sale... the monthly payment that analysis produced..." |

They are four **class attributes** on `_AuditWorkbookBase`
(`STATUS_AT_EXPORT`, `ANCHOR_RESULTS_NOTE`, `AUDIT_SOURCE_NOTE`,
`DEBT_BALANCE_NOTE`), stated together beside the other mode-specific copy,
rather than four conditionals scattered through the builder: the claim each
sheet makes is then reviewable in one place. The Lease-Level Summary note also
describes a saved *Deal* rather than a saved *analysis*.

**Why this is not cosmetic.** Every figure in an audit workbook is offered on
the authority of its stated source. A workbook that tells an analyst its
Anchor column was "saved with this Deal's current analysis" describes an
artifact that does not exist for this mode, and invites the reader to trust a
provenance the product never had. What is still true is what these strings now
say: the *inputs* are saved, the fingerprint identifies those inputs, and
Anchor's values are constants no Working Input can move.

`test_excel_export_3_lease_level_audit.py` reads every literal string in every
golden workbook and fails on any phrase asserting a persisted analysis, and
separately pins that Quick and Detailed still carry the shared defaults.

## 3. Architecture

| Layer | File | Role |
| --- | --- | --- |
| Store (read only) | `src/anchor/deals/store.py` -- `get_lease_level_export_provenance` | Reads the Deal and every typed child record in one connection, with its canonical analysis fingerprint. Nothing written; no analysis run. |
| Export | `src/anchor/exports/excel/source.py` | Eligibility and typed refusals; re-runs the authoritative analysis and builds `LeaseLevelAuditSource`. |
| Export | `src/anchor/exports/excel/_workbook.py` | The shared workbook: presentation, Inputs, the below-NOI model, debt, equity, returns, IRR, Anchor Results, Checks, Summary and Audit Metadata. |
| Export | `src/anchor/exports/excel/lease_level_audit.py` | Lease-Level's own part: the rent roll, the rollover lattice, the monthly schedules, the annual projection and its checks. |
| Export | `src/anchor/exports/excel/filenames.py` | Filename sanitisation and `Content-Disposition`. |
| API | `src/anchor/api.py` | `GET /deals/{deal_id}/exports/lease-level.xlsx`. |
| Web | `web/src/api.ts`, `App.tsx` | The Lease-Level client and its arm of the mode-routed export action. |

Dependency direction is unchanged: the export package consumes engine and
leasing contracts and the stored-Deal read. No production module except
`anchor.api` imports `anchor.exports`, so no workbook formula can feed an
application result.

### 3.1 What the export module may and may not do

`lease_level_audit.py` reads the leasing package for exactly two things:

- **`resolve_market_leasing`**, the one D0 Section 24.5 precedence authority,
  so the override rule is the package's own and cannot drift here;
- the **calendar and the contract enums**, so month identity and lease
  structure are not restated.

It calls **no** analysis entry point and **no** leasing builder that produces
dollars -- `test_excel_export_3_architecture.py` pins that by AST inspection.
Every financial figure in the workbook is either an Excel formula or a frozen
Anchor constant.

## 4. Why the rollover lattice is laid out, not looked up

Anchor's recursive rollover is a probability-mass state machine over
*rollover-event states* keyed by expiration period (D2 Section 5.5). A
worksheet cannot create a row, so the *set* of events must be known before any
of them is priced.

It is knowable, by integer arithmetic alone. For a state at period `p` and
branch `b`:

```
c      = p + 1 + floor(D_b)
last   = c + T_b - 1
       = p + floor(D_b) + T_b
```

so the advance `delta_b = floor(D_b) + T_b` is **independent of `p`**. The
reachable states are therefore a lattice fixed by the seed, the two branch
deltas and the horizon, and `_reachable_states` walks it with the same rules
the propagation core applies: a state is processed only when
`1 <= p < horizon`, and a child at or beyond the horizon contributes but seeds
nothing.

`test_planned_rollover_events_are_exactly_the_engine_s` asserts, on **every**
golden case, that this set is exactly the set of
`parent_expiration_period`s Anchor's own state machine processes.

**Excel computes every mass itself.** On the `Rollover` sheet each event row
carries:

```
state mass   = seed + SUMIFS(event masses above, successor expiries above, p)
event mass   = state mass x branch weight
```

Every contributor to a state expires strictly earlier than it, so the SUMIFS
ranges end above the current state's own rows: the chain resolves in one pass
and **no formula is circular**. Merging is what the SUMIFS already does -- two
paths reaching one period add their mass and nothing else; no rent, term, date
or rate is averaged.

Both branches are laid out for every state whatever the renewal probability,
so `p = 0` and `p = 1` produce a zero-mass row rather than a different layout.
That is exactly equivalent in IEEE-754 (`mass x 0.0` is `0.0`, `mass x 1.0` is
`mass`) and it is what lets the renewal probability stay editable.

### 4.1 Term and downtime are structural

Because they set the lattice, `renewal_term_months`, `new_term_months`,
`renewal_downtime_months`, `new_downtime_months` and
`initial_lease_up_months` are **disclosed but fixed** -- locked, with a status
saying why -- exactly as the hold period is in Excel Export 1 and 2 for setting
the period columns.

Every other leasing assumption stays an editable Working Input: market rent and
its growth, the renewal spread and explicit renewal level, renewal probability,
successor escalation, free rent, TI per SF, LC per cent, and the expense stops.
**None of them can move a state**, so editing one is always honest.

## 5. Workbook contract (`anchor.excel.lease-level-formula-audit/1`)

Fourteen sheets, in order:

`Summary`, `Inputs`, `Suites`, `Leases`, `Rollover`, `Monthly Leasing`,
`Monthly Recoveries`, `Monthly Property`, `Annual Projection`, `Debt Schedule`,
`Equity Cash Flow`, `Anchor Results`, `Checks`, `Audit Metadata`.

**Why not the published eight.** Quick and Detailed model a property-level
operating statement, which fits eight sheets. A rent roll does not: the
calculation chain runs through per-suite, per-event and per-month detail, and
flattening it would hide exactly the steps this export exists to show. The six
extra sheets are the chain's own stages, in order, so a reader can follow one
suite from its lease abstract to its contribution to exit NOI. `Annual
Projection` takes the structural place `Operating Projection` holds in the
other two exports: it carries the annual NOI row and the below-NOI block.

- **Inputs.** The published `Assumption | Original Export | Working Input |
  Units | Status` contract, and the **only** editable surface in the workbook.
  It holds the acquisition and debt terms, the property operating inputs, the
  property-default market leasing assumptions, one complete section per suite
  carrying a full override, and the Business Plan by year. A suite with only a
  rent-level override (D0 Section 24.1's one exception) gets that single row.
- **Suites.** Every suite, its area, its pro-rata share, its opening state and
  the market leasing assumptions it resolved to -- each one a formula reading
  the Inputs row that won under the precedence rule, so which record applied is
  visible in the cell.
- **Leases.** The in-place rent roll as saved, including the **raw, unclamped**
  first and last rent periods, so a lease that commenced before the analysis
  start visibly keeps its own escalation clock (failure mode FM-5).
- **Rollover.** Every event, its mass, its timing, its pricing, its full-term
  face rent and its TI and LC.
- **Monthly Leasing.** Per suite: the in-place lease's own rows, then one
  block per line item (occupancy factor, free-rent abatement, contractual base
  rent, contractual activity, TI, LC) with one row per rollover event. Then a
  contiguous suite-totals block that weights each event by its mass.
- **Monthly Recoveries.** The one recoverable pool, then one row per lease and
  per event, then suite totals.
- **Monthly Property.** The complete statement by canonical month.
- **Annual Projection.** Years 1..H and the forward Year H+1 window, then the
  below-NOI block.

Presentation is Excel Export 1's, unchanged: Arial 10; gridlines hidden; navy
section bars; blue editable inputs; black same-sheet calculations; green
cross-sheet reads; gray frozen Anchor values; negatives in parentheses, zero as
a dash; no merged cells, macros, external links, data connections, `INDIRECT`,
`OFFSET` or volatile functions; every sheet protected without a password,
formulas never hidden; identifying columns and headers frozen, and filters on
the long-form schedules.

## 6. Financial-convention mapping

Restating the D0-D4 authorities, which govern on any discrepancy.

| Convention | Anchor | Workbook |
| --- | --- | --- |
| Market rent | `market_rent_psf x (1+g)^floor((m-1)/12)` | same, on the resolved suite cells |
| Renewal pricing | explicit `renewal_rent_psf` grown to `c`, else `MarketRent(c) x (1+spread)` | the same precedence, emitted per suite |
| New-tenant pricing | `MarketRent(c)`, never a renewal spread | same |
| Successor commencement | `c = e + 1 + floor(D)` | `=p+1+FLOOR(D,1)` |
| Successor expiry | `c + T - 1` | same |
| Occupancy factor | `0` outside the term, `1-frac(D)` at `c`, `1` after | same |
| Free rent | **sequential** waterfall: `min(O_m, remaining)` | a running `MIN(O, F - SUM(earlier))` along the row |
| Cash rent | `face x (O_m - abatement_m)` | same |
| Contractual rent | `psf x (1+esc)^floor((m-c)/12) x area / 12` | same, dividing by 12 once, last |
| TI | `ti_psf x area`, at the first month with `O > 0` | same |
| LC | `lc_pct x` full-term contractual **face** rent | the term's escalation steps, summed |
| Recovery | `O_m x f(share x pool_m, stop)` by lease type | same, three explicit branches |
| Recoverable pool | `ratio x fixed operating expenses` | same; the management fee is never in it |
| Credit loss | `pct x (cash rent + recoveries)` | same -- not on other income |
| EGI | `cash rent + recoveries + other income - credit loss` | same |
| Management fee | `EGI x pct`, on EGI **including** recoveries | same, never grown from a Year 1 amount |
| NOI | `EGI - fixed opex - fee` | same |
| Exit NOI | sum of monthly NOI over months `12H+1 .. 12H+12` | `=SUM(...)` over that exact span |
| TI/LC | below NOI, hold years only | one below-NOI line; the forward window is disclosed only |

### 6.1 The three recovery proofs

- **The pool excludes the management fee.** The pool row reads the *fixed*
  operating expense total only; the fee row is below it and feeds nothing
  upward. This is what makes the dependency graph acyclic, and it is why the
  workbook contains no circular reference.
- **The fee uses EGI including recoveries.** The fee formula reads the EGI
  cell, which includes the recovery line. A mutation replacing it with cash
  rent alone fails the guarding row.
- **Recovery income is not netted against expenses.** Recoveries are a revenue
  line inside EGI; the expense lines are gross. The `Identity: EGI` rows prove
  the composition month by month.

Credit loss follows the approved Lease-Level basis (cash rent and recoveries),
which its own identity row proves for every month.

### 6.2 The forward window

Years 1..H and the complete forward Year H+1 window are aggregated from the
*same* monthly series. Exit NOI is the sum of months `12H+1` through `12H+12` --
never Year H grown, never twelve times one month. The forward window's TI and
LC are disclosed on their own line and are **excluded from seller cash flow**
by construction: the below-NOI block runs hold years only. They also never
reduce exit NOI, because no leasing capital ever entered NOI.

Owner Business Plan capital stays a channel separate from the rent roll's TI
and LC: both reach owner cash flow, neither is merged into the other.

## 7. Eligibility and refusals

| Condition | HTTP | `detail.code` |
| --- | --- | --- |
| Deal does not exist | 404 | `deal_not_found` |
| Quick or Detailed Deal | 422 | `unsupported_operating_mode` |
| Saved Lease-Level inputs invalid or internally inconsistent | 409 | `lease_level_inputs_invalid` |
| Forward exit NOI not positive (HD-D4-7, via the existing typed validation) | 422 | `terminal_value_not_capitalizable` |
| The Deal is larger than an Excel worksheet | 422 | `excel_capacity_exceeded` |
| Any other failure while building | 500 | `export_generation_failed` |

Every refusal is `{"detail": {"code", "message"}}`; messages say what to do and
never carry a path, an exception string or an internal id.

`LeaseLevelAuditRefusalCode` is its own enum. Three tokens coincide with the
other two exports because they mean the same thing on the wire; the rest are
Lease-Level's own. The non-positive forward exit NOI is reported separately
from ordinary input defects because it is a *modelled outcome of a valid rent
roll*, not a malformed input -- telling an analyst their inputs are broken when
the building simply does not cover its costs would be wrong.

A successful response is
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` with
`Content-Disposition: attachment; filename="<Deal Name> - Lease-Level
Underwrite Audit.xlsx"; filename*=UTF-8''...`, `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`. The filename is sanitised by the same
independent function the other two exports use.

## 8. Excel capacity

No arbitrary commercial limit on suite count or hold period is imposed. The
only bound is the one the file format actually has, and it is **calculated
before anything is written**:

```
columns      = 5 + (12H + 12)
leasing rows = 40 + sum over suites of (3 + 2 if occupied + 6 x (events + 1))
                  + suites x 7
recovery rows= 40 + sum over suites of (3 + 1 if occupied + events) + suites
```

`plan_lease_level_workbook` computes these from the structural plan and refuses
with `excel_capacity_exceeded` if either exceeds Excel's 1,048,576 rows or
16,384 columns, naming what to change. `test_excel_export_3_lease_level_audit.py`
tests the column limit **at the boundary**: the largest hold period that fits is
accepted and the next one is refused. The plan is also asserted to be an
over-estimate of the real sheet, so a workbook that fits is never refused.

## 9. Browser behaviour

The existing "Export Excel audit (.xlsx)" action in the header's "More deal
actions" menu now routes all three modes. Lease-Level's arm reads **only** the
Lease-Level workspace's own saved id, dirty flag and analysing flag -- never
Quick's or Detailed's.

- **unsaved Deal**: disabled, "Save this Deal to export the Excel audit
  workbook."
- **unsaved changes**: disabled, explaining that only saved inputs are
  exported.
- **analysis running**: disabled.
- **saved and clean**: allowed. It deliberately does **not** wait for an
  in-browser result, because Lease-Level persists none and the server analyses
  the saved state itself. Requiring one would block an export the server can
  serve, and would imply a persisted analysis that does not exist.
- **success**: a status line naming the downloaded file.
- **refusal**: the server's message, verbatim.
- The success line is shown only while the action is available, so it never
  sits beside unsaved edits or another Deal.

`web/src/leaseLevelAuditExport.test.tsx` holds the **mode-isolation guard**: it
opens a Lease-Level, a Detailed and a Quick Deal in one app, exports each, and
asserts the exact set of export requests -- one per mode, each to its own path
and carrying its own deal id. A handler reading another workspace's state would
send the wrong request and fail there.

## 10. Read-only proof

- `get_lease_level_export_provenance` calls `_read_deal` and the fingerprint
  helper, and no writer (pinned by AST inspection).
- The route writes nothing; the App flow asserts no non-`GET` request is made.
- Two exports of the same Deal leave the database's `iterdump` **and its bytes**
  identical, and leave `updated_at` untouched.
- Schema stays v14. No DDL, no migration, and no `analysis_snapshot` column is
  added to `lease_level_deals` -- asserted against the diff itself.

## 11. Security

User-authored text -- Deal name, suite ids and labels, tenant names, lease ids,
subtype and Business Plan descriptions -- is written with `write_string`, and
the workbook is opened with `strings_to_formulas`, `strings_to_numbers` and
`strings_to_urls` off, so `=`, `+`, `-` and `@` text stays text (tested with
hostile values, including after a real Excel round trip). No macros, external
links, connections or hidden formulas. The filename is sanitised independently.
Refusals and generation failures expose no path or exception text, and no local
path or environment value appears anywhere in the package.

## 12. Dependencies

None added. XlsxWriter (already a dependency) remains the only writer; openpyxl
remains the reader in tests. `pyproject.toml` is asserted byte-identical to the
baseline. No desktop application is a production dependency.

## 13. Native recalculation evidence

Desktop Excel 16 (COM) via `tests/excel_native_recalc.py` (opt-in with
`ANCHOR_EXCEL_NATIVE_RECALC=1`; it records and terminates only the Excel
process it starts). `tests/test_excel_export_3_native_recalc.py`:

- **23 golden cases, 68,248 reconciliation rows, every one passing.** The
  matrix covers an occupied suite with no in-hold rollover; multiple suites;
  fractional-month downtime at the commencement boundary; free rent on both
  branches; contractual rent steps; renewal probability 0%, 100% and blended;
  new-tenant downtime; a full suite-level market-leasing override and a
  rent-level-only override; initial vacancy `HOLD_VACANT` and
  `MARKET_LEASE_UP`; all three recovery structures and a Modified Gross
  successor with a stop; partly recoverable expenses; credit loss and the
  management fee; TI and LC inside the hold and in the forward window; revenue
  and expense growth diverging; a Business Plan at closing, during and after
  the hold; amortizing, interest-only and all-cash debt; a ten-year hold with
  several rollover generations; and hostile text. No Excel error and no `####`
  cell in any workbook; every formula still a formula after Excel saves.
- **Independent read-back.** Excel's own suite-month, recovery-month,
  property-month, annual, exit, debt-schedule and return cells are compared
  with Anchor's engine in Python without consulting a single Checks row, so a
  row that compared a cell with itself could not hide.
- **Mutation proofs.** A suite's cash rent inflated; free rent dropped; a
  rollover event's probability mass forced to 1; a suite's recoveries halved; a
  fixed expense grown at the wrong rate; the management fee taken on cash rent
  alone rather than EGI; a leasing cheque dropped; exit NOI approximated by
  growing Year H. Each fails the row that guards it while an unrelated row
  still passes. A deleted formula reads `Missing`, never zero; an injected
  `1/0` reads `Excel error` and the counts survive it.
- **Perturbation matrix.** Market rent, expense growth, the management fee and
  the renewal probability, each edited in turn: the workbook reads modified,
  every row reads `Not like-for-like`, the lines each input feeds move and an
  independent line does not, and the in-place lease's own months are untouched
  by a probability change. Restoring a value returns every check to passing.

## 14. Manual acceptance

1. Open a saved Lease-Level Deal; export; confirm the filename.
2. Open the workbook in Excel: Summary shows "Excel formulas recalculated:
   Yes" and every check passed.
3. Walk every sheet for layout and clarity, at normal zoom.
4. Read one suite end to end: its lease on `Leases`, its resolved assumptions
   on `Suites`, its events on `Rollover`, its months on `Monthly Leasing`, its
   reimbursement on `Monthly Recoveries`, and its contribution to `Monthly
   Property`.
5. Confirm Year H+1 is present, labelled the forward exit window, and built by
   the same formulas as every hold year -- and that its TI and LC are disclosed
   without entering seller cash flow.
6. Edit a Working Input (for example market rent): confirm the lines it feeds
   move, an independent line does not, the Inputs row says Modified, Checks
   says Not like-for-like, and Anchor Results is unchanged; restore it and
   confirm every check passes.
7. Confirm a term or downtime cell is locked, and says why.
8. Confirm unsaved changes, an unsaved Deal, a Quick Deal and a Detailed Deal
   cannot be exported through this route.
