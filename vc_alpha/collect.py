"""Run a collection pass.

    uv run python -m vc_alpha.collect --source substack --visits 5
    uv run python -m vc_alpha.collect --suggestions substack
"""

from __future__ import annotations

import argparse
import logging
import sqlite3

from vc_alpha import frontier, theses
from vc_alpha.collectors.base import CandidateRecord
from vc_alpha.collectors.github import GitHubCollector
from vc_alpha.collectors.hackernews import HackerNewsCollector
from vc_alpha.collectors.substack import SubstackCollector
from vc_alpha.db import connect, now, retention_until

log = logging.getLogger(__name__)

COLLECTORS = {
    "substack": SubstackCollector,
    "hackernews": HackerNewsCollector,
    "github": GitHubCollector,
}


def store(conn: sqlite3.Connection, records: list[CandidateRecord], active) -> int:
    """Insert new candidates, dropping anything a thesis excludes outright.

    Returns how many survived. That count is the node's hit contribution, which is
    what the frontier gates expansion on.
    """
    kept = 0
    for r in records:
        if all(t.excluded(r.raw_text) for t in active):
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO candidates
               (id, source, source_url, raw_text, title, author, node,
                discovered_at, posted_at, retention_until)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r.id, r.source, r.source_url, r.raw_text, r.title, r.author,
             r.node, now(), r.posted_at, retention_until()),
        )
        kept += cur.rowcount  # 0 when already seen, so reruns add nothing
    conn.commit()
    return kept


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=sorted(COLLECTORS), default="substack")
    ap.add_argument("--visits", type=int, default=10)
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--db", default="data/candidates.sqlite")
    ap.add_argument("--seed", action="append", help="extra node to start from")
    ap.add_argument("--suggestions", metavar="SOURCE",
                    help="show discovered nodes ranked by measured hit rate, then exit")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = connect(args.db)

    if args.suggestions:
        rows = frontier.suggestions(conn, args.suggestions)
        if not rows:
            print("nothing discovered yet — run a collection pass first")
            return
        print(f"{'node':<28} {'hit rate':>9} {'hits':>6} {'seen':>6}  from")
        for r in rows:
            print(f"{r['node']:<28} {r['hit_rate']:>8.1%} {r['hit_count']:>6} "
                  f"{r['seen_count']:>6}  {r['parent'] or '-'}")
        return

    active = theses.load_all()
    collector = COLLECTORS[args.source]()

    for node in args.seed or []:
        if frontier.add_node(conn, args.source, node, source_kind="manual"):
            log.info("seeded %s", node)

    stats = frontier.expand(
        conn, collector,
        frontier.Budget(max_visits=args.visits, max_depth=args.depth),
        on_candidates=lambda recs: store(conn, recs, active),
    )

    total = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    log.info(
        "visited %(visited)d, %(candidates)d candidates, %(hits)d new, "
        "%(discovered)d nodes discovered", stats,
    )
    log.info("%d candidates in the database", total)


if __name__ == "__main__":
    main()
