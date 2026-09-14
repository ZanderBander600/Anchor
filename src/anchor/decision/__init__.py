"""Phase 7 Gate P7.5 -- the Decision layer.

A read-only presentation over completed deterministic results
(``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Section 14.1,
P-5, DC-1). It imports result contracts only, never an engine calculation
module, and it persists nothing. See ``comparison.py``.
"""

from __future__ import annotations
