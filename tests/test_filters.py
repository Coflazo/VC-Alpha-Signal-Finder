"""Pre-embedding filters.

These run before the expensive stage, which makes them the easiest place in the
system to lose signal silently. Anything dropped here is invisible to every later
stage, so the false-positive cases are pinned as hard as the true ones.
"""

from datetime import datetime, timedelta, timezone

import pytest

from vc_alpha.filters import MIN_CHARS, reject

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
FOUNDER = ("I left my infrastructure job in Berlin and built a tool that "
           "reconciles invoices for mid-size companies. Two design partners so far.")


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


def test_a_founder_post_passes():
    assert reject(FOUNDER, posted_at=ago(1), now=NOW) is None


@pytest.mark.parametrize("text,expected", [
    ("We're hiring a senior backend engineer, competitive salary", "job_ad"),
    ("Black Friday discount code inside, limited time offer for everyone", "promo"),
    ("Ask HN: what is the best time series database for heavy write loads?", "question"),
    ("x" * (MIN_CHARS - 1), "too_short"),
])
def test_noise_is_dropped_with_a_reason(text, expected):
    r = reject(text, now=NOW)
    assert r and r.filter == expected
    assert r.reason, "a rejection with no reason is undebuggable"


# The measured failure. On a real corpus 8 of 57 question-rejections were founders,
# including "Ask HN: How do we build a team? (bootstrapped B2B startup)".
@pytest.mark.parametrize("text", [
    "Ask HN: How do we build a team? (bootstrapped B2B startup)",
    "Ask HN: I built a CLI for this, would anyone else use it?",
    "Ask HN: we launched last month and growth stalled, what would you try?",
    "Ask HN: When you sell your company, how do you receive the money?",
])
def test_a_founder_asking_a_question_is_still_a_founder(text):
    assert reject(text, now=NOW) is None, "builder language must override the question filter"


def test_genuinely_old_posts_are_dropped():
    assert reject(FOUNDER, posted_at=ago(900), now=NOW).filter == "too_old"


def test_recent_posts_survive():
    assert reject(FOUNDER, posted_at=ago(100), now=NOW) is None


@pytest.mark.parametrize("stamp", [None, "not a date", ""])
def test_an_unknown_date_never_rejects(stamp):
    """Absent evidence should not reject. Plenty of sources omit a timestamp."""
    assert reject(FOUNDER, posted_at=stamp, now=NOW) is None


def test_filters_run_cheapest_first():
    """Ordering is the whole point: each filter should see fewer items than the last."""
    from vc_alpha.filters import FILTERS, too_short
    assert FILTERS[0] is too_short
