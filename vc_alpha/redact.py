"""Strip a private message down to the fragment that carries the lead.

WhatsApp group chats are private conversations among people who never agreed to
have their messages analysed. The agreed handling is: keep the whole export
locally, embed it locally, and send only an extracted fragment to a cloud model.

This module is that extraction. It is deliberately blunt. Anything it is unsure
about it removes, because the cost of over-redacting is a slightly worse triage
decision and the cost of under-redacting is someone's private conversation in a
third party's training data.
"""

from __future__ import annotations

import re

# Lines that carry a lead: a link, or somebody describing a company doing something.
_URL = re.compile(r"https?://\S+")
_PHONE = re.compile(r"[+(]?\d[\d\s().-]{6,}\d")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_HANDLE = re.compile(r"[@~]\w[\w.-]*")

# Sentence-ish split that survives missing punctuation in chat messages.
_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

LEAD_HINTS = (
    "raised", "raising", "launched", "launching", "building", "built", "founded",
    "co-founder", "cofounder", "founder", "startup", "seed", "pre-seed", "series a",
    "yc ", "demo day", "pitch", "spun out", "stealth", "hiring", "shipped",
)


def looks_like_lead(text: str) -> bool:
    """Cheap promotion test. Generous on purpose: the embedding decides properly.

    Getting this wrong in the permissive direction costs one local embedding.
    Getting it wrong the other way loses the lead entirely.
    """
    low = text.lower()
    return bool(_URL.search(text)) or any(h in low for h in LEAD_HINTS)


def scrub(text: str) -> str:
    """Remove the identifiers a fragment never needs."""
    text = _EMAIL.sub("[email]", text)
    text = _PHONE.sub("[phone]", text)
    text = _HANDLE.sub("[handle]", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def extract(text: str, *, known_names: set[str] | None = None, max_chars: int = 400) -> str:
    """Return only the sentences that carry the lead, scrubbed of identifiers.

    Surrounding conversation is dropped rather than trimmed. A neighbouring message
    about someone's divorce is not made acceptable to send by being short.
    """
    parts = [p.strip() for p in _SPLIT.split(text) if p.strip()]
    kept = [p for p in parts if looks_like_lead(p)] or parts[:1]

    out = scrub(" ".join(kept))
    for name in sorted(known_names or (), key=len, reverse=True):
        if len(name) > 2:
            out = re.sub(rf"\b{re.escape(name)}\b", "[name]", out, flags=re.I)
    return out[:max_chars]
