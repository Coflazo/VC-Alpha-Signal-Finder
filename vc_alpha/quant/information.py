"""Which candidate a human should look at next.

The review queue is currently sorted by score descending. That is the wrong order,
and the reason is a short piece of decision theory.

## Value of information

A human review resolves uncertainty about a candidate. Uncertainty is only worth
resolving if it could change a decision. Formally, with posterior p that a
candidate is worth pursuing, payoff R if it is and loss L if it is not, the
decision without more information is

    v(p) = max(pR − (1−p)L,  0)

and the decision threshold is where those are equal:

    τ = L / (R + L)

With perfect information you would pursue only the good ones, worth pR. So the
expected value of perfect information is

    EVPI(p) = pR − v(p) = { pR        if p < τ     (you would have passed, wrongly)
                          { (1−p)L    if p ≥ τ     (you would have pursued, wrongly)

**This is a tent function peaking exactly at p = τ, and zero at p = 0 and p = 1.**

## What that means in practice

Reviewing the top-scoring candidate teaches you almost nothing: you were going to
pursue it anyway, and the review will not change that. Reviewing the bottom one is
equally pointless. The information is at the boundary, among the candidates the
model cannot separate.

This is the opposite of how every deal-flow tool orders its queue, and it matters
most here because these labels are what turn the stage-2 threshold from a guess
into a measured number. Sorting by score would spend an analyst's attention
confirming what the model already knows.

Under a time budget, the right index is EVSI per unit of analyst time. Reviews cost
roughly the same each, so ordering by EVPI alone is the correct simplification, and
the cost term is kept explicit for when that stops being true.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecisionEconomics:
    """Payoffs in fund-return multiples.

    A hit that returns the fund is worth far more than the cost of a wasted
    meeting, which is what makes τ small and the review boundary sit low.

    reward: value of correctly pursuing a good company, in multiples.
    loss:   cost of pursuing a bad one — diligence hours and opportunity cost,
            not capital, since most bad ones are dropped before investment.
    """

    reward: float = 30.0
    loss: float = 1.0

    @property
    def threshold(self) -> float:
        """τ = L/(R+L). The posterior above which pursuit beats passing."""
        return self.loss / (self.reward + self.loss)

    def value(self, p: float) -> float:
        return max(p * self.reward - (1.0 - p) * self.loss, 0.0)

    def evpi(self, p: float) -> float:
        """Expected value of perfect information. Peaks at τ, zero at 0 and 1."""
        p = min(max(p, 0.0), 1.0)
        return p * self.reward if p < self.threshold else (1.0 - p) * self.loss


def evsi_gaussian(p: float, econ: DecisionEconomics, d_prime: float = 1.0,
                  grid: int = 200) -> float:
    """Expected value of an *imperfect* review, of discriminability d'.

    A human review is not perfect information. Model it as an observation x with
    x|good ~ N(d'/2, 1) and x|bad ~ N(−d'/2, 1), so d' is how well the reviewer
    separates the two. EVSI → EVPI as d' → ∞, and → 0 as d' → 0.

    Integrating over the predictive distribution of x:

        EVSI = E_x[ max over actions given posterior(x) ] − max over actions now
    """
    if p <= 0.0 or p >= 1.0 or d_prime <= 0:
        return 0.0

    lo, hi = -6.0 - d_prime, 6.0 + d_prime
    h = (hi - lo) / grid
    expected = 0.0
    for i in range(grid + 1):
        x = lo + i * h
        # Densities under each hypothesis.
        f1 = math.exp(-0.5 * (x - d_prime / 2) ** 2)
        f0 = math.exp(-0.5 * (x + d_prime / 2) ** 2)
        marginal = p * f1 + (1 - p) * f0
        if marginal <= 0:
            continue
        post = p * f1 / marginal
        weight = 1 if i in (0, grid) else (4 if i % 2 else 2)
        # The 1/√(2π) cancels between the posterior and the marginal weighting.
        expected += weight * marginal * econ.value(post)
    expected *= h / 3.0 / math.sqrt(2.0 * math.pi)

    return max(0.0, expected - econ.value(p))


def review_priority(p: float, econ: DecisionEconomics | None = None,
                    d_prime: float = 1.5, cost: float = 1.0) -> float:
    """Index for ordering the review queue: information gained per unit of time.

    Sorting by this rather than by score is the whole point. Two candidates scoring
    0.9 and 0.5 against a threshold of 0.03 are not equally informative — the second
    is nearer the boundary in log-odds terms and will teach you more.
    """
    econ = econ or DecisionEconomics()
    return evsi_gaussian(p, econ, d_prime) / max(cost, 1e-9)


def calibrate_to_posterior(score: float, base_rate: float = 0.02,
                           d_prime: float = 1.2) -> float:
    """Turn a 0..1 model score into a posterior probability of being worth pursuing.

    A model score is not a probability. It is a ranking statistic, and treating it
    as a probability is how a system ends up claiming 90% confidence in a hit rate
    that is really 2%. Map it through the base rate with a logistic link:

        logit(posterior) = logit(base_rate) + d' · (score − 0.5) · k

    The base rate dominates, which is correct: at a 2% prior, even a strong signal
    leaves the posterior well under a half. Until there are enough labels to fit
    this properly it is a stated assumption, not a measurement.
    """
    base_rate = min(max(base_rate, 1e-6), 1 - 1e-6)
    prior_logit = math.log(base_rate / (1 - base_rate))
    # Scale so a score of 1.0 moves the log-odds by about 3 d' units.
    z = prior_logit + d_prime * (score - 0.5) * 6.0
    return 1.0 / (1.0 + math.exp(-z))
