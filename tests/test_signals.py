"""Multi-action scoring.

The point of splitting one relevance score into several is that funds disagree
about what a good lead is, and should be able to express that by editing numbers
rather than by retraining anything. These tests pin that property.
"""

import pytest

from vc_alpha import theses
from vc_alpha.signals import SIGNALS, combine, default_weights, explain, schema

STRONG = {"is_building": 0.9, "thesis_fit": 0.8, "founder_quality": 0.8,
          "timing": 0.8, "reachable": 1.0, "too_late": 0.0}
IDEA = {"is_building": 0.2, "thesis_fit": 0.7, "founder_quality": 0.9,
        "timing": 0.3, "reachable": 0.8, "too_late": 0.0}


def test_score_is_bounded():
    assert 0.0 <= combine(STRONG) <= 1.0
    assert combine({k: 0.0 for k in default_weights()}) == 0.0


def test_a_negative_signal_subtracts():
    """Already funded past the stage is a wrong answer, not a weak match."""
    assert combine({**STRONG, "too_late": 0.9}) < combine(STRONG)


def test_score_never_goes_below_zero():
    assert combine({k: 0.0 for k in default_weights()} | {"too_late": 1.0}) == 0.0


def test_weights_change_ranking_without_retraining():
    """The whole argument for multi-action scoring."""
    traction_led = {"is_building": 0.6, "thesis_fit": 0.2, "founder_quality": 0.1,
                    "timing": 0.05, "reachable": 0.05, "too_late": 0.2}
    founder_led = {"is_building": 0.1, "thesis_fit": 0.2, "founder_quality": 0.6,
                   "timing": 0.05, "reachable": 0.05, "too_late": 0.2}
    assert combine(STRONG, traction_led) > combine(IDEA, traction_led)
    assert combine(IDEA, founder_led) > combine(IDEA, traction_led)


def test_zeroing_a_signal_does_not_inflate_the_rest():
    """Normalising by positive weights only, so dropping a signal cannot raise
    every remaining score."""
    w = default_weights() | {"timing": 0.0}
    assert combine(STRONG, w) <= 1.0


def test_real_fund_configs_disagree_as_their_theses_say_they_should():
    funds = {t.id: t for t in theses.load_all()}
    # 212 explicitly demands demonstrated traction; e2vc invests pre-product.
    gap_212 = combine(STRONG, funds["212"].weights) - combine(IDEA, funds["212"].weights)
    gap_e2vc = combine(STRONG, funds["e2vc"].weights) - combine(IDEA, funds["e2vc"].weights)
    assert gap_212 > gap_e2vc, "the traction-led fund should penalise idea stage harder"


def test_every_fund_has_weights_for_every_signal():
    for t in theses.load_all():
        missing = {s.key for s in SIGNALS} - set(t.weights)
        assert not missing, f"{t.id} is missing weights for {missing}"


def test_explain_accounts_for_the_whole_score():
    parts = explain(STRONG)
    assert {p["key"] for p in parts} == {s.key for s in SIGNALS}
    assert parts == sorted(parts, key=lambda p: abs(p["contribution"]), reverse=True)


def test_schema_demands_a_quote_for_every_signal():
    """A signal an analyst cannot check gets redone, which defeats the product."""
    props = schema()["properties"]
    for s in SIGNALS:
        assert "quote" in props[s.key]["required"], f"{s.key} may be claimed without evidence"
