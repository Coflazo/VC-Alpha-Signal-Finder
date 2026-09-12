"""Run stages 3 to 5 over whatever survived stage 2.

    uv run python -m vc_alpha.pipeline --limit 20
    uv run python -m vc_alpha.pipeline --thesis treeo --research

Wiring only. Every step it calls already exists and is tested on its own.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from vc_alpha import score, theses, triage
from vc_alpha.db import connect
from vc_alpha.enrich.embed import survivors_by_rank
from vc_alpha.llm import NoCapacityLeft, Router, Sending
from vc_alpha.output.report import research, write_csv
from vc_alpha.redact import extract

log = logging.getLogger(__name__)

OUT_DIR = Path("data/reports")

# Sources whose text is private. Triage sees a redacted fragment, never the message.
PRIVATE_SOURCES = {"whatsapp"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/candidates.sqlite")
    ap.add_argument("--keep-rate", type=float, default=0.10,
                    help="fraction of each source to pass to triage")
    ap.add_argument("--floor", type=float, default=0.25)
    ap.add_argument("--limit", type=int, default=25, help="max candidates to triage")
    ap.add_argument("--thesis", help="only produce this fund's report")
    ap.add_argument("--source", help="only triage candidates from this source")
    ap.add_argument("--research", action="store_true",
                    help="also run stage 4, which costs several calls per candidate")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = connect(args.db)
    active = theses.load_all()
    by_id = {t.id: t for t in active}
    router = Router(conn)

    if not router.available():
        raise SystemExit(
            "no provider available. Set GEMINI_API_KEY, GROQ_API_KEY or "
            "CEREBRAS_API_KEY (all free, no card), or run 'ollama serve'."
        )
    log.info("providers: %s", ", ".join(p.name for p in router.available()))

    # Stage 2 gate, per source so no source crowds out another.
    gated = survivors_by_rank(conn, keep_rate=args.keep_rate, floor=args.floor)
    if not gated:
        raise SystemExit("nothing passed stage 2 — run vc_alpha.score_all first")
    cutoff = min(r["similarity"] for r in gated)
    log.info("%d candidates passed stage 2 (lowest kept: %.3f)", len(gated), cutoff)

    # Stage 3.
    public = triage.run(conn, router, active, threshold=cutoff, limit=args.limit,
                        source=args.source)
    log.info("triage: %(triaged)d done, %(startups)d startups, "
             "%(invalid_json)d unparseable", public)

    # Private sources go through the same triage, but on a redacted fragment.
    for row in conn.execute(
        f"""SELECT id, raw_text, thesis_id FROM candidates
            WHERE source IN ({','.join('?' * len(PRIVATE_SOURCES))})
              AND similarity >= ? AND triage_json IS NULL LIMIT ?""",
        (*PRIVATE_SOURCES, cutoff, args.limit),
    ).fetchall():
        thesis = by_id.get(row["thesis_id"]) or active[0]
        try:
            verdict = triage.triage_one(
                router, extract(row["raw_text"]), thesis, Sending.REDACTED
            )
        except (NoCapacityLeft, ValueError) as e:
            log.warning("private triage stopped: %s", e)
            break
        conn.execute(
            """UPDATE candidates SET triage_json = ?, is_startup = ?,
               stage_guess = ?, confidence = ? WHERE id = ?""",
            (json.dumps(verdict), int(bool(verdict.get("is_startup"))),
             verdict.get("stage"), float(verdict.get("confidence") or 0), row["id"]),
        )
        conn.commit()

    log.info("scored %d candidates", score.rescore(conn))

    # Stage 4, opt-in: several calls per candidate against a finite free allowance.
    if args.research:
        for row in score.ranked(conn, args.thesis, limit=args.limit):
            if row["research_md"]:
                continue
            thesis = by_id.get(row["thesis_id"]) or active[0]
            sending = (Sending.REDACTED if row["source"] in PRIVATE_SOURCES
                       else Sending.PUBLIC)
            try:
                report = research(router, row, thesis, sending)
            except (NoCapacityLeft, ValueError) as e:
                log.warning("research stopped: %s", e)
                break
            conn.execute("UPDATE candidates SET research_md = ? WHERE id = ?",
                         (json.dumps(report), row["id"]))
            conn.commit()

    # Stage 5.
    args.out.mkdir(parents=True, exist_ok=True)
    for t in active:
        if args.thesis and t.id != args.thesis:
            continue
        rows = score.ranked(conn, t.id, limit=200)
        if not rows:
            continue
        path = write_csv(conn, t, rows, args.out / f"{t.id}.csv")
        log.info("%-12s %2d candidates -> %s", t.name, len(rows), path)

    for u in router.budget.report():
        log.info("  %s: %d requests today", u["provider"], u["requests"])


if __name__ == "__main__":
    main()
