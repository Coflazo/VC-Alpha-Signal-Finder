# Setup

Everything the product needs from you, what each unlocks, and what works without it.

**Nothing here requires a payment card.** The product is built to cost nothing to
operate, and every credential below is a free tier or a free account.

```bash
uv sync --extra dev
uv run vc-alpha          # http://127.0.0.1:8420
```

That already works. With no credentials at all it collects from Hacker News,
Substack and GitHub, filters, and scores locally through Ollama. The Setup tab in
the app shows the same list below, with live status for each.

---

## Works with nothing configured

| Source | Notes |
|---|---|
| Hacker News | Algolia API, no key, no limit worth planning around |
| Substack | Public archive and recommendation graph |
| GitHub | Anonymous search; uses your `gh` CLI token automatically if you have one |
| WhatsApp | Drop exports in `data/whatsapp/`, they never leave the machine |
| Inbound | Drop `.eml` files or a form CSV in `data/inbound/` |

---

## Inference — pick any, all free, no card

The router tries them in order and fails over when one runs out. Set one and the
product is usable; set three and you will not hit a limit.

| Variable | Where | Free allowance |
|---|---|---|
| `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | 1,500 requests/day. Also used for embeddings. |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | 1,000 requests/day, very fast |
| `CEREBRAS_API_KEY` | [cloud.cerebras.ai](https://cloud.cerebras.ai) | 1M tokens/day |
| `GITHUB_MODELS_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens) | Free within limits, no new signup |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) | 50 requests/day |

**Without any of these**, triage falls back to local Ollama. That works, but
measured on a 2017 dual-core i5 a trivial reply took 31 seconds from a 1B model and
131 seconds from a 3B, and the 1B fabricated 1 of 9 supporting quotes. Local proves
the pipeline; it is not a working default. One free key changes that entirely.

```bash
export GEMINI_API_KEY=...      # or put it in .env, which is gitignored
```

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

```bash
export REDDIT_CLIENT_ID=...
export REDDIT_CLIENT_SECRET=...
uv sync --extra reddit
```

Unlocks the Reddit collector, the subreddit watchlist, and discovery of new
subreddits from the co-posting graph.

---

## Google Sheets — for writing findings and editing them in the app

1. In [Google Cloud](https://console.cloud.google.com), create a project and enable
   the **Google Sheets API**
2. Create a **service account** and download its JSON key
3. Save it as `config/service-account.json` (gitignored)
4. Create a sheet, and **share it with the service account's email address** — this
   is the step people miss
5. Copy the sheet id from its URL, the long string between `/d/` and `/edit`

```bash
export VC_ALPHA_SHEET_ID=...
uv sync --extra sheets
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
2. Copy the `li_at` cookie from developer tools

```bash
export LINKEDIN_SESSION_COOKIE=...
uv sync --extra enrich
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
WhatsApp and inbound processed without anything leaving the machine.

---

## Scheduled runs — free

GitHub Actions runs collection, scoring and reporting on a schedule. Free and
unmetered on a public repository; 2,000 minutes a month on a private one.

Add `GEMINI_API_KEY`, `GROQ_API_KEY` and `CEREBRAS_API_KEY` as repository secrets.
All are optional and the workflows degrade rather than fail without them.

Substack, WhatsApp, LinkedIn and inbound are deliberately excluded from CI: the
first is IP-blocked on datacenter ranges and the rest are private or risky. They run
from the app on your machine.

---

## Summary

| Thing | Cost | Unlocks | Works without? |
|---|---|---|---|
| One inference key | free | Fast, reliable triage | Yes, slowly, via Ollama |
| Reddit OAuth app | free | The Reddit collector | No |
| Google service account | free | Sheets read and write | Yes, CSV instead |
| LinkedIn cookie | free | The LinkedIn collector | No |
| Ollama | free | Fully offline operation | Yes, if you have a key |
