"""Persistence Phase A/C / Detailed Operating Model V2.1 Gate 5b -- Deal
Library backend foundation.

Public surface: the ``Deal``/``DealNotFoundError`` contracts and the
CRUD/lifecycle functions the API layer delegates to. ``anchor.deals`` never
imports an ``anchor.engine`` *calculation* module (``acquisition``/``debt``/
``noi``/``returns``/``operating_projection``) or ``anchor.validation`` -- it
stores and returns already-validated ``AcquisitionInputs``/
``AcquisitionTerms``/``DetailedOperatingInputs`` values and performs no
financial calculation and no input validation of its own. Owner Return
Metrics V3 Gate A6's ``analysis_snapshot``/``ai_snapshot`` are cached,
already-computed results (``anchor.engine.contracts``/``anchor.ai.contracts``
result *shapes*, never calculation modules) -- see ``store.py``'s module
docstring for the full architecture, its two-table Quick/Detailed split,
and its numeric-representation rationale.
"""

from __future__ import annotations

from .contracts import Deal, DealNotFoundError
from .store import (
    SnapshotValidationError,
    create_deal,
    create_detailed_deal,
    delete_deal,
    duplicate_deal,
    get_deal,
    get_db_path,
    list_deals,
    update_ai_snapshot,
    update_analysis_snapshot,
    update_deal,
    update_detailed_deal,
)

__all__ = [
    "Deal",
    "DealNotFoundError",
    "SnapshotValidationError",
    "create_deal",
    "create_detailed_deal",
    "delete_deal",
    "duplicate_deal",
    "get_deal",
    "get_db_path",
    "list_deals",
    "update_ai_snapshot",
    "update_analysis_snapshot",
    "update_deal",
    "update_detailed_deal",
]
