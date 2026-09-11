"""Phase 6 Gate D6.2 -- the neutral-input bit oracle against the real 7e67cde
engine.

``docs/architecture/D6_BUSINESS_PLAN_CONVENTIONS.md`` Section 14: an empty
Business Plan must preserve every existing D5 financial output. "Preserve" is
measured here, not argued: the pre-D6.2 source tree is exported from git
(``git archive``, which reads objects and never touches the index), both it and
today's tree run the same case set in fresh interpreters, and every field that
existed at 7e67cde must match **bit for bit** -- through the mode entry points
*and* through the D6.2 Business Plan entry points with ``BusinessPlan()``.

Quick, Detailed and Lease-Level are all covered, including the Detailed
operating projection and the Lease-Level annual projection, which D6.2 must not
touch at all. Only the nine genuinely new D6.2 fields are exempt, and they are
checked for neutrality instead.

The runner is ``tests/_d6_2_oracle_cases.py``. It imports ``anchor`` from the
tree under test and asserts that it did, so an installed copy can never stand
in for either side.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = Path(__file__).resolve().parent / "_d6_2_oracle_cases.py"
_BASELINE_COMMIT = "7e67cde"

_D6_2_FIELDS = frozenset(
    {
        "closing_project_capital",
        "project_capital_by_year",
        "post_hold_project_capital",
        "owner_expenses_by_year",
        "property_cash_flow_by_year",
        "unlevered_owner_cash_flow_by_year",
        "levered_owner_cash_flow_by_year",
        "total_closing_uses",
        "total_closing_sources",
    }
)


def _run(root: Path, out: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, str(_RUNNER), str(root), str(out)],
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return json.loads(out.read_text(encoding="utf-8"))


def _mismatches(baseline: dict, current: dict) -> tuple[list[tuple], int]:
    """Every baseline field compared against both current variants."""

    mismatches: list[tuple] = []
    compared = 0
    for case, sections in baseline.items():
        if case.startswith("_"):
            continue
        for variant in (case, f"{case}#bp"):
            if variant not in current:
                mismatches.append((variant, "<missing case>"))
                continue
            for section, fields in sections.items():
                for field, value in fields.items():
                    compared += 1
                    got = current[variant][section].get(field, "<missing field>")
                    if got != value:
                        mismatches.append((variant, section, field, value, got))
    return mismatches, compared


@pytest.fixture(scope="module")
def oracle(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, dict]:
    scratch = tmp_path_factory.mktemp("d6_2_oracle")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True,
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")

    baseline = _run(scratch / "baseline", scratch / "baseline.json")
    current = _run(_PROJECT_ROOT, scratch / "current.json")
    return baseline, current


def test_the_two_sides_are_the_two_engines(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle

    assert baseline["_has_bp"] is False, "the baseline side is not the pre-D6.2 engine"
    assert current["_has_bp"] is True, "the current side lacks the D6.2 entry points"
    cases = [case for case in baseline if not case.startswith("_")]
    assert len(cases) == 9
    assert {case[0] for case in cases} == {"Q", "D", "L"}
    for case in cases:
        assert not _D6_2_FIELDS & set(baseline[case]["results"])


def test_the_empty_plan_reproduces_7e67cde_bit_for_bit(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle

    mismatches, compared = _mismatches(baseline, current)

    assert not mismatches, mismatches[:20]
    assert compared > 600, compared  # 9 cases x 2 variants x every pre-D6.2 field


def test_the_only_new_fields_are_the_d6_2_fields_and_they_are_neutral(
    oracle: tuple[dict, dict],
) -> None:
    baseline, current = oracle
    zero = (0.0).hex()

    for case, sections in baseline.items():
        if case.startswith("_"):
            continue
        for variant in (case, f"{case}#bp"):
            for section, fields in sections.items():
                new = set(current[variant][section]) - set(fields)
                assert new == (_D6_2_FIELDS if section == "results" else set()), (variant, section)
            results = current[variant]["results"]
            hold = len(results["noi_by_year"])
            assert results["closing_project_capital"] == zero
            assert results["post_hold_project_capital"] == zero
            assert results["project_capital_by_year"] == [zero] * hold
            assert results["owner_expenses_by_year"] == [zero] * hold
            assert (
                results["unlevered_owner_cash_flow_by_year"]
                == results["property_cash_flow_by_year"]
            )
            assert (
                results["unlevered_cash_flows"][1:hold]
                == results["unlevered_owner_cash_flow_by_year"][: hold - 1]
            )


def test_the_comparison_detects_a_single_changed_bit(oracle: tuple[dict, dict]) -> None:
    """Self-test: the oracle cannot pass vacuously."""

    baseline, current = oracle
    tampered = json.loads(json.dumps(current))
    value = float.fromhex(tampered["L1_rollover_and_lease_up#bp"]["results"]["levered_cash_flows"][2])
    tampered["L1_rollover_and_lease_up#bp"]["results"]["levered_cash_flows"][2] = (
        value + abs(value) * 2.0**-52
    ).hex()

    mismatches, _ = _mismatches(baseline, tampered)
    assert [m[:3] for m in mismatches] == [
        ("L1_rollover_and_lease_up#bp", "results", "levered_cash_flows")
    ]
