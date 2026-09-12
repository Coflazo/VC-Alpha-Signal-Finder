# VC Alpha Signal Finder

An evaluation engine for early-stage venture, that costs nothing to run.

Give it a thesis written in plain English. It reads Hacker News, Substack, GitHub, Reddit, LinkedIn, WhatsApp exports and your own inbound, assembles what it finds into founder and company dossiers, scores each against your thesis with the evidence attached, and writes ranked results into a Google Sheet in the format your fund actually asked for.

**Status:** working end to end. Six sources, 846 candidates, 1,076 entity mentions, 139 tests passing. Zero credentials and zero cost so far.

### Why an evaluation engine and not another sourcing tool

From a 2026 review of the deal-sourcing market: *"Most venture capital firms do not lack access to companies. They lack the analyst bandwidth to evaluate them systematically. The bottleneck these tools collectively do not solve is evaluation."* A $200M fund takes 3,000 inbound enquiries a year and closes ten.

Harmonic and Specter are enterprise-priced, track growth velocity and team pattern-matching, and still leave that gap. Competing on "find companies sooner" means losing to funded data pipelines. Competing on "decide faster, with evidence" is open, and that is what this is built for — which is also why it takes your own inbound, not only what it scrapes.

---

## Why this exists

Startup discovery tools mostly sit in one of two places, and both miss the window.

Paid data platforms (PitchBook, Crunchbase, Dealroom) are accurate and expensive, but they are downstream. A company appears once it has raised, been covered, or filed something. By then it has been found.

News and funding databases have the same problem in cheaper form. A funding announcement is a record that somebody else got there first.

The window this targets is earlier and noisier: a founder complaining on r/SaaS about a problem they are about to go build, a repo under a three-week-old org whose stars are climbing, a Show HN post at 40 points, a person quietly changing their title to "building something new". None of that is in a database. All of it is public.

The reason nobody does this cheaply is that the signal-to-noise ratio is brutal. Reading everything is expensive, and hundreds of thousands of posts a week is well past what a person or a paid LLM budget can absorb. This system's answer is a cost ladder: every stage is cheaper than the one after it, so expensive work only ever touches what already survived something cheaper.

---

## How it works

Five stages. Cost per item rises at every step, and volume falls faster.

```
                                                    cost/item   survivors
1. COLLECT    graph-walking sources + your inbound         ~0    100,000/wk
                     |
2. FILTER     cheap predicates: age, job ads, questions   ~µs       ~93,000
                     |
3. EMBED      cosine against thesis + founder-voice       ~ms        ~5,000
                     |
4. TRIAGE     six weighted signals, each with a quote  ~1 call         ~200
                     |
5. RESOLVE    mentions collapse into founders/companies    ~0          ~120
                     |
6. WRITE      ranked dossiers in the fund's format          —          ~20
```

Filtering sits **before** embedding, not after. Scoring is the expensive stage, so
dropping the ineligible first is the cheapest win available — a rule taken from the
six-stage ranking pattern popularised by xAI's open-sourced For You algorithm.

The numbers are illustrative, not measured; the shape is the point. **Stage 2 does the real work.** Embedding a post costs milliseconds and no tokens, and it discards the overwhelming majority of what was collected. Everything after it operates on a set small enough to afford.

### Stage 1 — Collect

Sources are walked as graphs, not scraped as lists. See [The frontier](#the-frontier) below.

**In:** a set of seed nodes. **Out:** `CandidateRecord` rows, deduplicated on `source_url`.

### Stage 2 — Filter

1. Apply each thesis's `exclude` terms as plain string gates. A hard exclude must never cost an embedding, let alone an inference call.
2. Embed `raw_text`.
3. Cosine against every active thesis vector.
4. Keep the best score and which thesis produced it.
5. Drop anything below threshold.

**The threshold is the most consequential number in the system.** A candidate dropped here is never seen again by any later stage. Too high and real signal dies where nothing can rescue it; too low and stage 3 drowns and burns the daily free allowance. It currently sits at 0.35, which is a guess, and calibrating it against hand-labelled data is the single highest-leverage task outstanding.

### Stage 4 — Triage, as six separate questions

One "relevance" score conflates things that are genuinely different: a post can be a
real company that does not fit this fund, or a perfect fit that is five years too
late. So the model scores each independently, and each fund holds its own weights.

| Signal | Question |
|---|---|
| `is_building` | Is a real company being built, rather than discussed? |
| `thesis_fit` | Does it match this fund's thesis? |
| `founder_quality` | Relevant experience, prior shipped work, felt the problem? |
| `timing` | Raising, or about to? |
| `reachable` | Is there a route to them? |
| `too_late` | Already raised past this stage? *(subtracts)* |

**Behaviour changes by editing numbers in a YAML file.** Nothing is retrained and no
fund's tuning affects another's. Measured on the same two candidates: 212, which
demands demonstrated traction, rates an idea-stage company 0.500; e2vc, which invests
pre-product, rates it 0.675.

Every signal must return the verbatim quote behind it, and **quotes are checked
against the source text**. A fabricated quote is worse than none, because it looks
like evidence and gets trusted instead of checked. Measured on real local-model
output: 11% fabrication caught and dropped.

### Stage 5 — Dossiers, not posts

Team is the strongest early-stage predictor: 95% of 885 institutional VCs called it
essential, and relevant prior experience and shared work history are what separate
top performers. So the unit that gets ranked is the **person or company**, assembled
from every mention across every source.

A founder on Hacker News, in a Substack piece and in a WhatsApp group is one dossier
with three pieces of evidence. Corroboration across independent sources raises the
score, saturating at 1.25 so a prolific poster cannot outrank a good company.

Resolution merges on identifiers, flags name-only matches for a human, and **never
merges two things carrying conflicting identifiers** — Acme Security and Acme
Analytics stay apart. A wrong merge silently corrupts a dossier a partner then acts
on; a duplicate is merely untidy.

### Stage 4 — Research

Only the shortlist. For each survivor: who the founders are and what they did before, whether a product exists and who uses it, who else is doing this, why now, and any funding history the earlier stages missed.

Person-level deduplication happens here, not at stage 1. The same founder appearing on Reddit, HN and Substack is three independent pieces of evidence at collection time, and one research document at this point.

### Stage 5 — Write

Appended to Google Sheets, ordered by score. Never rewritten, because a human editing the status column must not have their work destroyed by the next run. `sheet_row` tracks what has already been written.

```
score = 0.3 * similarity          (stage 2 cosine)
      + 0.5 * thesis_match        (stage 3 judgement)
      + 0.2 * recency_decay(posted_at)
```

Those weights are a starting guess, to be refitted once enough `was_good` labels exist.

### Stage 6 — Review

One page listing candidates with two buttons: good, or not. That is the entire feature set. It exists to produce `was_good` labels, which are what let the threshold and the score weights be fitted rather than guessed. Any feature that does not serve that is out of scope.

---

## The frontier

The design insight that removed most of the work: **every source is the same problem.** A graph of nodes you visit, each yielding candidates and pointing at neighbours.

| Source | Node | How it expands | Risk |
|---|---|---|---|
| Substack | publication | `/api/v1/recommendations/from/{id}` | None. Public, free, an intended feature. |
| Hacker News | query, then author | queries expand to the people who answered them | None. |
| GitHub | query, then org | queries expand to the organisations behind matching repos | None. |
| Reddit | subreddit | co-posting graph of authors who already scored well | Low. Free OAuth. |
| LinkedIn | person | "People also viewed" | **High.** Hard budget required. |

So there is one `frontier.py` and the collectors stay thin. Each implements two methods: `seeds()` and `visit(node)`.

### Why expansion is score-gated

Only nodes that produced good candidates get to add their neighbours.

This is a **quality** mechanism before it is a safety one. Expand blindly from a founder's LinkedIn and you reach their recruiters and university classmates within two hops. Expand blindly from a startup newsletter and you arrive at cooking newsletters. Gating on measured yield is what keeps a crawl on-thesis.

Two details that matter:

- **New nodes get the benefit of the doubt.** One hit in two posts is not a 50% hit rate, it is noise. A node is only judged after `min_seen_before_gating` observations.
- **Rejection is a soft delete.** Deactivating a node preserves its hit-rate history and stops discovery from re-suggesting something already turned down.

Discovery suggestions are ranked by **measured** hit rate. A model can explain why a node looks promising, but the ordering comes from what it actually produced. Live proof: four seed newsletters produced 92 posts and discovered 78 further publications in one pass, reaching `andrewchen`, `The VC Corner` and `speedrun` within a single hop.

---

## Sources

| Source | Endpoint | Auth | Notes |
|---|---|---|---|
| **Hacker News** | `hn.algolia.com/api/v1/search_by_date` | none | The best first-hand source. A Show HN post is a founder describing their own work before any press exists. |
| **Substack** | `/api/v1/archive`, `/api/v1/recommendations/from/{id}` | none | Public archive only. Custom domains 301 away from `*.substack.com`. |
| **GitHub** | `/search/repositories`, `/orgs/{org}/repos` | optional | Works anonymously; reuses the `gh` CLI token for a higher limit if present, never prompts. |
| **Reddit** | PRAW | **OAuth required** | Public JSON returns 403 and RSS returns an empty body, so there is no anonymous path. Free app, two minutes. |
| **WhatsApp** | export files | none | Your own group exports. Nothing leaves the machine. |
| **Inbound** | `.eml` / CSV folder | none | Your own deal flow. The bottleneck the research identified. |
| **LinkedIn** | Scrapling stealth | session cookie | Highest risk. Home IP only, 40/day, stops on first challenge. |

### Where each source runs

Three cannot run on a shared runner, for different reasons, so the local app is the
product rather than a viewer bolted onto a pipeline elsewhere.

| Runs in CI | Local only |
|---|---|
| Hacker News, GitHub, Reddit | Substack (403s datacenter IPs), WhatsApp (private), Inbound (private), LinkedIn (ban risk) |

### Warm paths

For any dossier: who do we already know who is near this person — a shared WhatsApp
group, the same subreddit, the same GitHub org. Harmonic and Specter cannot do this,
because it needs membership in your own communities. Computed locally, never
transmitted, and stated as an observation ("is in your Founders TR group") rather
than a claimed relationship.

Live sample from Hacker News, showing the signal is genuinely first-hand:

```
I built an App to give alerts when your dependencies (Postgres) reach EOL
I built a browser and HTTP client together from scratch for pentesting
```

---

## Zero cost, and what that actually costs

The product must be free to operate. Not cheap, zero. Here is how each layer gets there and what the trade is.

### Inference

Free tiers, no credit card, rotated by `vc_alpha/llm.py`.

| Provider | Free allowance | Position |
|---|---|---|
| Google Gemini Flash | 1,500 requests/day | Primary |
| Groq (llama-3.3-70b) | 1,000 req/day, 100K tokens/day | Fast short calls |
| Cerebras | 1M tokens/day | Overflow |
| GitHub Models | free within limits | Overflow, no new signup |
| OpenRouter free models | 50 req/day | Last resort |
| Ollama, local | unlimited | Offline fallback |

Roughly **3,000 classifications a day at zero cost**. Stage 2 cuts volume long before any of this is reached.

The router tracks each provider's daily usage in SQLite so counts survive restarts, and treats a 429 as better evidence than its own counter, since calls may have come from another machine.

### The honest caveat about free inference

**Free tiers generally train on what you send them.** For a tool whose whole value is proprietary deal flow, that is a real cost, just not a monetary one.

The mitigation is enforced in code, not documented and hoped for. `Router.complete()` takes a required `public_text` argument and raises `PrivateTextRefused` otherwise. Only text that was already published by someone else goes out. Thesis prose, match reasoning and assembled reports never leave the machine.

The reasoning: a Reddit post anyone can read is not the asset. The asset is the aggregation, the scoring against a private thesis, and the ranked shortlist. Those stay local. A fund uncomfortable even with public text leaving can point one config value at a paid or local endpoint, and nothing else in the codebase changes.

### Compute

GitHub Actions is **free and unmetered on public repositories**, on 4 vCPU / 16 GB Ubuntu runners. Private repos get 2,000 minutes a month, around 66 minutes a day, which is enough for scheduled collection. Oracle Cloud Always Free (4 ARM cores, 24 GB, no time limit) is the option if the pipeline ever needs to be persistently resident rather than scheduled.

### Measured performance, and why local models are not the default

Benchmarked on the development machine, an **Intel Core i5-7360U, 2 cores, 2017, no usable GPU offload** (`ollama` reports `offloaded 0/13 layers to GPU`):

| Task | Model | Time per item |
|---|---|---|
| Embedding | `qwen3-embedding:0.6b` | 2.8 s |
| Embedding | `nomic-embed-text` | 2.4 s |
| Triage (trivial reply) | `llama3.2:1b` | 31 s |
| Triage (trivial reply) | `qwen2.5:3b` | 131 s |

Those triage numbers are for a throwaway two-field reply. A real screening prompt
needs minutes per candidate, so **local triage is a fallback of last resort on
hardware like this, not a working default.** Groq answers the same prompt in under
a second, free. This is the clearest argument for the free-tier ladder: it is not
only cheaper than local, it is the difference between the stage running and not.

Input length barely changed the result, so this is compute-bound rather than token-bound. The original design put a local model tier first specifically to avoid API cost. Since free hosted inference exists and is faster, local-first was paying latency to solve a problem that was already solved. Ollama stays last on the ladder for offline work.

---

## Theses

A thesis is two things in one file: the prose stage 2 embeds and matches against, and the report template the fund expects at the end. Both live in `config/theses/*.yaml`.

```yaml
id: treeo
name: Treeo VC

prose: >
  We back immigrant founders building AI-native B2B companies at pre-seed and
  seed. Founders who moved countries and are building for a global market...

exclude: [recruitment agency, dropshipping, crypto trading bot]

hard_signals:                 # put to the triage model explicitly
  - Founder is an immigrant or has moved countries to build this
  - Product is AI-native rather than AI bolted onto an existing product
  - The US is on their horizon as a market

report_fields:                # exactly what this fund asked for
  - key: startup_name
    label: "Startup name"
  ...
```

Five funds are configured: **Treeo VC**, **Revo Capital**, **212**, **e2vc** and **Earlybird**. They are real, researched theses, and they double as the test set precisely because they disagree with each other.

Each shares a common report core, then adds what its own thesis turns on:

| Fund | Its own questions |
|---|---|
| Treeo | Immigrant founder status, US on the horizon |
| Revo | Which Türkiye link applies (founders or R&D), technical depth |
| 212 | Traction evidence, PMF evidence — this thesis fails without them |
| e2vc | Why this founder (at idea stage that *is* the investment), global from day one |
| Earlybird | Category, and the technical moat |

**Three of the five turn on something keyword search cannot see**: founder origin, immigrant status, pre-category timing. That is the gap the embedding and LLM stages exist to close. Had all five been "fintech in Germany", a keyword filter would have been the honest answer and this architecture would be overbuilt.

Every candidate is scored against all active theses and keeps its best match. Rescraping per thesis would be absurd.

---

## Data model

SQLite, WAL mode. Three tables.

**`candidates`** — one row per discovered thing. `id` is the sha256 of `source_url`, which is also uniquely constrained, so reruns are free. Columns fill in left to right as a row moves through the stages: `embedding`/`similarity`/`thesis_id` at stage 2, `triage_json`/`is_startup`/`confidence` at stage 3, `research_md` at 4, `score`/`sheet_row` at 5, `reviewed`/`was_good` at 6.

`retention_until` is present from the first migration rather than bolted on later, and `forget_author()` is a single function so a deletion request has exactly one code path.

**`nodes`** — the frontier, across every source. Carries `depth`, `parent`, `source_kind` (seed/discovered/manual), `active`, `exhausted`, and the `seen_count`/`hit_count` pair that gating and suggestion ranking both read.

**`author_activity`** — which authors appear where. This is what Reddit's co-posting discovery and LinkedIn cross-seeding are built on.

**`llm_usage`** — per-day, per-provider request and failure counts, so free allowances are tracked across restarts and machines.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+, `uv` | The whole pipeline is IO-bound |
| HTTP | `httpx` | Substack, HN and GitHub return clean JSON; a scraping framework on top would be ceremony |
| Anti-bot fetching | [Scrapling](https://github.com/D4Vinci/Scrapling) (BSD-3) | Tiered HTTP → stealth → browser, Cloudflare handling, and `adaptive=True` selectors that relocate elements after a redesign |
| HTML to text | [Crawl4AI](https://github.com/unclecode/crawl4ai) (Apache-2.0) | Clean markdown with noise filtering |
| Reddit | PRAW | `subreddit.stream.submissions()` pushes new posts instead of polling |
| Storage | SQLite | Postgres only if concurrent writers become a real problem |

**Deliberately not used: Firecrawl and Maxun.** Both are AGPL-3.0, which is viral over *network* use, so building on them would force this project open the moment it is exposed to anyone. That is a licensing decision, not a quality one; Firecrawl is excellent software.

### Performance

Three things dominate wall clock at scale. Everything else is IO-bound and would
gain nothing from being rewritten.

| Path | Before | After | Change |
|---|---|---|---|
| Entity resolution | **O(N²)** — 31 ms/mention at 4k entities | indexed lookup, 0.46 ms | **68×**, and flat |
| Cosine over stored vectors | pure Python, 987 ms per 2k×1024 | C++ on packed blobs, 23 ms | **43×** |
| MinHash | pure Python | C++ | **279×** |
| Near-duplicate detection | didn't exist; naive is O(N²) | MinHash + LSH, O(N) | linear, verified |

The entity-resolution one was a live bug, not an optimisation: `resolve()` scanned
every existing entity on every mention. At 50,000 entities it would have taken hours.

Cosine needed two attempts. The obvious binding — pass a list of lists — measured
only **2×**, because converting 2000×1024 Python floats into an array costs more
than the arithmetic. The bottleneck was marshalling, not maths. Reading the packed
float32 blobs SQLite already returns skips creating those objects at all.

Every C++ function has a pure-Python twin. The twins are the specification the tests
compare against, the fallback for machines with no compiler, and the readable
statement of intent when the C++ is wrong.

---

## Installing

Runs entirely on your machine. Nothing is transmitted to anyone — no telemetry, no
licence server, no phone-home. **You are the data controller; we never receive your
data.** See [PRIVACY.md](PRIVACY.md).

```bash
./install.sh          # or: pipx install vc-alpha
vc-alpha              # opens http://127.0.0.1:8420
```

Docker, for firms whose IT policy prefers it:

```bash
docker build -t vc-alpha . && docker run -p 8420:8420 -v $(pwd)/data:/app/data vc-alpha
```

Optional speed, once, if you have a compiler:

```bash
uv run python scripts/build_ext.py    # 43x on cosine, 279x on MinHash
```

It works without it. The pure-Python fallback is transparent.

### Adding your fund

Open the **Setup** tab, paste the paragraph you already use to describe your fund,
and it writes a commented config you can then edit. No YAML by hand.

## Setup

```bash
git clone git@github.com:Coflazo/VC-Alpha-Signal-Finder.git
cd VC-Alpha-Signal-Finder
uv sync --extra dev

# Collect. No credentials needed for these three.
uv run python -m vc_alpha.collect --source hackernews --visits 5
uv run python -m vc_alpha.collect --source substack   --visits 5
uv run python -m vc_alpha.collect --source github     --visits 5

# What the graph found, ranked by measured hit rate
uv run python -m vc_alpha.collect --suggestions substack

# Score against the theses
uv run python -m vc_alpha.score_all --thesis treeo --top 15

uv run pytest
```

### Optional credentials, all free

| Variable | From | Unlocks |
|---|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | Primary inference and embeddings |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | Fast inference |
| `CEREBRAS_API_KEY` | [cloud.cerebras.ai](https://cloud.cerebras.ai) | Overflow inference |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | reddit.com/prefs/apps, script type | The Reddit collector |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Cloud, Sheets API enabled | Sheets output |

None require a credit card. Without any of them, collection and stage 2 still run against local Ollama.

---

## Privacy and legal

This processes personal data, and the theses target European founders, so GDPR applies.

Legitimate interest is a workable basis for B2B research, and it comes with obligations that are built in rather than promised: collect only fields used for scoring, set a retention period and enforce it with a real deletion job, and be able to erase an individual on request through one function. Public posts are still personal data once tied to an identifiable person; being public changes the expectation of privacy, not whether the regulation applies.

**Scope limits held deliberately:**

- Public content only. Paywalled Substack posts stay paywalled.
- LinkedIn is read-only: profiles and articles, no messaging, no connection requests, no feed interaction.
- No credential sharing, no access-control circumvention.
- LinkedIn runs at a hard daily cap with jitter, and stops on the first soft block rather than retrying.

---

## Open questions

Written down so they do not get decided by accident.

- **The stage-2 threshold is uncalibrated.** 0.35 is a guess. Roughly 100 hand-labelled candidates would replace it with a number that has precision and recall attached. Highest-value hour available.
- **Free tiers train on submitted data.** Mitigated by the public-text rule, not eliminated. A fund may reasonably want a paid endpoint.
- **LinkedIn is legally and technically fragile.** Treated as a nice-to-have that must never break a run.
- **How feedback loops back.** `was_good` labels could retune the threshold, adjust the triage prompt, or train a separate classifier. Undecided, and should stay undecided until there are labels.
- **Public or private repo.** Public converts GitHub Actions from 2,000 minutes a month to unlimited, at the cost of publishing the code.

---

## Layout

```
vc_alpha/
├── db.py                  schema, retention, forget_author
├── filters.py             cheap predicates, run before embedding
├── frontier.py            score-gated graph expansion, shared by all sources
├── theses.py              thesis prose, founder voice, weights, report fields
├── signals.py             the six signals and per-fund weighting
├── entities.py            people and companies, resolution rules
├── extract.py             mentions from URLs, orgs and authors — no model calls
├── founders.py            entity scoring, corroboration, quote verification
├── warmpath.py            who you already know who is near this person
├── llm.py                 free-tier ladder, budgets, privacy guard
├── redact.py              fragment extraction for private sources
├── triage.py  score.py  pipeline.py  calibrate.py
├── collectors/            substack, hackernews, github, whatsapp, inbound,
│                          reddit, linkedin — one protocol, seven sources
├── enrich/embed.py        multi-vector matching, rank gating
└── app/                   FastAPI + one page: dashboard, dossiers, review,
                           reports, sheet, setup

config/theses/*.yaml       five real funds, each with its own weights and report
SETUP.md                   exactly what you need to supply, all of it free
docs/                      PLAN, COLLECTORS, TOOLCHAIN
```

## The quantitative models

Four places used a plausible constant where the problem has a known structure.
Each model states its assumptions and is tested against a closed form or Monte
Carlo, because the only reason to put mathematics here is that it is right.

### Winner's curse — what a signal is worth after accounting for who else sees it

Deal allocation is a **common-value auction**: every fund observes
*s<sub>i</sub> = V + ε<sub>i</sub>* and the founder takes the best offer. Conditional
on winning, your signal was the maximum of N noisy draws, so it was biased upward:

```
bias(N, ρ) = β · σ_e · √(1−ρ) · E[max of N standard normals]
```

| Source | Audience | ρ | Penalty |
|---|---|---|---|
| WhatsApp | 3 | 0.10 | 0.089 |
| Inbound | 8 | 0.20 | 0.140 |
| Hacker News | 200 | 0.60 | 0.192 |

A public lead must score about **0.10 higher** to match a private one. That is the
arithmetic reason to read private communities, and it is a statement about order
statistics rather than taste.

Correlation between rivals' errors **reduces** the curse: the common shock moves
everyone together and confers no advantage in winning, so only the idiosyncratic
part, scaled √(1−ρ), can mislead the winner. At ρ = 1 there is no curse at all.

The textbook asymptotic √(2 ln N) was tried and rejected — against 40,000-trial
Monte Carlo it errs by up to 0.25 and is worst at small N, giving 0.597 against a
true 0.846 at N = 3. Every audience here is 3 to 200, so it is wrong exactly where
the product operates. The integral is computed directly instead.

### Adverse selection — which channel a founder is in is itself a signal

A founder who can raise through introductions generally does, so open channels are
drawn from a truncated part of the distribution, with the shortfall given by the
inverse Mills ratio λ(z) = φ(z)/Φ(z).

Cold inbound scoring as adversely selected is not a modelling artefact: it is the
warm-introduction doctrine stated as arithmetic. The correction is capped below
0.10 because it rests on a separating equilibrium that founders who build in public
on purpose simply break.

### Value of information — the review queue was sorted wrong

With payoff R, loss L and threshold τ = L/(R+L):

```
EVPI(p) = pR        for p < τ
          (1−p)L    for p ≥ τ
```

A tent peaking **exactly at the decision boundary**, zero at both ends. Reviewing
your top candidate teaches you nothing — you would pursue it anyway. The queue
orders by expected value of sample information instead. The most informative score
to review measures 0.57, whose posterior is 0.0327 against a threshold of 0.0323.

### Tails and portfolio size — where the usual tools stop working

Venture multiples are Pareto with α ≈ 1.5–2.5. **Below α = 2 the variance does not
exist**, so Sharpe ratios, mean-variance optimisation and normal confidence
intervals are undefined rather than merely inaccurate. Tail index comes from the
Hill estimator over the upper order statistics.

Expected fund-returners go as *p̄ · n<sup>1−α</sup>*, so with α > 1 the mathematics
favours **concentration**, and adding ranking noise does not flip it. Real funds
hold 20 to 40 positions because a seed company can only absorb so much capital —
a capacity constraint, not portfolio theory. The useful question is therefore what
screening is worth at the size a fund must hold anyway: at n = 20, perfect
screening lifts P(fund returned) by **+265%** over none.

### Deployment — the acceptance bar should fall as the fund ages

With *m* slots and *k* expected arrivals, this is the sequential assignment problem
of Derman, Lieberman and Ross:

```
V(k, m) = E[ max( X + V(k−1, m−1),  V(k−1, m) ) ]
accept when  X ≥ V(k−1, m) − V(k−1, m−1)
```

The threshold is the option value of holding a slot. It falls as the window closes,
falls as slots accumulate, and **rises with deal flow** — better sourcing should
make a fund *more* selective, not less. Computed live from the pipeline's own score
distribution and shown on the dashboard.

Not the 1/e secretary rule, which is the no-information variant where only relative
ranks are observed.

## The app

```bash
uv run vc-alpha            # http://127.0.0.1:8420
```

Six screens. **Dashboard** with corpus counts and run controls. **Dossiers**, where
each founder shows why they scored what they scored, with the quote behind every
signal and a link to where it was said. **Review**, two buttons, which is what turns
the stage-2 threshold from a guess into a measured number. **Reports** per fund in
that fund's columns. **Sheet**, editable in place and written straight back.
**Setup**, which lists exactly what is still missing.
