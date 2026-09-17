"""Phase 7 Gate P7.9 -- the Common Equity seam.

Restates ``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Sections 2 and 3
(ratified); that document governs on any discrepancy.

This is the package's only reader of Capital Structure *results*. The
Partnership allocates ``StructuredCapitalResult.common_equity.cash_flows`` --
for either analysis root, with or without authored positions -- and never a
project ``levered_cash_flows`` directly, which would bypass the structured
positions and the unresolved-funding rule.

``StructuredCapitalResult`` is read whole, rather than only its
``common_equity``, because the unresolved Funding Requirement ids an
unavailable Partnership reports live on the result's
``funding_requirements``; ``CommonEquityReturns`` carries the reason and
message but not the ids.
"""

from __future__ import annotations

from ..capital_structure.contracts import CapitalStructureStatus, FundingRequirementStatus
from ..capital_structure.execution_contracts import StructuredCapitalResult
from .contracts import (
    CashFlowCadence,
    CommonEquityCashFlowInput,
    CommonEquityUnavailable,
    Partnership,
    PartnershipExecutionError,
    PartnershipExecutionIssue,
    PartnershipExecutionIssueCode,
    PartnershipResult,
)
from .waterfall import allocate_partnership, unavailable_partnership_result


def common_equity_input(structured: StructuredCapitalResult) -> CommonEquityCashFlowInput | CommonEquityUnavailable:
    """The annual Common Equity Cash Flow of a completed structured analysis,
    or why it is unavailable. The series is passed through untouched."""

    common_equity = structured.common_equity
    if common_equity.cash_flows is None:
        if common_equity.status is not CapitalStructureStatus.UNRESOLVED_FUNDING or common_equity.unavailable_reason is None:
            raise PartnershipExecutionError((PartnershipExecutionIssue(
                code=PartnershipExecutionIssueCode.INVALID_COMMON_EQUITY_SERIES,
                message="The Common Equity Cash Flow is missing without an unresolved-funding reason.",
            ),))
        return CommonEquityUnavailable(
            reason=common_equity.unavailable_reason,
            message=common_equity.unavailable_message or "",
            requirement_ids=tuple(
                requirement.requirement_id
                for requirement in structured.funding_requirements
                if requirement.status is FundingRequirementStatus.UNRESOLVED
            ),
        )
    if len(common_equity.cash_flows) != structured.hold_period + 1:
        raise PartnershipExecutionError((PartnershipExecutionIssue(
            code=PartnershipExecutionIssueCode.INVALID_COMMON_EQUITY_SERIES,
            message=(
                f"The Common Equity Cash Flow has {len(common_equity.cash_flows)} periods; "
                f"a {structured.hold_period}-year hold has {structured.hold_period + 1}."
            ),
        ),))
    return CommonEquityCashFlowInput(cadence=CashFlowCadence.ANNUAL, cash_flows=common_equity.cash_flows)


def execute_partnership(partnership: Partnership, structured: StructuredCapitalResult) -> PartnershipResult:
    """The Partnership economics over a completed structured analysis.

    An invalid or unexecutable contract raises, whatever the upstream state.
    An unavailable Common Equity Cash Flow is not an error: the result is
    ``UNAVAILABLE`` with the upstream reason and requirement ids."""

    source = common_equity_input(structured)
    if isinstance(source, CommonEquityUnavailable):
        return unavailable_partnership_result(
            partnership,
            upstream_reason=source.reason,
            upstream_message=source.message,
            requirement_ids=source.requirement_ids,
        )
    return allocate_partnership(partnership, source)
