"""SQLite storage. Schema lives here; docs/PLAN.md explains the reasoning."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    """Delete candidates past their retention date. Returns how many went."""
    n = conn.execute(
        "DELETE FROM candidates WHERE retention_until < ?", (now(),)
    ).rowcount
    n += conn.execute(
        "DELETE FROM whatsapp_messages WHERE retention_until < ?", (now(),)
    ).rowcount
    conn.commit()
    return n


def forget_author(conn: sqlite3.Connection, author: str) -> int:
    """Erase one person everywhere. Single path, so a deletion request is one call."""
    n = conn.execute("DELETE FROM candidates WHERE author = ?", (author,)).rowcount
    conn.execute("DELETE FROM author_activity WHERE author = ?", (author,))
    n += conn.execute(
        "DELETE FROM whatsapp_messages WHERE sender = ?", (author,)
    ).rowcount
    conn.commit()
    return n
