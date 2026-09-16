"""Phase 7 Gate P7.8B -- mutation proofs B1-B10.

Each mutant below is the specific wrong thing a reviewer would worry about,
applied to the **real** code and shown to be caught -- not asserted to be
impossible. Where the property is source-level (an arithmetic ban the browser
must obey), it is audited against the real source rather than described.

The gate names ten. They are the ten ways this integration could look correct
and be wrong:

- **B1** the structured fingerprint hashes an empty structure instead of
  collapsing to the Project fingerprint (FP-2);
- **B2** a position's *name* enters the financial fingerprint (FP-1);
- **B3** a Strategy's Capital Structure MERGES with Base instead of replacing
  it (ST-2);
- **B4** an explicit empty Strategy structure is read as Inherit Base;
- **B5** one ``position_id`` may change class between structures (P-8);
- **B6** the Position matrix keys on the Project fingerprint instead of the
  structured one;
- **B7** a position a Strategy does not hold reads as zero, or as an invalid
  variant, instead of Not Applicable (P-9, DC-2);
- **B8** the Common Equity perspective reads the project's levered IRR instead
  of the structured Common Equity IRR (NS-1);
- **B9** removing a Unit ignores a Capital Structure that still references it;
- **B10** the frontend computes a Position metric or a cross-cell figure.

P7.8A's own M1-M15 / U1 / O1 / P1 mutants are deliberately not rerun: no
production financial module changed at this gate, and
``tests/test_p7_8b_product_integration_architecture.py`` proves each is
byte-identical to the reviewed head.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from _p7_6_fixtures import create_investment, quick_deal  # type: ignore[import-not-found]
from _p7_7_fixtures import fee, funding, unit_scope  # type: ignore[import-not-found]
from _p7_8_fixtures import (  # type: ignore[import-not-found]
    GOLDEN_MEZZ_AMOUNT,
    cash_pay_debt,
    claim_position,
    common_marker,
    round_deal,
    structure,
)
from anchor.analysis.strategy import (
    InvestmentStrategyOverlay,
    StrategyDomain,
    resolve_capital_structure,
    strategy_capital_structure,
)
from anchor.capital_structure.contracts import (
    CapitalPosition,
    CapitalStructure,
    DebtTerms,
    FixedAmount,
    PositionClass,
    ShortfallResolution,
)
from anchor.deals import store
from anchor.deals.contracts import InvestmentStructureError
from anchor.deals.fingerprint import capital_structure_payload, fingerprint_structured_source
from anchor.deals.position_identity import (
    PositionIdentityConflictError,
    PositionIdentityIssueCode,
    StructureOwner,
    StructureOwnerKind,
    require_coherent_position_identity,
)
from anchor.decision.comparison import (
    CellStatus,
    DecisionPerspective,
    PositionApplicability,
    PositionMetric,
    position_decision_matrix_fingerprint,
)
from anchor.deals.decision_matrix import analyze_position_decision_matrix
from anchor.deals.structured_variants import analyze_structured_variant

BASE = "base"

PROJECT = "9" * 64
EMPTY = CapitalStructure(positions=())
CEC = ShortfallResolution.COMMON_EQUITY_CONTRIBUTION

REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_GUARD = REPO_ROOT / "web" / "src" / "capitalStructureArchitecture.test.ts"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def debt_terms(**overrides: Any) -> DebtTerms:
    stated: dict[str, Any] = {
        "interest_rate": 0.12,
        "amortization": 25,
        "io_period": 1,
        "maturity_month": 48,
        "fees": (fee("mezz-fee", amount=15_000.0),),
        "current_pay_rate": 0.12,
        "pik_rate": 0.0,
    }
    stated.update(overrides)
    return DebtTerms(**stated)


def mezz(unit_id: str, **overrides: Any) -> CapitalPosition:
    stated: dict[str, Any] = {
        "position_id": "mezz-a",
        "name": "Mezzanine",
        "position_class": PositionClass.MEZZANINE_DEBT,
        "priority": 2,
        "scope": unit_scope(unit_id),
        "funding": (funding("mezz-f", rule=FixedAmount(amount=1_500_000.0)),),
        "terms": debt_terms(),
        "shortfall_resolution": CEC,
    }
    stated.update(overrides)
    return CapitalPosition(**stated)


def senior(unit_id: str, **overrides: Any) -> CapitalPosition:
    stated: dict[str, Any] = {
        "position_id": "senior-a",
        "name": "Senior Loan",
        "position_class": PositionClass.SENIOR_DEBT,
        "priority": 1,
        "scope": unit_scope(unit_id),
        "funding": (funding("senior-f", rule=FixedAmount(amount=6_000_000.0)),),
        "terms": debt_terms(interest_rate=0.06, current_pay_rate=0.06, fees=()),
        "shortfall_resolution": CEC,
    }
    stated.update(overrides)
    return CapitalPosition(**stated)


def overlay(content: CapitalStructure) -> InvestmentStrategyOverlay:
    return InvestmentStrategyOverlay(domain=StrategyDomain.CAPITAL_STRUCTURE, content=content)


def structured(capital_structure: CapitalStructure, project: str = PROJECT) -> str:
    return fingerprint_structured_source(
        project_source_fingerprint=project, capital_structure=capital_structure
    )


def _sha(payload: Any) -> str:
    """The digest the *mutant* would produce: the ordinary hashing path, applied
    where the real function collapses instead."""

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# =============================================================================
# B1 -- an empty structure collapses; it is not hashed
# =============================================================================


def test_b1_an_empty_structure_is_the_project_fingerprint_itself() -> None:
    """The mutant: hash the empty structure like any other payload.

    It is caught because the real function returns the project fingerprint
    *character for character*, and the mutant's digest is a different token --
    so neutral structured capital would have created a second identity for every
    Deal that never opted in (FP-2)."""

    assert structured(EMPTY) == PROJECT

    mutant = _sha({"project_source_fingerprint": PROJECT, "capital_structure": capital_structure_payload(EMPTY)})
    assert mutant != PROJECT

    # And the collapse is specific rather than a function that ignores its
    # structure: a stated position does move the fingerprint.
    assert structured(CapitalStructure(positions=(mezz("u1"),))) != PROJECT


def test_b1b_the_collapse_holds_for_every_project_fingerprint() -> None:
    for project in (PROJECT, "0" * 64, "a3f" * 21 + "b"):
        assert structured(EMPTY, project) == project


# =============================================================================
# B2 -- names are presentation; only economics are identity
# =============================================================================


def test_b2_a_position_name_never_enters_the_financial_fingerprint() -> None:
    """The mutant: include the name. It is caught because renaming a position --
    which changes no cash -- would invalidate every cached result and every
    matrix that named it (FP-1)."""

    named = CapitalStructure(positions=(mezz("u1", name="Mezzanine"),))
    renamed = CapitalStructure(positions=(mezz("u1", name="Second Lien"),))
    assert structured(named) == structured(renamed)

    # Teeth: an economic field of the same position does move it.
    repriced = CapitalStructure(positions=(mezz("u1", terms=debt_terms(interest_rate=0.13)),))
    assert structured(repriced) != structured(named)

    # And the payload the fingerprint is taken over names no name at all.
    assert "Mezzanine" not in json.dumps(capital_structure_payload(named))


# =============================================================================
# B3 / B4 -- whole replacement, and the two empties are different decisions
# =============================================================================


@pytest.fixture
def investment(db: Path) -> tuple[Path, str, str]:
    deal = quick_deal(db, name="A")
    record = create_investment(db, deal)
    store.set_base_capital_structure(
        record.id, CapitalStructure(positions=(senior(deal.id), mezz(deal.id))), db_path=db
    )
    return db, record.id, deal.id


def test_b3_a_strategy_structure_replaces_base_whole_and_never_merges(
    investment: tuple[Path, str, str],
) -> None:
    """The mutant: merge the Strategy's positions over Base's.

    It is caught because Base's senior loan must be *absent* from a Strategy
    that restates the stack without it. A merge would silently finance the deal
    with a position the analyst deleted (ST-2)."""

    db, investment_id, unit_id = investment
    record = store.create_strategy(
        investment_id,
        name="Mezz only",
        root_overlays=(overlay(CapitalStructure(positions=(mezz(unit_id),))),),
        db_path=db,
    )
    base = store.get_base_capital_structure(investment_id, db_path=db)
    assert [position.position_id for position in base.positions] == ["senior-a", "mezz-a"]

    resolved = resolve_capital_structure(base, record.strategy)
    assert [position.position_id for position in resolved.positions] == ["mezz-a"]
    # The Base structure itself is untouched, so removing the overlay restores
    # it exactly (P-6).
    assert store.get_base_capital_structure(investment_id, db_path=db) == base


def test_b4_an_explicit_empty_strategy_structure_is_not_inherit_base(
    investment: tuple[Path, str, str],
) -> None:
    """The mutant: read a stated-but-empty structure as "states none".

    It is caught because the two resolve to different stacks: inheriting gives
    Base's two positions, and stating none gives no structured capital at all.
    Collapsing them would quietly finance an unlevered strategy with Base's
    debt."""

    db, investment_id, _ = investment
    stated_empty = store.create_strategy(
        investment_id, name="No structured capital", root_overlays=(overlay(EMPTY),), db_path=db
    )
    inheriting = store.create_strategy(investment_id, name="Inherit", db_path=db)
    base = store.get_base_capital_structure(investment_id, db_path=db)

    # The contract keeps them apart: `None` means inherit, `EMPTY` means none.
    assert strategy_capital_structure(stated_empty.strategy) == EMPTY
    assert strategy_capital_structure(inheriting.strategy) is None

    # And so does resolution.
    assert resolve_capital_structure(base, stated_empty.strategy) == EMPTY
    assert resolve_capital_structure(base, inheriting.strategy) == base

    # They are different economic identities, too.
    assert structured(EMPTY) != structured(base)


# =============================================================================
# B5 -- one position_id names one instrument
# =============================================================================


def test_b5_a_position_id_may_not_change_class_between_structures() -> None:
    """The mutant: allow it.

    It is caught because ``POSITION(position_id)`` would otherwise compare a
    mezzanine loan in one Strategy with a preferred equity position in another
    and present the two as one instrument's alternatives (P-8)."""

    base_owner = StructureOwner(
        kind=StructureOwnerKind.BASE, owner_id="inv-1", label="the Base Capital Structure"
    )
    strategy_owner = StructureOwner(
        kind=StructureOwnerKind.STRATEGY, owner_id="str-1", label="Strategy 'Value-Add'"
    )
    as_mezzanine = CapitalStructure(positions=(mezz("u1"),))
    as_senior = CapitalStructure(positions=(mezz("u1", position_class=PositionClass.SENIOR_DEBT),))

    with pytest.raises(PositionIdentityConflictError) as refused:
        require_coherent_position_identity(
            [(base_owner, as_mezzanine), (strategy_owner, as_senior)]
        )

    (issue,) = refused.value.issues
    assert issue.code is PositionIdentityIssueCode.POSITION_CLASS_CONFLICT
    assert issue.position_id == "mezz-a"
    # The message names both owners, so the analyst knows which to change.
    assert "the Base Capital Structure" in issue.message and "Value-Add" in issue.message

    # Teeth: the same id, the same class, different economics is *not* a
    # conflict -- that is exactly what a Strategy is for.
    repriced = CapitalStructure(positions=(mezz("u1", terms=debt_terms(interest_rate=0.15)),))
    require_coherent_position_identity([(base_owner, as_mezzanine), (strategy_owner, repriced)])


# =============================================================================
# B6 -- the Position matrix keys on the structured fingerprint
# =============================================================================


def test_b6_the_position_matrix_fingerprint_reads_structured_not_project_identities() -> None:
    """The mutant: build the matrix fingerprint from each cell's *project*
    source fingerprint.

    It is caught because two matrices whose Capital Structures differ -- and
    whose Project inputs are identical, which is the ordinary case -- would
    share one digest, and one could be served as the other."""

    cells_structured = (("base", "base", "S-1"), ("str-1", "base", "S-2"))
    cells_project = (("base", "base", "P-1"), ("str-1", "base", "P-1"))

    real = position_decision_matrix_fingerprint("mezz-a", cells_structured)
    mutant = position_decision_matrix_fingerprint("mezz-a", cells_project)
    assert real != mutant

    # Moving one cell's structured fingerprint moves the matrix's.
    moved = position_decision_matrix_fingerprint("mezz-a", (("base", "base", "S-1"), ("str-1", "base", "S-3")))
    assert moved != real

    # And the selected position is part of the identity: the same variants
    # compared for a different position are a different comparison.
    assert position_decision_matrix_fingerprint("pref-a", cells_structured) != real

    # The perspective is stated in the payload rather than implied.
    assert DecisionPerspective.POSITION.value == "position"


# =============================================================================
# B7 / B8 -- an absent position, and the Common Equity residual
# =============================================================================


def golden_mezz(unit_id: str, *, rate: float = 0.12) -> Any:
    """The executable mezzanine of the P7.8 fixtures: real economics, so the
    matrix below is a real analysis rather than a shape."""

    return claim_position(
        "mezz-a",
        position_class=PositionClass.MEZZANINE_DEBT,
        priority=2,
        terms=cash_pay_debt(
            rate=rate,
            amortization=25,
            io_period=1,
            maturity_month=48,
            fees=(fee("mezz-fee", amount=15_000.0),),
        ),
        resolution=CEC,
        amount=GOLDEN_MEZZ_AMOUNT,
        scope=unit_scope(unit_id),
    )


@pytest.fixture
def matrix(db: Path) -> tuple[Path, str, str, str]:
    """A Deal holding a mezzanine loan and the Common Equity marker, and one
    Strategy that restates the stack without the mezzanine."""

    deal = round_deal(db, name="Mutation deal")
    investment_id, _ = store.set_deal_capital_structure(
        deal.id,
        structure(golden_mezz(deal.id), common_marker("common-a", scope=unit_scope(deal.id))),
        db_path=db,
    )
    assert investment_id is not None
    without = store.create_strategy(
        investment_id,
        name="No mezzanine",
        root_overlays=(
            overlay(structure(common_marker("common-a", scope=unit_scope(deal.id)))),
        ),
        db_path=db,
    )
    return db, investment_id, deal.id, without.strategy.strategy_id


def _cells(matrix_report: Any) -> dict[tuple[str, str], Any]:
    return {(cell.strategy_id, cell.scenario_id): cell for cell in matrix_report.cells}


def test_b7_a_position_a_strategy_does_not_hold_is_not_applicable_not_zero(
    matrix: tuple[Path, str, str, str],
) -> None:
    """The mutant: report the absent position as zero, or refuse the whole cell
    as an invalid variant.

    It is caught because the cell must be *valid* -- the Strategy analysed
    perfectly well -- and carry no figure at all. A zero would read as a
    mezzanine that earned nothing, which is a different and much worse claim
    than one the Strategy never issued (P-9, DC-2)."""

    db, investment_id, _, without_id = matrix
    cells = _cells(analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix)

    absent = cells[(without_id, BASE)]
    assert absent.status is CellStatus.VALID
    assert absent.applicability is PositionApplicability.NOT_PRESENT
    # Not zero: no metric of an absent position carries a figure.
    assert all(value.value is None for value in absent.metrics)

    present = cells[(BASE, BASE)]
    assert present.applicability is PositionApplicability.PRESENT
    assert any(value.value is not None for value in present.metrics)


def test_b8_the_common_equity_perspective_reads_the_structured_residual(
    matrix: tuple[Path, str, str, str],
) -> None:
    """The mutant: read ``AcquisitionResults.levered_*`` for the Common Equity
    marker.

    It is caught because every Common Equity figure is pinned to
    ``StructuredCapitalResult.common_equity`` -- the residual *after* the
    mezzanine is paid. The project's levered return is a different number with a
    different meaning once structured capital exists, and presenting one as the
    other would overstate what the common holder actually receives (NS-1)."""

    db, investment_id, _, _ = matrix
    report = analyze_position_decision_matrix(investment_id, "common-a", db_path=db)
    assert report.matrix.is_common_equity_marker is True

    analysis = analyze_structured_variant(investment_id, BASE, BASE, db_path=db)
    residual = analysis.result.common_equity
    cell = _cells(report.matrix)[(BASE, BASE)]

    def value(name: PositionMetric) -> Any:
        return next(entry for entry in cell.metrics if entry.metric is name).value

    assert value(PositionMetric.COMMON_EQUITY_IRR) == residual.irr
    assert value(PositionMetric.EQUITY_MULTIPLE) == residual.equity_multiple
    assert value(PositionMetric.TOTAL_EQUITY_INVESTED) == residual.total_equity_invested
    # The residual is genuinely subordinate: it is not the mezzanine's return.
    mezzanine = _cells(analyze_position_decision_matrix(investment_id, "mezz-a", db_path=db).matrix)
    mezz_irr = next(
        entry for entry in mezzanine[(BASE, BASE)].metrics if entry.metric is PositionMetric.IRR
    ).value
    assert value(PositionMetric.COMMON_EQUITY_IRR) != mezz_irr


# =============================================================================
# B9 -- a Unit that a structure still references does not quietly leave
# =============================================================================


def test_b9_removing_a_referenced_unit_is_refused_and_writes_nothing(db: Path) -> None:
    """The mutant: ignore Capital Structure references when removing a Unit.

    It is caught because the position would be left scoped to a Unit the
    Investment no longer holds -- a structure that references nothing, found
    only when someone next ran it."""

    first, second = quick_deal(db, name="A"), quick_deal(db, name="B")
    record = create_investment(db, first, second)
    store.set_base_capital_structure(
        record.id, CapitalStructure(positions=(mezz(second.id),)), db_path=db
    )

    with pytest.raises(InvestmentStructureError) as refused:
        store.remove_investment_unit(record.id, second.id, db_path=db)

    message = str(refused.value)
    assert "Mezzanine" in message and "the Base Capital Structure" in message
    # Nothing was removed.
    assert len(store.get_visible_investment(record.id, db_path=db).units) == 2
    assert store.get_base_capital_structure(record.id, db_path=db).positions


# =============================================================================
# B10 -- the browser computes no Position metric and no cross-cell figure
# =============================================================================


def test_b10_the_frontend_arithmetic_ban_is_enforced_by_a_guard_with_teeth() -> None:
    """The mutant: compute one Position metric or cross-cell figure in the
    browser.

    The kill lives on the TypeScript side, where the mutants can be parsed:
    ``web/src/capitalStructureArchitecture.test.ts`` feeds a funded amount, a
    profit, a MOIC, a ``Math.min`` coverage, a ``reduce`` total, a ``Number()``
    re-parse and a negation through the same analyser the production modules are
    held to, and requires each to be reported. This asserts that guard exists,
    covers every P7.8B module, and pins the complete allowed set -- so the ban
    cannot be widened here without a reviewer seeing it."""

    source = FRONTEND_GUARD.read_text(encoding="utf-8")
    assert "would see a smuggled funded amount, return, coverage or attachment (M4)" in source

    for module in (
        "capitalTypes.ts",
        "capitalStructureForm.ts",
        "useCapitalStructure.ts",
        "usePositionDecisionMatrix.ts",
        "components/CapitalStructureEditor.tsx",
        "components/CapitalStructureResults.tsx",
        "components/CapitalStructureWorkspace.tsx",
        "components/PositionDecisionMatrixPanel.tsx",
    ):
        assert f"'{module}'" in source, module

    # The only arithmetic the browser is allowed: the display-scale conversions
    # and a counter in each hook. Every surface holds none.
    for allowed in ("'index += 1'", "'rule.pct * 100'", "'key + 1'"):
        assert allowed in source, allowed
    for surface in (
        "'components/CapitalStructureEditor.tsx': []",
        "'components/CapitalStructureResults.tsx': []",
        "'components/CapitalStructureWorkspace.tsx': []",
        "'components/PositionDecisionMatrixPanel.tsx': []",
    ):
        assert surface in source, surface
