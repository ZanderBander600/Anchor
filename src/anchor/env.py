"""Local-development ``.env`` loading.

``anchor.api`` imports this module and calls ``load_repo_env()`` once at
import time so a developer running ``uvicorn anchor.api:app`` picks up the
repo-local ``.env`` (OpenAI / Azure Document Intelligence credentials)
without having to export them by hand first. Resolves the ``.env`` path
from this file's own location rather than the process's current working
directory, so the fix works regardless of which directory the backend was
launched from. Never overrides a variable already present in the real
process environment (``override=False``) -- a real environment variable
always wins over a ``.env`` value, so CI/production configuration is
unaffected.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = _REPO_ROOT / ".env"


def load_repo_env() -> None:
    """Load ``ENV_FILE`` into ``os.environ``, if it exists.

    No-ops when ``.env`` is absent -- environments that set real
    environment variables directly (CI, production) are unaffected.
    """

    if ENV_FILE.is_file():
        load_dotenv(dotenv_path=ENV_FILE, override=False)
