"""Regression tests for repo-local ``.env`` loading (``anchor.env``).

Covers the bug where the FastAPI process never saw ``AZURE_DOCUMENTINTELLIGENCE_
ENDPOINT``/``_KEY`` (or ``OPENAI_API_KEY``) from the repo-root ``.env`` because
nothing loaded it into ``os.environ`` before ``anchor.api`` was imported.
"""

from __future__ import annotations

import os

from anchor.env import load_repo_env


def test_missing_env_file_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.setattr("anchor.env.ENV_FILE", tmp_path / "does-not-exist.env")

    load_repo_env()  # must not raise


def test_env_file_value_is_loaded_when_unset(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ANCHOR_TEST_ONLY_VAR=from-dotenv\n")
    monkeypatch.setattr("anchor.env.ENV_FILE", env_file)
    monkeypatch.delenv("ANCHOR_TEST_ONLY_VAR", raising=False)

    load_repo_env()

    assert os.environ["ANCHOR_TEST_ONLY_VAR"] == "from-dotenv"


def test_real_environment_variable_takes_precedence_over_env_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ANCHOR_TEST_ONLY_VAR=from-dotenv\n")
    monkeypatch.setattr("anchor.env.ENV_FILE", env_file)
    monkeypatch.setenv("ANCHOR_TEST_ONLY_VAR", "from-real-environment")

    load_repo_env()

    assert os.environ["ANCHOR_TEST_ONLY_VAR"] == "from-real-environment"
