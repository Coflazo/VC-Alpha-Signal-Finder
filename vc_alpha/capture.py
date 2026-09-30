"""One page, sent from the browser extension while the analyst is looking at it.

Every other source arrives in bulk and has to earn an LLM call by surviving
cheaper stages first. A capture is a page a person chose to send, so it skips the
cheap filters and the similarity gate and goes straight to triage: the click did
the filtering. It is still embedded, so it ranks beside everything else, and it
is stored as an ordinary candidate, so the review queue, the report and the
Sheet see it like any other source.

Two sources, because privacy is decided per page rather than per collector.
`extension` is a page anyone could open. `extension_private` is one the analyst
marked private, such as an email or an internal document. It is handled exactly
like a WhatsApp message: embedded only by a local model, and triaged on a
redacted fragment rather than the text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3

from vc_alpha import score, theses, triage
from vc_alpha.collectors.base import CandidateRecord
from vc_alpha.db import now, retention_until
from vc_alpha.enrich.embed import Embedder, best_similarity, pack, thesis_vectors
from vc_alpha.founders import _quote_is_real
from vc_alpha.llm import NoCapacityLeft, Router, Sending, set_a_key
from vc_alpha.redact import extract
from vc_alpha.signals import SIGNALS
from vc_alpha.theses import Thesis

log = logging.getLogger(__name__)

PUBLIC = "extension"
PRIVATE = "extension_private"

# A whole visible page fits comfortably. Triage reads the first 6,000 characters
# and embedding the first 4,000, so anything beyond this is storage with no use.
MAX_CHARS = 50_000

# Derived from the text. Cleared when a page is captured again, because they
# describe the old text. Review labels are kept: a partner's judgement is about
# the company, not about one snapshot of its page.
_DERIVED = ("embedding", "embedding_model", "similarity", "thesis_id", "triage_json",
            "is_startup", "stage_guess", "confidence", "research_md", "score",
            "filtered_reason")


class UnknownThesis(LookupError):
    pass


def capture(conn: sqlite3.Connection, text: str, *, url: str | None = None,
            title: str | None = None, private: bool = False,
            thesis_id: str | None = None) -> dict:
    """Store one page, embed it, triage it, and report what the engine made of it.

    Raises ValueError for empty or oversized text and UnknownThesis for a fund id
    that is not configured. Everything else returns a result with a `note`, since
    a capture that could not be screened should still be kept.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Nothing was captured. Select some text, or open a page "
                         "that has some.")
    if len(text) > MAX_CHARS:
        raise ValueError(f"That page is {len(text):,} characters. Select the part "
                         f"about the company instead (up to {MAX_CHARS:,}).")

    active = theses.load_all()
    pinned = None
    if thesis_id:
        pinned = next((t for t in active if t.id == thesis_id), None)
        if pinned is None:
            raise UnknownThesis(f"No fund called '{thesis_id}' is configured.")
    eligible = [pinned] if pinned else active

    if eligible and all(t.excluded(text) for t in eligible):
        return _result(conn, None, "excluded",
                       "The fund's thesis excludes this outright, so it was not kept.",
                       thesis=pinned)

    record = CandidateRecord(
        source=PRIVATE if private else PUBLIC,
        source_url=url or "capture:" + hashlib.sha256(text.encode()).hexdigest()[:16],
        raw_text=text, title=title,
    )
    existing = conn.execute("SELECT source, triage_json FROM candidates WHERE id = ?",
                            (record.id,)).fetchone()
    if existing and existing["source"] not in (PUBLIC, PRIVATE):
        # A collector found this first. Its text is the post itself rather than a
        # whole page with navigation and comments, and its source is provenance
        # the report relies on, so neither is overwritten.
        return _result(conn, record.id, "scored" if existing["triage_json"] else "stored",
                       f"Already collected from {existing['source']}. Showing what "
                       "the engine has on it.")
    _save(conn, record, refresh=existing is not None)

    if not active:
        return _result(conn, record.id, "stored", theses.NO_FUNDS)

    embed_note = _embed(conn, record.id, text, eligible, private)
    thesis_row = conn.execute("SELECT thesis_id FROM candidates WHERE id = ?",
                              (record.id,)).fetchone()
    thesis = pinned or next((t for t in active if t.id == thesis_row["thesis_id"]),
                            active[0])
    conn.execute("UPDATE candidates SET thesis_id = ? WHERE id = ?",
                 (thesis.id, record.id))
    conn.commit()

    router = Router(conn)
    if not router.available():
        return _result(conn, record.id, "stored", f"Saved, not screened. {set_a_key()}")

    sent = extract(text) if private else text
    try:
        verdict = triage.triage_one(router, sent, thesis,
                                    Sending.REDACTED if private else Sending.PUBLIC)
    except NoCapacityLeft as e:
        return _result(conn, record.id, "stored", f"Saved, not screened. {e}")
    except (ValueError, KeyError) as e:
        log.warning("unparseable triage reply for capture %s: %s", record.id[:8], e)
        return _result(conn, record.id, "stored", "Saved, not screened: the model's "
                       "reply could not be read. Capture it again to retry.")

    # A fabricated quote looks like evidence and gets trusted instead of checked.
    # Checked against the text the model was actually shown.
    for sig in SIGNALS:
        part = verdict.get(sig.key)
        if isinstance(part, dict) and not _quote_is_real(part.get("quote") or "", sent):
            part["quote"] = ""

    triage.save_verdict(conn, record.id, verdict, thesis)
    score.rescore(conn)
    return _result(conn, record.id, "scored", embed_note)


def _save(conn: sqlite3.Connection, r: CandidateRecord, *, refresh: bool) -> None:
    if refresh:
        cleared = ", ".join(f"{c} = NULL" for c in _DERIVED)
        conn.execute(
            f"UPDATE candidates SET source = ?, raw_text = ?, title = ?, {cleared} "
            "WHERE id = ?", (r.source, r.raw_text, r.title, r.id))
    else:
        conn.execute(
            """INSERT INTO candidates (id, source, source_url, raw_text, title,
               discovered_at, retention_until) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (r.id, r.source, r.source_url, r.raw_text, r.title, now(),
             retention_until()))
    conn.commit()


def _embed(conn: sqlite3.Connection, cid: str, text: str, eligible: list[Thesis],
           private: bool) -> str:
    """Embed and record the best-matching thesis. Returns a note, empty if it worked.

    A failed embedding costs the capture its similarity, not the capture itself.
    """
    emb = Embedder()
    if private and not emb.provider_info.local:
        return "Private page: similarity needs a local embedding model, so it was skipped."
    try:
        if not emb.available():
            return "No embedding model is reachable, so similarity was skipped."
        vec = emb.embed(text)
        # ponytail: thesis vectors are re-embedded on every capture. Two hosted
        # calls is nothing; cache them if a local embedder makes clicks slow.
        vectors = thesis_vectors(emb, eligible)
    except Exception as e:                      # any provider error, same outcome
        log.warning("capture embedding failed: %s", e)
        return "Embedding failed, so similarity was skipped."

    by_id = {t.id: t for t in eligible}
    best_id, best = max(
        ((tid, best_similarity(vec, tv)) for tid, tv in vectors.items()
         if not by_id[tid].excluded(text)),
        key=lambda pair: pair[1], default=(None, None))
    conn.execute(
        "UPDATE candidates SET embedding = ?, embedding_model = ?, similarity = ?, "
        "thesis_id = ? WHERE id = ?",
        (pack(vec), emb.fingerprint, best, best_id, cid))
    conn.commit()
    return ""


def _result(conn: sqlite3.Connection, cid: str | None, status: str, note: str, *,
            thesis: Thesis | None = None) -> dict:
    """What the extension shows. Read back from the row, so it matches the app."""
    out = {"id": cid, "status": status, "source": None,
           "thesis": {"id": thesis.id, "name": thesis.name} if thesis else None,
           "similarity": None, "confidence": None, "score": None, "stage": None,
           "summary": None, "signals": [], "note": note}
    row = conn.execute("SELECT * FROM candidates WHERE id = ?", (cid,)).fetchone() \
        if cid else None
    if row is None:
        return out

    try:
        verdict = json.loads(row["triage_json"]) if row["triage_json"] else {}
    except ValueError:
        verdict = {}
    match = next((t for t in theses.load_all() if t.id == row["thesis_id"]), None)
    out.update(
        source=row["source"],
        thesis={"id": match.id, "name": match.name} if match else out["thesis"],
        similarity=row["similarity"], confidence=row["confidence"], score=row["score"],
        stage=row["stage_guess"], summary=verdict.get("summary"),
        signals=[{"key": s.key, "score": float(part.get("score") or 0.0),
                  "quote": part.get("quote") or ""}
                 for s in SIGNALS if isinstance(part := verdict.get(s.key), dict)],
    )
    return out
