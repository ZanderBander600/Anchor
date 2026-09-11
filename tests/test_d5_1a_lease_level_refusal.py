"""D5.1A -- the behavioural half: ``lease_level`` parses, and is refused.

``tests/test_d5_1a_operating_mode_total_dispatch.py`` proves the *shape* of
dispatch is total. This file proves what that shape buys, through the running
application:

1. **The 422 matrix.** Every mode-aware endpoint refuses ``"lease_level"``, and
   -- the assertion that actually matters -- refuses it *without* returning
   Quick or Detailed economics. A 200 carrying Quick numbers under a
   Lease-Level label is the exact failure HD-D4-9 deferred publication to avoid.
2. **Unparseable vs unsupported.** ``"leaselevel"`` is not a mode;
   ``"lease_level"`` is a mode this endpoint does not serve. Two different
   facts, two different messages. Collapsing them would tell a caller that
   ``"lease_level"`` is not a mode, which stopped being true at D5.1A.
3. **Quick and Detailed are untouched**, endpoint by endpoint.
4. **The domain layers refuse too** -- ``Deal``, ``duplicate_deal``,
   ``AnalysisContext`` and ``build_presentation_payload`` -- so safety does not
   depend on the API being the only door.
5. **Mutation kills.** Each named mutant from the D5.1A charter is applied and
   shown to be caught, rather than merely asserted to be impossible.

Every Lease-Level capability remains owned by a later gate: D5.2 parsing, D5.3
analysis, D5.4 persistence, D5.8 AI. Nothing here makes any of them reachable.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from anchor.ai.contracts import AnalysisContext
from anchor.ai.presentation import build_presentation_payload
from anchor.api import app
from anchor.contracts import OperatingMode, UnsupportedOperatingModeError
from anchor.deals import store as deals_store
from anchor.deals.contracts import Deal

_ANCHOR_DIR = Path(__file__).resolve().parents[1] / "src" / "anchor"

QUICK_INPUTS: dict[str, Any] = {
    "purchase_price": 10_000_000,
    "current_noi": 600_000,
    "occupancy": 0.95,
    "noi_growth": 0.03,
    "hold_period": 5,
    "exit_cap_rate": 0.065,
    "ltv": 0.60,
    "interest_rate": 0.05,
    "amortization": 30,
}

TERMS: dict[str, Any] = {
    "purchase_price": 10_000_000,
    "hold_period": 5,
    "exit_cap_rate": 0.065,
    "ltv": 0.60,
    "interest_rate": 0.05,
    "amortization": 30,
    "acquisition_cost_pct": 0.02,
    "financing_fee_pct": 0.01,
    "disposition_cost_pct": 0.025,
    "annual_capex_reserve": 50_000,
    "io_period": 2,
}

DETAILED_OPERATING: dict[str, Any] = {
    "gross_potential_rent": 800_000,
    "other_income": 20_000,
    "vacancy_credit_loss_pct": 0.05,
    "property_taxes": 60_000,
    "insurance": 20_000,
    "utilities": 25_000,
    "repairs_maintenance": 20_000,
    "other_operating_expenses": 16_000,
    "management_fee_pct": 0.05,
    "revenue_growth": 0.03,
    "expense_growth": 0.03,
}

_HURDLES: dict[str, Any] = {
    "target_levered_irr": 0.10,
    "target_headline_dscr": 1.20,
    "target_equity_multiple": 1.50,
}

_AXES: dict[str, Any] = {
    "row_assumption": "exit_cap_rate",
    "row_values": [0.06, 0.065],
    "column_assumption": "interest_rate",
    "column_values": [0.05, 0.055],
    "metric": "levered_irr",
}

#: (method, path, extra body). The mode-aware endpoints that **still refuse**
#: Lease-Level, each given a body that is *otherwise completely valid* -- so a
#: refusal can only be about the mode, never about a missing field. That is what
#: makes "did not return Quick results" a meaningful assertion rather than an
#: accident of a broken payload.
#:
#: **Narrowed twice.** D5.3 wired ``/analyze`` and ``/sensitivity`` (and added
#: ``/sensitivity/one-way``); D5.4 wired the three deal endpoints. Each moved out
#: of this table into the gate that proves the far stronger property replacing
#: refusal -- that its numbers, or its persisted inputs, survive a round trip
#: against the deterministic pipeline.
#:
#: **Narrowed a third time.** D5.8 wired ``/ai/analysis`` and it moves out of
#: this table on exactly the same terms as its predecessors: the gate that
#: wires an endpoint owns proving the stronger property that replaces refusal.
#: See ``tests/test_d5_8_lease_level_ai_analyst.py``, which shows the endpoint
#: grounding a real Lease-Level analysis rather than declining to.
#:
#: What remains is what no gate in D5 will wire: presets and break-even are
#: permanently refused for Lease-Level -- no standardized preset bundle exists
#: for this mode, and guardrail G35 forbids a Lease-Level break-even.
#:
#: Those two refusals are *not* the same statement as "Lease-Level has no
#: sensitivity analysis". D5.7 ships analyst-directed one-way and two-way
#: Lease-Level sensitivity on its own endpoints; what ``/sensitivity/presets``
#: refuses is the fixed Quick/Detailed preset package, which this mode does not
#: have. D5.8's AI grounding makes that same distinction to the model.
ENDPOINTS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("post", "/sensitivity/presets", {"inputs": QUICK_INPUTS}),
    ("post", "/break-even", {"inputs": QUICK_INPUTS, **_HURDLES}),
)

#: Fields that only ever appear in a *successful* analysis. Their presence in a
#: refusal response would mean the endpoint computed and returned economics.
_RESULT_MARKERS = (
    "levered_irr",
    "unlevered_irr",
    "equity_multiple",
    "going_in_cap_rate",
    "loan_amount",
    "exit_value",
    "matrix",
    "financial_input_fingerprint",
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client whose deal store is a throwaway file, so the ``/deals`` rows in
    this module can never touch a developer's real ``data/anchor.db``."""

    monkeypatch.setenv("ANCHOR_DB_PATH", str(tmp_path / "d5-1a.db"))
    return TestClient(app)


def _call(client: TestClient, method: str, path: str, body: dict[str, Any]):
    return getattr(client, method)(path, json=body)


# =============================================================================
# 1. The Lease-Level 422 matrix
# =============================================================================


@pytest.mark.parametrize(
    ("method", "path", "body"), ENDPOINTS, ids=lambda v: v if isinstance(v, str) else ""
)
def test_lease_level_is_refused_by_every_mode_aware_endpoint(
    client: TestClient, method: str, path: str, body: dict[str, Any]
) -> None:
    response = _call(client, method, path, {**body, "operating_mode": "lease_level"})

    assert response.status_code == 422, (
        f"{method.upper()} {path} answered operating_mode='lease_level' with "
        f"{response.status_code}; no D5.1A endpoint implements Lease-Level"
    )


@pytest.mark.parametrize(
    ("method", "path", "body"), ENDPOINTS, ids=lambda v: v if isinstance(v, str) else ""
)
def test_a_refused_lease_level_request_never_carries_economics(
    client: TestClient, method: str, path: str, body: dict[str, Any]
) -> None:
    """The assertion HD-D4-9 actually existed for.

    A 422 alone is not the guarantee -- the guarantee is that the response does
    not contain an answer computed for a *different* mode. The bodies above are
    valid Quick payloads precisely so that a fallthrough would succeed and be
    visible here.
    """

    response = _call(client, method, path, {**body, "operating_mode": "lease_level"})
    text = response.text

    for marker in _RESULT_MARKERS:
        assert marker not in text, (
            f"{method.upper()} {path} refused Lease-Level but its response still "
            f"contains {marker!r} -- economics computed for another mode leaked "
            "into a Lease-Level refusal"
        )


@pytest.mark.parametrize(
    ("method", "path", "body"), ENDPOINTS, ids=lambda v: v if isinstance(v, str) else ""
)
def test_the_refusal_names_the_mode_and_the_endpoint(
    client: TestClient, method: str, path: str, body: dict[str, Any]
) -> None:
    """The refusal must be the *unsupported* one, not the unparseable one."""

    response = _call(client, method, path, {**body, "operating_mode": "lease_level"})
    detail = str(response.json()["detail"])

    assert "lease_level" in detail
    assert "not supported by" in detail, (
        f"{method.upper()} {path} refused Lease-Level with the wrong error "
        f"class; expected an unsupported-mode refusal, got: {detail}"
    )


# =============================================================================
# 2. Unparseable vs. unsupported -- the distinction D5.1A must not collapse
# =============================================================================


def test_an_unknown_mode_token_is_still_an_invalid_enum(client: TestClient) -> None:
    response = client.post(
        "/analyze", json={**QUICK_INPUTS, "operating_mode": "leaselevel"}
    )
    # ``/analyze`` serves Lease-Level from D5.3, but an *unparseable* token
    # never reaches dispatch at all -- it fails at the mode gate, exactly as
    # before.

    assert response.status_code == 422
    detail = str(response.json()["detail"])
    assert "must be one of" in detail
    assert "leaselevel" in detail
    # The enumeration now advertises the published member.
    assert "lease_level" in detail


def test_valid_but_unsupported_is_a_different_message_from_unparseable(
    client: TestClient,
) -> None:
    """Both are 422; they must not be the *same* 422.

    Asserted on ``/break-even`` from D5.3: ``/analyze`` now *serves*
    Lease-Level, so it no longer produces an unsupported-mode refusal to
    compare against. The distinction under test is unchanged -- a mode that
    does not exist versus a real mode this endpoint does not serve -- and
    break-even is where that second case still lives (guardrail G35).
    """

    unsupported = client.post(
        "/break-even",
        json={"inputs": QUICK_INPUTS, **_HURDLES, "operating_mode": "lease_level"},
    )
    unparseable = client.post(
        "/break-even",
        json={"inputs": QUICK_INPUTS, **_HURDLES, "operating_mode": "leaselevel"},
    )

    assert unsupported.status_code == unparseable.status_code == 422

    unsupported_detail = str(unsupported.json()["detail"])
    unparseable_detail = str(unparseable.json()["detail"])

    assert unsupported_detail != unparseable_detail
    assert "not supported by" in unsupported_detail
    assert "not supported by" not in unparseable_detail
    assert "must be one of" in unparseable_detail
    assert "must be one of" not in unsupported_detail


def test_the_mode_parses_even_though_no_endpoint_serves_it() -> None:
    """Parsing a valid mode and supporting it are separate operations."""

    assert OperatingMode("lease_level") is OperatingMode.LEASE_LEVEL
    with pytest.raises(ValueError):
        OperatingMode("leaselevel")


# =============================================================================
# 3. Quick and Detailed are untouched
# =============================================================================


@pytest.mark.parametrize(
    ("method", "path", "body"),
    (
        ("post", "/analyze", dict(QUICK_INPUTS)),
        ("post", "/sensitivity", {"inputs": QUICK_INPUTS, **_AXES}),
        ("post", "/deals", {"name": "Quick deal", "inputs": QUICK_INPUTS}),
        ("post", "/deals/fingerprint", {"inputs": QUICK_INPUTS}),
        # Every remaining refusal-table endpoint. The ``/ai/analysis``
        # exclusion this line used to carry is gone with the entry itself:
        # a Quick AI request needs a provider, so it is exercised where the
        # provider can be injected rather than over a live TestClient.
        *ENDPOINTS,
    ),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_quick_requests_still_succeed(
    client: TestClient, method: str, path: str, body: dict[str, Any]
) -> None:
    """Absent ``operating_mode`` still means Quick, and still works.

    Keeps ``/analyze`` and ``/sensitivity`` in the sweep even though they left
    the refusal table: Quick must keep working on an endpoint that grew a new
    mode arm, which is the whole point of checking.
    """

    response = _call(client, method, path, body)
    assert response.status_code == 200, response.text


def _jsonish(value: Any) -> Any:
    """Normalise tuples to lists so an engine dataclass and a JSON response are
    directly comparable. Compared with ``==`` rather than ``approx``: the same
    engine ran on the same inputs, so anything short of bit-identity would
    itself be the regression."""

    if isinstance(value, dict):
        return {k: _jsonish(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonish(v) for v in value]
    return value


def test_quick_analyze_is_bit_identical_to_the_engine(client: TestClient) -> None:
    from anchor.engine import analyze_acquisition
    from anchor.validation import validate_acquisition_inputs

    response = client.post("/analyze", json=QUICK_INPUTS)

    assert response.status_code == 200
    expected = dataclasses.asdict(
        analyze_acquisition(validate_acquisition_inputs(QUICK_INPUTS))
    )
    assert response.json() == _jsonish(expected)


def test_detailed_analyze_is_bit_identical_to_the_engine(client: TestClient) -> None:
    from anchor.engine import analyze_detailed_acquisition_with_projection
    from anchor.validation import (
        validate_acquisition_terms,
        validate_detailed_operating_inputs,
    )

    response = client.post(
        "/analyze",
        json={
            "operating_mode": "detailed",
            "terms": TERMS,
            "detailed_operating_inputs": DETAILED_OPERATING,
        },
    )

    assert response.status_code == 200
    expected = dataclasses.asdict(
        analyze_detailed_acquisition_with_projection(
            validate_acquisition_terms(TERMS),
            validate_detailed_operating_inputs(DETAILED_OPERATING),
        )
    )
    assert response.json() == _jsonish(expected)


@pytest.mark.parametrize(
    ("path", "body"),
    (
        ("/sensitivity", {"terms": TERMS, "detailed_operating_inputs": DETAILED_OPERATING, **_AXES}),
        ("/sensitivity/presets", {"terms": TERMS, "detailed_operating_inputs": DETAILED_OPERATING}),
        ("/break-even", {"terms": TERMS, "detailed_operating_inputs": DETAILED_OPERATING, **_HURDLES}),
        ("/deals", {"name": "detailed", "terms": TERMS, "detailed_operating_inputs": DETAILED_OPERATING}),
        ("/deals/fingerprint", {"terms": TERMS, "detailed_operating_inputs": DETAILED_OPERATING}),
    ),
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_detailed_requests_still_succeed(
    client: TestClient, path: str, body: dict[str, Any]
) -> None:
    response = client.post(path, json={**body, "operating_mode": "detailed"})
    assert response.status_code == 200, response.text


def test_quick_and_detailed_deal_round_trips_are_unchanged(client: TestClient) -> None:
    quick = client.post(
        "/deals", json={"name": "Quick deal", "inputs": QUICK_INPUTS}
    ).json()
    detailed = client.post(
        "/deals",
        json={
            "name": "Detailed deal",
            "operating_mode": "detailed",
            "terms": TERMS,
            "detailed_operating_inputs": DETAILED_OPERATING,
        },
    ).json()

    assert quick["operating_mode"] == "quick"
    assert quick["inputs"] is not None and quick["terms"] is None
    assert detailed["operating_mode"] == "detailed"
    assert detailed["terms"] is not None and detailed["inputs"] is None

    for deal in (quick, detailed):
        duplicate = client.post(f"/deals/{deal['id']}/duplicate", json={})
        assert duplicate.status_code == 200, duplicate.text
        copy = duplicate.json()
        assert copy["operating_mode"] == deal["operating_mode"], (
            "duplication changed the deal's operating mode"
        )
        assert copy["id"] != deal["id"]
        assert copy["name"] == f"{deal['name']} (Copy)"


# =============================================================================
# 4. The domain layers refuse independently of the API
# =============================================================================


def _bypass_construct(cls, **fields):
    """Build a frozen, slotted instance without running ``__post_init__``.

    The narrowest technique that can reach a Lease-Level branch which is, by
    design, unreachable through the running application: ``Deal`` and
    ``AnalysisContext`` both *refuse to construct* the mode, which is precisely
    the behavior under test, so a normal constructor cannot produce the object a
    downstream consumer must also refuse. Nothing in production is faked or
    made more permissive to accommodate this.
    """

    instance = object.__new__(cls)
    for name, value in fields.items():
        object.__setattr__(instance, name, value)
    return instance


def test_a_lease_level_deal_cannot_borrow_another_modes_fields() -> None:
    """**Superseded at D5.4**, which gave Lease-Level its own persisted fields.

    Until then a Lease-Level ``Deal`` was unconstructible, and this asserted
    exactly that -- the safe holding state while there were no columns to hold a
    rent roll. D5.4 adds them, so the invariant becomes the one that outlives
    construction: a Lease-Level deal must carry its *own* five fields and none of
    the other modes'. Borrowing ``inputs`` or ``detailed_operating_inputs``
    would give the deal two answers to which engine underwrites it.
    """

    import datetime

    with pytest.raises(ValueError, match="must have 'terms'"):
        Deal(
            id="x",
            name="Lease-Level",
            operating_mode=OperatingMode.LEASE_LEVEL,
            inputs=None,
            terms=None,
            detailed_operating_inputs=None,
            deal_context=None,
            analysis_snapshot=None,
            ai_snapshot=None,
            created_at=datetime.datetime(2027, 1, 1),
            updated_at=datetime.datetime(2027, 1, 1),
        )


def test_a_lease_level_deal_is_never_duplicated_as_detailed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The latent defect this gate closed, still closed.

    Before D5.1A ``duplicate_deal`` was ``if QUICK: ... else: <Detailed copy>``,
    so a Lease-Level deal would have been silently rewritten into a *Detailed*
    one -- changing which engine later underwrites it. That is data corruption,
    not a wrong error message.

    **Superseded at D5.4**, which implements the real copy. The assertion that
    mattered is unchanged and is now the whole test: whatever ``duplicate_deal``
    does with a Lease-Level deal, it must not be a Quick or Detailed writer.
    """

    stub = _bypass_construct(
        Deal,
        id="ll-1",
        name="Lease-Level",
        operating_mode=OperatingMode.LEASE_LEVEL,
        inputs=None,
        terms=None,
        detailed_operating_inputs=None,
        property_inputs=None,
        operating_inputs=None,
        market_leasing=None,
        suites=None,
        leases=None,
        deal_context=None,
        analysis_snapshot=None,
        ai_snapshot=None,
        created_at=None,
        updated_at=None,
    )
    monkeypatch.setattr(deals_store, "get_deal", lambda *a, **k: stub)

    called: list[str] = []
    monkeypatch.setattr(
        deals_store,
        "create_detailed_deal",
        lambda *a, **k: called.append("detailed"),
    )
    monkeypatch.setattr(
        deals_store, "create_deal", lambda *a, **k: called.append("quick")
    )

    # The stub carries no rent roll, so the real Lease-Level writer refuses it.
    # Either outcome is acceptable; writing a *different mode* is not.
    with pytest.raises(Exception):
        deals_store.duplicate_deal("ll-1")

    assert called == [], (
        f"duplicate_deal created a {called} copy of a Lease-Level deal"
    )



class _FabricatedMode:
    """A mode that is not an ``OperatingMode`` member.

    Total dispatch means every arm is named and anything else is refused. That
    "anything else" needs a stand-in to be testable at all, and it needs a
    ``.value`` because ``UnsupportedOperatingModeError`` reports the mode by
    name. Deliberately not a real enum member: the point is that it is not one.
    """

    value = "fabricated_mode"

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "<fabricated_mode>"


_FABRICATED_MODE = _FabricatedMode()

def test_a_lease_level_ai_context_is_representable_but_still_validated() -> None:
    """D5.8 replaces D5.1A's refusal -- and keeps the invariant underneath it.

    D5.1A refused a Lease-Level ``AnalysisContext`` because the contract could
    not describe one honestly: ``sensitivities`` and ``break_even`` were
    required and typed to bundles this mode does not have. D5.8 made both
    optional and the mode is representable, so the refusal is gone.

    What must not be gone is the reason the refusal was safe: a context that
    cannot be described honestly is still refused. The body below is the exact
    one D5.1A used -- Lease-Level with nothing populated -- and it is still
    rejected, now by name rather than by mode.
    """

    with pytest.raises(ValueError) as excinfo:
        AnalysisContext(
            operating_mode=OperatingMode.LEASE_LEVEL,
            inputs=None,
            terms=None,
            detailed_operating_inputs=None,
            operating_projection=None,
            results=None,
            sensitivities=None,
            break_even=None,
            target_levered_irr=0.1,
            target_equity_multiple=1.5,
            target_headline_dscr=1.2,
            return_hurdle_metric=None,
            deal_context=None,
        )

    assert "LEASE_LEVEL" in str(excinfo.value)

    # And a mode the contract still cannot represent is still refused as one.
    with pytest.raises(UnsupportedOperatingModeError) as unsupported:
        AnalysisContext(
            operating_mode=_FABRICATED_MODE,  # type: ignore[arg-type]
            inputs=None,
            terms=None,
            detailed_operating_inputs=None,
            operating_projection=None,
            results=None,
            sensitivities=None,
            break_even=None,
            target_levered_irr=0.1,
            target_equity_multiple=1.5,
            target_headline_dscr=1.2,
            return_hurdle_metric=None,
            deal_context=None,
        )

    assert unsupported.value.operation == "AnalysisContext"


def test_an_unrepresentable_mode_is_never_presented_to_the_model_as_detailed() -> None:
    """Presentation refuses on its own, not merely because the context did.

    Describing one mode's economics under another mode's section names is a
    grounding failure, so this layer carries its own refusal rather than
    relying on ``AnalysisContext`` being the only way in. D5.1A demonstrated
    that with Lease-Level, the only mode the presentation layer could not then
    serve; D5.8 serves it, so the demonstration moves to a mode that still has
    no arm -- the property being proved is unchanged, and is the reason D5.8
    could add its arm safely.

    That Lease-Level is now presented under its *own* section names, and never
    Detailed's, is proved positively against a real payload in
    ``tests/test_d5_8_lease_level_ai_analyst.py``.
    """

    stub = _bypass_construct(
        AnalysisContext,
        operating_mode=_FABRICATED_MODE,
        inputs=None,
        terms=None,
        detailed_operating_inputs=None,
        operating_projection=None,
        lease_level_inputs=None,
        lease_level_results=None,
        results=None,
        sensitivities=None,
        break_even=None,
        target_levered_irr=0.1,
        target_equity_multiple=1.5,
        target_headline_dscr=1.2,
        return_hurdle_metric=None,
        deal_context=None,
    )

    with pytest.raises(UnsupportedOperatingModeError) as excinfo:
        build_presentation_payload(stub)

    assert excinfo.value.operation == "build_presentation_payload"


def test_the_ti_lc_exclusion_was_spent_by_the_gate_that_owned_it() -> None:
    """D5.1A deferred the TI/LC presentation decision to D5.8, which took it.

    Both fields now reach the model, and the allowlist that held them is empty.
    The condition D4.5A attached to their release -- a reviewed presentation
    *and* the grounding rules to interpret them by -- is checked here rather
    than assumed: the rule that keeps leasing capital from being read as an
    operating expense must exist in the shipped prompt.
    """

    from anchor.ai.presentation import INTENTIONALLY_EXCLUDED_RESULT_FIELDS
    from anchor.ai.prompts import build_system_prompt

    assert INTENTIONALLY_EXCLUDED_RESULT_FIELDS == frozenset()

    prompt = build_system_prompt()
    assert "LEASING-CAPITAL RULE" in prompt
    assert "BELOW net operating income" in prompt
    assert "NOT operating expenses" in prompt


# =============================================================================
# 5. Mutation kills
#
# Each mutant is *applied* to a copy of the real source and shown to be caught,
# rather than asserted to be impossible. M1-M12 share one mechanism because they
# are one defect wearing twelve hats: delete a mode's explicit arm and let it
# fall into a sibling's behavior.
# =============================================================================


def _strip_lease_level_arm(source: str, site_lineno: int) -> str:
    """Remove the ``LEASE_LEVEL`` arm at ``site_lineno``, leaving the
    fallthrough that D5.1A exists to prevent."""

    lines = source.split("\n")
    start = next(
        i
        for i, line in enumerate(lines)
        if i >= site_lineno - 1 and "OperatingMode.LEASE_LEVEL" in line
    )
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        stripped = lines[end].strip()
        if stripped and (len(lines[end]) - len(lines[end].lstrip())) <= indent:
            break
        end += 1
    return "\n".join(lines[:start] + lines[end:])


_MUTANTS = (
    ("M1", "api.py", "POST /analyze"),
    ("M2", "api.py", "POST /sensitivity"),
    ("M3", "api.py", "POST /sensitivity/presets"),
    ("M4", "api.py", "POST /break-even"),
    ("M5", "api.py", "POST /ai/analysis"),
    ("M6", "api.py", "POST /deals"),
    ("M7", "api.py", "PUT /deals/{deal_id}"),
    ("M8", "api.py", "POST /deals/fingerprint"),
    ("M9", "deals/contracts.py", None),
    ("M10", "deals/store.py", None),
    ("M11", "ai/contracts.py", None),
    ("M12", "ai/presentation.py", None),
)


@pytest.mark.parametrize(
    ("mutant", "relative_path", "marker"), _MUTANTS, ids=[m[0] for m in _MUTANTS]
)
def test_m1_to_m12_deleting_a_lease_level_arm_is_killed(
    mutant: str, relative_path: str, marker: str | None
) -> None:
    """Deleting any Lease-Level arm must be caught by the total-dispatch audit.

    Imports the guardrail module's own finders, so this proves the *shipped*
    guardrail kills the mutant -- not a re-implementation of it that might
    diverge.
    """

    from test_d5_1a_operating_mode_total_dispatch import (  # type: ignore[import-not-found]
        _if_chain_dispatch_sites,
        _match_dispatch_sites,
    )

    source_file = _ANCHOR_DIR / relative_path
    source = source_file.read_text(encoding="utf-8")

    if marker is not None:
        anchor_index = source.index(f'endpoint="{marker}"')
        lineno = source[:anchor_index].count("\n") + 1
        # walk back to this endpoint's LEASE_LEVEL arm
        arm = source.rindex("OperatingMode.LEASE_LEVEL", 0, anchor_index)
        lineno = source[:arm].count("\n") + 1
    else:
        # The *dispatch arm*, not merely the first mention. From D5.4
        # ``store.py`` also *constructs* ``OperatingMode.LEASE_LEVEL`` when it
        # reads a saved deal back, and that line comes first -- mutating it
        # would leave the arm under test untouched and report a mutant as
        # surviving when it was never actually applied.
        marker = (
            "case OperatingMode.LEASE_LEVEL:"
            if "case OperatingMode.LEASE_LEVEL:" in source
            else "OperatingMode.LEASE_LEVEL"
        )
        lineno = source[: source.index(marker)].count(chr(10)) + 1

    mutated = _strip_lease_level_arm(source, lineno)
    assert mutated != source, f"{mutant}: mutation did not change the source"

    tree = ast.parse(mutated)
    members = {m.name for m in OperatingMode}
    under_handled = [
        node.lineno
        for node, named in _if_chain_dispatch_sites(tree) + _match_dispatch_sites(tree)
        if members - named
    ]

    assert under_handled, (
        f"{mutant}: removing the Lease-Level arm from {relative_path} was NOT "
        "detected by the total-dispatch audit -- the guardrail does not kill "
        "this mutant"
    )


def test_m13_treating_a_valid_mode_as_an_invalid_enum_is_killed(
    client: TestClient,
) -> None:
    """M13: reporting ``lease_level`` as an invalid enum after publication.

    Moved to ``/break-even`` at D5.3 for the same reason as the test above:
    ``/analyze`` serves the mode now, so the surface that can still get this
    wrong is one that refuses it.
    """

    detail = str(
        client.post(
            "/break-even",
            json={"inputs": QUICK_INPUTS, **_HURDLES, "operating_mode": "lease_level"},
        ).json()["detail"]
    )

    assert "must be one of" not in detail, (
        "M13: a published mode was reported as an invalid enum value"
    )
    assert "not supported by" in detail


def test_m14_an_unknown_mode_is_never_accepted_through_a_generic_fallback(
    client: TestClient,
) -> None:
    """M14: an unknown token must not reach any dispatch at all."""

    for token in ("leaselevel", "LEASE_LEVEL", "", "quick ", "detailed2", "null"):
        response = client.post(
            "/analyze", json={**QUICK_INPUTS, "operating_mode": token}
        )
        assert response.status_code == 422, f"M14: {token!r} was accepted"
        assert "must be one of" in str(response.json()["detail"]), (
            f"M14: {token!r} was parsed as a valid mode"
        )


def test_m15_publishing_a_member_before_conversion_would_be_killed() -> None:
    """M15: the ordering violation -- a member added while a site lacks an arm.

    Simulated by asking the shipped audit about a member the code has never
    heard of. If the audit reports nothing, it would not have caught
    ``LEASE_LEVEL`` being published into eight silent fallthroughs either, which
    is the whole ordering invariant of this gate.
    """

    from test_d5_1a_operating_mode_total_dispatch import (  # type: ignore[import-not-found]
        _AUDITED,
        _if_chain_dispatch_sites,
        _match_dispatch_sites,
        _tree,
    )

    hypothetical = {m.name for m in OperatingMode} | {"PORTFOLIO"}

    unhandled: list[str] = []
    for path in _AUDITED:
        tree = _tree(path)
        for node, named in _if_chain_dispatch_sites(tree) + _match_dispatch_sites(tree):
            if hypothetical - named:
                unhandled.append(f"{path.name}:{node.lineno}")

    assert len(unhandled) >= 12, (
        "M15: the audit would not have flagged a newly-published mode with no "
        f"explicit arm (flagged only {unhandled})"
    )
