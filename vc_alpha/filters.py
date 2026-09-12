"""Cheap filters that run before anything expensive touches a candidate.

The pipeline had this backwards. It embedded everything, then gated on the score.
Embedding costs seconds per item on modest hardware; these predicates cost
microseconds and are computed from text already in hand. Filtering first is the
single largest efficiency win available, and it is free.

Ordered cheap-to-expensive and universal-before-specific, so each filter sees
fewer items than the one before it.

Every filter returns a reason string when it rejects, never a bare False. A
candidate that vanishes without explanation is impossible to debug, and this is
the stage where silent over-filtering would quietly starve everything downstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

# A founder announcing a company is signal. A company advertising a vacancy is
# not: the company already exists and is usually well past the window.
_JOB_AD = re.compile(
    r"\b(we'?re hiring|now hiring|job opening|apply now|send your (cv|resume)|"
    r"who'?s hiring|seeking candidates|full[- ]time position|job alert|"
    r"remote position|competitive salary|benefits package)\b",
    re.I,
)

# Posts that are asking rather than building.
_PURE_QUESTION = re.compile(
    r"^(ask hn|question|does anyone know|how do i|what'?s the best|"
    r"looking for recommendations|eli5)\b",
    re.I,
)

_PROMO = re.compile(
    r"\b(discount code|coupon|black friday|limited time offer|buy now|"
    r"affiliate link|sponsored post|giveaway)\b",
    re.I,
)

# Someone describing what they have built, even inside a question. Measured on a
# real corpus: 8 of 57 posts the question filter rejected contained this language,
# including "Ask HN: How do we build a team? (bootstrapped B2B startup)" — a
# founder, which is exactly who this product exists to find. A question asked by
# someone who is building is signal, not noise.
_BUILDER = re.compile(
    r"\b(i|we) (built|made|created|launched|shipped|founded|started|"
    r"am building|are building|'?ve built)\b|\bmy (startup|company|product|saas)\b|"
    r"\bour (startup|company|product)\b|\bbootstrapped\b|\bsold (my|our) company\b",
    re.I,
)

MIN_CHARS = 40


@dataclass(frozen=True, slots=True)
class Rejection:
    filter: str
    reason: str


def too_short(text: str, **_) -> Rejection | None:
    """A title with no body cannot support a judgement about a company."""
    if len(text.strip()) < MIN_CHARS:
        return Rejection("too_short", f"{len(text.strip())} chars, under {MIN_CHARS}")
    return None


def is_job_ad(text: str, **_) -> Rejection | None:
    if m := _JOB_AD.search(text):
        return Rejection("job_ad", f"reads as a vacancy: {m.group(0)!r}")
    return None


def is_promo(text: str, **_) -> Rejection | None:
    if m := _PROMO.search(text):
        return Rejection("promo", f"promotional: {m.group(0)!r}")
    return None


def is_pure_question(text: str, **_) -> Rejection | None:
    """Asking about a space, not building in it.

    Deliberately anchored to the start: a post that opens 'Ask HN' is a question,
    but one that mentions a question halfway through may still be a launch.
    """
    if not _PURE_QUESTION.match(text.strip()):
        return None
    # A founder asking a question is still a founder. Builder language overrides.
    if _BUILDER.search(text):
        return None
    return Rejection("question", "opens as a question with no sign of building")


def too_old(text: str, *, posted_at: str | None = None, max_age_days: int = 540,
            now: datetime | None = None, **_) -> Rejection | None:
    """A founder from two years ago has either raised or stopped.

    Generous by default. The recency weighting in score.py handles the gradient;
    this only drops things far enough back to be certainly stale. An unknown date
    passes, because absent evidence should not reject.
    """
    if not posted_at:
        return None
    try:
        when = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - when).days
    if age > max_age_days:
        return Rejection("too_old", f"{age} days old, over {max_age_days}")
    return None


# Cheapest first. Each sees fewer candidates than the last.
FILTERS = (too_short, is_promo, is_job_ad, is_pure_question, too_old)


def reject(text: str, *, posted_at: str | None = None, **kw) -> Rejection | None:
    """The first reason this candidate should not be embedded, or None."""
    for f in FILTERS:
        if r := f(text, posted_at=posted_at, **kw):
            return r
    return None
