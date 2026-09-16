# P7.8B Capital Structure Product Integration

Status: Session B implementation complete; automated backend/frontend proof and
the browser QA are complete; **human visual acceptance is pending**
(Section 14).
Base: Session A's reviewed head `f5850ad` on
`feature/p7-8-structured-position-returns`.
Risk: Tier 2 (state / integration), over a Tier 1 engine that does not move.

`docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md` is the authority
(Sections 7.4, 12, 14.1 and 15).
`docs/architecture/P7_8_STRUCTURED_POSITION_ECONOMICS.md` records the financial
engine this gate makes reachable; **every formula there is frozen**, and no
formula is restated here. `docs/architecture/P7_7_CAPITAL_STRUCTURE_FOUNDATION.md`
records the foundation both sit on.

---

## 1. What this gate is

P7.8A built and had approved a deterministic engine that nothing could reach:
no store, no route, no Strategy domain, no perspective. P7.8B connects it --
persistence, resolution, identity, fingerprints, orchestration, comparison and
the API -- **without changing one financial module**. The five P7.8A modules,
the four P7.7 modules and the mature engine are byte-identical to `f5850ad`,
and a guard proves it in the working tree.

## 2. One owner: the Investment

A Capital Structure belongs to an Investment (Section 15.1), never to a Deal
and never to a Unit:

- the implicit **Base Strategy owns the Investment's Base Capital Structure**;
- each **Strategy may own one whole replacement**;
- a Unit of a visible Investment has none of its own, and asking for one is a
  409 that says where the Investment's lives.

A standalone Deal reaches its structure through a convenience door
(`/deals/{id}/capital-structure`). Reading it materializes nothing; the first
non-empty save materializes the hidden one-unit Investment exactly as a first
Scenario or Strategy does (Q4), and the UI keeps saying "Deal". Clearing the
last structure removes the wrapper when no Scenario and no Strategy remain, and
the Deal is standalone again (P-11).

## 3. Schema v11: six additive tables

`capital_structures` (the owner marker: `owner_kind` `base` | `strategy`,
`UNIQUE (owner_kind, owner_id)`), and its children `capital_positions`,
`capital_funding_events`, `capital_position_fees`, `capital_debt_terms`,
`capital_preferred_terms`.

- **Additive only.** No `ALTER`, no legacy row read or rewritten; a v10 database
  gains six empty tables. The migration oracle is
  `tests/test_p7_8_compatibility_oracle.py`, which builds a real v10 database
  from the `a9f9b09` tree; every recorded response stays identical.
- **Relational and typed**, never a JSON blob: REAL for rates and dollars
  (bit-identical round trip), INTEGER for months, years and sequences, TEXT for
  the wire tokens the enums already use.
- **Position ids are owner-scoped.** The same `position_id` is *meant* to appear
  in the Base structure and in a Strategy's own, so every key is
  `(structure_id, ...)`. Event and fee ids repeat across structures the same way.
- **Fail closed.** A token the contract no longer knows, terms rows that
  disagree with a position's class, an orphaned child row, or a structure the
  P7.7 validator refuses raise `PersistedCapitalStructureDataError`. Nothing is
  repaired, and nothing reads as an empty structure.

## 4. Marker semantics (the distinction the gate turns on)

| Stored | Means |
|---|---|
| no `base` row | the Investment states no Base structure: the neutral empty one |
| no `strategy` row | that Strategy **inherits** the Base structure |
| a `strategy` row with no position | that Strategy **explicitly uses no structured capital** |

The last two are different rows, different wire payloads and different
resolutions. An empty `base` marker is never written, and a database holding one
is corrupt.

## 5. The Investment-root Strategy domain

`StrategyDomain.CAPITAL_STRUCTURE` is the first **Investment-root** domain.
`UNIT_STRATEGY_DOMAINS` (the five P7.4 domains) and
`INVESTMENT_STRATEGY_DOMAINS` are the two sets, and every rule reads them rather
than the enum.

- `InvestmentStrategyOverlay(domain, content)` is addressed **by its domain
  alone** -- no `unit_id`, no sentinel, no `"*"` -- because the positions inside
  it carry their own Unit or Investment scope.
- `StrategyDefinition.root_overlays` is additive and defaults to none.
- A root domain stated as a Unit overlay is refused (`root_domain_on_unit`), and
  a Unit domain stated at the root is refused (`unit_domain_at_root`).
  `root_domain_on_unit` is a **deliberate, wire-visible change**: before this
  gate, `capital_structure` on a Unit overlay was refused as
  `unsupported_domain`, because the domain did not exist. Now that
  `CAPITAL_STRUCTURE` is a published Strategy domain, the request is not an
  unknown domain but a known one stated in the wrong place, and it earns the
  more specific refusal. `tests/test_p7_4_strategy_api.py` pins the new code.
- P7.9 adds `PARTNERSHIP` to the same collection without another
  representation.

**Resolution** is whole-domain replacement (ST-2):
`resolve_capital_structure(base, strategy)` returns the Strategy's own structure
where it states one, else the Base structure. Never a merge; removing the
overlay restores the Base structure exactly (P-6).

**The Project pathway never sees it.** `_unit_strategy` drops root overlays
before resolution, so a Capital Structure cannot change a resolved Project
input, make a Project variant invalid, or reach a Project fingerprint (P-4).
`deals/variants.py` and `deals/investment_variants.py` are unchanged by this
gate, which is that layering stated in the ledger.

## 6. One position identity per Investment (P-8)

Within one Investment, a `position_id` that appears in more than one structure
names **one economic instrument**: its `PositionClass` and its `PositionScope`
are the same everywhere. Its name, funding, rate, maturity, priority, fees and
shortfall resolution may all differ -- that is what a Strategy is for.

A conflict is refused with `position_class_conflict` or
`position_scope_conflict`, on every write path (Base save, Deal save, Strategy
create and Strategy update). No id is regenerated for the analyst: a different
instrument gets a new id, and the frontend mints one when the class or scope of
an edited position changes.

This is what makes `POSITION(position_id)` a coherent perspective.

## 7. Layered fingerprints

```
PROJECT source fingerprint      the existing P7.2 / P7.4 / P7.6 resolved-input
        |                       fingerprint, UNCHANGED
        v
STRUCTURED source fingerprint = f(project fingerprint, resolved structure)
```

- **FP-2, exactly.** An empty resolved structure returns the project fingerprint
  *itself*, character for character. Neutral structured capital adds no second
  identity, and a Strategy that explicitly uses none collapses onto its own
  Project identity.
- **FP-1, exactly.** Only economics enter: class, priority, scope, resolution,
  funding timing/sequence/amount rule, debt and preferred terms, fee amounts and
  timing. A position's name, a fee's description, the authored tuple order, the
  storage row order, database ids and timestamps do not. A position's stable
  `position_id` does, because it is the addressable identity.
- Canonical order is `economic_order` (scope, then priority); events order by
  (model month, sequence).
- **Editing a Capital Structure therefore invalidates the structured analysis
  and the Position matrix, and nothing upstream.** The Project result, its cache
  and the Project Decision Matrix stay exactly as current as they were.

## 8. The structured variant service

`deals/structured_variants.py` is the one place a persisted structure meets the
approved executor:

- **hidden one-unit Investment**: `analyze_variant` + `inspect_variant_inputs`
  → `execute_unit_capital_structure`;
- **visible Investment**: `analyze_investment_variant` +
  `inspect_investment_variant_inputs` → `execute_investment_capital_structure`.

One service dispatches both; there is no second route family, resolver or
engine, and P7.6 consolidation is never reconstructed. A variant's result and
the inputs read beside it must share a Project fingerprint, or the pair is
refused (`StructuredVariantConflictError`) -- the P7.5 coherence rule applied to
one variant.

**Recomputed, never cached (Q14).** No structured result is persisted. The
Project half may still be served from its existing cache, and that status is
reported as operational metadata.

**Three distinct refusals, and one state that is not a refusal:**

| Raised | Means |
|---|---|
| `StrategyValidationError` / `ScenarioValidationError` / `LeaseValidationError` / `InvestmentVariantValidationError` | the **Project** variant is invalid |
| `CapitalStructureValidationError` | the structure is not a valid **contract** for this analysis |
| `CapitalStructureExecutionError` | a valid contract this **Project state** cannot execute (an over-funded closing, a convention P7.8 does not schedule) |
| *(nothing)* | an **unresolved Funding Requirement**: a successful analysis whose returns are N/A with a deterministic reason, and whose structural metrics stand |

## 9. The POSITION Decision Matrix (DC-3)

A new perspective over `StructuredCapitalResult`, with the Project matrix
untouched -- its perspective, catalog, Project fingerprints and its own matrix
fingerprint are exactly as they were.

- **Catalogs.** Eleven metrics for a claim-bearing position (funded amount, IRR,
  MOIC, profit, attachment and detachment LTP, last-dollar basis, debt yield
  through, headline and minimum coverage through, balance at maturity or exit);
  five for an authored Common Equity marker (Common Equity IRR, equity multiple,
  total equity invested, total cash returned, total profit), read from
  `StructuredCapitalResult.common_equity` and never from
  `AcquisitionResults.levered_*` (NS-1). Every value is one P7.8A field,
  selected.
- **Three honest cell states** (DC-2, P-9): an invalid variant; a valid variant
  whose Strategy does not hold the position (`not_applicable_to_perspective`,
  which also makes that row's Worst Case and Range unavailable); and a valid
  variant that holds it, whose *returns* may be N/A with the funding reason
  while its structural metrics stand.
- **Cross-cell figures** are the unchanged P7.5 Delta vs Base Scenario, Worst
  Case and Range, computed in the backend (Q22).
- **Differing holds** omit minimum coverage and balance at maturity or exit with
  the existing `different_hold_periods` reason (DC-4).
- **Identity**: the matrix fingerprint includes the selected `position_id` and
  every cell's *structured* fingerprint, so two positions over the same variants
  never share one.
- The whole run is bracketed by an economic state token that now includes every
  stored structure's canonical economics; a rename is not a conflict.

## 10. The API

| Route | Purpose |
|---|---|
| `GET`/`PUT /deals/{id}/capital-structure` | the Deal's door; GET materializes nothing, the first non-empty PUT opts in |
| `GET`/`PUT /investments/{id}/capital-structure` | the Investment's Base structure |
| `GET /investments/{id}/structured-variants/{strategy}/{scenario}/fingerprint` | both fingerprints, executing nothing |
| `POST /investments/{id}/structured-variants/{strategy}/{scenario}/analysis` | the structured analysis, either root |
| `GET /investments/{id}/position-perspectives` | the addressable positions, by name |
| `POST /investments/{id}/position-decision-matrix/{position_id}` | the Position matrix |

- **Kinds are explicit on the wire.** Each typed variant carries a `kind` from
  one codec (`deals/capital_structure_codec.py`), because a union is a class in
  Python and nothing at all in JSON.
- **The authoring surface is the executable subset.** Persistence can represent
  every P7.7 contract; these routes accept only what P7.8 executes -- closing
  funding, `FixedAmount` and `PctOfPrice`, closing fees, cash-pay debt and
  explicit preferred terms -- refusing the rest with P7.8A's own stable codes
  (`unsupported_amount_rule`, `unsupported_funding_timing`,
  `unsupported_fee_timing`, `unsupported_debt_pik`,
  `unsupported_debt_current_pay`).
- **Strategy responses are unchanged for a Strategy that states no structure**:
  `root_overlays` appears only when one is stated, so "inherits the Base
  structure" and "this gate added a field" can never be confused, and no
  existing response gained a key.

## 11. Lifecycle

- Deleting a **Strategy** deletes its own structure only.
- Deleting an **Investment** deletes every structure it owns and releases its
  Deals (Q3).
- Deleting a **Deal** takes its hidden wrapper and every capital row with it.
- A **Unit may not be removed** while a Base or Strategy structure scopes a
  position to it: 409, naming the position and the structure by their display
  names. Nothing is reassigned or deleted for the analyst (P7.6's rule,
  extended).
- **Promotion** keeps the same Investment, its structures and their position
  ids. It is refused when a stored structure names its residual at Unit scope,
  because a visible Investment's residual is the Investment's: the analyst
  changes the marker (under a new id, since scope is identity) or removes it
  first. Promotion never rewrites a stored financial contract.

## 12. What the frontend layer holds

The wire contracts (`capitalTypes.ts`), the Strategy root-overlay contracts, the
typed client (`api.ts`), two state hooks (`useCapitalStructure.ts` and
`usePositionDecisionMatrix.ts`), the editor's form model
(`capitalStructureForm.ts`), and four components: the editor, the result
surface, the Risk view that holds them, and the Position matrix.

**Capital Structure is the fourth decision view**, beside the Decision Matrix,
the Strategies and the Scenarios, in all three Deal modes and on a visible
Investment; an open editor is a draft, so leaving warns before it is discarded.

**A Strategy states its own structure once**, not per Unit -- its positions
carry their own scope, so there is nothing to address by `unit_id`. The choice
is Inherit Base or a whole replacement; the first switch to a replacement
prefills a deep copy of Base with every position id kept (P-8), and a
replacement holding no position is the third, explicit decision to use no
structured capital. The Strategy editor renders the same editor component,
embedded, so a structure is authored one way wherever it is stated.

**The Decision Matrix has two typed perspectives (DC-3).** A Project / Position
selector chooses between the deal's own economics and one capital position's
over the same variants. They are never mixed in one table: a Project IRR and a
mezzanine IRR are different claims on different cash. A cell whose Strategy does
not hold the selected position says so in words -- absent is not zero and not
unavailable (P-9) -- and a cell that holds it may still report no *return*, with
the engine's reason, while its structural metrics stand.

**It computes nothing.** Every funded amount, return, attachment, detachment,
last-dollar basis, debt yield, coverage, accrual, Funding Requirement and Common
Equity figure is a backend field, selected and formatted.
`web/src/capitalStructureArchitecture.test.ts` parses all eight modules and
allows exactly seven expressions: the four display-scale conversions and the
position-id sequence in `capitalStructureForm.ts`, and a reload counter in each
hook. Every other arithmetic expression, `Math` call, aggregate, ordering and
re-parse is rejected, and the editor, the result surface, the workspace and the
Position matrix hold **none**.

**No default is invented.** A new claim-bearing position has no shortfall
resolution selected and a preferred position that accrues has no convention
selected; both read "Choose…", and the editor names what is still unstated
before the round trip. **Identity is class and scope**: changing either mints a
new `position_id` rather than redefining the one the Position matrix addresses
(P-8), and the editor routes every such change through `withClassOrScope`.

## 13. Deferred, unchanged

`PctOfValue` and valuation timepoints (P7.10), scheduled draws and later funding
months (Phase 8), debt PIK and non-closing fees, refinancing and
recapitalization, partnership and investor returns (P7.9), further shortfall
resolutions, and any second IRR cadence.

## 14. Closeout status

Every approved P7.8A capability this gate exists to reach is now reachable from
the product, and the automated proof is in the tree:

- **component tests** for the editor, the result surface, the Risk view, the
  Position matrix and a Strategy's own structure -- **complete**;
- the **B1-B10 mutation proofs** (`tests/test_p7_8b_mutation_proofs.py`) --
  **complete**;
- the **browser QA at 1440 / 1280 / 390 and the screenshot package** --
  **complete**: the mixed-mode Investment (Quick + Detailed + Lease-Level
  Units), a Strategy inheriting / replacing / explicitly emptying the
  structure, the Project matrix left unchanged, the POSITION matrix over
  3 Strategies x 3 Scenarios including the not-applicable and unresolved cell
  states, the Common Equity perspective, the Unit-removal refusal, draft
  survival across a Unit save, and the 1280 and 390 passes.

**Visual acceptance remains human-owned.** No automated run in this gate is a
visual approval, and this document never claims one. Browser QA being complete
is evidence that the product behaves as specified -- not that a human has
accepted how it looks.

## 15. Evidence

The Session B gate report records the suite results. The oracles are
`tests/test_p7_8b_capital_structure_persistence.py`,
`tests/test_p7_8b_structured_fingerprints.py`,
`tests/test_p7_8b_structured_variants.py`,
`tests/test_p7_8b_position_decision_matrix.py`,
`tests/test_p7_8b_capital_structure_api.py` and the ledger and invariants in
`tests/test_p7_8b_product_integration_architecture.py`; the compatibility
oracles of P7.2, P7.4, P7.6, P7.7 and P7.8 were re-pinned to schema v11 and pass
unchanged in every response they compare.
