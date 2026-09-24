"""Shared P7.2 fixtures (not a test module).

One saved Deal per operating mode, built from the P7.1 scenario fixtures, plus
helpers that read the database directly -- never through the store under test --
so persistence claims are measured, not asserted by the code that makes them.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path
from typing import Any

import _p7_1_scenario_fixtures as fx  # type: ignore[import-not-found]
from anchor.analysis import (
    analyze_detailed_acquisition_with_business_plan,
    analyze_lease_level_acquisition_with_business_plan,
    analyze_quick_acquisition_with_business_plan,
)
from anchor.analysis.scenario import ScenarioOperation, ScenarioOverride, ScenarioTarget
from anchor.business_plan import BusinessPlan
from anchor.contracts import OperatingMode
from anchor.deals import store
from anchor.deals.contracts import Deal
from anchor.deals.fingerprint import (
    fingerprint_detailed_inputs,
    fingerprint_lease_level_inputs,
    fingerprint_quick_inputs,
)

MODES = ("quick", "detailed", "lease_level")

#: The five tables schema v8 adds.
P7_2_TABLES = (
    "investments",
    "investment_units",
    "scenarios",
    "scenario_overrides",
    "variant_snapshots",
)


# =============================================================================
# Deals
# =============================================================================


def create_deal(
    mode: str, db: Path, *, business_plan: BusinessPlan = BusinessPlan(), name: str = "P7.2 deal"
) -> Deal:
    if mode == "quick":
        return store.create_deal(name, fx.quick_inputs(), business_plan=business_plan, db_path=db)
    if mode == "detailed":
        return store.create_detailed_deal(
            name, fx.detailed_terms(), fx.detailed_operating(), business_plan=business_plan, db_path=db
        )
    suites, leases = fx.rent_roll()
    return store.create_lease_level_deal(
        name,
        fx.lease_level_terms(),
        fx.lease_level_property(),
        fx.lease_level_operating(),
        fx.market(),
        tuple(suites),
        tuple(leases),
        business_plan=business_plan,
        db_path=db,
    )


def update_deal(
    deal: Deal, db: Path, *, business_plan: BusinessPlan | None = None, **terms_changes: Any
) -> Deal:
    """Save ``deal`` again with some terms (Quick: inputs) replaced and,
    optionally, a new Business Plan."""

    plan = deal.business_plan if business_plan is None else business_plan
    if deal.operating_mode is OperatingMode.QUICK:
        assert deal.inputs is not None
        return store.update_deal(
            deal.id, deal.name, dataclasses.replace(deal.inputs, **terms_changes),
            business_plan=plan, db_path=db,
        )
    assert deal.terms is not None
    terms = dataclasses.replace(deal.terms, **terms_changes)
    if deal.operating_mode is OperatingMode.DETAILED:
        assert deal.detailed_operating_inputs is not None
        return store.update_detailed_deal(
            deal.id, deal.name, terms, deal.detailed_operating_inputs, business_plan=plan, db_path=db
        )
    assert deal.property_inputs is not None and deal.operating_inputs is not None
    assert deal.market_leasing is not None and deal.suites is not None and deal.leases is not None
    return store.update_lease_level_deal(
        deal.id, deal.name, terms, deal.property_inputs, deal.operating_inputs,
        deal.market_leasing, deal.suites, deal.leases, business_plan=plan, db_path=db,
    )


def deal_fingerprint(deal: Deal) -> str:
    """The Deal's own financial fingerprint, through the existing authority."""

    if deal.operating_mode is OperatingMode.QUICK:
        assert deal.inputs is not None
        return fingerprint_quick_inputs(deal.inputs, business_plan=deal.business_plan)
    assert deal.terms is not None
    if deal.operating_mode is OperatingMode.DETAILED:
        assert deal.detailed_operating_inputs is not None
        return fingerprint_detailed_inputs(
            deal.terms, deal.detailed_operating_inputs, business_plan=deal.business_plan
        )
    assert deal.property_inputs is not None and deal.operating_inputs is not None
    assert deal.market_leasing is not None and deal.suites is not None and deal.leases is not None
    return fingerprint_lease_level_inputs(
        deal.terms, deal.property_inputs, deal.suites, deal.leases,
        market_leasing=deal.market_leasing, operating_inputs=deal.operating_inputs,
        business_plan=deal.business_plan,
    )


def analyze_deal(deal: Deal) -> Any:
    """The Deal's ordinary analysis envelope, through the D6 entry points."""

    if deal.operating_mode is OperatingMode.QUICK:
        assert deal.inputs is not None
        return analyze_quick_acquisition_with_business_plan(deal.inputs, business_plan=deal.business_plan)
    assert deal.terms is not None
    if deal.operating_mode is OperatingMode.DETAILED:
        assert deal.detailed_operating_inputs is not None
        return analyze_detailed_acquisition_with_business_plan(
            deal.terms, deal.detailed_operating_inputs, business_plan=deal.business_plan
        )
    assert deal.property_inputs is not None and deal.operating_inputs is not None
    assert deal.market_leasing is not None and deal.suites is not None and deal.leases is not None
    return analyze_lease_level_acquisition_with_business_plan(
        deal.terms, deal.property_inputs, deal.suites, deal.leases,
        market_leasing=deal.market_leasing, operating_inputs=deal.operating_inputs,
        business_plan=deal.business_plan,
    )


# =============================================================================
# Overrides
# =============================================================================


def override(unit_id: str, target: str, operation: str, value: Any) -> ScenarioOverride:
    """An override from wire tokens; a token that names no member stays raw."""

    def member(token_type: Any, token: Any) -> Any:
        try:
            return token_type(token)
        except (ValueError, TypeError):
            return token

    return ScenarioOverride(
        unit_id=unit_id,
        target=member(ScenarioTarget, target),
        operation=member(ScenarioOperation, operation),
        value=value,
    )


#: One valid, economically material override per mode.
_ECONOMIC = {
    "quick": ("exit_cap_rate", "add", 0.005),
    "detailed": ("vacancy_credit_loss_pct", "add", 0.02),
    "lease_level": ("market_rent_psf", "scale", 0.9),
}
#: A second, independent one per mode.
_SECOND = {
    "quick": ("interest_rate", "add", 0.01),
    "detailed": ("interest_rate", "add", 0.01),
    "lease_level": ("interest_rate", "add", 0.01),
}


def economic_override(mode: str, unit_id: str) -> ScenarioOverride:
    return override(unit_id, *_ECONOMIC[mode])


def second_override(mode: str, unit_id: str) -> ScenarioOverride:
    return override(unit_id, *_SECOND[mode])


# =============================================================================
# Reading the database directly
# =============================================================================


def _connect(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(db)


def table_names(db: Path) -> set[str]:
    connection = _connect(db)
    try:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()


def row_counts(db: Path) -> dict[str, int]:
    """Row counts of the five P7.2 tables. A database the P7.2 store has never
    opened has no such tables; it reports zero for each."""

    present = table_names(db)
    connection = _connect(db)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if table in present
            else 0
            for table in P7_2_TABLES
        }
    finally:
        connection.close()


EMPTY = dict.fromkeys(P7_2_TABLES, 0)


def rows(db: Path, table: str) -> list[tuple[Any, ...]]:
    connection = _connect(db)
    try:
        return connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
    finally:
        connection.close()


#: The eight Strategy tables schema v9 adds (P7.4). They are P7 structure, never
#: legacy rows, exactly like the five above.
P7_4_TABLES = (
    "strategies",
    "strategy_acquisition_overlays",
    "strategy_financing_overlays",
    "strategy_business_plan_overlays",
    "strategy_capital_plan_items",
    "strategy_owner_expense_items",
    "strategy_operating_outcomes",
    "strategy_disposition_overlays",
)


#: The five visible-Investment sidecars schema v10 adds (P7.6). P7 structure,
#: never legacy rows, exactly like the tables above.
P7_6_TABLES = (
    "investment_details",
    "investment_unit_details",
    "investment_capital_plan_items",
    "investment_owner_expense_items",
    "investment_transaction_costs",
)


#: The six Capital Structure tables schema v11 adds (P7.8B): the structure owner
#: and its positions, funding events, fees, debt terms and preferred terms. P7
#: structure, never legacy rows, exactly like the tables above.
P7_8_TABLES = (
    "capital_structures",
    "capital_positions",
    "capital_funding_events",
    "capital_position_fees",
    "capital_debt_terms",
    "capital_preferred_terms",
)


#: The eight Partnership tables schema v12 adds (P7.9 Stage 2): the Partnership
#: owner marker and its partners, benchmark shares, promote participants,
#: waterfall tiers, tier splits, hurdle conditions and catch-up terms.
P7_9_TABLES = (
    "partnerships",
    "partners",
    "partnership_benchmark_shares",
    "partnership_promote_participants",
    "waterfall_tiers",
    "waterfall_tier_splits",
    "waterfall_hurdle_conditions",
    "waterfall_catch_up_terms",
)

#: The two tables schema v13 adds (Gate AM1).
AM1_TABLES = (
    "managed_assets",
    "monthly_asset_reports",
)

#: The two classification tables schema v14 adds (Asset Types 1). Unlike the
#: tables above they hold Deal and Managed Asset metadata rather than P7
#: structure, so ``legacy_rows`` deliberately keeps them: no P7 operation may
#: change a classification.
ASSET_TYPES_1_TABLES = (
    "deal_asset_classifications",
    "managed_asset_classifications",
)

#: The sixteen valuation and Investment Memo tables schema v15 adds (P7.10
#: Stage 2): the analyst's valuation definitions and their unit instructions,
#: the Evidence References, the one mutable memo draft with its item and
#: citation tables, the immutable published versions with their frozen content,
#: evidence, valuations and dependency ledger, and the committee's separate
#: decision. P7 structure, never legacy rows, exactly like the tables above: an
#: Investment gains one only when the analyst authors it.
P7_10_TABLES = (
    "valuation_timepoints",
    "valuation_unit_instructions",
    "memo_evidence_references",
    "investment_memo_drafts",
    "memo_items",
    "memo_risk_items",
    "memo_term_items",
    "memo_draft_evidence",
    "memo_claim_evidence",
    "memo_selected_valuations",
    "investment_memo_versions",
    "memo_version_items",
    "memo_version_risk_items",
    "memo_version_term_items",
    "memo_version_evidence",
    "memo_version_valuations",
    "memo_version_claim_evidence",
    "memo_version_dependencies",
    "investment_committee_decisions",
)

#: The one table schema v16 adds (P7.10 Stage 4): the immutable report and PDF
#: stored with each published memo version, so what a committee was issued does
#: not change when the underwriting does. Like every table above, it is P7
#: structure a legacy database never holds, and a version gains a row only when
#: an analyst publishes one.
P7_10_STAGE_4_TABLES = ("memo_version_report_artifacts",)

#: The six tables schema v17 adds (Refinance & Capital Events V1 Stage 2): the
#: persisted capital events, each a child of one stored Capital Structure. A
#: legacy database never holds a row in them, and a structure gains one only
#: when an analyst authors a refinance.
REFINANCE_V1_STAGE_2_TABLES = (
    "capital_events",
    "capital_event_retirements",
    "capital_event_constraints",
    "capital_event_valuation_refs",
    "capital_event_costs",
    "capital_refinance_proceeds",
)

#: The two keys Asset Types 1 adds to every Deal and Managed Asset response.
CLASSIFICATION_KEYS = ("asset_type", "asset_subtype")


def without_unstated_classification(current: Any, recorded: Any) -> Any:
    """``current`` minus exactly the classification keys a pre-Asset-Types-1
    response could not have carried -- and only where they read ``null``.

    Every compatibility oracle replays responses a baseline tree recorded before
    classification existed. Asset Types 1 adds two keys to each Deal body, and a
    legacy record must answer them with ``null`` ("Not specified"): nothing may
    be inferred for it. So a key is removed only when (a) it is one of the two,
    (b) the recorded object at the same position lacks it, and (c) its value is
    ``None``. A legacy record that came back *classified* keeps the key and
    fails the comparison, and every other byte must still match exactly -- the
    oracle is not loosened anywhere else.
    """

    if isinstance(current, dict) and isinstance(recorded, dict):
        return {
            key: (
                without_unstated_classification(value, recorded[key]) if key in recorded else value
            )
            for key, value in current.items()
            if not (key in CLASSIFICATION_KEYS and key not in recorded and value is None)
        }
    if isinstance(current, list) and isinstance(recorded, list) and len(current) == len(recorded):
        return [
            without_unstated_classification(item, recorded_item)
            for item, recorded_item in zip(current, recorded, strict=True)
        ]
    return current


def legacy_rows(db: Path) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table that is not a P7 table, in rowid order.

    A later gate's P7 tables are excluded as each earlier gate's are: this
    compares the rows a legacy database already held, and a gate that appends
    empty tables must not read as a row that moved. Each gate's own oracle
    proves its tables arrive empty."""

    return {
        table: rows(db, table)
        for table in sorted(
            table_names(db)
            - set(P7_2_TABLES)
            - set(P7_4_TABLES)
            - set(P7_6_TABLES)
            - set(P7_8_TABLES)
            - set(P7_9_TABLES)
            - set(AM1_TABLES)
            - set(P7_10_TABLES)
            - set(P7_10_STAGE_4_TABLES)
            - set(REFINANCE_V1_STAGE_2_TABLES)
        )
        if not table.startswith("sqlite_")
    }


def execute(db: Path, sql: str, parameters: tuple[Any, ...] = ()) -> None:
    connection = _connect(db)
    try:
        connection.execute(sql, parameters)
        connection.commit()
    finally:
        connection.close()
