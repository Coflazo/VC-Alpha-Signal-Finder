"""Keys typed into the Setup screen, saved so they survive a restart.

Before this, configuring the product meant exporting environment variables in the
shell you happened to launch it from. That is a reasonable ask of the person who
wrote it and an unreasonable one of a partner at a fund, who is the person the
product is for. The Setup screen can now take a key directly.

Three rules, because this handles credentials:

  **Written, never read back.** Every endpoint reports whether a key is present.
  None of them return its value. A key that can be read out of the UI is a key
  that leaks through a screenshot, a support request or a browser cache.

  **Only names we know.** The variable name is checked against a fixed list
  rather than trusted, so a request cannot set PATH, LD_PRELOAD or anything else
  that happens to be an environment variable.

  **0600, always.** The file holds live credentials and no other user on the
  machine has any business reading it.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from vc_alpha import paths
from vc_alpha.enrich.embed import EMBEDDERS
from vc_alpha.llm import LADDER

log = logging.getLogger(__name__)

# Where to get each one. Kept beside the names so the screen can link straight to
# the page that issues the key rather than describing where it might be.
WHERE = {
    "GROQ_API_KEY": "console.groq.com — free, no card",
    "MISTRAL_API_KEY": "console.mistral.ai — free tier, also does embeddings",
    "GEMINI_API_KEY": "aistudio.google.com — 1,500 requests a day",
    "NVIDIA_NIM_API_KEY": "build.nvidia.com — free credits",
    "CEREBRAS_API_KEY": "cloud.cerebras.ai",
    "SAMBANOVA_API_KEY": "cloud.sambanova.ai",
    "OPENROUTER_API_KEY": "openrouter.ai/keys — many models behind one key",
    "COHERE_API_KEY": "dashboard.cohere.com — embeddings",
    "REDDIT_CLIENT_ID": "reddit.com/prefs/apps — create a 'script' app",
    "REDDIT_CLIENT_SECRET": "the same page, beside the client id",
    "LINKEDIN_SESSION_COOKIE": "the li_at cookie from a logged-in browser. "
                               "Use a secondary account.",
    "VC_ALPHA_SHEET_ID": "the long string in your sheet's URL, between /d/ and /edit",
}

# Anything not on this list is refused. Built from the ladders so a new provider
# becomes settable by being added to one, not by being remembered here as well.
SETTABLE: set[str] = (
    {p.env_key for p in LADDER if not p.local}
    | {p.env_key for p in EMBEDDERS if not p.local}
    | {"REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "LINKEDIN_SESSION_COOKIE",
       "VC_ALPHA_SHEET_ID"}
)

_LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$")


class NotSettable(ValueError):
    """A name the Setup screen is not allowed to write."""


def _read(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.is_file() else []


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with the right mode from the outset. Writing first and chmod-ing
    # after leaves a window where the key is world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("".join(f"{line}\n" for line in lines))
    os.chmod(path, 0o600)


def present() -> dict[str, bool]:
    """Which keys are set in this process. Values are deliberately not included."""
    return {name: bool(os.environ.get(name)) for name in sorted(SETTABLE)}


def save(name: str, value: str, *, path: Path | None = None) -> None:
    """Persist one key and apply it immediately.

    An empty value removes it, which is how the screen offers "clear this key"
    without a second endpoint.
    """
    if name not in SETTABLE:
        raise NotSettable(f"{name} is not a key this product sets")

    value = value.strip()
    # A newline would let one field write a second variable into the file.
    if "\n" in value or "\r" in value:
        raise NotSettable("a key cannot contain a line break")

    path = path or paths.env_file()
    lines = [ln for ln in _read(path) if not _matches(ln, name)]
    if value:
        lines.append(f"{name}={value}")
        os.environ[name] = value
    else:
        os.environ.pop(name, None)

    _write(path, lines)
    log.info("%s %s", "saved" if value else "cleared", name)


def _matches(line: str, name: str) -> bool:
    m = _LINE.match(line)
    return bool(m and m.group(1) == name)
