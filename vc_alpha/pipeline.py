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

from vc_alpha import calibrate, env, paths, score, theses, triage
from vc_alpha.db import connect, purge_expired
from vc_alpha.enrich.embed import survivors_by_rank
from vc_alpha.llm import NoCapacityLeft, Router, Sending, set_a_key
from vc_alpha.output.report import research, write_csv
from vc_alpha.output.sheets_writer import push
from vc_alpha.redact import extract

log = logging.getLogger(__name__)


# Sources whose text is private. Triage sees a redacted fragment, never the message.
PRIVATE_SOURCES = {"whatsapp"}


def main() -> None:
    env.load()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None)
    ap.add_argument("--keep-rate", type=float, default=0.10,
                    help="fraction of each source to pass to triage")
    ap.add_argument("--floor", type=float, default=None,
                    help="absolute similarity floor; defaults to the fitted "
                         "value, or 0.25 before calibration")
    ap.add_argument("--limit", type=int, default=25, help="max candidates to triage")
    ap.add_argument("--thesis", help="only produce this fund's report")
    ap.add_argument("--source", help="only triage candidates from this source")
    ap.add_argument("--research", action="store_true",
                    help="also run stage 4, which costs several calls per candidate")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--to-sheet", action="store_true",
                    help="also append new rows to the fund's Google Sheet")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = connect(args.db)
    purge_expired(conn)
    active = theses.load_all()
    if not active:
        raise SystemExit(theses.NO_FUNDS)
    by_id = {t.id: t for t in active}
    router = Router(conn)

    if not router.available():
        raise SystemExit(f"no provider available. {set_a_key()}")
    log.info("providers: %s", ", ".join(p.name for p in router.available()))

    # Stage 2 gate, per source so no source crowds out another. The floor comes
    # from the fitted calibration when there is one; `active()` logs which.
    cal = calibrate.active(conn)
    gated = survivors_by_rank(conn, keep_rate=args.keep_rate,
                              floor=args.floor if args.floor is not None else cal.floor)
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
    out = args.out or paths.reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    for t in active:
        if args.thesis and t.id != args.thesis:
            continue
        rows = score.ranked(conn, t.id, limit=200)
        if not rows:
            continue
        path = write_csv(conn, t, rows, out / f"{t.id}.csv")
        log.info("%-12s %2d candidates -> %s", t.name, len(rows), path)

        if args.to_sheet:
            result = push(conn, t, rows)
            log.info("%-12s %s", t.name, result.detail)

    for u in router.budget.report():
        log.info("  %s: %d requests today", u["provider"], u["requests"])


if __name__ == "__main__":
    main()
