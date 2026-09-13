"""Reddit, via PRAW.

The design is in docs/COLLECTORS.md. Three jobs, three mechanisms: stream the
watchlist continuously, backfill when a subreddit is added, and discover new
subreddits from the co-posting graph of authors who already scored well.

Reddit has no anonymous path. Its JSON endpoints return 403 and the RSS feeds come
back empty, so this needs a free OAuth app: reddit.com/prefs/apps, script type,
about two minutes. Without credentials the collector reports that clearly rather
than failing obscurely.
"""

from __future__ import annotations

import logging
import os
import sqlite3

from vc_alpha.collectors.base import CandidateRecord, Collector, Neighbour, Visit

log = logging.getLogger(__name__)

DEFAULT_SUBREDDITS = [
    ("SaaS", "r/SaaS"),
    ("startups", "r/startups"),
    ("EntrepreneurRideAlong", "r/EntrepreneurRideAlong"),
    ("indiehackers", "r/indiehackers"),
    ("SideProject", "r/SideProject"),
    ("microsaas", "r/microsaas"),
]

USER_AGENT = "vc-alpha-signal-finder/0.1 by /u/coflazo"


class RedditUnavailable(RuntimeError):
    """No credentials. Says what to do about it."""


def client():
    """A read-only PRAW client, or an error explaining exactly what is missing."""
    cid = os.environ.get("REDDIT_CLIENT_ID")
    secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and secret):
        raise RedditUnavailable(
            "Reddit needs a free OAuth app. Create one at reddit.com/prefs/apps, "
            "choose 'script', then set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET. "
            "There is no anonymous path: the JSON endpoints 403 and the RSS feeds "
            "come back empty."
        )
    try:
        import praw
    except ImportError as e:
        raise RedditUnavailable("praw is not installed. Run: uv sync --inexact --extra reddit") from e

    return praw.Reddit(
        client_id=cid, client_secret=secret,
        user_agent=os.environ.get("REDDIT_USER_AGENT", USER_AGENT),
        check_for_async=False,
    )


def _record(post, node: str) -> CandidateRecord:
    return CandidateRecord(
        source="reddit",
        source_url=f"https://reddit.com{post.permalink}",
        raw_text=f"{post.title}\n\n{getattr(post, 'selftext', '') or ''}".strip(),
        title=post.title,
        author=str(post.author) if post.author else None,
        node=node,
        posted_at=__import__("datetime").datetime.fromtimestamp(
            post.created_utc, __import__("datetime").timezone.utc
        ).isoformat(),
    )


class RedditCollector(Collector):
    source = "reddit"

    def __init__(self, conn: sqlite3.Connection | None = None, reddit=None,
                 per_node: int = 60):
        self.conn = conn
        self._reddit = reddit
        self.per_node = per_node

    @property
    def reddit(self):
        if self._reddit is None:
            self._reddit = client()
        return self._reddit

    def seeds(self):
        return [Neighbour(name, label) for name, label in DEFAULT_SUBREDDITS]

    def visit(self, node: str) -> Visit:
        """Recent posts from one subreddit.

        `.new()` rather than `.hot()`: a post that is already hot has been seen by
        everyone. The window this product targets is before that.
        """
        sub = self.reddit.subreddit(node)
        candidates, authors = [], set()
        for post in sub.new(limit=self.per_node):
            candidates.append(_record(post, node))
            if post.author:
                authors.add(str(post.author))

        # Neighbours come from the co-posting graph, computed in discover() against
        # authors who already scored well, not from every author seen here. Adding
        # all of them would expand into wherever Reddit's general population goes.
        return Visit(candidates=candidates, neighbours=[], exhausted=False)

    def discover(self, conn: sqlite3.Connection, limit: int = 10) -> list[Neighbour]:
        """Subreddits where authors who already scored well also post.

        The strong signal is not semantic similarity, it is people. Ranked by
        distinct good authors rather than post count, so one prolific poster cannot
        nominate forty subreddits.
        """
        rows = conn.execute(
            """SELECT a.node, COUNT(DISTINCT a.author) AS good_authors
               FROM author_activity a
               JOIN candidates c ON c.author = a.author AND c.source = 'reddit'
               WHERE a.source = 'reddit' AND c.is_startup = 1 AND c.confidence > 0.6
                 AND a.node NOT IN (SELECT node FROM nodes WHERE source = 'reddit')
               GROUP BY a.node ORDER BY good_authors DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [Neighbour(r["node"], f"r/{r['node']} ({r['good_authors']} good authors)")
                for r in rows]
