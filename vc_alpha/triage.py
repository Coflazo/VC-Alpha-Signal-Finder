"""Stage 3: decide whether a candidate is actually a startup worth looking at.

Stage 2 answers "is this topically near the thesis". That is not the same question.
A post can sit right next to a thesis in embedding space and still be a journalist
writing about the sector, a student asking for advice, or a company five years and
three rounds past the window. Only a model reading the text can tell those apart.

Each thesis carries `hard_signals`, the things keyword search cannot see: founder
origin, immigrant status, whether a category exists yet. Those are asked explicitly
rather than left to inference, because a model that is not asked about immigrant
status will not volunteer it.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from vc_alpha.llm import NoCapacityLeft, Router
from vc_alpha.theses import Thesis

log = logging.getLogger(__name__)

ACCEPT_CONFIDENCE = 0.7

SCHEMA = {
    "type": "object",
    "properties": {
        "is_startup": {"type": "boolean"},
        "stage": {
            "type": "string",
            "enum": ["idea", "prototype", "pre-seed", "seed", "later", "unknown"],
        },
        "thesis_match": {"type": "number"},
        "founder_signal": {"type": "boolean"},
        "signals_present": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": [
        "is_startup", "stage", "thesis_match", "founder_signal",
        "signals_present", "reasoning", "confidence",
    ],
}

PROMPT = """You are screening public posts for an early-stage venture fund.

The fund's thesis:
{prose}

Signals that matter to this fund. For each, say whether the post shows it:
{signals}

The post:
---
{text}
---

Answer as JSON only:
- is_startup: is a real company or product being built here? A person asking for
  advice, a journalist writing about the sector, or a hobby project is not.
- stage: idea, prototype, pre-seed, seed, later, or unknown.
- thesis_match: 0 to 1, how well this fits the thesis above.
- founder_signal: is the author the one building it, rather than writing about it?
- signals_present: which of the listed signals the post actually evidences. Only
  ones you can point at in the text. An empty list is a fine answer.
- reasoning: one or two sentences, citing what in the post led you there.
- confidence: 0 to 1, how sure you are. Be honest; low confidence is routed to a
  human rather than held against you."""


def build_prompt(text: str, thesis: Thesis, max_chars: int = 6000) -> str:
    signals = "\n".join(f"- {s}" for s in thesis.hard_signals) or "- (none specified)"
    return PROMPT.format(prose=thesis.prose.strip(), signals=signals, text=text[:max_chars])


def triage_one(router: Router, text: str, thesis: Thesis) -> dict:
    """One candidate. The post is public by definition; the thesis prose is not.

    Note the prose does go into the prompt. That is a deliberate, narrow exception:
    screening cannot work without it. Funds who object should point the router at a
    local or paid endpoint, which is a one-value config change.
    """
    return router.complete(
        build_prompt(text, thesis), schema=SCHEMA, public_text=True
    )


def run(
    conn: sqlite3.Connection,
    router: Router,
    theses: list[Thesis],
    *,
    threshold: float,
    limit: int = 50,
) -> dict[str, int]:
    """Triage everything that passed stage 2 and has not been triaged yet."""
    by_id = {t.id: t for t in theses}
    rows = conn.execute(
        """SELECT id, raw_text, title, thesis_id FROM candidates
           WHERE similarity >= ? AND triage_json IS NULL
           ORDER BY similarity DESC LIMIT ?""",
        (threshold, limit),
    ).fetchall()

    stats = {"triaged": 0, "startups": 0, "invalid_json": 0, "no_capacity": 0}

    for row in rows:
        thesis = by_id.get(row["thesis_id"]) or theses[0]
        try:
            verdict = triage_one(router, row["raw_text"], thesis)
        except NoCapacityLeft:
            # Expected at the end of a day. Stop cleanly; the rest keeps until tomorrow.
            stats["no_capacity"] += 1
            log.warning("out of free capacity, stopping with %d left", len(rows) - stats["triaged"])
            break
        except (ValueError, KeyError) as e:
            # A reply we could not parse. Recorded, not retried: a retry costs a
            # request from an allowance we are trying not to spend.
            stats["invalid_json"] += 1
            log.warning("unparseable reply for %s: %s", row["id"][:8], e)
            continue

        conn.execute(
            """UPDATE candidates
               SET triage_json = ?, is_startup = ?, stage_guess = ?, confidence = ?
               WHERE id = ?""",
            (json.dumps(verdict),
             int(bool(verdict.get("is_startup"))),
             verdict.get("stage"),
             float(verdict.get("confidence") or 0),
             row["id"]),
        )
        conn.commit()
        stats["triaged"] += 1
        stats["startups"] += int(bool(verdict.get("is_startup")))

    return stats
