# Excel Export 1: Quick Underwrite Formula Audit

Status: **implemented, merged, and human accepted.** Core work merged in PR
#44, with presentation polish merged in **PR #45 at `b9437e4`**. Implementation
baseline: `main` at `51c5bf1` (Asset Types 1
merged, schema v14). Risk tier: 1 (the workbook independently reproduces NOI,
debt, exit value, equity cash flow, equity multiple and IRR), with Tier 2
eligibility and stale-state behaviour. No financial calculation, fingerprint,
stored analysis, schema or AI behaviour changes.

**Later change.** Excel Export 2
(`docs/architecture/EXCEL_EXPORT_2_DETAILED_FORMULA_AUDIT.md`) moved the
presentation, the below-NOI model, the debt and equity sheets and the
reconciliation into a shared `_workbook.py` that both exports are built on, and
gave the "Export Excel audit (.xlsx)" action a second mode. This workbook's
*output* is unchanged: all 18 golden cases below are byte-for-byte identical to
`b9437e4`, which is how that refactor was accepted. Section 2's file table and
Section 10's Quick-only menu note describe the original gate; the Quick
behaviour they describe still holds, and Detailed is now offered beside it.

## 1. Scope

A saved, currently analysed **Quick Underwrite** Deal can be downloaded as one
`.xlsx` workbook that is both a readable underwriting deliverable and an
independent, formula-level audit of Anchor's Quick engine.

Explicitly excluded: Detailed Underwrite, Lease-Level, Investments, Scenarios,
Strategies, Capital Structure, Partnership Waterfalls and Asset Management
exports; P7.10; any change to Asset Types 1.

## 2. Architecture

| Layer | File | Role |
| --- | --- | --- |
| Store (read only) | `src/anchor/deals/store.py` -- `get_quick_analysis_provenance` | Reads a Quick Deal and classifies its stored analysis as `CURRENT`, `MISSING` or `STALE` in one connection. One `SELECT`; nothing written. |
| Export | `src/anchor/exports/excel/source.py` | Eligibility and typed refusals; builds `QuickAuditSource` from stored data only. |
| Export | `src/anchor/exports/excel/quick_audit.py` | The workbook (XlsxWriter). |
| Export | `src/anchor/exports/excel/filenames.py` | Filename sanitisation and `Content-Disposition`. |
| Export | `src/anchor/exports/excel/provenance.py` | Anchor version and source commit (identifiers only). |
| API | `src/anchor/api.py` | `GET /deals/{deal_id}/exports/quick-underwrite.xlsx`; `Content-Disposition` exposed to the web client through CORS. |
| Web | `web/src/api.ts`, `App.tsx`, `components/DealHeader.tsx`, `index.css` | The Quick-only "Export Excel audit (.xlsx)" action. |

Dependency direction: the export package consumes engine contracts
(`AcquisitionResults`, `IrrStatus`), the pure debt functions in
`anchor.engine.debt`, the stored-Deal read and the classification labels. No
production module except `anchor.api` imports `anchor.exports`, so no workbook
formula can feed an application result. The export never resolves a Business
Plan (the D6.2 single-resolver invariant holds); the annual totals it shows are
the saved analysis's own.

## 3. Eligibility and refusals

The server decides eligibility from what is stored, independently of the web
client:

| Condition | HTTP | `detail.code` |
| --- | --- | --- |
| Deal does not exist | 404 | `deal_not_found` |
| Detailed or Lease-Level Deal | 422 | `unsupported_operating_mode` |
| No saved analysis | 409 | `analysis_missing` |
| Saved analysis no longer matches the saved inputs/Business Plan (or is unreadable) | 409 | `analysis_stale` |
| Saved analysis cannot be reconciled with the saved inputs (lengths, zero TI/LC, final balance) | 409 | `analysis_inconsistent` |
| Hold period above 100 years (the workbook's layout limit; Anchor's input domain has none) | 422 | `hold_period_exceeds_export_limit` |
| Any other failure while building | 500 | `export_generation_failed` |

Every refusal is `{"detail": {"code", "message"}}`; messages say what to do and
never carry a path, an exception string or an internal id. "Current" is decided
by exactly the gate `get_deal` uses (fingerprint match), so an export can never
call current what the Deal Library would call stale. A successful response is
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` with
`Content-Disposition: attachment; filename="<Deal Name> - Quick Underwrite
Audit.xlsx"; filename*=UTF-8''...`, `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`.

The filename is sanitised on its own: NFKC-normalised, control and format
characters removed, `\ / : * ? " < > |` replaced by `-`, whitespace collapsed,
leading/trailing dots and spaces stripped, 100 characters kept, `Untitled Deal`
when nothing remains, and an ASCII-only `filename` beside the exact UTF-8
`filename*`.

## 4. Workbook contract (`anchor.excel.quick-formula-audit/1`)

Sheets, in order: `Summary`, `Inputs`, `Operating Projection`, `Debt Schedule`,
`Equity Cash Flow`, `Anchor Results`, `Checks`, `Audit Metadata`.

- **Inputs.** `Assumption | Original Export | Working Input | Units | Status`.
  Original Export is the saved value (gray, locked); Working Input starts equal
  (blue, unlocked, data-validated to Anchor's input domains) and is the only
  column any model formula reads, directly or through readable defined names
  (`Purchase_Price`, `Current_NOI`, `NOI_Growth`, `Hold_Period`,
  `Exit_Cap_Rate`, `Loan_To_Value`, `Interest_Rate`, `Amortization_Years`,
  `IO_Period_Years`, `Acquisition_Cost_Pct`, `Financing_Fee_Pct`,
  `Disposition_Cost_Pct`, `CapEx_Reserve`, `Closing_Project_Capital`). Hold
  period (it sets the period columns), occupancy (informational; the Quick
  engine never reads it) and post-hold capital (disclosure only) are fixed at
  export. The Business Plan appears as annual project capital and owner expenses
  (Original and Working per year) plus its saved items for reference, which
  Excel resolves independently with `SUMIFS`/`SUMPRODUCT`.
- **Operating Projection.** Years 1..H plus Year H+1: growth factor, NOI, change
  from prior year, CapEx reserve, property cash flow, Business Plan outflows,
  unlevered owner cash flow, going-in cap rate. Quick has no revenue, vacancy
  or expense lines; NOI is its input and is reconciled directly.
- **Debt Schedule.** Loan terms, the amortizing payment, an annual summary
  (beginning balance, debt service, interest, principal, ending balance, DSCR,
  minimum DSCR, Year 1 debt yield, payoff) and the complete monthly schedule
  (`12 x H` rows: phase, beginning balance, payment, interest, principal,
  ending balance).
- **Equity Cash Flow.** Years 0..H: acquisition (price, costs, fee, closing
  capital, loan proceeds, acquisition equity, closing uses/sources), operations,
  sale (gross price, selling costs, payoff, net proceeds), total and cumulative
  equity cash flow, returns, both IRRs with a visible sign-rule audit, owner
  metrics by year and the unlevered project cash flow.
- **Anchor Results.** The saved analysis as constants (gray, protected, never
  formulas), `Unavailable` where Anchor reports none, plus the frozen record of
  the exported inputs. Annual ending balances come from Anchor's own debt
  functions at export (the saved analysis records only the exit balance); the
  builder requires the final one to equal the saved balance exactly.
- **Checks.** `Metric | Anchor Result | Excel Result | Difference | Tolerance |
  Status | Excel location | Open`, 100+ rows for a five-year hold (150 for the
  seven-year QA deal), and a status block: recalculated, working inputs that
  differ, modified since export, original inputs unchanged, reconciliation
  available, counts, and the first check not passed with its location.
- **Audit Metadata.** Deal name and ID, mode, classification, generated time
  (Excel date and ISO 8601 with offset), Anchor version, source commit, analysis
  fingerprint, contract version, conventions, tolerances, stored precision and
  the Quick-only limitation. No path, environment value or database location.

Presentation: Arial 10 throughout; gridlines hidden; navy section bars; blue
editable inputs on a light fill; black same-sheet calculations; green for any
formula that reads another sheet (a mechanical rule, tested); gray frozen Anchor
values; negatives in parentheses, zero as a dash; percentages and multiples
stored as decimals; dates as Excel dates; no merged cells, macros, external
links, data connections, `INDIRECT`, `OFFSET` or volatile functions; every sheet
protected without a password, formulas never hidden, columns resizable; label
columns frozen on the model sheets.

## 5. Financial-convention mapping

| Convention | Anchor | Workbook |
| --- | --- | --- |
| Periods | Annual, t = 0..H; sale at end of H inside Year H | Same columns |
| NOI | `NOI_y = NOI_current x (1+g)^(y-1)` | `=Current_NOI x (1+g)^(year-1)` |
| Exit NOI | `NOI_current x (1+g)^H` (Year H+1) | Year H+1 column |
| Exit value | exit NOI / exit cap | same |
| Selling costs | exit value x disposition % | same |
| Loan | price x LTV | same |
| Fees | acq = price x %; financing = loan x %; equity-funded | same |
| Monthly rate | annual / 12 | same |
| Amortizing payment | loan x r / (1-(1+r)^-N); loan/N at r = 0; 0 with no loan | same branches, explicit formula |
| IO | first `12 x IO` months pay loan x r; then N amortizing payments | same |
| Recurrence | interest = beginning x r; principal = payment - interest; balance zeroed at maturity | same, row per month |
| Debt service | sum of twelve monthly payments | `SUM` of the year's twelve rows |
| Payoff | balance at month min(12H, maturity) | Year H ending balance |
| Equity cash flow | `-initial equity`; NOI - DS - CapEx - PC - OE; + net sale proceeds in H | same lines, signed |
| Equity multiple | positive total / abs(negative total); unavailable when no negative | `SUMIF` split; `Unavailable` |
| IRR | annual periodic, equal intervals; valid only if first nonzero negative, a positive exists, exactly one sign change | Excel `IRR` (not `XIRR`), evaluated only when the same rules pass |
| Rounding | none; presentation only | none; number formats only |

IRR numerics: Anchor solves by bracket-and-bisection; Excel iterates. Each
Excel IRR is seeded with its own series' cash multiple raised to `1/H`, which
kept Excel on the correct root at both boundaries tested (about +331% and
-99.9998%). A series that passes the sign rules but on which Excel fails to
converge shows `Did not converge` (never a number, never a pass); any other
Excel error stays visible. Anchor-only outcomes
(`ROOT_OUTSIDE_SEARCH_DOMAIN`, `NUMERICAL_FAILURE`) cannot be reproduced by the
sign rules, so those rows FAIL by design; a golden case pins that.

## 6. Reconciliation and tolerances

Anchor and Excel both use IEEE-754 doubles on the same unrounded inputs; they
differ only in operation order. Measured differences: currency ~2e-15 relative
(e.g. 1.3e-8 on a $14.1M balance), ratios ~1e-15, IRR ~1e-11. Tolerances:

- currency: `MAX(1e-6, 1e-10 x |Anchor|)`;
- ratios, rates, multiples: `1e-10`;
- IRR: `1e-7` (Excel's documented IRR precision, 0.00001%);
- hold period, period count, IRR availability: exact.

A status passes only with two numbers inside tolerance, or `Unavailable` on both
sides. A blank source reads `Missing`; an error reads `Excel error`; with
modified Working Inputs every row reads `Not like-for-like` and the sheet says
why (Excel now describes a modified case; the frozen Anchor results are
unchanged).

Numbers are stored to 16 significant digits (XlsxWriter's serialisation, beyond
Excel's 15-digit display), so a frozen value can differ from Anchor's double by
about one part in 10^16. This is stated in Audit Metadata and pinned by test.

## 7. Calculation and cached values

`fullCalcOnLoad="1"` with automatic calculation. Every formula is written with a
pessimistic cached value: blank, or `Not recalculated` for statuses. Nothing is
copied from Anchor into a formula cache, so an unrecalculated workbook shows no
pass anywhere (tested), and only a real spreadsheet engine can produce one.

## 8. Dependency decision

`openpyxl` was already a dependency (ingestion reads workbooks). The generator
uses **XlsxWriter** (`XlsxWriter>=3.2,<4`, BSD, pure Python, no dependencies):
it is write-only, writes deterministic packages (same saved Deal and time give
identical bytes, tested), controls each formula's cached value (which openpyxl
cannot), and covers protection, defined names, data validation, freeze panes and
calculation settings. openpyxl remains the reader in tests. No desktop
application is a production dependency.

## 9. Native recalculation evidence

Desktop Excel 16 (COM) was available on the development machine and used only
for disposable QA workbooks (`tests/excel_native_recalc.py`, opt-in with
`ANCHOR_EXCEL_NATIVE_RECALC=1`; it records and terminates only the Excel process
it starts). `tests/test_excel_export_1_native_recalc.py`:

- 18 golden cases (amortizing; IO with every fee; zero, negative and strong
  growth; IO beyond the hold; amortized before sale; all cash; zero rate; full
  leverage with no equity; Business Plan items; multiple sign changes; no
  positive cash flow; very high return; near-total loss over 1 and 3 years; a
  30-year hold; a root outside Anchor's search domain) -- every row passes
  except the four documented Anchor-only IRR rows of the last case; no Excel
  error anywhere; every formula still a formula after Excel saves;
- Excel's own model cells read back and compared with the engine in Python,
  independent of the Checks sheet;
- mutation proofs: exit NOI period, sale proceeds, one month's balance
  recurrence, debt payoff, Year 0 sign (value and IRR availability), IRR range
  and equity-multiple denominator each fail the row that guards them while an
  unrelated row still passes; a deleted formula reads `Missing`; a Working
  Input edit makes every row `Not like-for-like`, moves its dependents and
  leaves unrelated NOI unchanged; tampering with an Original Export value is
  reported.

## 10. Browser behaviour

The action lives in the header's "More deal actions" menu, Quick mode only
(`byMode`: Detailed and Lease-Level pass none). It is disabled, with the reason
attached by `aria-describedby`, when the Deal is unsaved ("Save this Deal, then
analyze it..."), has unsaved changes ("Unsaved changes are not exported. Save
the Deal and analyze the saved inputs first."), is analysing, or has no current
result ("Analyze the saved inputs first..."). A server refusal is shown
verbatim as an alert; a success as a status line naming the file. The outcome
line is shown only while the action is available, so it never sits beside
unsaved edits. Exporting writes nothing.

## 11. Security

User-authored text (Deal name, subtype, Business Plan descriptions) is written
with `write_string`, and the workbook is opened with `strings_to_formulas`,
`strings_to_numbers` and `strings_to_urls` off, so `=`, `+`, `-` and `@` text
stays text (tested with hostile values). No macros, external links, connections
or hidden formulas. The filename is sanitised independently. Refusals and
generation failures expose no path or exception text.

## 12. Manual acceptance

1. Open a saved, analysed Quick Deal; export; confirm the filename.
2. Open the workbook in Excel: Summary shows "Excel formulas recalculated: Yes"
   and every check passed.
3. Walk every sheet for layout and clarity.
4. Edit a Working Input (for example the exit cap rate): confirm the model
   moves, the Inputs row says Modified, Checks says Not like-for-like, and
   Anchor Results is unchanged; restore it and confirm every check passes.
5. Confirm unsaved changes, an unanalysed Deal and a Detailed or Lease-Level
   Deal cannot be exported.

## 13. Human acceptance and feature closeout

On 2026-09-20 the human explicitly accepted Excel Export 1, including the PR
#45 workbook presentation polish. The final isolated acceptance sweep against
merged `main` at `1afd003` completed a Quick Underwrite audit export and
confirmed the mode-specific success status and sanitized `.xlsx` filename.

Excel Export 1 is therefore **complete and accepted**. This record changes
status only and starts no later export gate.
