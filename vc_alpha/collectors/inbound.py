"""A fund's own inbound: forwarded emails and application-form exports.

This is the collector that addresses the bottleneck the research actually
identified. Funds do not lack access to companies; they lack the analyst bandwidth
to evaluate what already arrives. A $200M fund takes 3,000 inbound enquiries a year
and closes ten. Every other source here guesses at what might be interesting;
inbound is pre-qualified by the founder's own decision to reach out.

It also produces labelled data faster than anything else, because a fund already
knows which inbound got a meeting.

Deliberately file-based. A watched folder of .eml files and a CSV export need no
OAuth, no integration and no permission from anyone's IT department, which means a
fund can try this in ten minutes.
"""

from __future__ import annotations

import csv
import email
import email.policy
import logging
from pathlib import Path

from vc_alpha.collectors.base import CandidateRecord, Collector, Neighbour, Visit

log = logging.getLogger(__name__)

INBOX_DIR = Path("data/inbound")

# Forwarding wrappers and signature blocks carry no signal and drown the pitch.
_CUT_AT = (
    "\n-----original message-----",
    "\n--- forwarded message ---",
    "\n---------- forwarded message ----------",
    "\nsent from my ",
    "\nunsubscribe",
    "\nconfidentiality notice",
)


def _body(msg: email.message.Message) -> str:
    """Plain text if offered, otherwise fall back to whatever is there."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_content()
                except Exception:
                    continue
        return ""
    try:
        return msg.get_content()
    except Exception:
        return str(msg.get_payload())


def trim(text: str) -> str:
    """Drop quoted history and signatures. The pitch is at the top."""
    low = text.lower()
    cut = min((low.find(m) for m in _CUT_AT if low.find(m) > 0), default=-1)
    return (text[:cut] if cut > 0 else text).strip()


def read_eml(path: Path) -> CandidateRecord | None:
    try:
        msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    except Exception as e:
        log.warning("could not parse %s: %s", path.name, e)
        return None

    subject = str(msg.get("subject") or path.stem)
    sender = str(msg.get("from") or "")
    body = trim(_body(msg))
    if not body and not subject:
        return None

    return CandidateRecord(
        source="inbound",
        # The file name is the identity: the same email re-dropped is the same lead.
        source_url=f"inbound://{path.name}",
        raw_text=f"{subject}\n\n{body}",
        title=subject,
        author=sender,
        node=path.parent.name,
        posted_at=str(msg.get("date") or "") or None,
    )


def read_csv(path: Path) -> list[CandidateRecord]:
    """An application-form export. Column names vary, so match them loosely."""
    out: list[CandidateRecord] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            lower = {(k or "").strip().lower(): (v or "") for k, v in row.items()}

            def pick(*names: str) -> str:
                for n in names:
                    for key, value in lower.items():
                        if n in key and value.strip():
                            return value.strip()
                return ""

            name = pick("company", "startup", "name")
            pitch = pick("description", "pitch", "what", "summary", "about")
            if not (name or pitch):
                continue
            out.append(CandidateRecord(
                source="inbound",
                source_url=f"inbound://{path.name}#{i}",
                raw_text="\n\n".join(filter(None, [
                    name, pitch, pick("website", "url"), pick("stage"),
                    pick("raising", "round"), pick("founder", "team"),
                ])),
                title=name or pitch[:80],
                author=pick("founder", "contact", "email"),
                node=path.name,
            ))
    return out


class InboundCollector(Collector):
    """A node is one folder of inbound. No neighbours: inbound does not branch."""

    source = "inbound"
    local_only = True   # a fund's private deal flow stays on the fund's machine

    def __init__(self, inbox: Path = INBOX_DIR):
        self.inbox = Path(inbox)

    def seeds(self):
        if not self.inbox.exists():
            return []
        folders = [p for p in self.inbox.iterdir() if p.is_dir()]
        return [Neighbour(p.name, p.name) for p in folders] or [Neighbour(".", "inbox")]

    def visit(self, node: str) -> Visit:
        folder = self.inbox if node == "." else self.inbox / node
        if not folder.exists():
            return Visit(exhausted=True)

        records: list[CandidateRecord] = []
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() == ".eml":
                if rec := read_eml(path):
                    records.append(rec)
            elif path.suffix.lower() == ".csv":
                records.extend(read_csv(path))

        log.info("%s: %d inbound leads", node, len(records))
        # A folder does not grow on its own; re-running picks up new files.
        return Visit(candidates=records, neighbours=[], exhausted=False)
