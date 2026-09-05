"""Sprint D Gate D1.0 -- leasing-scoped validation.

Restates
``docs/plans/2026-09-04-anchor-lease-level-underwriting-d0-architecture.md``
Section 19; that document governs except where this module records an
explicit, reviewed override below.

**One deliberate departure from D0, approved at D1.0 human financial
review.** D0 Sections 18.4 and 19.3 permit ``sum(suite_area_sf)`` to fall
short of the property's area, reporting the residual as a
``AREA_SHORTFALL_TREATED_AS_COMMON_AREA`` *warning* and inferring that the
difference is common area. That convention is rejected: a generic building
area is not a valid denominator for lease-level occupancy, and inferring
common area from a residual lets unmodeled leasable space silently dilute
occupancy. Anchor instead requires that every rentable square foot be
accounted for by a suite, with vacant space declared explicitly as a
``Suite`` carrying no lease. The reconciliation is exact and any mismatch is
a ``RENTABLE_AREA_NOT_RECONCILED`` **ERROR**; the warning code no longer
exists. The contract field is named ``rentable_area_sf`` to match the
meaning D0 already assigned it ("Total rentable area", Section 4.2). D0
itself is unchanged by this gate.

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

No rent and no schedule is computed anywhere in this module. Every rule that
reasons about time -- expiry before the analysis start, same-suite overlap, and
the two D1.1 horizon warnings -- expresses itself in canonical model months via
``anchor.leasing.calendar.month_index``, so there is exactly one notion of
"which month" in the package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from math import floor, isfinite
from typing import Iterable

from .contracts import ModelMonth  # noqa: F401  (used in signatures below)
from .calendar import (
    is_first_day_of_month,
    is_last_day_of_month,
    month_index,
    projection_month_count,
)
from .contracts import (
    EscalationBasis,
    Lease,
    LeaseLevelPropertyInputs,
    LeaseOrigin,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RecoverableExpensePool,
    Suite,
)


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
    RENTABLE_AREA_OUT_OF_DOMAIN = "RENTABLE_AREA_OUT_OF_DOMAIN"

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
    RENTABLE_AREA_NOT_RECONCILED = "RENTABLE_AREA_NOT_RECONCILED"

    # --- dates ---
    LEASE_DATE_NOT_MONTH_ALIGNED = "LEASE_DATE_NOT_MONTH_ALIGNED"
    LEASE_EXPIRES_BEFORE_COMMENCEMENT = "LEASE_EXPIRES_BEFORE_COMMENCEMENT"
    LEASE_POSSESSION_AFTER_RENT_START = "LEASE_POSSESSION_AFTER_RENT_START"
    LEASE_EXPIRED_BEFORE_ANALYSIS_START = "LEASE_EXPIRED_BEFORE_ANALYSIS_START"
    OVERLAPPING_LEASES_IN_SUITE = "OVERLAPPING_LEASES_IN_SUITE"

    # --- horizon (D1.1; warnings, evaluated only when a hold period is given)
    LEASE_STARTS_AFTER_HORIZON = "LEASE_STARTS_AFTER_HORIZON"
    LEASE_EXTENDS_BEYOND_HORIZON = "LEASE_EXTENDS_BEYOND_HORIZON"

    # --- market leasing (D2.1) ---
    MARKET_RENT_OUT_OF_DOMAIN = "MARKET_RENT_OUT_OF_DOMAIN"
    MARKET_RENT_GROWTH_OUT_OF_DOMAIN = "MARKET_RENT_GROWTH_OUT_OF_DOMAIN"
    MARKET_LEASING_DEFAULT_REQUIRED = "MARKET_LEASING_DEFAULT_REQUIRED"

    # --- renewal rollover (D2.2) ---
    RENEWAL_RENT_OUT_OF_DOMAIN = "RENEWAL_RENT_OUT_OF_DOMAIN"
    RENEWAL_RENT_SPREAD_OUT_OF_DOMAIN = "RENEWAL_RENT_SPREAD_OUT_OF_DOMAIN"
    RENEWAL_TERM_OUT_OF_DOMAIN = "RENEWAL_TERM_OUT_OF_DOMAIN"
    SUCCESSOR_ESCALATION_OUT_OF_DOMAIN = "SUCCESSOR_ESCALATION_OUT_OF_DOMAIN"
    SUCCESSOR_LEASE_NAMES_A_TENANT = "SUCCESSOR_LEASE_NAMES_A_TENANT"

    # --- downtime and free rent (D2.3) ---
    DOWNTIME_OUT_OF_DOMAIN = "DOWNTIME_OUT_OF_DOMAIN"
    FREE_RENT_OUT_OF_DOMAIN = "FREE_RENT_OUT_OF_DOMAIN"
    NEW_TERM_OUT_OF_DOMAIN = "NEW_TERM_OUT_OF_DOMAIN"
    FREE_RENT_EXCEEDS_OCCUPIABLE_TERM = "FREE_RENT_EXCEEDS_OCCUPIABLE_TERM"

    # --- leasing costs (D2.4) ---
    TI_OUT_OF_DOMAIN = "TI_OUT_OF_DOMAIN"
    LC_PCT_OUT_OF_DOMAIN = "LC_PCT_OUT_OF_DOMAIN"
    UNSUPPORTED_LEASING_COMMISSION_METHOD = "UNSUPPORTED_LEASING_COMMISSION_METHOD"

    # --- probability composition (D2.5) ---
    RENEWAL_PROBABILITY_OUT_OF_DOMAIN = "RENEWAL_PROBABILITY_OUT_OF_DOMAIN"
    WEIGHTED_ROLLOVER_APPLIED = "WEIGHTED_ROLLOVER_APPLIED"

    # --- expense recoveries (D3.1) ---
    RECOVERABLE_EXPENSES_OUT_OF_DOMAIN = "RECOVERABLE_EXPENSES_OUT_OF_DOMAIN"
    RECOVERY_POOL_NOT_ALIGNED = "RECOVERY_POOL_NOT_ALIGNED"
    MISSING_MODIFIED_GROSS_RECOVERY_BASIS = (
        "MISSING_MODIFIED_GROSS_RECOVERY_BASIS"
    )

    # --- rent ---
    BASE_RENT_OUT_OF_DOMAIN = "BASE_RENT_OUT_OF_DOMAIN"
    ESCALATION_OUT_OF_DOMAIN = "ESCALATION_OUT_OF_DOMAIN"
    ESCALATION_BASIS_REQUIRES_ZERO_ESCALATION = (
        "ESCALATION_BASIS_REQUIRES_ZERO_ESCALATION"
    )

    # --- numeric ---
    NON_FINITE_VALUE = "NON_FINITE_VALUE"


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
# Numeric helpers
#
# The date predicates and month identity this module needs live in
# ``anchor.leasing.calendar`` (D1.1) and are imported above. D1.0's private
# copies were removed there so month-boundary logic exists in exactly one
# place; behavior is unchanged.
#
# D1.0's private ``_month_key`` is likewise gone: every rule below that
# reasons about time now uses the public, analysis-anchored ``month_index``.
# Both surviving uses are translation-invariant comparisons, so anchoring them
# leaves their semantics bit-identical while removing a competing notion of
# "which month".
# =============================================================================


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _areas_reconcile(total_suite_area: float, rentable_area: float) -> bool:
    """Whether two area figures agree under Anchor's numeric-comparison rule.

    Mirrors the scaled tolerance already used in production by
    ``anchor.ingestion.classifier_provider._isclose``
    (``abs(a - b) <= 1e-9 * max(1.0, |a|, |b|)``) rather than introducing a
    second, competing convention.

    An exact ``==`` would be wrong here: ``sum()`` over many suite areas
    accumulates ordinary IEEE-754 last-bit drift that scales with both the
    suite count and the building size, so a rent roll that reconciles
    perfectly on paper could fail on floating-point noise alone. A fixed
    absolute epsilon would be equally wrong in the other direction -- tight
    enough for a 10,000 SF building, too tight for a 1,000,000 SF one. The
    scaled form is correct at any building size and is fully deterministic:
    the same inputs always give the same answer.

    The tolerance is deliberately far tighter than any real area discrepancy:
    at 1,000,000 SF it permits ``0.001`` SF -- about ``0.144`` square inches --
    so a genuine unmodeled floor can never slip through.
    """

    return abs(total_suite_area - rentable_area) <= 1e-9 * max(
        1.0, abs(total_suite_area), abs(rentable_area)
    )


def _months_within_tolerance(left: float, right: float) -> bool:
    """Whether two month counts are equal under Anchor's scaled comparison.

    The same form ``_areas_reconcile`` uses, for the same reason: an exact
    ``==`` would be wrong because ``frac(D)`` carries ordinary IEEE-754
    representation error, so a concession stated as exactly the maximum
    consumable amount could fail on floating-point noise alone. At the
    magnitudes involved -- months, rarely above a few hundred -- the tolerance
    is far tighter than any economically meaningful difference.
    """

    return abs(left - right) <= 1e-9 * max(1.0, abs(left), abs(right))


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

    if not is_first_day_of_month(property_inputs.analysis_start_date):
        issues.append(
            _issue(
                LeaseIssueCode.ANALYSIS_START_NOT_MONTH_ALIGNED,
                "property.analysis_start_date",
                f"analysis_start_date {property_inputs.analysis_start_date.isoformat()} "
                "must be the first day of a calendar month.",
            )
        )

    area = property_inputs.rentable_area_sf
    if not _is_finite_number(area):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                "property.rentable_area_sf",
                "rentable_area_sf must be a finite number.",
            )
        )
    elif area <= 0:
        issues.append(
            _issue(
                LeaseIssueCode.RENTABLE_AREA_OUT_OF_DOMAIN,
                "property.rentable_area_sf",
                f"rentable_area_sf {area!r} must be greater than 0.",
            )
        )

    return issues


def _validate_non_negative_months(
    value: object, *, path: str, field: str, code: LeaseIssueCode
) -> list[LeaseValidationIssue]:
    """Domain ``>= 0``, fractional permitted, for a duration in months.

    Shared by the downtime and free-rent fields on both branches so the four
    cannot drift apart. Fractional values are legitimate: an analyst may state
    ``4.5`` months of downtime or ``7.5`` months of free rent, and D2
    Sections 6 and 7 define both exactly.
    """

    if not _is_finite_number(value):
        return [
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                path,
                f"{field} must be a finite number of months.",
            )
        ]
    if value < 0:
        return [
            _issue(
                code,
                path,
                f"{field} {value!r} must be greater than or equal to 0.",
            )
        ]
    return []


def _validate_free_rent_over_grant(
    assumptions: MarketLeasingAssumptions,
    *,
    path: str,
    branch: str,
    term_months: object,
    downtime_months: object,
    free_rent_months: object,
) -> list[LeaseValidationIssue]:
    """D2 Section 7.5, approved at D2.3: the concession must be consumable.

    ```
    free_rent_months <= term_months - frac(downtime_months)
    ```

    Evaluated only when the three inputs are individually in domain -- a
    negative term or a non-finite downtime already has its own error, and
    stacking a derived complaint on top of it would report the same defect
    twice.

    The comparison uses the package's scaled numeric convention rather than a
    bare ``>``, so a concession stated as exactly the maximum survives the
    ordinary floating-point representation of ``frac(D)``.
    """

    if isinstance(term_months, bool) or not isinstance(term_months, int):
        return []
    if term_months < 1:
        return []
    if not _is_finite_number(downtime_months) or downtime_months < 0:
        return []
    if not _is_finite_number(free_rent_months) or free_rent_months < 0:
        return []

    maximum = term_months - (downtime_months - floor(downtime_months))
    if free_rent_months <= maximum or _months_within_tolerance(
        free_rent_months, maximum
    ):
        return []

    return [
        _issue(
            LeaseIssueCode.FREE_RENT_EXCEEDS_OCCUPIABLE_TERM,
            f"{path}.{branch}_free_rent_months",
            f"{branch}_free_rent_months {free_rent_months!r} exceeds the "
            f"{maximum!r} month-equivalents the successor term can absorb "
            f"({branch}_term_months {term_months!r} less the "
            f"{downtime_months - floor(downtime_months)!r} fractional month of "
            f"{branch}_downtime_months {downtime_months!r}). The concession "
            "would be silently discarded.",
        )
    ]


def _validate_market_leasing_assumptions(
    assumptions: MarketLeasingAssumptions, *, path: str
) -> list[LeaseValidationIssue]:
    """Domain rules for one ``MarketLeasingAssumptions`` record (D0 Section 4.5).

    Exactly D0's two D2.1 domains, neither widened nor tightened:

    - ``market_rent_psf >= 0``. Zero is **permitted** and means a market rent
      of zero, which computes to exactly zero in every period. It is never
      reinterpreted as vacancy, missing data, or free rent, so it is not an
      error and not a warning.
    - ``market_rent_growth > -1``. This is the same lower bound every other
      Anchor compounding rate carries, so a declining market is expressible;
      exactly ``-1`` is excluded because it collapses the market to zero at
      the first anniversary and stays there, which is a degenerate assumption
      rather than a rate.

    The D2.3 downtime and free-rent domains (D0 Section 4.5, D2 Sections 6-7),
    applied identically to both branches:

    - ``renewal_downtime_months``, ``new_downtime_months`` ``>= 0``, fractional
      permitted. Zero is the ordinary renewal case, not an absence.
    - ``renewal_free_rent_months``, ``new_free_rent_months`` ``>= 0``,
      fractional permitted, denominated in full month-equivalents of
      base-rent abatement.
    - ``new_term_months >= 1``, a whole number of months.

    Plus the **free-rent over-grant** rule (D2 Section 7.5, approved at D2.3),
    checked per branch:

    ```
    free_rent_months <= term_months - frac(downtime_months)
    ```

    The right-hand side is the largest concession the waterfall can absorb over
    the successor's term: the first period contributes ``1 - frac(D)`` and the
    remaining ``T - 1`` periods contribute ``1.0`` each. A larger concession
    cannot be fully consumed within the lease, and silently discarding the
    remainder would understate it invisibly -- exactly the failure the
    sequential waterfall replaced. Anchor therefore refuses rather than
    capping, discarding, carrying the remainder past expiration, or extending
    the term to absorb it.

    **The bound uses the FULL contractual term, never the visible
    projection.** A 60-month successor of which only eight months fall inside
    the canonical window may legitimately carry a twelve-month concession; the
    schedule simply ends with free rent still being consumed. Validating
    against the visible portion would reject sound underwriting because of
    where the hold period happens to end.

    The D2.5 probability domain (D0 Section 4.5, D2 HD-D2-1):

    - ``renewal_probability`` finite, ``0 <= p <= 1``. There is deliberately no
      ``new_tenant_probability`` input to cross-check: it is ``1 - p`` by
      construction, so the pair cannot disagree and no sums-to-one rule is
      needed.

    Plus one **WARNING**, ``WEIGHTED_ROLLOVER_APPLIED``, whenever
    ``0 < p < 1`` (D0 Section 8.4, failure mode FM-D2-18). The composed result
    is then an expected value corresponding to no single real-world outcome: at
    ``p = 0.65`` it pays a rent no actual tenant would pay. The economics are
    correct and the analysis proceeds -- but an interface must never present
    that figure as a known tenancy, and the warning is what makes the
    convention visible rather than assumed. At the endpoints the result *is* a
    single scenario, so no warning fires.

    The D2.4 leasing-cost domains (D0 Section 4.5), applied per branch:

    - ``renewal_ti_psf``, ``new_ti_psf`` ``>= 0``, in ``$/SF``. Zero is a real
      allowance -- a renewal often carries none -- never an absence.
    - ``renewal_lc_pct``, ``new_lc_pct`` ``0 <= x <= 1``. The upper bound is
      D0's, not invented here: a commission exceeding the entire contractual
      rent stream is not a rate.
    - ``leasing_commission_method`` must be a supported
      ``LeasingCommissionMethod``. D2 implements exactly one member
      (D0 Section 12.3); an unsupported method is refused rather than silently
      computed under another method's rule.

    The D2.2 renewal domains, likewise exactly as D0 Section 4.5 states them:

    - ``renewal_rent_psf >= 0``, or ``None``. ``None`` means "no explicit
      renewal level was supplied" and sends pricing down the spread path
      (D0 Section 24.3); it is never read as zero.
    - ``renewal_rent_spread > -1``. ``0.0`` renews at market; negative is a
      discount and positive a premium. The bound excludes exactly ``-1``,
      which would price every renewal at zero.
    - ``renewal_term_months >= 1``, a whole number of months. Booleans are
      rejected explicitly: ``True`` is an ``int`` in Python and a one-month
      term arrived at by accident is not a term.
    - ``successor_escalation_pct > -1``, the same lower bound every other
      Anchor compounding rate carries.

    The record is checked wherever it appears -- as the property default or as
    a suite's full override -- by one function, so the two can never drift
    apart. There is no "incomplete override" rule to write: every field is
    required on the dataclass and none has a default, so an all-or-nothing
    override (D0 Section 24.2) is enforced structurally at construction.
    """

    issues: list[LeaseValidationIssue] = []

    rent = assumptions.market_rent_psf
    if not _is_finite_number(rent):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                f"{path}.market_rent_psf",
                "market_rent_psf must be a finite number.",
            )
        )
    elif rent < 0:
        issues.append(
            _issue(
                LeaseIssueCode.MARKET_RENT_OUT_OF_DOMAIN,
                f"{path}.market_rent_psf",
                f"market_rent_psf {rent!r} must be greater than or equal to 0.",
            )
        )

    growth = assumptions.market_rent_growth
    if not _is_finite_number(growth):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                f"{path}.market_rent_growth",
                "market_rent_growth must be a finite number.",
            )
        )
    elif growth <= -1:
        issues.append(
            _issue(
                LeaseIssueCode.MARKET_RENT_GROWTH_OUT_OF_DOMAIN,
                f"{path}.market_rent_growth",
                f"market_rent_growth {growth!r} must be greater than -1.",
            )
        )

    renewal_rent = assumptions.renewal_rent_psf
    if renewal_rent is not None:
        if not _is_finite_number(renewal_rent):
            issues.append(
                _issue(
                    LeaseIssueCode.NON_FINITE_VALUE,
                    f"{path}.renewal_rent_psf",
                    "renewal_rent_psf must be a finite number or None.",
                )
            )
        elif renewal_rent < 0:
            issues.append(
                _issue(
                    LeaseIssueCode.RENEWAL_RENT_OUT_OF_DOMAIN,
                    f"{path}.renewal_rent_psf",
                    f"renewal_rent_psf {renewal_rent!r} must be greater than "
                    "or equal to 0, or None.",
                )
            )

    spread = assumptions.renewal_rent_spread
    if not _is_finite_number(spread):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                f"{path}.renewal_rent_spread",
                "renewal_rent_spread must be a finite number.",
            )
        )
    elif spread <= -1:
        issues.append(
            _issue(
                LeaseIssueCode.RENEWAL_RENT_SPREAD_OUT_OF_DOMAIN,
                f"{path}.renewal_rent_spread",
                f"renewal_rent_spread {spread!r} must be greater than -1.",
            )
        )

    term = assumptions.renewal_term_months
    if isinstance(term, bool) or not isinstance(term, int):
        issues.append(
            _issue(
                LeaseIssueCode.RENEWAL_TERM_OUT_OF_DOMAIN,
                f"{path}.renewal_term_months",
                f"renewal_term_months {term!r} must be a whole number of "
                "months.",
            )
        )
    elif term < 1:
        issues.append(
            _issue(
                LeaseIssueCode.RENEWAL_TERM_OUT_OF_DOMAIN,
                f"{path}.renewal_term_months",
                f"renewal_term_months {term!r} must be at least 1.",
            )
        )

    escalation = assumptions.successor_escalation_pct
    if not _is_finite_number(escalation):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                f"{path}.successor_escalation_pct",
                "successor_escalation_pct must be a finite number.",
            )
        )
    elif escalation <= -1:
        issues.append(
            _issue(
                LeaseIssueCode.SUCCESSOR_ESCALATION_OUT_OF_DOMAIN,
                f"{path}.successor_escalation_pct",
                f"successor_escalation_pct {escalation!r} must be greater "
                "than -1.",
            )
        )

    new_term = assumptions.new_term_months
    if isinstance(new_term, bool) or not isinstance(new_term, int):
        issues.append(
            _issue(
                LeaseIssueCode.NEW_TERM_OUT_OF_DOMAIN,
                f"{path}.new_term_months",
                f"new_term_months {new_term!r} must be a whole number of "
                "months.",
            )
        )
    elif new_term < 1:
        issues.append(
            _issue(
                LeaseIssueCode.NEW_TERM_OUT_OF_DOMAIN,
                f"{path}.new_term_months",
                f"new_term_months {new_term!r} must be at least 1.",
            )
        )

    for field_name in ("renewal_downtime_months", "new_downtime_months"):
        issues.extend(
            _validate_non_negative_months(
                getattr(assumptions, field_name),
                path=f"{path}.{field_name}",
                field=field_name,
                code=LeaseIssueCode.DOWNTIME_OUT_OF_DOMAIN,
            )
        )

    for field_name in ("renewal_free_rent_months", "new_free_rent_months"):
        issues.extend(
            _validate_non_negative_months(
                getattr(assumptions, field_name),
                path=f"{path}.{field_name}",
                field=field_name,
                code=LeaseIssueCode.FREE_RENT_OUT_OF_DOMAIN,
            )
        )

    for field_name, code in (
        ("renewal_ti_psf", LeaseIssueCode.TI_OUT_OF_DOMAIN),
        ("new_ti_psf", LeaseIssueCode.TI_OUT_OF_DOMAIN),
    ):
        value = getattr(assumptions, field_name)
        if not _is_finite_number(value):
            issues.append(
                _issue(
                    LeaseIssueCode.NON_FINITE_VALUE,
                    f"{path}.{field_name}",
                    f"{field_name} must be a finite number.",
                )
            )
        elif value < 0:
            issues.append(
                _issue(
                    code,
                    f"{path}.{field_name}",
                    f"{field_name} {value!r} must be greater than or equal "
                    "to 0.",
                )
            )

    for field_name in ("renewal_lc_pct", "new_lc_pct"):
        value = getattr(assumptions, field_name)
        if not _is_finite_number(value):
            issues.append(
                _issue(
                    LeaseIssueCode.NON_FINITE_VALUE,
                    f"{path}.{field_name}",
                    f"{field_name} must be a finite number.",
                )
            )
        elif not 0 <= value <= 1:
            issues.append(
                _issue(
                    LeaseIssueCode.LC_PCT_OUT_OF_DOMAIN,
                    f"{path}.{field_name}",
                    f"{field_name} {value!r} must be between 0 and 1 "
                    "inclusive.",
                )
            )

    probability = assumptions.renewal_probability
    if not _is_finite_number(probability):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                f"{path}.renewal_probability",
                "renewal_probability must be a finite number.",
            )
        )
    elif not 0 <= probability <= 1:
        issues.append(
            _issue(
                LeaseIssueCode.RENEWAL_PROBABILITY_OUT_OF_DOMAIN,
                f"{path}.renewal_probability",
                f"renewal_probability {probability!r} must be between 0 and 1 "
                "inclusive.",
            )
        )
    elif 0 < probability < 1:
        issues.append(
            _issue(
                LeaseIssueCode.WEIGHTED_ROLLOVER_APPLIED,
                f"{path}.renewal_probability",
                f"renewal_probability {probability!r} produces a "
                "probability-weighted expected rollover. The composed result "
                "is an expected value, not a signed lease, and must never be "
                "presented as a known tenancy.",
                LeaseIssueSeverity.WARNING,
            )
        )

    method = assumptions.leasing_commission_method
    if not isinstance(method, LeasingCommissionMethod):
        issues.append(
            _issue(
                LeaseIssueCode.UNSUPPORTED_LEASING_COMMISSION_METHOD,
                f"{path}.leasing_commission_method",
                f"leasing_commission_method {method!r} must be a "
                "LeasingCommissionMethod member.",
            )
        )

    issues.extend(
        _validate_free_rent_over_grant(
            assumptions,
            path=path,
            branch="renewal",
            term_months=assumptions.renewal_term_months,
            downtime_months=assumptions.renewal_downtime_months,
            free_rent_months=assumptions.renewal_free_rent_months,
        )
    )
    issues.extend(
        _validate_free_rent_over_grant(
            assumptions,
            path=path,
            branch="new",
            term_months=assumptions.new_term_months,
            downtime_months=assumptions.new_downtime_months,
            free_rent_months=assumptions.new_free_rent_months,
        )
    )

    return issues


def _validate_suite_market_leasing(
    suites: tuple[Suite, ...],
    *,
    market_leasing: MarketLeasingAssumptions | None,
) -> list[LeaseValidationIssue]:
    """D2.1 market-rent rules for the property default and every suite.

    Three rules, in declared suite order so the output stays deterministic:

    1. The property default, when supplied, satisfies its domains.
    2. Each suite's ``market_rent_psf`` rent-level override (D0 Section 24.1)
       satisfies the same ``>= 0`` domain as the field it replaces.
    3. Each suite's full ``market_leasing_override`` record satisfies both
       domains.

    Plus one structural rule: **a suite may not carry a market override with
    no property default in force.** D0 Section 4.5 states the property default
    is always present, and a suite supplying only a rent level has no growth
    rate without it. Rather than invent a growth rate, this is an
    ``MARKET_LEASING_DEFAULT_REQUIRED`` ERROR.

    When ``market_leasing`` is ``None`` and no suite declares a market field,
    no market rule is evaluated at all -- which is exactly the D1 rent-roll
    call, whose behaviour is therefore unchanged.

    Deliberately not written here: "override for unknown suite" and "duplicate
    suite override". Both are structurally impossible under the D0
    Section 4.3 architecture, where an override is a field **on** the ``Suite``
    rather than a free-standing record keyed by ``suite_id``. An override
    cannot name a suite that does not exist, and a suite declared twice is
    already a ``DUPLICATE_SUITE_ID`` error. Adding codes for unreachable
    states would imply a keyed-override design that D0 did not approve.
    """

    issues: list[LeaseValidationIssue] = []

    if market_leasing is not None:
        issues.extend(
            _validate_market_leasing_assumptions(
                market_leasing, path="market_leasing"
            )
        )

    for index, suite in enumerate(suites):
        path = f"suites[{index}]"
        declares_market = (
            suite.market_rent_psf is not None
            or suite.market_leasing_override is not None
        )

        if declares_market and market_leasing is None:
            issues.append(
                _issue(
                    LeaseIssueCode.MARKET_LEASING_DEFAULT_REQUIRED,
                    f"{path}.market_rent_psf"
                    if suite.market_leasing_override is None
                    else f"{path}.market_leasing_override",
                    f"suite {suite.suite_id!r} declares a market-rent override "
                    "but no property-level MarketLeasingAssumptions default was "
                    "supplied; the property default is always required.",
                )
            )

        suite_rent = suite.market_rent_psf
        if suite_rent is not None:
            if not _is_finite_number(suite_rent):
                issues.append(
                    _issue(
                        LeaseIssueCode.NON_FINITE_VALUE,
                        f"{path}.market_rent_psf",
                        "market_rent_psf must be a finite number.",
                    )
                )
            elif suite_rent < 0:
                issues.append(
                    _issue(
                        LeaseIssueCode.MARKET_RENT_OUT_OF_DOMAIN,
                        f"{path}.market_rent_psf",
                        f"market_rent_psf {suite_rent!r} must be greater than "
                        "or equal to 0.",
                    )
                )

        if suite.market_leasing_override is not None:
            issues.extend(
                _validate_market_leasing_assumptions(
                    suite.market_leasing_override,
                    path=f"{path}.market_leasing_override",
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
    if not is_first_day_of_month(lease.rent_commencement_date):
        issues.append(
            _issue(
                LeaseIssueCode.LEASE_DATE_NOT_MONTH_ALIGNED,
                f"{path}.rent_commencement_date",
                f"rent_commencement_date {lease.rent_commencement_date.isoformat()} "
                "must be the first day of a calendar month.",
            )
        )

    if not is_last_day_of_month(lease.lease_expiration_date):
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

    if month_index(lease.lease_expiration_date, analysis_start=analysis_start_date) < 1:
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
    elif lease.escalation_basis is EscalationBasis.NONE and escalation != 0.0:
        # "No escalation basis" and "a 3% escalation" are contradictory
        # instructions. Ignoring the percentage would silently pick one
        # reading; Anchor makes the analyst state which they meant. The
        # converse pairing -- LEASE_ANNIVERSARY with 0.0 -- is unambiguous
        # (a flat lease whose basis is stated anyway) and stays valid.
        issues.append(
            _issue(
                LeaseIssueCode.ESCALATION_BASIS_REQUIRES_ZERO_ESCALATION,
                f"{path}.escalation_pct",
                f"escalation_pct {escalation!r} must be 0.0 when "
                "escalation_basis is NONE; set a basis of LEASE_ANNIVERSARY "
                "to apply it, or 0.0 to state a flat rent.",
            )
        )

    # --- rollover provenance (D2.2) ---
    if lease.origin is LeaseOrigin.SUCCESSOR and lease.tenant_name is not None:
        # D0 Section 8.4, made unrepresentable rather than merely discouraged.
        # A successor is an underwriting assumption about what follows an
        # expiry; naming a tenant on one gives a modelled outcome documentary
        # certainty it does not have (failure mode FM-D2-18).
        issues.append(
            _issue(
                LeaseIssueCode.SUCCESSOR_LEASE_NAMES_A_TENANT,
                f"{path}.tenant_name",
                f"lease {lease.lease_id!r} has origin SUCCESSOR but names "
                f"tenant {lease.tenant_name!r}; a rollover successor is an "
                "underwriting assumption, never a known tenant.",
            )
        )

    return issues


def _validate_suite_occupancy_overlap(
    leases: tuple[Lease, ...], *, analysis_start_date: date
) -> list[LeaseValidationIssue]:
    """One suite may never be economically occupied by two leases at once.

    Overlap is evaluated on each lease's **economic occupancy interval**,
    ``[rent_commencement_date, lease_expiration_date]``, reduced to canonical
    model months. ``lease_start_date`` (possession) is deliberately not
    consulted: it is informational and never enters an economic calculation,
    so two leases whose possession periods touch but whose rent-paying
    periods do not are not an overlap.

    Anchoring the comparison to ``analysis_start_date`` is a translation of
    every index by the same constant, so the overlap relation is bit-identical
    to D1.0's origin-free formulation -- the anchoring exists only so the
    package has one notion of "which month".

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
        first_a = month_index(
            lease_a.rent_commencement_date, analysis_start=analysis_start_date
        )
        last_a = month_index(
            lease_a.lease_expiration_date, analysis_start=analysis_start_date
        )
        for index_b, lease_b in indexed[position + 1 :]:
            if lease_a.suite_id != lease_b.suite_id:
                continue
            first_b = month_index(
                lease_b.rent_commencement_date, analysis_start=analysis_start_date
            )
            last_b = month_index(
                lease_b.lease_expiration_date, analysis_start=analysis_start_date
            )
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


def _validate_horizon(
    leases: tuple[Lease, ...],
    *,
    analysis_start_date: date,
    hold_period: int,
) -> list[LeaseValidationIssue]:
    """Flag leases that fall outside the canonical projection window.

    Both rules are **WARNING**, per D0 Sections 6.4 and 19.3: neither makes
    the financial input ambiguous or incorrect, so neither may block analysis.

    The horizon is the **full canonical projection** -- ``12H + 12`` months,
    the acquisition hold plus the twelve forward exit-NOI months -- not merely
    the sale month at ``12H``. A lease running into the forward window is
    economically live there, because that window is what exit NOI is measured
    over (D0 Section 17.1).

    ``LEASE_STARTS_AFTER_HORIZON``: the lease's economic commencement falls
    entirely beyond the window, so it contributes nothing. Evaluated on
    ``rent_commencement_date``, never on the informational
    ``lease_start_date`` -- a possession or execution date must never
    determine economics.

    ``LEASE_EXTENDS_BEYOND_HORIZON``: the contractual term outlasts the
    window. Entirely normal; noted so the analyst knows revenue is truncated
    at the horizon while the D2 leasing-commission basis is not (D0
    Section 12.2). The ``Lease`` contract itself is never truncated or
    rewritten -- D1.2 simply computes only the months inside the window.

    Boundary semantics are inclusive at the final modeled month: commencing or
    expiring exactly in month ``12H+12`` is inside the horizon and warns
    nothing; one month later warns.
    """

    horizon = projection_month_count(hold_period)
    issues: list[LeaseValidationIssue] = []

    for index, lease in enumerate(leases):
        path = f"leases[{index}]"

        first_rent_period = month_index(
            lease.rent_commencement_date, analysis_start=analysis_start_date
        )
        if first_rent_period > horizon:
            issues.append(
                _issue(
                    LeaseIssueCode.LEASE_STARTS_AFTER_HORIZON,
                    f"{path}.rent_commencement_date",
                    f"lease {lease.lease_id!r} commences in model month "
                    f"{first_rent_period}, beyond the {horizon}-month "
                    f"projection window for a {hold_period}-year hold; it "
                    "contributes nothing to this analysis.",
                    LeaseIssueSeverity.WARNING,
                )
            )
            # A lease that starts beyond the horizon necessarily ends beyond
            # it too. Reporting both would be one fact told twice.
            continue

        last_rent_period = month_index(
            lease.lease_expiration_date, analysis_start=analysis_start_date
        )
        if last_rent_period > horizon:
            issues.append(
                _issue(
                    LeaseIssueCode.LEASE_EXTENDS_BEYOND_HORIZON,
                    f"{path}.lease_expiration_date",
                    f"lease {lease.lease_id!r} runs to model month "
                    f"{last_rent_period}, past the {horizon}-month projection "
                    f"window for a {hold_period}-year hold; its revenue is "
                    "truncated at the window.",
                    LeaseIssueSeverity.WARNING,
                )
            )

    return issues


def _validate_rentable_area_reconciliation(
    property_inputs: LeaseLevelPropertyInputs, suites: tuple[Suite, ...]
) -> list[LeaseValidationIssue]:
    """Every rentable square foot must be accounted for by a suite.

    ``sum(suite_area_sf)`` must equal ``rentable_area_sf`` -- not merely stay
    under it. Both directions are ERRORs:

    - **Over-allocation** means the rent roll claims more leasable area than
      the property has.
    - **Shortfall** means part of the property's rentable area is simply
      absent from the rent roll. That is an incomplete rent roll, not a
      description of common area. Treating a residual as common area would
      let unmodeled leasable space silently dilute physical occupancy and
      understate both vacancy and upside, with nothing on screen to show it.

    Vacant space is represented explicitly, as a ``Suite`` with no lease
    (D0 Section 4.3) -- so a correct rent roll always reconciles exactly, and
    Anchor never has to infer what unaccounted area was.

    This tightens D0 Sections 18.4/19.3, which permitted a shortfall as a
    ``AREA_SHORTFALL_TREATED_AS_COMMON_AREA`` warning. That convention was
    rejected at D1.0 human financial review; the ERROR below replaces it, and
    the warning code no longer exists. See the module docstring.

    Skipped entirely when any input area is non-finite or non-positive: those
    have already produced their own, more specific errors, and summing them
    would only add noise.
    """

    rentable_area = property_inputs.rentable_area_sf
    if not _is_finite_number(rentable_area) or rentable_area <= 0:
        return []
    if not all(
        _is_finite_number(suite.suite_area_sf) and suite.suite_area_sf > 0
        for suite in suites
    ):
        return []

    total_suite_area = sum(suite.suite_area_sf for suite in suites)
    if _areas_reconcile(total_suite_area, rentable_area):
        return []

    unaccounted = rentable_area - total_suite_area
    if unaccounted > 0:
        detail = (
            f"{unaccounted!r} SF of rentable area is not represented by any "
            "suite; vacant space must be declared as a Suite with no lease, "
            "never omitted from the rent roll"
        )
    else:
        detail = (
            f"suite areas exceed rentable_area_sf by {-unaccounted!r} SF"
        )

    return [
        _issue(
            LeaseIssueCode.RENTABLE_AREA_NOT_RECONCILED,
            "property.rentable_area_sf",
            f"suite areas total {total_suite_area!r} SF against "
            f"rentable_area_sf {rentable_area!r}: {detail}.",
        )
    ]


def validate_lease_level_inputs(
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    hold_period: int | None = None,
    market_leasing: MarketLeasingAssumptions | None = None,
) -> LeaseValidationResult:
    """Validate one complete Lease-Level input set, deterministically.

    Returns a ``LeaseValidationResult`` whether or not errors were found;
    ``require_valid_lease_level_inputs`` is the variant that raises. Warnings
    never prevent a valid result.

    ``hold_period`` is the acquisition hold in whole years, from
    ``AcquisitionTerms``. It is optional because it is needed by exactly two
    rules -- the horizon warnings, which are definitionally relative to the
    projection window (D0 Section 19.3). Omitting it evaluates every other
    rule unchanged and simply raises no horizon warning; it never weakens an
    error or alters a result in any other way.

    ``market_leasing`` is the property-level ``MarketLeasingAssumptions``
    default (D2.1). It is optional for the same reason: a D1 contractual rent
    roll needs no market assumption, and omitting it leaves every D1 rule and
    every D1 result bit-identical. Supplying it evaluates the D2.1 market
    domains for the default and for every suite override. A suite that
    declares a market override while this is omitted is an error rather than
    a silent inheritance of nothing.

    **Issue ordering** (D0 Section 19.1) is fixed and reproducible:
    property-level issues first, then suites in declared order, then the
    market-leasing rules (the property default, then suites in declared
    order), then leases in declared order with each lease's own fields in
    canonical field order, then the cross-lease suite-overlap rule, then the
    horizon warnings in declared lease order, then area reconciliation. Nothing here iterates a ``set`` or
    ``dict`` to produce output, so repeated runs emit byte-identical
    sequences.

    No value is defaulted, coerced, rounded, or inferred: a missing or
    malformed input becomes an issue, never a substituted number.
    """

    suite_tuple = tuple(suites)
    lease_tuple = tuple(leases)

    issues: list[LeaseValidationIssue] = []
    issues.extend(_validate_property(property_inputs))
    issues.extend(_validate_suites(suite_tuple))
    issues.extend(
        _validate_suite_market_leasing(suite_tuple, market_leasing=market_leasing)
    )

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

    issues.extend(
        _validate_suite_occupancy_overlap(
            lease_tuple, analysis_start_date=property_inputs.analysis_start_date
        )
    )
    if hold_period is not None:
        issues.extend(
            _validate_horizon(
                lease_tuple,
                analysis_start_date=property_inputs.analysis_start_date,
                hold_period=hold_period,
            )
        )
    issues.extend(
        _validate_rentable_area_reconciliation(property_inputs, suite_tuple)
    )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_lease_level_inputs(
    property_inputs: LeaseLevelPropertyInputs,
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    hold_period: int | None = None,
    market_leasing: MarketLeasingAssumptions | None = None,
) -> LeaseValidationResult:
    """Validate and raise ``LeaseValidationError`` if any ERROR was found.

    Returns the full result (including warnings) when valid, so a caller that
    wants both the go-ahead and the warnings needs exactly one call.
    """

    result = validate_lease_level_inputs(
        property_inputs,
        suites,
        leases,
        hold_period=hold_period,
        market_leasing=market_leasing,
    )
    if result.errors:
        raise LeaseValidationError(result)
    return result


# =============================================================================
# D3.1 -- expense-recovery validation
#
# Deliberately a SEPARATE entry point, not folded into
# `validate_lease_level_inputs`. `MODIFIED_GROSS` is a perfectly valid lease
# type -- D1 has captured it since D1.0 and D2 carries it through rollover
# unchanged -- so it must not become invalid input merely because the gate that
# prices it has not landed. It is only *recovery* that cannot yet be computed
# for one, and that is what this validator says.
# =============================================================================


def validate_recovery_inputs(
    leases: Iterable[Lease],
    pool: RecoverableExpensePool,
    *,
    months: tuple[ModelMonth, ...] | None = None,
) -> LeaseValidationResult:
    """Validate the inputs to a D3.1 expense-recovery calculation.

    Three rules, in a fixed order so the emitted sequence is reproducible: the
    pool's own domain, its alignment to the canonical timeline, then each lease
    in declared order.

    **Pool domain** (D3 Section 3, ``RECOVERABLE_EXPENSES_OUT_OF_DOMAIN``): every
    figure finite and ``>= 0``. A negative pool would be an expense credit, for
    which the accepted D3 model has no convention; it is refused rather than
    given an invented meaning.

    **Alignment** (``RECOVERY_POOL_NOT_ALIGNED``): when ``months`` is supplied,
    the pool must have been built against that exact tuple. Checking month
    *identity* rather than length is the point -- a pool from a different
    projection would zip cleanly and produce a plausible, wrong answer.

    **Modified Gross** (``MISSING_MODIFIED_GROSS_RECOVERY_BASIS``, D0
    Section 16.2 / D3 Section 6.1): a `MODIFIED_GROSS` lease has no explicit
    contractual recovery basis, because D3.1 declares no field to hold one. The
    basis is never inferred -- not from Hold Year 1, the analysis year, the
    acquisition year or the current expense schedule -- so recovery for such a
    lease is refused rather than defaulted. D3.2 introduces the field, and this
    same code then fires when it is present but unset.

    Not validated here: `NNN` and `GROSS` need no recovery input beyond the pool
    and their own area, both already validated elsewhere.
    """

    lease_tuple = tuple(leases)
    issues: list[LeaseValidationIssue] = []

    for index, amount in enumerate(pool.recoverable_expenses):
        path = f"recoverable_expense_pool.recoverable_expenses[{index}]"
        if not _is_finite_number(amount):
            issues.append(
                _issue(
                    LeaseIssueCode.NON_FINITE_VALUE,
                    path,
                    "recoverable expense must be a finite number.",
                )
            )
        elif amount < 0:
            issues.append(
                _issue(
                    LeaseIssueCode.RECOVERABLE_EXPENSES_OUT_OF_DOMAIN,
                    path,
                    f"recoverable expense {amount!r} must be greater than or "
                    "equal to 0; a negative pool would be an expense credit, "
                    "which D3 has no convention for.",
                )
            )

    if months is not None and pool.months != months:
        issues.append(
            _issue(
                LeaseIssueCode.RECOVERY_POOL_NOT_ALIGNED,
                "recoverable_expense_pool.months",
                "the recoverable expense pool was built against a different "
                "month sequence than the canonical projection; both must share "
                "one timeline.",
            )
        )

    for index, lease in enumerate(lease_tuple):
        if lease.lease_type is LeaseType.MODIFIED_GROSS:
            issues.append(
                _issue(
                    LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS,
                    f"leases[{index}].lease_type",
                    f"lease {lease.lease_id!r} is MODIFIED_GROSS and carries no "
                    "explicit contractual recovery basis. A base year or "
                    "expense stop is never inferred from Hold Year 1, the "
                    "analysis year, the acquisition year or the current "
                    "expense schedule; the analyst must supply it. Modified "
                    "Gross recovery arrives at D3.2.",
                )
            )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_recovery_inputs(
    leases: Iterable[Lease],
    pool: RecoverableExpensePool,
    *,
    months: tuple[ModelMonth, ...] | None = None,
) -> LeaseValidationResult:
    """Validate recovery inputs and raise ``LeaseValidationError`` on any ERROR.

    Returns the full result when valid, so a caller that wants both the
    go-ahead and any warnings needs exactly one call.
    """

    result = validate_recovery_inputs(leases, pool, months=months)
    if result.errors:
        raise LeaseValidationError(result)
    return result
