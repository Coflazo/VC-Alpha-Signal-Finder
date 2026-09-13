"""Closing the loop from review clicks to the number the pipeline runs on.

The Review screen has always written `was_good`. Nothing read it. Meanwhile
calibrate.py asked the user to export a CSV and label it by hand — the same work,
done twice, with the half that was already happening thrown away.

The property worth pinning hardest is the refusal: a threshold fitted from twelve
clicks carries the authority of "measured" with the variance of a guess, and is
worse than the honest default it replaces.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from vc_alpha import calibrate, paths, score
from vc_alpha.app.main import app
from vc_alpha.db import SCHEMA, migrate


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    migrate(c)
    return c


def _label(conn, cid, similarity, good, *, match=None, model="mistral/mistral-embed"):
    """A reviewed candidate, as the Review screen leaves it."""
    triage = json.dumps({"thesis_match": match}) if match is not None else None
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until, similarity, embedding_model, triage_json, posted_at,
           reviewed, was_good)
           VALUES (?, 'hackernews', ?, 'building developer tooling', '2026-01-01',
                   '2099-01-01', ?, ?, ?, '2026-09-01', 1, ?)""",
        (cid, f"https://x/{cid}", similarity, model, triage, int(good)),
    )
    conn.commit()


def _separable(conn, n=60, boundary=0.50):
    """Labels a threshold can actually separate: good ones score above the line."""
    for i in range(n):
        sim = 0.20 + (i / n) * 0.60
        _label(conn, f"c{i}", sim, sim >= boundary, match=0.9 if sim >= boundary else 0.1)


# --- the refusal -------------------------------------------------------------


def test_fitting_is_refused_below_the_minimum(conn):
    """A number fitted from a handful of clicks is worse than an honest guess."""
    for i in range(10):
        _label(conn, f"c{i}", 0.5, i % 2 == 0)

    with pytest.raises(calibrate.NotEnoughLabels) as e:
        calibrate.fit(conn)
    assert "30 more" in str(e.value), "it should say how many more are needed"


def test_fitting_is_refused_when_nothing_was_marked_good(conn):
    """With no positives there is no signal to separate, only a count."""
    for i in range(50):
        _label(conn, f"c{i}", 0.4 + i / 200, False)

    with pytest.raises(calibrate.NotEnoughLabels):
        calibrate.fit(conn)


def test_defaults_are_used_until_something_is_fitted():
    cal = calibrate.load()
    assert not cal.fitted
    assert cal.threshold == calibrate.DEFAULT_THRESHOLD
    assert score.weights() == calibrate.DEFAULT_WEIGHTS


# --- fitting -----------------------------------------------------------------


def test_the_labels_come_from_the_review_screen(conn):
    """The whole point: the clicks were already being recorded."""
    _label(conn, "a", 0.7, True)
    _label(conn, "b", 0.2, False)
    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until, similarity) VALUES ('c','hackernews','https://x/c','t',
           '2026-01-01','2099-01-01',0.5)""")
    conn.commit()

    labels = calibrate.labels_from_db(conn)
    assert {r["id"] for r in labels} == {"a", "b"}, "unreviewed rows are not labels"


def test_a_separable_set_recovers_the_boundary(conn):
    _separable(conn, n=60, boundary=0.50)
    cal = calibrate.fit(conn, prefer="f1")

    assert cal.fitted
    assert cal.threshold == pytest.approx(0.50, abs=0.03)
    assert cal.precision > 0.9 and cal.recall > 0.9


def test_preferring_recall_sets_a_lower_bar_than_f1(conn):
    """Missing a real founder costs more than reading a dud, so this is default."""
    _separable(conn, n=60, boundary=0.50)
    by_f1 = calibrate.fit(conn, prefer="f1").threshold
    by_recall = calibrate.fit(conn, prefer="recall").threshold
    assert by_recall <= by_f1


def test_the_floor_sits_below_the_threshold(conn):
    """It is the safety net for a run where a whole source is junk, not a second bar."""
    _separable(conn)
    cal = calibrate.fit(conn)
    assert cal.floor < cal.threshold


def test_the_fitted_values_are_persisted_and_reloaded(conn):
    _separable(conn)
    fitted = calibrate.fit(conn)

    assert paths.calibration_file().is_file()
    assert calibrate.load().threshold == fitted.threshold
    assert calibrate.load().fitted


def test_the_pipeline_reads_the_fitted_weights(conn):
    """Fitting has to change what the product does, or it is a report."""
    _separable(conn)
    calibrate.fit(conn)
    assert score.weights() == calibrate.load().weights

    # And a score computed now uses them.
    w = calibrate.load().weights
    expected = w["similarity"] * 1.0 + w["thesis_match"] * 1.0 + w["recency"] * 0.5
    assert score.combine(1.0, 1.0, None) == pytest.approx(expected)


def test_weights_stay_on_the_simplex(conn):
    _separable(conn)
    w = calibrate.fit(conn).weights
    assert sum(w.values()) == pytest.approx(1.0, abs=0.01)
    assert all(v >= 0 for v in w.values())


# --- the embedding-model trap ------------------------------------------------


def test_a_threshold_is_ignored_under_a_different_embedding_model(conn):
    """Providers score on wildly different scales — measured, an unrelated sentence
    reaches 0.567 against a thesis under mistral-embed. Applying a threshold fitted
    on one model to vectors from another is silently the wrong bar."""
    _separable(conn)
    fitted = calibrate.fit(conn)
    assert fitted.embedding_model == "mistral/mistral-embed"

    same = calibrate.active(conn, embedding_model="mistral/mistral-embed")
    assert same.threshold == fitted.threshold

    other = calibrate.active(conn, embedding_model="cohere/embed-v4.0")
    assert other.threshold == calibrate.DEFAULT_THRESHOLD
    assert not other.fitted


def test_mixed_models_in_the_labels_record_no_model(conn):
    """If the labelled corpus was embedded by two providers, the fit cannot claim
    to belong to either."""
    _separable(conn, n=50)
    _label(conn, "other", 0.6, True, match=0.8, model="cohere/embed-v4.0")
    assert calibrate.fit(conn).embedding_model is None


# --- progress and the API ----------------------------------------------------


def test_progress_reports_how_far_along_the_labelling_is(conn):
    for i in range(12):
        _label(conn, f"c{i}", 0.5, i % 3 == 0)

    p = calibrate.progress(conn)
    assert p["labelled"] == 12
    assert p["positives"] == 4
    assert p["minimum"] == calibrate.MIN_LABELS
    assert not p["can_fit"]


def test_the_api_refuses_to_fit_too_early():
    client = TestClient(app)
    assert client.get("/api/calibration").json()["labelled"] == 0
    assert client.post("/api/calibration/fit").status_code == 400


def test_average_precision_rewards_good_ranking():
    perfect = [(0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)]
    inverted = [(0.9, 0), (0.8, 0), (0.2, 1), (0.1, 1)]
    assert calibrate.average_precision(perfect) == pytest.approx(1.0)
    assert calibrate.average_precision(inverted) < 0.6
    assert calibrate.average_precision([(0.5, 0)]) == 0.0
