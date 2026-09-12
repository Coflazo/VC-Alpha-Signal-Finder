"""WhatsApp parsing, promotion and redaction.

Fixtures are synthetic. No real chat data belongs in a repo, least of all one that
might go public.
"""

import sqlite3
import zipfile
from pathlib import Path

import pytest

from vc_alpha.collectors.whatsapp import WhatsAppCollector, parse, read_export, store
from vc_alpha.db import SCHEMA, purge_expired
from vc_alpha.llm import PrivateTextRefused, Router, Sending
from vc_alpha.redact import extract, looks_like_lead, scrub

IOS = """[15/01/2024, 14:23:01] Ayse: morning all
[15/01/2024, 14:24:10] Mehmet: my friend just raised a seed round for https://acme.io
[15/01/2024, 14:25:00] Ayse: <Media omitted>
[15/01/2024, 14:26:00] Mehmet: she's building invoice AI
and looking for design partners
[15/01/2024, 14:27:00] Messages and calls are end-to-end encrypted.
"""

ANDROID = """15/01/2024, 14:23 - Ayse: morning all
15/01/2024, 14:24 - Mehmet: launching next week, check it out
"""

US = """1/15/24, 2:23 PM - Ayse: morning all
1/15/24, 2:24 PM - Mehmet: we raised a pre-seed round
"""

ISO = """[2024-01-15, 14:23:01] Ayse: morning all
[2024-01-15, 14:24:10] Mehmet: founded a company last month
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


@pytest.mark.parametrize("fixture,name", [
    (IOS, "ios"), (ANDROID, "android"), (US, "us"), (ISO, "iso")
])
def test_all_locale_formats_parse(fixture, name):
    msgs = parse(fixture, "Founders")
    assert msgs, f"{name} export parsed to nothing"
    assert msgs[0].sender == "Ayse"
    assert msgs[0].text == "morning all"


def test_multiline_messages_are_joined():
    msgs = parse(IOS, "Founders")
    joined = next(m for m in msgs if "invoice AI" in m.text)
    assert "design partners" in joined.text, "continuation line was lost"


def test_system_messages_and_media_placeholders_are_dropped():
    texts = [m.text for m in parse(IOS, "Founders")]
    assert not any("end-to-end encrypted" in t for t in texts)
    assert not any("Media omitted" in t for t in texts)


def test_colons_in_message_bodies_survive():
    msgs = parse("[15/01/2024, 14:24:10] Ayse: see this: https://x.io/a\n", "C")
    assert msgs[0].sender == "Ayse"
    assert msgs[0].text == "see this: https://x.io/a"


def test_reimport_adds_nothing(conn):
    msgs = parse(IOS, "Founders")
    assert store(conn, msgs) == len(msgs)
    assert store(conn, msgs) == 0, "re-importing an export duplicated it"


def test_zip_and_txt_both_read(tmp_path: Path):
    txt = tmp_path / "WhatsApp Chat with Founders.txt"
    txt.write_text(ANDROID, encoding="utf-8")
    assert read_export(txt)

    z = tmp_path / "WhatsApp Chat with Founders.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("_chat.txt", IOS)
    assert read_export(z)


def test_only_leads_are_promoted(conn, tmp_path: Path):
    """The archive keeps everything; the pipeline only sees what looks like a lead."""
    (tmp_path / "chat.txt").write_text(IOS, encoding="utf-8")
    visit = WhatsAppCollector(conn, tmp_path).visit("chat.txt")

    stored = conn.execute("SELECT COUNT(*) FROM whatsapp_messages").fetchone()[0]
    assert stored > len(visit.candidates), "everything got promoted"
    assert any("seed round" in c.raw_text for c in visit.candidates)
    assert not any(c.raw_text == "morning all" for c in visit.candidates)


def test_chats_expose_no_neighbours(conn, tmp_path: Path):
    """Following participants between private groups would profile people across
    conversations they are in for unrelated reasons."""
    (tmp_path / "chat.txt").write_text(IOS, encoding="utf-8")
    assert WhatsAppCollector(conn, tmp_path).visit("chat.txt").neighbours == []


# --- the privacy path -------------------------------------------------------


def test_raw_private_message_cannot_reach_a_provider():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    r = Router(conn, ladder=[])
    r._call_one = lambda *a: (_ for _ in ()).throw(
        AssertionError("a private message reached the network")
    )
    with pytest.raises(PrivateTextRefused):
        r.complete("Ayse: my friend just raised", sending=Sending.PRIVATE)


def test_redaction_removes_identifiers():
    out = extract(
        "lol ok. my friend Ayse raised a seed round for https://acme.io, "
        "call +90 532 111 2233 or ayse@acme.io. what time is dinner?",
        known_names={"Ayse"},
    )
    assert "acme.io" in out, "the lead itself was redacted away"
    assert "Ayse" not in out
    assert "532" not in out
    assert "ayse@acme.io" not in out


def test_redaction_drops_surrounding_conversation():
    """Neighbouring chatter is dropped, not trimmed. A short private sentence is
    still private."""
    out = extract("what time is dinner? Acme just raised a seed round. ok see you")
    assert "raised" in out
    assert "dinner" not in out


def test_scrub_leaves_ordinary_text_alone():
    assert scrub("building an invoice tool") == "building an invoice tool"


def test_lead_detection_is_generous_but_not_indiscriminate():
    assert looks_like_lead("check https://acme.io")
    assert looks_like_lead("she raised a pre-seed")
    assert not looks_like_lead("what time is dinner")


def test_retention_covers_the_whatsapp_archive(conn):
    conn.execute(
        """INSERT INTO whatsapp_messages (id, chat, text, retention_until)
           VALUES ('x','C','old','2000-01-01T00:00:00+00:00')"""
    )
    conn.commit()
    assert purge_expired(conn) == 1


def test_cloud_embedder_never_sees_whatsapp_rows(conn, monkeypatch):
    """Belt and braces: the guard is a query filter, not a convention callers
    have to remember."""
    from vc_alpha import theses
    from vc_alpha.enrich.embed import Embedder, score_pending

    conn.execute(
        """INSERT INTO candidates (id, source, source_url, raw_text, discovered_at,
           retention_until) VALUES ('w','whatsapp','whatsapp://c#1','private chat',
           '2026-01-01','2027-01-01')"""
    )
    conn.commit()

    monkeypatch.setenv("GEMINI_API_KEY", "pretend")
    cloud = Embedder()
    assert cloud.provider == "gemini"
    def guard(texts):
        # Thesis prose is fine to embed in the cloud; the private message is not.
        if any("private chat" in x for x in texts):
            raise AssertionError("whatsapp text was sent to a cloud embedder")
        return [[0.0, 1.0] for _ in texts]

    cloud.embed_many = guard
    assert score_pending(conn, cloud, theses.load_all())["scored"] == 0
