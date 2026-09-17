"""Phase 7 Gate P7.9 Stage 2 -- the Partnership source fingerprint.

``docs/architecture/P7_9_PARTNERSHIP_WATERFALLS.md`` Section 17.2 and
``docs/architecture/P7_COMPETITION_DECISION_ARCHITECTURE.md`` Sections 15.4
(FP-1, FP-2) and 15.5. The claims:

- **Layered.** ``PARTNERSHIP = f(structured source fingerprint, resolved
  Partnership economics)``: a different structured fingerprint is a different
  Partnership fingerprint.
- **Every economic field is included** -- each one, changed alone, moves the
  digest.
- **Presentation is excluded** -- partner and tier names and ``role`` never do.
- **Canonical order** -- partners, shares and participants by id, tiers by
  sequence, conditions by id: no permutation moves it.
- **No Partnership, no fingerprint, no key (FP-2).**
- **Invalidation boundary.** A Partnership edit moves the Partnership
  fingerprints and the Partner matrix only; the Project and structured
  fingerprints, the Project matrix and the Position matrix stay exactly where
  they were.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable

import pytest

import _p7_9_fixtures as f  # type: ignore[import-not-found]
from _p7_9_stage_2_fixtures import (  # type: ignore[import-not-found]
    class_subject_terms,
    no_partnership_overlay,
    partnership_overlay,
    renamed,
    structured_deal,
    with_partner,
)
from anchor.deals import store
from anchor.deals.decision_matrix import (
    analyze_decision_matrix,
    analyze_partner_decision_matrix,
    analyze_position_decision_matrix,
)
from anchor.deals.fingerprint import (
    UnfingerprintableValueError,
    fingerprint_partnership_source,
    partnership_payload,
)
from anchor.deals.partnership_variants import partnership_variant_fingerprint
from anchor.deals.structured_variants import structured_variant_fingerprint
from anchor.partnership import (
    CatchUpRecipient,
    HurdleCombinator,
    HurdleSubject,
    Partnership,
    PartnerRole,
    ProRataByContribution,
    TierKind,
)

STRUCTURED = "a" * 64


def digest(partnership: Partnership, structured: str = STRUCTURED) -> str:
    return fingerprint_partnership_source(structured_source_fingerprint=structured, partnership=partnership)


def _tier(partnership: Partnership, target: str, **changes: Any) -> Partnership:
    return dataclasses.replace(
        partnership,
        tiers=tuple(dataclasses.replace(t, **changes) if t.tier_id == target else t for t in partnership.tiers),
    )


def _hurdle(partnership: Partnership, target: str, **changes: Any) -> Partnership:
    tier = next(t for t in partnership.tiers if t.tier_id == target)
    assert tier.hurdle is not None
    return _tier(partnership, target, hurdle=dataclasses.replace(tier.hurdle, **changes))


def _condition(partnership: Partnership, target: str, condition: Any) -> Partnership:
    return _hurdle(partnership, target, conditions=(condition,))


def _catch_up(partnership: Partnership, **changes: Any) -> Partnership:
    tier = next(t for t in partnership.tiers if t.kind is TierKind.CATCH_UP)
    assert tier.catch_up is not None
    return _tier(partnership, tier.tier_id, catch_up=dataclasses.replace(tier.catch_up, **changes))


F1 = f.f1_terms()
F12 = f.f12_terms()
CLASS = class_subject_terms()

#: Each included economic field, changed alone (Section 17.2's list). The terms
#: stay structurally ordinary; validity is irrelevant to what the digest reads.
_ECONOMIC_EDITS: list[tuple[str, Callable[[], Partnership]]] = [
    ("partner id", lambda: dataclasses.replace(
        F1,
        partners=tuple(dataclasses.replace(p, partner_id="sponsor") if p.partner_id == "gp" else p for p in F1.partners),
    )),
    ("investor class", lambda: with_partner(F1, "gp", investor_class="sponsor")),
    ("commitment share", lambda: with_partner(F1, "gp", commitment_share=0.11)),
    ("benchmark share", lambda: dataclasses.replace(F1, promote_benchmark=f.benchmark(lp=0.95, gp=0.05))),
    ("promote participants", lambda: dataclasses.replace(F1, promote_participant_ids=())),
    ("another promote participant", lambda: dataclasses.replace(F1, promote_participant_ids=("gp", "lp"))),
    ("tier id", lambda: _tier(F1, "promote_2", tier_id="residual")),
    ("tier sequence", lambda: _tier(F1, "promote_2", sequence=50)),
    ("tier kind", lambda: _tier(F1, "promote_1", kind=TierKind.RESIDUAL)),
    ("split rule", lambda: _tier(F1, "promote_2", split=ProRataByContribution())),
    ("split share", lambda: _tier(F1, "promote_2", split=f.split(lp=0.75, gp=0.25))),
    ("subject partner", lambda: _hurdle(F1, "pref", hurdle_subject=f.of_partner("gp"))),
    ("subject kind", lambda: _hurdle(F1, "pref", hurdle_subject=f.ALL_EQUITY)),
    ("subject class", lambda: _hurdle(CLASS, "pref", hurdle_subject=f.of_class("sponsor"))),
    ("condition id", lambda: _condition(F1, "pref", f.compound("pref-8b", 0.08))),
    ("condition rate", lambda: _condition(F1, "pref", f.compound("pref-8", 0.085))),
    ("accrual convention", lambda: _condition(F1, "pref", f.simple("pref-8", 0.08, f.ACCRUED_FIRST))),
    ("condition kind", lambda: _condition(F1, "pref", f.moic("pref-8", 1.08))),
    ("combinator", lambda: _hurdle(F1, "pref", combinator=HurdleCombinator.ANY)),
    ("catch-up recipient", lambda: _catch_up(F1, recipient=f.to_partner("lp"))),
    ("catch-up target", lambda: _catch_up(F1, target_profit_share=0.25)),
]

_CLASS_EDITS: list[tuple[str, Callable[[], Partnership]]] = [
    ("SIMPLE order", lambda: _hurdle(
        CLASS, "pref",
        conditions=(f.simple("pref-8", 0.08, f.CAPITAL_FIRST), f.moic("moic-15", 1.5)),
    )),
    ("multiple", lambda: _hurdle(
        CLASS, "pref",
        conditions=(f.simple("pref-8", 0.08, f.ACCRUED_FIRST), f.moic("moic-15", 1.6)),
    )),
    ("recipient class", lambda: _catch_up(F12, recipient=f.to_class("limited"))),
    ("recipient kind", lambda: _catch_up(F12, recipient=f.to_partner("g1"))),
]


@pytest.mark.parametrize(("field", "edit"), _ECONOMIC_EDITS + _CLASS_EDITS, ids=[n for n, _ in _ECONOMIC_EDITS + _CLASS_EDITS])
def test_every_economic_field_is_included(field: str, edit: Callable[[], Partnership]) -> None:
    edited = edit()
    original = CLASS if field in {"SIMPLE order", "multiple", "subject class"} else F12 if field.startswith("recipient") else F1

    assert edited != original
    assert digest(edited) != digest(original), field


def test_the_payload_names_every_included_field_and_no_excluded_one() -> None:
    payload = partnership_payload(F12)

    assert set(payload) == {"partners", "contribution_rule", "promote_benchmark", "promote_participant_ids", "tiers"}
    assert set(payload["partners"][0]) == {"partner_id", "investor_class", "commitment_share"}
    assert set(payload["tiers"][0]) == {"tier_id", "sequence", "kind", "split", "hurdle", "catch_up"}
    assert set(payload["tiers"][0]["hurdle"]) == {"hurdle_subject", "conditions", "combinator"}
    assert set(payload["tiers"][0]["hurdle"]["conditions"][0]) == {
        "kind", "condition_id", "rate", "accrual_convention", "simple_distribution_order",
    }
    assert set(payload["tiers"][1]["catch_up"]) == {"recipient", "target_profit_share"}
    assert payload["contribution_rule"] == "pro_rata_by_commitment"
    text = repr(payload)
    for excluded in ("name", "role", "'LP'", "'GP'", "Pref", "Catch Up"):
        assert excluded not in text, excluded


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: renamed(p),
        lambda p: with_partner(p, "gp", role=PartnerRole.CO_INVESTOR),
        lambda p: with_partner(p, "lp", role=PartnerRole.GP, name="Limited Partner"),
    ],
    ids=["names", "gp-role", "lp-role-and-name"],
)
def test_names_and_roles_are_excluded(edit: Callable[[Partnership], Partnership]) -> None:
    assert digest(edit(F1)) == digest(F1)


def test_canonical_order_never_moves_the_digest() -> None:
    permuted = dataclasses.replace(
        F12,
        partners=tuple(reversed(F12.partners)),
        tiers=tuple(reversed(F12.tiers)),
        promote_participant_ids=tuple(reversed(F12.promote_participant_ids)),
        promote_benchmark=dataclasses.replace(
            F12.promote_benchmark, shares=tuple(reversed(F12.promote_benchmark.shares))
        ),
    )
    permuted = dataclasses.replace(
        permuted,
        tiers=tuple(
            dataclasses.replace(t, split=dataclasses.replace(t.split, shares=tuple(reversed(t.split.shares))))
            for t in permuted.tiers
        ),
    )
    assert permuted != F12
    assert digest(permuted) == digest(F12)

    reordered_conditions = _hurdle(
        CLASS, "pref", conditions=tuple(reversed(next(t for t in CLASS.tiers if t.tier_id == "pref").hurdle.conditions))
    )
    assert reordered_conditions != CLASS
    assert digest(reordered_conditions) == digest(CLASS)


def test_a_different_structured_fingerprint_is_a_different_partnership_fingerprint() -> None:
    assert digest(F1, "a" * 64) != digest(F1, "b" * 64)


def test_there_is_no_fingerprint_without_a_partnership() -> None:
    for value in (None, "", 0):
        with pytest.raises(UnfingerprintableValueError):
            fingerprint_partnership_source(structured_source_fingerprint=value, partnership=F1)  # type: ignore[arg-type]
    for value in (None, object(), dataclasses.asdict(F1)):
        with pytest.raises(UnfingerprintableValueError):
            fingerprint_partnership_source(structured_source_fingerprint=STRUCTURED, partnership=value)  # type: ignore[arg-type]


def test_an_unknown_union_member_is_refused_not_hashed() -> None:
    @dataclasses.dataclass(frozen=True)
    class EqualSplit:
        pass

    with pytest.raises(TypeError):
        digest(_tier(F1, "promote_2", split=EqualSplit()))
    with pytest.raises(TypeError):
        digest(_condition(F1, "pref", object()))
    with pytest.raises(TypeError):
        digest(_hurdle(F1, "pref", hurdle_subject=HurdleSubject(kind="fund", partner_id="lp", investor_class=None, account=None)))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        digest(_catch_up(F1, recipient=CatchUpRecipient(kind="economic_account", partner_id=None, investor_class=None)))  # type: ignore[arg-type]


# =============================================================================
# Over stored state: FP-2 and the invalidation boundary
# =============================================================================


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "anchor.db"


def test_no_partnership_has_no_partnership_fingerprint(db: Path) -> None:
    _, investment_id = structured_deal(db)

    fingerprint = partnership_variant_fingerprint(investment_id, "base", "base", db_path=db)
    structured = structured_variant_fingerprint(investment_id, "base", "base", db_path=db)

    assert fingerprint.partnership is None and fingerprint.partnership_source_fingerprint is None
    assert fingerprint.structured_source_fingerprint == structured.structured_source_fingerprint
    assert fingerprint.project_source_fingerprint == structured.project_source_fingerprint


def test_a_stored_partnership_fingerprints_as_its_contract(db: Path) -> None:
    _, investment_id = structured_deal(db, F1)

    fingerprint = partnership_variant_fingerprint(investment_id, "base", "base", db_path=db)

    assert fingerprint.partnership == F1
    assert fingerprint.partnership_source_fingerprint == digest(F1, fingerprint.structured_source_fingerprint)


def test_an_explicit_none_strategy_has_no_partnership_fingerprint(db: Path) -> None:
    _, investment_id = structured_deal(db, F1)
    none = store.create_strategy(investment_id, name="None", root_overlays=(no_partnership_overlay(),), db_path=db)

    fingerprint = partnership_variant_fingerprint(investment_id, none.strategy.strategy_id, "base", db_path=db)

    assert fingerprint.partnership is None and fingerprint.partnership_source_fingerprint is None
    assert fingerprint.partnership_source.value == "strategy"


def _state(db: Path, investment_id: str, strategy_ids: list[str]) -> dict[str, Any]:
    return {
        "project": {
            sid: structured_variant_fingerprint(investment_id, sid, "base", db_path=db).project_source_fingerprint
            for sid in strategy_ids
        },
        "structured": {
            sid: structured_variant_fingerprint(investment_id, sid, "base", db_path=db).structured_source_fingerprint
            for sid in strategy_ids
        },
        "partnership": {
            sid: partnership_variant_fingerprint(investment_id, sid, "base", db_path=db).partnership_source_fingerprint
            for sid in strategy_ids
        },
        "project_matrix": analyze_decision_matrix(investment_id, db_path=db).matrix.matrix_fingerprint,
        "position_matrix": analyze_position_decision_matrix(investment_id, "mezz", db_path=db).matrix.matrix_fingerprint,
        "partner_matrix": analyze_partner_decision_matrix(investment_id, "lp", db_path=db).matrix.matrix_fingerprint,
    }


def test_a_base_partnership_edit_invalidates_only_the_partnership_layer(db: Path) -> None:
    _, investment_id = structured_deal(db, F1)
    own = store.create_strategy(
        investment_id, name="Own", root_overlays=(partnership_overlay(f.f7_terms()),), db_path=db
    )
    ids = ["base", own.strategy.strategy_id]
    before = _state(db, investment_id, ids)

    store.set_base_partnership(investment_id, with_partner(F1, "gp", investor_class="sponsor"), db_path=db)
    after = _state(db, investment_id, ids)

    for layer in ("project", "structured", "project_matrix", "position_matrix"):
        assert after[layer] == before[layer], layer
    assert after["partnership"]["base"] != before["partnership"]["base"]
    # A Strategy that replaces the Partnership whole is not downstream of Base.
    assert after["partnership"][own.strategy.strategy_id] == before["partnership"][own.strategy.strategy_id]
    assert after["partner_matrix"] != before["partner_matrix"]


def test_a_strategy_partnership_edit_moves_only_that_strategys_partnership_fingerprint(db: Path) -> None:
    _, investment_id = structured_deal(db, F1)
    own = store.create_strategy(
        investment_id, name="Own", root_overlays=(partnership_overlay(f.f7_terms()),), db_path=db
    )
    inherit = store.create_strategy(investment_id, name="Inherit", db_path=db)
    ids = ["base", own.strategy.strategy_id, inherit.strategy.strategy_id]
    before = _state(db, investment_id, ids)

    store.update_strategy(
        investment_id,
        own.strategy.strategy_id,
        name="Own",
        root_overlays=(partnership_overlay(dataclasses.replace(f.f7_terms(), promote_participant_ids=())),),
        db_path=db,
    )
    after = _state(db, investment_id, ids)

    for layer in ("project", "structured", "project_matrix", "position_matrix"):
        assert after[layer] == before[layer], layer
    assert after["partnership"][own.strategy.strategy_id] != before["partnership"][own.strategy.strategy_id]
    assert after["partnership"]["base"] == before["partnership"]["base"]
    assert after["partnership"][inherit.strategy.strategy_id] == before["partnership"][inherit.strategy.strategy_id]
    assert after["partner_matrix"] != before["partner_matrix"]


def test_a_rename_moves_no_fingerprint(db: Path) -> None:
    _, investment_id = structured_deal(db, F1)
    before = _state(db, investment_id, ["base"])

    store.set_base_partnership(investment_id, renamed(with_partner(F1, "gp", role=PartnerRole.GP)), db_path=db)

    after = _state(db, investment_id, ["base"])
    assert after == before


def test_a_capital_structure_edit_moves_the_partnership_fingerprint_through_the_structured_one(db: Path) -> None:
    """The layering, end to end: junior capital is upstream of the waterfall."""

    from _p7_8_fixtures import golden_mezz  # type: ignore[import-not-found]
    from _p7_9_stage_2_fixtures import unit_scope  # type: ignore[import-not-found]
    from anchor.capital_structure import CapitalStructure

    deal, investment_id = structured_deal(db, F1)
    before = partnership_variant_fingerprint(investment_id, "base", "base", db_path=db)

    bigger = dataclasses.replace(golden_mezz(), scope=unit_scope(deal.id), priority=3)
    store.set_base_capital_structure(investment_id, CapitalStructure(positions=(bigger,)), db_path=db)
    after = partnership_variant_fingerprint(investment_id, "base", "base", db_path=db)

    assert after.project_source_fingerprint == before.project_source_fingerprint
    assert after.structured_source_fingerprint != before.structured_source_fingerprint
    assert after.partnership_source_fingerprint != before.partnership_source_fingerprint
    assert after.partnership_source_fingerprint == digest(F1, after.structured_source_fingerprint)
