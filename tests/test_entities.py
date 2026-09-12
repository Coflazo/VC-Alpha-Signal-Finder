"""Entity resolution.

The governing rule: a wrong merge is far worse than a duplicate. A merged pair
silently corrupts a dossier and a partner acts on it; a duplicate is untidy and
obvious. The refusal-to-merge cases below matter more than the merge cases.
"""

import sqlite3

import pytest

from vc_alpha.db import SCHEMA
from vc_alpha.entities import (
    Mention, evidence, handle_from, install, normalise_domain, normalise_name, resolve,
)

NOW = "2026-09-12T00:00:00+00:00"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    install(c)
    return c


def add_candidate(conn, cid, text="text"):
    conn.execute(
        """INSERT OR IGNORE INTO candidates (id, source, source_url, raw_text,
           discovered_at, retention_until) VALUES (?,?,?,?,?,?)""",
        (cid, "hackernews", f"https://x/{cid}", text, NOW, NOW),
    )
    conn.commit()


# --- normalisation ----------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://news.ycombinator.com/item?id=1",
    "https://foo.substack.com/p/bar",
    "https://www.reddit.com/r/saas/x",
])
def test_aggregator_urls_are_not_company_domains(url):
    """Otherwise every HN post would merge into one giant 'company'."""
    assert normalise_domain(url) is None


def test_real_domains_survive_and_drop_www():
    assert normalise_domain("https://www.acme.io/about") == "acme.io"


def test_legal_suffixes_do_not_block_a_match():
    assert normalise_name("Acme, Inc.") == normalise_name("acme")


def test_linkedin_person_and_company_paths_both_parse():
    assert handle_from("https://www.linkedin.com/in/ayse-k") == ("linkedin", "ayse-k")
    assert handle_from("https://linkedin.com/company/acme") == ("linkedin", "acme")


# --- merging ----------------------------------------------------------------


def test_same_domain_across_two_sources_becomes_one_entity(conn):
    """The whole point: one founder seen in three places is one dossier."""
    add_candidate(conn, "hn1")
    add_candidate(conn, "sub1")
    a = resolve(conn, Mention("Acme", domain="acme.io", candidate_id="hn1",
                              source="hackernews"), now=NOW)
    b = resolve(conn, Mention("Acme Inc", domain="acme.io", candidate_id="sub1",
                              source="substack"), now=NOW)
    assert a == b
    row = conn.execute("SELECT * FROM entities WHERE id = ?", (a,)).fetchone()
    assert row["mentions"] == 2
    assert set(row["sources"].split(",")) == {"hackernews", "substack"}


def test_github_org_merges_with_domain_sighting(conn):
    add_candidate(conn, "g1"); add_candidate(conn, "g2")
    a = resolve(conn, Mention("Acme", domain="acme.io", github="acme",
                              candidate_id="g1"), now=NOW)
    b = resolve(conn, Mention("Acme", github="acme", candidate_id="g2"), now=NOW)
    assert a == b


def test_identifiers_accumulate_across_sightings(conn):
    """A later sighting can supply an identifier the first one lacked."""
    add_candidate(conn, "c1"); add_candidate(conn, "c2")
    e = resolve(conn, Mention("Acme", domain="acme.io", candidate_id="c1"), now=NOW)
    resolve(conn, Mention("Acme", domain="acme.io", github="acme", candidate_id="c2"), now=NOW)
    assert conn.execute("SELECT github FROM entities WHERE id=?", (e,)).fetchone()[0] == "acme"


# --- refusing to merge ------------------------------------------------------


def test_different_domains_never_merge_however_similar_the_name(conn):
    """Acme Security and Acme Analytics are different companies."""
    a = resolve(conn, Mention("Acme", domain="acme-security.io"), now=NOW)
    b = resolve(conn, Mention("Acme", domain="acme-analytics.com"), now=NOW)
    assert a != b


def test_a_person_never_merges_into_a_company(conn):
    a = resolve(conn, Mention("Acme", kind="person"), now=NOW)
    b = resolve(conn, Mention("Acme", kind="company"), now=NOW)
    assert a != b


def test_a_name_only_match_is_merged_but_flagged_for_review(conn):
    """Names collide. Merging keeps the dossier whole; the flag lets a human split
    it. Guessing silently is the one thing that must not happen."""
    a = resolve(conn, Mention("Ayse Kaya", kind="person"), now=NOW)
    b = resolve(conn, Mention("Ayse Kaya", kind="person"), now=NOW)
    assert a == b
    assert conn.execute("SELECT needs_review FROM entities WHERE id=?", (a,)).fetchone()[0] == 1


def test_a_confirmed_match_is_not_flagged(conn):
    a = resolve(conn, Mention("Acme", domain="acme.io"), now=NOW)
    resolve(conn, Mention("Acme", domain="acme.io"), now=NOW)
    assert conn.execute("SELECT needs_review FROM entities WHERE id=?", (a,)).fetchone()[0] == 0


# --- evidence ---------------------------------------------------------------


def test_evidence_returns_every_supporting_candidate(conn):
    add_candidate(conn, "e1"); add_candidate(conn, "e2")
    e = resolve(conn, Mention("Acme", domain="acme.io", candidate_id="e1"), now=NOW)
    resolve(conn, Mention("Acme", domain="acme.io", candidate_id="e2"), now=NOW)
    assert {r["id"] for r in evidence(conn, e)} == {"e1", "e2"}


def test_re_resolving_the_same_mention_does_not_double_count(conn):
    add_candidate(conn, "r1")
    e = resolve(conn, Mention("Acme", domain="acme.io", candidate_id="r1"), now=NOW)
    resolve(conn, Mention("Acme", domain="acme.io", candidate_id="r1"), now=NOW)
    assert conn.execute("SELECT mentions FROM entities WHERE id=?", (e,)).fetchone()[0] == 1


# --- found by running extraction over a real corpus --------------------------


@pytest.mark.parametrize("url", [
    "https://apps.apple.com/app/id123",
    "https://theverge.com/2026/some-article",
    "https://chromewebstore.google.com/detail/x",
    "https://myproject.vercel.app",
])
def test_stores_press_and_hosting_are_not_companies(url):
    """These were confidently promoted to companies on a real run. An app store
    listing is where a product is distributed, not the company building it."""
    assert normalise_domain(url) is None


def test_a_platform_username_is_a_hard_identifier(conn):
    """Two posts by the same Hacker News account are the same person. Before this,
    they merged on name alone and were flagged for review, which buried the
    genuinely ambiguous cases the flag exists for."""
    add_candidate(conn, "p1"); add_candidate(conn, "p2")
    a = resolve(conn, Mention("patio11", kind="person", handle="hackernews:patio11",
                              candidate_id="p1", source="hackernews"), now=NOW)
    b = resolve(conn, Mention("patio11", kind="person", handle="hackernews:patio11",
                              candidate_id="p2", source="hackernews"), now=NOW)
    assert a == b
    assert conn.execute("SELECT needs_review FROM entities WHERE id=?", (a,)).fetchone()[0] == 0


def test_the_same_name_on_two_platforms_does_not_merge(conn):
    """Handles are unique per platform, not across them."""
    a = resolve(conn, Mention("alex", kind="person", handle="hackernews:alex"), now=NOW)
    b = resolve(conn, Mention("alex", kind="person", handle="reddit:alex"), now=NOW)
    assert a != b


def test_a_later_identifier_clears_the_review_flag(conn):
    """A name-only match that is later confirmed by a hard identifier is no longer
    a guess. Leaving the flag set forever trains people to ignore it."""
    a = resolve(conn, Mention("Acme", kind="company"), now=NOW)
    # The flag is set by a *match*, not by a first sighting.
    resolve(conn, Mention("Acme", kind="company"), now=NOW)
    assert conn.execute("SELECT needs_review FROM entities WHERE id=?", (a,)).fetchone()[0] == 1

    resolve(conn, Mention("Acme", kind="company", domain="acme.io"), now=NOW)
    assert conn.execute("SELECT needs_review FROM entities WHERE id=?", (a,)).fetchone()[0] == 0
