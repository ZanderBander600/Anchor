"""Anchor deterministic acquisition engine.

Converts a validated ``AcquisitionInputs`` (Quick) or ``AcquisitionTerms`` +
``DetailedOperatingInputs`` (Detailed) into ``AcquisitionResults``
(``docs/phase_2_deterministic_engine.md``,
``docs/detailed_operating_model_v2_1_architecture.md``). The engine is
independent of Excel, AI, and any UI/API framework.

``analyze_acquisition`` (Quick), ``analyze_detailed_acquisition`` (Detailed,
returns ``AcquisitionResults`` only), and
``analyze_detailed_acquisition_with_projection`` (Detailed, Gate 4: also
exposes the deterministic ``OperatingProjection`` via
``DetailedAcquisitionResults``) are the public entry points. All three
delegate their entire downstream acquisition/debt/returns calculation to
the same ``analyze_acquisition_from_operating_projection`` -- there is
exactly one downstream calculation path, never two. The individual Phase
2A/2B/2C/2D/Detailed-Gate-2 modules remain importable directly by tests and
other in-progress engine code, but are not re-exported here, to keep this
package's public surface narrow:

- ``anchor.engine.contracts``
- ``anchor.engine.noi``
- ``anchor.engine.debt``
- ``anchor.engine.acquisition``
- ``anchor.engine.returns``
- ``anchor.engine.operating_projection``
"""

from __future__ import annotations

from .acquisition import (
    analyze_acquisition,
    analyze_detailed_acquisition,
    analyze_detailed_acquisition_with_projection,
)
from .contracts import AcquisitionResults, DetailedAcquisitionResults

__all__ = [
    "analyze_acquisition",
    "analyze_detailed_acquisition",
    "analyze_detailed_acquisition_with_projection",
    "AcquisitionResults",
    "DetailedAcquisitionResults",
]
