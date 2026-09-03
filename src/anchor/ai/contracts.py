"""Phase 9A / Detailed Operating Model V2.1 Gate 9 AI Analyst contracts.

Like ``anchor.engine.contracts`` and ``anchor.analysis.contracts``,
this module performs no calculation of its own -- it only describes the
shape of the deterministic context handed to the model
(``AnalysisContext``) and the structured interpretation handed back
(``AIAnalysis``). Neither dataclass computes, stores, or derives any
financial metric; ``AnalysisContext`` only aggregates already-computed
Phase 2/7/8 (and Detailed Operating Model V2.1) result contracts, and
every ``AIAnalysis`` field is prose the model produced by interpreting
that context.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..analysis.contracts import (
    ReturnHurdleMetric,
    StandardBreakEvenAnalysis,
    StandardDetailedBreakEvenAnalysis,
    StandardDetailedSensitivityPresets,
    StandardSensitivityPresets,
)
from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
)
from ..engine.contracts import AcquisitionResults, OperatingProjection


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalysisContext:
    """The complete deterministic Anchor context supplied to the AI
    Analyst for one request -- one context shape for both Quick and
    Detailed Underwrite, discriminated by ``operating_mode`` (Detailed
    Operating Model V2.1 Gate 9), mirroring the ``Deal`` persistence
    contract's own QUICK/DETAILED split (``anchor.deals.contracts``).

    A ``QUICK`` context has ``inputs`` populated and ``terms``/
    ``detailed_operating_inputs``/``operating_projection`` all ``None`` --
    unchanged from the original Phase 9A shape. A ``DETAILED`` context has
    ``terms``/``detailed_operating_inputs``/``operating_projection``
    populated and ``inputs`` ``None`` -- a Detailed context never carries a
    fabricated ``AcquisitionInputs`` (no manufactured ``current_noi``/
    ``noi_growth``), mirroring the engine-layer resolution
    (Gate 3/4) exactly. ``results`` is always the same
    ``AcquisitionResults`` shape either way -- it is genuinely identical
    for both modes, never mode-specific.

    Every field is either an already-validated input contract, an
    already-computed Phase 2/7/8/Detailed-Gate-2/8 result contract, or one
    of the three user-supplied hurdle targets from the request -- nothing
    here is computed by this module. Nesting the existing frozen contracts
    directly (rather than flattening/re-deriving their fields) guarantees
    the AI Analyst always sees the exact same raw decimals the
    deterministic engine and analysis layers produced.
    """

    operating_mode: OperatingMode
    inputs: AcquisitionInputs | None
    terms: AcquisitionTerms | None
    detailed_operating_inputs: DetailedOperatingInputs | None
    operating_projection: OperatingProjection | None
    results: AcquisitionResults
    sensitivities: StandardSensitivityPresets | StandardDetailedSensitivityPresets
    break_even: StandardBreakEvenAnalysis | StandardDetailedBreakEvenAnalysis
    target_levered_irr: float
    target_equity_multiple: float
    target_headline_dscr: float
    return_hurdle_metric: ReturnHurdleMetric

    def __post_init__(self) -> None:
        if self.operating_mode is OperatingMode.QUICK:
            if self.inputs is None:
                raise ValueError("A QUICK AnalysisContext must have 'inputs' populated.")
            if (
                self.terms is not None
                or self.detailed_operating_inputs is not None
                or self.operating_projection is not None
            ):
                raise ValueError(
                    "A QUICK AnalysisContext must not have 'terms', "
                    "'detailed_operating_inputs', or 'operating_projection' populated."
                )
        else:
            if (
                self.terms is None
                or self.detailed_operating_inputs is None
                or self.operating_projection is None
            ):
                raise ValueError(
                    "A DETAILED AnalysisContext must have 'terms', "
                    "'detailed_operating_inputs', and 'operating_projection' all populated."
                )
            if self.inputs is not None:
                raise ValueError(
                    "A DETAILED AnalysisContext must not have 'inputs' populated -- "
                    "current_noi/noi_growth/occupancy do not exist in this path."
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class AIAnalysis:
    """The structured investment-analyst interpretation returned by the AI
    provider, suitable for direct frontend rendering.

    Every field is prose (or a tuple of prose statements) produced by
    interpreting a supplied ``AnalysisContext`` -- this contract never
    carries a newly generated numeric financial metric. Field set frozen
    per the Phase 9A AI Analyst spec, unchanged by Detailed Operating
    Model V2.1 Gate 9 -- the same report structure applies to both modes.
    """

    executive_summary: str
    investment_view: str
    strengths: tuple[str, ...]
    risks: tuple[str, ...]
    return_drivers: tuple[str, ...]
    downside_analysis: str
    capital_structure_analysis: str
    break_even_analysis: str
    questions_to_investigate: tuple[str, ...]
    confidence_notes: tuple[str, ...]
