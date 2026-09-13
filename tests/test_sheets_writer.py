"""Pushing findings to a Google Sheet.

The property that matters more than any other: **a partner's notes survive.** The
sheet is where they actually work, and a run that overwrote their column would
destroy the thing the sheet is for, silently. Everything here tests that from a
different angle.

A fake stands in for the API so these run with no credentials. That makes stage 5
complete and tested; live verification against a real Google account is a separate
claim and is not made here.
"""

import json
import sqlite3

import pytest

from vc_alpha.db import SCHEMA
from vc_alpha.output.sheets_writer import headers_for, push, row_for
from vc_alpha import theses


class FakeSheet:
    """An in-memory stand-in that records exactly what was asked of it."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.header_calls = 0
        self.updates = []          # any call here would mean overwriting

    def read(self, cell_range=None):
        return self.rows

    def ensure_headers(self, headers):
        self.header_calls += 1
        if not self.rows:
            self.rows.append(list(headers))

    def append(self, rows):
        self.rows.extend(rows)
        return len(rows)

    def update_cell(self, row, column, value):
        self.updates.append((row, column, value))


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


@pytest.fixture
def treeo():
    return next(t for t in theses.load_all() if t.id == "treeo")


def add(conn, cid, *, score=0.8, research=None, sheet_row=None):
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until, score, research_md, sheet_row, is_startup)
           VALUES (?,?,?,?,?,?,?,?,?,1)""",
        (cid, "hackernews", f"https://x/{cid}", "text", "2026-01-01", "2027-01-01",
         score, json.dumps(research) if research else None, sheet_row))
    conn.commit()
    return conn.execute("SELECT * FROM candidates WHERE id = ?", (cid,)).fetchone()


# --- the rule that matters ---------------------------------------------------


def test_a_partners_notes_are_never_overwritten(conn, treeo):
    """The whole reason this appends. update_cell is never called by a push."""
    sheet = FakeSheet([["Score", "Link", "Status"],
                       ["0.9", "https://x/a", "Met them, following up"]])
    push(conn, treeo, [add(conn, "b")], sheet=sheet)
    assert sheet.updates == [], "a push wrote over an existing row"
    assert sheet.rows[1][2] == "Met them, following up"


def test_only_unwritten_candidates_are_appended(conn, treeo):
    already = add(conn, "old", sheet_row=5)
    fresh = add(conn, "new")
    sheet = FakeSheet()
    result = push(conn, treeo, [already, fresh], sheet=sheet)
    assert result.appended == 1 and result.skipped == 1


def test_a_second_run_appends_nothing(conn, treeo):
    """The behaviour that makes the pipeline safe to run on a schedule."""
    sheet = FakeSheet()
    rows = [add(conn, "a"), add(conn, "b")]
    assert push(conn, treeo, rows, sheet=sheet).appended == 2

    rows = conn.execute("SELECT * FROM candidates").fetchall()
    assert push(conn, treeo, rows, sheet=sheet).appended == 0
    assert len(sheet.rows) == 3          # header plus the original two


def test_the_row_number_is_recorded(conn, treeo):
    """Without this, a rerun cannot tell what it already wrote."""
    sheet = FakeSheet()
    push(conn, treeo, [add(conn, "a")], sheet=sheet)
    assert conn.execute("SELECT sheet_row FROM candidates WHERE id='a'").fetchone()[0] == 2


def test_row_numbers_are_sequential(conn, treeo):
    sheet = FakeSheet()
    push(conn, treeo, [add(conn, "a"), add(conn, "b"), add(conn, "c")], sheet=sheet)
    rows = [r[0] for r in conn.execute(
        "SELECT sheet_row FROM candidates ORDER BY sheet_row")]
    assert rows == [2, 3, 4]


# --- headers -----------------------------------------------------------------


def test_headers_match_the_funds_own_report(conn, treeo):
    h = headers_for(treeo)
    assert h[:3] == ["Score", "Source", "Link"]
    assert "Startup name" in h and "Geographic focus" in h


def test_an_existing_header_row_is_left_alone(conn, treeo):
    """A fund may have renamed columns to suit itself."""
    sheet = FakeSheet([["Their", "Own", "Headers"]])
    push(conn, treeo, [add(conn, "a")], sheet=sheet)
    assert sheet.rows[0] == ["Their", "Own", "Headers"]


# --- the row itself ----------------------------------------------------------


def test_report_fields_land_in_their_columns(conn, treeo):
    row = add(conn, "a", research={"startup_name": "Acme", "website": "https://acme.io"})
    values = row_for(row, treeo)
    assert "Acme" in values and "https://acme.io" in values


def test_a_candidate_without_research_still_writes_a_row(conn, treeo):
    """Score and link are useful even before the research stage has run."""
    values = row_for(add(conn, "a"), treeo)
    assert values[0] == "0.800" and values[2] == "https://x/a"


def test_broken_research_json_does_not_break_the_push(conn, treeo):
    conn.execute("""INSERT INTO candidates (id, source, source_url, raw_text,
        discovered_at, retention_until, score, research_md)
        VALUES ('bad','hn','https://x/bad','t','2026','2027',0.5,'not json')""")
    conn.commit()
    row = conn.execute("SELECT * FROM candidates WHERE id='bad'").fetchone()
    assert row_for(row, treeo)[2] == "https://x/bad"


# --- no credentials ----------------------------------------------------------


def test_an_unconfigured_sheet_says_so_instead_of_failing(conn, treeo, monkeypatch):
    """The ordinary state on a fresh install. CSV output still works."""
    from vc_alpha.app import sheets as sheets_mod
    monkeypatch.setattr(sheets_mod, "status",
                        lambda: sheets_mod.SheetStatus(False, "No service account.", None))
    result = push(conn, treeo, [add(conn, "a")])
    assert not result.configured and result.appended == 0
    assert "service account" in result.detail
