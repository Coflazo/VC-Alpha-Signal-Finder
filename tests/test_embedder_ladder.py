"""The embedding ladder, and the vector-mixing failure it has to prevent.

Stage 2 runs over everything, so it is the one stage that genuinely cannot afford
to be slow. It used to be a Gemini-or-Ollama `if`, which meant a fund without a
Gemini key embedded locally at 2.4 seconds an item. Measured against Mistral at
batch 64: 12.5 ms an item.

The subtler problem is what happens when the provider changes. Vectors from
different providers have different dimensionalities, and both fastpath twins
define cosine between mismatched dimensions as 0.0. That is safe but silent —
every previously scored candidate drops to zero and reads as "nothing matches any
more" rather than "these need re-embedding".
"""

from __future__ import annotations

import sqlite3

import pytest

from vc_alpha import theses
from vc_alpha.db import SCHEMA, migrate
from vc_alpha.enrich.embed import (
    EMBEDDERS, Embedder, active_provider, pack, rescore_similarities, score_pending,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    migrate(c)
    return c


class Fake:
    """An embedder with a declared fingerprint, like the real one."""

    def __init__(self, fingerprint: str, dims: int = 4, provider: str = "fake"):
        self.fingerprint = fingerprint
        self.provider = provider
        self.dims = dims
        self.calls = 0

    def embed_many(self, texts):
        self.calls += len(texts)
        return [[float(len(t) % 7) + i for i in range(self.dims)] for t in texts]

    def embed(self, text):
        return self.embed_many([text])[0]


def _add(conn, cid, *, model=None, embedding=None):
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until, embedding, embedding_model, similarity)
           VALUES (?, 'hackernews', ?, 'I left my job to build developer tooling',
                   '2026-01-01', '2027-01-01', ?, ?, 0.5)""",
        (cid, f"https://x/{cid}", embedding, model),
    )
    conn.commit()


def test_the_ladder_falls_through_to_local_with_no_keys():
    """The promise the product makes: it works with nothing configured."""
    assert active_provider().name == "ollama"
    assert active_provider().local


def test_a_hosted_key_takes_precedence(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "pretend")
    assert active_provider().name == "cohere"
    # And a better rung wins over a worse one regardless of which was set first.
    monkeypatch.setenv("MISTRAL_API_KEY", "pretend")
    assert active_provider().name == "mistral"


def test_every_rung_is_overridable_by_environment(monkeypatch):
    """Model ids are the most perishable thing here; two shipped ones already 404."""
    monkeypatch.setenv("MISTRAL_API_KEY", "pretend")
    monkeypatch.setenv("MISTRAL_EMBED_MODEL", "mistral/some-future-model")
    import importlib

    from vc_alpha.enrich import embed as mod
    importlib.reload(mod)
    try:
        assert mod.active_provider().model == "mistral/some-future-model"
    finally:
        importlib.reload(mod)


def test_the_fingerprint_is_recorded_with_every_vector(conn):
    _add(conn, "a")
    emb = Fake("mistral/mistral-embed")
    score_pending(conn, emb, theses.load_all())
    row = conn.execute("SELECT embedding_model FROM candidates WHERE id='a'").fetchone()
    assert row["embedding_model"] == "mistral/mistral-embed"


def test_a_provider_change_re_embeds_rather_than_scoring_zero(conn):
    """The silent failure this column exists to prevent.

    Without it the old vector stays, cosine against the new thesis vectors is 0.0
    because the dimensions differ, and the candidate vanishes from every ranking
    with no error anywhere.
    """
    _add(conn, "old", model="gemini/text-embedding-004", embedding=pack([1.0, 0.0]))

    emb = Fake("mistral/mistral-embed")
    stats = score_pending(conn, emb, theses.load_all())

    assert stats["scored"] == 1, "a differently-embedded row must be picked up again"
    row = conn.execute(
        "SELECT embedding_model, similarity FROM candidates WHERE id='old'"
    ).fetchone()
    assert row["embedding_model"] == "mistral/mistral-embed"
    assert row["similarity"] is not None


def test_rescore_ignores_vectors_from_another_model(conn):
    """Rescoring compares stored vectors. Ones from another provider are not
    comparable, so they are left for score_pending rather than scored as zero."""
    _add(conn, "mine", model="fake/v1", embedding=pack([1.0, 0.0, 0.0, 0.0]))
    _add(conn, "theirs", model="other/v9", embedding=pack([1.0, 0.0]))

    assert rescore_similarities(conn, Fake("fake/v1"), theses.load_all()) == 1


def test_batch_size_follows_the_provider(conn, monkeypatch):
    """8 locally, where a batch takes minutes and resumability is worth the cost.
    64 hosted, where measurement showed batch 8 costs nearly 3x per item."""
    sizes = []

    class Counting(Fake):
        def embed_many(self, texts):
            sizes.append(len(texts))
            return super().embed_many(texts)

    for i in range(20):
        _add(conn, f"c{i}")
    score_pending(conn, Counting("x", provider="ollama"), theses.load_all())
    assert max(sizes) <= 8

    sizes.clear()
    conn.execute("UPDATE candidates SET embedding = NULL, embedding_model = NULL")
    conn.commit()
    score_pending(conn, Counting("y", provider="mistral"), theses.load_all())
    assert max(sizes) > 8


def test_whatsapp_never_reaches_a_hosted_embedder(conn):
    """Enforced by the query, not by callers remembering.

    The text has to be long enough to survive the cheap filters, or the row never
    reaches an embedder for reasons that have nothing to do with privacy and the
    test passes without testing anything.
    """
    private = ("I am leaving my job at the bank next month to build the invoice "
               "reconciliation thing we talked about, looking for a technical "
               "cofounder who has felt this problem")
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until) VALUES ('w','whatsapp','wa://1',?,
           '2026-01-01','2027-01-01')""",
        (private,),
    )
    conn.commit()

    class Refuses(Fake):
        def embed_many(self, texts):
            assert not any(private in t for t in texts), \
                "whatsapp text was sent to a hosted embedder"
            return super().embed_many(texts)

    assert score_pending(conn, Refuses("m", provider="mistral"),
                         theses.load_all())["scored"] == 0

    # ...but the local embedder is allowed to see it, which is the whole point of
    # having a local rung at all.
    assert score_pending(conn, Fake("local", provider="ollama"),
                         theses.load_all())["scored"] == 1


def test_nvidia_is_not_offered_as_an_embedding_rung():
    """Its embedding endpoints answered 410 Gone on every published model id.
    Listing it would promise a rung that does not exist."""
    assert "nvidia" not in {p.name for p in EMBEDDERS}


def test_embedder_reports_which_provider_is_live(monkeypatch):
    """Surfaced so a slow run has a visible explanation rather than being a mystery."""
    monkeypatch.setenv("MISTRAL_API_KEY", "pretend")
    e = Embedder()
    assert e.provider == "mistral"
    assert e.fingerprint == e.model
    assert not e.provider_info.local
