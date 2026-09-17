# Anchor

Anchor is a deterministic real-estate acquisition and investment decision
application. It supports Quick, Detailed, and Lease-Level underwriting while
keeping authoritative financial calculations in a testable Python engine.

## Current capabilities

- Excel and Offering Memorandum ingestion with analyst approval
- Deterministic property, debt, exit, and return calculations
- Quick, Detailed, and Lease-Level operating models
- Business Plans and owner capital economics
- Scenarios, Strategies, and comparison matrices
- Multi-unit Investments and consolidation
- Structured capital with debt, preferred equity, Common Equity residuals,
  position returns, and position-level decision comparison
- AI interpretation grounded only in verified deterministic results

## Project status

P7.8 is the latest accepted milestone. No development gate is currently
active. P7.9 Partnership Waterfalls + Investor Returns is the next ratified
architectural gate and has not started.

Read these files before development:

1. `AGENTS.md`
2. `CLAUDE.md`
3. `docs/CURRENT_STATE.md`
4. `docs/development/ANCHOR_DEVELOPMENT_PROTOCOL.md`

The dated documents under `docs/plans/` and the predecessor examples under
`docs/solutions/` are historical context, not current-status authorities.

## Core rule

AI may extract, normalize, classify, summarize, and interpret information. AI
does not authoritatively calculate IRR, equity multiple, debt service, DSCR,
loan balance, exit value, NOI forecasts, or acquisition cash flows.

## Run locally

Use `Launch Anchor.bat` on Windows, or run the FastAPI backend and Vite frontend
with the project dependencies described in `pyproject.toml` and
`web/package.json`.
