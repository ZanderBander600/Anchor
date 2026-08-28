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


@dataclass(frozen=True, slots=True, kw_only=True)
class CapitalStack:
    loan_amount: float
    initial_equity: float


@dataclass(frozen=True, slots=True, kw_only=True)
class DebtSchedule:
    monthly_debt_service: float
    annual_debt_service: tuple[float, ...]
    remaining_loan_balance: float


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionCashFlows:
    exit_value: float
    net_sale_proceeds: float
    unlevered_cash_flows: tuple[float, ...]
    levered_cash_flows: tuple[float, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ReturnMetrics:
    dscr_by_year: tuple[float | None, ...]
    headline_dscr: float | None
    equity_multiple: float | None
    unlevered_irr: float | None
    levered_irr: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionResults:
    """The Phase 2 public output contract.

    Exact field set and order frozen by the "Phase 2 Output Contract" and
    "Frozen Phase 2 Decisions" sections of
    ``docs/phase_2_deterministic_engine.md``. Produced only by
    ``analyze_acquisition`` in ``acquisition.py``, which assembles it from
    the already-computed Phase 2A/2B/2C/2D results below -- this dataclass
    itself performs no calculation.
    """

    going_in_cap_rate: float
    loan_amount: float
    initial_equity: float
    monthly_debt_service: float
    annual_debt_service: tuple[float, ...]
    remaining_loan_balance: float
    noi_by_year: tuple[float, ...]
    exit_noi: float
    exit_value: float
    net_sale_proceeds: float
    unlevered_cash_flows: tuple[float, ...]
    levered_cash_flows: tuple[float, ...]
    unlevered_irr: float | None
    levered_irr: float | None
    equity_multiple: float | None
    dscr_by_year: tuple[float | None, ...]
    headline_dscr: float | None
