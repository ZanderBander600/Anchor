# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Relationships

AcquisitionInputs flows into the Deterministic Engine, which produces AcquisitionResults. Every other analysis layer (sensitivity, break-even, the AI Analyst) reads AcquisitionResults but never derives its own version of one; the AI Analyst is the last stage and only interprets, subject to its Grounding Rules.

## AcquisitionInputs

The fixed set of acquisition inputs an analyst supplies before any analysis runs: purchase price, current NOI, occupancy, NOI growth, hold period, exit cap rate, LTV, interest rate, and amortization. This is the entire core-engine input surface — no additional field may be added to it without explicit approval.

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
