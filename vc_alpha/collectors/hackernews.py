"""Hacker News, via the Algolia search API. Free, no key, no rate limit worth planning around.

This is the best first-hand source available. A Show HN post is a founder announcing
their own thing, in their own words, usually before there is a press mention or a
funding round. Substack gives you people writing *about* startups; this gives you the
founder directly.

The graph here is authorial. A node is either a query or an author:

    query:show hn          search, the entry point
    author:patio11         everything that person submitted

A founder who posts one good Show HN has usually posted before, and their earlier
submissions tell you how long they have been at it. So a query that yields a match
expands into that person's other work.
"""

from __future__ import annotations

import logging

import httpx

from vc_alpha.collectors.base import CandidateRecord, Collector, Neighbour, Visit

log = logging.getLogger(__name__)

API = "https://hn.algolia.com/api/v1"
TIMEOUT = httpx.Timeout(20.0)
UA = "vc-alpha-signal-finder/0.1 (+https://github.com/Coflazo/VC-Alpha-Signal-Finder)"

# Phrases founders use about their own work. Deliberately first person.
DEFAULT_SEEDS = [
    ("query:show hn", "Show HN"),
    ("query:i built", "I built"),
    ("query:we built", "We built"),
    ("query:launching", "Launching"),
    ("query:my startup", "My startup"),
    ("query:we raised", "We raised"),
]

PAGE = 100


class HackerNewsCollector(Collector):
    source = "hackernews"

    def __init__(self, client: httpx.Client | None = None, max_items: int = 100):
        self._client = client or httpx.Client(
            timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True
        )
        self.max_items = max_items

    def seeds(self):
        return [Neighbour(n, label) for n, label in DEFAULT_SEEDS]

    def _search(self, params: dict) -> list[dict]:
        r = self._client.get(f"{API}/search_by_date", params=params)
        r.raise_for_status()
        return r.json().get("hits", [])

    def visit(self, node: str) -> Visit:
        kind, _, value = node.partition(":")
        limit = min(self.max_items, PAGE)

        if kind == "author":
            hits = self._search(
                {"tags": f"story,author_{value}", "hitsPerPage": limit}
            )
        elif kind == "query":
            hits = self._search(
                {"tags": "story", "query": value, "hitsPerPage": limit}
            )
        else:
            log.warning("unknown hackernews node kind: %s", node)
            return Visit(exhausted=True)

        candidates, authors = [], set()
        for h in hits:
            oid = h.get("objectID")
            if not oid:
                continue
            title = h.get("title") or h.get("story_title") or ""
            body = h.get("story_text") or h.get("comment_text") or ""
            # The discussion URL, not the product URL, so one submission is one row
            # however many times it is reposted elsewhere.
            candidates.append(
                CandidateRecord(
                    source=self.source,
                    source_url=f"https://news.ycombinator.com/item?id={oid}",
                    raw_text=f"{title}\n\n{body}\n\n{h.get('url') or ''}".strip(),
                    title=title,
                    author=h.get("author"),
                    node=node,
                    posted_at=h.get("created_at"),
                )
            )
            if h.get("author"):
                authors.add(h["author"])

        # Queries expand into the people who answered them. Authors are leaves:
        # following author to author would drift into general HN, not founders.
        neighbours = (
            [Neighbour(f"author:{a}", a) for a in sorted(authors)]
            if kind == "query" else []
        )

        return Visit(
            candidates=candidates,
            neighbours=neighbours,
            exhausted=kind == "author" and len(hits) < limit,
        )
