"""Phase 6 Gate D6.3 -- architecture guardrails for project returns and IRR
status.

D6.3 is the first gate to change ``engine/returns.py`` since D4.5A, and it
touches the IRR procedure's source. The freeze on the IRR *algorithm* therefore
has to be stated as a structural claim, not left to byte-identity:

1. **Source regions.** Every byte of ``returns.py`` outside an enumerated D6.3
   surface is identical to b828956: DSCR, the Horner evaluation, the first
   nonzero index, the rate conversion and every Owner Return Metrics function.
2. **The solver is the same solver.** With each ``return (value, status)``
   read as ``return value``, ``_solve_x_star`` is AST-identical to b828956's --
   every evaluation, comparison, constant, bound and iteration. The sign
   rules' checks and loop are AST-identical too.
3. **One path.** ``calculate_irr`` is ``evaluate_irr``'s value; the return
   metrics call ``evaluate_irr`` and never a second solver.
4. **One decomposition.** The Equity Multiple and the project-return summary
   read the same sign split, whose expressions are the Equity Multiple's own.
5. **Narrow threading and contracts.** ``acquisition.py`` gained six keyword
   arguments; ``contracts.py`` gained ``IrrStatus`` and six appended fields on
   each result -- and nothing else, not even a premature D6.4+ field.
6. **The ledger.** D6.3 changed exactly four production files.

Every git query runs against a private copy of the index (protocol Section
11.2). Source text is compared CRLF-normalised to LF and nothing else.
"""

from __future__ import annotations

import ast
import copy
import difflib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _PROJECT_ROOT / "src"

#: ``main`` after D6.2, immediately before D6.3.
_D6_2_MERGE = "b828956"

_RETURNS = "src/anchor/engine/returns.py"
_ACQUISITION = "src/anchor/engine/acquisition.py"
_CONTRACTS = "src/anchor/engine/contracts.py"

_RETURNS_FAILURE = "engine/returns.py changed outside D6.3's authorized surface"
_CONTRACTS_FAILURE = "engine/contracts.py changed beyond D6.3's authorized additions"

_D6_3_FIELDS = (
    "net_additional_equity_requirement_by_year",
    "total_equity_invested",
    "total_cash_returned",
    "total_profit",
    "unlevered_irr_status",
    "levered_irr_status",
)
_D6_3_FIELD_LINES = [
    "    net_additional_equity_requirement_by_year: tuple[float, ...]",
    "    total_equity_invested: float",
    "    total_cash_returned: float",
    "    total_profit: float",
    "    unlevered_irr_status: IrrStatus",
    "    levered_irr_status: IrrStatus",
]


# =============================================================================
# Helpers
# =============================================================================


def _git_bytes(arguments: list[str]) -> bytes:
    index_path = subprocess.run(
        ["git", "rev-parse", "--git-path", "index"],
        capture_output=True,
        text=True,
        check=True,
        cwd=_PROJECT_ROOT,
    ).stdout.strip()
    with tempfile.TemporaryDirectory() as scratch:
        private_index = Path(scratch) / "index"
        shutil.copyfile(_PROJECT_ROOT / index_path, private_index)
        completed = subprocess.run(
            ["git", *arguments],
            capture_output=True,
            cwd=_PROJECT_ROOT,
            env={**os.environ, "GIT_INDEX_FILE": str(private_index)},
        )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return completed.stdout


def _files_changed_since(commit: str, repo_relative: str) -> list[str]:
    tracked = _git_bytes(["diff", "--name-only", commit, "--", repo_relative]).decode()
    untracked = _git_bytes(
        ["ls-files", "--others", "--exclude-standard", "--", repo_relative]
    ).decode()
    return sorted(
        {line.strip() for line in (*tracked.splitlines(), *untracked.splitlines()) if line.strip()}
    )


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def _baseline(path: str) -> str:
    return _lf(_git_bytes(["show", f"{_D6_2_MERGE}:{path}"]).decode("utf-8"))


def _current(path: str) -> str:
    return _lf((_PROJECT_ROOT / path).read_bytes().decode("utf-8"))


def _functions(source: str) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
    }


def _body_without_docstring(function: ast.FunctionDef) -> list[ast.stmt]:
    body = function.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _dump(statements: list[ast.stmt]) -> str:
    return ast.dump(ast.Module(body=statements, type_ignores=[]))


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _calls(node: ast.AST) -> list[ast.Call]:
    return [child for child in ast.walk(node) if isinstance(child, ast.Call)]


# =============================================================================
# 1. returns.py -- nothing outside the enumerated surface moved
# =============================================================================

#: Each D6.3 region as ``(baseline span, current span)``: the first and last
#: top-level key of the span on each side. Everything between them on one side
#: is collapsed to a single placeholder; everything outside every region must
#: match b828956 byte for byte.
_RETURNS_REGIONS = {
    "import": (("from .contracts", "from .contracts"), ("from .contracts", "from .contracts")),
    # The Equity Multiple, now reading the shared decomposition, plus the new
    # decomposition before it and the project-return section after it.
    "equity": (
        ("def calculate_equity_multiple", "def calculate_equity_multiple"),
        ("def _equity_cash_flow_totals", "def calculate_net_additional_equity_requirement_by_year"),
    ),
    "validity": (
        ("def _is_valid_irr_series", "def _is_valid_irr_series"),
        ("def _irr_validity_failure", "def _irr_validity_failure"),
    ),
    "solver": (("def _solve_x_star", "def _solve_x_star"), ("def _solve_x_star", "def _solve_x_star")),
    "irr": (("def calculate_irr", "def calculate_irr"), ("def evaluate_irr", "def calculate_irr")),
    "metrics": (
        ("def calculate_return_metrics", "def calculate_return_metrics"),
        ("def calculate_return_metrics", "def calculate_return_metrics"),
    ),
}


def _spans(source: str) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef):
            key = f"def {node.name}"
        elif isinstance(node, ast.ImportFrom):
            key = f"from {'.' * node.level}{node.module or ''}"
        else:
            continue
        assert key not in spans, f"{_RETURNS_FAILURE}: {key} appears twice"
        assert node.end_lineno is not None
        spans[key] = (node.lineno - 1, node.end_lineno)
    return spans


def _collapsed(source: str, side: int) -> str:
    lines = source.split("\n")
    spans = _spans(source)
    ranges = []
    for name, sides in _RETURNS_REGIONS.items():
        first_key, last_key = sides[side]
        assert first_key in spans and last_key in spans, (
            f"{_RETURNS_FAILURE}: region {name!r} is missing {first_key} or {last_key}"
        )
        start, stop = spans[first_key][0], spans[last_key][1]
        assert start < stop
        ranges.append((start, stop, name))
    for start, stop, name in sorted(ranges, reverse=True):
        lines[start:stop] = [f"<<{name}>>"]
    return "\n".join(lines)


def _assert_returns_changed_only_in_its_regions(baseline: str, current: str) -> None:
    expected, remainder = _collapsed(baseline, 0), _collapsed(current, 1)
    assert remainder == expected, (
        f"{_RETURNS_FAILURE}:\n"
        + "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                remainder.splitlines(keepends=True),
                _D6_2_MERGE,
                "current (regions collapsed)",
                n=1,
            )
        )
    )


def test_returns_changed_only_inside_the_authorized_d6_3_surface() -> None:
    _assert_returns_changed_only_in_its_regions(_baseline(_RETURNS), _current(_RETURNS))


_RETURNS_TAMPERS = [
    pytest.param(
        "        horner_value = horner_value * x + cash_flows[t]\n",
        "        horner_value = cash_flows[t] + horner_value * x\n",
        id="horner-evaluation",
    ),
    pytest.param(
        "    irr = 1.0 / x_star - 1.0\n", "    irr = (1.0 / x_star) - 1.0 + 0.0\n", id="rate-conversion"
    ),
    pytest.param(
        "            dscr_y = noi_y / ads_y\n", "            dscr_y = noi_y / ads_y * 1.0\n", id="dscr"
    ),
    pytest.param(
        "        if cash_flow != 0.0:\n", "        if cash_flow > 0.0 or cash_flow < 0.0:\n",
        id="first-nonzero-index",
    ),
    pytest.param(
        '    return ensure_finite("year_1_debt_yield", year_1_noi / loan_amount)\n',
        '    return ensure_finite("year_1_debt_yield", (year_1_noi / loan_amount))\n',
        id="debt-yield",
    ),
    pytest.param(
        "# Owner Return Metrics V3 Gate A2\n", "# Owner Return Metrics V3\n", id="banner-comment"
    ),
]


@pytest.mark.parametrize(("old", "new"), _RETURNS_TAMPERS)
def test_the_returns_guardrail_rejects_an_unauthorized_change(old: str, new: str) -> None:
    current = _current(_RETURNS)
    assert current.count(old) == 1, old

    with pytest.raises(AssertionError, match=_RETURNS_FAILURE):
        _assert_returns_changed_only_in_its_regions(
            _baseline(_RETURNS), current.replace(old, new)
        )


def test_the_returns_guardrail_accepts_crlf() -> None:
    current = _current(_RETURNS)
    _assert_returns_changed_only_in_its_regions(
        _baseline(_RETURNS), _lf(current.replace("\n", "\r\n"))
    )


# =============================================================================
# 2. The IRR algorithm is frozen -- proved on the AST
# =============================================================================


class _ValueOnlyReturns(ast.NodeTransformer):
    """Read ``return value, status`` as ``return value``."""

    def visit_Return(self, node: ast.Return) -> ast.Return:
        assert isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2, (
            "every solver exit returns (value, status)"
        )
        status = node.value.elts[1]
        assert (
            isinstance(status, ast.Attribute)
            and isinstance(status.value, ast.Name)
            and status.value.id == "IrrStatus"
        )
        return ast.Return(value=node.value.elts[0])


def test_the_solver_is_the_b828956_solver_with_named_exits() -> None:
    baseline = _functions(_baseline(_RETURNS))["_solve_x_star"]
    current = copy.deepcopy(_functions(_current(_RETURNS))["_solve_x_star"])

    stripped = _ValueOnlyReturns().visit(current)
    assert _dump(_body_without_docstring(stripped)) == _dump(_body_without_docstring(baseline))
    assert [arg.arg for arg in current.args.args] == [arg.arg for arg in baseline.args.args]


def test_each_solver_exit_names_the_right_status() -> None:
    solver = _functions(_current(_RETURNS))["_solve_x_star"]
    exits = [node for node in ast.walk(solver) if isinstance(node, ast.Return)]

    for exit_node in exits:
        value, status = exit_node.value.elts  # type: ignore[union-attr]
        member = status.attr  # type: ignore[attr-defined]
        if isinstance(value, ast.Constant) and value.value is None:
            assert member in ("NUMERICAL_FAILURE", "ROOT_OUTSIDE_SEARCH_DOMAIN")
        else:
            assert member == "DEFINED", ast.unparse(exit_node)

    # The bound exit is the one inside ``if x_high >= 1e12``, and only it.
    bound_exits = [
        node
        for node in ast.walk(solver)
        if isinstance(node, ast.If) and ast.unparse(node.test) == "x_high >= 1000000000000.0"
    ]
    assert len(bound_exits) == 1
    assert ast.unparse(bound_exits[0].body[0]) == (
        "return (None, IrrStatus.ROOT_OUTSIDE_SEARCH_DOMAIN)"
    )
    assert sum("ROOT_OUTSIDE_SEARCH_DOMAIN" in ast.unparse(e) for e in exits) == 1


def test_the_sign_rules_are_the_b828956_sign_rules() -> None:
    baseline = _body_without_docstring(_functions(_baseline(_RETURNS))["_is_valid_irr_series"])
    current = _body_without_docstring(_functions(_current(_RETURNS))["_irr_validity_failure"])

    # The first-nonzero check, in the same place, on the same test.
    assert isinstance(baseline[0], ast.If) and isinstance(current[0], ast.If)
    assert ast.dump(current[0].test) == ast.dump(baseline[0].test)
    assert ast.unparse(current[0].body[0]) == "return IrrStatus.FIRST_NONZERO_NOT_NEGATIVE"
    # The four accumulators and the sign loop, unchanged.
    assert _dump(current[1:6]) == _dump(baseline[1:6])
    # The validity condition itself, unchanged, now naming the rule it fails.
    assert isinstance(baseline[6], ast.Return) and isinstance(current[6], ast.If)
    assert ast.dump(current[6].test) == ast.dump(baseline[6].value)
    assert ast.unparse(current[6].body[0]) == "return None"
    assert [ast.unparse(statement) for statement in current[7:]] == [
        "if not has_positive:\n    return IrrStatus.NO_POSITIVE_CASH_FLOW",
        "return IrrStatus.MULTIPLE_SIGN_CHANGES",
    ]


def test_calculate_irr_is_evaluate_irr_s_value_and_the_only_path() -> None:
    functions = _functions(_current(_RETURNS))

    assert [ast.unparse(s) for s in _body_without_docstring(functions["calculate_irr"])] == [
        "irr, _ = evaluate_irr(cash_flows)",
        "return irr",
    ]
    evaluate_calls = [_callee(call) for call in _calls(functions["evaluate_irr"])]
    assert evaluate_calls.count("_solve_x_star") == 1
    assert evaluate_calls.count("_irr_validity_failure") == 1

    metrics_calls = [_callee(call) for call in _calls(functions["calculate_return_metrics"])]
    assert metrics_calls.count("evaluate_irr") == 2
    assert "calculate_irr" not in metrics_calls
    assert "_solve_x_star" not in metrics_calls

    # Nothing else in the tree reaches the solver or the sign rules.
    for path in sorted((_SRC_DIR / "anchor").rglob("*.py")):
        if path.name == "returns.py":
            continue
        text = path.read_text(encoding="utf-8")
        for private in ("_solve_x_star", "_irr_validity_failure", "_evaluate_horner"):
            assert private not in text, f"{path.name} reaches {private}"


# =============================================================================
# 3. One decomposition, read off the Equity Cash Flow alone
# =============================================================================


def test_the_equity_multiple_and_the_summary_share_one_decomposition() -> None:
    baseline = _functions(_baseline(_RETURNS))["calculate_equity_multiple"]
    functions = _functions(_current(_RETURNS))
    base_body = _body_without_docstring(baseline)
    totals_body = _body_without_docstring(functions["_equity_cash_flow_totals"])
    em_body = _body_without_docstring(functions["calculate_equity_multiple"])

    # The decomposition's two sums are the Equity Multiple's own two sums.
    assert _dump(totals_body[:2]) == _dump(base_body[:2])
    # The Equity Multiple reads them and is otherwise unchanged.
    assert ast.unparse(em_body[0]) == (
        "positive_total, negative_total = _equity_cash_flow_totals(levered_cash_flows)"
    )
    assert _dump(em_body[1:]) == _dump(base_body[2:])

    readers = sorted(
        name
        for name, function in functions.items()
        if "_equity_cash_flow_totals" in [_callee(call) for call in _calls(function)]
    )
    assert readers == ["calculate_equity_multiple", "calculate_project_return_totals"]


@pytest.mark.parametrize(
    "name",
    ["calculate_project_return_totals", "calculate_net_additional_equity_requirement_by_year"],
)
def test_the_summary_reads_the_equity_cash_flow_and_nothing_else(name: str) -> None:
    function = _functions(_current(_RETURNS))[name]

    assert [a.arg for a in function.args.kwonlyargs] == ["levered_cash_flows"]
    assert not function.args.args
    names = {n.id for n in ast.walk(function) if isinstance(n, ast.Name)}
    for forbidden in (
        "project_capital_by_year",
        "owner_expenses_by_year",
        "closing_project_capital",
        "tenant_improvements_by_year",
        "unlevered_cash_flows",
        "business_plan",
    ):
        assert forbidden not in names

    metrics = _functions(_current(_RETURNS))["calculate_return_metrics"]
    call = next(c for c in _calls(metrics) if _callee(c) == name)
    assert {k.arg: ast.unparse(k.value) for k in call.keywords} == {
        "levered_cash_flows": "levered_cash_flows"
    }


def test_net_additional_equity_excludes_t0() -> None:
    function = _functions(_current(_RETURNS))["calculate_net_additional_equity_requirement_by_year"]
    source = "\n".join(ast.unparse(s) for s in _body_without_docstring(function))

    assert "levered_cash_flows[1:]" in source
    assert "max(" not in source  # the branch is explicit, so -0.0 cannot leak


# =============================================================================
# 4. acquisition.py -- only the six threaded keywords
# =============================================================================


def test_acquisition_changed_only_by_threading_the_six_fields() -> None:
    baseline, current = _baseline(_ACQUISITION), _current(_ACQUISITION)
    base_functions, cur_functions = _functions(baseline), _functions(current)

    assert sorted(base_functions) == sorted(cur_functions)
    for name, function in base_functions.items():
        if name == "analyze_acquisition_from_operating_projection":
            continue
        assert ast.unparse(cur_functions[name]) == ast.unparse(function), name

    orchestrator = copy.deepcopy(cur_functions["analyze_acquisition_from_operating_projection"])
    results_call = next(c for c in _calls(orchestrator) if _callee(c) == "AcquisitionResults")
    threaded = {k.arg: ast.unparse(k.value) for k in results_call.keywords if k.arg in _D6_3_FIELDS}
    assert threaded == {field: f"return_metrics.{field}" for field in _D6_3_FIELDS}
    results_call.keywords = [k for k in results_call.keywords if k.arg not in _D6_3_FIELDS]
    assert ast.dump(orchestrator) == ast.dump(
        base_functions["analyze_acquisition_from_operating_projection"]
    )

    # Byte-level too: the only lines added are the threading, and none removed.
    diff = list(difflib.unified_diff(baseline.splitlines(), current.splitlines(), n=0, lineterm=""))
    removed = [line for line in diff if line.startswith("-") and not line.startswith("---")]
    assert removed == []


# =============================================================================
# 5. contracts.py -- IrrStatus and the appended fields, nothing else
# =============================================================================


def _class_node(source: str, name: str) -> ast.ClassDef:
    matches = [
        node for node in ast.parse(source).body if isinstance(node, ast.ClassDef) and node.name == name
    ]
    assert len(matches) == 1, f"{_CONTRACTS_FAILURE}: expected one {name}"
    return matches[0]


def _with_baseline_class(source: str, baseline: str, name: str, appended: list[str]) -> str:
    """``source`` with class ``name`` restored to the baseline text, after
    proving its docstring was only extended and exactly ``appended`` field
    lines follow its existing fields."""

    lines, base_lines = source.split("\n"), baseline.split("\n")
    node, base_node = _class_node(source, name), _class_node(baseline, name)
    doc, base_doc = node.body[0], base_node.body[0]
    assert doc.end_lineno is not None and base_doc.end_lineno is not None
    assert node.end_lineno is not None and base_node.end_lineno is not None

    first, base_first = node.lineno - 1, base_node.lineno - 1
    first -= len(node.decorator_list)
    base_first -= len(base_node.decorator_list)
    header = lines[first : doc.lineno - 1]
    assert header == base_lines[base_first : base_doc.lineno - 1], (
        f"{_CONTRACTS_FAILURE}: {name}'s header changed"
    )
    current_doc = ast.get_docstring(node, clean=False) or ""
    base_docstring = ast.get_docstring(base_node, clean=False) or ""
    assert current_doc.startswith(base_docstring.rstrip()), (
        f"{_CONTRACTS_FAILURE}: {name}'s existing docstring changed"
    )
    assert lines[doc.end_lineno : node.end_lineno] == (
        base_lines[base_doc.end_lineno : base_node.end_lineno] + appended
    ), f"{_CONTRACTS_FAILURE}: {name}'s fields changed by more than the D6.3 additions"
    return "\n".join(
        lines[:first] + base_lines[base_first : base_node.end_lineno] + lines[node.end_lineno :]
    )


def _without_irr_status(source: str) -> str:
    lines = source.split("\n")
    assert lines.count("from enum import StrEnum") == 1, f"{_CONTRACTS_FAILURE}: the enum import"
    lines.remove("from enum import StrEnum")
    source = "\n".join(lines)
    node = _class_node(source, "IrrStatus")
    assert not node.decorator_list and node.end_lineno is not None
    lines = source.split("\n")
    assert lines[node.end_lineno : node.end_lineno + 2] == ["", ""], (
        f"{_CONTRACTS_FAILURE}: IrrStatus must be followed by its two blank separator lines"
    )
    removed = ast.parse("\n".join(lines[node.lineno - 1 : node.end_lineno + 2])).body
    assert [(type(s), getattr(s, "name", None)) for s in removed] == [(ast.ClassDef, "IrrStatus")]
    return "\n".join(lines[: node.lineno - 1] + lines[node.end_lineno + 2 :])


def _assert_contracts_changed_only_by_d6_3(baseline: str, current: str) -> None:
    remainder = _without_irr_status(current)
    remainder = _with_baseline_class(remainder, baseline, "ReturnMetrics", _D6_3_FIELD_LINES)
    remainder = _with_baseline_class(remainder, baseline, "AcquisitionResults", _D6_3_FIELD_LINES)
    assert remainder == baseline, (
        f"{_CONTRACTS_FAILURE}:\n"
        + "".join(
            difflib.unified_diff(
                baseline.splitlines(keepends=True), remainder.splitlines(keepends=True), n=1
            )
        )
    )


def test_contracts_changed_only_by_irr_status_and_the_appended_fields() -> None:
    _assert_contracts_changed_only_by_d6_3(_baseline(_CONTRACTS), _current(_CONTRACTS))


_CONTRACTS_TAMPERS = [
    pytest.param(
        "    levered_irr_status: IrrStatus\n\n\n@dataclass(frozen=True, slots=True, kw_only=True)\n"
        "class DetailedAcquisitionResults",
        "    levered_irr_status: IrrStatus\n    peak_funding_requirement: float\n\n\n"
        "@dataclass(frozen=True, slots=True, kw_only=True)\nclass DetailedAcquisitionResults",
        id="premature-d6-4-result-field",
    ),
    pytest.param(
        "    levered_irr_status: IrrStatus\n\n\n@dataclass(frozen=True, slots=True, kw_only=True)\n"
        "class OwnerReturnMetrics",
        "    levered_irr_status: IrrStatus\n    business_plan_fingerprint: str\n\n\n"
        "@dataclass(frozen=True, slots=True, kw_only=True)\nclass OwnerReturnMetrics",
        id="premature-return-metrics-field",
    ),
    pytest.param(
        "    total_profit: float\n    unlevered_irr_status: IrrStatus\n    levered_irr_status: IrrStatus\n\n\n"
        "@dataclass(frozen=True, slots=True, kw_only=True)\nclass DetailedAcquisitionResults",
        "    total_profit: float = 0.0\n    unlevered_irr_status: IrrStatus\n    levered_irr_status: IrrStatus\n\n\n"
        "@dataclass(frozen=True, slots=True, kw_only=True)\nclass DetailedAcquisitionResults",
        id="defaulted-field",
    ),
    pytest.param(
        "    equity_multiple: float | None\n    unlevered_irr: float | None\n",
        "    equity_multiple: float\n    unlevered_irr: float | None\n",
        id="existing-return-metrics-annotation",
    ),
    pytest.param(
        "    replace it.\n", "    replaces it.\n", id="existing-return-metrics-docstring"
    ),
    pytest.param(
        "from math import isfinite\n", "from math import isfinite, isnan\n", id="unrelated-import"
    ),
]


@pytest.mark.parametrize(("old", "new"), _CONTRACTS_TAMPERS)
def test_the_contracts_guardrail_rejects_an_unauthorized_change(old: str, new: str) -> None:
    current = _current(_CONTRACTS)
    assert current.count(old) == 1, old

    with pytest.raises(AssertionError, match=_CONTRACTS_FAILURE):
        _assert_contracts_changed_only_by_d6_3(_baseline(_CONTRACTS), current.replace(old, new))


def test_irr_status_members_are_exactly_the_solver_outcomes() -> None:
    node = _class_node(_current(_CONTRACTS), "IrrStatus")
    members = [
        (target.id, statement.value.value)
        for statement in node.body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name) and isinstance(statement.value, ast.Constant)
    ]
    assert members == [
        ("DEFINED", "defined"),
        ("NO_NONZERO_CASH_FLOW", "no_nonzero_cash_flow"),
        ("FIRST_NONZERO_NOT_NEGATIVE", "first_nonzero_not_negative"),
        ("NO_POSITIVE_CASH_FLOW", "no_positive_cash_flow"),
        ("MULTIPLE_SIGN_CHANGES", "multiple_sign_changes"),
        ("ROOT_OUTSIDE_SEARCH_DOMAIN", "root_outside_search_domain"),
        ("NUMERICAL_FAILURE", "numerical_failure"),
    ]


# =============================================================================
# 6. The ledger -- D6.3 changed exactly its authorized production files
# =============================================================================

_D6_3_PRODUCTION_FILES = frozenset(
    {
        "src/anchor/engine/returns.py",
        "src/anchor/engine/contracts.py",
        "src/anchor/engine/acquisition.py",
        "src/anchor/ai/presentation.py",
        # D6.3 closeout: the one authorised decoder branch that rehydrates
        # IrrStatus in stored snapshots (see test 7 below).
        "src/anchor/deals/store.py",
    }
)


#: ``main`` after D6.3 -- the end of D6.3's committed range.
_D6_3_MERGE = "ba804ca"


def _files_changed_between(start: str, end: str, repo_relative: str) -> list[str]:
    changed = _git_bytes(["diff", "--name-only", start, end, "--", repo_relative]).decode()
    return sorted({line.strip() for line in changed.splitlines() if line.strip()})


def test_d6_3_changed_exactly_its_authorized_production_files() -> None:
    """No debt, NOI, operating projection, leasing, Business Plan resolver,
    sensitivity, break-even, API, persistence, fingerprint, prompt or frontend
    file moved since D6.2."""

    # Pinned at D6.4 to D6.3's own committed range, b828956..ba804ca, so the
    # ledger keeps proving exactly what D6.3 changed however later gates move
    # the tree (``tests/test_d6_4_business_plan_threading_architecture.py``
    # keeps D6.4's ledger).
    changed = set(_files_changed_between(_D6_2_MERGE, _D6_3_MERGE, "src")) | set(
        _files_changed_between(_D6_2_MERGE, _D6_3_MERGE, "web")
    )
    assert changed == _D6_3_PRODUCTION_FILES, (
        f"unexpected: {sorted(changed - _D6_3_PRODUCTION_FILES)}; "
        f"missing: {sorted(_D6_3_PRODUCTION_FILES - changed)}"
    )


def test_the_d6_3_ledger_detects_a_real_difference() -> None:
    # Pinned at D6.5 to D6.3's committed range: D6.5 changes the persistence
    # package on purpose (``tests/test_d6_5_business_plan_persistence_architecture.py``).
    changed = _files_changed_between(_D6_2_MERGE, _D6_3_MERGE, "src/anchor/deals")
    assert changed == ["src/anchor/deals/store.py"]
    _assert_engine_ledger()


# =============================================================================
# 7. deals/store.py -- exactly the IrrStatus rehydration branch (D6.3 closeout)
# =============================================================================

_STORE = "src/anchor/deals/store.py"
_STORE_FAILURE = "deals/store.py changed beyond the authorized IrrStatus rehydration"


def _store_spans(source: str) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == "_coerce_snapshot_value":
            key = "def _coerce_snapshot_value"
        elif isinstance(node, ast.ImportFrom) and node.level == 2 and node.module == "engine.contracts":
            key = "from ..engine.contracts"
        else:
            continue
        assert key not in spans, f"{_STORE_FAILURE}: {key} appears twice"
        assert node.end_lineno is not None
        spans[key] = (node.lineno - 1, node.end_lineno)
    assert set(spans) == {"def _coerce_snapshot_value", "from ..engine.contracts"}, (
        f"{_STORE_FAILURE}: a region is missing"
    )
    return spans


def _store_collapsed(source: str) -> str:
    lines = source.split("\n")
    for key, (start, stop) in sorted(_store_spans(source).items(), key=lambda i: -i[1][0]):
        lines[start:stop] = [f"<<{key}>>"]
    return "\n".join(lines)


def _assert_store_changed_only_by_irr_status_rehydration(baseline: str, current: str) -> None:
    """Everything outside two regions is b828956's text; inside them, the
    engine-contracts import gained exactly ``IrrStatus`` and
    ``_coerce_snapshot_value`` gained exactly one ``if hint is IrrStatus``
    statement -- its other statements unchanged, in order."""

    assert _store_collapsed(current) == _store_collapsed(baseline), (
        f"{_STORE_FAILURE}: text outside the decoder surface changed"
    )

    def regions(source: str) -> tuple[ast.ImportFrom, ast.FunctionDef]:
        tree = ast.parse(source)
        imports = [
            n for n in tree.body
            if isinstance(n, ast.ImportFrom) and n.level == 2 and n.module == "engine.contracts"
        ]
        coerce = [
            n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_coerce_snapshot_value"
        ]
        return imports[0], coerce[0]

    base_import, base_coerce = regions(baseline)
    cur_import, cur_coerce = regions(current)
    assert sorted(a.name for a in cur_import.names) == sorted(
        [a.name for a in base_import.names] + ["IrrStatus"]
    ), f"{_STORE_FAILURE}: the engine-contracts import"

    base_body = _body_without_docstring(base_coerce)
    cur_body = _body_without_docstring(cur_coerce)
    inserted = [
        s for s in cur_body if isinstance(s, ast.If) and ast.unparse(s.test) == "hint is IrrStatus"
    ]
    assert len(inserted) == 1, f"{_STORE_FAILURE}: expected one IrrStatus branch"
    remaining = [s for s in cur_body if s is not inserted[0]]
    assert _dump(remaining) == _dump(base_body), (
        f"{_STORE_FAILURE}: _coerce_snapshot_value changed beyond the IrrStatus branch"
    )
    # The branch rehydrates strictly -- exactly the member, or
    # SnapshotValidationError -- pinned structurally, so a default, a fallback
    # member or a pass-through cannot hide inside it.
    branch = inserted[0]
    assert not branch.orelse, f"{_STORE_FAILURE}: the IrrStatus branch has an else"
    assert len(branch.body) == 1 and isinstance(branch.body[0], ast.Try), (
        f"{_STORE_FAILURE}: the IrrStatus branch is not a single try"
    )
    attempt = branch.body[0]
    assert [ast.unparse(s) for s in attempt.body] == ["return IrrStatus(value)"], (
        f"{_STORE_FAILURE}: the IrrStatus branch returns something other than the member"
    )
    assert not attempt.orelse and not attempt.finalbody
    assert len(attempt.handlers) == 1, f"{_STORE_FAILURE}: one handler expected"
    handler = attempt.handlers[0]
    assert handler.type is not None and ast.unparse(handler.type) == "(ValueError, TypeError)"
    assert len(handler.body) == 1 and isinstance(handler.body[0], ast.Raise), (
        f"{_STORE_FAILURE}: an unknown token must be refused"
    )
    raised = handler.body[0].exc
    assert isinstance(raised, ast.Call) and _callee(raised) == "SnapshotValidationError", (
        f"{_STORE_FAILURE}: an unknown token must raise SnapshotValidationError"
    )


def _store_at_d6_3_merge() -> str:
    """``deals/store.py`` as D6.3 left it.

    Pinned at D6.5, which changes the store on purpose to persist the Business
    Plan. This claim keeps proving exactly what D6.3 changed; the D6.5 guard
    separately proves the IrrStatus branch is still byte-identical today."""

    return _lf(_git_bytes(["show", f"{_D6_3_MERGE}:{_STORE}"]).decode("utf-8"))


def test_store_changed_only_by_the_irr_status_rehydration_branch() -> None:
    _assert_store_changed_only_by_irr_status_rehydration(
        _baseline(_STORE), _store_at_d6_3_merge()
    )


_STORE_TAMPERS = [
    pytest.param(
        "_ANALYSIS_SNAPSHOT_SCHEMA_VERSION = 1\n",
        "_ANALYSIS_SNAPSHOT_SCHEMA_VERSION = 2\n",
        id="snapshot-schema-version",
    ),
    pytest.param(
        "            return IrrStatus(value)\n",
        "            return IrrStatus(value) if value else IrrStatus.DEFINED\n",
        id="defaulting-branch",
    ),
    pytest.param(
        "    if get_origin(hint) is tuple:\n",
        "    if hint is str:\n        return str(value)\n    if get_origin(hint) is tuple:\n",
        id="second-coercion-branch",
    ),
    pytest.param(
        "    IrrStatus,\n    OperatingProjection,\n",
        "    IrrStatus,\n    OperatingProjection,\n    ReturnMetrics,\n",
        id="wider-engine-import",
    ),
]


@pytest.mark.parametrize(("old", "new"), _STORE_TAMPERS)
def test_the_store_guardrail_rejects_an_unauthorized_change(old: str, new: str) -> None:
    current = _store_at_d6_3_merge()
    assert current.count(old) == 1, old

    with pytest.raises(AssertionError, match=_STORE_FAILURE):
        _assert_store_changed_only_by_irr_status_rehydration(
            _baseline(_STORE), current.replace(old, new)
        )


def _assert_engine_ledger() -> None:
    assert _files_changed_since(_D6_2_MERGE, "src/anchor/engine") == [
        "src/anchor/engine/acquisition.py",
        "src/anchor/engine/contracts.py",
        "src/anchor/engine/returns.py",
    ]
