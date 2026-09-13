"""Scoring and report assembly. A silent bug in either produces a plausible-looking
ranked list that is wrong, which is worse than a crash.
"""

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from vc_alpha import theses
from vc_alpha.db import SCHEMA
from vc_alpha.output.report import research_prompt, to_markdown, write_csv
from vc_alpha.score import HALF_LIFE_DAYS, combine, ranked, recency_decay, rescore

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


@pytest.fixture
def treeo():
    return next(t for t in theses.load_all() if t.id == "treeo")


def test_recency_halves_at_the_half_life():
    assert recency_decay(ago(0), now=NOW) == pytest.approx(1.0)
    assert recency_decay(ago(HALF_LIFE_DAYS), now=NOW) == pytest.approx(0.5, abs=1e-6)


def test_unknown_date_neither_rewards_nor_punishes():
    """Absent evidence should sit in the middle, not at either extreme."""
    assert recency_decay(None) == 0.5
    assert recency_decay("not a date") == 0.5


def test_future_dates_do_not_exceed_one():
    assert recency_decay((NOW + timedelta(days=30)).isoformat(), now=NOW) == 1.0


def test_thesis_match_outweighs_similarity():
    """Stage 3 actually read the post; stage 2 only measured proximity."""
    shallow = combine(similarity=1.0, thesis_match=0.0, posted_at=ago(0), now=NOW)
    read_it = combine(similarity=0.0, thesis_match=1.0, posted_at=ago(0), now=NOW)
    assert read_it > shallow


def test_missing_components_do_not_crash():
    assert 0.0 <= combine(None, None, None) <= 1.0


def _insert(conn, cid, sim, match, posted, is_startup=1):
    conn.execute(
        """INSERT INTO candidates
           (id, source, source_url, raw_text, discovered_at, retention_until,
            similarity, thesis_id, triage_json, is_startup, posted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (cid, "hackernews", f"https://x/{cid}", "text", NOW.isoformat(),
         NOW.isoformat(), sim, "treeo", json.dumps({"thesis_match": match}),
         is_startup, posted),
    )
    conn.commit()


def test_rescore_then_rank(conn):
    _insert(conn, "old", 0.9, 0.9, ago(400))
    _insert(conn, "fresh", 0.6, 0.9, ago(1))
    assert rescore(conn) == 2
    assert [r["id"] for r in ranked(conn)] == ["fresh", "old"], "recency ignored"


def test_non_startups_are_excluded_from_the_ranking(conn):
    _insert(conn, "company", 0.8, 0.8, ago(1), is_startup=1)
    _insert(conn, "article", 0.9, 0.9, ago(1), is_startup=0)
    rescore(conn)
    assert [r["id"] for r in ranked(conn)] == ["company"]


def test_unparseable_triage_json_does_not_break_rescoring(conn):
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until, similarity, triage_json, is_startup)
           VALUES ('bad','hn','https://x/bad','t',?,?,0.5,'not json',1)""",
        (NOW.isoformat(), NOW.isoformat()),
    )
    conn.commit()
    assert rescore(conn) == 1
    assert conn.execute("SELECT score FROM candidates WHERE id='bad'").fetchone()[0] is not None


def test_research_prompt_carries_every_field(treeo):
    p = research_prompt("a post", "https://x/1", treeo)
    for f in treeo.report_fields:
        assert f.key in p, f"{f.key} missing from research prompt"


def test_conditions_live_in_the_schema_not_the_prompt(treeo):
    """Hints and conditions used to appear in both, paying for the same instruction
    twice. At 8,000 tokens a minute that was three research calls a minute instead
    of six, so the prompt now carries field names and the schema carries meaning."""
    from vc_alpha.output.report import research_schema

    schema = research_schema(treeo)
    assert "n/a" in schema["properties"]["raising_when"]["description"]
    assert "only when" not in research_prompt("a post", "https://x/1", treeo)


def test_markdown_hides_conditional_fields_that_do_not_apply(treeo):
    md = to_markdown(
        {"startup_name": "Acme", "raising_now": "Y", "raising_when": "n/a"}, treeo
    )
    assert "Acme" in md
    assert "when are they going to start raising" not in md.lower()


def test_csv_uses_the_funds_own_columns_and_appends(conn, treeo, tmp_path: Path):
    _insert(conn, "a", 0.8, 0.8, ago(1))
    conn.execute(
        "UPDATE candidates SET research_md = ? WHERE id = 'a'",
        (json.dumps({"startup_name": "Acme", "based_in": "Berlin, Germany"}),),
    )
    rescore(conn)
    out = tmp_path / "treeo.csv"

    write_csv(conn, treeo, ranked(conn), out)
    write_csv(conn, treeo, ranked(conn), out)  # a second run must not clobber

    rows = list(csv.reader(out.open()))
    assert rows[0][3] == "Startup name"
    assert "Geographic focus" in rows[0]
    assert len(rows) == 3, "append-only broken: a partner's edits would be lost"
    assert rows[1][3] == "Acme"
