# Anchor Agent Instructions

## Project

Anchor is a local commercial real estate acquisition underwriting application:
a deterministic Python engine behind a FastAPI API, with a React web app and
SQLite storage.

The project must remain financially deterministic, testable, auditable, and modular.

## Current Authorities

- `docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md` is the
  architecture authority for Phase 7 (Scenarios, Strategies, the Decision
  Matrix, Investments, consolidation, Capital Structure and later P7 gates),
  together with the P7 gate records in `docs/architecture/`.
- `docs/development/ANCHOR_DEVELOPMENT_PROTOCOL.md` governs how every gate is
  run: risk tiers, verification, session and Git discipline, stop conditions.

Where this file and those documents differ, those documents govern.

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

Do not expand the engine's inputs or financial contracts without explicit
approval; each engine gate records its own engine-scope approval.

Anti-overfitting (permanent): historical cases are acceptance archetypes only.
No production identifier, module, enum member, table, route, component or copy
string may name a case, a competition, a sponsor or a specific transaction.
Ask "can the generic architecture represent this case?", never "how do we code
this case?" (`tests/test_p7_0_decision_architecture.py` enforces this.)

Do not modify unrelated files.

Do not introduce dependencies without explaining why they are required.

## Documented Solutions

`docs/solutions/` — documented engineering lessons from past phases (architecture patterns, conventions, workflow issues), organized by category with YAML frontmatter (`module`, `tags`, `problem_type`). Relevant when implementing or debugging in areas those phases already covered.

`CONCEPTS.md` — shared domain vocabulary (entities, named processes, status concepts). Relevant when orienting to the codebase or discussing domain concepts.

## Testing

Every financial calculation must have automated tests.

Every bug fix should receive a regression test when practical.

For Project Anchor work, verification scope is governed by `docs/development/ANCHOR_DEVELOPMENT_PROTOCOL.md`. Follow its risk-tier policy and run full suites when that protocol requires them rather than as a universal completion requirement.

Before declaring implementation complete:
1. Assign the gate a risk tier under the protocol.
2. Run relevant targeted tests.
3. Complete the verification that risk tier requires, including full suites where the protocol calls for them. A full suite is not required for every Tier 3 or Tier 4 change.
4. Report the test results.
5. Review git diff for unintended changes.

## Git

`main` tracks the latest approved state going forward: a phase or feature branch merges into `main` once it is complete and approved, rather than accumulating unmerged on its own branch chain.

Development occurs on feature branches.

Do not commit directly to main unless explicitly instructed.

Do not merge branches unless explicitly instructed.

Do not rewrite existing Git history.
