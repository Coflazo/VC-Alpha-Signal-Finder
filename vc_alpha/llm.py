"""Every model call in the product goes through here.

## Why this is a thin wrapper and not a provider ladder

It used to be a hand-rolled ladder: a list of providers, manual failover, manual
rate-limit parsing, manual pacing. A live API key found four bugs in it within an
hour — a retired model name returning 404, a schema strict mode rejected, rate-limit
headers misread as daily exhaustion twice, and pacing that never worked.

All four are solved problems. LiteLLM covers 100+ providers with model aliasing,
fallback chains, retries with backoff, and routing that tracks requests *and tokens*
per minute against each provider's published limits. It runs as a library — no
proxy, no Redis, no server — which keeps the product local-first and free to run.

What stays here is what no gateway can know:

  Sending   the privacy classification. A domain rule about what may leave this
            machine, which is the product's promise to its users.
  Budget    the free-tier ceiling, tracked in our own database so "free forever"
            is a property we enforce rather than a hope about someone's quota.
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

log = logging.getLogger(__name__)


class NoCapacityLeft(RuntimeError):
    """Every configured provider is spent for today. Wait, or add a key."""


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
    """One rung of the fallback chain.

    `model` is a LiteLLM identifier, "<provider>/<model>". Overridable by
    environment because model names are the most perishable thing in this file:
    providers retire them without notice, which is exactly how the old code broke.
    """

    name: str
    env_key: str
    model: str
    daily_requests: int

    @property
    def local(self) -> bool:
        return self.name == "ollama"

    @property
    def configured(self) -> bool:
        return self.local or bool(os.environ.get(self.env_key))


# Ordered best-first. Every one is a free tier and none needs a payment card.
#
# Model ids are the most perishable thing in this file and the list has already
# rotted once: `cerebras/llama-3.3-70b` and
# `openrouter/meta-llama/llama-3.3-70b-instruct:free` were both shipped here and
# both now return 404, because the providers retired them. Every id below was
# checked against a live call on 14 September 2026 — see docs/VALIDATION.md — and
# every one is overridable by environment so a retirement is a config change
# rather than a release.
LADDER = [
    # Measured 100% valid JSON across 93 triage calls on this corpus, which no
    # other rung has evidence for, so it leads despite not being the fastest.
    # Binds on tokens per minute rather than requests per day.
    Provider("groq", "GROQ_API_KEY",
             os.environ.get("GROQ_MODEL", "groq/openai/gpt-oss-120b"), 1000),
    # Ten times faster than anything else here (0.41s against 4.8s) and generous
    # per minute, so it is what actually carries a long run once Groq's
    # tokens-per-minute ceiling starts throttling.
    Provider("mistral", "MISTRAL_API_KEY",
             os.environ.get("MISTRAL_MODEL", "mistral/ministral-8b-latest"), 1000),
    Provider("gemini", "GEMINI_API_KEY",
             os.environ.get("GEMINI_MODEL", "gemini/gemini-2.0-flash"), 1500),
    # The largest model on the ladder. Slower, and worth having when a candidate
    # is genuinely ambiguous rather than for bulk triage.
    Provider("nvidia", "NVIDIA_NIM_API_KEY",
             os.environ.get("NVIDIA_MODEL",
                            "nvidia_nim/nvidia/nemotron-3-super-120b-a12b"), 1000),
    # Cerebras and SambaNova both answered "payment required" on a free key when
    # this was last checked. Kept as rungs because a fund may hold a paid key and
    # the only cost of an unusable one is a single failed call that falls through,
    # but placed below everything that was verified working.
    Provider("cerebras", "CEREBRAS_API_KEY",
             os.environ.get("CEREBRAS_MODEL", "cerebras/gpt-oss-120b"), 1000),
    Provider("sambanova", "SAMBANOVA_API_KEY",
             os.environ.get("SAMBANOVA_MODEL", "sambanova/gpt-oss-120b"), 1000),
    # One key reaching many models, with provider failover handled server-side.
    # Small allowance and measured at 29s a call, so it sits last before local.
    Provider("openrouter", "OPENROUTER_API_KEY",
             os.environ.get("OPENROUTER_MODEL",
                            "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"), 50),
    # Always last, always available, needs no key. Slow on modest hardware, but it
    # is what makes the product work with nothing configured, and it is the only
    # option for private sources.
    Provider("ollama", "OLLAMA_HOST",
             os.environ.get("OLLAMA_MODEL", "ollama/qwen2.5:3b-instruct-q4_K_M"),
             10_000_000),
]

def set_a_key() -> str:
    """The "what do I do now" sentence, built from the ladder rather than typed out.

    The hardcoded version named three providers, one of which had been retired and
    another of which no longer has a free tier. A message that tells someone to go
    and get a key that will not work is worse than no message.
    """
    names = ", ".join(f"{p.env_key}" for p in LADDER if not p.local)
    return (f"Set one of {names} — all free, no card — in the Setup screen, "
            "or run 'ollama serve' to work entirely offline.")


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
    """Per-provider daily request counts, persisted so a restart does not reset them.

    Counted here rather than inferred from response headers. Two attempts at reading
    a daily limit out of 429 headers were both wrong, because those headers describe
    a rolling window: a 1,000-request limit that resets in four minutes is not a day.
    Our own counter is the only number we actually know.
    """

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

    def report(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM llm_usage WHERE day = ? ORDER BY requests DESC",
            (date.today().isoformat(),),
        ).fetchall()


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object out of a reply, repairing one common failure.

    Some providers wrap the object in prose or a code fence even under a schema.
    One repair beats a retry, which would spend a request from an allowance the
    product is trying not to spend.
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

    def available(self) -> list[Provider]:
        """Configured providers with allowance left today, best first."""
        return [p for p in self.ladder
                if p.configured and self.budget.used(p.name) < p.daily_requests]

    def complete(self, prompt: str, *, schema: dict | None = None,
                 sending: Sending, system: str | None = None
                 ) -> dict[str, Any] | str:
        """Run a prompt against the best available provider.

        `sending` is not a formality. Classifying a WhatsApp message as PUBLIC
        because it was convenient is how private conversation ends up in someone's
        training set, so the judgement belongs with the caller who knows the source.
        """
        if sending is Sending.PRIVATE:
            raise PrivateTextRefused(
                "refusing to send private text to a provider that may train on it. "
                "Extract a fragment with vc_alpha.redact first, or point the router "
                "at a local endpoint."
            )

        usable = self.available()
        if not usable:
            raise NoCapacityLeft(
                f"no free capacity left today. {set_a_key()}"
            )

        import litellm
        litellm.suppress_debug_info = True
        # Not every provider on the ladder takes reasoning_effort. Dropping the
        # parameter where it is unsupported is better than keeping a per-provider
        # table of which ones do.
        litellm.drop_params = True

        primary, *rest = usable
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {
            "model": primary.model,
            "messages": messages,
            "temperature": 0,
            # LiteLLM retries with backoff and honours each provider's published
            # rate limits, which is the part the hand-rolled version never got right.
            "num_retries": 3,
            "fallbacks": [p.model for p in rest],
            # Reasoning models think in tokens that count against the same output
            # budget as the answer. Left alone, gpt-oss-20b spent 4,900 characters
            # reasoning about a research prompt and 350 answering it, and when the
            # thinking ran past the ceiling the answer came back empty — which a
            # strict schema rejects as invalid JSON. Extraction from a given text
            # does not need deliberation; "low" cuts the cost of a call by 40% and
            # stops the empty completions.
            "reasoning_effort": "low",
            "max_tokens": 3000,
        }
        if schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": True},
            }

        try:
            response = litellm.completion(**kwargs)
        except Exception as e:
            self.budget.note(primary.name, failed=True)
            raise NoCapacityLeft(f"every provider failed: {e}") from e

        # Attribute the request to whichever model actually answered, since a
        # fallback may have handled it.
        answered = getattr(response, "model", "") or primary.model
        charged = next((p.name for p in usable if p.model.endswith(answered)
                        or answered in p.model), primary.name)
        self.budget.note(charged)

        content = response.choices[0].message.content or ""
        return _extract_json(content) if schema else content
