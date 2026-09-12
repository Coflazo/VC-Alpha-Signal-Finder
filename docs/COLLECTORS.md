# Collectors

Design notes for the two hard sources. Reddit and LinkedIn both have existing open-source prior art, and both were studied before writing anything. This records what was taken, what was rejected, and why.

---

## Reddit

The primary source. Founders talk on Reddit before they have a website, a LinkedIn title, or anything to announce.

### What it needs to do

1. Watch a list of subreddits continuously and feed new posts into the pipeline
2. Let the list be edited by hand, adding and removing subreddits at any time
3. Work out which other subreddits are worth watching, and say why

### Prior art studied

| Repo | Stars | License | What was taken |
|---|---|---|---|
| [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach) | 79.6K | MIT | Already installed as a skill. Multi-backend routing with failover. Used for ad-hoc lookups and cross-platform enrichment, not for the main stream. |
| [JosephLai241/URS](https://github.com/JosephLai241/URS) | 1.0K | MIT | The livestream idea. URS wraps PRAW's stream API for real-time subreddit monitoring, which is exactly the "constantly scrape" requirement. Also a useful reminder that PRAW has rate-limit tooling built in. |
| [shaikhsajid1111/social-media-profile-scrapers](https://github.com/shaikhsajid1111/social-media-profile-scrapers) | 574 | Apache-2.0 | Cross-platform profile shapes. Minor influence. |

All three are permissively licensed, so there is no constraint on what can be borrowed.

### Architecture

Three jobs, three different mechanisms. Conflating them is the mistake to avoid.

```
watchlist (user-editable)
     |
     v
PRAW stream over multireddit  ---> new posts, continuously
     |
     +-- on subreddit added --> backfill via .new() and .top()
     |
     v
candidates table
     |
     v
co-posting graph ---> subreddit suggestions ---> user accepts/rejects
```

**Streaming, not polling.** PRAW exposes `subreddit.stream.submissions(skip_existing=True)`, which yields new posts as they appear. A multireddit string (`r/sub1+sub2+sub3`) streams many subreddits through one connection. This is dramatically cheaper than polling each subreddit on a timer, and it arrives in near real time.

```python
reddit.subreddit("+".join(active_subs)).stream.submissions(skip_existing=True)
```

`skip_existing=True` matters on restart. Without it, a restart replays history and floods the pipeline.

**Backfill on add.** When a subreddit joins the watchlist, stream alone gives nothing until someone posts. So an add triggers a one-off pull of `.new(limit=200)` and `.top(time_filter="month")` to establish a baseline and immediately produce a hit-rate estimate.

**Watchlist table.**

```sql
CREATE TABLE subreddits (
  name           TEXT PRIMARY KEY,   -- without the r/
  added_at       TIMESTAMP NOT NULL,
  active         INTEGER DEFAULT 1,
  source         TEXT,               -- manual | discovered
  seen_count     INTEGER DEFAULT 0,
  hit_count      INTEGER DEFAULT 0,  -- passed stage 3
  last_streamed  TIMESTAMP
);
```

Removal sets `active = 0` rather than deleting the row. Two reasons: the historical hit rate stays available, and a subreddit the user has already rejected does not get re-suggested by the discovery job a week later.

The stream reconnects when the active set changes. Simplest correct approach is a supervisor that holds the current subreddit set, checks it periodically, and restarts the stream when it differs.

### Subreddit discovery

The part worth getting right, and the part where the obvious approach is weak.

**The obvious approach, which is not good enough.** Ask an LLM "what subreddits discuss developer infrastructure?" It will produce a plausible list. Some entries will be dead, some will be enormous and noisy, and none of it is grounded in whether those subreddits actually contain the kind of person the thesis wants.

**The better signal: the co-posting graph.** Authors whose posts scored well are the strongest available evidence of where similar people gather. If eleven different founders who passed triage also post in `r/EUstartups`, that is a measurement, not a guess.

```sql
-- candidate subreddits ranked by distinct good authors
SELECT other.subreddit, COUNT(DISTINCT c.author) AS good_authors
FROM candidates c
JOIN author_activity other ON other.author = c.author
WHERE c.is_startup = 1 AND c.confidence > 0.7
  AND other.subreddit NOT IN (SELECT name FROM subreddits)
GROUP BY other.subreddit
ORDER BY good_authors DESC;
```

Counting distinct authors rather than total posts matters. One prolific poster across forty subreddits should not be able to nominate all forty.

**Then measure before recommending.** Take the top candidates, sample around 50 recent posts from each, and run that sample through the normal stage 2 and stage 3 path. That produces an observed hit rate. The recommendation is the measurement; the LLM only writes the explanation of what the subreddit is and why those authors are there.

Output is a ranked list: subreddit, measured hit rate, how many known-good authors post there, and two or three example posts that matched. The user accepts or rejects. Accepted entries enter the watchlist with `source = 'discovered'`.

**Cold start.** Before there are enough good authors to build a graph, the graph is empty. reddapi semantic search covers this gap: search the thesis prose, see which subreddits the results cluster in. Once the graph has signal, it takes over.

### Rate limits and etiquette

Reddit's free OAuth tier allows 100 queries per minute, averaged over 10 minutes. Streaming sits well inside that. PRAW handles backoff internally, so the main risk is running several collectors against the same credentials at once. One client, one process.

Reddit's terms distinguish commercial use from research and personal use. Internal research on public posts is the ordinary case, but this is worth reading properly before the output ever becomes something sold to other funds.

### Files

```
collectors/reddit/
├── stream.py      PRAW multireddit stream, supervisor, reconnect
├── backfill.py    .new() and .top() pull when a subreddit is added
├── discover.py    co-posting graph, sampling, measured hit rates
└── watchlist.py   add, remove, list, hit-rate accounting
```

---

## LinkedIn

The highest-risk source and the lowest priority. Build it last.

### Prior art studied

| Repo | Stars | License | Approach | Verdict |
|---|---|---|---|---|
| [joeyism/linkedin_scraper](https://github.com/joeyism/linkedin_scraper) | 4.5K | **GPL-3.0** | Playwright, async, session file. `PersonScraper`, `CompanyScraper`, `JobSearchScraper`, `CompanyPostsScraper`. No built-in rate limiter. | Read for technique. **Take no code.** |
| [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy) | 4.3K | MIT | No browser at all. Hits job endpoints directly, round-robins proxies, outputs a DataFrame. Rate limited around page 10 per IP. | Good model for the no-browser path, but jobs only, not profiles. |
| [stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server) | 3.4K | Apache-2.0 | Patchright stealth browser, imports sessions from real installed browsers, persistent profile directory, shared-browser queue locking, Docker. | The strongest reference. Actively maintained. |

### The license finding

**joeyism/linkedin_scraper is GPL-3.0.** Copying its code into this project would make the derivative work GPL-3.0 as well. While the repo stays private that obligation never triggers, since GPL is about distribution. But it permanently forecloses open-sourcing this, or shipping it to anyone, without releasing the whole thing under GPL.

So the rule for this project: read joeyism to understand how LinkedIn's DOM and session handling work, then write independently. The Apache-2.0 and MIT references carry no such constraint.

### Where it runs, and why that matters most

**LinkedIn collection runs on the Mac, not the cloud server.**

LinkedIn's detection weights IP reputation heavily, and Oracle, AWS and GCP ranges are well-known datacenter blocks. A headless browser arriving from one of those, logged into an account, is close to the worst possible signal combination. A home residential IP removes the largest single risk factor and costs nothing.

The tradeoff is that LinkedIn collection only happens when the Mac is awake. Given LinkedIn is the weakest of the four sources for early signal, that is an acceptable trade. Everything else runs on the server as normal.

### Design

**Patchright over Playwright.** Patchright is a patched Chromium that removes the Chrome DevTools Protocol artifacts vanilla Playwright leaks. This is the central technical lesson from linkedin-mcp-server and the main reason it works where plain Playwright setups get flagged.

**Session cookie import, never programmatic login.** Reuse a browser profile that is already logged in and persist it to disk. Driving the login form is the single most reliably detected automation behaviour there is. linkedin-mcp-server's approach of importing from an installed browser is the right one.

**A real rate limiter, which none of the three references have.** All of them advise going slowly and none enforce it. This one enforces it:

- token bucket with a hard daily cap
- 30 to 60 seconds of jitter between profile fetches, never a fixed interval
- full stop on the first soft block or challenge page, no retry loop
- the cap is a config value, and the default is deliberately low

**Schematron-3B parses the HTML, not CSS selectors.** Every reference repo is selector-based, which is why every one of them has a commit history full of "fix selectors after LinkedIn update". Feeding cleaned HTML plus a JSON schema to a model trained for that job survives layout changes. This is the durability win over all the prior art.

**Fail open.** LinkedIn breaking must never stop a run. Downstream stages treat missing LinkedIn data as absent, not as an error. Assume this source dies periodically and design so nothing notices.

### Scope

Profiles and company pages only. Read-only, public data.

No messaging, no connection requests, no feed interaction, no posting. That boundary is what keeps this ordinary business research rather than platform manipulation, and it is also the boundary that keeps the volume low enough to stay unremarkable.

### Files

```
collectors/linkedin/
├── session.py   cookie import, profile persistence, expiry detection
├── fetch.py     patchright driver, navigation, soft-block detection
├── parse.py     HTML to record via Schematron-3B
└── limits.py    token bucket, daily cap, jitter, stop conditions
```

---

## Privacy

Both collectors process personal data, and the thesis targets European founders, so GDPR applies.

Legitimate interest is a workable lawful basis for B2B research, but it is not a free pass. It requires collecting only fields actually used for scoring, setting a retention period and enforcing it, being able to say what is held and why, and being able to delete an individual on request.

Public Reddit posts are still personal data once tied to an identifiable person. Being public affects the expectation of privacy, not whether the regulation applies.

Practical consequences, all cheaper to build in now than to retrofit:

- `retention_until` on the candidates table from the first migration
- store extracted fields and `source_url`, not full page dumps, wherever the record is enough
- one deletion function that removes a person across every table, not deletion logic scattered per collector
- the review page never becomes a general-purpose people search
