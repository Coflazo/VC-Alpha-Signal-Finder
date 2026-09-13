"""The two GDPR obligations the product documented and did not discharge.

`purge_expired()` and `forget_author()` both existed. Neither was called by
anything outside a test, while README, PLAN and PRIVACY all described retention
as "enforced by a real deletion job" and pointed funds at `forget_author` for
erasure requests.

`forget_author` was also incomplete in the way that matters most: it cleared
candidates, activity and messages but left `entities` and `entity_evidence`
alone, so the person named in an erasure request kept their dossier — name,
handle, score and the quotes behind it — and the fund would report the erasure
done.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from vc_alpha.app.main import app
from vc_alpha.db import (
    SCHEMA, expiring_within, forget_author, migrate, purge_expired,
)
from vc_alpha.entities import Mention, install, resolve

PAST = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
SOON = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
FAR = (datetime.now(timezone.utc) + timedelta(days=300)).isoformat()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    migrate(c)
    return c


def _candidate(conn, cid, *, author="ada", until=FAR, url=None):
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, author,
           discovered_at, retention_until)
           VALUES (?, 'hackernews', ?, 'I am building developer tooling',
                   ?, '2026-01-01', ?)""",
        (cid, url or f"https://news.ycombinator.com/{cid}", author, until),
    )
    conn.commit()


# --- retention ---------------------------------------------------------------


def test_expired_rows_are_deleted(conn):
    _candidate(conn, "old", until=PAST)
    _candidate(conn, "current", until=FAR)

    assert purge_expired(conn) == 1
    remaining = {r[0] for r in conn.execute("SELECT id FROM candidates")}
    assert remaining == {"current"}


def test_expiring_within_reports_what_is_about_to_go(conn):
    _candidate(conn, "soon", until=SOON)
    _candidate(conn, "later", until=FAR)
    assert expiring_within(conn, 7) == 1
    assert expiring_within(conn, 365) == 2


def test_purge_takes_the_evidence_with_it(conn):
    """Evidence rows point at candidates with no foreign key between them, so
    nothing else would ever clean these up."""
    install(conn)
    _candidate(conn, "old", until=PAST)
    conn.execute(
        "INSERT INTO entity_evidence (entity_id, candidate_id, role) "
        "VALUES ('e1', 'old', 'author')")
    conn.commit()

    purge_expired(conn)
    assert conn.execute("SELECT COUNT(*) FROM entity_evidence").fetchone()[0] == 0


def test_purge_works_before_entities_are_ever_built(conn):
    """A database that has only collected has no entity tables at all."""
    _candidate(conn, "old", until=PAST)
    assert purge_expired(conn) == 1


@pytest.mark.parametrize("module", ["collect", "score_all", "pipeline"])
def test_every_entry_point_runs_the_retention_job(module):
    """The defect was not a missing function, it was a function nothing called."""
    import inspect
    import importlib

    src = inspect.getsource(importlib.import_module(f"vc_alpha.{module}"))
    assert "purge_expired(conn)" in src, f"{module} does not enforce retention"


# --- erasure -----------------------------------------------------------------


def test_erasure_removes_the_persons_own_rows(conn):
    _candidate(conn, "a", author="ada")
    _candidate(conn, "b", author="grace")
    conn.execute(
        """INSERT INTO whatsapp_messages (id, chat, sender, sent_at, text, line_no,
           retention_until) VALUES ('m1','chat','ada','2026-01-01','hello',1,?)""",
        (FAR,))
    conn.execute(
        "INSERT INTO author_activity (source, author, node, seen_at) "
        "VALUES ('hackernews','ada','n1','2026-01-01')")
    conn.commit()

    forget_author(conn, "ada")

    assert [r[0] for r in conn.execute("SELECT author FROM candidates")] == ["grace"]
    assert conn.execute("SELECT COUNT(*) FROM whatsapp_messages").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM author_activity").fetchone()[0] == 0


def test_erasure_removes_the_dossier_too(conn):
    """The defect. The person kept their entity profile — name, handle, score and
    the quotes behind it — while the fund reported the erasure complete."""
    install(conn)
    _candidate(conn, "a", author="ada", url="https://news.ycombinator.com/user?id=ada")
    resolve(conn, Mention(kind="person", name="ada", handle="hackernews:ada",
                          candidate_id="a", source="hackernews", role="author"), now="2026-01-01")

    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1

    forget_author(conn, "ada")

    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM entity_evidence").fetchone()[0] == 0


def test_nothing_of_the_person_survives_anywhere(conn):
    """The property an erasure request actually needs: grep every table."""
    install(conn)
    _candidate(conn, "a", author="ada")
    resolve(conn, Mention(kind="person", name="ada", handle="hackernews:ada",
                          candidate_id="a", source="hackernews", role="author"), now="2026-01-01")
    forget_author(conn, "ada")

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        for row in conn.execute(f"SELECT * FROM {table}"):
            for col, value in zip(cols, row):
                assert "ada" != str(value), f"{table}.{col} still holds the person"


def test_erasure_removes_their_crawl_target_so_it_does_not_undo_itself(conn):
    """Found against the real database.

    A person's own node — their Substack subdomain, their GitHub profile — is a
    place the collector revisits every six hours. Delete their posts but leave the
    node and the next scheduled run puts everything straight back, so the erasure
    quietly expires. The node row also holds their handle and display name.
    """
    conn.execute(
        """INSERT INTO nodes (source, node, display_name, added_at, source_kind)
           VALUES ('substack', 'ada', 'ada', '2026-01-01', 'discovered')""")
    conn.execute(
        """INSERT INTO nodes (source, node, display_name, added_at, source_kind, parent)
           VALUES ('substack', 'someone-else', 'Someone Else', '2026-01-01',
                   'discovered', 'ada')""")
    _candidate(conn, "a", author="ada")
    conn.commit()

    forget_author(conn, "ada")

    nodes = {r["node"]: r["parent"] for r in conn.execute("SELECT * FROM nodes")}
    assert "ada" not in nodes, "their own crawl target must go, or collection resumes"
    # The people they led us to are not themselves personal data about them, but
    # the pointer back to them is.
    assert nodes["someone-else"] is None


def test_erasure_leaves_other_people_alone(conn):
    install(conn)
    _candidate(conn, "a", author="ada")
    _candidate(conn, "b", author="grace")
    resolve(conn, Mention(kind="person", name="grace", handle="hackernews:grace",
                          candidate_id="b", source="hackernews", role="author"), now="2026-01-01")

    forget_author(conn, "ada")
    assert conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1


# --- reachable without a Python shell ----------------------------------------


def test_the_api_reports_scope_before_deleting():
    """Irreversible, so the operator sees what would go first."""
    client = TestClient(app)
    r = client.post("/api/forget", json={"author": "nobody"})
    assert r.status_code == 200
    assert r.json()["confirmed"] is False
    assert "would_delete" in r.json()


def test_the_api_refuses_an_empty_name():
    assert TestClient(app).post("/api/forget", json={"author": "  "}).status_code == 400


def test_retention_policy_is_visible():
    d = TestClient(app).get("/api/retention").json()
    assert d["retention_days"] == 365
    assert "expiring_within_7_days" in d


def test_the_cli_exposes_both():
    """PRIVACY.md used to tell a fund to open a Python shell and import a function.
    That is not a procedure anyone follows under a 30-day statutory deadline."""
    from vc_alpha.cli import COMMANDS

    assert "forget" in COMMANDS
    assert "purge" in COMMANDS


def test_the_mcp_server_requires_confirmation():
    """An assistant should not be able to erase someone by misreading a sentence."""
    from vc_alpha.mcp_server import forget_person

    out = forget_person.fn("ada") if hasattr(forget_person, "fn") else forget_person("ada")
    assert out["confirmed"] is False
