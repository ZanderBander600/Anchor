"""Phase 2A/2B engine contracts and numerical-failure signaling.

These contracts are narrow intermediate results, not the final
``AcquisitionResults`` contract described in
``docs/phase_2_deterministic_engine.md``. ``AcquisitionResults`` cannot be
legitimately constructed until later Phase 2 parts (exit value, cash flows,
returns) exist, so this module defines only the results Phase 2A and 2B
actually produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol


class NonFiniteResultError(ValueError):
    """Raised when a required Phase 2 deterministic calculation is non-finite.

    Per the Phase 2A non-finite safety rule, the engine must fail explicitly
    rather than silently clamp, round, replace, or propagate a NaN/infinite
    value into a result contract.
    """

    def __init__(self, field_name: str, value: float) -> None:
        self.field_name = field_name
        self.value = value
        super().__init__(
            f"{field_name} produced a non-finite result: {value!r}."
        )


def ensure_finite(field_name: str, value: float) -> float:
    """Return ``value`` unchanged, or raise ``NonFiniteResultError``."""

    if not isfinite(value):
        raise NonFiniteResultError(field_name, value)
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class NoiForecast:
    noi_by_year: tuple[float, ...]
    exit_noi: float
    going_in_cap_rate: float


class OperatingProjectionLike(Protocol):
    """Detailed Operating Model V2.1 Gate 1
    (``docs/detailed_operating_model_v2_1_architecture.md`` Section 2.2.1)
    -- the narrow, structural shape the downstream acquisition/debt/returns
    engine actually reads off an operating projection, regardless of which
    mode produced it. Both ``NoiForecast`` (Quick) and ``OperatingProjection``
    (Detailed, below) satisfy this without modification.

    Deliberately just these three fields: every calculation downstream of
    ``analyze_acquisition_from_operating_projection`` (capital stack, debt
    schedule, exit value, cash flows, returns) reads only ``noi_by_year``,
    ``exit_noi``, and ``going_in_cap_rate`` off its operating projection --
    never any of ``OperatingProjection``'s eleven Detailed-only line-item
    schedules. Kept as a field here (rather than re-derived downstream from
    ``noi_by_year[0] / purchase_price``, which is mathematically equivalent)
    because both producing contracts already compute it once and
    ``AcquisitionResults.going_in_cap_rate`` already reads it directly --
    re-deriving it downstream would be a second, redundant computation of
    the same value.
    """

    noi_by_year: tuple[float, ...]
    exit_noi: float
    going_in_cap_rate: float


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatingProjection:
    """Detailed Operating Model V2.1 Gate 1
    (``docs/detailed_operating_model_v2_1_financial_conventions.md``,
    ``docs/detailed_operating_model_v2_1_architecture.md`` Section 2.1) --
    the canonical, deterministic Detailed operating schedule: every
    ``_by_year`` field has length ``hold_period`` (Years 1..H); ``exit_noi``
    is the single scalar Year ``H+1`` value used only for exit valuation,
    never a member of ``noi_by_year``.

    Produced solely by
    ``anchor.engine.operating.build_detailed_operating_projection`` (Gate 2)
    -- like every other contract in this module, this dataclass performs no
    calculation of its own. Satisfies ``OperatingProjectionLike`` without
    needing to declare it explicitly (structural typing) -- the downstream
    engine (``analyze_acquisition_from_operating_projection``) reads only
    the three ``OperatingProjectionLike`` fields off an instance of this
    contract, never any of the eleven line-item schedules below, which
    exist for display (the institutional operating-statement UI) and for
    this contract's own golden-case test, not for the acquisition engine.
    """

    gross_potential_rent_by_year: tuple[float, ...]
    other_income_by_year: tuple[float, ...]
    vacancy_credit_loss_by_year: tuple[float, ...]
    effective_gross_income_by_year: tuple[float, ...]

    property_taxes_by_year: tuple[float, ...]
    insurance_by_year: tuple[float, ...]
    utilities_by_year: tuple[float, ...]
    repairs_maintenance_by_year: tuple[float, ...]
    other_operating_expenses_by_year: tuple[float, ...]
    management_fee_by_year: tuple[float, ...]

    total_operating_expenses_by_year: tuple[float, ...]
    noi_by_year: tuple[float, ...]

    exit_noi: float
    going_in_cap_rate: float


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalStack:
    """Underwriting V2 Gate 2 adds ``acquisition_costs`` and
    ``financing_fee`` -- both equity-funded, both folded into
    ``initial_equity``, neither affecting ``loan_amount``. At Gate 2 neutral
    defaults (``acquisition_cost_pct = financing_fee_pct = 0``), both are
    ``0.0`` and ``initial_equity`` reduces to exactly the V1 formula."""

    loan_amount: float
    acquisition_costs: float
    financing_fee: float
    initial_equity: float


@dataclass(frozen=True, slots=True, kw_only=True)
class DebtSchedule:
    monthly_debt_service: float
    annual_debt_service: tuple[float, ...]
    remaining_loan_balance: float


@dataclass(frozen=True, slots=True, kw_only=True)
class OperatingCapitalSchedule:
    """Below-NOI, year-varying property capital outflows, Years 1..H
    (``docs/plans/2026-09-05-anchor-lease-level-underwriting-d4-integration-architecture.md``
    Section 17.2, resolving D0's HD-1).

    **Deliberately not named for leasing.** A future Development Engine needs
    the same channel for construction and lease-up capital, and the shared
    acquisition engine must not become lease-aware. The *components* are named
    for their real cause, because an analyst auditing a cash flow must be able
    to see which dollars were tenant improvements and which were leasing
    commissions -- a single opaque number would destroy that split.

    **This is a generic engine contract.** Nothing here knows what a Suite, a
    Lease, a rollover or a recovery is; it carries completed annual dollars and
    says nothing about where they came from. Producing them is the caller's
    job.

    ``tenant_improvements_by_year`` and ``leasing_commissions_by_year`` each
    hold exactly ``hold_period`` values, Years 1..H in chronological order.
    **There is no Year H+1 entry**: a forward-window capital event occurs after
    the modelled sale, is not a seller cash flow, and is excluded before this
    boundary is reached (D4 Section 21.3). The engine has no concept of a
    forward window at all.

    Every figure is finite and ``>= 0``. A negative "outflow" would be capital
    *income*, for which the accepted model has no convention, so it is refused
    rather than given an invented meaning -- the same reasoning that refuses a
    negative recoverable-expense pool.

    **Absent means absent.** Where no schedule is supplied the engine behaves
    exactly as it did before this channel existed; see
    ``anchor.engine.acquisition.calculate_operating_capital_by_year``.

    Where this reaches, and where it deliberately does not
    (D4 Sections 17.4 and 22):

    - **Reduces** unlevered and levered cash flows, both recurring owner-return
      series, and through them IRR, equity multiple, cash-on-cash, cash yield
      and cumulative distributions.
    - **Never touches** ``noi_by_year``, ``exit_noi``, ``exit_value``,
      ``disposition_costs``, the debt schedule, ``dscr_by_year``,
      ``headline_dscr``, ``min_dscr`` or ``year_1_debt_yield``. Lender metrics
      are NOI-based by convention and stay that way.
    - Is **separate from** ``capex_by_year``, which continues to report the
      constant ``AcquisitionTerms.annual_capex_reserve`` alone. The two are
      additive, never merged.

    This dataclass performs no calculation of its own.
    """

    tenant_improvements_by_year: tuple[float, ...]
    leasing_commissions_by_year: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.tenant_improvements_by_year) != len(
            self.leasing_commissions_by_year
        ):
            raise ValueError(
                "OperatingCapitalSchedule requires one tenant-improvement and "
                "one leasing-commission figure per hold year; got "
                f"{len(self.tenant_improvements_by_year)} and "
                f"{len(self.leasing_commissions_by_year)}."
            )
        for name, series in (
            ("tenant_improvements_by_year", self.tenant_improvements_by_year),
            ("leasing_commissions_by_year", self.leasing_commissions_by_year),
        ):
            for year, amount in enumerate(series):
                if not isfinite(amount):
                    raise NonFiniteResultError(f"{name}[{year}]", amount)
                if amount < 0.0:
                    raise ValueError(
                        f"{name}[{year}] is {amount!r}; an operating-capital "
                        "outflow is finite and greater than or equal to 0. A "
                        "negative outflow would be capital income, for which "
                        "there is no convention."
                    )


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionCashFlows:
    """Underwriting V2 Gate 2 adds ``disposition_costs``. ``exit_value``
    remains the gross, unmodified market-value estimate; disposition costs
    are deducted only when deriving ``net_sale_proceeds`` and the terminal
    cash-flow entries, never folded back into ``exit_value`` itself.

    Underwriting V2 Gate 3 adds ``capex_by_year`` -- the deterministic,
    below-NOI annual CapEx-reserve series consumed by both cash-flow
    tuples below. It is computed once and reused, never recomputed
    per series."""

    exit_value: float
    disposition_costs: float
    net_sale_proceeds: float
    capex_by_year: tuple[float, ...]
    unlevered_cash_flows: tuple[float, ...]
    levered_cash_flows: tuple[float, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ReturnMetrics:
    """Underwriting V2 Gate 4 adds ``min_dscr`` -- the minimum of the
    non-``None`` entries in ``dscr_by_year``, or ``None`` if every entry is
    ``None``. It supplements ``headline_dscr`` (``DSCR_1``); it does not
    replace it."""

    dscr_by_year: tuple[float | None, ...]
    headline_dscr: float | None
    min_dscr: float | None
    equity_multiple: float | None
    unlevered_irr: float | None
    levered_irr: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerReturnMetrics:
    """Owner Return Metrics V3 Gate A2
    (``docs/owner_return_metrics_v3_financial_conventions.md``) -- annual
    Levered Cash-on-Cash Return, annual Unlevered Cash Yield, the
    Cumulative Operating Distributions dollar schedule, and Year 1 Debt
    Yield. Every series here is derived from recurring (operating-only)
    cash flow -- sale proceeds, refinance proceeds, and other terminal
    liquidation proceeds are excluded from every entry, including the
    final hold year.

    A narrow intermediate result, mirroring ``ReturnMetrics`` above: not
    itself part of ``AcquisitionResults`` (its four fields are flattened
    directly onto ``AcquisitionResults``, matching how ``ReturnMetrics``'s
    fields are flattened there rather than nested), used only to keep
    ``calculate_owner_return_metrics`` (``returns.py``) a single
    well-typed return value.
    """

    levered_cash_on_cash_by_year: tuple[float | None, ...]
    unlevered_cash_yield_by_year: tuple[float | None, ...]
    cumulative_operating_distributions_by_year: tuple[float, ...]
    year_1_debt_yield: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionResults:
    """The Phase 2 public output contract, plus the three Underwriting V2
    Gate 2 transaction-cost fields (``acquisition_costs``,
    ``financing_fee``, ``disposition_costs``), the Gate 3 ``capex_by_year``
    series, the Gate 4 ``min_dscr``
    (``docs/underwriting_v2_financial_conventions.md``), and the Owner
    Return Metrics V3 Gate A2 fields
    (``docs/owner_return_metrics_v3_financial_conventions.md``):
    ``levered_cash_on_cash_by_year``, ``unlevered_cash_yield_by_year``,
    ``cumulative_operating_distributions_by_year``, and
    ``year_1_debt_yield``. Identical for Quick and Detailed -- computed
    once in ``analyze_acquisition_from_operating_projection`` from fields
    already on this same result, never a second mode-specific
    calculation.

    Exact V1 field set and order frozen by the "Phase 2 Output Contract"
    and "Frozen Phase 2 Decisions" sections of
    ``docs/phase_2_deterministic_engine.md``. Produced only by
    ``analyze_acquisition`` in ``acquisition.py``, which assembles it from
    the already-computed Phase 2A/2B/2C/2D (and now Gate 2/3) results below
    -- this dataclass itself performs no calculation. The meaning of every
    pre-existing field is unchanged; ``exit_value`` in particular remains
    the gross market-value estimate, never reduced by ``disposition_costs``,
    and ``noi_by_year`` is never reduced by ``capex_by_year`` -- CapEx is
    modeled strictly below NOI, in the cash-flow series only.
    """

    going_in_cap_rate: float
    loan_amount: float
    acquisition_costs: float
    financing_fee: float
    initial_equity: float
    monthly_debt_service: float
    annual_debt_service: tuple[float, ...]
    remaining_loan_balance: float
    noi_by_year: tuple[float, ...]
    capex_by_year: tuple[float, ...]
    tenant_improvements_by_year: tuple[float, ...]
    leasing_commissions_by_year: tuple[float, ...]
    exit_noi: float
    exit_value: float
    disposition_costs: float
    net_sale_proceeds: float
    unlevered_cash_flows: tuple[float, ...]
    levered_cash_flows: tuple[float, ...]
    unlevered_irr: float | None
    levered_irr: float | None
    equity_multiple: float | None
    dscr_by_year: tuple[float | None, ...]
    headline_dscr: float | None
    min_dscr: float | None
    levered_cash_on_cash_by_year: tuple[float | None, ...]
    unlevered_cash_yield_by_year: tuple[float | None, ...]
    cumulative_operating_distributions_by_year: tuple[float, ...]
    year_1_debt_yield: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DetailedAcquisitionResults:
    """Detailed Operating Model V2.1 Gate 4 -- the Detailed result envelope.

    Exposes the deterministic ``OperatingProjection`` (the full Detailed
    revenue/vacancy/EGI/expense-line/NOI schedule) to downstream consumers
    (API, frontend) *alongside* the unchanged, authoritative
    ``AcquisitionResults`` -- a higher-level envelope rather than
    contaminating ``AcquisitionResults`` itself with Detailed-only line
    items, per the architecture document's contract-separation principle
    (Section 2.1.1). Quick Underwrite has no equivalent envelope: it
    returns a bare ``AcquisitionResults``, unchanged.

    Produced only by
    ``anchor.engine.acquisition.analyze_detailed_acquisition_with_projection``,
    which computes ``operating_projection`` exactly once and reuses it for
    both fields below -- this dataclass performs no calculation of its own.
    """

    operating_projection: OperatingProjection
    results: AcquisitionResults
