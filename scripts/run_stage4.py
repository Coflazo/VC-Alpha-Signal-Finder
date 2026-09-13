"""Research every ranked candidate that has not been researched yet.

Separate from the pipeline so it can run unattended: research is the slowest stage
and the free-tier token budget paces it to a handful of calls a minute.
"""

from __future__ import annotations

import json
import sys
import time

from vc_alpha.db import connect
from vc_alpha.llm import NoCapacityLeft, Router, Sending
from vc_alpha.output.report import research
from vc_alpha import score, theses

PAUSE = 9.0   # keeps us inside 8,000 tokens/minute at ~1,175 tokens a call


def main() -> None:
    conn = connect("data/candidates.sqlite")
    router = Router(conn)
    done = failed = 0

    for thesis in theses.load_all():
        pending = [r for r in score.ranked(conn, thesis.id, limit=200)
                   if not r["research_md"]]
        if not pending:
            continue
        print(f"{thesis.name}: {len(pending)} to research", flush=True)

        for row in pending:
            try:
                report = research(router, row, thesis, Sending.PUBLIC)
            except NoCapacityLeft:
                print("out of free capacity; stopping", flush=True)
                sys.exit(0)
            except Exception as e:
                failed += 1
                print(f"  failed {row['id'][:8]}: {str(e)[:80]}", flush=True)
                continue
            conn.execute("UPDATE candidates SET research_md = ? WHERE id = ?",
                         (json.dumps(report), row["id"]))
            conn.commit()
            done += 1
            name = report.get("startup_name", "?")
            print(f"  {done:>2}. {str(name)[:40]}", flush=True)
            time.sleep(PAUSE)

    print(f"\nresearched {done}, failed {failed}", flush=True)


if __name__ == "__main__":
    main()
