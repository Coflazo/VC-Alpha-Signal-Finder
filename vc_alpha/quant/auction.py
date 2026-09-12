"""What a signal is worth once you account for who else can see it.

This is the piece of mathematics that most changes how the product should behave,
and it is the reason private sources are not merely a nice extra.

## The model

Early-stage deal allocation is a **common-value auction**. The company has some
true quality V that is the same for every investor. Fund i does not observe V; it
observes a noisy signal

    s_i = V + ε_i,        ε_i ~ N(0, σ_e²)  iid across funds

The founder runs a process and takes the best offer, so the fund that wins is
approximately the one with the highest signal. That is the trap.

## The curse

Conditional on winning, your signal was the maximum of N draws. A maximum is high
either because V was high or because your ε_i was high, and the more competitors
there are, the more of that maximum is explained by your own error:

    E[ε_i | i wins] > 0,  and grows with N

For ε iid normal, the expected maximum of N standard normals is asymptotically

    E[max Z_1..Z_N] ≈ √(2 ln N) − (ln ln N + ln 4π) / (2√(2 ln N))

So the bias in your posterior on V, conditional on having won, is

    bias(N) ≈ β · σ_e · E[max Z_1..Z_N],      β = σ_v² / (σ_v² + σ_e²)

β is the shrinkage factor from the normal-normal posterior: how much of a signal
movement you should believe. The correct adjusted value of winning is therefore

    E[V | s_i, win] ≈ μ + β(s_i − μ) − bias(N)

**The practical consequence.** Two candidates with identical model scores are not
equally valuable. One seen by three funds and one seen by two hundred differ by

    β σ_e [√(2 ln 200) − √(2 ln 3)] ≈ 1.78 σ_e

The crowded one must score materially higher to be worth the same. This is why a
signal nobody else can see is worth more than an equally accurate public one, and
it is a statement about arithmetic rather than about taste.

## Assumptions, and where they fail

- Signals iid conditional on V. Funds using the same data vendor have correlated
  errors, which makes the true curse *worse* than this estimate, not better.
- The founder picks the highest offer. Often they pick on reputation or speed, and
  for a fund that reliably wins on something other than price the curse is smaller.
- Normal errors. The √(2 ln N) growth is specific to the normal tail; heavier
  tails give a larger correction, so this is the conservative direction.
- N is estimated per source, not observed. See SOURCE_AUDIENCE below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

def _phi(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _Phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@lru_cache(maxsize=512)
def expected_max_normal(n: int, *, grid: int = 4000, span: float = 9.0) -> float:
    """E[max of n iid N(0,1)], by numerical integration of the exact density.

        E[M_n] = ∫ x · n · φ(x) · Φ(x)^(n-1) dx

    The textbook route here is Cramér's asymptotic expansion, √(2 ln n) minus a
    correction. It was tried first and rejected: checked against 40,000-trial Monte
    Carlo it underestimates by 0.13 to 0.25 across the whole range, and is worst
    precisely where this product operates. At n = 3 it gives 0.597 against a true
    0.846, a 29% error, because the expansion is asymptotic and n = 3 is not large.

    Since every audience of interest is between 3 and 200, the asymptotic form is
    wrong in exactly the region that matters, so the integral is computed directly.
    Simpson's rule over ±9σ is exact to ~1e-6 here and is evaluated once per
    distinct n.
    """
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0 / math.sqrt(math.pi)          # closed form, used as a check

    h = 2.0 * span / grid
    total = 0.0
    for i in range(grid + 1):
        x = -span + i * h
        f = x * n * _phi(x) * (_Phi(x) ** (n - 1))
        weight = 1 if i in (0, grid) else (4 if i % 2 else 2)
        total += weight * f
    return total * h / 3.0


# How many funds plausibly see a signal from each source. These are estimates and
# should be argued with; the ordering is what matters and the ordering is not
# controversial. A Hacker News front-page post is read by every associate in the
# industry; a message in a private founders group is read by its members.
SOURCE_AUDIENCE = {
    "whatsapp": 3,        # your groups; a handful of investors at most
    "inbound": 8,         # they emailed several funds, but not the whole market
    "linkedin": 25,       # visible, but requires knowing to look
    "reddit": 60,         # public, niche subreddits, moderately watched
    "substack": 80,       # newsletters investors read on purpose
    "github": 120,        # trending repos are watched by many scouts
    "hackernews": 200,    # the most watched public signal in technology
}

DEFAULT_AUDIENCE = 100


@dataclass(frozen=True, slots=True)
class CurseModel:
    """Parameters of the common-value model, in score units (0..1).

    sigma_e: the model's scoring error. Measurable from disagreement between the
             system and human labels, and from repeat scoring of the same
             candidate. Until that data exists, 0.15 is a deliberately modest
             placeholder — the *ordering* it produces is robust to the value.
    sigma_v: dispersion of true quality across candidates.
    """

    sigma_e: float = 0.15
    sigma_v: float = 0.25

    @property
    def beta(self) -> float:
        """Shrinkage: how much of a signal movement to believe."""
        denom = self.sigma_v ** 2 + self.sigma_e ** 2
        return (self.sigma_v ** 2) / denom if denom else 0.0

    def penalty(self, audience: int) -> float:
        """Expected overvaluation from winning against `audience` competitors."""
        return self.beta * self.sigma_e * expected_max_normal(max(1, audience))

    def adjust(self, score: float, source: str | None = None,
               audience: int | None = None) -> float:
        """Score net of the winner's curse. Never below zero."""
        n = audience if audience is not None else SOURCE_AUDIENCE.get(
            source or "", DEFAULT_AUDIENCE)
        return max(0.0, score - self.penalty(n))


def exclusivity_edge(model: CurseModel, private: str, public: str) -> float:
    """How much higher a public signal must score to match a private one.

    The number that justifies reading private communities at all.
    """
    return model.penalty(SOURCE_AUDIENCE.get(public, DEFAULT_AUDIENCE)) - \
           model.penalty(SOURCE_AUDIENCE.get(private, DEFAULT_AUDIENCE))


def break_even_audience(model: CurseModel, edge: float) -> int:
    """Largest audience at which a signal with `edge` advantage still wins.

    Inverts penalty(N) = edge. Useful for asking "how much better does our public
    scoring have to be before crowding stops mattering?"
    """
    if edge <= 0 or model.beta <= 0 or model.sigma_e <= 0:
        return 1
    target = edge / (model.beta * model.sigma_e)
    n = 1
    while n < 10_000 and expected_max_normal(n + 1) <= target:
        n += 1
    return n
