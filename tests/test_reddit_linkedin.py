"""Reddit and LinkedIn, tested against fakes since neither has credentials yet.

The LinkedIn tests matter more than usual: its failure mode is a banned account,
which is not recoverable by fixing code.
"""

import sqlite3
import types
from datetime import datetime, timezone

import pytest

from vc_alpha.collectors.linkedin import (
    DAILY_CAP, LinkedInCollector, LinkedInUnavailable, RateLimiter, SoftBlocked,
    _people_also_viewed, looks_blocked,
)
from vc_alpha.collectors.reddit import RedditCollector, RedditUnavailable, client
from vc_alpha.db import SCHEMA


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


# --- reddit -----------------------------------------------------------------


def test_missing_credentials_say_what_to_do(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    with pytest.raises(RedditUnavailable, match="prefs/apps"):
        client()


class FakePost:
    def __init__(self, i, author="ayse"):
        self.title = f"I built thing {i}"
        self.selftext = "details"
        self.permalink = f"/r/SaaS/comments/{i}/"
        self.author = author
        self.created_utc = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()


class FakeReddit:
    def subreddit(self, name):
        return types.SimpleNamespace(new=lambda limit: [FakePost(i) for i in range(3)])


def test_posts_become_candidates():
    v = RedditCollector(reddit=FakeReddit()).visit("SaaS")
    assert len(v.candidates) == 3
    assert v.candidates[0].source_url.startswith("https://reddit.com/r/SaaS")
    assert v.candidates[0].author == "ayse"
    assert v.candidates[0].posted_at


def test_a_subreddit_does_not_expand_to_every_author_seen():
    """Expansion comes from the co-posting graph of authors who already scored
    well. Following everyone would reach wherever Reddit's population goes."""
    assert RedditCollector(reddit=FakeReddit()).visit("SaaS").neighbours == []


def test_discovery_ranks_by_distinct_good_authors(conn):
    """One prolific poster must not be able to nominate forty subreddits."""
    for i, (author, node) in enumerate([("a", "good"), ("b", "good"), ("c", "weak")]):
        conn.execute(
            """INSERT INTO candidates (id, source, source_url, raw_text, author,
               discovered_at, retention_until, is_startup, confidence)
               VALUES (?,?,?,?,?,?,?,1,0.9)""",
            (f"c{i}", "reddit", f"https://r/{i}", "t", author, "2026", "2027"),
        )
        conn.execute("INSERT INTO author_activity VALUES ('reddit',?,?,'2026')",
                     (author, node))
    conn.commit()
    found = RedditCollector(conn=conn, reddit=FakeReddit()).discover(conn)
    assert found and found[0].node == "good"


# --- linkedin ---------------------------------------------------------------


def test_refuses_to_run_in_ci(monkeypatch):
    """A datacenter IP is the fastest way to lose the account, so this is refused
    outright rather than left to configuration."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("LINKEDIN_SESSION_COOKIE", "x")
    from vc_alpha.collectors.linkedin import fetcher
    with pytest.raises(LinkedInUnavailable, match="CI"):
        fetcher()


def test_requires_a_session_cookie_rather_than_logging_in(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("RUNNER_OS", raising=False)
    monkeypatch.delenv("LINKEDIN_SESSION_COOKIE", raising=False)
    from vc_alpha.collectors.linkedin import fetcher
    with pytest.raises(LinkedInUnavailable, match="cookie"):
        fetcher()


def test_the_daily_cap_is_enforced_not_advised():
    """None of the three reference scrapers enforce a limit; they advise one in the
    README and leave it to the caller."""
    r = RateLimiter(cap=2)
    r.take(); r.last = 0
    r.take(); r.last = 0
    with pytest.raises(LinkedInUnavailable, match="daily cap"):
        r.take()


def test_the_default_cap_is_deliberately_small():
    assert DAILY_CAP <= 50, "a generous default quietly stops being a limit"


@pytest.mark.parametrize("html", [
    "<div>checkpoint/challenge</div>",
    "<p>We noticed unusual activity</p>",
    "<div class=authwall>",
])
def test_challenge_pages_are_recognised(html):
    assert looks_blocked(html)


def test_a_challenge_stops_the_run_rather_than_retrying(conn):
    """Retrying into a challenge is how an account dies."""
    fake = types.SimpleNamespace(
        fetch=lambda *a, **k: types.SimpleNamespace(html_content="please verify"))
    c = LinkedInCollector(conn=conn, fetch=fake, limiter=RateLimiter(cap=5))
    with pytest.raises(SoftBlocked):
        c.visit("someone")


def test_people_also_viewed_is_capped_and_deduplicated():
    html = "".join(f'<a href="/in/person{i}/">x</a>' for i in range(20)) * 2
    slugs = _people_also_viewed(html)
    assert len(slugs) <= 8 and len(set(slugs)) == len(slugs)


def test_seeds_come_from_entities_that_already_scored_well(conn):
    """A founder matched on Reddit is a far better start than a cold search."""
    from vc_alpha.entities import install
    install(conn)
    conn.execute(
        """INSERT INTO entities (id,kind,name,linkedin,first_seen,last_seen,score)
           VALUES ('1','person','Ayse','ayse-k','2026','2026',0.8)""")
    conn.commit()
    assert [n.node for n in LinkedInCollector(conn=conn).seeds()] == ["ayse-k"]
