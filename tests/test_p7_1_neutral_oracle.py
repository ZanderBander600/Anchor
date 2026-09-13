"""Phase 7 Gate P7.1 -- the neutral bit oracle against the real ``f234e4c``
engine (Part AE; Section 15.3).

Two claims, measured rather than argued:

1. **Ordinary analysis with no scenario is bit-identical to** ``main`` **@**
   ``f234e4c``. That covers Quick, Detailed and Lease-Level, through the plan-less
   and the Business Plan entry points, with and without a non-empty plan, with
   and without suite overrides. The baseline tree is exported with
   ``git archive``, which reads objects and never touches the index. Both
   trees run the same cases in fresh interpreters.
2. **A zero-override scenario reproduces that same baseline** bit for bit.

``f234e4c`` is main after P7.0, which changed no production file. Its
production tree is therefore Phase 6's ``0593baa``, the neutral-oracle
baseline Section 15.3 names. The runner is ``tests/_p7_1_oracle_cases.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = Path(__file__).resolve().parent / "_p7_1_oracle_cases.py"
_BASELINE_COMMIT = "f234e4c"


def _run(root: Path, out: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, str(_RUNNER), str(root), str(out)], capture_output=True, cwd=_PROJECT_ROOT
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def oracle(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, dict]:
    scratch = tmp_path_factory.mktemp("p7_1_oracle")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True, capture_output=True, cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    return _run(scratch / "baseline", scratch / "baseline.json"), _run(_PROJECT_ROOT, scratch / "current.json")


def _cases(side: dict) -> list[str]:
    return [case for case in side if not case.startswith("_") and "#" not in case]


def test_the_two_sides_are_the_two_trees(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    assert baseline["_has_scenario"] is False, "the baseline side already has a scenario layer"
    assert current["_has_scenario"] is True
    assert _cases(baseline) == _cases(current)
    assert {case[0] for case in _cases(baseline)} == {"Q", "D", "L"}
    assert len(_cases(baseline)) == 9


def test_ordinary_analysis_is_bit_identical_to_f234e4c(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    mismatched = [case for case in _cases(baseline) if baseline[case] != current[case]]
    assert mismatched == []


def test_a_zero_override_scenario_reproduces_f234e4c_bit_for_bit(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    scenario_cases = [case for case in current if case.endswith("#scenario0")]
    assert len(scenario_cases) == 7
    mismatched = [case for case in scenario_cases if current[case] != baseline[case.removesuffix("#scenario0")]]
    assert mismatched == []


def test_the_comparison_detects_a_single_changed_bit(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    tampered = json.loads(json.dumps(current["L_plan#scenario0"]))
    flows = tampered["results"]["levered_cash_flows"]
    value = float.fromhex(flows[2])
    flows[2] = (value + abs(value) * 2.0**-52).hex()
    assert tampered != baseline["L_plan"]
