---
title: OM Ingestion — Provenance Verification and the Analyst Approval Gate
date: 2026-08-27
category: architecture-patterns
module: ingestion, web
problem_type: architecture_pattern
component: ingestion
severity: high
applies_when:
  - "Adding a new document type, extraction provider, or classification model to the ingestion pipeline"
  - "Adding any new AI-proposed value that could reach the financial engine"
  - "Deciding whether a document-derived value should ever bypass analyst review"
  - "Porting the ingestion pipeline into a successor project (Anchor)"
tags: [om-ingestion, provenance, analyst-approval, evidence-status, provider-isolation, azure-document-intelligence]
related_components: [financial_engine, ai_layer]
---

# OM Ingestion — Provenance Verification and the Analyst Approval Gate

## Context

Phase 10A added Offering Memorandum (OM) PDF ingestion: Azure Document Intelligence extracts document structure, then GPT classifies that structure into candidate values for the same nine `AcquisitionInputs` fields the analyst would otherwise type by hand, plus five read-only deal-context fields. This is the highest-risk AI surface in Mini-Anchor, because unlike the AI Analyst (which only produces prose commentary), OM ingestion proposes values that could, if trusted blindly, become the literal numbers the deterministic engine runs on. The pipeline was built with three independent safeguards — deterministic provenance verification, an explicit five-state evidence model, and a mandatory analyst approval gate — and all three are worth carrying forward exactly as designed, not simplified, when this is ported to Anchor.

## Guidance

**1. A citation is verified deterministically against the actual extracted document — never trusted because the model asserted it, and never re-checked with a second model call.**

`GPTClassifierProvider` receives only Azure DI's flattened `StructuredDocument` (paragraphs and table cells, each with a stable anchor id like `paragraph:12` or `table:2:cell:3:1`) — never the raw PDF (`src/mini_anchor/ingestion/orchestrator.py:1-11`). Every candidate GPT proposes must cite one of those anchor ids. Verification is two checks, both done in plain Python against the same `StructuredDocument` object that was actually sent, not a fresh model call: (a) the cited anchor id must exist in the document, and (b) the anchor's literal text must numerically or textually support the proposed value (`src/mini_anchor/ingestion/classifier_provider.py:9-21`). A citation that fails either check is downgraded to `unverifiable` before it's ever returned (`src/mini_anchor/ingestion/classifier_provider.py:244-258`).

The numeric-match check is itself carefully scoped: percentage-vs-fraction equivalence (5.5% verifying a proposed 0.055) is applied only to the five fields that are actually percent-scale in the OM's narrative style (`occupancy`, `noi_growth`, `exit_cap_rate`, `ltv`, `interest_rate`) — an absolute-magnitude field like `purchase_price` or `hold_period` never gets that equivalence, so a cited "30" can never verify a proposed "3000" and a cited "2026" can never verify a proposed "20.26" (`src/mini_anchor/ingestion/classifier_provider.py:56-68`). This distinction exists because a generic "numbers roughly match" check would have created a specific, silent failure mode: a proposed value passing verification against unrelated document text purely by coincidence of scale.

**2. Evidence status is a closed five-state model, and each state has one specific meaning worth preserving exactly.**

`EvidenceStatus` is `stated | interpreted | conflicting | unverifiable | missing` (`src/mini_anchor/ingestion/contracts.py:51-58`). The design decisions behind this shape matter more than the enum itself:

- **`missing` is a legitimate first-class outcome, not an error.** A missing field is represented by zero candidates, never a placeholder or a forced guess (`src/mini_anchor/ingestion/contracts.py:113-117`, KD2 in `docs/plans/2026-08-26-1343-feat-om-ingestion-foundation-plan.md:82`). This is a deliberate divergence from the earlier Phase 9A AI Analyst's strict-required JSON schema, where every field is always present — OM extraction had to relax that because an OM legitimately doesn't always state every input.
- **`conflicting` triggers automatically, not by model self-report.** When two or more *verified* candidates for one field propose genuinely differing values, every verified candidate for that field is relabeled `conflicting` — this is computed deterministically after verification, by comparing normalized values, never by asking the model whether it's conflicted (`src/mini_anchor/ingestion/classifier_provider.py:261-299`). Two representations of the *same* fact (a table cell and a narrative sentence stating the same number, or 95% vs. 0.95) are never treated as conflicting — only a genuinely differing value is (e.g. 95% in one place vs. 94% in another).
- **A candidate that resolves to the same fact from more than one place in the document is deduplicated, not shown as repeated evidence.** `_deduplicate_candidates` collapses a candidate only when it matches an existing one on normalized value, evidence status, *and* redundant source evidence (the same anchor, or anchors whose text is the same underlying statement) — never a genuine conflict, which always survives as multiple candidates (`src/mini_anchor/ingestion/classifier_provider.py:316-353`).
- **`unverifiable` is not the same as `missing`.** `unverifiable` means the model proposed something and cited *some* evidence, but that evidence didn't hold up (wrong anchor, or text that doesn't support the value) — it is shown to the analyst with whatever citation attempt exists, never silently dropped to `missing` (`src/mini_anchor/ingestion/contracts.py:98-106`).

**3. No document-derived value reaches the financial engine without an explicit, per-field analyst action.**

`OmReviewPanel` is a review surface, not a second way to originate an assumption: a truly `missing` field renders read-only with no value-entry, edit, or approval control at all — the analyst must supply it (if at all) through the existing `AssumptionsForm`, exactly as before ingestion existed (`web/src/components/OmReviewPanel.tsx:112-127`, comment cites R7/R11). For every other field, the analyst must explicitly Approve a specific candidate, Edit it to a different value, or Reject it — nothing is pre-approved by default (`web/src/components/OmReviewPanel.tsx:30-43`, `225-257`). "Use approved values" only ever hands the set of explicitly-approved values up to the parent component; it never calls the analysis endpoint itself (`web/src/components/OmReviewPanel.tsx:203-207`). The parent (`App.tsx`) takes those approved values and merges them into the *same* form state (`values`) that manual typing would set, then resets any downstream analysis result (`web/src/App.tsx:104-111`). This means an OM-derived value and a hand-typed value are, from the moment of approval onward, indistinguishable to the rest of the system — the approval gate is the entire mechanism, there is no separate "trusted" code path for document-derived data. The ingestion plan states this as an explicit key technical decision: "Approved candidate values pre-fill the existing `AssumptionsForm`; the review screen never calls `/analyze` directly... reuses existing validation UX instead of duplicating it" (KTD5, `docs/plans/2026-08-26-1343-feat-om-ingestion-foundation-plan.md:192`).

**4. The provider-isolation pattern from the AI Analyst layer was deliberately reused, not reinvented.**

`src/mini_anchor/ingestion/` mirrors `src/mini_anchor/ai/`'s shape exactly: `contracts.py` (frozen dataclasses), one provider module per external call with its SDK imported lazily inside that module only, a `prompts.py`, and an orchestrator that calls each provider exactly once and accepts an injectable provider for tests (KTD1, `docs/plans/2026-08-26-1343-feat-om-ingestion-foundation-plan.md:188`). `di_provider.py` and `classifier_provider.py` are, alongside `src/mini_anchor/ai/provider.py`, the only three modules in Mini-Anchor that import an external SDK (`src/mini_anchor/ingestion/classifier_provider.py:1-8`). This is enforced the same AST-guardrail way as the AI layer (`tests/test_ingestion_architecture.py`, mirroring `tests/test_ai_architecture.py`).

**5. Credentials for every external provider are backend-only; the frontend never sees them.**

Azure DI and OpenAI credentials are read exclusively from backend process environment variables — `AZURE_DOCUMENTINTELLIGENCE_ENDPOINT`, `AZURE_DOCUMENTINTELLIGENCE_KEY` (`src/mini_anchor/ingestion/di_provider.py:27-28`) and `OPENAI_API_KEY` (`src/mini_anchor/ingestion/classifier_provider.py:48`, `src/mini_anchor/ai/provider.py:23` — also used by the AI Analyst layer) — resolved lazily only when a real provider call is made, never read or referenced anywhere under `web/src/`. The raw PDF itself is never persisted past the extraction call: `pdf_bytes` exists only as a local argument for the duration of `extract_om()` and is never stored on any returned object or module-level state (R13, `src/mini_anchor/ingestion/orchestrator.py:8-10`).

## Why This Matters

The single most dangerous outcome for an ingestion pipeline feeding a financial underwriting tool is a document-derived number reaching the engine that nobody actually looked at — either because it was wrong (a misread table cell) or because it was fabricated (a model hallucinating a plausible-looking value with no real source). This design closes both failure modes independently: provenance verification means a fabricated value has no real citation to hide behind (it gets caught as `unverifiable` before the analyst even sees it as if-verified), and the mandatory approval gate means even a *correctly* verified value still requires a human decision before it can affect underwriting — verification proves the citation is real, not that the analyst wants to use it. Losing either safeguard independently would still leave the other standing; a design that merges them (e.g., auto-approving anything that verifies) would remove the analyst from the loop entirely and should be treated as a regression, not a simplification, if proposed during the Anchor migration.

## When to Apply

- Adding a new ingestion source (a different document type, a different extraction provider) — give it its own adapter module under the ingestion package's existing shape, and keep the deterministic-verification-then-approval sequence rather than trusting a new provider's output more readily than Azure DI's.
- Adding a new AI-facing feature anywhere in the system that could produce a value an analyst might act on — ask explicitly whether it needs its own `stated/interpreted/conflicting/unverifiable/missing`-equivalent evidence model, or whether it can reuse this one.
- Any proposal to auto-fill or auto-approve a field based on confidence score, high verification quality, or repeated agreement across documents — this pattern deliberately has no such shortcut, and adding one needs to be a conscious, explicit decision, not an incremental convenience.
- The Anchor migration: preserve the three-safeguard shape (deterministic provenance check, five-state evidence model, mandatory per-field analyst action before values reach the authoritative form) as one unit — it is the reason document ingestion doesn't undermine the deterministic-engine guarantee documented in [deterministic-engine-ai-grounding-boundary](deterministic-engine-ai-grounding-boundary.md).

## Examples

The percent-scale equivalence boundary — the exact set of fields where a 100x scale difference is treated as the same evidence, and the explicit statement of what must never share that leniency:

```python
# src/mini_anchor/ingestion/classifier_provider.py:66-68
_PERCENT_SCALE_FIELD_IDS = frozenset(
    {"occupancy", "noi_growth", "exit_cap_rate", "ltv", "interest_rate"}
)
```

The missing-field boundary in the review UI — read-only, no controls, by design:

```tsx
// web/src/components/OmReviewPanel.tsx:112-127
// R7/R11 boundary: a truly missing field carries no document evidence at
// all, so the review screen offers no value-entry, edit, or approval
// control for it -- this stays a document-evidence review surface, not a
// second place to originate underwriting assumptions.
if (isMissing) {
  return (
    <div className="om-field-card om-field-card-missing">
      ...
      <p className="om-field-missing">Not found in OM.</p>
    </div>
  );
}
```

## Related

- [deterministic-engine-ai-grounding-boundary](deterministic-engine-ai-grounding-boundary.md) — the same "AI proposes, deterministic/human process verifies" shape applied to financial calculation instead of document extraction; both share the provider-isolation pattern.
- `docs/plans/2026-08-26-1343-feat-om-ingestion-foundation-plan.md` — the original Key Decisions (KD1-KD7) and Key Technical Decisions (KTD1-KTD12) this doc draws its R-numbers and KD/KTD references from.
