# Concepts

Shared domain vocabulary for this project — entities, named processes, and
status concepts with project-specific meaning. Glossary only, not a financial
specification, architecture authority, or live status record. See
`docs/CURRENT_STATE.md` for current project status.

## Relationships

Operating-mode inputs flow into the Deterministic Engine, which produces
AcquisitionResults. Scenarios and Strategies resolve to ordinary approved input
contracts before that run. Consolidation consumes completed Unit results;
Capital Structure consumes completed Project cash; future Partnership economics
will consume Common Equity cash. The Decision layer compares results, and the
AI Analyst only interprets verified outputs subject to its Grounding Rules.

## AcquisitionInputs

The fixed nine-field Quick Underwrite input contract: purchase price, current
NOI, occupancy, NOI growth, hold period, exit cap rate, LTV, interest rate, and
amortization. No field may be added to that core contract without explicit
approval. Detailed and Lease-Level operating inputs, Business Plans, and P7
decision contracts are separately approved layers; they do not silently widen
this dataclass.

## AcquisitionResults

The complete deterministic output of running one AcquisitionInputs through the Deterministic Engine: the capital stack, the NOI and cash-flow forecasts, and every return metric (IRR, equity multiple, DSCR). Every downstream consumer only ever reads fields off an AcquisitionResults it obtained by re-running the engine — it never derives its own.

## Deterministic Engine

The one authoritative calculation path that produces AcquisitionResults from AcquisitionInputs. Financially deterministic: given the same inputs it always returns the same outputs, computed by a fixed, testable set of formulas rather than estimated or approximated. Every other layer in the system is required to call the Deterministic Engine again rather than reimplement or approximate any of its calculations.

## AI Analyst

The layer that interprets an already-computed AcquisitionResults (and its sensitivity/break-even results) into prose investment commentary. Never permitted to calculate, estimate, or derive a financial value of its own — including a simple delta between two supplied numbers — and must cite the Deterministic Engine's output as authoritative rather than reformat or recompute it.

## Grounding Rule

A specific, enumerated restriction placed on the AI Analyst's behavior (for example, "never compute a derived delta between two supplied numbers" or "never independently judge a hurdle comparison") that closes one concrete way the AI Analyst could produce an unverified financial claim. Distinguished from a general instruction by being narrow enough to catch one specific failure mode rather than relying on the model to infer it from a broad principle.

## Evidence Status

The classification an OM ingestion candidate value carries about how well-supported it is by the source document: `stated` (explicit), `interpreted` (the model inferred it), `conflicting` (two or more verified candidates disagree), `unverifiable` (citation failed deterministic verification), or `missing` (no candidate at all). Exactly these five states — no other value is valid.

## Provenance

The verified evidence backing one extraction candidate: the page number, the anchor id it cites, and the literal snippet text at that anchor. A candidate loses its `stated`/`interpreted` status and is downgraded to `unverifiable` when its citation cannot be resolved or its snippet does not support the value — Provenance is never trusted from the model's own claim.

## Document Anchor

One directly addressable unit of a source document's extracted layout — a paragraph or a single table cell — identified by a stable id. An extraction candidate's citation must resolve to a real Document Anchor in the document actually processed, or it fails verification.

## Analyst Approval Gate

The review step between document-derived candidate values and the Deterministic Engine: an analyst must explicitly approve, edit, or reject each proposed value before it can reach the engine's inputs. No document-derived value reaches an analysis run automatically, regardless of its Evidence Status.

## Deal / Unit

The persisted underwriting object for one property-level analysis. In a visible
Investment it is called a Unit. A standalone Deal can be wrapped in a hidden
one-unit Investment when the analyst opts into P7 features.

## Investment

The root for one or more Units, Investment-level Business Plan economics,
transaction costs, Scenarios, Strategies, consolidation, and Investment-scoped
Capital Structure. A simple standalone Deal does not expose meaningless
Investment chrome until the analyst opts in.

## Scenario

A typed set of assumption overrides representing a view of the world, such as
Base, Downside, or Upside. A Scenario resolves before analysis and never mutates
the underlying base inputs.

## Strategy

A typed set of domain overlays representing what the investor chooses to do.
Strategies resolve before analysis. Unit-root domains and Investment-root
domains remain explicit; Capital Structure is an Investment-root domain.

## Analysis Variant

One deterministic Strategy x Scenario cell after every applicable override and
overlay has resolved to ordinary input contracts. The Decision Matrix compares
variants but does not create a second financial truth.

## Capital Structure

The downstream layer that determines sources of capital, contractual claims,
priority, repayment, and position economics after Property and Business Plan
economics determine available cash. It never changes NOI, Project Capital,
Owner Expenses, or exit value.

## Capital Position

One addressable instrument in a Capital Structure: Senior Debt, Mezzanine Debt,
Preferred Equity, or the Common Equity marker. Its stable position id identifies
the same economic instrument across Base and Strategy-specific structures.

## Funding Requirement

A deterministic result stating that cash available after senior claims is
insufficient for a contractual payment. It records the amount, period, scope,
and unpaid claims. It is never silently cured; resolution must be explicit.

## Project Returns

Returns on the property or Investment economics produced upstream of structured
capital allocation. They are distinct from Position Returns and must not be
overwritten by them.

## Position Returns

Provider-side IRR, MOIC, profit, and related structural metrics for one Capital
Position. These are distinct from Project Returns and future Investor Returns.

## Partnership / Investor Returns

The P7.9 layer that will allocate Common Equity cash among partners and report
investor economics. It is ratified architecture but is not implemented at the
current P7.8 baseline.
