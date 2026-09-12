"""Phase 6 Gate D6.5 -- shared fixtures (not a test module).

One material Business Plan and one deal per operating mode. The deals are the
D6.2 engine fixtures, so every D6.5 oracle compares against the same deals the
engine gates already proved.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder

from anchor.analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.business_plan import (
    BusinessPlan,
    CapitalItemCategory,
    CapitalPlanItem,
    OwnerExpenseCategory,
    OwnerExpenseItem,
)
from anchor.deals import store as deals_store
from anchor.deals.contracts import Deal
from anchor.deals.fingerprint import (
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)
from anchor.engine.contracts import AcquisitionResults

from test_d6_2_owner_cash_flow_engine import (  # type: ignore[import-not-found]
    DETAILED_OPERATING,
    DETAILED_TERMS,
    HOLD,
    LL_LEASES,
    LL_MARKET,
    LL_OPERATING,
    LL_PROPERTY,
    LL_SUITES,
    LL_TERMS,
    QUICK,
)

MODES = ("quick", "detailed", "lease_level")

#: The input fingerprints the pre-D6.5 tree (93636ee) computed for the three
#: D6.2 fixture deals -- captured before any D6.5 source changed. An empty
#: Business Plan must keep every one of them (decision D11).
PRE_D6_5_DIGESTS = {
    "quick": "4c2331de436c6933834b2b07225fe96c8535b334c89faafe44980eff4a4b895c",
    "detailed": "26ccc4e315b5c742be8757f8f684e3c2105446c39087a43478f8e78aa703f881",
    "lease_level": "cccf4d09b0f29d5cc936af2aa2bd81cc32f35f1c39da0ad354c9b26c3f188081",
}

#: Closing Project Capital ($250k), Year 2 Project Capital ($1M), post-hold
#: capital, an open-ended Owner Expense ($50k/yr) and one that runs past the
#: hold -- declared out of ID order in both collections, so order preservation
#: is visible, with every category distinct.
MATERIAL = BusinessPlan(
    capital_items=(
        CapitalPlanItem(
            item_id="cap-C",
            description="Roof and HVAC replacement",
            category=CapitalItemCategory.BUILDING_SYSTEMS,
            month=18,
            amount=1_000_000.0,
        ),
        CapitalPlanItem(
            item_id="cap-A",
            description="Lobby renovation at closing",
            category=CapitalItemCategory.VALUE_ADD_RENOVATION,
            month=0,
            amount=250_000.0,
        ),
        CapitalPlanItem(
            item_id="cap-B",
            description="Facade work after the sale",
            category=CapitalItemCategory.EXTERIOR_COMMON_AREA,
            month=12 * HOLD + 6,
            amount=300_000.0,
        ),
    ),
    owner_expense_items=(
        OwnerExpenseItem(
            item_id="oe-Z",
            description="Asset management fee",
            category=OwnerExpenseCategory.ASSET_MANAGEMENT,
            annual_amount=50_000.0,
            first_year=1,
            last_year=None,
        ),
        OwnerExpenseItem(
            item_id="oe-Y",
            description="Partnership legal and audit",
            category=OwnerExpenseCategory.LEGAL_PARTNERSHIP,
            annual_amount=25_000.0,
            first_year=4,
            last_year=8,
        ),
    ),
)


def reversed_plan(business_plan: BusinessPlan) -> BusinessPlan:
    """The same items with both collections in reverse order."""

    return BusinessPlan(
        capital_items=tuple(reversed(business_plan.capital_items)),
        owner_expense_items=tuple(reversed(business_plan.owner_expense_items)),
    )


def edit_item(
    business_plan: BusinessPlan, collection: str, index: int, **changes: Any
) -> BusinessPlan:
    """``business_plan`` with one item's fields replaced."""

    items = list(getattr(business_plan, collection))
    items[index] = dataclasses.replace(items[index], **changes)
    return dataclasses.replace(business_plan, **{collection: tuple(items)})


def wire(business_plan: BusinessPlan) -> dict[str, Any]:
    """The plan as JSON -- the shape a saved deal serialises it to."""

    return jsonable_encoder(business_plan)


# =============================================================================
# Requests
# =============================================================================

LEASE_LEVEL_WIRE_INPUTS: dict[str, Any] = {
    "property_inputs": jsonable_encoder(LL_PROPERTY),
    "operating_inputs": jsonable_encoder(LL_OPERATING),
    "market_leasing": jsonable_encoder(LL_MARKET),
    "suites": jsonable_encoder(LL_SUITES),
    "leases": jsonable_encoder(LL_LEASES),
}


def _mode_body(mode: str, *, flat_quick: bool) -> dict[str, Any]:
    if mode == "quick":
        inputs = dataclasses.asdict(QUICK)
        return inputs if flat_quick else {"operating_mode": "quick", "inputs": inputs}
    if mode == "detailed":
        return {
            "operating_mode": "detailed",
            "terms": dataclasses.asdict(DETAILED_TERMS),
            "detailed_operating_inputs": dataclasses.asdict(DETAILED_OPERATING),
        }
    return {
        "operating_mode": "lease_level",
        "terms": dataclasses.asdict(LL_TERMS),
        **LEASE_LEVEL_WIRE_INPUTS,
    }


def analysis_request(mode: str, business_plan: BusinessPlan | None = None) -> dict[str, Any]:
    """A ``POST /analyze`` body. Quick's is the flat inputs object."""

    body = _mode_body(mode, flat_quick=True)
    if business_plan is not None:
        body["business_plan"] = wire(business_plan)
    return body


def deal_request(
    mode: str, business_plan: BusinessPlan | None = None, **extra: Any
) -> dict[str, Any]:
    """A body for every other endpoint: Quick nests its inputs under
    ``inputs``."""

    body = {**_mode_body(mode, flat_quick=False), **extra}
    if business_plan is not None:
        body["business_plan"] = wire(business_plan)
    return body


# =============================================================================
# Direct analysis
# =============================================================================


def analysis_envelope(mode: str, business_plan: BusinessPlan) -> Any:
    """What ``POST /analyze`` returns for the fixture deal, computed directly."""

    if mode == "quick":
        return analyze_quick_acquisition_with_business_plan(QUICK, business_plan=business_plan)
    if mode == "detailed":
        return analyze_detailed_acquisition_with_business_plan(
            DETAILED_TERMS, DETAILED_OPERATING, business_plan=business_plan
        )
    return analyze_lease_level_acquisition_with_business_plan(
        LL_TERMS,
        LL_PROPERTY,
        LL_SUITES,
        LL_LEASES,
        market_leasing=LL_MARKET,
        operating_inputs=LL_OPERATING,
        business_plan=business_plan,
    )


def analyze(mode: str, business_plan: BusinessPlan) -> AcquisitionResults:
    envelope = analysis_envelope(mode, business_plan)
    return envelope if mode == "quick" else envelope.results


def analysis_snapshot_payload(mode: str, business_plan: BusinessPlan) -> dict[str, Any]:
    """The analysis snapshot a Quick or Detailed deal stores."""

    return dataclasses.asdict(analysis_envelope(mode, business_plan))


def analyze_deal(deal: Deal) -> AcquisitionResults:
    """Re-underwrite a loaded deal from nothing but its own stored state."""

    if deal.inputs is not None:
        return analyze_quick_acquisition_with_business_plan(
            deal.inputs, business_plan=deal.business_plan
        )
    assert deal.terms is not None
    if deal.detailed_operating_inputs is not None:
        return analyze_detailed_acquisition_with_business_plan(
            deal.terms, deal.detailed_operating_inputs, business_plan=deal.business_plan
        ).results
    assert deal.property_inputs is not None and deal.operating_inputs is not None
    assert deal.market_leasing is not None
    assert deal.suites is not None and deal.leases is not None
    return analyze_lease_level_acquisition_with_business_plan(
        deal.terms,
        deal.property_inputs,
        deal.suites,
        deal.leases,
        market_leasing=deal.market_leasing,
        operating_inputs=deal.operating_inputs,
        business_plan=deal.business_plan,
    ).results


def fingerprint_with(module: Any, mode: str, business_plan: BusinessPlan | None) -> str:
    """The fixture deal's input fingerprint through ``module`` (the real
    fingerprint module, or a probe of it). ``None`` omits the argument, to
    exercise the compatibility default."""

    plan = {} if business_plan is None else {"business_plan": business_plan}
    if mode == "quick":
        return module.fingerprint_quick_inputs(QUICK, **plan)
    if mode == "detailed":
        return module.fingerprint_detailed_inputs(DETAILED_TERMS, DETAILED_OPERATING, **plan)
    return module.fingerprint_lease_level_inputs(
        LL_TERMS,
        LL_PROPERTY,
        LL_SUITES,
        LL_LEASES,
        market_leasing=LL_MARKET,
        operating_inputs=LL_OPERATING,
        **plan,
    )


def input_fingerprint(mode: str, business_plan: BusinessPlan) -> str:
    if mode == "quick":
        return fingerprint_quick_inputs(QUICK, business_plan=business_plan)
    if mode == "detailed":
        return fingerprint_detailed_inputs(
            DETAILED_TERMS, DETAILED_OPERATING, business_plan=business_plan
        )
    return fingerprint_lease_level_inputs(
        LL_TERMS,
        LL_PROPERTY,
        LL_SUITES,
        LL_LEASES,
        market_leasing=LL_MARKET,
        operating_inputs=LL_OPERATING,
        business_plan=business_plan,
    )


# =============================================================================
# Persistence
# =============================================================================


def create(mode: str, db: Path, *, business_plan: BusinessPlan, name: str = "D6.5 deal") -> Deal:
    if mode == "quick":
        return deals_store.create_deal(name, QUICK, business_plan=business_plan, db_path=db)
    if mode == "detailed":
        return deals_store.create_detailed_deal(
            name, DETAILED_TERMS, DETAILED_OPERATING, business_plan=business_plan, db_path=db
        )
    return deals_store.create_lease_level_deal(
        name,
        LL_TERMS,
        LL_PROPERTY,
        LL_OPERATING,
        LL_MARKET,
        LL_SUITES,
        LL_LEASES,
        business_plan=business_plan,
        db_path=db,
    )


def update(
    mode: str,
    deal_id: str,
    db: Path,
    *,
    business_plan: BusinessPlan,
    name: str = "D6.5 deal",
    purchase_price: float | None = None,
) -> Deal:
    """Save ``deal_id`` with the fixture inputs (optionally a new purchase
    price) and ``business_plan``."""

    if mode == "quick":
        inputs = QUICK if purchase_price is None else dataclasses.replace(
            QUICK, purchase_price=purchase_price
        )
        return deals_store.update_deal(
            deal_id, name, inputs, business_plan=business_plan, db_path=db
        )
    base_terms = DETAILED_TERMS if mode == "detailed" else LL_TERMS
    terms = base_terms if purchase_price is None else dataclasses.replace(
        base_terms, purchase_price=purchase_price
    )
    if mode == "detailed":
        return deals_store.update_detailed_deal(
            deal_id, name, terms, DETAILED_OPERATING, business_plan=business_plan, db_path=db
        )
    return deals_store.update_lease_level_deal(
        deal_id,
        name,
        terms,
        LL_PROPERTY,
        LL_OPERATING,
        LL_MARKET,
        LL_SUITES,
        LL_LEASES,
        business_plan=business_plan,
        db_path=db,
    )


def plan_rows(db: Path, deal_id: str) -> tuple[int, int]:
    """How many capital and owner-expense rows the database holds for
    ``deal_id`` -- read directly, never through the store."""

    connection = sqlite3.connect(db)
    try:
        return tuple(  # type: ignore[return-value]
            connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE deal_id = ?", (deal_id,)
            ).fetchone()[0]
            for table in ("deal_capital_plan_items", "deal_owner_expense_items")
        )
    finally:
        connection.close()
