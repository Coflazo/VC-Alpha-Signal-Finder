"""Score an entity from all its evidence, not each post separately.

The research this rests on: team is the strongest early-stage predictor (95% of
885 institutional VCs called it essential), three or more years of relevant
industry experience strongly predicts a top performer, and co-founders with shared
work history survive longer. Seed-stage prediction rests on team signals; traction
matters later.

Two things follow. Scoring belongs at the entity level, because a founder seen
three times is better evidenced than one seen once. And corroboration across
independent sources is itself a signal: the same company surfacing on GitHub and
Hacker News separately is stronger than either sighting alone.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from vc_alpha.entities import evidence, install
from vc_alpha.quant.auction import SOURCE_AUDIENCE, CurseModel
from vc_alpha.signals import SIGNALS, combine
from vc_alpha.theses import Thesis

log = logging.getLogger(__name__)

# How much a second and third independent source are worth. Corroboration is real
# signal but it saturates: two sources is much better than one, five is not much
# better than three, and letting it grow without limit would rank prolific posters
# above good companies.
CORROBORATION = {1: 1.00, 2: 1.12, 3: 1.20}
CORROBORATION_MAX = 1.25


def corroboration(sources: int) -> float:
    return CORROBORATION.get(sources, CORROBORATION_MAX if sources > 3 else 1.0)


def _quote_is_real(quote: str, source_text: str) -> bool:
    """Does this quote actually appear in the post?

    Models fabricate supporting quotes, and a fabricated one is worse than no quote
    at all: it looks like evidence, so it gets trusted rather than checked. Compared
    on collapsed whitespace and casing, since models reflow text they copy.
    """
    if not quote.strip():
        return False
    norm = lambda s: " ".join(s.lower().split())
    return norm(quote) in norm(source_text or "")


def aggregate(rows: list[sqlite3.Row]) -> tuple[dict[str, float], list[dict]]:
    """Best score per signal across every piece of evidence, with its quote.

    Max rather than mean. Evidence is not a poll: one post that clearly shows a
    founder shipped something before is not weakened by three others that happen
    not to mention it. Absence of evidence in one post is not evidence of absence.
    """
    best: dict[str, float] = {}
    quotes: dict[str, dict] = {}

    for row in rows:
        if not row["triage_json"]:
            continue
        try:
            verdict = json.loads(row["triage_json"])
        except (ValueError, TypeError):
            continue
        for sig in SIGNALS:
            block = verdict.get(sig.key) or {}
            value = float(block.get("score") or 0.0)
            if value <= best.get(sig.key, -1.0):
                continue
            quote = (block.get("quote") or "").strip()
            verified = _quote_is_real(quote, row["raw_text"] or "")
            best[sig.key] = value
            quotes[sig.key] = {
                "signal": sig.key,
                "score": value,
                # A quote that is not in the source is dropped rather than shown.
                "quote": quote if verified else "",
                "fabricated": bool(quote) and not verified,
                "source": row["source"],
                "url": row["source_url"],
            }

    return best, [quotes[k] for k in sorted(quotes, key=lambda k: -quotes[k]["score"])]


def score_entity(
    conn: sqlite3.Connection, entity_id: str, thesis: Thesis
) -> dict | None:
    """Score one entity against one fund. Returns None when nothing is triaged yet."""
    rows = evidence(conn, entity_id)
    if not rows:
        return None

    scores, supporting = aggregate(rows)
    if not scores:
        return None

    distinct_sources = len({r["source"] for r in rows})
    base = combine(scores, thesis.weights)
    corroborated = min(1.0, base * corroboration(distinct_sources))

    # Winner's curse. A deal visible to two hundred funds is worth less than an
    # identically-scored one visible to three, because conditional on winning a
    # crowded process your signal was the maximum of many noisy draws and was
    # therefore biased upward. The correction uses the least crowded source the
    # entity was seen in: if you learned about it privately, you are not competing
    # with everyone who could have read the public version.
    curse = CurseModel()
    sources = {r["source"] for r in rows}
    penalty = min(
        (curse.penalty(SOURCE_AUDIENCE.get(s, 100)) for s in sources), default=0.0
    )
    final = max(0.0, corroborated - penalty)

    return {
        "thesis": thesis.id,
        "base": round(base, 4),
        "corroboration": corroboration(distinct_sources),
        "curse_penalty": round(penalty, 4),
        "score_before_curse": round(corroborated, 4),
        "score": round(final, 4),
        "sources": distinct_sources,
        "evidence_count": len(rows),
        "signals": scores,
        # Quotes without a source URL are unverifiable, so they do not appear.
        "support": [s for s in supporting if s["quote"] and s["url"]],
    }


def score_all(conn: sqlite3.Connection, theses: list[Thesis]) -> dict[str, int]:
    """Score every entity against every thesis, keeping the best fund per entity."""
    install(conn)
    stats = {"scored": 0, "skipped": 0}

    for (entity_id,) in conn.execute("SELECT id FROM entities").fetchall():
        best = None
        for thesis in theses:
            result = score_entity(conn, entity_id, thesis)
            if result and (best is None or result["score"] > best["score"]):
                best = result
        if not best:
            stats["skipped"] += 1
            continue
        conn.execute(
            "UPDATE entities SET score = ?, signals_json = ? WHERE id = ?",
            (best["score"], json.dumps(best), entity_id),
        )
        stats["scored"] += 1

    conn.commit()
    return stats
