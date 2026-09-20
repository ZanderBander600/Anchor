# Excel Export 2: Detailed Underwrite Formula Audit

Status: **implemented, merged in PR #46 (`fe70d40`), and human accepted.**
Implementation baseline: `main` at `b9437e4`
(Excel Export 1 merged in PR #44, its presentation polish in PR #45; schema
v14). Risk tier: 1 (the workbook independently reproduces the whole Detailed
operating model, debt, exit value, equity cash flow, equity multiple and IRR),
with Tier 2 eligibility and stale-state behaviour and Tier 3 export
interaction. No financial calculation, fingerprint, stored analysis, schema or
AI behaviour changes.

## 1. Scope

A saved, currently analysed **Detailed Underwrite** Deal can be downloaded as
one `.xlsx` workbook that is both a readable underwriting deliverable and an
independent, formula-level audit of Anchor's Detailed engine.

Explicitly excluded: Lease-Level, Investments, Scenarios, Strategies, Capital
Structure, Partnership Waterfalls and Asset Management exports; P7.10; any
schema, fingerprint, AI or financial-engine change. Quick Underwrite keeps its
own workbook (Excel Export 1), unchanged.

### 1.1 The eleven Detailed operating inputs

`DetailedOperatingInputs` defines **eleven** fields, and the field tables,
formulas and validation in
`docs/detailed_operating_model_v2_1_financial_conventions.md` describe eleven.
Two sentences of that document's prose still say "twelve"; they are stale
narration, not authority. This export models the eleven the frozen class
defines and invents no twelfth. `tests/test_excel_export_2_detailed_audit.py`
pins the count against the dataclass itself.

## 2. Architecture

| Layer | File | Role |
| --- | --- | --- |
| Store (read only) | `src/anchor/deals/store.py` -- `get_detailed_analysis_provenance` | Reads a Detailed Deal and classifies its stored analysis as `CURRENT`, `MISSING` or `STALE` in one connection. One `SELECT`; nothing written. |
| Export | `src/anchor/exports/excel/source.py` | Eligibility and typed refusals; builds `DetailedAuditSource` from stored data only. |
| Export | `src/anchor/exports/excel/_workbook.py` | The shared workbook: presentation, Inputs, the below-NOI model, debt, equity, returns, IRR, Anchor Results, Checks, Summary and Audit Metadata. |
| Export | `src/anchor/exports/excel/detailed_audit.py` | Detailed's own part: its inputs, its operating statement, its checks and its words. |
| Export | `src/anchor/exports/excel/quick_audit.py` | Quick's own part, on the same base. |
| Export | `src/anchor/exports/excel/filenames.py` | Filename sanitisation and `Content-Disposition`. |
| API | `src/anchor/api.py` | `GET /deals/{deal_id}/exports/detailed-underwrite.xlsx`. |
| Web | `web/src/api.ts`, `App.tsx` | The Detailed client and the mode-routed "Export Excel audit (.xlsx)" action. |

Dependency direction is unchanged from Excel Export 1: the export package
consumes engine contracts, the pure debt functions in `anchor.engine.debt`,
the stored-Deal read and the classification labels. No production module
except `anchor.api` imports `anchor.exports`, so no workbook formula can feed
an application result. The export never resolves a Business Plan (the D6.2
single-resolver invariant holds) and never runs an `analyze_*` entry point --
it reads the saved analysis and reproduces it.

### 2.1 Why one shared base, not a mode flag

Quick and Detailed differ only in how they *produce* an NOI schedule. Both
hand the identical schedule to the single, unmodified acquisition engine
(`docs/detailed_operating_model_v2_1_architecture.md` "Quick/Detailed
Convergence"), whose seam is `OperatingProjectionLike`: `noi_by_year`,
`exit_noi`, `going_in_cap_rate`.

`_workbook.py` mirrors that seam exactly. A subclass fills the Operating
Projection sheet and publishes the same three things plus the below-NOI row
handles; every sheet after it is written by shared code, identically for both
modes. This is the project's own architecture expressed in the workbook, not
a convenience: it is why the two workbooks cannot silently disagree about
debt, sale, returns or IRR, and it is what makes the permanent Quick/Detailed
equivalence case meaningful in Excel as well as in Python.

The Quick workbook's output is **byte-for-byte identical** to `b9437e4` for
all 18 of its golden cases after this refactor, which is how the
"semantically unchanged" requirement is discharged. The only shared-code
behaviour change is additive and unreachable from Quick: a `_Check` may now
declare `guard_anchor`, which tests the *Anchor* side of a row for an Excel
error as well as the Excel side. Quick never sets it (its Anchor side is
always a frozen constant), so Quick's emitted formulas are unchanged;
Detailed's identity rows set it, because both of their sides are live
formulas.

## 3. Eligibility and refusals

The server decides eligibility from what is stored, independently of the web
client:

| Condition | HTTP | `detail.code` |
| --- | --- | --- |
| Deal does not exist | 404 | `deal_not_found` |
| Quick or Lease-Level Deal | 422 | `unsupported_operating_mode` |
| No saved analysis | 409 | `analysis_missing` |
| Saved analysis no longer matches the saved inputs/Business Plan (or is unreadable) | 409 | `analysis_stale` |
| Saved analysis cannot be reconciled with the saved inputs (envelope halves disagree, schedule lengths, zero TI/LC, final balance) | 409 | `analysis_inconsistent` |
| Hold period above 100 years (the workbook's layout limit) | 422 | `hold_period_exceeds_export_limit` |
| Any other failure while building | 500 | `export_generation_failed` |

Every refusal is `{"detail": {"code", "message"}}`; messages say what to do and
never carry a path, an exception string or an internal id. "Current" is decided
by exactly the gate `get_deal` uses (fingerprint match over the stored terms,
Detailed operating inputs and Business Plan), so an export can never call
current what the Deal Library would call stale.

`DetailedAuditRefusalCode` is its own enum spelling the same wire tokens as
Quick's. Each export owns its published contract, and neither can be changed
by editing the other; one client vocabulary still covers both.

A successful response is
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` with
`Content-Disposition: attachment; filename="<Deal Name> - Detailed Underwrite
Audit.xlsx"; filename*=UTF-8''...`, `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`. The filename is sanitised by the same
independent function Quick uses.

### 3.1 Internal consistency

`DetailedAcquisitionResults` is one envelope holding two halves written by one
engine call: the `OperatingProjection` and the `AcquisitionResults`. The export
refuses if they disagree -- if any schedule is not `hold_period` long, or if
`noi_by_year`, `exit_noi` or `going_in_cap_rate` differ between them. A
disagreement means the stored snapshot is not what it claims, and preferring
one half would hide that.

## 4. Workbook contract (`anchor.excel.detailed-formula-audit/1`)

Sheets, in order: `Summary`, `Inputs`, `Operating Projection`, `Debt Schedule`,
`Equity Cash Flow`, `Anchor Results`, `Checks`, `Audit Metadata` -- the same
eight, in the same order, as Excel Export 1.

- **Inputs.** `Assumption | Original Export | Working Input | Units | Status`.
  Original Export is the saved value (gray, locked); Working Input starts equal
  (blue, unlocked, data-validated to Anchor's exact input domains) and is the
  only column any model formula reads, through readable defined names:
  `Purchase_Price`, `Acquisition_Cost_Pct`, `Gross_Potential_Rent`,
  `Other_Income`, `Vacancy_Credit_Loss_Pct`, `Revenue_Growth`,
  `Property_Taxes`, `Insurance`, `Utilities`, `Repairs_Maintenance`,
  `Other_Operating_Expenses`, `Management_Fee_Pct`, `Expense_Growth`,
  `CapEx_Reserve`, `Loan_To_Value`, `Interest_Rate`, `Amortization_Years`,
  `IO_Period_Years`, `Financing_Fee_Pct`, `Hold_Period`, `Exit_Cap_Rate`,
  `Disposition_Cost_Pct`, `Closing_Project_Capital`. Validation matches
  `anchor.validation`: `>= 0` for the five fixed expense lines, gross potential
  rent, other income and the CapEx reserve; `0..1` for vacancy, the management
  fee, LTV, and the three cost percentages; `> -1` for revenue and expense
  growth; `> 0` for purchase price and exit cap rate. Hold period is fixed (it
  sets the period columns) and post-hold capital is disclosure only. Asset Type
  and the analyst-authored subtype are metadata on Summary and Audit Metadata,
  never inputs. The Business Plan appears as annual project capital and owner
  expenses (Original and Working per year) plus its saved items for reference,
  which Excel resolves independently with `SUMIFS`/`SUMPRODUCT`.
- **Operating Projection.** Years 1..H **and Year H+1**, every line built by
  the identical formulas: revenue and expense growth factors, gross potential
  rent, other income, vacancy and credit loss, effective gross income, the five
  fixed expense lines, the management fee, total operating expenses, NOI and
  the change from the prior year. Then, below NOI, the CapEx reserve, the
  Business Plan outflows and the unlevered owner cash flow; then the going-in
  cap rate.
- **Debt Schedule, Equity Cash Flow, Anchor Results, Checks, Summary, Audit
  Metadata.** As Excel Export 1, plus: Anchor Results carries the saved
  Detailed operating schedule for Years 1..H, and Checks adds every operating
  line for every year and the operating-statement identities.

Presentation is Excel Export 1's, unchanged, including the header-separation
rules merged in PR #45: Arial 10; gridlines hidden; navy section bars; blue
editable inputs; black same-sheet calculations; green cross-sheet reads; gray
frozen Anchor values; negatives in parentheses, zero as a dash; no merged
cells, macros, external links, data connections, `INDIRECT`, `OFFSET` or
volatile functions; every sheet protected without a password, formulas never
hidden; label columns frozen.

## 5. Financial-convention mapping

Restating `docs/detailed_operating_model_v2_1_financial_conventions.md`, which
governs on any discrepancy. For operating year `y`, `1 <= y <= H+1`:

| Convention | Anchor | Workbook |
| --- | --- | --- |
| Revenue growth | `GPR_y = GPR_1 x (1+revenue_growth)^(y-1)`; other income the same rate | `=Gross_Potential_Rent*<revenue factor>`, factor `=(1+Revenue_Growth)^(year-1)` |
| Vacancy | `Vacancy_y = GPR_y x vacancy_pct`, on GPR **only** | `=<GPR cell>*Vacancy_Credit_Loss_Pct` |
| EGI | `EGI_y = GPR_y - Vacancy_y + OtherIncome_y` | same three cells |
| Fixed expenses | each of five lines `= Line_1 x (1+expense_growth)^(y-1)` | `=<line>*<expense factor>` |
| Management fee | `Fee_y = EGI_y x management_fee_pct` -- scaled from EGI, never grown | `=<EGI cell>*Management_Fee_Pct` |
| Total opex | sum of the five fixed lines and the fee | `SUM` of the six contiguous rows |
| NOI | `NOI_y = EGI_y - TotalOpex_y` | same two cells |
| Projection horizon | `noi_by_year = NOI_1..NOI_H`; `exit_noi = NOI_(H+1)`, run through the **complete** schedule | Year H+1 is a full column of the same formulas |
| Below NOI | CapEx, debt service, acquisition costs, financing fees, disposition costs | all below the NOI row, in the cash-flow assembly |
| DSCR | `NOI_y / ADS_y`, on NOI before capital reserves | same |
| Occupancy | never read by Detailed | absent from the model |

Everything downstream of `noi_by_year`/`exit_noi` is the Underwriting V2
contract Excel Export 1 already documents, reproduced by the same shared
formulas.

**The exit year is the load-bearing case.** The conventions forbid
approximating `exit_noi` by applying a blended growth rate to `NOI_H`, and that
becomes visible the moment revenue growth and expense growth diverge. The
workbook projects Year H+1 through every line. A mutation test replaces the
forward-year NOI with `NOI_H x (NOI_H / NOI_(H-1))` on a divergent-growth case
and requires the exit row to fail.

## 6. Reconciliation and tolerances

`Anchor Results` holds the saved analysis as constants (gray, never formulas),
`Unavailable` where Anchor reports none. `Checks` compares it with the Excel
model row by row: `Metric | Anchor Result | Excel Result | Difference |
Tolerance | Status | Excel location | Open`.

Coverage, for a hold of `H`:

- every one of the twelve Detailed operating lines, for every year 1..H,
  against the saved `OperatingProjection` -- not only the NOI they add up to;
- exit NOI against the saved `exit_noi`;
- five operating-statement **identities** for every year including H+1
  (vacancy, EGI, management fee, total opex, NOI);
- CapEx, Business Plan capital and owner expenses, property cash flow and
  unlevered owner cash flow; the going-in cap rate;
- acquisition and financing amounts; the monthly payment; annual debt service,
  ending balances and DSCR; headline and minimum DSCR; Year 1 debt yield;
- exit value, disposition costs, debt payoff, net sale proceeds;
- levered and unlevered cash flows for every period, equity cash flow,
  cumulative distributions, cash-on-cash and unlevered cash yield;
- total equity invested, cash returned, profit, equity multiple, both IRRs and
  both IRR availability states;
- Business Plan totals and Excel's independent resolution of the saved items;
- hold period and equity cash-flow period count, exactly.

190 rows for the five-year golden case; 345 for a ten-year hold.

### 6.1 The exit year's individual lines

`OperatingProjection` stores line items for Years 1..H only -- the saved
analysis keeps the forward year's NOI as `exit_noi` and nothing else. So the
exit year's revenue and expense lines have no Anchor value to compare against,
and the workbook says so rather than inventing one. They are proved by
identity instead: the same five conventions, restated as expressions over the
sheet's own cells. For Years 1..H those identities are a second, independent
proof beside the Anchor reconciliation; for Year H+1 they are what proves the
forward year was actually projected.

Identity rows carry `guard_anchor`, so an error on either side reads as
`Excel error` rather than escaping into the pass/fail counts.

### 6.2 Tolerances

Unchanged from Excel Export 1, for the same reason: both engines use IEEE-754
doubles on the same unrounded inputs and differ only in operation order.

- currency: `MAX(1e-6, 1e-10 x |Anchor|)`;
- ratios, rates, multiples: `1e-10`;
- IRR: `1e-7` (Excel's documented `IRR` precision);
- hold period, period count, IRR availability: exact.

A status passes only with two numbers inside tolerance, or `Unavailable` on
both sides. A blank source reads `Missing`; an error reads `Excel error`; with
modified Working Inputs every row reads `Not like-for-like` and the sheet says
why.

## 7. Calculation and cached values

`fullCalcOnLoad="1"` with automatic calculation. Every formula is written with
a pessimistic cached value: blank, or `Not recalculated` for statuses. Nothing
is copied from Anchor into a formula cache, so an unrecalculated workbook shows
no pass anywhere (tested), and only a real spreadsheet engine can produce one.
The recalculation canary is a formula whose only text is `"Yes"` and whose
cached value is `Not recalculated`.

## 8. Dependencies

None added. XlsxWriter (already a dependency for Excel Export 1) remains the
only writer and is now imported by `_workbook.py` alone; openpyxl remains the
reader in tests. No desktop application is a production dependency.

## 9. Native recalculation evidence

Desktop Excel 16 (COM) via `tests/excel_native_recalc.py` (opt-in with
`ANCHOR_EXCEL_NATIVE_RECALC=1`; it records and terminates only the Excel
process it starts, never a user's). `tests/test_excel_export_2_native_recalc.py`:

- **20 golden cases, 4,061 reconciliation rows, every one passing.** The
  matrix covers the frozen V2.1 golden case; revenue outgrowing expenses and
  the reverse, at 6, 7 and 10-year holds; zero, negative and high growth on
  both rates; zeroed other income and expense lines; no vacancy and total
  vacancy; no management fee and a fee that is the entire expense load; IO
  beyond the hold, no IO, all cash, zero interest, full leverage with no
  equity; a Business Plan with items at closing, inside the hold and after it;
  and a deal with no positive levered cash flow. No Excel error in any cell;
  every formula still a formula after Excel saves.
- **Independent read-back.** Excel's own operating cells are compared with
  Anchor's engine in Python without consulting a single Checks row, so a row
  that compared a cell with itself could not hide. The forward year's NOI is
  read the same way and equals `exit_noi`.
- **Mutation proofs.** Vacancy taken on EGI instead of GPR; the management fee
  grown like a fixed expense; exit NOI approximated by a blended rate on a
  divergent-growth case; a deleted formula; a formula corrupted to `1/0`. Each
  fails the row that guards it while an unrelated row still passes, and the
  counts survive an error rather than being voided by it.
- **Perturbation matrix.** Revenue growth, expense growth, vacancy, the
  management fee, one fixed expense, the exit cap rate, leverage and one
  Business Plan year, each edited in turn: the lines each feeds move, an
  independent line does not, and the two below-NOI inputs leave the whole
  operating statement untouched. Restoring a value returns every check to
  passing.
- **Convergence in the spreadsheet.** The Detailed workbook's equity multiple,
  both IRRs and total profit equal the Quick workbook's on the case whose NOI
  schedules are the same series.
- A hostile Deal name is still text after Excel opens and saves the file.

## 10. Browser behaviour

The existing "Export Excel audit (.xlsx)" action in the header's "More deal
actions" menu is now mode-routed:

- **Quick** uses the Quick endpoint, unchanged.
- **Detailed** uses the Detailed endpoint, gated on the Detailed workspace's
  own saved id, dirty flag, analysing flag and result -- never the Quick
  workspace's. It is disabled, with the reason attached by `aria-describedby`,
  when the Deal is unsaved, has unsaved changes, is analysing, or has no
  current result.
- **Lease-Level** shows the action disabled with an honest, mode-specific
  explanation rather than hiding it: an analyst who has seen it in the other
  two modes should be told it does not exist here.

A server refusal is shown verbatim as an alert; a success as a status line
naming the file. The outcome line is shown only while the action is available,
so it never sits beside unsaved edits. Exporting writes nothing.

Verified in a real browser against an isolated database: the Detailed deal
downloads as `Rivermark Apartments - Detailed Underwrite Audit.xlsx` and
recalculates 267/267 checks in Excel with no errors and 2,636 formulas still
formulas; the Quick deal routes to the Quick endpoint and the Detailed deal to
the Detailed one, each only to its own; unsaved edits, an unanalysed Deal and
Lease-Level are refused with their exact messages; the "Exported" line
disappears on an unsaved edit; the action works at 1440px and 390px with no
horizontal overflow and no console errors; and the database file's hash is
identical before and after.

## 11. Security

User-authored text (Deal name, subtype, Business Plan descriptions) is written
with `write_string`, and the workbook is opened with `strings_to_formulas`,
`strings_to_numbers` and `strings_to_urls` off, so `=`, `+`, `-` and `@` text
stays text (tested with hostile values, including after a real Excel round
trip). No macros, external links, connections or hidden formulas. The filename
is sanitised independently. Refusals and generation failures expose no path or
exception text, and no local path or environment value appears anywhere in the
package.

## 12. Read-only proof

The Detailed provenance read executes one `SELECT` beside `_read_deal` and
calls no writer (pinned by AST inspection). The route writes nothing. Two
exports of the same Deal leave the database's `iterdump` **and its bytes**
identical, and leave `updated_at` and the stored snapshot untouched. Schema
stays v14; no DDL and no migration was added.

## 13. Manual acceptance

1. Open a saved, analysed Detailed Deal; export; confirm the filename.
2. Open the workbook in Excel: Summary shows "Excel formulas recalculated:
   Yes" and every check passed.
3. Walk every sheet for layout and clarity, at normal zoom.
4. Read the Operating Projection as an operating statement: confirm the
   twelve lines, and that Year H+1 is present, labelled exit-only, and built
   like every other year.
5. Edit a Working Input (for example expense growth): confirm the expense
   lines and NOI move, revenue does not, the Inputs row says Modified, Checks
   says Not like-for-like, and Anchor Results is unchanged; restore it and
   confirm every check passes.
6. Confirm unsaved changes, an unanalysed Deal, a Quick Deal and a Lease-Level
   Deal cannot be exported through this route.

## 14. Human acceptance and feature closeout

On 2026-09-20 the human explicitly accepted Excel Export 2. The final isolated
acceptance sweep against merged `main` at `1afd003` completed a Detailed
Underwrite audit export and confirmed the mode-specific success status and
sanitized `.xlsx` filename.

Excel Export 2 is therefore **complete and accepted**. This record changes
status only and starts no later export gate.
