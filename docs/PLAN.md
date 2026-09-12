# Plan

The detailed version. README has the overview; this has the decisions.

## What counts as a signal

A signal is evidence that a company exists or is about to, before that evidence reaches a place VCs already monitor. Concretely:

- A founder describing a problem they are building a solution to, in first person, with specifics
- A launch post on a niche subreddit rather than Product Hunt
- A repo under a brand-new org that gains stars unusually fast for its age
- A LinkedIn title change to founder, co-founder, or stealth
- A build-in-public writeup on a personal blog with no funding announcement attached

Not signals: funding announcements, press coverage, accelerator batch lists, anything already aggregated. By the time those exist, the window is closed.

## The thesis object

A thesis is stored as a document, not a query.

```json
{
  "id": "thesis_dev_infra_eu",
  "name": "European dev infrastructure, pre-seed",
  "prose": "We back technical founders building developer infrastructure in Europe at pre-seed, ideally before they have a product. We care about founders who have felt the problem themselves, usually at a previous engineering job.",
  "must_have": ["technical founder", "developer tooling or infrastructure"],
  "exclude": ["agency", "consultancy", "crypto trading"],
  "geo": ["EU", "UK", "CH"],
  "stage_max": "seed",
  "embedding": [0.0123, -0.0455, ...]
}
```

`prose` is what gets embedded. `must_have` and `exclude` are cheap string gates applied before embedding, because a hard exclude should never cost an inference call. `embedding` is computed once and cached, recomputed only when `prose` changes.

Supporting multiple theses is the point. A fund has more than one, and the same scraped corpus should be scorable against all of them without rescraping.

## The candidate record

One row per discovered thing, stored in SQLite.

```sql
CREATE TABLE candidates (
  id              TEXT PRIMARY KEY,     -- hash of source_url
  source          TEXT NOT NULL,        -- reddit | github | linkedin | blog
  source_url      TEXT NOT NULL UNIQUE,
  raw_text        TEXT NOT NULL,
  author          TEXT,
  discovered_at   TIMESTAMP NOT NULL,
  posted_at       TIMESTAMP,

  embedding       BLOB,                 -- stage 2
  similarity      REAL,                 -- best cosine across active theses
  thesis_id       TEXT,                 -- which thesis it matched best

  triage_json     TEXT,                 -- stage 3 raw model output
  is_startup      INTEGER,              -- 0/1
  stage_guess     TEXT,                 -- idea | prototype | pre-seed | seed | later
  confidence      REAL,                 -- 0..1

  research_md     TEXT,                 -- stage 4
  score           REAL,                 -- final ranking score
  sheet_row       INTEGER,              -- stage 5, null until written

  reviewed        INTEGER DEFAULT 0,    -- human feedback
  was_good        INTEGER               -- null | 0 | 1
);

CREATE INDEX idx_pipeline ON candidates(similarity, is_startup, reviewed);
```

`source_url` is the dedup key. The same founder posting to three subreddits produces three rows, and that is correct: three independent pieces of evidence. Deduplication by person happens at stage 4, not stage 1.

`was_good` is the whole feedback loop. Everything the review page collects lands there.

## Stage detail

### Stage 1, Collect

Runs on a schedule. Writes rows with everything after `posted_at` left null.

Cadence per source, chosen so the free tiers hold:

| Source | Frequency | Volume per run |
|---|---|---|
| Reddit, watched subreddits | every 6 hours | a few hundred posts |
| Reddit, semantic search per thesis | daily | ~100 per thesis |
| GitHub trending | daily | ~100 repos |
| GitHub new-org scan | weekly | varies |
| LinkedIn | weekly, small batches | tens |
| Blogs and RSS | daily | varies |

Every collector goes through `agent-reach` where a backend exists for the platform. Direct HTTP only for RSS and plain pages.

LinkedIn is deliberately the smallest and least frequent. It is the most fragile source both technically and under terms of service. If it breaks, the pipeline must keep working without it.

### Stage 2, Filter

The cheap gate. No LLM calls.

1. Apply `exclude` string gates. Drop matches.
2. Embed `raw_text` with `nomic-embed-text`.
3. Cosine against every active thesis embedding.
4. Keep the best score and which thesis produced it.
5. Drop anything below threshold.

The threshold is the single most important tuned number in the system. Start at 0.35 and calibrate against a hand-labelled set, because the right value depends on the thesis prose and cannot be guessed. Too high and real signals die here where nothing downstream can rescue them. Too low and stage 3 drowns.

This is where C++ earns its place. Embedding every item is IO-bound and fine in Python, but similarity search across the full corpus, plus near-duplicate detection, runs over everything repeatedly.

### Stage 3, Triage

The local model. Every call uses a GBNF grammar, no exceptions.

Output schema:

```json
{
  "is_startup": true,
  "stage": "pre-seed",
  "thesis_match": 0.72,
  "founder_signal": true,
  "reasoning": "Author says they left their infra job to build this, has a prototype, no funding mentioned.",
  "confidence": 0.81
}
```

Routing:

- `confidence >= 0.7` accept the answer, done
- `confidence < 0.7` re-run on `gpt-oss-20b`
- still uncertain, mark for human review rather than guessing

`reddit-leads` scoring, where the item came from Reddit, feeds in as a prior. A post it scores 90 for intent starts with a thumb on the scale.

### Stage 4, Research

Only the shortlist. Expensive and worth it.

For each candidate that survives stage 3, establish: who the founders are and what they did before, whether a product exists and who uses it, who else is doing this, why now, and whether there is any funding history the earlier stages missed.

Person-level deduplication happens here. Three rows about the same founder collapse into one research document with three pieces of supporting evidence.

Uses `deep-research`, which wants Firecrawl and Exa. The Firecrawl 401 partially blocks this stage.

### Stage 5, Write

Append to Google Sheets, ordered by `score` descending.

Column layout:

| Column | Contents |
|---|---|
| A | Date discovered |
| B | Company or project name |
| C | Founder name |
| D | Source link |
| E | Stage guess |
| F | Thesis matched |
| G | Score |
| H | One-line summary |
| I | Research notes |
| J | Status (blank, then filled by a human) |

Appending only, never rewriting. A human editing column J must never have their work overwritten by the next run. `sheet_row` on the candidate record tracks what has already been written.

Final score combines the three earlier judgements:

```
score = 0.3 * similarity
      + 0.5 * thesis_match
      + 0.2 * recency_decay(posted_at)
```

Weights are a starting guess. Recalibrate once there are enough `was_good` labels to fit them properly.

### Stage 6, Review

One page. A list of candidates, each with its summary and research notes, and two buttons: good or not.

That is the entire feature set. It exists to produce `was_good` labels, and any feature that does not serve that is out of scope.

## Repo layout

```
.
├── CLAUDE.md              read first on a new machine
├── README.md              overview
├── docs/
│   ├── PLAN.md            this file
│   └── TOOLCHAIN.md       every source, where each is used
├── scripts/
│   └── install-skills.sh
├── collectors/            stage 1, python
├── core/                  stage 2, c++
├── triage/                stage 3, python + gbnf grammars
├── research/              stage 4
├── output/                stage 5, sheets writer
├── web/                   stage 6, review page
└── schemas/               gbnf grammars and json schemas
```

## Build order

Each milestone ends somewhere useful, so the project survives being put down for a week.

1. **One source, end to end.** Reddit only, one thesis, no local model. Collect, embed, filter, write straight to Sheets. Proves the spine works. No triage yet.
2. **Add triage.** Ollama plus a GBNF grammar. Measure tokens per second and JSON validity on a fixed 200-post sample before trusting it.
3. **Add research.** Claude on the shortlist. Person-level dedup.
4. **Add sources.** GitHub, then blogs, then LinkedIn last.
5. **Move C++ under stage 2.** Only when the Python version is measurably too slow. Not before.
6. **Review page.** Once there is enough output to be worth reviewing.
7. **Feedback loop.** Use accumulated `was_good` labels to recalibrate the threshold and the score weights.

Resist building 5 before 1 works. The C++ layer is the most interesting part and the least urgent.

## Things that will go wrong

Written down now so they are not surprises later.

- **The threshold will be wrong at first.** Plan to hand-label a hundred items early. There is no shortcut.
- **Reddit rate limits.** reddapi.dev abstracts this but does not remove it. Back off properly.
- **LinkedIn will break.** Assume it, and make sure nothing downstream depends on it.
- **The local model will produce confident nonsense on ambiguous posts.** That is what the confidence threshold and the second tier are for. Do not raise the acceptance threshold to make the numbers look better.
- **Free tiers change.** GitHub Actions minutes, Groq limits, Oracle capacity. Keep the `llm_call` abstraction honest so swapping a provider is a one-file change.
- **Oracle reclaims idle Always Free instances.** If using the VM, keep a heartbeat job running.
