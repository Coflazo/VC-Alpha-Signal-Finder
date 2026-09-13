# Using it from Claude or Codex

You do not have to open the app at all. Hand this to Claude and ask questions in
plain English — Claude operates the product for you.

> *"Who did we find this week that fits the Treeo thesis?"*
> *"Tell me about that founder — what do we actually know, and where from?"*
> *"Should I be taking more meetings right now, or fewer?"*
> *"Go and check Hacker News for anything new."*

## Claude Desktop

Open **Settings → Developer → Edit Config** and add this. Replace the path with
wherever you keep the product.

```json
{
  "mcpServers": {
    "vc-alpha": {
      "command": "vc-alpha",
      "args": ["mcp"],
      "env": {
        "VC_ALPHA_DB": "/Users/you/VC Alpha Signal Finder/data/candidates.sqlite"
      }
    }
  }
}
```

Restart Claude. You should see a tools icon in the message box; VC Alpha's tools
will be listed there.

If `vc-alpha` is not on your path, use the full path to it — `which vc-alpha` on
macOS or Linux, `where vc-alpha` on Windows, will tell you.

## Claude Code

```bash
claude mcp add vc-alpha -- vc-alpha mcp
```

## Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.vc-alpha]
command = "vc-alpha"
args = ["mcp"]
```

## What Claude can do

| Ask for | Tool it uses |
|---|---|
| Which funds are configured and what they look for | `list_funds` |
| The best candidates found, optionally for one fund | `search_candidates` |
| Founders and companies, gathered across every source | `list_founders` |
| Everything known about one founder, with sources | `get_founder` |
| Record that something was or was not worth pursuing | `review_candidate` |
| How selective to be, given capital and time left | `acceptance_threshold` |
| What each source has found and whether it is connected | `source_status` |
| Go and look for new candidates | `collect` |

## What it will not do

**Private material does not cross this boundary.** An MCP client is a third party:
whatever model is on the other end receives what these tools return. WhatsApp
messages and inbound pitches stay on your machine — Claude sees the scores, the
reasoning and where something came from, and gets a note in place of the text:

```
[Private source. The text stays on this machine; scores and reasoning
 are shown instead.]
```

That is enforced in code and tested, not a policy. Public posts pass through
normally, because surfacing those is the entire point.

## Worth knowing

- Every score is an estimate from a model. Quotes are checked against the original
  text and dropped if they cannot be found, so anything quoted is real — but the
  judgement around it is not verified.
- `collect` goes out to the internet and can take a few minutes.
- The database is a file. Back it up like any other document.
