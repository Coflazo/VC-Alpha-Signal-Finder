"""Migrations, run against databases that predate them.

This file exists because of a bug that reached a user. Every other test builds a
fresh schema, so the migration path was never exercised against an old database —
the only situation in which a migration can fail. The tests had new data; the bug
needed old data.

So each test here stands up a *previous* schema, runs the current code against it,
and checks the result.
"""

import sqlite3

import pytest

from vc_alpha.db import SCHEMA
from vc_alpha.entities import Mention, install, normalise_name, ranked, resolve

NOW = "2026-09-12T00:00:00+00:00"

# The entities table as it was before norm_name and handle were added. Kept
# verbatim rather than generated, so it cannot drift with the current schema.
OLD_ENTITIES = """
CREATE TABLE entities (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,
  name          TEXT NOT NULL,
  domain        TEXT,
  github        TEXT,
  linkedin      TEXT,
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  mentions      INTEGER NOT NULL DEFAULT 0,
  sources       TEXT,
  score         REAL,
  signals_json  TEXT,
  needs_review  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE entity_evidence (
  entity_id     TEXT NOT NULL,
  candidate_id  TEXT NOT NULL,
  role          TEXT,
  PRIMARY KEY (entity_id, candidate_id, role)
);
"""


@pytest.fixture
def old_db():
    """A database as it existed two schema versions ago, with data in it."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.executescript(OLD_ENTITIES)
    c.execute(
        """INSERT INTO entities (id, kind, name, domain, first_seen, last_seen,
           mentions, sources, score)
           VALUES ('e1','company','Acme, Inc.','acme.io',?,?,3,'hackernews',0.7)""",
        (NOW, NOW))
    c.commit()
    return c


def test_install_succeeds_on_a_database_that_predates_the_columns(old_db):
    """The exact failure a user hit: 'no such column: norm_name', because the index
    was declared in the schema that runs before the migration adds the column."""
    install(old_db)          # must not raise
    cols = {r[1] for r in old_db.execute("PRAGMA table_info(entities)")}
    assert {"norm_name", "handle"} <= cols


def test_existing_rows_are_backfilled_not_orphaned(old_db):
    """A row written before the column existed must still be findable by it.
    Without backfill it becomes invisible to the indexed lookup and silently stops
    merging, which is worse than an error because nothing complains."""
    install(old_db)
    row = old_db.execute("SELECT norm_name FROM entities WHERE id='e1'").fetchone()
    assert row["norm_name"] == normalise_name("Acme, Inc.")


def test_old_rows_still_match_new_mentions(old_db):
    """The behaviour the backfill is for: a mention of the same company resolves to
    the pre-existing row rather than creating a duplicate."""
    install(old_db)
    eid = resolve(old_db, Mention("Acme", domain="acme.io"), now=NOW)
    assert eid == "e1"
    assert old_db.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1


def test_install_is_idempotent(old_db):
    install(old_db)
    install(old_db)
    install(old_db)
    assert old_db.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1


def test_ranked_works_after_migration(old_db):
    """The endpoint that returned a 500."""
    install(old_db)
    assert [r["id"] for r in ranked(old_db)] == ["e1"]


def test_the_index_exists_after_migration(old_db):
    install(old_db)
    names = {r[0] for r in old_db.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_entity_norm" in names, "the O(1) lookup would silently become O(N)"
