"""Run stage 2 over everything unscored, then show what survived.

    uv run python -m vc_alpha.score_all
    uv run python -m vc_alpha.score_all --thesis treeo --top 15
"""

from __future__ import annotations

import argparse
import logging

from vc_alpha import theses
from vc_alpha.db import connect
from vc_alpha.enrich.embed import DEFAULT_THRESHOLD, Embedder, score_pending


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/candidates.sqlite")
    ap.add_argument("--limit", type=int, help="only score this many (for a quick look)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--thesis", help="show top matches for one thesis")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = connect(args.db)
    active = theses.load_all()
    emb = Embedder()

    if not emb.available():
        raise SystemExit("ollama is not reachable at localhost:11434 — run 'ollama serve'")

    stats = score_pending(conn, emb, active, limit=args.limit)
    print(f"scored {stats['scored']}, skipped {stats['skipped_empty']} empty")

    if args.thesis:
        rows = conn.execute(
            """SELECT title, source, author, similarity FROM candidates
               WHERE thesis_id = ? ORDER BY similarity DESC LIMIT ?""",
            (args.thesis, args.top),
        ).fetchall()
        print(f"\ntop matches for {args.thesis}:")
        for r in rows:
            print(f"  {r['similarity']:.3f}  [{r['source']:<10}] {(r['title'] or '')[:62]}")
        return

    print("\nbest match per thesis:")
    for t in active:
        row = conn.execute(
            """SELECT COUNT(*) n, MAX(similarity) hi FROM candidates WHERE thesis_id = ?""",
            (t.id,),
        ).fetchone()
        print(f"  {t.id:<12} claimed {row['n']:>4}   best {row['hi'] or 0:.3f}")

    above = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE similarity >= ?", (args.threshold,)
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    print(f"\n{above}/{total} above threshold {args.threshold}")


if __name__ == "__main__":
    main()
