"""Phase 2A acquisition capital-stack basics: loan amount and initial equity.

Restates ``docs/financial_conventions.md`` "Loan and debt service" (capital-
stack portion) exactly; that document governs on any discrepancy. Debt
service, amortization, and loan-balance machinery are out of scope for
Phase 2A and belong to Phase 2B.
"""

from __future__ import annotations

from ..contracts import AcquisitionInputs
from .contracts import CapitalStack, ensure_finite


def calculate_loan_amount(*, purchase_price: float, ltv: float) -> float:
    loan_amount = purchase_price * ltv
    return ensure_finite("loan_amount", loan_amount)


def calculate_initial_equity(*, purchase_price: float, loan_amount: float) -> float:
    initial_equity = purchase_price - loan_amount
    return ensure_finite("initial_equity", initial_equity)


def calculate_capital_stack(inputs: AcquisitionInputs) -> CapitalStack:
    """Compute the Phase 2A capital-stack basics for one ``AcquisitionInputs``."""

    loan_amount = calculate_loan_amount(
        purchase_price=inputs.purchase_price, ltv=inputs.ltv
    )
    initial_equity = calculate_initial_equity(
        purchase_price=inputs.purchase_price, loan_amount=loan_amount
    )
    return CapitalStack(loan_amount=loan_amount, initial_equity=initial_equity)
