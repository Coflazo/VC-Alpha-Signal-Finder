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

from vc_alpha.llm import NoCapacityLeft, Router, Sending
from vc_alpha.signals import SIGNALS, combine, schema
from vc_alpha.theses import Thesis

log = logging.getLogger(__name__)

ACCEPT_CONFIDENCE = 0.7

SCHEMA = schema()

PROMPT = """You are screening public posts for an early-stage venture fund.

The fund's thesis:
{prose}

Signals that matter to this fund. For each, say whether the post shows it:
{signals}

The post:
---
{text}
---

Score each of these independently, 0 to 1. They are separate questions: a post can
be a real company that does not fit this fund, or a perfect fit that is five years
too late.

{questions}

Also give `stage` (idea, prototype, pre-seed, seed, later, unknown) and a one
sentence `summary`.

For every signal include a `quote`: the verbatim words from the post that led you
to that score. If nothing in the text supports it, score it low and leave the quote
empty. Do not paraphrase and do not invent a quote — an analyst will check it
against the source, and a fabricated one is worse than a low score."""


def build_prompt(text: str, thesis: Thesis, max_chars: int = 6000) -> str:
    signals = "\n".join(f"- {s}" for s in thesis.hard_signals) or "- (none specified)"
    questions = "\n".join(f"- {s.key}: {s.question}" for s in SIGNALS)
    return PROMPT.format(
        prose=thesis.prose.strip(), signals=signals,
        questions=questions, text=text[:max_chars],
    )


def triage_one(
    router: Router, text: str, thesis: Thesis, sending: Sending = Sending.PUBLIC
) -> dict:
    """Screen one candidate.

    `sending` defaults to PUBLIC because five of six sources are published material,
    but WhatsApp passes Sending.REDACTED with a fragment from vc_alpha.redact rather
    than the raw message.

    The thesis prose does go into the prompt. That is a deliberate, narrow exception:
    screening cannot happen without telling the model what it is screening for. A
    fund that objects points the router at a local endpoint, which is one config
    value and no code change.
    """
    return router.complete(build_prompt(text, thesis), schema=SCHEMA, sending=sending)


def run(
    conn: sqlite3.Connection,
    router: Router,
    theses: list[Thesis],
    *,
    threshold: float,
    limit: int = 50,
    sending: Sending = Sending.PUBLIC,
    source: str | None = None,
) -> dict[str, int]:
    """Triage everything that passed stage 2 and has not been triaged yet.

    `source` narrows to one collector. Useful when a fund wants its own inbound
    screened first, and when only some sources yield entities worth a dossier.
    """
    by_id = {t.id: t for t in theses}
    sql = ["""SELECT id, raw_text, title, thesis_id FROM candidates
              WHERE similarity >= ? AND triage_json IS NULL"""]
    params: list = [threshold]
    if source:
        sql.append("AND source = ?")
        params.append(source)
    sql.append("ORDER BY similarity DESC LIMIT ?")
    params.append(limit)
    rows = conn.execute(" ".join(sql), params).fetchall()

    stats = {"triaged": 0, "startups": 0, "invalid_json": 0, "no_capacity": 0}

    for row in rows:
        thesis = by_id.get(row["thesis_id"]) or theses[0]
        try:
            verdict = triage_one(router, row["raw_text"], thesis, sending)
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

        scores = {
            s.key: float((verdict.get(s.key) or {}).get("score") or 0.0)
            for s in SIGNALS
        }
        conn.execute(
            """UPDATE candidates
               SET triage_json = ?, is_startup = ?, stage_guess = ?, confidence = ?
               WHERE id = ?""",
            (json.dumps(verdict),
             int(scores["is_building"] >= 0.5),
             verdict.get("stage"),
             combine(scores, thesis.weights),
             row["id"]),
        )
        conn.commit()
        stats["triaged"] += 1
        stats["startups"] += int(scores["is_building"] >= 0.5)

    return stats
