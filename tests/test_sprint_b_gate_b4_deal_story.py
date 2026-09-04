"""Sprint B Gate B4 -- AI Deal Story.

The One-Page Owner Summary gains a concise, owner-level AI interpretation:
``DealStory`` (``anchor.ai.contracts``), nested inside the existing
``AIAnalysis`` so that

  * one "Generate AI Analysis" click remains exactly one OpenAI call
    producing both the full analyst report and the Deal Story;
  * the Deal Story persists, restores, invalidates, duplicates, and has its
    provenance validated through the *existing* ``ai_snapshot`` column and
    ``ai_context_fingerprint`` -- no new column, no new schema version, no
    parallel persistence system (Gate A6/A7 architecture reused verbatim);
  * a pre-B4 ``ai_snapshot`` still decodes, restores its full report, and
    simply shows no Deal Story until the analyst regenerates.

This file covers the Gate B4 required backend test list end to end:
contract validity and caps, nullable ``model_gap``, both Quick and Detailed
context paths reaching the same shared contract, the Deal Context trust
boundary, Owner Return Metrics reaching the Deal Story's evidence, the
refinance model-gap instruction, the absence of any new financial
calculation, and the full persistence matrix (save/restore for both modes,
restart, financial invalidation, Deal Context invalidation, stale
provenance rejection, legacy snapshot safety, corrupt snapshot never
blocking Deal Open).

Every test uses a fake provider or a patched generator -- never the real
``openai`` SDK, never a network call, never any API spend.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import sqlite3
from pathlib import Path
from typing import Any, get_type_hints

import pytest
from fastapi.testclient import TestClient

from anchor import api as api_module
from anchor.ai import build_analysis_context, build_detailed_analysis_context
from anchor.ai.analyst import generate_ai_analysis, generate_detailed_ai_analysis
from anchor.ai.contracts import AIAnalysis, DealStory
from anchor.ai.prompts import build_system_prompt, build_user_prompt
from anchor.ai.provider import AI_ANALYSIS_JSON_SCHEMA
from anchor.contracts import AcquisitionInputs, AcquisitionTerms, DetailedOperatingInputs
from anchor.deals import SnapshotValidationError
from anchor.deals import store as deals_store
from anchor.deals.fingerprint import (
    fingerprint_ai,
    fingerprint_detailed_inputs,
    fingerprint_quick_inputs,
)
from anchor.deals.store import _dataclass_from_json

# =============================================================================
# Fixtures -- the same golden Quick/Detailed pair the Gate A6/A7 snapshot
# tests use, so persistence behavior here is directly comparable to theirs.
# =============================================================================

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

QUICK_PAYLOAD: dict[str, Any] = {
    "purchase_price": 10_000_000.0,
    "current_noi": 600_000.0,
    "occupancy": 0.95,
    "noi_growth": 0.03,
    "hold_period": 5,
    "exit_cap_rate": 0.065,
    "ltv": 0.60,
    "interest_rate": 0.05,
    "amortization": 30,
    "acquisition_cost_pct": 0.02,
    "financing_fee_pct": 0.01,
    "disposition_cost_pct": 0.025,
    "annual_capex_reserve": 50_000.0,
    "io_period": 2,
}
OTHER_QUICK_PAYLOAD = {**QUICK_PAYLOAD, "purchase_price": 25_000_000.0}

DETAILED_TERMS_PAYLOAD: dict[str, Any] = {
    "purchase_price": 10_000_000.0,
    "hold_period": 5,
    "exit_cap_rate": 0.065,
    "ltv": 0.60,
    "interest_rate": 0.05,
    "amortization": 30,
    "acquisition_cost_pct": 0.02,
    "financing_fee_pct": 0.01,
    "disposition_cost_pct": 0.025,
    "annual_capex_reserve": 50_000.0,
    "io_period": 2,
}
OTHER_DETAILED_TERMS_PAYLOAD = {**DETAILED_TERMS_PAYLOAD, "purchase_price": 25_000_000.0}

DETAILED_OPERATING_PAYLOAD: dict[str, Any] = {
    "gross_potential_rent": 800_000.0,
    "other_income": 20_000.0,
    "vacancy_credit_loss_pct": 0.05,
    "property_taxes": 60_000.0,
    "insurance": 20_000.0,
    "utilities": 25_000.0,
    "repairs_maintenance": 20_000.0,
    "other_operating_expenses": 16_000.0,
    "management_fee_pct": 0.05,
    "revenue_growth": 0.03,
    "expense_growth": 0.03,
}

DEAL_STORY = DealStory(
    investment_view=(
        "Coverage and recurring distributions support the stated income focus, "
        "but the modeled levered IRR sits below the supplied hurdle."
    ),
    key_strengths=("Year 1 DSCR is labeled above its supplied target.",),
    key_risks=("Levered IRR is labeled below its supplied target.",),
    model_gap=None,
)

AI_ANALYSIS = AIAnalysis(
    executive_summary="Five-year hold with moderate leverage.",
    investment_view="Return profile clears the supplied hurdles at baseline.",
    strengths=("Levered IRR clears the target hurdle.",),
    risks=("Exit cap rate expansion compresses returns.",),
    return_drivers=("NOI growth",),
    downside_analysis="Levered IRR remains positive across the tested range.",
    capital_structure_analysis="Leverage produces adequate Year 1 DSCR.",
    break_even_analysis="Break-even was found within the tested range.",
    questions_to_investigate=("What is the in-place rent roll composition?",),
    confidence_notes=("No tenant credit data was supplied.",),
    deal_story=DEAL_STORY,
)

# The exact ``ai_snapshot`` JSON a pre-Gate-B4 build persisted: the ten
# report fields, and no ``deal_story`` key at all.
LEGACY_AI_ANALYSIS_DICT: dict[str, Any] = {
    "executive_summary": "Five-year hold with moderate leverage.",
    "investment_view": "Return profile clears the supplied hurdles at baseline.",
    "strengths": ["Levered IRR clears the target hurdle."],
    "risks": ["Exit cap rate expansion compresses returns."],
    "return_drivers": ["NOI growth"],
    "downside_analysis": "Levered IRR remains positive across the tested range.",
    "capital_structure_analysis": "Leverage produces adequate Year 1 DSCR.",
    "break_even_analysis": "Break-even was found within the tested range.",
    "questions_to_investigate": ["What is the in-place rent roll composition?"],
    "confidence_notes": ["No tenant credit data was supplied."],
}


def _as_json_dict(value: object) -> dict[str, Any]:
    """Emulate a genuine HTTP JSON round-trip (tuples -> lists), exactly as
    the Gate A6/A7 snapshot tests do."""

    return json.loads(json.dumps(dataclasses.asdict(value)))


AI_ANALYSIS_DICT = _as_json_dict(AI_ANALYSIS)
DEAL_STORY_DICT = _as_json_dict(DEAL_STORY)

REFINANCE_CONTEXT = (
    "Value-add strategy. Improve NOI, refinance in Year 5 to return a portion "
    "of equity, then continue holding long term."
)
INCOME_CONTEXT = (
    "Long-term hold. Prioritize recurring cash yield and capital preservation "
    "over maximum IRR."
)

TARGETS: dict[str, float] = {
    "target_levered_irr": 0.10,
    "target_equity_multiple": 1.50,
    "target_headline_dscr": 1.20,
}


class _FakeProvider:
    """Records the prompts it is handed and returns a canned ``AIAnalysis``
    -- never touches the network."""

    def __init__(self, analysis: AIAnalysis = AI_ANALYSIS) -> None:
        self.analysis = analysis
        self.calls: list[dict[str, str]] = []

    def generate_analysis(self, *, system_prompt: str, user_prompt: str) -> AIAnalysis:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self.analysis


def _evidence_payload(context: Any) -> dict[str, Any]:
    """The JSON evidence block of a built user prompt, parsed back out."""

    prompt = build_user_prompt(context)
    return json.loads(prompt[prompt.index("{") :])


def _deal_story_prompt_block() -> str:
    prompt = build_system_prompt()
    return prompt[prompt.index("DEAL STORY (the nested") :]


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test-anchor.db"


@pytest.fixture()
def client(db_path: Path) -> Any:
    """A TestClient bound to a throwaway SQLite file, mirroring the Gate
    A6/A7 fixtures."""

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("ANCHOR_DB_PATH", str(db_path))
        yield TestClient(api_module.app)


def _create_quick_deal(client: TestClient, *, deal_context: str | None = None) -> str:
    body: dict[str, Any] = {"name": "Quick Deal", "inputs": QUICK_PAYLOAD}
    if deal_context is not None:
        body["deal_context"] = deal_context
    response = client.post("/deals", json=body)
    assert response.status_code == 200
    return response.json()["id"]


def _create_detailed_deal(client: TestClient, *, deal_context: str | None = None) -> str:
    body: dict[str, Any] = {
        "name": "Detailed Deal",
        "operating_mode": "detailed",
        "terms": DETAILED_TERMS_PAYLOAD,
        "detailed_operating_inputs": DETAILED_OPERATING_PAYLOAD,
    }
    if deal_context is not None:
        body["deal_context"] = deal_context
    response = client.post("/deals", json=body)
    assert response.status_code == 200
    return response.json()["id"]


def _quick_ai_fingerprint(deal_context: str | None) -> str:
    return fingerprint_ai(
        analysis_fingerprint=fingerprint_quick_inputs(QUICK_INPUTS), deal_context=deal_context
    )


def _detailed_ai_fingerprint(deal_context: str | None) -> str:
    return fingerprint_ai(
        analysis_fingerprint=fingerprint_detailed_inputs(
            DETAILED_TERMS, DETAILED_OPERATING_INPUTS
        ),
        deal_context=deal_context,
    )


def _attach_ai_snapshot(
    client: TestClient,
    deal_id: str,
    fingerprint: str,
    snapshot: dict[str, Any] | None = None,
) -> Any:
    return client.put(
        f"/deals/{deal_id}/ai-snapshot",
        json={
            "ai_snapshot": snapshot if snapshot is not None else AI_ANALYSIS_DICT,
            "ai_context_fingerprint": fingerprint,
        },
    )


# =============================================================================
# 1-4. Contract validity, caps, nullability
# =============================================================================


def test_deal_story_contract_validates() -> None:
    """Required test 1."""

    story = DealStory(
        investment_view="A concise, decision-oriented owner view.",
        key_strengths=("Coverage is strong.", "Distributions are durable."),
        key_risks=("Return sits below its hurdle.", "Exit cap sensitivity is material."),
        model_gap="The stated refinance is not modeled.",
    )

    assert story.investment_view.startswith("A concise")
    assert len(story.key_strengths) == 2
    assert len(story.key_risks) == 2
    assert story.model_gap == "The stated refinance is not modeled."


def test_deal_story_enforces_the_maximum_number_of_strengths() -> None:
    """Required test 2."""

    with pytest.raises(ValueError, match="key_strengths"):
        DealStory(
            investment_view="View.",
            key_strengths=("One.", "Two.", "Three."),
            key_risks=(),
            model_gap=None,
        )


def test_deal_story_enforces_the_maximum_number_of_risks() -> None:
    """Required test 3."""

    with pytest.raises(ValueError, match="key_risks"):
        DealStory(
            investment_view="View.",
            key_strengths=(),
            key_risks=("One.", "Two.", "Three."),
            model_gap=None,
        )


def test_deal_story_model_gap_is_nullable() -> None:
    """Required test 4 -- ``None`` is a first-class value, never a filler
    sentence manufactured to fill the field."""

    story = DealStory(investment_view="View.", key_strengths=(), key_risks=(), model_gap=None)

    assert story.model_gap is None


# =============================================================================
# 5-6, 12, 16 -- generation architecture, shared across Quick and Detailed
# =============================================================================


def test_quick_context_generates_a_deal_story_through_one_provider_call() -> None:
    """Required tests 5 and 12: a Quick AI request produces the full report
    AND the Deal Story from ONE provider call -- the user never pays for a
    second LLM request to populate the Owner Summary."""

    provider = _FakeProvider()
    analysis = generate_ai_analysis(QUICK_INPUTS, provider=provider, **TARGETS)

    assert len(provider.calls) == 1
    assert analysis.deal_story == DEAL_STORY
    assert analysis.executive_summary == AI_ANALYSIS.executive_summary


def test_detailed_context_generates_the_same_deal_story_contract() -> None:
    """Required tests 6 and 16: Detailed uses the identical contract, the
    identical prompt rules, and the identical single-call architecture --
    there is no separate Quick/Detailed AI product."""

    provider = _FakeProvider()
    analysis = generate_detailed_ai_analysis(
        DETAILED_TERMS, DETAILED_OPERATING_INPUTS, provider=provider, **TARGETS
    )

    assert len(provider.calls) == 1
    assert isinstance(analysis.deal_story, DealStory)
    assert analysis.deal_story == DEAL_STORY


def test_quick_and_detailed_send_the_identical_deal_story_instructions() -> None:
    quick_provider = _FakeProvider()
    detailed_provider = _FakeProvider()
    generate_ai_analysis(QUICK_INPUTS, provider=quick_provider, **TARGETS)
    generate_detailed_ai_analysis(
        DETAILED_TERMS, DETAILED_OPERATING_INPUTS, provider=detailed_provider, **TARGETS
    )

    assert (
        quick_provider.calls[0]["system_prompt"] == detailed_provider.calls[0]["system_prompt"]
    )


def test_one_structured_schema_carries_both_the_report_and_the_deal_story() -> None:
    """Required test 12 (schema level): the provider asks for both in a
    single strict structured response."""

    properties = AI_ANALYSIS_JSON_SCHEMA["properties"]

    assert "deal_story" in properties
    assert "deal_story" in AI_ANALYSIS_JSON_SCHEMA["required"]
    assert properties["deal_story"]["type"] == "object"
    assert "executive_summary" in properties


def test_deal_story_prompt_instructions_are_present_and_dedicated() -> None:
    prompt = build_system_prompt()

    assert "DEAL STORY (the nested" in prompt
    assert "deal_story.investment_view" in prompt
    assert "deal_story.key_strengths" in prompt
    assert "deal_story.key_risks" in prompt
    assert "deal_story.model_gap" in prompt


def test_deal_story_prompt_states_explicit_length_constraints() -> None:
    """B4.17 -- explicit length constraints, so the owner surface stays a
    20-30 second read rather than a second IC memo."""

    prompt = build_system_prompt()

    assert "at most 60 words" in prompt
    assert "at most 2 items, at most 30 words each" in prompt
    assert "at most 40 words" in prompt


def test_deal_story_prompt_reuses_rather_than_duplicates_the_system_prompt() -> None:
    """B4.17 -- the dedicated block says what the surface is for; it does
    not restate the grounding/Deal-Context rules that already apply."""

    block = _deal_story_prompt_block()

    assert "Every rule above applies unchanged" in block
    assert "GROUNDING RULES (mandatory)" not in block
    assert "DEAL CONTEXT RULES" not in block


# =============================================================================
# 7. Deal Context remains user-authored / unverified
# =============================================================================


def test_deal_context_remains_labeled_user_authored_and_unverified() -> None:
    """Required test 7 -- Gate A4's trust boundary is unchanged by B4. The
    Deal Story block adds no permission to restate Deal Context as fact."""

    prompt = build_system_prompt()

    assert "DEAL CONTEXT RULES" in prompt
    assert "user-authored free text" in prompt
    assert "never as a fact you may restate as" in prompt


def test_deal_story_block_never_promotes_deal_context_to_evidence() -> None:
    """The Deal Story instructions speak of the *stated* strategy
    throughout -- never of a verified market or property fact."""

    block = _deal_story_prompt_block()

    assert "never restate the stated strategy as established fact" in block
    assert "never a strength you" in block
    assert "Never an external market risk the" in block


def test_deal_context_reaches_the_evidence_payload_without_being_relabeled() -> None:
    payload = _evidence_payload(
        build_analysis_context(QUICK_INPUTS, deal_context=INCOME_CONTEXT, **TARGETS)
    )

    assert payload["deal_context"] == INCOME_CONTEXT
    # Deal Context is structurally separate from every deterministic section.
    assert "deal_context" not in payload["base_results"]
    assert "deal_context" not in payload["base_inputs"]


# =============================================================================
# 8. Owner Return Metrics reach the Deal Story's evidence
# =============================================================================

OWNER_RETURN_METRIC_FIELDS = (
    "levered_cash_on_cash_by_year",
    "unlevered_cash_yield_by_year",
    "cumulative_operating_distributions_by_year",
    "year_1_debt_yield",
)


@pytest.mark.parametrize("field_name", OWNER_RETURN_METRIC_FIELDS)
def test_owner_return_metrics_reach_the_deal_story_context_quick(field_name: str) -> None:
    """Required test 8 -- the Deal Story reads the SAME evidence payload the
    full report reads (there is only one), so every Owner Return Metric is
    already available to it. Nothing new is computed for the Deal Story."""

    payload = _evidence_payload(
        build_analysis_context(QUICK_INPUTS, deal_context=INCOME_CONTEXT, **TARGETS)
    )

    assert field_name in payload["base_results"]


@pytest.mark.parametrize("field_name", OWNER_RETURN_METRIC_FIELDS)
def test_owner_return_metrics_reach_the_deal_story_context_detailed(field_name: str) -> None:
    payload = _evidence_payload(
        build_detailed_analysis_context(
            DETAILED_TERMS, DETAILED_OPERATING_INPUTS, deal_context=INCOME_CONTEXT, **TARGETS
        )
    )

    assert field_name in payload["base_results"]


# =============================================================================
# 9. No financial calculation introduced
# =============================================================================


def test_deal_story_contract_module_imports_no_math() -> None:
    """Required test 9 -- the AI contracts module still reproduces no
    financial formula. The Deal Story is prose about numbers the engine
    already produced."""

    from anchor.ai import contracts as contracts_module

    tree = ast.parse(Path(contracts_module.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert "math" not in imported


def test_deal_story_declares_no_numeric_field() -> None:
    hints = get_type_hints(DealStory)
    field_hints = {hints[field.name] for field in dataclasses.fields(DealStory)}

    assert field_hints == {str, str | None, tuple[str, ...]}


def test_deal_story_generation_calls_no_extra_engine_entry_point() -> None:
    """Adding the Deal Story did not introduce a second analyze /
    sensitivity / break-even run -- one context assembly, as before."""

    from anchor.engine import analyze_acquisition as engine_analyze

    calls: list[str] = []

    def _counting_analyze(inputs: AcquisitionInputs) -> Any:
        calls.append("analyze")
        return engine_analyze(inputs)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("anchor.ai.analyst.analyze_acquisition", _counting_analyze)
        generate_ai_analysis(QUICK_INPUTS, provider=_FakeProvider(), **TARGETS)

    assert calls == ["analyze"]


# =============================================================================
# 10. Refinance context produces a model-gap instruction
# =============================================================================


def test_refinance_context_produces_a_model_gap_instruction() -> None:
    """Required test 10 -- the instruction set explicitly names the
    refinance case and forbids inventing its economics."""

    block = _deal_story_prompt_block()

    assert "refinance" in block
    assert "not modeled in Anchor's current" in block
    assert "never manufacture a" in block
    assert "refinance proceeds" in block


def test_refinance_deal_context_is_carried_verbatim_into_the_evidence() -> None:
    context = build_analysis_context(QUICK_INPUTS, deal_context=REFINANCE_CONTEXT, **TARGETS)

    assert REFINANCE_CONTEXT in build_user_prompt(context)


def test_a_refinance_model_gap_persists_and_restores(client: TestClient) -> None:
    """The showcase case end to end: a Deal Story whose ``model_gap`` names
    the unmodeled refinance survives save and reopen."""

    story = dataclasses.replace(
        DEAL_STORY,
        model_gap=(
            "The stated refinance-and-hold strategy is not modeled in Anchor's "
            "current deterministic cash flows, which assume a terminal sale."
        ),
    )
    snapshot = dict(AI_ANALYSIS_DICT, deal_story=_as_json_dict(story))
    deal_id = _create_quick_deal(client, deal_context=REFINANCE_CONTEXT)

    attached = _attach_ai_snapshot(
        client, deal_id, _quick_ai_fingerprint(REFINANCE_CONTEXT), snapshot=snapshot
    )
    assert attached.status_code == 200

    restored = client.get(f"/deals/{deal_id}").json()["ai_snapshot"]["deal_story"]
    assert "not modeled" in restored["model_gap"]


# =============================================================================
# 11. Empty context remains valid
# =============================================================================


def test_no_deal_context_still_produces_a_valid_deal_story_request() -> None:
    """Required test 11 -- the Deal Story must work with no stated
    strategy at all; ``model_gap`` is simply ``None`` in that case."""

    provider = _FakeProvider()
    analysis = generate_ai_analysis(QUICK_INPUTS, deal_context=None, provider=provider, **TARGETS)

    payload_text = provider.calls[0]["user_prompt"]
    payload = json.loads(payload_text[payload_text.index("{") :])
    assert "deal_context" not in payload
    assert analysis.deal_story is not None


def test_empty_deal_story_lists_are_valid() -> None:
    story = DealStory(
        investment_view="Only one thing matters here.",
        key_strengths=(),
        key_risks=(),
        model_gap=None,
    )

    assert story.key_strengths == ()
    assert story.key_risks == ()


# =============================================================================
# 13-15. Persistence: saved Quick / saved Detailed / restart
# =============================================================================


def test_saved_quick_deal_story_persists_and_restores(client: TestClient) -> None:
    """Required test 13."""

    deal_id = _create_quick_deal(client)

    assert _attach_ai_snapshot(client, deal_id, _quick_ai_fingerprint(None)).status_code == 200

    reopened = client.get(f"/deals/{deal_id}")
    assert reopened.status_code == 200
    assert reopened.json()["ai_snapshot"]["deal_story"] == DEAL_STORY_DICT


def test_saved_detailed_deal_story_persists_and_restores(client: TestClient) -> None:
    """Required test 14."""

    deal_id = _create_detailed_deal(client)

    assert _attach_ai_snapshot(client, deal_id, _detailed_ai_fingerprint(None)).status_code == 200

    reopened = client.get(f"/deals/{deal_id}")
    assert reopened.status_code == 200
    assert reopened.json()["ai_snapshot"]["deal_story"] == DEAL_STORY_DICT


def test_deal_story_survives_a_backend_restart(db_path: Path) -> None:
    """Required test 15 -- a fresh TestClient over the same SQLite file:
    the Deal Story is genuinely durable, not in-memory state."""

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("ANCHOR_DB_PATH", str(db_path))
        first = TestClient(api_module.app)
        deal_id = _create_quick_deal(first)
        assert _attach_ai_snapshot(first, deal_id, _quick_ai_fingerprint(None)).status_code == 200

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("ANCHOR_DB_PATH", str(db_path))
        second = TestClient(api_module.app)
        reopened = second.get(f"/deals/{deal_id}")

    assert reopened.status_code == 200
    assert reopened.json()["ai_snapshot"]["deal_story"] == DEAL_STORY_DICT


def test_duplicating_a_deal_copies_its_deal_story(client: TestClient) -> None:
    """Duplicate behavior follows the existing AI snapshot convention --
    the Deal Story rides along because it lives inside ``ai_snapshot``."""

    deal_id = _create_quick_deal(client)
    assert _attach_ai_snapshot(client, deal_id, _quick_ai_fingerprint(None)).status_code == 200

    duplicated = client.post(f"/deals/{deal_id}/duplicate")

    assert duplicated.status_code == 200
    assert duplicated.json()["ai_snapshot"]["deal_story"] == DEAL_STORY_DICT


# =============================================================================
# 16-17. Invalidation
# =============================================================================


def test_a_financial_change_invalidates_the_deal_story(client: TestClient) -> None:
    """Required test 16 -- a changed assumption makes the whole AI snapshot
    (Deal Story included) stop matching its provenance fingerprint, so it is
    never returned again."""

    deal_id = _create_quick_deal(client)
    assert _attach_ai_snapshot(client, deal_id, _quick_ai_fingerprint(None)).status_code == 200

    updated = client.put(
        f"/deals/{deal_id}", json={"name": "Quick Deal", "inputs": OTHER_QUICK_PAYLOAD}
    )

    assert updated.status_code == 200
    assert updated.json()["ai_snapshot"] is None
    assert client.get(f"/deals/{deal_id}").json()["ai_snapshot"] is None


def test_a_deal_context_change_invalidates_the_deal_story(client: TestClient) -> None:
    """Required test 17 -- Deal Context is part of the AI fingerprint, so
    editing the stated strategy invalidates the Deal Story that interpreted
    it, while the deterministic analysis snapshot is untouched."""

    deal_id = _create_quick_deal(client, deal_context=INCOME_CONTEXT)
    assert (
        _attach_ai_snapshot(client, deal_id, _quick_ai_fingerprint(INCOME_CONTEXT)).status_code
        == 200
    )
    assert client.get(f"/deals/{deal_id}").json()["ai_snapshot"] is not None

    updated = client.put(
        f"/deals/{deal_id}",
        json={
            "name": "Quick Deal",
            "inputs": QUICK_PAYLOAD,
            "deal_context": REFINANCE_CONTEXT,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["ai_snapshot"] is None


def test_a_financial_change_invalidates_a_detailed_deal_story(client: TestClient) -> None:
    deal_id = _create_detailed_deal(client)
    assert _attach_ai_snapshot(client, deal_id, _detailed_ai_fingerprint(None)).status_code == 200

    updated = client.put(
        f"/deals/{deal_id}",
        json={
            "name": "Detailed Deal",
            "operating_mode": "detailed",
            "terms": OTHER_DETAILED_TERMS_PAYLOAD,
            "detailed_operating_inputs": DETAILED_OPERATING_PAYLOAD,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["ai_snapshot"] is None


# =============================================================================
# 18. Stale provenance rejected
# =============================================================================


def test_a_deal_story_carrying_stale_provenance_is_rejected(client: TestClient) -> None:
    """Required test 18 -- a Deal Story generated under one stated strategy
    can never be relabeled as current for another."""

    deal_id = _create_quick_deal(client, deal_context=INCOME_CONTEXT)

    stale = _attach_ai_snapshot(client, deal_id, _quick_ai_fingerprint(REFINANCE_CONTEXT))

    assert stale.status_code == 422
    assert client.get(f"/deals/{deal_id}").json()["ai_snapshot"] is None


def test_a_deal_story_from_other_assumptions_is_rejected(client: TestClient) -> None:
    deal_id = _create_quick_deal(client)
    other_fingerprint = fingerprint_ai(
        analysis_fingerprint=fingerprint_quick_inputs(
            dataclasses.replace(QUICK_INPUTS, purchase_price=25_000_000.0)
        ),
        deal_context=None,
    )

    rejected = _attach_ai_snapshot(client, deal_id, other_fingerprint)

    assert rejected.status_code == 422


# =============================================================================
# 19-20. Legacy and corrupt AI snapshots
# =============================================================================


def test_a_legacy_pre_b4_ai_snapshot_still_restores_its_full_report(client: TestClient) -> None:
    """Required test 19 -- a snapshot written before ``deal_story`` existed
    decodes cleanly, keeps its full analyst report, and simply reports no
    Deal Story. Nothing is lost and nothing is fabricated."""

    deal_id = _create_quick_deal(client)

    attached = _attach_ai_snapshot(
        client, deal_id, _quick_ai_fingerprint(None), snapshot=LEGACY_AI_ANALYSIS_DICT
    )
    assert attached.status_code == 200

    snapshot = client.get(f"/deals/{deal_id}").json()["ai_snapshot"]
    assert snapshot["executive_summary"] == LEGACY_AI_ANALYSIS_DICT["executive_summary"]
    assert snapshot["deal_story"] is None


def test_a_legacy_ai_snapshot_decodes_directly_in_the_store_layer() -> None:
    """The same guarantee at the layer that owns it -- decoding a pre-B4
    JSON shape is a supported path, not an accident of the API."""

    analysis = _dataclass_from_json(AIAnalysis, LEGACY_AI_ANALYSIS_DICT)

    assert isinstance(analysis, AIAnalysis)
    assert analysis.deal_story is None
    assert analysis.strengths == ("Levered IRR clears the target hurdle.",)


def test_a_corrupt_ai_snapshot_never_blocks_deal_open(
    client: TestClient, db_path: Path
) -> None:
    """Required test 20 -- an unreadable cached AI artifact is treated as
    absent, never surfaced and never fatal. Deal Open keeps working."""

    deal_id = _create_quick_deal(client)
    assert _attach_ai_snapshot(client, deal_id, _quick_ai_fingerprint(None)).status_code == 200

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE deals SET ai_snapshot = ? WHERE id = ?",
            ('{"deal_story": {"investment_view": ', deal_id),
        )
        connection.commit()
    finally:
        connection.close()

    reopened = client.get(f"/deals/{deal_id}")

    assert reopened.status_code == 200
    assert reopened.json()["ai_snapshot"] is None
    assert reopened.json()["inputs"]["purchase_price"] == 10_000_000.0


def test_a_deal_story_of_the_wrong_shape_is_rejected_on_write(client: TestClient) -> None:
    """A malformed Deal Story supplied by a caller is a 422 on the write
    path -- never silently dropped, never silently persisted (the read path
    stays forgiving; only fresh caller input is strict)."""

    deal_id = _create_quick_deal(client)
    malformed = dict(AI_ANALYSIS_DICT, deal_story={"investment_view": "only this field"})

    rejected = _attach_ai_snapshot(
        client, deal_id, _quick_ai_fingerprint(None), snapshot=malformed
    )

    assert rejected.status_code == 422


def test_an_over_long_deal_story_is_rejected_on_write(client: TestClient) -> None:
    """The contract cap is enforced at the persistence boundary too -- the
    provider trims a chatty model, but a hand-crafted payload cannot bypass
    the cap the Owner Summary depends on."""

    deal_id = _create_quick_deal(client)
    over_long = dict(
        AI_ANALYSIS_DICT,
        deal_story=dict(DEAL_STORY_DICT, key_risks=["One.", "Two.", "Three."]),
    )

    rejected = _attach_ai_snapshot(client, deal_id, _quick_ai_fingerprint(None), snapshot=over_long)

    assert rejected.status_code == 422


def test_store_layer_rejects_an_over_long_deal_story_snapshot() -> None:
    over_long = dict(
        AI_ANALYSIS_DICT,
        deal_story=dict(DEAL_STORY_DICT, key_strengths=["One.", "Two.", "Three."]),
    )

    with pytest.raises(SnapshotValidationError):
        _dataclass_from_json(AIAnalysis, over_long)


# =============================================================================
# Architecture -- no new persistence system, no second AI workflow
# =============================================================================


def test_gate_b4_adds_no_new_snapshot_column() -> None:
    """The Deal Story reuses ``ai_snapshot`` wholesale: no ``deal_story``
    column, no second fingerprint, no second schema version."""

    source = Path(deals_store.__file__).read_text(encoding="utf-8")

    assert "deal_story_snapshot" not in source
    assert "deal_story_fingerprint" not in source
    assert '("ai_snapshot", "TEXT")' in source


def test_gate_b4_adds_no_second_ai_endpoint() -> None:
    """B4.14: no second, confusing AI-generation workflow -- ``/ai/analysis``
    remains the only route that produces AI output, and it now returns the
    Deal Story too."""

    source = Path(api_module.__file__).read_text(encoding="utf-8")

    assert source.count('@app.post("/ai/') == 1
    assert "deal-story" not in source
