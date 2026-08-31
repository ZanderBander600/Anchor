---
title: Testing Conventions and Architecture Guardrails
date: 2026-08-27
category: conventions
module: tests
problem_type: convention
component: testing_framework
severity: medium
applies_when:
  - "Adding a new isolated layer/package that must never import a sibling layer or an external SDK directly"
  - "Adding a new financial calculation or a new consumer of AcquisitionResults"
  - "Fixing a bug found through live/manual testing against a real external API or a real document"
  - "Running pytest on Windows in this project (or its Anchor successor)"
tags: [testing, architecture-guardrails, pytest, windows, golden-case, regression-tests]
related_components: [financial_engine, ingestion]
---

# Testing Conventions and Architecture Guardrails

## Context

Mini-Anchor's testing approach isn't just "write tests for financial code" (`AGENTS.md`'s stated rule) — three specific, reusable test *shapes* recur across every phase, and a fourth item, a Windows-specific pytest temp-directory problem, recurred as friction throughout the project without ever being fully closed out. Both are worth capturing before Anchor: the shapes because they are the actual mechanism that kept the architecture boundaries in [deterministic-engine-ai-grounding-boundary](../architecture-patterns/deterministic-engine-ai-grounding-boundary.md) and [om-ingestion-provenance-and-analyst-approval-gate](../architecture-patterns/om-ingestion-provenance-and-analyst-approval-gate.md) intact, and the Windows quirk because it should be fixed properly in Anchor rather than carried forward as a recurring nuisance.

## Guidance

**1. Architecture boundaries are enforced with AST-parsing import tests, one file per isolated layer.**

`tests/test_ai_architecture.py`, `tests/test_analysis_architecture.py`, and `tests/test_ingestion_architecture.py` each parse the AST of every source file in the layer they guard (never a runtime import, which could succeed even when a forbidden dependency exists but is merely unused on that path) and assert three things: the SDK a layer owns (`openai`, `azure`) is imported in exactly one adapter module and nowhere else in that layer; the `mini_anchor.engine` and `mini_anchor.analysis` packages never import the layer at all; and importing the frozen packages (`mini_anchor.engine`) in a fresh subprocess never pulls the SDK into `sys.modules` (`tests/test_ai_architecture.py:46-129`, `tests/test_ingestion_architecture.py:1-13`, mirrored explicitly — "Mirrors the style of `test_ai_architecture.py`"). This shape is the reusable artifact: any new isolated layer in Anchor should get the same four-part test (SDK-confined-to-one-file, forbidden-import-absent, subprocess-import-check, delegation-via-mock-wraps) on day one, not added later after a violation is found in review.

**2. A static import-graph guarantee is paired with a runtime data-flow spy test for the property that actually matters.** `test_ingestion_architecture.py`'s `test_classifier_never_receives_the_raw_pdf_bytes` (`tests/test_ingestion_architecture.py:216-235`) doesn't check imports at all — it plants a unique byte marker inside fake PDF bytes, runs the real `extract_om()` orchestration with spy providers, and asserts the marker appears nowhere in what the classifier actually received (system prompt, user prompt, or any document anchor text). An import-graph test proves a forbidden capability doesn't exist in the code; this proves the specific data the rule cares about never flows down a path that would violate it even if some future refactor made that capability possible again. The two checks are complementary, not redundant — write both when the property that matters is really about data flow, not just which modules a file imports.

**3. Delegation to the authoritative engine call is asserted with `unittest.mock.patch(..., wraps=...)`, not just tested indirectly.**

Rather than only checking that a layer's *output* looks plausible, the test wraps the real function so it still executes, and separately asserts it was called exactly once with the expected arguments (`tests/test_ai_architecture.py:137-169`). This catches a class of bug that output-only assertions miss: a layer that happens to produce the right numbers via its own reimplementation rather than by calling the authoritative engine, which would drift silently on the next engine change.

**4. Golden-case tests pin known values from the frozen spec document, at a stringent, explicitly-justified tolerance.**

`tests/test_engine_golden_case.py` takes its expected values directly from the "Golden Case" section of `docs/phase_2_deterministic_engine.md` and compares with `pytest.approx(expected, rel=0.0, abs=1e-9)` — tight enough to reject presentation-scale rounding errors, loose enough to tolerate ordinary IEEE-754 last-bit noise from the bisection-based IRR solver, with the reasoning stated inline rather than left for a future reader to guess (`tests/test_engine_golden_case.py:22-25`). A spec-derived golden case is a stronger regression anchor than a hand-picked example, because a future change that "still passes the golden case" is provably still consistent with the frozen written specification, not just internally consistent with itself.

**5. A bug found through live/manual testing gets a diagnostic regression test that narrows where a recurrence would come from — not just a test that the specific bug is fixed.**

Three concrete examples from Phase 10A ingestion, each traceable to a real symptom seen when the pipeline was smoke-tested against live Azure DI and OpenAI APIs rather than only against fakes:
- **Azure DI silently truncating a document.** `test_azure_silently_truncating_an_8_page_pdf_to_2_pages_fails_explicitly` (`tests/test_ingestion_di_provider.py:241-255`) exists because Azure DI's free (F0) tier can return a normal, warning-free response after processing only a prefix of an uploaded PDF — which, unguarded, would have read as "the later pages had no evidence" (fields silently `missing`) rather than a real extraction failure. The fix compares the source PDF's real page count (via `pypdf`) against the pages Azure DI actually returned evidence for, and fails loudly on a mismatch.
- **Magnitude-representation false conflicts.** `test_equivalent_purchase_price_in_different_magnitude_representations_is_not_conflicting` (`tests/test_ingestion_classifier_provider.py:189-199`) exists because a live OM stated the same purchase price as `$45,000,000` in one section and `$45.0 million` in another, and raw-string comparison wrongly surfaced this as a `conflicting` field (`tests/test_ingestion_classifier_provider.py:180-186`).
- **A diagnostic test that bisects future blame, not just today's bug.** `test_two_distinctly_anchored_occupancy_values_both_survive_end_to_end` (`tests/test_ingestion_classifier_provider.py:859-896`) was written after a live report of "expected occupancy conflict not surfaced." Its comment explicitly states its diagnostic purpose: if this test keeps passing but the symptom recurs live, the cause is upstream of this module — either Azure DI never produced a separate anchor for the second value, or the GPT response itself omitted the second candidate (`tests/test_ingestion_classifier_provider.py:847-856`). **This is the reusable idea:** when a live symptom could originate in more than one stage of a pipeline, write the regression test to prove which stage is *not* at fault, so a future recurrence's investigation starts already narrowed instead of starting from zero again.

None of these three bugs were caught by the mocked/fake-provider unit tests that existed before them — they surfaced only when the pipeline was smoke-tested against the real Azure DI/OpenAI APIs with a real (synthetic but realistic) OM PDF (`tests/fixtures/mini_anchor_synthetic_om_test.pdf`), per the ingestion plan's own Definition of Done: "Manual smoke check: uploading a sample OM PDF through the running app produces a review screen with at least one `stated`, one `missing`, and (with a suitable fixture OM) one `conflicting` field..." (`docs/plans/2026-08-26-1343-feat-om-ingestion-foundation-plan.md:439`). Mocked unit tests alone would not have found any of the three — each depends on how a *real* provider actually behaves (a real tier limit, real inconsistent OM phrasing, a real extraction gap), not on any assumption the mock's author could have anticipated in advance.

**6. A fixed, ordered completion ritual is required before declaring implementation done** (`AGENTS.md` "Testing"): run the relevant targeted tests, then the full suite, report the exact results, then review `git diff` for unintended changes. The ingestion plan's own Definition of Done repeats this verbatim ("`git diff` reviewed for unintended changes, per `AGENTS.md`") rather than restating a different process per phase — the ritual itself, not just the individual test files, is a piece of process worth carrying into Anchor unchanged.

**7. Windows pytest temp-directory friction — resolved 2026-08-31, root cause confirmed.**

The "Ignore pytest temporary artifacts" commit (local history only, not cited by SHA here since this repo has no PR history to anchor it against) deleted 83 files that had been accidentally committed under a repo-root, now-deleted `.pytest-temp/<test-name>/...` tree (e.g. a since-removed `.pytest-temp/test_all_blank_value_represent0/input.xlsx`). That earlier pass left the root cause as an unconfirmed working hypothesis (unresolved `TMPDIR`/`TEMP`). It was wrong: `TEMP`/`TMP` resolve correctly to a real OS temp directory in this environment.

- **Confirmed root cause.** All 85 backend errors on 2026-08-31 were `PermissionError: [WinError 5] Access is denied` inside pytest's own `find_prefixed()` (`_pytest/pathlib.py:175`), scanning `%TEMP%\pytest-of-<user>` — pytest's shared, *username-keyed* base directory for the `tmp_path`/`tmpdir` fixtures. That directory denied access to the real interactive account entirely (confirmed via `icacls`/`Get-Acl`, both "Access is denied" just reading its ACL, not only its contents). `icacls` on the parent `%TEMP%` showed ACEs for a distinct sandboxed-execution account/group (e.g. a coding-agent tool's Windows sandbox) alongside the real user's SID. Pytest names `pytest-of-<user>` from the *username string* (`getpass.getuser()`), not the SID — so a sandboxed principal and the real interactive principal that happen to resolve to the same username string collide on one path, and NTFS ACLs (per-SID) lock out whichever principal didn't create it first. This exactly accounts for the failure count: only `tests/test_excel_reader.py` and `tests/test_cli.py` use `tmp_path`, and their parametrized instances total exactly 85 test IDs.
- **Fix.** `pyproject.toml`'s `[tool.pytest.ini_options]` now sets `addopts = "--basetemp=.pytest-temp"` (`pyproject.toml`), routing `tmp_path`/`tmpdir` to a repo-relative, gitignored directory (`.gitignore:44`) instead of the shared OS-global path. This makes Anchor's test suite independent of that shared, cross-account-collidable location — no repair of the broken `pytest-of-<user>` directory was needed or attempted, since the fix means pytest never touches it again. Trade-off: `--basetemp` clears its contents at the start of every session, so pytest's normal "retain last 3 runs" postmortem behavior is lost; acceptable since `.pytest-temp` is disposable scratch space and a failing test's temp path is still printed within that run's output.

## Why This Matters

The AST-guardrail + delegation-mock-wraps + golden-case pattern is what makes "the AI layer never calculates" and "sensitivity never reimplements a formula" *enforced* claims rather than *aspirational* ones — a reviewer or a future agent doesn't have to re-audit every import by hand, because a violation fails a fast, specific, deterministic test instead of surfacing as a subtle production drift weeks later. The diagnostic-regression-test pattern matters because live/manual testing against real external services is exactly where a POC's mocked test suite has no coverage by construction — every one of the three ingestion bugs above is a category of failure a fake provider literally cannot produce, because the person writing the fake already knows what a "normal" response looks like. Both patterns compound: they're cheap to write once the shape is known, and expensive to reconstruct from scratch under time pressure if forgotten during a rewrite. The Windows temp-directory item matters for the opposite reason — it's a case where the *process* (delete-when-noticed) never became a *fix* (prevent-from-recurring), and that gap should not be carried forward silently into Anchor.

## When to Apply

- Any new isolated package/layer: add its own `test_<layer>_architecture.py` with the four-part guardrail shape on the same PR that introduces the layer, not as a follow-up.
- Any new derived-analysis or AI-facing module that must delegate to an existing authoritative entry point: assert delegation with `patch(..., wraps=...)`, not just output equality.
- Any new frozen-spec calculation: add or extend a golden-case test sourced from the spec document, with the tolerance choice justified inline.
- Any bug found via live/manual testing against a real external service: before closing it out, ask whether the regression test should also narrow *where* a future recurrence of the same symptom would point, the way the occupancy-conflict test does.
- Setting up Anchor's test suite on Windows: verify `TMPDIR`/`TEMP` resolve correctly in the actual execution environment before relying on `tmp_path`, and gitignore any temp-artifact path proactively rather than after a first accidental commit.

## Examples

The reusable AST-guardrail shape (adapt `_ENGINE_DIR`/`openai` per layer):

```python
# tests/test_ai_architecture.py:58-63
def test_engine_package_has_no_openai_import() -> None:
    for source_file in _ENGINE_DIR.glob("*.py"):
        names = _imported_module_names(source_file)
        assert not any(name.startswith("openai") for name in names), (
            f"{source_file} must not import openai"
        )
```

Delegation assertion via `wraps`:

```python
# tests/test_ai_architecture.py:137-148
def test_ai_analyst_delegates_to_the_authoritative_engine_entry_point() -> None:
    with patch(
        "mini_anchor.ai.analyst.analyze_acquisition", wraps=analyze_acquisition
    ) as mock_analyze:
        ai_analyst_module.build_analysis_context(
            GOLDEN_INPUTS,
            target_levered_irr=0.10,
            target_equity_multiple=1.50,
            target_headline_dscr=1.20,
        )

    mock_analyze.assert_called_once_with(GOLDEN_INPUTS)
```

## Related

- [deterministic-engine-ai-grounding-boundary](../architecture-patterns/deterministic-engine-ai-grounding-boundary.md) — the architectural pattern these tests exist to enforce.
- [om-ingestion-provenance-and-analyst-approval-gate](../architecture-patterns/om-ingestion-provenance-and-analyst-approval-gate.md) — the ingestion-side counterpart, including the three live-testing-derived regressions detailed above.
