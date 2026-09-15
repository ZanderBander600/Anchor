"""Anchor Phase 7 Gate P7.6 -- consolidation.

Governed by ``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md``
Section 9, which is authoritative on any discrepancy.

One deterministic layer downstream of the existing engine::

    each Unit (an existing Deal)  ->  the existing engine  ->  AcquisitionResults
                                                                   |
    the Investment Business Plan and transaction costs  ->  consolidate
                                                                   |
                                                         ConsolidatedResults

There is no portfolio or mixed-use operating engine: both are Units plus this
layer (Section 8.3).

**Dependency direction.** This package imports the calculation-free
``anchor.engine.contracts``, the existing ``anchor.engine.returns`` functions
(P-3: returns on a new series are the engine's own), and the Investment-level
input contracts and validation. It never imports an engine entry point, a mode,
storage or a route, and nothing upstream imports it.
"""

from __future__ import annotations

from .contracts import (
    AreaMetricReason,
    ConsolidatedResults,
    ConsolidationError,
    ConsolidationUnit,
)
from .engine import consolidate

__all__ = [
    "AreaMetricReason",
    "ConsolidatedResults",
    "ConsolidationError",
    "ConsolidationUnit",
    "consolidate",
]
