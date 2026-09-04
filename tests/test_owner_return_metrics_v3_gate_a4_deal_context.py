"""Owner Return Metrics V3 Gate A4 -- Deal Context persistence + AI Analyst
awareness.

Covers: Quick and Detailed Deal Context persistence (create/reopen/update/
duplicate/legacy-compatibility/migration), the deterministic engine's
complete isolation from Deal Context, and the AI Analyst layer's Gate A4
extensions (Deal Context threaded into ``AnalysisContext``/the presentation
payload, clearly labeled as user-authored, and the now-exposed Owner Return
Metrics fields). No financial formula is exercised here beyond confirming
Deal Context never reaches one.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from anchor.ai.analyst import build_analysis_context, build_detailed_analysis_context
from anchor.ai.prompts import build_system_prompt, build_user_prompt
from anchor.ai.presentation import build_presentation_payload
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.deals import Deal
from anchor.deals.store import (
    _SCHEMA_VERSION,
    create_deal,
    create_detailed_deal,
    duplicate_deal,
    get_deal,
    update_deal,
    update_detailed_deal,
)
from anchor.engine import analyze_acquisition, analyze_detailed_acquisition

QUICK_INPUTS = AcquisitionInputs(
    purchase_price=10_000_000.0,
    current_noi=600_000.0,
    occupancy=0.95,
    noi_growth=0.03,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)

DETAILED_TERMS = AcquisitionTerms(
    purchase_price=10_000_000.0,
    hold_period=5,
    exit_cap_rate=0.065,
    ltv=0.60,
    interest_rate=0.05,
    amortization=30,
    acquisition_cost_pct=0.02,
    financing_fee_pct=0.01,
    disposition_cost_pct=0.025,
    annual_capex_reserve=50_000.0,
    io_period=2,
)
DETAILED_OPERATING_INPUTS = DetailedOperatingInputs(
    gross_potential_rent=800_000.0,
    other_income=20_000.0,
    vacancy_credit_loss_pct=0.05,
    property_taxes=60_000.0,
    insurance=20_000.0,
    utilities=25_000.0,
    repairs_maintenance=20_000.0,
    other_operating_expenses=16_000.0,
    management_fee_pct=0.05,
    revenue_growth=0.03,
    expense_growth=0.03,
)

SAMPLE_DEAL_CONTEXT = (
    "Value-add multifamily acquisition. Prioritize durable cash yield over "
    "maximum IRR. Renovate approximately 60% of units over three years, "
    "refinance after NOI growth, return 30-40% of invested equity if "
    "coverage permits, and hold long term."
)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test-anchor.db"


# =============================================================================
# 1-2. Quick and Detailed deals can persist Deal Context
# =============================================================================


def test_quick_deal_persists_deal_context(db_path: Path) -> None:
    deal = create_deal("Deal", QUICK_INPUTS, deal_context=SAMPLE_DEAL_CONTEXT, db_path=db_path)

    assert deal.deal_context == SAMPLE_DEAL_CONTEXT

    reopened = get_deal(deal.id, db_path=db_path)
    assert reopened.deal_context == SAMPLE_DEAL_CONTEXT


def test_detailed_deal_persists_deal_context(db_path: Path) -> None:
    deal = create_detailed_deal(
        "Deal",
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        deal_context=SAMPLE_DEAL_CONTEXT,
        db_path=db_path,
    )

    assert deal.deal_context == SAMPLE_DEAL_CONTEXT

    reopened = get_deal(deal.id, db_path=db_path)
    assert reopened.deal_context == SAMPLE_DEAL_CONTEXT


def test_new_deal_starts_with_blank_context_by_default(db_path: Path) -> None:
    quick_deal = create_deal("Deal", QUICK_INPUTS, db_path=db_path)
    detailed_deal = create_detailed_deal(
        "Detailed Deal", DETAILED_TERMS, DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    assert quick_deal.deal_context is None
    assert detailed_deal.deal_context is None


def test_editing_deal_context_persists_on_update(db_path: Path) -> None:
    deal = create_deal("Deal", QUICK_INPUTS, db_path=db_path)
    assert deal.deal_context is None

    updated = update_deal(deal.id, "Deal", QUICK_INPUTS, deal_context="New strategy.", db_path=db_path)
    assert updated.deal_context == "New strategy."

    reopened = get_deal(deal.id, db_path=db_path)
    assert reopened.deal_context == "New strategy."


def test_editing_detailed_deal_context_persists_on_update(db_path: Path) -> None:
    deal = create_detailed_deal(
        "Deal", DETAILED_TERMS, DETAILED_OPERATING_INPUTS, db_path=db_path
    )
    assert deal.deal_context is None

    updated = update_detailed_deal(
        deal.id,
        "Deal",
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        deal_context="New Detailed strategy.",
        db_path=db_path,
    )
    assert updated.deal_context == "New Detailed strategy."


# =============================================================================
# 3. Context survives "restart" -- store.py opens a fresh sqlite3 connection
#    per call, never caching state in memory, so a later independent call
#    against the same db_path is exactly equivalent to a process restart.
# =============================================================================


def test_deal_context_survives_a_fresh_connection(db_path: Path) -> None:
    deal = create_deal("Deal", QUICK_INPUTS, deal_context=SAMPLE_DEAL_CONTEXT, db_path=db_path)

    # A brand new call against the same file, sharing no in-memory state
    # with the call above -- store.py's _connect opens/closes a connection
    # per call, so this is indistinguishable from a fresh process.
    reopened = get_deal(deal.id, db_path=db_path)

    assert reopened.deal_context == SAMPLE_DEAL_CONTEXT


# =============================================================================
# 4. Legacy deals (no deal_context column at all) still load
# =============================================================================


def _write_legacy_pre_gate_a4_database(db_path: Path) -> None:
    """A genuine schema-version-2 database (Detailed Operating Model V2.1,
    pre-Gate-A4): both ``deals`` and ``detailed_deals`` exist, neither has a
    ``deal_context`` column. Built directly via raw ``sqlite3``, never
    through the current (already-Gate-A4-aware) store module."""

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE deals (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, purchase_price REAL NOT NULL,
                current_noi REAL NOT NULL, occupancy REAL NOT NULL, noi_growth REAL NOT NULL,
                hold_period INTEGER NOT NULL, exit_cap_rate REAL NOT NULL, ltv REAL NOT NULL,
                interest_rate REAL NOT NULL, amortization INTEGER NOT NULL,
                acquisition_cost_pct REAL NOT NULL DEFAULT 0.0,
                financing_fee_pct REAL NOT NULL DEFAULT 0.0,
                disposition_cost_pct REAL NOT NULL DEFAULT 0.0,
                annual_capex_reserve REAL NOT NULL DEFAULT 0.0,
                io_period INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE detailed_deals (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, purchase_price REAL NOT NULL,
                hold_period INTEGER NOT NULL, exit_cap_rate REAL NOT NULL, ltv REAL NOT NULL,
                interest_rate REAL NOT NULL, amortization INTEGER NOT NULL,
                acquisition_cost_pct REAL NOT NULL, financing_fee_pct REAL NOT NULL,
                disposition_cost_pct REAL NOT NULL, annual_capex_reserve REAL NOT NULL,
                io_period INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE detailed_operating_inputs (
                deal_id TEXT PRIMARY KEY REFERENCES detailed_deals(id),
                gross_potential_rent REAL NOT NULL, other_income REAL NOT NULL,
                vacancy_credit_loss_pct REAL NOT NULL, property_taxes REAL NOT NULL,
                insurance REAL NOT NULL, utilities REAL NOT NULL,
                repairs_maintenance REAL NOT NULL, other_operating_expenses REAL NOT NULL,
                management_fee_pct REAL NOT NULL, revenue_growth REAL NOT NULL,
                expense_growth REAL NOT NULL
            )
            """
        )
        now = "2025-01-01T00:00:00+00:00"
        connection.execute(
            "INSERT INTO deals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-quick",
                "Legacy Quick Deal",
                10_000_000.0,
                600_000.0,
                0.95,
                0.03,
                5,
                0.065,
                0.6,
                0.05,
                30,
                0.02,
                0.01,
                0.025,
                50_000.0,
                2,
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO detailed_deals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-detailed",
                "Legacy Detailed Deal",
                10_000_000.0,
                5,
                0.065,
                0.6,
                0.05,
                30,
                0.02,
                0.01,
                0.025,
                50_000.0,
                2,
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO detailed_operating_inputs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-detailed",
                800_000.0,
                20_000.0,
                0.05,
                60_000.0,
                20_000.0,
                25_000.0,
                20_000.0,
                16_000.0,
                0.05,
                0.03,
                0.03,
            ),
        )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    finally:
        connection.close()


def test_legacy_quick_deal_without_deal_context_column_still_loads(db_path: Path) -> None:
    _write_legacy_pre_gate_a4_database(db_path)

    deal = get_deal("legacy-quick", db_path=db_path)

    assert deal.name == "Legacy Quick Deal"
    assert deal.inputs == QUICK_INPUTS
    assert deal.deal_context is None


def test_legacy_detailed_deal_without_deal_context_column_still_loads(db_path: Path) -> None:
    _write_legacy_pre_gate_a4_database(db_path)

    deal = get_deal("legacy-detailed", db_path=db_path)

    assert deal.name == "Legacy Detailed Deal"
    assert deal.terms == DETAILED_TERMS
    assert deal.detailed_operating_inputs == DETAILED_OPERATING_INPUTS
    assert deal.deal_context is None


# =============================================================================
# 14. Migration is additive and idempotent
# =============================================================================


def test_migration_from_pre_gate_a4_schema_is_additive_and_idempotent(db_path: Path) -> None:
    _write_legacy_pre_gate_a4_database(db_path)

    # First open triggers the migration.
    get_deal("legacy-quick", db_path=db_path)

    connection = sqlite3.connect(db_path)
    try:
        version_after_first_open = connection.execute("PRAGMA user_version").fetchone()[0]
        deals_columns = {row[1] for row in connection.execute("PRAGMA table_info(deals)")}
        detailed_deals_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(detailed_deals)")
        }
    finally:
        connection.close()

    assert version_after_first_open == _SCHEMA_VERSION
    assert "deal_context" in deals_columns
    assert "deal_context" in detailed_deals_columns
    # No pre-existing column was dropped -- purely additive.
    assert "purchase_price" in deals_columns
    assert "purchase_price" in detailed_deals_columns

    # Existing rows are unharmed and readable (no financial data modified).
    quick = get_deal("legacy-quick", db_path=db_path)
    detailed = get_deal("legacy-detailed", db_path=db_path)
    assert quick.inputs == QUICK_INPUTS
    assert detailed.terms == DETAILED_TERMS

    # A second open against an already-migrated database is a no-op --
    # idempotent, no error, no duplicate ALTER.
    get_deal("legacy-quick", db_path=db_path)
    connection2 = sqlite3.connect(db_path)
    try:
        version_after_second_open = connection2.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection2.close()
    assert version_after_second_open == _SCHEMA_VERSION


# =============================================================================
# 5. Duplicate preserves Deal Context
# =============================================================================


def test_duplicate_quick_deal_preserves_deal_context(db_path: Path) -> None:
    original = create_deal(
        "Deal", QUICK_INPUTS, deal_context=SAMPLE_DEAL_CONTEXT, db_path=db_path
    )

    duplicate = duplicate_deal(original.id, db_path=db_path)

    assert duplicate.id != original.id
    assert duplicate.deal_context == SAMPLE_DEAL_CONTEXT


def test_duplicate_detailed_deal_preserves_deal_context(db_path: Path) -> None:
    original = create_detailed_deal(
        "Deal",
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        deal_context=SAMPLE_DEAL_CONTEXT,
        db_path=db_path,
    )

    duplicate = duplicate_deal(original.id, db_path=db_path)

    assert duplicate.id != original.id
    assert duplicate.deal_context == SAMPLE_DEAL_CONTEXT


def test_duplicate_preserves_none_deal_context(db_path: Path) -> None:
    original = create_deal("Deal", QUICK_INPUTS, db_path=db_path)

    duplicate = duplicate_deal(original.id, db_path=db_path)

    assert duplicate.deal_context is None


# =============================================================================
# 6 / 12. Deal Context is absent from the deterministic engine, structurally
# =============================================================================


def test_deal_context_is_not_a_field_on_any_engine_input_contract() -> None:
    for contract in (AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs):
        field_names = {field for field in contract.__dataclass_fields__}
        assert "deal_context" not in field_names


def test_no_engine_or_analysis_source_file_references_deal_context() -> None:
    """Architecture guardrail: scans every ``.py`` file under
    ``anchor.engine`` and ``anchor.analysis`` for the literal identifier
    ``deal_context``. Zero occurrences proves no calculation module reads
    it, imports it, or branches on it -- not just that today's tests don't
    exercise such a path."""

    import anchor.engine as engine_package
    import anchor.analysis as analysis_package

    for package in (engine_package, analysis_package):
        package_dir = Path(package.__file__).parent
        for source_file in package_dir.rglob("*.py"):
            tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
            identifiers = {
                node.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
            } | {
                node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            } | {
                node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)
            }
            assert "deal_context" not in identifiers, (
                f"{source_file} references 'deal_context' -- the deterministic "
                "engine/analysis layers must remain completely independent of it."
            )


# =============================================================================
# 7. Analyze results are identical regardless of Deal Context
# =============================================================================


def test_quick_analyze_results_unaffected_by_deal_context(db_path: Path) -> None:
    with_context = create_deal(
        "A", QUICK_INPUTS, deal_context="Aggressive value-add play.", db_path=db_path
    )
    without_context = create_deal("B", QUICK_INPUTS, db_path=db_path)

    assert with_context.inputs == without_context.inputs == QUICK_INPUTS
    result_with = analyze_acquisition(with_context.inputs)
    result_without = analyze_acquisition(without_context.inputs)

    assert result_with == result_without


def test_detailed_analyze_results_unaffected_by_deal_context(db_path: Path) -> None:
    with_context = create_detailed_deal(
        "A",
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        deal_context="Refinance in Year 5.",
        db_path=db_path,
    )
    without_context = create_detailed_deal(
        "B", DETAILED_TERMS, DETAILED_OPERATING_INPUTS, db_path=db_path
    )

    result_with = analyze_detailed_acquisition(with_context.terms, with_context.detailed_operating_inputs)
    result_without = analyze_detailed_acquisition(
        without_context.terms, without_context.detailed_operating_inputs
    )

    assert result_with == result_without


# =============================================================================
# 8-9. AI context receives Deal Context; empty context preserves existing
#      behavior
# =============================================================================


def test_quick_analysis_context_carries_deal_context() -> None:
    context = build_analysis_context(
        QUICK_INPUTS,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
        deal_context=SAMPLE_DEAL_CONTEXT,
    )

    assert context.deal_context == SAMPLE_DEAL_CONTEXT


def test_detailed_analysis_context_carries_deal_context() -> None:
    context = build_detailed_analysis_context(
        DETAILED_TERMS,
        DETAILED_OPERATING_INPUTS,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
        deal_context=SAMPLE_DEAL_CONTEXT,
    )

    assert context.deal_context == SAMPLE_DEAL_CONTEXT


def test_empty_deal_context_produces_no_payload_key() -> None:
    context_none = build_analysis_context(
        QUICK_INPUTS,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
        deal_context=None,
    )
    context_blank = build_analysis_context(
        QUICK_INPUTS,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
        deal_context="   ",
    )

    payload_none = build_presentation_payload(context_none)
    payload_blank = build_presentation_payload(context_blank)

    assert "deal_context" not in payload_none
    assert "deal_context" not in payload_blank


def test_non_empty_deal_context_produces_a_top_level_payload_key() -> None:
    context = build_analysis_context(
        QUICK_INPUTS,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
        deal_context=SAMPLE_DEAL_CONTEXT,
    )

    payload = build_presentation_payload(context)

    assert payload["deal_context"] == SAMPLE_DEAL_CONTEXT
    # Structurally distinct from every deterministic section -- never
    # merged into base_inputs/base_results.
    assert "deal_context" not in payload["base_results"]


# =============================================================================
# 10. Owner Return Metrics reach the AI context (Gate A2's exclusion lifted)
# =============================================================================


def test_owner_return_metrics_are_presented_to_the_ai(db_path: Path) -> None:
    context = build_analysis_context(
        QUICK_INPUTS,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
    )
    payload = build_presentation_payload(context)

    for field in (
        "levered_cash_on_cash_by_year",
        "unlevered_cash_yield_by_year",
        "cumulative_operating_distributions_by_year",
        "year_1_debt_yield",
    ):
        assert field in payload["base_results"]
        assert payload["base_results"][field] not in (None, "")


# =============================================================================
# 11. Context is clearly labeled as user-authored, not verified evidence
# =============================================================================


def test_system_prompt_labels_deal_context_as_user_authored_unverified() -> None:
    prompt = build_system_prompt().lower()

    assert "deal context rules" in prompt
    assert "user-authored" in prompt
    assert "not verified market evidence" in prompt or "not verified" in prompt
    assert "never assume a refinance occurred" in prompt
    assert "never calculate or estimate" in prompt and "refinance proceeds" in prompt


def test_user_prompt_explains_deal_context_when_present() -> None:
    context = build_analysis_context(
        QUICK_INPUTS,
        target_levered_irr=0.10,
        target_equity_multiple=1.50,
        target_headline_dscr=1.20,
        deal_context=SAMPLE_DEAL_CONTEXT,
    )

    prompt = build_user_prompt(context)

    assert "deal_context" in prompt
    assert "user-authored" in prompt.lower()


# =============================================================================
# 13. AI architecture still forbids calculations (Deal Context introduces no
#     math import or independent calculation anywhere in anchor.ai)
# =============================================================================


def test_ai_package_still_imports_no_math_module() -> None:
    """Mirrors test_ai_architecture.py's existing guardrail -- re-asserted
    here because Gate A4 touched every file in ``anchor.ai`` and this is
    the cheapest direct proof none of those edits introduced a
    calculation."""

    import anchor.ai as ai_package

    package_dir = Path(ai_package.__file__).parent
    for source_file in package_dir.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.append(node.module)
        assert "math" not in imported_names, f"{source_file} imports math"
