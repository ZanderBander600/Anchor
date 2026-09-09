"""Phase 9A / Detailed Operating Model V2.1 Gate 9 AI Analyst contracts.

Like ``anchor.engine.contracts`` and ``anchor.analysis.contracts``,
this module performs no calculation of its own -- it only describes the
shape of the deterministic context handed to the model
(``AnalysisContext``) and the structured interpretation handed back
(``AIAnalysis``, plus the concise owner-level ``DealStory`` nested inside
it since Sprint B Gate B4). No dataclass here computes, stores, or derives
any financial metric; ``AnalysisContext`` only aggregates already-computed
Phase 2/7/8 (and Detailed Operating Model V2.1) result contracts, and
every ``AIAnalysis``/``DealStory`` field is prose the model produced by
interpreting that context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ..analysis import ParsedLeaseLevelInputs
from ..analysis.contracts import (
    LeaseLevelAcquisitionResults,
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
    UnsupportedOperatingModeError,
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

    **D5.8 -- the third mode.** A ``LEASE_LEVEL`` context has ``terms``
    populated (Lease-Level shares the same eleven-field ``AcquisitionTerms``
    Detailed uses), plus ``lease_level_inputs`` -- the five analyst-approved
    leasing input records -- and ``lease_level_results``, the authoritative
    ``LeaseLevelAcquisitionResults`` envelope. ``inputs``,
    ``detailed_operating_inputs`` and ``operating_projection`` are all ``None``:
    Lease-Level has no ``current_noi``/``noi_growth`` and no Detailed operating
    projection, and fabricates neither to resemble a mode it is not.

    ``results`` is still the same ``AcquisitionResults`` for all three modes,
    and for Lease-Level it is **the same object** as
    ``lease_level_results.results`` -- one returns engine, joined at the
    existing seam, never a Lease-Level copy of a return figure.

    **``sensitivities`` and ``break_even`` are optional as of D5.8**, which is
    what lets a Lease-Level context exist at all. The two ``None`` values mean
    different things and are never collapsed into "unsupported":

      * ``sensitivities=None`` means *no standardized preset bundle was
        supplied with this context*. Lease-Level sensitivity is supported and
        shipped (D5.7): it is analyst-directed, one axis or two at a time,
        chosen in Risk. What Lease-Level does not have is Quick's and
        Detailed's fixed preset package, so there is nothing standardized to
        attach here. Presenting this absence as "sensitivity is unsupported for
        this mode" would be false.
      * ``break_even=None`` means *break-even was not supplied*, and for
        Lease-Level it genuinely does not exist (guardrail G35). The absence is
        the honest answer; a zero, a placeholder or a "not enough data" result
        would not be.

    Quick and Detailed still require both to be populated, asserted below, so
    the optionality is a widening for the third mode only and cannot silently
    empty the other two.

    ``deal_context`` (Owner Return Metrics V3 Gate A4) is the optional,
    user-authored free text from the active ``Deal`` (``anchor.deals.
    contracts``), threaded in separately from every deterministic field
    above -- it is never an ``AcquisitionInputs``/``AcquisitionTerms``/
    ``DetailedOperatingInputs`` field and never read by the engine or
    analysis layers that produced ``results``/``sensitivities``/
    ``break_even``. ``None`` when no context was supplied, identical in
    shape for both modes.
    """

    operating_mode: OperatingMode
    inputs: AcquisitionInputs | None
    terms: AcquisitionTerms | None
    detailed_operating_inputs: DetailedOperatingInputs | None
    operating_projection: OperatingProjection | None
    # Defaulted to ``None`` so a Quick or Detailed construction reads exactly
    # as it did before D5.8. ``sensitivities``/``break_even`` deliberately get
    # no default: those two became optional in this gate, and a default would
    # let a Quick or Detailed caller drop a bundle it has always supplied by
    # simply not mentioning it.
    lease_level_inputs: ParsedLeaseLevelInputs | None = None
    lease_level_results: LeaseLevelAcquisitionResults | None = None
    results: AcquisitionResults
    sensitivities: StandardSensitivityPresets | StandardDetailedSensitivityPresets | None
    break_even: StandardBreakEvenAnalysis | StandardDetailedBreakEvenAnalysis | None
    target_levered_irr: float
    target_equity_multiple: float
    target_headline_dscr: float
    return_hurdle_metric: ReturnHurdleMetric
    deal_context: str | None

    def __post_init__(self) -> None:
        # D5.1A: total dispatch. Previously ``if QUICK: ... else: <DETAILED
        # invariants>``, so a third mode would have been validated against
        # Detailed's required-field rules and, on passing them, presented to the
        # model as a Detailed deal. Each mode now states its own invariants.
        # A mode this contract cannot yet represent honestly is refused by name
        # -- see D7/D5.8, which owns making ``sensitivities``/``break_even``
        # optional so Lease-Level can be represented at all.
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
            self._require_standard_scenario_analysis("QUICK")
            self._reject_lease_level_fields("QUICK")
        elif self.operating_mode is OperatingMode.DETAILED:
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
            self._require_standard_scenario_analysis("DETAILED")
            self._reject_lease_level_fields("DETAILED")
        elif self.operating_mode is OperatingMode.LEASE_LEVEL:
            # D5.8. The mode is representable now that ``sensitivities`` and
            # ``break_even`` are optional -- the exact widening D5.1A named as
            # the blocker when it wrote the refusal this arm replaces.
            if self.terms is None:
                raise ValueError(
                    "A LEASE_LEVEL AnalysisContext must have 'terms' populated."
                )
            if self.lease_level_inputs is None or self.lease_level_results is None:
                raise ValueError(
                    "A LEASE_LEVEL AnalysisContext must have 'lease_level_inputs' "
                    "and 'lease_level_results' populated."
                )
            if (
                self.inputs is not None
                or self.detailed_operating_inputs is not None
                or self.operating_projection is not None
            ):
                raise ValueError(
                    "A LEASE_LEVEL AnalysisContext must not have 'inputs', "
                    "'detailed_operating_inputs', or 'operating_projection' "
                    "populated -- none of them exists in this path."
                )
            # One returns engine. ``results`` is not a Lease-Level copy of the
            # envelope's returns; it is the identical object, so a figure can
            # never be presented twice with two values.
            if self.results is not self.lease_level_results.results:
                raise ValueError(
                    "A LEASE_LEVEL AnalysisContext's 'results' must be the same "
                    "object as 'lease_level_results.results'."
                )
        else:
            raise UnsupportedOperatingModeError(
                self.operating_mode, operation="AnalysisContext"
            )

    def _require_standard_scenario_analysis(self, mode_label: str) -> None:
        """D5.8: the two fields became optional so Lease-Level could exist.

        Quick and Detailed are held to exactly what they carried before, here,
        so the widening cannot quietly empty a mode that has always supplied
        both. A Quick or Detailed context with ``sensitivities=None`` is not a
        mode with no preset bundle -- it is a context that lost one.
        """

        if self.sensitivities is None:
            raise ValueError(
                f"A {mode_label} AnalysisContext must have 'sensitivities' populated."
            )
        if self.break_even is None:
            raise ValueError(
                f"A {mode_label} AnalysisContext must have 'break_even' populated."
            )

    def _reject_lease_level_fields(self, mode_label: str) -> None:
        if self.lease_level_inputs is not None or self.lease_level_results is not None:
            raise ValueError(
                f"A {mode_label} AnalysisContext must not have "
                "'lease_level_inputs' or 'lease_level_results' populated."
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DealStory:
    """Sprint B Gate B4 -- the concise, owner-level AI interpretation
    rendered inside the One-Page Owner Summary.

    A deliberately narrow companion to ``AIAnalysis`` (the full AI Analyst
    report), not a replacement for it and never a frontend truncation of
    it: the model produces these four fields directly, under their own
    dedicated prompt instructions and their own length limits, in the same
    single structured response that produces the full report. Like
    ``AIAnalysis``, every field here is prose the model wrote by
    interpreting an already-computed ``AnalysisContext`` -- this contract
    never carries a newly generated numeric financial metric, and nothing
    in this module calculates anything.

    ``key_strengths``/``key_risks`` are capped at ``MAX_STORY_ITEMS`` items
    each -- the cap is a hard contract invariant enforced below, so an
    over-long list can never reach the Owner Summary (the provider layer
    trims a chatty model's response to the cap before construction, so the
    cap is a guarantee rather than a request failure).

    ``model_gap`` is first-class and nullable: it states, in the model's
    own words, which part of the stated strategy Anchor's deterministic
    cash flows do not model (the canonical example being a stated
    refinance-and-hold plan against Anchor's terminal-sale engine). It is
    ``None`` -- never a manufactured filler sentence -- whenever no
    material gap exists.
    """

    MAX_STORY_ITEMS: ClassVar[int] = 2

    investment_view: str
    key_strengths: tuple[str, ...]
    key_risks: tuple[str, ...]
    model_gap: str | None

    def __post_init__(self) -> None:
        for field_name in ("key_strengths", "key_risks"):
            value = getattr(self, field_name)
            if len(value) > self.MAX_STORY_ITEMS:
                raise ValueError(
                    f"DealStory.{field_name} may carry at most "
                    f"{self.MAX_STORY_ITEMS} items; got {len(value)}."
                )


@dataclass(frozen=True, slots=True, kw_only=True)
class AIAnalysis:
    """The structured investment-analyst interpretation returned by the AI
    provider, suitable for direct frontend rendering.

    Every field is prose (or a tuple of prose statements) produced by
    interpreting a supplied ``AnalysisContext`` -- this contract never
    carries a newly generated numeric financial metric. The ten original
    report fields are frozen per the Phase 9A AI Analyst spec, unchanged by
    Detailed Operating Model V2.1 Gate 9 -- the same report structure
    applies to both modes.

    ``deal_story`` (Sprint B Gate B4) is the one addition: the concise,
    owner-level ``DealStory`` the same single provider response produces
    alongside the full report, so "Generate AI Analysis" remains one
    OpenAI call and one persisted ``ai_snapshot`` rather than two of each.
    It is ``None`` only for an AI snapshot saved before Gate B4 existed --
    a legacy snapshot still restores its full report unchanged, and simply
    shows no Deal Story until the analyst regenerates. A live provider
    response always carries one (the structured-output schema requires it).
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
    deal_story: DealStory | None = None
