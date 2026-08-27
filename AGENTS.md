# Mini-Anchor Agent Instructions

## Project

Mini-Anchor is a proof-of-concept real estate acquisition analysis application.

The project must remain financially deterministic, testable, auditable, and modular.

## Core Architecture Rule

AI is permitted to:
- extract information
- normalize information
- classify information
- summarize information
- interpret verified financial results

AI must not be the authoritative calculator for:
- IRR
- equity multiple
- debt service
- DSCR
- loan balance
- exit value
- NOI forecast
- acquisition cash flows

These calculations belong in the deterministic Python engine.

## Development Discipline

Work only within the explicit scope of the current task.

Do not implement future phases unless explicitly instructed.

Do not silently change financial conventions.

Do not modify unrelated files.

Do not introduce dependencies without explaining why they are required.

## Documented Solutions

`docs/solutions/` — documented engineering lessons from past phases (architecture patterns, conventions, workflow issues), organized by category with YAML frontmatter (`module`, `tags`, `problem_type`). Relevant when implementing or debugging in areas those phases already covered.

`CONCEPTS.md` — shared domain vocabulary (entities, named processes, status concepts). Relevant when orienting to the codebase or discussing domain concepts.

## Testing

Every financial calculation must have automated tests.

Every bug fix should receive a regression test when practical.

Before declaring implementation complete:
1. Run relevant targeted tests.
2. Run the full test suite.
3. Report the test results.
4. Review git diff for unintended changes.

## Git

main represents the latest stable approved version.

Development occurs on feature branches.

Do not commit directly to main unless explicitly instructed.

Do not merge branches unless explicitly instructed.

Do not rewrite existing Git history.

## Current POC Scope

The core engine uses nine acquisition inputs:

1. Purchase Price
2. Current NOI
3. Occupancy
4. NOI Growth
5. Hold Period
6. Exit Cap Rate
7. LTV
8. Interest Rate
9. Amortization

Do not expand the core engine beyond these inputs without explicit approval.

## Development Sequence

Phase 0: Financial specification
Phase 1: Excel ingestion
Phase 2: Deterministic engine
Phase 3: Financial QA
Phase 4: Results contract and CLI
Phase 5: FastAPI
Phase 6: UI/UX
Phase 7: End-to-end web POC
Phase 8: Azure ingestion
Phase 9: OpenAI investment analysis
Phase 10: Final hardening