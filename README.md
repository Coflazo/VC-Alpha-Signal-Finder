# VC Alpha Signal Finder

Finds early-stage startups before they reach the places every other fund is already watching, and costs nothing to run.

Give it a VC thesis written in plain English. It reads Hacker News, Substack, GitHub, Reddit and LinkedIn looking for founders and projects that match, scores each one, researches the survivors properly, and writes ranked results into a Google Sheet using the exact report format the fund asked for.

**Status:** working spine. Three sources collect live, 565 candidates and 439 graph nodes in the database, 22 tests passing, zero credentials and zero cost so far. Triage, research and output are next.

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
                                                 cost/item    typical survivors
1. COLLECT    graph-walking scrapers                    ~0       100,000/week
                     |
2. FILTER     embed, cosine against thesis vectors     ~0ms         ~5,000
                     |
3. TRIAGE     free-tier LLM, structured output         ~1 call        ~200
                     |
4. RESEARCH   deep multi-source investigation       ~20 calls          ~20
                     |
5. WRITE      ranked rows in the fund's format           —            ~20
```

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

### Stage 3 — Triage

A free-tier LLM answers a structured question per candidate, including the thesis's `hard_signals` explicitly rather than hoping they are inferred.

```json
{
  "is_startup": true,
  "stage": "pre-seed",
  "thesis_match": 0.72,
  "founder_signal": true,
  "reasoning": "Author left an infrastructure job to build this, has a prototype, no funding mentioned.",
  "confidence": 0.81
}
```

Confidence at or above 0.7 is accepted. Below that it escalates to the next provider on the ladder. Still uncertain means a human looks, rather than the system guessing.

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
| **Reddit** | PRAW streaming | **OAuth required** | Public JSON returns 403 and RSS returns an empty body, so there is no anonymous path. Free app registration takes two minutes. |
| **LinkedIn** | Scrapling stealth fetch | session cookie | Highest risk. Runs from a home IP, never a cloud server. |

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

| Model | Time per item | 565 candidates |
|---|---|---|
| `qwen3-embedding:0.6b` | 2.8 s | 27 min |
| `nomic-embed-text` | 2.4 s | 22 min |

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

### On the C++ layer

The original plan put C++ under stage 2's similarity search. Honest reassessment: at 565 candidates, and at 100,000, numpy does this in milliseconds and is far quicker to write.

C++ earns its place when the corpus passes roughly a million vectors and brute-force cosine stops fitting in memory — and the right move then is an approximate index, not hand-rolled loops. It stays on the roadmap with a stated trigger rather than being built before the thing it optimises exists.

---

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
├── frontier.py            score-gated graph expansion, shared by all sources
├── theses.py              thesis configs and report templates
├── llm.py                 free-tier provider ladder, budgets, privacy guard
├── collect.py             collection CLI
├── score_all.py           stage 2 CLI
├── collectors/
│   ├── base.py            CandidateRecord, Collector protocol
│   ├── substack.py        archive + recommendation graph
│   ├── hackernews.py      Algolia search, query → author expansion
│   └── github.py          repo search, query → org expansion
└── enrich/embed.py        embedding and cosine scoring

config/theses/*.yaml       the five funds
docs/PLAN.md               detailed design decisions
docs/COLLECTORS.md         Reddit and LinkedIn collector designs
docs/TOOLCHAIN.md          every skill, plugin and model, with sources
```
