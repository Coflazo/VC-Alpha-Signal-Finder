"""Push findings into a fund's Google Sheet.

The sheet is where a partner actually works, which sets one hard rule: **the
pipeline appends and never overwrites.** Column J holds their notes, their status,
their decision. A run that rewrote existing rows would destroy the thing the sheet is
for, and it would do it silently.

So every candidate that has been written carries its row number in `sheet_row`, and
anything with a row number is never touched again. New findings go on the end.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass

from vc_alpha.app import sheets
from vc_alpha.theses import Thesis

log = logging.getLogger(__name__)


@dataclass(slots=True)
class PushResult:
    appended: int
    skipped: int
    detail: str
    configured: bool = True

    def as_dict(self) -> dict:
        return {"appended": self.appended, "skipped": self.skipped,
                "detail": self.detail, "configured": self.configured}


def headers_for(thesis: Thesis) -> list[str]:
    """Same columns as the CSV, so a fund sees one format everywhere."""
    return ["Score", "Source", "Link"] + [f.label for f in thesis.report_fields]


def row_for(candidate: sqlite3.Row, thesis: Thesis) -> list[str]:
    try:
        report = json.loads(candidate["research_md"]) if candidate["research_md"] else {}
    except (ValueError, TypeError):
        report = {}
    score = candidate["score"]
    return [
        f"{score:.3f}" if score is not None else "",
        candidate["source"] or "",
        candidate["source_url"] or "",
        *[str(report.get(f.key, "")) for f in thesis.report_fields],
    ]


def push(conn: sqlite3.Connection, thesis: Thesis, candidates: list[sqlite3.Row],
         sheet: "sheets.Sheet | None" = None) -> PushResult:
    """Append candidates that have not been written before.

    Returns rather than raises when the sheet is not set up, because that is the
    ordinary state on a fresh install and the CSV output still works.
    """
    if sheet is None:
        status = sheets.status()
        if not status.configured:
            return PushResult(0, 0, status.detail, configured=False)
        try:
            sheet = sheets.Sheet(tab=thesis.name[:40] or "Sheet1")
        except sheets.SheetsUnavailable as e:
            return PushResult(0, 0, str(e), configured=False)

    # Written before means it is already in the sheet, possibly with a partner's
    # notes beside it. Those rows are not ours to touch.
    fresh = [c for c in candidates if c["sheet_row"] is None]
    skipped = len(candidates) - len(fresh)
    if not fresh:
        return PushResult(0, skipped, "Everything here is already in the sheet.")

    try:
        sheet.ensure_headers(headers_for(thesis))
        existing = len(sheet.read())
        sheet.append([row_for(c, thesis) for c in fresh])
    except Exception as e:
        return PushResult(0, skipped, f"Could not write to the sheet: {e}", False)

    # Record where each landed, so a rerun knows to leave them alone. Headers
    # occupy row 1, so the first appended row is `existing + 1` counting from there.
    start = max(existing, 1) + 1
    for offset, candidate in enumerate(fresh):
        conn.execute("UPDATE candidates SET sheet_row = ? WHERE id = ?",
                     (start + offset, candidate["id"]))
    conn.commit()

    return PushResult(len(fresh), skipped,
                      f"Added {len(fresh)} to {thesis.name}. "
                      f"Nothing already in the sheet was changed.")
