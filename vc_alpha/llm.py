"""Every model call in the product goes through here.

The product has to cost nothing to run, forever. That is a property of this file.
It holds a ladder of free providers, tracks each one's daily allowance, and fails
over when one is exhausted or rate-limits. Nothing else in the codebase imports a
provider SDK or knows a provider's name.

Two rules are enforced here rather than trusted to callers.

Free tiers generally train on what you send them. So `public_text` is a required,
explicit argument: callers must state that the text was already public before it
gets sent. Thesis prose, match reasoning and assembled reports never leave the
machine, because the aggregation is the asset, not the individual public post.

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
from typing import Any

import httpx

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(90.0)


class NoCapacityLeft(RuntimeError):
    """Every provider is exhausted for today. Wait, or add a key."""


class PrivateTextRefused(ValueError):
    """Something tried to send text that was not already public."""


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
    def key(self) -> str | None:
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
    Provider("ollama", "OLLAMA_HOST",
             "http://localhost:11434/v1", "qwen2.5:3b-instruct-q4_K_M",
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
            f"{p.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {p.key}"},
            json=body,
        )
        if r.status_code == 429:
            raise httpx.HTTPStatusError("rate limited", request=r.request, response=r)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def complete(
        self, prompt: str, *, schema: dict | None = None, public_text: bool
    ) -> dict[str, Any] | str:
        """Run a prompt down the ladder until one provider answers.

        `public_text` is not a formality. Pass True only when everything in the
        prompt was already published by someone else.
        """
        if not public_text:
            raise PrivateTextRefused(
                "refusing to send non-public text to a free provider that may train "
                "on it; run this against a local or paid endpoint instead"
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
