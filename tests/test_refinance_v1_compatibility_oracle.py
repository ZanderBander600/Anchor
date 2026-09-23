"""Refinance & Capital Events V1 Stage 1 -- no-refinance byte parity (F20).

``docs/architecture/REFINANCE_CAPITAL_EVENTS_V1.md`` Section 19 and invariant
INV-10. With no refinance, every Capital Structure and Partnership result must
be exactly what the accepted product baseline ``0e9f8cc`` produces: the same
classes, the same fields and the same bits.

The baseline is the accepted tree itself, exported with ``git archive`` (which
reads objects and never touches the index -- no stash, no second checkout), and
the one builder (``tests/_refinance_v1_baseline_builder.py``) runs the same
fixed corpus against it and against this tree. The builder asserts which tree
it imported, so the two runs cannot silently share one.

Stage 1 adds no route, store, schema, codec or report, so the persisted and
HTTP parity of Section 19 belongs to Stage 2's oracle; the existing
compatibility oracles (P7.7 to P7.10) keep proving their own surfaces here.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = Path(__file__).resolve().parent / "_refinance_v1_baseline_builder.py"
#: The accepted product baseline: the last commit that changed product
#: behavior before this gate is ``d7e4d75``; ``0e9f8cc`` and ``2e1f84a`` after it
#: are documentation only, and this oracle proves it by running the tree.
_BASELINE_COMMIT = "0e9f8cc29309ca129f514469c44bbcf8df4a4424"


def _build(root: Path, out: Path) -> dict[str, str]:
    completed = subprocess.run(
        [sys.executable, str(_BUILDER), str(root), str(out)], capture_output=True, cwd=_PROJECT_ROOT
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def records(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, str], dict[str, str]]:
    scratch = tmp_path_factory.mktemp("refinance_v1_baseline")
    archive = scratch / "baseline.zip"
    subprocess.run(
        ["git", "archive", "--format=zip", "-o", str(archive), _BASELINE_COMMIT, "src"],
        check=True,
        capture_output=True,
        cwd=_PROJECT_ROOT,
    )
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(scratch / "baseline")
    return _build(scratch / "baseline", scratch / "baseline.json"), _build(_PROJECT_ROOT, scratch / "current.json")


def test_the_baseline_is_the_accepted_tree_without_any_refinance() -> None:
    """The two runs cannot be one tree: the builder asserts the tree it
    imported, and the accepted tree holds no refinance module at all."""

    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", _BASELINE_COMMIT, "src/anchor/capital_structure", "src/anchor/engine"],
        capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT,
    ).stdout.split()
    assert "src/anchor/capital_structure/contracts.py" in listing
    assert not [path for path in listing if "refinance" in path or "event" in path or "debt_balance" in path]


def test_every_no_refinance_result_is_identical_to_the_accepted_baseline(
    records: tuple[dict[str, str], dict[str, str]],
) -> None:
    baseline, current = records
    assert sorted(baseline) == sorted(current)
    for name in sorted(baseline):
        assert current[name] == baseline[name], name


def test_the_corpus_covers_every_structured_path(records: tuple[dict[str, str], dict[str, str]]) -> None:
    baseline, _ = records
    assert "UNRESOLVED_FUNDING" in baseline["unit-unresolved"] or "unresolved_funding" in baseline["unit-unresolved"]
    assert "PREFERRED_EQUITY" in baseline["unit-stack"] or "preferred_equity" in baseline["unit-stack"]
    assert "StructuredCapitalResult(analysis_scope=<ScopeKind.INVESTMENT" in baseline["investment-stack"]
    assert "PartnershipResult(" in baseline["partnership-stack"]
    fields = baseline["fields"]
    assert "'CapitalStructure': ['positions']" in fields
