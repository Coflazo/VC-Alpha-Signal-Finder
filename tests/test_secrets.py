"""Keys typed into the Setup screen.

This handles live credentials, so the properties worth pinning are the security
ones rather than the happy path: the file is never world-readable, a value never
comes back out of the API, and an arbitrary environment variable cannot be set by
asking nicely.
"""

from __future__ import annotations

import os
import stat

import pytest
from fastapi.testclient import TestClient

from vc_alpha import paths, secrets
from vc_alpha.app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_only_known_names_can_be_written():
    """The whitelist is the whole defence. Without it a POST sets PATH."""
    for hostile in ("PATH", "LD_PRELOAD", "PYTHONPATH", "HOME", "VC_ALPHA_HOME"):
        with pytest.raises(secrets.NotSettable):
            secrets.save(hostile, "anything")


def test_the_ladders_define_what_is_settable():
    """Adding a provider to a ladder should make it settable, without a second
    list here to keep in sync."""
    assert "GROQ_API_KEY" in secrets.SETTABLE
    assert "MISTRAL_API_KEY" in secrets.SETTABLE
    assert "COHERE_API_KEY" in secrets.SETTABLE, "embedding-only rungs count too"
    assert "OLLAMA_HOST" not in secrets.SETTABLE, "the local rung needs no key"


def test_a_newline_cannot_smuggle_a_second_variable():
    with pytest.raises(secrets.NotSettable):
        secrets.save("GROQ_API_KEY", "real\nPATH=/tmp/evil")


def test_saved_key_is_applied_immediately_and_persisted():
    secrets.save("GROQ_API_KEY", "gsk-test-value")
    assert os.environ["GROQ_API_KEY"] == "gsk-test-value"
    assert "GROQ_API_KEY=gsk-test-value" in paths.env_file().read_text()


def test_the_file_is_never_world_readable():
    """It holds live credentials; no other user on the machine needs to read it."""
    secrets.save("GROQ_API_KEY", "gsk-test-value")
    mode = stat.S_IMODE(paths.env_file().stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_an_empty_value_clears_the_key():
    secrets.save("GROQ_API_KEY", "gsk-test-value")
    secrets.save("GROQ_API_KEY", "")
    assert "GROQ_API_KEY" not in os.environ
    assert "GROQ_API_KEY" not in paths.env_file().read_text()


def test_saving_one_key_leaves_the_others_alone():
    secrets.save("GROQ_API_KEY", "one")
    secrets.save("MISTRAL_API_KEY", "two")
    secrets.save("GROQ_API_KEY", "one-replaced")

    body = paths.env_file().read_text()
    assert "MISTRAL_API_KEY=two" in body
    assert "GROQ_API_KEY=one-replaced" in body
    assert body.count("GROQ_API_KEY") == 1, "replacing must not append a duplicate"


# --- through the API ---------------------------------------------------------


def test_the_endpoint_saves_and_reports_presence(client):
    r = client.post("/api/setup/key",
                    json={"name": "GROQ_API_KEY", "value": "gsk-from-the-screen"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "present": True}

    item = next(i for i in client.get("/api/setup").json()["items"]
                if i["env"] == "GROQ_API_KEY")
    assert item["present"]


def test_no_endpoint_ever_returns_a_key_value(client):
    """A key readable from the UI leaks through a screenshot or a support thread."""
    value = "gsk-this-must-never-come-back"
    client.post("/api/setup/key", json={"name": "GROQ_API_KEY", "value": value})

    for route in ("/api/setup", "/api/providers", "/api/health", "/api/overview"):
        assert value not in client.get(route).text, route


def test_the_endpoint_refuses_a_name_it_does_not_own(client):
    r = client.post("/api/setup/key", json={"name": "PATH", "value": "/tmp/evil"})
    assert r.status_code == 400


def test_setup_says_where_keys_are_stored(client):
    """So a fund can find, back up or delete the file without asking."""
    assert client.get("/api/setup").json()["stored_in"] == str(paths.env_file())


def test_testing_a_key_that_is_not_a_provider_is_refused(client):
    assert client.post("/api/setup/test",
                       json={"name": "VC_ALPHA_SHEET_ID", "value": ""}).status_code == 400
