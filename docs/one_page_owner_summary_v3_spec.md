# One-Page Owner Summary V3 — Gate B1 Specification

Sprint B, Gate B1. **Specification only.** No engine, API, persistence, AI
prompt, frontend component, or test in this repository is modified by this
document. Every data source cited below was confirmed by reading the actual
current contracts (`src/anchor/engine/contracts.py`,
`src/anchor/contracts.py`, `src/anchor/analysis/contracts.py`,
`src/anchor/ai/contracts.py`, `src/anchor/deals/contracts.py`,
`web/src/types.ts`, `web/src/App.tsx`, `web/src/components/ResultsPanel.tsx`)
at the time of writing, not assumed from memory or from other gates'
descriptions.

---

## 1. Product Objective

A one-page, owner-oriented deal summary that lets an investment principal
understand a deal in roughly 30–60 seconds, before ever touching a detailed
schedule. It must read as an investment story, not a dump of underwriting
fields, and it must answer, in order: what is the deal, what is the play,
what am I paying, what does the property earn, what return am I getting, how
safe is the debt, what drives the result, what could go wrong, and what part
of the stated strategy is not yet modeled.

Guiding line: *"If it does not make sense on one page, it will not make
sense on 100 pages."*

## 2. Design Principles

1. **Presentation only.** The summary is a new arrangement of already-
   authoritative data. It performs no calculation — not IRR, not CoC, not
   DSCR, not NOI, not debt yield, not a growth rate, not a valuation, not a
   sensitivity, not a refinance scenario. Every number it shows already
   exists on `AcquisitionResults`, an input contract, a sensitivity/break-even
   result, or `AIAnalysis`.
2. **One shared architecture, not two products.** Quick and Detailed render
   the same `OwnerSummaryPanel` from the same `AcquisitionResults` shape —
   exactly the pattern `ResultsPanel` already uses today (`App.tsx` calls it
   as `<ResultsPanel results={results} />` for Quick and
   `<ResultsPanel results={detailedResults.results} />` for Detailed). No
   `QuickSummary`/`DetailedSummary` split.
3. **Hierarchy over completeness.** The page is not obligated to show every
   available field. A field earns a place by helping the owner decide, not
   by existing.
4. **Deal Context is framing, not fact.** The user's stated strategy is
   visually and semantically distinct from modeled, deterministic output —
   mirroring the AI system prompt's own existing DEAL CONTEXT RULES
   (`src/anchor/ai/prompts.py`), which already require the model to never
   restate Deal Context as established fact.
5. **Graceful absence, never fabrication.** A missing analysis, missing AI
   output, missing sensitivity/break-even, or a structurally `None` metric
   (zero leverage, zero initial equity, one-year hold) is displayed as an
   absence — `N/A` or an explicit "not yet calculated" state — never a
   fabricated zero or invented number.

## 3. Authoritative Data Sources

The summary may read only from:

- `AcquisitionResults` (identical shape for Quick and Detailed; for Detailed
  it is `DetailedAcquisitionResults.results`, plus `DetailedAcquisitionResults
  .operating_projection` for the Detailed-only operating schedule)
- `AcquisitionInputs` (Quick) / `AcquisitionTerms` + `DetailedOperatingInputs`
  (Detailed) — the validated assumptions, not re-derived
- `Deal.deal_context` — user-authored, optional, never engine input
- `StandardSensitivityPresets` / `StandardDetailedSensitivityPresets` and
  `StandardBreakEvenAnalysis` / `StandardDetailedBreakEvenAnalysis` — already
  computed by the existing `/sensitivity`, `/sensitivity/presets`, and
  `/break-even` endpoints; the summary never calls these itself, it reads
  whatever the workspace's existing `sensitivity`/`breakEven` React state
  already holds
- `AIAnalysis` (the existing `ai_snapshot` / live AI Analyst output)
- The already-computed, in-memory `saveStatus`/`isDirty`/`operatingMode`
  workspace state `App.tsx` already maintains

It must never call `/analyze`, `/sensitivity`, `/break-even`, or `/ai/analysis`
itself, and it must never write to any persisted state.

## 4. Final Information Hierarchy

**A. Deal Identity** — Deal name, operating mode badge (Quick/Detailed),
save status. *No property address or image* — see §17 (Data Gaps).

**B. The Play** — `deal_context`, labeled and visually distinct (§8). Omitted
(collapsed, not a blank card) when absent.

**C. Investment Snapshot** — Purchase Price, Year 1 NOI, Going-In Cap Rate,
Hold Period, Exit Cap Rate, LTV, Interest Rate; IO Period shown only when
`io_period > 0`. All nine are either a raw authoritative input or
`AcquisitionResults.going_in_cap_rate`/`noi_by_year[0]` — see §21 row-by-row.
`current_noi` (Quick's raw input) is **not** the source for "Year 1 NOI" —
`AcquisitionTerms`/`DetailedOperatingInputs` has no `current_noi` field at
all, so the only field that exists identically in both modes is
`AcquisitionResults.noi_by_year[0]`. Using it uniformly is also strictly
correct for Quick, since `occupancy` is confirmed (by the `AcquisitionTerms`
docstring) to affect no downstream calculation — `noi_by_year[0] ==
current_noi` always holds for Quick.

**D. Key Returns** — Levered IRR, Unlevered IRR, Equity Multiple.

**E. Owner Returns** — Year 1 Levered CoC, Year 1 Debt Yield, Cumulative
Operating Distributions through hold. An optional compact annual Levered CoC
trend (reusing the full `levered_cash_on_cash_by_year` tuple already on
`AcquisitionResults` — no new data).

**F. Debt / Risk** — Year 1 DSCR with Minimum DSCR as a caption (the exact
pattern `ResultsPanel` already uses — see §5), Loan Amount, and IO Period
inline if greater than zero.

**G. Operating Story** — Year 1 NOI, Final-Year NOI (labeled dynamically —
"Year `{hold_period}` NOI", never a hardcoded "Year 5"), and the modeled
growth *inputs* as an informational note: Quick shows `noi_growth`; Detailed
shows `revenue_growth`/`expense_growth` (two independent rates — there is no
single blended figure). These are raw, already-authoritative inputs, not a
computed CAGR — no new metric is introduced. **No NOI CAGR is computed or
shown**, per charter.

**H. Sensitivity / Break-Even Highlights** — Base Levered IRR, Max Purchase
Price for the target return metric, Max Exit Cap Rate for the target return
metric, Max Interest Rate for the target DSCR — all read directly off
`BreakEvenResult.solved_assumption_value`/`.status`. See §10 for the
important caveat that this section is very frequently empty on a freshly
reopened saved deal.

**I. Key Risks / Model Gaps** — A concise AI-derived block. See §9.

Rationale for what was cut from the charter's suggested list: `occupancy` is
excluded from Investment Snapshot — it is Quick-only, informational, and (per
the `AcquisitionTerms` docstring) read by no downstream calculation, so
showing it on the one owner-facing summary risks implying it drives the
numbers below it. `acquisition_cost_pct`/`financing_fee_pct`/
`disposition_cost_pct`/`annual_capex_reserve` stay out of the one-pager
entirely — they belong to `ResultsPanel`'s existing "Capitalization"/"Exit"
detail cards, not to a 30-second read.

## 5. Hero Metrics

Evaluated the charter's proposed Tier 1/Tier 2 split against
`AcquisitionResults` directly; one change recommended.

**Tier 1 (hero cards, maximum 4):**
- Levered IRR
- Equity Multiple
- Year 1 Levered CoC
- **Year 1 DSCR, with Minimum DSCR as a caption** (not "Minimum DSCR" alone)

The charter proposed "Minimum DSCR" as the fourth hero card. `ResultsPanel`
already establishes the convention of presenting DSCR as *Year 1 value, Min
as a secondary line* (`StatCard` with a `caption` prop) — a lone "Minimum
DSCR" number loses the Day-1 anchor point an owner and a lender both think in
first. Reusing the existing two-line pattern gives both numbers without a
fifth card and keeps one visual convention for "the DSCR story" across the
whole app.

**Tier 2 (supporting cards, maximum 4):**
- Unlevered IRR
- Year 1 Debt Yield
- Cumulative Operating Distributions (through hold)
- Year 1 NOI

## 6. Supporting Metrics

Everything in §4.C/F/G not already promoted to a hero/Tier-2 card: Purchase
Price, Going-In Cap Rate, Hold Period, Exit Cap Rate, LTV, Interest Rate, IO
Period (conditional), Loan Amount, Final-Year NOI, modeled growth input(s).
Rendered as compact info rows (`InfoRow`-style, not `StatCard`), consistent
with `ResultsPanel`'s existing secondary-information styling.

## 7. Quick vs Detailed Behavior

**Common sections (identical component, identical props shape):** Deal
Identity, The Play, Investment Snapshot (minus IO Period when zero), Key
Returns, Owner Returns, Debt/Risk, Sensitivity/Break-Even Highlights, Key
Risks/Model Gaps. All of these read from the same `AcquisitionResults`
instance regardless of mode — Detailed's caller simply passes
`detailedResults.results` instead of `results`, exactly as `App.tsx` already
does for `ResultsPanel`.

**Detailed-only enrichment:** Operating Story's growth note shows
`revenue_growth`/`expense_growth` instead of Quick's single `noi_growth`. No
other Detailed-only card is warranted for B1 — `OperatingProjection`'s
eleven line-item schedules stay in the existing institutional operating
statement, not the one-pager (adding e.g. an expense ratio would be a new,
uncomputed-today metric, out of scope).

No blank cards for a field one mode lacks — a card is omitted, not rendered
empty, exactly like `deal_context`'s own omit-when-blank rule.

## 8. Deal Context Treatment

Labeled **"THE PLAY"**, secondary caption "User strategy" (or equivalent),
styled visibly differently from every authoritative metric card — e.g. a
quoted/italic block on a neutral background, never inside a `stat-card`.
Blank Deal Context omits the section (a subtle "No Deal Context provided" is
acceptable but not required) — never fabricated text. Density: show at most
2–3 lines by default (roughly 200–280 characters); a "show more" affordance
for longer text is acceptable but not required for B1 (out of scope: full
rich-text or markdown rendering of Deal Context — it is always plain text
today).

## 9. AI Role

**No new AI output is implemented in B1.** Two real options exist for a
future gate:

- **(A) Deterministically reuse existing `AIAnalysis` fields.** Show
  `investment_view` verbatim and the first 1–2 entries of `strengths`/
  `risks` verbatim (whole tuple entries — never truncating mid-sentence).
  This works today, with zero new contract, but has no dedicated "Model Gap"
  slot: the refinance/strategy-mismatch flag the AI is *already instructed*
  to produce (`SYSTEM_PROMPT` rule 13f, `src/anchor/ai/prompts.py`) has no
  guaranteed field to land in — it may appear inside `risks`,
  `downside_analysis`, or `capital_structure_analysis`, or nowhere
  extractable, depending on how the model phrases it that run.
- **(B) A dedicated, concise "Deal Story" AI contract** (recommended for
  B4): a new, narrow output —
  ```
  investment_view: str          # 1-2 sentences
  key_strengths: tuple[str, ...] # max 2
  key_risks: tuple[str, ...]     # max 2
  model_gap: str | None          # max 1, explicitly the strategy-mismatch /
                                  # not-modeled-capability statement
  ```
  generated by its own prompt (reusing the existing `AnalysisContext`/
  `build_presentation_payload` evidence pipeline — no new deterministic data
  needed), so the "what's not modeled" line is a first-class, reliably
  present field instead of an implicit hope inside free text.

**Recommendation: (B).** It is the only architecture where "Model Gap" is
guaranteed to exist as its own slot rather than something the frontend has
to go fishing for inside `risks`/`downside_analysis`. Frontend text
truncation of an arbitrary AI paragraph is explicitly rejected as a primary
solution, per charter — (A) avoids truncation (it only selects whole,
already-discrete tuple entries) but still cannot guarantee a Model Gap
exists at all. Until B4 ships, B2 should implement (A) as a stopgap with an
explicit "Model Gap" area that simply does not render when nothing in the
existing fields is identifiable as one — never inferred by frontend keyword
matching.

**Explicitly rejected:** brittle frontend keyword-matching over `risks`/
`downside_analysis` text (e.g. searching for the word "refinance") to
synthesize a Model Gap bullet. This is a presentation layer; inventing
semantic extraction over free-form prose is exactly the kind of fragile logic
the charter warns against, and it would silently break the moment the model
phrases the same finding differently.

## 10. Sensitivity / Break-Even Treatment

No matrix, no grid. Four numbers only, read directly off already-computed
`BreakEvenResult`s: Base Levered IRR (`baseline_metric_value` off any of the
existing break-even results — they share one base case), Max Purchase Price,
Max Exit Cap Rate (both driven by `context.return_hurdle_metric`'s selected
target), and Max Interest Rate (always DSCR-driven). A `NO_SOLUTION_IN_RANGE`
status renders as "No solution within the tested range" — never a fabricated
number, never restated as "impossible."

**Important architectural finding, not previously documented at the
presentation layer:** sensitivity and break-even are **not persisted**.
`Deal` only carries `analysis_snapshot`/`ai_snapshot`; `sensitivity`/
`breakEven` are pure in-session React state, and `handleOpenDeal` restores
only `results`/`lastRequest`/`aiAnalysis` — confirmed by reading `App.tsx`
directly. This means **this section will very commonly be empty
immediately after reopening any saved deal**, even though Key Returns/Owner
Returns/Debt-Risk are fully populated from the restored snapshot. This is
not an edge case — it is the default state on every reopen until the analyst
clicks Analyze again in that session. The section must have a first-class
"Not yet calculated this session" state, not just a loading spinner.

## 11. Empty / Null States

| Situation | Behavior |
|---|---|
| No analysis yet | Owner Summary does not render at all (there is nothing to summarize) — same gate `ResultsPanel` already uses (`{results && <ResultsPanel .../>}`) |
| No Deal Context | Omit "The Play," or a single subtle line — never fabricated strategy text |
| No AI analysis yet (including reopened deal with `ai_snapshot === null`) | Omit Key Risks/Model Gaps section, or show "AI analysis not yet generated for this deal" |
| Quick mode | Operating Story shows `noi_growth` only; no Detailed-only fields ever attempted |
| `year_1_debt_yield === null` (all-cash deal) | "N/A" via the existing `formatPercent`/`formatMultiple`/`formatCurrency` null convention (`web/src/format.ts` already returns `"N/A"` for `null`/`undefined` — reuse, do not reimplement) |
| `levered_cash_on_cash_by_year[0] === null` (zero initial equity) | "N/A", same convention |
| One-year hold | Final-Year NOI equals Year 1 NOI — both shown as-is, no artificial distinct card suppressed |
| Sensitivity/break-even not yet computed this session | "Not yet calculated this session" per §10 — not a spinner, not a fabricated placeholder |
| Saved deal with restored analysis but no AI snapshot | Results/Returns/Debt sections render fully; Key Risks/Model Gaps section shows its empty state only |

No fake zeros anywhere. `N/A` reserved for a metric that is conceptually
undefined for this scenario, never used for "hasn't loaded yet" (which gets
its own distinct empty-state copy).

## 12. Persistence Behavior

The summary consumes the exact same hydrated `results`/`detailedResults`/
`aiAnalysis` state the rest of the workspace already restores from
`analysis_snapshot`/`ai_snapshot` on deal open — **no new persisted
artifact.** No "summary snapshot" is introduced. A future concise AI Deal
Story (§9 option B) may reuse the *existing* `ai_snapshot` persistence path
if its shape is added to (or replaces) `AIAnalysis`, or may need its own
narrow snapshot column if it is generated by a separate call — that decision
belongs to B4, once the actual contract shape and generation trigger are
designed; it is out of scope to decide here.

## 13. Navigation Recommendation

Inspected the current shell: one `operating-mode-toggle` (Quick/Detailed)
plus a `view: 'workspace' | 'library'` switch (`App.tsx`). Within a
workspace, the assumptions form and every results panel
(`ResultsPanel`, `OperatingStatementTable`, `SensitivityPanel`,
`BreakEvenPanel`, `AiAnalystPanel`) already render as one continuous vertical
stack — there is no existing sub-tab structure inside "Results" to slot a
new tab into.

**Recommendation: Option B** — render `OwnerSummaryPanel` as the first thing
shown once `results`/`detailedResults` exist, positioned immediately above
the existing `ResultsPanel` (which, along with everything below it, is
unchanged and reachable by scrolling). This satisfies "first thing an owner
sees after analysis" with the smallest possible diff to the existing render
tree — no new view-state machine, no tab bar, no restructuring of the
existing panels. A dedicated Summary/Full-Analysis toggle (Option D) is a
reasonable future evolution if the page grows too long, but is unnecessary
for B1/B2 and would be a larger UI change than this gate's scope calls for.

## 14. Text Wireframe

```
------------------------------------------------------------
 [Deal Name]                    [QUICK|DETAILED]  [Saved ·]
------------------------------------------------------------
 THE PLAY  (user strategy)
 "quoted deal-context text, 2-3 lines, or omitted"
------------------------------------------------------------
 KEY RETURNS  (hero, 4 cards)
 Levered IRR | Equity Multiple | Yr1 Levered CoC | Yr1 DSCR (Min: x)
------------------------------------------------------------
 INVESTMENT SNAPSHOT              |  DEBT / RISK
 Purchase Price                   |  Loan Amount
 Year 1 NOI                       |  Year 1 DSCR (Min: x)
 Going-In Cap Rate                |  IO Period (if > 0)
 Hold Period · Exit Cap · LTV     |
 Interest Rate                    |
------------------------------------------------------------
 OPERATING STORY                  |  OWNER RETURNS
 Year 1 NOI -> Year H NOI         |  Yr1 Debt Yield
 Modeled growth (input, not calc) |  Cumulative Distributions
------------------------------------------------------------
 BREAK-EVEN HIGHLIGHTS  (or "Not yet calculated this session")
 Base IRR | Max Price | Max Exit Cap | Max Rate
------------------------------------------------------------
 INVESTMENT VIEW  (AI, if generated)
 1-2 sentences
 STRENGTHS (max 2)     RISKS (max 2)     MODEL GAP (max 1, if any)
------------------------------------------------------------
```

Not mandatory — a card-grid rather than a strict linear stack is equally
valid, provided the reading order above is preserved.

## 15. Density Rules

- Maximum 4 hero cards.
- Maximum 2 supporting-card groups side by side per row (Investment
  Snapshot/Debt-Risk, then Operating Story/Owner Returns) — matches
  `ResultsPanel`'s existing `card-row` (3-across) convention, scaled down
  for a shorter page.
- Maximum 4 break-even highlight numbers.
- Maximum 2 AI strengths, 2 AI risks, 1 model-gap bullet.
- Maximum ~3 lines (≈250 characters) of Deal Context shown by default.
- Tooltips: reserved for clarifying a metric's definition (e.g. "Year 1 Debt
  Yield = Year 1 NOI ÷ Loan Amount") — never for content required to read
  the page (per §18, core content must never be hover-only).
- Compact tables: none on this page — the one candidate (an annual CoC
  trend) is a small sparkline/strip, not a table; the full annual schedule
  stays in `OwnerReturnSchedule` below.
- Hide, do not gray out, a field that is structurally unavailable for the
  current mode (no "N/A" card for a field that doesn't exist in this mode —
  `N/A` is reserved for a field that exists but is `None` this run).

## 16. Future Export Considerations

Not implemented in B1. Design choices already compatible with a future
PDF/PPT export:
- Fixed, named sections (§4) rather than a freeform dashboard — predictable
  slicing into pages/slides later.
- No content that exists only on hover (§15) — a printed page can't hover.
- Stable labels (already true of every metric name reused from
  `ResultsPanel`/`AIAnalysis`).
- Deterministic rendering — every value is a direct read of already-computed
  state, so the same deal renders identically every time (no animation-
  dependent or randomized content).
- A reasonable, roughly-1440px-wide desktop layout maps predictably onto a
  single portrait or landscape page later.
- No drag-and-drop or interactive-only layout (§19 already excludes this).

## 17. Explicit Non-Goals (Sprint B1)

Per charter §19, unchanged: PDF export, PowerPoint export, property images,
document thumbnails, Market Intelligence, refinance engine, AAR, Current
Equity, Current LTV, current implied valuation, lease-by-lease engine,
post-acquisition Deal Tracker, Development Engine, large UI redesign,
drag-and-drop dashboard customization. Additionally out of scope for B1
specifically: any new AI contract (§9), any new persisted artifact (§12), any
new sensitivity/break-even computation, print CSS.

## 18. Open Questions

1. **Hurdle targets are not persisted per-deal.** `target_levered_irr`/
   `target_equity_multiple`/`target_headline_dscr` live only as ephemeral
   `App.tsx` form state (`DEFAULT_TARGET_LEVERED_IRR_PERCENT`, etc.),
   editable in the Break-Even panel, reset to hardcoded defaults every
   session/reload — never stored on `Deal`. If the Owner Summary shows an
   "Actual vs Target" comparison, the target shown will be whatever is
   currently in that session's form state, not necessarily whatever the
   analyst had in mind when the deal was last saved. Confirmed acceptable
   for B1 (the charter only asks for this "if targets are already
   authoritative application inputs," which they are — just not persisted).
   **Should hurdle targets become a persisted per-deal field in a later
   gate?** Not decided here.
2. **AI Model Gap interim behavior (§9):** is showing nothing (rather than a
   best-effort excerpt from `risks`/`downside_analysis`) acceptable for B2,
   pending B4's dedicated contract? Recommended yes, but this is a product
   call, not a technical one.
3. Should the Owner Summary be visible for a *dirty* (unsaved-edits) deal,
   or only for a clean/saved analysis? The current recommendation (§13)
   renders it whenever `results`/`detailedResults` is non-null, matching
   `ResultsPanel`'s own gating — i.e. yes, it also shows for an unsaved or
   dirty deal, exactly like every other results panel today. Flagging in
   case product wants different behavior for the "story" page specifically.
4. Annual Levered CoC trend sparkline (§4.E) is optional per charter
   ("only if it materially improves comprehension") — left as a B2
   implementation judgment call, not decided here.

---

## 19. Contract Inventory

Every field named in §4–§10, mapped to its exact current source.
`NEW CONTRACT REQUIRED?` is "No" unless stated otherwise.

| Summary Field | Current Authoritative Source | Quick? | Detailed? | Nullable? | New Contract Required? |
|---|---|---|---|---|---|
| Deal Name | `Deal.name` | Yes | Yes | No | No |
| Operating Mode | `Deal.operating_mode` | Yes | Yes | No | No |
| Save Status / Last Saved | `App.tsx`-computed (`saveStatus`, `lastSavedAt`) | Yes | Yes | N/A | No |
| Property Address | *(none — see §17 gap below)* | No | No | — | Not proposed; data gap |
| The Play (Deal Context) | `Deal.deal_context` | Yes | Yes | Yes | No |
| Purchase Price | `AcquisitionInputs.purchase_price` / `AcquisitionTerms.purchase_price` | Yes | Yes | No | No |
| Year 1 NOI | `AcquisitionResults.noi_by_year[0]` | Yes | Yes | No | No |
| Going-In Cap Rate | `AcquisitionResults.going_in_cap_rate` | Yes | Yes | No | No |
| Hold Period | `AcquisitionInputs.hold_period` / `AcquisitionTerms.hold_period` | Yes | Yes | No | No |
| Exit Cap Rate | `AcquisitionInputs.exit_cap_rate` / `AcquisitionTerms.exit_cap_rate` | Yes | Yes | No | No |
| LTV | `AcquisitionInputs.ltv` / `AcquisitionTerms.ltv` | Yes | Yes | No | No |
| Interest Rate | `AcquisitionInputs.interest_rate` / `AcquisitionTerms.interest_rate` | Yes | Yes | No | No |
| IO Period | `AcquisitionInputs.io_period` / `AcquisitionTerms.io_period` | Yes | Yes | No (0 = none) | No |
| Levered IRR | `AcquisitionResults.levered_irr` | Yes | Yes | Yes | No |
| Unlevered IRR | `AcquisitionResults.unlevered_irr` | Yes | Yes | Yes | No |
| Equity Multiple | `AcquisitionResults.equity_multiple` | Yes | Yes | Yes | No |
| Year 1 DSCR | `AcquisitionResults.headline_dscr` (or `dscr_by_year[0]`, identical value) | Yes | Yes | Yes | No |
| Minimum DSCR | `AcquisitionResults.min_dscr` | Yes | Yes | Yes | No |
| Loan Amount | `AcquisitionResults.loan_amount` | Yes | Yes | No (0 if all-cash) | No |
| Year 1 Levered CoC | `AcquisitionResults.levered_cash_on_cash_by_year[0]` | Yes | Yes | Yes | No |
| Year 1 Debt Yield | `AcquisitionResults.year_1_debt_yield` | Yes | Yes | Yes | No |
| Cumulative Operating Distributions | `AcquisitionResults.cumulative_operating_distributions_by_year[-1]` | Yes | Yes | No | No |
| Annual Levered CoC trend (optional) | `AcquisitionResults.levered_cash_on_cash_by_year` (full tuple) | Yes | Yes | Yes (entries) | No |
| Final-Year NOI | `AcquisitionResults.noi_by_year[-1]` | Yes | Yes | No | No |
| Modeled NOI Growth (Quick) | `AcquisitionInputs.noi_growth` | Yes | N/A | No | No |
| Modeled Revenue/Expense Growth (Detailed) | `DetailedOperatingInputs.revenue_growth` / `.expense_growth` | N/A | Yes | No | No |
| Base Levered IRR (break-even baseline) | `BreakEvenResult.baseline_metric_value` (session-only `breakEven` state) | Yes* | Yes* | Yes | No |
| Max Purchase Price for target | `StandardBreakEvenAnalysis(Detailed).max_purchase_price.{solved_assumption_value,status}` | Yes* | Yes* | Yes | No |
| Max Exit Cap Rate for target | `...max_exit_cap_rate.{solved_assumption_value,status}` | Yes* | Yes* | Yes | No |
| Max Interest Rate for target DSCR | `...max_interest_rate.{solved_assumption_value,status}` | Yes* | Yes* | Yes | No |
| Return hurdle targets (IRR/EM/DSCR) | Ephemeral `App.tsx` form state, not on `Deal` | Yes (session default) | Yes (session default) | N/A | Maybe — open question §18.1 |
| AI Investment View | `AIAnalysis.investment_view` | Yes | Yes | Yes (no `ai_snapshot`) | No (B2 stopgap); dedicated contract recommended for B4 |
| AI Key Strengths (max 2) | `AIAnalysis.strengths[0:2]` | Yes | Yes | Yes | No (B2 stopgap); dedicated field recommended for B4 |
| AI Key Risks (max 2) | `AIAnalysis.risks[0:2]` | Yes | Yes | Yes | No (B2 stopgap); dedicated field recommended for B4 |
| Model Gap / Strategy Mismatch | *(no discrete field — implicit in AI prose only, per `SYSTEM_PROMPT` rule 13f)* | Yes (unreliable) | Yes (unreliable) | Yes | **Yes — recommended new `model_gap: str \| None` field in B4** |

`*` = available only when the workspace has run Analyze in the current
session; never restored from a saved deal's persisted snapshot (§10).

### Confirmed data gap: property identity metadata

There is no persisted property address, image, or thumbnail anywhere in the
current `Deal`/`AcquisitionInputs`/`AcquisitionTerms` contracts. An
`address` field exists only as a transient OM-ingestion candidate
(`ExtractionResult.address` / `DealContext` in `anchor/ingestion/contracts.py`,
Quick-mode ingestion only — Detailed's `DetailedExtractionResult` doesn't even
have one) shown during the ingestion-review step and **never carried forward
into a saved `Deal`**. Per charter §4.A and §19, no new address/image
architecture is proposed here; this is recorded as a known gap for a future
gate to decide on, not solved now.
