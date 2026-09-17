"""Demo polish -- analyst-facing refusals name things, never internal ids.

A refusal an analyst can reach on a normal path says what happened in the
words the analyst used: a Scenario or Strategy by its name, a missing Deal or
Investment by what it is. The internal ids stay on the error objects for logs
and callers; they are not the message.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import _p7_4_fixtures as f4  # type: ignore[import-not-found]
from _p7_2_fixtures import override  # type: ignore[import-not-found]
from _p7_6_fixtures import create_investment, quick_deal  # type: ignore[import-not-found]
from anchor import api as api_module
from anchor.deals import store
from anchor.deals.contracts import InvestmentStructureError

MISSING = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "polish.db"


@pytest.fixture
def client(db: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ANCHOR_DB_PATH", str(db))
    return TestClient(api_module.app)


def test_a_unit_refusal_names_its_scenario_and_strategy_without_their_ids(db: Path) -> None:
    first, second = quick_deal(db), quick_deal(db)
    visible = create_investment(db, first, second)
    scenario = store.create_scenario(
        visible.id,
        name="Wide exit",
        overrides=(override(second.id, "exit_cap_rate", "add", 0.005),),
        db_path=db,
    )
    strategy = store.create_strategy(
        visible.id, name="Hold", overlays=(f4.disposition(second.id, 5),), db_path=db
    )

    with pytest.raises(InvestmentStructureError) as error:
        store.remove_investment_unit(visible.id, second.id, db_path=db)

    message = str(error.value)
    assert "Scenario 'Wide exit'" in message
    assert "Strategy 'Hold'" in message
    assert scenario.scenario.scenario_id not in message
    assert strategy.strategy.strategy_id not in message


def test_deleting_a_unit_deal_is_refused_without_quoting_its_id(db: Path) -> None:
    first, second = quick_deal(db), quick_deal(db)
    create_investment(db, first, second)

    with pytest.raises(InvestmentStructureError) as error:
        store.delete_deal(first.id, db_path=db)

    assert str(error.value).startswith("This deal is a Unit of a visible Investment.")
    assert first.id not in str(error.value)


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("get", f"/deals/{MISSING}/capital-structure", "This deal could not be found."),
        ("get", f"/investments/{MISSING}/capital-structure", "This investment could not be found."),
        ("get", f"/investments/{MISSING}/details", "This investment could not be found."),
    ],
)
def test_a_missing_record_is_reported_in_words(
    client: TestClient, method: str, path: str, expected: str
) -> None:
    response = getattr(client, method)(path)

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail.startswith(expected)
    assert MISSING not in detail


def test_a_missing_scenario_or_strategy_is_reported_in_words(db: Path, client: TestClient) -> None:
    first, second = quick_deal(db), quick_deal(db)
    visible = create_investment(db, first, second)

    scenario = client.get(f"/investments/{visible.id}/scenarios/{MISSING}")
    strategy = client.get(f"/investments/{visible.id}/strategies/{MISSING}")

    assert scenario.status_code == 404
    assert scenario.json()["detail"].startswith("This scenario could not be found.")
    assert strategy.status_code == 404
    assert strategy.json()["detail"].startswith("This strategy could not be found.")
    for response in (scenario, strategy):
        assert MISSING not in response.json()["detail"]
        assert visible.id not in response.json()["detail"]


# =============================================================================
# A rejected AI model names the setting that chose it
# =============================================================================


def _provider_failure(kind_name: str, status_code: int, message: str, code: str | None) -> Exception:
    """The provider layer's own error for one SDK refusal, raised through the
    real ``OpenAIAnalystProvider`` so the cause chain is the real one."""

    import httpx
    import openai

    from anchor.ai.provider import AIProviderError, OpenAIAnalystProvider

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    body = {"message": message, "type": "invalid_request_error", "param": None, "code": code}
    refusal = getattr(openai, kind_name)(
        message, response=httpx.Response(status_code, request=request), body=body
    )

    class _Responses:
        def create(self, **_: object) -> None:
            raise refusal

    class _Client:
        responses = _Responses()

    try:
        OpenAIAnalystProvider(client=_Client(), model="gpt-x").generate_analysis(
            system_prompt="s", user_prompt="u"
        )
    except AIProviderError as error:
        return error
    raise AssertionError("the provider did not refuse")


REQUEST = {
    "inputs": {
        "purchase_price": 50_000_000, "current_noi": 2_500_000, "occupancy": 0.95,
        "noi_growth": 0.03, "hold_period": 5, "exit_cap_rate": 0.055, "ltv": 0.65,
        "interest_rate": 0.0525, "amortization": 30,
    },
    "target_levered_irr": 0.10,
    "target_headline_dscr": 1.20,
    "target_equity_multiple": 1.50,
}

MODEL_MESSAGE = (
    "The AI model 'gpt-configured' is not available to this OpenAI API key (the provider "
    "reports it as not found or not permitted). Set ANCHOR_AI_MODEL in .env to a model this "
    "key can use, then restart Anchor."
)


@pytest.mark.parametrize(
    ("kind_name", "status_code", "message", "code"),
    [
        ("NotFoundError", 404, "The model `gpt-x` does not exist or you do not have access to it.", "model_not_found"),
        ("PermissionDeniedError", 403, "You do not have access to model gpt-x.", None),
    ],
)
def test_a_rejected_model_is_reported_by_its_setting(
    monkeypatch: pytest.MonkeyPatch, kind_name: str, status_code: int, message: str, code: str | None
) -> None:
    from unittest.mock import patch

    monkeypatch.setenv("ANCHOR_AI_MODEL", "gpt-configured")
    failure = _provider_failure(kind_name, status_code, message, code)
    with patch("anchor.api.generate_ai_analysis", side_effect=failure):
        response = TestClient(api_module.app).post("/ai/analysis", json=REQUEST)

    assert response.status_code == 502
    assert response.json()["detail"] == MODEL_MESSAGE


def test_any_other_provider_failure_keeps_its_sanitized_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import patch

    monkeypatch.setenv("ANCHOR_AI_MODEL", "gpt-configured")
    failure = _provider_failure("PermissionDeniedError", 403, "Country, region, or territory not supported.", None)
    with patch("anchor.api.generate_ai_analysis", side_effect=failure):
        response = TestClient(api_module.app).post("/ai/analysis", json=REQUEST)

    assert response.status_code == 502
    assert response.json()["detail"] == "The AI provider request failed (PermissionDeniedError)."
