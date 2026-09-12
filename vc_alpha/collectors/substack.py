"""Substack.

Two public endpoints, no key, no account, no scraping library:

    GET /api/v1/archive?sort=new&limit=N&offset=M    posts for a publication
    GET /api/v1/recommendations/from/{pub_id}        publications it recommends

The recommendation graph is the interesting half. Publications recommend each
other as an intended product feature, so walking it is reading something Substack
built to be read. Seeding from one VC newsletter reaches andrewchen, The VC Corner
and speedrun in a single hop.

Public posts only. Paywalled content stays paywalled.
"""

from __future__ import annotations

import logging
import re

import httpx

from vc_alpha.collectors.base import CandidateRecord, Collector, Neighbour, Visit

log = logging.getLogger(__name__)

# Newsletters that write about people starting companies. The graph does the rest.
DEFAULT_SEEDS = [
    ("thevccorner", "The VC Corner"),
    ("andrewchen", "@andrewchen"),
    ("thegeneralist", "The Generalist"),
    ("speedrun", "speedrun"),
]

ARCHIVE_PAGE = 50
TIMEOUT = httpx.Timeout(20.0)
UA = "vc-alpha-signal-finder/0.1 (+https://github.com/Coflazo/VC-Alpha-Signal-Finder)"

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _text(html: str | None) -> str:
    """Strip tags for embedding. Full markdown extraction is enrich/fetch.py's job."""
    if not html:
        return ""
    return _WS.sub(" ", _TAGS.sub(" ", html)).strip()


class SubstackCollector(Collector):
    source = "substack"

    def __init__(self, client: httpx.Client | None = None, max_posts: int = 100):
        self._client = client or httpx.Client(
            timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True
        )
        self.max_posts = max_posts

    def seeds(self):
        return [Neighbour(sub, name) for sub, name in DEFAULT_SEEDS]

    def _get(self, subdomain: str, path: str):
        r = self._client.get(f"https://{subdomain}.substack.com{path}")
        r.raise_for_status()
        return r.json()

    def _archive(self, subdomain: str) -> list[dict]:
        """Paged archive. Stops early when a page comes back short."""
        posts: list[dict] = []
        offset = 0
        while len(posts) < self.max_posts:
            limit = min(ARCHIVE_PAGE, self.max_posts - len(posts))
            page = self._get(
                subdomain, f"/api/v1/archive?sort=new&limit={limit}&offset={offset}"
            )
            if not page:
                break
            posts.extend(page)
            if len(page) < limit:
                break  # reached the end of the archive
            offset += len(page)
        return posts

    def _recommendations(self, publication_id: int, subdomain: str) -> list[Neighbour]:
        try:
            rows = self._get(subdomain, f"/api/v1/recommendations/from/{publication_id}")
        except httpx.HTTPError:
            # Plenty of publications recommend nobody. Not an error worth shouting about.
            return []
        out = []
        for row in rows:
            pub = row.get("recommendedPublication") or {}
            if sub := pub.get("subdomain"):
                out.append(Neighbour(sub, pub.get("name")))
        return out

    def visit(self, node: str) -> Visit:
        posts = self._archive(node)
        if not posts:
            return Visit(exhausted=True)

        candidates = []
        for p in posts:
            body = _text(p.get("description")) or _text(p.get("truncated_body_text"))
            title = p.get("title") or ""
            url = p.get("canonical_url")
            if not url:
                continue
            byline = (p.get("publishedBylines") or [{}])[0]
            candidates.append(
                CandidateRecord(
                    source=self.source,
                    source_url=url,
                    raw_text=f"{title}\n\n{body}".strip(),
                    title=title,
                    author=byline.get("name"),
                    node=node,
                    posted_at=p.get("post_date"),
                )
            )

        pub_id = posts[0].get("publication_id")
        neighbours = self._recommendations(pub_id, node) if pub_id else []

        # An archive shorter than the cap means we have seen everything it has.
        return Visit(
            candidates=candidates,
            neighbours=neighbours,
            exhausted=len(posts) < self.max_posts,
        )
