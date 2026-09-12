"""Who do we already know who is near this person.

The one thing a funded data pipeline cannot replicate, because it needs membership
in the user's own communities. Harmonic and Specter can tell a fund that a company
exists; neither can tell them that someone in their WhatsApp group has been talking
to the founder for a year.

Everything here is computed from data already collected and never leaves the
machine. It states observations, never relationships: "posts in the same two
subreddits" is a fact, "knows" is a claim this has no basis to make.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Ordered by how much a warm introduction is actually worth. A shared private group
# is worth far more than a shared public forum, because membership implies someone
# vouched for someone.
STRENGTH = {
    "whatsapp_group": 1.00,
    "github_org": 0.60,
    "same_subreddit": 0.35,
    "same_publication": 0.25,
}


@dataclass(frozen=True, slots=True)
class Path:
    kind: str
    via: str          # the group, org or forum
    person: str       # who in it we already have
    strength: float

    def describe(self) -> str:
        """Deliberately an observation, not a claim of relationship."""
        return {
            "whatsapp_group": f"{self.person} is in your {self.via} group",
            "github_org": f"{self.person} appears in the {self.via} org",
            "same_subreddit": f"{self.person} also posts in r/{self.via}",
            "same_publication": f"{self.person} also writes in {self.via}",
        }[self.kind]


def _author_of(conn: sqlite3.Connection, entity_id: str) -> str | None:
    row = conn.execute(
        """SELECT c.author FROM entity_evidence e
           JOIN candidates c ON c.id = e.candidate_id
           WHERE e.entity_id = ? AND c.author IS NOT NULL LIMIT 1""",
        (entity_id,),
    ).fetchone()
    return row["author"] if row else None


def paths_to(conn: sqlite3.Connection, entity_id: str, limit: int = 10) -> list[Path]:
    """Routes from people already in the corpus to this entity.

    A person shares a node with the target: the same WhatsApp group, subreddit,
    GitHub org or publication. Since collection is driven by the user's own
    watchlists and groups, everyone here is someone they have some proximity to.
    """
    author = _author_of(conn, entity_id)
    if not author:
        return []

    nodes = conn.execute(
        """SELECT DISTINCT c.source, c.node FROM entity_evidence e
           JOIN candidates c ON c.id = e.candidate_id
           WHERE e.entity_id = ? AND c.node IS NOT NULL""",
        (entity_id,),
    ).fetchall()

    kind_for = {
        "whatsapp": "whatsapp_group",
        "reddit": "same_subreddit",
        "substack": "same_publication",
        "github": "github_org",
    }

    found: dict[tuple[str, str], Path] = {}
    for n in nodes:
        kind = kind_for.get(n["source"])
        if not kind:
            continue
        others = conn.execute(
            """SELECT DISTINCT author FROM candidates
               WHERE source = ? AND node = ? AND author IS NOT NULL AND author != ?
               LIMIT 25""",
            (n["source"], n["node"], author),
        ).fetchall()
        for o in others:
            key = (kind, o["author"])
            if key not in found:
                found[key] = Path(kind, n["node"], o["author"], STRENGTH[kind])

    return sorted(found.values(), key=lambda p: -p.strength)[:limit]


def reachability(paths: list[Path]) -> float:
    """A 0..1 summary for the `reachable` signal.

    Driven by the strongest single path rather than the count. One person in a
    private group is worth more than twenty strangers in the same large forum, and
    summing would say the opposite.
    """
    return max((p.strength for p in paths), default=0.0)
