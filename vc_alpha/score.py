"""Final ranking.

Three signals, deliberately combined rather than picking one:

  similarity    stage 2, cheap and shallow. Topical proximity only.
  thesis_match  stage 3, a model that actually read the post.
  recency       a founder who posted eight months ago has already been found.

The weights below are a starting guess. They stay a guess until enough `was_good`
labels exist to fit them, and the honest move then is to refit rather than defend
the numbers that happen to be here.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone

W_SIMILARITY = 0.3
W_THESIS_MATCH = 0.5
W_RECENCY = 0.2

# A post loses half its recency credit after this long. Roughly the window in which
# a pre-seed founder is still findable before the round is done.
HALF_LIFE_DAYS = 90


def recency_decay(posted_at: str | None, *, now: datetime | None = None) -> float:
    """1.0 for something posted today, decaying by half every HALF_LIFE_DAYS.

    Unknown dates get 0.5 rather than 0 or 1: absent evidence should neither
    reward nor punish, and plenty of sources omit a timestamp.
    """
    if not posted_at:
        return 0.5
    try:
        when = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.5
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    days = ((now or datetime.now(timezone.utc)) - when).total_seconds() / 86400
    if days < 0:
        return 1.0
    return math.pow(0.5, days / HALF_LIFE_DAYS)


def combine(similarity: float | None, thesis_match: float | None,
            posted_at: str | None, *, now: datetime | None = None) -> float:
    return (
        W_SIMILARITY * (similarity or 0.0)
        + W_THESIS_MATCH * (thesis_match or 0.0)
        + W_RECENCY * recency_decay(posted_at, now=now)
    )


def rescore(conn: sqlite3.Connection) -> int:
    """Recompute scores for everything triaged. Cheap, so just redo all of it."""
    import json

    rows = conn.execute(
        "SELECT id, similarity, triage_json, posted_at FROM candidates "
        "WHERE triage_json IS NOT NULL"
    ).fetchall()

    for r in rows:
        try:
            match = json.loads(r["triage_json"]).get("thesis_match")
        except (ValueError, TypeError):
            match = None
        conn.execute(
            "UPDATE candidates SET score = ? WHERE id = ?",
            (combine(r["similarity"], match, r["posted_at"]), r["id"]),
        )
    conn.commit()
    return len(rows)


def ranked(conn: sqlite3.Connection, thesis_id: str | None = None,
           limit: int = 50, min_confidence: float = 0.0) -> list[sqlite3.Row]:
    sql = ["SELECT * FROM candidates WHERE score IS NOT NULL AND is_startup = 1"]
    params: list = []
    if thesis_id:
        sql.append("AND thesis_id = ?")
        params.append(thesis_id)
    if min_confidence:
        sql.append("AND confidence >= ?")
        params.append(min_confidence)
    sql.append("ORDER BY score DESC LIMIT ?")
    params.append(limit)
    return conn.execute(" ".join(sql), params).fetchall()
