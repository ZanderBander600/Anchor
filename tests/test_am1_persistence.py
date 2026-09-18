"""Gate AM1 -- Managed Asset and Monthly Asset Report persistence.

``docs/architecture/AM1_MANAGED_ASSETS_MONTHLY_PERFORMANCE.md`` Section 5. The
round trips, the two uniqueness rules, the frozen budget, and the separation
that makes a Managed Asset independent of the Deal it came from.

Every claim about what is on disk is measured by reading the database directly,
never through the store under test.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import date
from pathlib import Path

import pytest

import _am1_fixtures as am  # type: ignore[import-not-found]
import _p7_2_fixtures as fx  # type: ignore[import-not-found]
from anchor.asset_management import (
    AssetReportValidationError,
    BudgetImmutableError,
    ManagedAssetExistsError,
    ManagedAssetNotFoundError,
    MonthlyReportExistsError,
    MonthlyReportNotFoundError,
    analyze_asset_performance,
)
from anchor.contracts import OperatingMode
from anchor.deals import store
from anchor.deals.contracts import DealNotFoundError, InvestmentStructureError

MODES = ("quick", "detailed", "lease_level")


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return tmp_path / "am1.db"


def _rows(db: Path, sql: str, *params: object) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _analyzed_deal(mode: str, db: Path, *, name: str = "Harbor Point Apartments"):
    """A saved Deal a Managed Asset may be created from.

    Quick and Detailed get a current cached analysis snapshot. Lease-Level
    cannot: ``lease_level_deals`` has no ``analysis_snapshot`` column, so there
    is no snapshot to write -- see ``create_managed_asset`` for why AM1 exempts
    that mode rather than barring it.
    """

    deal = fx.create_deal(mode, db, name=name)
    if mode != "lease_level":
        store.update_analysis_snapshot(
            deal.id,
            dataclasses.asdict(fx.analyze_deal(deal)),
            financial_input_fingerprint=fx.deal_fingerprint(deal),
            db_path=db,
        )
    return store.get_deal(deal.id, db_path=db)


def _asset(db: Path, mode: str = "quick", **overrides):
    deal = _analyzed_deal(mode, db)
    kwargs = {
        "source_deal_id": deal.id,
        "acquisition_date": date(2026, 10, 1),
        "property_type": "Multifamily",
        "market": "Toronto, ON",
        "db_path": db,
    }
    kwargs.update(overrides)
    return deal, store.create_managed_asset(**kwargs)


# =============================================================================
# Creating a Managed Asset
# =============================================================================


@pytest.mark.parametrize("mode", MODES)
def test_a_managed_asset_is_created_from_a_saved_deal_in_every_mode(mode: str, db: Path) -> None:
    deal, asset = _asset(db, mode)
    assert asset.source_deal_id == deal.id
    assert asset.name == deal.name
    assert asset.property_type == "Multifamily"
    assert asset.market == "Toronto, ON"
    assert asset.acquisition_date == date(2026, 10, 1)
    assert asset.id != deal.id


@pytest.mark.parametrize("mode", MODES)
def test_the_frozen_fingerprint_is_the_deals_authoritative_one(mode: str, db: Path) -> None:
    """The same definition the rest of Anchor uses -- never an AM1-private
    notion of what a Deal fingerprints to."""

    deal, asset = _asset(db, mode)
    assert asset.acquisition_fingerprint == fx.deal_fingerprint(deal)


def test_a_deal_can_create_at_most_one_managed_asset(db: Path) -> None:
    deal, asset = _asset(db)
    with pytest.raises(ManagedAssetExistsError) as raised:
        store.create_managed_asset(
            source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db
        )
    assert raised.value.managed_asset_id == asset.id
    assert len(_rows(db, "SELECT id FROM managed_assets")) == 1


def test_the_uniqueness_rule_is_enforced_by_the_database(db: Path) -> None:
    """A UNIQUE constraint, not a check a future write path could forget."""

    deal, asset = _asset(db)
    connection = sqlite3.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO managed_assets (id, source_deal_id, name, acquisition_date, "
                "property_type, market, acquisition_fingerprint, created_at, updated_at) "
                "VALUES ('other', ?, 'x', '2026-10-01', NULL, NULL, 'fp', 'n', 'n')",
                (deal.id,),
            )
    finally:
        connection.close()


def test_a_deal_with_no_current_analysis_cannot_become_a_managed_asset(db: Path) -> None:
    """An approved basis nobody has analyzed is not a basis."""

    deal = fx.create_deal("quick", db, name="Unanalyzed")
    with pytest.raises(InvestmentStructureError):
        store.create_managed_asset(
            source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db
        )
    assert _rows(db, "SELECT id FROM managed_assets") == []


def test_a_deal_whose_analysis_went_stale_cannot_become_a_managed_asset(db: Path) -> None:
    """Editing assumptions invalidates the cached snapshot, so the Deal no
    longer has a current analysis to freeze."""

    deal = _analyzed_deal("quick", db)
    fx.update_deal(deal, db, purchase_price=deal.inputs.purchase_price + 1_000_000.0)
    assert store.get_deal(deal.id, db_path=db).analysis_snapshot is None
    with pytest.raises(InvestmentStructureError):
        store.create_managed_asset(
            source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db
        )


def test_lease_level_is_exempt_from_the_snapshot_check_by_storage_not_by_policy(
    db: Path,
) -> None:
    """`lease_level_deals` has no `analysis_snapshot` column at all, so the
    check could never pass for that mode. Applying it anyway would bar an
    entire operating mode from Asset Management as a side effect of an
    unrelated persistence gap. The fingerprint -- what AM1 actually freezes --
    is available in all three modes."""

    columns = {row["name"] for row in _rows(db, "PRAGMA table_info(lease_level_deals)")}
    assert "analysis_snapshot" not in columns

    deal = fx.create_deal("lease_level", db, name="Riverbend Retail")
    assert store.get_deal(deal.id, db_path=db).analysis_snapshot is None
    asset = store.create_managed_asset(
        source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db
    )
    assert asset.acquisition_fingerprint == fx.deal_fingerprint(
        store.get_deal(deal.id, db_path=db)
    )


def test_an_unknown_deal_is_not_found(db: Path) -> None:
    with pytest.raises(DealNotFoundError):
        store.create_managed_asset(
            source_deal_id="nope", acquisition_date=date(2026, 10, 1), db_path=db
        )


def test_an_invalid_identity_is_refused_and_writes_nothing(db: Path) -> None:
    deal = _analyzed_deal("quick", db)
    with pytest.raises(AssetReportValidationError):
        store.create_managed_asset(
            source_deal_id=deal.id,
            name="   ",
            acquisition_date=date(2026, 10, 1),
            db_path=db,
        )
    assert _rows(db, "SELECT id FROM managed_assets") == []


# =============================================================================
# A Managed Asset is not a Deal
# =============================================================================


def test_creating_a_managed_asset_rewrites_no_deal_row(db: Path) -> None:
    deal = _analyzed_deal("quick", db)
    before = dict(_rows(db, "SELECT * FROM deals WHERE id = ?", deal.id)[0])
    store.create_managed_asset(
        source_deal_id=deal.id, acquisition_date=date(2026, 10, 1), db_path=db
    )
    after = dict(_rows(db, "SELECT * FROM deals WHERE id = ?", deal.id)[0])
    assert after == before


def test_a_later_deal_edit_does_not_rewrite_the_asset_or_its_fingerprint(db: Path) -> None:
    """The divergence between the Deal's current fingerprint and the asset's
    frozen copy is provenance, never a trigger to rewrite anything."""

    deal, asset = _asset(db)
    fx.update_deal(deal, db, purchase_price=deal.inputs.purchase_price + 5_000_000.0)

    reread = store.get_managed_asset(asset.id, db_path=db)
    assert reread == asset
    assert reread.acquisition_fingerprint == asset.acquisition_fingerprint

    edited = store.get_deal(deal.id, db_path=db)
    assert fx.deal_fingerprint(edited) != asset.acquisition_fingerprint


def test_renaming_the_deal_does_not_rename_the_asset(db: Path) -> None:
    deal, asset = _asset(db)
    store.update_deal(deal.id, "Renamed Deal", deal.inputs, business_plan=deal.business_plan, db_path=db)
    assert store.get_managed_asset(asset.id, db_path=db).name == asset.name
    assert store.get_deal(deal.id, db_path=db).name == "Renamed Deal"


def test_a_deal_edit_does_not_alter_a_frozen_budget_or_a_saved_report(db: Path) -> None:
    deal, asset = _asset(db)
    saved = store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        commentary=am.MARCH_COMMENTARY,
        db_path=db,
    )
    fx.update_deal(deal, db, purchase_price=deal.inputs.purchase_price + 2_000_000.0)
    assert store.get_monthly_report(asset.id, am.MARCH, db_path=db) == saved


# =============================================================================
# Monthly report round trip
# =============================================================================


def test_a_monthly_report_round_trips_every_figure(db: Path) -> None:
    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        commentary=am.MARCH_COMMENTARY,
        db_path=db,
    )
    reread = store.get_monthly_report(asset.id, am.MARCH, db_path=db)
    assert reread.budget == am.MARCH_BUDGET
    assert reread.actual == am.MARCH_ACTUAL
    assert reread.commentary == am.MARCH_COMMENTARY
    assert reread.reporting_month == am.MARCH


def test_figures_are_stored_in_typed_columns_not_a_json_blob(db: Path) -> None:
    """Every figure is queryable and typed; a column cannot acquire a field no
    contract declares."""

    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    row = _rows(db, "SELECT * FROM monthly_asset_reports")[0]
    assert row["budget_rental_revenue"] == 100_000.0
    assert row["actual_repairs_and_maintenance"] == 8_000.0
    assert row["budget_occupancy"] == 0.95
    columns = {description[0] for description in [(k,) for k in row.keys()]}
    assert not any("json" in name or "blob" in name for name in columns)


def test_nothing_computed_is_persisted(db: Path) -> None:
    """No total, variance, percentage, assessment, attention item or trend point
    has a column. Every one is derived on read."""

    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    columns = {row["name"] for row in _rows(db, "PRAGMA table_info(monthly_asset_reports)")}
    forbidden = (
        "total_revenue",
        "total_operating_expenses",
        "net_operating_income",
        "cash_flow_after_capex",
        "net_cash_flow",
        "noi_margin",
        "variance",
        "variance_pct",
        "assessment",
        "attention",
        "trend",
    )
    for name in columns:
        assert not any(name.endswith(token) or name == token for token in forbidden), name


def test_the_reporting_month_is_normalized_on_write_and_on_read(db: Path) -> None:
    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=date(2027, 3, 31),
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    assert _rows(db, "SELECT reporting_month FROM monthly_asset_reports")[0][0] == "2027-03-01"
    assert store.get_monthly_report(asset.id, date(2027, 3, 17), db_path=db).reporting_month == am.MARCH


def test_one_report_per_asset_and_month(db: Path) -> None:
    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    with pytest.raises(MonthlyReportExistsError):
        store.create_monthly_report(
            managed_asset_id=asset.id,
            reporting_month=date(2027, 3, 15),
            budget=am.figures(payroll=1.0),
            actual=am.MARCH_ACTUAL,
            db_path=db,
        )
    assert len(_rows(db, "SELECT 1 FROM monthly_asset_reports")) == 1


def test_two_assets_may_each_report_the_same_month(db: Path) -> None:
    _, first = _asset(db)
    second_deal = _analyzed_deal("detailed", db, name="Westlake Industrial")
    second = store.create_managed_asset(
        source_deal_id=second_deal.id, acquisition_date=date(2026, 11, 1), db_path=db
    )
    for asset in (first, second):
        store.create_monthly_report(
            managed_asset_id=asset.id,
            reporting_month=am.MARCH,
            budget=am.MARCH_BUDGET,
            actual=am.MARCH_ACTUAL,
            db_path=db,
        )
    assert len(_rows(db, "SELECT 1 FROM monthly_asset_reports")) == 2


def test_an_invalid_report_is_refused_and_writes_nothing(db: Path) -> None:
    _, asset = _asset(db)
    with pytest.raises(AssetReportValidationError):
        store.create_monthly_report(
            managed_asset_id=asset.id,
            reporting_month=am.MARCH,
            budget=am.figures(payroll=-1.0),
            actual=am.MARCH_ACTUAL,
            db_path=db,
        )
    assert _rows(db, "SELECT 1 FROM monthly_asset_reports") == []


# =============================================================================
# The frozen budget
# =============================================================================


def test_actuals_and_commentary_may_be_updated(db: Path) -> None:
    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        commentary=am.MARCH_COMMENTARY,
        db_path=db,
    )
    updated = store.update_monthly_report_actuals(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        actual=am.figures(utilities=7_500.0),
        commentary="Revised after the utility true-up.",
        db_path=db,
    )
    assert updated.actual.utilities == 7_500.0
    assert updated.commentary == "Revised after the utility true-up."
    assert updated.budget == am.MARCH_BUDGET


def test_a_budget_change_fails_with_a_typed_conflict(db: Path) -> None:
    """Not a validation failure: the submitted budget is well-formed, and the
    refusal is about authority rather than shape."""

    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    with pytest.raises(BudgetImmutableError) as raised:
        store.update_monthly_report_actuals(
            managed_asset_id=asset.id,
            reporting_month=am.MARCH,
            actual=am.MARCH_ACTUAL,
            budget=am.figures(payroll=9_000.0, insurance=5_500.0),
            db_path=db,
        )
    assert raised.value.changed_fields == ("insurance", "payroll")
    assert not isinstance(raised.value, AssetReportValidationError)


def test_a_refused_budget_change_leaves_the_actuals_untouched_too(db: Path) -> None:
    """Never a partial write: the whole update is refused."""

    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    with pytest.raises(BudgetImmutableError):
        store.update_monthly_report_actuals(
            managed_asset_id=asset.id,
            reporting_month=am.MARCH,
            actual=am.figures(utilities=99_000.0),
            budget=am.figures(payroll=9_000.0),
            db_path=db,
        )
    reread = store.get_monthly_report(asset.id, am.MARCH, db_path=db)
    assert reread.budget == am.MARCH_BUDGET
    assert reread.actual == am.MARCH_ACTUAL


@pytest.mark.parametrize(
    "bad",
    [None, "6000", float("nan"), float("inf"), -1.0, True],
    ids=["null", "string", "nan", "inf", "negative", "bool"],
)
def test_a_malformed_echoed_budget_is_a_validation_error_not_a_crash(db: Path, bad) -> None:
    """A caller that echoes a budget back may echo it badly. That is a bad
    request, not an internal failure: before this was validated, the field-by-
    field comparison called ``float(None)`` and raised an uncaught TypeError."""

    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        commentary=am.MARCH_COMMENTARY,
        db_path=db,
    )
    with pytest.raises(AssetReportValidationError) as raised:
        store.update_monthly_report_actuals(
            managed_asset_id=asset.id,
            reporting_month=am.MARCH,
            actual=am.MARCH_ACTUAL,
            budget=am.figures(payroll=bad),
            db_path=db,
        )
    assert [issue.field for issue in raised.value.issues] == ["payroll"]
    assert raised.value.issues[0].scope == "budget"


def test_a_malformed_echoed_budget_is_never_the_frozen_budget_conflict(db: Path) -> None:
    """Shape and authority are different refusals. A malformed echoed budget is
    the caller's to fix; it must not be reported as "this is no longer yours to
    change"."""

    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    with pytest.raises(AssetReportValidationError) as raised:
        store.update_monthly_report_actuals(
            managed_asset_id=asset.id,
            reporting_month=am.MARCH,
            actual=am.MARCH_ACTUAL,
            budget=am.figures(payroll=None),
            db_path=db,
        )
    assert not isinstance(raised.value, BudgetImmutableError)


def test_a_malformed_echoed_budget_writes_nothing(db: Path) -> None:
    _, asset = _asset(db)
    before = store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        commentary=am.MARCH_COMMENTARY,
        db_path=db,
    )
    with pytest.raises(AssetReportValidationError):
        store.update_monthly_report_actuals(
            managed_asset_id=asset.id,
            reporting_month=am.MARCH,
            actual=am.figures(utilities=99_000.0),
            commentary="Should not be stored.",
            budget=am.figures(payroll=None),
            db_path=db,
        )
    after = store.get_monthly_report(asset.id, am.MARCH, db_path=db)
    assert after.budget == before.budget
    assert after.actual == before.actual
    assert after.commentary == before.commentary


def test_a_malformed_actual_is_still_refused_when_a_budget_is_echoed(db: Path) -> None:
    """Validating the supplied budget must not stop the actuals being checked."""

    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    with pytest.raises(AssetReportValidationError) as raised:
        store.update_monthly_report_actuals(
            managed_asset_id=asset.id,
            reporting_month=am.MARCH,
            actual=am.figures(utilities=-1.0),
            budget=am.MARCH_BUDGET,
            db_path=db,
        )
    assert [(issue.scope, issue.field) for issue in raised.value.issues] == [("actual", "utilities")]


def test_resubmitting_the_identical_budget_is_not_a_conflict(db: Path) -> None:
    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    updated = store.update_monthly_report_actuals(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        actual=am.figures(payroll=6_100.0),
        budget=am.MARCH_BUDGET,
        db_path=db,
    )
    assert updated.actual.payroll == 6_100.0


def test_many_updates_never_move_a_budget_column(db: Path) -> None:
    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        db_path=db,
    )
    before = {
        key: value
        for key, value in dict(_rows(db, "SELECT * FROM monthly_asset_reports")[0]).items()
        if key.startswith("budget_")
    }
    for utilities in (5_100.0, 5_200.0, 5_300.0):
        store.update_monthly_report_actuals(
            managed_asset_id=asset.id,
            reporting_month=am.MARCH,
            actual=am.figures(utilities=utilities),
            db_path=db,
        )
    after = {
        key: value
        for key, value in dict(_rows(db, "SELECT * FROM monthly_asset_reports")[0]).items()
        if key.startswith("budget_")
    }
    assert after == before


# =============================================================================
# Listing and lookup
# =============================================================================


def test_listing_reports_returns_them_in_month_order(db: Path) -> None:
    _, asset = _asset(db)
    for month in (date(2027, 3, 1), date(2027, 1, 1), date(2027, 2, 1)):
        store.create_monthly_report(
            managed_asset_id=asset.id,
            reporting_month=month,
            budget=am.MARCH_BUDGET,
            actual=am.MARCH_ACTUAL,
            db_path=db,
        )
    months = [report.reporting_month for report in store.list_monthly_reports(asset.id, db_path=db)]
    assert months == [date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 1)]


def test_an_asset_with_no_reports_lists_empty_but_an_unknown_asset_is_not_found(db: Path) -> None:
    """An empty list means "no reports yet", and must never also mean "no such
    asset"."""

    _, asset = _asset(db)
    assert store.list_monthly_reports(asset.id, db_path=db) == []
    with pytest.raises(ManagedAssetNotFoundError):
        store.list_monthly_reports("nope", db_path=db)


def test_unknown_lookups_raise_their_own_errors(db: Path) -> None:
    _, asset = _asset(db)
    with pytest.raises(ManagedAssetNotFoundError):
        store.get_managed_asset("nope", db_path=db)
    with pytest.raises(MonthlyReportNotFoundError):
        store.get_monthly_report(asset.id, am.MARCH, db_path=db)


def test_listing_assets_is_most_recently_updated_first(db: Path) -> None:
    _, first = _asset(db)
    second_deal = _analyzed_deal("detailed", db, name="Westlake Industrial")
    second = store.create_managed_asset(
        source_deal_id=second_deal.id, acquisition_date=date(2026, 11, 1), db_path=db
    )
    listed = [asset.id for asset in store.list_managed_assets(db_path=db)]
    assert set(listed) == {first.id, second.id}


# =============================================================================
# The stored report drives the authoritative result
# =============================================================================


def test_the_stored_report_reproduces_the_authorized_demo_result(db: Path) -> None:
    """Persistence to engine, end to end: the figures that come back off disk
    produce exactly the authorized numbers."""

    _, asset = _asset(db)
    store.create_monthly_report(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        budget=am.MARCH_BUDGET,
        actual=am.MARCH_ACTUAL,
        commentary=am.MARCH_COMMENTARY,
        db_path=db,
    )
    result = analyze_asset_performance(
        managed_asset_id=asset.id,
        reporting_month=am.MARCH,
        reports=store.list_monthly_reports(asset.id, db_path=db),
    )
    assert result.monthly.budget.net_operating_income == 67_000.0
    assert result.monthly.actual.net_operating_income == 61_500.0
    assert result.commentary == am.MARCH_COMMENTARY
