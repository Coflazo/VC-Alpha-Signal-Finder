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
import sqlite3
import struct

import httpx

from vc_alpha.theses import Thesis

log = logging.getLogger(__name__)

OLLAMA = "http://localhost:11434"
MODEL = "qwen3-embedding:0.6b"
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


class Embedder:
    def __init__(self, model: str = MODEL, base: str = OLLAMA):
        self.model = model
        self._client = httpx.Client(base_url=base, timeout=TIMEOUT)

    def available(self) -> bool:
        try:
            return self._client.get("/api/tags").status_code == 200
        except httpx.HTTPError:
            return False

    def embed(self, text: str) -> list[float]:
        r = self._client.post(
            "/api/embed", json={"model": self.model, "input": text[:MAX_CHARS]}
        )
        r.raise_for_status()
        return r.json()["embeddings"][0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        r = self._client.post(
            "/api/embed",
            json={"model": self.model, "input": [t[:MAX_CHARS] for t in texts]},
        )
        r.raise_for_status()
        return r.json()["embeddings"]


def thesis_vectors(emb: Embedder, theses: list[Thesis]) -> dict[str, list[float]]:
    """Embed each thesis once. Cheap enough to redo per run, so no cache to invalidate."""
    return {t.id: emb.embed(t.prose) for t in theses}


def score_pending(
    conn: sqlite3.Connection,
    emb: Embedder,
    theses: list[Thesis],
    *,
    batch: int = 32,
    limit: int | None = None,
) -> dict[str, int]:
    """Embed and score every candidate that has not been scored yet."""
    vectors = thesis_vectors(emb, theses)
    by_id = {t.id: t for t in theses}

    sql = "SELECT id, raw_text, title FROM candidates WHERE embedding IS NULL"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()

    stats = {"scored": 0, "skipped_empty": 0}

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
                s = cosine(vec, tvec)
                if s > best_score:
                    best_id, best_score = tid, s

            conn.execute(
                "UPDATE candidates SET embedding = ?, similarity = ?, thesis_id = ? WHERE id = ?",
                (pack(vec), best_score, best_id, row["id"]),
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
