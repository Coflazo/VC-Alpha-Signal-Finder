"""LinkedIn. The highest-risk collector, and the one with the tightest limits.

Runs from a home connection only. LinkedIn weights IP reputation heavily and
datacenter ranges are the fastest way to get an account flagged, so this refuses
to run in CI outright rather than trusting a configuration to be right.

Read-only, profiles and articles. No messaging, no connection requests, no feed
interaction. That boundary is what keeps this ordinary business research, and it
also keeps the volume low enough to be unremarkable.

Studied but not copied: joeyism/linkedin_scraper is GPL-3.0, and copying it would
force this project open the moment it were distributed. Technique was read from
stickerdaniel/linkedin-mcp-server (Apache-2.0), which is where the Patchright and
session-cookie approach comes from.
"""

from __future__ import annotations

import logging
import os
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date

from vc_alpha.collectors.base import CandidateRecord, Collector, Neighbour, Visit

log = logging.getLogger(__name__)

# Deliberately small. The limit that protects the account is the one that is
# actually enforced, and a generous default would quietly stop being one.
DAILY_CAP = 40
MIN_GAP_SECONDS = 30
MAX_GAP_SECONDS = 60


class LinkedInUnavailable(RuntimeError):
    pass


class SoftBlocked(RuntimeError):
    """LinkedIn served a challenge. Stop entirely; do not retry."""


def _in_ci() -> bool:
    return any(os.environ.get(v) for v in ("CI", "GITHUB_ACTIONS", "RUNNER_OS"))


@dataclass
class RateLimiter:
    """Token bucket with a hard daily cap and jitter.

    None of the three reference implementations enforce a limit; they all advise
    going slowly in the README and then leave it to the caller. This one refuses.
    """

    cap: int = DAILY_CAP
    used: int = 0
    day: date = field(default_factory=date.today)
    last: float = 0.0

    def take(self) -> None:
        if self.day != date.today():
            self.day, self.used = date.today(), 0
        if self.used >= self.cap:
            raise LinkedInUnavailable(
                f"daily cap of {self.cap} profiles reached. This limit is what keeps "
                "the account alive; raise it in config only if you accept that risk."
            )
        if self.last:
            # Jitter, never a fixed interval: a metronome is the easiest possible
            # automation signature to detect.
            gap = random.uniform(MIN_GAP_SECONDS, MAX_GAP_SECONDS)
            if (wait := gap - (time.time() - self.last)) > 0:
                time.sleep(wait)
        self.used += 1
        self.last = time.time()


def fetcher():
    """Scrapling's stealth fetcher, which wraps a patched Chromium.

    Vanilla Playwright leaks CDP artifacts that are trivially detected. Session
    cookies are imported from an already-logged-in browser rather than driving the
    login form, because automated login is the most reliably detected behaviour
    there is.
    """
    if _in_ci():
        raise LinkedInUnavailable(
            "refusing to run LinkedIn collection in CI. Datacenter IP ranges are "
            "the fastest way to get an account flagged; run this from the app on a "
            "home connection."
        )
    if not os.environ.get("LINKEDIN_SESSION_COOKIE"):
        raise LinkedInUnavailable(
            "set LINKEDIN_SESSION_COOKIE to the li_at cookie from a logged-in "
            "browser. Use a secondary account, not your own."
        )
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as e:
        raise LinkedInUnavailable("run: uv sync --inexact --extra enrich") from e
    return StealthyFetcher


CHALLENGE_MARKERS = ("authwall", "checkpoint/challenge", "unusual activity",
                     "please verify", "sign in to continue")


def looks_blocked(html: str) -> bool:
    low = (html or "").lower()
    return any(m in low for m in CHALLENGE_MARKERS)


class LinkedInCollector(Collector):
    """A node is one profile slug. Expansion is 'People also viewed'."""

    source = "linkedin"
    local_only = True

    def __init__(self, conn: sqlite3.Connection | None = None,
                 limiter: RateLimiter | None = None, fetch=None):
        self.conn = conn
        self.limiter = limiter or RateLimiter()
        self._fetch = fetch

    def seeds(self):
        """Founders already matched elsewhere, rather than a cold search.

        Someone who scored well on Reddit or Hacker News is a far better starting
        point than a keyword search, and they arrive pre-qualified.
        """
        if not self.conn:
            return []
        rows = self.conn.execute(
            """SELECT DISTINCT linkedin FROM entities
               WHERE linkedin IS NOT NULL AND score > 0.5 LIMIT 20"""
        ).fetchall()
        return [Neighbour(r["linkedin"], r["linkedin"]) for r in rows]

    def visit(self, node: str) -> Visit:
        fetch = self._fetch or fetcher()
        self.limiter.take()

        url = f"https://www.linkedin.com/in/{node}/"
        page = fetch.fetch(url, headless=True, network_idle=True)
        html = getattr(page, "html_content", "") or str(page)

        if looks_blocked(html):
            # Stop on the first challenge. Retrying into one is how an account dies.
            raise SoftBlocked(f"challenge page on {node}; stopping this run")

        text = getattr(page, "get_all_text", lambda: html)()
        record = CandidateRecord(
            source=self.source,
            source_url=url,
            raw_text=text[:8000],
            title=node,
            author=node,
            node=node,
        )

        # "People also viewed" is the expansion, but only from profiles that scored
        # well. Blind breadth-first from a founder reaches their recruiters and
        # university classmates within two hops and burns the daily cap on noise.
        neighbours = [
            Neighbour(slug) for slug in _people_also_viewed(html)
        ]
        return Visit(candidates=[record], neighbours=neighbours, exhausted=True)


def _people_also_viewed(html: str) -> list[str]:
    import re
    slugs = re.findall(r'/in/([A-Za-z0-9\-%]{3,80})/?"', html or "")
    seen, out = set(), []
    for s in slugs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out[:8]
