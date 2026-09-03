"""Persistence Phase A / Detailed Operating Model V2.1 Gate 5b -- Deal
contracts.

Like ``anchor.engine.contracts`` and ``anchor.analysis.contracts``, this
module performs no calculation and no I/O of its own -- it only describes
the shape of a saved deal. ``Deal.inputs`` (Quick) and ``Deal.terms`` /
``Deal.detailed_operating_inputs`` (Detailed) nest the existing, frozen
``AcquisitionInputs`` / ``AcquisitionTerms`` / ``DetailedOperatingInputs``
contracts directly rather than flattening or re-declaring their fields, so a
saved deal's assumptions are always the exact same validated shape the
engine already consumes -- never a parallel representation that could drift
from it.

A ``Deal`` never carries a stored ``AcquisitionResults``. Reopening a deal
means resubmitting its assumptions to the existing, unmodified engine entry
point (``analyze_acquisition`` or ``analyze_detailed_acquisition``) -- the
engine remains the sole authority for every derived number.

One domain-level ``Deal`` shape represents both operating modes, per
``operating_mode``: a ``QUICK`` deal has ``inputs`` populated and ``terms``/
``detailed_operating_inputs`` both ``None``; a ``DETAILED`` deal has
``terms``/``detailed_operating_inputs`` populated and ``inputs`` ``None`` --
never a fabricated ``AcquisitionInputs`` with a placeholder ``current_noi``/
``noi_growth``/``occupancy``. See ``docs/detailed_operating_model_v2_1_architecture.md``
Section 4 and Section 6 for the resolution this mirrors at the persistence
layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..contracts import (
    AcquisitionInputs,
    AcquisitionTerms,
    DetailedOperatingInputs,
    OperatingMode,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Deal:
    """One saved, named acquisition deal, Quick or Detailed.

    ``id`` is a server-generated identifier, opaque to callers.

    For a ``QUICK`` deal: ``inputs`` is the exact ``AcquisitionInputs``
    contract the Quick engine entry point already consumes; ``terms`` and
    ``detailed_operating_inputs`` are ``None``.

    For a ``DETAILED`` deal: ``terms`` and ``detailed_operating_inputs`` are
    the exact contracts the Detailed engine entry point already consumes;
    ``inputs`` is ``None`` -- a Detailed deal never has an
    ``AcquisitionInputs`` instance, matching the engine-layer resolution
    (Gate 3) exactly.
    """

    id: str
    name: str
    operating_mode: OperatingMode
    inputs: AcquisitionInputs | None
    terms: AcquisitionTerms | None
    detailed_operating_inputs: DetailedOperatingInputs | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.operating_mode is OperatingMode.QUICK:
            if self.inputs is None:
                raise ValueError("A QUICK Deal must have 'inputs' populated.")
            if self.terms is not None or self.detailed_operating_inputs is not None:
                raise ValueError(
                    "A QUICK Deal must not have 'terms' or "
                    "'detailed_operating_inputs' populated."
                )
        else:
            if self.terms is None or self.detailed_operating_inputs is None:
                raise ValueError(
                    "A DETAILED Deal must have both 'terms' and "
                    "'detailed_operating_inputs' populated."
                )
            if self.inputs is not None:
                raise ValueError("A DETAILED Deal must not have 'inputs' populated.")


class DealNotFoundError(LookupError):
    """Raised when a deal id has no corresponding row in either the Quick
    (``deals``) or Detailed (``detailed_deals``) store."""

    def __init__(self, deal_id: str) -> None:
        self.deal_id = deal_id
        super().__init__(f"No deal found with id {deal_id!r}.")
