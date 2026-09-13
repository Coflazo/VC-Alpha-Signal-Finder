"""Stage 2: embed everything, score it against every thesis, keep the best match.

This is the cheap gate and the one nothing downstream can recover from. A candidate
dropped here is never seen by triage, research or the report, so the threshold is the
most consequential number in the system. It is a config value, not a constant, and it
wants calibrating against hand-labelled data rather than guessing.

No LLM calls here. Embedding a post costs milliseconds and no tokens, which is what
makes it affordable to run over everything.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import struct
from dataclasses import dataclass

import httpx

from vc_alpha.fastpath import cosine_blobs
from vc_alpha.filters import reject
from vc_alpha.theses import Thesis

log = logging.getLogger(__name__)

OLLAMA = "http://localhost:11434"
MODEL = "qwen3-embedding:0.6b"          # local fallback
TIMEOUT = httpx.Timeout(120.0)

# Starting point only. Calibrate against labelled data before trusting it.
DEFAULT_THRESHOLD = 0.35

# Embedding models cost more per token than they gain from very long inputs, and most
# of the signal in a post is near the top.
MAX_CHARS = 4000


def pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


@dataclass(frozen=True, slots=True)
class EmbeddingProvider:
    """One rung of the embedding ladder. Mirrors llm.Provider deliberately."""

    name: str
    env_key: str
    model: str          # a LiteLLM identifier, except for the local rung

    @property
    def local(self) -> bool:
        return self.name == "ollama"

    @property
    def key(self) -> str | None:
        return os.environ.get(self.env_key)

    @property
    def configured(self) -> bool:
        return self.local or bool(self.key)


# Ordered best-first. Checked against live calls on 14 September 2026.
#
# This used to be a Gemini-or-Ollama `if`, which meant a fund without a Gemini key
# fell all the way to local embedding at 2.4 seconds an item — and stage 2 is the
# stage that has to run over *everything*. Embedding is the one place the product
# genuinely cannot afford to be slow, so it gets a ladder like inference has.
EMBEDDERS = [
    EmbeddingProvider("mistral", "MISTRAL_API_KEY",
                      os.environ.get("MISTRAL_EMBED_MODEL", "mistral/mistral-embed")),
    EmbeddingProvider("cohere", "COHERE_API_KEY",
                      os.environ.get("COHERE_EMBED_MODEL", "cohere/embed-v4.0")),
    EmbeddingProvider("gemini", "GEMINI_API_KEY",
                      os.environ.get("GEMINI_EMBED_MODEL",
                                     "gemini/text-embedding-004")),
    # Always available, needs no key, and the only rung private sources may use.
    EmbeddingProvider("ollama", "OLLAMA_HOST", os.environ.get("EMBED_MODEL", MODEL)),
]

# NVIDIA is deliberately absent. Its embedding endpoints answered 410 Gone on every
# published model id when this was checked, so listing it would promise a rung that
# does not exist.


def active_provider() -> EmbeddingProvider:
    return next(p for p in EMBEDDERS if p.configured)


class Embedder:
    """Embeddings from the best configured free provider.

    Hosted providers go through LiteLLM, which is already the product's gateway for
    inference and normalises every provider's response shape. Ollama keeps its own
    direct call: it is the privacy-critical path and the one that has to work when
    nothing else does, so it does not gain a dependency it does not need.
    """

    def __init__(self, model: str | None = None, base: str = OLLAMA,
                 provider: EmbeddingProvider | None = None):
        self.provider_info = provider or active_provider()
        self.provider = self.provider_info.name
        self.model = model or self.provider_info.model
        self._client = httpx.Client(timeout=TIMEOUT)
        self._base = base

    @property
    def fingerprint(self) -> str:
        """What gets stored beside each vector, so vectors are never mixed.

        Different providers return different dimensionalities — Mistral 1024,
        Cohere 1536, Gemini 768 — and cosine between two of them is defined to be
        zero by both fastpath twins. That is safe but silent: switch provider and
        every previously scored candidate quietly drops to 0.0 similarity, which
        reads as "nothing matches any more" rather than "these need re-embedding".
        """
        return self.model

    def available(self) -> bool:
        if not self.provider_info.local:
            return True
        try:
            return self._client.get(f"{self._base}/api/tags").status_code == 200
        except httpx.HTTPError:
            return False

    def _hosted(self, texts: list[str]) -> list[list[float]]:
        from vc_alpha.llm import quiet_litellm

        litellm = quiet_litellm()
        response = litellm.embedding(
            model=self.model, input=[t[:MAX_CHARS] for t in texts]
        )
        # LiteLLM normalises to OpenAI's shape but does not guarantee ordering on
        # every provider, so index rather than trusting the sequence.
        data = sorted(response.data, key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    def _ollama(self, texts: list[str]) -> list[list[float]]:
        r = self._client.post(
            f"{self._base}/api/embed",
            json={"model": self.model, "input": [t[:MAX_CHARS] for t in texts]},
        )
        r.raise_for_status()
        return r.json()["embeddings"]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return self._ollama(texts) if self.provider_info.local else self._hosted(texts)

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]


def thesis_vectors(
    emb: Embedder, theses: list[Thesis]
) -> dict[str, list[list[float]]]:
    """Embed every phrasing of every thesis. A handful of vectors, computed once.

    Each thesis gets one vector per phrasing: the fund's own prose, and the same
    thesis as a founder would write it. A candidate scores against the best of
    them, so VC commentary and a founder's own post can both match without either
    being penalised for using the wrong vocabulary.
    """
    return {t.id: emb.embed_many(t.vectors_text()) for t in theses}


def best_similarity(vec: list[float], thesis_vecs: list[list[float]]) -> float:
    """Max over a thesis's phrasings. Max, not mean: matching one framing well is
    the signal, and averaging would dilute it with the framing that does not apply."""
    return max((cosine(vec, tv) for tv in thesis_vecs), default=0.0)


def score_pending(
    conn: sqlite3.Connection,
    emb: Embedder,
    theses: list[Thesis],
    *,
    batch: int | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    """Embed and score every candidate that has not been scored yet.

    Batch size follows the provider, because the trade-off is not the same on both.

    Locally, a batch of 32 can sit in flight for minutes on a 2-core laptop, which
    makes progress invisible and a Ctrl-C expensive. Each batch commits, so small
    batches buy resumability at almost no throughput cost — 8 is right there.

    Hosted, the numbers invert. Measured on Mistral: 35.6 ms/item at batch 8 and
    12.5 ms/item at batch 64, so the small batch costs nearly 3x for resumability
    of a batch that takes under a second anyway.
    """
    if batch is None:
        batch = 8 if getattr(emb, "provider", "") == "ollama" else 64
    vectors = thesis_vectors(emb, theses)
    by_id = {t.id: t for t in theses}

    # WhatsApp text is private and must be embedded locally. Rather than trusting
    # callers to remember, a cloud embedder simply does not see those rows.
    #
    # Rows embedded by a *different* model are picked up too. Their stored vector
    # cannot be compared against this one — different dimensionality scores zero —
    # so leaving them alone would silently drop them out of every future ranking.
    sql = ("SELECT id, raw_text, title, source, posted_at FROM candidates "
           "WHERE (embedding IS NULL OR embedding_model IS NOT ?) "
           "AND filtered_reason IS NULL")
    params: list = [emb.fingerprint]
    if emb.provider != "ollama":
        sql += " AND source NOT IN ('whatsapp')"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, params).fetchall()

    stats = {"scored": 0, "skipped_empty": 0, "filtered": 0}

    # Filter before embedding, not after. Embedding costs seconds per item on
    # modest hardware and these predicates cost microseconds, so every candidate
    # dropped here is time bought back. The reason is recorded rather than the row
    # deleted, so over-filtering is visible instead of silent.
    keep = []
    for row in rows:
        if r := reject(row["raw_text"] or "", posted_at=row["posted_at"]):
            conn.execute(
                "UPDATE candidates SET filtered_reason = ? WHERE id = ?",
                (f"{r.filter}: {r.reason}", row["id"]),
            )
            stats["filtered"] += 1
        else:
            keep.append(row)
    conn.commit()
    rows = keep

    for i in range(0, len(rows), batch):
        chunk = [r for r in rows[i : i + batch] if (r["raw_text"] or "").strip()]
        stats["skipped_empty"] += len(rows[i : i + batch]) - len(chunk)
        if not chunk:
            continue

        vecs = emb.embed_many([r["raw_text"] for r in chunk])

        for row, vec in zip(chunk, vecs):
            best_id, best_score = None, -1.0
            for tid, tvec in vectors.items():
                # A thesis that excludes this outright should not be able to match it.
                if by_id[tid].excluded(row["raw_text"]):
                    continue
                s = best_similarity(vec, tvec)
                if s > best_score:
                    best_id, best_score = tid, s

            conn.execute(
                "UPDATE candidates SET embedding = ?, embedding_model = ?, "
                "similarity = ?, thesis_id = ? WHERE id = ?",
                (pack(vec), emb.fingerprint, best_score, best_id, row["id"]),
            )
            stats["scored"] += 1

        conn.commit()
        log.info("scored %d/%d", stats["scored"], len(rows))

    return stats


def survivors(
    conn: sqlite3.Connection, threshold: float = DEFAULT_THRESHOLD, limit: int = 50
) -> list[sqlite3.Row]:
    """What passes the gate, best first. This is what stage 3 sees."""
    return conn.execute(
        """SELECT * FROM candidates
           WHERE similarity >= ? ORDER BY similarity DESC LIMIT ?""",
        (threshold, limit),
    ).fetchall()


def rescore_similarities(
    conn: sqlite3.Connection, emb: Embedder, theses: list[Thesis]
) -> int:
    """Recompute similarity from stored vectors, without re-embedding anything.

    Candidate vectors do not change when a thesis is reworded or a new phrasing is
    added; only the comparison does. Re-embedding 565 candidates costs half an hour
    on this hardware, recomputing cosine over stored blobs costs a second. Anything
    that edits a thesis should call this, not score_pending.
    """
    vectors = thesis_vectors(emb, theses)
    by_id = {t.id: t for t in theses}
    # Only vectors this embedder produced. A row embedded by another provider would
    # score 0.0 against every thesis and look like a candidate that stopped
    # matching, rather than one that needs re-embedding; score_pending picks those
    # up instead.
    rows = conn.execute(
        "SELECT id, embedding, raw_text FROM candidates "
        "WHERE embedding IS NOT NULL AND embedding_model IS ?",
        (emb.fingerprint,),
    ).fetchall()
    stale = conn.execute(
        "SELECT COUNT(*) FROM candidates "
        "WHERE embedding IS NOT NULL AND embedding_model IS NOT ?",
        (emb.fingerprint,),
    ).fetchone()[0]
    if stale:
        log.warning(
            "%d candidates were embedded by a different model and are not ranked "
            "until re-embedded; run score again to pick them up", stale)

    # Flatten every thesis phrasing into one query list so the whole comparison is
    # a single call into the C++ kernel rather than a Python loop per candidate.
    flat, owner = [], []
    for tid, tvecs in vectors.items():
        for tv in tvecs:
            flat.append(tv)
            owner.append(tid)

    blobs = [row["embedding"] for row in rows]
    scores = cosine_blobs(blobs, flat)

    for row, row_scores in zip(rows, scores):
        best_id, best_score = None, -1.0
        for tid, s in zip(owner, row_scores):
            if by_id[tid].excluded(row["raw_text"]):
                continue
            if s > best_score:
                best_id, best_score = tid, s
        conn.execute(
            "UPDATE candidates SET similarity = ?, thesis_id = ? WHERE id = ?",
            (best_score, best_id, row["id"]),
        )
    conn.commit()
    return len(rows)


def survivors_by_rank(
    conn: sqlite3.Connection, keep_rate: float = 0.10, floor: float = 0.25
) -> list[sqlite3.Row]:
    """Top `keep_rate` of each source, subject to an absolute floor.

    Per source, because sources have different baselines. Measured: Substack reaches
    0.58 while Hacker News tops out near 0.42, so one global threshold set for
    Substack would discard every HN candidate, including the first-hand founder posts
    that are the best signal in the system. Each source competes with itself.

    The floor is the safety net for a run where an entire source is junk: without it,
    "top 10%" faithfully returns the best 10% of nothing worth having.
    """
    out: list[sqlite3.Row] = []
    for (source,) in conn.execute(
        "SELECT DISTINCT source FROM candidates WHERE similarity IS NOT NULL"
    ).fetchall():
        n = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE source = ? AND similarity >= ?",
            (source, floor),
        ).fetchone()[0]
        if not n:
            continue
        out.extend(conn.execute(
            """SELECT * FROM candidates
               WHERE source = ? AND similarity >= ?
               ORDER BY similarity DESC LIMIT ?""",
            (source, floor, max(1, round(n * keep_rate))),
        ).fetchall())
    return sorted(out, key=lambda r: r["similarity"], reverse=True)
