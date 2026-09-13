"""Choose the stage-2 threshold from data instead of guessing it.

This is the most consequential number in the system. Everything after stage 2 only
ever sees what survived it, so a candidate dropped here is invisible to triage,
research and the report. Too high and real signal dies where nothing can rescue it.
Too low and triage drowns and burns the daily free allowance on noise.

    uv run python -m vc_alpha.calibrate distribution
    uv run python -m vc_alpha.calibrate sample --n 100 > data/to_label.csv
    uv run python -m vc_alpha.calibrate evaluate --labels data/labels.csv
"""

from __future__ import annotations

import argparse
import csv
import random
import sqlite3
import sys
from pathlib import Path

from vc_alpha import env
from vc_alpha.db import connect


def percentiles(values: list[float], points=(5, 25, 50, 75, 90, 95, 99)) -> dict[int, float]:
    if not values:
        return {}
    ordered = sorted(values)
    return {
        p: ordered[min(int(len(ordered) * p / 100), len(ordered) - 1)] for p in points
    }


def distribution(conn: sqlite3.Connection) -> None:
    """Where the scores actually sit, overall and cut by source and thesis.

    Cut by source because a Substack post and an HN title differ wildly in length,
    and length moves cosine. If the per-source distributions are far apart, one
    global threshold is the wrong shape and each source needs its own.
    """
    rows = conn.execute(
        "SELECT source, thesis_id, similarity FROM candidates WHERE similarity IS NOT NULL"
    ).fetchall()
    if not rows:
        sys.exit("nothing scored yet — run vc_alpha.score_all first")

    def show(label: str, vals: list[float]) -> None:
        pct = percentiles(vals)
        line = "  ".join(f"p{p}={v:.3f}" for p, v in pct.items())
        print(f"{label:<22} n={len(vals):<5} {line}")

    print(f"\n{'scope':<22} {'count':<7} percentiles")
    print("-" * 92)
    show("ALL", [r["similarity"] for r in rows])

    print()
    for source in sorted({r["source"] for r in rows}):
        show(f"source: {source}", [r["similarity"] for r in rows if r["source"] == source])

    print()
    for tid in sorted({r["thesis_id"] for r in rows if r["thesis_id"]}):
        show(f"thesis: {tid}", [r["similarity"] for r in rows if r["thesis_id"] == tid])

    all_vals = [r["similarity"] for r in rows]
    pct = percentiles(all_vals)
    print(
        f"\nA threshold keeping the top 5% sits at {pct[95]:.3f}; "
        f"the top 10% at {pct[90]:.3f}."
    )
    print("Label a sample before trusting either — percentile is not precision.")


def sample(conn: sqlite3.Connection, n: int, seed: int = 0) -> None:
    """Emit a labelling sheet, stratified across the score range.

    Sampling only the top would measure precision and say nothing about recall,
    which is the failure mode that matters: signal quietly dying below the gate.
    """
    rows = conn.execute(
        """SELECT id, source, thesis_id, similarity, title, source_url
           FROM candidates WHERE similarity IS NOT NULL ORDER BY similarity"""
    ).fetchall()
    if not rows:
        sys.exit("nothing scored yet")

    rnd = random.Random(seed)
    buckets: dict[int, list] = {}
    for r in rows:
        buckets.setdefault(int(r["similarity"] * 20), []).append(r)

    per = max(1, n // max(1, len(buckets)))
    picked = []
    for _, items in sorted(buckets.items()):
        picked.extend(rnd.sample(items, min(per, len(items))))

    w = csv.writer(sys.stdout)
    w.writerow(["id", "source", "thesis_id", "similarity", "title", "source_url", "label"])
    for r in picked[:n]:
        w.writerow([r["id"], r["source"], r["thesis_id"], f"{r['similarity']:.4f}",
                    (r["title"] or "")[:120], r["source_url"], ""])


def evaluate(labels_path: Path) -> None:
    """Sweep thresholds over the labelled set and report the trade at each.

    Accuracy is meaningless here. Real hits are a few percent, so a model that
    rejects everything scores ~97% accurate and finds nothing. Precision and recall
    are the only numbers worth printing.
    """
    rows = [r for r in csv.DictReader(labels_path.open()) if r.get("label", "").strip()]
    if not rows:
        sys.exit(f"no labelled rows in {labels_path} — fill the label column with 1 or 0")

    data = [(float(r["similarity"]), r["label"].strip() in ("1", "y", "yes")) for r in rows]
    positives = sum(1 for _, good in data if good)
    print(f"labelled {len(data)}, of which {positives} positive "
          f"({positives / len(data):.1%})\n")

    if not positives:
        sys.exit("no positives in the labelled set — label more, or the sources are wrong")

    print(f"{'threshold':>10} {'kept':>6} {'precision':>10} {'recall':>8} {'F1':>7}")
    print("-" * 46)
    best = None
    for i in range(10, 70, 2):
        t = i / 100
        kept = [(s, good) for s, good in data if s >= t]
        if not kept:
            break
        tp = sum(1 for _, good in kept if good)
        precision = tp / len(kept)
        recall = tp / positives
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
        marker = ""
        if best is None or f1 > best[1]:
            best, marker = (t, f1), ""
        print(f"{t:>10.2f} {len(kept):>6} {precision:>10.1%} {recall:>8.1%} {f1:>7.3f}{marker}")

    print(f"\nbest F1 at threshold {best[0]:.2f} (F1 {best[1]:.3f})")
    print("F1 weights precision and recall equally. If missing a real founder costs "
          "more than\nreading a dud, pick a lower threshold than this and accept the noise.")


def main() -> None:
    env.load()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["distribution", "sample", "evaluate"])
    ap.add_argument("--db", default=None)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--labels", type=Path, default=Path("data/labels.csv"))
    args = ap.parse_args()

    if args.command == "evaluate":
        evaluate(args.labels)
        return

    conn = connect(args.db)
    if args.command == "distribution":
        distribution(conn)
    else:
        sample(conn, args.n)


if __name__ == "__main__":
    main()
