"""Quantitative models, checked against closed forms and simulation.

A model that has not been checked against something external is a plausible-looking
function. Each of these is verified against either an analytic result or Monte
Carlo, because the whole value of putting mathematics here is that it is right.
"""

import math
import random
import statistics

import pytest

from vc_alpha.quant.auction import (
    CurseModel, SOURCE_AUDIENCE, break_even_audience, exclusivity_edge,
    expected_max_normal,
)
from vc_alpha.quant.information import (
    DecisionEconomics, calibrate_to_posterior, evsi_gaussian, review_priority,
)
from vc_alpha.quant.tails import (
    QualityCurve, expected_fund_returners, hill_estimator, moments_exist,
    optimal_portfolio_size, prob_fund_returner, value_of_screening,
)

# --- extreme value -----------------------------------------------------------


def test_expected_max_matches_closed_forms():
    """E[max of 1] = 0 and E[max of 2] = 1/√π are exact."""
    assert expected_max_normal(1) == 0.0
    assert expected_max_normal(2) == pytest.approx(1 / math.sqrt(math.pi), abs=1e-9)


@pytest.mark.parametrize("n", [3, 5, 10, 25, 100, 200])
def test_expected_max_matches_monte_carlo(n):
    """The asymptotic √(2 ln n) expansion was rejected for this: it errs by up to
    0.25 at small n, which is exactly the range every audience here falls in."""
    random.seed(11 + n)
    mc = statistics.fmean(
        max(random.gauss(0, 1) for _ in range(n)) for _ in range(20_000)
    )
    assert expected_max_normal(n) == pytest.approx(mc, abs=0.02)


def test_expected_max_is_increasing_in_n():
    vals = [expected_max_normal(n) for n in (2, 5, 20, 100, 500)]
    assert vals == sorted(vals)


# --- winner's curse ----------------------------------------------------------


def test_curse_grows_with_the_number_of_competitors():
    m = CurseModel()
    assert m.penalty(3) < m.penalty(50) < m.penalty(500)


def test_a_private_signal_beats_an_equally_scored_public_one():
    """The arithmetic that justifies reading private communities at all."""
    m = CurseModel()
    assert m.adjust(0.70, "whatsapp") > m.adjust(0.70, "hackernews")


def test_the_edge_is_material_not_cosmetic():
    """If the correction were 0.01 it would not be worth modelling.

    This asserted > 0.15 before correlation was modelled. Giving public sources
    credit for their rivals forming similar views from identical words legitimately
    shrank the edge to roughly 0.10, which is still a tenth of the score range and
    still decisive between two otherwise equal candidates.
    """
    edge = exclusivity_edge(CurseModel(), "whatsapp", "hackernews")
    assert edge > 0.08, "a public lead must score materially higher to compete"


def test_adjustment_never_goes_negative():
    assert CurseModel().adjust(0.01, "hackernews") >= 0.0


def test_no_competition_means_no_curse():
    """With a single bidder there is nothing to overpay against."""
    assert CurseModel().penalty(1) == 0.0


def test_zero_noise_means_no_curse():
    """The curse is entirely a consequence of signal error."""
    assert CurseModel(sigma_e=0.0).penalty(200) == 0.0


def test_break_even_audience_inverts_the_penalty():
    m = CurseModel()
    n = break_even_audience(m, m.penalty(25))
    assert abs(n - 25) <= 2


def test_source_audiences_are_ordered_sensibly():
    a = SOURCE_AUDIENCE
    assert a["whatsapp"] < a["inbound"] < a["linkedin"] < a["hackernews"]


# --- value of information ----------------------------------------------------


def test_evpi_peaks_exactly_at_the_decision_threshold():
    """The central result: information is worth most where the decision is closest.
    Reviewing something you are already sure about teaches you nothing."""
    econ = DecisionEconomics(reward=30, loss=1)
    tau = econ.threshold
    at_tau = econ.evpi(tau)
    assert at_tau > econ.evpi(tau / 4)
    assert at_tau > econ.evpi(min(1.0, tau * 8))
    assert econ.evpi(0.0) == 0.0
    assert econ.evpi(1.0) == pytest.approx(0.0)


def test_threshold_follows_the_payoff_asymmetry():
    """A big reward against a small loss means pursuing on thin evidence."""
    assert DecisionEconomics(reward=30, loss=1).threshold < \
           DecisionEconomics(reward=3, loss=1).threshold


def test_evsi_is_bounded_by_evpi():
    """An imperfect review cannot be worth more than a perfect one."""
    econ = DecisionEconomics()
    for p in (0.01, 0.03, 0.1, 0.5):
        assert evsi_gaussian(p, econ, d_prime=1.5) <= econ.evpi(p) + 1e-9


def test_evsi_rises_with_reviewer_skill():
    econ = DecisionEconomics()
    p = econ.threshold
    assert evsi_gaussian(p, econ, 0.3) < evsi_gaussian(p, econ, 1.5) < evsi_gaussian(p, econ, 4.0)


def test_a_certain_candidate_is_not_worth_reviewing():
    econ = DecisionEconomics()
    assert evsi_gaussian(0.9999, econ, 1.5) == pytest.approx(0.0, abs=1e-6)


def test_the_queue_order_is_not_the_score_order():
    """The counterintuitive consequence, and the reason the review tab changes:
    a middling candidate can be worth more of an analyst's time than a top one."""
    high = calibrate_to_posterior(0.90)
    mid = calibrate_to_posterior(0.70)
    assert high > mid                                   # still ranks higher
    assert review_priority(mid) > review_priority(high)  # but is worth reviewing first


def test_calibration_respects_the_base_rate():
    """A model score is a ranking statistic, not a probability. At a 2% prior even
    a strong score must leave the posterior well under a half."""
    assert calibrate_to_posterior(0.9, base_rate=0.02) < 0.5
    assert calibrate_to_posterior(0.5, base_rate=0.02) < 0.1
    assert calibrate_to_posterior(0.9) > calibrate_to_posterior(0.5)


# --- tails -------------------------------------------------------------------


@pytest.mark.parametrize("alpha", [1.5, 2.0, 2.5])
def test_hill_recovers_a_known_tail_index(alpha):
    """Sampled from an exact Pareto, so the true α is known."""
    random.seed(int(alpha * 100))
    xs = [(1 - random.random()) ** (-1 / alpha) for _ in range(20_000)]
    assert hill_estimator(xs, k=2000) == pytest.approx(alpha, rel=0.12)


def test_moments_that_do_not_exist_are_reported_as_such():
    """The point most mean-variance thinking misses about venture returns."""
    assert moments_exist(1.8)["variance"] is False
    assert moments_exist(1.8)["sharpe_is_defined"] is False
    assert moments_exist(0.9)["mean"] is False
    assert moments_exist(3.0)["variance"] is True


def test_quality_curve_is_bounded_at_the_top():
    """The first version was unbounded as rank → 0 and gave the best candidate a
    100% hit rate."""
    c = QualityCurve(p_top=0.10, decay=0.35)
    assert c.hit_rate_at_rank(1) == pytest.approx(0.10)
    assert all(c.hit_rate_at_rank(r) <= 1.0 for r in (1, 2, 10, 1000))


def test_quality_declines_with_rank():
    c = QualityCurve()
    assert c.hit_rate_at_rank(1) > c.hit_rate_at_rank(10) > c.hit_rate_at_rank(500)


def test_a_useless_ranking_is_expressible():
    """decay = 0 is the null hypothesis: selection adds nothing."""
    flat = QualityCurve(p_top=0.05, decay=0.0)
    assert flat.hit_rate_at_rank(1) == flat.hit_rate_at_rank(900)


def test_the_sign_of_the_exponent_decides_concentration():
    """Expected fund-returners go as p̄·n^(1−α), so α = 1 is the pivot."""
    c = QualityCurve()
    heavy = [expected_fund_returners(n, 1000, c, alpha=0.8) for n in (1, 20)]
    light = [expected_fund_returners(n, 1000, c, alpha=1.8) for n in (1, 20)]
    assert heavy[1] > light[1]
    assert light[0] > light[1], "with α > 1 the mathematics favours concentration"


def test_portfolio_size_is_set_by_capacity_not_by_the_objective():
    """The honest finding: the objective is monotone, so what sets n is how much a
    seed company can absorb, not portfolio theory."""
    out = optimal_portfolio_size(1000, QualityCurve(), alpha=1.8,
                                 max_check_fraction=0.05)
    assert out["binding_constraint"] == "capacity"
    assert out["n"] == out["n_floor"] == 20


def test_screening_lift_is_large_at_a_realistic_portfolio_size():
    """The number that justifies the product existing."""
    v = value_of_screening(20, 1000, QualityCurve(), alpha=1.8)
    assert v["perfect_screening"] > v["no_screening"]
    assert v["relative_lift"] > 1.0


def test_screening_cannot_help_when_the_ranking_is_worthless():
    flat = QualityCurve(p_top=0.05, decay=0.0)
    v = value_of_screening(20, 1000, flat, alpha=1.8)
    assert v["lift"] == pytest.approx(0.0, abs=1e-9)


# --- correlation in the auction model ----------------------------------------


def test_correlation_reduces_the_curse_it_does_not_worsen_it():
    """An earlier version of auction.py claimed the opposite in a comment. The
    common shock moves every fund together and confers no advantage in winning;
    only the idiosyncratic part, scaled √(1−ρ), can mislead the winner."""
    m = CurseModel()
    assert m.penalty(50, rho=0.0) > m.penalty(50, rho=0.5) > m.penalty(50, rho=0.9)


def test_perfect_correlation_removes_the_curse_entirely():
    """If every fund sees exactly the same thing, winning is random."""
    assert CurseModel().penalty(500, rho=1.0) == 0.0


@pytest.mark.parametrize("rho", [0.0, 0.3, 0.6, 0.9])
def test_sqrt_one_minus_rho_scaling_matches_simulation(rho):
    """Simulate equicorrelated errors and measure the winner's idiosyncratic excess."""
    random.seed(int(rho * 100) + 1)
    n = 25
    excess = []
    for _ in range(8000):
        u = random.gauss(0, 1)
        eps = [math.sqrt(rho) * u + math.sqrt(1 - rho) * random.gauss(0, 1)
               for _ in range(n)]
        excess.append(max(eps) - math.sqrt(rho) * u)
    predicted = math.sqrt(1 - rho) * expected_max_normal(n)
    assert predicted == pytest.approx(statistics.fmean(excess), abs=0.03)


def test_private_still_beats_public_after_correlation_credit():
    """Public sources get credit for their rivals thinking alike, and still lose."""
    assert exclusivity_edge(CurseModel(), "whatsapp", "hackernews") > 0.05


# --- adverse selection -------------------------------------------------------


@pytest.mark.parametrize("q", [0.1, 0.3, 0.5, 0.8])
def test_inverse_mills_matches_truncated_normal_simulation(q):
    """E[X | X < c] = −λ(c) for a standard normal."""
    from vc_alpha.quant.selection import _probit, inverse_mills
    random.seed(int(q * 100) + 2)
    c = _probit(q)
    xs = [x for x in (random.gauss(0, 1) for _ in range(150_000)) if x < c]
    assert -inverse_mills(c) == pytest.approx(statistics.fmean(xs), abs=0.02)


def test_a_rare_channel_is_more_sharply_selected():
    """Small share means sharp truncation. The first version of the table inverted
    this, assigning cold inbound the smallest share to try to give it the smallest
    penalty, which produces exactly the opposite."""
    from vc_alpha.quant.selection import SelectionModel
    m = SelectionModel()
    assert m.penalty(0.20) > m.penalty(0.40) > m.penalty(0.60)


def test_a_channel_used_by_half_says_nothing():
    from vc_alpha.quant.selection import NEUTRAL_SHARE, SelectionModel
    assert SelectionModel().penalty(NEUTRAL_SHARE) == pytest.approx(0.0, abs=1e-9)


def test_a_widely_used_channel_earns_a_small_bonus():
    """Above neutral, presence is mild positive evidence rather than a penalty."""
    from vc_alpha.quant.selection import SelectionModel
    assert SelectionModel().penalty(0.70) < 0


def test_the_selection_correction_stays_modest():
    """It rests on an assumed separating equilibrium, so it must move a ranking at
    the margin and never dominate it."""
    from vc_alpha.quant.selection import CHANNEL_SHARE, SelectionModel
    m = SelectionModel()
    assert max(abs(m.penalty(q)) for q in CHANNEL_SHARE.values()) < 0.10


# --- deployment thresholds ---------------------------------------------------


def test_threshold_on_the_last_arrival_is_zero():
    """A slot that expires unused is worth nothing, so take anything positive."""
    from vc_alpha.quant.deployment import DeploymentPolicy
    assert DeploymentPolicy().threshold(1, 5) == 0.0


def test_two_arrivals_one_slot_matches_the_closed_form():
    """τ(2,1) = E[X], which is 0.5 for uniform[0,1]. An exact check on the DP."""
    from vc_alpha.quant.deployment import DeploymentPolicy
    assert DeploymentPolicy().threshold(2, 1) == pytest.approx(0.5, abs=0.02)


def test_the_bar_falls_as_the_window_closes():
    from vc_alpha.quant.deployment import DeploymentPolicy
    p = DeploymentPolicy()
    bars = [p.threshold(k, 10) for k in (100, 50, 20, 5, 1)]
    assert bars == sorted(bars, reverse=True)


def test_the_bar_falls_as_slots_accumulate():
    from vc_alpha.quant.deployment import DeploymentPolicy
    p = DeploymentPolicy()
    bars = [p.threshold(100, m) for m in (1, 5, 10, 25, 50)]
    assert bars == sorted(bars, reverse=True)


def test_more_deal_flow_raises_the_bar():
    """Counterintuitive but correct: better sourcing makes each slot more valuable
    to hold, so the fund should become *more* selective, not less."""
    from vc_alpha.quant.deployment import DeploymentPolicy
    p = DeploymentPolicy()
    assert p.threshold(200, 10) > p.threshold(50, 10)


def test_no_scarcity_means_take_everything():
    """With at least as many slots as arrivals there is nothing to ration."""
    from vc_alpha.quant.deployment import DeploymentPolicy
    assert DeploymentPolicy().threshold(5, 10) == 0.0


def test_recommendation_is_ordered_over_the_fund_life():
    from vc_alpha.quant.deployment import recommend
    r = recommend([i / 100 for i in range(101)], slots_left=14, months_left=22,
                  deals_per_month=8)
    assert r["threshold_now"] > r["threshold_midway"] > r["threshold_final"]


def test_the_distribution_comes_from_observed_scores():
    """The bar is only meaningful on the same scale as the scores it gates."""
    from vc_alpha.quant.deployment import ScoreDistribution
    d = ScoreDistribution.from_scores([0.9] * 100)
    assert d.expectation(lambda x: x) == pytest.approx(0.9, abs=0.02)
