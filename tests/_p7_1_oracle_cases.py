"""P7.1 neutral oracle runner (not a test module; see
``tests/test_p7_1_neutral_oracle.py``).

Usage: ``python _p7_1_oracle_cases.py <repo_root> <out.json>``

Runs a fixed set of ordinary Quick / Detailed / Lease-Level analyses against
``<repo_root>/src``, never against whatever ``anchor`` is installed. It writes
every result field, encoded bit-exactly with ``float.hex``, so the last bit
and the sign of zero are visible. The Detailed and Lease-Level projections are
included.

When the tree has the P7.1 Scenario layer, every case is also run through it
with a **zero-override** scenario and stored as ``<case>#scenario0``.

It must run unchanged against ``f234e4c``, so it imports only names that
existed there, and the P7.1 names behind ``ImportError``.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
out_path = Path(sys.argv[2])
sys.path.insert(0, str(root / "src"))
sys.path.insert(1, str(Path(__file__).resolve().parent))

import anchor  # noqa: E402

assert Path(anchor.__file__).resolve().is_relative_to(root / "src"), anchor.__file__

from anchor.analysis.business_plan_analysis import (  # noqa: E402
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.business_plan import BusinessPlan  # noqa: E402
from anchor.engine import (  # noqa: E402
    analyze_acquisition,
    analyze_detailed_acquisition_with_projection,
)

import _p7_1_scenario_fixtures as fx  # noqa: E402

try:
    from anchor.analysis.scenario import (  # noqa: E402
        ScenarioDefinition,
        analyze_detailed_acquisition_with_scenario,
        analyze_lease_level_acquisition_with_scenario,
        analyze_quick_acquisition_with_scenario,
    )

    HAS_SCENARIO = True
except ImportError:
    HAS_SCENARIO = False


def encode(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, tuple):
        return [encode(item) for item in value]
    if dataclasses.is_dataclass(value):
        return {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return repr(value)


def lease_level_args(**roll: object) -> tuple[tuple, dict]:
    suites, leases = fx.rent_roll(**roll)  # type: ignore[arg-type]
    return (
        (fx.lease_level_terms(), fx.lease_level_property(), suites, leases),
        {"market_leasing": fx.market(), "operating_inputs": fx.lease_level_operating()},
    )


overridden_roll = {
    "c_override": fx.market(market_rent_psf=50.0, renewal_probability=0.5),
    "d_market_rent_psf": 60.0,
    "d_override": fx.market(market_rent_psf=55.0),
}

#: case -> (ordinary call, zero-override scenario call or None)
cases: dict[str, tuple] = {}

for label, plan in (("", BusinessPlan()), ("_plan", fx.business_plan())):
    cases[f"Q{label}"] = (
        lambda plan=plan: analyze_quick_acquisition_with_business_plan(fx.quick_inputs(), business_plan=plan),
        "quick",
        plan,
    )
    cases[f"D{label}"] = (
        lambda plan=plan: analyze_detailed_acquisition_with_business_plan(
            fx.detailed_terms(), fx.detailed_operating(), business_plan=plan
        ),
        "detailed",
        plan,
    )
    cases[f"L{label}"] = (
        lambda plan=plan: analyze_lease_level_acquisition_with_business_plan(
            *lease_level_args()[0], **lease_level_args()[1], business_plan=plan
        ),
        "lease_level",
        plan,
    )
cases["L_overrides_plan"] = (
    lambda: analyze_lease_level_acquisition_with_business_plan(
        *lease_level_args(**overridden_roll)[0],
        **lease_level_args(**overridden_roll)[1],
        business_plan=fx.business_plan(),
    ),
    "lease_level_overrides",
    fx.business_plan(),
)
cases["Q_plain"] = (lambda: analyze_acquisition(fx.quick_inputs()), None, None)
cases["D_plain"] = (
    lambda: analyze_detailed_acquisition_with_projection(fx.detailed_terms(), fx.detailed_operating()),
    None,
    None,
)


def scenario_call(kind: str, plan: BusinessPlan):  # type: ignore[no-untyped-def]
    empty = ScenarioDefinition(scenario_id="zero", name="Zero overrides")
    if kind == "quick":
        return analyze_quick_acquisition_with_scenario(fx.quick_inputs(), unit_id=fx.UNIT, scenario=empty, business_plan=plan)
    if kind == "detailed":
        return analyze_detailed_acquisition_with_scenario(
            fx.detailed_terms(), fx.detailed_operating(), unit_id=fx.UNIT, scenario=empty, business_plan=plan
        )
    roll = overridden_roll if kind == "lease_level_overrides" else {}
    args, kwargs = lease_level_args(**roll)
    return analyze_lease_level_acquisition_with_scenario(*args, **kwargs, unit_id=fx.UNIT, scenario=empty, business_plan=plan)


output: dict[str, object] = {"_has_scenario": HAS_SCENARIO}
for case, (ordinary, kind, plan) in cases.items():
    output[case] = encode(ordinary())
    if HAS_SCENARIO and kind is not None:
        output[f"{case}#scenario0"] = encode(scenario_call(kind, plan))

out_path.write_text(json.dumps(output), encoding="utf-8")
