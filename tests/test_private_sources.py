"""Private text must never reach a cloud model as if it were public.

`triage.run` used to select every row above the threshold regardless of source. A
WhatsApp row embedded locally would get a similarity, and the next run would send
the raw message to a cloud provider marked PUBLIC. Private browser captures take
the same path, so the rule now lives in one constant every stage reads.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from vc_alpha import signals, theses, triage
from vc_alpha.db import SCHEMA, now, retention_until
from vc_alpha.enrich.embed import score_pending
from vc_alpha.llm import Sending
from vc_alpha.redact import PRIVATE_SOURCES

VERDICT = {
    "is_building": {"score": 0.9, "quote": "we built"},
    "thesis_fit": {"score": 0.8, "quote": ""},
    "founder_quality": {"score": 0.6, "quote": ""},
    "timing": {"score": 0.5, "quote": ""},
    "reachable": {"score": 1.0, "quote": ""},
    "too_late": {"score": 0.0, "quote": ""},
    "stage": "pre-seed",
    "summary": "A company.",
}


class FakeRouter:
    def __init__(self):
        self.sent: list[tuple[str, Sending]] = []

    def available(self):
        return ["fake"]

    def complete(self, prompt, *, schema=None, sending, system=None):
        self.sent.append((prompt, sending))
        return VERDICT


class CloudEmbedder:
    fingerprint = "fake/cloud"
    provider = "mistral"

    def __init__(self):
        self.seen: list[str] = []

    def embed_many(self, texts):
        self.seen.extend(texts)
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _row(conn, cid, source, text, similarity=None):
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until, similarity, thesis_id)
           VALUES (?,?,?,?,?,?,?,?)""",
        (cid, source, f"https://x/{cid}", text, now(), retention_until(),
         similarity, "treeo"),
    )
    conn.commit()


def test_private_sources_cover_whatsapp_and_private_captures():
    assert {"whatsapp", "extension_private"} <= PRIVATE_SOURCES


def test_public_triage_never_selects_a_private_row(conn):
    _row(conn, "pub", "hackernews", "PUBLIC TEXT we built a thing", 0.9)
    _row(conn, "wa", "whatsapp", "WHATSAPP TEXT my friend is raising", 0.9)
    _row(conn, "cap", "extension_private", "PRIVATE CAPTURE from an inbox", 0.9)
    router = FakeRouter()

    stats = triage.run(conn, router, theses.load_all(), threshold=0.1)

    assert stats["triaged"] == 1
    prompts = " ".join(p for p, _ in router.sent)
    assert "PUBLIC TEXT" in prompts
    assert "WHATSAPP TEXT" not in prompts and "PRIVATE CAPTURE" not in prompts
    left = {r[0] for r in conn.execute(
        "SELECT id FROM candidates WHERE triage_json IS NULL")}
    assert left == {"wa", "cap"}


def test_a_cloud_embedder_never_sees_a_private_row(conn):
    _row(conn, "pub", "hackernews",
         "Show HN: we built an AI tool for immigrant founders raising pre-seed")
    _row(conn, "cap", "extension_private",
         "Forwarded pitch: we built an AI tool for immigrant founders")
    emb = CloudEmbedder()

    score_pending(conn, emb, theses.load_all())

    assert not any("Forwarded pitch" in t for t in emb.seen)
    row = conn.execute("SELECT embedding FROM candidates WHERE id='cap'").fetchone()
    assert row["embedding"] is None


def test_save_verdict_reads_the_six_signal_shape(conn):
    """The private loop in pipeline.py read `is_startup` and `confidence` straight
    off the verdict, keys the six-signal schema does not have, so every private
    row was stored as a non-startup with zero confidence and never ranked."""
    _row(conn, "wa", "whatsapp", "text", 0.9)
    thesis = next(t for t in theses.load_all() if t.id == "treeo")

    triage.save_verdict(conn, "wa", VERDICT, thesis)

    row = conn.execute("SELECT * FROM candidates WHERE id='wa'").fetchone()
    scores = {k: VERDICT[k]["score"] for k in (s.key for s in signals.SIGNALS)}
    assert row["is_startup"] == 1
    assert row["stage_guess"] == "pre-seed"
    assert row["confidence"] == pytest.approx(signals.combine(scores, thesis.weights))
    assert json.loads(row["triage_json"]) == VERDICT
