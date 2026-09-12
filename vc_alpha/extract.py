"""Pull entity mentions out of candidates using only what is already in hand.

No model calls. URLs, GitHub org names and authors are structured data sitting in
the text; spending inference on them would be paying for something free. The model
is for judgement, not for reading a hyperlink.
"""

from __future__ import annotations

import re
import sqlite3

from vc_alpha.entities import Mention, handle_from, normalise_domain, resolve
from vc_alpha.db import now

_URL = re.compile(r"https?://[^\s<>\"')]+")

# GitHub candidates arrive as "org/repo" in the title.
_REPO = re.compile(r"^([A-Za-z0-9][\w.-]*)/([\w.-]+)$")


def mentions_from(row: sqlite3.Row) -> list[Mention]:
    """Every entity a candidate points at. Often two: the founder and the company."""
    out: list[Mention] = []
    text = f"{row['title'] or ''}\n{row['raw_text'] or ''}"
    source = row["source"]

    # A GitHub candidate names its org directly.
    if source == "github" and (m := _REPO.match((row["title"] or "").strip())):
        out.append(Mention(
            name=m.group(1), kind="company", github=m.group(1).lower(),
            candidate_id=row["id"], source=source, role="founder_of",
        ))

    for url in _URL.findall(text):
        url = url.rstrip(".,)")
        if handle := handle_from(url):
            kind, value = handle
            is_person = kind == "linkedin" and "/in/" in url
            out.append(Mention(
                name=value, kind="person" if is_person else "company",
                **{kind: value},
                candidate_id=row["id"], source=source, role="mentioned",
            ))
        elif domain := normalise_domain(url):
            out.append(Mention(
                name=domain, kind="company", domain=domain,
                candidate_id=row["id"], source=source, role="mentioned",
            ))

    # The author of a first-hand post is the founder, not a mentioned third party.
    if row["author"] and source in ("hackernews", "reddit", "whatsapp"):
        out.append(Mention(
            name=row["author"], kind="person",
            handle=f"{source}:{row['author'].lower()}",
            candidate_id=row["id"], source=source, role="author",
        ))
    return out


def build(conn: sqlite3.Connection, limit: int | None = None) -> dict[str, int]:
    """Resolve entities for every candidate that passed the cheap filters."""
    sql = ("SELECT id, title, raw_text, source, author FROM candidates "
           "WHERE filtered_reason IS NULL")
    if limit:
        sql += f" LIMIT {int(limit)}"

    stamp = now()
    stats = {"candidates": 0, "mentions": 0}
    for row in conn.execute(sql).fetchall():
        stats["candidates"] += 1
        for mention in mentions_from(row):
            resolve(conn, mention, now=stamp)
            stats["mentions"] += 1
    return stats
