"""Extract entities from candidates and score them.

    uv run python -m vc_alpha.build_entities

Both steps are local and cheap: extraction reads URLs and authors already in the
text, and scoring reads triage results already stored. No model calls, so this can
run as often as you like.
"""

from __future__ import annotations

import argparse
import logging

from vc_alpha import env, extract, founders, theses
from vc_alpha.db import connect


def main() -> None:
    env.load()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = connect(args.db)

    found = extract.build(conn)
    print(f"{found['candidates']} candidates -> {found['mentions']} mentions")

    scored = founders.score_all(conn, theses.load_all())
    print(f"scored {scored['scored']} entities, {scored['skipped']} without triage yet")

    top = conn.execute(
        """SELECT name, kind, score, mentions, sources FROM entities
           WHERE score IS NOT NULL ORDER BY score DESC LIMIT 10"""
    ).fetchall()
    if top:
        print("\ntop entities:")
        for r in top:
            print(f"  {r['score']:.3f}  {r['kind']:<8} {r['name'][:36]:<36} {r['sources']}")


if __name__ == "__main__":
    main()
