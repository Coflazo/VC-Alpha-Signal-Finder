"""The router is what makes 'free forever' true rather than hoped for, so its
failure paths are tested rather than assumed.
"""

import sqlite3

import httpx
import pytest

from vc_alpha.llm import (
    Budget, NoCapacityLeft, PrivateTextRefused, Provider, Router, Sending,
    _extract_json,
)

A = Provider("a", "KEY_A", "https://a.test/v1", "model-a", daily_requests=2)
B = Provider("b", "KEY_B", "https://b.test/v1", "model-b", daily_requests=5)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("KEY_A", "x")
    monkeypatch.setenv("KEY_B", "y")


def router(conn, responder):
    r = Router(conn, ladder=[A, B])
    r._call_one = responder
    return r


def test_private_text_is_refused_before_any_network_call(conn):
    """The guard exists so a WhatsApp message cannot reach a training-on-data tier."""
    def explode(*a, **k):
        raise AssertionError("a private message reached the network")

    with pytest.raises(PrivateTextRefused):
        router(conn, explode).complete(
            "Ayse: my friend just raised a seed round", sending=Sending.PRIVATE
        )


def test_redacted_fragments_are_allowed_through(conn):
    """A stripped fragment is the agreed path for private sources."""
    out = router(conn, lambda p, prompt, schema: "ok").complete(
        "a company called Acme raised a seed round", sending=Sending.REDACTED
    )
    assert out == "ok"


def test_falls_over_to_the_next_provider_on_429(conn):
    calls = []

    def responder(p, prompt, schema):
        calls.append(p.name)
        if p.name == "a":
            req = httpx.Request("POST", "https://a.test")
            raise httpx.HTTPStatusError(
                "429", request=req, response=httpx.Response(429, request=req)
            )
        return "second provider answered"

    out = router(conn, responder).complete("public post", sending=Sending.PUBLIC)
    assert calls == ["a", "b"]
    assert out == "second provider answered"


def test_a_rate_limited_provider_is_skipped_next_time(conn):
    """A 429 is better evidence than our own counter, so trust it and stop asking."""
    r = router(conn, lambda p, *a: (_ for _ in ()).throw(
        httpx.HTTPStatusError(
            "429",
            request=httpx.Request("POST", "https://a.test"),
            response=httpx.Response(429, request=httpx.Request("POST", "https://a.test")),
        )
    ))
    with pytest.raises(NoCapacityLeft):
        r.complete("public", sending=Sending.PUBLIC)
    assert r.available() == []


def test_budget_stops_a_provider_at_its_daily_limit(conn):
    r = router(conn, lambda p, prompt, schema: "ok")
    assert [p.name for p in r.available()] == ["a", "b"]
    for _ in range(A.daily_requests):
        r.complete("public", sending=Sending.PUBLIC)
    assert [p.name for p in r.available()] == ["b"], "exhausted provider still offered"


def test_budget_survives_a_restart(conn):
    Budget(conn).note("a")
    assert Budget(conn).used("a") == 1, "usage did not persist across instances"


def test_unconfigured_providers_are_not_offered(conn, monkeypatch):
    monkeypatch.delenv("KEY_A")
    assert [p.name for p in Router(conn, ladder=[A, B]).available()] == ["b"]


def test_raises_when_nothing_is_left(conn, monkeypatch):
    monkeypatch.delenv("KEY_A")
    monkeypatch.delenv("KEY_B")
    with pytest.raises(NoCapacityLeft):
        Router(conn, ladder=[A, B]).complete("public", sending=Sending.PUBLIC)


def test_transport_errors_do_not_end_the_run(conn):
    def responder(p, prompt, schema):
        if p.name == "a":
            raise httpx.ConnectError("dns died")
        return "b answered"

    assert router(conn, responder).complete("public", sending=Sending.PUBLIC) == "b answered"


@pytest.mark.parametrize("reply", [
    '{"ok": true}',
    'Sure, here you go:\n```json\n{"ok": true}\n```',
    'The answer is {"ok": true} — hope that helps',
])
def test_json_is_recovered_from_chatty_replies(reply):
    """Providers differ on honouring a schema. One repair beats spending a retry."""
    assert _extract_json(reply) == {"ok": True}
