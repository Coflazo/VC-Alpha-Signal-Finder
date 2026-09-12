"""Every model call in the product goes through here.

The product has to cost nothing to run, forever. That is a property of this file.
It holds a ladder of free providers, tracks each one's daily allowance, and fails
over when one is exhausted or rate-limits. Nothing else in the codebase imports a
provider SDK or knows a provider's name.

Two rules are enforced here rather than trusted to callers.

Free tiers generally train on what you send them, so every caller must classify
what it is sending. There are three real states, not two: text somebody already
published, a fragment extracted from private material with names and context
stripped, and private material itself. The last is refused outright. WhatsApp
group exports are the reason this is an enum rather than a boolean.

And a provider that has run out is not an error. It is the expected steady state
at the end of a day, and the ladder handles it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Cloud providers answer in about a second; 90s is already generous and a hang
# should fail over rather than block. Local inference is a different animal:
# measured on a 2017 dual-core i5, llama3.2:1b took 31s and qwen2.5:3b took 131s
# for a trivial reply, so a real triage prompt needs minutes. Local is the
# fallback of last resort, and it gets a timeout that reflects that.
TIMEOUT = httpx.Timeout(90.0)
LOCAL_TIMEOUT = httpx.Timeout(900.0)


class NoCapacityLeft(RuntimeError):
    """Every provider is exhausted for today. Wait, or add a key."""


class PrivateTextRefused(ValueError):
    """Something tried to send private text to a provider that trains on it."""


class Sending(Enum):
    """What kind of text a caller is about to send.

    PUBLIC    somebody already published it: a Reddit post, an HN title.
    REDACTED  a fragment pulled out of private material by vc_alpha.redact,
              with senders, phone numbers and surrounding conversation removed.
    PRIVATE   the raw private material. Never sent anywhere, by anyone.
    """

    PUBLIC = "public"
    REDACTED = "redacted"
    PRIVATE = "private"


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    env_key: str
    base_url: str
    model: str
    daily_requests: int
    # OpenAI-compatible chat completions unless stated otherwise.
    style: str = "openai"

    @property
    def local(self) -> bool:
        """Local providers need no key and never leave the machine."""
        return self.name == "ollama"

    @property
    def key(self) -> str | None:
        # Local endpoints authenticate with nothing. Requiring an env var here
        # would mean a machine with no API keys at all has no provider, which
        # defeats the point of shipping a local fallback.
        if self.local:
            return os.environ.get(self.env_key) or "local"
        return os.environ.get(self.env_key)


# Ordered best-first. Limits are the published free-tier allowances; the tracker
# below is what actually stops us, so an over-generous number here costs nothing.
LADDER = [
    Provider("gemini", "GEMINI_API_KEY",
             "https://generativelanguage.googleapis.com/v1beta/openai",
             "gemini-2.0-flash", 1500),
    Provider("groq", "GROQ_API_KEY",
             "https://api.groq.com/openai/v1",
             "llama-3.3-70b-versatile", 1000),
    Provider("cerebras", "CEREBRAS_API_KEY",
             "https://api.cerebras.ai/v1",
             "llama-3.3-70b", 1000),
    Provider("github", "GITHUB_MODELS_TOKEN",
             "https://models.inference.ai.azure.com",
             "gpt-4o-mini", 150),
    Provider("openrouter", "OPENROUTER_API_KEY",
             "https://openrouter.ai/api/v1",
             "meta-llama/llama-3.3-70b-instruct:free", 50),
    # Always last: free, private, and on slow hardware, painfully slow.
    # Always last, always available, no key. Slow on modest hardware, but it is
    # what makes the product work with nothing configured at all, and the only
    # option for private sources.
    Provider("ollama", "OLLAMA_HOST",
             "http://localhost:11434/v1",
             # Overridable: on slow hardware a 1B model that answers in a minute
             # beats a 3B that takes five, and local is a fallback either way.
             os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct-q4_K_M"),
             10_000_000),
]

USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_usage (
  day       TEXT NOT NULL,
  provider  TEXT NOT NULL,
  requests  INTEGER NOT NULL DEFAULT 0,
  failures  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, provider)
);
"""


class Budget:
    """Per-provider daily request counts, persisted so a restart does not reset them."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.executescript(USAGE_SCHEMA)

    def used(self, provider: str) -> int:
        row = self.conn.execute(
            "SELECT requests FROM llm_usage WHERE day = ? AND provider = ?",
            (date.today().isoformat(), provider),
        ).fetchone()
        return row[0] if row else 0

    def note(self, provider: str, *, failed: bool = False) -> None:
        self.conn.execute(
            """INSERT INTO llm_usage (day, provider, requests, failures)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(day, provider) DO UPDATE SET
                 requests = requests + 1,
                 failures = failures + excluded.failures""",
            (date.today().isoformat(), provider, int(failed)),
        )
        self.conn.commit()

    def exhaust(self, provider: str, limit: int) -> None:
        """Mark a provider as spent for today, after it says so itself.

        A 429 is better evidence than our own counter, which can drift if calls
        were made from another process or another machine.
        """
        self.conn.execute(
            """INSERT INTO llm_usage (day, provider, requests) VALUES (?, ?, ?)
               ON CONFLICT(day, provider) DO UPDATE SET requests = ?""",
            (date.today().isoformat(), provider, limit, limit),
        )
        self.conn.commit()

    def report(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM llm_usage WHERE day = ? ORDER BY requests DESC",
            (date.today().isoformat(),),
        ).fetchall()


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object out of a model reply.

    Providers differ in how well they honour a schema, and some wrap the object in
    prose or a code fence. One repair attempt beats a retry, which costs a request
    from an allowance we are trying not to spend.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if m := _JSON_BLOCK.search(text):
        return json.loads(m.group(0))
    raise ValueError(f"no JSON object in reply: {text[:200]}")


class Router:
    def __init__(self, conn: sqlite3.Connection, ladder: list[Provider] | None = None):
        self.budget = Budget(conn)
        self.ladder = ladder if ladder is not None else LADDER
        self._client = httpx.Client(timeout=TIMEOUT)

    def available(self) -> list[Provider]:
        """Configured providers that still have allowance left today."""
        return [
            p for p in self.ladder
            if p.key and self.budget.used(p.name) < p.daily_requests
        ]

    def _call_one(self, p: Provider, prompt: str, schema: dict | None) -> str:
        headers = {} if p.local else {"Authorization": f"Bearer {p.key}"}
        body: dict[str, Any] = {
            "model": p.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        if schema:
            # Honoured by most OpenAI-compatible endpoints; the ones that ignore it
            # still usually return JSON, and _extract_json covers the rest.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            }
        r = self._client.post(
            f"{p.base_url}/chat/completions", headers=headers, json=body,
            timeout=LOCAL_TIMEOUT if p.local else TIMEOUT,
        )
        if r.status_code == 429:
            raise httpx.HTTPStatusError("rate limited", request=r.request, response=r)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def complete(
        self, prompt: str, *, schema: dict | None = None, sending: Sending
    ) -> dict[str, Any] | str:
        """Run a prompt down the ladder until one provider answers.

        `sending` is not a formality. A WhatsApp message classified PUBLIC because
        it was convenient is how private conversation ends up in someone's training
        set, so the classification belongs with the caller who knows the source.
        """
        if sending is Sending.PRIVATE:
            raise PrivateTextRefused(
                "refusing to send private text to a provider that may train on it. "
                "Extract a fragment with vc_alpha.redact first, or point the router "
                "at a local endpoint."
            )

        tried = []
        for p in self.available():
            try:
                out = self._call_one(p, prompt, schema)
            except httpx.HTTPStatusError as e:
                if e.response is not None and e.response.status_code == 429:
                    log.info("%s is rate limited, moving down the ladder", p.name)
                    self.budget.exhaust(p.name, p.daily_requests)
                else:
                    log.warning("%s failed: %s", p.name, e)
                    self.budget.note(p.name, failed=True)
                tried.append(p.name)
                continue
            except httpx.HTTPError as e:
                log.warning("%s unreachable: %s", p.name, e)
                self.budget.note(p.name, failed=True)
                tried.append(p.name)
                continue

            self.budget.note(p.name)
            return _extract_json(out) if schema else out

        raise NoCapacityLeft(
            f"no free capacity left today (tried: {tried or 'nothing configured'}). "
            "Set GEMINI_API_KEY, GROQ_API_KEY or CEREBRAS_API_KEY, or run ollama."
        )
