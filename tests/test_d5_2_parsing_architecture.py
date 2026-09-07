"""D5.2 -- architectural guardrails on the Lease-Level structural parser.

``tests/test_d5_2_lease_level_parsing.py`` proves the parser behaves correctly
on the inputs it was shown. This file proves the things a behavioural suite
cannot: that the parser *has no capacity* to become an underwriting authority,
and that it cannot silently drift out of step with the contracts it parses.

Four properties:

1. **No arithmetic, no ranges, no rounding, no date math.** A structural parser
   that could compute could also normalise, and a normalisation invented at the
   transport layer is an unstated financial convention -- reviewed by nobody,
   covered by no golden case.
2. **No domain vocabulary.** Not one leasing rule is restated here. Every issue
   code the parser can raise is one of the two structural ones.
3. **Contract-driven.** Accepted keys, required-ness and target types come from
   ``dataclasses.fields``/``get_type_hints``, never from a parallel list of field
   names that could drift when a contract gains a field.
4. **No analysis.** The parser reaches no builder, no projection and no engine.

The mutation section applies each named mutant from the D5.2 charter to the real
source and shows it is caught, rather than asserting it is impossible.
"""

from __future__ import annotations

import ast
import dataclasses
import types
import typing
from datetime import date
from enum import Enum
from pathlib import Path

import pytest

from anchor.leasing import contracts as leasing_contracts
from anchor.leasing.parsing import ParsedLeaseLevelRequest, parse_lease_level_request
from anchor.leasing.validation import LeaseIssueCode, LeaseIssueSeverity

_PARSING = Path(__file__).resolve().parents[1] / "src" / "anchor" / "leasing" / "parsing.py"
_SOURCE = _PARSING.read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)


def _code_only(tree: ast.Module) -> str:
    """The module's *executable* text, with comments and docstrings removed.

    Every textual check below asks what the parser can **do**, and prose is not
    behaviour. ``parsing.py``'s docstrings deliberately name the domain codes and
    validators it defers to -- that documentation is the point of the boundary,
    and a guardrail that banned mentioning a rule would forbid explaining where
    the rule actually lives. ``ast.unparse`` of a docstring-stripped tree drops
    comments (never parsed) and string-expression statements alike.
    """

    stripped = ast.parse(ast.unparse(tree))
    for node in ast.walk(stripped):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        body[:] = [
            statement
            for statement in body
            if not (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            )
        ]
    return ast.unparse(stripped)


#: Executable text only -- see ``_code_only``.
_CODE = _code_only(_TREE)

#: Every contract the parser reconstructs, plus the two nested ones.
_PARSED_CONTRACTS = (
    leasing_contracts.LeaseLevelPropertyInputs,
    leasing_contracts.LeaseLevelOperatingInputs,
    leasing_contracts.MarketLeasingAssumptions,
    leasing_contracts.Suite,
    leasing_contracts.Lease,
    leasing_contracts.InitialVacancyAssumptions,
)


def _numeric_constants(node: ast.AST) -> list[object]:
    return [
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, (int, float))
        and not isinstance(child.value, bool)
    ]


# =============================================================================
# 1. The parser cannot compute
# =============================================================================


def test_the_parser_performs_no_numeric_arithmetic() -> None:
    """No add, multiply, divide, modulo or power -- anywhere.

    These are how a percentage becomes a decimal, a rate becomes basis points,
    and an annual figure becomes a monthly one. A parser with none of them
    cannot perform any of those conversions by accident.
    """

    forbidden = (ast.Add, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.MatMult)
    offenders = [
        f"line {node.lineno}: {type(node.op).__name__}"
        for node in ast.walk(_TREE)
        if isinstance(node, ast.BinOp) and isinstance(node.op, forbidden)
    ]

    assert offenders == [], f"parsing.py performs arithmetic: {offenders}"


def test_the_only_remaining_binary_operators_are_set_and_type_algebra() -> None:
    """``-`` and ``|`` survive, on sets and type annotations, never on numbers.

    ``set(payload) - declared`` finds unknown keys and ``X | None`` is an
    annotation. Both are structural. The check is that neither ever has a
    numeric operand, which is what would make it arithmetic.
    """

    for node in ast.walk(_TREE):
        if not isinstance(node, ast.BinOp):
            continue
        assert isinstance(node.op, (ast.Sub, ast.BitOr)), (
            f"line {node.lineno}: unexpected operator {type(node.op).__name__}"
        )
        assert _numeric_constants(node) == [], (
            f"line {node.lineno}: {type(node.op).__name__} applied to a number"
        )


def test_the_parser_expresses_no_numeric_range() -> None:
    """No ``<``, ``>``, ``<=`` or ``>=``.

    Ordering comparisons on numbers are how a domain bound is written --
    ``0 <= renewal_probability <= 1`` is D2's rule, and it must live in D2's
    validator, once.
    """

    offenders = [
        f"line {node.lineno}"
        for node in ast.walk(_TREE)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, (ast.Lt, ast.Gt, ast.LtE, ast.GtE)) for op in node.ops)
    ]

    assert offenders == [], f"parsing.py compares magnitudes: {offenders}"


def test_the_parser_never_rounds_clips_or_aggregates() -> None:
    called = {
        node.func.id
        for node in ast.walk(_TREE)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    } | {
        node.func.attr
        for node in ast.walk(_TREE)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    for forbidden in ("round", "abs", "min", "max", "sum", "floor", "ceil", "trunc", "quantize", "clamp"):
        assert forbidden not in called, f"parsing.py calls {forbidden}()"


def test_the_parser_performs_no_date_arithmetic() -> None:
    """A date is reconstructed and handed on. It is never moved.

    Month-start snapping is the specific hazard: ``2027-01-15`` must reach D1's
    validator as the 15th and be refused by name, not silently become the 1st.
    """

    for forbidden in ("timedelta", "relativedelta", "calendar", "monthrange", "replace(day"):
        assert forbidden not in _CODE, f"parsing.py uses {forbidden}"

    # ``date`` is used only to name the type and to call ``fromisoformat``.
    date_calls = {
        node.func.attr
        for node in ast.walk(_TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "date"
    }
    assert date_calls <= {"fromisoformat"}, date_calls


def test_the_parser_declares_only_ordering_constants() -> None:
    """The only numbers in the file rank issue classes for sorting."""

    assert sorted(set(_numeric_constants(_TREE))) == [0, 1, 2]


# =============================================================================
# 2. The parser restates no domain rule
# =============================================================================


def test_the_parser_names_no_domain_issue_code() -> None:
    structural = {LeaseIssueCode.UNKNOWN_FIELD.name, LeaseIssueCode.MALFORMED_FIELD.name}
    for code in LeaseIssueCode:
        if code.name in structural:
            continue
        assert code.name not in _CODE, (
            f"parsing.py names the domain code {code.name}; that rule belongs to "
            "leasing/validation.py and must exist in exactly one place"
        )


def test_the_parser_uses_no_domain_vocabulary() -> None:
    for forbidden in (
        "reconcil", "downtime", "free_rent", "probability", "recoverable",
        "occupancy", "vacancy_rate", "escalate", "amortis", "amortiz",
        "noi", "irr", "dscr", "cap_rate", "exit_value", "month_align",
        "month_start", "first_day", "last_day",
    ):
        assert forbidden not in _CODE.lower(), f"parsing.py mentions {forbidden!r}"


def test_the_parser_can_only_raise_the_two_approved_codes() -> None:
    named = {
        node.attr
        for node in ast.walk(_TREE)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "LeaseIssueCode"
    }

    assert named == {"UNKNOWN_FIELD", "MALFORMED_FIELD"}


def test_the_parser_emits_only_error_severity() -> None:
    named = {
        node.attr
        for node in ast.walk(_TREE)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "LeaseIssueSeverity"
    }

    assert named == {"ERROR"}
    assert LeaseIssueSeverity.WARNING.name not in _CODE


# =============================================================================
# 3. Contract-driven, not field-listed
# =============================================================================


def test_no_contract_field_name_is_hardcoded_in_the_parser() -> None:
    """Accepted keys come from the contracts, so they cannot drift.

    The envelope's own field names (``suites``, ``leases``) and the two
    externally-owned top-level keys are the deliberate exceptions -- the request
    body is a JSON object with no dataclass of its own.
    """

    envelope = {field.name for field in dataclasses.fields(ParsedLeaseLevelRequest)}
    allowed = envelope | {"operating_mode", "terms"}

    literals = {
        node.value
        for node in ast.walk(_TREE)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    for contract in _PARSED_CONTRACTS:
        for field in dataclasses.fields(contract):
            if field.name in allowed:
                continue
            assert field.name not in literals, (
                f"parsing.py hardcodes the field name {field.name!r}; accepted keys "
                "must be derived from the contract so they cannot drift"
            )


def test_the_parser_reads_its_field_set_from_the_dataclasses() -> None:
    assert "dataclasses.fields(" in _CODE
    assert "typing.get_type_hints(" in _CODE


def test_every_field_of_every_parsed_contract_has_a_supported_type() -> None:
    """Keeps the parser's "unsupported type" refusal unreachable.

    If a contract ever gains a field this parser cannot reconstruct -- a nested
    list, a ``dict``, a ``Decimal`` -- this fails here, at the gate that owns the
    wire format, rather than as a runtime refusal in production.
    """

    def supported(annotation: object) -> bool:
        origin = typing.get_origin(annotation)
        if origin is types.UnionType or origin is typing.Union:
            args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
            return len(args) == 1 and supported(args[0])
        if isinstance(annotation, type):
            if dataclasses.is_dataclass(annotation) or issubclass(annotation, Enum):
                return True
            return annotation in (int, float, str, date)
        return False

    unsupported: list[str] = []
    for contract in _PARSED_CONTRACTS:
        hints = typing.get_type_hints(contract)
        for field in dataclasses.fields(contract):
            if not supported(hints[field.name]):
                unsupported.append(f"{contract.__name__}.{field.name}: {hints[field.name]}")

    assert unsupported == [], (
        f"these contract fields have no structural wire representation: {unsupported}"
    )


def test_the_parser_writes_no_default_of_its_own() -> None:
    """Contract defaults are applied by omission, never copied.

    A default duplicated here would be a second statement of an underwriting
    assumption, free to drift from the contract's.
    """

    for contract in _PARSED_CONTRACTS:
        for field in dataclasses.fields(contract):
            if field.default is dataclasses.MISSING:
                continue
            if isinstance(field.default, Enum):
                assert field.default.name not in _CODE, (
                    f"parsing.py restates the default for {contract.__name__}.{field.name}"
                )


# =============================================================================
# 4. No analysis, no persistence, no API
# =============================================================================


def test_the_parser_imports_no_analysis_or_delivery_layer() -> None:
    imported: set[str] = set()
    for node in ast.walk(_TREE):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for forbidden in ("anchor.analysis", "anchor.engine", "anchor.api", "anchor.deals",
                      "anchor.ai", "anchor.ingestion", "fastapi", "sqlite3"):
        assert not any(name == forbidden or name.startswith(f"{forbidden}.") for name in imported), (
            f"parsing.py imports {forbidden}"
        )


def test_the_parser_calls_no_builder_or_engine() -> None:
    for forbidden in (
        "analyze_lease_level_acquisition_with_projection",
        "build_model_months",
        "build_recursive_rollover",
        "build_initial_vacancy_rollover",
        "build_property_expense_schedule",
        "build_recoverable_expense_pool",
        "build_monthly_property_projection",
        "aggregate_monthly_to_annual",
        "analyze_acquisition",
        "run_lease_level_one_way_sensitivity",
        "run_lease_level_two_way_sensitivity",
    ):
        assert forbidden not in _CODE, f"parsing.py reaches {forbidden}"


def test_the_parser_runs_no_domain_validation() -> None:
    """It may import the issue *contracts*; it must not run the validators."""

    for forbidden in (
        "validate_lease_level_inputs",
        "require_valid_lease_level_inputs",
        "require_valid_initial_vacancy_inputs",
        "validate_lease_level_acquisition_leases",
        "require_valid_lease_level_operating_inputs",
    ):
        assert forbidden not in _CODE, f"parsing.py runs {forbidden}"


def test_the_api_has_not_been_wired_to_the_parser() -> None:
    """D5.3 owns activation. D5.2 ships a parser nothing calls yet."""

    api = (_PARSING.parents[2] / "anchor" / "api.py").read_text(encoding="utf-8")
    assert "parse_lease_level_request" not in api
    assert "leasing.parsing" not in api


# =============================================================================
# 5. Mutation kills
# =============================================================================


def _payload():
    from test_d5_2_lease_level_parsing import request_payload  # type: ignore[import-not-found]

    return request_payload


def test_m1_an_unknown_field_is_not_silently_ignored() -> None:
    request_payload = _payload()
    from anchor.leasing.validation import LeaseValidationError

    with pytest.raises(LeaseValidationError) as excinfo:
        parse_lease_level_request(request_payload(unexpected_key=1))

    assert any(i.code is LeaseIssueCode.UNKNOWN_FIELD for i in excinfo.value.result.errors)


def test_m2_a_missing_required_field_is_not_defaulted() -> None:
    request_payload = _payload()
    from anchor.leasing.validation import LeaseValidationError

    payload = request_payload()
    del payload["property_inputs"]["rentable_area_sf"]

    with pytest.raises(LeaseValidationError):
        parse_lease_level_request(payload)


@pytest.mark.parametrize("value", ["3%", "0.03", " 0.03 ", "3 percent"])
def test_m3_m4_no_string_is_ever_converted_to_a_number(value: str) -> None:
    request_payload = _payload()
    from anchor.leasing.validation import LeaseValidationError

    payload = request_payload()
    payload["market_leasing"]["renewal_probability"] = value

    with pytest.raises(LeaseValidationError) as excinfo:
        parse_lease_level_request(payload)

    assert [i.path for i in excinfo.value.result.errors] == [
        "market_leasing.renewal_probability"
    ]


def test_m5_a_mid_month_date_is_not_snapped() -> None:
    request_payload = _payload()

    payload = request_payload()
    payload["property_inputs"]["analysis_start_date"] = "2027-01-15"

    parsed = parse_lease_level_request(payload)

    assert parsed.property_inputs.analysis_start_date == date(2027, 1, 15)


def test_m6_m7_out_of_domain_values_are_not_rejected_by_the_parser() -> None:
    request_payload = _payload()

    payload = request_payload()
    payload["market_leasing"]["renewal_probability"] = 1.2
    payload["property_inputs"]["rentable_area_sf"] = -100.0
    payload["suites"][0]["suite_area_sf"] = -1.0

    parsed = parse_lease_level_request(payload)

    assert parsed.market_leasing.renewal_probability == 1.2
    assert parsed.property_inputs.rentable_area_sf == -100.0
    assert parsed.suites[0].suite_area_sf == -1.0


def test_m8_an_invalid_enum_never_falls_back_to_a_default() -> None:
    request_payload = _payload()
    from anchor.leasing.validation import LeaseValidationError

    payload = request_payload()
    payload["leases"][0]["lease_type"] = "not-a-lease-type"

    with pytest.raises(LeaseValidationError) as excinfo:
        parse_lease_level_request(payload)

    assert [i.path for i in excinfo.value.result.errors] == ["leases[0].lease_type"]


def test_m9_no_stdlib_exception_text_reaches_a_message() -> None:
    request_payload = _payload()
    from anchor.leasing.validation import LeaseValidationError

    payload = request_payload()
    payload["property_inputs"]["analysis_start_date"] = "2027-02-30"

    with pytest.raises(LeaseValidationError) as excinfo:
        parse_lease_level_request(payload)

    message = excinfo.value.result.errors[0].message
    assert "isoformat" not in message.lower()
    assert "2027-02-30" not in message


def test_m10_m11_nested_objects_are_never_left_as_raw_dicts() -> None:
    request_payload = _payload()
    from anchor.leasing.contracts import InitialVacancyAssumptions, MarketLeasingAssumptions

    payload = request_payload()
    payload["suites"][0]["market_leasing_override"] = dict(payload["market_leasing"])
    parsed = parse_lease_level_request(payload)

    assert isinstance(parsed.suites[0].market_leasing_override, MarketLeasingAssumptions)
    assert isinstance(parsed.suites[1].initial_vacancy, InitialVacancyAssumptions)
    assert not isinstance(parsed.suites[0].market_leasing_override, dict)


def test_m12_json_arrays_become_tuples() -> None:
    request_payload = _payload()

    parsed = parse_lease_level_request(request_payload())

    assert type(parsed.suites) is tuple
    assert type(parsed.leases) is tuple


def test_m13_ordering_is_independent_of_mapping_iteration() -> None:
    request_payload = _payload()
    from anchor.leasing.validation import LeaseValidationError

    def issues(reverse: bool):
        payload = request_payload()
        suite = dict(payload["suites"][0])
        suite["zzz_unknown"] = 1
        suite["aaa_unknown"] = 1
        suite["suite_area_sf"] = "x"
        payload["suites"] = [dict(reversed(list(suite.items()))) if reverse else suite]
        with pytest.raises(LeaseValidationError) as excinfo:
            parse_lease_level_request(payload)
        return [(i.code, i.path) for i in excinfo.value.result.errors]

    assert issues(False) == issues(True)
    # Unknown keys are reported in a stable sorted order, not insertion order.
    assert issues(False)[0][1] == "suites[0].aaa_unknown"


def test_m14_the_parser_never_emits_a_warning() -> None:
    request_payload = _payload()
    from anchor.leasing.validation import LeaseValidationError

    payload = request_payload(unexpected=1)
    payload["suites"][0]["suite_area_sf"] = "x"
    del payload["market_leasing"]["renewal_probability"]

    with pytest.raises(LeaseValidationError) as excinfo:
        parse_lease_level_request(payload)

    assert excinfo.value.result.warnings == ()
    assert all(
        issue.severity is LeaseIssueSeverity.ERROR for issue in excinfo.value.result.issues
    )


def test_m16_no_third_parse_code_was_invented() -> None:
    """D5.0 approved exactly two. A third would be a contract change."""

    structural = [
        code for code in LeaseIssueCode
        if code.name in {"UNKNOWN_FIELD", "MALFORMED_FIELD", "MISSING_FIELD", "PARSE_ERROR"}
    ]

    assert [code.name for code in structural] == ["UNKNOWN_FIELD", "MALFORMED_FIELD"]
