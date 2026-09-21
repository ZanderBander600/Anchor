"""Phase 7 Gate P7.10 Stage 1 -- whether an authored valuation definition is
well formed.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 5.1
to 5.4 and the ratified decisions R-A, R-C and R-D; that document governs on
any discrepancy.

**Structural only.** Every rule here is a property of the definition itself and
holds under every Strategy and Scenario. Whether a month falls inside *this*
variant's hold, whether *this* variant holds the Units named, and whether the
forward NOI is positive all depend on the variant, so they are never issues
here: ``engine`` reports them as typed unavailable results, because the same
definition may resolve elsewhere.

**Refused whole.** A definition with any issue is never repaired, defaulted or
partially resolved. Issues come in field order, then the instructions' in
canonical ``unit_id`` order; list position never participates.
"""

from __future__ import annotations

from collections import Counter
from math import isfinite

from .contracts import (
    AnalystValue,
    DirectCap,
    ValuationIssue,
    ValuationIssueCode,
    ValuationKind,
    ValuationTimepoint,
    ValuationValidationError,
)


def _blank(text: str) -> bool:
    return not text.strip()


def _issue(
    code: ValuationIssueCode, message: str, *, unit_id: str | None = None, field: str | None = None
) -> ValuationIssue:
    return ValuationIssue(code=code, message=message, unit_id=unit_id, field=field)


def _month_issues(timepoint: ValuationTimepoint) -> list[ValuationIssue]:
    """``model_month`` is ``0`` or a hold-year end ``12y`` (R-A), and the kind
    agrees with it (R-C). No inside-year month exists in this contract: a
    monthly valuation would need a new forward-NOI convention, which is
    deferred."""

    month = timepoint.model_month
    issues: list[ValuationIssue] = []
    if month < 0 or month % 12 != 0:
        issues.append(
            _issue(
                ValuationIssueCode.INVALID_MODEL_MONTH,
                f"Valuation timepoint {timepoint.timepoint_id!r} is at model month {month!r}; an initial timepoint "
                "is at closing (model month 0) or a hold-year end (a multiple of 12). Inside-year valuation would "
                "need a forward-NOI convention this contract does not state.",
                field="model_month",
            )
        )
        return issues
    if timepoint.kind is ValuationKind.AS_IS and month != 0:
        issues.append(
            _issue(
                ValuationIssueCode.KIND_MONTH_MISMATCH,
                f"As-Is valuation {timepoint.timepoint_id!r} is at model month {month}; As-Is is the closing-time "
                "value and is always model month 0.",
                field="model_month",
            )
        )
    elif timepoint.kind is ValuationKind.STABILIZED and month == 0:
        issues.append(
            _issue(
                ValuationIssueCode.KIND_MONTH_MISMATCH,
                f"Stabilized valuation {timepoint.timepoint_id!r} is at model month 0, which is closing. A "
                "stabilized value is declared at a hold-year end; stabilization at closing is As-Is.",
                field="model_month",
            )
        )
    return issues


def _method_issues(unit_id: str, method: object, *, field: str) -> list[ValuationIssue]:
    """The two initial methods, and nothing else (R-D)."""

    match method:
        case DirectCap():
            if not isfinite(method.cap_rate) or method.cap_rate <= 0.0:
                return [
                    _issue(
                        ValuationIssueCode.INVALID_CAP_RATE,
                        f"Unit {unit_id!r} capitalises at {method.cap_rate!r}; a capitalisation rate is finite and "
                        "greater than zero. It is never floored, defaulted or inferred from the going-in rate.",
                        unit_id=unit_id,
                        field=f"{field}.method.cap_rate",
                    )
                ]
            return []
        case AnalystValue():
            issues: list[ValuationIssue] = []
            if not isfinite(method.amount) or method.amount < 0.0:
                issues.append(
                    _issue(
                        ValuationIssueCode.INVALID_ANALYST_AMOUNT,
                        f"Unit {unit_id!r} states an analyst-supplied value of {method.amount!r}; it is finite and "
                        "non-negative.",
                        unit_id=unit_id,
                        field=f"{field}.method.amount",
                    )
                )
            if _blank(method.evidence_id):
                issues.append(
                    _issue(
                        ValuationIssueCode.BLANK_EVIDENCE_ID,
                        f"Unit {unit_id!r} states an analyst-supplied value with no evidence identifier; an "
                        "analyst-supplied value names the approved Evidence Reference supporting it (R-D).",
                        unit_id=unit_id,
                        field=f"{field}.method.evidence_id",
                    )
                )
            return issues
        case _:
            return [
                _issue(
                    ValuationIssueCode.UNSUPPORTED_METHOD,
                    f"Unit {unit_id!r} states valuation method {method!r}; the initial methods are direct "
                    "capitalisation and an explicitly labelled analyst-supplied value.",
                    unit_id=unit_id,
                    field=f"{field}.method",
                )
            ]


def validate_valuation_timepoint(timepoint: ValuationTimepoint) -> tuple[ValuationIssue, ...]:
    """Every structural reason ``timepoint`` is not a well-formed definition,
    or ``()``."""

    issues: list[ValuationIssue] = []
    if _blank(timepoint.timepoint_id):
        issues.append(
            _issue(
                ValuationIssueCode.BLANK_TIMEPOINT_ID,
                "A valuation timepoint names itself by a stable, nonblank, opaque timepoint id.",
                field="timepoint_id",
            )
        )
    if _blank(timepoint.investment_id):
        issues.append(
            _issue(
                ValuationIssueCode.BLANK_INVESTMENT_ID,
                f"Valuation timepoint {timepoint.timepoint_id!r} names no Investment; every definition belongs to "
                "exactly one Investment.",
                field="investment_id",
            )
        )
    if _blank(timepoint.label):
        issues.append(
            _issue(
                ValuationIssueCode.BLANK_LABEL,
                f"Valuation timepoint {timepoint.timepoint_id!r} has no label; an analyst-facing label is required, "
                "and is presentation only.",
                field="label",
            )
        )
    issues.extend(_month_issues(timepoint))

    instructions = timepoint.unit_instructions
    if not instructions:
        issues.append(
            _issue(
                ValuationIssueCode.NO_UNIT_INSTRUCTION,
                f"Valuation timepoint {timepoint.timepoint_id!r} instructs no Unit; a definition states exactly one "
                "instruction for every included Unit.",
                field="unit_instructions",
            )
        )
        return tuple(issues)

    counts = Counter(instruction.unit_id for instruction in instructions)
    for unit_id in sorted(unit_id for unit_id, count in counts.items() if count > 1):
        issues.append(
            _issue(
                ValuationIssueCode.DUPLICATE_UNIT_INSTRUCTION,
                f"Valuation timepoint {timepoint.timepoint_id!r} instructs Unit {unit_id!r} {counts[unit_id]} times; "
                "exactly one instruction values a Unit, and no instruction overrides another.",
                unit_id=unit_id,
                field="unit_instructions",
            )
        )
    for instruction in sorted(instructions, key=lambda item: item.unit_id):
        field = f"unit_instructions[{instruction.unit_id}]"
        if _blank(instruction.unit_id):
            issues.append(
                _issue(
                    ValuationIssueCode.BLANK_UNIT_ID,
                    f"Valuation timepoint {timepoint.timepoint_id!r} states an instruction naming no Unit; every "
                    "instruction names one Unit by its stable id.",
                    field="unit_instructions",
                )
            )
            continue
        issues.extend(_method_issues(instruction.unit_id, instruction.method, field=field))
    return tuple(issues)


def require_valid_valuation_timepoint(timepoint: ValuationTimepoint) -> ValuationTimepoint:
    """``timepoint`` unchanged, or raise ``ValuationValidationError``."""

    issues = validate_valuation_timepoint(timepoint)
    if issues:
        raise ValuationValidationError(issues)
    return timepoint
