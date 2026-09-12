"""Turn a candidate into the report its fund actually asked for.

Each thesis declares `report_fields`. Treeo wants immigrant status and whether the
US is on the horizon; 212 wants traction and PMF evidence or the thesis fails.
Those are not presentation differences, they are different questions, so the
research prompt is generated per fund rather than filled from one template.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from vc_alpha.llm import Router
from vc_alpha.theses import Thesis

RESEARCH_PROMPT = """Research this company from the post below and fill in the report.

Post:
---
{text}
---
Source: {url}

Fill in every field. Where the post does not say and you cannot reasonably infer,
write "unknown" rather than guessing. Guessing here is worse than a gap, because a
partner will act on this.

Fields:
{fields}

Answer as JSON with exactly these keys: {keys}"""


def research_prompt(text: str, url: str, thesis: Thesis) -> str:
    lines = []
    for f in thesis.report_fields:
        bit = f"- {f.key} ({f.label})"
        if f.hint:
            bit += f": {f.hint}"
        if f.only_if:
            bit += f" [only when {f.only_if}, otherwise \"n/a\"]"
        lines.append(bit)
    keys = ", ".join(f.key for f in thesis.report_fields)
    return RESEARCH_PROMPT.format(
        text=text[:8000], url=url, fields="\n".join(lines), keys=keys
    )


def research(router: Router, row: sqlite3.Row, thesis: Thesis) -> dict:
    schema = {
        "type": "object",
        "properties": {f.key: {"type": "string"} for f in thesis.report_fields},
        "required": [f.key for f in thesis.report_fields if f.required],
    }
    return router.complete(
        research_prompt(row["raw_text"], row["source_url"], thesis),
        schema=schema, public_text=True,
    )


def to_markdown(report: dict, thesis: Thesis) -> str:
    out = [f"# {report.get('startup_name') or 'Unnamed'} — {thesis.name}", ""]
    for f in thesis.report_fields:
        value = report.get(f.key) or "unknown"
        if f.only_if and value in ("n/a", "unknown"):
            continue
        out.append(f"**{f.label}:** {value}")
    return "\n".join(out)


def write_csv(conn: sqlite3.Connection, thesis: Thesis, rows: list[sqlite3.Row],
              path: Path) -> Path:
    """One CSV per fund, in that fund's column order.

    Append-only by design: a partner editing a status column must never have their
    work overwritten by the next run.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = ["score", "source", "source_url"] + [f.label for f in thesis.report_fields]
    existing = path.exists()

    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if not existing:
            w.writerow(headers)
        for r in rows:
            try:
                report = json.loads(r["research_md"]) if r["research_md"] else {}
            except (ValueError, TypeError):
                report = {}
            w.writerow(
                [f"{r['score']:.3f}", r["source"], r["source_url"]]
                + [report.get(f.key, "") for f in thesis.report_fields]
            )
    return path
