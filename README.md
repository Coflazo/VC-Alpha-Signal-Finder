# VC Alpha Signal Finder

Finds early-stage startups before they show up in the places everyone already watches.

Give it a VC thesis in plain English. It reads Reddit, LinkedIn, GitHub, blogs and forums looking for founders and projects that match, scores each one, researches the survivors properly, and writes the results into a Google Sheet in priority order.

The point is coverage without cost. Most signal work either costs a lot (paid data platforms) or misses the early window (news and funding databases only see a company after someone else found it). This sits earlier: a founder complaining about a problem on r/SaaS, a repo that suddenly picks up stars, a person quietly changing their LinkedIn title to "building something new."

## Status

Early. Repo scaffolding and architecture only. No pipeline code yet.

## How it works

Five stages. Each one is cheaper than the next, so expensive work only runs on what survived.

```
1. COLLECT     scrapers pull raw posts, repos, profiles
                     |
2. FILTER      embeddings score each item against the thesis
               (cosine similarity, no LLM call)
                     |
3. TRIAGE      small local model classifies survivors
               is this a startup? what stage? does it fit?
                     |
4. RESEARCH    Claude digs into the shortlist properly
               founders, traction, competitors, why now
                     |
5. WRITE       ranked findings appended to Google Sheets
```

Stage 2 matters more than it looks. Embedding a Reddit post costs roughly nothing and takes milliseconds, and it throws away the 95% of scraped content that has nothing to do with the thesis. Every stage after it only sees candidates that already passed a relevance bar.

### Sources

| Source | What we look for | How we get it |
|---|---|---|
| Reddit | Founders describing problems, launch posts, "I built this" threads | PRAW stream over a watchlist, plus reddapi.dev semantic search |
| GitHub | Repos with unusual star velocity, new orgs, fresh commit history | GitHub Trending, GitHub API |
| LinkedIn | Title changes to founder/stealth, new company pages | Patchright, run from the Mac only |
| Blogs, forums | Build-in-public writeups, Show HN, indie posts | Firecrawl, RSS |

Reddit is the primary source. It is where founders talk before they have anything to announce. A watchlist of subreddits streams continuously, and the system works out which other subreddits are worth adding by looking at where the founders it already liked also post.

LinkedIn runs from the Mac rather than the server, because LinkedIn weights IP reputation heavily and cloud datacenter ranges are the fastest way to get an account flagged. Full design for both in [docs/COLLECTORS.md](docs/COLLECTORS.md).

### Thesis matching

A thesis is a paragraph, not a keyword list. "We back technical founders building developer infrastructure in Europe, pre-seed, ideally before they have a product" has no useful keywords in it.

So the thesis gets embedded once into a vector. Every scraped item gets embedded too. Cosine similarity between them is the first filter. It is crude but it is nearly free, and crude-but-free is what you want when you are scoring a hundred thousand items a week.

The local model handles the judgement the embedding cannot: is this person actually starting a company, or just complaining? Are they pre-seed or Series A? Is this a real product or a weekend project?

## The local model tier

The cheap brain runs on free infrastructure. That constraint drives every model choice here.

Two hosting options, and they are not exclusive:

**GitHub Actions.** 2,000 free minutes a month on a private repo. Good for scheduled scrape-and-score runs. No server to maintain, no uptime to worry about. This is the default.

**Oracle Cloud Always Free.** 4 ARM cores and 24 GB RAM, free with no time limit. No GPU. Worth having if the pipeline needs to run continuously rather than on a schedule, or if you want a persistent Postgres instance.

The Oracle box has no GPU, and that is the number that decides everything else. A normal 7B or 8B model runs at roughly 5 to 12 tokens per second on those cores. Too slow to triage tens of thousands of posts.

The fix is not a smaller model. It is a differently shaped one.

### Models to download

Extraction and judgement are separate jobs, so they get separate models. Pulling a messy page into a typed record is a parsing problem with a known schema. Deciding whether that record matches the thesis is a reasoning problem. A model built for one is not the best choice for the other, and splitting them means both can be small.

| Role | Model | Size | Notes |
|---|---|---|---|
| Embeddings | `Qwen3-Embedding-0.6B` | ~639 MB | Stage 2 filter. 70.7 on MTEB-eng-v2, Apache-2.0. Stage 2 is the one filter nothing downstream can recover from, so it gets the better model rather than the smaller one. |
| Extraction | `Schematron-3B` Q4_K_M | ~2 GB | Purpose-trained for noisy HTML to schema-conformant JSON, 128K context. Turns scraped pages into typed records without CSS selectors that break on every layout change. |
| Triage | `Qwen3.5-4B-Instruct` Q4_K_M | ~2.5 GB | Stage 3 judgement. Best sub-8B model for structured output at 96.60% F1, and 1.7 to 1.8 times faster than Gemma 3 4B which ties it on quality. |
| Hard cases | Groq or Cerebras free tier | — | Escalation for anything triage marks uncertain. Faster and better than any 20B that fits on this hardware. |
| Reranking (optional) | `bge-reranker-v2-m3` | ~2.2 GB | Only if stage 2 precision measures badly. Do not install preemptively. |

```bash
ollama pull qwen3-embedding:0.6b
ollama pull richardyoung/schematron-3b
ollama pull qwen3.5:4b-instruct-q4_K_M
```

Everything local totals about 5 GB, so all three stay resident at once on a 24 GB box.

**Why no 20B or 30B model.** The obvious move is a mixture-of-experts model in the 20B to 30B range, since few active parameters means CPU-friendly speed. It does not survive the benchmarks. Schematron-8B beats GPT-OSS-20B on structured extraction with 2.5 times fewer parameters, and Phi-4 at 14B beats both. Meanwhile GPT-OSS-20B alone would have taken 13 GB, over half the RAM budget. A 30B MoE at Q4 lands near 18 GB and leaves nothing for KV cache at long context.

The conclusion from the structured-output benchmarks is blunt: prompting and constraint strategy matter more than parameter count. So the money goes into the grammar, not the model.

Sources: [LLMStructBench](https://arxiv.org/abs/2602.14743), [Structured Output Benchmark](https://arxiv.org/html/2604.25359v1), [Schematron](https://inference.net/blog/schematron/).

**The thing that actually controls failure rate.** Not model size. Constrained decoding. Run llama.cpp with a GBNF grammar that forces output into the exact JSON schema, and a 4B model produces valid parseable JSON essentially every time. A much larger model writing free-form prose does not. One grammar file is worth more here than ten billion parameters.

```
llama-cli -m qwen3.5-4b-instruct-q4_k_m.gguf --grammar-file schemas/triage.gbnf
```

### Burst capacity

When the queue backs up, overflow to free hosted tiers rather than waiting on CPU:

- Groq free tier (fast, generous daily limits)
- Cerebras free tier
- Gemini Flash free tier

Keep every call behind one function so the tiers stay swappable:

```python
llm_call(prompt: str, schema: dict) -> dict
```

Never call a provider SDK directly from pipeline code.

## Stack

- **C++** for the throughput-sensitive parts: dedup, embedding similarity search, anything that runs over the full corpus.
- **Python** for scrapers, orchestration, LLM calls, Sheets output. Fast to change, and speed does not matter where it is IO-bound anyway.
- **SQLite** for the candidate queue to start. Postgres later only if concurrent writers become a real problem, not before.
- **Frontend** minimal. A single page to review the shortlist and mark hits or misses. That feedback is training data for the scoring model, so it earns its keep.

## Required Claude skills

This is the part that matters when opening this repo on a new machine. Run the install script first, then work.

```bash
./scripts/install-skills.sh
```

Everything it installs, and why:

### Core pipeline

| Skill | Package | Why |
|---|---|---|
| gws-sheets | `googleworkspace/cli@gws-sheets` | Writes findings to Google Sheets. Official Google, 53K installs. |
| data-scraper-agent | `affaan-m/ecc@data-scraper-agent` | Scheduled collection agents that run free on GitHub Actions. Closest existing thing to this product's shape. |
| deep-research | `affaan-m/ecc@deep-research` | Stage 4. Multi-source research with citations. |
| python-patterns | `affaan-m/ecc@python-patterns` | Python idioms and typing discipline. |

### Reddit

| Skill | Package | Why |
|---|---|---|
| reddapi | `lignertys/reddit-research-skills@reddapi` | Semantic search over Reddit, no OAuth needed. |
| reddit-leads | `lignertys/reddit-research-skills@reddit-leads` | Scores posts 0-100 for intent and classifies signal type. Built for B2B lead finding, which is structurally the same problem as founder finding. |
| reddit-search-api | `lignertys/reddit-research-skills@reddit-search-api` | Raw endpoint reference for debugging the integration. |

### Discovery

| Skill | Package | Why |
|---|---|---|
| github-trending | `hoodini/ai-agents-skills@github-trending` | Startups leave GitHub traces before they leave press traces. |

### C++

| Skill | Package | Why |
|---|---|---|
| cpp-coding-standards | `affaan-m/ecc@cpp-coding-standards` | C++ Core Guidelines enforcement. |
| cpp-testing | `affaan-m/ecc@cpp-testing` | GoogleTest and CTest setup, sanitizers, coverage. |

### ML and cost control

| Skill | Package | Why |
|---|---|---|
| mle-workflow | `affaan-m/ecc@mle-workflow` | Reproducible training, evaluation, monitoring, rollback. |
| cost-aware-llm-pipeline | `affaan-m/ecc@cost-aware-llm-pipeline` | Model routing by task complexity and budget tracking. Directly describes the tiered brain above. |
| browser-qa | `affaan-m/ecc@browser-qa` | Visual verification of the review frontend. |

### Already installed, used by this project

These are not in the install script because they were set up separately. If they are missing on a new machine, install them too.

| Skill | Source | Role |
|---|---|---|
| agent-reach | [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach) | Platform router for Reddit, X, LinkedIn, GitHub, RSS. Use this rather than writing per-platform fetch code. Check health with `agent-reach doctor --json`. |
| gstack-browser | `garrytan/gstack` | Headless browser for scraping targets that need JS rendering. |
| ml-skill | personal | Local corpus covering sklearn, evaluation, imbalanced data, time series. |
| minimalist-ui | `leonxlnx/taste-skill` | Frontend direction for the review page. |
| impeccable | `pbakaus/impeccable` | Interface design and audit. |
| latex | personal | Investment memo output, if it ever needs to leave the spreadsheet. |

### Plugins

| Plugin | Marketplace | Role |
|---|---|---|
| superpowers | `claude-plugins-official` | Brainstorming, planning, TDD, debugging workflows. |
| claude-mem | `thedotmack` | Cross-session memory. Lets a new session recall prior work on this repo. |
| clangd-lsp | `claude-plugins-official` | C++ language server. |
| ponytail | `DietrichGebert` | Keeps implementations minimal. |

### MCP servers

| Server | Status | Role |
|---|---|---|
| firecrawl | **Broken, returns 401** | Scraping and search. Needs a fresh API key before it is usable. |
| browserbase | Working | Hosted browser automation. |

## Setup on a new machine

```bash
# 1. skills
./scripts/install-skills.sh

# 2. restart Claude Code so plugins and skills load

# 3. local models
ollama pull qwen3-embedding:0.6b
ollama pull richardyoung/schematron-3b
ollama pull qwen3.5:4b-instruct-q4_K_M

# 4. toolchain
brew install cmake

# 5. credentials (none are committed)
#    - reddapi.dev key
#    - Google service account JSON for Sheets
#    - Firecrawl key, if using Firecrawl
#    - Groq / Cerebras / Gemini keys for burst capacity
```

## Open questions

Things not decided yet, listed so they do not quietly get decided by accident.

- **Firecrawl key is dead.** Either renew it or drop Firecrawl and lean on agent-reach plus Browserbase.
- **GitHub Actions or Oracle VM.** Actions is simpler and probably enough. Oracle only earns its place if the pipeline needs to be continuously resident.
- **Benchmark before committing to a model.** The table above is reasoned from published numbers, not measured on the actual instance. First real task: run a fixed 200-post sample through the triage tier and measure tokens per second and JSON validity rate.
- **LinkedIn scraping is legally and technically fragile.** Rate limits and terms of service both apply. Treat it as a nice-to-have, not a dependency.
- **How thesis feedback loops back.** The review page collects hit/miss labels. Unclear yet whether that retrains the embedding filter, adjusts the triage prompt, or trains a separate classifier.

## Conventions

- Commit after every meaningful change, however small.
- Sole contributor is Coflazo. No co-author trailers.
- Credentials never get committed. `.env` is gitignored and stays that way.
