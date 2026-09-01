"""Persistence Phase A -- Deal contracts.

Like ``anchor.engine.contracts`` and ``anchor.analysis.contracts``, this
module performs no calculation and no I/O of its own -- it only describes
the shape of a saved deal. ``Deal.inputs`` nests the existing, frozen
``AcquisitionInputs`` contract directly rather than flattening or
re-declaring its fields, so a saved deal's assumptions are always the exact
same validated shape ``/analyze`` already accepts -- never a parallel
representation that could drift from it.

A ``Deal`` never carries a stored ``AcquisitionResults``. Reopening a deal
means resubmitting ``Deal.inputs`` to the existing, unmodified ``/analyze``
endpoint -- the engine remains the sole authority for every derived number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..contracts import AcquisitionInputs


@dataclass(frozen=True, slots=True, kw_only=True)
class Deal:
    """One saved, named acquisition deal.

    ``id`` is a server-generated identifier, opaque to callers. ``inputs``
    is the exact nine-field ``AcquisitionInputs`` contract the engine
    already consumes -- persistence adds no tenth field and reinterprets
    none of the nine.
    """

    id: str
    name: str
    inputs: AcquisitionInputs
    created_at: datetime
    updated_at: datetime


class DealNotFoundError(LookupError):
    """Raised when a deal id has no corresponding row in the store."""

    def __init__(self, deal_id: str) -> None:
        self.deal_id = deal_id
        super().__init__(f"No deal found with id {deal_id!r}.")
