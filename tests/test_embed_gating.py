"""Stage 2 is the gate nothing downstream can recover from, so its two known
failure modes are pinned here: register bias against founders, and one source
crowding out another.
"""

import sqlite3

import pytest

from vc_alpha import theses
from vc_alpha.db import SCHEMA
from vc_alpha.enrich.embed import (
    best_similarity, cosine, pack, rescore_similarities, survivors_by_rank, unpack,
)


class FakeEmbedder:
    """Deterministic bag-of-words vectors. No model, no network, no 6s per call."""

    VOCAB = ["founder", "built", "moved", "pre-seed", "checks", "portfolio", "colour"]

    def embed_many(self, texts):
        return [
            [float(t.lower().count(w)) for w in self.VOCAB] or [0.0] * len(self.VOCAB)
            for t in texts
        ]

    def embed(self, text):
        return self.embed_many([text])[0]


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def test_packing_round_trips():
    vec = [0.1, -0.25, 3.0]
    assert unpack(pack(vec)) == pytest.approx(vec, abs=1e-6)


def test_cosine_bounds():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 1]) == 0.0, "zero vector must not divide by zero"


def test_best_similarity_takes_the_max_not_the_mean():
    """Matching one phrasing well is the signal. Averaging dilutes it with the
    phrasing that does not apply."""
    vec = [1.0, 0.0]
    assert best_similarity(vec, [[1.0, 0.0], [0.0, 1.0]]) == pytest.approx(1.0)


def test_every_thesis_has_both_phrasings():
    for t in theses.load_all():
        assert len(t.vectors_text()) == 2, f"{t.id} is missing founder_voice"


def test_founder_voice_lifts_a_first_hand_post():
    """The bug this fixes: fund-language prose matches VC commentary better than it
    matches a founder describing their own company, which is backwards."""
    emb = FakeEmbedder()
    prose = emb.embed("we write pre-seed checks into portfolio companies")
    voice = emb.embed("I moved countries and built this, I am the founder")
    post = emb.embed("I moved here and built it, I am the founder")

    assert best_similarity(post, [prose, voice]) > cosine(post, prose)


def _add(conn, cid, source, sim):
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until, similarity, embedding)
           VALUES (?,?,?,?,'2026-01-01','2027-01-01',?,?)""",
        (cid, source, f"https://x/{cid}", "text", sim, pack([sim, 0.0])),
    )
    conn.commit()


def test_rank_gating_keeps_every_source_represented(conn):
    """A global threshold tuned for the high-baseline source silently deletes the
    low-baseline one. Measured: Substack reaches 0.58, Hacker News 0.42."""
    for i in range(20):
        _add(conn, f"sub{i}", "substack", 0.40 + i * 0.01)
    for i in range(20):
        _add(conn, f"hn{i}", "hackernews", 0.26 + i * 0.005)

    sources = {r["source"] for r in survivors_by_rank(conn, keep_rate=0.2, floor=0.25)}
    assert sources == {"substack", "hackernews"}, "a source was crowded out"


def test_floor_blocks_a_junk_source_entirely(conn):
    """Without a floor, 'top 10%' faithfully returns the best 10% of nothing."""
    for i in range(10):
        _add(conn, f"junk{i}", "github", 0.05 + i * 0.001)
    assert survivors_by_rank(conn, keep_rate=0.5, floor=0.25) == []


def test_rescore_uses_stored_vectors_and_never_re_embeds(conn):
    """Rewording a thesis must not cost a re-embedding pass. On this hardware that
    is the difference between one second and half an hour."""
    _add(conn, "a", "substack", 0.0)

    class Exploding(FakeEmbedder):
        def embed_many(self, texts):
            if any("text" == t for t in texts):
                raise AssertionError("re-embedded a candidate during rescore")
            return super().embed_many(texts)

    assert rescore_similarities(conn, Exploding(), theses.load_all()) == 1
    assert conn.execute("SELECT similarity FROM candidates WHERE id='a'").fetchone()[0] is not None
