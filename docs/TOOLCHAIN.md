# Toolchain

Every skill, plugin, MCP server, model and CLI this project uses, where each one came from, and where in the pipeline it gets used.

Pipeline stages referenced below:

| Stage | Name | What happens |
|---|---|---|
| 1 | Collect | Scrapers pull raw posts, repos, profiles |
| 2 | Filter | Embedding similarity against the thesis vector |
| 3 | Triage | Local small model classifies survivors |
| 4 | Research | Claude investigates the shortlist |
| 5 | Write | Ranked results appended to Google Sheets |

---

## Claude skills

All installed through the Skills CLI (`npx skills`), which stores them in `~/.agents/skills/` and symlinks them into `~/.claude/skills/`. Re-running an install is safe.

### Required by this project

| Skill | Install | Source repo | Stage | Where it is used |
|---|---|---|---|---|
| `gws-sheets` | `npx skills add googleworkspace/cli@gws-sheets -g -y` | [googleworkspace/cli](https://github.com/googleworkspace/cli) | 5 | The only thing that writes to the output spreadsheet. Handles auth, ranges, append semantics. Official Google, so the API surface tracks the real one. |
| `data-scraper-agent` | `npx skills add affaan-m/ecc@data-scraper-agent -g -y` | [affaan-m/ecc](https://github.com/affaan-m/ecc) | 1 | Reference architecture for the whole collection layer. It builds scheduled collectors that run free on GitHub Actions and write to Sheets, which is structurally this product minus the thesis matching. Read it before writing any scraper. |
| `reddapi` | `npx skills add lignertys/reddit-research-skills@reddapi -g -y` | [lignertys/reddit-research-skills](https://github.com/lignertys/reddit-research-skills) | 1 | Primary Reddit collector. Semantic and vector search over Reddit without Reddit OAuth. Also does subreddit discovery, which is how we find new places to watch. |
| `reddit-leads` | `npx skills add lignertys/reddit-research-skills@reddit-leads -g -y` | same | 1, 3 | Scores posts 0-100 for intent and classifies them (pain_point, solution_request, complaint, feature_request, comparison). Built for B2B sales prospecting, but founder-hunting is the same shape of problem: find someone with a live problem who is about to act on it. Use its scoring as a prior that feeds stage 3. |
| `reddit-search-api` | `npx skills add lignertys/reddit-research-skills@reddit-search-api -g -y` | same | 1 | Bare endpoint reference. Use when debugging the reddapi integration and you need exact field names or error codes, not workflow advice. |
| `github-trending` | `npx skills add hoodini/ai-agents-skills@github-trending -g -y` | [hoodini/ai-agents-skills](https://github.com/hoodini/ai-agents-skills) | 1 | Trending repos and developers. Star velocity on a young repo is one of the earliest public signals a company exists. |
| `deep-research` | `npx skills add affaan-m/ecc@deep-research -g -y` | [affaan-m/ecc](https://github.com/affaan-m/ecc) | 4 | The shortlist investigation. Multi-source synthesis with citations. Note it expects Firecrawl and Exa MCPs, so the Firecrawl 401 blocks part of it. |
| `python-patterns` | `npx skills add affaan-m/ecc@python-patterns -g -y` | same | all | Typing and idiom discipline for the scrapers and orchestration. |
| `cpp-coding-standards` | `npx skills add affaan-m/ecc@cpp-coding-standards -g -y` | same | 2 | C++ Core Guidelines. Applies to the similarity search and dedup code. |
| `cpp-testing` | `npx skills add affaan-m/ecc@cpp-testing -g -y` | same | 2 | GoogleTest and CTest setup, sanitizers, coverage. The C++ layer runs over the entire corpus, so a silent correctness bug there poisons everything downstream. Test it properly. |
| `mle-workflow` | `npx skills add affaan-m/ecc@mle-workflow -g -y` | same | 2, 3 | Data contracts, reproducible training, evaluation, monitoring, rollback. Relevant once the hit/miss feedback from the review page starts training anything. |
| `cost-aware-llm-pipeline` | `npx skills add affaan-m/ecc@cost-aware-llm-pipeline -g -y` | same | 3, 4 | Model routing by task complexity, budget tracking, retry logic, prompt caching. This skill describes the tiered brain directly. Consult it before changing which tier handles what. |
| `browser-qa` | `npx skills add affaan-m/ecc@browser-qa -g -y` | same | 6 | Visual verification of the review frontend after deploys. |

Everything above is installed by `scripts/install-skills.sh`.

### Already present, used by this project

Not in the install script because they were set up outside the Skills CLI. If a new machine lacks them, install them by hand.

| Skill | Source | Stage | Where it is used |
|---|---|---|---|
| `agent-reach` | [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach) (CLI, v1.5.0) | 1 | The platform router. Covers Reddit, Twitter/X, LinkedIn, GitHub, YouTube, RSS and arbitrary URLs behind one interface with backend failover. **Do not write per-platform fetch code.** Run `agent-reach doctor --json` first to see which backend is live for each platform. This is the reason the plan skips installing separate Twitter and LinkedIn skills. |
| `gstack-browser` | [garrytan/gstack](https://github.com/garrytan/gstack) | 1 | Headless browser for pages that need JS execution before content appears. Falls to this when agent-reach and plain HTTP both come back empty. |
| `ml-skill` | Personal (local corpus, ~464 MB) | 2, 3 | sklearn, evaluation, imbalanced data, outlier detection, time series. The candidate set is extremely imbalanced (thousands of posts, a handful of real signals), so the imbalanced-data material is the relevant part. |
| `minimalist-ui` | [leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill) | 6 | Visual direction for the review page. |
| `impeccable` | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | 6 | Interface design and audit for the review page. |
| `design-taste-frontend` | [leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill) | 6 | Frontend implementation taste. |
| `latex` | Personal | 5 | Only if an investment memo ever needs to leave the spreadsheet as a PDF. |
| `karpathy-coder` | Source not recorded locally | all | Guards against overcomplication and unrequested abstraction. |

### Present but unrelated to this project

Listed for completeness so a future session does not wonder whether they matter here. They do not.

`addyosmani-engineer`, `matt-builder`, `research`, `voice` ([brandonwise/humanizer](https://github.com/brandonwise/humanizer)), `humanizer`, `caveman` ([JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman)), `graphify` ([safishamsi/graphify](https://github.com/safishamsi/graphify)), `hooks` ([aaaronmiller/custom-skills](https://github.com/aaaronmiller/custom-skills)), `diagram`, `neilization` ([Coflazo/neilization](https://github.com/Coflazo/neilization)), `teaching-document`, `thesis-uva-economics`, `top-design`, `find-skills` ([vercel-labs/skills](https://github.com/vercel-labs/skills)), plus the Emil Kowalski animation set ([emilkowalski/skills](https://github.com/emilkowalski/skills)) and the rest of the `leonxlnx/taste-skill` design family.

---

## Plugins

Installed with `claude plugin install <name>@<marketplace>`. Marketplaces are added first with `claude plugin marketplace add <github-repo>`.

| Plugin | Marketplace repo | Install | Where it is used |
|---|---|---|---|
| `superpowers` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | `claude plugin install superpowers@claude-plugins-official` | Process skills: brainstorming before building, systematic-debugging when something breaks, test-driven-development, writing-plans. Use brainstorming before any new pipeline stage. |
| `claude-mem` | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | `claude plugin install claude-mem@thedotmack` | Cross-session memory. This is what lets a session on a different machine recall prior decisions on this repo. Search it with the `mem-search` skill before re-deriving anything. |
| `clangd-lsp` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | `claude plugin install clangd-lsp@claude-plugins-official` | C++ language server. Needed for the stage-2 code. |
| `ponytail` | [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) | `claude plugin install ponytail@ponytail` | Keeps implementations minimal. Relevant because this project has many tempting places to over-engineer. |
| `ui-ux-pro-max` | [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | `claude plugin install ui-ux-pro-max@ui-ux-pro-max-skill` | Design system and component guidance for the review page. |
| `vercel-plugin` | [vercel/vercel-plugin](https://github.com/vercel/vercel-plugin) | `claude plugin install vercel-plugin@vercel` | Only if the review page gets deployed to Vercel. Optional. |
| `figma` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | `claude plugin install figma@claude-plugins-official` | Optional. Design handoff. |

Plugin changes need a Claude Code restart before they take effect.

---

## MCP servers

| Server | Status | Where it is used |
|---|---|---|
| Firecrawl | **Broken, HTTP 401** | Blog and article scraping, plus `deep-research` depends on it. Get a key at [firecrawl.dev](https://firecrawl.dev) and update `~/.claude.json`. Until then this is a hole in stage 1 and stage 4. |
| Browserbase | Working | Hosted browser automation. Backup for pages that defeat gstack-browser. |

---

## Models

Run through Ollama during development. Production may use llama.cpp directly for grammar-constrained decoding, which Ollama exposes less directly.

| Model | Pull | Size | Stage | Where it is used |
|---|---|---|---|---|
| `Qwen3-Embedding-0.6B` | `ollama pull qwen3-embedding:0.6b` | ~639 MB | 2 | Embeds the thesis once, then every collected item. Cosine similarity between them is the first filter. 70.7 MTEB-eng-v2, Apache-2.0. Stage 2 is the one gate nothing downstream can recover from, so it gets the stronger model. `nomic-embed-text` (274 MB, 62.28 MTEB) is the fallback if this measures too slow. |
| `Qwen3.5-4B-Instruct` Q4_K_M | `ollama pull qwen3.5:4b-instruct-q4_K_M` | ~2.5 GB | 3 | The triage workhorse. Classifies each survivor: is this a startup, what stage, does it match the thesis, confidence. 25 to 40 tok/s on CPU. Always run with a GBNF grammar. |
| `Schematron-3B` Q4_K_M | `ollama pull richardyoung/schematron-3b` | ~2 GB | 1 | Turns scraped HTML into typed records against a JSON schema. Purpose-trained for exactly this, 128K context. Replaces CSS selectors, which break every time a site ships a layout change. The 8B variant exists for harder pages but the vendor recommends 3B as the default. |
| `bge-reranker-v2-m3` | `ollama pull bge-reranker-v2-m3` | ~2.2 GB | 2 | Optional. Only add this if stage 2 precision measures badly. Do not install it preemptively. |

Deliberately not used: `Qwen3-30B-A3B` and similar 30B-class MoE models. Same appealing shape, but Q4 lands near 18 GB and leaves too little room for KV cache on a 24 GB machine. Revisit if the project ever leaves the free tier.

### Hosted fallbacks

Used when the local queue backs up. All free tiers.

| Provider | Where it is used |
|---|---|
| Groq | Burst triage. Fastest of the three. |
| Cerebras | Second burst option. |
| Gemini Flash | Third. Also what `data-scraper-agent` uses by default for enrichment. |

Every call goes through one `llm_call(prompt, schema)` function. No provider SDK gets imported in pipeline code.

---

## CLIs and system tools

| Tool | Install | Status | Where it is used |
|---|---|---|---|
| `npx skills` | ships with Node | present | Skill package manager. `add`, `update`, `remove`, `find`. |
| `claude` | [claude.com/claude-code](https://claude.com/claude-code) | present | Also manages plugins and marketplaces. |
| `gh` | `brew install gh` | present, authed as Coflazo | Repo operations and GitHub API for the collector. |
| `ollama` | [ollama.com](https://ollama.com) | installed, not running | Local model serving. Start with `ollama serve`. |
| `llama.cpp` | `brew install llama.cpp` | **not installed** | Needed for GBNF grammar-constrained decoding, which is the main lever on output reliability. |
| `cmake` | `brew install cmake` | **not installed** | Required before any C++ work. |
| `uv` | present (0.11.7) | present | Python environment and dependency management. |
| `python3` | present (3.13.5) | present | |
| `node` | present (v20.20.0) | present | |
| `agent-reach` | see skill table | present (v1.5.0) | |

---

## Accounts and credentials

None of these are committed. All are needed before the pipeline runs end to end.

| What | Needed for | Where to get it |
|---|---|---|
| reddapi.dev API key | Stage 1, Reddit collection | [reddapi.dev](https://reddapi.dev) |
| Google service account JSON | Stage 5, Sheets writes | Google Cloud console, enable Sheets API, share the target sheet with the service account email |
| Firecrawl API key | Stage 1 and 4, currently broken | [firecrawl.dev](https://firecrawl.dev) |
| Groq API key | Burst capacity | [console.groq.com](https://console.groq.com) |
| Gemini API key | Burst capacity | [aistudio.google.com](https://aistudio.google.com) |
| GitHub token | Higher API rate limits for repo scanning | `gh auth token`, already authed |
| Oracle Cloud account | Only if choosing the VM over GitHub Actions | [cloud.oracle.com](https://cloud.oracle.com) |
