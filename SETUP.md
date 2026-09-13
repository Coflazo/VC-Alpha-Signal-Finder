# Setup

Everything the product needs from you, what each unlocks, and what works without it.

**Nothing here requires a payment card.** The product is built to cost nothing to
operate, and every credential below is a free tier or a free account.

```bash
./install.sh             # or: uv sync --inexact --extra dev
vc-alpha                 # opens http://127.0.0.1:8420
```

Then do two things, both in the **Setup** tab:

1. **Describe your fund.** Paste the paragraph you already use. It writes a
   commented config you can edit later. A fresh install has no thesis, and nothing
   downstream can run without one.
2. **Paste one API key.** Any of the ones below. Each has a **Test** button that
   spends one call proving it works.

That is the whole setup.

### Where your data lives

An installed copy keeps everything in `~/.vc-alpha` — the database, your theses,
your keys. Run it from a git checkout and it uses the checkout instead, so
development and an install do not fight over the same files. `$VC_ALPHA_HOME`
overrides both.

Keys are saved to `~/.vc-alpha/.env` at mode `0600` and are never displayed again.
Environment variables still work and take precedence over the file, which is what
CI and `GROQ_API_KEY=... vc-alpha run` rely on.

### Three ways to use it

| | For whom |
|---|---|
| `vc-alpha` | The app, in a browser. No terminal knowledge needed. |
| `vc-alpha status`, `collect`, `score`, `run`, `report` | A terminal, for anyone who prefers one. |
| **Claude or Codex, over MCP** | **Ask questions in plain English and let the assistant drive.** See [docs/MCP.md](docs/MCP.md). |

Run `vc-alpha --help` for the full list. Every command takes `--json`.

---

## Works with nothing configured

| Source | Notes |
|---|---|
| Hacker News | Algolia API, no key, no limit worth planning around |
| Substack | Public archive and recommendation graph |
| GitHub | Anonymous search; uses your `gh` CLI token automatically if you have one |
| WhatsApp | Drop exports in `~/.vc-alpha/data/whatsapp/`, they never leave the machine |
| Inbound | Drop `.eml` files or a form CSV in `~/.vc-alpha/data/inbound/` |

---

## Inference — pick any, all free, no card

The router tries them in order and fails over when one runs out. Set one and the
product is usable; set two and you will not hit a limit.

Every model id below was checked against a live call on 14 September 2026.

| Variable | Where | Free allowance | Measured |
|---|---|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | 1,000 req/day | 4.8s |
| `MISTRAL_API_KEY` | [console.mistral.ai](https://console.mistral.ai) | generous per minute | **0.41s** |
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | 1,500 req/day | — |
| `NVIDIA_NIM_API_KEY` | [build.nvidia.com](https://build.nvidia.com) | free credits | 4.6s |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | 50 req/day | 29s |

Groq leads because it is the rung with measured evidence on this corpus: 100% valid
JSON across 93 triage calls. Mistral is ten times faster and takes over on a long
run, because Groq's real ceiling is tokens per minute rather than requests per day.

**Cerebras and SambaNova are still in the code but both answered "payment required"
on a free key.** They sit below everything verified working, so an unusable key
costs one failed call that falls through rather than a broken run.

**Without any of these**, triage falls back to local Ollama. That works, but measured
on a 2017 dual-core i5 a trivial reply took 31 seconds from a 1B model and 507
seconds from a 3B, and the 1B fabricated 1 of 9 supporting quotes. Local proves the
pipeline; it is not a working default. One free key changes that entirely.

## Embeddings — the one that decides how long a run takes

A separate ladder, because this stage runs over **everything**.

| Variable | Model | Measured |
|---|---|---|
| `MISTRAL_API_KEY` | `mistral-embed` | **12.5 ms/item** |
| `COHERE_API_KEY` | `embed-v4.0` | comparable |
| `GEMINI_API_KEY` | `text-embedding-004` | — |
| none — local Ollama | `qwen3-embedding:0.6b` | 2,400 ms/item |

That is a 190x difference on the stage that touches every candidate, which is why
`MISTRAL_API_KEY` is the single most useful key to set: it covers both ladders.

NVIDIA is not offered here. Its embedding endpoints answered 410 Gone on every
published model id.

**If you change embedding provider, re-score.** Vectors from different providers
have different dimensionalities and are not comparable. The product records which
model produced each vector and re-embeds rather than silently scoring them zero,
but it has to actually run to do that — and any fitted threshold needs re-fitting
afterwards, because providers put their cosines on completely different scales.

### A note on what leaves the machine

Free tiers generally train on what you send them. The router therefore requires
every caller to classify what it is sending, and refuses private text outright.
Public posts go out; your thesis prose, WhatsApp messages and assembled reports do
not. WhatsApp and inbound are embedded locally regardless of which keys are set.

If you want nothing at all leaving the building, run only Ollama and accept the
speed.

---

## Reddit — two minutes, free

Reddit has no anonymous path: its JSON endpoints return 403 and the RSS feeds come
back empty. It needs a free OAuth app.

1. Go to [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps)
2. Create an app, choose **script**
3. Set the redirect URI to `http://localhost:8080` (unused, but required)

Paste the client id and secret into the Setup tab, then:

```bash
uv sync --inexact --extra reddit
```

Unlocks the Reddit collector, the subreddit watchlist, and discovery of new
subreddits from the co-posting graph.

---

## Google Sheets — for writing findings and editing them in the app

1. In [Google Cloud](https://console.cloud.google.com), create a project and enable
   the **Google Sheets API**
2. Create a **service account** and download its JSON key
3. Save it as `~/.vc-alpha/config/service-account.json`
4. Create a sheet, and **share it with the service account's email address** — this
   is the step people miss
5. Copy the sheet id from its URL, the long string between `/d/` and `/edit`, and
   paste it into the Setup tab

```bash
uv sync --inexact --extra sheets
```

The Sheet tab then shows the sheet as an editable table. Edits write straight back.
The pipeline only ever appends, so your notes are never overwritten.

---

## LinkedIn — optional, and the one with real risk

LinkedIn weights IP reputation heavily. This collector refuses to run in CI and is
capped at 40 profiles a day with 30 to 60 seconds of jitter, stopping entirely on
the first challenge page.

**Use a secondary account, not your own.** Assume it will eventually be flagged.

1. Log into LinkedIn in a browser
2. Copy the `li_at` cookie from developer tools into the Setup tab

```bash
uv sync --inexact --extra enrich
```

---

## Local models — optional

```bash
ollama serve
ollama pull qwen3-embedding:0.6b     # embeddings, 639 MB
ollama pull llama3.2:1b              # fast fallback triage
export OLLAMA_MODEL=llama3.2:1b      # on slow hardware
```

Only needed if you want the product to work with no API keys at all, or if you want
WhatsApp and inbound processed without anything leaving the machine. The Setup tab
will install and pick a model sized to your machine for you.

---

## Calibrating it to your own judgement

The matching threshold decides what survives to be triaged, and nothing downstream
can recover a candidate it drops. It starts as a guess.

Review candidates in the app — two buttons, good or not for us — and the Review
screen counts toward the point where it can be fitted instead:

```bash
vc-alpha calibrate distribution    # where your scores actually sit
vc-alpha calibrate fit             # fit it to your own decisions
```

It refuses below 40 labels, and says how many more are needed. The button on the
Review screen does the same thing.

---

## Scheduled runs — free

GitHub Actions runs collection, scoring and reporting on a schedule. Free and
unmetered on a public repository; 2,000 minutes a month on a private one.

Add whichever keys you have as repository secrets. All are optional and the
workflows degrade rather than fail without them.

Substack, WhatsApp, LinkedIn and inbound are deliberately excluded from CI: the
first is IP-blocked on datacenter ranges and the rest are private or risky. They run
from the app on your machine.

---

## Deleting things

Required if you operate under GDPR, and built in rather than promised:

```bash
vc-alpha forget "person name"        # shows what would go
vc-alpha forget "person name" --yes  # erases it everywhere
vc-alpha purge                       # delete everything past its retention date
```

Retention is 365 days and the deletion job runs when the app starts and before
every run. The same controls are on the Setup tab. See [PRIVACY.md](PRIVACY.md).

---

## Summary

| Thing | Cost | Unlocks | Works without? |
|---|---|---|---|
| One inference key | free | Fast, reliable triage | Yes, slowly, via Ollama |
| **`MISTRAL_API_KEY`** | free | **Both ladders at once — set this one first** | Yes, 190x slower |
| Reddit OAuth app | free | The Reddit collector | No |
| Google service account | free | Sheets read and write | Yes, CSV instead |
| LinkedIn cookie | free | The LinkedIn collector | No |
| Ollama | free | Fully offline operation | Yes, if you have a key |
| ~40 review clicks | free | A fitted threshold instead of a guess | Yes, on the default |
