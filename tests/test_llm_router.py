"""The router.

It is now a thin wrapper: LiteLLM handles providers, fallbacks, retries and rate
limits, and what remains here is what no gateway can know — the privacy
classification and the free-tier ceiling. So these tests cover exactly those two
things, plus the reply parsing.

The previous version of this file tested hand-rolled failover and rate-limit header
parsing. Those tests are gone because the code they described is gone, and it was
replaced precisely because four separate bugs proved it was the wrong thing to own.
"""

import os
import sqlite3

import pytest

from vc_alpha.llm import (
    LADDER, Budget, NoCapacityLeft, PrivateTextRefused, Provider, Router, Sending,
    _extract_json,
)

A = Provider("a", "KEY_A", "fake/model-a", daily_requests=2)
B = Provider("b", "KEY_B", "fake/model-b", daily_requests=5)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("KEY_A", "x")
    monkeypatch.setenv("KEY_B", "y")


# --- the privacy guard, which is the whole reason this file still exists ------


def test_private_text_is_refused_before_any_network_call(conn):
    """The guard exists so a WhatsApp message cannot reach a training-on-data tier."""
    with pytest.raises(PrivateTextRefused):
        Router(conn, ladder=[A, B]).complete(
            "Ayse: my friend just raised a seed round", sending=Sending.PRIVATE
        )


def test_the_refusal_says_what_to_do_instead(conn):
    with pytest.raises(PrivateTextRefused, match="redact"):
        Router(conn, ladder=[A]).complete("private", sending=Sending.PRIVATE)


# --- the budget, which makes "free forever" enforced rather than hoped for ----


def test_a_provider_is_dropped_once_its_daily_allowance_is_spent(conn):
    r = Router(conn, ladder=[A, B])
    assert [p.name for p in r.available()] == ["a", "b"]
    for _ in range(A.daily_requests):
        r.budget.note("a")
    assert [p.name for p in r.available()] == ["b"], "a spent provider was still offered"


def test_usage_survives_a_restart(conn):
    Budget(conn).note("a")
    assert Budget(conn).used("a") == 1, "usage did not persist across instances"


def test_unconfigured_providers_are_not_offered(conn, monkeypatch):
    monkeypatch.delenv("KEY_A")
    assert [p.name for p in Router(conn, ladder=[A, B]).available()] == ["b"]


def test_running_out_says_which_free_keys_to_get(conn, monkeypatch):
    monkeypatch.delenv("KEY_A")
    monkeypatch.delenv("KEY_B")
    with pytest.raises(NoCapacityLeft, match="GROQ_API_KEY"):
        Router(conn, ladder=[A, B]).complete("public", sending=Sending.PUBLIC)


def test_local_needs_no_key_so_the_product_works_with_nothing_configured():
    """Requiring an env var for a local endpoint would mean a machine with no API
    keys had no provider at all, which defeats shipping a local fallback."""
    ollama = next(p for p in LADDER if p.local)
    assert ollama.configured


def test_every_shipped_provider_is_a_free_tier():
    assert all(p.daily_requests > 0 for p in LADDER)
    assert {p.name for p in LADDER} >= {"gemini", "groq", "openrouter", "ollama"}


def test_model_names_are_overridable_by_environment():
    """Model names are the most perishable thing in the file: a retired one returning
    404 is what broke the previous implementation.

    Run in a subprocess rather than reloading the module in-process. Reloading
    rebuilds the Sending enum, so any module that already imported it holds a
    different class and `sending is Sending.PRIVATE` silently stops matching —
    which quietly disabled the privacy guard in another test file.
    """
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c",
         "from vc_alpha.llm import LADDER;"
         "print(next(p.model for p in LADDER if p.name == 'groq'))"],
        env={**os.environ, "GROQ_MODEL": "groq/something-else"},
        capture_output=True, text=True,
    )
    assert out.stdout.strip() == "groq/something-else", out.stderr[-300:]


# --- reply parsing -----------------------------------------------------------


@pytest.mark.parametrize("reply", [
    '{"ok": true}',
    'Sure, here you go:\n```json\n{"ok": true}\n```',
    'The answer is {"ok": true} — hope that helps',
])
def test_json_is_recovered_from_chatty_replies(reply):
    """Some providers wrap the object in prose even under a schema. One repair beats
    a retry, which would spend an allowance the product is trying not to spend."""
    assert _extract_json(reply) == {"ok": True}


def test_an_unparseable_reply_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        _extract_json("no object here at all")
