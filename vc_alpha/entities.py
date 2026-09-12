"""People and companies, assembled from every mention across every source.

The research is unambiguous that the predictive unit at seed stage is the team:
95% of 885 institutional VCs called it the essential factor, and relevant prior
experience and shared work history are what separate top performers. This product
was scoring posts, which is the wrong unit. A founder who appears on Hacker News,
in a Substack piece and in a WhatsApp group was three unrelated rows.

An entity gathers those mentions. Three independent sightings across three sources
is a materially stronger signal than one post scoring well, and only becomes
visible once the mentions are joined.

The governing rule for resolution: **a wrong merge is far worse than a duplicate.**
A merged pair silently corrupts a dossier and a partner acts on it. A duplicate is
untidy and obvious. So identifiers merge, strong name matches merge, and anything
ambiguous is left apart and flagged for a human rather than guessed at.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from urllib.parse import urlparse

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,          -- person | company
  name          TEXT NOT NULL,
  -- Denormalised so a name match is an index lookup rather than a table scan.
  -- Without it resolve() compared every existing entity on every mention, which
  -- is O(N) per mention and O(N²) overall: measured at 4.7ms per mention with 500
  -- entities and 31ms with 4,000, so a 50,000-entity corpus would take hours.
  norm_name     TEXT,
  domain        TEXT,
  github        TEXT,
  linkedin      TEXT,
  handle        TEXT,
  first_seen    TEXT NOT NULL,
  last_seen     TEXT NOT NULL,
  mentions      INTEGER NOT NULL DEFAULT 0,
  sources       TEXT,                   -- comma separated, for "seen in N places"
  score         REAL,
  signals_json  TEXT,
  needs_review  INTEGER NOT NULL DEFAULT 0   -- an ambiguous match a human should judge
);

-- Which candidates are evidence for which entity. A candidate can support more
-- than one, since a post often mentions both a founder and their company.
CREATE TABLE IF NOT EXISTS entity_evidence (
  entity_id     TEXT NOT NULL,
  candidate_id  TEXT NOT NULL,
  role          TEXT,                   -- author | mentioned | founder_of
  PRIMARY KEY (entity_id, candidate_id, role)
);

CREATE INDEX IF NOT EXISTS idx_entity_score ON entities(score DESC);
CREATE INDEX IF NOT EXISTS idx_entity_norm ON entities(kind, norm_name);
CREATE INDEX IF NOT EXISTS idx_evidence_entity ON entity_evidence(entity_id);
"""

# Hosts that identify a person or company by their URL path rather than being one.
_HANDLE_HOSTS = {
    "github.com": "github",
    "www.github.com": "github",
    "linkedin.com": "linkedin",
    "www.linkedin.com": "linkedin",
}

# Never a company's own site: aggregators, app stores, press, and places people
# host things. Found by running extraction over a real corpus, where apps.apple.com
# and theverge.com were confidently promoted to companies.
_NOT_A_COMPANY = {
    # aggregators and forums
    "news.ycombinator.com", "substack.com", "reddit.com", "twitter.com", "x.com",
    "medium.com", "youtube.com", "youtu.be", "lobste.rs", "producthunt.com",
    "dev.to", "hashnode.dev", "linkedin.com", "github.com", "gitlab.com",
    # app stores and distribution
    "apps.apple.com", "play.google.com", "chromewebstore.google.com",
    "addons.mozilla.org", "marketplace.visualstudio.com", "npmjs.com", "pypi.org",
    # press
    "theverge.com", "techcrunch.com", "wired.com", "arstechnica.com", "nytimes.com",
    "bloomberg.com", "reuters.com", "forbes.com", "businessinsider.com",
    # docs and shorteners
    "docs.google.com", "drive.google.com", "notion.so", "imgur.com",
    "archive.org", "web.archive.org", "en.wikipedia.org", "bit.ly", "t.co",
}

# Hosting platforms, matched by suffix: a project at myproject.vercel.app is
# hosted there, it does not own the domain. Exact matching missed every subdomain,
# which is the only form these ever appear in.
_HOSTING_SUFFIXES = (
    ".substack.com", ".vercel.app", ".netlify.app", ".herokuapp.com", ".pages.dev",
    ".github.io", ".gitlab.io", ".notion.site", ".webflow.io", ".framer.website",
    ".myshopify.com", ".wordpress.com", ".blogspot.com", ".medium.com",
    ".streamlit.app", ".onrender.com", ".fly.dev", ".workers.dev", ".replit.app",
)

_NOISE_WORDS = re.compile(
    r"\b(inc|llc|ltd|gmbh|bv|ab|oy|corp|co|the|a|an)\b\.?", re.I
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalise_name(name: str) -> str:
    """Lowercase, strip legal suffixes and punctuation, for comparison only."""
    return _NON_ALNUM.sub("", _NOISE_WORDS.sub("", (name or "").lower())).strip()


def normalise_domain(url: str | None) -> str | None:
    """The registrable-ish host, or None if this URL does not identify a company."""
    if not url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return None
    if not host or host in _NOT_A_COMPANY:
        return None
    if host.endswith(_HOSTING_SUFFIXES):
        return None
    return host


def handle_from(url: str | None) -> tuple[str, str] | None:
    """('github', 'acme-inc') for a GitHub or LinkedIn URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    kind = _HANDLE_HOSTS.get((parsed.hostname or "").lower())
    if not kind:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if kind == "linkedin":
        # /in/<slug> is a person; /company/<slug> is a company.
        if len(parts) >= 2 and parts[0] in ("in", "company"):
            return kind, parts[1].lower()
        return None
    return (kind, parts[0].lower()) if parts else None


@dataclass(slots=True)
class Mention:
    """One sighting of something that might be an entity."""

    name: str
    kind: str = "company"
    domain: str | None = None
    github: str | None = None
    linkedin: str | None = None
    # A username on a platform, as "hackernews:patio11". Unique on that platform,
    # so it is a hard identifier rather than a name guess. Without this every
    # repeat author merged on name alone and was flagged for review, which buried
    # the genuinely ambiguous cases the flag exists for.
    handle: str | None = None
    candidate_id: str | None = None
    source: str | None = None
    role: str = "mentioned"
    keys: set[str] = field(default_factory=set)

    def identity_keys(self) -> set[str]:
        """Strong keys only. Two mentions sharing one of these are the same thing."""
        keys = set()
        if self.domain:
            keys.add(f"domain:{self.domain}")
        if self.github:
            keys.add(f"github:{self.github}")
        if self.linkedin:
            keys.add(f"linkedin:{self.linkedin}")
        if self.handle:
            keys.add(f"handle:{self.handle}")
        return keys

    @property
    def id(self) -> str:
        seed = sorted(self.identity_keys()) or [f"{self.kind}:{normalise_name(self.name)}"]
        return hashlib.sha256("|".join(seed).encode()).hexdigest()[:32]


# Columns added after the first release. SQLite has no ALTER TABLE IF NOT EXISTS,
# and CREATE TABLE IF NOT EXISTS silently leaves an older table alone, so a schema
# change is invisible until a query fails on live data. Applied explicitly instead.
_ADDED_COLUMNS = {"entities": {"handle": "TEXT", "norm_name": "TEXT"}}


def install(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, columns in _ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                log.info("migrated %s: added %s", table, name)

    # Backfill for rows written before norm_name existed, otherwise they are
    # invisible to the indexed lookup and would silently stop merging.
    for row in conn.execute(
        "SELECT id, name FROM entities WHERE norm_name IS NULL"
    ).fetchall():
        conn.execute("UPDATE entities SET norm_name = ? WHERE id = ?",
                     (normalise_name(row["name"]), row["id"]))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_norm ON entities(kind, norm_name)")
    conn.commit()


def resolve(conn: sqlite3.Connection, mention: Mention, *, now: str) -> str:
    """Find or create the entity for a mention, and record the evidence.

    Matching order, strongest first:
      1. a shared identity key (domain, github, linkedin) — merge outright
      2. identical normalised name AND the same kind — merge, but flag for review
         when neither side carries an identity key, because names collide
      3. otherwise a new entity

    Embedding similarity is deliberately not used here. It would merge "Acme
    Security" with "Acme Analytics", and per the rule above a wrong merge costs far
    more than a duplicate.
    """
    install(conn)
    keys = mention.identity_keys()

    row = None
    if keys:
        clauses, params = [], []
        for k in keys:
            field_name, _, value = k.partition(":")
            clauses.append(f"{field_name} = ?")
            params.append(value)
        row = conn.execute(
            f"SELECT * FROM entities WHERE {' OR '.join(clauses)} LIMIT 1", params
        ).fetchone()

    flagged = False
    norm = normalise_name(mention.name)
    if row is None:
        if norm:
            # Indexed equality lookup rather than a scan over every entity of this
            # kind. Only genuine name matches come back, so the loop below runs
            # over a handful of rows instead of the whole table.
            candidates = conn.execute(
                "SELECT * FROM entities WHERE kind = ? AND norm_name = ?",
                (mention.kind, norm),
            ).fetchall()
            for c in candidates:
                # Both sides carry identifiers and none of them agree: these are
                # definitively different things that happen to share a name. Acme
                # Security and Acme Analytics are not one company. Never merge.
                existing = {f"domain:{c['domain']}" if c["domain"] else "",
                            f"github:{c['github']}" if c["github"] else "",
                            f"linkedin:{c['linkedin']}" if c["linkedin"] else "",
                            f"handle:{c['handle']}" if c["handle"] else ""} - {""}
                if keys and existing and not (keys & existing):
                    continue
                # Same name, and at least one side has no hard identifier: plausible
                # but not certain. Merge so the dossier stays whole, flag so a human
                # can split it if the guess was wrong.
                row = c
                flagged = not (keys and existing)
                break

    if row is None:
        entity_id = mention.id
        conn.execute(
            """INSERT OR IGNORE INTO entities
               (id, kind, name, norm_name, domain, github, linkedin, handle,
                first_seen, last_seen, mentions, sources, needs_review)
               VALUES (?,?,?,?,?,?,?,?,?,?,0,?,0)""",
            (entity_id, mention.kind, mention.name, norm, mention.domain,
             mention.github, mention.linkedin, mention.handle, now, now,
             mention.source or ""),
        )
    else:
        entity_id = row["id"]
        sources = {s for s in (row["sources"] or "").split(",") if s}
        if mention.source:
            sources.add(mention.source)
        conn.execute(
            """UPDATE entities SET last_seen = ?, sources = ?,
                   domain = COALESCE(domain, ?), github = COALESCE(github, ?),
                   linkedin = COALESCE(linkedin, ?), handle = COALESCE(handle, ?),
                   -- A later sighting carrying a hard identifier confirms a match
                   -- that was previously only a name guess, so the flag clears.
                   -- Leaving it set forever would train people to ignore it.
                   needs_review = ?
               WHERE id = ?""",
            (now, ",".join(sorted(sources)), mention.domain, mention.github,
             mention.linkedin, mention.handle,
             int(flagged and not keys), entity_id),
        )

    if mention.candidate_id:
        conn.execute(
            "INSERT OR IGNORE INTO entity_evidence VALUES (?,?,?)",
            (entity_id, mention.candidate_id, mention.role),
        )
    conn.execute(
        """UPDATE entities SET mentions =
             (SELECT COUNT(DISTINCT candidate_id) FROM entity_evidence WHERE entity_id = ?)
           WHERE id = ?""",
        (entity_id, entity_id),
    )
    conn.commit()
    return entity_id


def evidence(conn: sqlite3.Connection, entity_id: str) -> list[sqlite3.Row]:
    """Every candidate supporting an entity, best first. This is the dossier."""
    return conn.execute(
        """SELECT c.*, e.role FROM entity_evidence e
           JOIN candidates c ON c.id = e.candidate_id
           WHERE e.entity_id = ?
           ORDER BY COALESCE(c.score, c.similarity) DESC""",
        (entity_id,),
    ).fetchall()


def ranked(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    install(conn)
    return conn.execute(
        """SELECT * FROM entities
           WHERE score IS NOT NULL ORDER BY score DESC LIMIT ?""",
        (limit,),
    ).fetchall()
