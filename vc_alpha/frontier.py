"""Score-gated graph expansion, shared by all three sources.

The rule that matters: only expand from nodes that produced good candidates.

That is a quality mechanism before it is a safety one. Expanding blindly from a
founder's LinkedIn reaches their recruiters and university classmates within two
hops, and on Substack it drifts from startup newsletters into cooking ones. Gating
on yield keeps a crawl on-thesis. It also happens to keep request volume low, which
is what makes LinkedIn survivable.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from vc_alpha.collectors.base import Collector, Neighbour
from vc_alpha.db import now

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Budget:
    """Hard limits on one expansion run. LinkedIn needs these to be small."""

    max_visits: int = 50
    max_depth: int = 3
    # A node must produce at least this fraction of hits to be worth expanding from.
    min_hit_rate: float = 0.02
    # ...but only once it has been seen enough times for that rate to mean anything.
    min_seen_before_gating: int = 20


def add_node(
    conn: sqlite3.Connection,
    source: str,
    node: str,
    *,
    display_name: str | None = None,
    source_kind: str = "discovered",
    depth: int = 0,
    parent: str | None = None,
) -> bool:
    """Add a node to the frontier. Returns False if it was already known.

    Already-known covers deactivated nodes too, so a node the user rejected does
    not quietly come back the next time discovery runs.
    """
    cur = conn.execute(
        """INSERT OR IGNORE INTO nodes
           (source, node, display_name, added_at, source_kind, depth, parent)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source, node, display_name, now(), source_kind, depth, parent),
    )
    conn.commit()
    return cur.rowcount > 0


def deactivate(conn: sqlite3.Connection, source: str, node: str) -> None:
    """Stop visiting a node without forgetting it.

    Soft delete on purpose: the hit-rate history survives, and discovery will not
    re-suggest something already turned down.
    """
    conn.execute(
        "UPDATE nodes SET active = 0 WHERE source = ? AND node = ?", (source, node)
    )
    conn.commit()


def pending(conn: sqlite3.Connection, source: str, budget: Budget) -> list[sqlite3.Row]:
    """Nodes worth visiting next, shallowest first.

    Shallowest-first keeps the crawl near its seeds, where precision is highest,
    rather than racing to the edge of the graph.
    """
    return conn.execute(
        """SELECT * FROM nodes
           WHERE source = ? AND active = 1 AND exhausted = 0 AND depth <= ?
           ORDER BY last_visited IS NOT NULL, depth, last_visited
           LIMIT ?""",
        (source, budget.max_depth, budget.max_visits),
    ).fetchall()


def record_visit(
    conn: sqlite3.Connection, source: str, node: str, seen: int, hits: int, exhausted: bool
) -> None:
    conn.execute(
        """UPDATE nodes
           SET seen_count = seen_count + ?, hit_count = hit_count + ?,
               last_visited = ?, exhausted = ?
           WHERE source = ? AND node = ?""",
        (seen, hits, now(), int(exhausted), source, node),
    )
    conn.commit()


def worth_expanding(row: sqlite3.Row, budget: Budget) -> bool:
    """Has this node earned the right to add its neighbours to the frontier?

    Seed nodes always qualify, otherwise nothing would ever expand from a cold
    start. Beyond that a node must clear the hit-rate bar, but only once it has
    been seen enough times for the rate to be meaningful: one hit out of two posts
    is not a 50% hit rate, it is noise.
    """
    if row["source_kind"] == "seed":
        return True
    if row["seen_count"] < budget.min_seen_before_gating:
        return True  # not enough evidence to reject it yet
    return (row["hit_count"] / row["seen_count"]) >= budget.min_hit_rate


def expand(
    conn: sqlite3.Connection,
    collector: Collector,
    budget: Budget | None = None,
    *,
    on_candidates=None,
) -> dict[str, int]:
    """Visit pending nodes, store what they yield, and grow the frontier.

    `on_candidates` receives each visit's candidates so the caller decides how they
    are scored and stored. The frontier deliberately knows nothing about scoring.
    """
    budget = budget or Budget()
    source = collector.source

    if not conn.execute(
        "SELECT 1 FROM nodes WHERE source = ? LIMIT 1", (source,)
    ).fetchone():
        for seed in collector.seeds():
            add_node(
                conn, source, seed.node,
                display_name=seed.display_name, source_kind="seed", depth=0,
            )

    stats = {"visited": 0, "candidates": 0, "hits": 0, "discovered": 0}

    for row in pending(conn, source, budget):
        if stats["visited"] >= budget.max_visits:
            break
        try:
            visit = collector.visit(row["node"])
        except Exception:
            # One bad node must never end a run. Fail open, keep going.
            log.exception("visit failed: %s/%s", source, row["node"])
            continue

        stats["visited"] += 1
        stats["candidates"] += len(visit.candidates)

        hits = on_candidates(visit.candidates) if on_candidates else 0
        stats["hits"] += hits
        record_visit(conn, source, row["node"], len(visit.candidates), hits, visit.exhausted)

        if worth_expanding(row, budget) and row["depth"] < budget.max_depth:
            for nb in visit.neighbours:
                if add_node(
                    conn, source, nb.node,
                    display_name=nb.display_name,
                    depth=row["depth"] + 1, parent=row["node"],
                ):
                    stats["discovered"] += 1

    return stats


def suggestions(conn: sqlite3.Connection, source: str, limit: int = 20) -> list[sqlite3.Row]:
    """Discovered nodes ranked by measured hit rate, for the user to accept or reject.

    Measured, not guessed. A model can explain why a node looks promising, but the
    ordering here comes from what it actually produced.
    """
    return conn.execute(
        """SELECT *, CAST(hit_count AS REAL) / seen_count AS hit_rate
           FROM nodes
           WHERE source = ? AND source_kind = 'discovered'
             AND active = 1 AND seen_count > 0
           ORDER BY hit_rate DESC, hit_count DESC
           LIMIT ?""",
        (source, limit),
    ).fetchall()
