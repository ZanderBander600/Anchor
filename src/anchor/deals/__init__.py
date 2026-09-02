"""Persistence Phase A/C / Detailed Operating Model V2.1 Gate 5b -- Deal
Library backend foundation.

Public surface: the ``Deal``/``DealNotFoundError`` contracts and the
CRUD/lifecycle functions the API layer delegates to. ``anchor.deals`` never
imports ``anchor.engine`` or ``anchor.validation`` -- it stores and returns
already-validated ``AcquisitionInputs``/``AcquisitionTerms``/
``DetailedOperatingInputs`` values and performs no financial calculation and
no input validation of its own. See ``store.py`` for the storage mechanism,
its two-table Quick/Detailed split, and its numeric-representation
rationale.
"""

from __future__ import annotations

from .contracts import Deal, DealNotFoundError
from .store import (
    create_deal,
    create_detailed_deal,
    delete_deal,
    duplicate_deal,
    get_deal,
    get_db_path,
    list_deals,
    update_deal,
    update_detailed_deal,
)

__all__ = [
    "Deal",
    "DealNotFoundError",
    "create_deal",
    "create_detailed_deal",
    "delete_deal",
    "duplicate_deal",
    "get_deal",
    "get_db_path",
    "list_deals",
    "update_deal",
    "update_detailed_deal",
]
