# The browser extension

Every other way into the pipeline is a collector running over a source in bulk.
The extension is the way in for the page you are looking at right now: a founder's
site, a Show HN post, a LinkedIn profile, a pitch someone forwarded. One click
scores it locally in the browser and sends it to the engine, which screens it
against your fund's thesis the same way it screens everything else.

The code is in `extension/`. It is a Chrome Manifest V3 extension, and
`extension/README.md` covers what it does on its own.

## Running it

```bash
uv run vc-alpha                     # the engine, at http://127.0.0.1:8420
cd extension && npm install && npm run build
```

Then open `chrome://extensions`, turn on Developer Mode, click **Load unpacked** and
select `extension/dist`.

Captures go to the engine by default. Settings has the switch and the fund the
engine should screen against (`treeo` unless you change it; leave it blank for the
best match across every configured fund).

## What happens to a capture

The extension posts the text to `POST /api/capture` while its own analysis runs,
so the click costs no extra time. In the engine:

1. **Excluded?** If the fund's thesis excludes the text outright, nothing is kept.
2. **Stored** as a candidate with source `extension`, or `extension_private` for a
   page marked private. A page captured again is refreshed, and any review you
   gave it survives. A page a collector already found keeps the collector's text
   and source, and the engine shows what it already has.
3. **Embedded** and scored for similarity against the thesis.
4. **Triaged** on the six signals, with the quote behind each one. Quotes that are
   not in the text are blanked before anything is stored.

It skips two stages on purpose. The cheap filters and the similarity threshold
exist to save calls when collecting in bulk. A capture is one page a person chose
to send, so the click has done the filtering already.

After that it is an ordinary candidate, under the same rules as every other one. It
appears on the Review screen once it has a similarity. It ranks in the fund's
report and the Sheet if the model judged it a company being built. The next
dossier build includes it. A private page captured without a local embedding
model has no similarity yet, so it stays off the Review screen until
`score_all` embeds it locally.

The extension shows the verdict in a **Thesis fit** section of the side panel,
next to its own local score. The two are not the same number: the local score
comes from the extension's own rules, and the thesis fit is the engine's six
signals combined with your fund's weights.

When the engine is off, the section says so and the extension works as before.

## Private pages

Anyone could open most pages. Some pages are not like that, such as an email or
an internal document. The popup has a **Private page** switch for those. It is on
by default for Gmail and Outlook.

A private page is handled exactly like a WhatsApp message:

- embedded only by a local model; with a hosted embedder it gets no similarity
- triaged on a redacted fragment from `vc_alpha/redact.py`, never the text itself
- never selected by `triage.run`, and hidden by the MCP server

The rule lives in one constant, `redact.PRIVATE_SOURCES`, which embedding,
triage, the pipeline and the MCP server all read.

## Who can post a capture

Any web page open in the same browser can send requests to `127.0.0.1`. So
`/api/capture` refuses any `Origin` except `chrome-extension://…`; curl and other
local tools send no Origin and are allowed. The extension's only host permission
is `http://127.0.0.1:8420/*`.

## The endpoint

```
POST /api/capture
{"text": "...", "url": "https://...", "title": "...", "private": false, "thesis": "treeo"}
```

Only `text` is required, up to 50,000 characters. A capture with no URL is keyed
on a hash of its text, so pasting the same thing twice gives one candidate.

The response is the candidate as the engine now sees it:

```
{"id", "status", "source", "thesis": {"id", "name"}, "similarity", "confidence",
 "score", "stage", "summary", "signals": [{"key", "score", "quote"}], "note"}
```

`status` is `scored`, `stored` (kept but not screened, and `note` says why, for
example which free key to add) or `excluded`. The errors are 400 for empty or
oversized text, 403 for a disallowed Origin and 404 for an unknown fund.
