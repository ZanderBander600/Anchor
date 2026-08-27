---
title: Deterministic Financial Engine as the Sole Calculation Authority
date: 2026-08-27
category: architecture-patterns
module: engine, analysis, ai
problem_type: architecture_pattern
component: financial_engine
severity: high
applies_when:
  - "Adding any feature that touches acquisition math (new metric, new scenario type, new AI-facing summary)"
  - "Wiring an LLM or other probabilistic component to financial output"
  - "Porting Mini-Anchor's engine/analysis/ai layers into a successor project (Anchor)"
tags: [deterministic-engine, ai-grounding, sensitivity-analysis, break-even, financial-calculations]
---

# Deterministic Financial Engine as the Sole Calculation Authority

## Context

Mini-Anchor's core design constraint, stated in `AGENTS.md` and frozen in `docs/financial_conventions.md`, is that every acquisition number (IRR, equity multiple, debt service, DSCR, loan balance, exit value, NOI forecast, acquisition cash flows) must come from one deterministic Python engine, never from an LLM. Phases 7-9 added sensitivity analysis, break-even analysis, and an AI "analyst" layer on top of that engine without ever weakening this boundary. The pattern that resulted — one authoritative entry point, everything else re-derives from it rather than approximating it — is the single most load-bearing architectural decision in the codebase and is worth carrying forward unchanged into Anchor.

## Guidance

**One calculation entry point, called again rather than reimplemented.** `mini_anchor.engine.analyze_acquisition()` (`src/mini_anchor/engine/acquisition.py`) is the only function that computes `AcquisitionResults`. Every higher layer that needs a "what if" answer — sensitivity (`src/mini_anchor/analysis/sensitivity.py`), break-even search (`src/mini_anchor/analysis/break_even.py`), the AI analyst (`src/mini_anchor/ai/analyst.py`) — builds a new validated `AcquisitionInputs` (via the shared `validate_acquisition_inputs`, never a duplicated domain check) and calls `analyze_acquisition()` again, then only reads a field off the result. Nothing above the engine reimplements a formula, rearranges one algebraically, or approximates one numerically. `break_even.py`'s docstring states this explicitly: "This module never reproduces a financial formula and never algebraically rearranges one... The search itself is a plain bounded bisection over the assumption value." The break-even solver bisects on the *input* (e.g. purchase price) and re-evaluates the whole engine at each candidate — it never inverts the IRR/DSCR formulas directly.

**AI is wired downstream of the engine, not beside it.** `src/mini_anchor/ai/analyst.py`'s `build_analysis_context()` calls `analyze_acquisition`, `build_standard_presets`, and `build_standard_break_even_analysis` exactly once each and reads their results into `AnalysisContext` — "This module reproduces no financial formula, sensitivity scenario, or break-even search of its own." The AI provider (`src/mini_anchor/ai/provider.py`, the only module that imports the `openai` SDK) receives only that already-computed, already-formatted context; it is structurally incapable of seeing raw inputs and computing its own numbers, because the deterministic values are all it is ever given.

**The AI's system prompt encodes the grounding rule explicitly and specifically** (`src/mini_anchor/ai/prompts.py`, `SYSTEM_PROMPT`). The rules go well past "don't calculate IRR" — they were sharpened by specific failure modes worth reusing verbatim in Anchor:
- Never independently calculate or estimate any of: IRR, equity multiple, DSCR, debt service, loan balance, exit value, NOI forecast, acquisition cash flows, sensitivities, or break-even values.
- **Never compute even a simple derived delta between two supplied numbers** — no spread, basis-point gap, or difference, "even simple subtraction." If a relationship isn't already a field in the supplied data, describe it only qualitatively ("the exit cap rate is lower than the going-in cap rate," never "25 bps tighter"). This rule exists because subtraction *looks* harmless but is still an uncontrolled calculation.
- **Never independently judge a hurdle comparison** (is this DSCR above or below target?) by reading a formatted number and reasoning about it. Every hurdle-relevant metric is pre-labeled with its relationship to its hurdle (e.g. `"1.22x -- above 1.20x target"`) by the deterministic presentation layer (`src/mini_anchor/ai/presentation.py`), and the model is instructed to cite that label, never recompute the comparison itself.
- A break-even `"no_solution_in_range"` status must never be restated as "impossible" — it only means no qualifying value existed inside the documented search bounds.
- The model must not invent unsupplied property facts (address, tenancy, market comps) and must say explicitly when evidence is insufficient rather than filling the gap.

**Occupancy is a recurring landmine, not just a field.** Occupancy is informational-only under the frozen POC convention — `src/mini_anchor/engine/noi.py` never reads it, and it must never be multiplied into current or forecast NOI. This rule shows up independently in `docs/financial_conventions.md`, in `src/mini_anchor/analysis/sensitivity.py`'s comment on why occupancy is excluded from `SUPPORTED_ASSUMPTIONS`, and in the AI system prompt (rule 6). Any successor engine that reintroduces occupancy as a NOI driver must update all three places, not just the formula.

**Financial conventions are frozen in a spec document, not just in code.** `docs/financial_conventions.md` is the Phase 0 specification: exact formulas, input domains, rounding rules ("rounding is presentation-only," full precision is retained through every intermediate calculation), IRR's exact bisection algorithm and validity rules, and an explicit "Frozen Decisions" section. Code implements this spec; it does not silently redefine it. This is what let Phases 7-9 build sensitivity/break-even/AI on top of the engine with confidence that "re-run the engine" always means the same thing.

## Why This Matters

An LLM asked to interpret financial results will, by default, happily do arithmetic on them — compute a spread, round differently, or "helpfully" restate a comparison in its own words. Each of those is a silent second source of truth that can drift from the deterministic engine, and once it does, nothing in the system can tell you which number is right. The specific, enumerated prohibitions in the system prompt (not just "don't calculate the big numbers," but "don't even subtract two of them") are evidence that a general instruction wasn't sufficient and had to be hardened against particular failure modes. Anchor should inherit the prompt's granularity, not just its spirit.

The "always re-call the authoritative entry point, never shortcut" pattern is what makes sensitivity and break-even analysis trustworthy: a two-way sensitivity grid and a five-question break-even search are both, structurally, nothing more than the same `analyze_acquisition()` called dozens of times with different validated inputs. There is no separate "fast path" formula that could drift from the engine's real behavior.

## When to Apply

- Any new feature that touches acquisition math, in Mini-Anchor or in Anchor.
- Any change that adds a new consumer of engine output (a new UI panel, a new export format, a new AI-facing summary).
- Any prompt-engineering work for an LLM that is shown financial data — assume the model will try to do arithmetic unless explicitly and specifically forbidden from each category of arithmetic it might attempt.
- Migrating this codebase: preserve `analyze_acquisition()` as the single entry point, preserve the "re-call, don't rederive" discipline in any new analysis module, and carry the system-prompt grounding rules forward (updating field names as needed) rather than re-deriving them from scratch under time pressure.

## Examples

Sensitivity and break-even both follow the same call shape:

```python
# analysis/break_even.py -- _evaluate_candidate
scenario_inputs = _build_scenario_inputs(inputs, {assumption: candidate_value})
scenario_results = analyze_acquisition(scenario_inputs)
return _extract_metric(scenario_results, metric)
```

No formula for IRR or DSCR appears in this file — only a call into the frozen engine and a field read.

The AI system prompt's grounding rule for derived deltas, verbatim:

> "Do not calculate a spread, difference, delta, basis-point gap, or any other derived ratio or metric between two or more supplied numbers, even simple subtraction... describe it only qualitatively, never with a derived numeric magnitude you computed yourself."

## Related

- `docs/financial_conventions.md` — the frozen Phase 0 financial specification the engine implements.
- `docs/phase_2_deterministic_engine.md` — engine implementation notes.
- [om-ingestion-provenance-and-analyst-approval-gate](om-ingestion-provenance-and-analyst-approval-gate.md) — the same "AI proposes, deterministic/human process verifies" shape applied to document extraction instead of financial calculation.
