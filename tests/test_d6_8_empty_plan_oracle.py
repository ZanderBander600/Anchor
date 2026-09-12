"""Phase 6 Gate D6.8 -- the empty-plan oracle against 7f52b9e (gate Parts V and
AS).

The pre-D6.8 source tree is exported from git (``git archive``, which reads
objects and never touches the index). Both it and today's tree run
``tests/_d6_8_oracle_cases.py`` in fresh interpreters over deals with no
Business Plan in all three modes. The oracle proves three things:

1. Every deterministic figure the AI context carries is bit-identical --
   results, sensitivity presets and break-even.
2. The user prompt is byte-identical wherever both IRRs are reported. Where one
   is not, the only addition is ``irr_status``, the reason for the N/A.
3. The system prompt changed only as documented. Its removed lines are exactly
   the three amended rules (2b, 35, 36); everything else D6.8 did to it is
   addition.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = Path(__file__).resolve().parent / "_d6_8_oracle_cases.py"
_BASELINE_COMMIT = "7f52b9e"


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
    scratch = tmp_path_factory.mktemp("d6_8_oracle")
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


def _payload(user_prompt: str) -> tuple[str, dict]:
    start = user_prompt.index("{")
    return user_prompt[:start], json.loads(user_prompt[start:])


def test_the_oracle_ran_both_trees_over_the_same_cases(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    assert set(baseline) == set(current) == {
        "quick-golden",
        "quick-v2-with-context",
        "detailed",
        "lease-level",
        "lease-level-with-context",
    }


def test_every_deterministic_figure_is_bit_identical_under_an_empty_plan(
    oracle: tuple[dict, dict],
) -> None:
    baseline, current = oracle
    for case in baseline:
        for part in ("results", "sensitivities", "break_even"):
            assert current[case][part] == baseline[case][part], (case, part)


def test_the_user_prompt_is_byte_identical_wherever_both_irrs_are_reported(
    oracle: tuple[dict, dict],
) -> None:
    baseline, current = oracle
    reported = [
        case
        for case in baseline
        if baseline[case]["results"]["levered_irr_status"] == "defined"
        and baseline[case]["results"]["unlevered_irr_status"] == "defined"
    ]
    assert {"quick-golden", "quick-v2-with-context", "detailed"} <= set(reported)
    for case in reported:
        assert current[case]["user_prompt"] == baseline[case]["user_prompt"], case


def test_an_unreported_irr_adds_only_its_reason(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    unreported = [
        case
        for case in baseline
        if baseline[case]["results"]["levered_irr_status"] != "defined"
        or baseline[case]["results"]["unlevered_irr_status"] != "defined"
    ]
    # Not vacuous: the Lease-Level fixture's lease-up capital makes its equity
    # cash flow change sign twice, with no plan at all.
    assert unreported == ["lease-level", "lease-level-with-context"]
    for case in unreported:
        base_preamble, base_payload = _payload(baseline[case]["user_prompt"])
        preamble, shown = _payload(current[case]["user_prompt"])
        assert preamble == base_preamble, case
        assert "business_plan_and_capital_economics" not in shown, case
        assert "irr_status" in shown, case
        assert {key: value for key, value in shown.items() if key != "irr_status"} == base_payload, case


#: Every baseline system-prompt line D6.8 removed -- the old wording of the
#: three rules whose claims a Business Plan would make false. Nothing else.
_REMOVED_LINES = [
    "   supplied NOI/CapEx/debt-service schedule already shown to you (for",
    "   Improvements and Leasing Commissions. A year carrying heavy leasing",
    "   capital -- initial lease-up, a large expiry, the opening year of a",
    "   lease_level hold -- therefore shows a figure depressed by capital",
    "   events, not by the property's ongoing operations. Never call such a",
    "   distribution\", a \"capital call\", \"additional equity\", \"owner funding\",",
    "   or a shortfall the owner must fund -- Anchor supplies no such field and",
    "   models no such event. This holds for every supplied cash-flow figure: a",
]


def test_the_system_prompt_changed_only_as_documented(oracle: tuple[dict, dict]) -> None:
    baseline, current = oracle
    before = baseline["quick-golden"]["system_prompt"].splitlines()
    after = current["quick-golden"]["system_prompt"].splitlines()

    assert [line for line in before if line not in set(after)] == _REMOVED_LINES
    added = "\n".join(line for line in after if line not in set(before))
    for block in ("BUSINESS PLAN & CAPITAL ECONOMICS RULES", "IRR STATUS RULES"):
        assert block in added
    # One system prompt for every mode, before and after.
    for record in (baseline, current):
        assert len({record[case]["system_prompt"] for case in record}) == 1
