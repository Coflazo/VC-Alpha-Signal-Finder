"""System prompts.

The point of these tests is to stop the prompts drifting back into the thing they
were written instead of: a very long, general-purpose instruction that buries the
task and eats the token budget.
"""

import pytest

from vc_alpha.prompts import BY_TASK, MAX_TOKENS, approx_tokens, for_task


@pytest.mark.parametrize("task", sorted(BY_TASK))
def test_every_prompt_stays_within_budget(task):
    """The vendor prompts considered as a base came to ~108,000 tokens against a
    free-tier budget of 8,000 per minute. This is the guard against growing back
    toward that."""
    assert approx_tokens(BY_TASK[task]) < MAX_TOKENS


@pytest.mark.parametrize("task", sorted(BY_TASK))
def test_every_prompt_states_the_cost_of_inventing(task):
    """The failure both prompts exist to prevent."""
    assert "unknown" in BY_TASK[task].lower()


def test_triage_defends_calibration():
    """A model that scores generously destroys the ranking, which is the whole
    output. Measured mean signal scores of 0.06 to 0.19 are the correct shape."""
    assert "0.7" in BY_TASK["triage"]


def test_research_forbids_the_inferences_that_were_actually_observed():
    """'Based in: San Francisco, USA' for a post with no location in it."""
    p = BY_TASK["research"].lower()
    assert "timezone" in p and "nationality" in p


def test_research_still_asks_for_real_writing_where_it_is_wanted():
    """Extraction discipline must not turn the description into 'unknown' too."""
    assert "yours to write" in BY_TASK["research"]


def test_prompts_do_not_argue_with_the_model():
    """Craft lesson worth keeping: intensifiers read as persuasion rather than
    instruction, and an earlier draft of these prompts used them."""
    for task, prompt in BY_TASK.items():
        low = prompt.lower()
        for word in ("very important", "critically", "extremely", "far better",
                     "absolutely", "you must never"):
            assert word not in low, f"{task} argues instead of instructing: {word}"


def test_unknown_tasks_get_no_prompt_rather_than_a_generic_one():
    assert for_task("something-else") is None
