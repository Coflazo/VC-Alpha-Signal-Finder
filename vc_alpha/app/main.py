"""The app. One page, JSON behind it.

FastAPI rather than a script because the stated path is a hosted product later,
and this is the shape that gets there: same routes, same JSON, add auth and swap
SQLite for Postgres. Nothing here assumes a single user except the job runner,
which says so.

Three of the six sources cannot run in CI — Substack is IP-blocked on datacenter
ranges, WhatsApp is private, LinkedIn would get flagged — so this app is where
they run, not a viewer bolted onto a pipeline that lives elsewhere.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vc_alpha import (
    capture, entities, env, founders, paths, score, secrets, theses, warmpath)
from vc_alpha.app import sheets
from vc_alpha.app.jobs import runner
from vc_alpha.db import connect, expiring_within, forget_author, purge_expired
from vc_alpha.enrich.embed import EMBEDDERS
from vc_alpha.llm import LADDER, Router, Sending
from vc_alpha.quant.information import (
    DecisionEconomics, calibrate_to_posterior, review_priority)

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"

# Keys the user saved in the Setup screen live in a file, not the shell that
# launched this, so they have to be read before anything asks whether a
# provider is configured.
env.load()
paths.ensure()

# Sources that cannot run on a shared runner, and why. Surfaced in the UI so the
# split is visible rather than folklore.
LOCAL_ONLY = {
    "substack": "Substack returns 403 to datacenter IP ranges",
    "whatsapp": "private exports never leave this machine",
    "linkedin": "a datacenter IP is the fastest way to get flagged",
    "inbound": "a fund's own deal flow stays on the fund's machine",
}

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Enforce retention when the app starts.

    The app is where most people will actually run this, so it is the one place
    the deletion job is guaranteed to happen even for a fund that never touches
    the command line or the scheduled workflows.
    """
    try:
        gone = purge_expired(db())
        if gone:
            log.info("retention: removed %d expired rows on startup", gone)
    except Exception as e:                        # never block startup on this
        log.warning("retention job did not run: %s", e)
    yield


app = FastAPI(title="VC Alpha Signal Finder", lifespan=lifespan)


def db() -> sqlite3.Connection:
    return connect(paths.db_path())


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/overview")
def overview() -> dict:
    conn = db()
    sources = [
        {
            "source": r["source"],
            "total": r["n"],
            "scored": r["scored"],
            "triaged": r["triaged"],
            "local_only": r["source"] in LOCAL_ONLY,
            "note": LOCAL_ONLY.get(r["source"], ""),
        }
        for r in conn.execute(
            """SELECT source, COUNT(*) n,
                      SUM(similarity IS NOT NULL) scored,
                      SUM(triage_json IS NOT NULL) triaged
               FROM candidates GROUP BY source ORDER BY n DESC"""
        )
    ]
    nodes = conn.execute(
        """SELECT COUNT(*) total, SUM(active) active, SUM(exhausted) exhausted
           FROM nodes"""
    ).fetchone()
    reviewed = conn.execute(
        "SELECT COUNT(*) n, SUM(was_good) good FROM candidates WHERE reviewed = 1"
    ).fetchone()

    return {
        "sources": sources,
        "nodes": dict(nodes) if nodes else {},
        "funds": len(theses.load_all()),
        "first_run": theses.NO_FUNDS,
        "reviewed": {"n": reviewed["n"] or 0, "good": reviewed["good"] or 0},
        "job": runner.current.as_dict() if runner.current else None,
    }


@app.get("/api/providers")
def providers() -> dict:
    """What inference capacity is left today, and what is simply not configured.

    The point of this screen is that 'free forever' is checkable rather than
    claimed.
    """
    conn = db()
    router = Router(conn)
    used = {u["provider"]: u["requests"] for u in router.budget.report()}
    return {
        "providers": [
            {
                "name": p.name,
                # Not bool(p.key): the local rung needs no key and is the one
                # thing that works with nothing set up at all.
                "configured": p.configured,
                "env": p.env_key,
                "local": p.local,
                "used": used.get(p.name, 0),
                "limit": p.daily_requests,
                "model": p.model,
            }
            for p in LADDER
        ]
    }


@app.get("/api/candidates")
def candidates(limit: int = 50, thesis: str | None = None,
               unreviewed: bool = True, order: str = "information") -> dict:
    """The review queue.

    Ordered by expected value of information by default, not by score. Reviewing
    the top-scoring candidate teaches you almost nothing — you were going to pursue
    it anyway and the review will not change that. The information sits at the
    decision boundary, among the candidates the model cannot separate, and these
    labels exist precisely to calibrate that boundary.

    Pass order=score for the conventional ranking.
    """
    sql = ["SELECT * FROM candidates WHERE similarity IS NOT NULL"]
    params: list = []
    if thesis:
        sql.append("AND thesis_id = ?")
        params.append(thesis)
    if unreviewed:
        sql.append("AND reviewed = 0")
    # Fetch a wider slice than requested, then reorder by information value in
    # Python: EVSI is not expressible in SQL and the candidate set is small.
    sql.append("ORDER BY COALESCE(score, similarity) DESC LIMIT ?")
    params.append(limit * 5 if order == "information" else limit)

    rows = []
    econ = DecisionEconomics()
    for r in db().execute(" ".join(sql), params):
        triage = {}
        if r["triage_json"]:
            try:
                triage = json.loads(r["triage_json"])
            except ValueError:
                pass
        rows.append({
            "id": r["id"],
            "source": r["source"],
            "url": r["source_url"],
            "title": r["title"],
            "author": r["author"],
            "text": (r["raw_text"] or "")[:600],
            "similarity": r["similarity"],
            "score": r["score"],
            "thesis": r["thesis_id"],
            "is_startup": r["is_startup"],
            "stage": r["stage_guess"],
            "confidence": r["confidence"],
            "reasoning": triage.get("reasoning"),
            "posted_at": r["posted_at"],
        })

    for row in rows:
        posterior = calibrate_to_posterior(row["score"] or row["similarity"] or 0.0)
        row["posterior"] = round(posterior, 4)
        row["review_value"] = round(review_priority(posterior, econ), 5)

    if order == "information":
        rows.sort(key=lambda r: -r["review_value"])
    return {
        "candidates": rows[:limit],
        "order": order,
        "decision_threshold": round(econ.threshold, 4),
    }


class Verdict(BaseModel):
    good: bool


@app.post("/api/candidates/{candidate_id}/review")
def review(candidate_id: str, verdict: Verdict) -> dict:
    """Record a human judgement.

    These labels are the only way the stage-2 threshold stops being a guess, so
    this is the most valuable endpoint in the app despite being the simplest.
    """
    conn = db()
    cur = conn.execute(
        "UPDATE candidates SET reviewed = 1, was_good = ? WHERE id = ?",
        (int(verdict.good), candidate_id),
    )
    conn.commit()
    if not cur.rowcount:
        raise HTTPException(404, "no such candidate")
    return {"ok": True}


class CaptureRequest(BaseModel):
    text: str
    url: str | None = None
    title: str | None = None
    private: bool = False
    thesis: str | None = None


@app.post("/api/capture")
def capture_page(req: CaptureRequest, request: Request) -> dict:
    """A page sent from the browser extension. See vc_alpha/capture.py.

    Any web page open in the same browser can reach 127.0.0.1 too, so the Origin
    is checked. The extension sends its own `chrome-extension://` origin; curl and
    other local tools send none. A page on any website sends its site, and is
    refused, so it cannot plant candidates in a fund's pipeline.
    """
    origin = request.headers.get("origin")
    if origin is not None and not origin.startswith("chrome-extension://"):
        raise HTTPException(403, "Captures are only accepted from the browser extension.")
    try:
        return capture.capture(db(), req.text, url=req.url, title=req.title,
                               private=req.private, thesis_id=req.thesis)
    except capture.UnknownThesis as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/calibration")
def calibration() -> dict:
    """How close the review queue is to replacing the guessed threshold.

    Shown on the Review screen so the clicks have a visible destination. Without
    it, reviewing is a chore with no feedback — which is how a feedback loop that
    nobody closes ends up collecting labels nothing reads.
    """
    from vc_alpha import calibrate

    return calibrate.progress(db())


@app.post("/api/calibration/fit")
def fit_calibration() -> dict:
    """Fit the threshold and the score weights from the recorded reviews."""
    from vc_alpha import calibrate

    try:
        cal = calibrate.fit(db())
    except calibrate.NotEnoughLabels as e:
        raise HTTPException(400, str(e)) from e

    # Every stored score was computed with the old weights.
    rescored = score.rescore(db())
    return {"ok": True, "threshold": cal.threshold, "weights": cal.weights,
            "labels": cal.n_labels, "precision": cal.precision,
            "recall": cal.recall, "rescored": rescored, "caveats": cal.caveats}


@app.get("/api/theses")
def list_theses() -> dict:
    return {
        "theses": [
            {
                "id": t.id,
                "name": t.name,
                "url": t.url,
                "prose": t.prose.strip(),
                "fields": [{"key": f.key, "label": f.label} for f in t.report_fields],
            }
            for t in theses.load_all()
        ]
    }


@app.get("/api/reports/{thesis_id}")
def report(thesis_id: str, limit: int = 100) -> dict:
    thesis = next((t for t in theses.load_all() if t.id == thesis_id), None)
    if not thesis:
        raise HTTPException(404, "no such thesis")

    rows = []
    for r in score.ranked(db(), thesis_id, limit=limit):
        data = {}
        if r["research_md"]:
            try:
                data = json.loads(r["research_md"])
            except ValueError:
                pass
        rows.append({
            "score": r["score"],
            "url": r["source_url"],
            "source": r["source"],
            "fields": {f.key: data.get(f.key, "") for f in thesis.report_fields},
        })
    return {
        "thesis": thesis.name,
        "columns": [{"key": f.key, "label": f.label} for f in thesis.report_fields],
        "rows": rows,
    }


class NewThesis(BaseModel):
    name: str
    prose: str
    founder_voice: str = ""
    exclude: list[str] = []
    hard_signals: list[str] = []


@app.post("/api/theses")
def create_thesis(req: NewThesis) -> dict:
    """Turn a plain-English thesis into a working config.

    Hand-editing YAML is the largest barrier to anyone but the author using this.
    The generated file is commented and meant to be edited, not treated as opaque.
    """
    from vc_alpha import onboard

    if not req.name.strip() or len(req.prose.strip()) < 40:
        raise HTTPException(400, "Give the fund a name and at least a sentence or "
                                 "two describing what you back.")
    try:
        path = onboard.create(req.name, req.prose, req.founder_voice,
                              req.exclude or None, req.hard_signals or None)
    except FileExistsError as e:
        raise HTTPException(409, str(e)) from e
    return {"id": onboard.slugify(req.name), "path": str(path),
            "stage": onboard.infer_stage(req.prose)}


@app.get("/api/health")
def health() -> dict:
    """Everything a support conversation needs in one call."""
    from vc_alpha.fastpath import HAVE_FAST

    conn = db()
    return {
        "candidates": conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
        "theses": len(theses.load_all()),
        "fast_extension": HAVE_FAST,
        "providers_configured": [p.name for p in Router(conn).available()],
        "sheets": sheets.status().configured,
    }


# What each source is, why it matters, and what it needs — in the words a partner
# would use. Shown on that source's own tab.
SOURCE_INFO = {
    "hackernews": {
        "label": "Hacker News",
        "what": "Founders announcing their own work, usually before any press.",
        "needs": None,
        "action": "Search recent launches",
    },
    "substack": {
        "label": "Substack",
        "what": "Newsletters that write about new companies, and the writers they recommend.",
        "needs": None,
        "action": "Read watched newsletters",
    },
    "github": {
        "label": "GitHub",
        "what": "New projects gaining attention fast, often before a company exists.",
        "needs": None,
        "action": "Scan trending projects",
    },
    "reddit": {
        "label": "Reddit",
        "what": "Founders asking for help and sharing what they are building.",
        "needs": "REDDIT_CLIENT_ID",
        "setup": "Create a free app at reddit.com/prefs/apps and pick 'script'. Takes two minutes.",
        "action": "Read watched subreddits",
    },
    "linkedin": {
        "label": "LinkedIn",
        "what": "Profiles and posts from people who have just started something.",
        "needs": "LINKEDIN_SESSION_COOKIE",
        "setup": "Sign in on LinkedIn in a browser and copy the li_at cookie. Use a spare account.",
        "action": "Check saved profiles",
    },
    "whatsapp": {
        "label": "WhatsApp",
        "what": "Your own group chats. Nothing here ever leaves this computer.",
        "needs": None,
        "setup": "Export a chat from WhatsApp and drop the file into data/whatsapp.",
        "action": "Read imported chats",
    },
    "inbound": {
        "label": "Inbound",
        "what": "Pitches sent straight to you. Already the most qualified thing you have.",
        "needs": None,
        "setup": "Save emails as .eml files, or drop a CSV export, into data/inbound.",
        "action": "Read new pitches",
    },
}


@app.get("/api/sources")
def sources() -> dict:
    """Everything needed to draw one tab per source."""
    conn = db()
    counts = {
        r["source"]: dict(r) for r in conn.execute(
            """SELECT source, COUNT(*) n,
                      SUM(similarity IS NOT NULL) scored,
                      SUM(triage_json IS NOT NULL) triaged,
                      MAX(discovered_at) last_seen
               FROM candidates GROUP BY source""")
    }
    nodes = {
        r["source"]: r["n"] for r in conn.execute(
            "SELECT source, COUNT(*) n FROM nodes WHERE active = 1 GROUP BY source")
    }

    out = []
    for key, info in SOURCE_INFO.items():
        c = counts.get(key, {})
        needs = info.get("needs")
        out.append({
            "key": key,
            "label": info["label"],
            "what": info["what"],
            "action": info["action"],
            "setup": info.get("setup"),
            "ready": not needs or bool(os.environ.get(needs)),
            "needs_env": needs,
            "local_only": key in LOCAL_ONLY,
            "local_reason": LOCAL_ONLY.get(key, ""),
            "candidates": c.get("n", 0),
            "scored": c.get("scored") or 0,
            "triaged": c.get("triaged") or 0,
            "last_seen": c.get("last_seen"),
            "watching": nodes.get(key, 0),
        })
    return {"sources": out}


@app.get("/api/sources/{key}")
def source_detail(key: str, limit: int = 25) -> dict:
    """One source: what it found, and what it is watching."""
    if key not in SOURCE_INFO:
        raise HTTPException(404, "no such source")
    conn = db()
    recent = [
        {"title": r["title"], "url": r["source_url"], "author": r["author"],
         "score": r["score"], "similarity": r["similarity"],
         "posted_at": r["posted_at"]}
        for r in conn.execute(
            """SELECT title, source_url, author, score, similarity, posted_at
               FROM candidates WHERE source = ?
               ORDER BY COALESCE(score, similarity) DESC NULLS LAST LIMIT ?""",
            (key, limit))
    ]
    watching = [
        {"node": r["node"], "name": r["display_name"], "seen": r["seen_count"],
         "hits": r["hit_count"], "kind": r["source_kind"]}
        for r in conn.execute(
            """SELECT node, display_name, seen_count, hit_count, source_kind
               FROM nodes WHERE source = ? AND active = 1
               ORDER BY hit_count DESC, seen_count DESC LIMIT 25""", (key,))
    ]
    return {"key": key, "recent": recent, "watching": watching,
            **SOURCE_INFO[key]}


@app.get("/api/hardware")
def hardware() -> dict:
    """What this machine is and what it could run, in plain language."""
    from vc_alpha.hardware import profile
    from vc_alpha.installer import installed_models, ollama_running
    from vc_alpha.modelpick import recommend

    m = profile()
    rec = recommend(m)
    return {
        "summary": m.summary(),
        "total_ram_gb": round(m.total_ram_gb, 1),
        "usable_gb": round(m.usable_ram_gb(), 2),
        "notes": m.notes,
        "ollama_running": ollama_running(),
        "installed": installed_models(),
        "recommendation": {
            "model": rec.model.name if rec.ok else None,
            "reason": rec.reason,
            "rejected": [{"model": n, "why": w} for n, w in rec.rejected],
        },
    }


@app.post("/api/setup/auto")
def setup_auto(allow_download: bool = True) -> dict:
    """One action: inspect, measure, choose, install, verify.

    Returns every step with its plain-language explanation, so a user can see what
    was decided and why rather than being handed a result to trust.
    """
    from vc_alpha.installer import auto_setup
    steps = [{"name": s.name, "ok": s.ok, "detail": s.detail, "data": s.data}
             for s in auto_setup(allow_download=allow_download)]
    return {"steps": steps, "ok": all(s["ok"] for s in steps)}


@app.get("/api/deployment")
def deployment(slots: int = 14, months: int = 22,
               deals_per_month: float = 8.0) -> dict:
    """What the acceptance bar should be right now, given fund and window left.

    Sequential assignment (Derman, Lieberman and Ross). The threshold is the option
    value of holding a slot: it falls as the window closes, falls as slots
    accumulate, and rises with deal flow — so better sourcing should make a fund
    more selective rather than less.

    The score distribution comes from the pipeline's own output, so the bar is on
    the same scale as the numbers it gates.
    """
    from vc_alpha.quant.deployment import recommend

    scores = [
        r[0] for r in db().execute(
            "SELECT COALESCE(score, similarity) FROM candidates "
            "WHERE COALESCE(score, similarity) IS NOT NULL"
        ).fetchall()
    ]
    out = recommend(scores, slots, months, deals_per_month)
    out["observations"] = len(scores)
    return out


# --- entities ---------------------------------------------------------------


@app.get("/api/entities")
def list_entities(limit: int = 50) -> dict:
    conn = db()
    entities.install(conn)
    rows = []
    for r in entities.ranked(conn, limit=limit):
        detail = json.loads(r["signals_json"]) if r["signals_json"] else {}
        rows.append({
            "id": r["id"], "kind": r["kind"], "name": r["name"],
            "domain": r["domain"], "score": r["score"],
            "mentions": r["mentions"],
            "sources": [s for s in (r["sources"] or "").split(",") if s],
            "needs_review": bool(r["needs_review"]),
            "thesis": detail.get("thesis"),
            "corroboration": detail.get("corroboration"),
        })
    return {"entities": rows}


@app.get("/api/entities/{entity_id}")
def dossier(entity_id: str) -> dict:
    """Everything known about one founder or company, with the source of each claim.

    This is the screen the product lives or dies on. An analyst who cannot check a
    claim redoes the work, and then the tool has saved nobody anything — so every
    number here arrives with the text that produced it.
    """
    conn = db()
    entities.install(conn)
    row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such entity")

    detail = json.loads(row["signals_json"]) if row["signals_json"] else {}
    ev = [
        {
            "id": e["id"], "source": e["source"], "url": e["source_url"],
            "title": e["title"], "author": e["author"], "role": e["role"],
            "posted_at": e["posted_at"], "similarity": e["similarity"],
            "text": (e["raw_text"] or "")[:400],
        }
        for e in entities.evidence(conn, entity_id)
    ]

    warm = [
        {"kind": p.kind, "via": p.via, "person": p.person,
         "strength": p.strength, "describe": p.describe()}
        for p in warmpath.paths_to(conn, entity_id)
    ]

    breakdown = []
    if detail.get("signals"):
        thesis = next((t for t in theses.load_all() if t.id == detail.get("thesis")), None)
        from vc_alpha.signals import explain
        breakdown = explain(detail["signals"], thesis.weights if thesis else None)

    return {
        "entity": {
            "id": row["id"], "kind": row["kind"], "name": row["name"],
            "domain": row["domain"], "github": row["github"],
            "linkedin": row["linkedin"], "score": row["score"],
            "mentions": row["mentions"], "needs_review": bool(row["needs_review"]),
            "sources": [s for s in (row["sources"] or "").split(",") if s],
        },
        "scoring": detail,
        "breakdown": breakdown,
        "support": detail.get("support", []),
        "evidence": ev,
        "warm_paths": warm,
    }


@app.post("/api/entities/build")
def build_entities() -> dict:
    """Extract entities from candidates, then score them. Both are local and cheap."""
    from vc_alpha import extract
    conn = db()
    stats = extract.build(conn)
    stats |= founders.score_all(conn, theses.load_all())
    return stats


# --- jobs -------------------------------------------------------------------

JOB_COMMANDS = {
    "collect": lambda src, n: ["vc_alpha.collect", "--source", src, "--visits", str(n)],
    "entities": lambda src, n: ["vc_alpha.build_entities"],
    "score": lambda src, n: ["vc_alpha.score_all"],
    "pipeline": lambda src, n: ["vc_alpha.pipeline", "--limit", str(n)],
}

# Jobs that operate on everything already collected and take no source.
NEEDS_SOURCE = {"collect"}


class JobRequest(BaseModel):
    kind: str
    source: str = "hackernews"
    n: int = 10


@app.post("/api/jobs")
def start_job(req: JobRequest) -> dict:
    if req.kind not in JOB_COMMANDS:
        raise HTTPException(400, f"unknown job: {req.kind}")

    # Validate here rather than letting an empty value reach argparse, which
    # answers with a usage dump. A person who is not technical should never be
    # shown "usage: collect.py [-h] [--source {github,...}]".
    if req.kind in NEEDS_SOURCE:
        if not req.source:
            raise HTTPException(400, "Choose where to look before starting.")
        if req.source not in SOURCE_INFO:
            raise HTTPException(
                400, f"{req.source} is not a source this product knows about.")

    argv = JOB_COMMANDS[req.kind](req.source, req.n)
    try:
        job = runner.start(f"{req.kind} {req.source}".strip(), argv)
    except RuntimeError as e:
        # One job at a time: they all write the same SQLite file.
        raise HTTPException(409, str(e)) from e
    return job.as_dict()


@app.get("/api/jobs/current")
def current_job() -> dict:
    return runner.current.as_dict() if runner.current else {"name": None}


# --- sheet ------------------------------------------------------------------


@app.get("/api/sheet")
def sheet() -> dict:
    """The Google Sheet as rows, or a clear explanation of what is missing.

    A missing credential is the expected state on a fresh install, so this returns
    200 with guidance rather than an error the UI has to special-case.
    """
    st = sheets.status()
    if not st.configured:
        return {"configured": False, "detail": st.detail, "url": st.url}
    try:
        values = sheets.Sheet().read()
    except Exception as e:
        return {"configured": False, "detail": str(e), "url": st.url}
    return {
        "configured": True,
        "url": st.url,
        "headers": values[0] if values else [],
        "rows": values[1:] if len(values) > 1 else [],
    }


class PushRequest(BaseModel):
    thesis: str
    limit: int = 200


@app.post("/api/sheet/push")
def push_to_sheet(req: PushRequest) -> dict:
    """Append findings for one fund. Never touches rows already there."""
    from vc_alpha.output.sheets_writer import push

    thesis = next((t for t in theses.load_all() if t.id == req.thesis), None)
    if not thesis:
        raise HTTPException(404, "no such fund")
    conn = db()
    return push(conn, thesis, score.ranked(conn, req.thesis, limit=req.limit)).as_dict()


class CellEdit(BaseModel):
    row: int      # 1-indexed, including the header row
    column: int   # 1-indexed
    value: str


@app.post("/api/sheet/cell")
def edit_cell(edit: CellEdit) -> dict:
    """Write one cell straight back to Google.

    One cell rather than a range: this writes exactly what a person just typed,
    and a wider write could clobber a neighbouring edit made in the Google UI
    between our read and our write.
    """
    try:
        sheets.Sheet().update_cell(edit.row, edit.column, edit.value)
    except sheets.SheetsUnavailable as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@app.get("/api/setup")
def setup() -> dict:
    """Exactly what is still missing, where each piece comes from, and — now —
    somewhere to put it.

    Everything here is free and none of it needs a payment card. No value is ever
    returned, only whether one is present: a key readable from the UI is a key
    that leaks through a screenshot or a support request.
    """
    st = sheets.status()
    items = [
        {
            "name": p.name,
            "env": p.env_key,
            "present": p.configured and not p.local,
            "optional": True,
            "settable": p.env_key in secrets.SETTABLE,
            "unlocks": "Triage and research" if not p.local else "Offline fallback",
            "where": secrets.WHERE.get(
                p.env_key, "ollama.com — runs locally, no account"),
        }
        for p in LADDER
    ]
    # Embedding rungs that are not also inference rungs. Stage 2 runs over
    # everything, so which of these is set is the single biggest lever on how long
    # a run takes: measured, 12.5 ms an item hosted against 2,400 ms locally.
    seen = {p.env_key for p in LADDER}
    items += [
        {
            "name": f"{p.name} (embeddings)",
            "env": p.env_key,
            "present": p.configured and not p.local,
            "optional": True,
            "settable": True,
            "unlocks": "Stage 2 embedding, ~190x faster than local",
            "where": secrets.WHERE.get(p.env_key, ""),
        }
        for p in EMBEDDERS if not p.local and p.env_key not in seen
    ]
    items.append({
        "name": "reddit", "env": "REDDIT_CLIENT_ID", "extra_env": "REDDIT_CLIENT_SECRET",
        "present": bool(os.environ.get("REDDIT_CLIENT_ID"))
                   and bool(os.environ.get("REDDIT_CLIENT_SECRET")),
        "optional": True, "settable": True,
        "unlocks": "The Reddit collector",
        "where": secrets.WHERE["REDDIT_CLIENT_ID"],
    })
    items.append({
        "name": "google sheets", "env": sheets.SHEET_ENV,
        "present": st.configured, "optional": True, "settable": True,
        "unlocks": "Writing findings to a sheet, and editing it here",
        "where": st.detail,
    })
    items.append({
        "name": "linkedin", "env": "LINKEDIN_SESSION_COOKIE",
        "present": bool(os.environ.get("LINKEDIN_SESSION_COOKIE")),
        "optional": True, "settable": True,
        "unlocks": "The LinkedIn collector. Use a secondary account.",
        "where": secrets.WHERE["LINKEDIN_SESSION_COOKIE"],
    })
    return {"items": items, "stored_in": str(paths.env_file())}


class KeyEdit(BaseModel):
    name: str
    value: str


@app.post("/api/setup/key")
def save_key(edit: KeyEdit) -> dict:
    """Save one credential and apply it to the running process.

    This is what makes the product usable by someone who does not want to know
    what an environment variable is. An empty value clears the key, so the same
    endpoint covers removing one.
    """
    try:
        secrets.save(edit.name, edit.value)
    except secrets.NotSettable as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "present": bool(os.environ.get(edit.name))}


@app.post("/api/setup/test")
def test_key(edit: KeyEdit) -> dict:
    """Spend one call proving a key works, rather than waiting for a run to fail.

    A key that is present but wrong is worse than a missing one: the product
    reports itself configured and then every call fails somewhere less visible.
    """
    provider = next((p for p in LADDER if p.env_key == edit.name), None)
    if not provider:
        embedder = next((p for p in EMBEDDERS if p.env_key == edit.name), None)
        if not embedder:
            raise HTTPException(400, "not a provider key")
        try:
            from vc_alpha.enrich.embed import Embedder
            vec = Embedder(provider=embedder).embed("a test sentence")
            return {"ok": True, "detail": f"{len(vec)}-dimension embeddings"}
        except Exception as e:
            return {"ok": False, "detail": str(e)[:200]}

    try:
        answer = Router(db(), ladder=[provider]).complete(
            "Reply with the single word: ready", sending=Sending.PUBLIC)
        return {"ok": True, "detail": f"{provider.model} answered"}
    except Exception as e:
        return {"ok": False, "detail": str(e)[:200]}


class ForgetRequest(BaseModel):
    author: str
    confirm: bool = False


@app.post("/api/forget")
def forget(req: ForgetRequest) -> dict:
    """Erase one person from every table, on request.

    GDPR gives a person the right to be erased and the fund the obligation to do
    it. Before this the only route was opening a Python shell and importing a
    function, which is not a procedure a fund can follow under a deadline.

    Called without `confirm` it reports what would go, so the operator sees the
    scope before anything is deleted.
    """
    author = req.author.strip()
    if not author:
        raise HTTPException(400, "name the person to erase")

    conn = db()
    if not req.confirm:
        counts = {
            "candidates": conn.execute(
                "SELECT COUNT(*) FROM candidates WHERE author = ?", (author,)
            ).fetchone()[0],
            "whatsapp_messages": conn.execute(
                "SELECT COUNT(*) FROM whatsapp_messages WHERE sender = ?", (author,)
            ).fetchone()[0],
        }
        return {"confirmed": False, "would_delete": counts,
                "detail": f"Erasing {author} removes these rows permanently."}

    return {"confirmed": True, "deleted": forget_author(conn, author),
            "detail": f"{author} has been erased."}


@app.get("/api/retention")
def retention() -> dict:
    """What the retention policy is and what it is about to remove."""
    from vc_alpha.db import RETENTION_DAYS

    conn = db()
    return {
        "retention_days": RETENTION_DAYS,
        "expiring_within_7_days": expiring_within(conn, 7),
        "total": conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
    }


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def serve() -> None:
    """Console entry point: `uv run vc-alpha`."""
    import uvicorn

    host = os.environ.get("VC_ALPHA_HOST", "127.0.0.1")
    port = int(os.environ.get("VC_ALPHA_PORT", "8420"))
    print(f"\n  VC Alpha Signal Finder  ->  http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
