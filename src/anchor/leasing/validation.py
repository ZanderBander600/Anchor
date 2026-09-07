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
from .market import resolve_market_leasing
from .calendar import (
    is_first_day_of_month,
    is_last_day_of_month,
    month_index,
    projection_month_count,
)
from .contracts import (
    EscalationBasis,
    Lease,
    LeaseLevelOperatingInputs,
    LeaseLevelPropertyInputs,
    MonthlyPropertyExpenseSchedule,
    MonthlyPropertyProjection,
    PropertyOperatingSchedule,
    PropertyRecoverySchedule,
    SuiteOperatingProjection,
    LeaseOrigin,
    LeaseType,
    LeasingCommissionMethod,
    MarketLeasingAssumptions,
    RecoverableExpensePool,
    InitialVacancyStrategy,
    SuiteRecoveryProjection,
    RecoveryBasis,
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

    # --- structural parsing (D5.2) ---
    #
    # Raised by ``anchor.leasing.parsing`` at the transport boundary, before any
    # contract exists to validate. They live on this enum rather than on a
    # second, parse-only issue contract because D8 ratified one issue stream for
    # the whole Lease-Level input workflow: a frontend renders a malformed field
    # and an out-of-domain field through the same ``path``/``code``/``severity``
    # shape, and ``anchor.validation.IssueCategory`` already sets the precedent
    # by carrying WORKBOOK_OPEN and MALFORMED_TABLE beside OUT_OF_DOMAIN_VALUE.
    #
    # One stream is not one phase. Everything else on this enum describes a
    # defect in an *assembled* rent roll; these two describe JSON that could not
    # become one. The parser raises only these, and no rule below is restated
    # there.
    UNKNOWN_FIELD = "UNKNOWN_FIELD"
    MALFORMED_FIELD = "MALFORMED_FIELD"

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
    RECOVERY_SCHEDULE_NOT_ALIGNED = "RECOVERY_SCHEDULE_NOT_ALIGNED"
    MISSING_SUITE_RECOVERY_SCHEDULE = "MISSING_SUITE_RECOVERY_SCHEDULE"
    MISSING_INITIAL_VACANCY_TREATMENT = "MISSING_INITIAL_VACANCY_TREATMENT"
    INITIAL_VACANCY_ON_OCCUPIED_SUITE = "INITIAL_VACANCY_ON_OCCUPIED_SUITE"
    MISSING_INITIAL_LEASE_UP_MONTHS = "MISSING_INITIAL_LEASE_UP_MONTHS"
    INITIAL_LEASE_UP_ON_HOLD_VACANT = "INITIAL_LEASE_UP_ON_HOLD_VACANT"
    INITIAL_LEASE_UP_OUT_OF_DOMAIN = "INITIAL_LEASE_UP_OUT_OF_DOMAIN"
    MISSING_MODIFIED_GROSS_RECOVERY_BASIS = (
        "MISSING_MODIFIED_GROSS_RECOVERY_BASIS"
    )
    RECOVERY_BASIS_ON_NON_MODIFIED_GROSS = (
        "RECOVERY_BASIS_ON_NON_MODIFIED_GROSS"
    )
    EXPENSE_STOP_OUT_OF_DOMAIN = "EXPENSE_STOP_OUT_OF_DOMAIN"
    UNSUPPORTED_RECOVERY_BASIS = "UNSUPPORTED_RECOVERY_BASIS"

    # --- Lease-Level acquisition integration (D4.5B) ---
    NON_POSITIVE_FORWARD_EXIT_NOI = "NON_POSITIVE_FORWARD_EXIT_NOI"
    MULTIPLE_KNOWN_LEASES_IN_SUITE = "MULTIPLE_KNOWN_LEASES_IN_SUITE"

    # --- annual operating adapter (D4.4) ---
    PROJECTION_NOT_CANONICAL = "PROJECTION_NOT_CANONICAL"
    PURCHASE_PRICE_OUT_OF_DOMAIN = "PURCHASE_PRICE_OUT_OF_DOMAIN"

    # --- monthly property projection (D4.3) ---
    PROPERTY_RECOVERY_NOT_ALIGNED = "PROPERTY_RECOVERY_NOT_ALIGNED"
    PROPERTY_EXPENSE_SCHEDULE_NOT_ALIGNED = (
        "PROPERTY_EXPENSE_SCHEDULE_NOT_ALIGNED"
    )
    PROPERTY_RECOVERY_AREA_MISMATCH = "PROPERTY_RECOVERY_AREA_MISMATCH"
    PROPERTY_RECOVERY_SUITE_UNIVERSE_MISMATCH = (
        "PROPERTY_RECOVERY_SUITE_UNIVERSE_MISMATCH"
    )

    # --- property leasing aggregation (D4.2) ---
    OPERATING_SCHEDULE_NOT_ALIGNED = "OPERATING_SCHEDULE_NOT_ALIGNED"
    MISSING_SUITE_OPERATING_PROJECTION = "MISSING_SUITE_OPERATING_PROJECTION"
    SUITE_AREA_MISMATCH = "SUITE_AREA_MISMATCH"

    # --- property operating inputs (D4.1) ---
    PROPERTY_EXPENSE_OUT_OF_DOMAIN = "PROPERTY_EXPENSE_OUT_OF_DOMAIN"
    EXPENSE_GROWTH_OUT_OF_DOMAIN = "EXPENSE_GROWTH_OUT_OF_DOMAIN"
    RECOVERABLE_EXPENSE_RATIO_OUT_OF_DOMAIN = (
        "RECOVERABLE_EXPENSE_RATIO_OUT_OF_DOMAIN"
    )
    OTHER_INCOME_OUT_OF_DOMAIN = "OTHER_INCOME_OUT_OF_DOMAIN"
    OTHER_INCOME_GROWTH_OUT_OF_DOMAIN = "OTHER_INCOME_GROWTH_OUT_OF_DOMAIN"
    MANAGEMENT_FEE_OUT_OF_DOMAIN = "MANAGEMENT_FEE_OUT_OF_DOMAIN"
    CREDIT_LOSS_OUT_OF_DOMAIN = "CREDIT_LOSS_OUT_OF_DOMAIN"
    UNUSUALLY_HIGH_CREDIT_LOSS = "UNUSUALLY_HIGH_CREDIT_LOSS"

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

    **Modified Gross** (D0 Section 16.2 / D3 Section 6.1). A `MODIFIED_GROSS`
    lease must carry **both** ``recovery_basis`` and ``expense_stop_psf``; the
    basis is never inferred from Hold Year 1, the analysis year, the acquisition
    year or the current expense schedule, so a missing one is
    ``MISSING_MODIFIED_GROSS_RECOVERY_BASIS`` rather than a default. A basis D3
    does not implement is ``UNSUPPORTED_RECOVERY_BASIS``.

    **A stop on `NNN` or `GROSS` is an ERROR**, not a silently ignored field
    (``RECOVERY_BASIS_ON_NON_MODIFIED_GROSS``, D3 Section 5.2). *A stop implies
    Modified Gross*; permitting one elsewhere would make ``lease_type``
    unreliable as an economic discriminator and leave a financial input with no
    effect.

    **Stop domain** (``EXPENSE_STOP_OUT_OF_DOMAIN``): finite and ``>= 0``
    wherever supplied. Zero is economically valid -- it means the lease
    reimburses its full share -- and is not an upper-bounded quantity.
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
        path = f"leases[{index}]"
        modified_gross = lease.lease_type is LeaseType.MODIFIED_GROSS

        if modified_gross:
            if lease.recovery_basis is None or lease.expense_stop_psf is None:
                issues.append(
                    _issue(
                        LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS,
                        f"{path}.recovery_basis",
                        f"lease {lease.lease_id!r} is MODIFIED_GROSS and "
                        "carries no explicit contractual recovery basis. A base "
                        "year or expense stop is never inferred from Hold "
                        "Year 1, the analysis year, the acquisition year or "
                        "the current expense schedule; the analyst must supply "
                        "both recovery_basis and expense_stop_psf.",
                    )
                )
            elif not isinstance(lease.recovery_basis, RecoveryBasis):
                issues.append(
                    _issue(
                        LeaseIssueCode.UNSUPPORTED_RECOVERY_BASIS,
                        f"{path}.recovery_basis",
                        f"recovery_basis {lease.recovery_basis!r} must be a "
                        "RecoveryBasis member.",
                    )
                )
            elif lease.recovery_basis is not RecoveryBasis.EXPENSE_STOP_PSF:
                issues.append(
                    _issue(
                        LeaseIssueCode.UNSUPPORTED_RECOVERY_BASIS,
                        f"{path}.recovery_basis",
                        f"recovery basis {lease.recovery_basis.value!r} is not "
                        "implemented; D3 supports only EXPENSE_STOP_PSF.",
                    )
                )
        elif lease.recovery_basis is not None or lease.expense_stop_psf is not None:
            # A stop implies Modified Gross. Refused rather than ignored,
            # because a silently-ignored financial field would make
            # `lease_type` unreliable as an economic discriminator (D3 5.2).
            issues.append(
                _issue(
                    LeaseIssueCode.RECOVERY_BASIS_ON_NON_MODIFIED_GROSS,
                    f"{path}.recovery_basis",
                    f"lease {lease.lease_id!r} is "
                    f"{lease.lease_type.value} but carries a recovery basis or "
                    "expense stop. A lease with a contractual expense stop is "
                    "MODIFIED_GROSS in Anchor, not NNN or GROSS.",
                )
            )

        stop = lease.expense_stop_psf
        if stop is not None:
            if not _is_finite_number(stop):
                issues.append(
                    _issue(
                        LeaseIssueCode.NON_FINITE_VALUE,
                        f"{path}.expense_stop_psf",
                        "expense_stop_psf must be a finite number.",
                    )
                )
            elif stop < 0:
                issues.append(
                    _issue(
                        LeaseIssueCode.EXPENSE_STOP_OUT_OF_DOMAIN,
                        f"{path}.expense_stop_psf",
                        f"expense_stop_psf {stop!r} must be greater than or "
                        "equal to 0. Zero is valid and means the lease "
                        "reimburses its full share.",
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


def validate_successor_recovery_assumptions(
    assumptions: MarketLeasingAssumptions,
    *,
    path: str = "market_leasing",
) -> LeaseValidationResult:
    """Validate the **branch-specific** successor recovery terms (D3.3).

    Deliberately **separate** from ``validate_lease_level_inputs`` and from
    ``validate_recovery_inputs``, for the reason D3.1 established: a set of
    assumptions that cannot yet price a recovery is not thereby invalid input
    to D1 or D2. The market-leasing record remains a legitimate D2 rollover
    input whether or not a D3 pool exists, so an incomplete recovery term is
    reported by the calculation that needs it and by nothing else.

    Each branch is checked **independently and by the same rule**, because a
    renewal and a new letting are separate contracts (HD-D3-2). The rule is the
    one `Lease` already follows (D3 Section 5.2), applied per branch:

    - a `MODIFIED_GROSS` branch requires a supported ``RecoveryBasis`` **and**
      an ``expense_stop_psf``, since Anchor never infers a stop -- not from
      Hold Year 1, the analysis year, the acquisition year, the current
      expense schedule, and now also **not from the lease being replaced**
      (D3 Section 6.1, FM-D3-6);
    - an `NNN` or `GROSS` branch must carry **neither**, because a stop implies
      Modified Gross; accepting one and ignoring it would make the branch's
      ``lease_type`` unreliable as an economic discriminator;
    - a stop outside ``>= 0`` and finite is an error, exactly as on a `Lease`.

    The codes are the D3 Section 11 set, unchanged. A branch-specific code
    would report the same financial defect under a second name, and the issue
    ``path`` already names which branch failed.
    """

    issues: list[LeaseIssue] = []

    for branch, lease_type, basis, stop in (
        (
            "renewal",
            assumptions.renewal_lease_type,
            assumptions.renewal_recovery_basis,
            assumptions.renewal_expense_stop_psf,
        ),
        (
            "new",
            assumptions.new_lease_type,
            assumptions.new_recovery_basis,
            assumptions.new_expense_stop_psf,
        ),
    ):
        field = f"{path}.{branch}"

        if lease_type is LeaseType.MODIFIED_GROSS:
            if basis is None or stop is None:
                issues.append(
                    _issue(
                        LeaseIssueCode.MISSING_MODIFIED_GROSS_RECOVERY_BASIS,
                        f"{field}_recovery_basis",
                        f"the {branch} successor is MODIFIED_GROSS but states "
                        "no explicit recovery basis and expense stop. Anchor "
                        "never infers one, and never inherits one from the "
                        "lease being replaced.",
                    )
                )
            elif basis is not RecoveryBasis.EXPENSE_STOP_PSF:
                issues.append(
                    _issue(
                        LeaseIssueCode.UNSUPPORTED_RECOVERY_BASIS,
                        f"{field}_recovery_basis",
                        f"recovery basis {basis.value!r} is not implemented; "
                        "D3 supports only EXPENSE_STOP_PSF.",
                    )
                )
        elif basis is not None or stop is not None:
            issues.append(
                _issue(
                    LeaseIssueCode.RECOVERY_BASIS_ON_NON_MODIFIED_GROSS,
                    f"{field}_recovery_basis",
                    f"the {branch} successor is {lease_type.value} but carries "
                    "a recovery basis or expense stop. A successor with a "
                    "contractual expense stop is MODIFIED_GROSS in Anchor, "
                    "not NNN or GROSS.",
                )
            )

        if stop is not None:
            if not _is_finite_number(stop):
                issues.append(
                    _issue(
                        LeaseIssueCode.NON_FINITE_VALUE,
                        f"{field}_expense_stop_psf",
                        f"{branch}_expense_stop_psf must be a finite number.",
                    )
                )
            elif stop < 0:
                issues.append(
                    _issue(
                        LeaseIssueCode.EXPENSE_STOP_OUT_OF_DOMAIN,
                        f"{field}_expense_stop_psf",
                        f"{branch}_expense_stop_psf {stop!r} must be greater "
                        "than or equal to 0. Zero is valid and means the "
                        "successor reimburses its full share.",
                    )
                )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_successor_recovery_assumptions(
    assumptions: MarketLeasingAssumptions,
    *,
    path: str = "market_leasing",
) -> LeaseValidationResult:
    """Validate successor recovery terms and raise on any ERROR.

    Returns the full result when valid, so a caller that wants both the
    go-ahead and any warnings needs exactly one call.
    """

    result = validate_successor_recovery_assumptions(assumptions, path=path)
    if result.errors:
        raise LeaseValidationError(result)
    return result


def validate_property_recovery_inputs(
    projections: Iterable[SuiteRecoveryProjection],
    *,
    months: tuple[ModelMonth, ...],
    suites: Iterable[Suite] | None = None,
    leases: Iterable[Lease] | None = None,
) -> LeaseValidationResult:
    """Validate the inputs to one property recovery aggregation (D3.5).

    Leasing-scoped, and deliberately separate from
    ``validate_lease_level_inputs``: a rent roll is valid input to D1 and D2
    whether or not any recovery has been modelled, so a missing recovery
    schedule is reported by the aggregation that needs it and by nothing else.

    **Duplicate suites** (``DUPLICATE_SUITE_ID``) are an ERROR rather than a
    silent sum. Two projections for one suite would double that tenant's
    recovery revenue -- a plausible-looking overstatement with no visible
    symptom, since the property total is a sum and nothing else constrains it.

    **Month identity is checked, not length**
    (``RECOVERY_SCHEDULE_NOT_ALIGNED``). Schedules from a different analysis
    start, hold horizon or forward window would zip cleanly by position and
    add up to a plausible, wrong answer. There is one canonical timeline.

    **Unknown suites** (``UNKNOWN_SUITE_REFERENCE``) are an ERROR when
    ``suites`` is supplied: a projection for space the property does not
    contain adds revenue from nowhere.

    **Missing schedules** (``MISSING_SUITE_RECOVERY_SCHEDULE``) are an ERROR
    only when both ``suites`` and ``leases`` are supplied, because only then is
    completeness knowable: a suite that has a lease has a tenant whose recovery
    someone decided not to model, and silently omitting it understates the
    property. A suite with **no** lease correctly has no projection and
    contributes zero -- Anchor never synthesizes a schedule, or a lease, for
    vacant space.

    Issues are emitted in a deterministic order: alignment and duplication in
    the caller's own projection order, then unknown suites, then missing ones
    in suite order.
    """

    issues: list[LeaseIssue] = []
    projection_tuple = tuple(projections)

    seen: set[str] = set()
    for index, projection in enumerate(projection_tuple):
        path = f"suite_recovery[{index}]"

        if projection.months != months:
            issues.append(
                _issue(
                    LeaseIssueCode.RECOVERY_SCHEDULE_NOT_ALIGNED,
                    f"{path}.months",
                    f"the recovery schedule for suite {projection.suite_id!r} "
                    "was built against a different canonical month sequence; "
                    "one property aggregation shares one timeline, and "
                    "matching lengths are not matching months.",
                )
            )

        if projection.suite_id in seen:
            issues.append(
                _issue(
                    LeaseIssueCode.DUPLICATE_SUITE_ID,
                    f"{path}.suite_id",
                    f"suite {projection.suite_id!r} has more than one recovery "
                    "schedule in this aggregation; its recovery revenue would "
                    "be counted twice.",
                )
            )
        seen.add(projection.suite_id)

    if suites is None:
        return LeaseValidationResult(issues=tuple(issues))

    suite_tuple = tuple(suites)
    known = {suite.suite_id for suite in suite_tuple}

    for index, projection in enumerate(projection_tuple):
        if projection.suite_id not in known:
            issues.append(
                _issue(
                    LeaseIssueCode.UNKNOWN_SUITE_REFERENCE,
                    f"suite_recovery[{index}].suite_id",
                    f"recovery schedule references suite "
                    f"{projection.suite_id!r}, which is not a suite of this "
                    "property; recovery revenue cannot come from space the "
                    "property does not contain.",
                )
            )

    if leases is None:
        return LeaseValidationResult(issues=tuple(issues))

    tenanted = {lease.suite_id for lease in leases}
    for suite in suite_tuple:
        if suite.suite_id in seen:
            continue

        if suite.suite_id in tenanted:
            issues.append(
                _issue(
                    LeaseIssueCode.MISSING_SUITE_RECOVERY_SCHEDULE,
                    f"suites[{suite.suite_id}]",
                    f"suite {suite.suite_id!r} has a lease but no recovery "
                    "schedule in this aggregation; omitting a known tenant "
                    "understates property recovery revenue.",
                )
            )
        elif suite.initial_vacancy is not None:
            # D3.6: a vacant suite that WAS underwritten -- either way -- owes
            # the aggregation a projection. HOLD_VACANT contributes an
            # explicit zero, which is how deliberate vacancy stays visible.
            issues.append(
                _issue(
                    LeaseIssueCode.MISSING_SUITE_RECOVERY_SCHEDULE,
                    f"suites[{suite.suite_id}]",
                    f"suite {suite.suite_id!r} is vacant with an explicit "
                    f"{suite.initial_vacancy.strategy.value} treatment but has "
                    "no recovery schedule in this aggregation. A suite that "
                    "was underwritten must appear in the result, so a "
                    "deliberate zero is distinguishable from an omission.",
                )
            )
        else:
            # D3.6: vacant and never underwritten at all. The aggregation is a
            # future-looking gate, so this is the error the gate exists for.
            issues.append(
                _issue(
                    LeaseIssueCode.MISSING_INITIAL_VACANCY_TREATMENT,
                    f"suites[{suite.suite_id}].initial_vacancy",
                    f"suite {suite.suite_id!r} is vacant at the analysis start "
                    "and states no initial-vacancy treatment, so its future "
                    "recovery cannot be aggregated. Anchor does not assume "
                    "vacant space stays vacant: state HOLD_VACANT or "
                    "MARKET_LEASE_UP explicitly.",
                )
            )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_property_recovery_inputs(
    projections: Iterable[SuiteRecoveryProjection],
    *,
    months: tuple[ModelMonth, ...],
    suites: Iterable[Suite] | None = None,
    leases: Iterable[Lease] | None = None,
) -> LeaseValidationResult:
    """Validate property recovery inputs and raise on any ERROR.

    Returns the full result when valid, so a caller that wants both the
    go-ahead and any warnings needs exactly one call.
    """

    result = validate_property_recovery_inputs(
        projections, months=months, suites=suites, leases=leases
    )
    if result.errors:
        raise LeaseValidationError(result)
    return result


def validate_initial_vacancy_inputs(
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    property_defaults: MarketLeasingAssumptions | None = None,
    path: str = "suites",
) -> LeaseValidationResult:
    """Validate initial-vacancy treatments for a **future-looking** projection.

    **Scoped, and deliberately not part of ``validate_lease_level_inputs``**
    (HD-D3.6-1, accepted). D1 is a factual contractual-rent layer: a suite with
    no lease genuinely earns zero rent today, and that is an observation rather
    than a speculation. A bare vacant suite therefore remains valid D1 input.

    The error belongs where a silent zero would be a **modelling claim** --
    the initial-vacancy builder and property recovery aggregation. There,
    *"this space never lets"* and *"nobody told us how this space lets"* are
    different statements and must not produce the same output.

    | Rule | Code |
    |---|---|
    | Vacant suite with no treatment | `MISSING_INITIAL_VACANCY_TREATMENT` |
    | Occupied suite carrying a treatment | `INITIAL_VACANCY_ON_OCCUPIED_SUITE` |
    | `MARKET_LEASE_UP` with no lease-up period | `MISSING_INITIAL_LEASE_UP_MONTHS` |
    | `HOLD_VACANT` carrying a lease-up period | `INITIAL_LEASE_UP_ON_HOLD_VACANT` |
    | Lease-up period negative or non-finite | `INITIAL_LEASE_UP_OUT_OF_DOMAIN` |
    | First-event concession unconsumable | `FREE_RENT_EXCEEDS_OCCUPIABLE_TERM` |

    **The occupied-suite rule refuses rather than ignores.** A treatment on a
    suite that already has a tenant is a financially meaningful field that
    could never be read; silently dropping it would let an analyst believe
    lease-up was modelled when the space was never empty.

    **The first-event free-rent check is the subtle one.** D2 already validates
    ``new_free_rent_months <= new_term_months - frac(new_downtime_months)``.
    The first tenant reuses the same concession but waits
    ``initial_lease_up_months``, so its boundary fraction is different, and a
    grant that is consumable after a future 2.0-month downtime may be
    unconsumable after a 2.25-month lease-up. It is re-validated against
    ``frac(initial_lease_up_months)`` through the **same** helper, so there is
    one over-grant rule and the concession can never be silently discarded.
    ``property_defaults`` supplies the term and grant; when omitted the check
    is skipped rather than guessed.

    Issues are emitted in suite order, deterministically.
    """

    issues: list[LeaseIssue] = []
    suite_tuple = tuple(suites)
    tenanted = {lease.suite_id for lease in leases}

    for suite in suite_tuple:
        field = f"{path}[{suite.suite_id}].initial_vacancy"
        treatment = suite.initial_vacancy
        occupied = suite.suite_id in tenanted

        if occupied:
            if treatment is not None:
                issues.append(
                    _issue(
                        LeaseIssueCode.INITIAL_VACANCY_ON_OCCUPIED_SUITE,
                        field,
                        f"suite {suite.suite_id!r} has a lease but carries an "
                        "initial-vacancy treatment. The space is not vacant at "
                        "the analysis start, so the assumption could never be "
                        "read; it is refused rather than silently ignored.",
                    )
                )
            continue

        if treatment is None:
            issues.append(
                _issue(
                    LeaseIssueCode.MISSING_INITIAL_VACANCY_TREATMENT,
                    field,
                    f"suite {suite.suite_id!r} is vacant at the analysis start "
                    "and states no initial-vacancy treatment. Anchor does not "
                    "assume vacant space stays vacant: state HOLD_VACANT to "
                    "underwrite it as vacant deliberately, or MARKET_LEASE_UP "
                    "with an explicit lease-up period.",
                )
            )
            continue

        lease_up = treatment.initial_lease_up_months

        if treatment.strategy is InitialVacancyStrategy.HOLD_VACANT:
            if lease_up is not None:
                issues.append(
                    _issue(
                        LeaseIssueCode.INITIAL_LEASE_UP_ON_HOLD_VACANT,
                        f"{field}.initial_lease_up_months",
                        f"suite {suite.suite_id!r} is HOLD_VACANT but states a "
                        f"lease-up period of {lease_up!r}. The space is "
                        "deliberately not let, so the period would never "
                        "apply; state one intent, not half of each.",
                    )
                )
            continue

        if lease_up is None:
            issues.append(
                _issue(
                    LeaseIssueCode.MISSING_INITIAL_LEASE_UP_MONTHS,
                    f"{field}.initial_lease_up_months",
                    f"suite {suite.suite_id!r} is MARKET_LEASE_UP but states no "
                    "initial_lease_up_months. Anchor never infers a lease-up "
                    "period and never falls back to new_downtime_months, which "
                    "is a different underwriting judgement.",
                )
            )
            continue

        if not _is_finite_number(lease_up) or lease_up < 0:
            issues.append(
                _issue(
                    LeaseIssueCode.INITIAL_LEASE_UP_OUT_OF_DOMAIN,
                    f"{field}.initial_lease_up_months",
                    f"initial_lease_up_months {lease_up!r} must be a finite "
                    "number of months greater than or equal to 0. Zero is "
                    "valid and means the space lets immediately.",
                )
            )
            continue

        if property_defaults is not None:
            resolved = resolve_market_leasing(
                suite, property_defaults=property_defaults
            ).assumptions
            # The first tenant reuses new_free_rent_months but waits
            # initial_lease_up_months, so the boundary fraction differs.
            issues.extend(
                _validate_free_rent_over_grant(
                    resolved,
                    path=f"{path}[{suite.suite_id}]",
                    branch="new",
                    term_months=resolved.new_term_months,
                    downtime_months=lease_up,
                    free_rent_months=resolved.new_free_rent_months,
                )
            )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_initial_vacancy_inputs(
    suites: Iterable[Suite],
    leases: Iterable[Lease],
    *,
    property_defaults: MarketLeasingAssumptions | None = None,
    path: str = "suites",
) -> LeaseValidationResult:
    """Validate initial-vacancy treatments and raise on any ERROR."""

    result = validate_initial_vacancy_inputs(
        suites, leases, property_defaults=property_defaults, path=path
    )
    if result.errors:
        raise LeaseValidationError(result)
    return result


# =============================================================================
# D4.5B -- the Lease-Level acquisition integration boundary
#
# Two rules, and both belong here rather than upstream. Neither is an operating
# rule: a projection carrying either defect is a perfectly valid *operating*
# model, and only the act of running an acquisition analysis against it is
# refused.
# =============================================================================


def validate_capitalizable_exit_noi(
    exit_noi: float, *, path: str = "annual_projection.exit_noi"
) -> LeaseValidationResult:
    """Refuse a non-positive forward exit NOI (HD-D4-7).

    ``exit_value = exit_noi / exit_cap_rate`` is a valuation only when the
    numerator is an income stream. With a non-positive numerator the expression
    behaves perversely -- a *lower* cap rate makes the "value" *more* negative
    -- and it then propagates into net sale proceeds, both cash-flow series and
    both IRRs. Reporting that number, and returns derived from it, would be
    worse than refusing.

    **This is an acquisition-boundary rule, not an operating one.** The monthly
    and annual projections of a distressed building build successfully and stay
    fully inspectable; negative monthly NOI, negative hold-year NOI and a
    negative going-in cap rate are all legitimate results and none is refused
    here. Only the forward NOI *used for cap-rate terminal valuation* is
    restricted, and only at the point where that capitalization is about to
    happen.

    Deliberately not in ``anchor.engine``: ``calculate_exit_value`` keeps its
    behaviour for every caller, so Quick and Detailed are provably unaffected
    (G-2).
    """

    if not _is_finite_number(exit_noi):
        return LeaseValidationResult(
            issues=(
                _issue(
                    LeaseIssueCode.NON_FINITE_VALUE,
                    path,
                    "the forward exit NOI must be a finite number.",
                ),
            )
        )
    if exit_noi <= 0:
        return LeaseValidationResult(
            issues=(
                _issue(
                    LeaseIssueCode.NON_POSITIVE_FORWARD_EXIT_NOI,
                    path,
                    f"the forward exit NOI is {exit_noi!r}. Cap-rate terminal "
                    "valuation requires a positive forward income stream: "
                    "dividing a loss by a cap rate does not produce a price a "
                    "buyer would pay, and a lower cap rate would make the "
                    "result more negative. The operating projection itself is "
                    "valid and remains inspectable; only capitalizing it is "
                    "refused.",
                ),
            )
        )
    return LeaseValidationResult(issues=())


def require_capitalizable_exit_noi(
    exit_noi: float, *, path: str = "annual_projection.exit_noi"
) -> LeaseValidationResult:
    """Validate the forward exit NOI and raise ``LeaseValidationError`` on any
    ERROR. Called immediately before the shared exit-cap calculation."""

    result = validate_capitalizable_exit_noi(exit_noi, path=path)
    if result.errors:
        raise LeaseValidationError(result)
    return result


def validate_lease_level_acquisition_leases(
    suites: Iterable[Suite], leases: Iterable[Lease]
) -> LeaseValidationResult:
    """Refuse a suite carrying more than one **known** lease (D4.5B).

    Lease-Level acquisition underwriting supports at most one known lease per
    suite. Zero known leases follow the initial-vacancy path (``HOLD_VACANT``
    or ``MARKET_LEASE_UP``); exactly one follows the occupied recursive
    rollover path; more than one is rejected.

    **"Known", not "in place".** The count is of every lease stated for the
    suite, with no date condition, so a signed *future* lease that does not
    overlap the current one is rejected by this same rule. That is deliberate
    and is the reason the code says ``KNOWN`` rather than ``IN_PLACE``.

    **A scoped acquisition restriction, not an economic default, and not a D1
    rule.** D1 is a contractual/factual layer and legitimately represents
    sequential known leases; that representation is unchanged and this
    validator is not applied there. What is missing is downstream: the
    authoritative full-chain builder for an occupied suite --
    ``build_recursive_rollover`` -- is seeded from exactly one expiring lease,
    and ``suite_operating_projection`` takes exactly one chain per suite. No
    contract describes the economics required to compose *known lease A ->
    known future lease B -> market recursion*: the committed successor's
    concessions, TI, LC, commencement-gap treatment, recovery structure and
    exact handoff to probabilistic rollover all have no home.

    So the alternatives are all worse than refusing. Dropping the later lease,
    keeping only the first, reinterpreting a signed future lease as a
    probabilistic market successor, or fabricating concessions, TI, LC or
    downtime to bridge the gap would each report a number nobody underwrote.
    Committed/sequential future known leases are a deferred leasing capability.

    Emitted in suite order, so the sequence is reproducible.
    """

    issues: list[LeaseValidationIssue] = []
    lease_tuple = tuple(leases)

    for suite in tuple(suites):
        matching = [
            lease.lease_id
            for lease in lease_tuple
            if lease.suite_id == suite.suite_id
        ]
        if len(matching) > 1:
            issues.append(
                _issue(
                    LeaseIssueCode.MULTIPLE_KNOWN_LEASES_IN_SUITE,
                    f"suites[{suite.suite_id}]",
                    f"suite {suite.suite_id!r} carries {len(matching)} known "
                    f"leases ({sorted(matching)}). Lease-Level acquisition "
                    "underwriting currently supports at most one known lease "
                    "per suite; sequential or committed future known leases are "
                    "not yet supported. State the in-place lease and let the "
                    "rollover engine price what follows it.",
                )
            )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_lease_level_acquisition_leases(
    suites: Iterable[Suite], leases: Iterable[Lease]
) -> LeaseValidationResult:
    """Validate suite/lease association for the acquisition path and raise on
    any ERROR."""

    result = validate_lease_level_acquisition_leases(suites, leases)
    if result.errors:
        raise LeaseValidationError(result)
    return result


# =============================================================================
# D4.4 -- the annual operating adapter
#
# Two rules only. The reducers in ``aggregation.py`` already enforce that a
# monthly series has exactly ``12H + 12`` values, and every contract already
# enforces its own series lengths, so this validator adds precisely what
# nothing upstream can know: that the hold/forward partition the adapter is
# about to slice on is the one the calendar actually describes, and that the
# valuation denominator is usable.
# =============================================================================


def validate_annual_adapter_inputs(
    monthly: MonthlyPropertyProjection,
    *,
    hold_period: int,
    purchase_price: float,
) -> LeaseValidationResult:
    """Validate the inputs to one monthly-to-annual derivation (D4.4).

    **Canonical partition** (``PROJECTION_NOT_CANONICAL``). The adapter slices
    hold years out of months ``1 .. 12H`` and the exit window out of
    ``12H+1 .. 12H+12``. Both slices are position-based, so the partition must
    match what ``ModelMonth`` says: the projection must hold exactly
    ``12H + 12`` months, and exactly the final twelve must carry
    ``is_forward_exit_month``. A projection whose flags disagree with its
    length would still slice cleanly and would silently move the sale date.

    **Valuation denominator** (``PURCHASE_PRICE_OUT_OF_DOMAIN``). ``> 0`` and
    finite, the same domain ``anchor.validation`` already applies to
    ``purchase_price``, reproduced here under the leasing-scoped severity
    architecture rather than by importing or modifying the global validator.
    The denominator is needed only to construct ``going_in_cap_rate``, which
    ``OperatingProjectionLike`` requires; accepting it is not acquisition
    integration, and nothing else in this gate reads it.

    **Deliberately not checked: the sign of the forward NOI.** A non-positive
    ``exit_noi`` is a legitimate operating result and this gate constructs it
    faithfully. Cap-rate terminal valuation is what it makes meaningless, and
    that is refused at the Lease-Level acquisition/integration boundary at
    D4.5 (HD-D4-7, D4 Section 21.6). Moving the check here would make the
    operating projection of a distressed building unbuildable, which is
    exactly what the accepted decision avoids.
    """

    issues: list[LeaseValidationIssue] = []

    expected_months = projection_month_count(hold_period)
    if len(monthly.months) != expected_months:
        issues.append(
            _issue(
                LeaseIssueCode.PROJECTION_NOT_CANONICAL,
                "monthly_projection.months",
                f"a {hold_period}-year hold has {expected_months} canonical "
                f"months ({hold_period} hold years plus the twelve forward "
                f"exit months); the projection holds {len(monthly.months)}.",
            )
        )
    else:
        last_hold_month = 12 * hold_period
        for position, month in enumerate(monthly.months):
            is_forward = position >= last_hold_month
            if month.is_forward_exit_month is not is_forward:
                issues.append(
                    _issue(
                        LeaseIssueCode.PROJECTION_NOT_CANONICAL,
                        f"monthly_projection.months[{position}]",
                        f"month {month.period_index} is marked "
                        f"is_forward_exit_month="
                        f"{month.is_forward_exit_month!r} but position "
                        f"{position} of a {hold_period}-year hold is "
                        f"{'inside' if is_forward else 'outside'} the forward "
                        "exit window; the sale date is month "
                        f"{last_hold_month}.",
                    )
                )
                break

    if not _is_finite_number(purchase_price):
        issues.append(
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                "purchase_price",
                "purchase_price must be a finite number.",
            )
        )
    elif purchase_price <= 0:
        issues.append(
            _issue(
                LeaseIssueCode.PURCHASE_PRICE_OUT_OF_DOMAIN,
                "purchase_price",
                f"purchase_price {purchase_price!r} must be greater than 0; it "
                "is the going-in cap rate's denominator.",
            )
        )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_annual_adapter_inputs(
    monthly: MonthlyPropertyProjection,
    *,
    hold_period: int,
    purchase_price: float,
) -> LeaseValidationResult:
    """Validate annual-adapter inputs and raise on any ERROR."""

    result = validate_annual_adapter_inputs(
        monthly, hold_period=hold_period, purchase_price=purchase_price
    )
    if result.errors:
        raise LeaseValidationError(result)
    return result


# =============================================================================
# D4.3 -- monthly property projection composition
#
# Three completed schedules are about to be read position by position. Each
# check below exists because the corresponding mistake would produce a
# plausible, wrong statement rather than a crash: a recovery series from a
# different projection, an expense series from a different hold horizon, or a
# recovery schedule belonging to another building entirely.
# =============================================================================


def validate_property_projection_inputs(
    operating: PropertyOperatingSchedule,
    recovery: PropertyRecoverySchedule,
    expenses: MonthlyPropertyExpenseSchedule,
    *,
    operating_inputs: LeaseLevelOperatingInputs,
) -> LeaseValidationResult:
    """Validate the three schedules and the assumptions D4.3 composes.

    **The leasing schedule defines the timeline.** ``PropertyOperatingSchedule``
    is the accepted property-level authority (D4.2), so its ``months`` is the
    canonical sequence and the other two are checked against it.

    Rules, in a fixed order so the emitted sequence is reproducible:

    1. **Operating-input domains**, through the existing
       ``validate_lease_level_operating_inputs`` -- one authority, reused, not
       a second copy. D4.3 consumes only ``other_income``,
       ``other_income_growth``, ``credit_loss_pct`` and ``management_fee_pct``,
       but the whole contract is validated because that is what the single
       authority does, and an out-of-domain field it does not read is still an
       out-of-domain field.
    2. **Recovery alignment** (``PROPERTY_RECOVERY_NOT_ALIGNED``) -- month
       *identity*, on the same semantic basis D3.5 and D4.2 already use
       (tuple equality over ``ModelMonth``), never length. A recovery series
       from a different analysis start or hold horizon would zip cleanly by
       position and add up to a plausible, wrong EGI.
    3. **Expense alignment** (``PROPERTY_EXPENSE_SCHEDULE_NOT_ALIGNED``) -- the
       same rule, for the same reason.
    4. **Property-area identity** (``PROPERTY_RECOVERY_AREA_MISMATCH``) --
       both schedules carry their own ``rentable_area_sf``; they must agree
       under Anchor's existing scaled area tolerance. Two buildings can easily
       share a timeline, and the areas are the only scalar both schedules
       independently record.
    5. **Suite-universe identity**
       (``PROPERTY_RECOVERY_SUITE_UNIVERSE_MISMATCH``) -- both schedules retain
       their per-suite projections, so the suites they describe must be the
       same set. This is what actually distinguishes "the same property" from
       "a property of the same size"; the area check alone would not.

    Deliberately **not** checked here: anything the source contracts already
    guarantee. Series lengths are enforced by each schedule's own
    ``__post_init__``, the recovery domain by D3, and the expense domain by
    D4.1. There is one validation authority per rule.
    """

    issues: list[LeaseValidationIssue] = []

    issues.extend(
        validate_lease_level_operating_inputs(operating_inputs).issues
    )

    months = operating.months

    if recovery.months != months:
        issues.append(
            _issue(
                LeaseIssueCode.PROPERTY_RECOVERY_NOT_ALIGNED,
                "recovery_schedule.months",
                "the property recovery schedule was built against a different "
                "canonical month sequence than the property leasing schedule; "
                "one projection shares one timeline, and matching lengths are "
                "not matching months.",
            )
        )

    if expenses.months != months:
        issues.append(
            _issue(
                LeaseIssueCode.PROPERTY_EXPENSE_SCHEDULE_NOT_ALIGNED,
                "expense_schedule.months",
                "the monthly property expense schedule was built against a "
                "different canonical month sequence than the property leasing "
                "schedule; one projection shares one timeline.",
            )
        )

    if not _areas_reconcile(recovery.rentable_area_sf, operating.rentable_area_sf):
        issues.append(
            _issue(
                LeaseIssueCode.PROPERTY_RECOVERY_AREA_MISMATCH,
                "recovery_schedule.rentable_area_sf",
                f"the recovery schedule states {recovery.rentable_area_sf!r} "
                f"rentable SF and the leasing schedule "
                f"{operating.rentable_area_sf!r}; the two must describe the "
                "same property.",
            )
        )

    operating_suites = sorted(
        projection.suite_id for projection in operating.suite_projections
    )
    recovery_suites = sorted(
        projection.suite_id for projection in recovery.suite_projections
    )
    if operating_suites != recovery_suites:
        issues.append(
            _issue(
                LeaseIssueCode.PROPERTY_RECOVERY_SUITE_UNIVERSE_MISMATCH,
                "recovery_schedule.suite_projections",
                f"the recovery schedule covers suites {recovery_suites} and "
                f"the leasing schedule {operating_suites}; two schedules of "
                "the same property describe the same suites, and equal areas "
                "and timelines alone do not make one property.",
            )
        )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_property_projection_inputs(
    operating: PropertyOperatingSchedule,
    recovery: PropertyRecoverySchedule,
    expenses: MonthlyPropertyExpenseSchedule,
    *,
    operating_inputs: LeaseLevelOperatingInputs,
) -> LeaseValidationResult:
    """Validate projection composition inputs and raise on any ERROR."""

    result = validate_property_projection_inputs(
        operating, recovery, expenses, operating_inputs=operating_inputs
    )
    if result.errors:
        raise LeaseValidationError(result)
    return result


# =============================================================================
# D4.2 -- property leasing aggregation
#
# Mirrors ``validate_property_recovery_inputs`` (D3.5) rule for rule, with one
# deliberate tightening: ``suites`` is REQUIRED and completeness is
# unconditional. D3.5 could only judge completeness when it also knew the
# leases, because a suite with no lease legitimately had no recovery schedule.
# At D4.2 every suite has leasing economics -- an occupied one has its chain,
# a MARKET_LEASE_UP one has its lease-up chain, and a HOLD_VACANT one has an
# explicit all-zero chain -- so "this suite may be omitted" is no longer a
# thing, and D3.6's refusal to let deliberate vacancy look like an omission is
# preserved rather than weakened.
# =============================================================================


def validate_property_operating_inputs(
    projections: Iterable[SuiteOperatingProjection],
    suites: Iterable[Suite],
    *,
    months: tuple[ModelMonth, ...],
    leases: Iterable[Lease] | None = None,
) -> LeaseValidationResult:
    """Validate the inputs to one property leasing aggregation (D4.2).

    Leasing-scoped, and deliberately separate from
    ``validate_lease_level_inputs``: a rent roll is valid input to D1 and D2
    whether or not anyone has projected a suite, so a missing projection is
    reported by the aggregation that needs it and by nothing else.

    **Month identity is checked, not length**
    (``OPERATING_SCHEDULE_NOT_ALIGNED``). A projection from a different
    analysis start, hold horizon or forward window would zip cleanly by
    position and add up to a plausible, wrong answer. There is one canonical
    timeline, and matching lengths are not matching months.

    **Duplicate suites** (``DUPLICATE_SUITE_ID``) are an ERROR rather than a
    silent sum. Two projections for one suite would double that suite's rent,
    TI, LC **and** its occupied area -- an overstatement with no visible
    symptom, since the property total is a sum and nothing else constrains it.

    **Unknown suites** (``UNKNOWN_SUITE_REFERENCE``): a projection for space
    the property does not contain adds rent and occupied area from nowhere.

    **Area mismatch** (``SUITE_AREA_MISMATCH``): a projection must claim the
    suite's authoritative ``suite_area_sf``, compared under Anchor's existing
    scaled tolerance rather than ``==``. The area is what every occupancy
    figure is measured against, so a projection quietly carrying a different
    one would corrupt property occupancy while every rent figure still looked
    right.

    **Missing projections**: every suite must appear exactly once. A suite
    carrying an explicit initial-vacancy treatment that produced no projection
    is ``MISSING_SUITE_OPERATING_PROJECTION`` -- a deliberate zero must be
    *present*, so it stays distinguishable from an omission. A suite that is
    vacant and was never underwritten at all is
    ``MISSING_INITIAL_VACANCY_TREATMENT``, the D3.6 rule, unchanged: Anchor
    does not assume vacant space stays vacant.

    Issues are emitted in a deterministic order: alignment, duplication and
    area in the caller's own projection order, then unknown suites, then
    missing ones in suite order. Nothing here iterates a ``set`` or ``dict``
    to produce an issue.
    """

    issues: list[LeaseValidationIssue] = []
    projection_tuple = tuple(projections)
    suite_tuple = tuple(suites)
    areas = {suite.suite_id: suite.suite_area_sf for suite in suite_tuple}

    seen: set[str] = set()
    for index, projection in enumerate(projection_tuple):
        path = f"suite_operating[{index}]"

        if projection.months != months:
            issues.append(
                _issue(
                    LeaseIssueCode.OPERATING_SCHEDULE_NOT_ALIGNED,
                    f"{path}.months",
                    f"the operating projection for suite "
                    f"{projection.suite_id!r} was built against a different "
                    "canonical month sequence; one property aggregation "
                    "shares one timeline, and matching lengths are not "
                    "matching months.",
                )
            )

        if projection.suite_id in seen:
            issues.append(
                _issue(
                    LeaseIssueCode.DUPLICATE_SUITE_ID,
                    f"{path}.suite_id",
                    f"suite {projection.suite_id!r} has more than one "
                    "operating projection in this aggregation; its rent, "
                    "leasing costs and occupied area would all be counted "
                    "twice.",
                )
            )
        seen.add(projection.suite_id)

        authoritative = areas.get(projection.suite_id)
        if authoritative is not None and not _areas_reconcile(
            projection.suite_area_sf, authoritative
        ):
            issues.append(
                _issue(
                    LeaseIssueCode.SUITE_AREA_MISMATCH,
                    f"{path}.suite_area_sf",
                    f"the operating projection for suite "
                    f"{projection.suite_id!r} claims "
                    f"{projection.suite_area_sf!r} SF but the suite is "
                    f"{authoritative!r} SF; occupancy is measured against the "
                    "suite's authoritative area.",
                )
            )

    known = set(areas)
    for index, projection in enumerate(projection_tuple):
        if projection.suite_id not in known:
            issues.append(
                _issue(
                    LeaseIssueCode.UNKNOWN_SUITE_REFERENCE,
                    f"suite_operating[{index}].suite_id",
                    f"operating projection references suite "
                    f"{projection.suite_id!r}, which is not a suite of this "
                    "property; rent and occupied area cannot come from space "
                    "the property does not contain.",
                )
            )

    tenanted = None if leases is None else {lease.suite_id for lease in leases}
    for suite in suite_tuple:
        if suite.suite_id in seen:
            continue

        if suite.initial_vacancy is None and (
            tenanted is not None and suite.suite_id not in tenanted
        ):
            issues.append(
                _issue(
                    LeaseIssueCode.MISSING_INITIAL_VACANCY_TREATMENT,
                    f"suites[{suite.suite_id}].initial_vacancy",
                    f"suite {suite.suite_id!r} is vacant at the analysis start "
                    "and states no initial-vacancy treatment, so its future "
                    "leasing economics cannot be aggregated. Anchor does not "
                    "assume vacant space stays vacant: state HOLD_VACANT or "
                    "MARKET_LEASE_UP explicitly.",
                )
            )
        else:
            treatment = (
                "is occupied or unlabelled"
                if suite.initial_vacancy is None
                else f"is vacant with an explicit "
                f"{suite.initial_vacancy.strategy.value} treatment"
            )
            issues.append(
                _issue(
                    LeaseIssueCode.MISSING_SUITE_OPERATING_PROJECTION,
                    f"suites[{suite.suite_id}]",
                    f"suite {suite.suite_id!r} {treatment} but has no "
                    "operating projection in this aggregation. Every suite "
                    "appears exactly once, so a deliberate zero is "
                    "distinguishable from an omission.",
                )
            )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_property_operating_inputs(
    projections: Iterable[SuiteOperatingProjection],
    suites: Iterable[Suite],
    *,
    months: tuple[ModelMonth, ...],
    leases: Iterable[Lease] | None = None,
) -> LeaseValidationResult:
    """Validate property leasing-aggregation inputs and raise on any ERROR."""

    result = validate_property_operating_inputs(
        projections, suites, months=months, leases=leases
    )
    if result.errors:
        raise LeaseValidationError(result)
    return result


# =============================================================================
# D4.1 -- property operating inputs
#
# Deliberately separate from ``validate_lease_level_inputs``, for the reason
# D3.1 established for recovery inputs: a rent roll that carries no property
# operating assumptions is not thereby invalid input to D1, D2 or D3. The
# market-leasing engine remains usable before any expense schedule exists, so
# an operating-input defect is reported by the calculation that needs it and by
# nothing else.
#
# The domains below are the *identical* domains ``anchor.validation`` already
# applies to the same six Detailed concepts, reproduced here under the
# leasing-scoped ERROR/WARNING architecture (HD-6) rather than by importing or
# modifying the global validator -- which D4 Section 9.2 requires be left
# untouched, since it owns the API boundary for Quick and Detailed and the
# Lease-Level API boundary is D5.
# =============================================================================


#: The five eligible fixed property expense lines, in the order
#: ``MonthlyPropertyExpenseSchedule`` declares them, so validation issues are
#: emitted in the same canonical order the schedule accumulates them.
_FIXED_EXPENSE_FIELDS: tuple[str, ...] = (
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_maintenance",
    "other_operating_expenses",
)

#: Above this, a Lease-Level credit-loss allowance is more likely a Detailed
#: ``vacancy_credit_loss_pct`` carried across by mistake than a genuine bad-debt
#: assumption (D0 Section 15.4). Physical vacancy is already modeled per suite
#: per month, so it must not be inside this percentage a second time.
_UNUSUAL_CREDIT_LOSS_THRESHOLD = 0.10


def _validate_ratio_field(
    value: object, *, code: LeaseIssueCode, path: str, label: str
) -> list[LeaseValidationIssue]:
    """Finite and ``0 <= x <= 1``."""

    if not _is_finite_number(value):
        return [
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                path,
                f"{label} must be a finite number.",
            )
        ]
    if not 0 <= value <= 1:
        return [
            _issue(
                code,
                path,
                f"{label} {value!r} must be between 0 and 1, inclusive.",
            )
        ]
    return []


def _validate_growth_field(
    value: object, *, code: LeaseIssueCode, path: str, label: str
) -> list[LeaseValidationIssue]:
    """Finite and ``> -1`` -- the exact Detailed growth domain.

    No upper bound, and negative growth is permitted: a building whose taxes
    are being appealed downward is ordinary. ``g <= -1`` is refused because
    ``(1 + g)`` is then non-positive, which either collapses every later year
    to exactly zero (``g == -1``) or flips its sign every year (``g < -1``) --
    neither is meaningful for a compounding dollar amount. This is the same
    reasoning, and the same boundary, ``anchor.validation`` records for
    ``expense_growth`` and ``revenue_growth``.
    """

    if not _is_finite_number(value):
        return [
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                path,
                f"{label} must be a finite number.",
            )
        ]
    if not value > -1:
        return [
            _issue(
                code,
                path,
                f"{label} {value!r} must be greater than -1; at or below -1 a "
                "compounding amount collapses to zero or flips sign each year.",
            )
        ]
    return []


def _validate_non_negative_dollars(
    value: object, *, code: LeaseIssueCode, path: str, label: str
) -> list[LeaseValidationIssue]:
    """Finite and ``>= 0`` -- the exact Detailed expense/other-income domain.

    Zero is valid and economically meaningful: a building with no separately
    metered utilities carries ``utilities = 0.0``. Negative is refused; a
    negative annual operating expense is an expense credit, for which the
    accepted model has no convention, exactly as D3 refuses a negative pool.
    """

    if not _is_finite_number(value):
        return [
            _issue(
                LeaseIssueCode.NON_FINITE_VALUE,
                path,
                f"{label} must be a finite number.",
            )
        ]
    if value < 0:
        return [
            _issue(
                code,
                path,
                f"{label} {value!r} must be greater than or equal to 0.",
            )
        ]
    return []


def validate_recoverable_expense_ratio(
    recoverable_expense_ratio: object,
    *,
    path: str = "operating_inputs.recoverable_expense_ratio",
) -> LeaseValidationResult:
    """Validate a standalone ``recoverable_expense_ratio`` (D4.1).

    Finite and ``0 <= x <= 1`` (D0 Section 4.6). Both endpoints are valid and
    meaningful: ``0.0`` is a property whose expenses are wholly the landlord's,
    ``1.0`` a fully recoverable expense structure.

    **No silent clipping.** A ratio outside the domain is an ERROR, never
    clamped to the nearest endpoint -- clamping would turn an analyst's typo
    (``60`` meaning 60%) into a plausible, wrong model.

    Exists because ``expenses.build_recoverable_expense_pool`` takes the ratio
    as a bare scalar alongside an already-built schedule, so it needs a guard
    of its own. It shares ``_validate_ratio_field`` with
    ``validate_lease_level_operating_inputs`` below, so there is exactly one
    rule with two entry points rather than two rules that could drift.
    """

    return LeaseValidationResult(
        issues=tuple(
            _validate_ratio_field(
                recoverable_expense_ratio,
                code=LeaseIssueCode.RECOVERABLE_EXPENSE_RATIO_OUT_OF_DOMAIN,
                path=path,
                label="recoverable_expense_ratio",
            )
        )
    )


def require_valid_recoverable_expense_ratio(
    recoverable_expense_ratio: object,
    *,
    path: str = "operating_inputs.recoverable_expense_ratio",
) -> LeaseValidationResult:
    """Validate a standalone ratio and raise ``LeaseValidationError`` on any
    ERROR."""

    result = validate_recoverable_expense_ratio(
        recoverable_expense_ratio, path=path
    )
    if result.errors:
        raise LeaseValidationError(result)
    return result


def validate_lease_level_operating_inputs(
    operating_inputs: LeaseLevelOperatingInputs,
    *,
    path: str = "operating_inputs",
) -> LeaseValidationResult:
    """Validate one ``LeaseLevelOperatingInputs`` (D4.1).

    Rules are evaluated in a **fixed order** so the emitted sequence is
    reproducible and never depends on ``dict`` iteration, ``set`` iteration or
    the caller: the five fixed expense lines in
    ``MonthlyPropertyExpenseSchedule``'s declared order, then
    ``expense_growth``, then ``recoverable_expense_ratio``, then the revenue
    and rate fields D4.3 will consume, then the credit-loss warning last.

    **Every field is validated, including the four this gate does not use.**
    ``other_income``, ``other_income_growth``, ``management_fee_pct`` and
    ``credit_loss_pct`` are declared on the contract by D4 Section 9.2 and are
    financially inert until D4.3 -- but an accepted field that nothing checks
    is a hole, and a negative ``other_income`` should be refused when it is
    supplied, not two gates later. Validating a value is not calculating with
    it: no D4.1 output changes when any of the four changes.

    Domains, each identical to the one ``anchor.validation`` applies to the
    same Detailed concept:

    - the five fixed expense lines and ``other_income`` -- finite, ``>= 0``
    - ``expense_growth`` and ``other_income_growth`` -- finite, ``> -1``
    - ``management_fee_pct``, ``credit_loss_pct`` and
      ``recoverable_expense_ratio`` -- finite, ``0 <= x <= 1``

    **One WARNING** (D0 Section 15.4): ``UNUSUALLY_HIGH_CREDIT_LOSS`` above
    10%. Lease-Level's ``credit_loss_pct`` covers **bad debt only** -- physical
    vacancy is modeled explicitly, per suite, per month -- so a figure at
    Detailed's blended ``vacancy_credit_loss_pct`` magnitude usually means the
    two were confused and vacancy is about to be counted twice. It is a
    warning, not an error: a genuinely high bad-debt assumption is computable
    and defensible, and Anchor never downgrades a mathematically invalid input
    to a warning nor upgrades a merely unusual one to an error.
    """

    issues: list[LeaseValidationIssue] = []

    for name in _FIXED_EXPENSE_FIELDS:
        issues.extend(
            _validate_non_negative_dollars(
                getattr(operating_inputs, name),
                code=LeaseIssueCode.PROPERTY_EXPENSE_OUT_OF_DOMAIN,
                path=f"{path}.{name}",
                label=name,
            )
        )

    issues.extend(
        _validate_growth_field(
            operating_inputs.expense_growth,
            code=LeaseIssueCode.EXPENSE_GROWTH_OUT_OF_DOMAIN,
            path=f"{path}.expense_growth",
            label="expense_growth",
        )
    )
    issues.extend(
        _validate_ratio_field(
            operating_inputs.recoverable_expense_ratio,
            code=LeaseIssueCode.RECOVERABLE_EXPENSE_RATIO_OUT_OF_DOMAIN,
            path=f"{path}.recoverable_expense_ratio",
            label="recoverable_expense_ratio",
        )
    )
    issues.extend(
        _validate_non_negative_dollars(
            operating_inputs.other_income,
            code=LeaseIssueCode.OTHER_INCOME_OUT_OF_DOMAIN,
            path=f"{path}.other_income",
            label="other_income",
        )
    )
    issues.extend(
        _validate_growth_field(
            operating_inputs.other_income_growth,
            code=LeaseIssueCode.OTHER_INCOME_GROWTH_OUT_OF_DOMAIN,
            path=f"{path}.other_income_growth",
            label="other_income_growth",
        )
    )
    issues.extend(
        _validate_ratio_field(
            operating_inputs.management_fee_pct,
            code=LeaseIssueCode.MANAGEMENT_FEE_OUT_OF_DOMAIN,
            path=f"{path}.management_fee_pct",
            label="management_fee_pct",
        )
    )
    credit_loss_issues = _validate_ratio_field(
        operating_inputs.credit_loss_pct,
        code=LeaseIssueCode.CREDIT_LOSS_OUT_OF_DOMAIN,
        path=f"{path}.credit_loss_pct",
        label="credit_loss_pct",
    )
    issues.extend(credit_loss_issues)

    if not credit_loss_issues and (
        operating_inputs.credit_loss_pct > _UNUSUAL_CREDIT_LOSS_THRESHOLD
    ):
        issues.append(
            _issue(
                LeaseIssueCode.UNUSUALLY_HIGH_CREDIT_LOSS,
                f"{path}.credit_loss_pct",
                f"credit_loss_pct {operating_inputs.credit_loss_pct!r} exceeds "
                "10%. Lease-Level credit loss covers bad debt only; physical "
                "vacancy is already modeled per suite per month, so a Detailed "
                "vacancy_credit_loss_pct must not be carried across here.",
                LeaseIssueSeverity.WARNING,
            )
        )

    return LeaseValidationResult(issues=tuple(issues))


def require_valid_lease_level_operating_inputs(
    operating_inputs: LeaseLevelOperatingInputs,
    *,
    path: str = "operating_inputs",
) -> LeaseValidationResult:
    """Validate property operating inputs and raise on any ERROR.

    Returns the full result when valid, so a caller wanting both the go-ahead
    and any warnings needs exactly one call.
    """

    result = validate_lease_level_operating_inputs(operating_inputs, path=path)
    if result.errors:
        raise LeaseValidationError(result)
    return result
