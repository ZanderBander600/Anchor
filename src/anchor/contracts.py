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


@dataclass(frozen=True, slots=True, kw_only=True)
class AcquisitionTerms:
    """Detailed Operating Model V2.1 Gate 1
    (``docs/detailed_operating_model_v2_1_architecture.md`` Section 2.2) --
    the acquisition/debt/exit assumptions shared, unmodified, by both Quick
    and Detailed Underwrite: every ``AcquisitionInputs`` field except
    ``current_noi``, ``occupancy``, and ``noi_growth`` (how NOI is produced,
    which is exactly what differs between the two modes).

    Deliberately excludes ``occupancy``: it is read by no downstream
    acquisition/debt/returns calculation today (confirmed by inspection --
    see the architecture document's "Where ``occupancy`` belongs" finding),
    and putting it on a contract both modes share would risk exactly the
    second, competing vacancy mechanism the V2.1 conventions document rules
    out. ``occupancy`` remains solely a Quick-mode, informational
    ``AcquisitionInputs`` field, unchanged.

    Constructed for Quick Underwrite via ``acquisition_terms_from_inputs``
    below; constructed directly for Detailed Underwrite from its own
    already-validated fields. Neither path ever needs an
    ``AcquisitionInputs`` instance to reach this contract.
    """

    purchase_price: float
    hold_period: int
    exit_cap_rate: float
    ltv: float
    interest_rate: float
    amortization: int
    acquisition_cost_pct: float
    financing_fee_pct: float
    disposition_cost_pct: float
    annual_capex_reserve: float
    io_period: int


def acquisition_terms_from_inputs(inputs: AcquisitionInputs) -> AcquisitionTerms:
    """Deterministic field projection from an already-validated
    ``AcquisitionInputs`` -- performs no validation of its own (``inputs``
    is validated by construction) and no calculation: every
    ``AcquisitionTerms`` field is copied verbatim from the identically-named
    ``AcquisitionInputs`` field. The sole adapter from Quick's public
    contract into the mode-agnostic downstream shape; the Detailed path
    never calls this, since it has no ``AcquisitionInputs`` to adapt from.
    """

    return AcquisitionTerms(
        purchase_price=inputs.purchase_price,
        hold_period=inputs.hold_period,
        exit_cap_rate=inputs.exit_cap_rate,
        ltv=inputs.ltv,
        interest_rate=inputs.interest_rate,
        amortization=inputs.amortization,
        acquisition_cost_pct=inputs.acquisition_cost_pct,
        financing_fee_pct=inputs.financing_fee_pct,
        disposition_cost_pct=inputs.disposition_cost_pct,
        annual_capex_reserve=inputs.annual_capex_reserve,
        io_period=inputs.io_period,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DetailedOperatingInputs:
    """Detailed Operating Model V2.1 Gate 1
    (``docs/detailed_operating_model_v2_1_financial_conventions.md``) --
    the eleven Year-1 revenue/expense/growth assumptions that produce a
    Detailed deal's ``OperatingProjection`` (``anchor.engine.contracts``).

    Every field is required -- unlike ``AcquisitionInputs``' five
    Underwriting V2 fields, none of these has an economically meaningful
    neutral default (there is no such thing as a neutral
    ``gross_potential_rent``): a Detailed deal supplies all eleven, or it
    isn't a Detailed deal. Validated by
    ``anchor.validation.validate_detailed_operating_inputs``, never by
    ``validate_acquisition_inputs``.
    """

    gross_potential_rent: float
    other_income: float
    vacancy_credit_loss_pct: float
    property_taxes: float
    insurance: float
    utilities: float
    repairs_maintenance: float
    other_operating_expenses: float
    management_fee_pct: float
    revenue_growth: float
    expense_growth: float
