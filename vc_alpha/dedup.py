"""Near-duplicate detection, in O(N) rather than O(N²).

The pipeline deduplicates on exact `source_url` only, so the same launch posted to
Hacker News, written up in a newsletter and linked from Reddit is three candidates,
three embeddings and three triage calls. That is wasted money on the paid path and
wasted hours on the local one, and it distorts the frontier's hit-rate statistics
by counting one thing three times.

Comparing every pair is O(N²): at 100,000 candidates that is five billion
comparisons. **MinHash with LSH banding** makes it O(N) expected.

## How it works

A MinHash signature is the minimum hash of any word shingle, under each of many
independent hash seeds. Two documents agree at a signature position with
probability equal to the Jaccard similarity of their shingle sets, so comparing
signatures estimates similarity without comparing documents.

LSH then avoids comparing even the signatures pairwise. Split the signature into
`bands` bands and hash each band. Two documents sharing any band hash become a
candidate pair. The probability of that is

    P(share a band) = 1 − (1 − s^r)^b

with s the true similarity, r rows per band, b bands. That curve is an S-shape with
its steep region near s ≈ (1/b)^(1/r), which is the tunable threshold. Only
candidate pairs are compared properly, and there are O(N) of them.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict

from vc_alpha.fastpath import band_hashes, minhash, signature_similarity

log = logging.getLogger(__name__)

PERMS = 128
BANDS = 16          # 8 rows per band → steep near s ≈ 0.74
SHINGLE = 3
THRESHOLD = 0.70    # confirmed similarity required to call it a duplicate

SCHEMA = """
CREATE TABLE IF NOT EXISTS duplicates (
  candidate_id  TEXT PRIMARY KEY,
  duplicate_of  TEXT NOT NULL,
  similarity    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dup_of ON duplicates(duplicate_of);
"""


def install(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def bands_for(threshold: float, perms: int = PERMS) -> int:
    """Band count whose LSH threshold is closest to the one asked for.

    The banding decides which pairs are ever *compared*; the threshold only decides
    which compared pairs are *kept*. Leaving banding fixed while the caller lowers
    the threshold produces a parameter that silently does not work: the pair is
    filtered correctly but never surfaced in the first place.

    The approximate LSH threshold for b bands of r rows is (1/b)^(1/r), so this
    picks the divisor of `perms` whose value lands nearest the request.
    """
    divisors = [b for b in range(1, perms + 1) if perms % b == 0]
    return min(divisors, key=lambda b: abs((1.0 / b) ** (b / perms) - threshold))


def find_duplicates(texts: dict[str, str], threshold: float = THRESHOLD,
                    bands: int | None = None, perms: int = PERMS
                    ) -> dict[str, tuple[str, float]]:
    """Map each duplicate id to the id it duplicates, and the measured similarity.

    The first occurrence in iteration order is treated as the original, so results
    are stable for a stable input order.

    LSH is probabilistic: a pair above the threshold can still be missed if it
    happens to collide in no band. Band count is derived from the threshold so the
    miss rate stays low for the similarity actually being asked about.
    """
    if bands is None:
        bands = bands_for(threshold, perms)
    sigs = {cid: minhash(text or "", perms, SHINGLE) for cid, text in texts.items()}

    # Bucket by band hash. Only ids sharing a bucket are ever compared.
    buckets: dict[tuple[int, int], list[str]] = defaultdict(list)
    for cid, sig in sigs.items():
        for band_index, h in enumerate(band_hashes(sig, bands)):
            buckets[(band_index, h)].append(cid)

    order = {cid: i for i, cid in enumerate(texts)}
    dupes: dict[str, tuple[str, float]] = {}

    for members in buckets.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda c: order[c])
        first = members[0]
        for other in members[1:]:
            if other in dupes:
                continue
            s = signature_similarity(sigs[first], sigs[other])
            if s >= threshold:
                dupes[other] = (first, s)
    return dupes


def mark_duplicates(conn: sqlite3.Connection, limit: int | None = None,
                    threshold: float = THRESHOLD) -> dict[str, int]:
    """Flag near-duplicate candidates so they are not embedded or triaged twice.

    Marked rather than deleted: the duplicate is evidence that the same thing
    surfaced in more than one place, which is exactly the corroboration signal
    entity scoring rewards. Deleting it would discard that.
    """
    install(conn)
    sql = ("SELECT id, title, raw_text FROM candidates "
           "WHERE filtered_reason IS NULL ORDER BY discovered_at")
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()

    texts = {r["id"]: f"{r['title'] or ''} {r['raw_text'] or ''}" for r in rows}
    dupes = find_duplicates(texts, threshold)

    for cid, (original, sim) in dupes.items():
        conn.execute("INSERT OR REPLACE INTO duplicates VALUES (?,?,?)",
                     (cid, original, sim))
        conn.execute(
            "UPDATE candidates SET filtered_reason = ? WHERE id = ? "
            "AND filtered_reason IS NULL",
            (f"duplicate: {sim:.2f} similar to {original[:12]}", cid),
        )
    conn.commit()
    return {"examined": len(rows), "duplicates": len(dupes)}
