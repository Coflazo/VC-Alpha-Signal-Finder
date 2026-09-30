# Product Transformation Notes

## Current Product

Treeo VC Scout is now an evidence-first founder intelligence extension rather than a LinkedIn-only profile analyzer. It is designed around analyst-controlled capture, local-first storage, deterministic scoring, optional BYOK LLM synthesis, read-only public signal modules, relationship graphing, and exportable diligence artifacts.

## Product Boundary

The extension does not implement stealth scraping, background crawling, auto-scroll harvesting, cookie/session extraction, CAPTCHA bypassing, account automation, or mass profile collection. For LinkedIn-like pages, supported ingestion is limited to manual paste, selected text, visible-page capture after a click, file import, or approved API adapter stubs.

## Implemented Upgrade

- Manifest V3 extension with minimal permissions: `activeTab`, `storage`, `sidePanel`, and `scripting`.
- Typed local data model backed by Dexie IndexedDB.
- Safe capture modes for visible page, selected text, manual paste, CSV import, JSON import, and approved API stubs.
- Multi-pass AI pipeline with Zod validation and mock, Groq, Gemini, OpenRouter, and localhost provider adapters.
- Newion-style provider routing patterns: fallback order, response cache, rate-limit cooldowns, and circuit breakers.
- Deterministic scoring for founder likelihood, stage, technical credibility, market pain, timing, investor fit, outreach urgency, red-flag risk, and data quality.
- Read-only Hacker News, GitHub, and YC signal modules, with public research disabled by default.
- Relationship graph builder with founder, company, HN, GitHub, YC, market, investor, evidence, and risk nodes.
- Analyst dashboard with overview, founder signals, startup analysis, technical diligence, public signals, graph, evidence, exports, and notes.
- Export engine for JSON, CSV bundle, XLSX workbook, Markdown memo, HTML memo, graph JSON, graph SVG, and standalone graph HTML.
- Minimal neutral visual system with restrained accent color and no decorative orb or gradient-heavy background.

## Verification Targets

- `npm run typecheck`: TypeScript type safety.
- `npm test`: scoring, graph, export, and mock provider tests.
- `npm run build`: production extension bundle.
- Manual Chrome load test from `dist/`.

## Remaining Product Gaps

- Product Hunt adapter is scaffolded but not fully wired to a token-backed search flow.
- Graph PNG export is not implemented; SVG, JSON, and HTML graph exports are available.
- Public web research is limited to the read-only HN, GitHub, and curated YC modules.
- The dashboard is single-user local-first; team sync or CRM export should wait for a privacy and data governance review.
