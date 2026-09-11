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

Sprint D5.8A adds one more kind of cached, already-computed artifact:
``OneWaySensitivitySnapshot``/``TwoWaySensitivitySnapshot``, the latest
successful Lease-Level sensitivity runs, stored in their own
``deal_sensitivity_snapshots`` table and written only through
``update_one_way_sensitivity_snapshot``/``update_two_way_sensitivity_snapshot``.
They are derived snapshots in exactly the sense ``ai_snapshot`` is -- guarded by
the same canonical input fingerprint, never a source of truth, and never a
calculation this layer performs.
"""

from __future__ import annotations

from .contracts import (
    Deal,
    DealNotFoundError,
    OneWaySensitivityConfiguration,
    OneWaySensitivitySnapshot,
    TwoWaySensitivityConfiguration,
    TwoWaySensitivitySnapshot,
)
from .fingerprint import (
    fingerprint_ai,
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)
from .store import (
    SnapshotValidationError,
    create_deal,
    create_detailed_deal,
    create_lease_level_deal,
    delete_deal,
    duplicate_deal,
    get_deal,
    get_db_path,
    list_deals,
    update_ai_snapshot,
    update_analysis_snapshot,
    update_deal,
    update_detailed_deal,
    update_lease_level_deal,
    update_one_way_sensitivity_snapshot,
    update_two_way_sensitivity_snapshot,
)

__all__ = [
    "Deal",
    "DealNotFoundError",
    "OneWaySensitivityConfiguration",
    "OneWaySensitivitySnapshot",
    "SnapshotValidationError",
    "TwoWaySensitivityConfiguration",
    "TwoWaySensitivitySnapshot",
    "create_deal",
    "create_detailed_deal",
    "create_lease_level_deal",
    "delete_deal",
    "duplicate_deal",
    "fingerprint_ai",
    "fingerprint_detailed_inputs",
    "fingerprint_lease_level_inputs",
    "fingerprint_quick_inputs",
    "get_deal",
    "get_db_path",
    "list_deals",
    "update_ai_snapshot",
    "update_analysis_snapshot",
    "update_deal",
    "update_detailed_deal",
    "update_lease_level_deal",
    "update_one_way_sensitivity_snapshot",
    "update_two_way_sensitivity_snapshot",
]
