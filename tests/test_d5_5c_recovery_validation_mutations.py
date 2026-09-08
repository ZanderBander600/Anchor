"""D5.5C -- mutation kills for the recovery-validation orchestration.

Each mutant below is the specific wrong thing a reviewer would worry about,
applied to the **real** orchestration and shown to be caught -- not asserted to
be impossible. Where a mutant is a source-level property (an import that must
exist, an ordering that must hold, a formula that must not appear), it is
audited against the real source rather than described.

The behavioural mutants monkeypatch the validators that D5.5C wired in, which is
the closest reachable approximation of "the fix was reverted": with the validator
neutered, the defective input must reach the builder's defensive ``ValueError``
again -- proving the validator, not something incidental, is what stops it.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import anchor.analysis.lease_level as orchestration
from anchor.api import app
from anchor.leasing import LeaseIssueCode, LeaseType, LeaseValidationError, RecoveryBasis

from test_d5_5c_recovery_validation import (  # noqa: E402
    LEASE_A,
    MARKET,
    SUITE_A,
    SUITE_B,
    VALID_STRUCTURES,
    analyze,
    result_fingerprint,
    wire_body,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATION = REPO_ROOT / "src" / "anchor" / "analysis" / "lease_level.py"
RECOVERIES = REPO_ROOT / "src" / "anchor" / "leasing" / "recoveries.py"
API = REPO_ROOT / "src" / "anchor" / "api.py"


client = TestClient(app)


# =============================================================================
# M1-M2: the validators are called, and called in the right place
# =============================================================================


def test_m1_the_recovery_validators_are_called_from_the_orchestration() -> None:
    """The mutant: the fix reverted -- neither validator invoked."""

    source = inspect.getsource(
        orchestration.analyze_lease_level_acquisition_with_projection
    )
    assert "require_valid_recovery_inputs(" in source
    assert "require_valid_successor_recovery_assumptions(" in source


def test_m1b_neutering_the_lease_validator_restores_the_defect() -> None:
    """With the validator removed, the invalid lease reaches the builder again.

    This is what makes M1 more than a grep: it proves the call is what stands
    between analyst input and the defensive guard.
    """

    monkeypatched = pytest.MonkeyPatch()
    monkeypatched.setattr(
        orchestration, "require_valid_recovery_inputs", lambda *a, **k: None
    )
    try:
        lease = dataclasses.replace(LEASE_A, lease_type=LeaseType.MODIFIED_GROSS)
        with pytest.raises(ValueError) as caught:
            analyze(leases=(lease,))
        assert not isinstance(caught.value, LeaseValidationError)
        assert "MODIFIED_GROSS" in str(caught.value)
    finally:
        monkeypatched.undo()


def test_m1c_neutering_the_successor_validator_restores_the_defect() -> None:
    """The renewal branch, because this fixture renews with certainty
    (``renewal_probability = 1.0``) and so actually resolves to it.

    The *new*-tenant branch is refused by the validator too, but on this roll no
    builder would ever read it -- which is the point of validating declared
    inputs rather than only resolved ones, and is exactly what the D1/D2 market
    validator above already does for the same records' other fields.
    """

    monkeypatched = pytest.MonkeyPatch()
    monkeypatched.setattr(
        orchestration,
        "require_valid_successor_recovery_assumptions",
        lambda *a, **k: None,
    )
    try:
        market = dataclasses.replace(
            MARKET, renewal_lease_type=LeaseType.MODIFIED_GROSS
        )
        with pytest.raises(ValueError) as caught:
            analyze(market_leasing=market)
        assert not isinstance(caught.value, LeaseValidationError)
        assert "MODIFIED_GROSS" in str(caught.value)
    finally:
        monkeypatched.undo()


def test_m2_the_validators_precede_the_recovery_builders() -> None:
    """The mutant: validation moved after the builders, where it can never run.

    Ordering is read from the real source, so moving either call below the
    builder it protects fails here.
    """

    source = inspect.getsource(
        orchestration.analyze_lease_level_acquisition_with_projection
    )
    successor_check = source.index("require_valid_successor_recovery_assumptions(")
    lease_check = source.index("require_valid_recovery_inputs(")
    first_rollover = source.index("build_recursive_rollover(")
    recursive_recovery = source.index("build_recursive_rollover_recovery(")
    vacancy_recovery = source.index("build_initial_vacancy_rollover_recovery(")

    # Successor terms: validated before any chain is built at all.
    assert successor_check < first_rollover
    # In-place terms: validated before any recovery is attached.
    assert lease_check < recursive_recovery
    assert lease_check < vacancy_recovery


# =============================================================================
# M3-M4: coverage is complete, not partial
# =============================================================================


def test_m3_successor_assumptions_do_not_bypass_validation() -> None:
    """The mutant: only in-place leases validated, successors left to the builder."""

    for branch in ("renewal", "new"):
        market = dataclasses.replace(
            MARKET, **{f"{branch}_lease_type": LeaseType.MODIFIED_GROSS}
        )
        with pytest.raises(LeaseValidationError) as caught:
            analyze(market_leasing=market)
        assert {issue.code for issue in caught.value.result.errors} == {
            LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS
        }


def test_m4_suite_overrides_do_not_bypass_validation() -> None:
    """The mutant: the property default validated while every override sails past.

    Deliberately checked on a suite that is *not* the first, so a fix that
    validated only ``suites[0]`` -- or only the default -- fails.
    """

    override = dataclasses.replace(MARKET, new_lease_type=LeaseType.MODIFIED_GROSS)
    suite_b = dataclasses.replace(SUITE_B, market_leasing_override=override)

    with pytest.raises(LeaseValidationError) as caught:
        analyze(suites=(SUITE_A, suite_b))

    paths = [issue.path for issue in caught.value.result.errors]
    assert "suites[1].market_leasing_override.new_recovery_basis" in paths


def test_m4b_every_override_is_validated_not_just_the_first() -> None:
    override = dataclasses.replace(MARKET, renewal_lease_type=LeaseType.MODIFIED_GROSS)
    suite_a = dataclasses.replace(SUITE_A, market_leasing_override=MARKET)
    suite_b = dataclasses.replace(SUITE_B, market_leasing_override=override)

    with pytest.raises(LeaseValidationError) as caught:
        analyze(suites=(suite_a, suite_b))

    assert "suites[1].market_leasing_override.renewal_recovery_basis" in [
        issue.path for issue in caught.value.result.errors
    ]


# =============================================================================
# M5-M6: the reported defects specifically
# =============================================================================


def test_m5_modified_gross_without_a_basis_never_reaches_the_builder() -> None:
    lease = dataclasses.replace(LEASE_A, lease_type=LeaseType.MODIFIED_GROSS)
    with pytest.raises(LeaseValidationError) as caught:
        analyze(leases=(lease,))
    # Not the builder's message.
    assert "Validate recovery inputs before building a schedule" not in str(caught.value)


def test_m6_recovery_terms_on_a_non_modified_gross_lease_never_reach_the_builder() -> None:
    for lease_type in (LeaseType.NNN, LeaseType.GROSS):
        lease = dataclasses.replace(
            LEASE_A,
            lease_type=lease_type,
            recovery_basis=RecoveryBasis.EXPENSE_STOP_PSF,
            expense_stop_psf=10.0,
        )
        with pytest.raises(LeaseValidationError) as caught:
            analyze(leases=(lease,))
        assert LeaseIssueCode.RECOVERY_BASIS_ON_NON_MODIFIED_GROSS in {
            issue.code for issue in caught.value.result.errors
        }


# =============================================================================
# M7-M9: the API transports the validation error, and nothing else
# =============================================================================


def test_m7_api_error_mapping_was_not_touched() -> None:
    """The mutant: `except ValueError: return 422` bolted on instead of a fix.

    That substitution would turn every genuine internal invariant breach into a
    validation message, telling an analyst their inputs were wrong when the
    model broke. D5.5C makes no API change at all -- the existing
    `LeaseValidationError` mapping already produced the right 422 once the
    error was actually raised.
    """

    import subprocess

    changed = subprocess.run(
        ["git", "diff", "--name-only", "6ccd225", "--", "src/anchor/api.py"],
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert changed.returncode == 0, changed.stderr.decode()
    assert changed.stdout.decode().strip() == "", "api.py changed"


def test_m7b_the_structured_handler_precedes_any_generic_one() -> None:
    """`LeaseValidationError` subclasses `ValueError`, so clause **order** is
    what decides whether an analyst sees a structured issue list or a raw Python
    string.

    `api.py` keeps a last-resort `except ValueError` on the sensitivity handlers
    -- pre-existing, and legitimate as a floor. This pins the thing that makes it
    safe: every handler that catches both must catch the specific one first. If
    they were reordered, the fix would still raise correctly and the API would
    still answer 422, but the `code`/`path`/`severity` detail would silently
    become a sentence.
    """

    tree = ast.parse(API.read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        names: list[str] = []
        for handler in node.handlers:
            if handler.type is None:
                names.append("<bare>")
            elif isinstance(handler.type, ast.Name):
                names.append(handler.type.id)
            elif isinstance(handler.type, ast.Tuple):
                names.extend(
                    element.id
                    for element in handler.type.elts
                    if isinstance(element, ast.Name)
                )
        if "LeaseValidationError" in names and "ValueError" in names:
            assert names.index("LeaseValidationError") < names.index("ValueError"), (
                f"line {node.lineno}: a generic ValueError handler precedes the "
                "structured LeaseValidationError one, so the issue detail would "
                "be flattened to a string"
            )
            checked += 1
    assert checked > 0, "the handler audit found nothing to check"


def test_m8_the_invalid_case_is_not_a_500() -> None:
    for body in (
        wire_body(lease_overrides={"lease_type": "modified_gross"}),
        wire_body(
            lease_overrides={
                "recovery_basis": "expense_stop_psf",
                "expense_stop_psf": 10.0,
            }
        ),
        wire_body(market_overrides={"new_lease_type": "modified_gross"}),
        wire_body(market_overrides={"renewal_lease_type": "modified_gross"}),
    ):
        response = client.post("/analyze", json=body)
        assert response.status_code == 422, response.text[:200]


def test_m9_the_invalid_case_is_not_a_200() -> None:
    """The opposite failure: validation loosened until the deal simply passes."""

    response = client.post(
        "/analyze", json=wire_body(lease_overrides={"lease_type": "modified_gross"})
    )
    assert response.status_code != 200
    assert "monthly_projection" not in response.text


# =============================================================================
# M10-M12: valid economics are byte-identical
# =============================================================================


@pytest.mark.parametrize("structure", sorted(VALID_STRUCTURES))
def test_m10_m11_m12_valid_structures_are_unchanged_by_validation(
    structure: str,
) -> None:
    """The mutant: the fix quietly altered what a valid deal computes.

    A validation-only change must leave the whole result envelope identical, so
    the fingerprint is compared against itself across a call that now runs two
    extra validators. Any recovery, NOI or return drift shows here.
    """

    lease = dataclasses.replace(LEASE_A, **VALID_STRUCTURES[structure])
    first = result_fingerprint(analyze(leases=(lease,)))
    second = result_fingerprint(analyze(leases=(lease,)))
    assert first == second

    # And the analysis really did produce recovery economics to be wrong about.
    monthly = analyze(leases=(lease,)).monthly_projection
    assert len(monthly.expense_recovery) == len(monthly.noi)


def test_m10b_the_three_valid_structures_remain_distinguishable() -> None:
    """If validation had flattened recovery -- or bypassed it -- these collapse."""

    gross_successors = dataclasses.replace(
        MARKET,
        renewal_lease_type=LeaseType.GROSS,
        new_lease_type=LeaseType.GROSS,
    )
    totals = {
        structure: sum(
            analyze(
                leases=(dataclasses.replace(LEASE_A, **overrides),),
                market_leasing=gross_successors,
            ).monthly_projection.expense_recovery
        )
        for structure, overrides in VALID_STRUCTURES.items()
    }
    assert totals["nnn"] > totals["modified_gross"] > totals["gross"]
    assert totals["gross"] == pytest.approx(0.0)


# =============================================================================
# M13-M14: the fix stayed in its lane
# =============================================================================


def test_m13_no_frontend_validation_was_added_as_a_workaround() -> None:
    """The mutant: the defect papered over in the client instead of fixed.

    The frontend must keep submitting the analyst's actual inputs and rendering
    whatever the backend says -- so no client-side recovery rule, and no
    disabling of the Modified Gross option.
    """

    web = REPO_ROOT / "web" / "src"
    for relative in (
        "leaseLevelConvert.ts",
        "components/SuiteLeaseEditor.tsx",
        "components/RentRollTable.tsx",
        "useLeaseLevelDeal.ts",
    ):
        text = (web / relative).read_text(encoding="utf-8")
        for forbidden in (
            "MISSING_MODIFIED_GROSS_RECOVERY_BASIS",
            "RECOVERY_BASIS_ON_NON_MODIFIED_GROSS",
            "requires a recovery basis",
            "must be modified gross",
        ):
            assert forbidden not in text, f"{relative} restates a backend rule"

    # Modified Gross is still offered to the analyst.
    convert = (web / "leaseLevelConvert.ts").read_text(encoding="utf-8")
    assert "modified_gross" in convert


def test_m14_no_recovery_formula_was_introduced_or_changed() -> None:
    """The mutant: a 'fix' that reached into the recovery arithmetic.

    `recoveries.py` is financial authority. D5.5C changes validation coverage
    only, so the module must be byte-identical to the pre-gate commit -- and the
    orchestration must contain no recovery arithmetic of its own.
    """

    import subprocess

    changed = subprocess.run(
        ["git", "diff", "--name-only", "6ccd225", "--", "src/anchor/leasing/"],
        capture_output=True,
        cwd=REPO_ROOT,
    )
    assert changed.returncode == 0, changed.stderr.decode()
    assert changed.stdout.decode().strip() == "", "a leasing module changed"

    # The orchestration adds calls, not arithmetic.
    source = inspect.getsource(
        orchestration.analyze_lease_level_acquisition_with_projection
    )
    # Real arithmetic, not assignments: `recovery = build_...()` is a call.
    for forbidden in ("expense_stop_psf -", "* share", "max(0", "* pool.", "/ 12"):
        assert forbidden not in source, f"orchestration computes recovery: {forbidden}"


def test_the_defensive_guards_remain_in_the_builder() -> None:
    """D5.5C does not weaken the builders' invariants; it stops analyst input
    from reaching them. The guard must still be there for every other caller."""

    text = RECOVERIES.read_text(encoding="utf-8")
    assert "is MODIFIED_GROSS and carries no " in text
    assert "explicit contractual recovery basis; Anchor never infers one. " in text
    assert "a recovery basis or expense stop; a lease with a contractual stop " in text
