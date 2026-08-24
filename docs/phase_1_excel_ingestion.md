# Mini-Anchor POC V1 Phase 1: Excel Ingestion

## Purpose and Authority

This document is the authoritative Phase 1 specification for converting one canonical Mini-Anchor Excel workbook into one validated `AcquisitionInputs` object. It inherits the nine input definitions and validation domains frozen in `docs/financial_conventions.md` and does not revise them.

Phase 1 is an ingestion boundary only. It reads workbook data, maps the nine authoritative Field IDs, normalizes permitted numeric representations, and validates the resulting inputs. It produces no financial outputs and performs no underwriting calculations.

In particular, Phase 1 must not calculate going-in cap rate, an NOI forecast, loan amount, debt service, DSCR, loan balance, exit value, IRR, Equity Multiple, acquisition cash flows, or any other derived financial result. Those responsibilities begin in Phase 2 and remain in the deterministic Python engine.

## Canonical Workbook Contract

### File and worksheet

The canonical POC V1 workbook format is an Excel Open XML `.xlsx` workbook that can be opened by `openpyxl`. Alternate Excel and non-Excel formats are outside Phase 1.

The workbook must contain a worksheet whose title is exactly `Inputs`. The comparison is case-sensitive: for example, `inputs`, `INPUTS`, and `Inputs ` do not satisfy the requirement. A workbook may contain other worksheets, but the reader must ignore them; they are not acquisition data sources.

### Table location and headers

To make header discovery deterministic, POC V1 freezes the canonical table header at row 1 of the `Inputs` worksheet:

| Cell | Required header |
| --- | --- |
| `A1` | `Field ID` |
| `B1` | `Input` |
| `C1` | `Value` |
| `D1` | `Unit` |

The four header values and their order must match exactly, case-sensitively, and without trimming whitespace. For example, `Field ID` is valid in `A1`, while `field id` and `Field ID ` are invalid. Missing, renamed, duplicated, shifted, or reordered headers are a malformed table/header error. The ingestion table is limited to columns A through D. Cells outside A:D are ignored by ingestion and must neither supply acquisition inputs nor extend the table scan.

Merged cells are not permitted in the required `A1:D1` header range. Any merged range that intersects `A1:D1`, including a merge that causes a required header cell not to contain its exact required literal value, fails with the existing malformed table/header error. No separate merged-cell error category is introduced.

Data records begin below the header. Their row numbers and order have no meaning. The reader must scan from row 2 through the greatest worksheet row containing cell content in A:D and map each record solely by its Field ID; it must not assume that a particular input is on a particular row or stop at the first empty row. If A:D contain no records, all nine required Field IDs are missing.

A row whose cells in columns A through D are all blank may be ignored. For Field ID classification, a Field ID cell is blank when its underlying value is `None` or absent, the empty string `""`, or a string containing only whitespace characters. A whitespace-only Field ID is therefore blank, not an unknown Field ID. A non-empty row with a blank Field ID is a malformed row under the existing malformed table/header error category and must not be treated as an ignorable empty row. For example, if `A5` contains `"   "` and `C5` contains `1000000`, ingestion must report that malformed-row issue associated with row 5, not an unknown Field ID issue.

### Required records

The canonical table contains these nine required records:

| Field ID | Human-readable Input label | Suggested Unit | Python field | Python type |
| --- | --- | --- | --- | --- |
| `purchase_price` | Purchase Price | `USD` | `purchase_price` | `float` |
| `current_noi` | Current NOI | `USD/year` | `current_noi` | `float` |
| `occupancy` | Occupancy | `%` | `occupancy` | `float` |
| `noi_growth` | NOI Growth | `%/year` | `noi_growth` | `float` |
| `hold_period` | Hold Period | `years` | `hold_period` | `int` |
| `exit_cap_rate` | Exit Cap Rate | `%` | `exit_cap_rate` | `float` |
| `ltv` | LTV | `%` | `ltv` | `float` |
| `interest_rate` | Interest Rate | `%` | `interest_rate` | `float` |
| `amortization` | Amortization | `years` | `amortization` | `int` |

Each required Field ID must appear exactly once. A missing required Field ID is an error, a repeated required Field ID is an error, and any additional non-empty Field ID is an error in POC V1.

Field IDs are exact, case-sensitive identifiers. The reader must not trim any non-blank Field ID string before matching, change its case, perform fuzzy matching, recognize aliases, or infer an intended ID from nearby text. A non-blank near-match is an unknown Field ID, not a match. The classifications include:

| Underlying Field ID value | Classification |
| --- | --- |
| `"purchase_price"` | Valid Field ID |
| `" purchase_price"` | Unknown Field ID |
| `"purchase_price "` | Unknown Field ID |
| `"PURCHASE_PRICE"` | Unknown Field ID |
| `"   "` | Blank Field ID; malformed row when the row is non-empty |

The values in the Input and Unit columns are descriptive only. The listed Input labels are the canonical human-readable labels and the listed units are recommended presentation text, but neither column participates in mapping, type selection, normalization, or validation. Changing or leaving descriptive text blank must not change the parsed result. Field ID is the only machine-mapping key.

## Workbook Value Rules

For every required record, the cell in the Value column must contain an underlying literal Excel numeric value.

The following rules are frozen for POC V1:

1. A required Value cell must not be blank. For error classification, an absent value, an empty string, or whitespace-only text is blank.
2. A formula is prohibited in each of the nine Value cells, even if Excel has stored a cached numeric result for that formula. Formula detection must use formula-preserving workbook data or cell metadata; a reader must not use a cached result to disguise a formula as a literal value.
3. Numeric-looking text such as `"1000000"`, `"$1,000,000"`, or `"5.25%"` is not numeric and must not be parsed or coerced.
4. Excel Boolean, semantically date/time/duration, error, and text cell types are not accepted as financial numeric inputs. In particular, Python `bool` values must be rejected even though `bool` is a subclass of `int`. A cell surfaced by the workbook library as a date, time, or duration is rejected; Phase 1 does not recover and reinterpret its underlying Excel serial number.
5. Currency inputs are ordinary numeric cell values. A currency symbol, thousands separator, or other number format changes display only and must not change the underlying value returned by ingestion.
6. Percentage inputs use Excel decimal semantics. For example, a displayed value of `5.25%` has the underlying value `0.0525`, and a displayed value of `65%` has the underlying value `0.65`.
7. The reader must preserve the underlying percentage value. It must never divide a percentage by 100, multiply it by 100, or use the Unit text or Excel number format to rescale it.
8. For a cell that remains an accepted numeric cell, presentation properties such as currency, percentage, or custom numeric display formats, cell styles, hidden rows, and filtering must not alter or rescale the underlying value. Date/time/duration cells are classified by rule 4 rather than treated as financial serial numbers.
9. Missing values must not be inferred from labels, units, neighboring cells, defaults, prior workbooks, or any other source.

Consequently, an underlying value of `65` remains `65`; it is never converted to `0.65`. The later domain check rejects `65` for Occupancy or LTV, while fields for which Phase 0 defines no upper bound must not receive a newly invented plausibility limit.

## `AcquisitionInputs` Contract

The shared input contract is an immutable, standard-library Python dataclass with exactly the following declaration and fields, in this order:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionInputs:
    purchase_price: float
    current_noi: float
    occupancy: float
    noi_growth: float
    hold_period: int
    exit_cap_rate: float
    ltv: float
    interest_rate: float
    amortization: int
```

No additional underwriting fields, derived metrics, workbook coordinates, source metadata, confidence values, labels, or units belong in this contract. Runtime instances produced by ingestion must contain built-in `float` values for the seven rate/currency/NOI fields and built-in `int` values for the two year fields.

`AcquisitionInputs` is independent of Excel. It must not import `openpyxl`, retain workbook objects, know cell addresses, or behave differently according to the source of its values. Type annotations alone do not perform validation; the validation boundary must establish all invariants before constructing the object.

## Normalization and Mapping

Normalization is deliberately narrow and must not repair invalid financial input.

For the seven fields declared as `float`, a literal Excel numeric value is normalized to a built-in Python `float` without rounding or scaling. The normalized float must be finite.

For Hold Period and Amortization, a literal Excel numeric value is eligible for conversion to a built-in Python `int` only when it is finite and mathematically integral. Thus `5` and `5.0` may both normalize to `5`. The whole-number check is exact: no rounding, truncation, epsilon tolerance, string conversion, or other coercion is permitted. A value such as `5.5` is rejected rather than normalized.

Mapping uses this fixed one-to-one registry:

```text
purchase_price  -> purchase_price
current_noi     -> current_noi
occupancy       -> occupancy
noi_growth      -> noi_growth
hold_period     -> hold_period
exit_cap_rate   -> exit_cap_rate
ltv             -> ltv
interest_rate   -> interest_rate
amortization    -> amortization
```

The mapping step must not derive one input from another. In particular, Occupancy and Current NOI are copied independently. Occupancy is preserved as supplied, remains informational in POC V1, and is never multiplied into Current NOI or any forecast NOI.

## Validation Domains

Validation must apply the Phase 0 domains exactly after type checks and normalization. It must not add reasonableness tests, warnings, relationships between fields, or tighter bounds.

| Field | Required domain | Boundary meaning |
| --- | --- | --- |
| Purchase Price | finite and `> 0` | Zero and negative values are invalid. No additional upper bound exists. |
| Current NOI | finite and `>= 0` | Zero is valid. No additional upper bound exists. |
| Occupancy | finite and `0 <= value <= 1` | Both `0` and `1` are valid. |
| NOI Growth | finite and `> -1` | `-1` is invalid. POC V1 has no hard upper bound. |
| Hold Period | finite whole-number years and `>= 1` | `1` is valid; zero and negative integers are invalid. |
| Exit Cap Rate | finite and `> 0` | Zero and negative values are invalid. No additional upper bound exists. |
| LTV | finite and `0 <= value <= 1` | Both `0` and `1` are valid; 100% LTV is permitted. |
| Interest Rate | finite and `>= 0` | Zero is valid. No additional upper bound exists. |
| Amortization | finite whole-number years and `>= 1` | `1` is valid; zero and negative integers are invalid. |

Examples of prohibited extra validation include limiting positive NOI Growth, Exit Cap Rate, or Interest Rate; rejecting 100% LTV; requiring Current NOI to be less than Purchase Price; or imposing a relationship between Hold Period and Amortization. Such policies would change Phase 0 and are not part of ingestion.

## Separation of Responsibilities

Phase 1 has three distinct conceptual responsibilities:

### 1. Workbook Reader

The Workbook Reader:

- opens the `.xlsx` workbook;
- locates the exactly named `Inputs` worksheet;
- verifies the fixed four-column header structure;
- scans the table without assigning meaning to row order;
- reads literal cell contents while retaining enough cell metadata to detect formulas; and
- detects workbook, worksheet, header, and malformed-row problems.

The Workbook Reader does not apply financial domains or calculate financial results.

### 2. Normalization / Mapping

Normalization / Mapping:

- resolves exact Field IDs through the fixed registry;
- detects missing, duplicate, and unknown Field IDs;
- verifies that required Value cells are literal numeric cells rather than blanks, formulas, text, or other Excel types;
- converts accepted non-year values to `float`;
- converts valid whole-number Hold Period and Amortization values to `int`; and
- preserves percentage decimal semantics and all other underlying numeric values without rounding.

Normalization / Mapping does not infer, default, rescale, or calculate inputs.

### 3. Validation

Validation:

- rejects non-finite normalized values;
- applies only the frozen Phase 0 domains;
- reports field-specific domain failures; and
- constructs and returns `AcquisitionInputs` only after all nine fields are present, normalized, and valid.

Validation must be reusable independently of Excel so that later non-Excel ingestion routes can submit the same nine normalized field values to the validator without importing the workbook reader.

### Dependency direction

`openpyxl` belongs only at the Excel ingestion boundary. The financial engine must never import or depend on `openpyxl`. The contracts and validation layers should use only the Python standard library, and `AcquisitionInputs` must not depend on the workbook reader.

The intended dependency direction is:

```text
Excel workbook -> Workbook Reader (openpyxl) -> Normalization / Mapping
               -> Validation -> AcquisitionInputs -> Phase 2 engine
```

No dependency may point back from `AcquisitionInputs`, validation, or the Phase 2 engine to the Workbook Reader.

## Deterministic Processing Sequence

For the same workbook bytes and implementation version, ingestion must produce the same `AcquisitionInputs` value or the same issue categories, order, and field/cell context. An optional display path is diagnostic context and is not part of this determinism guarantee. Processing follows this sequence:

1. Open the workbook with `openpyxl` using `data_only=False`, so formulas remain visible rather than being replaced by cached results. If it cannot be opened, stop with a workbook-open error.
2. Locate the exact `Inputs` worksheet. If it is absent, stop with a missing-sheet error.
3. Validate `A1:D1`. If the header is malformed, stop with a malformed table/header error.
4. Scan rows 2 through the greatest row containing cell content in A:D. Ignore only rows that are wholly blank in A:D.
5. Classify non-empty rows by exact Field ID. A Field ID whose underlying value is absent, `""`, or a whitespace-only string is blank. A blank, formula, or non-text Field ID on a non-empty row is malformed; only an unrecognized non-blank literal text ID is unknown.
6. Determine duplicates and missing required Field IDs. Do not choose one duplicate occurrence or use an unknown row as a substitute.
7. For every uniquely present required field, inspect the Value cell in this precedence order: formula, blank, then numeric cell type.
8. Normalize and validate each numeric value as described above. For the seven float fields, convert to `float` and then apply finiteness. For each year field, establish finiteness and exact integrality before converting to `int`. Then apply the Phase 0 domain and construct `AcquisitionInputs` only if no errors exist.

The parser must never return a partial `AcquisitionInputs`, a partially validated dictionary presented as success, or an object populated with inferred/defaulted values.

## Deterministic Error Contract

Ingestion failures must use a dedicated, stable, machine-testable error category and a user-readable message. A field-specific issue must include the exact affected Field ID. Row-specific structural, duplicate, and unknown-ID issues must include the worksheet row number; duplicate errors must identify every conflicting row. Workbook/library exceptions must be translated into the ingestion error contract rather than exposed as the only user-facing behavior.

An implementation may represent an issue category with exception subclasses or stable error codes, but it must distinguish at least the following conditions:

| Error category | Trigger | Required context |
| --- | --- | --- |
| Workbook cannot be opened | Path is inaccessible, file is corrupt, encrypted/unsupported, not a valid canonical `.xlsx`, or `openpyxl` otherwise cannot open it. | Workbook identifier/path when safe to display; no field. |
| `Inputs` worksheet missing | No worksheet title equals `Inputs` exactly. | Required worksheet name; no field. |
| Malformed table/header structure | `A1:D1` does not match the four exact headers, a merged range intersects `A1:D1`, or a non-empty data row has a blank, formula, or non-text Field ID. | Expected structure and offending cell/row when applicable. |
| Missing Field ID | A required canonical Field ID does not occur. | Missing canonical Field ID. |
| Duplicate Field ID | A required canonical Field ID occurs more than once. | Canonical Field ID and all conflicting rows. |
| Unknown Field ID | A non-blank literal textual Field ID is not one of the nine exact IDs. | Supplied ID and row. |
| Blank Value | The Value cell for a required field has no usable content as defined above. | Canonical Field ID and row/cell. |
| Formula Value | The Value cell for a required field is a formula, regardless of cached result. | Canonical Field ID and row/cell. |
| Non-numeric Value | The Value cell is text, Boolean, date/time, duration, Excel error, or another non-numeric cell type. | Canonical Field ID and row/cell. |
| Non-finite Value | An otherwise numeric value is NaN, positive infinity, negative infinity, or cannot normalize to a finite built-in float. | Canonical Field ID and offending value when safely representable. |
| Out-of-domain Value | A finite, correctly typed value violates its Phase 0 inequality or inclusive bound. | Canonical Field ID, supplied value, and required domain. |
| Non-whole-number Hold Period | Hold Period is finite and numeric but not mathematically integral. | `hold_period`, supplied value, and row/cell. |
| Non-whole-number Amortization | Amortization is finite and numeric but not mathematically integral. | `amortization`, supplied value, and row/cell. |

After a valid header is available, the parser must collect every discoverable issue that can be identified without selecting among duplicates, inventing values, or otherwise guessing. It must report those issues as one ordered failure collection. Their order is:

1. malformed or unknown row issues in ascending worksheet row order;
2. duplicate required IDs in the canonical field order shown in this document;
3. missing required IDs in canonical field order; and
4. Value/type/domain issues for uniquely mapped records in canonical field order.

A terminal workbook-open, missing-sheet, or malformed-header error is reported before row-level analysis because later analysis is not reliable. Records for a duplicated required ID are not value-validated because no occurrence may be selected authoritatively.

Within one Value cell, formula detection takes precedence over cached content, blank takes precedence over non-numeric, non-numeric takes precedence over finiteness, non-finite takes precedence over domain, and a finite fractional year receives its field-specific non-whole-number error. An integral year value at or below zero receives an out-of-domain error.

Error messages may add diagnostic detail, but they must not expose stack traces as user guidance, vary according to arbitrary dictionary/set iteration order, or replace the stable category and field context.

## Dependency and Recommended Implementation Shape

The later Phase 1 implementation may add `openpyxl` as its sole new runtime dependency. No other runtime dependency is approved by this specification. `pytest` remains the test dependency.

A minimal implementation may use the following structure:

```text
src/mini_anchor/contracts.py
src/mini_anchor/validation.py
src/mini_anchor/excel_reader.py

tests/test_contracts.py
tests/test_validation.py
tests/test_excel_reader.py

examples/mini_anchor_input.xlsx
```

This structure is a recommendation, not an authorization to create these files during the specification-only task. Whatever structure is chosen later must preserve the dependency boundaries above.

## Required Phase 1 Tests

The Phase 1 implementation is not complete without automated tests covering at least the following behavior:

1. A valid canonical workbook produces the expected `AcquisitionInputs`.
2. All five percentage fields preserve Excel decimal semantics, including `0.0525` for a displayed `5.25%` and `0.65` for a displayed `65%`.
3. Currency values parse as their underlying numeric values regardless of currency display format.
4. A literal integer Hold Period parses correctly as a Python `int`.
5. A literal integer Amortization parses correctly as a Python `int`.
6. Hold Period value `5.0` normalizes to Python `int` value `5`.
7. A fractional Hold Period is rejected with the specific non-whole-number field error.
8. A fractional Amortization is rejected with the specific non-whole-number field error.
9. A workbook without the exact `Inputs` sheet is rejected.
10. Each missing required Field ID is rejected and identified.
11. Each duplicate required Field ID is rejected and identified with its rows.
12. Each unknown additional Field ID is rejected and identified.
13. Each defined blank representation—an absent value, an empty string, and whitespace-only text—in a required Value cell is rejected and identified.
14. A formula Value is rejected, including a formula with a cached numeric result.
15. Text where a numeric value is required is rejected without numeric-string coercion.
16. NaN, positive infinity, and negative infinity are rejected as non-finite values.
17. Every Phase 0 lower and upper validation boundary is tested as detailed in the boundary matrix below.
18. Occupancy is preserved exactly as supplied and is never applied to or used to change Current NOI.
19. Parser output contains exactly the nine `AcquisitionInputs` dataclass fields with the specified runtime types and no metadata or derived values.
20. Reordering the nine workbook rows does not change the result.
21. Changing human-readable Input labels does not change machine mapping or results.
22. Changing Unit text does not change machine mapping, scaling, or results.
23. An inaccessible, corrupt, unsupported, or non-workbook input produces the workbook-open error contract.
24. Missing, renamed (including case-changed or whitespace-padded), shifted, duplicated, reordered, or merged headers produce the malformed table/header error.
25. Sheet titles and non-blank Field IDs are exact and case-sensitive; surrounding whitespace, case changes, and near-matches are not normalized.
26. A non-empty row with `A5 = "   "` and `C5 = 1000000` produces a malformed-row issue under the existing malformed table/header error category, associated with row 5 and not classified as an unknown Field ID.
27. Fully empty rows before, between, and after records are ignored without ending the scan, while a non-empty row with a blank Field ID is rejected as malformed.
28. Boolean, date/time, duration, Excel error, and numeric-looking text Value cells are rejected as non-numeric.
29. Number formats and presentation styles do not alter parsed numeric values; hidden or filtered required rows are still read.
30. An underlying percentage value is never divided or multiplied by 100.
31. Error categories, field/row context, precedence, and multi-error ordering are deterministic.
32. Validation and `AcquisitionInputs` can be used without importing `openpyxl`, and no ingestion test relies on Phase 2 calculations.
33. The contract is frozen, slotted, keyword-only, and has the exact specified field names, order, and annotations.

### Phase 0 boundary matrix

Boundary tests must demonstrate all of the following without introducing approximate business rules:

| Field | Must accept | Must reject |
| --- | --- | --- |
| Purchase Price | A representative finite value strictly above `0` and a large finite value | `0` and a negative finite value |
| Current NOI | `0`, a positive finite value, and a large finite value | A negative finite value |
| Occupancy | `0`, an interior value, and `1` | A finite value below `0` and a finite value above `1` |
| NOI Growth | A finite value just above `-1`, `0`, and a large positive finite value | `-1` and a finite value below `-1` |
| Hold Period | `1`, `1.0` normalized to `1`, and a large whole number | `0`, a negative integer, and finite fractional values |
| Exit Cap Rate | A representative finite value strictly above `0` and a large finite value | `0` and a negative finite value |
| LTV | `0`, an interior value, and `1` | A finite value below `0` and a finite value above `1` |
| Interest Rate | `0` and a positive finite value, including a large value | A negative finite value |
| Amortization | `1`, `1.0` normalized to `1`, and a large whole number | `0`, a negative integer, and finite fractional values |

Finiteness tests must cover all nine fields at the normalization or validation boundary. Where a real `.xlsx` writer cannot encode a non-finite literal, the validation layer must be tested directly; the inability to construct that workbook fixture does not remove the invariant.

The tests must also establish that fields with no Phase 0 upper bound remain without one. They must not call or assert going-in cap rate, NOI forecast, debt, exit, return, or cash-flow logic.

## Phase 1 Definition of Done

This definition applies to the future implementation; publication of this specification alone does not claim that Phase 1 implementation is complete.

Phase 1 is complete only when:

- a canonical workbook can be parsed successfully;
- all nine values are mapped by exact Field ID into the correct contract fields;
- the frozen Phase 0 domains are enforced without additional financial constraints;
- structurally invalid, incorrectly typed, and out-of-domain workbooks fail deterministically with user-readable field context;
- the output is an immutable `AcquisitionInputs` containing no calculations or source-specific metadata;
- row ordering does not affect the result;
- tests cover successful ingestion and structural, type, finiteness, whole-number, and domain failures;
- all targeted tests and the full `pytest` suite pass;
- the final diff contains only intended Phase 1 changes; and
- no Phase 2 financial-engine logic exists in Phase 1.

## Frozen Phase 1 Decisions

- The canonical input is one openable `.xlsx` workbook containing an exactly named `Inputs` worksheet.
- The canonical table uses the exact `A1:D1` headers `Field ID`, `Input`, `Value`, and `Unit`.
- The nine exact, case-sensitive Field IDs are the sole machine-mapping authority; row order, Input labels, Unit text, and presentation formatting are not authoritative.
- Every required Field ID appears exactly once. Missing, duplicate, and unknown IDs are errors; only wholly empty rows may be ignored.
- Each required Value is a literal Excel numeric value. Blank, formula, text, Boolean, date/time, duration, error, and other non-numeric cells are invalid.
- Cached formula results are never accepted, and Phase 1 does not evaluate formulas.
- Currency values are ordinary underlying numerics. Percentage values retain Excel decimal semantics and are never automatically rescaled.
- Hold Period and Amortization accept only exact whole-number years; integral numeric values such as `5.0` normalize to Python `int` values without rounding or truncation.
- Validation uses exactly the Phase 0 domains, including 100% LTV, zero Current NOI, zero Interest Rate, no hard upper bound for NOI Growth, and no newly invented relationships between inputs.
- `AcquisitionInputs` is the exact immutable, slotted, keyword-only nine-field dataclass specified here and remains independent of Excel.
- Workbook reading, normalization/mapping, and validation are separate responsibilities. `openpyxl` is confined to the workbook reader, and the deterministic financial engine never depends on it.
- Phase 1 performs no financial calculations and returns no partial or inferred successful result.
- Failures use stable categories, deterministic precedence/order, user-readable messages, and field/row context where applicable.
- `openpyxl` is the only runtime dependency Phase 1 may add without separate approval; `pytest` remains the test dependency.

## Deferred Beyond Phase 1

- Financial calculations, including going-in cap rate, NOI forecasting, loan amount, debt service, DSCR, loan balance, exit value, IRR, Equity Multiple, and cash flows
- Azure document extraction
- GPT normalization
- Frontend upload
- FastAPI
- Provenance/confidence metadata
- Alternate Excel formats
- Automatic fuzzy field matching
- Formula evaluation
- Multiple worksheets as acquisition data sources
