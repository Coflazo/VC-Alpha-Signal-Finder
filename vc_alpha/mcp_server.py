"""Run the product as an MCP server, so an assistant can operate it.

The point is not convenience for engineers. A partner who will never open a terminal
can paste one config block into Claude and then ask questions — "who did we find
this week that fits the Treeo thesis", "tell me about this founder", "should I be
taking more meetings right now" — and the assistant works the product on their
behalf. For a non-technical user that is very often a better interface than a table.

Every tool is a thin call into functions the web app already uses, so there is one
implementation of each behaviour and no second version to drift.

## The privacy rule, which matters more here than anywhere else

An MCP client is a third party by definition: whatever model sits on the other end
receives what these tools return. The product's promise is that private material
never leaves the machine, and a tool that quietly handed WhatsApp logs to a remote
model would break exactly that promise while looking helpful.

So tools never return raw text from private sources. A WhatsApp or inbound candidate
comes back with its scores, its reasoning and a note saying where it came from, and
the message itself stays local. This is the same `Sending` distinction the router
enforces, applied at a second boundary.
"""

from __future__ import annotations

import json
import os
from typing import Any

# MCP SDK v2 renamed FastMCP to MCPServer. Names in this ecosystem are
# perishable, which is why the version is pinned in pyproject.
from mcp.server.mcpserver import MCPServer

from vc_alpha import entities, env, founders, paths, score, theses
from vc_alpha.db import connect
from vc_alpha.redact import PRIVATE_SOURCES as PIPELINE_PRIVATE

env.load()

# Sources whose text must not cross this boundary: everything the pipeline treats
# as private, plus a fund's own inbound, mirroring app.main.LOCAL_ONLY.
PRIVATE_SOURCES = {"inbound", *PIPELINE_PRIVATE}

mcp = MCPServer("VC Alpha Signal Finder")


def _db():
    return connect(paths.db_path())


def _safe_text(source: str, text: str | None, limit: int = 400) -> str:
    """Return post text, or a note in its place when the source is private."""
    if source in PRIVATE_SOURCES:
        return ("[Private source. The text stays on this machine; scores and "
                "reasoning are shown instead.]")
    return (text or "")[:limit]


@mcp.tool()
def list_funds() -> list[dict[str, Any]]:
    """List the investment theses configured, with what each fund looks for.

    Use this first when the user mentions a fund by name, to get its id.
    """
    return [{"id": t.id, "name": t.name, "looks_for": t.prose.strip(),
             "avoids": t.exclude,
             "signals_that_matter": t.hard_signals} for t in theses.load_all()]


@mcp.tool()
def search_candidates(fund: str | None = None, limit: int = 10,
                      min_score: float = 0.0) -> list[dict[str, Any]]:
    """Find the best candidates discovered so far, optionally for one fund.

    `fund` is a fund id from list_funds. Results are ranked by the combined score.
    """
    conn = _db()
    rows = score.ranked(conn, fund, limit=limit)
    out = []
    for r in rows:
        if (r["score"] or 0) < min_score:
            continue
        triage = {}
        if r["triage_json"]:
            try:
                triage = json.loads(r["triage_json"])
            except ValueError:
                pass
        out.append({
            "title": r["title"],
            "url": r["source_url"],
            "source": r["source"],
            "author": r["author"],
            "score": r["score"],
            "stage": r["stage_guess"],
            "matched_fund": r["thesis_id"],
            "summary": triage.get("summary"),
            "text": _safe_text(r["source"], r["raw_text"]),
        })
    return out


@mcp.tool()
def list_founders(limit: int = 15) -> list[dict[str, Any]]:
    """List founders and companies, each assembled from every mention of them.

    More useful than searching candidates when the question is about people, since
    one founder may appear in several places.
    """
    conn = _db()
    entities.install(conn)
    return [{"id": r["id"], "name": r["name"], "kind": r["kind"],
             "score": r["score"], "mentions": r["mentions"],
             "seen_in": [s for s in (r["sources"] or "").split(",") if s],
             "needs_checking": bool(r["needs_review"])}
            for r in entities.ranked(conn, limit=limit)]


@mcp.tool()
def get_founder(founder_id: str) -> dict[str, Any]:
    """Everything known about one founder or company, with the source of each claim.

    Includes the score breakdown, the verified quote behind each signal, and where
    each piece of evidence came from. Quotes that could not be found in the original
    text are dropped rather than shown, so anything here is checkable.
    """
    conn = _db()
    entities.install(conn)
    row = conn.execute("SELECT * FROM entities WHERE id = ?", (founder_id,)).fetchone()
    if not row:
        return {"error": f"No founder with id {founder_id}. Try list_founders."}

    detail = json.loads(row["signals_json"]) if row["signals_json"] else {}
    evidence = [
        {"source": e["source"], "url": e["source_url"], "title": e["title"],
         "text": _safe_text(e["source"], e["raw_text"], 300)}
        for e in entities.evidence(conn, founder_id)
    ]
    return {
        "name": row["name"], "kind": row["kind"], "score": row["score"],
        "domain": row["domain"], "seen_in": (row["sources"] or "").split(","),
        "signals": detail.get("signals", {}),
        "evidence_quotes": detail.get("support", []),
        "found_in": evidence,
        "caveat": ("Scores are estimates from a model. Quotes are verified against "
                   "the source text, but judgement is not."),
    }


@mcp.tool()
def review_candidate(url: str, worth_a_look: bool) -> dict[str, Any]:
    """Record whether a candidate was worth pursuing.

    These judgements are the only way the product learns where a fund's bar actually
    sits, so recording them is genuinely valuable rather than bookkeeping.
    """
    conn = _db()
    cur = conn.execute(
        "UPDATE candidates SET reviewed = 1, was_good = ? WHERE source_url = ?",
        (int(worth_a_look), url))
    conn.commit()
    if not cur.rowcount:
        return {"error": f"No candidate with url {url}."}
    return {"ok": True, "recorded": "worth a look" if worth_a_look else "not for us"}


@mcp.tool()
def forget_person(name: str, confirm: bool = False) -> dict[str, Any]:
    """Erase one person from every table, on request.

    For an erasure request under GDPR Article 17. Removes their posts, their
    WhatsApp messages, their activity history, their entity profile and every
    piece of evidence drawn from them.

    Reports the scope first. Nothing is deleted unless `confirm` is true, because
    this is irreversible and an assistant should not be able to do it by
    misreading a sentence.
    """
    from vc_alpha.db import forget_author

    conn = _db()
    name = name.strip()
    if not name:
        return {"error": "Name the person to erase."}

    scope = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE author = ?", (name,)).fetchone()[0]
    if not confirm:
        return {"confirmed": False, "candidates": scope,
                "next_step": f"Call again with confirm=true to erase {name}."}
    return {"confirmed": True, "deleted": forget_author(conn, name)}


@mcp.tool()
def acceptance_threshold(investments_left: int = 14, months_left: int = 22,
                         deals_per_month: float = 8.0) -> dict[str, Any]:
    """How selective a fund should be right now, given capital and time remaining.

    Sequential assignment: the threshold is the option value of holding a slot. It
    falls as the window closes and rises with deal flow, so better sourcing should
    make a fund more selective rather than less.
    """
    from vc_alpha.quant.deployment import recommend

    conn = _db()
    scores = [r[0] for r in conn.execute(
        "SELECT COALESCE(score, similarity) FROM candidates "
        "WHERE COALESCE(score, similarity) IS NOT NULL")]
    out = recommend(scores, investments_left, months_left, deals_per_month)
    out["plain_english"] = (
        f"With {investments_left} investments left and {months_left} months to make "
        f"them, take anything scoring above {out['threshold_now']}. That bar falls "
        f"to {out['threshold_midway']} halfway through.")
    return out


@mcp.tool()
def source_status() -> list[dict[str, Any]]:
    """What each source has found, and whether it is connected yet."""
    from vc_alpha.app.main import LOCAL_ONLY, SOURCE_INFO

    conn = _db()
    counts = {r["source"]: r["n"] for r in conn.execute(
        "SELECT source, COUNT(*) n FROM candidates GROUP BY source")}
    return [{"source": k, "name": v["label"], "what_it_is": v["what"],
             "found": counts.get(k, 0),
             "connected": not v.get("needs") or bool(os.environ.get(v["needs"])),
             "how_to_connect": v.get("setup"),
             "stays_on_this_machine": k in LOCAL_ONLY}
            for k, v in SOURCE_INFO.items()]


@mcp.tool()
def collect(source: str, how_many: int = 5) -> dict[str, Any]:
    """Go and look for new candidates from one source.

    Takes a while. Use source_status first to see which sources are connected.
    """
    from vc_alpha.app.main import SOURCE_INFO
    from vc_alpha.collect import COLLECTORS, NEEDS_CONN, store
    from vc_alpha import frontier

    if source not in SOURCE_INFO:
        return {"error": f"Unknown source {source}. Try source_status."}
    conn = _db()
    factory = COLLECTORS[source]
    collector = factory(conn) if source in NEEDS_CONN else factory()
    active = theses.load_all()
    try:
        stats = frontier.expand(
            conn, collector, frontier.Budget(max_visits=how_many),
            on_candidates=lambda recs: store(conn, recs, active))
    except Exception as e:
        return {"error": f"{source} could not run: {e}"}
    return {"source": source, **stats}


def main() -> None:
    """Entry point for `vc-alpha mcp`, spoken over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
