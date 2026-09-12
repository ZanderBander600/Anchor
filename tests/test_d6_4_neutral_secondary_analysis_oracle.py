"""Phase 6 Gate D6.4 -- neutral secondary analysis against the real ba804ca tree
(gate Part L, reference case R11).

The pre-D6.4 source tree is exported from git (``git archive``, which reads
objects and never touches the index). Both it and today's tree run
``tests/_d6_4_oracle_cases.py`` in fresh interpreters over one fixed corpus:
Quick, Detailed and Lease-Level one-way and two-way sensitivity across every
supported target and metric, both standard preset bundles, both standard
break-even bundles under both return hurdles, both public threshold solvers,
and the Quick and Detailed AI Analyst contexts together with the user prompt
each one produces.

Every output is compared bit for bit (``float.hex``):

- today's call with no Business Plan must equal ba804ca's; and
- today's call with ``business_plan=BusinessPlan()`` must equal ba804ca's too.

So no existing target value, cell, threshold, bundle or prompt moved.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = Path(__file__).resolve().parent / "_d6_4_oracle_cases.py"
#: ``main`` after D6.3, immediately before D6.4.
_BASELINE_COMMIT = "ba804ca"


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
    scratch = tmp_path_factory.mktemp("d6_4_oracle")
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


def _cases(side: dict) -> set[str]:
    return {name for name in side if not name.startswith("_") and not name.endswith("#bp")}


def test_the_two_sides_are_the_two_trees_on_one_corpus(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle

    assert baseline["_has_bp"] is False and current["_has_bp"] is True
    assert _cases(baseline) == _cases(current)
    assert {name + "#bp" for name in _cases(current)} <= set(current)

    names = _cases(baseline)
    families = {
        "quick one-way": sum(n.startswith("quick/") and "/one_way/" in n for n in names),
        "detailed one-way": sum(n.startswith("detailed/") and "/one_way/" in n for n in names),
        "lease-level one-way": sum(n.startswith("lease_level/one_way/") for n in names),
        "two-way": sum("/two_way/" in n for n in names),
        "presets": sum(n.endswith("/presets") for n in names),
        "break-even": sum("/break_even/" in n or n.endswith("/threshold") for n in names),
        "ai prompts": sum(n.endswith("/ai_user_prompt") for n in names),
    }
    assert families == {
        "quick one-way": 90,
        "detailed one-way": 40,
        "lease-level one-way": 16,
        "two-way": 15,
        "presets": 5,
        "break-even": 15,
        "ai prompts": 5,
    }
    # The corpus is answered, not refused: no case raised on either side.
    assert not [n for n in names if isinstance(baseline[n], dict) and "raises" in baseline[n]]


def test_no_neutral_secondary_output_moved_since_ba804ca(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    moved = sorted(name for name in _cases(baseline) if current[name] != baseline[name])
    assert moved == []


def test_the_explicit_empty_plan_reproduces_ba804ca_bit_for_bit(
    oracle: tuple[dict, dict],
) -> None:
    baseline, current = oracle
    moved = sorted(
        name for name in _cases(baseline) if current[name + "#bp"] != baseline[name]
    )
    assert moved == []


def test_the_ai_user_prompt_is_unchanged_since_ba804ca(oracle: tuple[dict, dict]) -> None:
    """The prompt the model receives for a deal with no plan is byte-identical
    to ba804ca's -- D6.4 changes no prompt content."""

    baseline, current = oracle
    prompts = sorted(n for n in _cases(baseline) if n.endswith("/ai_user_prompt"))
    assert prompts
    for name in prompts:
        assert isinstance(baseline[name], str) and baseline[name]
        assert current[name] == baseline[name]
        assert current[name + "#bp"] == baseline[name]
