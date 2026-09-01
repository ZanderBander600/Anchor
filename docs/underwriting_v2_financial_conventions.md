# Underwriting V2 Financial Conventions Specification

## Status

**Frozen — Phase 0.** This document is the authoritative Underwriting V2 financial
specification, approved for implementation planning. It inherits and extends
`docs/financial_conventions.md` (POC V1) and `docs/phase_2_deterministic_engine.md`.
Where this document is silent, the V1 documents govern for the nine original
inputs and their formulas — nothing in V1 is revised, relaxed, or reinterpreted
by this document except where explicitly stated below.

This is a specification-only document. No `AcquisitionInputs`/`AcquisitionResults`
contract change, no engine code, no validation code, no Excel reader change, no
persistence schema change, no frontend change, and no test has been implemented
as part of producing it.

## Purpose

Anchor's POC V1 deterministic engine deliberately uses a frozen nine-input
simplified model, appropriate for a proof of concept. This document defines the
smallest expansion of that model — five new inputs — that materially improves
real commercial real estate acquisition realism without introducing
ARGUS-level complexity: lease-by-lease modeling, rent-roll forecasting, tenant
improvements, leasing commissions, rollover/downtime, multiple debt tranches,
refinancing, waterfalls/promote, development/construction modeling, taxes,
depreciation, portfolio analytics, variable-rate debt, and monthly modeling all
remain explicitly out of scope, unless a specific investigation step below
proved one necessary for correctness (none did).

## Current V1 Model (baseline, verified against the live implementation)

Nine inputs (`src/anchor/contracts.py`): `purchase_price`, `current_noi`,
`occupancy` (informational only, never read by any calculation), `noi_growth`,
`hold_period`, `exit_cap_rate`, `ltv`, `interest_rate`, `amortization`.

- `loan_amount = purchase_price * ltv`; `initial_equity = purchase_price - loan_amount`.
- NOI: `NOI_1 = current_noi`; `NOI_y = current_noi*(1+g)^(y-1)`. `exit_noi = NOI_(H+1)`.
- Debt: a single fixed-rate, fully amortizing tranche, amortization beginning
  month 1. No interest-only period, no rate resets, no second tranche.
- Exit: `exit_value = exit_noi / exit_cap_rate`. No sale costs.
- `UCF_0 = -purchase_price`; `UCF_y = NOI_y`; `UCF_H = NOI_H + exit_value`. No acquisition costs.
- `LCF_0 = -initial_equity`; `LCF_y = NOI_y - ADS_y`; `LCF_H = NOI_H - ADS_H + net_sale_proceeds`,
  where `net_sale_proceeds = exit_value - remaining_loan_balance`.
- `DSCR_y = NOI_y/ADS_y` or `None`; `headline_dscr = DSCR_1`.
- `equity_multiple = Σpositive(LCF) / |Σnegative(LCF)|`, `None` at a zero denominator.
- IRR: a bespoke bisection/Horner solver, applied identically to both cash-flow series.

Explicit V1 exclusions (`docs/financial_conventions.md`): acquisition costs,
sale costs, taxes, CapEx, TI, LC, refinancing, waterfalls, additional debt
tranches — acquisition and sale costs are "explicitly set to zero." That
document's own "Questions Deferred Beyond POC V1" section names exactly the
gaps this document closes: *"Whether and how acquisition costs or sale costs
should be modeled in a future version"* and the CapEx/TI/LC/refi/waterfall
list. This is a direct, anticipated continuation of that document.

## V2 Input Set

Five new fields, each collapsing to exact V1 behavior at its neutral value:

| Field | Type | Neutral | Domain |
|---|---|---|---|
| `acquisition_cost_pct` | float | `0.0` | `0.0 <= x <= 1.0` |
| `financing_fee_pct` | float | `0.0` | `0.0 <= x <= 1.0` |
| `disposition_cost_pct` | float | `0.0` | `0.0 <= x <= 1.0` |
| `annual_capex_reserve` | float | `0.0` | `x >= 0.0` (currency/year, flat — **not** a function of NOI or NOI growth) |
| `io_period` | int | `0` | `x >= 0` whole years; may equal or exceed `hold_period` |

Fourteen total inputs. Percentage-shaped fields are canonical decimal fractions
(e.g. `0.02` for 2%), consistent with every existing percentage-shaped field
in `AcquisitionInputs`.

### Inputs considered and deferred

- **Splitting acquisition costs into closing costs + due diligence.** One
  combined line captures the dominant T=0-equity effect; the split changes no
  return and is deferred.
- **Flat-dollar acquisition/financing/disposition costs.** Rejected — every
  existing input that scales with deal size is percentage-based; a flat-dollar
  field would be the first inconsistent unit in the form.
- **CapEx as $/unit or $/SF.** The standard real-world convention, but Anchor
  has no unit-count or square-footage input today. `annual_capex_reserve`
  (flat currency/year) is the smallest version that needs no new scale input.
  A future Anchor version may support $/unit or $/SF reserves once a
  property-scale input exists.
- **Upfront CapEx/reserve escrow funded at closing** (distinct from the
  ongoing annual reserve). A real institutional-loan nuance; the ongoing
  reserve already captures the dominant economic effect. Deferred.
- **"DSCR after reserves"** as an alternate DSCR convention. Standard lender
  covenant practice computes DSCR on NOI before capital reserves; `DSCR_y`
  stays `NOI_y/ADS_y`, unchanged. `min_dscr` (below) addresses the more
  urgent gap IO creates.
- **Loan-to-cost (LTC) vs. loan-to-value.** `loan_amount` stays based on
  `purchase_price` only (see below) — a real, larger complexity increase not
  yet justified.
- **Exit cap rate coupled to entry cap rate.** `exit_cap_rate` remains a free,
  independently set input; that flexibility is correct and unchanged.
- Every category the task scope explicitly excludes (lease-level modeling,
  variable-rate/multi-tranche/refinancing/waterfalls/taxes/depreciation/
  portfolio analytics/monthly modeling) was checked against the five inputs
  above and found not necessary for their correctness. No sixth input was
  found so fundamental that its absence would make the five below misleading.

## Terminology

- `io_period` — years before scheduled principal amortization begins.
- `amortization` — the amortization schedule length that follows the IO
  period, unchanged in meaning from V1.
- **Anchor V2 does not model contractual loan term, maturity, or a balloon
  payment.** `io_period + amortization` is never described as "the loan's
  term" or "contractual maturity" — it is only the point at which the
  *modeled* schedule (interest-only, then amortizing) reaches a zero balance,
  if the property is held that long. It is not a claim about a lender's
  contractual maturity date. Refinancing, balloon payoff, and loan extension
  remain explicitly out of scope.

## Acquisition Sources & Uses

```
Loan Amount        = purchase_price * ltv            (unchanged basis: purchase price only, not total cost)
Acquisition Costs  = acquisition_cost_pct * purchase_price
Financing Fee      = financing_fee_pct * loan_amount
Initial Equity     = purchase_price - loan_amount + acquisition_costs + financing_fee
```

Acquisition costs and the financing fee are funded entirely by equity —
never financed into the loan. Lenders size and fund against purchase price
(or appraised value), not against soft costs; rolling these into the loan
would require a second, loan-to-cost-style sizing basis not justified by this
phase's minimal-expansion goal. `loan_amount` continuing to derive from
`purchase_price` alone (not total project cost) is a deliberate, reviewed
choice, not an oversight — loan-to-cost sizing is a legitimate future
enhancement, not adopted here.

At `acquisition_cost_pct = financing_fee_pct = 0`, `Initial Equity` collapses
to exactly `purchase_price - loan_amount`, the unmodified V1 formula.

## Debt-Service Mechanics

Let `r = interest_rate / 12`, `io_months = io_period * 12`,
`N = amortization * 12` (the fixed, full amortizing-phase payment count —
unchanged meaning from V1, and never varies with `hold_period`).

```
Payment_t = loan_amount * r                          for 1 <= t <= io_months          (interest-only)
Payment_t = PMT (existing V1 Branch 1/2/3 formula)    for io_months < t <= io_months + N
Payment_t = 0                                          for t > io_months + N
```

`PMT` is computed by the exact, unmodified V1 formula (the ordered
zero-loan / zero-rate / positive-rate branches, including the numerically
stable `log1p`/`expm1` evaluation), using `loan_amount` and `N` exactly as V1
already does — only the calendar offset at which the amortizing phase begins
changes.

Balance recurrence: the same V1 three-step (Interest → Principal → Ending
Balance) monthly process throughout. During the IO phase,
`Beginning Balance_t = loan_amount` for every `t` — this falls out of the
existing math automatically (`Principal_t = Payment_t - Interest_t = 0` when
`Payment_t` is pure interest on an unchanged balance), and is not
special-cased.

### Remaining loan balance at exit — `m` vs. `N`

Let `N` remain the fixed, full amortizing-phase payment count
(`= amortization * 12`, a property of the loan structure alone, independent
of the hold period). Let `m` be the number of *amortizing* payments actually
made by the sale date — a quantity that depends on `hold_period` and is
**never** the same variable as `N`:

```
m = clamp( H*12 - io_months, 0, N )
```

```
remaining_loan_balance:
  H <= io_period:                             = loan_amount exactly       (m = 0; never amortized before sale)
  io_period < H <= io_period + amortization:    = B_m, the balance after m amortizing
                                                   payments on the N-payment schedule
  H > io_period + amortization:                 = 0.0                     (m = N; modeled schedule fully paid down)
```

Closed-form cross-check only (test/reference oracle, per the same V1 rule
that the monthly recurrence — not the closed form — is the authoritative
implementation path):

```
B_m = L*(1+r)^m - PMT*[(1+r)^m - 1]/r
```

`m` and `N` must never be conflated in an implementation: `N` is fixed by
`amortization` alone; `m` is exit-date-dependent and recomputed from
`hold_period` and `io_period`.

Because `io_period` is a whole number of years, `io_months` always lands on a
year boundary — no year ever straddles the IO/amortizing boundary. Each
`ADS_y` is entirely IO, entirely amortizing, or entirely zero
(post-schedule-payoff), never mixed.

`io_period >= hold_period` is an explicitly valid, non-error case (the entire
hold sits inside the IO phase; the loan never begins amortizing before sale).

## Annual Cash-Flow Construction

```
CapEx_y = annual_capex_reserve                                     for y = 1..H     (flat; never a function of NOI)

UCF_0 = -(purchase_price + acquisition_costs)
UCF_y = NOI_y - annual_capex_reserve                                 for 1 <= y < H
UCF_H = NOI_H - annual_capex_reserve + exit_value - disposition_costs

LCF_0 = -initial_equity
LCF_y = NOI_y - ADS_y - annual_capex_reserve                         for 1 <= y < H
LCF_H = NOI_H - ADS_H - annual_capex_reserve + net_sale_proceeds
```

`UCF_0` excludes the financing fee (an all-cash buyer never pays one); `LCF_0`
includes it, folded into the expanded `initial_equity` above. `NOI_y`,
`going_in_cap_rate`, and `exit_noi` are entirely unchanged from V1 —
`annual_capex_reserve` stays strictly below NOI and never alters it, the
going-in cap rate, exit NOI, or exit value.

## Exit Proceeds

```
exit_value          = exit_noi / exit_cap_rate                          (unchanged, gross — never reduced by costs)
disposition_costs   = disposition_cost_pct * exit_value
net_sale_proceeds    = exit_value - disposition_costs - remaining_loan_balance
```

`exit_value` keeps its V1 meaning as a gross market-value estimate;
disposition costs are layered on only when deriving the net figure, following
the same precedent `net_sale_proceeds` already set relative to `exit_value`
in V1.

## DSCR

`DSCR_y = NOI_y / ADS_y` if `ADS_y > 0` else `None` — **formula unchanged**;
only `ADS_y` itself reflects the IO-aware schedule. `headline_dscr =
dscr_by_year[0]`, unchanged in meaning.

New: `min_dscr = min(d for d in dscr_by_year if d is not None)`, or `None` if
every entry is `None`. This is the direct, necessary companion to
introducing IO: Year-1 DSCR during an interest-only period can materially
overstate a deal's true minimum debt-service coverage, since the interest-only
payment is always lower than the subsequent amortizing payment for the same
balance and rate.

## IRR and Equity Multiple

Both algorithms are **unchanged** from V1 — the same Horner/bisection solver
(same domain, iteration cap, and stopping tolerances) and the same
`Σpositive(LCF)/|Σnegative(LCF)|` equity-multiple formula. Only the
cash-flow tuples fed into them change, per the construction above.

## Proposed `AcquisitionInputs` Additions

```python
acquisition_cost_pct: float = 0.0     # 0.0 <= x <= 1.0
financing_fee_pct: float = 0.0        # 0.0 <= x <= 1.0
disposition_cost_pct: float = 0.0     # 0.0 <= x <= 1.0
annual_capex_reserve: float = 0.0     # x >= 0.0
io_period: int = 0                    # x >= 0, may be >= hold_period
```

Dataclass-level defaults are required so every existing call site
constructing `AcquisitionInputs` with only the original nine keyword
arguments continues to compile and run unmodified — a source-level
compatibility guarantee, not only a value-level one.

## Proposed `AcquisitionResults` Additions

```python
acquisition_costs: float
financing_fee: float
disposition_costs: float
annual_capex_reserve_by_year: tuple[float, ...]   # length H
min_dscr: float | None
```

Justification follows the existing contract's own precedent for
`noi_by_year` (`docs/phase_2_deterministic_engine.md`): without these fields,
nobody — analyst or AI Analyst — can verify why `initial_equity` or a given
cash flow differs from the naive purchase-price-only figure, without
re-deriving it by hand. `initial_equity` keeps a single field and expands its
*definition*, rather than gaining a redundant duplicate field, consistent
with the existing contract's explicit rule against duplicate/derived
convenience fields.

## Excel Ingestion Compatibility

The Excel reader is already a Field-ID registry scan (not positional), so
adding five canonical Field IDs is mechanical. The five new Field IDs are
**optional** in the reader — if absent, the corresponding `AcquisitionInputs`
field is defaulted to its neutral value (`0.0`/`0`) rather than raising a
missing-field error — while the original nine remain exactly as strictly
required as they are today. This is a deliberate, scoped exception to the
existing "all Field IDs required, no missing" rule, limited to the five V2
fields.

The ingestion response additionally reports which of the five V2 Field IDs
were absent and therefore defaulted (a byproduct of the reader's existing
per-Field-ID presence scan, already computed for its own missing-required-
field-error path — not a new provenance system). This signal exists so the
frontend can distinguish "the workbook genuinely supplied zero" from "the
workbook didn't address this assumption at all" (see below).

A complete V2 workbook — one that supplies all five new Field IDs — populates
every field normally, exactly like the original nine always have.

## Backward-Compatibility-Preserving UX for Intake (not a provenance system)

**Principle.** Neutral (zero) defaults exist only at the contract,
persistence, and legacy-ingestion layers, to preserve compatibility with
existing data and callers. They must never be presented to an analyst as if
they were a considered answer. This section defines the smallest mechanism
that achieves that, reusing existing patterns rather than adding new
machinery.

**Backend layer (unchanged permissiveness, for compatibility):**
- `/analyze`'s payload, Excel ingestion, and persisted deals all continue to
  treat the five V2 fields as optional, defaulting to their neutral value
  when absent. This is what makes legacy workbooks, legacy persisted deals,
  and any direct API caller continue to work unmodified.

**Frontend layer (deliberately stricter than the backend, by UX policy, not
an engine or validation-layer rule change):**
- The five V2 fields **never render pre-filled with `"0"`** at the moment of
  fresh intake — identical in spirit to how the original nine fields already
  start blank on a New Deal today:
  - **Fresh manual deals** start with all five V2 fields blank.
  - **OM-derived deals** leave the five V2 fields blank — OM ingestion is not
    extended to propose candidates for them in this phase (see below), so
    they are simply never populated by the existing approval hand-off, which
    already leaves an unaddressed field blank rather than defaulting it.
  - **Legacy Excel workbooks** (missing one or more V2 Field IDs): the
    frontend uses the ingestion response's defaulted-field-ID list to leave
    exactly those corresponding form fields blank, even though the
    underlying parsed value returned by the backend is literally `0.0`. Any
    V2 field the workbook *did* supply populates normally, not blank.
  - **Complete V2 Excel workbooks** populate all fields normally.
- Whenever one or more V2 fields are blank at intake, a concise review banner
  is shown, naming which assumptions were not provided and are not yet
  reflected in the form.
- The five V2 fields are validated at the frontend form layer with the
  **same required-field treatment already used for the original nine** — a
  blank V2 field blocks submission with the same "X is required" validation
  error a blank core field already produces today, through the existing
  validation mechanism, not a new one. The analyst must consciously enter a
  value — including explicitly entering `0` if zero is genuinely intended —
  before the shared assumptions-conversion path used by both **Save** and
  **Analyze** will proceed. (Save and Analyze already share this conversion
  path; requiring conscious entry before either is a direct, intended
  consequence of that shared path, not a special case introduced for one
  action only.)
- This deliberate asymmetry — permissive backend, strict frontend — is by
  design: the backend stays permissive so legacy data and non-UI callers keep
  working; the UI enforces conscious analyst entry as a matter of
  presentation policy layered on top, not a change to what the engine or
  `/analyze` will accept.

**Reopening a saved deal is exempt from the blank/review treatment.** A
persisted deal's values — via `GET /deals/{id}` — populate the form
**normally, never blank**, regardless of whether a given V2 field happens to
be `0`. A saved deal represents its analyst's actual, on-the-record
assumptions, not intake provenance; Anchor does not track, on reopen,
whether a persisted `0` originated from deliberate entry or from a legacy
default at the moment it was first saved. This mirrors exactly how the
original nine fields have always been treated once persisted.

**Why this is not a provenance system.** Nothing new is persisted. The
"was this reviewed" signal is a session-local, ephemeral, purely
frontend-computed value ("are any of these five fields currently blank right
now"), recomputed on every render from ordinary form state, discarded the
moment a value is saved. It reuses three things that already exist — blank
vs. populated form state, the Excel reader's already-existing Field-ID
presence scan, and OM ingestion's existing "no candidate, stays blank"
behavior — and adds exactly one small, already-mostly-computed response field
(the defaulted-Field-ID list) plus one banner. No evidence-status enum,
citation, or confidence tracking is introduced for these fields.

## Impact on Manual UI

`AssumptionsForm` currently groups the nine fields into three groups of
three. Five new fields need a fourth logical group ("Costs & Reserves": the
four percentage/currency fields), with `io_period` joining the existing
Financing group. No new input widget type is required — every new field is a
plain percentage, currency, or integer input, identical in kind to the
existing nine.

## Impact on OM Ingestion

OM extraction is **not** extended to propose candidates for the five V2
fields in this phase. Acquisition/financing/disposition costs and CapEx
reserves are frequently analyst assumptions rather than seller-disclosed
figures in an offering memorandum, unlike the original nine, which are
typically directly stated. Extending the provenance/evidence-status
machinery (`EvidenceStatus`, `ExtractionCandidate`) to less-reliably-stated
assumptions is separate, deferred work. This is a deliberate, communicated
initial-launch limitation, not an oversight.

## Impact on Sensitivity and Break-Even

Not extended in this phase. Sensitivity's presets and break-even's solve
targets both operate on a small, hand-curated assumption-ID set today;
plugging the five new fields in is an independent, lower-risk follow-on once
the core engine change is stable and tested.

## Impact on Persistence

Five new `NOT NULL` columns on the `deals` SQLite table — the first schema
migration this project needs, matching the migration strategy the Phase A
persistence work already anticipated (`ALTER TABLE ... ADD COLUMN ... NOT
NULL DEFAULT 0`, gated by `PRAGMA user_version`, no data rewrite). Same
`REAL`/`INTEGER` numeric-representation architecture already established —
no new representation question is introduced.

## Reference-Case and QA Strategy

1. **First test written, before any input-specific test**: the existing V1
   golden case, re-run with all five V2 inputs at their neutral defaults,
   must reproduce today's `AcquisitionResults` to the exact tolerance already
   used for that case. This is the mechanism that *enforces* the
   backward-compatibility design goal below — see that section for what this
   document does and does not claim about it today.
2. The V2 Golden Reference Case (`docs/underwriting_v2_golden_case.md`)
   becomes the new authoritative V2 reference, at the same frozen status as
   the existing V1 golden case.
3. **Per-input differential tests**: starting from the V1 golden case, vary
   exactly one new input at a time and assert exactly which output fields
   move and which do not, directly testing the affects/does-not-affect
   conventions defined above.
4. **IO boundary tests**: `io_period=0` (must equal no-IO exactly),
   `io_period < hold_period`, `io_period == hold_period`,
   `io_period > hold_period`, `io_period + amortization == hold_period`,
   `io_period + amortization < hold_period`.
5. **`min_dscr` tests**: equals `headline_dscr` when DSCR is flat/monotonic;
   strictly less than `headline_dscr` in an IO scenario; `None` only when
   every `DSCR_y` is `None`.
6. **Architecture guardrails extended, not replaced**: the existing
   AST-import-guardrail and `patch(..., wraps=...)` delegation-proof pattern
   must cover any new AI-Analyst-facing context referencing the five new
   fields — AI still only ever receives already-computed values.

## Backward-Compatibility Design Goal

The financial conventions in this document are **designed** so that, at the
five V2 inputs' neutral defaults, every formula above reduces algebraically
to the exact, unmodified V1 formula — this is demonstrated by direct
substitution throughout this document (e.g. `Initial Equity` collapsing to
`purchase_price - loan_amount`, `UCF_0` collapsing to `-purchase_price`,
`Payment_t` collapsing to the unmodified V1 `PMT` schedule when
`io_period = 0`). This is a design property of the conventions, established
by this specification — it is **not yet a proven property of any
implementation**, because no implementation exists yet.

This guarantee must be enforced, during implementation, by a **permanent
V1-neutral regression test**: the existing V1 golden case, submitted through
the V2-shaped engine with all five new inputs at their neutral defaults, must
reproduce the exact `AcquisitionResults` the V1 engine already produces, at
the same tolerance the existing golden-case test already uses. That test —
not this document — is what proves the guarantee; it must be written before
Phase 2 of the implementation sequence is considered complete, and must
remain permanently in the suite. If that test is ever weakened or removed,
the backward-compatibility guarantee silently lapses.

## Recommended Phased Implementation Sequence

0. **Spec sign-off** — this document and the V2 golden case, frozen. No code. *(This phase.)*
1. **Contract** — `AcquisitionInputs`/`validate_acquisition_inputs` gain the
   five fields with neutral defaults; zero engine change. Full existing suite
   must pass unmodified.
2. **Engine, one-time additions** — acquisition costs, financing fee,
   disposition costs. No debt-structure change yet. The V1-neutral regression
   test (above) is written and passes at this point, before any further
   engine phase begins.
3. **Engine, recurring addition** — `annual_capex_reserve`, isolated from
   debt-structure work.
4. **Engine, debt-structure addition** — `io_period` + `min_dscr`. Last among
   engine phases: the most mechanically involved generalization, built on
   the simpler, already-stable additions.
5. **Excel ingestion** — five new optional Field IDs, the defaulted-Field-ID
   response addition, a new canonical example workbook.
6. **Persistence** — schema migration, round-trip tests for the expanded contract.
7. **Frontend** — new AssumptionsForm group, the blank/review-banner
   mechanism, results-display additions (cost/reserve breakout, `min_dscr`).
8. **AI Analyst** — prompt/context expanded to reference the new fields; still zero calculation.
9. *(Optional, lower priority)* Sensitivity/break-even axis extensions.

## Risks and Unresolved Decisions

1. **Validation-strictness relaxation.** Making the five new fields optional
   with zero defaults at the `/analyze` payload and Excel-ingestion
   boundaries is a genuine, deliberate weakening of the current "no missing,
   no extra" backend validation philosophy, needed for backward
   compatibility. Confirmed as an intentional, scoped exception limited to
   these five fields.
2. **OM ingestion is not extended to the five new fields in this phase** — a
   real, user-visible limitation to communicate, not silently ship.
3. **Sensitivity/break-even are not extended in this phase** — users may want
   this soon after V2 ships; expectations should be set.
4. **`min_dscr`'s prominence is a product decision**, not purely
   engineering — how visible it should be alongside `headline_dscr` needs
   product sign-off.
5. **`annual_capex_reserve` does not scale with NOI or inflation.** A flat
   reserve slightly understates real capital needs late in a strong
   NOI-growth hold and slightly overstates them in a declining-NOI scenario,
   relative to a percentage-of-NOI convention. A deliberate, acknowledged
   trade-off in exchange for not coupling a cost assumption to a growth
   assumption and not requiring a new escalation input.
6. **The review-banner/blank-field mechanism is intake-time only.** It does
   not resurface on reopening a previously saved deal (by design — see
   "Backward-Compatibility-Preserving UX for Intake" above). Worth explicit
   confirmation that this is the intended scope of the guarantee, not a gap.
7. **The backward-compatibility guarantee is a design property until the
   permanent V1-neutral regression test exists and passes** — see the
   dedicated section above. This document alone does not prove it.
