# Anchor

Anchor is a local, single-user workbench for underwriting commercial real estate
acquisitions. A deterministic Python engine does every financial calculation;
a React web app is where the analyst enters assumptions, reviews results and
compares decisions. An optional AI Analyst writes commentary about results the
engine has already produced. It never calculates them.

## What it does

### Three operating modes

Every deal is underwritten in one of three modes. All three feed the same
downstream engine, so debt, exit, cash flows and returns are computed one way.

- **Quick Underwrite:** current NOI, occupancy and NOI growth, plus
  acquisition, debt and exit terms.
- **Detailed Underwrite:** a property-level operating build: gross potential
  rent, other income, vacancy and credit loss, five expense lines, a
  management fee, and separate revenue and expense growth.
- **Lease-Level Underwrite:** a suite-and-lease rent roll with monthly
  rollover, renewal probability, downtime, free rent, recoveries (NNN, gross,
  modified gross, expense stops), TI / LC and initial vacancy treatment.

Each deal reports Levered and Unlevered IRR, equity multiple, DSCR, debt
yield, cash-on-cash, Sources & Uses, annual cash flows and an operating
statement. When the engine does not report an IRR (for example, cash flows
that change sign more than once), Anchor says why rather than showing a number.

### Business Plan

Each deal can carry a Business Plan: project capital (renovations, lease-up
costs and similar items, timed by month or year) and owner-level expenses.
The plan flows through the same engine into owner cash flows and returns.

### Risk and decisions

- **Sensitivity:** one-way and two-way tables for returns and debt metrics.
- **Break-even:** the maximum purchase price, exit cap rate or interest rate
  that still meets a chosen hurdle (Levered IRR, equity multiple or Year 1
  DSCR), plus other break-even questions in Quick and Detailed.
- **Scenarios:** named views of *what may happen*, such as a downside or an
  upside. Each overrides selected assumptions (set, add, scale or cap).
- **Strategies:** named *choices the analyst makes*: acquisition price,
  financing, Business Plan, operating outcome, hold period and capital
  structure. Each domain either inherits the base underwriting or replaces
  it whole.
- **Decision Matrix:** every Strategy under every Scenario, each cell a
  complete deterministic analysis, with the change from Base, the worst case
  and the range. It runs when its view opens (and again on Refresh), and
  explains each invalid variant once, in the validators' own words. It does not rank strategies or assign probabilities.

### Investments and consolidation

Several deals can be grouped into a visible **Investment**: for example the
phases of one project, or a portfolio acquired together. Anchor checks that
unit price allocations reconcile to the transaction price, adds
Investment-level transaction costs and Business Plan items, and consolidates
the units into one set of project cash flows and returns. Scenarios,
Strategies and the Decision Matrix work at the Investment level too.

### Capital Structure

A deal or Investment can be underwritten with an explicit capital structure:
senior debt, mezzanine debt and preferred equity above common equity, each
with its own terms and priority. Anchor reports what each position funds and
earns (IRR, multiple, attachment and detachment points, coverage) and any
funding requirement the structure creates. The Decision Matrix can compare
one position across all Strategies and Scenarios.

### Intake

- **Manual entry** in the web forms.
- **Excel workbooks** for Quick and Detailed. Formulas are never evaluated.
- **Offering memoranda (PDF)** for Quick and Detailed. Text and tables are
  extracted, candidate values are proposed with citations, and each value is
  checked against its cited source.

Imported values are only *proposals*. The analyst approves, edits or rejects
each one before it reaches the form, and nothing runs until the analyst
analyzes the deal.

### Persistence

Deals, Business Plans, Scenarios, Strategies, Investments and Capital
Structures are saved to a local SQLite database. The latest analysis, AI
report and sensitivity results are stored with a fingerprint of the
assumptions that produced them. If the assumptions change, those results are
marked out of date rather than shown as current. Opening a saved deal
re-runs its analysis automatically.

## The AI boundary

The AI Analyst (OpenAI) receives results the engine has already computed, in
a formatted, allow-listed context. It returns prose only: an executive
summary, strengths, risks, return drivers, downside discussion, questions to
investigate and a short deal story. Its output schema has no numeric fields.

AI is never the authority for IRR, equity multiple, debt service, DSCR, loan
balances, exit value, NOI or any cash flow. Those belong to the deterministic
engine, and architecture tests enforce that boundary. Document intake uses AI
only to *propose* values, which a person must approve.

## Getting started

Requirements: Python 3.14+ and Node.js (developed on Node 24).

```powershell
# Backend
python -m venv .venv
.venv\Scripts\pip install -e .[dev]

# Frontend
cd web
npm install
```

Optional settings go in a repo-root `.env` (see `.env.example`):

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Needed only for the AI Analyst and OM intake |
| `ANCHOR_AI_MODEL` | Model for the AI Analyst (default `gpt-5.6-terra`) |
| `AZURE_DOCUMENTINTELLIGENCE_ENDPOINT`, `AZURE_DOCUMENTINTELLIGENCE_KEY` | Needed only for OM intake |
| `ANCHOR_DB_PATH` | Database file (default `data/anchor.db`) |

Without any keys, Anchor still underwrites, saves and compares deals; only the
AI Analyst and OM intake are unavailable.

## Running

```powershell
# Backend API on http://127.0.0.1:8000
.venv\Scripts\python -m uvicorn anchor.api:app

# Web app on http://localhost:5173
cd web
npm run dev
```

`Launch Anchor.bat` starts both and opens the browser.
`Launch Anchor Demo.bat` does the same against `data\demo.db`.

A command-line report for a Quick workbook is also available:

```powershell
.venv\Scripts\python -m anchor examples\anchor_input.xlsx
```

## Testing

```powershell
# Backend: engine, API, persistence and architecture guards
.venv\Scripts\python -m pytest

# Frontend
cd web
npm test            # vitest
npx tsc -b          # type check
npm run lint        # oxlint
npm run build       # production build
```

The backend suite includes golden cases reconciled by hand and against earlier
versions of the engine, plus architecture tests that keep the dependency
direction and the AI boundary in place. Development follows the risk-tiered
process in `docs/development/ANCHOR_DEVELOPMENT_PROTOCOL.md`.

## Repository layout

```
src/anchor/
  engine/              deterministic NOI, debt, cash flow and return calculations
  leasing/             Lease-Level rent roll, rollover, recoveries, TI / LC
  business_plan/       project capital and owner expense plans
  analysis/            sensitivity, break-even, Scenario and Strategy resolution
  investment/          multi-unit Investment contracts and validation
  consolidation/       unit results -> consolidated Investment results
  capital_structure/   capital positions and position-level returns
  decision/            Decision Matrix comparisons
  deals/               SQLite persistence, fingerprints, variant services
  ingestion/           offering memorandum intake with citation checks
  ai/                  AI Analyst context, prompts and provider
  api.py               FastAPI application
web/src/               React app (workspaces, editors, results, matrices)
tests/                 backend tests
docs/                  specifications, conventions and architecture records
examples/              sample input workbooks
```
