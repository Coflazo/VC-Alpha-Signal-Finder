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

**Conclusion: keep the prompt, and tune it.** It is doing the thing it was written
for, but it is over-warning and suppressing legitimate extraction along with the
guesses. The next revision should keep the anti-invention framing and drop the
repetition that makes the model treat "unknown" as the safe default answer. That is
a measurable change, so it will be measured.

Recorded here rather than quietly re-run until it looked better.

## What is still unmeasured

Stated plainly rather than implied:

- **Stage 4 research** has not been run at scale. The report fields are generated but
  the quality of the research output is unmeasured.
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
