"""Phase 7 Gate P7.1 -- Scenario architecture guards and the Phase 7 ledger.

``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 3
(P-1, P-2, P-6), 7.2 and 7.3, plus the P7.1 gate (Part AC). These guards
inspect ``src/anchor/analysis/scenario.py`` structurally, with no reliance on
its comments, and they hold:

1. no financial formula: the ratified operations are the only arithmetic;
2. nothing in production imports the Scenario layer;
3. resolution produces the existing input contracts and runs the existing D6
   entry points;
4. purchase price, or any other decision field, can never be written;
5. the Business Plan is carried, never modified;
6. no case name and no scenario name has meaning;
7. the target registry is an explicit, finite literal;
8. every target states its own operation whitelist;
9. no reflection and no path patching;
10. **the Phase 7 production ledger**, which is P7.1's first required action.
    P7.0 changed no production file, so nothing held Phase 7 production
    changes until this ledger.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import subprocess
from pathlib import Path

from anchor.analysis import scenario as scenario_module
from anchor.analysis.scenario import SCENARIO_TARGET_REGISTRY, ScenarioTarget, ScenarioTargetSpec
from anchor.contracts import OperatingMode

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"
_ANCHOR = _SRC / "anchor"
_SCENARIO = _ANCHOR / "analysis" / "scenario.py"


def _source() -> str:
    return _SCENARIO.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_source())


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _enclosing_function_of(tree: ast.Module) -> dict[ast.AST, str]:
    owner: dict[ast.AST, str] = {}
    for function in _functions(tree).values():
        for node in ast.walk(function):
            owner[node] = function.name
    return owner


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ast.unparse(func)


def _docstrings(tree: ast.Module) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


# =============================================================================
# 1. No financial formula
# =============================================================================

_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow, ast.Mod, ast.MatMult)


def _arithmetic_sites(tree: ast.Module) -> list[tuple[str, str]]:
    owner = _enclosing_function_of(tree)
    sites: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and isinstance(node.op, _ARITHMETIC):
            sites.append((owner.get(node, "<module>"), type(node.op).__name__))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            sites.append((owner.get(node, "<module>"), "USub"))
    return sorted(sites)


def test_the_only_arithmetic_is_the_ratified_add_and_scale() -> None:
    """``SET`` assigns and ``CAP_AT`` is ``min``. The scenario layer computes
    no NOI, debt service, value or return, because it has no arithmetic in
    which to do so."""

    assert _arithmetic_sites(_tree()) == [("_apply_operation", "Add"), ("_apply_operation", "Mult")]


def test_min_is_called_only_by_cap_at_and_no_other_numeric_builtin_is_called() -> None:
    tree = _tree()
    owner = _enclosing_function_of(tree)
    numeric = {"min", "max", "sum", "round", "abs", "pow", "divmod", "fsum", "prod", "sqrt", "exp", "log"}
    calls = sorted(
        (owner.get(node, "<module>"), _callee(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee(node) in numeric
    )
    assert calls == [("_apply_operation", "min")]


def test_the_arithmetic_guard_detects_a_smuggled_formula() -> None:
    mutant = _source().replace(
        "    return float(resolved)\n",
        "    return float(resolved)\n\n\ndef _noi(rent, expenses):\n    return rent - expenses\n",
        1,
    )
    assert mutant != _source()
    assert ("_noi", "Sub") in _arithmetic_sites(ast.parse(mutant))


# =============================================================================
# 2. Import boundaries
# =============================================================================


def _absolute_imports(path: Path) -> dict[str, set[str]]:
    package = path.relative_to(_SRC).parts[:-1]
    found: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.setdefault(alias.name, set()).add("*")
        elif isinstance(node, ast.ImportFrom):
            base = list(package[: len(package) - node.level + 1]) if node.level else []
            module = ".".join([*base, *(node.module.split(".") if node.module else [])])
            found.setdefault(module, set()).update(alias.name for alias in node.names)
    return found


def test_the_scenario_module_imports_exactly_these_names() -> None:
    """Only contracts, validators and the three D6 entry points; never a
    builder, the bridge, or an engine calculation module."""

    assert _absolute_imports(_SCENARIO) == {
        "__future__": {"annotations"},
        "collections.abc": {"Iterable", "Mapping"},
        "dataclasses": {"asdict", "dataclass", "replace"},
        "enum": {"StrEnum"},
        "math": {"isfinite"},
        "types": {"MappingProxyType"},
        "anchor.business_plan": {"BusinessPlan"},
        "anchor.contracts": {
            "AcquisitionInputs", "AcquisitionTerms", "DetailedOperatingInputs", "OperatingMode",
        },
        "anchor.engine.contracts": {"AcquisitionResults", "DetailedAcquisitionResults"},
        "anchor.leasing": {
            "Lease", "LeaseLevelOperatingInputs", "LeaseLevelPropertyInputs", "LeaseValidationIssue",
            "MarketLeasingAssumptions", "Suite", "validate_lease_level_inputs",
            "validate_lease_level_operating_inputs",
        },
        "anchor.validation": {
            "InputValidationError", "validate_acquisition_inputs", "validate_acquisition_terms",
            "validate_detailed_operating_inputs",
        },
        "anchor.analysis.business_plan_analysis": {
            "analyze_detailed_acquisition_with_business_plan",
            "analyze_lease_level_acquisition_with_business_plan",
            "analyze_quick_acquisition_with_business_plan",
        },
        "anchor.analysis.contracts": {"LeaseLevelAcquisitionResults"},
    }


def _names_scenario(path: Path) -> bool:
    for module, names in _absolute_imports(path).items():
        if module == "anchor.analysis.scenario" or module.startswith("anchor.analysis.scenario."):
            return True
        if module == "anchor.analysis" and "scenario" in names:
            return True
    return False


def test_no_production_module_imports_the_scenario_layer() -> None:
    """The engine, the leasing layer, sensitivity and the AI never learn a
    scenario exists (P-2).

    **Widened at P7.2 -- by exactly four named files**, when persistence and
    the API arrive: the persisted-Scenario contract names ``ScenarioDefinition``
    (``deals/contracts.py``); the store validates Scenarios with the P7.1
    validator (``deals/store.py``); the variant service resolves them with the
    P7.1 resolvers (``deals/variants.py``); and the API parses a request into
    the P7.1 contract and reports the P7.1 issues (``api.py``). None of them
    resolves, validates or computes anything itself
    (``tests/test_p7_2_investment_scenario_architecture.py``)."""

    importers = sorted(
        path.relative_to(_SRC).as_posix()
        for path in _ANCHOR.rglob("*.py")
        if path != _SCENARIO and _names_scenario(path)
    )
    # **Widened at P7.4 -- by exactly one named file.** The Strategy engine
    # applies an operating outcome through the P7.1 per-target resolvers with
    # SET, then runs the P7.1 resolver on the Strategy-resolved contracts. It
    # restates no target, operation or accessor
    # (``tests/test_p7_4_strategy_architecture.py``).
    assert importers == [
        "anchor/analysis/strategy.py",
        "anchor/api.py",
        "anchor/deals/contracts.py",
        "anchor/deals/store.py",
        "anchor/deals/variants.py",
    ]


_SCENARIO_NAMES = (
    "ScenarioDefinition", "ScenarioOverride", "ScenarioOperation", "ScenarioTarget",
    "ScenarioTargetSpec", "ScenarioIssue", "ScenarioValidationError", "SCENARIO_TARGET_REGISTRY",
)


def test_no_other_production_file_defines_or_names_a_scenario_contract() -> None:
    """Widened at P7.2 by exactly the four files that import the Scenario
    layer (see above), and at P7.4 by the Strategy engine. None of them
    *defines* a scenario contract: the P7.2 and P7.4 guards prove they define
    no class of these names."""

    offenders = sorted(
        path.relative_to(_SRC).as_posix()
        for path in _ANCHOR.rglob("*.py")
        if path != _SCENARIO
        and any(re.search(rf"\b{name}\b", path.read_text(encoding="utf-8")) for name in _SCENARIO_NAMES)
    )
    assert offenders == [
        "anchor/analysis/strategy.py",
        "anchor/api.py",
        "anchor/deals/contracts.py",
        "anchor/deals/store.py",
        "anchor/deals/variants.py",
    ]


# =============================================================================
# 3. Existing contracts in, existing contracts out, existing entry points run
# =============================================================================

_EXPECTED_CLASSES = {
    "ScenarioOperation", "ScenarioTarget", "ScenarioTargetSpec", "ScenarioOverride",
    "ScenarioDefinition", "ScenarioIssueStage", "ScenarioIssueCode", "ScenarioIssue",
    "ScenarioValidationError", "ResolvedQuickInputs", "ResolvedDetailedInputs",
    "ResolvedLeaseLevelInputs",
}

_RESOLVED_FIELDS = {
    "ResolvedQuickInputs": {"inputs": "AcquisitionInputs", "business_plan": "BusinessPlan"},
    "ResolvedDetailedInputs": {
        "terms": "AcquisitionTerms",
        "detailed_operating_inputs": "DetailedOperatingInputs",
        "business_plan": "BusinessPlan",
    },
    "ResolvedLeaseLevelInputs": {
        "terms": "AcquisitionTerms",
        "property_inputs": "LeaseLevelPropertyInputs",
        "suites": "tuple[Suite, ...]",
        "leases": "tuple[Lease, ...]",
        "market_leasing": "MarketLeasingAssumptions",
        "operating_inputs": "LeaseLevelOperatingInputs",
        "business_plan": "BusinessPlan",
    },
}


def test_the_module_defines_no_parallel_financial_contract() -> None:
    tree = _tree()
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    assert set(classes) == _EXPECTED_CLASSES
    for name, fields in _RESOLVED_FIELDS.items():
        annotations = {
            statement.target.id: ast.unparse(statement.annotation)
            for statement in classes[name].body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        }
        assert annotations == fields, name


def test_each_analysis_wrapper_resolves_once_then_calls_its_existing_entry_point() -> None:
    functions = _functions(_tree())
    for mode, entry in (
        ("quick", "analyze_quick_acquisition_with_business_plan"),
        ("detailed", "analyze_detailed_acquisition_with_business_plan"),
        ("lease_level", "analyze_lease_level_acquisition_with_business_plan"),
    ):
        wrapper = functions[f"analyze_{mode}_acquisition_with_scenario"]
        calls = [_callee(node) for node in ast.walk(wrapper) if isinstance(node, ast.Call)]
        assert sorted(calls) == sorted([f"resolve_{mode}_scenario", entry])
        entry_call = next(n for n in ast.walk(wrapper) if isinstance(n, ast.Call) and _callee(n) == entry)
        arguments = [ast.unparse(a) for a in entry_call.args] + [
            f"{k.arg}={ast.unparse(k.value)}" for k in entry_call.keywords
        ]
        assert all(argument.split("=")[-1].startswith("resolved.") for argument in arguments)


def test_only_the_d6_entry_points_are_called_from_the_analysis_layer() -> None:
    called = {_callee(node) for node in ast.walk(_tree()) if isinstance(node, ast.Call)}
    assert not {c for c in called if c.startswith("analyze_") and not c.endswith(("_with_business_plan", "_with_scenario"))}
    assert not {c for c in called if c.startswith(("calculate_", "build_", "aggregate_", "evaluate_"))}


# =============================================================================
# 4 / 5. What resolution may write -- never a decision, never the plan
# =============================================================================

_WRITABLE_FIELDS = {
    # the target fields themselves
    "exit_cap_rate", "interest_rate", "ltv", "noi_growth", "revenue_growth",
    "vacancy_credit_loss_pct", "expense_growth", "market_rent_psf", "renewal_probability",
    "recoverable_expense_ratio",
    # the market-rent reach into a suite's full override record
    "market_leasing_override",
    # the resolved bundle's contract slots
    "terms", "detailed_operating_inputs", "market_leasing", "suites", "operating_inputs",
}


def _replace_calls(tree: ast.Module) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _callee(node) == "replace"]


def test_replace_is_only_ever_called_with_literal_approved_field_keywords() -> None:
    calls = _replace_calls(_tree())
    assert len(calls) >= 17
    for call in calls:
        assert len(call.args) == 1, ast.unparse(call)
        keywords = [keyword.arg for keyword in call.keywords]
        assert None not in keywords, f"**-unpacked replace: {ast.unparse(call)}"
        assert set(keywords) <= _WRITABLE_FIELDS, ast.unparse(call)


def test_purchase_price_is_unreachable_as_a_target_and_as_a_write() -> None:
    tree = _tree()
    assert "purchase_price" not in {t.value for t in ScenarioTarget}
    assert "PURCHASE_PRICE" not in ScenarioTarget.__members__
    written = {kw.arg for call in _replace_calls(tree) for kw in call.keywords}
    read = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for decision in ("purchase_price", "hold_period", "amortization", "io_period",
                     "acquisition_cost_pct", "financing_fee_pct", "disposition_cost_pct",
                     "annual_capex_reserve", "business_plan"):
        assert decision not in written
    assert "purchase_price" not in read


def test_the_business_plan_is_named_carried_and_never_opened() -> None:
    tree = _tree()
    assert _absolute_imports(_SCENARIO)["anchor.business_plan"] == {"BusinessPlan"}
    # The plan-specific item fields. (``category`` is omitted: the module reads
    # ``InputIssue.category``, the validator's issue category, which is not a
    # plan field.)
    plan_item_fields = {
        "capital_items", "owner_expense_items", "item_id", "month", "amount",
        "annual_amount", "first_year", "last_year",
    }
    assert not plan_item_fields & {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for call in ast.walk(tree):
        if isinstance(call, ast.Call):
            for keyword in call.keywords:
                if keyword.arg == "business_plan":
                    assert ast.unparse(keyword.value) in {"business_plan", "resolved.business_plan"}
    assert not {c for c in (_callee(n) for n in ast.walk(tree) if isinstance(n, ast.Call))
                if c in {"resolve_business_plan", "validate_business_plan", "CapitalPlanItem", "OwnerExpenseItem"}}


# =============================================================================
# 6. No case names; scenario naming carries no meaning
# =============================================================================


def test_no_case_identifier_and_no_meaningful_scenario_name() -> None:
    import test_p7_0_decision_architecture as p7_0

    source = _source()
    assert p7_0._case_identifiers_in(source) == []
    tree = _tree()
    docstrings = _docstrings(tree)
    reserved = {"base", "downside", "upside", "recession", "stress", "bull", "bear", "worst", "best"}
    literals = {
        node.value.strip().lower()
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
    }
    assert not literals & reserved


def test_scenario_identity_and_naming_are_read_only_by_stage_one_header_validation() -> None:
    tree = _tree()
    owner = _enclosing_function_of(tree)
    readers = {
        owner.get(node, "<module>")
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"scenario_id", "name", "description"}
    }
    assert readers == {"_header_issues"}


# =============================================================================
# 7 / 8. The registry is an explicit, finite literal with explicit whitelists
# =============================================================================


def _registry_literal(tree: ast.Module) -> ast.Dict:
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and ast.unparse(node.target) == "SCENARIO_TARGET_REGISTRY":
            assert isinstance(node.value, ast.Call) and _callee(node.value) == "MappingProxyType"
            (literal,) = node.value.args
            assert isinstance(literal, ast.Dict)
            return literal
    raise AssertionError("SCENARIO_TARGET_REGISTRY is not a module-level literal")


def test_the_target_enum_is_a_finite_list_of_literal_members() -> None:
    tree = _tree()
    (target_class,) = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ScenarioTarget"]
    members = [s for s in target_class.body if isinstance(s, ast.Assign)]
    assert len(members) == len(ScenarioTarget) == 10
    for member in members:
        (name,) = member.targets
        assert isinstance(member.value, ast.Constant) and isinstance(member.value.value, str)
        assert member.value.value == ast.unparse(name).lower()


def test_the_registry_literal_names_every_target_once_with_its_own_whitelist() -> None:
    literal = _registry_literal(_tree())
    keys = [ast.unparse(key) for key in literal.keys if key is not None]
    assert keys == [f"ScenarioTarget.{member}" for member in ScenarioTarget.__members__]
    assert None not in literal.keys  # no ** merge of another mapping
    for key, value in zip(literal.keys, literal.values, strict=True):
        assert isinstance(value, ast.Call) and _callee(value) == "ScenarioTargetSpec"
        keywords = {k.arg: k.value for k in value.keywords}
        assert set(keywords) == {"target", "allowed_operations", "owner_fields", "units"}
        assert ast.unparse(keywords["target"]) == ast.unparse(key)
        whitelist = keywords["allowed_operations"]
        assert isinstance(whitelist, ast.Call) and _callee(whitelist) == "frozenset"
        (members,) = whitelist.args
        assert isinstance(members, ast.Set)
        assert all(ast.unparse(m).startswith("ScenarioOperation.") for m in members.elts)


def test_no_target_spec_field_has_a_default() -> None:
    for field in dataclasses.fields(ScenarioTargetSpec):
        assert field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING


def _match_targets(function: ast.FunctionDef) -> tuple[set[str], bool]:
    (match,) = [n for n in ast.walk(function) if isinstance(n, ast.Match)]
    targets: set[str] = set()
    has_wildcard_raise = False
    for case in match.cases:
        patterns = case.pattern.patterns if isinstance(case.pattern, ast.MatchOr) else [case.pattern]
        for pattern in patterns:
            if isinstance(pattern, ast.MatchValue):
                targets.add(ast.unparse(pattern.value).removeprefix("ScenarioTarget."))
            elif isinstance(pattern, ast.MatchAs) and pattern.pattern is None:
                has_wildcard_raise = isinstance(case.body[-1], ast.Raise)
    return targets, has_wildcard_raise


def test_each_mode_resolver_covers_exactly_the_targets_the_registry_gives_that_mode() -> None:
    functions = _functions(_tree())
    terms, terms_closed = _match_targets(functions["_resolve_terms_target"])
    assert terms_closed and terms == {"EXIT_CAP_RATE", "INTEREST_RATE", "LTV"}
    for mode, name in (
        (OperatingMode.QUICK, "_resolve_quick_target"),
        (OperatingMode.DETAILED, "_resolve_detailed_target"),
        (OperatingMode.LEASE_LEVEL, "_resolve_lease_level_target"),
    ):
        covered, closed = _match_targets(functions[name])
        assert closed, f"{name} must fail closed on an unmatched target"
        expected = {t.name for t, spec in SCENARIO_TARGET_REGISTRY.items() if mode in spec.modes}
        assert covered == expected, name


def test_the_scenario_layer_names_modes_as_data_and_never_dispatches_on_one() -> None:
    """The D4.5B G32 / D5.1A concern is an implicit-else mode branch routing
    one mode's inputs into another mode's economics. Here an ``OperatingMode``
    member appears only as a registry key or as a resolver's constant argument.
    The only comparison on a mode is membership in a target's own mode set,
    which refuses and never routes. Every ``match`` is on an operation or a
    target, never on a mode."""

    tree = _tree()
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    member_sites = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "OperatingMode":
            member_sites += 1
            parent = parents[node]
            as_registry_key = isinstance(parent, ast.Dict) and node in parent.keys
            as_constant_argument = (
                isinstance(parent, ast.Call)
                and _callee(parent) in {"_require_resolvable", "_no_resolver"}
                and node in parent.args
            )
            assert as_registry_key or as_constant_argument, ast.unparse(parent)
        if isinstance(node, ast.Match):
            assert ast.unparse(node.subject) in {"operation", "override.target"}
        if isinstance(node, ast.Compare) and any(
            "mode" in ast.unparse(side) for side in (node.left, *node.comparators)
        ):
            assert all(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops), ast.unparse(node)
            assert ast.unparse(node.comparators[-1]) == "spec.modes", ast.unparse(node)
    assert member_sites >= 10


def test_the_operation_match_fails_closed() -> None:
    covered, closed = _match_targets(_functions(_tree())["_apply_operation"])
    assert closed
    assert covered == {"ScenarioOperation.SET", "ScenarioOperation.ADD", "ScenarioOperation.SCALE", "ScenarioOperation.CAP_AT"}


# =============================================================================
# Unit addressing (Section 7.2, SC-1, SC-5) -- the P7.1 review correction
# =============================================================================


def test_every_override_is_unit_addressed_and_unit_id_is_required() -> None:
    fields = dataclasses.fields(scenario_module.ScenarioOverride)
    assert [field.name for field in fields] == ["unit_id", "target", "operation", "value"]
    assert fields[0].default is dataclasses.MISSING
    assert fields[0].default_factory is dataclasses.MISSING
    assert "unit_id" not in {f.name for f in dataclasses.fields(scenario_module.ScenarioDefinition)}


def test_duplicate_identity_is_the_unit_and_target_address() -> None:
    """SC-1: overrides are grouped by ``(unit_id, target)``, never by target
    alone, so the same target on two units is two addresses."""

    validate = _functions(_tree())["validate_scenario"]
    keys = [
        ast.unparse(node.args[0])
        for node in ast.walk(validate)
        if isinstance(node, ast.Call) and _callee(node) == "setdefault"
    ]
    assert keys == ["(override.unit_id, override.target)"]


def test_no_resolver_can_discard_or_reassign_a_foreign_unit_override() -> None:
    """Only stage 1 reads an override's unit. Resolution receives every
    override stage 1 accepted, unfiltered. A foreign-unit override can
    therefore only ever surface as an issue; it can never be dropped or
    quietly applied to the analysed unit."""

    tree = _tree()
    owner = _enclosing_function_of(tree)
    readers = {
        owner.get(node, "<module>")
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "unit_id"
    }
    assert readers == {"validate_scenario"}

    functions = _functions(tree)
    (ordering,) = [
        node for node in ast.walk(functions["_require_resolvable"])
        if isinstance(node, ast.Call) and _callee(node) == "sorted"
    ]
    assert ast.unparse(ordering.args[0]) == "scenario.overrides"
    for name, function in functions.items():
        if name.startswith(("resolve_", "analyze_", "_resolve_")) or name == "_require_resolvable":
            filtered = [n for n in ast.walk(function) if isinstance(n, ast.comprehension) and n.ifs]
            assert filtered == [], name


def test_every_public_entry_point_takes_a_required_keyword_unit_id() -> None:
    functions = _functions(_tree())
    for name in (
        "validate_scenario",
        "resolve_quick_scenario", "resolve_detailed_scenario", "resolve_lease_level_scenario",
        "analyze_quick_acquisition_with_scenario", "analyze_detailed_acquisition_with_scenario",
        "analyze_lease_level_acquisition_with_scenario",
    ):
        arguments = functions[name].args
        keyword_only = [argument.arg for argument in arguments.kwonlyargs]
        assert "unit_id" in keyword_only, name
        assert arguments.kw_defaults[keyword_only.index("unit_id")] is None, name
        assert "unit_id" not in [argument.arg for argument in arguments.args], name


# =============================================================================
# 9. No reflection, no path patching
# =============================================================================


def test_no_reflection_eval_or_path_patching_exists() -> None:
    tree = _tree()
    forbidden_calls = {
        "getattr", "setattr", "delattr", "hasattr", "eval", "exec", "compile", "vars", "globals",
        "locals", "__import__", "import_module", "attrgetter", "itemgetter", "loads", "fields",
        "object.__setattr__",
    }
    called = {_callee(n) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not called & forbidden_calls
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attributes & {"__dict__", "__setattr__", "__getattribute__", "__slots__"}
    imported = set(_absolute_imports(_SCENARIO))
    assert not imported & {"json", "operator", "importlib", "copy", "functools", "inspect"}
    subscripted_strings = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str)
    ]
    assert subscripted_strings == []


def test_the_reflection_guard_detects_a_setattr_patch() -> None:
    mutant = _source() + "\n\ndef _patch(obj, path, value):\n    setattr(obj, path, value)\n"
    assert "setattr" in {_callee(n) for n in ast.walk(ast.parse(mutant)) if isinstance(n, ast.Call)}


def test_the_module_exposes_the_scenario_contracts_it_documents() -> None:
    for name in (
        "ScenarioDefinition", "ScenarioOverride", "ScenarioOperation", "ScenarioTarget",
        "SCENARIO_TARGET_REGISTRY", "ScenarioValidationError", "validate_scenario",
        "resolve_quick_scenario", "resolve_detailed_scenario", "resolve_lease_level_scenario",
        "analyze_quick_acquisition_with_scenario", "analyze_detailed_acquisition_with_scenario",
        "analyze_lease_level_acquisition_with_scenario",
    ):
        assert name in vars(scenario_module), name


# =============================================================================
# 10. The Phase 7 production ledger
# =============================================================================

#: ``main`` when P7.1 began: the no-ff P7.0 merge, whose parents are the Phase 6
#: merge and the P7.0 ratification patch. P7.0 changed no production file, so
#: this is also the last commit of Phase 6 production code.
_PHASE_7_LEDGER_BASE = "f234e4c"
_P7_0_MERGE_PARENTS = ("0593baa", "c4639eb")

#: Every production file P7.1 changes, exactly. It is the one new module; no
#: existing production file moves, so no ordinary analysis can change.
_P7_1_PRODUCTION_FILES = frozenset({"src/anchor/analysis/scenario.py"})


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, cwd=_PROJECT_ROOT
    ).stdout


def _is_production(path: str) -> bool:
    return path.startswith(("src/", "web/")) and re.search(r"\.test\.tsx?$", path) is None


def _ledger_violations(changed: set[str]) -> tuple[list[str], list[str]]:
    return sorted(changed - _P7_1_PRODUCTION_FILES), sorted(_P7_1_PRODUCTION_FILES - changed)


#: ``main`` after P7.1 -- the no-ff merge of ``feature/p7-1-scenario-engine``,
#: and the end of P7.1's committed range.
_P7_1_MERGE = "58f862d"


def _production_changes_between(start: str, end: str) -> set[str]:
    """Production files that differ between two commits. Reads Git only; it
    never touches the index (protocol 11.2)."""

    changed = _git("diff", "--name-only", start, end, "--", "src", "web").split()
    return {path for path in changed if _is_production(path)}


def test_p7_1_changed_exactly_its_authorized_production_files() -> None:
    """The Phase 7 production ledger for P7.1.

    Pinned at P7.2 to P7.1's own committed range, ``f234e4c..58f862d``, so it
    keeps proving exactly what P7.1 changed however later gates move the tree.
    That is the D6 ledger precedent. P7.2's own ledger is
    ``tests/test_p7_2_investment_scenario_architecture.py``. Never widen this
    set to admit another gate's files."""

    unexpected, missing = _ledger_violations(
        _production_changes_between(_PHASE_7_LEDGER_BASE, _P7_1_MERGE)
    )
    assert (unexpected, missing) == ([], [])


def test_the_p7_1_ledger_end_is_the_p7_1_merge() -> None:
    """``58f862d`` is the P7.1 merge: its second parent is the reviewed P7.1
    head, and its first parent is the P7.0 merge this ledger starts from."""

    parents = _git("rev-list", "--parents", "-n", "1", _P7_1_MERGE).split()[1:]
    assert parents == [
        _git("rev-parse", _PHASE_7_LEDGER_BASE).strip(),
        _git("rev-parse", "5aa7bd6").strip(),
    ]


def test_the_phase_7_ledger_base_is_the_p7_0_merge() -> None:
    parents = _git("rev-list", "--parents", "-n", "1", _PHASE_7_LEDGER_BASE).split()[1:]
    assert parents == [_git("rev-parse", ref).strip() for ref in _P7_0_MERGE_PARENTS]


def test_p7_0_itself_changed_no_production_file() -> None:
    assert {p for p in _git("diff", "--name-only", "0593baa", _PHASE_7_LEDGER_BASE, "--", "src", "web").split()
            if _is_production(p)} == set()


def test_the_ledger_rejects_any_unexpected_production_change() -> None:
    assert _ledger_violations(set(_P7_1_PRODUCTION_FILES)) == ([], [])
    for intruder in (
        "src/anchor/engine/acquisition.py",
        "src/anchor/analysis/sensitivity.py",
        "src/anchor/deals/store.py",
        "src/anchor/api.py",
        "src/anchor/ai/prompts.py",
        "web/src/App.tsx",
        "web/src/index.css",
    ):
        assert _ledger_violations({*_P7_1_PRODUCTION_FILES, intruder}) == ([intruder], [])
    assert _ledger_violations(set()) == ([], sorted(_P7_1_PRODUCTION_FILES))
    assert not _is_production("web/src/businessPlan.test.ts")
    assert not _is_production("tests/test_p7_1_scenario_architecture.py")
    assert not _is_production("docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md")
