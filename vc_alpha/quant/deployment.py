"""How good a deal has to be, given how much fund and how much time is left.

Every partner knows the bar should drop as a fund ages. Almost nobody computes it.
This does, exactly, and the computation is a classical one.

## The problem

A fund has *m* slots left and expects *k* more candidates before the deployment
window closes. Candidates arrive one at a time with quality X ~ F. The decision is
irrevocable in both directions: pass and the company is gone, invest and a slot is
spent. Maximise the total quality of what gets funded.

This is the sequential assignment problem of Derman, Lieberman and Ross, and it has
an exact optimal policy by backward induction:

    V(k, m) = E[ max( X + V(k−1, m−1),  V(k−1, m) ) ]
    V(0, m) = V(k, 0) = 0

Accept the arrival exactly when taking it beats holding the slot:

    X + V(k−1, m−1) ≥ V(k−1, m)
    ⇔  X ≥ V(k−1, m) − V(k−1, m−1)  =:  τ(k, m)

The threshold is the *option value of the slot*: what that slot is worth if kept.

## What the policy looks like

- **τ falls as the window closes.** With one arrival left, take anything positive:
  a slot that expires unused is worth nothing.
- **τ falls as slots accumulate.** Ten slots and ten arrivals left means taking
  almost everything, because there is no scarcity to ration.
- **τ rises with deal flow.** More expected arrivals makes each slot more valuable
  to hold, so the bar goes up. **Better sourcing therefore raises the bar rather
  than lowering it**, which is the opposite of the usual intuition that more deal
  flow means more investments.

## What this is not

Not the classic 1/e secretary rule. That is the *no-information* problem, where only
relative ranks are observed and the distribution is unknown. Here F is known and
estimated from the pipeline, which is the full-information variant (Gilbert and
Mosteller). The thresholds differ and 1/e does not appear.

The model assumes arrivals are exchangeable and that F is stationary over the
window. Both are approximations: deal flow is seasonal and a fund's own sourcing
improves over time, which is precisely what the rest of this product is for.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class ScoreDistribution:
    """The quality distribution of arriving candidates, discretised.

    Built from the pipeline's own scores rather than assumed, because the threshold
    is only meaningful on the same scale as the scores it is compared against.
    """

    values: tuple[float, ...]
    probs: tuple[float, ...]

    @classmethod
    def from_scores(cls, scores: list[float], bins: int = 40) -> "ScoreDistribution":
        """Empirical distribution of observed scores."""
        clean = [min(max(s, 0.0), 1.0) for s in scores if s is not None]
        if not clean:
            return cls.uniform(bins)
        counts = [0] * bins
        for s in clean:
            counts[min(int(s * bins), bins - 1)] += 1
        total = len(clean)
        return cls(
            values=tuple((i + 0.5) / bins for i in range(bins)),
            probs=tuple(c / total for c in counts),
        )

    @classmethod
    def uniform(cls, bins: int = 40) -> "ScoreDistribution":
        return cls(
            values=tuple((i + 0.5) / bins for i in range(bins)),
            probs=tuple(1.0 / bins for _ in range(bins)),
        )

    def expectation(self, f) -> float:
        return sum(p * f(v) for v, p in zip(self.values, self.probs) if p)


class DeploymentPolicy:
    """Optimal acceptance thresholds over a fund's remaining life."""

    def __init__(self, dist: ScoreDistribution | None = None):
        self.dist = dist or ScoreDistribution.uniform()

    @lru_cache(maxsize=None)
    def value(self, arrivals: int, slots: int) -> float:
        """V(k, m): expected total quality captured under the optimal policy."""
        if arrivals <= 0 or slots <= 0:
            return 0.0
        take = self.value(arrivals - 1, slots - 1)
        skip = self.value(arrivals - 1, slots)
        return self.dist.expectation(lambda x: max(x + take, skip))

    def threshold(self, arrivals: int, slots: int) -> float:
        """τ(k, m): accept a candidate scoring at or above this.

        Equal to the option value of holding the slot. Zero on the last arrival,
        since an unused slot is worth nothing.
        """
        if arrivals <= 0 or slots <= 0:
            return 0.0
        return max(0.0, self.value(arrivals - 1, slots)
                   - self.value(arrivals - 1, slots - 1))

    def schedule(self, arrivals: int, slots: int, points: int = 6) -> list[dict]:
        """How the bar falls as the window closes, holding slots fixed."""
        out = []
        for i in range(points):
            k = max(1, round(arrivals * (1 - i / points)))
            out.append({
                "arrivals_left": k,
                "slots_left": slots,
                "threshold": round(self.threshold(k, slots), 4),
            })
        return out


def recommend(scores: list[float], slots_left: int, months_left: int,
              deals_per_month: float) -> dict:
    """The partner-facing answer: what the bar should be right now, and later.

    `deals_per_month` is how many candidates clear earlier stages in a typical
    month, so expected arrivals is that rate times the months remaining.
    """
    arrivals = max(1, int(round(deals_per_month * months_left)))
    policy = DeploymentPolicy(ScoreDistribution.from_scores(scores))

    now = policy.threshold(arrivals, slots_left)
    half = policy.threshold(max(1, arrivals // 2), slots_left)
    end = policy.threshold(1, slots_left)

    return {
        "arrivals_expected": arrivals,
        "slots_left": slots_left,
        "months_left": months_left,
        "threshold_now": round(now, 4),
        "threshold_midway": round(half, 4),
        "threshold_final": round(end, 4),
        "expected_total_quality": round(policy.value(arrivals, slots_left), 4),
        "schedule": policy.schedule(arrivals, slots_left),
    }
