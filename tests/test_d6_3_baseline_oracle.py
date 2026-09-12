"""Phase 6 Gate D6.3 -- IRR, equity multiple and result identity against the
real b828956 engine (gate specification Parts B and N).

The pre-D6.3 source tree is exported from git (``git archive``, which reads
objects and never touches the index), both it and today's tree run
``tests/_d6_3_oracle_cases.py`` in fresh interpreters, and:

- ``calculate_irr`` and ``calculate_equity_multiple`` must return exactly the
  same float -- or ``None`` -- as b828956 for every one of 3,000+ series,
  covering every IRR branch;
- every ``AcquisitionResults`` field that existed at b828956 must match bit for
  bit for Quick, Detailed and Lease-Level under six Business Plans, including
  multiple-sign-change and final-year-deficit profiles;
- the only new fields are D6.3's six, and each new status agrees with its
  value (``defined`` exactly when an IRR is reported).
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = Path(__file__).resolve().parent / "_d6_3_oracle_cases.py"
_BASELINE_COMMIT = "b828956"

_D6_3_FIELDS = frozenset(
    {
        "net_additional_equity_requirement_by_year",
        "total_equity_invested",
        "total_cash_returned",
        "total_profit",
        "unlevered_irr_status",
        "levered_irr_status",
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


@pytest.fixture(scope="module")
def oracle(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, dict]:
    scratch = tmp_path_factory.mktemp("d6_3_oracle")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True,
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    return _run(scratch / "baseline", scratch / "baseline.json"), _run(
        _PROJECT_ROOT, scratch / "current.json"
    )


def _result_mismatches(baseline: dict, current: dict) -> list[tuple]:
    mismatches = []
    for case, fields in baseline["results"].items():
        for field, value in fields.items():
            got = current["results"][case].get(field, "<missing>")
            if got != value:
                mismatches.append((case, field, value, got))
    return mismatches


def test_the_two_sides_are_the_two_engines_on_one_corpus(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle

    assert baseline["has_status"] is False and current["has_status"] is True
    assert baseline["corpus"]["digest"] == current["corpus"]["digest"]
    assert len(baseline["corpus"]["irr"]) > 3000
    assert len(baseline["results"]) == 18


def test_calculate_irr_is_bit_identical_to_b828956(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    base_irr, cur_irr = baseline["corpus"]["irr"], current["corpus"]["irr"]

    differing = [index for index, (a, b) in enumerate(zip(base_irr, cur_irr)) if a != b]
    assert not differing, differing[:10]
    # The corpus exercises both outcomes heavily, not one.
    assert sum(value is None for value in base_irr) > 500
    assert sum(value is not None for value in base_irr) > 500


def test_the_equity_multiple_is_bit_identical_to_b828956(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    assert baseline["corpus"]["equity_multiple"] == current["corpus"]["equity_multiple"]


def test_every_status_agrees_with_its_value(oracle: tuple[dict, dict]) -> None:
    _, current = oracle
    statuses = current["corpus"]["status"]

    for irr, status in zip(current["corpus"]["irr"], statuses):
        assert (status == "defined") == (irr is not None)
    # Every member is reached by the corpus.
    assert set(statuses) == {
        "defined",
        "no_nonzero_cash_flow",
        "first_nonzero_not_negative",
        "no_positive_cash_flow",
        "multiple_sign_changes",
        "root_outside_search_domain",
        "numerical_failure",
    }


def test_every_b828956_result_field_is_bit_identical(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle

    assert not _result_mismatches(baseline, current)
    for case, fields in current["results"].items():
        assert set(fields) - set(baseline["results"][case]) == _D6_3_FIELDS, case
        assert (fields["levered_irr_status"] == "defined") == (fields["levered_irr"] is not None)
        assert (fields["unlevered_irr_status"] == "defined") == (
            fields["unlevered_irr"] is not None
        )
    # The deficit plans really do produce undefined IRRs through the engine.
    assert current["results"]["quick/final_year_deficit"]["levered_irr_status"] == (
        "multiple_sign_changes"
    )


def test_the_comparison_detects_a_single_changed_bit(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    tampered = json.loads(json.dumps(current))
    value = float.fromhex(tampered["results"]["detailed/everything"]["equity_multiple"])
    tampered["results"]["detailed/everything"]["equity_multiple"] = (value * (1 + 2.0**-52)).hex()

    assert [m[:2] for m in _result_mismatches(baseline, tampered)] == [
        ("detailed/everything", "equity_multiple")
    ]
