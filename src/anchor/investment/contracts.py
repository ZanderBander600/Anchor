"""Phase 7 Gate P7.6 -- the Investment-level input contracts.

Restates ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections
6, 8.2, 9.1 (CON-1), 10 (BP-7, BP-8) and 11 (PP-1 to PP-4, TC-1 to TC-5), and
the Section 21 record (Q3, Q6, Q7, Q8, Q9); that document governs on any
discrepancy. Like ``anchor.business_plan.contracts``, this module performs no
calculation and no I/O: it only describes the shape of what an analyst states
about a visible Investment beyond its Units.

**The Unit is the existing Deal (Q2, Option A).** Nothing here restates a
Unit's economics. A Unit's allocated purchase price *is* its Deal's
``purchase_price`` (PP-1), its hold is its Deal's ``hold_period``, and its Business
Plan is its Deal's plan. A membership only records what the Investment adds
about the Unit: presentation, and economic timing.

**Unit timing (the P7.6 Section 21.3 decision).** ``acquisition_month`` and
``disposition_month`` are model months relative to the Investment's closing
(D6 Section 4). CON-1 is validation, not structure: P7.6 accepts only
``acquisition_month = 0`` and ``disposition_month = None``, where ``None`` means
the Unit stays through the common Investment horizon and exits through its own
Deal's hold and exit mechanics. The hold is deliberately *not* copied here as a
disposition month: that would duplicate the Deal's hold assumption, and a
DISPOSITION Strategy would then conflict with stale membership data. A later
gate can accept a later acquisition or an explicit disposition without changing
this contract.

**Reporting-only metadata.** ``UnitKind``, a membership's ``label`` and
``ordinal``, and a transaction cost's ``description`` and ``category`` never
reach a calculation, a fingerprint or an economic order. Nothing may branch on
them financially.

**Transaction costs are Closing Uses (BP-8, TC-1, TC-2).** They are not Project
Capital, Owner Expenses, unit acquisition costs, financing fees or any operating
line. In P7.6 they are equity-funded at closing, their one subtraction site is
consolidation, and they never reach a Unit's loan, price, costs, NOI, exit value
or debt service. Loan origination, refinancing and position fees are not
transaction costs: they belong to a capital position (TC-4, P7.7+).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

#: CON-1 in P7.6: every Unit closes at the Investment's closing (model month 0).
SUPPORTED_ACQUISITION_MONTH = 0

#: TC timing in P7.6: every transaction cost is a closing use (model month 0).
SUPPORTED_TRANSACTION_COST_MONTH = 0

#: PP-2 (Q6): the largest difference, in dollars, between the canonical sum of
#: the Units' allocated purchase prices and the transaction price. A decimal
#: string, because the comparison is made on the wire dollar values exactly
#: (``anchor.investment.validation``).
ALLOCATION_TOLERANCE = "0.01"


class UnitKind(StrEnum):
    """What a Unit is to its Investment (Section 8.2, 8.3).

    **Reporting metadata only.** A portfolio asset is ``PROPERTY``, a separately
    valued mixed-use component is ``COMPONENT``, and ``PHASE`` names a future
    development phase -- which does not make Phase 8 development legal. The
    financial semantics of every kind are identical: no calculation branches on
    it."""

    PROPERTY = "property"
    COMPONENT = "component"
    PHASE = "phase"


class TransactionCostCategory(StrEnum):
    """What an Investment transaction cost is for (Section 11.2, Q8).

    **Reporting metadata only.** No category changes a calculation. Financing
    fees are deliberately not members: they belong to a capital position."""

    ACQUISITION_FEE = "acquisition_fee"
    DUE_DILIGENCE = "due_diligence"
    LEGAL = "legal"
    PORTFOLIO_TRANSACTION_COST = "portfolio_transaction_cost"
    OTHER = "other"


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentTransactionCost:
    """One Investment-level closing cost (Section 11.2).

    - ``cost_id``: stable, opaque and nonblank, in its own namespace. It orders
      records canonically and never carries financial meaning.
    - ``description``: required analyst text. Reporting only.
    - ``category``: reporting only.
    - ``amount``: nominal dollars, finite and ``>= 0``.
    - ``model_month``: an integer ``>= 0`` (D6 Section 4). P7.6 accepts only
      ``0``, closing; the field keeps later timing possible.

    Shape only: ``anchor.investment.validation`` holds the rules, following the
    repository's contract/validator split."""

    cost_id: str
    description: str
    category: TransactionCostCategory
    amount: float
    model_month: int


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentUnitMembership:
    """What a visible Investment records about one of its Units.

    - ``unit_id``: the existing Deal's id.
    - ``ordinal``: presentation order only. It never orders a sum.
    - ``label``: an optional analyst display label, or ``None``.
    - ``unit_kind``: reporting only.
    - ``acquisition_month``: the Unit's acquisition, as a model month relative
      to the Investment's closing. P7.6 accepts only ``0``.
    - ``disposition_month``: an explicit earlier or later Unit disposition, as
      a model month, or ``None``. P7.6 accepts only ``None``: the Unit exits
      through its own Deal's hold at the common horizon.

    Shape only: ``anchor.investment.validation`` holds the rules."""

    unit_id: str
    ordinal: int
    label: str | None
    unit_kind: UnitKind
    acquisition_month: int
    disposition_month: int | None


# =============================================================================
# Deterministic issues -- the invalid-Investment contract
# =============================================================================


class InvestmentIssueCode(StrEnum):
    """Stable, machine-readable reasons an Investment's own inputs, or one of
    its variants, are invalid.

    ``INVALID_BUSINESS_PLAN`` wraps the D6 validator's finding on the
    Investment-level plan; its ``source_code`` is the D6 code and its message
    the D6 wording, so the plan rules keep one authority.

    ``ALLOCATION_MISMATCH``, ``HOLD_PERIOD_MISMATCH`` and
    ``ANALYSIS_START_DATE_MISMATCH`` concern the Units' *resolved* inputs: the
    Base inputs, or the inputs a Strategy and Scenario resolved to."""

    INVALID_NAME = "invalid_name"
    INVALID_TRANSACTION_PRICE = "invalid_transaction_price"
    INVALID_UNITS = "invalid_units"
    NO_UNITS = "no_units"
    INVALID_UNIT_ID = "invalid_unit_id"
    DUPLICATE_UNIT = "duplicate_unit"
    UNIT_NOT_RETAINED = "unit_not_retained"
    INVALID_ORDINAL = "invalid_ordinal"
    INVALID_LABEL = "invalid_label"
    UNKNOWN_UNIT_KIND = "unknown_unit_kind"
    INVALID_ACQUISITION_MONTH = "invalid_acquisition_month"
    UNSUPPORTED_ACQUISITION_MONTH = "unsupported_acquisition_month"
    INVALID_DISPOSITION_MONTH = "invalid_disposition_month"
    UNSUPPORTED_DISPOSITION_MONTH = "unsupported_disposition_month"
    INVALID_TRANSACTION_COSTS = "invalid_transaction_costs"
    INVALID_COST_ID = "invalid_cost_id"
    DUPLICATE_COST_ID = "duplicate_cost_id"
    INVALID_COST_DESCRIPTION = "invalid_cost_description"
    UNKNOWN_COST_CATEGORY = "unknown_cost_category"
    INVALID_COST_AMOUNT = "invalid_cost_amount"
    INVALID_COST_MONTH = "invalid_cost_month"
    UNSUPPORTED_COST_MONTH = "unsupported_cost_month"
    INVALID_BUSINESS_PLAN = "invalid_business_plan"
    ALLOCATION_MISMATCH = "allocation_mismatch"
    HOLD_PERIOD_MISMATCH = "hold_period_mismatch"
    ANALYSIS_START_DATE_MISMATCH = "analysis_start_date_mismatch"


@dataclass(frozen=True, slots=True, kw_only=True)
class InvestmentIssue:
    """One deterministic reason an Investment, or a variant of it, cannot be
    analysed. ``unit_id`` names the Unit concerned where one is; ``field``
    locates the finding in the request; ``source_code`` is an existing
    validator's own code."""

    code: InvestmentIssueCode
    message: str
    unit_id: str | None = None
    field: str | None = None
    source_code: str | None = None

    def __str__(self) -> str:
        return self.message


class InvestmentValidationError(ValueError):
    """An invalid Investment input or variant: one ordered collection of
    ``InvestmentIssue``, following the repository's validation-error precedent:
    no result is ever returned for an invalid Investment, and nothing is
    repaired."""

    def __init__(self, issues: Iterable[InvestmentIssue]) -> None:
        ordered_issues = tuple(issues)
        if not ordered_issues:
            raise ValueError("InvestmentValidationError requires at least one issue.")
        if not all(isinstance(issue, InvestmentIssue) for issue in ordered_issues):
            raise TypeError("issues must contain only InvestmentIssue instances.")

        self.issues = ordered_issues
        super().__init__("\n".join(issue.message for issue in ordered_issues))
