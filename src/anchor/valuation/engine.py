"""Phase 7 Gate P7.10 Stage 1 -- resolving a valuation definition against one
Analysis Variant.

Restates ``docs/architecture/P7_10_VALUATION_MEMO_REPORTING.md`` Sections 5.2
to 5.6 and the ratified decisions R-A to R-D; that document governs on any
discrepancy. P7.10 Stage 1 carries no engine-scope approval to move a
Property, NOI, exit, acquisition-debt, consolidation, Strategy, Scenario,
Capital Structure, position, Partnership or return formula, and moves none.

**Reads, never recomputes.** The forward NOI of a model month is the variant's
own ``noi_by_year`` entry, and the Exit view is the variant's own terminal
result. Nothing here re-derives either. The selected Strategy and Scenario
reach this layer only by having produced those numbers, so a valuation
resolves separately per variant without duplicating a line of their logic.

**Forward NOI (Section 5.3).** Direct capitalisation at a model month
capitalises the NOI of the year that *follows* it:

- model month ``0`` (closing) capitalises Year 1 NOI, ``noi_by_year[0]``;
- hold-year end ``12y`` with ``y < H`` capitalises Year ``y + 1`` NOI,
  ``noi_by_year[y]``;
- the exit month ``12H`` capitalises Year ``H + 1`` NOI -- which is exactly
  ``exit_noi`` over the exit cap rate, the reserved system Exit view. A stored
  definition never occupies that month (R-B), so no second terminal value can
  drift from the first.

No NOI is floored, smoothed, annualised, stabilised, uplifted to market or
estimated. A non-positive forward NOI makes direct capitalisation unavailable
with a typed reason; it is never divided by the cap rate anyway.

**Reporting only.** Every value here is a reporting value. This module returns
no cash-flow series, produces no sale proceed and alters no upstream result.
Exit remains the only cash-producing valuation, and it is read, not made.
"""

from __future__ import annotations

from ..consolidation.contracts import ConsolidatedResults
from ..contracts import AcquisitionTerms
from ..engine.contracts import AcquisitionResults, ensure_finite
from .contracts import (
    AnalystValue,
    DirectCap,
    ExitValuationView,
    InvestmentValuationResult,
    UnitValuationInstruction,
    UnitValuationResult,
    ValuationAvailability,
    ValuationError,
    ValuationMethodKind,
    ValuationScopeKind,
    ValuationTimepoint,
    ValuationUnavailableReason,
    ValuationUnitInputs,
    ValuationVariantInputs,
)
from .validation import require_valid_valuation_timepoint

# =============================================================================
# Variant inputs, read off completed results
# =============================================================================


def unit_inputs(*, unit_id: str, terms: AcquisitionTerms, results: AcquisitionResults) -> ValuationUnitInputs:
    """One Unit's valuation inputs, copied from its resolved terms and its
    completed results. Nothing is recalculated and nothing is defaulted."""

    return ValuationUnitInputs(
        unit_id=unit_id,
        hold_period=terms.hold_period,
        noi_by_year=results.noi_by_year,
        exit_noi=results.exit_noi,
        exit_cap_rate=terms.exit_cap_rate,
        exit_value=results.exit_value,
        disposition_costs=results.disposition_costs,
        net_sale_proceeds=results.net_sale_proceeds,
    )


def variant_inputs(*, investment_id: str, units: tuple[ValuationUnitInputs, ...]) -> ValuationVariantInputs:
    """The variant's inputs, canonicalised by ``unit_id``. Every Unit shares
    the Investment's one common hold horizon, which the consolidation already
    requires; a disagreement is a programming error, not an analyst finding."""

    if not units:
        raise ValuationError(f"Investment {investment_id!r} resolved no Unit to value.")
    ordered = tuple(sorted(units, key=lambda unit: unit.unit_id))
    holds = {unit.hold_period for unit in ordered}
    if len(holds) != 1:
        raise ValuationError(
            f"Investment {investment_id!r} resolved Units with hold periods {sorted(holds)}; an Investment has one "
            "common hold horizon."
        )
    (hold_period,) = holds
    return ValuationVariantInputs(investment_id=investment_id, hold_period=hold_period, units=ordered)


# =============================================================================
# The reserved system Exit view (R-B)
# =============================================================================


def unit_exit_view(unit: ValuationUnitInputs) -> ExitValuationView:
    """One Unit's Exit view: its existing D6 terminal result, read unchanged."""

    return ExitValuationView(
        scope_kind=ValuationScopeKind.UNIT,
        unit_id=unit.unit_id,
        model_month=unit.hold_period * 12,
        exit_noi=unit.exit_noi,
        exit_cap_rate=unit.exit_cap_rate,
        exit_value=unit.exit_value,
        disposition_costs=unit.disposition_costs,
        net_sale_proceeds=unit.net_sale_proceeds,
    )


def investment_exit_view(consolidated: ConsolidatedResults) -> ExitValuationView:
    """The Investment's Exit view: the existing consolidated terminal result,
    read unchanged. ``implied_exit_cap_rate`` is reported as the consolidation
    states it, including ``None`` where it reports none; no rate is inferred
    from the Units."""

    return ExitValuationView(
        scope_kind=ValuationScopeKind.INVESTMENT,
        unit_id=None,
        model_month=consolidated.hold_period * 12,
        exit_noi=consolidated.exit_noi,
        exit_cap_rate=consolidated.implied_exit_cap_rate,
        exit_value=consolidated.exit_value,
        disposition_costs=consolidated.disposition_costs,
        net_sale_proceeds=consolidated.net_sale_proceeds,
    )


# =============================================================================
# Timing
# =============================================================================


def exit_model_month(hold_period: int) -> int:
    """The exit month of a hold, ``H * 12``."""

    return hold_period * 12


def require_hold_year_end(model_month: int) -> int:
    """``model_month`` unchanged, or raise ``ValuationError``.

    A valuation month is closing or a hold-year end: ``0`` or a multiple of 12
    (R-A). An inside-year month has no forward NOI in this contract, and is
    never annualised, interpolated or rounded to the nearest year to find one.
    ``validation`` refuses such a definition, so reaching here is a programming
    error -- never an analyst finding."""

    if model_month < 0 or model_month % 12 != 0:
        raise ValuationError(
            f"Model month {model_month} is not a valuation timepoint: an initial timepoint is at closing (0) or a "
            "hold-year end (a multiple of 12). Inside-year valuation would need a forward-NOI convention this "
            "contract does not state."
        )
    return model_month


def timepoint_month_reason(model_month: int, *, hold_period: int) -> ValuationUnavailableReason | None:
    """Why ``model_month`` is not a storable timepoint of a hold of
    ``hold_period`` years, or ``None``.

    ``model_month`` is already a hold-year end (see ``require_hold_year_end``).
    Storable months are closing and the hold-year ends strictly before the
    exit. The exit month itself is the reserved system Exit view (R-B): a
    stored definition there would be a second terminal value competing with
    D6's, which is exactly the drift that decision prevents. A month beyond the
    hold is outside this variant's horizon and may resolve under a longer
    hold."""

    if model_month == 0:
        return None
    exit_month = exit_model_month(hold_period)
    if model_month == exit_month:
        return ValuationUnavailableReason.RESERVED_EXIT_MONTH
    if model_month > exit_month:
        return ValuationUnavailableReason.OUTSIDE_HOLD_HORIZON
    return None


def forward_noi_at(unit: ValuationUnitInputs, *, model_month: int) -> float:
    """The forward NOI capitalised at ``model_month``: Year 1 NOI at closing,
    and Year ``y + 1`` NOI at hold-year end ``12y``.

    ``model_month`` must already be a storable month of this Unit's hold; a
    month that is not is a programming error here, because the caller reads
    ``timepoint_month_reason`` first."""

    require_hold_year_end(model_month)
    if timepoint_month_reason(model_month, hold_period=unit.hold_period) is not None:
        raise ValuationError(
            f"Unit {unit.unit_id!r} has no forward NOI at model month {model_month}; that month is not a storable "
            "valuation timepoint of its hold."
        )
    index = model_month // 12
    if index >= len(unit.noi_by_year):
        raise ValuationError(
            f"Unit {unit.unit_id!r} reports {len(unit.noi_by_year)} NOI years against a {unit.hold_period}-year "
            "hold; its results do not span its hold."
        )
    return unit.noi_by_year[index]


# =============================================================================
# Unit resolution
# =============================================================================


def _unavailable(
    *,
    unit_id: str,
    model_month: int,
    method_kind: ValuationMethodKind,
    analyst_supplied: bool,
    evidence_id: str | None,
    reason: ValuationUnavailableReason,
    message: str,
) -> UnitValuationResult:
    return UnitValuationResult(
        unit_id=unit_id,
        model_month=model_month,
        method_kind=method_kind,
        analyst_supplied=analyst_supplied,
        status=ValuationAvailability.UNAVAILABLE,
        value=None,
        forward_noi=None,
        cap_rate=None,
        evidence_id=evidence_id,
        unavailable_reason=reason,
        unavailable_message=message,
    )


def _method_kind(instruction: UnitValuationInstruction) -> tuple[ValuationMethodKind, bool, str | None]:
    match instruction.method:
        case DirectCap():
            return ValuationMethodKind.DIRECT_CAP, False, None
        case AnalystValue():
            return ValuationMethodKind.ANALYST_VALUE, True, instruction.method.evidence_id
        case _:
            raise ValuationError(f"Unit {instruction.unit_id!r} states an unsupported valuation method.")


def resolve_unit_valuation(
    instruction: UnitValuationInstruction, *, unit: ValuationUnitInputs, model_month: int
) -> UnitValuationResult:
    """One Unit's value at ``model_month`` under one resolved variant.

    A direct-cap result reports the forward NOI and cap rate it used; an
    analyst-supplied result reports its evidence identifier and always says it
    is analyst supplied, so no reader can mistake it for an Anchor
    conclusion (Section 5.4)."""

    method_kind, analyst_supplied, evidence_id = _method_kind(instruction)
    require_hold_year_end(model_month)
    month_reason = timepoint_month_reason(model_month, hold_period=unit.hold_period)
    if month_reason is not None:
        detail = (
            "is the exit month, whose value is the reserved system Exit view"
            if month_reason is ValuationUnavailableReason.RESERVED_EXIT_MONTH
            else f"is beyond this variant's {unit.hold_period}-year hold"
        )
        return _unavailable(
            unit_id=unit.unit_id,
            model_month=model_month,
            method_kind=method_kind,
            analyst_supplied=analyst_supplied,
            evidence_id=evidence_id,
            reason=month_reason,
            message=f"Unit {unit.unit_id!r} is not valued at model month {model_month}, which {detail}.",
        )

    match instruction.method:
        case AnalystValue():
            # Constant across Strategies and Scenarios: it is the definition's
            # own stated amount, not an engine conclusion, so no variant
            # result participates.
            amount = ensure_finite(f"analyst_value[{unit.unit_id}]", float(instruction.method.amount))
            return UnitValuationResult(
                unit_id=unit.unit_id,
                model_month=model_month,
                method_kind=method_kind,
                analyst_supplied=True,
                status=ValuationAvailability.AVAILABLE,
                value=amount,
                forward_noi=None,
                cap_rate=None,
                evidence_id=evidence_id,
                unavailable_reason=None,
                unavailable_message=None,
            )
        case DirectCap():
            cap_rate = instruction.method.cap_rate
            forward = forward_noi_at(unit, model_month=model_month)
            if not (forward > 0.0):
                return _unavailable(
                    unit_id=unit.unit_id,
                    model_month=model_month,
                    method_kind=method_kind,
                    analyst_supplied=False,
                    evidence_id=None,
                    reason=ValuationUnavailableReason.NON_POSITIVE_FORWARD_NOI,
                    message=(
                        f"Unit {unit.unit_id!r} has a forward NOI of {forward!r} at model month {model_month}; "
                        "direct capitalisation of a non-positive NOI has no meaning. The NOI is not floored, "
                        "substituted or stabilised, and no value is reported."
                    ),
                )
            value = ensure_finite(f"direct_cap[{unit.unit_id}]", forward / cap_rate)
            return UnitValuationResult(
                unit_id=unit.unit_id,
                model_month=model_month,
                method_kind=method_kind,
                analyst_supplied=False,
                status=ValuationAvailability.AVAILABLE,
                value=value,
                forward_noi=forward,
                cap_rate=cap_rate,
                evidence_id=None,
                unavailable_reason=None,
                unavailable_message=None,
            )
        case _:  # pragma: no cover -- ``_method_kind`` already refused it
            raise ValuationError(f"Unit {instruction.unit_id!r} states an unsupported valuation method.")


# =============================================================================
# Investment resolution (Section 5.5)
# =============================================================================


def resolve_investment_valuation(
    timepoint: ValuationTimepoint, *, variant: ValuationVariantInputs
) -> InvestmentValuationResult:
    """The Investment's contemporaneous value at ``timepoint``, and every
    Unit's own result.

    The Investment value is the canonical-order sum of the Unit values, and
    exists only when every member Unit has a valid value at the same model
    month. One missing or invalid Unit makes it unavailable and names that
    Unit; a partial portfolio sum is never presented as the Investment value.

    A hidden one-unit Investment follows this same contract: its Investment
    value equals its one Unit's value, and the two remain separately labelled
    scopes."""

    require_valid_valuation_timepoint(timepoint)
    if timepoint.investment_id != variant.investment_id:
        raise ValuationError(
            f"Valuation timepoint {timepoint.timepoint_id!r} belongs to Investment "
            f"{timepoint.investment_id!r} and is never valued against Investment {variant.investment_id!r}."
        )

    month = timepoint.model_month
    by_unit = {unit.unit_id: unit for unit in variant.units}
    instructed = {instruction.unit_id: instruction for instruction in timepoint.unit_instructions}

    results: list[UnitValuationResult] = []
    for unit_id in sorted(set(by_unit) | set(instructed)):
        unit = by_unit.get(unit_id)
        instruction = instructed.get(unit_id)
        if instruction is None:
            results.append(
                _unavailable(
                    unit_id=unit_id,
                    model_month=month,
                    method_kind=ValuationMethodKind.DIRECT_CAP,
                    analyst_supplied=False,
                    evidence_id=None,
                    reason=ValuationUnavailableReason.UNIT_NOT_VALUED,
                    message=(
                        f"Investment {variant.investment_id!r} holds Unit {unit_id!r}, which valuation timepoint "
                        f"{timepoint.timepoint_id!r} does not instruct. Every member Unit is valued, or the "
                        "Investment has no value."
                    ),
                )
            )
            continue
        method_kind, analyst_supplied, evidence_id = _method_kind(instruction)
        if unit is None:
            results.append(
                _unavailable(
                    unit_id=unit_id,
                    model_month=month,
                    method_kind=method_kind,
                    analyst_supplied=analyst_supplied,
                    evidence_id=evidence_id,
                    reason=ValuationUnavailableReason.UNIT_NOT_IN_VARIANT,
                    message=(
                        f"Valuation timepoint {timepoint.timepoint_id!r} instructs Unit {unit_id!r}, which this "
                        f"variant of Investment {variant.investment_id!r} does not hold."
                    ),
                )
            )
            continue
        results.append(resolve_unit_valuation(instruction, unit=unit, model_month=month))

    ordered = tuple(results)
    missing = tuple(result for result in ordered if result.status is not ValuationAvailability.AVAILABLE)
    if missing:
        named = ", ".join(f"{result.unit_id!r} ({result.unavailable_reason})" for result in missing)
        return InvestmentValuationResult(
            timepoint_id=timepoint.timepoint_id,
            investment_id=variant.investment_id,
            kind=timepoint.kind,
            label=timepoint.label,
            model_month=month,
            scope_kind=ValuationScopeKind.INVESTMENT,
            status=ValuationAvailability.UNAVAILABLE,
            value=None,
            unit_results=ordered,
            unavailable_reason=ValuationUnavailableReason.INCOMPLETE_UNITS,
            unavailable_message=(
                f"Investment {variant.investment_id!r} has no value at valuation timepoint "
                f"{timepoint.timepoint_id!r}: {named}. A partial sum of the Units that do have a value is never "
                "the Investment value."
            ),
        )

    total = 0.0
    for result in ordered:
        if result.value is None:  # pragma: no cover -- every result here is available
            raise ValuationError(f"Unit {result.unit_id!r} reported an available valuation with no value.")
        total = total + result.value
    return InvestmentValuationResult(
        timepoint_id=timepoint.timepoint_id,
        investment_id=variant.investment_id,
        kind=timepoint.kind,
        label=timepoint.label,
        model_month=month,
        scope_kind=ValuationScopeKind.INVESTMENT,
        status=ValuationAvailability.AVAILABLE,
        value=ensure_finite(f"investment_value[{timepoint.timepoint_id}]", total),
        unit_results=ordered,
        unavailable_reason=None,
        unavailable_message=None,
    )
