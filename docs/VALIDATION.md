# Validation

Measured, not asserted. Every number here came from running the pipeline on the real
corpus, and the date and sample size are recorded so the claims can be re-checked or
found stale.

## Run of 13 September 2026

| | |
|---|---|
| Corpus | 846 candidates from Hacker News, Substack and GitHub |
| Triaged | 93 |
| Model | `openai/gpt-oss-120b` and `openai/gpt-oss-20b` via Groq free tier |
| Router | LiteLLM with fallback to local Ollama |

### Structured output

| Metric | Result |
|---|---|
| Valid JSON | **93 / 93 (100%)** |
| Signals with a quote | 90 |
| **Quotes fabricated** | **6 (6.7%)** |

Every fabricated quote was caught by checking it against the source text, and none
reached a report. This is why quotes are verified rather than trusted: a fabricated
quote is worse than no quote, because it looks like evidence and so gets believed
instead of checked.

For comparison, a local 1B model measured **11%** fabrication on the same check.

### Score distribution

Mean score per signal across the sample:

| Signal | Mean |
|---|---|
| reachable | 0.189 |
| is_building | 0.148 |
| thesis_fit | 0.127 |
| too_late | 0.124 |
| founder_quality | 0.083 |
| timing | 0.062 |

These are low, and that is the correct result rather than a disappointing one. The
sample is general Hacker News and Substack traffic, most of which is genuinely not a
fundable company. A model returning high scores across this corpus would be
rubber-stamping, and the low `timing` mean in particular is right: almost nobody in
a random sample is raising this week.

### Throughput

Groq's free tier binds on **tokens per minute** (8,000), not requests per day
(1,000). A triage prompt is roughly 1,500 tokens, so sustained throughput is about
five candidates a minute, or 300 an hour, at no cost.

Latency per call, measured:

| Path | Time |
|---|---|
| Groq via LiteLLM | **2.4 s** |
| Local Ollama, 3B, on a 2017 dual-core i5 | 507 s |

## System prompts, A/B on 13 September 2026

Purpose-built system prompts were added for triage and research. The obvious
question is whether they help, and the product already tracks the metric that
answers it, so it was measured rather than assumed. Five Show HN candidates, same
inputs, same model, with and without the research system prompt.

| | Without | With |
|---|---|---|
| Factual claims made | 22 | 11 |
| Of those, invented | 9 | 2 |
| **Invention rate** | **40.9%** | **18.2%** |
| Filled-field rate | 74.0% | 40.0% |
| Latency | 1.3 s | 2.5 s |

**The result is mixed, and the honest reading is not the flattering one.**

The prompt more than halves the invention rate, which is what it was written to do.
But it also makes the model far more conservative, and the arithmetic underneath
matters: without the prompt, 22 claims minus 9 inventions leaves **13 true facts**;
with it, 11 minus 2 leaves **9**. Since `ground_report` removes ungrounded fields
either way, the cautious prompt currently ends up delivering *less* real information
to a partner.

Two things stop that from being a verdict against it. The grounding check is a loose
prefix match, so it catches obvious inventions and certainly misses subtle ones — a
model that guesses more produces undetected errors as well as detected ones, and
only the detected ones appear in that table. And five candidates is a small sample;
the difference between 9 and 13 facts is a handful of fields.

**Conclusion at that point: keep the prompt, and tune it.** It was over-warning —
three separate warnings about guessing in 352 tokens, with a cost attached to
inventing and none attached to omitting, so the model faced a one-way incentive.

### After tuning

The rule was stated once instead of three times, and the missing counterweight added:
omitting something the post does state costs the reader the company. Same five
candidates, same model.

| | Without | With, first version | With, tuned |
|---|---|---|---|
| Invention rate | 36.4% | 18.2% | **15.4%** |
| Filled-field rate | 74.0% | 40.0% | **46.0%** |
| True facts surviving | 14 | 9 | 11 |

Tuning moved both numbers the right way. The prompt now cuts fabrication by
**58%** and recovers some of the lost extraction.

**It still does not flip the net calculation, and that is worth saying plainly.**
After grounding strips unsupported fields, the run without a system prompt delivers
14 real facts against 11 with it. On this evidence the prompt costs net information.

The measurement cannot settle it, for a reason worth stating rather than glossing:
**it can only count the inventions the grounding check catches.** Grounding is a
loose prefix match. Eight detected inventions in the careless arm almost certainly
means undetected ones as well — a plausible founding date that appears nowhere in
the post would pass. Two detected in the careful arm implies fewer hidden ones. So
the true-fact counts above flatter the arm that guesses more.

What is established, across two runs in the same direction: **the prompt trades
recall for precision, reliably.** Whether that trade is worth it depends on how much
one trusts a heuristic grounding check, and the honest answer is not very much. The
prompt stays.

The cheaper improvement is probably not more prompt tuning but better grounding,
since that is deterministic, costs nothing at inference time, and does not halve the
fill rate. Recorded as the next thing to try rather than presented as done.

## Stage 4 over every ranked candidate

The first end-to-end research run across all five funds: 24 ranked candidates, every
one researched, no failures. It produced the artefact the whole pipeline exists to
produce, `data/reports/treeo.csv` and its equivalents, with real company names and
live URLs in the columns rather than empty ones.

Three things went wrong, and finding them is most of what the run was for.

**Thinking ate the answer.** The first attempt failed with `json_validate_failed` and
an empty `failed_generation`. gpt-oss-20b is a reasoning model, and its thinking is
billed against the same output budget as its reply: measured on one research prompt,
4,919 characters of reasoning against 353 of answer. When the thinking ran past the
ceiling the answer came back empty, which a strict schema rejects outright. Setting
`reasoning_effort` to `low` cut a call from 1,486 tokens to 905 and ended the failures
— extraction from a supplied text does not need deliberation. The run went from 4
candidates in 375 seconds with errors to 19 in 90 seconds with none.

**The sentinel was louder than the fact.** Fields blanked by the grounding check were
being written as `unknown (not stated in the source)`. In a spreadsheet column that
reads as noise next to the model's own `unknown`, and both mean the same thing to a
partner. It also inflated the first fill-rate reading, which counted the sentinel as
a filled cell. Now both are `unknown`; which fields were blanked is still returned by
`ground_report`, where it is actually useful.

**Caution leaked into the fields that do not take it.** Six of 23 reports came back
with `description: "unknown"` for posts that plainly described a product. The
description and the fit are written, not extracted, so `unknown` is never right for
them. Saying so explicitly fixed the description immediately — and left fit at 9/15,
because the sentence justified only the description and the model applied it only
there. Naming both took fit to 13/15. Stating one branch of a rule and expecting the
other to follow has now failed twice in this file.

Fill rate for Treeo, 15 candidates, after all three fixes:

| Field | Filled |
|---|---|
| Description | 14/15 |
| Your input (fit) | 13/15 |
| Startup name | 13/15 |
| Website | 10/15 |
| Are they currently raising? | 8/15 |
| Geographic focus | 8/15 |
| Founders' names and contact info | 2/15 |
| Based in | 0/15 |
| Founded in | 0/15 |
| **Overall** | **68/150 = 45%** |

The zeroes are not a bug. Reddit and Hacker News posts rarely state a location or a
founding date, and the prompt forbids inferring one from a timezone or a domain
suffix. A blank there is the honest answer; filling it would mean guessing. The
fields that can be answered from a post — what the company does, whether it fits,
what it is called, where to find it — are answered most of the time.

What this does not measure is whether the filled values are *correct*. Grounding
checks that a claim appears in the source, not that the source was right, and nothing
checks the fit assessments at all, since fit is judgement rather than fact.

## What is still unmeasured

Stated plainly rather than implied:

- **Research quality is unverified.** Stage 4 now runs to completion over every ranked
  candidate, and the fill rates above are real, but no human has read the 24 reports
  and said which are accurate.
- **The stage-2 threshold is still uncalibrated.** It needs roughly 100 human labels
  from the review queue, and those do not exist yet. Everything downstream inherits
  whatever error that threshold carries.
- **Precision and recall are unknown.** Without labels there is no ground truth, so
  no claim is made about how many real founders the pipeline finds or misses.
- **Reddit and LinkedIn have never run live.** Both are code-complete and tested
  against fakes.

## Bugs this validation found

None of these were reachable without a live key, which is the argument for validating
before shipping rather than after.

1. **Retired model name.** The configured Groq model returned 404; the catalogue had
   rotated. The fallback worked but took 507 seconds to reach local inference.
2. **Schema rejected.** Strict structured-output mode requires
   `additionalProperties: false` on every nested object. Every request returned 400.
3. **Rate limits misread, twice.** Headers describing a rolling window were read as a
   daily budget, so the provider was written off for a day after about five calls.
4. **Pacing that did not work**, which is what prompted replacing the hand-rolled
   router with LiteLLM entirely.
