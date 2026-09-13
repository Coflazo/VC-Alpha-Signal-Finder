"""Test isolation from whatever keys happen to be on this machine.

LiteLLM calls `load_dotenv()` when it is imported, so importing anything that
touches the router quietly pulls the developer's real `.env` into `os.environ`.
That made a test asserting "the cloud embedder is Gemini" pass or fail depending
on which keys were lying around — the machine was a hidden input to the suite.

So every test starts with no provider keys and no configured home, and any test
that wants one sets it explicitly.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# The five real funds ship as examples now rather than as installed defaults, so a
# fresh install starts empty. The suite still needs real theses to score against,
# and these are the ones every measurement in docs/VALIDATION.md was taken with.
EXAMPLE_THESES = Path(__file__).resolve().parent.parent / "examples" / "theses"

# Everything the router, the embedder or a collector reads to decide whether it is
# configured. Cleared wholesale rather than named per test, so a new provider
# cannot reintroduce the same leak.
PROVIDER_KEYS = [
    "GEMINI_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "MISTRAL_API_KEY",
    "NVIDIA_NIM_API_KEY", "SAMBANOVA_API_KEY", "OPENROUTER_API_KEY",
    "COHERE_API_KEY", "GITHUB_MODELS_TOKEN",
    "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "LINKEDIN_SESSION_COOKIE",
    "GOOGLE_SERVICE_ACCOUNT_JSON", "VC_ALPHA_SHEET_ID",
    "GEMINI_MODEL", "GROQ_MODEL", "MISTRAL_MODEL", "NVIDIA_MODEL",
    "CEREBRAS_MODEL", "SAMBANOVA_MODEL", "OPENROUTER_MODEL", "OLLAMA_MODEL",
    "MISTRAL_EMBED_MODEL", "COHERE_EMBED_MODEL", "GEMINI_EMBED_MODEL", "EMBED_MODEL",
]


@pytest.fixture(autouse=True)
def no_ambient_credentials(request, monkeypatch, tmp_path):
    for key in PROVIDER_KEYS:
        monkeypatch.delenv(key, raising=False)
    # A home of its own, so no test reads or writes the developer's real database,
    # theses or .env. Seeded with the example funds, because most of the suite is
    # about scoring against a thesis rather than about having none.
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    if request.node.get_closest_marker("empty_install") is None:
        shutil.copytree(EXAMPLE_THESES, home / "config" / "theses")
    monkeypatch.setenv("VC_ALPHA_HOME", str(home))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "empty_install: start with no thesis at all, as a firm does on day one")
