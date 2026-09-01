"""Persistence Phase A -- Deal Library backend foundation.

Public surface: the ``Deal``/``DealNotFoundError`` contracts and the four
CRUD functions the API layer delegates to. ``anchor.deals`` never imports
``anchor.engine`` or ``anchor.validation`` -- it stores and returns already-
validated ``AcquisitionInputs`` values and performs no financial
calculation and no input validation of its own. See ``store.py`` for the
storage mechanism and its numeric-representation rationale.
"""

from __future__ import annotations

from .contracts import Deal, DealNotFoundError
from .store import create_deal, get_deal, get_db_path, list_deals, update_deal

__all__ = [
    "Deal",
    "DealNotFoundError",
    "create_deal",
    "get_deal",
    "get_db_path",
    "list_deals",
    "update_deal",
]
