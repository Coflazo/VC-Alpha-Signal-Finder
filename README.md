# VC Alpha Signal Finder

An evaluation engine for early-stage venture, that costs nothing to run.

Give it a thesis written in plain English. It reads Hacker News, Substack, GitHub, Reddit, LinkedIn, WhatsApp exports and your own inbound, assembles what it finds into founder and company dossiers, scores each against your thesis with the evidence attached, and writes ranked results into a Google Sheet in the format your fund actually asked for.

**Status:** working end to end, and installable by someone who is not the author.
Seven sources, 846 candidates, 375 tests passing. Every credential is free and
entered in the app rather than exported in a shell. Zero cost so far.

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

Eight stages. Cost per item rises at every step, and volume falls faster.

```
                                                    cost/item   survivors
1. COLLECT    graph-walking sources + your inbound         ~0    100,000/wk
                     |
2. FILTER     cheap predicates: age, job ads, questions   ~µs       ~93,000
                     |
3. EMBED      cosine against thesis + founder-voice     ~12ms        ~5,000
                     |
4. TRIAGE     six weighted signals, each with a quote  ~1 call         ~200
                     |
5. RESOLVE    mentions collapse into founders/companies    ~0          ~120
                     |
6. RESEARCH   the shortlist only, opt-in              ~5 calls          ~40
                     |
7. WRITE      ranked dossiers in the fund's format          —          ~20
                     |
8. REVIEW     two buttons, and the labels feed 3 back       —           —
```

Filtering sits **before** embedding, not after. Scoring is the expensive stage, so
dropping the ineligible first is the cheapest win available — a rule taken from the
six-stage ranking pattern popularised by xAI's open-sourced For You algorithm.

The survivor counts are illustrative; the shape is the point. The cost figures are
measured. **Stage 3 does the real work**: at 12ms an item it discards the
overwhelming majority of what was collected, and everything after it operates on a
set small enough to afford. The loop from 8 back to 3 is what stops stage 3's
threshold being a guess.

### Stage 1 — Collect

Sources are walked as graphs, not scraped as lists. See [The frontier](#the-frontier) below.

**In:** a set of seed nodes. **Out:** `CandidateRecord` rows, deduplicated on `source_url`.

### Stage 2 — Filter

Cheap string predicates: age, job ads, pure questions, and each thesis's `exclude`
terms. A hard exclude must never cost an embedding, let alone an inference call.
The reason is recorded rather than the row deleted, so over-filtering is visible
instead of silent.

### Stage 3 — Embed

1. Embed `raw_text` against the best available provider.
2. Cosine against every active thesis vector, in both the fund's own words and the
   same thesis as a founder would write it.
3. Keep the best score and which thesis produced it.
4. Drop anything below the threshold.

**The threshold is the most consequential number in the system.** A candidate
dropped here is never seen again by any later stage. Too high and real signal dies
where nothing can rescue it; too low and stage 4 drowns and burns the daily free
allowance. It is fitted from your own review decisions — see
[Calibration](#calibration).

Which embedding provider is configured is the single biggest lever on how long a
run takes. Measured: **12.5 ms an item** hosted, against **2,400 ms** on a 2017
dual-core i5 locally. The ladder is Mistral, then Cohere, then Gemini, then local
Ollama, and the local rung is the only one private sources are ever given to.

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

### Stage 6 — Research, on the shortlist only

Opt-in, because it costs several calls a candidate. For each survivor: who the
founders are and what they did before, whether a product exists and who uses it,
who else is doing this, why now, and any funding history the earlier stages
missed. Every field is checked back against the source text and dropped if it is
not supported, so the report understates rather than invents.

### Stage 7 — Write

Appended to Google Sheets, ranked. Never rewritten, because a partner editing the
status column must not have their work destroyed by the next run. `sheet_row`
tracks what has already gone out.

```
score = w_similarity   * similarity        (stage 3 cosine)
      + w_thesis_match * thesis_match      (stage 4 judgement)
      + w_recency      * recency_decay(posted_at)
```

The weights start at 0.3 / 0.5 / 0.2 and stop being a guess as soon as there are
enough review decisions to fit them. See **Calibration** below.

### Stage 8 — Review

One page, two buttons: good, or not for us. That is the entire feature set.

It exists to produce labels, and those labels are now read. `vc-alpha calibrate
fit` turns them into the stage-2 threshold and the three score weights, and the
Review screen shows how many more are needed before it can.

## Calibration

**The threshold was the largest open question in the product and it is now
closed.** Stage 3 drops whatever scores below it, and nothing downstream can
recover a candidate dropped there, so the number matters more than anything else
here. It shipped at 0.35, guessed.

Measured on the live corpus, the median candidate scored 0.381 — so that "gate"
was passing roughly 60% of everything collected. Not a filter, a formality.

```bash
vc-alpha calibrate distribution   # where your scores actually sit
vc-alpha calibrate fit            # fit the threshold and weights to your reviews
vc-alpha calibrate show           # what is in force, and where it came from
```

Three things worth knowing:

- **It refuses below 40 labels.** A threshold fitted from a dozen clicks carries
  the authority of "measured" with the variance of a guess. The refusal tells you
  how many more are needed.
- **It optimises F2, not F1.** F1 treats a false positive and a false negative as
  equally costly. They are not: reading a dud wastes a minute, missing a founder
  means the round closes without you. F2 weights recall twice as heavily.
- **A threshold belongs to an embedding model.** Providers score on completely
  different scales — an unrelated sentence reaches 0.567 against a thesis under
  `mistral-embed`. The model is recorded with the fit, and a mismatch falls back
  to the default rather than silently applying the wrong bar.

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

Every model id below was checked against a live call on **14 September 2026**.
This list has rotted before — two of the ids previously shipped here now return
404 — so each is overridable by environment, and the "you need a key" message is
built from the ladder rather than typed out, so it cannot name a dead provider.

| Provider | Model | Measured | Free allowance |
|---|---|---|---|
| Groq | `openai/gpt-oss-120b` | 4.8s | 1,000 req/day, binds on 8K tokens/min |
| Mistral | `ministral-8b-latest` | **0.41s** | generous per minute; also does embeddings |
| Google Gemini | `gemini-2.0-flash` | — | 1,500 req/day |
| NVIDIA NIM | `nemotron-3-super-120b` | 4.6s | free credits |
| OpenRouter | a rotating `:free` model | 29s | 50 req/day |
| Ollama, local | your choice | 507s | unlimited, and the only private-safe rung |

Groq leads because it is the only rung with measured evidence on this corpus —
100% valid JSON across 93 triage calls. Mistral is ten times faster and is what
actually carries a long run, because Groq's ceiling is tokens per minute, not
requests per day, so a sustained pass throttles there and falls through.

**Cerebras and SambaNova are listed in the code but answered "payment required"
on a free key.** They are kept as rungs for a fund holding a paid key, placed
below everything verified working, and cost one failed call that falls through.

### Embeddings

A separate ladder, because stage 3 runs over *everything* and is the one place
the product cannot afford to be slow.

| Provider | Model | Dimensions | Measured |
|---|---|---|---|
| Mistral | `mistral-embed` | 1024 | **12.5 ms/item** at batch 64 |
| Cohere | `embed-v4.0` | 1536 | comparable |
| Google Gemini | `text-embedding-004` | 768 | — |
| Ollama, local | `qwen3-embedding:0.6b` | 1024 | 2,400 ms/item |

NVIDIA is deliberately absent: its embedding endpoints answered 410 Gone on every
published model id, and listing a rung that does not exist is worse than omitting
it.

Which vectors came from which model is recorded per row. Cosine between different
dimensionalities is defined as zero by both implementations, so without that, a
change of provider would silently drop every older candidate to 0.0 similarity —
reading as "nothing matches any more" rather than "these need re-embedding".

The router tracks each provider's daily usage in SQLite so counts survive restarts, and treats a 429 as better evidence than its own counter, since calls may have come from another machine.

### The honest caveat about free inference

**Free tiers generally train on what you send them.** For a tool whose whole value is proprietary deal flow, that is a real cost, just not a monetary one.

The mitigation is enforced in code, not documented and hoped for. `Router.complete()` takes a required `sending` classification — `PUBLIC`, `REDACTED` or `PRIVATE` — and refuses the last outright. The judgement belongs with the caller, who knows the source; classifying a WhatsApp message as public because it was convenient is exactly how private conversation ends up in someone's training set. Only text somebody else already published goes out. Thesis prose, match reasoning and assembled reports never leave the machine, and private sources are embedded locally regardless of which keys are set.

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

A thesis is two things in one file: the prose stage 3 embeds and matches against, and the report template the fund expects at the end. Yours live in `~/.vc-alpha/config/theses/*.yaml`, or in `config/theses/` when running from a checkout; five worked examples ship in `examples/theses/`.

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

**`candidates`** — one row per discovered thing. `id` is the sha256 of `source_url`, which is also uniquely constrained, so reruns are free. Columns fill in left to right as a row moves through the stages: `embedding`/`embedding_model`/`similarity`/`thesis_id` at stage 3, `triage_json`/`is_startup`/`confidence` at stage 4, `research_md` at 6, `score`/`sheet_row` at 7, `reviewed`/`was_good` at 8 — and those last two feed back into stage 3's threshold. `retention_until` is set at collection and enforced by a deletion job that actually runs.

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

Run it from anywhere. An installed copy keeps its database, theses and keys in
`~/.vc-alpha`; run it from a checkout and it uses the checkout instead, so
development and an install do not fight over the same files. `$VC_ALPHA_HOME`
overrides both.

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

A fresh install ships with no thesis. Open the **Setup** tab, paste the paragraph
you already use to describe your fund, and it writes a commented config you can
then edit. No YAML by hand.

Five real funds ship in `examples/theses/` as worked examples, including one whose
report columns were specified by the fund itself. Copy one into your config
directory if you would rather start by editing than by writing.

### Adding your keys

Also the **Setup** tab. Each free provider has a field, a link to the page that
issues the key, and a **Test** button that spends one call proving it works — a
key that is present but wrong is worse than a missing one, because the product
reports itself configured and then fails somewhere less visible.

Keys are written to `~/.vc-alpha/.env` at mode 0600 and are never shown again. If
you would rather use environment variables, those still win over the file.

## Setup

```bash
git clone git@github.com:Coflazo/VC-Alpha-Signal-Finder.git
cd VC-Alpha-Signal-Finder
uv sync --inexact --extra dev

vc-alpha status                    # what is configured, and what has been found
vc-alpha collect hackernews        # no credentials needed for hn, substack, github
vc-alpha score                     # stage 3, against every fund you have added
vc-alpha run                       # stages 4 to 7
vc-alpha report treeo              # or open the app and read it there

vc-alpha calibrate distribution    # where your scores actually sit
vc-alpha calibrate fit             # replace the guessed threshold with a fitted one

vc-alpha forget "name"             # erase one person, on request
vc-alpha purge                     # delete everything past its retention date

uv run pytest
```

Every command takes `--json`. `vc-alpha` with no arguments opens the app, which is
what someone typing the bare command almost certainly wanted.

### Optional credentials, all free

Enter these in the **Setup** tab rather than here; the variable names are listed
because environment variables still work and still take precedence.

| Variable | From | Unlocks |
|---|---|---|
| `MISTRAL_API_KEY` | [console.mistral.ai](https://console.mistral.ai) | **Inference and embeddings.** The one to set first. |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | Inference, the rung with measured evidence |
| `COHERE_API_KEY` | [dashboard.cohere.com](https://dashboard.cohere.com) | Embeddings, if you would rather not use Mistral |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | Both, 1,500 req/day |
| `NVIDIA_NIM_API_KEY` | [build.nvidia.com](https://build.nvidia.com) | Inference, the largest model on the ladder |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | reddit.com/prefs/apps, script type | The Reddit collector |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Google Cloud, Sheets API enabled | Sheets output |

None require a credit card. Without any of them, collection and stage 3 still run
against local Ollama — correctly, but at 2,400 ms an item against 12.5 ms, which is
the difference between a run you wait for and a run you leave.

**Set one key and the product is usable. Set two and you will not hit a limit.**

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

- **Free tiers train on submitted data.** Mitigated by the public-text rule, not eliminated. A fund may reasonably want a paid endpoint.
- **LinkedIn is legally and technically fragile.** Treated as a nice-to-have that must never break a run.
- **The free tiers keep moving.** Two model ids shipped here have already been retired, and two providers withdrew their free tier. Every id is overridable by environment for exactly this reason, but it wants checking every few months rather than assuming.
- **Whether the fitted weights survive contact with a second fund.** The threshold and score weights are now fitted per installation. Whether one fund's fitted numbers generalise to another is unknown and should stay unknown until more than one fund has labelled anything.
- **Public or private repo.** Public converts GitHub Actions from 2,000 minutes a month to unlimited, at the cost of publishing the code.

Closed since the last revision: **the stage-2 threshold**, which was the largest of
these. It is fitted from review decisions rather than guessed — see
[Calibration](#calibration).

---

## Layout

```
vc_alpha/
├── paths.py               where this installation keeps its data, decided once
├── env.py                 reads the .env the Setup screen writes
├── secrets.py             keys in, never out; 0600; whitelisted names only
├── db.py                  schema, retention job, complete erasure
├── filters.py             cheap predicates, run before embedding
├── frontier.py            score-gated graph expansion, shared by all sources
├── theses.py              thesis prose, founder voice, weights, report fields
├── signals.py             the six signals and per-fund weighting
├── entities.py            people and companies, resolution rules
├── extract.py             mentions from URLs, orgs and authors — no model calls
├── founders.py            entity scoring, corroboration, quote verification
├── warmpath.py            who you already know who is near this person
├── llm.py                 free-tier ladder, budgets, privacy guard
├── calibrate.py           review labels → threshold and score weights
├── redact.py              fragment extraction for private sources
├── triage.py  score.py  pipeline.py  onboard.py
├── collectors/            substack, hackernews, github, whatsapp, inbound,
│                          reddit, linkedin — one protocol, seven sources
├── enrich/embed.py        embedding ladder, multi-vector matching, rank gating
└── app/                   FastAPI + one page: dashboard, dossiers, review,
                           reports, sheet, setup

examples/theses/*.yaml     five real funds, as worked examples to copy
~/.vc-alpha/               your own data, config and keys, when installed
SETUP.md                   exactly what you need to supply, all of it free
docs/                      PLAN, COLLECTORS, TOOLCHAIN, VALIDATION, MCP
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

Six screens, and nothing in them needs a terminal.

**Dashboard** — corpus counts, run controls, and how selective you should be right
now given the capital and time you have left. On a fresh install it leads with the
one thing you have to do first.

**Dossiers** — each founder shows why they scored what they scored, with the quote
behind every signal and a link to where it was said. Quotes are verified against
the source text, so a fabricated one is dropped rather than shown.

**Review** — two buttons, and a counter showing how close those clicks are to
replacing the guessed threshold with a fitted one. Ordered by expected value of
information, not by score: reviewing the top-ranked candidate teaches you almost
nothing, because you were going to pursue it either way.

**Reports** — per fund, in that fund's own columns.

**Sheet** — your Google Sheet, editable in place and written straight back. The
pipeline only ever appends, so your notes are never overwritten.

**Setup** — every free credential with somewhere to paste it and a button that
tests it, your fund's thesis from a paragraph of plain English, what this computer
can run locally, and the privacy controls: what the retention period is, what is
about to expire, and a way to erase one person on request.
