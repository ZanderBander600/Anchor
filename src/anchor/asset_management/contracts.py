"""Gate AM1 -- the Managed Asset and Monthly Performance contracts.

Restates ``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md``
Sections 2, 3, 4 and 5 (authorized); that document governs on any discrepancy.
Like ``anchor.partnership.contracts`` and ``anchor.capital_structure.contracts``,
this module performs no calculation and no I/O -- it only describes shapes.

AM1 is a **post-acquisition** layer. It consumes an approved acquisition only
as provenance (a name, a date and one fingerprint string) and never reaches an
underwriting engine, a Scenario, a Strategy, a Capital Structure or a
Partnership. Nothing here is appended to an acquisition result, and no
acquisition contract is imported: a Managed Asset is not a Deal.

Four groups:

- **Identity**: ``ManagedAsset`` -- an owned building, created once from a
  saved Deal and never rewritten by a later Deal edit.
- **Authored inputs**: ``MonthlyReportPeriod`` and ``OperatingFigures`` -- the
  twelve primitive operating lines plus occupancy, entered explicitly for both
  the approved budget and the actual results. No monthly figure is ever derived
  from an annual underwriting forecast.
- **Issues and errors**: structural refusal (``AssetReportValidationError``) and
  the typed frozen-budget conflict (``BudgetImmutableError``), deliberately
  distinct from one another.
- **Results**: the computed monthly and year-to-date performance namespace.
  Nothing computed here is persisted (Section 5.6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from ..asset_types import AssetClassification, AssetType


# =============================================================================
# Identity
# =============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagedAsset:
    """One owned building under management.

    Created from a saved Deal exactly once (``source_deal_id`` is unique), and
    thereafter an independent record. ``acquisition_fingerprint`` is the
    authoritative analysis fingerprint of the Deal *at the moment of creation* --
    the frozen approved acquisition basis. A later Deal edit changes that Deal's
    current fingerprint and leaves this copy, this asset, its budgets and its
    historical reports untouched; the divergence is provenance the product may
    show, never a reason to rewrite anything.

    ``market`` is optional analyst context. ``None`` is "not stated" -- never a
    fabricated default.

    **Classification (Asset Types 1)** is ``asset_type`` and ``asset_subtype``:
    a snapshot of the source Deal's classification copied once, at creation,
    exactly as the acquisition fingerprint is. A later Deal edit reclassifies
    the Deal and leaves this copy untouched. Both ``None`` is "Not specified" --
    an asset created before Asset Types 1, or from a Deal that was not yet
    classified. No type is ever inferred for it.

    ``property_type`` is **legacy** analyst text from before Asset Types 1, when
    it was typed by hand at creation. It is preserved and read back verbatim so
    nothing an analyst wrote is lost, but it is no longer authored, it is not a
    classification, and it is never mapped onto an ``AssetType``.
    """

    id: str
    source_deal_id: str
    name: str
    acquisition_date: date
    property_type: str | None
    asset_type: AssetType | None = None
    asset_subtype: str | None = None
    market: str | None
    acquisition_fingerprint: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        # The pair is one classification, held to the same rules as a Deal's.
        if self.asset_type is None:
            if self.asset_subtype is not None:
                raise ValueError(
                    "A Managed Asset with no 'asset_type' must not carry an 'asset_subtype'."
                )
        else:
            AssetClassification(asset_type=self.asset_type, asset_subtype=self.asset_subtype)


# =============================================================================
# Authored inputs
# =============================================================================


#: The twelve primitive monetary fields of ``OperatingFigures``, in statement
#: order. Every one is authored; none is derived. The tuple is the single
#: authority for "which fields are money here" -- validation, the store codec,
#: the totals and the architecture guards all read it rather than restating the
#: list, so a field added to the contract cannot be silently skipped by one of
#: them.
MONETARY_FIELDS: tuple[str, ...] = (
    "rental_revenue",
    "other_income",
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_and_maintenance",
    "payroll",
    "management_fees",
    "other_operating_expenses",
    "capital_expenditures",
    "debt_service",
)

#: The seven operating-expense fields ``total_operating_expenses`` sums, in
#: statement order. A subset of ``MONETARY_FIELDS``: capital expenditures and
#: debt service are deliberately absent -- neither is an operating expense, and
#: including either would silently change NOI.
OPERATING_EXPENSE_FIELDS: tuple[str, ...] = (
    "property_taxes",
    "insurance",
    "utilities",
    "repairs_and_maintenance",
    "payroll",
    "management_fees",
    "other_operating_expenses",
)

#: The two revenue fields ``total_revenue`` sums, in statement order.
REVENUE_FIELDS: tuple[str, ...] = ("rental_revenue", "other_income")


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatingFigures:
    """One month's operating figures: either the approved budget or the actual
    results. The same contract for both -- a budget and an actual are the same
    kind of statement, compared line for line, so they can never diverge in
    shape.

    ``occupancy`` is a fraction in ``[0, 1]``, matching the repository's
    existing occupancy convention exactly (``anchor.validation``'s
    ``0 <= value <= 1``). It is presented in percent and its variance in
    percentage points; both are conversions performed in Python, never a second
    stored scale.

    Every monetary field is finite and ``>= 0``. Negative money is refused
    rather than normalized: a negative "expense" is a correction the analyst
    must state as a smaller expense, not a sign this layer invents meaning for.
    """

    occupancy: float
    rental_revenue: float
    other_income: float
    property_taxes: float
    insurance: float
    utilities: float
    repairs_and_maintenance: float
    payroll: float
    management_fees: float
    other_operating_expenses: float
    capital_expenditures: float
    debt_service: float


@dataclass(frozen=True, slots=True, kw_only=True)
class MonthlyAssetReport:
    """One month of reporting for one Managed Asset.

    Identity is ``(managed_asset_id, reporting_month)``. ``reporting_month`` is
    always normalized to the first day of the month before it reaches this
    contract, so one calendar month has exactly one report and two spellings of
    the same month can never become two rows.

    ``budget`` is frozen at creation. It is carried on every read so the
    comparison never has to be reassembled from somewhere else, and every write
    path after the first refuses to change it (``BudgetImmutableError``).
    ``actual`` and ``commentary`` remain editable.

    ``commentary`` is analyst prose. ``None`` is "none written"; it is never
    generated, never interpreted, and reaches no calculation.
    """

    managed_asset_id: str
    reporting_month: date
    budget: OperatingFigures
    actual: OperatingFigures
    commentary: str | None
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Issues and errors
# =============================================================================


class AssetReportIssueCode(StrEnum):
    """Stable wire tokens for a structural refusal. Renaming one is a contract
    change; the value is what the API and the frontend match on."""

    INVALID_FIGURES = "invalid_figures"
    INVALID_AMOUNT = "invalid_amount"
    NEGATIVE_AMOUNT = "negative_amount"
    INVALID_OCCUPANCY = "invalid_occupancy"
    INVALID_REPORTING_MONTH = "invalid_reporting_month"
    INVALID_COMMENTARY = "invalid_commentary"
    INVALID_ASSET_NAME = "invalid_asset_name"
    INVALID_ACQUISITION_DATE = "invalid_acquisition_date"
    #: Retired by Asset Types 1: ``property_type`` is no longer authored, so no
    #: validator raises this. Kept so the token is never reused for a
    #: different meaning.
    INVALID_PROPERTY_TYPE = "invalid_property_type"
    INVALID_MARKET = "invalid_market"


@dataclass(frozen=True, slots=True, kw_only=True)
class AssetReportIssue:
    """One structural refusal.

    ``scope`` names which figures failed (``"budget"`` / ``"actual"``), or is
    ``None`` for an issue that belongs to the report itself rather than to one
    of its two statements. ``field`` names the exact contract field, so the
    frontend can anchor the message at the input the analyst typed in.
    """

    code: AssetReportIssueCode
    message: str
    scope: str | None
    field: str | None


class AssetReportValidationError(ValueError):
    """A structurally invalid Managed Asset or monthly report. Carries every
    issue found, in the validator's deterministic order -- never only the
    first, so one round trip reports every field the analyst must fix."""

    def __init__(self, issues: tuple[AssetReportIssue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(issue.message for issue in issues))


class BudgetImmutableError(Exception):
    """An attempt to change an approved budget after the report that froze it
    was created.

    Deliberately **not** an ``AssetReportValidationError``: the submitted budget
    may be perfectly well-formed. The refusal is about authority, not shape, and
    the product must be able to tell the two apart -- a validation failure says
    "fix this number", this says "this number is no longer yours to change".

    ``changed_fields`` names every field that differs from the frozen budget, in
    statement order, so the refusal can be explained precisely rather than as a
    blanket rejection. Never raised as a silent replacement or a revision.
    """

    def __init__(self, *, managed_asset_id: str, reporting_month: date, changed_fields: tuple[str, ...]) -> None:
        self.managed_asset_id = managed_asset_id
        self.reporting_month = reporting_month
        self.changed_fields = changed_fields
        super().__init__(
            f"The approved budget for {reporting_month.isoformat()} was frozen when the "
            f"report was created and cannot be changed "
            f"({', '.join(changed_fields)}). Record the difference in the actual "
            "results or in commentary."
        )


class ManagedAssetExistsError(Exception):
    """This Deal already has a Managed Asset. One saved Deal creates at most
    one (Section 2.2); the existing asset's id is carried so the product can
    open it instead of reporting a dead end."""

    def __init__(self, *, source_deal_id: str, managed_asset_id: str) -> None:
        self.source_deal_id = source_deal_id
        self.managed_asset_id = managed_asset_id
        super().__init__(
            f"Deal {source_deal_id} already has a Managed Asset ({managed_asset_id})."
        )


class MonthlyReportExistsError(Exception):
    """This asset already has a report for this month. The frozen budget lives
    in that existing report, so a second create would be an undeclared budget
    revision; the caller must update the existing report's actuals instead."""

    def __init__(self, *, managed_asset_id: str, reporting_month: date) -> None:
        self.managed_asset_id = managed_asset_id
        self.reporting_month = reporting_month
        super().__init__(
            f"A report for {reporting_month.isoformat()} already exists for this asset."
        )


class ManagedAssetNotFoundError(LookupError):
    """No Managed Asset with this id."""


class MonthlyReportNotFoundError(LookupError):
    """No report for this asset and month."""


# =============================================================================
# Results
# =============================================================================


class FinancialLine(StrEnum):
    """Every reportable line, authored and derived, in statement order.

    The token is the wire spelling and the stable identity of a row. Derived
    lines are members here because they are compared exactly as authored lines
    are -- a variance on Net Operating Income is the same kind of fact as a
    variance on Payroll, and giving it a different representation would let the
    two drift.
    """

    OCCUPANCY = "occupancy"
    RENTAL_REVENUE = "rental_revenue"
    OTHER_INCOME = "other_income"
    TOTAL_REVENUE = "total_revenue"
    PROPERTY_TAXES = "property_taxes"
    INSURANCE = "insurance"
    UTILITIES = "utilities"
    REPAIRS_AND_MAINTENANCE = "repairs_and_maintenance"
    PAYROLL = "payroll"
    MANAGEMENT_FEES = "management_fees"
    OTHER_OPERATING_EXPENSES = "other_operating_expenses"
    TOTAL_OPERATING_EXPENSES = "total_operating_expenses"
    NET_OPERATING_INCOME = "net_operating_income"
    CAPITAL_EXPENDITURES = "capital_expenditures"
    CASH_FLOW_AFTER_CAPEX = "cash_flow_after_capex"
    DEBT_SERVICE = "debt_service"
    NET_CASH_FLOW = "net_cash_flow"


class Assessment(StrEnum):
    """How a variance reads to an asset manager.

    ``NEUTRAL`` is a statement, not an absence: it says this line has no
    favorable direction at all, which is why it can never be confused with
    ``ON_PLAN`` (a line that does have a direction and landed exactly on it).
    """

    FAVORABLE = "favorable"
    UNFAVORABLE = "unfavorable"
    ON_PLAN = "on_plan"
    NEUTRAL = "neutral"


class VarianceDirection(StrEnum):
    """Which sign of ``actual - budget`` is favorable on a line.

    Declared per line in ``performance.py`` and carried on every variance so
    the frontend never has to re-derive favorability from the line's name -- the
    single place that could quietly disagree with the engine.
    """

    HIGHER_IS_FAVORABLE = "higher_is_favorable"
    LOWER_IS_FAVORABLE = "lower_is_favorable"
    NO_DIRECTION = "no_direction"


class UnitOfMeasure(StrEnum):
    """How a line's figures are scaled. ``PERCENT`` lines carry a fraction and
    a percentage-point variance; ``CURRENCY`` lines carry nominal dollars."""

    CURRENCY = "currency"
    PERCENT = "percent"


@dataclass(frozen=True, slots=True, kw_only=True)
class PeriodTotals:
    """Every derived total for one statement (a budget or an actual), for one
    period (a month or a year to date).

    ``noi_margin`` is ``None`` when total revenue is zero -- unavailable, which
    is neither zero nor infinite. A zero margin would assert that the asset
    earned nothing on revenue it did earn; this asserts that the ratio has no
    value, which is the truth.
    """

    total_revenue: float
    total_operating_expenses: float
    net_operating_income: float
    cash_flow_after_capex: float
    net_cash_flow: float
    noi_margin: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class LineVariance:
    """One line compared: what was approved, what happened, and how that reads.

    ``variance_pct`` is ``None`` when the budget is zero -- unavailable for the
    same reason ``noi_margin`` is. ``variance`` itself is always present: the
    difference is perfectly well defined even when the ratio is not.

    On a ``PERCENT`` line, ``budget``/``actual``/``variance`` stay on the
    contract's own fraction scale and ``variance_points`` carries the
    percentage-point difference the product reports. ``variance_points`` is
    ``None`` on every ``CURRENCY`` line -- percentage points are not a thing a
    dollar line has.
    """

    line: FinancialLine
    unit: UnitOfMeasure
    direction: VarianceDirection
    budget: float
    actual: float
    variance: float
    variance_pct: float | None
    variance_points: float | None
    assessment: Assessment


@dataclass(frozen=True, slots=True, kw_only=True)
class AttentionItem:
    """One deterministically unfavorable result, worded for a person.

    Derived only from ``LineVariance`` values the engine already computed --
    never generated, never ranked by a model, and never surfacing a
    ``NEUTRAL``, ``ON_PLAN`` or ``FAVORABLE`` line. ``message`` states the fact
    in words so the item never depends on color alone.
    """

    line: FinancialLine
    message: str
    assessment: Assessment


@dataclass(frozen=True, slots=True, kw_only=True)
class NoiTrendPoint:
    """Budget and actual NOI for one reported month of the selected calendar
    year, in month order. Only months that have a saved report appear -- a
    month with no report is absent, never a zero that would read as a month in
    which the asset earned nothing."""

    reporting_month: date
    budget_net_operating_income: float
    actual_net_operating_income: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PeriodPerformance:
    """One period's complete comparison: both statements' totals, every line's
    variance in statement order, and the attention items derived from them."""

    budget: PeriodTotals
    actual: PeriodTotals
    lines: tuple[LineVariance, ...]
    attention: tuple[AttentionItem, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class AssetPerformanceResult:
    """The authoritative result for one Managed Asset at one reporting month:
    the month itself, the year to date through it, and the NOI trend.

    ``year_to_date`` sums January through ``reporting_month`` over the saved
    reports of that calendar year. It carries no occupancy comparison at all --
    occupancy is a rate, and a sum of rates is not a fact (Section 4.6), so
    rather than reporting a meaningless number the year-to-date line set simply
    omits it.
    """

    managed_asset_id: str
    reporting_month: date
    monthly: PeriodPerformance
    year_to_date: PeriodPerformance
    year_to_date_months: int
    noi_trend: tuple[NoiTrendPoint, ...]
    commentary: str | None
