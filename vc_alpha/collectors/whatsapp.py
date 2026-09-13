"""WhatsApp group exports.

The only source here that reads private material. Everything else in the system
reads things people chose to publish; a group export is a conversation among
people who did not agree to be analysed. That is handled in code rather than in a
comment: the whole export is stored locally, embedding runs locally, and only a
redacted fragment ever reaches a cloud model. See vc_alpha/redact.py.

Format notes, since WhatsApp is inconsistent about this:
  - iOS exports a .zip containing _chat.txt; Android exports a bare .txt
  - three locale timestamp shapes are in the wild, all handled below
  - a line starting with a timestamp begins a message, anything else continues
    the previous one, which is how multi-line messages survive
  - system messages have a timestamp but no sender, and are dropped
  - exports are littered with invisible LTR/RTL marks that break naive regexes
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path

from vc_alpha import paths
from vc_alpha.collectors.base import CandidateRecord, Collector, Neighbour, Visit
from vc_alpha.db import now, retention_until
from vc_alpha.redact import looks_like_lead

log = logging.getLogger(__name__)

# Resolved on use, not at import: see vc_alpha/paths.py.

# WhatsApp sprinkles these through exports; they break anchored patterns.
_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‬﻿"), None)

# [DD/MM/YYYY, HH:MM:SS] Sender: text     (iOS, bracketed)
# DD/MM/YYYY, HH:MM - Sender: text        (Android, dash)
# both with optional am/pm and 2- or 4-digit years, and ISO dates.
_LINE = re.compile(
    r"""^\[?\s*
        (?P<ts>
            \d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}      # 15/01/2024 or 2024-01-15
            ,?\s+
            \d{1,2}:\d{2}(?::\d{2})?             # 14:23 or 14:23:01
            (?:\s*[APap]\.?[Mm]\.?)?             # optional am/pm
        )
        \s*[\]]?\s*
        (?:-\s*)?                                # Android's separator
        (?P<rest>.*)$""",
    re.X,
)

# Attachment placeholders carry no signal and inflate the archive.
_NOISE = re.compile(
    r"^(<media omitted>|image omitted|video omitted|audio omitted|sticker omitted|"
    r"gif omitted|document omitted|this message was deleted|you deleted this message|"
    r"missed voice call|missed video call|null)$",
    re.I,
)


@dataclass(slots=True)
class Message:
    chat: str
    sender: str | None
    sent_at: str | None
    text: str
    line_no: int

    @property
    def id(self) -> str:
        raw = f"{self.chat}|{self.sent_at}|{self.sender}|{self.text}"
        return hashlib.sha256(raw.encode()).hexdigest()


def _split_sender(rest: str) -> tuple[str | None, str]:
    """Separate 'Sender: text'. No colon means a system message, which has no sender.

    Only splits on the first colon followed by a space, so 'Sender: see https://x'
    keeps its URL intact.
    """
    if ": " not in rest:
        return None, rest
    sender, _, text = rest.partition(": ")
    # A 'sender' this long is a system message containing a colon, not a name.
    if len(sender) > 60 or "\n" in sender:
        return None, rest
    return sender.strip(), text


def parse(text: str, chat: str) -> list[Message]:
    messages: list[Message] = []
    for i, raw in enumerate(text.translate(_INVISIBLE).splitlines(), start=1):
        line = raw.rstrip()
        if not line:
            continue
        m = _LINE.match(line)
        if not m:
            # Continuation of the previous message.
            if messages:
                messages[-1].text += "\n" + line.strip()
            continue

        sender, body = _split_sender(m.group("rest").strip())
        if sender is None:
            continue  # system message
        if _NOISE.match(body.strip()):
            continue
        messages.append(
            Message(chat=chat, sender=sender, sent_at=m.group("ts"),
                    text=body.strip(), line_no=i)
        )
    return messages


def read_export(path: Path) -> list[Message]:
    """Read a .zip (iOS) or .txt (Android) export."""
    chat = path.stem.replace("WhatsApp Chat with ", "").replace("_chat", "").strip()
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".txt")]
            if not names:
                log.warning("no .txt inside %s", path.name)
                return []
            body = z.read(names[0]).decode("utf-8", errors="replace")
    else:
        body = path.read_text(encoding="utf-8", errors="replace")
    return parse(body, chat)


def store(conn: sqlite3.Connection, messages: list[Message]) -> int:
    """Persist the whole export. Returns how many rows were new."""
    new = 0
    for m in messages:
        new += conn.execute(
            """INSERT OR IGNORE INTO whatsapp_messages
               (id, chat, sender, sent_at, text, line_no, retention_until)
               VALUES (?,?,?,?,?,?,?)""",
            (m.id, m.chat, m.sender, m.sent_at, m.text, m.line_no, retention_until()),
        ).rowcount
    conn.commit()
    return new


class WhatsAppCollector(Collector):
    """A node is one export file. Chats have no neighbours, so none are returned.

    Following participants from group to group would be an expansion the other
    sources justify and this one does not: it would mean profiling people across
    private conversations they are in for unrelated reasons.
    """

    source = "whatsapp"
    # Never cloud, whatever keys are configured. Enforced by the pipeline, stated
    # here so it is visible at the source rather than buried in a config file.
    local_embedding_only = True

    def __init__(self, conn: sqlite3.Connection, export_dir: Path | None = None):
        self.conn = conn
        self.export_dir = Path(export_dir) if export_dir else paths.whatsapp_dir()

    def seeds(self):
        if not self.export_dir.exists():
            return []
        return [
            Neighbour(p.name, p.stem)
            for p in sorted(self.export_dir.iterdir())
            if p.suffix.lower() in (".zip", ".txt")
        ]

    def visit(self, node: str) -> Visit:
        path = self.export_dir / node
        if not path.exists():
            log.warning("export missing: %s", path)
            return Visit(exhausted=True)

        messages = read_export(path)
        store(self.conn, messages)

        # Promote only what looks like a lead. The rest stays in the archive and
        # never reaches the pipeline, so the frontier's hit-rate stats stay honest.
        candidates = []
        for m in messages:
            if not looks_like_lead(m.text):
                continue
            candidates.append(
                CandidateRecord(
                    source=self.source,
                    source_url=f"whatsapp://{m.chat}#{m.id[:16]}",
                    raw_text=m.text,
                    title=f"{m.chat}: {m.text[:60]}",
                    author=m.sender,
                    node=node,
                    posted_at=m.sent_at,
                )
            )
            self.conn.execute(
                "UPDATE whatsapp_messages SET promoted = 1 WHERE id = ?", (m.id,)
            )
        self.conn.commit()

        log.info("%s: %d messages, %d promoted", node, len(messages), len(candidates))
        # A file does not grow between runs.
        return Visit(candidates=candidates, neighbours=[], exhausted=True)
