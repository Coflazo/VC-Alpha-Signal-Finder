"""Turn the review clicks into the numbers the pipeline actually runs on.

Stage 2's threshold is the most consequential number in the system: everything
after it only ever sees what survived, so a candidate dropped here is invisible to
triage, research and the report. It shipped as 0.35, a guess, and the README has
always said so.

The labels to fix that were already being collected. The Review screen writes
`was_good` on every judgement, and `was_good` was read by nothing — the loop ran
from the model to the partner and stopped. Meanwhile this file asked the user to
export a CSV, label it by hand and feed it back, which is the same work done twice.
So the labels now come from the database, and what gets fitted is written to a
config the pipeline reads.

    vc-alpha calibrate distribution     where the scores actually sit
    vc-alpha calibrate fit              fit the threshold and weights
    vc-alpha calibrate sample --n 100   export a labelling sheet, if you prefer CSV
    vc-alpha calibrate evaluate         sweep thresholds over the labels

**A threshold belongs to an embedding model.** Different providers put their
cosines on completely different scales — measured, an unrelated sentence scores
0.567 against a thesis under mistral-embed and would have scored far lower under
Gemini. A number fitted on one model is meaningless under another, so the model is
stored with it and a mismatch falls back to the default rather than silently
applying the wrong bar.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from vc_alpha import env, paths
from vc_alpha.db import connect

log = logging.getLogger(__name__)

# Below this, a fitted number is worse than an honest guess: it would carry the
# authority of "measured" with the variance of a handful of clicks. Chosen so that
# a single unlucky label moves the threshold by less than a percentage point.
MIN_LABELS = 40

# What the Review screen counts toward. Not a hard requirement, a target: at 100
# labels the precision and recall either side of the threshold are worth reading.
TARGET_LABELS = 100

DEFAULT_THRESHOLD = 0.35
DEFAULT_FLOOR = 0.25
DEFAULT_WEIGHTS = {"similarity": 0.3, "thesis_match": 0.5, "recency": 0.2}


@dataclass(slots=True)
class Calibration:
    """What was fitted, from how much, and against which embedding model."""

    threshold: float = DEFAULT_THRESHOLD
    floor: float = DEFAULT_FLOOR
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    embedding_model: str | None = None
    n_labels: int = 0
    positives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    fitted_at: str | None = None
    # Reasons to distrust the numbers above, in plain English. A fitted threshold
    # that cannot say when its own evidence is thin is just a guess wearing a
    # measurement's clothes.
    caveats: list[str] = field(default_factory=list)

    @property
    def fitted(self) -> bool:
        return self.n_labels >= MIN_LABELS


def load(path: Path | None = None) -> Calibration:
    """The fitted values, or the defaults when nothing has been fitted yet."""
    path = path or paths.calibration_file()
    if not path.is_file():
        return Calibration()
    try:
        raw = yaml.safe_load(path.read_text()) or {}
        known = {f for f in Calibration.__slots__}
        return Calibration(**{k: v for k, v in raw.items() if k in known})
    except (ValueError, TypeError, yaml.YAMLError) as e:
        log.warning("could not read %s (%s); using defaults", path, e)
        return Calibration()


def save(cal: Calibration, path: Path | None = None) -> Path:
    path = path or paths.calibration_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Fitted from your own review decisions by `vc-alpha calibrate fit`.\n"
        "# Delete this file to go back to the defaults.\n"
        "#\n"
        "# The threshold only means anything for the embedding model named here.\n"
        "# Different providers score on different scales, so it is ignored if you\n"
        "# switch provider, and you should re-fit after re-embedding.\n"
        + yaml.safe_dump(asdict(cal), sort_keys=False)
    )
    return path


def active(conn: sqlite3.Connection | None = None,
           embedding_model: str | None = None) -> Calibration:
    """The calibration in force, having checked it applies to the current vectors.

    Logs which it chose. "The threshold is a guess" should be visible in a run's
    output rather than something you have to remember.
    """
    cal = load()
    if not cal.fitted:
        log.info("stage 2 threshold %.3f (default — label %d candidates in the "
                 "Review tab to fit it)", cal.threshold, MIN_LABELS)
        return Calibration()

    if embedding_model is None and conn is not None:
        row = conn.execute(
            "SELECT embedding_model FROM candidates WHERE embedding_model IS NOT NULL "
            "LIMIT 1").fetchone()
        embedding_model = row[0] if row else None

    if cal.embedding_model and embedding_model and cal.embedding_model != embedding_model:
        log.warning(
            "calibration was fitted against %s but the corpus is embedded with %s; "
            "falling back to the default threshold. Re-fit after re-embedding.",
            cal.embedding_model, embedding_model)
        return Calibration()

    log.info("stage 2 threshold %.3f (fitted from %d labels, precision %.0f%%, "
             "recall %.0f%%)", cal.threshold, cal.n_labels,
             cal.precision * 100, cal.recall * 100)
    return cal


# --- labels ------------------------------------------------------------------


def labels_from_db(conn: sqlite3.Connection) -> list[dict]:
    """Every judgement the Review screen has recorded.

    This is the whole point. The clicks were already happening; nothing read them.
    """
    return [dict(r) for r in conn.execute(
        """SELECT id, similarity, triage_json, posted_at, was_good, embedding_model
           FROM candidates
           WHERE reviewed = 1 AND was_good IS NOT NULL AND similarity IS NOT NULL"""
    )]


def labels_from_csv(path: Path) -> list[dict]:
    """The older route, kept: some people would rather label in a spreadsheet."""
    rows = [r for r in csv.DictReader(path.open()) if r.get("label", "").strip()]
    return [{"similarity": float(r["similarity"]),
             "was_good": int(r["label"].strip() in ("1", "y", "yes")),
             "triage_json": None, "posted_at": None, "embedding_model": None}
            for r in rows]


def _thesis_match(row: dict) -> float | None:
    if not row.get("triage_json"):
        return None
    try:
        return json.loads(row["triage_json"]).get("thesis_match")
    except (ValueError, TypeError):
        return None


# --- fitting -----------------------------------------------------------------


def f_beta(precision: float, recall: float, beta: float) -> float:
    """Precision and recall combined, with recall weighted beta times as heavily.

    beta=1 is the familiar F1, which treats the two errors as equally costly. They
    are not equally costly here: reading a dud wastes a minute, and missing a
    founder means the round closes without you. beta=2 says recall is worth twice
    precision, which is the asymmetry a fund actually faces.
    """
    b2 = beta * beta
    denominator = b2 * precision + recall
    return (1 + b2) * precision * recall / denominator if denominator else 0.0


def sweep(labels: list[dict], beta: float = 2.0) -> list[dict]:
    """Precision and recall at every candidate threshold.

    Accuracy is meaningless here. Real hits are a few percent of a corpus, so a
    rule that rejects everything scores about 97% accurate and finds nothing.
    """
    positives = sum(1 for r in labels if r["was_good"])
    out = []
    for i in range(5, 96, 1):
        t = i / 100
        kept = [r for r in labels if r["similarity"] >= t]
        if not kept:
            break
        tp = sum(1 for r in kept if r["was_good"])
        precision = tp / len(kept)
        recall = tp / positives if positives else 0.0
        out.append({"threshold": t, "kept": len(kept), "precision": precision,
                    "recall": recall,
                    "f1": f_beta(precision, recall, 1.0),
                    "score": f_beta(precision, recall, beta)})
    return out


def average_precision(scored: list[tuple[float, int]]) -> float:
    """Area under the precision-recall curve, for ranking quality.

    The right objective for fitting the score weights: what matters is that good
    candidates sort above bad ones, not that any particular cutoff is met.
    """
    positives = sum(good for _, good in scored)
    if not positives:
        return 0.0
    total = hits = 0.0
    for rank, (_, good) in enumerate(sorted(scored, key=lambda s: -s[0]), start=1):
        if good:
            hits += 1
            total += hits / rank
    return total / positives


def fit_weights(labels: list[dict], *, step: float = 0.05) -> dict[str, float]:
    """Grid search the three score weights over the simplex.

    Three weights and a few hundred rows. A coarse grid is the honest tool: it is
    fifteen lines, it cannot overfit in a way a finer grid would not, and adding
    scikit-learn to the dependency list for it would be a poor trade.

    Candidates with no triage verdict are excluded — they have no thesis_match to
    weight, and treating a missing judgement as zero would push the weight off it
    for the wrong reason.
    """
    from vc_alpha.score import recency_decay

    usable = [(r["similarity"], _thesis_match(r), r["posted_at"], r["was_good"])
              for r in labels]
    usable = [u for u in usable if u[1] is not None]
    if len(usable) < MIN_LABELS:
        return dict(DEFAULT_WEIGHTS)

    steps = [round(i * step, 2) for i in range(int(1 / step) + 1)]
    best, best_ap = dict(DEFAULT_WEIGHTS), -1.0
    for ws in steps:
        for wt in steps:
            wr = round(1.0 - ws - wt, 2)
            if wr < 0:
                continue
            scored = [
                (ws * sim + wt * match + wr * recency_decay(posted), good)
                for sim, match, posted, good in usable
            ]
            ap = average_precision(scored)
            if ap > best_ap:
                best_ap, best = ap, {"similarity": ws, "thesis_match": wt,
                                     "recency": wr}
    return best


def fit(conn: sqlite3.Connection, *, labels: list[dict] | None = None,
        prefer: str = "f1") -> Calibration:
    """Fit the threshold and the weights from recorded judgements.

    `prefer` chooses how the two errors are weighted. "f1" treats them as equally
    costly. "recall" — the default — uses F2, which weights recall twice as heavily,
    because reading a dud wastes a minute and missing a founder means the round
    closes without you. F2 is never a higher bar than F1, which is the direction
    that asymmetry should move it.
    """
    labels = labels_from_db(conn) if labels is None else labels
    positives = sum(1 for r in labels if r["was_good"])

    if len(labels) < MIN_LABELS:
        raise NotEnoughLabels(
            f"{len(labels)} labelled, need {MIN_LABELS}. Open the Review tab and "
            f"mark {MIN_LABELS - len(labels)} more — good or not for us, either "
            "way, since both teach the threshold where your bar is.")
    if not positives:
        raise NotEnoughLabels(
            "nothing was marked good yet, so there is no signal to separate. "
            "Mark at least a few promising ones.")

    table = sweep(labels, beta=2.0 if prefer == "recall" else 1.0)
    # Ties go to the lower threshold: where two bars perform identically on the
    # labelled set, the one that keeps more candidates is the safer bet on the
    # unlabelled rest.
    row = min(
        (r for r in table if r["score"] == max(x["score"] for x in table)),
        key=lambda r: r["threshold"],
    )

    models = {r["embedding_model"] for r in labels if r.get("embedding_model")}
    cal = Calibration(
        threshold=row["threshold"],
        # The per-source floor sits below the threshold: it is the safety net for a
        # run where a whole source is junk, not a second bar.
        floor=round(max(0.05, row["threshold"] * 0.7), 2),
        weights=fit_weights(labels),
        embedding_model=next(iter(models)) if len(models) == 1 else None,
        n_labels=len(labels),
        positives=positives,
        precision=round(row["precision"], 4),
        recall=round(row["recall"], 4),
        f1=round(row["f1"], 4),
        fitted_at=datetime.now(timezone.utc).isoformat(),
        caveats=caveats_for(conn, labels, row["threshold"]),
    )
    save(cal)
    return cal


def caveats_for(conn: sqlite3.Connection, labels: list[dict],
                threshold: float) -> list[str]:
    """Why this fit might not deserve the confidence its numbers imply.

    Written after a real fit returned "threshold 0.05, precision 92%" and said it
    with a straight face. It was right about its labels and wrong about the world:
    the labels had all come from the top of the ranking, where almost everything is
    good, so the honest conclusion was "keep everything" and the actual conclusion
    should have been "these labels cannot tell you where the bar goes".

    A threshold nothing can talk you out of is worse than a documented guess.
    """
    out = []
    positive_rate = sum(1 for r in labels if r["was_good"]) / len(labels)

    if positive_rate > 0.80:
        out.append(
            f"{positive_rate:.0%} of what you labelled was good. A real corpus is a "
            "few percent, so this looks like a sample taken from the top of the "
            "ranking rather than across it. Review some low-scoring candidates too, "
            "or the threshold has nothing to separate.")
    elif positive_rate < 0.05:
        out.append(
            f"only {positive_rate:.0%} was marked good, so the fit rests on very few "
            "positives and will move a lot with the next few labels.")

    # Recall below the lowest thing you looked at is unmeasured, not high.
    row = conn.execute(
        "SELECT MIN(similarity) lo, MAX(similarity) hi FROM candidates "
        "WHERE similarity IS NOT NULL").fetchone()
    if row and row["lo"] is not None:
        labelled_lo = min(r["similarity"] for r in labels)
        corpus_span = row["hi"] - row["lo"]
        if corpus_span > 0 and (labelled_lo - row["lo"]) / corpus_span > 0.25:
            out.append(
                f"nothing below {labelled_lo:.2f} was ever labelled, but the corpus "
                f"goes down to {row['lo']:.2f}. Whatever is down there is invisible "
                "to this fit, so the recall figure is optimistic by an unknown "
                "amount. `vc-alpha calibrate sample` draws across the whole range.")

    if threshold <= 0.10:
        out.append(
            "the fitted threshold is low enough to keep almost everything, which "
            "usually means the labels did not contain a clear boundary rather than "
            "that your bar is genuinely that wide.")

    return out


class NotEnoughLabels(RuntimeError):
    """Fewer judgements than it takes for a fitted number to beat a guess."""


def progress(conn: sqlite3.Connection) -> dict:
    """How far along the labelling is. Drives the Review screen's counter."""
    labels = labels_from_db(conn)
    return {
        "labelled": len(labels),
        "positives": sum(1 for r in labels if r["was_good"]),
        "minimum": MIN_LABELS,
        "target": TARGET_LABELS,
        "can_fit": len(labels) >= MIN_LABELS
                   and any(r["was_good"] for r in labels),
        "current": asdict(load()),
    }


# --- reporting ---------------------------------------------------------------


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
        "SELECT source, thesis_id, similarity, embedding_model FROM candidates "
        "WHERE similarity IS NOT NULL"
    ).fetchall()
    if not rows:
        sys.exit("nothing scored yet — run `vc-alpha score` first")

    def show(label: str, vals: list[float]) -> None:
        pct = percentiles(vals)
        line = "  ".join(f"p{p}={v:.3f}" for p, v in pct.items())
        print(f"{label:<22} n={len(vals):<5} {line}")

    models = {r["embedding_model"] for r in rows}
    print(f"\nembedded with: {', '.join(str(m) for m in models)}")
    print("A threshold only means anything for the model that produced the vectors.")

    print(f"\n{'scope':<22} {'count':<7} percentiles")
    print("-" * 92)
    show("ALL", [r["similarity"] for r in rows])

    print()
    for source in sorted({r["source"] for r in rows}):
        show(f"source: {source}", [r["similarity"] for r in rows if r["source"] == source])

    print()
    for tid in sorted({r["thesis_id"] for r in rows if r["thesis_id"]}):
        show(f"thesis: {tid}", [r["similarity"] for r in rows if r["thesis_id"] == tid])

    pct = percentiles([r["similarity"] for r in rows])
    print(
        f"\nA threshold keeping the top 5% sits at {pct[95]:.3f}; "
        f"the top 10% at {pct[90]:.3f}."
    )
    print("Percentile is not precision. Label a sample before trusting either.")


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


def evaluate(labels: list[dict]) -> None:
    """Print the trade at every threshold, and where the best sits."""
    positives = sum(1 for r in labels if r["was_good"])
    print(f"labelled {len(labels)}, of which {positives} positive "
          f"({positives / len(labels):.1%})\n")
    if not positives:
        sys.exit("no positives in the labelled set — label more, or the sources "
                 "are wrong")

    table = sweep(labels)
    best = max(table, key=lambda r: r["f1"])
    best_f2 = max(table, key=lambda r: r["score"])
    print(f"{'threshold':>10} {'kept':>6} {'precision':>10} {'recall':>8} {'F1':>7}")
    print("-" * 48)
    for row in table[::2]:
        mark = "  <- best F1" if row["threshold"] == best["threshold"] else ""
        print(f"{row['threshold']:>10.2f} {row['kept']:>6} {row['precision']:>10.1%} "
              f"{row['recall']:>8.1%} {row['f1']:>7.3f}{mark}")

    print(f"\nbest F1 at threshold {best['threshold']:.2f} (F1 {best['f1']:.3f})")
    print(f"best F2 at threshold {best_f2['threshold']:.2f} "
          f"(recall {best_f2['recall']:.0%})")
    print("F1 treats the two errors as equally costly. They are not: reading a dud "
          "wastes\na minute, missing a founder means the round closes without you. "
          "`fit` uses F2\nby default, which weights recall twice as heavily.")


def main() -> None:
    env.load()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command",
                    choices=["distribution", "sample", "evaluate", "fit", "show"])
    ap.add_argument("--db", default=None)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--labels", type=Path,
                    help="read labels from this CSV instead of your reviews")
    ap.add_argument("--prefer", choices=["f1", "recall"], default="recall",
                    help="what the threshold optimises (default: recall)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = connect(args.db)

    if args.command == "show":
        cal = load()
        print(yaml.safe_dump(asdict(cal), sort_keys=False))
        if not cal.fitted:
            print(f"Not fitted yet. Label {MIN_LABELS} candidates in the Review tab.")
        return

    if args.command == "distribution":
        distribution(conn)
        return
    if args.command == "sample":
        sample(conn, args.n)
        return

    labels = labels_from_csv(args.labels) if args.labels else labels_from_db(conn)

    if args.command == "evaluate":
        if not labels:
            sys.exit("no labels yet — review some candidates in the app first")
        evaluate(labels)
        return

    try:
        cal = fit(conn, labels=labels, prefer=args.prefer)
    except NotEnoughLabels as e:
        sys.exit(str(e))

    print(f"\nFitted from {cal.n_labels} labels ({cal.positives} positive).\n")
    print(f"  threshold  {cal.threshold:.2f}   "
          f"precision {cal.precision:.0%}, recall {cal.recall:.0%}")
    print(f"  floor      {cal.floor:.2f}")
    print(f"  weights    similarity {cal.weights['similarity']}, "
          f"thesis_match {cal.weights['thesis_match']}, "
          f"recency {cal.weights['recency']}")
    for caveat in cal.caveats:
        print(f"\n  ! {caveat}")
    print(f"\nWritten to {paths.calibration_file()}. The next run uses it.\n")


if __name__ == "__main__":
    main()
