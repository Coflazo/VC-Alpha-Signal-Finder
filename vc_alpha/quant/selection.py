"""Adverse selection: which channel a founder is in is itself a signal.

The winner's curse asks *how many* funds can see a deal. It does not ask why the
founder is in that channel at all, and that is a separate, compounding penalty.

## The signalling game

A founder knows their own quality θ and chooses how to raise. Warm introductions to
good funds require a network, and a network correlates with the things that make a
founder fundable: prior companies, a notable employer, people who will vouch. A
founder who can raise through introductions generally does, because it yields better
terms and a faster process.

Posting publicly is what you do when that route is thin. So in any separating
equilibrium, the founders who appear in open channels are drawn from the lower part
of the conditional quality distribution.

## The correction

If θ ~ N(μ, σ²) and a founder resorts to a public channel when θ falls below some
threshold c, then observing them there truncates the distribution from above:

    E[θ | θ < c] = μ − σ · λ(z),    λ(z) = φ(z)/Φ(z),    z = (c − μ)/σ

λ is the inverse Mills ratio. The penalty is therefore σ·λ(z), and it grows as the
channel becomes more of a last resort.

## The two effects are distinct, and they compound

    adjusted = raw − curse(N, ρ) − selection(channel)

Crowding is about how many rivals saw the same thing. Selection is about who chooses
to be seen there at all. A deal can be uncrowded and adversely selected, which is
the worst combination and the reason "nobody else has seen this" is not by itself a
reason to be excited.

## Where this breaks, stated plainly

The separating equilibrium is not the only one, and the assumption is doing real
work here:

- Founders who post publicly **on purpose**, to run a competitive process from a
  position of strength, invert the logic entirely.
- Technical founders who build in public are often the strongest ones and treat
  Hacker News as their native habitat rather than a fallback.
- First-time founders with no network can be excellent and simply have no other
  route, which is precisely the population several of the configured theses target.

So the correction is deliberately small, it is configurable, and **inbound carries
almost none of it** — a founder who emails you directly has chosen you, which is
close to the opposite of a last resort.

A model this assumption-heavy should move a ranking at the margin and never
dominate it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def inverse_mills(z: float) -> float:
    """λ(z) = φ(z)/Φ(z), the truncated-normal correction factor.

    Guarded in the far-left tail, where Φ(z) underflows and the ratio is better
    approximated by its asymptote λ(z) ≈ −z.
    """
    if z < -30.0:
        return -z
    phi = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    Phi = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return phi / Phi if Phi > 1e-300 else -z


# CHANNEL_SHARE is the fraction of the founder population that ends up in this
# channel. It is *not* a quality rating, and the direction is easy to get backwards.
#
# Small share ⇒ sharp truncation ⇒ large correction. Large share ⇒ almost everyone
# is here ⇒ the channel says nothing about quality either way. 0.5 is neutral, and
# anything above it earns a small *bonus* rather than a penalty, because presence
# is then mild positive evidence.
#
# The first version of this table inverted the relationship, assigning cold inbound
# the smallest share in an attempt to give it the smallest penalty. Working the
# algebra through showed that produces the opposite: a rarely-used channel is the
# most sharply selected one.
#
# That is not a modelling artefact. **Cold inbound being adversely selected is
# exactly the warm-introduction doctrine**, stated as arithmetic rather than as
# prejudice: a founder who can get an introduction generally gets one. The product
# still values inbound highly, because intent and thesis fit are separate signals
# from network strength, and because several of the configured theses deliberately
# target founders without networks. The correction is small and it is one term
# among several.
CHANNEL_SHARE = {
    "whatsapp": 0.70,     # membership of a curated group is mild positive evidence
    "linkedin": 0.60,     # essentially everybody is there; says little
    "github": 0.50,       # most technical founders, strong ones included
    "hackernews": 0.45,   # a large share of technical founders, by preference
    "reddit": 0.35,       # narrower, more first-time and indie
    "substack": 0.30,     # writing publicly is effortful and self-selecting
    "inbound": 0.25,      # cold outreach; the warm-intro doctrine, as arithmetic
}

DEFAULT_SHARE = 0.40

# Share at which the channel carries no information. Corrections are measured
# relative to this, so the model can express a bonus as well as a penalty.
NEUTRAL_SHARE = 0.5


@dataclass(frozen=True, slots=True)
class SelectionModel:
    """sigma_theta: dispersion of founder quality, in score units.

    strength: how much of the theoretical correction to actually apply. Below 1
    because the separating equilibrium is an assumption, not an observation, and a
    model resting on an unverified equilibrium should not be allowed to dominate a
    ranking. Raise it only with evidence.
    """

    sigma_theta: float = 0.25
    strength: float = 0.5

    def penalty(self, share: float) -> float:
        """Quality shortfall from observing a founder here, relative to neutral.

        Positive is a penalty, negative is a bonus. Measured against a channel used
        by half the population, which by construction carries no information.
        """
        q = min(max(share, 1e-6), 1.0 - 1e-6)
        baseline = inverse_mills(_probit(NEUTRAL_SHARE))
        return self.strength * self.sigma_theta * (inverse_mills(_probit(q)) - baseline)

    def adjust(self, score: float, source: str | None = None,
               share: float | None = None) -> float:
        s = (share if share is not None
             else CHANNEL_SHARE.get(source or "", DEFAULT_SHARE))
        return max(0.0, score - self.penalty(s))


def _probit(p: float) -> float:
    """Φ⁻¹(p), Acklam's rational approximation. Accurate to ~1e-9 over (0,1)."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425

    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
