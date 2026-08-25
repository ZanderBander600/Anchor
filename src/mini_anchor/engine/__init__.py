"""Mini-Anchor deterministic acquisition engine.

Converts a validated ``AcquisitionInputs`` into ``AcquisitionResults``
(``docs/phase_2_deterministic_engine.md``). The engine is independent of
Excel, AI, and any UI/API framework.

``analyze_acquisition`` is the sole public entry point
(``docs/phase_2_deterministic_engine.md`` "Public Engine Entry Point"). It
orchestrates the NOI forecast (Phase 2A), debt schedule (Phase 2B),
exit/cash-flow assembly (Phase 2C), and return metrics (Phase 2D) into one
``AcquisitionResults``. The individual Phase 2A/2B/2C/2D modules remain
importable directly by tests and other in-progress engine code, but are not
re-exported here, to keep this package's public surface narrow:

- ``mini_anchor.engine.contracts``
- ``mini_anchor.engine.noi``
- ``mini_anchor.engine.debt``
- ``mini_anchor.engine.acquisition``
- ``mini_anchor.engine.returns``
"""

from __future__ import annotations

from .acquisition import analyze_acquisition
from .contracts import AcquisitionResults

__all__ = ["analyze_acquisition", "AcquisitionResults"]
