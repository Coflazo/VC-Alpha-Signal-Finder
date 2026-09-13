"""SQLite storage. Schema lives here; docs/PLAN.md explains the reasoning."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# How long a candidate is kept before the retention job deletes it.
# These are people's posts and profiles, so this is a GDPR obligation, not a preference.
RETENTION_DAYS = 365

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
  id              TEXT PRIMARY KEY,     -- sha256 of source_url
  source          TEXT NOT NULL,        -- substack | reddit | linkedin
  source_url      TEXT NOT NULL UNIQUE,
  raw_text        TEXT NOT NULL,
  title           TEXT,
  author          TEXT,
  node            TEXT,                 -- frontier node this came from
  discovered_at   TEXT NOT NULL,
  posted_at       TEXT,

  embedding       BLOB,
  -- Which model produced `embedding`. Vectors from different providers have
  -- different dimensionalities and cosine between them is defined as zero, so
  -- mixing them silently zeroes every older score instead of erroring. Stored so
  -- a provider change is detected and re-embedded rather than quietly wrong.
  embedding_model TEXT,
  similarity      REAL,
  thesis_id       TEXT,

  triage_json     TEXT,
  is_startup      INTEGER,
  stage_guess     TEXT,
  confidence      REAL,

  research_md     TEXT,
  score           REAL,
  sheet_row       INTEGER,

  reviewed        INTEGER NOT NULL DEFAULT 0,
  was_good        INTEGER,

  retention_until TEXT NOT NULL,

  -- Why a cheap filter dropped this before embedding. Recorded rather
  -- than deleted so over-filtering is visible rather than silent.
  filtered_reason TEXT
);

-- Drives the "what still needs work" queries at every stage.
CREATE INDEX IF NOT EXISTS idx_pipeline ON candidates(similarity, is_startup, reviewed);
CREATE INDEX IF NOT EXISTS idx_source_node ON candidates(source, node);
CREATE INDEX IF NOT EXISTS idx_retention ON candidates(retention_until);

-- Frontier: one row per graph node across every source.
CREATE TABLE IF NOT EXISTS nodes (
  source        TEXT NOT NULL,          -- substack | reddit | linkedin
  node          TEXT NOT NULL,          -- subdomain | subreddit | profile slug
  display_name  TEXT,
  added_at      TEXT NOT NULL,
  source_kind   TEXT NOT NULL,          -- seed | discovered | manual
  depth         INTEGER NOT NULL DEFAULT 0,
  active        INTEGER NOT NULL DEFAULT 1,
  exhausted     INTEGER NOT NULL DEFAULT 0,
  parent        TEXT,
  seen_count    INTEGER NOT NULL DEFAULT 0,
  hit_count     INTEGER NOT NULL DEFAULT 0,
  last_visited  TEXT,
  PRIMARY KEY (source, node)
);

CREATE INDEX IF NOT EXISTS idx_frontier ON nodes(source, active, exhausted, depth);

-- Full WhatsApp exports, kept whole so a better model can re-read them later
-- without a re-import. Messages are promoted into `candidates` only when they
-- look like a lead; the rest stay here and never reach the pipeline.
CREATE TABLE IF NOT EXISTS whatsapp_messages (
  id              TEXT PRIMARY KEY,     -- sha256 of chat + timestamp + sender + text
  chat            TEXT NOT NULL,
  sender          TEXT,
  sent_at         TEXT,
  text            TEXT NOT NULL,
  line_no         INTEGER,
  promoted        INTEGER NOT NULL DEFAULT 0,
  retention_until TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wa_chat ON whatsapp_messages(chat, sent_at);
CREATE INDEX IF NOT EXISTS idx_wa_promoted ON whatsapp_messages(promoted);

-- Author activity, for Reddit's co-posting graph and LinkedIn cross-seeding.
CREATE TABLE IF NOT EXISTS author_activity (
  source     TEXT NOT NULL,
  author     TEXT NOT NULL,
  node       TEXT NOT NULL,
  seen_at    TEXT NOT NULL,
  PRIMARY KEY (source, author, node)
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open the database, creating it and its parent directory if needed.

    Resolved on call rather than at import, so `$VC_ALPHA_HOME` and `$VC_ALPHA_DB`
    still work when they are set after this module has been imported.
    """
    from vc_alpha import paths

    path = Path(path) if path is not None else paths.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Concurrent readers while a collector writes.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


# Columns added after the first release. `CREATE TABLE IF NOT EXISTS` leaves an
# existing table alone, so a schema change is invisible until a query fails on live
# data. Applied explicitly, the same way entities.install does.
_ADDED_COLUMNS = {"candidates": {"embedding_model": "TEXT"}}


def migrate(conn: sqlite3.Connection) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def retention_until(days: int = RETENTION_DAYS) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def purge_expired(conn: sqlite3.Connection) -> int:
    """Delete everything past its retention date. Returns how many rows went.

    Called at the start of every run and when the app starts. It used to be
    defined here and called by nothing, while README, PLAN and PRIVACY all
    described retention as "enforced by a real deletion job" — so the obligation
    was documented and not discharged. A retention period nothing acts on is a
    sentence in a file.
    """
    expired = [r[0] for r in conn.execute(
        "SELECT id FROM candidates WHERE retention_until < ?", (now(),))]
    n = conn.execute(
        "DELETE FROM candidates WHERE retention_until < ?", (now(),)
    ).rowcount
    n += conn.execute(
        "DELETE FROM whatsapp_messages WHERE retention_until < ?", (now(),)
    ).rowcount
    # Evidence rows point at candidates that no longer exist. There is no foreign
    # key between them, so nothing would have cleaned these up.
    for cid in expired:
        _drop_evidence(conn, cid)
    conn.commit()
    if n:
        log.info("retention: deleted %d expired rows", n)
    return n


def expiring_within(conn: sqlite3.Connection, days: int = 7) -> int:
    """How much is about to be deleted. Surfaced so retention is visible."""
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    return conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE retention_until < ?", (cutoff,)
    ).fetchone()[0]


def _drop_evidence(conn: sqlite3.Connection, candidate_id: str) -> None:
    """Remove a candidate from the entity tables, if those tables exist yet.

    Guarded because entities are installed lazily by entities.install(), so a
    database that has only ever collected has no such tables.
    """
    try:
        conn.execute("DELETE FROM entity_evidence WHERE candidate_id = ?",
                     (candidate_id,))
    except sqlite3.OperationalError:
        pass


def forget_author(conn: sqlite3.Connection, author: str) -> int:
    """Erase one person everywhere. Single path, so a deletion request is one call.

    "Everywhere" previously meant three tables and not the two that matter most.
    It cleared candidates, author_activity and whatsapp_messages but left
    `entities` and `entity_evidence` untouched — so the person named in an erasure
    request kept their dossier, with their name, their handle, their score and the
    quotes behind it. PRIVACY.md pointed a fund straight at this function, which
    made the gap worse than an undocumented one: the fund would report the erasure
    done.

    Returns the number of rows removed.
    """
    candidate_ids = [r[0] for r in conn.execute(
        "SELECT id FROM candidates WHERE author = ?", (author,))]

    n = conn.execute("DELETE FROM candidates WHERE author = ?", (author,)).rowcount
    conn.execute("DELETE FROM author_activity WHERE author = ?", (author,))
    n += conn.execute(
        "DELETE FROM whatsapp_messages WHERE sender = ?", (author,)
    ).rowcount
    n += _forget_entities(conn, author, candidate_ids)
    n += _forget_frontier(conn, author)

    conn.commit()
    log.info("erased %s: %d rows", author, n)
    return n


def _forget_frontier(conn: sqlite3.Connection, author: str) -> int:
    """Remove any crawl target that *is* this person, so nothing re-collects them.

    Two reasons this is not optional. Their own node — a Substack subdomain, a
    GitHub profile, a LinkedIn slug — is a place the collector revisits on a
    schedule, so leaving it means the next run puts their posts straight back and
    the erasure silently undoes itself within six hours. And the node row itself
    holds their handle and display name, which is personal data sitting in a table
    the deletion never touched.

    Deleted rather than deactivated. `frontier.deactivate` is a soft delete that
    keeps the row so hit-rate history survives, which is right for a subreddit
    that stopped producing and wrong for a person: the row is the data.

    A crawl target that merely shares a name with someone is lost as collateral.
    That is the correct way to be wrong here — the cost is one source, against an
    erasure that does not hold.
    """
    n = conn.execute(
        "DELETE FROM nodes WHERE node = ? OR display_name = ?", (author, author)
    ).rowcount
    # Their name also appears as the parent of whatever they led us to. The
    # children stay; the pointer back to the person does not.
    conn.execute("UPDATE nodes SET parent = NULL WHERE parent = ?", (author,))
    return n


def _forget_entities(conn: sqlite3.Connection, author: str,
                     candidate_ids: list[str]) -> int:
    """Remove the person's dossier and any evidence drawn from their posts.

    Matched the same way entities were created — on the normalised name and on the
    platform handle — so an erasure reaches exactly the rows a mention would have
    produced. Kept here rather than in entities.py so that erasure is one call
    against one module, which is the property a deletion request needs.
    """
    from vc_alpha.entities import normalise_name

    try:
        conn.execute("SELECT 1 FROM entities LIMIT 1")
    except sqlite3.OperationalError:
        return 0     # entities were never built on this database

    norm = normalise_name(author)
    ids = {r[0] for r in conn.execute(
        "SELECT id FROM entities WHERE norm_name = ? OR name = ?", (norm, author))}
    # A handle is stored as "platform:username", so the person is also whoever
    # posted under this name on any source.
    ids |= {r[0] for r in conn.execute(
        "SELECT id FROM entities WHERE handle LIKE ?", (f"%:{author}",))}

    n = 0
    for eid in ids:
        conn.execute("DELETE FROM entity_evidence WHERE entity_id = ?", (eid,))
        n += conn.execute("DELETE FROM entities WHERE id = ?", (eid,)).rowcount

    # Evidence rows drawn from their posts, even where the entity is someone else
    # — a company they founded keeps its dossier, but not the quote from them.
    for cid in candidate_ids:
        n += conn.execute(
            "DELETE FROM entity_evidence WHERE candidate_id = ?", (cid,)).rowcount
    return n
