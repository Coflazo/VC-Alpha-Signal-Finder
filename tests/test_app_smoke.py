"""Every screen the app serves, on a genuinely fresh install.

This file exists because two endpoints were shipped broken. `/api/providers` and
`/api/setup` both read `Provider.key`, an attribute that stopped existing when the
provider ladder moved to LiteLLM and `key` became `env_key`. Both returned 500 —
including the Setup screen, whose entire job is telling a new fund what to
configure. Nothing caught it, because nothing ever called them.

So: every GET route gets called, with no credentials and no thesis, which is
exactly the state a firm is in the first time they open it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vc_alpha.app.main import app


@pytest.fixture
def client():
    return TestClient(app)


# Routes taking no path parameter. Kept as a list rather than introspected from
# the router so that deleting a route is a visible change to this file.
GET_ROUTES = [
    "/api/overview", "/api/health", "/api/theses", "/api/setup", "/api/providers",
    "/api/sources", "/api/candidates", "/api/entities", "/api/hardware",
    "/api/sheet", "/api/deployment", "/api/jobs/current",
]


@pytest.mark.parametrize("route", GET_ROUTES)
def test_every_screen_loads_with_nothing_configured(client, route):
    assert client.get(route).status_code == 200, route


def test_the_setup_screen_lists_what_is_missing(client):
    """The screen a fund reads first. It must not need a key to render."""
    items = client.get("/api/setup").json()["items"]
    assert items
    assert all({"name", "env", "present", "unlocks", "where"} <= set(i) for i in items)
    assert not any(i["present"] for i in items if i["name"] != "ollama"), \
        "no credentials are set, so nothing hosted should report itself present"


def test_the_providers_screen_reports_capacity(client):
    """'Free forever' is meant to be checkable rather than claimed."""
    providers = client.get("/api/providers").json()["providers"]
    assert {p["name"] for p in providers} >= {"groq", "mistral", "ollama"}
    assert all(p["limit"] > 0 for p in providers)
    # The local rung is the one that works with nothing configured.
    assert next(p for p in providers if p["name"] == "ollama")["configured"]


@pytest.mark.empty_install
def test_a_fresh_install_says_what_to_do_first(client):
    d = client.get("/api/overview").json()
    assert d["funds"] == 0
    assert "Setup" in d["first_run"]


@pytest.mark.empty_install
def test_a_fund_can_be_created_from_prose_alone(client):
    """No YAML by hand — the whole point of the onboarding path."""
    r = client.post("/api/theses", json={
        "name": "Test Capital",
        "prose": "We back technical founders at pre-seed building developer "
                 "infrastructure in Europe, usually before they have a product.",
    })
    assert r.status_code == 200
    assert r.json()["id"] == "test-capital"
    assert r.json()["stage"] == "pre-seed"

    assert client.get("/api/overview").json()["funds"] == 1
    assert "Test Capital" in {t["name"] for t in client.get("/api/theses").json()["theses"]}


@pytest.mark.empty_install
def test_creating_the_same_fund_twice_is_refused_not_silently_overwritten(client):
    body = {"name": "Dup Capital",
            "prose": "We back seed-stage infrastructure companies in Europe, "
                     "usually led by engineers who hit the problem at work."}
    assert client.post("/api/theses", json=body).status_code == 200
    assert client.post("/api/theses", json=body).status_code == 409


def test_missing_thesis_is_a_404_not_a_crash(client):
    assert client.get("/api/reports/nope").status_code == 404
    assert client.post("/api/sheet/push", json={"thesis": "nope"}).status_code == 404
