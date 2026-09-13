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
    assert "invent" in BY_TASK[task].lower() or "guess" in BY_TASK[task].lower()


def test_research_states_the_cost_of_omitting_too():
    """The measured fault. With only a penalty for inventing and none for omitting,
    the model answered "unknown" whenever unsure and the filled-field rate fell from
    74% to 40% — removing more truth than falsehood."""
    p = BY_TASK["research"].lower()
    assert "omitting" in p and "costs them the company" in p


def test_the_research_rule_is_stated_once_not_three_times():
    """It was stated three times in 352 tokens, which breaks this file's own rule
    that every sentence be additive, and taught the model that "unknown" is the safe
    default answer."""
    assert BY_TASK["research"].lower().count('"unknown"') <= 2


def test_written_fields_are_excused_from_the_unknown_rule():
    """Six of 23 reports in the first real run came back with description "unknown",
    for posts that plainly described a product. The caution meant for the factual
    fields had leaked into the two fields that are always writable.

    Covering both by name matters: a first version justified only the description, and
    the model kept answering "unknown" for fit in exactly the same six reports.
    """
    p = BY_TASK["research"].lower()
    written = p[p.index("<written_fields>"):p.index("</written_fields>")]
    assert '"unknown" is never the answer' in written
    assert "description" in written and "fit" in written


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
