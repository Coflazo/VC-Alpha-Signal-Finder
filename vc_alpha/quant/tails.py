"""Portfolio mathematics when returns have infinite variance.

Venture returns are power-law distributed, and that single fact invalidates most of
the statistical machinery people reach for by default.

## Why the usual tools do not apply

If exit multiples follow a Pareto tail, P(R > r) ∝ r^(−α), then

    α ≤ 2  ⇒  Var[R] = ∞
    α ≤ 1  ⇒  E[R]   = ∞

Empirical estimates for early-stage venture put α between roughly 1.5 and 2.5.
**In the lower half of that range the variance does not exist.** Not "is large" —
does not exist. Every quantity built on it inherits the problem:

- **Sharpe ratio is undefined.** Its denominator is a quantity that has no value.
  A sample standard deviation can always be computed, but it does not converge as
  n grows; it drifts upward with each new extreme observation.
- **Mean-variance optimisation is undefined**, for the same reason.
- **The central limit theorem does not apply** in its usual form. Sums converge to
  an α-stable law, not a normal, so confidence intervals from the normal
  approximation are wrong and wrong in the dangerous direction, being too narrow.
- **Sample means converge slowly and non-monotonically.** A fund's realised average
  return is mostly an artefact of whether the one outlier has landed yet.

## What does apply

Order statistics and the tail index. What matters for a fund is not the mean but
the probability of touching the extreme tail at all, which is why the objective
below is P(at least one fund-returner) rather than expected return.

The Hill estimator gives α from the top k observations, and the
Pickands–Balkema–de Haan theorem justifies it: exceedances above a high threshold
converge to a generalised Pareto distribution regardless of the underlying
distribution's body.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def hill_estimator(sorted_desc: list[float], k: int | None = None) -> float:
    """Tail index α from the top k order statistics.

        γ̂ = (1/k) Σ_{i=1..k} [ln X_(i) − ln X_(k+1)],   α̂ = 1/γ̂

    k trades bias against variance: too small and the estimate is noisy, too large
    and the body of the distribution contaminates it. √n is the usual default and
    is what is used when k is not given.
    """
    xs = [x for x in sorted_desc if x > 0]
    if len(xs) < 3:
        return float("nan")
    xs.sort(reverse=True)
    k = k or max(2, int(math.sqrt(len(xs))))
    k = min(k, len(xs) - 1)

    ref = math.log(xs[k])
    gamma = sum(math.log(xs[i]) - ref for i in range(k)) / k
    return 1.0 / gamma if gamma > 0 else float("inf")


def moments_exist(alpha: float) -> dict[str, bool]:
    """Which moments exist at this tail index. The honest health check."""
    return {
        "mean": alpha > 1.0,
        "variance": alpha > 2.0,
        "sharpe_is_defined": alpha > 2.0,
        "clt_applies": alpha > 2.0,
    }


@dataclass(frozen=True, slots=True)
class QualityCurve:
    """How hit rate declines with rank as a fund becomes less selective.

    A power law in **rank**, not in quantile:

        p(r) = p_top · r^(−decay),   r = 1, 2, 3, …

    The first attempt used quantile u with p(u) = p_top·u^(−decay), which is
    unbounded as u → 0 and duly assigned the top-ranked candidate a 100% hit rate.
    Rank form is bounded by construction, since p(1) = p_top, and is also the shape
    selection curves empirically take: Zipf-like, with a steep head and a long flat
    body.

    p_top: hit rate of the single best candidate in the pipeline.
    decay: how fast quality falls with rank. 0 means ranking is worthless, which is
           the null hypothesis worth being able to state and test against.
    """

    p_top: float = 0.10
    decay: float = 0.35

    def hit_rate_at_rank(self, r: int) -> float:
        """Hit probability for the candidate ranked r (1 is best)."""
        return min(1.0, self.p_top * max(1, r) ** (-self.decay))

    def mean_hit_rate(self, n: int) -> float:
        """Average hit rate across the top n taken."""
        if n <= 0:
            return 0.0
        return sum(self.hit_rate_at_rank(r) for r in range(1, n + 1)) / n


def prob_at_least_one(n: int, pipeline: int, curve: QualityCurve) -> float:
    """P(the fund lands at least one outlier) making n investments from a pipeline.

    The objective that actually matters for an early-stage fund. Because returns
    are power-law, a fund's result is decided by whether it touched the tail at
    all, not by the average of what it held.
    """
    if n <= 0 or pipeline <= 0:
        return 0.0
    miss = 1.0
    for r in range(1, min(n, pipeline) + 1):
        miss *= 1.0 - curve.hit_rate_at_rank(r)
    return 1.0 - miss


def prob_fund_returner(n: int, pipeline: int, curve: QualityCurve,
                       alpha: float = 1.8, skill: float = 1.0) -> float:
    """P(at least one position returns the whole fund), with n equal positions.

    With n equal positions each is 1/n of the fund, so a winner must return a
    multiple of at least **n** to return the fund alone. Multiples are Pareto with
    index α, so P(multiple ≥ n) = n^(−α).

        P(fund returned) = 1 − ∏_{r=1..n} [1 − p_obs(r) · n^(−α)]

    `skill` ρ ∈ [0,1] is how much the ranking is worth. The observed hit rate at
    rank r is a blend of the true curve and the pipeline average:

        p_obs(r) = ρ · p_true(r) + (1 − ρ) · p̄

    At ρ = 1 the ranking is perfect; at ρ = 0 it carries no information and every
    position is an average one. This is where the product's own screening quality
    enters the portfolio question.
    """
    if n <= 0 or pipeline <= 0:
        return 0.0
    p_big_enough = float(n) ** (-alpha)
    p_bar = curve.mean_hit_rate(pipeline)
    miss = 1.0
    for r in range(1, min(n, pipeline) + 1):
        p_obs = skill * curve.hit_rate_at_rank(r) + (1.0 - skill) * p_bar
        miss *= 1.0 - p_obs * p_big_enough
    return 1.0 - miss


def expected_fund_returners(n: int, pipeline: int, curve: QualityCurve,
                            alpha: float = 1.8, skill: float = 1.0) -> float:
    """Expected count of fund-returning positions. Cleaner to reason about than P.

    Approximately p̄ · n^(1−α), and that exponent is the whole story:

        α > 1  ⇒  decreasing in n  ⇒  concentration wins
        α < 1  ⇒  increasing in n  ⇒  spreading wins

    Empirical venture α sits above 1, so **the mathematics says concentrate**, and
    it says so regardless of screening skill. Skill changes the level, not the
    direction.
    """
    if n <= 0:
        return 0.0
    p_bar = curve.mean_hit_rate(pipeline)
    scale = float(n) ** (-alpha)
    return sum(
        (skill * curve.hit_rate_at_rank(r) + (1 - skill) * p_bar) * scale
        for r in range(1, min(n, pipeline) + 1)
    )


def optimal_portfolio_size(pipeline: int, curve: QualityCurve, alpha: float = 1.8,
                           max_check_fraction: float = 0.05,
                           skill: float = 1.0) -> dict:
    """Portfolio size under the constraint that actually binds.

    Two earlier attempts at this were wrong in opposite directions, and the errors
    are worth recording because both looked plausible.

    The first applied dilution as a flat weight min(1, (1/n)/floor). It never bound
    inside the search range, the objective came out monotone increasing, and the
    answer was always "take everything".

    The second coupled dilution correctly through P(multiple ≥ n) = n^(−α), and the
    objective became monotone *decreasing*: always n = 1. Adding ranking noise did
    not flip it, because n^(−α) with α > 1 dominates the extra draws no matter how
    poor the ranking is.

    The second result is not a bug. Under these assumptions concentration genuinely
    does win, and the reason real funds hold 20 to 40 positions is **not** portfolio
    theory. It is a capacity constraint: an early-stage company can only absorb so
    much, so a fund cannot put more than `max_check_fraction` of itself into any
    one. That constraint is what sets n, and the portfolio question is therefore
    mostly answered before any optimisation happens.

    n is bounded below by 1/max_check_fraction, and the objective is decreasing, so
    the optimum sits exactly at that floor. The interesting quantity is not n at
    all — it is what better screening is worth at fixed n, which is
    `value_of_screening` below.
    """
    n_floor = max(1, math.ceil(1.0 / max_check_fraction))
    table = [
        {"n": n, "prob": prob_fund_returner(n, pipeline, curve, alpha, skill),
         "expected": expected_fund_returners(n, pipeline, curve, alpha, skill)}
        for n in range(1, min(pipeline, max(n_floor * 3, 60)) + 1)
    ]
    feasible = [row for row in table if row["n"] >= n_floor]
    best = max(feasible, key=lambda r: r["prob"]) if feasible else table[0]
    return {
        "n": best["n"],
        "prob": best["prob"],
        "n_floor": n_floor,
        "binding_constraint": "capacity" if best["n"] == n_floor else "objective",
        "mean_hit_rate": curve.mean_hit_rate(best["n"]),
        "alpha": alpha,
        "table": table,
    }


def value_of_screening(n: int, pipeline: int, curve: QualityCurve,
                       alpha: float = 1.8) -> dict:
    """What better screening is worth, in fund-return probability, at fixed n.

    Since portfolio size is set by capacity rather than by choice, this is the
    question the product can actually move: at the n a fund must hold anyway, how
    much does ranking skill raise the chance of touching the tail?
    """
    blind = prob_fund_returner(n, pipeline, curve, alpha, skill=0.0)
    perfect = prob_fund_returner(n, pipeline, curve, alpha, skill=1.0)
    return {
        "n": n,
        "no_screening": blind,
        "perfect_screening": perfect,
        "lift": perfect - blind,
        "relative_lift": (perfect / blind - 1.0) if blind > 0 else float("inf"),
    }
