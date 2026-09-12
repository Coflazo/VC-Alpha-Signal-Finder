"""GitHub, via the public search API.

Startups leave GitHub traces before they leave press traces. A young repo under a
brand-new organisation that is gaining stars fast is often a company two people are
building before they have announced anything.

Works unauthenticated at a low rate limit. If `gh auth token` is available it is used
automatically, which raises the limit substantially. No key needs to be configured.

Nodes:

    query:<github search>   a repository search
    org:<login>             that organisation's repositories

The expansion that matters is query to org. A promising repo points at the
organisation behind it, and an organisation's other repos say whether this is a
company or a weekend project.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import date, timedelta

import httpx

from vc_alpha.collectors.base import CandidateRecord, Collector, Neighbour, Visit

log = logging.getLogger(__name__)

API = "https://api.github.com"
TIMEOUT = httpx.Timeout(20.0)
UA = "vc-alpha-signal-finder/0.1 (+https://github.com/Coflazo/VC-Alpha-Signal-Finder)"

# Young repos with real traction. The date is filled in at visit time.
DEFAULT_QUERIES = [
    ("stars:>40 created:>{since}", "new repos gaining stars"),
    ("stars:>25 created:>{since} language:python", "new python repos"),
    ("stars:>25 created:>{since} language:typescript", "new typescript repos"),
    ("stars:>15 created:>{since} topic:ai-agent", "new ai-agent repos"),
]

REPO_AGE_DAYS = 120
PER_PAGE = 50


def _token() -> str | None:
    """Reuse the gh CLI's token if the user is already logged in. Never prompt."""
    try:
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() or None
    except Exception:
        return None


class GitHubCollector(Collector):
    source = "github"

    def __init__(self, client: httpx.Client | None = None, max_items: int = 50):
        headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
        if tok := _token():
            headers["Authorization"] = f"Bearer {tok}"
            log.debug("using gh CLI token for a higher rate limit")
        self._client = client or httpx.Client(
            timeout=TIMEOUT, headers=headers, follow_redirects=True
        )
        self.max_items = max_items

    def seeds(self):
        since = (date.today() - timedelta(days=REPO_AGE_DAYS)).isoformat()
        return [
            Neighbour(f"query:{q.format(since=since)}", label)
            for q, label in DEFAULT_QUERIES
        ]

    def _repo_record(self, r: dict, node: str) -> CandidateRecord | None:
        url = r.get("html_url")
        if not url:
            return None
        owner = (r.get("owner") or {}).get("login")
        text = "\n\n".join(
            filter(None, [
                r.get("full_name"),
                r.get("description"),
                " ".join(r.get("topics") or []),
                f"{r.get('stargazers_count', 0)} stars, created {r.get('created_at', '')[:10]}",
                r.get("homepage") or "",
            ])
        )
        return CandidateRecord(
            source=self.source,
            source_url=url,
            raw_text=text,
            title=r.get("full_name"),
            author=owner,
            node=node,
            posted_at=r.get("created_at"),
        )

    def visit(self, node: str) -> Visit:
        kind, _, value = node.partition(":")

        if kind == "query":
            r = self._client.get(
                f"{API}/search/repositories",
                params={"q": value, "sort": "stars", "order": "desc",
                        "per_page": min(self.max_items, PER_PAGE)},
            )
        elif kind == "org":
            r = self._client.get(
                f"{API}/orgs/{value}/repos",
                params={"sort": "created", "per_page": min(self.max_items, PER_PAGE)},
            )
        else:
            log.warning("unknown github node kind: %s", node)
            return Visit(exhausted=True)

        if r.status_code == 403:
            # Rate limited. Not an error worth retrying into; back off and move on.
            log.warning("github rate limited on %s", node)
            return Visit()
        r.raise_for_status()

        payload = r.json()
        repos = payload.get("items", payload) if isinstance(payload, dict) else payload

        candidates, orgs = [], set()
        for repo in repos:
            if rec := self._repo_record(repo, node):
                candidates.append(rec)
            owner = repo.get("owner") or {}
            # Only organisations, not personal accounts. A company usually has an org;
            # following every individual would pull in the whole of GitHub.
            if owner.get("type") == "Organization" and owner.get("login"):
                orgs.add(owner["login"])

        neighbours = (
            [Neighbour(f"org:{o}", o) for o in sorted(orgs)] if kind == "query" else []
        )
        return Visit(
            candidates=candidates,
            neighbours=neighbours,
            exhausted=kind == "org" and len(repos) < PER_PAGE,
        )
