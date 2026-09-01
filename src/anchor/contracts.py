"""``AcquisitionInputs`` -- the nine POC V1 fields, frozen by
``docs/financial_conventions.md``, plus the five Underwriting V2 fields
added at Gate 1 of ``docs/underwriting_v2_financial_conventions.md``. Every
V2 field defaults to its economically neutral value so that existing
construction using only the original nine keyword arguments continues to
compile and run unmodified, and so an ``AcquisitionInputs`` built this way
is bit-for-bit interchangeable with a V1-era instance wherever the
(unmodified, V1-only) engine reads it.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionInputs:
    purchase_price: float
    current_noi: float
    occupancy: float
    noi_growth: float
    hold_period: int
    exit_cap_rate: float
    ltv: float
    interest_rate: float
    amortization: int
    acquisition_cost_pct: float = 0.0
    financing_fee_pct: float = 0.0
    disposition_cost_pct: float = 0.0
    annual_capex_reserve: float = 0.0
    io_period: int = 0
