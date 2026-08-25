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
