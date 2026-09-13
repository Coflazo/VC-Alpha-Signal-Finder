"""Measure whether the system prompts help, on the real corpus.

Prompt engineering without measurement is taste. The product already tracks the two
things that matter — whether a quote is real, and whether a factual field is
supported by the source — so the same candidates can be run with and without the
system prompt and compared.

    uv run python scripts/ab_prompts.py --n 8

Whichever way it comes out goes into docs/VALIDATION.md. A prompt that does not help
is a finding, not a failure to report.
"""

from __future__ import annotations

import argparse
import json
import time

from vc_alpha.db import connect
from vc_alpha.founders import _quote_is_real
from vc_alpha.llm import Router, Sending
from vc_alpha.output.report import FACTUAL_FIELDS, _grounded, research_prompt, research_schema
from vc_alpha.prompts import for_task
from vc_alpha.signals import SIGNALS, schema as triage_schema
from vc_alpha.triage import build_prompt
from vc_alpha import theses


def score_triage(verdict: dict, source: str) -> dict:
    quotes = fabricated = 0
    scores = []
    for s in SIGNALS:
        block = verdict.get(s.key) or {}
        scores.append(float(block.get("score") or 0))
        q = (block.get("quote") or "").strip()
        if q:
            quotes += 1
            fabricated += not _quote_is_real(q, source)
    return {"quotes": quotes, "fabricated": fabricated,
            "mean_score": sum(scores) / len(scores) if scores else 0}


def score_research(report: dict, source: str, thesis) -> dict:
    checked = ungrounded = filled = total = 0
    for f in thesis.report_fields:
        v = str(report.get(f.key, "")).strip()
        total += 1
        real = bool(v) and v.lower() not in ("unknown", "n/a", "none", "")
        filled += real
        if f.key in FACTUAL_FIELDS and real:
            checked += 1
            ungrounded += not _grounded(v, source)
    return {"filled": filled, "total": total,
            "checked": checked, "ungrounded": ungrounded}


def run(n: int, pause: float) -> dict:
    conn = connect("data/candidates.sqlite")
    router = Router(conn)
    thesis = next(t for t in theses.load_all() if t.id == "treeo")

    rows = conn.execute("""
        SELECT * FROM candidates
        WHERE title LIKE 'Show HN%' AND LENGTH(raw_text) > 150
        ORDER BY COALESCE(score, similarity) DESC NULLS LAST LIMIT ?""", (n,)).fetchall()

    results = {"with": [], "without": []}
    timings = {"with": [], "without": []}

    for row in rows:
        src = row["raw_text"] or ""
        for arm, system in (("with", for_task("research")), ("without", None)):
            start = time.time()
            try:
                out = router.complete(
                    research_prompt(src, row["source_url"], thesis),
                    schema=research_schema(thesis), sending=Sending.PUBLIC,
                    system=system)
            except Exception as e:
                print(f"  {arm}: failed ({str(e)[:60]})")
                continue
            timings[arm].append(time.time() - start)
            results[arm].append(score_research(dict(out), src, thesis))
            time.sleep(pause)

    summary = {}
    for arm, rs in results.items():
        if not rs:
            continue
        filled = sum(r["filled"] for r in rs)
        total = sum(r["total"] for r in rs)
        checked = sum(r["checked"] for r in rs)
        ungrounded = sum(r["ungrounded"] for r in rs)
        summary[arm] = {
            "candidates": len(rs),
            "filled_rate": round(filled / total, 3) if total else 0,
            "factual_checked": checked,
            "invented": ungrounded,
            "invention_rate": round(ungrounded / checked, 3) if checked else 0,
            "mean_latency_s": round(sum(timings[arm]) / len(timings[arm]), 2),
        }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--pause", type=float, default=13.0,
                    help="seconds between calls, to stay inside the token budget")
    args = ap.parse_args()

    summary = run(args.n, args.pause)
    print(json.dumps(summary, indent=2))

    if "with" in summary and "without" in summary:
        w, o = summary["with"], summary["without"]
        print(f"\n  invention rate: {o['invention_rate']:.1%} without -> "
              f"{w['invention_rate']:.1%} with")
        print(f"  filled rate   : {o['filled_rate']:.1%} without -> "
              f"{w['filled_rate']:.1%} with")


if __name__ == "__main__":
    main()
