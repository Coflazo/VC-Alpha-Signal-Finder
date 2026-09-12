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
import time
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


# A throttle longer than this is treated as the provider being done for the day
# rather than something worth blocking on.
MAX_BACKOFF_SECONDS = 75.0


class RateLimited(RuntimeError):
    """A 429. Carries how long to wait, which decides whether it is fatal.

    Free tiers limit per minute *and* per day, and the two need different
    responses: a per-minute throttle is a pause, a daily one is a stop.
    """

    def __init__(self, retry_after: float, daily: bool = False):
        super().__init__(f"rate limited, retry after {retry_after:.0f}s")
        self.retry_after = retry_after
        self.daily = daily

    @classmethod
    def from_response(cls, r: httpx.Response) -> "RateLimited":
        """Read a 429 correctly, which is fiddlier than it looks.

        Groq's free tier limits **tokens per minute** far more tightly than
        requests per day: 8,000 tokens/min against 1,000 requests/day. A triage
        prompt is roughly 1,500 tokens, so the binding constraint is about four
        calls a minute, and it is almost never the daily request budget.

        The first version took max() over every reset header it could find. That
        picked up `x-ratelimit-reset-requests`, which is just the time until the
        rolling request window rolls over — a normal value present on successful
        responses too, often several minutes. Reading it as a retry-after made a
        routine token throttle look like a multi-minute wait, which then tripped the
        daily-exhaustion branch and wrote the provider off after five calls.

        So: trust `retry-after` if present, otherwise the reset for whichever
        budget is actually empty, and only call it daily when the *request* budget
        is the one at zero.
        """
        h = r.headers

        def seconds(raw: str | None) -> float | None:
            if not raw:
                return None
            m = re.match(r"^(?:(\d+)m)?([\d.]+)(m?s)?$", raw.strip())
            if not m:
                try:
                    return float(raw)
                except ValueError:
                    return None
            value = float(m.group(2))
            if m.group(3) == "ms":
                value /= 1000.0
            return int(m.group(1) or 0) * 60 + value

        def empty(name: str) -> bool:
            v = h.get(name)
            try:
                return v is not None and float(v) <= 0
            except ValueError:
                return False

        requests_gone = empty("x-ratelimit-remaining-requests")
        tokens_gone = empty("x-ratelimit-remaining-tokens")

        wait = seconds(h.get("retry-after"))
        if wait is None and tokens_gone:
            wait = seconds(h.get("x-ratelimit-reset-tokens"))
        if wait is None and requests_gone:
            wait = seconds(h.get("x-ratelimit-reset-requests"))

        # Only an empty request budget means done for the day. An empty token
        # budget refills within the minute.
        return cls(wait if wait is not None else 5.0, daily=requests_gone)


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


# Model names are the most perishable thing in this file. Providers retire them
# without notice: the previously configured Groq model returned 404 and the ladder
# spent 507 seconds falling through to local inference before anyone noticed. Each
# is overridable by environment, and _recover_model() below re-discovers a working
# one rather than writing the provider off.
#
# Worth knowing about the free tiers: the binding constraint is usually tokens per
# minute, not requests per day. Groq allows 8,000 tokens/min against 1,000
# requests/day, and a triage prompt is roughly 1,500 tokens, so throughput is about
# four calls a minute.
LADDER = [
    Provider("gemini", "GEMINI_API_KEY",
             "https://generativelanguage.googleapis.com/v1beta/openai",
             os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"), 1500),
    Provider("groq", "GROQ_API_KEY",
             "https://api.groq.com/openai/v1",
             os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"), 1000),
    Provider("cerebras", "CEREBRAS_API_KEY",
             "https://api.cerebras.ai/v1",
             os.environ.get("CEREBRAS_MODEL", "llama-3.3-70b"), 1000),
    Provider("github", "GITHUB_MODELS_TOKEN",
             "https://models.inference.ai.azure.com",
             os.environ.get("GITHUB_MODEL", "gpt-4o-mini"), 150),
    Provider("openrouter", "OPENROUTER_API_KEY",
             "https://openrouter.ai/api/v1",
             os.environ.get("OPENROUTER_MODEL",
                            "meta-llama/llama-3.3-70b-instruct:free"), 50),
    # Always last, always available, no key. Slow on modest hardware, but it is
    # what makes the product work with nothing configured at all, and the only
    # option for private sources.
    Provider("ollama", "OLLAMA_HOST",
             "http://localhost:11434/v1",
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
        """Mark a provider as spent for the rest of today.

        Reserved for a genuine daily exhaustion signal. A 429 alone is *not* that:
        free tiers rate limit per minute as well as per day, and treating a
        per-minute throttle as daily exhaustion writes off the provider for
        twenty-four hours over a two-second burst. That happened in testing — Groq
        was recorded as having used its full 1000-request daily allowance after a
        single 429 twelve requests in.
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


# Models that answer chat completions. Transcription, moderation and guard models
# share the catalogue and would fail in confusing ways if selected.
_NOT_CHAT = ("whisper", "tts", "embed", "guard", "safeguard", "orpheus", "moderation")


def _pick_chat_model(available: list[str], prefer: str) -> str | None:
    """Choose a replacement model from a provider's live catalogue.

    Prefers something sharing a prefix with the configured name, since that usually
    means the same family and similar behaviour, before falling back to the first
    plausible chat model.
    """
    usable = [m for m in available if not any(bad in m.lower() for bad in _NOT_CHAT)]
    if not usable:
        return None
    stem = prefer.split("/")[-1].split("-")[0].lower()
    same_family = [m for m in usable if stem and stem in m.lower()]
    return (same_family or usable)[0]


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
        # Replacement model per provider, discovered once after a 404.
        self._recovered: dict[str, str | None] = {}

    def _recover_model(self, p: Provider) -> str | None:
        """Ask a provider what it actually serves, after a model-not-found error.

        Called at most once per provider per process. A retired model name should
        cost one extra request, not the whole provider.
        """
        if p.name in self._recovered:
            return self._recovered[p.name]
        self._recovered[p.name] = None
        try:
            r = self._client.get(f"{p.base_url}/models",
                                 headers={"Authorization": f"Bearer {p.key}"},
                                 timeout=15.0)
            r.raise_for_status()
            names = [m.get("id", "") for m in r.json().get("data", [])]
        except Exception as e:
            log.warning("could not list models for %s: %s", p.name, e)
            return None

        choice = _pick_chat_model(names, p.model)
        if choice:
            log.warning("%s no longer serves %s; using %s instead",
                        p.name, p.model, choice)
        self._recovered[p.name] = choice
        return choice

    def available(self) -> list[Provider]:
        """Configured providers that still have allowance left today."""
        return [
            p for p in self.ladder
            if p.key and self.budget.used(p.name) < p.daily_requests
        ]

    def _call_one(self, p: Provider, prompt: str, schema: dict | None) -> str:
        headers = {} if p.local else {"Authorization": f"Bearer {p.key}"}
        body: dict[str, Any] = {
            "model": self._recovered.get(p.name) or p.model,
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
            raise RateLimited.from_response(r)
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
            except RateLimited as e:
                # Per-minute throttle: wait it out rather than abandoning the
                # provider. Only a genuine daily exhaustion should do that.
                if not e.daily and e.retry_after <= MAX_BACKOFF_SECONDS:
                    log.info("%s throttled, waiting %.0fs", p.name, e.retry_after)
                    time.sleep(e.retry_after)
                    try:
                        out = self._call_one(p, prompt, schema)
                        self.budget.note(p.name)
                        return _extract_json(out) if schema else out
                    except Exception:
                        pass
                else:
                    log.info("%s exhausted for today", p.name)
                    self.budget.exhaust(p.name, p.daily_requests)
                tried.append(p.name)
                continue
            except httpx.HTTPStatusError as e:
                status = e.response.status_code if e.response is not None else 0
                if status == 404 and not p.local and self._recover_model(p):
                    # The model was retired, not the provider. Retry once with a
                    # live one before giving up on it.
                    try:
                        out = self._call_one(p, prompt, schema)
                        self.budget.note(p.name)
                        return _extract_json(out) if schema else out
                    except httpx.HTTPError:
                        pass
                if status == 429:
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
