"""P7.8 baseline builder (not a test module; see
``tests/test_p7_8_compatibility_oracle.py``).

Usage: ``python _p7_8_baseline_builder.py <repo_root> <db_path> <manifest.json> <foundation.json>``

``<repo_root>/src`` is the P7.7 merge ``a9f9b09``, exported by ``git archive``.

1. The P7.7 builder (``_p7_7_baseline_builder.py``) runs against it, with its
   optional fourth argument ``p7_7`` asserting that the tree is the P7.7 merge.
   It writes the same database through that tree's own store and records the
   same representative HTTP exchanges into ``<manifest.json>``.
2. Then, through that tree's own P7.7 facades and on a private copy of the
   database (so nothing it reads can warm a cache the replay would see), this
   records the neutral Capital Structure foundation of the visible mixed-mode
   Investment, and of each of its Quick, Detailed and Lease-Level Units, into
   ``<foundation.json>``.
"""

from __future__ import annotations

import dataclasses
import json
import runpy
import shutil
import sys
from pathlib import Path

root, db_arg, manifest_arg, foundation_arg = sys.argv[1:5]
_P7_7_BUILDER = Path(__file__).resolve().with_name("_p7_7_baseline_builder.py")
sys.argv = [str(_P7_7_BUILDER), root, db_arg, manifest_arg, "p7_7"]
namespace = runpy.run_path(str(_P7_7_BUILDER), run_name="__p7_7_baseline_builder__")

import anchor  # noqa: E402
from anchor.capital_structure import (  # noqa: E402
    CapitalStructureUnit,
    analyze_investment_capital_structure,
    analyze_unit_capital_structure,
)
from anchor.contracts import acquisition_terms_from_inputs  # noqa: E402
from anchor.deals.investment_variants import analyze_investment_variant, inspect_investment_variant_inputs  # noqa: E402
from anchor.engine.contracts import AcquisitionResults  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(Path(root).resolve() / "src"), anchor.__file__

db = Path(db_arg)
private = db.with_name(f"{db.stem}.foundation{db.suffix}")
shutil.copyfile(db, private)
investment_id = namespace["visible"].id

analysis = analyze_investment_variant(investment_id, "base", "base", db_path=private)
inputs = inspect_investment_variant_inputs(investment_id, "base", "base", db_path=private)
units: list[CapitalStructureUnit] = []
for unit_inputs, unit_result in zip(inputs.units, analysis.unit_results, strict=True):
    assert unit_inputs.unit_id == unit_result.unit_id
    envelope = unit_result.results
    results = envelope if isinstance(envelope, AcquisitionResults) else envelope.results
    resolved = unit_inputs.resolved
    terms = getattr(resolved, "terms", None)
    units.append(
        CapitalStructureUnit(
            unit_id=unit_inputs.unit_id,
            terms=acquisition_terms_from_inputs(getattr(resolved, "inputs")) if terms is None else terms,
            results=results,
        )
    )

record = {
    "investment_id": investment_id,
    "units": {
        unit.unit_id: dataclasses.asdict(
            analyze_unit_capital_structure(unit_id=unit.unit_id, terms=unit.terms, results=unit.results)
        )
        for unit in units
    },
    "investment": dataclasses.asdict(
        analyze_investment_capital_structure(units=units, consolidated=analysis.consolidated_results)
    ),
}
Path(foundation_arg).write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
