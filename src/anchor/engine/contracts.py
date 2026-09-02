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
class AcquisitionResults:
    """The Phase 2 public output contract, plus the three Underwriting V2
    Gate 2 transaction-cost fields (``acquisition_costs``,
    ``financing_fee``, ``disposition_costs``), the Gate 3 ``capex_by_year``
    series, and the Gate 4 ``min_dscr``
    (``docs/underwriting_v2_financial_conventions.md``).

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
