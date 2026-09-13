"""Checks on the two pieces where a silent bug corrupts everything downstream:
thesis config loading and frontier expansion.
"""

import sqlite3

import pytest

from vc_alpha import frontier, theses
from vc_alpha.collectors.base import CandidateRecord, Neighbour, Visit
from vc_alpha.db import SCHEMA

# Every field Treeo asked for by name. If a rename drops one, this fails.
TREEO_REQUIRED = {
    "startup_name", "based_in", "website", "founded_in", "founders",
    "description", "fit", "raising_now", "raising_when", "geographic_focus",
}


def test_all_theses_load():
    loaded = theses.load_all()
    assert {t.id for t in loaded} == {"treeo", "revo", "e2vc", "212", "earlybird"}
    for t in loaded:
        assert t.prose.strip(), f"{t.id} has no prose to embed"
        assert t.report_fields, f"{t.id} has no report fields"


def test_treeo_report_matches_what_the_fund_asked_for():
    treeo = next(t for t in theses.load_all() if t.id == "treeo")
    assert {f.key for f in treeo.report_fields} >= TREEO_REQUIRED
    raising_when = next(f for f in treeo.report_fields if f.key == "raising_when")
    assert not raising_when.required  # conditional on them not currently raising


def test_every_thesis_carries_the_common_fields():
    """Each fund adds its own questions, but the core report is the same everywhere."""
    common = {"startup_name", "website", "founders", "description", "fit", "raising_now"}
    for t in theses.load_all():
        assert {f.key for f in t.report_fields} >= common, t.id


def test_exclude_gate_is_case_insensitive():
    treeo = next(t for t in theses.load_all() if t.id == "treeo")
    assert treeo.excluded("We run a Dropshipping store")
    assert not treeo.excluded("We build AI infrastructure for banks")


# --- frontier ---------------------------------------------------------------


class FakeCollector:
    """Two-node graph: 'a' points at 'b', 'b' points nowhere."""

    source = "fake"

    def __init__(self, hits_for=()):
        self.hits_for = set(hits_for)
        self.visited = []

    def seeds(self):
        return [Neighbour("a", "A")]

    def visit(self, node):
        self.visited.append(node)
        return Visit(
            candidates=[CandidateRecord("fake", f"https://x/{node}/1", "text", node=node)],
            neighbours=[Neighbour("b")] if node == "a" else [],
        )


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def test_seeds_then_expands(conn):
    col = FakeCollector()
    stats = frontier.expand(conn, col, frontier.Budget(max_visits=10))
    assert "a" in col.visited
    assert stats["discovered"] == 1  # found 'b' via 'a'


def test_budget_caps_visits(conn):
    col = FakeCollector()
    frontier.expand(conn, col, frontier.Budget(max_visits=1))
    assert len(col.visited) == 1


def test_deactivated_node_is_not_revisited_or_readded(conn):
    col = FakeCollector()
    frontier.expand(conn, col, frontier.Budget(max_visits=10))
    frontier.deactivate(conn, "fake", "b")

    col2 = FakeCollector()
    frontier.expand(conn, col2, frontier.Budget(max_visits=10))
    assert "b" not in col2.visited, "a rejected node came back"


def test_barren_node_stops_expanding_once_there_is_evidence(conn):
    """A node that has been seen plenty and produced nothing should not seed more."""
    frontier.add_node(conn, "fake", "dud", source_kind="discovered")
    frontier.record_visit(conn, "fake", "dud", seen=100, hits=0, exhausted=False)
    row = conn.execute(
        "SELECT * FROM nodes WHERE source='fake' AND node='dud'"
    ).fetchone()
    assert not frontier.worth_expanding(row, frontier.Budget())


def test_new_node_gets_benefit_of_the_doubt(conn):
    """One hit in two posts is noise, not a 50% hit rate. Do not judge too early."""
    frontier.add_node(conn, "fake", "young", source_kind="discovered")
    frontier.record_visit(conn, "fake", "young", seen=2, hits=0, exhausted=False)
    row = conn.execute(
        "SELECT * FROM nodes WHERE source='fake' AND node='young'"
    ).fetchone()
    assert frontier.worth_expanding(row, frontier.Budget())


def test_a_failing_node_does_not_end_the_run(conn):
    class Exploding(FakeCollector):
        def visit(self, node):
            if node == "a":
                raise RuntimeError("network died")
            return super().visit(node)

    frontier.add_node(conn, "fake", "a", source_kind="seed")
    frontier.add_node(conn, "fake", "c", source_kind="seed")
    col = Exploding()
    stats = frontier.expand(conn, col, frontier.Budget(max_visits=10))
    assert stats["visited"] == 1  # 'c' still got visited


def test_suggestions_rank_by_measured_hit_rate(conn):
    for node, seen, hits in [("good", 50, 20), ("weak", 50, 1)]:
        frontier.add_node(conn, "fake", node, source_kind="discovered")
        frontier.record_visit(conn, "fake", node, seen, hits, False)
    ranked = frontier.suggestions(conn, "fake")
    assert [r["node"] for r in ranked] == ["good", "weak"]


def test_numeric_fund_names_load_as_strings():
    """A fund called 212 arrives from YAML as an integer, which breaks anything that
    joins or formats names. Found when the CLI tried to list the funds."""
    for t in theses.load_all():
        assert isinstance(t.id, str), f"{t.id!r} is not a string"
        assert isinstance(t.name, str), f"{t.name!r} is not a string"
    assert ", ".join(t.name for t in theses.load_all())
