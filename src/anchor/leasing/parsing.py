"""D5.2 -- the Lease-Level transport boundary: raw JSON -> frozen contracts.

Anchor had a gap here. ``anchor.validation`` turns a raw mapping into
``AcquisitionInputs``/``AcquisitionTerms``/``DetailedOperatingInputs`` for Quick
and Detailed; ``anchor.leasing.validation`` turns *already-constructed* leasing
dataclasses into issues. Nothing bridged the two, so a Lease-Level HTTP body had
no way to become the typed contracts the deterministic analysis requires.

This module is that bridge, and **only** that bridge. It answers exactly one
question:

    Can this JSON faithfully construct the requested typed contract?

It never answers:

    Are these underwriting assumptions financially valid?

That second question already has an authority -- ``leasing/validation.py`` and
the D2/D3/D4 builders -- and this module restates none of it. The separation is
not stylistic. A parser that "helpfully" clamped ``renewal_probability`` to 1.0,
or snapped a mid-month ``analysis_start_date`` to the 1st, would be silently
authoring underwriting judgement at the transport layer, where no reviewer looks
for it and no golden case covers it. So a structurally-parseable but
economically-absurd payload parses **successfully** here and is refused
downstream, by name, with the code it has always had.

Worked examples of that boundary, each covered by a test:

    renewal_probability = 1.2      parses. RENEWAL_PROBABILITY_OUT_OF_DOMAIN
                                   is raised later, by D2's validator.
    analysis_start_date = 15th     parses. ANALYSIS_START_NOT_MONTH_ALIGNED is
                                   raised later, by D1's validator.
    rentable_area_sf = -100        parses. RENTABLE_AREA_OUT_OF_DOMAIN later.
    two leases on one suite        parses. MULTIPLE_KNOWN_LEASES_IN_SUITE is
                                   raised later, at the D4.5B acquisition
                                   boundary.

**Contract-driven, not field-listed.** Every accepted key, every required field
and every target type is read from ``dataclasses.fields`` and
``typing.get_type_hints`` at call time. There is no parallel list of field names
to drift out of step with the contracts, and adding a field to ``Suite`` needs no
edit here. The only thing this module knows about a *particular* field is what
its declared type already says.

**Defaults belong to contracts.** When a field is omitted and the contract
declares a default, this module simply does not pass it, so the contract's own
default applies. It never writes a default of its own -- the difference between
``Lease.origin`` defaulting to ``IN_PLACE`` (a documented contractual fact) and a
parser inventing ``credit_loss_pct = 0.0`` at the wire (an unstated assumption).

**Scope.** The five leasing contracts of a Lease-Level request.
``AcquisitionTerms`` is deliberately *not* parsed here: it already has a shipped
owner in ``anchor.validation.validate_acquisition_terms``, which both the
Detailed API path and Detailed persistence use, and which performs the shared
domain checks this module must not duplicate. D5.3 composes the two exactly as
``api.py`` already composes ``_require_deal_terms`` with
``_require_deal_detailed_operating_inputs``.
"""

from __future__ import annotations

import dataclasses
import itertools
import types
import typing
from collections.abc import Mapping, Sequence
from datetime import date
from enum import Enum
from math import isfinite
from typing import Any

from .contracts import (
    InitialVacancyAssumptions,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    MarketLeasingAssumptions,
    Suite,
)
from .validation import (
    LeaseIssueCode,
    LeaseIssueSeverity,
    LeaseValidationError,
    LeaseValidationIssue,
    LeaseValidationResult,
)

__all__ = [
    "ParsedLeaseLevelRequest",
    "parse_lease_level_request",
]


# =============================================================================
# Issue classes and ordering
#
# ``anchor.validation`` collects "unknown IDs first, then missing IDs, then
# value/type issues in canonical field order". That ordering is reproduced here
# so a Lease-Level payload reports its problems in the same shape a Quick one
# does -- unknown keys are usually typos and are the most actionable thing to
# show an analyst first.
#
# Ordering is by (class, discovery sequence). The sequence comes from walking the
# request in a fixed structural order, never from mapping iteration, so two
# payloads that differ only in key insertion order report identical issues.
# =============================================================================

_UNKNOWN = 0
_MISSING = 1
_MALFORMED = 2


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class _Finding:
    """One structural problem, tagged for deterministic ordering."""

    rank: int
    sequence: int
    issue: LeaseValidationIssue


class _Collector:
    """Accumulates findings and hands out monotonic discovery sequence numbers.

    The sequence is assigned as the walk visits each location, so it encodes
    structural position (``suites[0]`` before ``suites[1]``, declaration order
    within a contract) without any sorting of user input and without arithmetic
    on the paths themselves.
    """

    def __init__(self) -> None:
        self._findings: list[_Finding] = []
        self._next_sequence = itertools.count()

    def add(self, rank: int, code: LeaseIssueCode, path: str, message: str) -> None:
        self._findings.append(
            _Finding(
                rank=rank,
                sequence=next(self._next_sequence),
                issue=LeaseValidationIssue(
                    code=code,
                    path=path,
                    message=message,
                    # Always ERROR. A structural failure means no contract
                    # exists, so there is nothing for a warning to qualify.
                    severity=LeaseIssueSeverity.ERROR,
                ),
            )
        )

    def unknown(self, path: str, message: str) -> None:
        self.add(_UNKNOWN, LeaseIssueCode.UNKNOWN_FIELD, path, message)

    def missing(self, path: str, message: str) -> None:
        self.add(_MISSING, LeaseIssueCode.MALFORMED_FIELD, path, message)

    def malformed(self, path: str, message: str) -> None:
        self.add(_MALFORMED, LeaseIssueCode.MALFORMED_FIELD, path, message)

    @property
    def issues(self) -> tuple[LeaseValidationIssue, ...]:
        ordered = sorted(self._findings, key=lambda finding: (finding.rank, finding.sequence))
        return tuple(finding.issue for finding in ordered)

    def __bool__(self) -> bool:
        return bool(self._findings)


# =============================================================================
# Type introspection
# =============================================================================


def _describe(value: object) -> str:
    """Name a value's JSON-side type for an error message.

    Deliberately names the *JSON* type rather than the Python one: a caller
    sending a request body thinks in JSON, and telling them a field "must be a
    number, got string" is actionable where "got str" is an implementation
    detail. Never includes the value itself -- a payload can carry
    tenant names, and an error message is not a place to echo them back.
    """

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence):
        return "array"
    return "an unsupported value"


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Split ``X | None`` into ``(X, True)``; leave anything else ``(X, False)``."""

    origin = typing.get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _is_dataclass_type(annotation: Any) -> bool:
    return isinstance(annotation, type) and dataclasses.is_dataclass(annotation)


def _is_enum_type(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, Enum)


# =============================================================================
# Scalar parsing
#
# Numeric handling follows ``anchor.validation._normalize_field_value``
# (validation.py:240-273) exactly, because a Lease-Level payload and a Quick one
# reaching the same API deserve the same answer about what a number is:
#
#   * a JSON boolean is never a number, despite ``bool`` subclassing ``int``;
#   * a JSON integer satisfies a ``float`` field (widening);
#   * a JSON number satisfies an ``int`` field only when it is integral --
#     ``12.0`` yes, ``12.5`` no -- mirroring that function's ``is_integer()``
#     gate for the year fields;
#   * non-finite is refused.
#
# ``float()``/``int()`` here are type reconstruction at a serialization
# boundary, not numeric coercion of a stated assumption: no value's *magnitude*
# is changed by either call on the inputs they are allowed to see.
# =============================================================================


def _parse_number(value: object, annotation: Any, path: str, into: _Collector) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        into.malformed(
            path,
            f"must be a number; booleans and text are not accepted, got {_describe(value)}",
        )
        return _FAILED
    if not isfinite(value):
        into.malformed(path, "must be a finite number")
        return _FAILED

    if annotation is int:
        if isinstance(value, float) and not value.is_integer():
            into.malformed(path, "must be a whole number")
            return _FAILED
        return int(value)
    return float(value)


def _parse_date(value: object, path: str, into: _Collector) -> Any:
    if not isinstance(value, str):
        into.malformed(
            path, f"must be an ISO-8601 date string (YYYY-MM-DD), got {_describe(value)}"
        )
        return _FAILED
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        # Anchor owns this message. The stdlib's text ("Invalid isoformat
        # string: '01/15/2027'") is an implementation detail that would leak a
        # Python concept into an API response and change between versions.
        into.malformed(path, "must be an ISO-8601 date string (YYYY-MM-DD)")
        return _FAILED
    return parsed


def _parse_enum(value: object, annotation: Any, path: str, into: _Collector) -> Any:
    """Accept only exact wire tokens.

    No case folding, no punctuation stripping, no aliases: ``"triple net"`` does
    not become ``NNN``. An alias table is a transport convention, and Anchor has
    not ratified one; inventing it here would make the wire format depend on
    this module's taste rather than on a documented contract.
    """

    if not isinstance(value, str):
        into.malformed(path, f"must be a string, got {_describe(value)}")
        return _FAILED
    try:
        return annotation(value)
    except ValueError:
        accepted = ", ".join(repr(member.value) for member in annotation)
        into.malformed(path, f"must be one of {accepted}")
        return _FAILED


def _parse_string(value: object, path: str, into: _Collector) -> Any:
    if not isinstance(value, str):
        into.malformed(path, f"must be a string, got {_describe(value)}")
        return _FAILED
    return value


#: Sentinel for "this location produced no usable value". Distinct from ``None``,
#: which is a legitimate parsed result for every nullable field.
_FAILED = object()


def _parse_value(value: object, annotation: Any, path: str, into: _Collector) -> Any:
    """Reconstruct one value of the declared type, or record why it cannot be."""

    inner, optional = _unwrap_optional(annotation)

    if value is None:
        if optional:
            return None
        into.malformed(path, "must not be null")
        return _FAILED

    if _is_dataclass_type(inner):
        return _parse_dataclass(value, inner, path, into)
    if _is_enum_type(inner):
        return _parse_enum(value, inner, path, into)
    if inner is date:
        return _parse_date(value, path, into)
    if inner is str:
        return _parse_string(value, path, into)
    if inner in (int, float):
        return _parse_number(value, inner, path, into)

    # No parser for this declared type. Refusing is the only safe answer: a
    # guess here would invent a wire format for a contract change nobody
    # reviewed. The architecture test below keeps this branch unreachable by
    # asserting every field of every parsed contract has a supported type.
    into.malformed(path, "has a type this request format does not support")
    return _FAILED


def _parse_dataclass(value: object, target: type, path: str, into: _Collector) -> Any:
    """Reconstruct one frozen contract from a JSON object.

    Accepted keys, required-ness and target types all come from the contract
    itself, so this function has no knowledge of any particular field.
    """

    if not isinstance(value, Mapping):
        into.malformed(path, f"must be an object, got {_describe(value)}")
        return _FAILED

    fields = dataclasses.fields(target)
    hints = typing.get_type_hints(target)
    declared = {field.name for field in fields}

    # Unknown keys first, in sorted order so a payload's key insertion order
    # cannot change what is reported. A typo silently discarded is the failure
    # this catches: `suite_are_sf` must not vanish next to `suite_area_sf`.
    for key in sorted(set(value) - declared):
        into.unknown(_join(path, key), "is not a field of this object")

    kwargs: dict[str, Any] = {}
    failed = False

    for field in fields:
        field_path = _join(path, field.name)
        if field.name not in value:
            has_default = (
                field.default is not dataclasses.MISSING
                or field.default_factory is not dataclasses.MISSING
            )
            if has_default:
                # Omit it entirely and let the contract's own default apply.
                # Copying the value here would put a second, drifting statement
                # of an underwriting default at the transport layer.
                continue
            into.missing(field_path, "is required")
            failed = True
            continue

        parsed = _parse_value(value[field.name], hints[field.name], field_path, into)
        if parsed is _FAILED:
            failed = True
            continue
        kwargs[field.name] = parsed

    if failed:
        return _FAILED
    return target(**kwargs)


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _parse_sequence(
    value: object, target: type, path: str, into: _Collector
) -> tuple[Any, ...] | Any:
    """Reconstruct a homogeneous tuple of contracts from a JSON array.

    Returns a ``tuple`` because that is what the leasing contracts and the
    analysis boundary hold. Order is the request's own: nothing is sorted,
    deduplicated or normalised here. Duplicate ids and suite/lease association
    are D1/D4 questions with their own codes, and canonical ordering for
    fingerprinting is D5.4's.
    """

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        into.malformed(path, f"must be an array, got {_describe(value)}")
        return _FAILED

    parsed: list[Any] = []
    failed = False
    for index, element in enumerate(value):
        element_path = f"{path}[{index}]"
        result = _parse_dataclass(element, target, element_path, into)
        if result is _FAILED:
            failed = True
            continue
        parsed.append(result)

    if failed:
        return _FAILED
    return tuple(parsed)


# =============================================================================
# The request envelope
# =============================================================================


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ParsedLeaseLevelRequest:
    """The five leasing contracts a Lease-Level analysis needs, reconstructed.

    Deliberately *not* carrying ``AcquisitionTerms``: that contract has a shipped
    parser and validator in ``anchor.validation``, shared with the Detailed path,
    and re-parsing it here would either duplicate its domain rules or silently
    skip them. D5.3 supplies terms alongside this envelope, exactly as ``api.py``
    already pairs ``_require_deal_terms`` with the Detailed operating inputs.

    Field names are the request's top-level keys, so the accepted envelope shape
    is this contract rather than a list maintained beside it.
    """

    property_inputs: LeaseLevelPropertyInputs
    operating_inputs: LeaseLevelOperatingInputs
    market_leasing: MarketLeasingAssumptions
    suites: tuple[Suite, ...]
    leases: tuple[Lease, ...]


#: Top-level keys that belong to a Lease-Level request but are owned elsewhere:
#: ``operating_mode`` is the API's dispatch discriminator (popped before the body
#: reaches any parser) and ``terms`` is ``validate_acquisition_terms``'s. Named
#: here so the envelope's unknown-key check does not report a legitimate key --
#: the only place in this module where a key is named rather than derived, and
#: only because the envelope is a JSON object with no dataclass of its own.
_EXTERNALLY_OWNED_KEYS = frozenset({"operating_mode", "terms"})

#: The collection members of the envelope and the contract each element is.
_SEQUENCE_FIELDS: dict[str, type] = {"suites": Suite, "leases": Lease}


def parse_lease_level_request(payload: Mapping[str, Any]) -> ParsedLeaseLevelRequest:
    """Structurally parse one Lease-Level request body into frozen contracts.

    Returns the reconstructed envelope, or raises ``LeaseValidationError``
    carrying **every** structural issue found in one pass -- the exact contract
    ``anchor.validation.validate_acquisition_inputs`` already has for Quick and
    Detailed, which is the shipped precedent for turning a raw mapping into a
    typed contract. A caller that wants the issues rather than the exception
    reads ``error.result``, which ``LeaseValidationError`` carries by design.

    Collects rather than short-circuits: an analyst fixing a rent roll should see
    all six malformed rows at once, not one per round trip.

    Performs **no** domain validation. Returning successfully means the JSON
    could become the contracts -- not that the deal is analysable. That remains
    ``require_valid_lease_level_inputs``' answer, unchanged and uncopied.
    """

    into = _Collector()

    if not isinstance(payload, Mapping):
        into.malformed("", f"must be an object, got {_describe(payload)}")
        raise LeaseValidationError(LeaseValidationResult(issues=into.issues))

    declared = {field.name for field in dataclasses.fields(ParsedLeaseLevelRequest)}
    for key in sorted(set(payload) - declared - _EXTERNALLY_OWNED_KEYS):
        into.unknown(key, "is not part of a Lease-Level request")

    hints = typing.get_type_hints(ParsedLeaseLevelRequest)
    parts: dict[str, Any] = {}
    failed = False

    for field in dataclasses.fields(ParsedLeaseLevelRequest):
        name = field.name
        if name not in payload:
            into.missing(name, "is required")
            failed = True
            continue

        if name in _SEQUENCE_FIELDS:
            parsed = _parse_sequence(payload[name], _SEQUENCE_FIELDS[name], name, into)
        else:
            parsed = _parse_dataclass(payload[name], hints[name], name, into)

        if parsed is _FAILED:
            failed = True
            continue
        parts[name] = parsed

    if into:
        raise LeaseValidationError(LeaseValidationResult(issues=into.issues))
    assert not failed
    return ParsedLeaseLevelRequest(**parts)
