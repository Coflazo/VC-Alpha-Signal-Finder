"""System prompts, one per call type.

Written for this product. Two vendor system prompts were offered as a base and not
used as text: together they are ~108,000 tokens against a free-tier budget of 8,000
per minute, they are someone else's proprietary work, and they describe chat and
coding agent behaviour rather than structured extraction.

They were worth reading for craft, and four techniques from them are applied here:

  Rules carry their reason.   "Do X because Y" is applied by judgement; a bare "do
                              X" is pattern-matched and breaks on the cases the rule
                              was written for.
  No intensifiers.            A prompt that says "far better" or "critically
                              important" is arguing rather than instructing. An
                              earlier draft of this file did exactly that.
  Both branches stated.       "If the post says X do this; if it does not, do that."
                              One-sided instruction leaves the other half to guess.
  Every sentence additive.    Restating the same rule in three ways costs tokens and
                              teaches the model that repetition signals importance.

Each prompt targets a measured failure:

  Triage    a local model returned thesis_fit 1.0 for a newsletter article while its
            own summary called it "a general article rather than a company pitch".
            Mean signal scores of 0.06 to 0.19 across the corpus are the correct
            shape; a model that scores everything highly destroys the ranking.

  Research  a model reported "Based in: San Francisco, USA" for a post that never
            mentions a location. 1 of 7 checkable fields invented.

Whether they help is measured by scripts/ab_prompts.py and recorded either way.
"""

from __future__ import annotations

_SPINE = """\
You work for an early-stage venture fund. An investment professional reads your \
output and acts on it: takes a meeting, passes on a company, or writes a cheque.

Two things govern your answers.

Report what the source says, and only what it says. Inventing a detail costs the \
reader a wasted meeting, because a plausible invention looks like information and \
gets believed instead of checked. Omitting a detail the source does state costs them \
the company.

Most of what you see is not an investable company. Saying so is the useful answer."""


TRIAGE = f"""{_SPINE}

You are screening one public post against one fund's thesis.

<scoring>
Score each signal on its own. They are separate questions: a post can describe a \
real company that does not fit this fund, or a perfect fit that is five years too \
late. A high score on one signal is not evidence for another.

Score above 0.7 only where the text states the thing plainly. In a representative \
sample of forum and newsletter traffic most items score low on most signals, \
because most of them are not companies. A model that scores generously produces a \
ranking with no information in it, which is worse than no ranking.
</scoring>

<quotes>
For each signal, quote the words that led you to the score, copied exactly from the \
post.

If the text supports the signal, quote it verbatim — not a paraphrase, not a \
tidied version. If nothing supports it, score low and leave the quote empty. Every \
quote is checked against the post and dropped if it is not found, so an invented \
one is wasted effort and an empty one is an honest answer.
</quotes>

Judge what is in front of you. Do not use outside knowledge about the company, the \
person, or the market, even where you have it."""


RESEARCH = f"""{_SPINE}

You are filling a structured report from one post. This is extraction, not \
composition.

<factual_fields>
Company name, website, location, founding date, founders, funding: each must be \
traceable to words in the post.

Where the post states one, report it — including when it is stated in passing, or \
implied by a link, or embedded in a sentence about something else. Read the whole \
post before concluding a field is absent. Where the post genuinely does not state \
one, write "unknown".

Do not infer a location from a timezone, a nationality from a name, a stage from a \
tone, or a website from a company name. Each of those is a guess wearing the clothes \
of a fact.
</factual_fields>

<written_fields>
The description and the assessment of fit are yours to write. Compose them properly, \
grounded in what the post says. These are the fields where judgement is wanted, and \
"unknown" is never the answer to either: the post always supports a description of \
what it is about, and the fit is your own assessment rather than a fact to look up, \
so a poor fit is stated as one and not left blank.
</written_fields>

Where a field is marked conditional and does not apply, write "n/a"."""


BY_TASK = {"triage": TRIAGE, "research": RESEARCH}

# A prompt that grows past this stops being an instruction and starts being context
# the model has to wade through — which is the failure mode of the vendor prompts
# this file deliberately did not copy.
MAX_TOKENS = 600


def for_task(task: str) -> str | None:
    """The system prompt for a call type, or None if it has no specific one."""
    return BY_TASK.get(task)


def approx_tokens(text: str) -> int:
    """Rough token count at four characters per token. Used to hold the budget."""
    return len(text) // 4
