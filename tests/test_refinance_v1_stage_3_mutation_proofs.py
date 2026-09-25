"""Refinance & Capital Events V1 Stage 3 -- mutation proofs.

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Sections 12.5, 16.3 and
25. Each mutant is the specific wrong thing a reviewer would worry about in the
refinance-aware report, the gate's replacement, the presentation facts and the
audit workbook -- one exact textual edit to one real production module -- and
is shown to be caught by a named Stage 3 test, not asserted to be impossible.

The harness is Stage 2's, unchanged in method (``_mutant``, ``_install`` and
``_killed``): the module's own file in this repository is read (its path is
asserted first), the edit applied exactly once, and every function and class it
defines patched wherever the real one is referenced for the duration of the
proof only. The test must pass on the real code, fail with an assertion under
the mutant, and pass again once it is withdrawn. Nothing is written to the
repository.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

import test_refinance_v1_stage_2_mutation_proofs as harness
import test_refinance_v1_stage_3_audit_workbook as workbook_tests
import test_refinance_v1_stage_3_presentation as presentation_tests
import test_refinance_v1_stage_3_report as report_tests
from anchor import api as api_module
from anchor.deals import memo_dependencies, refinance_presentation, structured_variants
from anchor.exports.refinance import source as audit_source
from anchor.memo import publication
from anchor.reporting import assembly
from anchor.reporting import refinance as report_refinance


def _referencing_modules() -> tuple[ModuleType, ...]:
    return tuple(
        module
        for name, module in sorted(sys.modules.items())
        if isinstance(module, ModuleType)
        and (
            name == "anchor"
            or name.startswith("anchor.")
            or name.startswith(("test_refinance_v1_stage_3", "_refinance_v1_stage_3", "_refinance_v1"))
        )
    )


@pytest.fixture(autouse=True)
def _stage_3_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch a mutant wherever the Stage 3 tests and fixtures reference it."""

    monkeypatch.setattr(harness, "_referencing_modules", _referencing_modules)


@contextmanager
def _database() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="refi-s3-mutant-")) / "anchor.db"
    previous = os.environ.get("ANCHOR_DB_PATH")
    os.environ["ANCHOR_DB_PATH"] = str(path)
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop("ANCHOR_DB_PATH", None)
        else:
            os.environ["ANCHOR_DB_PATH"] = previous


def _with_db(test: Callable[[Path], None]) -> Callable[[], None]:
    def run() -> None:
        with _database() as db:
            test(db)

    return run


def _with_client(test: Callable[[Path, TestClient], None]) -> Callable[[], None]:
    def run() -> None:
        with _database() as db:
            test(db, TestClient(api_module.app))

    return run


_MUTANTS: dict[str, tuple[Callable[[], None], ModuleType, tuple[tuple[str, str], ...]]] = {
    # 1. A contribution printed with its sign under a heading that already
    #    says which way it moved: "-$640,000" beside "Contribution Required".
    "m1_contribution_keeps_its_sign": (
        _with_db(report_tests.test_f6_a_contribution_is_headed_as_one_and_shown_as_a_magnitude),
        report_refinance,
        (('return format_currency(value).removeprefix("-")', "return format_currency(value)"),),
    ),
    # 2. The IRR sign-rule outcome reported as a refinance failure.
    "m2_irr_reason_code_is_the_refinance_code": (
        _with_db(report_tests.test_f6_a_contribution_is_headed_as_one_and_shown_as_a_magnitude),
        report_refinance,
        (
            (
                "code=_irr_code(common.irr_status) if irr_note else REFINANCE_UNAVAILABLE_CODE,",
                "code=REFINANCE_UNAVAILABLE_CODE,",
            ),
        ),
    ),
    # 3. An LTV refinance's valuation dependency goes undisclosed.
    "m3_ltv_valuation_undisclosed": (
        _with_db(report_tests.test_an_ltv_refinance_discloses_the_value_it_measured_against),
        report_refinance,
        (("    value = event.value_dependency\n    if value is not None:", "    value = event.value_dependency\n    if False:"),),
    ),
    # 3b. A DSCR refinance's forward-NOI dependency goes undisclosed.
    "m3b_forward_noi_undisclosed": (
        _with_db(report_tests.test_a_dscr_only_refinance_discloses_no_valuation),
        report_refinance,
        (("    noi = event.noi_dependency\n    if noi is not None:", "    noi = event.noi_dependency\n    if False:"),),
    ),
    # 4. The gate's replacement dropped: an unexecuted refinance publishes.
    "m4_publication_ignores_an_unexecuted_refinance": (
        _with_db(report_tests.test_an_unexecuted_refinance_is_refused_at_publication),
        publication,
        (
            (
                "    refusals.extend(refinance_result_refusal(reason) for reason in context.unexecuted_refinances)\n",
                "",
            ),
        ),
    ),
    # 5. The one feeding function reports nothing missed.
    "m5_unexecuted_refinances_reports_none": (
        _with_db(report_tests.test_an_unexecuted_refinance_is_refused_at_publication),
        memo_dependencies,
        (("    missed = not_executed(analysis.result)\n    if not missed:", "    missed = ()\n    if not missed:"),),
    ),
    # 6. An unexecuted replacement vanishes from the positions table.
    "m6_unexecuted_replacement_is_omitted": (
        _with_db(report_tests.test_an_unexecuted_refinance_previews_as_unavailable_never_zero),
        assembly,
        (
            (
                '        structured.result.positions or getattr(structured.result, "unexecuted_positions", ())\n',
                "        structured.result.positions\n",
            ),
        ),
    ),
    # 7. No Common Equity matrix for a refinance without an authored marker.
    "m7_no_implicit_common_equity": (
        _with_client(presentation_tests.test_the_implicit_common_equity_matrix_reports_the_refinance_adjusted_return),
        structured_variants,
        (("    if not refinance_bearing or any(", "    if True or any("),),
    ),
    # 8. The acquisition DSCR left unlabeled in the presence facts.
    "m8_presence_drops_a_reference_metric": (
        _with_client(presentation_tests.test_presence_names_a_refinance_bearing_strategy_and_the_reference_metrics),
        refinance_presentation,
        (("    DecisionMetric.MIN_DSCR,\n", ""),),
    ),
    # 9. Exports 1-3 not labeled when a refinance exists.
    "m9_exports_unlabeled": (
        _with_client(presentation_tests.test_a_quick_export_labels_the_levered_figures_when_a_refinance_exists),
        api_module,
        (("    return dataclasses.replace(source, refinance_configured=True)", "    return source"),),
    ),
    # 10. The audit exported for an analysis that is no longer the saved state.
    "m10_audit_ignores_staleness": (
        _with_client(workbook_tests.test_a_structure_change_after_the_analysis_stales_the_audit),
        audit_source,
        (("    if analysis.structured_source_fingerprint != analysed_fingerprint:", "    if False:"),),
    ),
    # 11. The audit exported partially for an unexecuted refinance: both of
    #     its refusal layers -- the event status and Common Equity's own
    #     availability -- removed together (either alone still refuses).
    "m11_audit_exports_an_unexecuted_refinance": (
        _with_client(workbook_tests.test_an_unexecuted_refinance_is_refused_never_exported_partially),
        audit_source,
        (
            (
                "    if any(event.status is not RefinanceStatus.EXECUTED for event in events):",
                "    if False:",
            ),
            ("    if common.cash_flows is None or common.irr_status is None:", "    if False:"),
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(_MUTANTS))
def test_the_mutant_is_killed(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, module, edits = _MUTANTS[name]
    harness._killed(monkeypatch, fixture, module, *edits)


def test_every_mutant_edits_a_real_line() -> None:
    """A mutant whose text no longer matches would be a silent no-op; each
    edit must occur exactly once in its module's own file."""

    for name, (_, module, edits) in _MUTANTS.items():
        source = Path(module.__file__ or "").read_bytes().decode("utf-8").replace("\r\n", "\n")
        for old, _new in edits:
            assert source.count(old) == 1, (name, old)
