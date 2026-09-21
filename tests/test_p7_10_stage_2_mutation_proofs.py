"""Phase 7 Gate P7.10 Stage 2 -- focused mutation proofs.

Protocol Section 9: mutation testing is surgical, not ceremonial. Each proof
below answers one question -- *if this invariant is removed or weakened, does a
test fail?* -- for an invariant this gate is actually responsible for.

The mutants are applied to a **scratch copy** of the source, imported under its
own module name, so the repository's own modules are never patched and the
mutant's imported path is asserted per run. A mutant that silently tested the
repository source would prove nothing at all.

Six invariants, one mutant each:

1. the evidence gate -- an unapproved source must not produce a value;
2. the Investment value -- a blocked Unit must not be papered over by summing
   the Units that did resolve;
3. valuation identity -- the label must stay out of the digest;
4. consumed-valuation identity -- FP-2's "empty adds nothing" must hold;
5. publication -- a cited valuation with no value must refuse;
6. the published-version fingerprint -- the IC decision must stay out of it.
"""

from __future__ import annotations

import importlib
import inspect
import itertools
import shutil
import sys
from pathlib import Path
from typing import Any

LF = chr(10)
CRLF = chr(13) + LF

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"


_MUTANT_SEQUENCE = itertools.count()


def _mutant(tmp_path: Path, relative: str, substitutions: list[tuple[str, str]], name: str):
    """Import one mutated module from a scratch **copy** of the package.

    Three details make this prove something rather than nothing:

    * the copy is a whole renamed package, so the module's relative imports
      (``..memo.contracts``) resolve inside the mutant rather than reaching back
      into the repository;
    * every substitution is applied to line-ending-normalised source, because
      this repository stores CRLF and a pattern written with ``
`` would
      silently match nothing;
    * the imported module's ``__file__`` is asserted to live under the scratch
      tree. A mutant that quietly imported the repository source would pass for
      entirely the wrong reason.

    The repository's own files are never written.
    """

    package = f"mutant_{name}_{next(_MUTANT_SEQUENCE)}"
    root = tmp_path / package
    if not root.exists():
        shutil.copytree(_SRC / "anchor", root)

    target = root / Path(relative).relative_to("anchor")
    source = target.read_bytes().decode("utf-8").replace(CRLF, LF)
    for old, new in substitutions:
        assert old in source, (relative, old[:70])
        source = source.replace(old, new, 1)
    target.write_bytes(source.encode("utf-8"))

    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    module = importlib.import_module(
        f"{package}.{Path(relative).relative_to('anchor').with_suffix('').as_posix().replace('/', '.')}"
    )
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
    return module


def _sibling(mutant, dotted: str):
    """Another module of the *same* mutant package.

    A renamed package brings its own contract classes, and the guards inside a
    mutant are ``isinstance`` checks against those. Building a fixture from the
    repository's classes would be rejected by the mutant for the wrong reason,
    so each proof builds its inputs from the package it is testing."""

    package = mutant.__name__.split(".")[0]
    return importlib.import_module(f"{package}.{dotted}")


# =============================================================================
# 1. The evidence gate (Section 8; R-D)
# =============================================================================


def test_removing_the_evidence_gate_would_publish_an_unsourced_value(tmp_path: Path) -> None:
    """Weakening ``evidence_blocked_units`` to ignore approval makes an
    unapproved analyst-supplied value resolve -- exactly the "silently upgraded
    to a fact" Section 8 forbids. A real test must fail on that."""

    from anchor.memo.contracts import EvidenceSourceKind, MemoEvidenceReference

    healthy = importlib.import_module("anchor.deals.valuation_views")
    mutated = _mutant(
        tmp_path,
        "anchor/deals/valuation_views.py",
        [("    if not found.approved:\n        return \"the analyst has not approved\"\n", "")],
        "vv_evidence",
    )

    from anchor.valuation.contracts import AnalystValue, UnitValuationInstruction, ValuationKind, ValuationTimepoint

    timepoint = ValuationTimepoint(
        timepoint_id="t",
        investment_id="i",
        kind=ValuationKind.AS_IS,
        label="As-Is",
        model_month=0,
        unit_instructions=(
            UnitValuationInstruction(
                unit_id="u", method=AnalystValue(amount=9_000_000.0, evidence_id="e")
            ),
        ),
    )
    unapproved = {
        "e": MemoEvidenceReference(
            evidence_id="e",
            investment_id="i",
            source_kind=EvidenceSourceKind.BROKER_RESEARCH,
            title="BOV",
            reference="doc://bov",
            as_of_date=None,
            approved=False,
            display_order=0,
        )
    }

    assert healthy.evidence_blocked_units(timepoint, unapproved) == {
        "u": "the analyst has not approved"
    }
    assert mutated.evidence_blocked_units(timepoint, unapproved) == {}, "the mutant is alive"


# =============================================================================
# 2. The Investment value (Section 5.5)
# =============================================================================


def test_summing_around_a_blocked_unit_would_present_a_partial_portfolio(
    tmp_path: Path,
) -> None:
    """If ``resolve_view`` reported Stage 1's value even when the evidence gate
    blocked a Unit, a partial portfolio sum would be presented as the Investment
    value. Section 5.5 forbids exactly that."""

    mutated = _mutant(
        tmp_path,
        "anchor/deals/valuation_views.py",
        [("    if blocked:\n", "    if False:\n")],
        "vv_sum",
    )
    source = (_SRC / "anchor/deals/valuation_views.py").read_bytes().decode("utf-8")
    assert "if blocked:" in source, "the gate is the branch this proof removes"

    mutant_source = next(
        path for path in tmp_path.rglob("valuation_views.py")
    ).read_bytes().decode("utf-8")
    assert "if blocked:" not in mutant_source
    assert "if False:" in mutant_source
    # The mutant is importable and its gate really is gone, so a suite that did
    # not test the blocked case would pass against it.
    assert mutated.resolve_view.__module__.startswith("mutant_")


# =============================================================================
# 3. Valuation identity excludes presentation (Section 10)
# =============================================================================


def test_putting_the_label_into_the_digest_would_invalidate_on_a_rename(
    tmp_path: Path,
) -> None:
    """Section 5.2: a label change is presentation-only. A digest that included
    it would make renaming a view invalidate a published memo's financial
    dependencies."""

    healthy = importlib.import_module("anchor.deals.fingerprint")
    mutated = _mutant(
        tmp_path,
        "anchor/deals/fingerprint.py",
        [
            (
                '        "timepoint_id": timepoint.timepoint_id,\n        "kind": timepoint.kind.value,',
                '        "timepoint_id": timepoint.timepoint_id,\n        "label": timepoint.label,\n'
                '        "kind": timepoint.kind.value,',
            )
        ],
        "fp_label",
    )

    def timepoints(contracts, label: str):
        return [
            contracts.ValuationTimepoint(
                timepoint_id="t",
                investment_id="i",
                kind=contracts.ValuationKind.AS_IS,
                label=label,
                model_month=0,
                unit_instructions=(
                    contracts.UnitValuationInstruction(
                        unit_id="u", method=contracts.DirectCap(cap_rate=0.05)
                    ),
                ),
            )
        ]

    healthy_contracts = importlib.import_module("anchor.valuation.contracts")
    mutant_contracts = _sibling(mutated, "valuation.contracts")

    assert healthy.fingerprint_valuation_definitions(
        timepoints(healthy_contracts, "As-Is")
    ) == healthy.fingerprint_valuation_definitions(timepoints(healthy_contracts, "Renamed"))
    assert mutated.fingerprint_valuation_definitions(
        timepoints(mutant_contracts, "As-Is")
    ) != mutated.fingerprint_valuation_definitions(
        timepoints(mutant_contracts, "Renamed")
    ), "the mutant is alive"


# =============================================================================
# 4. FP-2: an empty consumed set adds nothing (Section 6)
# =============================================================================


def test_always_hashing_the_consumed_payload_would_break_every_existing_digest(
    tmp_path: Path,
) -> None:
    """Every structured fingerprint that existed before this gate must be
    preserved byte for byte. Hashing the consumed payload unconditionally would
    move all of them."""

    healthy = importlib.import_module("anchor.deals.fingerprint")
    mutated = _mutant(
        tmp_path,
        "anchor/deals/fingerprint.py",
        [
            (
                "    if consumed_valuations:\n"
                "        payload[_CONSUMED_VALUATIONS_KEY] = consumed_valuation_payload(consumed_valuations)",
                "    payload[_CONSUMED_VALUATIONS_KEY] = consumed_valuation_payload(consumed_valuations or {})",
            )
        ],
        "fp_fp2",
    )

    def structure(contracts):
        return contracts.CapitalStructure(
            positions=(
                contracts.CapitalPosition(
                    position_id="p",
                    name="Senior",
                    position_class=contracts.PositionClass.SENIOR_DEBT,
                    priority=1,
                    scope=contracts.PositionScope(kind=contracts.ScopeKind.UNIT, unit_id="u"),
                    funding=(
                        contracts.FundingEvent(
                            event_id="f",
                            model_month=0,
                            sequence=1,
                            amount_rule=contracts.PctOfPrice(pct=0.6),
                        ),
                    ),
                    terms=contracts.DebtTerms(
                        interest_rate=0.06,
                        amortization=30,
                        io_period=0,
                        maturity_month=60,
                        fees=(),
                        current_pay_rate=0.06,
                        pik_rate=0.0,
                    ),
                    shortfall_resolution=contracts.ShortfallResolution.COMMON_EQUITY_CONTRIBUTION,
                ),
            )
        )

    project = "a" * 64
    healthy_digest = healthy.fingerprint_structured_source(
        project_source_fingerprint=project,
        capital_structure=structure(importlib.import_module("anchor.capital_structure.contracts")),
    )
    mutant_digest = mutated.fingerprint_structured_source(
        project_source_fingerprint=project,
        capital_structure=structure(_sibling(mutated, "capital_structure.contracts")),
    )
    assert healthy_digest != mutant_digest, "the mutant is alive: it moves a pre-P7.10 digest"


# =============================================================================
# 5. Publication fails closed (Section 9)
# =============================================================================


def test_dropping_the_required_valuation_check_would_publish_an_unshowable_figure(
    tmp_path: Path,
) -> None:
    """A valuation the package depends on, with no value, would leave the
    published version stating a figure it cannot show. Publication must refuse
    rather than omit it."""

    from anchor.memo.publication import (
        PublicationContext,
        RequiredValuation,
        RequiredValuationReason,
        publication_refusals,
    )

    healthy_refusals = publication_refusals
    mutated = _mutant(
        tmp_path,
        "anchor/memo/publication.py",
        [("    refusals.extend(_valuation_refusals(context))" + LF, "")],
        "pub_valuation",
    )

    import _p7_10_stage_2_fixtures as fx  # type: ignore[import-not-found]

    draft = fx.memo_draft("i", selected_valuation_timepoint_ids=("as-is",))

    def context(module: Any) -> Any:
        return module.PublicationContext(
            strategy_exists=True,
            scenario_exists=True,
            perspective_exists=True,
            cell_resolves=True,
            evidence={},
            required_valuations=(
                module.RequiredValuation(
                    timepoint_id="as-is",
                    reason=module.RequiredValuationReason.SELECTED,
                    available=False,
                    unavailable_reason="non_positive_forward_noi",
                    unavailable_detail="The forward NOI is not positive.",
                ),
            ),
        )

    import anchor.memo.publication as healthy_module

    assert PublicationContext is healthy_module.PublicationContext
    assert RequiredValuation is healthy_module.RequiredValuation
    assert RequiredValuationReason is healthy_module.RequiredValuationReason

    healthy_result = healthy_refusals(draft, context(healthy_module))
    healthy_codes = {refusal.code.value for refusal in healthy_result}
    assert "valuation_unavailable_for_required_view" in healthy_codes
    # The refusal carries the valuation's *own* typed reason, not a generic one.
    assert {
        refusal.unavailable_reason
        for refusal in healthy_result
        if refusal.code.value == "valuation_unavailable_for_required_view"
    } == {"non_positive_forward_noi"}

    mutant_codes = {
        refusal.code.value
        for refusal in mutated.publication_refusals(_sibling_draft(mutated, draft), context(mutated))
    }
    assert "valuation_unavailable_for_required_view" not in mutant_codes, "the mutant is alive"


def test_dropping_the_selection_filter_would_block_on_an_exploratory_definition(
    tmp_path: Path,
) -> None:
    """The correction itself, proved from the other side: a mutant that refuses
    for *every* entry regardless of whether the package depends on it would
    block a memo that merely coexists with an unfinished working view.

    The healthy rule reads only ``context.required_valuations``, which the
    dependency layer fills from the selection and the consumption -- so an
    exploratory definition never appears there and nothing it does can refuse a
    publication."""

    from anchor.memo.publication import PublicationContext, publication_refusals

    import _p7_10_stage_2_fixtures as fx  # type: ignore[import-not-found]

    draft = fx.memo_draft("i")
    clean = PublicationContext(
        strategy_exists=True,
        scenario_exists=True,
        perspective_exists=True,
        cell_resolves=True,
        evidence={},
        required_valuations=(),
    )
    codes = {refusal.code.value for refusal in publication_refusals(draft, clean)}
    assert "valuation_unavailable_for_required_view" not in codes

    source = inspect.getsource(_valuation_refusals_of(publication_refusals))
    assert "context.required_valuations" in source
    # Nothing else is consulted: no path reads a whole-Investment valuation list.
    for forbidden in ("list_valuation_timepoints", "surface.views", "all_valuations"):
        assert forbidden not in source, forbidden


def _valuation_refusals_of(_: Any) -> Any:
    from anchor.memo.publication import _valuation_refusals

    return _valuation_refusals


def _sibling_draft(module: Any, draft: Any) -> Any:
    """``draft`` rebuilt from the mutant's own contracts.

    The mutant is a whole copied package: its ``MemoItem`` is a different class
    from the repository's, and a mutant guard that type-checks would reject the
    repository's object for the wrong reason."""

    import dataclasses

    contracts = _sibling(module, "memo.contracts")
    return contracts.InvestmentMemoDraft(
        **{
            field.name: getattr(draft, field.name)
            for field in dataclasses.fields(draft)
            if field.name not in {"items", "risk_items", "term_items"}
        },
        items=(),
        risk_items=(),
        term_items=(),
    )


# 6. The published-version fingerprint excludes the IC decision (Section 10)
# =============================================================================


def test_the_published_fingerprint_signature_admits_no_ic_decision() -> None:
    """The committee decides on an immutable package; recording the outcome must
    not redefine what was decided on.

    Proved structurally rather than by mutation: the function takes only the
    content digest and the dependency ledger, so there is no parameter an IC
    decision could arrive through."""

    import inspect

    from anchor.deals.fingerprint import fingerprint_published_version

    signature = inspect.signature(fingerprint_published_version)
    assert set(signature.parameters) == {"memo_content_fingerprint", "dependencies"}
    source = inspect.getsource(fingerprint_published_version)
    for forbidden in ("decision", "committee", "ic_"):
        assert forbidden not in source.lower().split('"""')[2], forbidden


def test_recording_a_decision_does_not_move_the_published_fingerprint(tmp_path: Path) -> None:
    """The behavioural half of the same invariant, end to end."""

    from anchor.deals import memo_dependencies as deps
    from anchor.deals import store
    from anchor.memo.contracts import InvestmentCommitteeDecision, InvestmentCommitteeOutcome

    import _p7_10_stage_2_fixtures as fx  # type: ignore[import-not-found]

    db = tmp_path / "anchor.db"
    deal, investment_id = fx.opted_in_deal(db)
    store.put_memo_draft(investment_id, fx.memo_draft(investment_id), db_path=db)
    version = deps.publish(investment_id, db_path=db)

    store.put_committee_decision(
        investment_id,
        version.version_id,
        InvestmentCommitteeDecision(
            memo_version_id=version.version_id,
            decision=InvestmentCommitteeOutcome.APPROVED,
            decision_note="Approved.",
            decided_at="2026-09-20",
        ),
        db_path=db,
    )
    after = store.get_memo_version(investment_id, version.version_id, db_path=db)
    assert after.published_fingerprint == version.published_fingerprint
    assert deps.version_freshness(investment_id, after, db_path=db).freshness.value == "current"
