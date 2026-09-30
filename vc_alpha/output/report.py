"""Turn a candidate into the report its fund actually asked for.

Each thesis declares `report_fields`. Treeo wants immigrant status and whether the
US is on the horizon; 212 wants traction and PMF evidence or the thesis fails.
Those are not presentation differences, they are different questions, so the
research prompt is generated per fund rather than filled from one template.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
from pathlib import Path

from vc_alpha.llm import Router, Sending
from vc_alpha.prompts import for_task
from vc_alpha.redact import PRIVATE_SOURCES, extract
from vc_alpha.schema import strict_object
from vc_alpha.theses import Thesis

log = logging.getLogger(__name__)

RESEARCH_PROMPT = """Fill in the report from this post.

---
{text}
---
Source: {url}

Answer as JSON with exactly these keys: {keys}"""


# The pitch is at the top of a post; the tail is comments and boilerplate. Passing
# 8,000 characters cost tokens without adding information, and at 8,000 tokens per
# minute on the free tier that was the difference between three research calls a
# minute and six.
RESEARCH_SOURCE_CHARS = 3000


def research_prompt(text: str, url: str, thesis: Thesis) -> str:
    # Field names only. The schema already carries every hint and condition, so
    # repeating them here paid for the same instruction twice.
    keys = ", ".join(f.key for f in thesis.report_fields)
    return RESEARCH_PROMPT.format(
        text=text[:RESEARCH_SOURCE_CHARS], url=url, fields=keys, keys=keys
    )


def research_schema(thesis: Thesis) -> dict:
    """The report this fund asked for, as a strict-mode schema.

    Every field is required. Strict mode has no optional properties, and omitting
    the conditional ones got every request rejected. A field that does not apply
    comes back as "n/a", which to_markdown already hides.
    """
    return strict_object(
        {f.key: {"type": "string",
                 "description": (f.hint or f.label)
                 + (f' (write "n/a" unless {f.only_if})' if f.only_if else "")}
         for f in thesis.report_fields})


# Fields whose answer can only come from the post. A model that produces one of
# these without support in the text has invented it.
#
# Description, "your input" and similar are synthesis — the model is *supposed* to
# generate those — so checking them would be a category error.
FACTUAL_FIELDS = {"startup_name", "website", "based_in", "founded_in", "founders",
                  "turkish_link", "traction", "raising_now"}

# Reads in a fund's spreadsheet next to the model's own "unknown", which is what a
# partner wants: both mean nobody knows. Which fields were blanked for being
# ungrounded is still returned by ground_report, so the distinction survives where
# it is useful without filling a column with an explanation of itself.
NOT_STATED = "unknown"


def _grounded(value: str, source: str) -> bool:
    """Does the post actually support this value?

    Compared loosely: lowercased, with URL scheme and trailing slash removed, on a
    prefix, because a model reformats what it copies. The aim is to catch invention,
    not to demand a byte-for-byte match.
    """
    v = re.sub(r"^https?://|/$", "", (value or "").lower().strip())
    if not v or v in ("unknown", "n/a", "none", "yes", "no", "y", "n"):
        return True                     # nothing asserted, nothing to check
    haystack = re.sub(r"^https?://", "", (source or "").lower())
    return v[:40] in haystack


def ground_report(report: dict, source_text: str, thesis: Thesis) -> tuple[dict, list[str]]:
    """Blank out factual claims the source does not support.

    Measured on real output: a model reported "Based in: San Francisco, USA" for a
    post that never mentions a location. A partner reads that and acts on it, which
    makes an invented fact worse than an admitted gap — it looks like information.

    Same rule already applied to quotes, extended to the report. Returns the cleaned
    report and the list of fields that were removed, so the removal is visible
    rather than silent.
    """
    removed = []
    for f in thesis.report_fields:
        if f.key not in FACTUAL_FIELDS:
            continue
        value = str(report.get(f.key, "")).strip()
        if value and not _grounded(value, source_text):
            report[f.key] = NOT_STATED
            removed.append(f.key)
    return report, removed


def research(
    router: Router, row: sqlite3.Row, thesis: Thesis,
    sending: Sending = Sending.PUBLIC,
) -> dict:
    """Research one shortlisted candidate.

    A private row is researched on a redacted fragment, whatever `sending` the
    caller passed. scripts/run_stage4.py passed PUBLIC for every row, and the
    pipeline passed REDACTED with the raw text still in the prompt, so either way
    a private message reached a cloud model whole. The row knows its own source,
    so the decision is made here, where no caller can get it wrong.
    """
    text = row["raw_text"] or ""
    if row["source"] in PRIVATE_SOURCES:
        text, sending = extract(text), Sending.REDACTED
    schema = research_schema(thesis)
    report = router.complete(
        research_prompt(text, row["source_url"], thesis),
        schema=schema, sending=sending, system=for_task("research"),
    )
    # Grounded against what the model was shown, so a claim cannot be "supported"
    # by text it never saw.
    report, removed = ground_report(dict(report), text, thesis)
    if removed:
        log.info("dropped unsupported fields for %s: %s",
                 row["source_url"], ", ".join(removed))
    return report


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
