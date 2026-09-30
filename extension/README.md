# Treeo VC Scout

Treeo VC Scout is a local-first Chrome Manifest V3 extension for evidence-linked founder intelligence. It helps a VC analyst turn a professional profile, pasted text, or public startup proof into a founder score, startup stage estimate, market pain read, Hacker News signal layer, GitHub build proof, YC fit, investor-fit notes, relationship graph, exports, and memo.

It is not a stealth scraper. For LinkedIn-like pages, use manual paste, selected text, visible-page capture after a click, CSV/JSON import, or future approved API adapters. The extension does not bypass access controls, automate browsing, auto-scroll, crawl profiles, copy cookies, or run account actions.

## What It Does

- Captures analyst-approved input from visible page text, selected text, manual paste, CSV, or JSON.
- Stores deals, evidence, claims, scores, graph nodes, settings, and API keys locally in IndexedDB.
- Scores founder likelihood, technical credibility, market pain, market timing, investor fit, urgency, risk, and data quality.
- Uses a multi-pass AI pipeline with mock mode by default and BYOK providers for Groq, Gemini, OpenRouter, or a local OpenAI-compatible server.
- Treats Hacker News as YC's news/community signal layer for Show HN launches, Ask HN pain, developer resonance, objections, and category heat.
- Adds GitHub repository quality checks and curated YC Requests for Startups matching.
- Exports JSON, CSV bundle, XLSX workbook, Markdown memo, HTML memo, graph JSON, graph SVG, and standalone graph HTML.

## Install

```bash
npm install
npm run build
```

Load the extension in Chrome:

1. Open `chrome://extensions`.
2. Enable Developer Mode.
3. Click **Load unpacked**.
4. Select the generated `dist/` directory.

For development rebuilds:

```bash
npm run dev
```

## Use It

### Analyze Pasted Text

1. Open the extension popup.
2. Click **Paste profile text**.
3. Paste a profile, company blurb, public launch text, Hacker News post, or analyst note.
4. Click **Analyze pasted text**.
5. Open the dashboard to review scores, evidence, graph, exports, and notes.

### Analyze A Visible Page

1. Open the page you are permitted to process.
2. Click the extension action.
3. Click **Analyze visible page**.

On LinkedIn-like pages, the extension shows the compliance notice:

> Only analyze data you are permitted to process. This tool does not bypass access controls, automate browsing, or crawl profiles.

### Analyze Selected Text

1. Select the text you want to process.
2. Open the popup.
3. Click **Analyze selected text**.

### Import CSV Or JSON

Use the popup **Import CSV or JSON** button. CSV files can include columns such as `name`, `headline`, `location`, `about`, `company`, `website`, `linkedin_url`, `experience`, `education`, `skills`, and `posts`.

## Public Signal Modules

Public research is off by default. Enable it in **Settings -> Enable public research**.

- **Hacker News radar:** Uses read-only Hacker News and Algolia HN search APIs for YC Hacker News stories and comments.
- **GitHub radar:** Searches public repositories and checks README quality, docs, tests, stars, forks, issues, and recent activity.
- **YC fit:** Matches captured company and product language against curated YC Requests for Startups topics.

The extension does not post, vote, comment, message, or automate account actions on any platform.

## Add API Keys

Open **Settings -> LLM provider router**.

1. Keep **Local-only mode** on for deterministic mock analysis.
2. To use external LLMs, turn local-only mode off.
3. Accept the LLM disclosure.
4. Enable Groq, Gemini, OpenRouter, or localhost.
5. Add the provider API key and model name.

Provider keys are stored locally in the extension's browser storage. The router uses fast/cheap models for extraction-like work and stronger configured providers for reasoning passes, with fallback, cache, rate-limit cooldowns, and circuit breakers.

## Export

Open the dashboard **Exports** tab.

- **JSON:** Full normalized profile map.
- **CSV bundle:** People, companies, relationships, evidence, investor signals, HN signals, GitHub signals, YC fit, and scorecard.
- **XLSX workbook:** Multi-sheet analyst workbook.
- **Memo:** Markdown and HTML.
- **Graph:** JSON, SVG, and standalone HTML.

## Project Structure

- `src/background/service-worker.ts`: capture orchestration, research queue, AI pipeline, graph build, and storage.
- `src/adapters/`: manual paste, CSV import, approved API stub, generic profile normalization, LinkedIn-safe visible capture adapter.
- `src/ai/`: provider router, mock/Groq/Gemini/OpenRouter/local providers, schemas, prompts, and multi-pass pipeline.
- `src/research/`: Hacker News, GitHub, Product Hunt placeholder, YC, source reliability, and query generation.
- `src/graph/`: relationship graph builder and graph exports.
- `src/export/`: CSV, XLSX, JSON, memo, and HTML graph exports.
- `src/db/`: Dexie IndexedDB schema, migration, repositories, and local data deletion.
- `src/popup/main.tsx`: capture console.
- `src/sidepanel/main.tsx`: analyst dashboard.
- `src/options/main.tsx`: privacy, provider, scoring, fund profile, and data controls.

## Verify

```bash
npm run typecheck
npm test
npm run build
```

## Privacy Model

- Local-first storage in IndexedDB.
- User-triggered capture only.
- No hidden network transmission for LLM calls.
- Public research is explicit and disabled by default.
- External LLM calls require provider enablement and disclosure acceptance.
- Delete-all-local-data control in settings.
- Evidence-linked claims and explicit unknowns instead of unsupported facts.
- No sensitive attribute inference, face recognition, or biometric analysis.

## Limitations

- Product Hunt support is a placeholder unless a user supplies a Product Hunt API token and search adapter integration is expanded.
- Public web research is limited to the implemented read-only HN, GitHub, and curated YC modules.
- Graph PNG export is not implemented; use SVG, JSON, or standalone HTML.
- AI output quality depends on the chosen provider and the evidence supplied.
- This is decision support for analysts, not an automated investment decision system.
