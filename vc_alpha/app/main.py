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
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vc_alpha import entities, founders, score, theses, warmpath
from vc_alpha.app import sheets
from vc_alpha.app.jobs import runner
from vc_alpha.db import connect
from vc_alpha.llm import LADDER, Router

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
DB = os.environ.get("VC_ALPHA_DB", "data/candidates.sqlite")

# Sources that cannot run on a shared runner, and why. Surfaced in the UI so the
# split is visible rather than folklore.
LOCAL_ONLY = {
    "substack": "Substack returns 403 to datacenter IP ranges",
    "whatsapp": "private exports never leave this machine",
    "linkedin": "a datacenter IP is the fastest way to get flagged",
}

app = FastAPI(title="VC Alpha Signal Finder")


def db() -> sqlite3.Connection:
    return connect(DB)


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
                "configured": bool(p.key),
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
               unreviewed: bool = True) -> dict:
    """The review queue, best first."""
    sql = ["SELECT * FROM candidates WHERE similarity IS NOT NULL"]
    params: list = []
    if thesis:
        sql.append("AND thesis_id = ?")
        params.append(thesis)
    if unreviewed:
        sql.append("AND reviewed = 0")
    sql.append("ORDER BY COALESCE(score, similarity) DESC LIMIT ?")
    params.append(limit)

    rows = []
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
    return {"candidates": rows}


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

    paths = [
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
        "warm_paths": paths,
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


class JobRequest(BaseModel):
    kind: str
    source: str = "hackernews"
    n: int = 10


@app.post("/api/jobs")
def start_job(req: JobRequest) -> dict:
    if req.kind not in JOB_COMMANDS:
        raise HTTPException(400, f"unknown job: {req.kind}")
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
    """Exactly what is still missing, and where each piece comes from.

    Everything here is free and none of it needs a payment card.
    """
    st = sheets.status()
    items = [
        {
            "name": p.name,
            "env": p.env_key,
            "present": bool(p.key) and not p.local,
            "optional": True,
            "unlocks": "Triage and research" if not p.local else "Offline fallback",
            "where": {
                "gemini": "https://aistudio.google.com",
                "groq": "https://console.groq.com",
                "cerebras": "https://cloud.cerebras.ai",
                "github": "https://github.com/settings/tokens",
                "openrouter": "https://openrouter.ai/keys",
                "ollama": "https://ollama.com — runs locally, no account",
            }.get(p.name, ""),
        }
        for p in LADDER
    ]
    items.append({
        "name": "reddit", "env": "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET",
        "present": bool(os.environ.get("REDDIT_CLIENT_ID")), "optional": True,
        "unlocks": "The Reddit collector",
        "where": "https://www.reddit.com/prefs/apps — script type, two minutes",
    })
    items.append({
        "name": "google sheets", "env": sheets.SHEET_ENV,
        "present": st.configured, "optional": True,
        "unlocks": "Writing findings to a sheet, and editing it here",
        "where": st.detail,
    })
    items.append({
        "name": "linkedin", "env": "LINKEDIN_SESSION_COOKIE",
        "present": bool(os.environ.get("LINKEDIN_SESSION_COOKIE")), "optional": True,
        "unlocks": "The LinkedIn collector. Use a secondary account.",
        "where": "Copy the li_at cookie from a logged-in browser",
    })
    return {"items": items}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def serve() -> None:
    """Console entry point: `uv run vc-alpha`."""
    import uvicorn

    host = os.environ.get("VC_ALPHA_HOST", "127.0.0.1")
    port = int(os.environ.get("VC_ALPHA_PORT", "8420"))
    print(f"\n  VC Alpha Signal Finder  ->  http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
