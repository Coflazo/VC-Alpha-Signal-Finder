"""Entity-level scoring, warm paths and inbound."""

import json
import sqlite3
import textwrap
from pathlib import Path

import pytest

from vc_alpha import theses
from vc_alpha.collectors.inbound import InboundCollector, read_csv, read_eml, trim
from vc_alpha.db import SCHEMA
from vc_alpha.entities import Mention, install, resolve
from vc_alpha.founders import aggregate, corroboration, score_entity
from vc_alpha.warmpath import Path as WarmPath, paths_to, reachability

NOW = "2026-09-12T00:00:00+00:00"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    install(c)
    return c


@pytest.fixture
def treeo():
    return next(t for t in theses.load_all() if t.id == "treeo")


def add(conn, cid, source, *, author=None, node=None, signals=None, quote="built it"):
    triage = None
    if signals:
        triage = json.dumps({k: {"score": v, "quote": quote} for k, v in signals.items()})
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, author, node,
           discovered_at, retention_until, triage_json)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (cid, source, f"https://x/{cid}", "text", author, node, NOW, NOW, triage),
    )
    conn.commit()


# --- aggregation ------------------------------------------------------------


def test_best_evidence_wins_rather_than_the_average(conn):
    """One post clearly showing a founder shipped before is not weakened by three
    that happen not to mention it. Absence of evidence is not evidence of absence."""
    add(conn, "a", "hackernews", signals={"founder_quality": 0.9})
    add(conn, "b", "hackernews", signals={"founder_quality": 0.1})
    e = resolve(conn, Mention("Acme", domain="acme.io", candidate_id="a"), now=NOW)
    resolve(conn, Mention("Acme", domain="acme.io", candidate_id="b"), now=NOW)

    from vc_alpha.entities import evidence
    scores, _ = aggregate(evidence(conn, e))
    assert scores["founder_quality"] == 0.9


def test_every_quote_carries_its_source(conn, treeo):
    """aggregate() reports every signal including the ones that scored zero, because
    knowing a signal was absent is useful. score_entity() is what filters to
    checkable evidence, so that is where the contract is asserted."""
    add(conn, "a", "hackernews", signals={"thesis_fit": 0.8}, quote="I built Acme")
    e = resolve(conn, Mention("Acme", domain="acme.io", candidate_id="a"), now=NOW)

    support = score_entity(conn, e, treeo)["support"]
    assert support, "a quoted signal did not reach the report"
    assert all(s["url"] and s["quote"] for s in support)


def test_unquoted_signals_do_not_reach_the_report(conn, treeo):
    """A claim an analyst cannot check gets the work redone, which defeats the point."""
    add(conn, "a", "hackernews", signals={"thesis_fit": 0.9}, quote="")
    e = resolve(conn, Mention("Acme", domain="acme.io", candidate_id="a"), now=NOW)
    assert score_entity(conn, e, treeo)["support"] == []


# --- corroboration ----------------------------------------------------------


def test_more_sources_raises_the_score(conn, treeo):
    sig = {"is_building": 0.8, "thesis_fit": 0.8, "founder_quality": 0.8}
    add(conn, "one", "hackernews", signals=sig)
    solo = resolve(conn, Mention("Solo", domain="solo.io", candidate_id="one"), now=NOW)

    add(conn, "x", "hackernews", signals=sig)
    add(conn, "y", "substack", signals=sig)
    multi = resolve(conn, Mention("Multi", domain="multi.io", candidate_id="x",
                                  source="hackernews"), now=NOW)
    resolve(conn, Mention("Multi", domain="multi.io", candidate_id="y",
                          source="substack"), now=NOW)

    assert score_entity(conn, multi, treeo)["score"] > score_entity(conn, solo, treeo)["score"]


def test_corroboration_saturates():
    """Otherwise a prolific poster outranks a good company."""
    assert corroboration(2) > corroboration(1)
    assert corroboration(20) <= 1.25


def test_score_stays_bounded(conn, treeo):
    perfect = {s: 1.0 for s in
               ("is_building", "thesis_fit", "founder_quality", "timing", "reachable")}
    for i, src in enumerate(["hackernews", "substack", "github", "reddit"]):
        add(conn, f"p{i}", src, signals=perfect)
        resolve(conn, Mention("Big", domain="big.io", candidate_id=f"p{i}", source=src), now=NOW)
    e = resolve(conn, Mention("Big", domain="big.io"), now=NOW)
    assert score_entity(conn, e, treeo)["score"] <= 1.0


def test_an_untriaged_entity_scores_nothing(conn, treeo):
    add(conn, "raw", "hackernews")
    e = resolve(conn, Mention("Raw", domain="raw.io", candidate_id="raw"), now=NOW)
    assert score_entity(conn, e, treeo) is None


# --- warm paths -------------------------------------------------------------


def test_a_shared_group_produces_a_path(conn):
    add(conn, "t", "whatsapp", author="Target", node="Founders TR")
    add(conn, "k", "whatsapp", author="Ayse", node="Founders TR")
    e = resolve(conn, Mention("Target", kind="person", handle="whatsapp:target",
                              candidate_id="t", source="whatsapp"), now=NOW)
    paths = paths_to(conn, e)
    assert any(p.person == "Ayse" and p.kind == "whatsapp_group" for p in paths)


def test_a_private_group_outranks_a_public_forum(conn):
    """Membership of a private group implies someone vouched for someone."""
    assert WarmPath("whatsapp_group", "g", "a", 1.0).strength > \
           WarmPath("same_subreddit", "r", "b", 0.35).strength


def test_reachability_follows_the_strongest_path_not_the_count():
    """One person in a private group beats twenty strangers in a large forum."""
    many = [WarmPath("same_subreddit", "saas", f"p{i}", 0.35) for i in range(20)]
    one = [WarmPath("whatsapp_group", "g", "ayse", 1.0)]
    assert reachability(one) > reachability(many)


def test_paths_describe_observations_not_relationships(conn):
    """"is in your group" is a fact. "knows" would be a claim with no basis."""
    text = WarmPath("whatsapp_group", "Founders TR", "Ayse", 1.0).describe()
    assert "knows" not in text.lower()


def test_no_paths_without_an_author(conn):
    add(conn, "anon", "substack", node="pub")
    e = resolve(conn, Mention("Anon", domain="anon.io", candidate_id="anon"), now=NOW)
    assert paths_to(conn, e) == []


# --- inbound ----------------------------------------------------------------


EML = textwrap.dedent("""\
    From: Ayse Kaya <ayse@acme.io>
    Subject: Acme - raising pre-seed
    Content-Type: text/plain

    I built Acme after hitting this problem at my last job.

    -----Original Message-----
    quoted noise that would drown the pitch
    """)


def test_quoted_history_is_stripped():
    assert "quoted noise" not in trim(EML)
    assert "I built Acme" in trim(EML)


def test_eml_becomes_a_candidate(tmp_path: Path):
    (tmp_path / "pitch.eml").write_text(EML, encoding="utf-8")
    rec = read_eml(tmp_path / "pitch.eml")
    assert rec.source == "inbound"
    assert "Acme" in rec.title
    assert "ayse@acme.io" in rec.author


def test_the_same_email_twice_is_one_lead(tmp_path: Path):
    """The file name is the identity, so re-dropping an export does not duplicate."""
    (tmp_path / "pitch.eml").write_text(EML, encoding="utf-8")
    assert read_eml(tmp_path / "pitch.eml").id == read_eml(tmp_path / "pitch.eml").id


def test_form_exports_match_columns_loosely(tmp_path: Path):
    """Every fund names its form columns differently."""
    (tmp_path / "a.csv").write_text(
        "Startup Name,What are you building,Website\nBeta,Agent infra,https://b.dev\n",
        encoding="utf-8")
    rows = read_csv(tmp_path / "a.csv")
    assert rows and rows[0].title == "Beta" and "Agent infra" in rows[0].raw_text


def test_inbound_never_branches(tmp_path: Path):
    (tmp_path / "pitch.eml").write_text(EML, encoding="utf-8")
    assert InboundCollector(tmp_path).visit(".").neighbours == []
