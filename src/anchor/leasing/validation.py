"""Sprint D Gate D1.0 -- leasing-scoped validation.

Restates
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Section 19 exactly; that document governs on any discrepancy.

**This module deliberately does not touch ``anchor.validation``.** Lease-Level
needs an ERROR/WARNING severity distinction that Anchor's global validator
does not have, and D0's HD-6 resolution is that the distinction is introduced
*locally*, here, rather than by refactoring the global validator to serve one
new mode. Whether global validation should later gain severity is a separate
architectural decision, made on its own merits, and D1 is not coupled to it.

Deliberately not implemented here (D0 Section 19.4): no date coercion, no
rounding, no silent default for a missing required value, no downgrade of a
mathematically invalid input to a warning. Where D1's scope cannot model
something correctly, validation refuses.

No rent, month index, or schedule is computed anywhere in this module. The two
rules that reason about time -- expiry before the analysis start, and
same-suite overlap -- compare **absolute month keys** derived from the dates
themselves (``_month_key``), which is order-isomorphic to the 1-based
sequential month index D1.1 will introduce but needs no origin and builds no
calendar.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from math import isfinite
from typing import Iterable

from .contracts import Lease, LeaseLevelPropertyInputs, Suite


class LeaseIssueSeverity(StrEnum):
    """Severity of one leasing validation issue.

    ``ERROR`` -- the economics are wrong, undefined, or not representable in
    the supported model. Analysis is refused.

    ``WARNING`` -- the economics are computable and defensible, but a
    convention the analyst should know about is being applied. Analysis
    proceeds.

    ``ERROR`` is the default (D0 Section 19.1). A mathematically invalid
    input is never downgraded to a warning, and a warning is never invented
    merely to exercise this enum.
    """

    ERROR = "error"
    WARNING = "warning"


class LeaseIssueCode(StrEnum):
    """Stable, machine-readable issue codes (D0 Sections 19.2 and 19.3).

    Declared as an enum rather than bare strings so that a code can never be
    misspelled at a call site and so the D1 rule set is enumerable by a test.
    Only the codes D1 can actually raise are declared; the D2/D3/D4 codes D0
    lists are added by the gate that can raise them.
    """

    # --- property / analysis ---
    ANALYSIS_START_NOT_MONTH_ALIGNED = "ANALYSIS_START_NOT_MONTH_ALIGNED"
    PROPERTY_AREA_OUT_OF_DOMAIN = "PROPERTY_AREA_OUT_OF_DOMAIN"

    # --- identity ---
    EMPTY_SUITE_ID = "EMPTY_SUITE_ID"
    EMPTY_LEASE_ID = "EMPTY_LEASE_ID"
    DUPLICATE_SUITE_ID = "DUPLICATE_SUITE_ID"
    DUPLICATE_LEASE_ID = "DUPLICATE_LEASE_ID"
    UNKNOWN_SUITE_REFERENCE = "UNKNOWN_SUITE_REFERENCE"

    # --- area ---
    SUITE_AREA_OUT_OF_DOMAIN = "SUITE_AREA_OUT_OF_DOMAIN"
    LEASE_AREA_OUT_OF_DOMAIN = "LEASE_AREA_OUT_OF_DOMAIN"
    LEASE_AREA_MISMATCH = "LEASE_AREA_MISMATCH"
    LEASED_AREA_EXCEEDS_PROPERTY_AREA = "LEASED_AREA_EXCEEDS_PROPERTY_AREA"

    # --- dates ---
    LEASE_DATE_NOT_MONTH_ALIGNED = "LEASE_DATE_NOT_MONTH_ALIGNED"
    LEASE_EXPIRES_BEFORE_COMMENCEMENT = "LEASE_EXPIRES_BEFORE_COMMENCEMENT"
    LEASE_POSSESSION_AFTER_RENT_START = "LEASE_POSSESSION_AFTER_RENT_START"
    LEASE_EXPIRED_BEFORE_ANALYSIS_START = "LEASE_EXPIRED_BEFORE_ANALYSIS_START"
    OVERLAPPING_LEASES_IN_SUITE = "OVERLAPPING_LEASES_IN_SUITE"

    # --- rent ---
    BASE_RENT_OUT_OF_DOMAIN = "BASE_RENT_OUT_OF_DOMAIN"
    ESCALATION_OUT_OF_DOMAIN = "ESCALATION_OUT_OF_DOMAIN"

    # --- numeric ---
    NON_FINITE_VALUE = "NON_FINITE_VALUE"

    # --- warnings ---
    AREA_SHORTFALL_TREATED_AS_COMMON_AREA = "AREA_SHORTFALL_TREATED_AS_COMMON_AREA"


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseValidationIssue:
    """One deterministic leasing validation finding.

    ``path`` locates the finding in the submitted input using the same
    dotted/indexed form the future review UI will anchor a row against --
    for example ``"leases[3].lease_expiration_date"`` or
    ``"suites[0].suite_area_sf"``.
    """

    code: LeaseIssueCode
    path: str
    message: str
    severity: LeaseIssueSeverity = LeaseIssueSeverity.ERROR


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseValidationResult:
    """The complete outcome of validating one Lease-Level input set.

    ``errors`` and ``warnings`` are each already ordered deterministically
    (see ``validate_lease_level_inputs``); ``issues`` preserves the single
    canonical order both were partitioned from, so a consumer that wants one
    merged list never has to re-derive the ordering.
    """

    issues: tuple[LeaseValidationIssue, ...] = ()

    errors: tuple[LeaseValidationIssue, ...] = field(init=False)
    warnings: tuple[LeaseValidationIssue, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "errors",
            tuple(
                issue
                for issue in self.issues
                if issue.severity is LeaseIssueSeverity.ERROR
            ),
        )
        object.__setattr__(
            self,
            "warnings",
            tuple(
                issue
                for issue in self.issues
                if issue.severity is LeaseIssueSeverity.WARNING
            ),
        )

    @property
    def is_valid(self) -> bool:
        """``True`` when no ERROR was raised. Warnings never make an input
        invalid."""

        return not self.errors


class LeaseValidationError(ValueError):
    """Raised when leasing validation produced at least one ERROR.

    Carries the whole ``LeaseValidationResult`` -- including any warnings
    raised alongside the errors -- so a caller never has to re-run validation
    to see the full picture. Mirrors ``anchor.validation.InputValidationError``
    in spirit (an ordered collection of deterministic issues), without
    importing from or modifying it.
    """

    def __init__(self, result: LeaseValidationResult) -> None:
        if not result.errors:
            raise ValueError(
                "LeaseValidationError requires a result with at least one error."
            )
        self.result = result
        super().__init__("\n".join(issue.message for issue in result.errors))


# =============================================================================
# Date helpers
#
# Private at D1.0. D1.1 introduces ``anchor.leasing.calendar`` and owns the
# public month-identity surface (``month_index``, ``build_model_months``,
# ``is_first_day_of_month``, ``is_last_day_of_month``); these helpers move
# there and this module imports them, rather than a second copy existing.
# =============================================================================


def _is_first_day_of_month(value: date) -> bool:
    return value.day == 1


def _is_last_day_of_month(value: date) -> bool:
    """``True`` when ``value`` is the final calendar day of its own month.

    Calendar-aware by construction: February 29 is the last day of February
    in a leap year and February 28 is the last day in a common year, and this
    returns the correct answer for both without a special case.
    """

    return value.day == calendar.monthrange(value.year, value.month)[1]


def _month_key(value: date) -> int:
    """An absolute, origin-free month ordinal: ``year * 12 + month``.

    Strictly increasing in calendar month, so comparing two ``_month_key``
    values answers "same month / earlier month / later month" exactly. It is
    order-isomorphic to D1.1's 1-based ``month_index`` (which is this value
    minus the analysis start's, plus one) but needs no origin and builds no
    calendar, so the two time-aware rules below can be expressed at D1.0
    without pre-empting D1.1.
    """

    return value.year * 12 + value.month


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


# =============================================================================
# Validation
# =============================================================================


def _issue(
    code: LeaseIssueCode,
    path: str,
    message: str,
    severity: LeaseIssueSeverity = LeaseIssueSeverity.ERROR,
) -> LeaseValidationIssue:
    return LeaseValidationIssue(
        code=code, path=path, message=message, severity=severity
    )


def _validate_property(
    property_inputs: LeaseLevelPropertyInputs,
) -> list[LeaseValidationIssue]:
    issues: list[LeaseValidationIssue] = []

    if not _is_first_day_of_month(property_inputs.analysis_start_date):
        issues.append(
            _issue(
                LeaseIssueCode.ANALYSIS_START_NOT_MONTH_ALIGNED,
                "property.analysis_start_date",
                f"analysis_start_date {property_inputs.analysis_start_date.isoformat()} "
                "must be the first day of a calendar month.",
            )
        )

    area = property_inputs.property_area_sf
    if not _is_finite_number(area):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                "property.property_area_sf",
                "property_area_sf must be a finite number.",
            )
        )
    elif area <= 0:
        issues.append(
            _issue(
                LeaseIssueCode.PROPERTY_AREA_OUT_OF_DOMAIN,
                "property.property_area_sf",
                f"property_area_sf {area!r} must be greater than 0.",
            )
        )

    return issues


def _validate_suites(suites: tuple[Suite, ...]) -> list[LeaseValidationIssue]:
    issues: list[LeaseValidationIssue] = []
    seen: set[str] = set()

    for index, suite in enumerate(suites):
        path = f"suites[{index}]"

        if not suite.suite_id or not suite.suite_id.strip():
            issues.append(
                _issue(
                    LeaseIssueCode.EMPTY_SUITE_ID,
                    f"{path}.suite_id",
                    "suite_id must be a non-empty identifier.",
                )
            )
        elif suite.suite_id in seen:
            issues.append(
                _issue(
                    LeaseIssueCode.DUPLICATE_SUITE_ID,
                    f"{path}.suite_id",
                    f"suite_id {suite.suite_id!r} is declared more than once.",
                )
            )
        else:
            seen.add(suite.suite_id)

        area = suite.suite_area_sf
        if not _is_finite_number(area):
            issues.append(
                _issue(
                    LeaseIssueCode.NON_FINITE_VALUE,
                    f"{path}.suite_area_sf",
                    "suite_area_sf must be a finite number.",
                )
            )
        elif area <= 0:
            issues.append(
                _issue(
                    LeaseIssueCode.SUITE_AREA_OUT_OF_DOMAIN,
                    f"{path}.suite_area_sf",
                    f"suite_area_sf {area!r} must be greater than 0.",
                )
            )

    return issues


def _validate_lease(
    lease: Lease,
    *,
    path: str,
    suites_by_id: dict[str, Suite],
    analysis_start_date: date,
    seen_lease_ids: set[str],
) -> list[LeaseValidationIssue]:
    """Validate one lease in isolation, in canonical field order.

    Field order here is the order the fields are declared on ``Lease``:
    identity, then suite reference, then area, then dates, then rent. Keeping
    it fixed is what makes the emitted issue sequence deterministic.
    """

    issues: list[LeaseValidationIssue] = []

    # --- identity ---
    if not lease.lease_id or not lease.lease_id.strip():
        issues.append(
            _issue(
                LeaseIssueCode.EMPTY_LEASE_ID,
                f"{path}.lease_id",
                "lease_id must be a non-empty identifier.",
            )
        )
    elif lease.lease_id in seen_lease_ids:
        issues.append(
            _issue(
                LeaseIssueCode.DUPLICATE_LEASE_ID,
                f"{path}.lease_id",
                f"lease_id {lease.lease_id!r} is declared more than once.",
            )
        )
    else:
        seen_lease_ids.add(lease.lease_id)

    suite = suites_by_id.get(lease.suite_id)
    if suite is None:
        issues.append(
            _issue(
                LeaseIssueCode.UNKNOWN_SUITE_REFERENCE,
                f"{path}.suite_id",
                f"suite_id {lease.suite_id!r} matches no declared Suite.",
            )
        )

    # --- area ---
    leased_area = lease.leased_area_sf
    if not _is_finite_number(leased_area):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                f"{path}.leased_area_sf",
                "leased_area_sf must be a finite number.",
            )
        )
    elif leased_area <= 0:
        issues.append(
            _issue(
                LeaseIssueCode.LEASE_AREA_OUT_OF_DOMAIN,
                f"{path}.leased_area_sf",
                f"leased_area_sf {leased_area!r} must be greater than 0.",
            )
        )
    elif suite is not None and _is_finite_number(suite.suite_area_sf):
        # D0 Section 4.4.1 -- one suite is one leasable unit in D1-D3. A
        # physically subdivided suite is modeled as two Suite rows, never as
        # two partial leases on one suite.
        if leased_area != suite.suite_area_sf:
            issues.append(
                _issue(
                    LeaseIssueCode.LEASE_AREA_MISMATCH,
                    f"{path}.leased_area_sf",
                    f"leased_area_sf {leased_area!r} must equal suite "
                    f"{lease.suite_id!r} area {suite.suite_area_sf!r}; "
                    "a subdivided suite is modeled as separate Suite rows.",
                )
            )

    # --- dates ---
    if not _is_first_day_of_month(lease.rent_commencement_date):
        issues.append(
            _issue(
                LeaseIssueCode.LEASE_DATE_NOT_MONTH_ALIGNED,
                f"{path}.rent_commencement_date",
                f"rent_commencement_date {lease.rent_commencement_date.isoformat()} "
                "must be the first day of a calendar month.",
            )
        )

    if not _is_last_day_of_month(lease.lease_expiration_date):
        issues.append(
            _issue(
                LeaseIssueCode.LEASE_DATE_NOT_MONTH_ALIGNED,
                f"{path}.lease_expiration_date",
                f"lease_expiration_date {lease.lease_expiration_date.isoformat()} "
                "must be the last day of a calendar month.",
            )
        )

    if lease.lease_expiration_date < lease.rent_commencement_date:
        issues.append(
            _issue(
                LeaseIssueCode.LEASE_EXPIRES_BEFORE_COMMENCEMENT,
                f"{path}.lease_expiration_date",
                f"lease_expiration_date {lease.lease_expiration_date.isoformat()} "
                "must not precede rent_commencement_date "
                f"{lease.rent_commencement_date.isoformat()}.",
            )
        )

    if (
        lease.lease_start_date is not None
        and lease.lease_start_date > lease.rent_commencement_date
    ):
        issues.append(
            _issue(
                LeaseIssueCode.LEASE_POSSESSION_AFTER_RENT_START,
                f"{path}.lease_start_date",
                f"lease_start_date {lease.lease_start_date.isoformat()} must not "
                "follow rent_commencement_date "
                f"{lease.rent_commencement_date.isoformat()}.",
            )
        )

    if _month_key(lease.lease_expiration_date) < _month_key(analysis_start_date):
        issues.append(
            _issue(
                LeaseIssueCode.LEASE_EXPIRED_BEFORE_ANALYSIS_START,
                f"{path}.lease_expiration_date",
                f"lease {lease.lease_id!r} expired "
                f"{lease.lease_expiration_date.isoformat()}, before the analysis "
                f"start {analysis_start_date.isoformat()}; it is not a lease of "
                "this deal.",
            )
        )

    # --- rent ---
    base_rent = lease.base_rent_psf
    if not _is_finite_number(base_rent):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                f"{path}.base_rent_psf",
                "base_rent_psf must be a finite number.",
            )
        )
    elif base_rent < 0:
        issues.append(
            _issue(
                LeaseIssueCode.BASE_RENT_OUT_OF_DOMAIN,
                f"{path}.base_rent_psf",
                f"base_rent_psf {base_rent!r} must be greater than or equal to 0.",
            )
        )

    escalation = lease.escalation_pct
    if not _is_finite_number(escalation):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                f"{path}.escalation_pct",
                "escalation_pct must be a finite number.",
            )
        )
    elif escalation <= -1:
        # Anchor's frozen convention for a compounding annual rate: a hard
        # floor at -1 exclusive, no ceiling. At exactly -1 the series
        # collapses to zero; below it, (1 + g) is negative and the rent
        # alternates sign every year, which no lease does.
        issues.append(
            _issue(
                LeaseIssueCode.ESCALATION_OUT_OF_DOMAIN,
                f"{path}.escalation_pct",
                f"escalation_pct {escalation!r} must be greater than -1.",
            )
        )

    return issues


def _validate_suite_occupancy_overlap(
    leases: tuple[Lease, ...],
) -> list[LeaseValidationIssue]:
    """One suite may never be economically occupied by two leases at once.

    Overlap is evaluated on each lease's **economic occupancy interval**,
    ``[rent_commencement_date, lease_expiration_date]``, reduced to absolute
    month keys. ``lease_start_date`` (possession) is deliberately not
    consulted: it is informational and never enters an economic calculation,
    so two leases whose possession periods touch but whose rent-paying
    periods do not are not an overlap.

    Because ``lease_expiration_date`` is inclusive and month-aligned,
    back-to-back leases do not overlap: an expiration of 2028-03-31 (month
    key M) and a commencement of 2028-04-01 (month key M+1) are adjacent, not
    overlapping.

    Without this rule, two leases covering the same month in one suite would
    both collect that month's rent in D1.2 -- double-counted revenue, and
    physically impossible occupancy.
    """

    issues: list[LeaseValidationIssue] = []

    indexed = tuple(enumerate(leases))
    for position, (index_a, lease_a) in enumerate(indexed):
        first_a = _month_key(lease_a.rent_commencement_date)
        last_a = _month_key(lease_a.lease_expiration_date)
        for index_b, lease_b in indexed[position + 1 :]:
            if lease_a.suite_id != lease_b.suite_id:
                continue
            first_b = _month_key(lease_b.rent_commencement_date)
            last_b = _month_key(lease_b.lease_expiration_date)
            if first_a <= last_b and first_b <= last_a:
                issues.append(
                    _issue(
                        LeaseIssueCode.OVERLAPPING_LEASES_IN_SUITE,
                        f"leases[{index_b}].rent_commencement_date",
                        f"lease {lease_b.lease_id!r} occupies suite "
                        f"{lease_b.suite_id!r} during months already occupied by "
                        f"lease {lease_a.lease_id!r} "
                        f"(leases[{index_a}]); one suite cannot be leased twice "
                        "in the same month.",
                    )
                )

    return issues


def _validate_area_reconciliation(
    property_inputs: LeaseLevelPropertyInputs, suites: tuple[Suite, ...]
) -> list[LeaseValidationIssue]:
    """Reconcile the sum of suite areas against the property's rentable area.

    Over-allocation is an ERROR: a rent roll whose suites exceed the building
    cannot be underwritten. A shortfall is a WARNING, not an error -- lobbies,
    corridors and mechanical space are legitimately non-leasable -- but the
    analyst must know, because physical occupancy is then computed on a
    denominator that includes area no lease can ever fill.

    Skipped entirely when any input area is non-finite or non-positive; those
    have already produced their own, more specific errors, and summing them
    would only add noise.
    """

    if not _is_finite_number(property_inputs.property_area_sf):
        return []
    if property_inputs.property_area_sf <= 0:
        return []
    if not all(
        _is_finite_number(suite.suite_area_sf) and suite.suite_area_sf > 0
        for suite in suites
    ):
        return []

    total_suite_area = sum(suite.suite_area_sf for suite in suites)

    if total_suite_area > property_inputs.property_area_sf:
        return [
            _issue(
                LeaseIssueCode.LEASED_AREA_EXCEEDS_PROPERTY_AREA,
                "property.property_area_sf",
                f"suite areas total {total_suite_area!r} SF, which exceeds "
                f"property_area_sf {property_inputs.property_area_sf!r}.",
            )
        ]

    if total_suite_area < property_inputs.property_area_sf:
        return [
            _issue(
                LeaseIssueCode.AREA_SHORTFALL_TREATED_AS_COMMON_AREA,
                "property.property_area_sf",
                f"suite areas total {total_suite_area!r} SF against "
                f"property_area_sf {property_inputs.property_area_sf!r}; the "
                "difference is treated as common area and is included in the "
                "occupancy denominator.",
                LeaseIssueSeverity.WARNING,
            )
        ]

    return []


def validate_lease_level_inputs(
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
) -> LeaseValidationResult:
    """Validate one complete Lease-Level input set, deterministically.

    Returns a ``LeaseValidationResult`` whether or not errors were found;
    ``require_valid_lease_level_inputs`` is the variant that raises. Warnings
    never prevent a valid result.

    **Issue ordering** (D0 Section 19.1) is fixed and reproducible:
    property-level issues first, then suites in declared order, then leases in
    declared order with each lease's own fields in canonical field order, then
    the cross-lease suite-overlap rule, then area reconciliation. Nothing here
    iterates a ``set`` or ``dict`` to produce output, so repeated runs emit
    byte-identical sequences.

    No value is defaulted, coerced, rounded, or inferred: a missing or
    malformed input becomes an issue, never a substituted number.
    """

    suite_tuple = tuple(suites)
    lease_tuple = tuple(leases)

    issues: list[LeaseValidationIssue] = []
    issues.extend(_validate_property(property_inputs))
    issues.extend(_validate_suites(suite_tuple))

    # First declaration of a suite_id wins as the area reference; a duplicate
    # id has already produced its own DUPLICATE_SUITE_ID error.
    suites_by_id: dict[str, Suite] = {}
    for suite in suite_tuple:
        suites_by_id.setdefault(suite.suite_id, suite)

    seen_lease_ids: set[str] = set()
    for index, lease in enumerate(lease_tuple):
        issues.extend(
            _validate_lease(
                lease,
                path=f"leases[{index}]",
                suites_by_id=suites_by_id,
                analysis_start_date=property_inputs.analysis_start_date,
                seen_lease_ids=seen_lease_ids,
            )
        )

    issues.extend(_validate_suite_occupancy_overlap(lease_tuple))
    issues.extend(_validate_area_reconciliation(property_inputs, suite_tuple))

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_lease_level_inputs(
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
) -> LeaseValidationResult:
    """Validate and raise ``LeaseValidationError`` if any ERROR was found.

    Returns the full result (including warnings) when valid, so a caller that
    wants both the go-ahead and the warnings needs exactly one call.
    """

    result = validate_lease_level_inputs(property_inputs, suites, leases)
    if result.errors:
        raise LeaseValidationError(result)
    return result
