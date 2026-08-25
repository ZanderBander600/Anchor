"""Mini-Anchor deterministic acquisition engine.

Converts a validated ``AcquisitionInputs`` into ``AcquisitionResults``
(``docs/phase_2_deterministic_engine.md``). The engine is independent of
Excel, AI, and any UI/API framework.

This package's public entry point, ``analyze_acquisition``, does not exist
yet; it is introduced in Phase 2E once the NOI forecast (Phase 2A), debt
schedule (Phase 2B), exit/cash-flow assembly (Phase 2C), and return metrics
(Phase 2D) are all in place. Until then, the modules below are internal and
are imported directly by tests and other in-progress engine code:

- ``mini_anchor.engine.contracts``
- ``mini_anchor.engine.noi``
- ``mini_anchor.engine.debt``
- ``mini_anchor.engine.acquisition``
- ``mini_anchor.engine.returns``
"""

from __future__ import annotations
