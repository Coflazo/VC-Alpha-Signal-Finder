"""A page sent from the browser extension, through the same stages as everything else.

The fakes stand in for the two network dependencies. What is under test is the
routing: which text reaches which provider, under which classification, and what
ends up in the database the rest of the pipeline reads.
"""

from __future__ import annotations

import json
import types

import pytest
from fastapi.testclient import TestClient

from vc_alpha import capture
from vc_alpha.app.main import app
from vc_alpha.db import connect
from vc_alpha.llm import Sending

PITCH = ("Show HN: I moved from Istanbul to Berlin and built an AI-native "
         "procurement tool for mid-market manufacturers. We are raising pre-seed.")


def verdict(quote="built an AI-native procurement tool"):
    return {
        "is_building": {"score": 0.9, "quote": quote},
        "thesis_fit": {"score": 0.8, "quote": "moved from Istanbul to Berlin"},
        "founder_quality": {"score": 0.5, "quote": ""},
        "timing": {"score": 0.7, "quote": "We are raising pre-seed"},
        "reachable": {"score": 0.6, "quote": ""},
        "too_late": {"score": 0.0, "quote": ""},
        "stage": "pre-seed",
        "summary": "AI procurement for manufacturers.",
    }


class FakeRouter:
    def __init__(self, reply=None, available=True):
        self.reply = reply or verdict()
        self._available = available
        self.sent: list[tuple[str, Sending]] = []

    def available(self):
        return ["fake"] if self._available else []

    def complete(self, prompt, *, schema=None, sending, system=None):
        self.sent.append((prompt, sending))
        return self.reply


class FakeEmbedder:
    fingerprint = "fake/embed"

    def __init__(self, local=False):
        self.provider_info = types.SimpleNamespace(local=local)
        self.provider = "ollama" if local else "mistral"
        self.seen: list[str] = []

    def available(self):
        return True

    def embed_many(self, texts):
        self.seen.extend(texts)
        return [[1.0, 0.5] for _ in texts]

    def embed(self, text):
        return self.embed_many([text])[0]


@pytest.fixture
def fakes(monkeypatch):
    router, emb = FakeRouter(), FakeEmbedder()
    monkeypatch.setattr(capture, "Router", lambda conn: router)
    monkeypatch.setattr(capture, "Embedder", lambda: emb)
    return router, emb


@pytest.fixture
def client():
    return TestClient(app)


def post(client, **body):
    body.setdefault("text", PITCH)
    body.setdefault("url", "https://news.ycombinator.com/item?id=1")
    return client.post("/api/capture", json=body)


def row(cid):
    return connect().execute("SELECT * FROM candidates WHERE id = ?", (cid,)).fetchone()


def test_a_public_capture_is_screened_against_the_pinned_thesis(client, fakes):
    router, emb = fakes
    r = post(client, thesis="treeo")

    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "scored"
    assert out["source"] == "extension"
    assert out["thesis"]["id"] == "treeo"
    assert out["similarity"] is not None and out["score"] is not None
    assert {s["key"] for s in out["signals"]} >= {"is_building", "too_late"}
    assert router.sent[0][1] is Sending.PUBLIC
    assert PITCH in router.sent[0][0]

    stored = row(out["id"])
    assert stored["source"] == "extension" and stored["is_startup"] == 1
    assert stored["thesis_id"] == "treeo" and stored["embedding_model"] == "fake/embed"


def test_a_fabricated_quote_is_blanked_before_it_is_stored(client, fakes):
    router, _ = fakes
    router.reply = verdict(quote="we have 400 paying customers")
    out = post(client, thesis="treeo").json()

    building = next(s for s in out["signals"] if s["key"] == "is_building")
    assert building["quote"] == ""
    assert "400 paying" not in row(out["id"])["triage_json"]


def test_a_private_capture_sends_only_a_fragment_and_skips_the_cloud_embedder(
        client, fakes):
    router, emb = fakes
    secret = "Ayse's divorce is final. " + PITCH
    out = post(client, text=secret, url="https://mail.google.com/mail/u/0/#inbox/1",
               private=True, thesis="treeo").json()

    assert out["source"] == "extension_private"
    prompt, sending = router.sent[0]
    assert sending is Sending.REDACTED
    assert "divorce" not in prompt
    assert not any("divorce" in t for t in emb.seen), "cloud embedder saw private text"
    assert out["similarity"] is None


def test_with_no_provider_the_capture_is_kept_and_says_what_to_configure(
        client, monkeypatch):
    monkeypatch.setattr(capture, "Router", lambda conn: FakeRouter(available=False))
    monkeypatch.setattr(capture, "Embedder", lambda: FakeEmbedder())
    out = post(client).json()

    assert out["status"] == "stored"
    assert "KEY" in out["note"]
    assert row(out["id"]) is not None


def test_a_page_the_thesis_excludes_is_not_stored(client, fakes):
    router, _ = fakes
    out = post(client, text="Scaling my dropshipping store to 10k a month",
               url="https://example.com/ds", thesis="treeo").json()

    assert out["status"] == "excluded"
    assert out["id"] is None
    assert not router.sent


def test_capturing_the_same_page_again_refreshes_it(client, fakes):
    first = post(client, url="https://acme.dev", thesis="treeo").json()
    connect().execute("UPDATE candidates SET reviewed = 1, was_good = 1 WHERE id = ?",
                      (first["id"],)).connection.commit()
    again = post(client, url="https://acme.dev", thesis="treeo",
                 text=PITCH + " Now with 3 design partners.").json()

    assert again["id"] == first["id"]
    stored = row(first["id"])
    assert "design partners" in stored["raw_text"]
    assert stored["was_good"] == 1, "a partner's review must survive a re-capture"


def test_a_page_another_source_already_collected_is_left_alone(client, fakes):
    router, _ = fakes
    url = "https://news.ycombinator.com/item?id=42"
    conn = connect()
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until) VALUES (?, 'hackernews', ?, 'the collected post',
           '2026-09-01', '2099-01-01')""",
        (capture.CandidateRecord("x", url, "").id, url))
    conn.commit()

    out = post(client, url=url).json()

    assert out["source"] == "hackernews"
    assert "hackernews" in out["note"]
    assert row(out["id"])["raw_text"] == "the collected post"
    assert not router.sent


def test_a_capture_without_a_url_gets_a_stable_id(client, fakes):
    a = client.post("/api/capture", json={"text": PITCH}).json()
    b = client.post("/api/capture", json={"text": PITCH}).json()
    assert a["id"] == b["id"]
    assert row(a["id"])["source_url"].startswith("capture:")


@pytest.mark.parametrize("origin", ["https://example.com", "http://evil.test:8420",
                                    "null"])
def test_a_web_page_cannot_post_a_capture(client, fakes, origin):
    r = client.post("/api/capture", json={"text": PITCH},
                    headers={"Origin": origin})
    assert r.status_code == 403


def test_the_extension_origin_is_accepted(client, fakes):
    r = client.post("/api/capture", json={"text": PITCH},
                    headers={"Origin": "chrome-extension://abcdefghijklmnop"})
    assert r.status_code == 200, r.text


def test_empty_text_is_refused(client, fakes):
    assert client.post("/api/capture", json={"text": "   "}).status_code == 400


def test_oversized_text_is_refused(client, fakes):
    r = client.post("/api/capture", json={"text": "x" * (capture.MAX_CHARS + 1)})
    assert r.status_code == 400


def test_an_unknown_thesis_is_a_404(client, fakes):
    assert post(client, thesis="no-such-fund").status_code == 404


@pytest.mark.empty_install
def test_with_no_fund_configured_the_capture_is_kept(client, fakes):
    out = post(client).json()
    assert out["status"] == "stored"
    assert "fund" in out["note"].lower()
    assert json.loads(json.dumps(out))  # plain JSON all the way down
