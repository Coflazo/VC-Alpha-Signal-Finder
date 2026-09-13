"""What the model is asked, and how a fund weights the answers.

The pipeline used to produce one `thesis_match` float. That conflates questions
that are genuinely separate: whether a company is being built at all, whether it
fits this fund, whether they are raising now, and whether the founder looks like
the kind of person the evidence says succeeds.

Predicting each separately and combining them with weights at serving time means a
fund changes behaviour by editing numbers in its own config. No retraining, and no
shared model that has to be right for every fund at once. This is the multi-action
pattern from the six-stage ranking framework, and it matters more here than in a
feed, because different funds genuinely disagree about what a good lead is.

Signals are scored candidate-isolated, so the pipeline stays deterministic and
cacheable.
"""

from __future__ import annotations

from dataclasses import dataclass

from vc_alpha.schema import strict_object


@dataclass(frozen=True, slots=True)
class Signal:
    key: str
    question: str
    default_weight: float
    # Negative signals subtract. A company two rounds past this fund's stage is
    # not a weak match, it is the wrong answer.
    negative: bool = False


SIGNALS = (
    Signal("is_building", "Is a real company or product being built here, rather "
           "than discussed, reported on, or asked about?", 0.25),
    Signal("thesis_fit", "Does this match the fund's thesis as written?", 0.30),
    Signal("founder_quality", "Does the author show the signals that predict "
           "early-stage outcomes: relevant industry experience before founding, "
           "prior shipped work, technical depth, having hit this problem "
           "themselves?", 0.25),
    Signal("timing", "Are they raising now, about to raise, or at a moment where "
           "an investor conversation would be welcome?", 0.15),
    Signal("reachable", "Is there a plausible route to this person: a named "
           "individual, a company, a contactable presence?", 0.05),
    Signal("too_late", "Have they already raised beyond this fund's stage, or been "
           "widely covered already?", 0.30, negative=True),
)

BY_KEY = {s.key: s for s in SIGNALS}


def default_weights() -> dict[str, float]:
    return {s.key: s.default_weight for s in SIGNALS}


def combine(scores: dict[str, float], weights: dict[str, float] | None = None) -> float:
    """Weighted sum, negatives subtracting, clamped to 0..1.

    Deliberately a linear sum rather than anything learned. With a handful of
    labels a fitted model would look more authoritative while being less true, and
    a partner can read this one and disagree with it, which is the point.
    """
    w = {**default_weights(), **(weights or {})}
    total = 0.0
    for sig in SIGNALS:
        value = float(scores.get(sig.key) or 0.0)
        weight = float(w.get(sig.key, sig.default_weight))
        total += -weight * value if sig.negative else weight * value

    # Positive weights only, so a fund that zeroes a signal does not inflate the rest.
    denom = sum(
        abs(float(w.get(s.key, s.default_weight))) for s in SIGNALS if not s.negative
    )
    return max(0.0, min(1.0, total / denom)) if denom else 0.0


def explain(scores: dict[str, float], weights: dict[str, float] | None = None) -> list[dict]:
    """Per-signal contribution, so a ranking can be read rather than trusted."""
    w = {**default_weights(), **(weights or {})}
    out = []
    for sig in SIGNALS:
        value = float(scores.get(sig.key) or 0.0)
        weight = float(w.get(sig.key, sig.default_weight))
        out.append({
            "key": sig.key,
            "value": value,
            "weight": weight,
            "contribution": (-weight * value if sig.negative else weight * value),
            "negative": sig.negative,
        })
    return sorted(out, key=lambda d: abs(d["contribution"]), reverse=True)


def schema() -> dict:
    """JSON schema for the triage call: every signal, plus its evidence.

    The quote is required, not optional. A signal with no quote cannot be checked,
    and an analyst who cannot check a claim will redo the work, which defeats the
    entire purpose of the product.
    """
    # additionalProperties must be false on *every* object, including nested ones.
    # Providers running strict structured-output mode reject the schema outright
    # otherwise, with a 400 rather than a degraded answer. Found by calling a real
    # endpoint; no amount of local testing would have surfaced it.
    props = {
        s.key: strict_object({
            "score": {"type": "number", "description": "0 to 1"},
            "quote": {"type": "string",
                      "description": "Verbatim text supporting this, or empty if none"},
        })
        for s in SIGNALS
    }
    props["stage"] = {
        "type": "string",
        "enum": ["idea", "prototype", "pre-seed", "seed", "later", "unknown"],
    }
    props["summary"] = {"type": "string", "description": "One sentence on the company"}
    return strict_object(props)
