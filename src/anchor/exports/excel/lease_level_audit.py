"""Excel Export 3 -- the Lease-Level Underwrite formula-audit workbook.

One workbook that rebuilds a saved Lease-Level Deal's economics in Excel
formulas, from the rent roll upward::

    Suites and leases
      -> the rollover-event lattice and its probability mass
      -> each event's own monthly leasing economics
      -> the suite and property leasing aggregates
      -> tenant expense recoveries against the one recoverable pool
      -> the monthly property statement (EGI, the management fee, NOI)
      -> the annual projection and the forward Year H+1 exit NOI
      -> the shared acquisition, debt, sale, equity and return model

Everything from NOI downward is the shared model in ``_workbook.py``, because
in Anchor it genuinely is the same model: Lease-Level hands an
``OperatingProjectionLike`` to the identical unmodified acquisition engine that
Quick and Detailed do
(``anchor.analysis.lease_level.analyze_lease_level_acquisition_with_projection``).
The one thing Lease-Level adds below NOI is its rent roll's TI and LC, which
reach owner cash flow through the generic ``OperatingCapitalSchedule`` -- a
channel deliberately separate from Business Plan project capital.

**Fourteen sheets rather than the published eight.** Quick and Detailed model a
property-level operating statement, which fits eight sheets. A rent roll does
not: the calculation chain runs through per-suite, per-event and per-month
detail, and flattening it would hide exactly the steps this export exists to
show. The extra sheets are the chain's own stages, in order, so a reader can
follow one suite from its lease abstract to its contribution to exit NOI.

**Why the rollover lattice is laid out, not looked up.** Anchor's recursive
rollover is a probability-mass state machine over *rollover-event states*
keyed by expiration period (D2 Section 5.5). Its structure is pure integer
arithmetic: a state at period ``p`` produces a child at ``p + floor(D_b) +
T_b`` for each branch ``b``, so the reachable states are a lattice fixed by the
seed, the two branch deltas and the horizon. This module enumerates that
lattice with integers only -- never from a financial result -- and Excel
computes every mass on it by its own recurrence. No monthly chain is copied
from Python: the frozen Anchor values live on Anchor Results and nowhere else.

**Term and downtime are structural.** Because they set the lattice, they are
disclosed but fixed, exactly as the hold period is in Excel Export 1 and 2 for
setting the period columns. Every other leasing assumption -- rent levels,
spreads, growth, renewal probability, free rent, TI, LC and escalation -- stays
an editable Working Input, and none of them can move a state.

The formulas are an *independent representation* of the ratified D0-D4
contracts; they are never read back by Anchor and never feed an application
result. Every formula cell is written with a *pessimistic* cached value, so
only a real recalculation can make a check pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

from ...leasing import Lease, MarketLeasingAssumptions, Suite
from ...leasing.calendar import (
    month_index,
    month_start_for_index,
    projection_month_count,
)
from ...leasing.contracts import (
    EscalationBasis,
    InitialVacancyStrategy,
    LeaseType,
    RecoveryBasis,
    RolloverBranchKind,
)
from ...leasing.market import resolve_market_leasing
from ._workbook import (
    ANCHOR,
    AUDIT,
    CHECKS,
    DEBT,
    EQUITY,
    EXCEL_MAX_COLUMNS,
    EXCEL_MAX_ROWS,
    INPUTS,
    NOTE_GRAY,
    NUM_CURRENCY,
    NUM_CURRENCY_CENTS,
    NUM_FACTOR,
    NUM_INTEGER,
    NUM_MULTIPLE,
    NUM_PERCENT,
    NUM_PERCENT_FINE,
    SUMMARY,

    _PROTECTION,
    _AuditWorkbookBase,
    _Check,
    _cell,
    _InputSpec,
    _range,
    _xref,
)
from .source import (
    LEASE_LEVEL_EXPORT_CONTRACT_VERSION,
    LeaseLevelAuditExportError,
    LeaseLevelAuditRefusalCode,
    LeaseLevelAuditSource,
)

__all__ = [
    "LEASE_LEVEL_SHEETS",
    "build_lease_level_audit_workbook",
    "plan_lease_level_workbook",
]

# --- The four sheets this export adds to the published eight -----------------

SUITES = "Suites"
LEASES = "Leases"
ROLLOVER = "Rollover"
MONTHLY_LEASING = "Monthly Leasing"
MONTHLY_RECOVERIES = "Monthly Recoveries"
MONTHLY_PROPERTY = "Monthly Property"
ANNUAL = "Annual Projection"

#: Sheets in their final order. ``Annual Projection`` takes the structural
#: place ``Operating Projection`` holds in the other two exports: it is the
#: sheet carrying the annual NOI row and the below-NOI block.
LEASE_LEVEL_SHEETS: tuple[str, ...] = (
    SUMMARY,
    INPUTS,
    SUITES,
    LEASES,
    ROLLOVER,
    MONTHLY_LEASING,
    MONTHLY_RECOVERIES,
    MONTHLY_PROPERTY,
    ANNUAL,
    DEBT,
    EQUITY,
    ANCHOR,
    CHECKS,
    AUDIT,
)

#: The five fixed property expense lines, in the order
#: ``anchor.leasing.expenses.FIXED_EXPENSE_LINES`` declares them and in which
#: ``fixed_operating_expenses`` accumulates them.
FIXED_EXPENSE_LINES: tuple[tuple[str, str], ...] = (
    ("property_taxes", "Property taxes"),
    ("insurance", "Insurance"),
    ("utilities", "Utilities"),
    ("repairs_maintenance", "Repairs and maintenance"),
    ("other_operating_expenses", "Other operating expenses"),
)

#: The monthly property statement, in statement order: the key, the row label
#: and the ``MonthlyPropertyProjection`` field holding Anchor's own series.
#: One list, used to write the Excel rows, to freeze Anchor's, to reconcile
#: them month by month and to aggregate them annually -- so a line cannot be
#: modelled, frozen, checked or aggregated in isolation.
PROPERTY_LINES: tuple[tuple[str, str, str], ...] = (
    ("contractual_base_rent", "Contractual base rent", "contractual_base_rent"),
    ("free_rent", "Free rent", "free_rent"),
    ("cash_base_rent", "Cash base rent", "cash_base_rent"),
    ("expense_recovery", "Expense recoveries", "expense_recovery"),
    ("other_income", "Other income", "other_income"),
    ("credit_loss", "Credit loss", "credit_loss"),
    ("effective_gross_income", "Effective gross income", "effective_gross_income"),
    ("property_taxes", "Property taxes", "property_taxes"),
    ("insurance", "Insurance", "insurance"),
    ("utilities", "Utilities", "utilities"),
    ("repairs_maintenance", "Repairs and maintenance", "repairs_maintenance"),
    ("other_operating_expenses", "Other operating expenses", "other_operating_expenses"),
    ("fixed_operating_expenses", "Total fixed operating expenses", "fixed_operating_expenses"),
    ("management_fee", "Management fee", "management_fee"),
    ("total_operating_expenses", "Total operating expenses", "total_operating_expenses"),
    ("noi", "Net operating income", "noi"),
    ("tenant_improvements", "Tenant improvements", "tenant_improvements"),
    ("leasing_commissions", "Leasing commissions", "leasing_commissions"),
)

#: The per-suite monthly leasing series the workbook aggregates and checks,
#: against ``SuiteOperatingProjection``'s fields of the same names.
SUITE_LINES: tuple[tuple[str, str], ...] = (
    ("contractual_base_rent", "Contractual base rent"),
    ("cash_base_rent", "Cash base rent"),
    ("free_rent", "Free rent"),
    ("occupied_area_sf", "Occupied area"),
    ("tenant_improvements", "Tenant improvements"),
    ("leasing_commissions", "Leasing commissions"),
)

#: The per-event line items laid out on Monthly Leasing, in the order their
#: blocks appear. Each is one row per rollover event.
EVENT_LINES: tuple[tuple[str, str, str], ...] = (
    ("occupancy_factor", "Occupancy factor", "month-equivalents"),
    ("abatement", "Free rent abatement", "month-equivalents"),
    ("face", "Contractual base rent", "$"),
    ("active", "Contractually active", "1 = in term"),
    ("ti", "Tenant improvements", "$"),
    ("lc", "Leasing commissions", "$"),
)


# =============================================================================
# Structural planning -- integers only
#
# Nothing below reads a rent, a rate or an analysis result. It answers only
# "which rollover-event states exist, and how big is the workbook", which is
# exactly the question Excel cannot answer for itself because a formula cannot
# create a row.
# =============================================================================


@dataclass(frozen=True, slots=True)
class _Event:
    """One rollover event: a parent expiration period and a branch.

    ``initial_lease_up`` marks D3.6's deterministic first tenant, which sits at
    the boundary period 0 with mass ``1.0`` and is never split by the renewal
    probability. Every other event is an ordinary lattice node."""

    parent_period: int
    branch: RolloverBranchKind
    initial_lease_up: bool = False

    @property
    def label(self) -> str:
        if self.initial_lease_up:
            return "Initial lease-up"
        kind = "Renewal" if self.branch is RolloverBranchKind.RENEWAL else "New tenant"
        return f"{kind} of expiry M{self.parent_period}"


@dataclass(frozen=True, slots=True)
class _SuitePlan:
    """One suite's structural facts: which chain it follows and which
    rollover-event states its lattice reaches."""

    index: int
    suite: Suite
    lease: Lease | None
    assumptions: MarketLeasingAssumptions
    override: bool
    strategy: InitialVacancyStrategy | None
    #: Raw, unclamped in-place rent periods; ``None`` for a vacant suite.
    in_place_first: int | None
    in_place_last: int | None
    events: tuple[_Event, ...]

    @property
    def occupied(self) -> bool:
        return self.lease is not None

    @property
    def label(self) -> str:
        return self.suite.suite_label or self.suite.suite_id


def _branch_delta(assumptions: MarketLeasingAssumptions, branch: RolloverBranchKind) -> int:
    """How far a branch advances the expiration clock.

    ``child_expiration = c + T - 1`` with ``c = p + 1 + floor(D)`` gives
    ``child = p + floor(D) + T``, so the advance is independent of ``p``. That
    is the whole reason the reachable states form a fixed lattice, and it is
    why term and downtime are structural while everything else is editable."""

    if branch is RolloverBranchKind.RENEWAL:
        return floor(assumptions.renewal_downtime_months) + assumptions.renewal_term_months
    return floor(assumptions.new_downtime_months) + assumptions.new_term_months


def _reachable_states(seed: int, *, deltas: tuple[int, int], horizon: int) -> tuple[int, ...]:
    """Every rollover-event state the propagation will process, ascending.

    The same walk ``anchor.leasing.rollover._propagate_rollover_mass``
    performs, reduced to its integer skeleton: a state is processed only when
    ``1 <= p < horizon``, and each processed state offers a child at ``p + d``
    for each branch delta. Both branches are always enumerated, whatever the
    renewal probability, so that editing that probability -- which is a
    Working Input -- can change masses but never the layout."""

    states: set[int] = set()
    frontier = [seed]
    while frontier:
        period = frontier.pop()
        if period in states or not (1 <= period < horizon):
            continue
        states.add(period)
        for delta in deltas:
            frontier.append(period + delta)
    return tuple(sorted(states))


def _suite_plan(
    index: int,
    suite: Suite,
    lease: Lease | None,
    *,
    property_defaults: MarketLeasingAssumptions,
    analysis_start,
    horizon: int,
) -> _SuitePlan:
    """One suite's chain, resolved through the D0 Section 24.5 authority.

    ``resolve_market_leasing`` is called rather than restated, so the
    all-or-nothing override rule and the rent-level exception are the
    package's own and cannot drift here."""

    resolved = resolve_market_leasing(suite, property_defaults=property_defaults)
    assumptions = resolved.assumptions
    deltas = (
        _branch_delta(assumptions, RolloverBranchKind.RENEWAL),
        _branch_delta(assumptions, RolloverBranchKind.NEW_TENANT),
    )

    first = last = None
    strategy = None
    events: list[_Event] = []

    if lease is not None:
        first = month_index(lease.rent_commencement_date, analysis_start=analysis_start)
        last = month_index(lease.lease_expiration_date, analysis_start=analysis_start)
        seed = last
    else:
        treatment = suite.initial_vacancy
        strategy = treatment.strategy if treatment is not None else None
        if strategy is not InitialVacancyStrategy.MARKET_LEASE_UP:
            # HOLD_VACANT is an explicit all-zero chain: no lease, no event, no
            # split, terminal mass 1.0.
            return _SuitePlan(
                index=index, suite=suite, lease=None, assumptions=assumptions,
                override=suite.market_leasing_override is not None, strategy=strategy,
                in_place_first=None, in_place_last=None, events=(),
            )
        lease_up = treatment.initial_lease_up_months if treatment is not None else 0.0
        events.append(
            _Event(parent_period=0, branch=RolloverBranchKind.NEW_TENANT, initial_lease_up=True)
        )
        # The first tenant's own expiration seeds the shared propagation core,
        # exactly as D3.6 does -- and only when it falls inside the horizon.
        seed = floor(lease_up or 0.0) + assumptions.new_term_months

    for period in _reachable_states(seed, deltas=deltas, horizon=horizon):
        events.append(_Event(parent_period=period, branch=RolloverBranchKind.RENEWAL))
        events.append(_Event(parent_period=period, branch=RolloverBranchKind.NEW_TENANT))

    return _SuitePlan(
        index=index, suite=suite, lease=lease, assumptions=assumptions,
        override=suite.market_leasing_override is not None, strategy=strategy,
        in_place_first=first, in_place_last=last, events=tuple(events),
    )


@dataclass(frozen=True, slots=True)
class _WorkbookPlan:
    """The whole workbook's structure, and whether Excel can hold it."""

    months: int
    suites: tuple[_SuitePlan, ...]
    leasing_rows: int
    recovery_rows: int
    columns: int

    @property
    def events(self) -> int:
        return sum(len(plan.events) for plan in self.suites)


#: Rows each monthly sheet needs beyond its per-suite blocks: titles, section
#: bars, the month index bands and the property/suite total blocks. Deliberately
#: generous -- a capacity check that under-counts is worse than one that
#: refuses a workbook which would have just fitted.
_LEASING_FIXED_ROWS = 40
_RECOVERY_FIXED_ROWS = 40
#: Identity columns before the first month column on a monthly sheet.
_FIRST_MONTH_COL = 5


def plan_lease_level_workbook(source: LeaseLevelAuditSource) -> _WorkbookPlan:
    """Measure the workbook this Deal would need, before any of it is built.

    Excel's hard limits are real limits: a worksheet cannot hold more than
    ``EXCEL_MAX_ROWS`` rows or ``EXCEL_MAX_COLUMNS`` columns, and a workbook
    written past them is not a smaller workbook but a corrupt one. So the size
    is computed from the structural plan and refused up front, with a reason an
    analyst can act on, rather than discovered halfway through writing a file.

    No arbitrary commercial cap on suite count or hold period is imposed: the
    only bound is the one the file format actually has."""

    terms = source.terms
    months = projection_month_count(terms.hold_period)
    horizon = months
    lease_for_suite = {lease.suite_id: lease for lease in source.leases}
    plans = tuple(
        _suite_plan(
            index,
            suite,
            lease_for_suite.get(suite.suite_id),
            property_defaults=source.market_leasing,
            analysis_start=source.property_inputs.analysis_start_date,
            horizon=horizon,
        )
        for index, suite in enumerate(source.suites)
    )

    # Monthly Leasing: per suite, one section bar, the in-place block, one
    # block per event line, then the suite-total block at the end.
    leasing_rows = _LEASING_FIXED_ROWS
    for plan in plans:
        leasing_rows += 3 + (2 if plan.occupied else 0)
        leasing_rows += len(EVENT_LINES) * (len(plan.events) + 1)
    leasing_rows += len(plans) * (len(SUITE_LINES) + 1)

    # Monthly Recoveries: per suite, the in-place row and one row per event,
    # plus a suite total; then the property total.
    recovery_rows = _RECOVERY_FIXED_ROWS
    for plan in plans:
        recovery_rows += 3 + (1 if plan.occupied else 0) + len(plan.events)
    recovery_rows += len(plans)

    columns = _FIRST_MONTH_COL + months

    plan = _WorkbookPlan(
        months=months,
        suites=plans,
        leasing_rows=leasing_rows,
        recovery_rows=recovery_rows,
        columns=columns,
    )

    if columns > EXCEL_MAX_COLUMNS:
        raise LeaseLevelAuditExportError(
            LeaseLevelAuditRefusalCode.EXCEL_CAPACITY_EXCEEDED,
            f"This Deal's {terms.hold_period}-year hold needs {columns:,} columns on the "
            f"monthly sheets, and an Excel worksheet holds {EXCEL_MAX_COLUMNS:,}. Shorten "
            "the hold period to export an audit workbook.",
        )
    needed = max(leasing_rows, recovery_rows)
    if needed > EXCEL_MAX_ROWS:
        raise LeaseLevelAuditExportError(
            LeaseLevelAuditRefusalCode.EXCEL_CAPACITY_EXCEEDED,
            f"This Deal's {len(plans):,} suites and {plan.events:,} modelled rollover events "
            f"need {needed:,} rows on the monthly sheets, and an Excel worksheet holds "
            f"{EXCEL_MAX_ROWS:,}. Reduce the number of suites, or shorten the hold period so "
            "fewer rollovers are modelled, to export an audit workbook.",
        )
    return plan


#: Data validation for each editable leasing assumption, matching the domains
#: ``anchor.leasing.validation`` enforces. A field absent here takes none.
_LEASING_VALIDATION: dict[str, dict[str, object]] = {
    "market_rent_psf": {"validate": "decimal", "criteria": ">=", "value": 0},
    "market_rent_growth": {"validate": "decimal", "criteria": ">", "value": -1},
    "renewal_probability": {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": 1},
    "renewal_rent_spread": {"validate": "decimal", "criteria": ">", "value": -1},
    "renewal_rent_psf": {"validate": "decimal", "criteria": ">=", "value": 0},
    "successor_escalation_pct": {"validate": "decimal", "criteria": ">", "value": -1},
    "renewal_free_rent_months": {"validate": "decimal", "criteria": ">=", "value": 0},
    "renewal_ti_psf": {"validate": "decimal", "criteria": ">=", "value": 0},
    "renewal_lc_pct": {"validate": "decimal", "criteria": ">=", "value": 0},
    "renewal_expense_stop_psf": {"validate": "decimal", "criteria": ">=", "value": 0},
    "new_free_rent_months": {"validate": "decimal", "criteria": ">=", "value": 0},
    "new_ti_psf": {"validate": "decimal", "criteria": ">=", "value": 0},
    "new_lc_pct": {"validate": "decimal", "criteria": ">=", "value": 0},
    "new_expense_stop_psf": {"validate": "decimal", "criteria": ">=", "value": 0},
}


# =============================================================================
# The workbook
# =============================================================================


def _identifier(text: str) -> str:
    """A defined-name-safe token built from an analyst-authored label."""

    safe = "".join(ch if ch.isalnum() else "_" for ch in text)
    return safe.strip("_") or "X"


class _LeaseLevelAuditWorkbook(_AuditWorkbookBase):
    """Lease-Level Underwrite's formula-audit workbook."""

    SHEETS = LEASE_LEVEL_SHEETS
    OPERATING_SHEET = ANNUAL
    HAS_OPERATING_CAPITAL = True

    MODE_LABEL = "Lease-Level Underwrite"
    WORKBOOK_TITLE = "Lease-Level Underwrite Audit"
    CONTRACT_VERSION = LEASE_LEVEL_EXPORT_CONTRACT_VERSION
    SUMMARY_NOTE = (
        "Formula-level audit of a saved Anchor Lease-Level Underwrite analysis. The Excel model "
        "rebuilds the rent roll, the rollover chain, recoveries and the property statement from "
        "the Inputs sheet; Anchor's results are frozen for comparison."
    )
    CHECKS_NOTE = (
        "Every suite's monthly leasing lines, every monthly recovery, every monthly property "
        "line and every annual line are reconciled, not only NOI. The forward Year H+1 window "
        "is the exit NOI: it is the sum of months 12H+1 to 12H+12 of the same monthly series."
    )
    NOI_CONVENTION = (
        "NOI is built from the rent roll upward, in the one order the dependency graph allows: "
        "cash base rent and free rent from each suite's lease and rollover chain; expense "
        "recoveries as the tenant's pro-rata share of the recoverable pool, clipped by any "
        "expense stop; credit loss on cash rent and recoveries; EGI = cash base rent + "
        "recoveries + other income - credit loss; the management fee = EGI x fee %, on EGI "
        "including recoveries; NOI = EGI - fixed operating expenses - management fee. The "
        "management fee is never in the recoverable pool, which is what makes the graph acyclic. "
        "Tenant improvements and leasing commissions are below NOI and never reduce it."
    )
    SCOPE_NOTE = (
        "Only Lease-Level Underwrite Deals are supported. Quick Underwrite and Detailed "
        "Underwrite each have their own audit workbook; Investments, Scenarios, Strategies, "
        "Capital Structure, Partnership Waterfalls and Asset Management are not exported."
    )

    def __init__(self, source: LeaseLevelAuditSource) -> None:
        self.ll = source
        self.plan = plan_lease_level_workbook(source)
        self.months = self.plan.months
        self.suite_plans = self.plan.suites
        self.analysis_start = source.property_inputs.analysis_start_date
        #: Defined names by leasing field, per suite index: a suite following
        #: the property default reads the property-default name; one carrying a
        #: full override reads its own. Precedence is therefore visible in the
        #: formula rather than resolved invisibly.
        self.suite_names: dict[int, dict[str, str]] = {}
        #: Suites-sheet cells for each suite's resolved assumptions.
        self.suite_cells: dict[int, dict[str, str]] = {}
        super().__init__(source, acquisition=source.terms, results=source.results)

    def _refuse(self, message: str) -> Exception:
        return LeaseLevelAuditExportError(
            LeaseLevelAuditRefusalCode.LEASE_LEVEL_INPUTS_INVALID, message
        )

    def _consistency_problems(self) -> list[bool]:
        """The annual projection and the acquisition results are two halves of
        one analysis this export just ran. They are checked all the same: a
        disagreement would mean the engine returned an envelope whose halves
        describe different runs, and preferring one would hide that."""

        annual, results = self.ll.annual, self.results
        hold = self.hold
        monthly = self.ll.monthly
        return [
            *super()._consistency_problems(),
            len(monthly.noi) != self.months,
            len(annual.noi_by_year) != hold,
            annual.noi_by_year != results.noi_by_year,
            annual.exit_noi != results.exit_noi,
            annual.going_in_cap_rate != results.going_in_cap_rate,
            len(annual.tenant_improvements_by_year) != hold,
            len(annual.leasing_commissions_by_year) != hold,
        ]

    # ------------------------------------------------------------ month helpers

    def _month_col(self, period: int) -> int:
        """The column holding canonical month ``period`` (1-based)."""

        return _FIRST_MONTH_COL + period - 1

    def _monthly_layout(self, sheet: str, note: str, title: str) -> int:
        """Page setup, the identity columns and the month index band, shared by
        the three monthly sheets so their columns line up exactly."""

        ws = self.sheets[sheet]
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, 44)
        self._set_column(sheet, 1, 1, 16)
        self._set_column(sheet, 2, 2, 16)
        self._set_column(sheet, 3, 3, 26)
        self._set_column(sheet, 4, 4, 12)
        self._set_column(sheet, 5, _FIRST_MONTH_COL + self.months - 1, 13)
        ws.set_landscape()
        # A monthly sheet is far too wide to fit one page; it is a working
        # schedule, so it is left to print across pages rather than shrunk to
        # illegibility.
        ws.protect("", _PROTECTION)
        self._title(sheet, title, note)

        last_col = _FIRST_MONTH_COL + self.months - 1
        row = 3
        self._section(sheet, row, "Canonical timeline", last_col)
        row += 1
        self._headers(
            sheet, row,
            [(0, "Line", "left"), (1, "Units", "left"), (2, "Suite", "left"),
             (3, "Line / rollover event", "left"), (4, "Probability", "right"),
             *((self._month_col(m), f"M{m}", "right") for m in range(1, self.months + 1))],
        )
        row += 1
        self.month_index_row = row
        self._label(sheet, row, "Model month")
        for period in range(1, self.months + 1):
            ws.write_number(row, self._month_col(period), period, self.fmt.value("calc", NUM_INTEGER))
        row += 1
        self.hold_year_row = row
        self._label(sheet, row, "Hold year")
        for period in range(1, self.months + 1):
            self._formula(
                sheet, row, self._month_col(period),
                f"=FLOOR(({_cell(self.month_index_row, self._month_col(period), row_abs=True)}-1)/12,1)+1",
                "calc", NUM_INTEGER,
            )
        row += 1
        self._label(sheet, row, "Window")
        for period in range(1, self.months + 1):
            text = "Hold" if period <= 12 * self.hold else "Forward exit"
            ws.write_string(row, self._month_col(period), text, self.fmt.get(align="right", font_color=NOTE_GRAY))
        row += 1
        self._label(sheet, row, "Month start")
        for period in range(1, self.months + 1):
            start = month_start_for_index(period, analysis_start=self.analysis_start)
            ws.write_string(
                row, self._month_col(period), start.strftime("%b %Y"),
                self.fmt.get(align="right", font_color=NOTE_GRAY),
            )
        ws.freeze_panes(row + 1, 5)
        return row + 2
    # ----------------------------------------------------------------- Inputs

    #: Every market-leasing assumption, as ``(field, label, units, format,
    #: structural)``. ``structural`` marks the four that set the rollover
    #: lattice: a change to a term or a downtime would move which
    #: rollover-event states exist, and a worksheet's rows are fixed once
    #: written. They are disclosed and locked, exactly as the hold period is in
    #: Excel Export 1 and 2 for setting the period columns.
    LEASING_FIELDS: tuple[tuple[str, str, str, str, bool], ...] = (
        ("market_rent_psf", "Market rent", "$ per SF per year", NUM_CURRENCY_CENTS, False),
        ("market_rent_growth", "Market rent growth", "% per year", NUM_PERCENT, False),
        ("renewal_probability", "Renewal probability", "%", NUM_PERCENT, False),
        ("renewal_rent_spread", "Renewal rent spread to market", "%", NUM_PERCENT, False),
        ("renewal_rent_psf", "Renewal rent (explicit level)", "$ per SF per year", NUM_CURRENCY_CENTS, False),
        ("successor_escalation_pct", "Successor escalation", "% per year", NUM_PERCENT, False),
        ("renewal_term_months", "Renewal term", "months", NUM_INTEGER, True),
        ("renewal_downtime_months", "Renewal downtime", "months", NUM_FACTOR, True),
        ("renewal_free_rent_months", "Renewal free rent", "months", NUM_FACTOR, False),
        ("renewal_ti_psf", "Renewal tenant improvements", "$ per SF", NUM_CURRENCY_CENTS, False),
        ("renewal_lc_pct", "Renewal leasing commission", "% of full-term face rent", NUM_PERCENT, False),
        ("renewal_expense_stop_psf", "Renewal expense stop", "$ per SF per year", NUM_CURRENCY_CENTS, False),
        ("new_term_months", "New tenant term", "months", NUM_INTEGER, True),
        ("new_downtime_months", "New tenant downtime", "months", NUM_FACTOR, True),
        ("new_free_rent_months", "New tenant free rent", "months", NUM_FACTOR, False),
        ("new_ti_psf", "New tenant improvements", "$ per SF", NUM_CURRENCY_CENTS, False),
        ("new_lc_pct", "New tenant leasing commission", "% of full-term face rent", NUM_PERCENT, False),
        ("new_expense_stop_psf", "New tenant expense stop", "$ per SF per year", NUM_CURRENCY_CENTS, False),
    )

    _STRUCTURAL_NOTE = "Fixed: it sets which rollover events exist, and so the workbook rows"

    def _inputs_note(self) -> str:
        return (
            "Original Export is what Anchor analysed. Working Input starts equal to it and is "
            "the only column the model reads; edit it to explore a modified case. A suite with "
            "a full market-leasing override has its own section below the property defaults, "
            "and the Suites sheet shows which record each suite resolved to."
        )

    def _leasing_specs(self, assumptions: MarketLeasingAssumptions, prefix: str) -> list[_InputSpec]:
        """One record's leasing assumptions as input rows.

        ``renewal_rent_psf`` and the two expense stops are optional levels.
        When the saved record states none, no row is written and no defined
        name exists: the workbook offers no cell to type a level into that
        Anchor would not have consulted."""

        specs: list[_InputSpec] = []
        for field, label, units, number_format, structural in self.LEASING_FIELDS:
            value = getattr(assumptions, field)
            if value is None:
                continue
            specs.append(
                _InputSpec(
                    key=f"{prefix}{field}",
                    label=label,
                    units=units,
                    value=float(value),
                    number_format=number_format,
                    name=None if structural else f"{prefix}{_identifier(field)}",
                    fixed_note=self._STRUCTURAL_NOTE if structural else None,
                    validation=None if structural else _LEASING_VALIDATION.get(field),
                )
            )
        return specs

    def _input_specs(self) -> list[tuple[str, list[_InputSpec]]]:
        t = self.terms
        o = self.ll.operating_inputs
        p = self.ll.property_inputs
        positive = {"validate": "decimal", "criteria": ">", "value": 0}
        non_negative = {"validate": "decimal", "criteria": ">=", "value": 0}
        fraction = {"validate": "decimal", "criteria": "between", "minimum": 0, "maximum": 1}
        above_minus_one = {"validate": "decimal", "criteria": ">", "value": -1}

        sections: list[tuple[str, list[_InputSpec]]] = [
            (
                "Acquisition",
                [
                    _InputSpec("purchase_price", "Purchase price", "$", t.purchase_price, NUM_CURRENCY, name="Purchase_Price", validation=positive),
                    _InputSpec("acquisition_cost_pct", "Acquisition costs", "% of purchase price", t.acquisition_cost_pct, NUM_PERCENT, name="Acquisition_Cost_Pct", validation=fraction),
                    _InputSpec("rentable_area_sf", "Rentable area", "SF", p.rentable_area_sf, NUM_INTEGER, name="Rentable_Area", validation=positive),
                ],
            ),
            (
                "Property income",
                [
                    _InputSpec("other_income", "Other income", "$ per year", o.other_income, NUM_CURRENCY, name="Other_Income", validation=non_negative),
                    _InputSpec("other_income_growth", "Other income growth", "% per year", o.other_income_growth, NUM_PERCENT, name="Other_Income_Growth", validation=above_minus_one),
                    _InputSpec("credit_loss_pct", "Credit loss", "% of cash rent and recoveries", o.credit_loss_pct, NUM_PERCENT, name="Credit_Loss_Pct", validation=fraction),
                ],
            ),
            (
                "Property operating expenses (Year 1 amounts)",
                [
                    *(
                        _InputSpec(field, label, "$ per year", getattr(o, field), NUM_CURRENCY, name=_identifier(label), validation=non_negative)
                        for field, label in FIXED_EXPENSE_LINES
                    ),
                    _InputSpec("expense_growth", "Expense growth", "% per year", o.expense_growth, NUM_PERCENT, name="Expense_Growth", validation=above_minus_one),
                    _InputSpec("management_fee_pct", "Management fee", "% of effective gross income", o.management_fee_pct, NUM_PERCENT, name="Management_Fee_Pct", validation=fraction),
                    _InputSpec("recoverable_expense_ratio", "Recoverable expense share", "% of fixed operating expenses", o.recoverable_expense_ratio, NUM_PERCENT, name="Recoverable_Expense_Ratio", validation=fraction),
                ],
            ),
            (
                "Market leasing assumptions (property default)",
                self._leasing_specs(self.ll.market_leasing, ""),
            ),
        ]

        # A suite carrying a full override states every field itself: the
        # override is all-or-nothing (D0 Section 24.2), so it gets its own
        # complete section rather than a diff against the default.
        for plan in self.suite_plans:
            prefix = f"S{plan.index + 1}_"
            specs: list[_InputSpec] = []
            if plan.override:
                specs.extend(self._leasing_specs(plan.assumptions, prefix))
            elif plan.suite.market_rent_psf is not None:
                # D0 Section 24.1's one exception: a rent level alone, applied
                # on top of whichever record won.
                specs.append(
                    _InputSpec(
                        f"{prefix}market_rent_psf", "Market rent", "$ per SF per year",
                        plan.suite.market_rent_psf, NUM_CURRENCY_CENTS,
                        name=f"{prefix}market_rent_psf", validation=non_negative,
                    )
                )
            if plan.strategy is InitialVacancyStrategy.MARKET_LEASE_UP:
                treatment = plan.suite.initial_vacancy
                specs.append(
                    _InputSpec(
                        f"{prefix}initial_lease_up_months", "Initial lease-up period", "months",
                        float(treatment.initial_lease_up_months or 0.0) if treatment else 0.0,
                        NUM_FACTOR, fixed_note=self._STRUCTURAL_NOTE,
                    )
                )
            if specs:
                sections.append((f"Suite {plan.label} -- market leasing", specs))

        sections.append(
            (
                "Financing",
                [
                    _InputSpec("ltv", "Loan to value", "% of purchase price", t.ltv, NUM_PERCENT, name="Loan_To_Value", validation=fraction),
                    _InputSpec("interest_rate", "Interest rate", "% per year", t.interest_rate, NUM_PERCENT, name="Interest_Rate", validation=non_negative),
                    _InputSpec("amortization", "Amortization", "years", t.amortization, NUM_INTEGER, name="Amortization_Years", validation=positive),
                    _InputSpec("io_period", "Interest-only period", "years", t.io_period, NUM_INTEGER, name="IO_Period_Years", validation=non_negative),
                    _InputSpec("financing_fee_pct", "Financing fee", "% of loan amount", t.financing_fee_pct, NUM_PERCENT, name="Financing_Fee_Pct", validation=fraction),
                ],
            ),
        )
        sections.append(
            (
                "Hold and exit",
                [
                    _InputSpec("hold_period", "Hold period", "years", float(self.hold), NUM_INTEGER, fixed_note="Fixed: it sets the model months and years", name="Hold_Period"),
                    _InputSpec("exit_cap_rate", "Exit cap rate", "%", t.exit_cap_rate, NUM_PERCENT, name="Exit_Cap_Rate", validation=positive),
                    _InputSpec("disposition_cost_pct", "Disposition costs", "% of exit value", t.disposition_cost_pct, NUM_PERCENT, name="Disposition_Cost_Pct", validation=fraction),
                    _InputSpec("annual_capex_reserve", "Annual CapEx reserve", "$ per year", t.annual_capex_reserve, NUM_CURRENCY, name="CapEx_Reserve", validation=non_negative),
                    _InputSpec("closing_project_capital", "Closing project capital", "$ at Year 0", self.results.closing_project_capital, NUM_CURRENCY, name="Closing_Project_Capital", validation=non_negative),
                    _InputSpec("post_hold_project_capital", "Post-hold project capital", "$ (disclosure only)", self.results.post_hold_project_capital, NUM_CURRENCY, fixed_note="Disclosure only: never enters the hold"),
                ],
            ),
        )
        return sections
    # ------------------------------------------------------------- resolution

    def _input_ref(self, plan: _SuitePlan, field: str) -> str:
        """The Inputs cell one suite's assumption resolves to.

        D0 Section 24.5's precedence, expressed as a *reference* rather than
        recomputed: a suite with a full override reads its own row, a suite
        with only a rent level reads that one row and the property default for
        everything else, and every other suite reads the property default. The
        Suites sheet then shows the resolved value as a formula, so which
        record won is visible in the cell rather than hidden in this code."""

        own = f"S{plan.index + 1}_{field}"
        if f"input:{own}" in self.excel:
            return self.excel[f"input:{own}"]
        return self.excel[f"input:{field}"]

    def _suite(self, plan: _SuitePlan, field: str) -> str:
        """The Suites-sheet cell carrying one suite's resolved assumption."""

        return self.suite_cells[plan.index][field]

    # ----------------------------------------------------------------- Suites

    def _build_suites(self) -> None:
        sheet = SUITES
        ws = self.sheets[sheet]
        text_fields = (
            ("renewal_lease_type", "Renewal lease type"),
            ("renewal_recovery_basis", "Renewal recovery basis"),
            ("new_lease_type", "New tenant lease type"),
            ("new_recovery_basis", "New tenant recovery basis"),
        )
        numeric = self.LEASING_FIELDS
        last_col = 6 + len(numeric) + len(text_fields)

        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, 26)
        self._set_column(sheet, 1, 1, 16)
        self._set_column(sheet, 2, 3, 14)
        self._set_column(sheet, 4, 5, 22)
        self._set_column(sheet, 6, last_col, 15)
        ws.set_landscape()
        ws.protect("", _PROTECTION)
        self._title(
            sheet,
            "Suites",
            "Every suite, its share of the property, and the market leasing assumptions it "
            "resolved to. Each assumption is a formula reading the Inputs row that won under "
            "the override precedence, so an edit there moves exactly the suites it should.",
        )

        row = 3
        headers = [
            (0, "Suite", "left"), (1, "Suite ID", "left"), (2, "Area", "right"),
            (3, "Pro-rata share", "right"), (4, "Opening state", "left"),
            (5, "Assumptions from", "left"),
        ]
        for offset, (_field, label, _units, _fmt, _structural) in enumerate(numeric):
            headers.append((6 + offset, label, "right"))
        for offset, (_field, label) in enumerate(text_fields):
            headers.append((6 + len(numeric) + offset, label, "left"))
        self._headers(sheet, row, headers)
        row += 1

        for plan in self.suite_plans:
            suite = plan.suite
            # Analyst-authored: always literal text, never a formula.
            ws.write_string(row, 0, plan.label, self.fmt.text())
            ws.write_string(row, 1, suite.suite_id, self.fmt.text())
            area = self._formula(sheet, row, 2, f"={suite.suite_area_sf}", "calc", NUM_INTEGER)
            share = self._formula(
                sheet, row, 3, f"={_cell(row, 2)}/{self.excel['input:rentable_area_sf']}",
                "calc", NUM_PERCENT_FINE,
            )
            if plan.occupied:
                opening = "Leased"
            elif plan.strategy is InitialVacancyStrategy.MARKET_LEASE_UP:
                opening = "Vacant - market lease-up"
            elif plan.strategy is InitialVacancyStrategy.HOLD_VACANT:
                opening = "Vacant - held vacant"
            else:
                opening = "Vacant"
            ws.write_string(row, 4, opening, self.fmt.text())
            if plan.override:
                origin = "Suite override"
            elif suite.market_rent_psf is not None:
                origin = "Default + suite rent"
            else:
                origin = "Property default"
            ws.write_string(row, 5, origin, self.fmt.text())

            # Cross-sheet references: every other sheet reads these, so they
            # must name the Suites sheet rather than resolving locally.
            cells: dict[str, str] = {
                "area": _xref(sheet, row, 2),
                "share": _xref(sheet, row, 3),
            }
            for offset, (field, _label, _units, number_format, _structural) in enumerate(numeric):
                col = 6 + offset
                value = getattr(plan.assumptions, field)
                if value is None:
                    ws.write_string(row, col, "-", self.fmt.get(align="right", font_color=NOTE_GRAY))
                    continue
                cells[field] = self._formula(
                    sheet, row, col, f"={self._input_ref(plan, field)}", "link", number_format
                )
            for offset, (field, _label) in enumerate(text_fields):
                col = 6 + len(numeric) + offset
                member = getattr(plan.assumptions, field)
                ws.write_string(
                    row, col, member.value if member is not None else "-", self.fmt.text()
                )
            if plan.strategy is InitialVacancyStrategy.MARKET_LEASE_UP:
                cells["initial_lease_up_months"] = self._input_ref(plan, "initial_lease_up_months")
            self.suite_cells[plan.index] = cells
            self.suite_rows_by_index = getattr(self, "suite_rows_by_index", {})
            self.suite_rows_by_index[plan.index] = row
            row += 1

        ws.freeze_panes(4, 2)
        ws.autofilter(3, 0, row - 1, last_col)

    # ----------------------------------------------------------------- Leases

    def _build_leases(self) -> None:
        """The in-place rent roll, exactly as saved.

        Every figure an in-place lease contributes is derived from these
        columns, and the two period columns are the rent roll's contact with
        the canonical timeline: they are the *raw, unclamped* month indices, so
        a lease that commenced before the analysis start keeps its real
        escalation clock (failure mode FM-5) rather than being reset to
        Month 1."""

        sheet = LEASES
        ws = self.sheets[sheet]
        last_col = 13
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, 24)
        self._set_column(sheet, 1, 2, 22)
        self._set_column(sheet, 3, 13, 16)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.protect("", _PROTECTION)
        self._title(
            sheet,
            "Leases",
            "The in-place leases as saved. First and last rent periods are raw canonical month "
            "indices and are deliberately not clamped to the projection window: a lease that "
            "commenced before the analysis start keeps its own escalation clock.",
        )
        row = 3
        self._headers(
            sheet, row,
            [(0, "Suite", "left"), (1, "Lease ID", "left"), (2, "Tenant", "left"),
             (3, "Leased area", "right"), (4, "Rent commencement", "left"),
             (5, "Expiration", "left"), (6, "First rent period", "right"),
             (7, "Last rent period", "right"), (8, "Base rent", "right"),
             (9, "Escalation", "right"), (10, "Escalation basis", "left"),
             (11, "Lease type", "left"), (12, "Recovery basis", "left"),
             (13, "Expense stop", "right")],
        )
        row += 1
        first_row = row
        for plan in self.suite_plans:
            lease = plan.lease
            if lease is None:
                continue
            ws.write_string(row, 0, plan.label, self.fmt.text())
            # Analyst-authored identifiers and names: literal text always.
            ws.write_string(row, 1, lease.lease_id, self.fmt.text())
            ws.write_string(row, 2, lease.tenant_name or "-", self.fmt.text())
            self._formula(sheet, row, 3, f"={lease.leased_area_sf}", "calc", NUM_INTEGER)
            ws.write_string(row, 4, lease.rent_commencement_date.isoformat(), self.fmt.text())
            ws.write_string(row, 5, lease.lease_expiration_date.isoformat(), self.fmt.text())
            ws.write_number(row, 6, plan.in_place_first or 0, self.fmt.value("calc", NUM_INTEGER))
            ws.write_number(row, 7, plan.in_place_last or 0, self.fmt.value("calc", NUM_INTEGER))
            self._formula(sheet, row, 8, f"={lease.base_rent_psf}", "calc", NUM_CURRENCY_CENTS)
            self._formula(sheet, row, 9, f"={lease.escalation_pct}", "calc", NUM_PERCENT)
            ws.write_string(row, 10, lease.escalation_basis.value, self.fmt.text())
            ws.write_string(row, 11, lease.lease_type.value, self.fmt.text())
            ws.write_string(
                row, 12,
                lease.recovery_basis.value if lease.recovery_basis is not None else "-",
                self.fmt.text(),
            )
            if lease.expense_stop_psf is None:
                ws.write_string(row, 13, "-", self.fmt.get(align="right", font_color=NOTE_GRAY))
            else:
                self._formula(sheet, row, 13, f"={lease.expense_stop_psf}", "calc", NUM_CURRENCY_CENTS)
            self.lease_rows = getattr(self, "lease_rows", {})
            self.lease_rows[plan.index] = row
            row += 1
        if row == first_row:
            ws.write_string(row, 0, "No suite carries an in-place lease.", self.fmt.note())
            row += 1
        else:
            ws.autofilter(3, 0, row - 1, last_col)
        ws.freeze_panes(4, 1)

    # --------------------------------------------------------------- Rollover

    #: Rollover sheet columns.
    _R_SUITE, _R_EVENT, _R_PARENT = 0, 1, 2
    _R_SEED, _R_INHERITED, _R_STATE, _R_WEIGHT, _R_MASS = 3, 4, 5, 6, 7
    _R_TERM, _R_DOWNTIME, _R_COMMENCE, _R_EXPIRY, _R_WITHIN = 8, 9, 10, 11, 12
    _R_MARKET, _R_START, _R_FACE, _R_TI, _R_LC = 13, 14, 15, 16, 17

    def _full_term_face_factor(self, term_months: int, escalation: str) -> str:
        """The successor's full contractual term, as escalation steps.

        ``contractual_face_rent_over_full_term`` prices each of the term's
        months on the lease's own chronology, so month ``m`` carries
        ``(1 + esc) ^ floor((m - 1) / 12)``. Months sharing a step share a
        factor, so the sum over the term is the count in each step times that
        step's factor -- the same arithmetic, grouped. The counts are integers
        fixed by the term, which is structural, so they are written literally
        and no lookup or volatile function is needed.

        It is deliberately not a geometric closed form: the last step is a
        partial year whenever the term is not a whole number of years, and a
        closed form would quietly assume it is not."""

        parts: list[str] = []
        step = 0
        while 12 * step < term_months:
            count = min(12, term_months - 12 * step)
            if step == 0:
                parts.append(f"{count}")
            else:
                parts.append(f"{count}*(1+{escalation})^{step}")
            step += 1
        return "+".join(parts)

    def _build_rollover(self) -> None:
        sheet = ROLLOVER
        ws = self.sheets[sheet]
        last_col = self._R_LC
        ws.hide_gridlines(2)
        self._set_column(sheet, 0, 0, 22)
        self._set_column(sheet, 1, 1, 26)
        self._set_column(sheet, 2, last_col, 15)
        ws.set_landscape()
        ws.protect("", _PROTECTION)
        self._title(
            sheet,
            "Rollover",
            "Every rollover event Anchor models, and the probability mass reaching it. A state "
            "at expiry month p sends mass to its two branches; each branch's successor expires "
            "at p + floor(downtime) + term, which is where that mass arrives next. Mass is "
            "inherited only from events above, so the chain resolves in one pass and no formula "
            "is circular.",
        )
        row = 3
        self._headers(
            sheet, row,
            [(self._R_SUITE, "Suite", "left"), (self._R_EVENT, "Rollover event", "left"),
             (self._R_PARENT, "Parent expiry month", "right"),
             (self._R_SEED, "Seed mass", "right"), (self._R_INHERITED, "Inherited mass", "right"),
             (self._R_STATE, "State mass", "right"), (self._R_WEIGHT, "Branch weight", "right"),
             (self._R_MASS, "Event mass", "right"), (self._R_TERM, "Term", "right"),
             (self._R_DOWNTIME, "Downtime", "right"), (self._R_COMMENCE, "Commencement", "right"),
             (self._R_EXPIRY, "Successor expiry", "right"),
             (self._R_WITHIN, "Commences in window", "right"),
             (self._R_MARKET, "Market rent at commencement", "right"),
             (self._R_START, "Starting rent", "right"),
             (self._R_FACE, "Full-term face rent", "right"),
             (self._R_TI, "Tenant improvements", "right"),
             (self._R_LC, "Leasing commission", "right")],
        )
        row += 1
        header_row = row
        #: Rollover row per (suite index, event index).
        self.event_rows: dict[tuple[int, int], int] = {}

        for plan in self.suite_plans:
            if not plan.events:
                ws.write_string(row, 0, plan.label, self.fmt.text())
                ws.write_string(
                    row, 1,
                    "Held vacant: no lease, no rollover event, no probability split."
                    if plan.strategy is InitialVacancyStrategy.HOLD_VACANT
                    else "No rollover event falls inside the projection window.",
                    self.fmt.note(),
                )
                row += 1
                continue

            suite_first = row
            # The seed: an occupied suite's in-place lease expiry carries mass
            # 1.0 into its first state. A lease-up suite has no in-place lease
            # -- its first tenant is an event of its own, and the mass it sends
            # onward is inherited through the same column as any other.
            seed_period = plan.in_place_last if plan.occupied else None
            for event_index, event in enumerate(plan.events):
                self.event_rows[(plan.index, event_index)] = row
                self._write_rollover_row(plan, event, event_index, row, suite_first, seed_period)
                row += 1

        ws.freeze_panes(header_row, 2)
        if row > header_row:
            ws.autofilter(header_row - 1, 0, row - 1, last_col)
        self.rollover_last_row = row

    def _write_rollover_row(
        self,
        plan: _SuitePlan,
        event: _Event,
        event_index: int,
        row: int,
        suite_first: int,
        seed_period: int | None,
    ) -> None:
        sheet = ROLLOVER
        ws = self.sheets[sheet]
        renewal = event.branch is RolloverBranchKind.RENEWAL
        branch = "renewal" if renewal else "new"

        ws.write_string(row, self._R_SUITE, plan.label, self.fmt.text())
        ws.write_string(row, self._R_EVENT, event.label, self.fmt.text())
        ws.write_number(row, self._R_PARENT, event.parent_period, self.fmt.value("calc", NUM_INTEGER))

        # --- mass ---------------------------------------------------------
        seed = 1.0 if (seed_period is not None and event.parent_period == seed_period and renewal) else 0.0
        if event.initial_lease_up:
            # D3.6: the first tenant of an initially vacant suite is
            # deterministic. It is contributed once at mass 1.0 and is never
            # weighted by the renewal probability -- there is no incumbent, so
            # there is no renewal branch to split.
            seed = 1.0
        ws.write_number(row, self._R_SEED, seed, self.fmt.value("calc", NUM_FACTOR))

        if row > suite_first:
            masses = _range(None, suite_first, self._R_MASS, row - 1, self._R_MASS)
            expiries = _range(None, suite_first, self._R_EXPIRY, row - 1, self._R_EXPIRY)
            inherited = f"=SUMIFS({masses},{expiries},{_cell(row, self._R_PARENT)})"
        else:
            inherited = "=0"
        self._formula(sheet, row, self._R_INHERITED, inherited, "calc", NUM_FACTOR)

        if renewal or event.initial_lease_up:
            state = f"={_cell(row, self._R_SEED)}+{_cell(row, self._R_INHERITED)}"
        else:
            # Both branches of one state share its mass; the new-tenant row
            # reads the renewal row's rather than recomputing it, so the two
            # cannot disagree.
            state = f"={_cell(row - 1, self._R_STATE)}"
        self._formula(sheet, row, self._R_STATE, state, "calc", NUM_FACTOR)

        if event.initial_lease_up:
            weight = "=1"
        elif renewal:
            weight = f"={self._suite(plan, 'renewal_probability')}"
        else:
            weight = f"=1-{self._suite(plan, 'renewal_probability')}"
        self._formula(sheet, row, self._R_WEIGHT, weight, "link" if not event.initial_lease_up else "calc", NUM_PERCENT)
        self._formula(
            sheet, row, self._R_MASS,
            f"={_cell(row, self._R_STATE)}*{_cell(row, self._R_WEIGHT)}",
            "calc", NUM_FACTOR,
        )

        # --- timing -------------------------------------------------------
        term = self._suite(plan, f"{branch}_term_months")
        self._formula(sheet, row, self._R_TERM, f"={term}", "link", NUM_INTEGER)
        if event.initial_lease_up:
            downtime = self._suite(plan, "initial_lease_up_months")
        else:
            downtime = self._suite(plan, f"{branch}_downtime_months")
        self._formula(sheet, row, self._R_DOWNTIME, f"={downtime}", "link", NUM_FACTOR)
        # c = e + 1 + floor(D). The fractional part never makes a fractional
        # date: it is carried entirely by the commencement month's occupancy
        # factor on Monthly Leasing.
        self._formula(
            sheet, row, self._R_COMMENCE,
            f"={_cell(row, self._R_PARENT)}+1+FLOOR({_cell(row, self._R_DOWNTIME)},1)",
            "calc", NUM_INTEGER,
        )
        self._formula(
            sheet, row, self._R_EXPIRY,
            f"={_cell(row, self._R_COMMENCE)}+{_cell(row, self._R_TERM)}-1",
            "calc", NUM_INTEGER,
        )
        self._formula(
            sheet, row, self._R_WITHIN,
            f"=IF(AND({_cell(row, self._R_COMMENCE)}>=1,{_cell(row, self._R_COMMENCE)}<={self.months}),1,0)",
            "calc", NUM_INTEGER,
        )

        # --- pricing ------------------------------------------------------
        growth_index = f"FLOOR(({_cell(row, self._R_COMMENCE)}-1)/12,1)"
        self._formula(
            sheet, row, self._R_MARKET,
            f"={self._suite(plan, 'market_rent_psf')}*"
            f"(1+{self._suite(plan, 'market_rent_growth')})^{growth_index}",
            "calc", NUM_CURRENCY_CENTS,
        )
        if renewal and not event.initial_lease_up and "renewal_rent_psf" in self.suite_cells[plan.index]:
            # D0 Section 24.3: an explicit renewal level wins, and is measured
            # on the same anchor as market rent, so it is grown to c the same
            # way rather than used as a level at commencement.
            starting = (
                f"={self._suite(plan, 'renewal_rent_psf')}*"
                f"(1+{self._suite(plan, 'market_rent_growth')})^{growth_index}"
            )
        elif renewal and not event.initial_lease_up:
            starting = (
                f"={_cell(row, self._R_MARKET)}*(1+{self._suite(plan, 'renewal_rent_spread')})"
            )
        else:
            # A new letting is market, and a renewal spread never reaches it.
            starting = f"={_cell(row, self._R_MARKET)}"
        self._formula(sheet, row, self._R_START, starting, "calc", NUM_CURRENCY_CENTS)

        escalation = self._suite(plan, "successor_escalation_pct")
        term_months = (
            plan.assumptions.renewal_term_months if renewal and not event.initial_lease_up
            else plan.assumptions.new_term_months
        )
        steps = self._full_term_face_factor(term_months, escalation)
        self._formula(
            sheet, row, self._R_FACE,
            f"=({_cell(row, self._R_START)}*({steps}))*{self._suite(plan, 'area')}/12",
            "calc", NUM_CURRENCY,
        )
        ti_psf = self._suite(plan, f"{branch}_ti_psf")
        lc_pct = self._suite(plan, f"{branch}_lc_pct")
        self._formula(
            sheet, row, self._R_TI, f"={ti_psf}*{self._suite(plan, 'area')}", "calc", NUM_CURRENCY
        )
        # The basis is full-term contractual FACE rent: gross of free rent,
        # untruncated by the horizon and unreduced by a fractional first month.
        self._formula(
            sheet, row, self._R_LC,
            f"={lc_pct}*{_cell(row, self._R_FACE)}", "calc", NUM_CURRENCY,
        )
    # --------------------------------------------------------- Monthly Leasing

    def _m(self, col: int) -> str:
        """The canonical month number for a column, read from the index band."""

        return _cell(self.month_index_row, col, row_abs=True)

    def _build_monthly_leasing(self) -> None:
        sheet = MONTHLY_LEASING
        row = self._monthly_layout(
            sheet,
            "Every suite's leasing economics, month by month. Each rollover event carries its "
            "own unweighted lease economics on its own row; the suite totals below weight them "
            "by the probability mass the Rollover sheet computed. The in-place lease is "
            "contributed once, unweighted, because it is contractual history rather than a "
            "modelled outcome.",
            "Monthly Leasing",
        )
        ws = self.sheets[sheet]
        last_col = _FIRST_MONTH_COL + self.months - 1

        #: (suite index, event line key) -> (first row, last row) of that block.
        self.event_blocks: dict[tuple[int, str], tuple[int, int]] = {}
        #: suite index -> {"face": row, "occupied": row} for the in-place lease.
        self.in_place_rows: dict[int, dict[str, int]] = {}

        for plan in self.suite_plans:
            self._section(sheet, row, f"Suite {plan.label}", last_col)
            row += 1
            if plan.occupied:
                row = self._write_in_place_rows(plan, row)
            if not plan.events:
                ws.write_string(
                    row, 0,
                    "No rollover event falls inside the projection window for this suite.",
                    self.fmt.note(),
                )
                row += 2
                continue
            for key, label, units in EVENT_LINES:
                self._subsection(sheet, row, f"{label} -- by rollover event", last_col)
                row += 1
                first = row
                for event_index, event in enumerate(plan.events):
                    self._write_event_row(plan, event, event_index, key, label, units, row)
                    row += 1
                self.event_blocks[(plan.index, key)] = (first, row - 1)
            row += 1

        self._section(sheet, row, "Suite totals  (probability-weighted)", last_col)
        row += 1
        self._suite_totals_first = row
        self.suite_total_rows: dict[tuple[int, str], int] = {}
        for plan in self.suite_plans:
            for key, label in SUITE_LINES:
                self._write_suite_total_row(plan, key, label, row)
                self.suite_total_rows[(plan.index, key)] = row
                row += 1
        self._suite_totals_last = row - 1
        ws.autofilter(4, 0, self._suite_totals_last, 4)

    def _write_in_place_rows(self, plan: _SuitePlan, row: int) -> int:
        """The known lease's own contractual history.

        Its cash rent equals its contractual rent: free rent and downtime are
        successor concepts, and a known lease's dates are month-aligned, so it
        has no fractional month either. It is never probability-weighted."""

        sheet = MONTHLY_LEASING
        ws = self.sheets[sheet]
        lease = plan.lease
        assert lease is not None
        lease_row = self.lease_rows[plan.index]
        first, last = plan.in_place_first or 0, plan.in_place_last or 0
        area = _xref(LEASES, lease_row, 3)
        base = _xref(LEASES, lease_row, 8)
        escalation = _xref(LEASES, lease_row, 9)

        rows: dict[str, int] = {}
        for key, label, units, number_format in (
            ("face", "In-place contractual base rent", "$", NUM_CURRENCY),
            ("occupied", "In-place occupied area", "SF", NUM_INTEGER),
        ):
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, units)
            ws.write_string(row, 2, plan.label, self.fmt.text())
            ws.write_string(row, 3, lease.lease_id, self.fmt.text())
            self._formula(sheet, row, 4, "=1", "calc", NUM_FACTOR)
            for period in range(1, self.months + 1):
                col = self._month_col(period)
                month = self._m(col)
                active = f"AND({month}>={first},{month}<={last})"
                if key == "face":
                    if lease.escalation_basis is EscalationBasis.NONE:
                        rate = base
                    else:
                        # Counted from the lease's own rent commencement, on the
                        # raw unclamped period, so acquisition never resets the
                        # escalation clock.
                        rate = f"({base}*(1+{escalation})^FLOOR(({month}-{first})/12,1))"
                    formula = f"=IF({active},{rate}*{area}/12,0)"
                else:
                    formula = f"=IF({active},{area},0)"
                self._formula(sheet, row, col, formula, "calc", number_format)
            rows[key] = row
            row += 1
        self.in_place_rows[plan.index] = rows
        return row

    def _write_event_row(
        self,
        plan: _SuitePlan,
        event: _Event,
        event_index: int,
        key: str,
        label: str,
        units: str,
        row: int,
    ) -> None:
        sheet = MONTHLY_LEASING
        ws = self.sheets[sheet]
        r = self.event_rows[(plan.index, event_index)]
        commence = _xref(ROLLOVER, r, self._R_COMMENCE)
        expiry = _xref(ROLLOVER, r, self._R_EXPIRY)
        downtime = _xref(ROLLOVER, r, self._R_DOWNTIME)
        start = _xref(ROLLOVER, r, self._R_START)
        renewal = event.branch is RolloverBranchKind.RENEWAL and not event.initial_lease_up
        branch = "renewal" if renewal else "new"
        free_rent = self._suite(plan, f"{branch}_free_rent_months")
        escalation = self._suite(plan, "successor_escalation_pct")
        area = self._suite(plan, "area")

        self._label(sheet, row, label, indent=2)
        self._units(sheet, row, units)
        ws.write_string(row, 2, plan.label, self.fmt.text())
        ws.write_string(row, 3, event.label, self.fmt.text())
        self._formula(sheet, row, 4, f"={_xref(ROLLOVER, r, self._R_MASS)}", "link", NUM_FACTOR)

        number_format = {
            "occupancy_factor": NUM_FACTOR, "abatement": NUM_FACTOR, "face": NUM_CURRENCY,
            "active": NUM_INTEGER, "ti": NUM_CURRENCY, "lc": NUM_CURRENCY,
        }[key]
        first_col = _FIRST_MONTH_COL
        for period in range(1, self.months + 1):
            col = self._month_col(period)
            month = self._m(col)
            in_term = f"AND({month}>={commence},{month}<={expiry})"
            if key == "occupancy_factor":
                # O = 0 outside the term, 1 - frac(D) in the commencement month,
                # 1 thereafter. Total month-equivalents forgone between expiry
                # and full occupancy is exactly D.
                formula = (
                    f"=IF(NOT({in_term}),0,"
                    f"IF({month}={commence},1-({downtime}-FLOOR({downtime},1)),1))"
                )
            elif key == "abatement":
                # The occupancy block is written immediately above this one
                # (``EVENT_LINES`` order), so the same event's factor is a
                # plain same-sheet reference.
                occupancy_first, _ = self.event_blocks[(plan.index, "occupancy_factor")]
                occupancy = _cell(occupancy_first + event_index, col)
                if col == first_col:
                    formula = f"=MIN({occupancy},{free_rent})"
                else:
                    consumed = _range(None, row, first_col, row, col - 1)
                    # Sequential, not multiplicative: free rent is consumed only
                    # while the successor is economically present, so a whole
                    # free month is never spent on a fractional month's rent.
                    formula = f"=MIN({occupancy},{free_rent}-SUM({consumed}))"
            elif key == "face":
                rate = f"({start}*(1+{escalation})^FLOOR(({month}-{commence})/12,1))"
                formula = f"=IF({in_term},{rate}*{area}/12,0)"
            elif key == "active":
                formula = f"=IF({in_term},1,0)"
            elif key == "ti":
                formula = f"=IF({month}={commence},{_xref(ROLLOVER, r, self._R_TI)},0)"
            else:
                formula = f"=IF({month}={commence},{_xref(ROLLOVER, r, self._R_LC)},0)"
            self._formula(sheet, row, col, formula, "calc", number_format)

    def _write_suite_total_row(self, plan: _SuitePlan, key: str, label: str, row: int) -> None:
        """One suite's monthly total for one line.

        The in-place lease enters once and unweighted; every rollover event
        enters as ``mass x its own economics``. A whole branch is never added:
        each event's row carries only its own successor, so no generation can
        re-count its predecessor's months."""

        sheet = MONTHLY_LEASING
        ws = self.sheets[sheet]
        units = "SF" if key == "occupied_area_sf" else "$"
        number_format = NUM_INTEGER if key == "occupied_area_sf" else NUM_CURRENCY
        self._label(sheet, row, f"{plan.label} -- {label}", indent=1)
        self._units(sheet, row, units)
        ws.write_string(row, 2, plan.suite.suite_id, self.fmt.text())
        ws.write_string(row, 3, label, self.fmt.text())

        has_events = bool(plan.events)
        for period in range(1, self.months + 1):
            col = self._month_col(period)
            terms: list[str] = []
            if plan.occupied:
                rows = self.in_place_rows[plan.index]
                if key in ("contractual_base_rent", "cash_base_rent"):
                    terms.append(_cell(rows["face"], col))
                elif key == "occupied_area_sf":
                    terms.append(_cell(rows["occupied"], col))
            if has_events:
                def block(name: str) -> str:
                    first, last = self.event_blocks[(plan.index, name)]
                    return _range(None, first, col, last, col)

                first, last = self.event_blocks[(plan.index, "face")]
                mass = _range(None, first, 4, last, 4)
                if key == "contractual_base_rent":
                    terms.append(f"SUMPRODUCT({mass},{block('face')})")
                elif key == "cash_base_rent":
                    terms.append(
                        f"SUMPRODUCT({mass},{block('face')},"
                        f"{block('occupancy_factor')}-{block('abatement')})"
                    )
                elif key == "free_rent":
                    terms.append(f"SUMPRODUCT({mass},{block('face')},{block('abatement')})")
                elif key == "occupied_area_sf":
                    terms.append(f"SUMPRODUCT({mass},{block('active')})*{self._suite(plan, 'area')}")
                elif key == "tenant_improvements":
                    terms.append(f"SUMPRODUCT({mass},{block('ti')})")
                elif key == "leasing_commissions":
                    terms.append(f"SUMPRODUCT({mass},{block('lc')})")
            formula = "=" + ("+".join(terms) if terms else "0")
            self._formula(sheet, row, col, formula, "calc", number_format)

    # ------------------------------------------------------ Monthly Recoveries

    def _recovery_full_month(self, share: str, pool: str, lease_type, stop: str | None) -> str:
        """One lease's full-month recovery obligation, before responsibility.

        The three structures are genuinely different contracts, not one formula
        with a factor: a Gross tenant reimburses nothing because of what its
        lease says, and a Modified Gross tenant's stop is subtracted from the
        tenant's own monthly share, both sides in tenant-level dollars per
        month. The clip is never negative -- there is no landlord credit and no
        carryforward."""

        if lease_type is LeaseType.GROSS:
            return "0"
        tenant_share = f"{share}*{pool}"
        if lease_type is LeaseType.MODIFIED_GROSS:
            return f"MAX(0,{tenant_share}-{stop})"
        return tenant_share

    def _build_monthly_recoveries(self) -> None:
        sheet = MONTHLY_RECOVERIES
        row = self._monthly_layout(
            sheet,
            "Tenant expense recoveries, month by month. Exactly one recoverable pool exists for "
            "the whole analysis and every suite consumes it. The management fee is never in the "
            "pool -- that exclusion is what keeps the fee out of its own basis and the model "
            "free of any circular formula.",
            "Monthly Recoveries",
        )
        ws = self.sheets[sheet]
        last_col = _FIRST_MONTH_COL + self.months - 1

        self._section(sheet, row, "The one recoverable expense pool", last_col)
        row += 1
        self._label(sheet, row, "Fixed operating expenses", indent=1)
        self._units(sheet, row, "$")
        for period in range(1, self.months + 1):
            col = self._month_col(period)
            self._formula(
                sheet, row, col,
                f"={_xref(MONTHLY_PROPERTY, self.property_rows['fixed_operating_expenses'], col)}",
                "link", NUM_CURRENCY,
            )
        fixed_row = row
        row += 1
        self._label(sheet, row, "Recoverable expense pool", bold=True)
        self._units(sheet, row, "$")
        for period in range(1, self.months + 1):
            col = self._month_col(period)
            self._formula(
                sheet, row, col,
                f"={_cell(fixed_row, col)}*{self.excel['input:recoverable_expense_ratio']}",
                "calc", NUM_CURRENCY, bold=True,
            )
        pool_row = row
        row += 2

        self.recovery_rows: dict[tuple[int, int | None], int] = {}
        for plan in self.suite_plans:
            self._section(sheet, row, f"Suite {plan.label}", last_col)
            row += 1
            share = self._suite(plan, "share")
            if plan.occupied:
                row = self._write_recovery_row(plan, None, share, pool_row, row)
            for event_index, event in enumerate(plan.events):
                row = self._write_recovery_row(plan, event_index, share, pool_row, row, event=event)
            if not plan.occupied and not plan.events:
                ws.write_string(
                    row, 0, "Held vacant: no tenant, so no recovery.", self.fmt.note()
                )
                row += 1
            row += 1

        self._section(sheet, row, "Suite totals  (probability-weighted)", last_col)
        row += 1
        self._recovery_totals_first = row
        self.recovery_total_rows: dict[int, int] = {}
        for plan in self.suite_plans:
            self._label(sheet, row, f"{plan.label} -- Expense recoveries", indent=1)
            self._units(sheet, row, "$")
            ws.write_string(row, 2, plan.suite.suite_id, self.fmt.text())
            ws.write_string(row, 3, "Expense recoveries", self.fmt.text())
            contributors = [self.recovery_rows[(plan.index, None)]] if plan.occupied else []
            contributors += [
                self.recovery_rows[(plan.index, index)] for index in range(len(plan.events))
            ]
            for period in range(1, self.months + 1):
                col = self._month_col(period)
                if not contributors:
                    formula = "=0"
                else:
                    # Each contributor's row already carries its own mass in
                    # column 4; weighting completed dollars is the only thing
                    # probability does here. No lease type, basis, stop or share
                    # is ever averaged.
                    terms = "+".join(
                        f"{_cell(r, 4)}*{_cell(r, col)}" for r in contributors
                    )
                    formula = f"={terms}"
                self._formula(sheet, row, col, formula, "calc", NUM_CURRENCY)
            self.recovery_total_rows[plan.index] = row
            row += 1
        self._recovery_totals_last = row - 1
        ws.autofilter(4, 0, self._recovery_totals_last, 4)

    def _write_recovery_row(
        self,
        plan: _SuitePlan,
        event_index: int | None,
        share: str,
        pool_row: int,
        row: int,
        *,
        event: _Event | None = None,
    ) -> int:
        sheet = MONTHLY_RECOVERIES
        ws = self.sheets[sheet]

        if event_index is None:
            lease = plan.lease
            assert lease is not None
            label, identity = "In-place lease recovery", lease.lease_id
            lease_type = lease.lease_type
            mass = "=1"
            stop = None
            if lease.expense_stop_psf is not None:
                lease_row = self.lease_rows[plan.index]
                stop = f"({_xref(LEASES, lease_row, 13)}*{_xref(LEASES, lease_row, 3)}/12)"
        else:
            assert event is not None
            label, identity = f"{event.label} recovery", event.label
            renewal = event.branch is RolloverBranchKind.RENEWAL and not event.initial_lease_up
            branch = "renewal" if renewal else "new"
            lease_type = getattr(plan.assumptions, f"{branch}_lease_type")
            r = self.event_rows[(plan.index, event_index)]
            mass = f"={_xref(ROLLOVER, r, self._R_MASS)}"
            stop = None
            stop_field = f"{branch}_expense_stop_psf"
            if stop_field in self.suite_cells[plan.index]:
                stop = f"({self._suite(plan, stop_field)}*{self._suite(plan, 'area')}/12)"

        self._label(sheet, row, label, indent=1)
        self._units(sheet, row, "$")
        ws.write_string(row, 2, plan.label, self.fmt.text())
        ws.write_string(row, 3, identity, self.fmt.text())
        self._formula(sheet, row, 4, mass, "calc" if event_index is None else "link", NUM_FACTOR)

        for period in range(1, self.months + 1):
            col = self._month_col(period)
            pool = _cell(pool_row, col, row_abs=True)
            full = self._recovery_full_month(share, pool, lease_type, stop)
            if event_index is None:
                first, last = plan.in_place_first or 0, plan.in_place_last or 0
                month = self._m(col)
                # A known lease's responsibility is 1 or 0: both its dates are
                # month-aligned, so it has no fractional month. It is derived
                # from contractual activity, never from rent dollars -- a
                # zero-rent lease is still fully responsible.
                factor = f"IF(AND({month}>={first},{month}<={last}),1,0)"
            else:
                occupancy_first, _ = self.event_blocks[(plan.index, "occupancy_factor")]
                factor = _xref(MONTHLY_LEASING, occupancy_first + event_index, col)
            # O x full, in that order: the whole-month obligation is computed
            # first and then scaled, so a fractional month is never compared
            # against a whole month's stop.
            self._formula(sheet, row, col, f"={factor}*({full})", "calc", NUM_CURRENCY)

        self.recovery_rows[(plan.index, event_index)] = row
        return row + 1

    # -------------------------------------------------------- Monthly Property

    def _layout_monthly_property(self) -> None:
        """Lay out the property statement and fill everything that does not
        depend on recoveries.

        Split in two because the dependency runs both ways *between sheets* and
        neither way *between cells*: the pool reads this sheet's fixed expense
        total, and this sheet's EGI reads the recovery total. The management
        fee's exclusion from the pool is exactly what makes that safe."""

        sheet = MONTHLY_PROPERTY
        row = self._monthly_layout(
            sheet,
            "The property statement by canonical month, in the one order the dependency graph "
            "allows. Recovery revenue is income and is never netted against expenses; the "
            "management fee is a percentage of EGI including recoveries; credit loss is taken "
            "on cash rent and recoveries. Tenant improvements and leasing commissions are "
            "disclosed here but sit below NOI and never reduce it.",
            "Monthly Property",
        )
        ws = self.sheets[sheet]
        last_col = _FIRST_MONTH_COL + self.months - 1

        self.property_rows: dict[str, int] = {}
        groups = (
            ("Leasing revenue", ("contractual_base_rent", "free_rent", "cash_base_rent")),
            ("Other revenue", ("expense_recovery", "other_income", "credit_loss")),
            # The section band is named apart from the line it introduces: the
            # two sit in the same column, and a reader (or a test) looking up
            # the line must not find the heading above it instead.
            ("Effective gross income (EGI)", ("effective_gross_income",)),
            ("Operating expenses", (
                "property_taxes", "insurance", "utilities", "repairs_maintenance",
                "other_operating_expenses", "fixed_operating_expenses", "management_fee",
                "total_operating_expenses",
            )),
            ("Net operating income (NOI)", ("noi",)),
            ("Below NOI -- leasing capital", ("tenant_improvements", "leasing_commissions")),
        )
        labels = {key: label for key, label, _field in PROPERTY_LINES}
        bold_keys = {
            "cash_base_rent", "effective_gross_income", "fixed_operating_expenses",
            "total_operating_expenses", "noi",
        }
        for title, keys in groups:
            self._section(sheet, row, title, last_col)
            row += 1
            for key in keys:
                self._label(sheet, row, labels[key], bold=key in bold_keys, indent=0 if key in bold_keys else 1)
                self._units(sheet, row, "$")
                self.property_rows[key] = row
                row += 1
            row += 1

        self._section(sheet, row, "Occupancy", last_col)
        row += 1
        for key, label, units, number_format in (
            ("occupied_area_sf", "Occupied area", "SF", NUM_INTEGER),
            ("vacant_area_sf", "Vacant area", "SF", NUM_INTEGER),
            ("physical_occupancy", "Physical occupancy", "%", NUM_PERCENT_FINE),
        ):
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, units)
            self.property_rows[key] = row
            self.property_formats = getattr(self, "property_formats", {})
            self.property_formats[key] = number_format
            row += 1
        self._monthly_property_last_row = row

        # The lines that depend only on the Inputs sheet, written now so the
        # recoverable pool has a fixed expense total to read.
        for period in range(1, self.months + 1):
            col = self._month_col(period)
            hold_year = _cell(self.hold_year_row, col, row_abs=True)
            growth = self.excel["input:expense_growth"]
            for field, _label in FIXED_EXPENSE_LINES:
                amount = self.excel[f"input:{field}"]
                self._formula(
                    sheet, self.property_rows[field], col,
                    f"=({amount}*(1+{growth})^({hold_year}-1))/12", "calc", NUM_CURRENCY,
                )
            first = self.property_rows[FIXED_EXPENSE_LINES[0][0]]
            last = self.property_rows[FIXED_EXPENSE_LINES[-1][0]]
            self._formula(
                sheet, self.property_rows["fixed_operating_expenses"], col,
                f"=SUM({_range(None, first, col, last, col)})", "calc", NUM_CURRENCY, bold=True,
            )
            self._formula(
                sheet, self.property_rows["other_income"], col,
                f"=({self.excel['input:other_income']}*"
                f"(1+{self.excel['input:other_income_growth']})^({hold_year}-1))/12",
                "calc", NUM_CURRENCY,
            )

    def _finish_monthly_property(self) -> None:
        """Fill the lines that read the leasing and recovery schedules."""

        sheet = MONTHLY_PROPERTY
        rows = self.property_rows
        leasing_range = (self._suite_totals_first, self._suite_totals_last)
        recovery_range = (self._recovery_totals_first, self._recovery_totals_last)

        for period in range(1, self.months + 1):
            col = self._month_col(period)

            def leasing(line: str) -> str:
                values = _range(MONTHLY_LEASING, leasing_range[0], col, leasing_range[1], col)
                keys = _range(MONTHLY_LEASING, leasing_range[0], 3, leasing_range[1], 3)
                return f"SUMIFS({values},{keys},\"{line}\")"

            recoveries = _range(MONTHLY_RECOVERIES, recovery_range[0], col, recovery_range[1], col)

            for key, line in (
                ("contractual_base_rent", "Contractual base rent"),
                ("free_rent", "Free rent"),
                ("cash_base_rent", "Cash base rent"),
                ("tenant_improvements", "Tenant improvements"),
                ("leasing_commissions", "Leasing commissions"),
            ):
                self._formula(
                    sheet, rows[key], col, f"={leasing(line)}", "link", NUM_CURRENCY,
                    bold=key == "cash_base_rent",
                )
            self._formula(
                sheet, rows["expense_recovery"], col, f"=SUM({recoveries})", "link", NUM_CURRENCY
            )
            cash = _cell(rows["cash_base_rent"], col)
            recovery = _cell(rows["expense_recovery"], col)
            other = _cell(rows["other_income"], col)
            # Credit loss is taken on cash rent and recoveries -- not on other
            # income, and not on contractual rent.
            self._formula(
                sheet, rows["credit_loss"], col,
                f"={self.excel['input:credit_loss_pct']}*({cash}+{recovery})", "calc", NUM_CURRENCY,
            )
            loss = _cell(rows["credit_loss"], col)
            self._formula(
                sheet, rows["effective_gross_income"], col,
                f"={cash}+{recovery}+{other}-{loss}", "calc", NUM_CURRENCY, bold=True,
            )
            egi = _cell(rows["effective_gross_income"], col)
            # On EGI including recoveries, and never grown from a Year 1 amount.
            self._formula(
                sheet, rows["management_fee"], col,
                f"={egi}*{self.excel['input:management_fee_pct']}", "calc", NUM_CURRENCY,
            )
            self._formula(
                sheet, rows["total_operating_expenses"], col,
                f"={_cell(rows['fixed_operating_expenses'], col)}+{_cell(rows['management_fee'], col)}",
                "calc", NUM_CURRENCY, bold=True,
            )
            self._formula(
                sheet, rows["noi"], col,
                f"={egi}-{_cell(rows['total_operating_expenses'], col)}",
                "calc", NUM_CURRENCY, bold=True,
            )
            self._formula(
                sheet, rows["occupied_area_sf"], col,
                f"={leasing('Occupied area')}", "link", NUM_INTEGER,
            )
            occupied = _cell(rows["occupied_area_sf"], col)
            area = self.excel["input:rentable_area_sf"]
            self._formula(
                sheet, rows["vacant_area_sf"], col, f"={area}-{occupied}", "calc", NUM_INTEGER
            )
            self._formula(
                sheet, rows["physical_occupancy"], col,
                f"={occupied}/{area}", "calc", NUM_PERCENT_FINE,
            )

    # ------------------------------------------------------- Annual Projection

    def _build_operating(self) -> None:
        """The whole Lease-Level model, built in dependency order.

        ``_workbook.py`` calls this once and then writes debt, equity, returns
        and the reconciliation from ``noi_row`` and the below-NOI handles --
        exactly as it does for Quick and Detailed."""

        self._build_suites()
        self._build_leases()
        self._build_rollover()
        self._build_monthly_leasing()
        self._layout_monthly_property()
        self._build_monthly_recoveries()
        self._finish_monthly_property()
        self._build_annual()

    def _month_span(self, row: int, first_period: int, last_period: int) -> str:
        return _range(
            MONTHLY_PROPERTY, row, self._month_col(first_period), row, self._month_col(last_period)
        )

    def _build_annual(self) -> None:
        sheet = ANNUAL
        ws = self.sheets[sheet]
        hold = self.hold
        first_col = 2
        forward_col = first_col + hold
        last_col = forward_col
        self._base_layout(sheet, hold + 1)
        self._title(
            sheet,
            "Annual Projection",
            "Each hold year is the sum of its twelve canonical months, taken from Monthly "
            f"Property. Year {hold + 1} is the forward exit window -- months {12 * hold + 1} to "
            f"{12 * hold + 12} -- and its NOI is the exit NOI. It is never Year {hold} grown, "
            "never twelve times one month, and never gross of free rent.",
        )
        row = 3

        labels = [f"Year {year}" for year in self.years] + [f"Year {hold + 1}"]
        self._period_header(sheet, row, first_col, labels)
        row += 1
        year_row = row
        self._label(sheet, row, "Year number")
        for offset, year in enumerate([*self.years, hold + 1]):
            ws.write_number(row, first_col + offset, year, self.fmt.value("calc", NUM_INTEGER))
        row += 1
        self._label(sheet, row, "Months")
        for offset in range(hold + 1):
            ws.write_string(
                row, first_col + offset, f"M{12 * offset + 1}-M{12 * offset + 12}",
                self.fmt.get(align="right", font_color=NOTE_GRAY),
            )
        row += 1
        self._label(sheet, row, "Window")
        for offset in range(hold):
            ws.write_string(row, first_col + offset, "Hold year", self.fmt.get(align="right", font_color=NOTE_GRAY))
        ws.write_string(row, forward_col, "Exit NOI only", self.fmt.get(align="right", font_color=NOTE_GRAY))
        row += 2

        self.annual_rows: dict[str, int] = {}
        bold_keys = {
            "cash_base_rent", "effective_gross_income", "fixed_operating_expenses",
            "total_operating_expenses", "noi",
        }
        self._section(sheet, row, "Operating statement", last_col)
        row += 1
        for key, label, _field in PROPERTY_LINES:
            if key in ("tenant_improvements", "leasing_commissions"):
                continue
            self._label(sheet, row, label, bold=key in bold_keys, indent=0 if key in bold_keys else 1)
            self._units(sheet, row, "$")
            self.annual_rows[key] = row
            row += 1
        noi_row = self.annual_rows["noi"]

        for offset in range(hold + 1):
            col = first_col + offset
            first_period = 12 * offset + 1
            last_period = 12 * offset + 12
            for key in self.annual_rows:
                self._formula(
                    sheet, self.annual_rows[key], col,
                    f"=SUM({self._month_span(self.property_rows[key], first_period, last_period)})",
                    "link", NUM_CURRENCY, bold=key in bold_keys,
                )
            year = offset + 1
            if offset == hold:
                self.excel["exit_noi"] = _xref(sheet, noi_row, col)
                for key in self.annual_rows:
                    self.excel[f"annual:{key}:exit"] = _xref(sheet, self.annual_rows[key], col)
            else:
                self.excel[f"noi:{year}"] = _xref(sheet, noi_row, col)
                for key in self.annual_rows:
                    self.excel[f"annual:{key}:{year}"] = _xref(sheet, self.annual_rows[key], col)
        row += 1

        self._section(sheet, row, "Occupancy", last_col)
        row += 1
        occupancy_specs = (
            ("occupied_area_at_year_end", "Occupied area at year end", "SF", NUM_INTEGER, "occupied_area_sf", "end"),
            ("vacant_area_at_year_end", "Vacant area at year end", "SF", NUM_INTEGER, "vacant_area_sf", "end"),
            ("physical_occupancy_at_year_end", "Physical occupancy at year end", "%", NUM_PERCENT_FINE, "physical_occupancy", "end"),
            ("average_physical_occupancy_over_year", "Average physical occupancy", "%", NUM_PERCENT_FINE, "physical_occupancy", "average"),
        )
        for key, label, units, number_format, source, mode in occupancy_specs:
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, units)
            for offset in range(hold + 1):
                col = first_col + offset
                source_row = self.property_rows[source]
                if mode == "end":
                    # A state, snapshotted at the year's final month -- never
                    # summed and never averaged.
                    ref = _xref(MONTHLY_PROPERTY, source_row, self._month_col(12 * offset + 12))
                    formula = f"={ref}"
                else:
                    span = self._month_span(source_row, 12 * offset + 1, 12 * offset + 12)
                    formula = f"=AVERAGE({span})"
                self._formula(sheet, row, col, formula, "link", number_format)
                if offset < hold:
                    self.excel[f"annual:{key}:{offset + 1}"] = _xref(sheet, row, col)
            row += 1
        row += 1

        self._section(sheet, row, "Rent-roll leasing capital (below NOI)", last_col)
        row += 1
        self.capital_rows: dict[str, int] = {}
        for key, label in (
            ("tenant_improvements", "Tenant improvements"),
            ("leasing_commissions", "Leasing commissions"),
        ):
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, "$")
            self.capital_rows[key] = row
            for offset in range(hold + 1):
                col = first_col + offset
                span = self._month_span(self.property_rows[key], 12 * offset + 1, 12 * offset + 12)
                self._formula(sheet, row, col, f"=SUM({span})", "link", NUM_CURRENCY)
                if offset < hold:
                    self.excel[f"annual:{key}:{offset + 1}"] = _xref(sheet, row, col)
                else:
                    self.excel[f"annual:{key}:exit"] = _xref(sheet, row, col)
            row += 1
        self._label(sheet, row, "Total rent-roll TI and LC", bold=True)
        self._units(sheet, row, "$")
        total_capital_row = row
        for offset in range(hold + 1):
            col = first_col + offset
            self._formula(
                sheet, row, col,
                f"={_cell(self.capital_rows['tenant_improvements'], col)}+"
                f"{_cell(self.capital_rows['leasing_commissions'], col)}",
                "calc", NUM_CURRENCY, bold=True,
            )
        self.excel["exit_window_leasing_costs"] = _xref(sheet, row, forward_col)
        self.annual_capital_row = total_capital_row
        row += 1
        ws.write_string(
            row, 0,
            f"Year {hold + 1}'s tenant improvements and leasing commissions are disclosed above "
            "and are deliberately excluded from seller cash flow: they fall after the sale. They "
            "also never reduce exit NOI, because no leasing capital ever entered NOI.",
            self.fmt.note(),
        )
        row += 2

        self.noi_row = noi_row
        row = self._build_below_noi(sheet, row, first_col, last_col, noi_row, self.excel["input:annual_capex_reserve"])

        self._section(sheet, row, "Valuation metric", last_col)
        row += 1
        self._label(sheet, row, "Going-in cap rate  (Year 1 NOI / purchase price)", indent=1)
        self._units(sheet, row, "%")
        self.excel["going_in_cap_rate"] = self._formula(
            sheet, row, 2,
            f"={_cell(noi_row, first_col)}/{self.excel['input:purchase_price']}",
            "calc", NUM_PERCENT,
        )
        ws.freeze_panes(0, 2)

    def _operating_capital_line(self) -> tuple[str, dict[int, str]] | None:
        """The rent roll's TI and LC, hold years only.

        ``calculate_operating_capital_by_year`` adds the two arrays and
        subtracts the total once, beside CapEx, for years 1..H. The forward
        year is structurally excluded -- D4.4's reducer cannot reach a forward
        month -- so a post-sale leasing cheque can never become seller cash
        flow."""

        return (
            "Rent-roll TI and LC",
            {
                year: _xref(ANNUAL, self.annual_capital_row, 2 + year - 1)
                for year in self.years
            },
        )

    # ----------------------------------------------------------- Anchor Results

    def _anchor_operating_rows(self, row: int, c0: int) -> int:
        """Anchor's own Lease-Level schedules, frozen as constants.

        This export re-ran the authoritative analysis over the saved inputs;
        these are that result. They are written as numbers, never formulas, so
        no Excel cell can ever feed the side it is being compared against."""

        sheet = ANCHOR
        monthly = self.ll.monthly
        annual = self.ll.annual
        hold = self.hold

        # --- annual ------------------------------------------------------
        last_col = c0 + hold
        self._section(sheet, row, f"Annual operating projection (Years 1 to {hold}, then the exit window)", last_col)
        row += 1
        self._period_header(
            sheet, row, c0,
            [f"Year {year}" for year in self.years] + [f"Year {hold + 1}"],
        )
        row += 1
        for key, label, field in PROPERTY_LINES:
            if key in ("tenant_improvements", "leasing_commissions"):
                continue
            self._label(sheet, row, label, indent=1)
            self._units(sheet, row, "$")
            values = getattr(annual, f"{field}_by_year")
            for offset, value in enumerate(values):
                self.anchor[f"annual:{key}:{offset + 1}"] = self._frozen(
                    sheet, row, c0 + offset, value, NUM_CURRENCY
                )
            row += 1
        row += 1

        # The forward year's NOI is the one forward figure Anchor stores.
        self._label(sheet, row, "Exit NOI  (sum of the forward twelve months)", bold=True)
        self._units(sheet, row, "$")
        self.anchor["exit_noi"] = self._frozen(sheet, row, c0, annual.exit_noi, NUM_CURRENCY)
        row += 1
        self._label(sheet, row, "Exit-window TI and LC  (disclosed, never deducted)", indent=1)
        self._units(sheet, row, "$")
        self.anchor["exit_window_leasing_costs"] = self._frozen(
            sheet, row, c0, annual.exit_window_leasing_costs, NUM_CURRENCY
        )
        row += 1
        for key, label, number_format in (
            ("tenant_improvements", "Tenant improvements", NUM_CURRENCY),
            ("leasing_commissions", "Leasing commissions", NUM_CURRENCY),
            ("occupied_area_at_year_end", "Occupied area at year end", NUM_INTEGER),
            ("vacant_area_at_year_end", "Vacant area at year end", NUM_INTEGER),
            ("physical_occupancy_at_year_end", "Physical occupancy at year end", NUM_PERCENT_FINE),
            ("average_physical_occupancy_over_year", "Average physical occupancy", NUM_PERCENT_FINE),
        ):
            self._label(sheet, row, label, indent=1)
            field = f"{key}_by_year" if key in ("tenant_improvements", "leasing_commissions") else key
            values = getattr(annual, field)
            for offset, value in enumerate(values):
                self.anchor[f"annual:{key}:{offset + 1}"] = self._frozen(
                    sheet, row, c0 + offset, value, number_format
                )
            row += 1
        row += 1

        # --- monthly property --------------------------------------------
        month_last_col = c0 + self.months - 1
        self._section(sheet, row, "Monthly property statement", month_last_col)
        row += 1
        self._period_header(sheet, row, c0, [f"M{m}" for m in range(1, self.months + 1)])
        row += 1
        for key, label, field in PROPERTY_LINES:
            self._label(sheet, row, label, indent=1)
            for period, value in enumerate(getattr(monthly, field), start=1):
                self.anchor[f"month:{key}:{period}"] = self._frozen(
                    sheet, row, c0 + period - 1, value, NUM_CURRENCY
                )
            row += 1
        for key, number_format in (
            ("occupied_area_sf", NUM_INTEGER),
            ("vacant_area_sf", NUM_INTEGER),
            ("physical_occupancy", NUM_PERCENT_FINE),
        ):
            self._label(sheet, row, _humanised(key), indent=1)
            for period, value in enumerate(getattr(monthly, key), start=1):
                self.anchor[f"month:{key}:{period}"] = self._frozen(
                    sheet, row, c0 + period - 1, value, number_format
                )
            row += 1
        row += 1

        # --- per suite ----------------------------------------------------
        self._section(sheet, row, "Monthly leasing and recoveries by suite", month_last_col)
        row += 1
        operating = monthly.operating_schedule.suite_projections
        recovery = {p.suite_id: p for p in monthly.recovery_schedule.suite_projections}
        for projection in operating:
            suite_id = projection.suite_id
            for key, label in SUITE_LINES:
                self._label(sheet, row, f"{suite_id} -- {label}", indent=1)
                number_format = NUM_INTEGER if key == "occupied_area_sf" else NUM_CURRENCY
                for period, value in enumerate(getattr(projection, key), start=1):
                    self.anchor[f"suite:{suite_id}:{key}:{period}"] = self._frozen(
                        sheet, row, c0 + period - 1, value, number_format
                    )
                row += 1
            self._label(sheet, row, f"{suite_id} -- Expense recoveries", indent=1)
            for period, value in enumerate(recovery[suite_id].expense_recovery, start=1):
                self.anchor[f"suite:{suite_id}:expense_recovery:{period}"] = self._frozen(
                    sheet, row, c0 + period - 1, value, NUM_CURRENCY
                )
            row += 1
        return row + 1

    # ----------------------------------------------------------------- Checks

    def _operations_checks(self) -> list[_Check]:
        """Every line of the Lease-Level model, reconciled.

        The chain is only as trustworthy as its weakest visible link, so this
        does not stop at NOI: each suite's monthly leasing lines and recoveries
        are reconciled against Anchor's own per-suite schedules, then the
        monthly property statement, then the annual view, then the exit."""

        checks: list[_Check] = []
        x, a = self.excel, self.anchor

        def add(metric: str, key: str, excel_ref: str, kind: str, number_format: str) -> None:
            checks.append(
                _Check(
                    metric=metric, anchor=a[key], excel=excel_ref,
                    location=excel_ref.replace("$", ""), kind=kind,
                    number_format=number_format,
                )
            )

        # --- per suite, per month ----------------------------------------
        for plan in self.suite_plans:
            suite_id = plan.suite.suite_id
            for key, label in SUITE_LINES:
                number_format = NUM_INTEGER if key == "occupied_area_sf" else NUM_CURRENCY_CENTS
                total_row = self.suite_total_rows[(plan.index, key)]
                for period in range(1, self.months + 1):
                    add(
                        f"{plan.label} {label} M{period}",
                        f"suite:{suite_id}:{key}:{period}",
                        _xref(MONTHLY_LEASING, total_row, self._month_col(period)),
                        "currency", number_format,
                    )
            recovery_row = self.recovery_total_rows[plan.index]
            for period in range(1, self.months + 1):
                add(
                    f"{plan.label} Expense recoveries M{period}",
                    f"suite:{suite_id}:expense_recovery:{period}",
                    _xref(MONTHLY_RECOVERIES, recovery_row, self._month_col(period)),
                    "currency", NUM_CURRENCY_CENTS,
                )

        # --- monthly property --------------------------------------------
        for key, label, _field in PROPERTY_LINES:
            for period in range(1, self.months + 1):
                add(
                    f"{label} M{period}", f"month:{key}:{period}",
                    _xref(MONTHLY_PROPERTY, self.property_rows[key], self._month_col(period)),
                    "currency", NUM_CURRENCY_CENTS,
                )
        for key, label, kind, number_format in (
            ("occupied_area_sf", "Occupied area", "currency", NUM_INTEGER),
            ("vacant_area_sf", "Vacant area", "currency", NUM_INTEGER),
            ("physical_occupancy", "Physical occupancy", "ratio", NUM_PERCENT_FINE),
        ):
            for period in range(1, self.months + 1):
                add(
                    f"{label} M{period}", f"month:{key}:{period}",
                    _xref(MONTHLY_PROPERTY, self.property_rows[key], self._month_col(period)),
                    kind, number_format,
                )

        # --- monthly identities, both sides live ---------------------------
        for period in range(1, self.months + 1):
            col = self._month_col(period)
            rows = self.property_rows

            def ref(key: str) -> str:
                return _xref(MONTHLY_PROPERTY, rows[key], col)

            for metric, expression, excel_ref in (
                (
                    f"Identity: EGI M{period}",
                    f"{ref('cash_base_rent')}+{ref('expense_recovery')}+{ref('other_income')}-{ref('credit_loss')}",
                    ref("effective_gross_income"),
                ),
                (
                    f"Identity: management fee on EGI M{period}",
                    f"{ref('effective_gross_income')}*{self.excel['input:management_fee_pct']}",
                    ref("management_fee"),
                ),
                (
                    f"Identity: credit loss basis M{period}",
                    f"{self.excel['input:credit_loss_pct']}*({ref('cash_base_rent')}+{ref('expense_recovery')})",
                    ref("credit_loss"),
                ),
                (
                    f"Identity: total operating expenses M{period}",
                    f"{ref('fixed_operating_expenses')}+{ref('management_fee')}",
                    ref("total_operating_expenses"),
                ),
                (
                    f"Identity: NOI M{period}",
                    f"{ref('effective_gross_income')}-{ref('total_operating_expenses')}",
                    ref("noi"),
                ),
                (
                    f"Identity: occupied + vacant = rentable M{period}",
                    f"{ref('occupied_area_sf')}+{ref('vacant_area_sf')}",
                    self.excel["input:rentable_area_sf"],
                ),
            ):
                checks.append(
                    _Check(
                        metric=metric, anchor=expression, excel=excel_ref,
                        location=excel_ref.replace("$", ""), kind="currency",
                        number_format=NUM_CURRENCY_CENTS, guard_anchor=True,
                    )
                )

        # --- annual -------------------------------------------------------
        for key, label, _field in PROPERTY_LINES:
            if key in ("tenant_improvements", "leasing_commissions"):
                continue
            for year in self.years:
                add(
                    f"{label} Year {year}", f"annual:{key}:{year}",
                    x[f"annual:{key}:{year}"], "currency", NUM_CURRENCY_CENTS,
                )
        for key, label, kind, number_format in (
            ("tenant_improvements", "Tenant improvements", "currency", NUM_CURRENCY_CENTS),
            ("leasing_commissions", "Leasing commissions", "currency", NUM_CURRENCY_CENTS),
            ("occupied_area_at_year_end", "Occupied area at year end", "currency", NUM_INTEGER),
            ("vacant_area_at_year_end", "Vacant area at year end", "currency", NUM_INTEGER),
            ("physical_occupancy_at_year_end", "Physical occupancy at year end", "ratio", NUM_PERCENT_FINE),
            ("average_physical_occupancy_over_year", "Average physical occupancy", "ratio", NUM_PERCENT_FINE),
        ):
            for year in self.years:
                add(f"{label} Year {year}", f"annual:{key}:{year}", x[f"annual:{key}:{year}"], kind, number_format)

        add("Exit NOI", "exit_noi", x["exit_noi"], "currency", NUM_CURRENCY_CENTS)
        add(
            "Exit-window TI and LC", "exit_window_leasing_costs",
            x["exit_window_leasing_costs"], "currency", NUM_CURRENCY_CENTS,
        )
        checks.append(
            _Check(
                metric="Going-in cap rate", anchor=a["going_in_cap_rate"],
                excel=x["going_in_cap_rate"], location=x["going_in_cap_rate"].replace("$", ""),
                kind="ratio", number_format=NUM_PERCENT_FINE, key="going_in_cap_rate",
            )
        )
        return checks

    # ---------------------------------------------------------------- Summary

    def _summary_metrics(self) -> tuple[tuple[str, str, str, str | None, str], ...]:
        x, a = self.excel, self.anchor
        hold = self.hold
        return (
            ("Purchase price", x["input:purchase_price"], x["original:purchase_price"], None, NUM_CURRENCY),
            ("Rentable area", x["input:rentable_area_sf"], x["original:rentable_area_sf"], None, NUM_INTEGER),
            ("Year 1 cash base rent", x["annual:cash_base_rent:1"], a["annual:cash_base_rent:1"], "metric:Cash base rent Year 1", NUM_CURRENCY),
            ("Year 1 expense recoveries", x["annual:expense_recovery:1"], a["annual:expense_recovery:1"], "metric:Expense recoveries Year 1", NUM_CURRENCY),
            ("Year 1 effective gross income", x["annual:effective_gross_income:1"], a["annual:effective_gross_income:1"], "metric:Effective gross income Year 1", NUM_CURRENCY),
            ("Year 1 NOI", x["noi:1"], a["annual:noi:1"], "metric:Net operating income Year 1", NUM_CURRENCY),
            ("Year 1 physical occupancy (year end)", x["annual:physical_occupancy_at_year_end:1"], a["annual:physical_occupancy_at_year_end:1"], "metric:Physical occupancy at year end Year 1", NUM_PERCENT),
            (f"Year {hold + 1} NOI (exit NOI)", x["exit_noi"], a["exit_noi"], "metric:Exit NOI", NUM_CURRENCY),
            ("Going-in cap rate", x["going_in_cap_rate"], a["going_in_cap_rate"], "going_in_cap_rate", NUM_PERCENT),
            ("Loan amount", x["loan_amount"], a["loan_amount"], "loan_amount", NUM_CURRENCY),
            ("Required equity (initial equity)", x["check_excel:initial_equity"], a["initial_equity"], "initial_equity", NUM_CURRENCY),
            ("Headline DSCR (Year 1)", x["headline_dscr"], a["headline_dscr"], "headline_dscr", NUM_MULTIPLE),
            ("Gross sale price", x["exit_value"], a["exit_value"], "exit_value", NUM_CURRENCY),
            ("Net sale proceeds", x["net_sale_proceeds"], a["net_sale_proceeds"], "net_sale_proceeds", NUM_CURRENCY),
            ("Total equity invested", x["total_equity_invested"], a["total_equity_invested"], "total_equity_invested", NUM_CURRENCY),
            ("Total cash returned", x["total_cash_returned"], a["total_cash_returned"], "total_cash_returned", NUM_CURRENCY),
            ("Total profit", x["total_profit"], a["total_profit"], "total_profit", NUM_CURRENCY),
            ("Equity multiple", x["equity_multiple"], a["equity_multiple"], "equity_multiple", NUM_MULTIPLE),
            ("Levered IRR", x["levered_irr"], a["levered_irr"], "levered_irr", NUM_PERCENT),
            ("Unlevered IRR", x["unlevered_irr"], a["unlevered_irr"], "unlevered_irr", NUM_PERCENT),
        )

    def _extra_conventions(self) -> tuple[tuple[str, str], ...]:
        return (
            (
                "Rollover",
                "Each rollover-event state splits its probability mass across a renewal and a "
                "new-tenant branch; each branch's successor is priced at market on its own "
                "commencement month, and its expiry seeds the next state. Merging combines "
                "probability mass and nothing else: no rent, term, date or rate is averaged.",
            ),
            (
                "Free rent",
                "Consumed sequentially against occupancy, so a whole free month is never spent "
                "abating a fractional month's rent. An abated month is fully occupied and its "
                "tenant still reimburses operating expenses.",
            ),
            (
                "Leasing commissions",
                "A percentage of the successor's contractual face rent over its entire term -- "
                "including escalations, gross of free rent, untruncated by the hold horizon and "
                "unreduced by a fractional first month.",
            ),
            (
                "Exit NOI",
                f"The sum of monthly NOI over months {12 * self.hold + 1} to "
                f"{12 * self.hold + 12}, from the same canonical series every hold year is "
                "summed from.",
            ),
        )


def _humanised(token: str) -> str:
    return token.replace("_sf", " (SF)").replace("_", " ").capitalize()


def build_lease_level_audit_workbook(source: LeaseLevelAuditSource) -> bytes:
    """Build one Lease-Level Underwrite formula-audit workbook."""

    return _LeaseLevelAuditWorkbook(source).build()
